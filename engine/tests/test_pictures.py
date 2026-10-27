"""The picture across the top of a video's details: TMDB's from its episode, else a frame from the
video itself, else its show's wide picture."""

import sqlite3
from pathlib import Path

import pytest

from maku import pictures, stills
from maku.config import DataPaths
from maku.web import Reply
from tests.fake_web import FakeWeb
from tests.shelf import library

FFMPEG = Path("C:/Maku/tools/ffmpeg/ffmpeg.exe")
BACKDROP = "GET https://image.tmdb.org/t/p/w1280/backdrop-1.jpg"


@pytest.fixture
def video(conn: sqlite3.Connection, tmp_path: Path) -> Path:
    """One episode of a made-up show TMDB has no picture from, with the show's own."""
    root = tmp_path / "Videos"
    library(conn, root, ["Starfall (2019)/Season 01/Starfall (2019) - S01E01.mkv"])
    with conn:
        conn.execute(
            "INSERT INTO titles (id, kind, name, backdrop)"
            " VALUES (1, 'series', 'Starfall', '/backdrop-1.jpg')"
        )
        conn.execute("UPDATE files SET title_id = 1, season = 1, episode = 1, matched = 'sure'")
        conn.execute("INSERT INTO episodes (title_id, season, number) VALUES (1, 1, 1)")
    return root / "Starfall (2019)" / "Season 01" / "Starfall (2019) - S01E01.mkv"


class Frames:
    """Stands in for taking a frame: writes one, or none for a file ffmpeg can't read."""

    def __init__(self, paths: DataPaths, works: bool = True) -> None:
        self.asked: list[tuple[Path, float | None]] = []
        self.kept = paths.cache / "frame.jpg"
        self.works = works

    def __call__(
        self, paths: DataPaths, ffmpeg: Path | None, video: Path, seconds: float | None
    ) -> Path | None:
        self.asked.append((video, seconds))
        if not self.works:
            return None
        self.kept.parent.mkdir(parents=True, exist_ok=True)
        self.kept.write_bytes(b"a frame")
        return self.kept


def test_without_tmdbs_picture_a_video_shows_a_frame_from_itself(
    paths: DataPaths,
    conn: sqlite3.Connection,
    video: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    frames = Frames(paths)
    monkeypatch.setattr(stills, "picture", frames)
    web = FakeWeb({BACKDROP: Reply(200, {}, b"the show's picture")})

    found = pictures.of_file(conn, paths, web, FFMPEG, 1)

    assert found is not None
    assert (found.path.read_bytes(), found.from_episode) == (b"a frame", True)
    assert frames.asked == [(video, 1440.0)]
    assert web.asked == []  # the show's picture wasn't needed


def test_a_film_shows_its_own_picture_rather_than_a_frame(
    paths: DataPaths,
    conn: sqlite3.Connection,
    video: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    frames = Frames(paths)
    monkeypatch.setattr(stills, "picture", frames)
    with conn:
        conn.execute("UPDATE titles SET kind = 'movie'")
        conn.execute("UPDATE files SET season = NULL, episode = NULL")
    web = FakeWeb({BACKDROP: Reply(200, {}, b"the film's picture")})

    found = pictures.of_file(conn, paths, web, FFMPEG, 1)

    assert found is not None
    assert (found.path.read_bytes(), found.from_episode) == (b"the film's picture", False)
    assert frames.asked == []  # nothing to blur, nothing given away
    # Without a picture of its own, a frame stands in, from the film: blurred till asked.
    with conn:
        conn.execute("UPDATE titles SET backdrop = NULL")
    framed = pictures.of_file(conn, paths, FakeWeb(), FFMPEG, 1)
    assert framed is not None
    assert framed.from_episode


def test_a_frame_that_cant_be_taken_gives_the_shows_picture(
    paths: DataPaths,
    conn: sqlite3.Connection,
    video: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(stills, "picture", Frames(paths, works=False))
    web = FakeWeb({BACKDROP: Reply(200, {}, b"the show's picture")})

    found = pictures.of_file(conn, paths, web, FFMPEG, 1)

    assert found is not None
    assert (found.path.read_bytes(), found.from_episode) == (b"the show's picture", False)


def test_a_video_that_wont_play_isnt_asked_for_a_frame(
    paths: DataPaths,
    conn: sqlite3.Connection,
    video: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    frames = Frames(paths)
    monkeypatch.setattr(stills, "picture", frames)
    with conn:
        conn.execute("UPDATE files SET problem = 'No video stream'")

    found = pictures.of_file(conn, paths, FakeWeb(), FFMPEG, 1)

    assert found is None
    assert frames.asked == []


def test_offline_an_episode_has_its_shows_picture_kept_from_before(
    paths: DataPaths, conn: sqlite3.Connection, video: Path
):
    online = FakeWeb({BACKDROP: Reply(200, {}, b"the show's picture")})
    assert pictures.of_episode(conn, paths, online, 1, 1, 1) is not None  # kept from now on
    with conn:
        conn.execute("UPDATE episodes SET still = '/still-1-1-1.jpg'")

    found = pictures.of_episode(conn, paths, FakeWeb(offline=True), 1, 1, 1)

    assert found is not None
    assert (found.path.read_bytes(), found.from_episode) == (b"the show's picture", False)
    assert pictures.of_episode(conn, paths, FakeWeb(), 1, 2, 1) is None  # no such episode


def test_offline_tmdbs_picture_waits_and_the_frame_stands_in(
    paths: DataPaths,
    conn: sqlite3.Connection,
    video: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(stills, "picture", Frames(paths))
    with conn:
        conn.execute("UPDATE episodes SET still = '/still-1-1-1.jpg'")

    found = pictures.of_file(conn, paths, FakeWeb(offline=True), FFMPEG, 1)

    assert found is not None
    assert (found.path.read_bytes(), found.from_episode) == (b"a frame", True)
