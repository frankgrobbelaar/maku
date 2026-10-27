"""Poster and background pictures next to each show, for media servers: written when the owner
wants them, never over a file already there, and only Maku's own, unchanged, taken away."""

import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from maku.artwork_files import forget_artwork, write_artwork
from maku.web import Reply
from tests.fake_web import Asked, FakeWeb
from tests.shelf import NOW, library

POSTER = "GET https://image.tmdb.org/t/p/w780/poster.jpg"
BACKDROP = "GET https://image.tmdb.org/t/p/w1280/backdrop.jpg"


@pytest.fixture
def show(conn: sqlite3.Connection, tmp_path: Path) -> Path:
    """Glass Orchard's first episode in its own show folder, the owner wanting the pictures."""
    library(
        conn,
        tmp_path / "Videos",
        ["TV/Glass Orchard (2012)/Season 01/Glass Orchard (2012) - S01E01.mkv"],
    )
    with conn:
        conn.execute(
            "INSERT INTO titles (id, kind, name, year, poster, backdrop)"
            " VALUES (1, 'series', 'Glass Orchard', 2012, '/poster.jpg', '/backdrop.jpg')"
        )
        conn.execute("UPDATE files SET title_id = 1, season = 1, episode = 1, matched = 'sure'")
        conn.execute("INSERT INTO settings (key, value) VALUES ('artwork', 'true')")
    return tmp_path / "Videos" / "TV" / "Glass Orchard (2012)"


@pytest.fixture
def pictures() -> FakeWeb:
    return FakeWeb(
        answers={
            POSTER: Reply(200, {"content-type": "image/jpeg"}, b"a poster"),
            BACKDROP: Reply(200, {"content-type": "image/jpeg"}, b"a background"),
        }
    )


def test_the_poster_and_background_go_next_to_the_show_once(
    conn: sqlite3.Connection, show: Path, pictures: FakeWeb
):
    assert write_artwork(conn, pictures, now=NOW) == 2
    assert write_artwork(conn, pictures, now=NOW) == 0  # there already: nothing asked again

    assert (show / "poster.jpg").read_bytes() == b"a poster"
    assert (show / "fanart.jpg").read_bytes() == b"a background"
    assert pictures.paths() == [POSTER, BACKDROP]


def test_nothing_is_written_unless_the_owner_wants_it(
    conn: sqlite3.Connection, show: Path, pictures: FakeWeb
):
    with conn:
        conn.execute("UPDATE settings SET value = 'false' WHERE key = 'artwork'")

    assert write_artwork(conn, pictures, now=NOW) == 0
    assert not (show / "poster.jpg").exists()


def test_a_picture_already_there_is_never_overwritten(
    conn: sqlite3.Connection, show: Path, pictures: FakeWeb
):
    (show / "poster.jpg").write_bytes(b"the owner's own poster")

    write_artwork(conn, pictures, now=NOW)

    assert (show / "poster.jpg").read_bytes() == b"the owner's own poster"
    assert (show / "fanart.jpg").read_bytes() == b"a background"


def test_offline_the_pictures_wait_for_next_time(conn: sqlite3.Connection, show: Path):
    assert write_artwork(conn, FakeWeb(offline=True), now=NOW) == 0

    assert not (show / "poster.jpg").exists()
    assert conn.execute("SELECT COUNT(*) FROM artwork_files").fetchone()[0] == 0


def test_only_makus_own_unchanged_pictures_are_taken_away(
    conn: sqlite3.Connection, show: Path, pictures: FakeWeb
):
    write_artwork(conn, pictures, now=NOW)
    (show / "fanart.jpg").write_bytes(b"the owner put another background in its place")

    assert forget_artwork(conn) == 1

    assert not (show / "poster.jpg").exists()
    assert (show / "fanart.jpg").read_bytes() == b"the owner put another background in its place"
    assert conn.execute("SELECT COUNT(*) FROM artwork_files").fetchone()[0] == 0


def test_a_folder_shared_with_another_series_gets_no_pictures(
    conn: sqlite3.Connection, show: Path, pictures: FakeWeb
):
    library(
        conn, show.parent.parent, ["TV/Glass Orchard (2012)/Season 01/The Harbour Line - 01.mkv"]
    )
    with conn:
        conn.execute("INSERT INTO titles (id, kind, name) VALUES (2, 'series', 'The Harbour Line')")
        conn.execute("UPDATE files SET title_id = 2 WHERE path LIKE '%The Harbour Line - 01.mkv'")

    assert write_artwork(conn, pictures, now=NOW) == 0


def test_only_pictures_named_as_maku_names_them_are_ever_taken_away(
    conn: sqlite3.Connection, show: Path
):
    precious = show / "thesis.docx"  # recorded as a picture, as a damaged database could hold
    precious.write_text("years of work")
    with conn:
        conn.execute(
            "INSERT INTO artwork_files (path, title_id, size, written_at) VALUES (?, 1, ?, 'now')",
            (str(precious), precious.stat().st_size),
        )

    assert forget_artwork(conn) == 0

    assert precious.read_text() == "years of work"


def jpeg(data: bytes) -> Reply:
    return Reply(200, {"content-type": "image/jpeg"}, data)


def test_a_show_whose_drive_isnt_connected_waits_without_asking(
    conn: sqlite3.Connection, show: Path, pictures: FakeWeb
):
    shutil.rmtree(show)  # its drive unplugged: its videos' records stay, its folder isn't there

    assert write_artwork(conn, pictures, now=NOW) == 0

    assert pictures.asked == []


def test_a_picture_the_server_refuses_is_passed_over_and_asked_again_a_day_later(
    conn: sqlite3.Connection, show: Path
):
    web = FakeWeb(answers={BACKDROP: jpeg(b"a background")})  # the poster is gone: a 404
    refused: dict[str, datetime] = {}

    assert write_artwork(conn, web, now=NOW, refused=refused) == 1
    write_artwork(conn, web, now=NOW + timedelta(minutes=5), refused=refused)
    write_artwork(conn, web, now=NOW + timedelta(days=1, minutes=1), refused=refused)

    assert (show / "fanart.jpg").read_bytes() == b"a background"
    assert web.paths() == [POSTER, BACKDROP, POSTER]


def test_the_poster_the_owner_chose_is_the_one_written(conn: sqlite3.Connection, show: Path):
    with conn:
        conn.execute("UPDATE titles SET poster_choice = '/chosen.jpg', backdrop = NULL")
    chosen = "GET https://image.tmdb.org/t/p/w780/chosen.jpg"
    web = FakeWeb(answers={chosen: jpeg(b"the owner's choice")})

    assert write_artwork(conn, web, now=NOW) == 1

    assert (show / "poster.jpg").read_bytes() == b"the owner's choice"
    assert web.paths() == [chosen]


def test_a_picture_anywhere_but_on_tmdbs_server_is_never_asked_for(
    conn: sqlite3.Connection, show: Path
):
    with conn:  # another server's address, as a damaged record could hold
        conn.execute("UPDATE titles SET poster = 'https://pictures.example/poster.jpg'")
    web = FakeWeb(answers={BACKDROP: jpeg(b"a background")})

    assert write_artwork(conn, web, now=NOW) == 1

    assert not (show / "poster.jpg").exists()
    assert web.paths() == [BACKDROP]


def test_after_a_change_of_match_makus_pictures_of_the_other_title_make_way(
    conn: sqlite3.Connection, show: Path, pictures: FakeWeb
):
    write_artwork(conn, pictures, now=NOW)
    (show / "fanart.jpg").write_bytes(b"the owner's own background")
    with conn:  # the owner changed the match: the videos are another title's now
        conn.execute(
            "INSERT INTO titles (id, kind, name, year, poster)"
            " VALUES (2, 'series', 'Glass Orchard Revisited', 2023, '/revisited.jpg')"
        )
        conn.execute("UPDATE files SET title_id = 2")
    web = FakeWeb(
        answers={"GET https://image.tmdb.org/t/p/w780/revisited.jpg": jpeg(b"its poster")}
    )

    assert write_artwork(conn, web, now=NOW) == 1

    assert (show / "poster.jpg").read_bytes() == b"its poster"
    assert (show / "fanart.jpg").read_bytes() == b"the owner's own background"


def test_after_a_change_of_match_a_picture_the_title_hasnt_goes_too(
    conn: sqlite3.Connection, show: Path, pictures: FakeWeb
):
    write_artwork(conn, pictures, now=NOW)
    with conn:  # matched anew to a title with neither picture
        conn.execute(
            "INSERT INTO titles (id, kind, name) VALUES (2, 'series', 'Glass Orchard Revisited')"
        )
        conn.execute("UPDATE files SET title_id = 2")

    write_artwork(conn, FakeWeb(), now=NOW)

    assert not (show / "poster.jpg").exists()
    assert not (show / "fanart.jpg").exists()
    assert conn.execute("SELECT COUNT(*) FROM artwork_files").fetchone()[0] == 0


def test_pictures_turned_off_while_they_are_written_all_go(conn: sqlite3.Connection, show: Path):
    def turned_off_meanwhile(asked: Asked) -> Reply:
        with conn:  # the owner turns them off as the poster arrives (Settings, on its own thread)
            conn.execute("UPDATE settings SET value = 'false' WHERE key = 'artwork'")
        forget_artwork(conn)
        return jpeg(b"a poster")

    web = FakeWeb(answers={POSTER: turned_off_meanwhile, BACKDROP: jpeg(b"a background")})

    write_artwork(conn, web, now=NOW)

    assert not (show / "poster.jpg").exists()
    assert not (show / "fanart.jpg").exists()
