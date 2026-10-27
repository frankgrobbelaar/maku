"""The library folders, and the videos a scan finds and reads in them."""

import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maku.core.media import Json
from maku.library import (
    FolderError,
    add_folder,
    find_files,
    folders,
    read_file,
    remove_folder,
    unread,
)
from maku.probe import ProbeError
from tests.fake_ffprobe import REPORT

NOW = datetime(2026, 10, 11, 9, 30, tzinfo=UTC)
STAMP = NOW.isoformat()


def paths_in(conn: sqlite3.Connection, *, gone: bool = False) -> set[str]:
    rows = conn.execute("SELECT path, gone_at FROM files").fetchall()
    return {Path(row["path"]).name for row in rows if (row["gone_at"] is not None) == gone}


def test_a_folder_is_added_once_whatever_its_case(conn: sqlite3.Connection, videos: Path):
    added = add_folder(conn, videos, now=NOW)

    assert folders(conn) == [added]
    with pytest.raises(FolderError) as raised:
        add_folder(conn, Path(str(videos).upper()), now=NOW)
    assert str(raised.value) == f"{videos} is already in your library."


def test_a_folder_inside_one_already_there_isnt_added(conn: sqlite3.Connection, videos: Path):
    add_folder(conn, videos, now=NOW)

    with pytest.raises(FolderError) as raised:
        add_folder(conn, videos / "The Harbour Line", now=NOW)

    assert str(raised.value) == (
        f"{videos / 'The Harbour Line'} is already in your library, as part of {videos}."
    )


def test_a_parent_folder_takes_in_the_folders_below_it_and_their_files(
    conn: sqlite3.Connection, videos: Path
):
    inner = add_folder(conn, videos / "The Harbour Line", now=NOW)
    find_files(conn, inner, stamp=STAMP)

    outer = add_folder(conn, videos, now=NOW)

    assert folders(conn) == [outer]
    rows = conn.execute("SELECT folder_id FROM files").fetchall()
    assert [row["folder_id"] for row in rows] == [outer.id]  # the episode kept what Maku knew


def test_a_folder_that_isnt_there_is_refused(conn: sqlite3.Connection, tmp_path: Path):
    missing = tmp_path / "Not here"

    with pytest.raises(FolderError) as raised:
        add_folder(conn, missing, now=NOW)

    assert str(raised.value) == (
        f"{missing} isn't there. Check the drive is connected and the folder exists."
    )


def test_a_scan_finds_every_video_and_passes_over_the_rest(conn: sqlite3.Connection, videos: Path):
    folder = add_folder(conn, videos, now=NOW)

    found = find_files(conn, folder, stamp=STAMP)

    assert found is not None
    assert (found.files, found.added, found.gone) == (3, 3, 0)
    assert paths_in(conn) == {
        "The Harbour Line - S01E01 - Pilot.mkv",
        "Northern Lights 2004.avi",
        "Glass.Orchard.S01E01.720p.HDTV.x264-GRP.MKV",
    }


def test_a_rescan_reads_only_what_changed(conn: sqlite3.Connection, videos: Path):
    folder = add_folder(conn, videos, now=NOW)
    find_files(conn, folder, stamp=STAMP)
    for file_id, path in unread(conn):
        read_file(conn, file_id, path, lambda _: REPORT, now=NOW)
    episode = videos / "The Harbour Line" / "The Harbour Line - S01E01 - Pilot.mkv"
    episode.write_bytes(b"episode one, replaced by a better copy")

    found = find_files(conn, folder, stamp="2026-10-12T09:30:00+00:00")

    assert found is not None
    assert (found.added, found.changed) == (0, 1)
    assert [path.name for _, path in unread(conn)] == [episode.name]


def test_files_that_disappear_are_marked_gone_and_come_back(conn: sqlite3.Connection, videos: Path):
    folder = add_folder(conn, videos, now=NOW)
    find_files(conn, folder, stamp=STAMP)
    movie = videos / "Northern Lights 2004.avi"
    kept = movie.read_bytes()
    movie.unlink()

    found = find_files(conn, folder, stamp="2026-10-12T09:30:00+00:00")
    assert found is not None
    assert found.gone == 1
    assert paths_in(conn, gone=True) == {movie.name}

    movie.write_bytes(kept)
    find_files(conn, folder, stamp="2026-10-13T09:30:00+00:00")
    assert paths_in(conn, gone=True) == set()


def test_an_unplugged_drive_leaves_its_files_as_they_were(conn: sqlite3.Connection, videos: Path):
    folder = add_folder(conn, videos, now=NOW)
    find_files(conn, folder, stamp=STAMP)
    videos.rename(videos.with_name("Videos (unplugged)"))

    found = find_files(conn, folder, stamp="2026-10-12T09:30:00+00:00")

    assert found is None
    assert paths_in(conn, gone=True) == set()


def test_reading_keeps_ffprobes_report_and_the_picture_at_a_glance(
    conn: sqlite3.Connection, videos: Path
):
    folder = add_folder(conn, videos, now=NOW)
    find_files(conn, folder, stamp=STAMP)

    for file_id, path in unread(conn):
        assert read_file(conn, file_id, path, lambda _: REPORT, now=NOW) is None

    assert unread(conn) == []
    row = conn.execute("SELECT * FROM files LIMIT 1").fetchone()
    assert (row["codec"], row["width"], row["height"]) == ("hevc", 720, 540)
    assert row["duration"] == pytest.approx(1244.2, abs=0.01)
    assert row["probed_at"] == STAMP


def test_a_file_that_cant_be_read_says_why_and_isnt_read_again(
    conn: sqlite3.Connection, videos: Path
):
    def damaged(path: Path) -> Json:
        raise ProbeError("Maku couldn't read it (Invalid data). It may be damaged, or not a video.")

    folder = add_folder(conn, videos, now=NOW)
    find_files(conn, folder, stamp=STAMP)
    [(file_id, path), *_] = unread(conn)

    problem = read_file(conn, file_id, path, damaged, now=NOW)

    assert problem == "Maku couldn't read it (Invalid data). It may be damaged, or not a video."
    assert file_id not in {each for each, _ in unread(conn)}


def test_removing_a_folder_forgets_its_files_and_touches_nothing(
    conn: sqlite3.Connection, videos: Path
):
    folder = add_folder(conn, videos, now=NOW)
    find_files(conn, folder, stamp=STAMP)

    assert remove_folder(conn, folder.id)

    assert folders(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
    assert (videos / "Northern Lights 2004.avi").exists()
    assert not remove_folder(conn, folder.id)


def junction(link: Path, target: Path) -> None:
    """A Windows junction, which a scan must never walk into."""
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],  # noqa: S607
        check=True,
        capture_output=True,
    )


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows'")
def test_a_scan_doesnt_walk_through_junctions(conn: sqlite3.Connection, videos: Path):
    junction(videos / "The Harbour Line" / "Loop back", videos)  # would go round for ever
    folder = add_folder(conn, videos, now=NOW)

    found = find_files(conn, folder, stamp=STAMP)

    assert found is not None
    assert found.files == 3


def test_a_folder_that_cant_be_opened_keeps_its_files(
    conn: sqlite3.Connection, videos: Path, monkeypatch: pytest.MonkeyPatch
):
    folder = add_folder(conn, videos, now=NOW)
    find_files(conn, folder, stamp=STAMP)
    real = os.scandir

    def denied(path: str | os.PathLike[str]) -> object:
        if Path(path).name == "Downloads":
            raise PermissionError(13, "Access is denied")
        return real(path)

    monkeypatch.setattr("maku.library.os.scandir", denied)

    found = find_files(conn, folder, stamp="2026-10-12T09:30:00+00:00")

    assert found is not None
    assert found.gone == 0
    assert found.problems == (f"Maku couldn't look in {videos / 'Downloads'}: Access is denied.",)
    assert paths_in(conn, gone=True) == set()


def test_a_folder_forgotten_while_it_is_walked_stops_the_walk_cleanly(
    conn: sqlite3.Connection, videos: Path
):
    folder = add_folder(conn, videos, now=NOW)

    def forget(path: Path) -> None:
        conn.execute("DELETE FROM folders WHERE id = ?", (folder.id,))

    assert find_files(conn, folder, stamp=STAMP, on_file=forget) is None
