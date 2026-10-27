"""What's still to come of the library's shows: each one's next episode by the day it airs, and a
word to the owner on the day one airs, once."""

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import NoReturn

import pytest
from fastapi.testclient import TestClient

from maku import coming, db
from maku.config import DataPaths
from maku.watch import Watcher
from tests.fake_web import FakeWeb
from tests.shelf import library

TODAY = date(2026, 10, 18)


@pytest.fixture
def shelf(conn: sqlite3.Connection, tmp_path: Path) -> None:
    """Two made-up shows the library has the first episodes of, still airing, and one it has
    none of."""
    root = tmp_path / "Videos"
    library(
        conn,
        root,
        [
            "Starfall (2026)/Season 01/Starfall (2026) - S01E01.mkv",
            "Lanterns (2026)/Season 01/Lanterns (2026) - S01E01.mkv",
        ],
    )
    with conn:
        conn.executemany(
            "INSERT INTO titles (id, kind, name) VALUES (?, 'series', ?)",
            [(1, "Starfall"), (2, "Lanterns"), (3, "Elsewhere")],
        )
        conn.execute("UPDATE files SET title_id = id, season = 1, episode = 1")
        conn.executemany(
            "INSERT INTO episodes (title_id, season, number, name, aired) VALUES (?, ?, ?, ?, ?)",
            [
                (1, 1, 1, "The First Night", "2026-10-04"),
                (1, 1, 2, "Lanterns", "2026-10-11"),  # aired, and not in the library: missing
                (1, 1, 3, "The Night Market", "2026-10-18"),
                (1, 1, 4, "Quiet Rain", "2026-10-25"),
                (2, 1, 1, "Arrival", "2026-10-10"),
                (2, 1, 2, "The Lake", "2026-10-23"),
                (2, 0, 1, "A Short Story", "2026-10-20"),
                (3, 1, 1, "Nobody's", "2026-10-19"),
            ],
        )


def test_each_show_says_its_next_episode_the_soonest_first(conn: sqlite3.Connection, shelf: None):
    found = coming.coming(conn, TODAY)

    assert [(each.title, each.season, each.number, each.later) for each in found] == [
        ("Starfall", 1, 3, 1),
        ("Lanterns", 0, 1, 1),
    ]
    assert found[0].aired == TODAY


def test_an_episode_the_library_has_already_isnt_coming(conn: sqlite3.Connection, shelf: None):
    with conn:
        conn.execute(
            """INSERT INTO files (folder_id, path, size, modified, found_at, seen_at, title_id,
                                  season, episode)
               SELECT folder_id, path || '.3.mkv', 1, 1, found_at, seen_at, 1, 1, 3
               FROM files WHERE id = 1"""
        )

    [starfall] = [each for each in coming.coming(conn, TODAY) if each.title == "Starfall"]

    assert (starfall.number, starfall.later) == (4, 0)


def test_the_owner_is_told_once_of_an_episode_out_today(conn: sqlite3.Connection, shelf: None):
    first = coming.out_today(conn, TODAY, "2026-10-18T08:00:00+00:00")
    again = coming.out_today(conn, TODAY, "2026-10-18T09:00:00+00:00")

    assert [(each.title, each.number) for each in first] == [("Starfall", 3)]
    assert again == []
    assert coming.told(first) == (
        "Out today",
        "Starfall S01E03 · The Night Market",
        "/titles/1",
    )


def test_several_out_on_a_day_are_told_together():
    def one(title: str, number: int) -> coming.Coming:
        return coming.Coming(1, title, coming.TitleKind.SERIES, None, 1, number, None, TODAY, 0)

    assert coming.told([one("Starfall", 3), one("Lanterns", 2)]) == (
        "2 episodes out today",
        "Starfall S01E03 and Lanterns S01E02",
        "/",
    )
    assert coming.told([one("A", 1), one("B", 2), one("C", 3)]) == (
        "3 episodes out today",
        "A S01E01, B S01E02 and 1 more",
        "/",
    )
    assert coming.told([]) is None


def test_the_watcher_tells_of_episodes_out_today(paths: DataPaths, shelf: None):
    told: list[tuple[str, str, str | None]] = []
    now = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
    watcher = Watcher(
        paths,
        _NoScans(),
        FakeWeb(),
        now=lambda: now,
        notify=lambda title, body, link=None: told.append((title, body, link)),
    )

    assert watcher.tell_aired() == 1
    assert watcher.tell_aired() == 0
    assert told == [("Out today", "Starfall S01E03 · The Night Market", "/titles/1")]
    with db.connect(paths.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM aired_told").fetchone()[0] == 1


def test_the_api_lists_whats_coming(client: TestClient, conn: sqlite3.Connection, shelf: None):
    found = client.get("/coming").json()

    # Today's date on this PC decides; the made-up list's dates are all in October 2026.
    assert all(
        {"titleId", "title", "season", "number", "aired", "later"} <= set(each) for each in found
    )


class _NoScans:
    """The watcher's scanner, never asked to scan here."""

    def start(self) -> NoReturn:
        raise AssertionError

    def status(self) -> NoReturn:
        raise AssertionError

    def moving(self) -> bool:
        return False
