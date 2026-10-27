"""Choosing a title's poster: TMDB's to choose from, the owner's choice kept over the one found as
the episode list is refreshed, and the poster next to the show following it."""

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from maku import posters
from maku.config import DataPaths
from maku.core.catalog import TitleKind, show
from maku.identify import save_show
from maku.tmdb import API as TMDB
from tests.fake_web import FakeWeb
from tests.services import with_key
from tests.tmdb_data import tv_details


@pytest.fixture
def title(conn: sqlite3.Connection, paths: DataPaths, web: FakeWeb) -> None:
    """A made-up show TMDB has three posters of."""
    with_key(paths)
    with conn:
        conn.execute(
            """INSERT INTO titles (id, kind, name, tmdb_type, tmdb_id, entry_id, poster)
               VALUES (1, 'series', 'Glass Orchard', 'tv', 4102, 4102, '/found.jpg')"""
        )
    web.answers[f"GET {TMDB}/tv/4102/images"] = {
        "posters": [
            {
                "file_path": "/plain.jpg",
                "iso_639_1": None,
                "width": 1000,
                "height": 1500,
                "vote_average": 5.2,
            },
            {
                "file_path": "/found.jpg",
                "iso_639_1": "en",
                "width": 680,
                "height": 1000,
                "vote_average": 5.6,
            },
            {
                "file_path": "/de.jpg",
                "iso_639_1": "de",
                "width": 1000,
                "height": 1500,
                "vote_average": 4.0,
            },
        ]
    }


def test_the_posters_to_choose_from_put_the_one_it_has_first(client: TestClient, title: None):
    found = client.get("/titles/1/posters").json()

    assert [(each["poster"], each["language"]) for each in found["options"]] == [
        ("/found.jpg", "en"),
        ("/plain.jpg", None),
        ("/de.jpg", "de"),
    ]
    assert found["options"][0]["address"] == "https://image.tmdb.org/t/p/w342/found.jpg"
    assert (found["found"], found["chosen"], found["problem"]) == ("/found.jpg", None, None)


def test_the_owners_choice_is_every_readers_poster_and_survives_a_refresh(
    client: TestClient, conn: sqlite3.Connection, title: None
):
    assert client.put("/titles/1/poster", json={"poster": "/de.jpg"}).status_code == 204

    row = conn.execute("SELECT poster, poster_choice FROM titles WHERE id = 1").fetchone()
    assert (row["poster"], row["poster_choice"]) == ("/found.jpg", "/de.jpg")
    refreshed = show(tv_details(4102, "Glass Orchard", (2,), first_aired=date(2012, 1, 10)))
    assert refreshed is not None
    save_show(conn, refreshed, TitleKind.SERIES, 4102, datetime.now(UTC))
    row = conn.execute("SELECT poster, poster_choice FROM titles WHERE id = 1").fetchone()
    assert (row["poster"], row["poster_choice"]) == ("/poster-4102.jpg", "/de.jpg")
    assert client.get("/titles/1").json()["hasPoster"] is True
    assert client.get("/titles/1/posters").json()["options"][0]["poster"] == "/de.jpg"
    assert client.put("/titles/1/poster", json={"poster": None}).status_code == 204
    assert conn.execute("SELECT poster_choice FROM titles WHERE id = 1").fetchone()[0] is None


def test_only_tmdbs_pictures_are_kept(client: TestClient, title: None):
    for elsewhere in ("https://example.com/x.jpg", "https://images.example.org/cover.jpg"):
        assert client.put("/titles/1/poster", json={"poster": elsewhere}).status_code == 400
    assert client.put("/titles/99/poster", json={"poster": "/de.jpg"}).status_code == 400


def test_the_poster_maku_wrote_next_to_the_show_makes_way(
    conn: sqlite3.Connection, tmp_path: Path, title: None
):
    picture = tmp_path / "Glass Orchard" / "poster.jpg"
    picture.parent.mkdir()
    picture.write_bytes(b"a poster")
    owners = tmp_path / "Glass Orchard" / "fanart.jpg"
    owners.write_bytes(b"maku's background")
    with conn:
        conn.executemany(
            "INSERT INTO artwork_files (path, title_id, size, written_at) VALUES (?, 1, ?, 'then')",
            [(str(picture), 8), (str(owners), 17)],
        )

    assert posters.choose(conn, 1, "/de.jpg")

    assert not picture.exists()
    assert owners.exists()  # the background isn't the poster
    assert [row[0] for row in conn.execute("SELECT path FROM artwork_files")] == [str(owners)]


def test_offline_the_choice_says_why_tmdbs_are_missing(
    client: TestClient, web: FakeWeb, title: None
):
    web.offline = True

    found = client.get("/titles/1/posters").json()

    assert found["problem"].startswith("TMDB's posters couldn't be asked for now")
    assert [each["poster"] for each in found["options"]] == ["/found.jpg"]


def test_without_a_key_theres_the_one_it_has(client: TestClient, paths: DataPaths, title: None):
    (paths.root / "credentials.json").unlink()

    found = client.get("/titles/1/posters").json()

    assert [each["poster"] for each in found["options"]] == ["/found.jpg"]
