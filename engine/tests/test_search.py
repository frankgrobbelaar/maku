"""Searching the library from the title bar: series and films by any name they go by, episodes
by code or name, and videos by their files' names, the closest first."""

import json
import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from maku.core.catalog import TitleKind
from maku.search import EpisodeFound, FileFound, TitleFound, search

TODAY = date(2026, 10, 15)
STARFALL = "D:\\Videos\\Starfall Academy"


@pytest.fixture
def shelf(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Two made-up series and a film with their videos, a video waiting for a match, one set
    aside as no series or film, one gone, and a title the library has no video of any more."""
    with conn:
        conn.execute("INSERT INTO folders (id, path, added_at) VALUES (1, 'D:\\Videos', 'then')")
        for row in (
            (1, "series", "Starfall Academy", 2019, "2019-04-03", 101, "/starfall.jpg"),
            (2, "series", "Moonlit Harbour", 2021, "2021-01-10", 102, None),
            (3, "movie", "Starfall Academy: The Lantern Festival", 2022, "2022-08-01", 103, None),
            (4, "series", "Lantern Keepers", 2020, "2020-01-01", 104, None),
        ):
            conn.execute(
                """INSERT INTO titles (id, kind, name, year, released, entry_id, poster)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                row,
            )
        conn.execute(
            """INSERT INTO entries (id, name, names, checked_at)
               VALUES (101, 'Starfall Academy', ?, 'then')""",
            (json.dumps(["Starfall Academy", "Hoshifuri Gakuen", "星降り学園"]),),
        )
        for row in (
            (1, 1, 1, "The First Night", "2019-04-03"),
            (1, 1, 2, "Lanterns Over the Lake", "2019-04-10"),
            (1, 1, 3, "The Café at Dawn", "2019-04-17"),
            (1, 1, 4, "Ghost Lights", "2026-12-01"),
            (2, 1, 1, "Harbour Lights", "2021-01-10"),
            (2, 1, 2, "The Tide Turns", "2021-01-17"),
        ):
            conn.execute(
                """INSERT INTO episodes (title_id, season, number, name, aired)
                   VALUES (?, ?, ?, ?, ?)""",
                row,
            )
        for row in (
            (1, f"{STARFALL}\\Starfall Academy - S01E01.mkv", 1, 1, 1, None, "sure", None),
            (
                2,
                f"{STARFALL}\\[Group] Starfall Academy - 02.mkv",
                1,
                1,
                2,
                None,
                "sure",
                None,
            ),
            (3, "D:\\Videos\\Moonlit Harbour\\Moonlit Harbour 01-02.mkv", 2, 1, 1, 2, "sure", None),
            (
                4,
                "D:\\Videos\\Starfall Academy The Lantern Festival (2022).mkv",
                3,
                None,
                None,
                None,
                "sure",
                None,
            ),
            (
                5,
                "D:\\Videos\\Downloads\\lantern_extras_01.mkv",
                None,
                None,
                None,
                None,
                "none",
                None,
            ),
            (
                6,
                "D:\\Videos\\Downloads\\lantern-trailer.mkv",
                None,
                None,
                None,
                None,
                "ignored",
                None,
            ),
            (7, "D:\\Videos\\Old\\lantern old.mkv", None, None, None, None, "none", "gone"),
        ):
            conn.execute(
                """INSERT INTO files (id, folder_id, path, size, modified, found_at, seen_at,
                                      title_id, season, episode, episode_end, matched, gone_at,
                                      identified_at)
                   VALUES (?, 1, ?, 1, 1, 'then', 'then', ?, ?, ?, ?, ?, ?, 'then')""",
                row,
            )
    return conn


def test_finds_series_and_films_by_any_name_they_go_by(shelf: sqlite3.Connection):
    found = search(shelf, "hoshifuri", TODAY)

    assert found.titles == [
        TitleFound(1, "Starfall Academy", TitleKind.SERIES, 2019, True, "Hoshifuri Gakuen")
    ]
    assert search(shelf, "星降り", TODAY).titles[0].also == "星降り学園"


def test_a_search_for_a_show_finds_the_show_not_every_episode_and_video(
    shelf: sqlite3.Connection,
):
    found = search(shelf, "Starfall", TODAY)

    # The series first: both start with it, and it came out first.
    assert [title.name for title in found.titles] == [
        "Starfall Academy",
        "Starfall Academy: The Lantern Festival",
    ]
    assert found.episodes == []
    assert found.files == []


def test_finds_episodes_and_videos_by_what_is_their_own(shelf: sqlite3.Connection):
    found = search(shelf, "lantern", TODAY)

    # Lantern Keepers has no video in the library any more.
    assert [title.name for title in found.titles] == ["Starfall Academy: The Lantern Festival"]
    assert found.episodes == [
        EpisodeFound(1, "Starfall Academy", 1, 2, "Lanterns Over the Lake", 2, coming=False)
    ]
    # Episode 2's video is listed as the episode; the gone video isn't there.
    assert [(file.file_id, file.place) for file in found.files] == [(6, "aside"), (5, "match")]
    assert found.files[1] == FileFound(
        5, "D:\\Videos\\Downloads\\lantern_extras_01.mkv", None, None, None, None, None, "match"
    )
    assert (found.total_titles, found.total_episodes, found.total_files) == (1, 1, 2)


def test_finds_an_episode_however_its_name_is_written_and_says_what_the_library_lacks(
    shelf: sqlite3.Connection,
):
    [missing] = search(shelf, "cafe", TODAY).episodes
    assert (missing.number, missing.file_id, missing.coming) == (3, None, False)

    found = search(shelf, "starfall s01", TODAY).episodes
    # What the library has first, then what it lacks, the one not out yet saying so.
    assert [(each.number, each.file_id, each.coming) for each in found] == [
        (1, 1, False),
        (2, 2, False),
        (3, None, False),
        (4, None, True),
    ]


def test_a_video_of_two_episodes_is_found_as_either(shelf: sqlite3.Connection):
    found = search(shelf, "harbour tide", TODAY)
    assert [(each.number, each.file_id) for each in found.episodes] == [(2, 3)]

    # Its file's name finds the second episode too, and so isn't listed again as a file.
    found = search(shelf, "harbour 01-02", TODAY)
    assert [(each.number, each.file_id) for each in found.episodes] == [(2, 3)]
    assert found.files == []


def test_lists_a_few_of_each_kind_and_counts_them_all(shelf: sqlite3.Connection):
    found = search(shelf, "s01", TODAY, limit=2)

    assert [(each.title, each.number) for each in found.episodes] == [
        ("Moonlit Harbour", 1),
        ("Moonlit Harbour", 2),
    ]
    assert found.total_episodes == 6


def test_an_empty_search_finds_nothing(shelf: sqlite3.Connection):
    assert search(shelf, " - ", TODAY).titles == []


def test_an_episode_without_a_date_is_out_unless_its_show_still_airs(shelf: sqlite3.Connection):
    with shelf:
        # Moonlit Harbour still airs, as TMDB says; Starfall Academy is finished.
        shelf.execute("UPDATE titles SET airing = 1, tmdb_type = 'tv', tmdb_id = 9 WHERE id = 2")
        for title_id, number, name in ((2, 3, "Tide Lanterns"), (1, 5, "Lantern Rain")):
            shelf.execute(
                "INSERT INTO episodes (title_id, season, number, name) VALUES (?, 1, ?, ?)",
                (title_id, number, name),
            )

    found = {
        (each.title_id, each.number): each.coming
        for each in search(shelf, "lantern", TODAY).episodes
    }

    assert found[(2, 3)] is True
    assert found[(1, 5)] is False


def test_says_where_a_video_filed_under_no_title_is(shelf: sqlite3.Connection):
    with shelf:
        for file_id, name, matched, identified in (
            (8, "Lantern Opening Titles.mkv", "extra", "then"),  # an opening, filed under no title
            (9, "Lantern Night 01.mkv", None, None),  # still being read
            (10, "Lantern Gala.mkv", "sure", "then"),  # its title went
        ):
            shelf.execute(
                """INSERT INTO files (id, folder_id, path, size, modified, found_at, seen_at,
                                      matched, identified_at)
                   VALUES (?, 1, ?, 1, 1, 'then', 'then', ?, ?)""",
                (file_id, f"D:\\Videos\\More\\{name}", matched, identified),
            )

    places = {each.file_id: each.place for each in search(shelf, "lantern", TODAY).files}

    assert places == {5: "match", 6: "aside", 8: "extra", 9: "reading", 10: "other"}


def test_the_api_answers_in_the_apps_own_words(client: TestClient, shelf: sqlite3.Connection):
    found = client.get("/search", params={"q": "harbour lights"}).json()

    assert found["titles"] == []
    assert found["episodes"] == [
        {
            "titleId": 2,
            "title": "Moonlit Harbour",
            "season": 1,
            "number": 1,
            "name": "Harbour Lights",
            "fileId": 3,
            "coming": False,
        }
    ]
    assert found["totalEpisodes"] == 1
