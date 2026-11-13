"""The library's shows by the day their episodes air: the last four weeks and all that's listed
ahead, each day's saying how much of it the library has, and a word to the owner on the day one
airs, once."""

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
                (3, 1, 1, "Nobody's", "2026-10-19"),  # a show the library has no video of
            ],
        )


def _add_file(conn: sqlite3.Connection, title_id: int, season: int, first: int, last: int | None):
    """Another video of a show in the library, holding these episodes."""
    with conn:
        conn.execute(
            """INSERT INTO files (folder_id, path, size, modified, found_at, seen_at, title_id,
                                  season, episode, episode_end)
               SELECT folder_id, path || ?, 1, 1, found_at, seen_at, ?, ?, ?, ?
               FROM files WHERE id = 1""",
            (f".{title_id}.{season}.{first}.mkv", title_id, season, first, last),
        )


def _days(found: list[coming.Coming]) -> list[tuple[str, str, int, int, int, int, int]]:
    return [
        (
            each.aired.isoformat(),
            each.title,
            each.season,
            each.number,
            each.last,
            each.episodes,
            each.held,
        )
        for each in found
    ]


def test_the_shows_episodes_by_the_day_they_air_saying_which_the_library_has(
    conn: sqlite3.Connection, shelf: None
):
    found = coming.coming(conn, TODAY)

    assert _days(found) == [
        ("2026-10-04", "Starfall", 1, 1, 1, 1, 1),
        ("2026-10-10", "Lanterns", 1, 1, 1, 1, 1),
        ("2026-10-11", "Starfall", 1, 2, 2, 1, 0),  # missing
        ("2026-10-18", "Starfall", 1, 3, 3, 1, 0),  # out today
        ("2026-10-20", "Lanterns", 0, 1, 1, 1, 0),  # a special
        ("2026-10-23", "Lanterns", 1, 2, 2, 1, 0),
        ("2026-10-25", "Starfall", 1, 4, 4, 1, 0),
    ]
    assert found[2].name == "Lanterns"


def test_an_episode_out_today_the_library_has_says_so(conn: sqlite3.Connection, shelf: None):
    _add_file(conn, 1, 1, 3, None)

    [today] = [each for each in coming.coming(conn, TODAY) if each.aired == TODAY]

    assert (today.title, today.number, today.held) == ("Starfall", 3, 1)
    assert coming.out_today(conn, TODAY, "2026-10-18T08:00:00+00:00") == []


def test_a_season_out_on_one_day_is_one_entry_saying_how_much_of_it_is_held(
    conn: sqlite3.Connection, shelf: None
):
    with conn:
        conn.executemany(
            "INSERT INTO episodes (title_id, season, number, name, aired) VALUES (2, 2, ?, ?, ?)",
            [(number, f"Part {number}", "2026-10-16") for number in range(1, 5)],
        )
    _add_file(conn, 2, 2, 1, 2)  # a video of the first two

    [season] = [each for each in coming.coming(conn, TODAY) if each.season == 2]

    assert (season.number, season.last, season.episodes, season.held) == (1, 4, 4, 2)
    assert season.name is None  # several: no one episode's name


def test_episodes_out_on_one_day_with_another_between_them_are_apart(
    conn: sqlite3.Connection, shelf: None
):
    with conn:
        conn.executemany(
            "INSERT INTO episodes (title_id, season, number, name, aired) VALUES (2, 2, ?, ?, ?)",
            [(5, "Five", "2026-10-16"), (6, "Six", "2026-10-17"), (7, "Seven", "2026-10-16")],
        )

    found = [each for each in coming.coming(conn, TODAY) if each.season == 2]

    # Not "S02E05–E07 · 2 episodes": the sixth isn't out that day.
    assert [(each.aired.isoformat(), each.number, each.last, each.name) for each in found] == [
        ("2026-10-16", 5, 5, "Five"),
        ("2026-10-16", 7, 7, "Seven"),
        ("2026-10-17", 6, 6, "Six"),
    ]


def test_what_aired_more_than_four_weeks_ago_is_left_out(conn: sqlite3.Connection, shelf: None):
    with conn:
        conn.executemany(
            "INSERT INTO episodes (title_id, season, number, name, aired) VALUES (1, 0, ?, ?, ?)",
            [(1, "Long Ago", "2026-09-19"), (2, "Four Weeks Ago", "2026-09-20")],
        )

    found = coming.coming(conn, TODAY)

    assert [each.name for each in found if each.season == 0 and each.title == "Starfall"] == [
        "Four Weeks Ago"
    ]


def test_whats_listed_ahead_is_kept_to_the_soonest_and_each_shows_next(
    conn: sqlite3.Connection, shelf: None, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(coming, "AHEAD", 1)

    found = coming.coming(conn, TODAY)

    # All that aired is there; of what's to come, the soonest, and every show's next however far.
    assert [(each.aired.isoformat(), each.title) for each in found] == [
        ("2026-10-04", "Starfall"),
        ("2026-10-10", "Lanterns"),
        ("2026-10-11", "Starfall"),
        ("2026-10-18", "Starfall"),
        ("2026-10-20", "Lanterns"),
    ]


def test_the_last_day_kept_ahead_is_kept_whole(
    conn: sqlite3.Connection, shelf: None, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(coming, "AHEAD", 2)
    with conn:
        conn.execute(
            """INSERT INTO episodes (title_id, season, number, name, aired)
               VALUES (1, 0, 1, 'A Special', '2026-10-20')"""
        )

    found = coming.coming(conn, TODAY)

    # The second kept is Lanterns' special on the 20th; Starfall's that day isn't cut off.
    assert [(each.aired.isoformat(), each.title) for each in found if each.aired >= TODAY] == [
        ("2026-10-18", "Starfall"),
        ("2026-10-20", "Lanterns"),
        ("2026-10-20", "Starfall"),
    ]


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


def test_several_out_on_a_day_are_told_together_and_lead_to_the_library():
    def one(title: str, number: int) -> coming.Coming:
        return coming.Coming(
            title_id=1,
            title=title,
            kind=coming.TitleKind.SERIES,
            poster=None,
            season=1,
            number=number,
            last=number,
            name=None,
            aired=TODAY,
            episodes=1,
            held=0,
        )

    assert coming.told([one("Starfall", 3), one("Lanterns", 2)]) == (
        "2 episodes out today",
        "Starfall S01E03 and Lanterns S01E02",
        "/library",
    )
    assert coming.told([one("A", 1), one("B", 2), one("C", 3)]) == (
        "3 episodes out today",
        "A S01E01, B S01E02 and 1 more",
        "/library",
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


def test_the_api_lists_the_shows_episodes_by_day(
    client: TestClient, conn: sqlite3.Connection, shelf: None
):
    # Today's date on this PC decides what's listed: an episode out today always is.
    today = datetime.now().astimezone().date().isoformat()
    with conn:
        conn.execute(
            """INSERT INTO episodes (title_id, season, number, name, aired)
               VALUES (1, 2, 1, 'The Return', ?)""",
            (today,),
        )

    found = client.get("/coming").json()

    assert {
        "titleId": 1,
        "title": "Starfall",
        "kind": "series",
        "hasPoster": False,
        "season": 2,
        "number": 1,
        "last": 1,
        "name": "The Return",
        "aired": today,
        "episodes": 1,
        "held": 0,
    } in found


class _NoScans:
    """The watcher's scanner, never asked to scan here."""

    def start(self) -> NoReturn:
        raise AssertionError

    def status(self) -> NoReturn:
        raise AssertionError

    def moving(self) -> bool:
        return False
