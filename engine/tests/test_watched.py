"""What the owner has watched, and where each video stopped: kept as the player says, shown on a
title's page, and Home's "Continue watching" going on from the latest played."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from maku import watched
from tests.shelf import library


@pytest.fixture
def shelf(conn: sqlite3.Connection, tmp_path: Path) -> None:
    """Three episodes of a made-up series, 24 minutes each, and a film."""
    root = tmp_path / "Videos"
    names = [f"Starfall (2019)/Season 01/Starfall (2019) - S01E0{n}.mkv" for n in (1, 2, 3)]
    library(conn, root, [*names, "Movies/Lanterns (2021)/Lanterns (2021).mkv"])
    with conn:
        conn.execute("INSERT INTO titles (id, kind, name) VALUES (1, 'series', 'Starfall')")
        conn.execute("INSERT INTO titles (id, kind, name) VALUES (2, 'movie', 'Lanterns')")
        conn.execute(
            """UPDATE files SET title_id = 1, season = 1, episode = id, matched = 'sure'
               WHERE id <= 3"""
        )
        conn.execute("UPDATE files SET title_id = 2, matched = 'sure' WHERE id = 4")
        conn.execute(
            """INSERT INTO episodes (title_id, season, number, name)
               VALUES (1, 1, 1, 'The First Night'), (1, 1, 2, 'Lanterns Over the Lake'),
                      (1, 1, 3, 'The Café at Dawn')"""
        )


def test_a_video_stopped_part_way_is_picked_up_there(conn: sqlite3.Connection, shelf: None):
    watched.note(conn, 2, 600, 1440, "2026-10-18T10:00:00+00:00")

    assert watched.of_title(conn, 1) == {2: watched.Watch(watched=False, resume=600)}
    [going] = watched.continuing(conn)
    assert (going.title, going.up_next, going.video.file_id, going.video.resume) == (
        "Starfall",
        False,
        2,
        600,
    )
    assert going.video.name == "Lanterns Over the Lake"
    assert [each.file_id for each in going.following] == [3]


def test_once_seen_to_its_end_the_next_episode_is_up_next(conn: sqlite3.Connection, shelf: None):
    watched.note(conn, 1, 1400, 1440, "2026-10-18T10:00:00+00:00")

    assert watched.of_title(conn, 1)[1] == watched.Watch(watched=True, resume=None)
    [going] = watched.continuing(conn)
    assert (going.up_next, going.video.file_id, going.video.resume) == (True, 2, None)


def test_two_copies_of_an_episode_are_one_step(conn: sqlite3.Connection, shelf: None):
    with conn:
        conn.execute(
            """INSERT INTO files (id, folder_id, path, size, modified, found_at, seen_at, probe,
                                  duration, title_id, season, episode)
               SELECT 9, folder_id, path || ' (copy).mkv', size, modified, found_at, seen_at,
                      probe, duration, 1, 1, 2
               FROM files WHERE id = 2"""
        )
    watched.note(conn, 1, 1440, 1440, "2026-10-18T10:00:00+00:00")

    [going] = watched.continuing(conn)
    assert going.video.episode == 2
    assert [each.episode for each in going.following] == [3]  # one E02, then E03

    watched.note(conn, 9, 1440, 1440, "2026-10-18T11:00:00+00:00")  # its copy, seen
    [going] = watched.continuing(conn)
    assert (going.video.episode, going.up_next) == (3, True)


def test_played_again_a_watched_video_stays_watched(conn: sqlite3.Connection, shelf: None):
    watched.note(conn, 1, 1400, 1440, "2026-10-18T10:00:00+00:00")
    watched.note(conn, 1, 300, 1440, "2026-10-18T11:00:00+00:00")

    assert watched.of_title(conn, 1)[1] == watched.Watch(watched=True, resume=300)
    [going] = watched.continuing(conn)
    assert (going.up_next, going.video.file_id) == (False, 1)


def test_a_quick_look_or_a_title_all_seen_isnt_listed(conn: sqlite3.Connection, shelf: None):
    watched.note(conn, 4, 12, 1440, "2026-10-18T10:00:00+00:00")  # the film, looked at
    watched.note(conn, 3, 1440, 1440, "2026-10-18T11:00:00+00:00")  # the last episode, seen

    assert watched.continuing(conn) == []


def test_a_quick_look_at_another_video_leaves_the_title_where_it_was(
    conn: sqlite3.Connection, shelf: None
):
    watched.note(conn, 2, 600, 1440, "2026-10-18T10:00:00+00:00")
    watched.note(conn, 1, 12, 1440, "2026-10-18T11:00:00+00:00")

    [going] = watched.continuing(conn)
    assert (going.video.file_id, going.video.resume) == (2, 600)


def test_a_video_that_wont_play_now_isnt_continued(conn: sqlite3.Connection, shelf: None):
    watched.note(conn, 2, 600, 1440, "2026-10-18T10:00:00+00:00")
    with conn:
        conn.execute("UPDATE files SET problem = 'No video stream' WHERE id = 2")

    assert watched.continuing(conn) == []


def test_the_latest_played_title_comes_first(conn: sqlite3.Connection, shelf: None):
    watched.note(conn, 1, 600, 1440, "2026-10-18T10:00:00+00:00")
    watched.note(conn, 4, 3000, 6000, "2026-10-18T12:00:00+00:00")

    assert [going.title for going in watched.continuing(conn)] == ["Lanterns", "Starfall"]


def test_marking_a_season_watched_goes_on_after_its_last(conn: sqlite3.Connection, shelf: None):
    watched.note(conn, 3, 600, 1440, "2026-10-18T10:00:00+00:00")
    watched.mark(conn, [1, 2], watched=True, now="2026-10-18T11:00:00+00:00")

    marked = watched.of_title(conn, 1)
    assert [marked[n].watched for n in (1, 2, 3)] == [True, True, False]
    [going] = watched.continuing(conn)
    assert (going.up_next, going.video.file_id, going.video.resume) == (True, 3, 600)


def test_marked_not_watched_a_video_starts_from_the_top(conn: sqlite3.Connection, shelf: None):
    watched.note(conn, 1, 1400, 1440, "2026-10-18T10:00:00+00:00")
    watched.mark(conn, [1], watched=False, now="2026-10-18T11:00:00+00:00")

    assert watched.of_title(conn, 1)[1] == watched.Watch(watched=False, resume=None)
    assert watched.continuing(conn) == []


def test_a_title_left_out_of_continue_watching_keeps_its_place(
    conn: sqlite3.Connection, shelf: None
):
    watched.note(conn, 2, 600, 1440, "2026-10-18T10:00:00+00:00")
    watched.forget(conn, 1)

    assert watched.continuing(conn) == []
    assert watched.of_title(conn, 1)[2].resume == 600
    watched.note(conn, 2, 700, 1440, "2026-10-18T11:00:00+00:00")
    assert [going.title for going in watched.continuing(conn)] == ["Starfall"]


def test_a_video_gone_from_the_library_takes_its_record_with_it(
    conn: sqlite3.Connection, shelf: None
):
    watched.note(conn, 2, 600, 1440, "2026-10-18T10:00:00+00:00")
    with conn:
        conn.execute("DELETE FROM files WHERE id = 2")

    assert conn.execute("SELECT COUNT(*) FROM watched").fetchone()[0] == 0


def test_the_api_keeps_positions_marks_and_lists(client: TestClient, shelf: None):
    assert (
        client.put("/files/2/position", json={"position": 600, "duration": 1440}).status_code == 204
    )
    assert client.put("/files/99/position", json={"position": 1}).status_code == 204  # gone
    [going] = client.get("/continue").json()
    assert going["video"]["fileId"] == 2
    assert going["video"]["resume"] == 600
    assert going["upNext"] is False
    assert going["hasPoster"] is False

    videos = client.get("/titles/1").json()["videos"]
    assert [(v["watched"], v["resume"]) for v in videos] == [
        (False, None),
        (False, 600),
        (False, None),
    ]
    assert client.post("/files/watched", json={"files": [2], "watched": True}).status_code == 204
    assert client.get("/titles/1").json()["videos"][1]["watched"] is True
    assert client.get("/continue").json()[0]["video"]["fileId"] == 3

    assert client.delete("/continue/1").status_code == 204
    assert client.get("/continue").json() == []
    assert client.put("/files/2/position", json={"position": -1}).status_code == 422
