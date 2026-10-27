"""The scan job: find every video, read each one, pause, and carry on after an exit."""

import itertools
import json
import os
import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

import maku.scan
from maku import db
from maku.config import DataPaths
from maku.core.library import work_of
from maku.core.media import Json
from maku.history import scans
from maku.library import Folder, Found, add_folder
from maku.probe import ProbeError, ProbeToolError
from maku.scan import ScanBusyError, Scanner
from maku.tools import Tools, manifest
from tests.fake_ffprobe import REPORT
from tests.fake_web import FakeWeb
from tests.services import internet, with_key

NOW = datetime(2026, 10, 11, 9, 30, tzinfo=UTC)
NO_KEY = "Maku needs your TMDB key to find series and films: add it in Settings."


def reads(path: Path) -> Json:
    return REPORT


def timed(path: Path) -> Json:
    """ffprobe's report, as long as the video is: a film (the AVI) 97 minutes, an episode 45."""
    minutes = 97 if path.suffix == ".avi" else 45
    format_ = cast("dict[str, object]", REPORT["format"])
    return {**REPORT, "format": {**format_, "duration": str(minutes * 60)}}


_SECONDS = itertools.count(1)  # one clock for every scanner, so a later scan starts later


def scanner(
    paths: DataPaths,
    read: Callable[[Path], Json] | None = reads,
    tools: Tools | None = None,
    web: FakeWeb | None = None,
) -> Scanner:
    """A scanner whose clock moves on a second each time it's read. Nothing it asks of TMDB is
    answered unless `web` says so."""
    return Scanner(
        paths,
        tools or Tools(paths, items=()),
        read=read,
        now=lambda: NOW + timedelta(seconds=next(_SECONDS)),
        transport=web or FakeWeb(),
    )


def installed_ffmpeg(paths: DataPaths) -> Tools:
    """Maku's tools with ffmpeg downloaded and unpacked, as after setup."""
    ffmpeg = next(item for item in manifest() if item.id == "ffmpeg")
    folder = paths.tools / "ffmpeg"
    folder.mkdir(parents=True)
    program = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    (folder / program).write_bytes(b"probe")
    marker = {"version": ffmpeg.version, "sha256": ffmpeg.sha256, "files": [program]}
    (folder / "maku-download.json").write_text(json.dumps(marker), encoding="utf-8")
    tools = Tools(paths, items=(ffmpeg,))
    assert tools.path("ffprobe") == folder / program
    return tools


def finished(scan: Scanner) -> None:
    scan.wait(timeout=10)


def test_a_scan_finds_and_reads_every_video(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    add_folder(conn, videos, now=NOW)
    scan = scanner(paths)

    scan.start()
    finished(scan)

    status = scan.status()
    assert (status.state, status.stage) == ("done", "done")
    assert (status.found, status.to_read, status.read, status.problems) == (3, 3, 3, 0)
    assert status.finished_at is not None
    assert status.unavailable == ()


def test_a_second_scan_reads_only_new_files(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    add_folder(conn, videos, now=NOW)
    scan = scanner(paths)
    scan.start()
    finished(scan)
    (videos / "The Harbour Line" / "The Harbour Line - S01E02 - Low Tide.mkv").write_bytes(b"new")

    scan.start()
    finished(scan)

    status = scan.status()
    assert (status.found, status.to_read, status.read) == (4, 1, 1)


def test_a_scan_says_what_it_found_new_and_gone(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    add_folder(conn, videos, now=NOW)
    scan = scanner(paths)
    scan.start()
    finished(scan)
    assert (scan.status().added, scan.status().gone) == (3, 0)
    scan.start()
    finished(scan)
    assert (scan.status().added, scan.status().gone) == (0, 0)  # nothing changed

    next(videos.rglob("*.mkv")).unlink()
    (videos / "The Harbour Line" / "The Harbour Line - S01E02 - Low Tide.mkv").write_bytes(b"new")
    scan.start()
    finished(scan)

    status = scan.status()
    assert (status.found, status.added, status.gone) == (3, 1, 1)
    latest, *_ = scans(conn)
    assert (latest.added, latest.gone) == (1, 1)  # History keeps it


def test_a_video_that_comes_back_counts_as_new_again(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    add_folder(conn, videos, now=NOW)
    scan = scanner(paths)
    scan.start()
    finished(scan)
    video = next(videos.rglob("*.mkv"))
    away = videos.parent / video.name
    video.rename(away)
    scan.start()
    finished(scan)
    assert (scan.status().added, scan.status().gone) == (0, 1)

    away.rename(video)
    scan.start()
    finished(scan)

    assert (scan.status().added, scan.status().gone) == (1, 0)


def test_a_scan_from_before_maku_counted_says_nothing_of_its_changes(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    add_folder(conn, videos, now=NOW)
    scan = scanner(paths)
    scan.start()
    finished(scan)
    with conn:
        conn.execute("UPDATE scans SET added = NULL, gone = NULL")  # as an older Maku left it

    assert (scan.status().added, scan.status().gone) == (None, None)


def test_files_that_cant_be_read_are_counted(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    def picky(path: Path) -> Json:
        if path.suffix == ".avi":
            raise ProbeError(
                "Maku couldn't read it (Invalid data). It may be damaged, or not a video."
            )
        return REPORT

    add_folder(conn, videos, now=NOW)
    scan = scanner(paths, picky)
    scan.start()
    finished(scan)

    assert scan.status().problems == 1


def test_pausing_stops_between_files_and_resuming_carries_on(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    reading, go_on = threading.Event(), threading.Event()

    def slow(path: Path) -> Json:
        reading.set()
        go_on.wait(10)
        return REPORT

    add_folder(conn, videos, now=NOW)
    scan = scanner(paths, slow)
    scan.start()
    assert reading.wait(10)

    scan.pause()
    go_on.set()
    finished(scan)
    paused = scan.status()
    assert (paused.state, paused.stage, paused.read) == ("paused", "reading", 1)

    scan.resume()
    finished(scan)
    done = scan.status()
    assert (done.state, done.read, done.to_read) == ("done", 3, 3)


def test_a_scan_stopped_by_an_exit_carries_on_at_the_next_start(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    add_folder(conn, videos, now=NOW)
    with conn:
        conn.execute(
            "INSERT INTO scans (started_at, state, stage) VALUES (?, 'running', 'finding')",
            (NOW.isoformat(),),
        )
    scan = scanner(paths)  # a fresh engine, after the exit

    scan.recover()
    finished(scan)

    status = scan.status()
    assert (status.state, status.found, status.read) == ("done", 3, 3)


def test_a_paused_scan_stays_paused_after_a_restart(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    add_folder(conn, videos, now=NOW)
    with conn:
        conn.execute(
            "INSERT INTO scans (started_at, state, stage) VALUES (?, 'paused', 'reading')",
            (NOW.isoformat(),),
        )
    scan = scanner(paths)

    scan.recover()

    assert scan.status().state == "paused"


def test_only_one_scan_runs_at_a_time(paths: DataPaths, conn: sqlite3.Connection, videos: Path):
    reading, go_on = threading.Event(), threading.Event()

    def slow(path: Path) -> Json:
        reading.set()
        go_on.wait(10)
        return REPORT

    add_folder(conn, videos, now=NOW)
    scan = scanner(paths, slow)
    scan.start()
    assert reading.wait(10)

    with pytest.raises(ScanBusyError):
        scan.start()
    go_on.set()
    finished(scan)


def test_without_ffmpeg_the_scan_says_what_to_do(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    add_folder(conn, videos, now=NOW)
    scan = scanner(paths, read=None)  # the real ffprobe, which hasn't been downloaded

    scan.start()
    finished(scan)

    status = scan.status()
    assert (status.state, status.found, status.read) == ("failed", 3, 0)
    assert status.problem == (
        "Maku needs ffmpeg to read the files it found. Download it, then scan again."
    )


def test_a_folder_on_an_unplugged_drive_is_named_and_the_rest_is_scanned(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path, tmp_path: Path
):
    other = tmp_path / "Other videos"
    other.mkdir()
    add_folder(conn, videos, now=NOW)
    add_folder(conn, other, now=NOW)
    other.rmdir()  # as if its drive were unplugged
    scan = scanner(paths)

    scan.start()
    finished(scan)

    status = scan.status()
    assert status.state == "done"
    assert status.unavailable == (str(other),)
    assert status.read == 3


def test_before_any_scan_there_is_nothing_to_report(paths: DataPaths, conn: sqlite3.Connection):
    status = scanner(paths).status()

    assert (status.state, status.stage, status.found) == ("idle", None, 0)


def test_a_broken_ffprobe_stops_the_scan_and_marks_no_file(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    def broken(path: Path) -> Json:
        raise ProbeToolError("ffprobe stopped with code 0xC0000135")

    add_folder(conn, videos, now=NOW)
    tools = installed_ffmpeg(paths)
    scan = scanner(paths, broken, tools)
    scan.start()
    finished(scan)

    status = scan.status()
    assert (status.state, status.read, status.problems) == ("failed", 0, 0)
    assert status.problem == (
        "ffprobe couldn't run (ffprobe stopped with code 0xC0000135), so Maku stopped the scan "
        "without marking any file. Get ffmpeg again in Setup, then scan again."
    )
    [(_, ffmpeg)] = tools.status()
    assert ffmpeg.state == "missing"  # so Setup offers to download it again

    again = scanner(paths)
    again.start()
    finished(again)
    assert (again.status().state, again.status().read) == ("done", 3)


def test_a_new_scan_tries_again_the_files_that_couldnt_be_read(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    def picky(path: Path) -> Json:
        if path.suffix == ".avi":
            raise ProbeError(
                "Maku couldn't read it (Invalid data). It may be damaged, or not a video."
            )
        return REPORT

    add_folder(conn, videos, now=NOW)
    first = scanner(paths, picky)
    first.start()
    finished(first)
    assert first.status().problems == 1

    second = scanner(paths)
    second.start()
    finished(second)

    status = second.status()
    assert (status.problems, status.to_read, status.read) == (0, 1, 1)


def test_a_folder_added_while_the_scan_is_finding_is_scanned_too(
    paths: DataPaths,
    conn: sqlite3.Connection,
    videos: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    more = tmp_path / "More videos"
    (more / "Quiet Hours").mkdir(parents=True)
    (more / "Quiet Hours" / "Quiet Hours - 03.mkv").write_bytes(b"three")
    add_folder(conn, videos, now=NOW)
    walk = maku.scan.find_files

    def while_walking(conn: sqlite3.Connection, folder: Folder, **options: Any) -> Found | None:
        if folder.path == videos:
            with closing(db.connect(paths.database)) as other:
                add_folder(other, more, now=NOW)
        return walk(conn, folder, **options)

    monkeypatch.setattr(maku.scan, "find_files", while_walking)
    scan = scanner(paths)
    scan.start()
    finished(scan)

    assert (scan.status().found, scan.status().read) == (4, 4)


def test_a_file_whose_folder_vanishes_mid_scan_is_left_for_the_next_one(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    show = videos / "The Harbour Line"  # its video is read last, in path order

    def moving_the_show(path: Path) -> Json:
        if show.exists():
            show.rename(videos / "The Harbour Line, moved")  # as if its drive dropped out
        return REPORT

    add_folder(conn, videos, now=NOW)
    scan = scanner(paths, moving_the_show)
    scan.start()
    finished(scan)

    row = conn.execute(
        "SELECT gone_at, probed_at FROM files WHERE path LIKE '%Pilot.mkv'"
    ).fetchone()
    assert (row["gone_at"], row["probed_at"]) == (None, None)


def test_a_scan_identifies_what_it_read(paths: DataPaths, conn: sqlite3.Connection, videos: Path):
    (videos / "Downloads" / "Mystery Show - S01E03.mkv").write_bytes(b"a show TMDB doesn't know")
    add_folder(conn, videos, now=NOW)
    scan = scanner(with_key(paths), timed, web=internet())

    scan.start()
    finished(scan)

    status = scan.status()
    assert (status.state, status.stage) == ("done", "done")
    # The Harbour Line, Glass Orchard and the film Northern Lights; Mystery Show waits.
    assert (status.titles, status.waiting, status.note) == (3, 1, None)


def test_without_a_tmdb_key_the_videos_wait_till_one_is_added(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    add_folder(conn, videos, now=NOW)
    web = internet()
    scan = scanner(paths, timed, web=web)

    scan.start()
    finished(scan)

    status = scan.status()
    assert (status.state, status.read, status.titles, status.waiting) == ("done", 3, 0, 0)
    assert status.note == NO_KEY
    assert web.asked == []

    with_key(paths)  # the owner adds one in Settings, and scans again
    scan.start()
    finished(scan)

    assert (scan.status().titles, scan.status().note) == (3, None)


def test_offline_a_scan_still_finishes_and_says_titles_wait(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    add_folder(conn, videos, now=NOW)
    offline = internet()
    offline.offline = True
    scan = scanner(with_key(paths), web=offline)

    scan.start()
    finished(scan)

    status = scan.status()
    assert status.state == "done"
    assert (status.note or "").startswith("Titles wait for the next scan: TMDB couldn't be asked")


def test_a_folder_holding_two_series_is_counted_as_mixed(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path
):
    root = tmp_path / "Library"
    for name in (
        "Downloads/The Harbour Line - S01E01.mkv",
        "Downloads/Glass Orchard - S01E01.mkv",
        "Glass Orchard/Glass Orchard - S01E02.mkv",
    ):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(name.encode())
    add_folder(conn, root, now=NOW)
    scan = scanner(with_key(paths), timed, web=internet())

    scan.start()
    finished(scan)

    status = scan.status()
    assert (status.titles, status.mixed) == (2, 1)  # Downloads holds both


def test_no_scan_starts_or_resumes_while_maku_moves_files(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    add_folder(conn, videos, now=NOW)
    with conn:
        conn.execute(
            "INSERT INTO scans (started_at, state, stage) VALUES (?, 'paused', 'reading')",
            (NOW.isoformat(),),
        )
    scan = scanner(paths)

    with scan.hold():
        with pytest.raises(ScanBusyError, match="Maku is moving files"):
            scan.start()
        with pytest.raises(ScanBusyError, match="Maku is moving files"):
            scan.resume()
        with pytest.raises(ScanBusyError, match="Maku is moving files"), scan.hold():
            pass

    scan.resume()
    finished(scan)
    assert scan.status().state == "done"


def test_files_never_move_while_a_scan_runs(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    reading, go_on = threading.Event(), threading.Event()

    def slow(path: Path) -> Json:
        reading.set()
        go_on.wait(10)
        return REPORT

    add_folder(conn, videos, now=NOW)
    scan = scanner(paths, slow)
    scan.start()
    assert reading.wait(10)

    with pytest.raises(ScanBusyError, match="A scan is running"), scan.hold():
        pass
    go_on.set()
    finished(scan)


def test_files_maku_moves_are_its_own_doing_till_a_moment_after(paths: DataPaths):
    moment = [0.0]
    scan = Scanner(paths, Tools(paths, items=()), clock=lambda: moment[0])

    assert scan.moving() is False
    with scan.hold():
        assert scan.moving() is True
    assert scan.moving() is True  # Windows tells of the moves a moment later

    moment[0] += 5
    assert scan.moving() is False


def test_a_scan_takes_away_results_no_conversion_is_waiting_with(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path
):
    root = tmp_path / "Videos"
    show = root / "Quiet Hours"
    show.mkdir(parents=True)
    for number in (1, 2):
        (show / f"Quiet Hours - 0{number}.mkv").write_bytes(b"an episode")
    add_folder(conn, root, now=NOW)
    scan = scanner(paths)
    scan.start()
    finished(scan)
    left = work_of(show / "Quiet Hours - 01.mkv")  # a skipped file's, its drive away then
    left.write_bytes(b"half a result")
    waiting = work_of(show / "Quiet Hours - 02.mkv")
    waiting.write_bytes(b"a result waiting for its player")
    second = conn.execute(
        "SELECT id FROM files WHERE path LIKE '%Quiet Hours - 02.mkv'"
    ).fetchone()[0]
    with conn:
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, added_at, retry_at)"
            " VALUES (?, 'best', 1, 'now', 'later')",
            (second,),
        )

    scan.start()
    finished(scan)

    assert not left.exists()
    assert waiting.exists()
