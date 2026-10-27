"""A video in full through the API: what it holds, where it is, the episode it is, and what
converting it does; an episode's own details, the library's or not; and the picture for the top
of each."""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from maku.web import Reply
from tests.fake_web import FakeWeb
from tests.shelf import library


@pytest.fixture
def shelf(conn: sqlite3.Connection, tmp_path: Path) -> Path:
    """Two episodes of a made-up series, read: the first with English and German subtitle files
    beside it, the English ones Maku's."""
    root = tmp_path / "Videos"
    names = [f"Starfall (2019)/Season 01/Starfall (2019) - S01E0{n}.mkv" for n in (1, 2)]
    library(conn, root, names)
    season = root / "Starfall (2019)" / "Season 01"
    english = season / "Starfall (2019) - S01E01.en.srt"
    english.write_text("1\n00:00:01,000 --> 00:00:02,000\nOver here!\n", "utf-8")
    (season / "Starfall (2019) - S01E01.de.srt").write_text("Hallo", "utf-8")
    written = english.stat()
    with conn:
        conn.execute("INSERT INTO titles (id, kind, name) VALUES (1, 'series', 'Starfall')")
        conn.execute("UPDATE files SET title_id = 1, season = 1, episode = id, matched = 'sure'")
        conn.execute(
            """INSERT INTO episodes (title_id, season, number, name, aired, overview, minutes)
               VALUES (1, 1, 1, 'The First Night', '2019-04-03', 'Mira arrives.', 24),
                      (1, 1, 2, 'Lanterns Over the Lake', '2019-04-10', NULL, 24),
                      (1, 1, 3, 'The Café at Dawn', '2019-04-17', 'A quiet morning.', 23)"""
        )
        conn.execute(
            """INSERT INTO made_subtitles (file_id, name, language, size, modified, made_at, sound)
               VALUES (1, '.en.srt', 'ja', ?, ?, 'then', 0)""",
            (written.st_size, written.st_mtime_ns),
        )
    return season


def test_a_video_says_what_it_holds_and_what_converting_it_does(client: TestClient, shelf: Path):
    found = client.get("/files/1").json()

    assert found["path"] == str(shelf / "Starfall (2019) - S01E01.mkv")
    assert (found["title"], found["season"], found["episode"]) == ("Starfall", 1, 1)
    assert (found["episodeName"], found["aired"], found["overview"]) == (
        "The First Night",
        "2019-04-03",
        "Mira arrives.",
    )
    assert found["picture"] == {
        "codec": "hevc",
        "width": 720,
        "height": 540,
        "bitDepth": 10,
        "frameRate": pytest.approx(23.976, abs=0.001),
    }
    assert found["sound"] == [
        {"language": "jpn", "codec": "aac", "channels": 2, "lossless": False, "heard": False}
    ]
    assert [(s["language"], s["beside"], s["made"]) for s in found["subtitles"]] == [
        ("de", True, False),
        ("en", True, True),
    ]
    assert found["duration"] == pytest.approx(1440)
    assert found["converted"] is False
    converting = found["converting"]
    assert (converting["state"], converting["method"]) == ("ready", "rename")  # HEVC 10-bit
    assert converting["reasons"] == ["Already HEVC 10-bit in MKV: only renamed"]


def test_a_track_that_doesnt_say_its_language_has_the_one_maku_heard(
    client: TestClient, conn: sqlite3.Connection, shelf: Path
):
    probe = json.loads(conn.execute("SELECT probe FROM files WHERE id = 1").fetchone()[0])
    for stream in probe["streams"]:
        if stream.get("codec_type") == "audio":
            stream.get("tags", {}).pop("language", None)
    with conn:
        conn.execute("UPDATE files SET probe = ? WHERE id = 1", (json.dumps(probe),))

    [sound] = client.get("/files/1").json()["sound"]

    assert (sound["language"], sound["heard"]) == ("ja", True)


def test_a_video_maku_doesnt_have_is_404(client: TestClient, shelf: Path):
    assert client.get("/files/99").status_code == 404


def test_an_episode_says_what_happens_in_it_and_where_its_video_is(client: TestClient, shelf: Path):
    held = client.get("/titles/1/episodes/1/2").json()
    lacking = client.get("/titles/1/episodes/1/3").json()

    assert (held["name"], held["overview"], held["fileId"]) == (
        "Lanterns Over the Lake",
        None,
        2,
    )
    assert (lacking["name"], lacking["overview"], lacking["minutes"], lacking["fileId"]) == (
        "The Café at Dawn",
        "A quiet morning.",
        23,
        None,
    )
    assert client.get("/titles/1/episodes/2/1").status_code == 404


STILL = "https://image.tmdb.org/t/p/original/still-1-1-1.jpg"
BACKDROP = "https://image.tmdb.org/t/p/w1280/backdrop-1.jpg"


def test_a_video_has_tmdbs_picture_from_its_episode_fetched_once(
    client: TestClient, conn: sqlite3.Connection, shelf: Path, web: FakeWeb
):
    with conn:
        conn.execute("UPDATE episodes SET still = '/still-1-1-1.jpg' WHERE number = 1")
    web.answers[f"GET {STILL}"] = Reply(200, {}, b"a picture from the episode")

    first = client.get("/files/1/picture")
    again = client.get("/files/1/picture")

    assert (first.status_code, first.content, first.headers["content-type"]) == (
        200,
        b"a picture from the episode",
        "image/jpeg",
    )
    # From the episode: the window blurs it till asked, for an episode not yet watched.
    assert first.headers["maku-picture"] == "episode"
    assert again.content == first.content
    assert web.paths().count(f"GET {STILL}") == 1


def test_an_episode_has_tmdbs_picture_from_it_else_its_shows(
    client: TestClient, conn: sqlite3.Connection, shelf: Path, web: FakeWeb
):
    with conn:
        conn.execute("UPDATE episodes SET still = '/still-1-1-1.jpg' WHERE number = 3")
        conn.execute("UPDATE titles SET backdrop = '/backdrop-1.jpg' WHERE id = 1")
    web.answers[f"GET {STILL}"] = Reply(200, {}, b"a picture from episode 3")
    web.answers[f"GET {BACKDROP}"] = Reply(200, {}, b"the show's picture")

    lacking = client.get("/titles/1/episodes/1/3/picture")
    without = client.get("/titles/1/episodes/1/2/picture")

    assert (lacking.content, lacking.headers["maku-picture"]) == (
        b"a picture from episode 3",
        "episode",
    )
    assert (without.content, without.headers["maku-picture"]) == (b"the show's picture", "show")
    assert client.get("/titles/1/episodes/2/1/picture").status_code == 404


def test_without_a_picture_anywhere_theres_none(
    client: TestClient, conn: sqlite3.Connection, shelf: Path
):
    assert client.get("/titles/1/episodes/1/3/picture").status_code == 404
    assert client.get("/files/1/picture").status_code == 404  # and no ffmpeg yet for a frame
    assert client.get("/files/99/picture").status_code == 404


def test_a_video_gone_from_the_library_has_no_picture(
    client: TestClient, conn: sqlite3.Connection, shelf: Path, web: FakeWeb
):
    with conn:
        conn.execute("UPDATE episodes SET still = '/still-1-1-1.jpg' WHERE number = 1")
        conn.execute("UPDATE files SET gone_at = 'then' WHERE id = 1")
    web.answers[f"GET {STILL}"] = Reply(200, {}, b"a picture from the episode")

    assert client.get("/files/1/picture").status_code == 404


def test_a_picture_is_asked_for_afresh_each_time(
    client: TestClient, conn: sqlite3.Connection, shelf: Path, web: FakeWeb
):
    # What's behind the address changes, as a match changes or TMDB's picture comes in.
    with conn:
        conn.execute("UPDATE episodes SET still = '/still-1-1-1.jpg' WHERE number = 1")
    web.answers[f"GET {STILL}"] = Reply(200, {}, b"a picture from the episode")

    assert client.get("/files/1/picture").headers["cache-control"] == "no-cache"
