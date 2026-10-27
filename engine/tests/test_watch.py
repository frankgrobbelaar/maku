"""Keeping the library current while Maku is open: catching up, watching, refreshing lists."""

import json
import shutil
import sqlite3
import time
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from watchdog.events import (
    DirCreatedEvent,
    DirModifiedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
)
from watchdog.observers import winapi

from maku.config import DataPaths
from maku.library import add_folder
from maku.scan import ScanBusyError, ScanStatus, State
from maku.tmdb import API as TMDB
from maku.watch import QUIET, TICK, Changes, Watcher, observe
from tests.fake_web import FakeWeb, reply
from tests.services import internet, with_key
from tests.shelf import NOW, identify, library


class Scans:
    """A scanner that only counts the scans it's asked for."""

    def __init__(self, state: State = "done") -> None:
        self.state: State = state
        self.started = 0
        self.busy = False
        self.maku_moving = False

    def start(self) -> ScanStatus:
        if self.busy:
            raise ScanBusyError
        self.started += 1
        return self.status()

    def status(self) -> ScanStatus:
        return ScanStatus(self.state, None, None, None, 0, 0, 0, 0, None, None, (), None)

    def moving(self) -> bool:
        return self.maku_moving


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def scans() -> Scans:
    return Scans()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def watcher(paths: DataPaths, scans: Scans, clock: Clock) -> Iterator[Watcher]:
    found = Watcher(paths, scans, FakeWeb(), now=lambda: NOW, clock=clock)
    yield found
    found.stop()


def set_up(conn: sqlite3.Connection, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    add_folder(conn, folder, now=NOW)
    with conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('set_up', ?)", (json.dumps(True),))


def test_at_start_a_scan_catches_up(
    watcher: Watcher, scans: Scans, conn: sqlite3.Connection, tmp_path: Path
):
    set_up(conn, tmp_path / "Videos")

    assert watcher.catch_up()
    assert scans.started == 1


def test_no_catching_up_before_setup_or_while_a_scan_is_paused(
    watcher: Watcher, scans: Scans, conn: sqlite3.Connection, tmp_path: Path
):
    assert not watcher.catch_up()  # setup isn't done

    set_up(conn, tmp_path / "Videos")
    scans.state = "paused"
    assert not watcher.catch_up()
    assert scans.started == 0


def test_a_change_starts_a_scan_once_the_folder_is_quiet(
    watcher: Watcher, scans: Scans, clock: Clock, conn: sqlite3.Connection
):
    watcher.notice()

    watcher.tick()
    assert scans.started == 0  # still settling: a season may be copying

    clock.now += QUIET
    watcher.tick()
    assert scans.started == 1

    watcher.tick()
    assert scans.started == 1  # once per change


def test_a_change_starts_a_scan_within_moments_of_the_folder_going_quiet(
    watcher: Watcher, scans: Scans, clock: Clock, conn: sqlite3.Connection, tmp_path: Path
):
    set_up(conn, tmp_path / "Videos")
    watcher.start()  # catches up, then watches
    assert scans.started == 1

    watcher.notice()
    clock.now += QUIET  # and the folder has been quiet since

    assert wait_for(lambda: scans.started == 2)  # not a whole look-around later


def test_a_change_waiting_on_a_paused_scan_isnt_looked_at_every_second(
    watcher: Watcher, scans: Scans, clock: Clock, conn: sqlite3.Connection
):
    watcher.notice()
    assert watcher.settling  # looked at every second till the folder is quiet

    clock.now += QUIET
    scans.state = "paused"
    watcher.tick()

    assert watcher.pending  # it waits for the owner to resume
    assert not watcher.settling  # and is looked at again with everything else, not every second
    assert scans.started == 0


def test_episode_lists_are_looked_at_while_a_folder_keeps_changing_but_not_every_second(
    watcher: Watcher,
    scans: Scans,
    clock: Clock,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
):
    refreshed: list[float] = []
    monkeypatch.setattr(watcher, "refresh", lambda: refreshed.append(clock.now) or 0)
    watcher.notice()  # a long copy: the folder keeps changing

    for _ in range(4):
        watcher.tick()
        clock.now += 1
        watcher.notice()
    clock.now += TICK
    watcher.notice()  # still copying
    watcher.tick()

    assert refreshed == [100.0, 100.0 + 4 + TICK]  # at once, then a look-around later


def test_files_maku_moves_itself_start_no_scan(
    watcher: Watcher, scans: Scans, clock: Clock, conn: sqlite3.Connection
):
    scans.maku_moving = True  # a tidy-up, or a converted file taking its original's place

    watcher.notice()
    clock.now += QUIET
    watcher.tick()

    assert scans.started == 0


def test_a_busy_scanner_gets_the_change_on_a_later_tick(
    watcher: Watcher, scans: Scans, clock: Clock, conn: sqlite3.Connection
):
    watcher.notice()
    clock.now += QUIET
    scans.busy = True

    watcher.tick()
    scans.busy = False
    watcher.tick()

    assert scans.started == 1


def test_a_change_while_the_owner_paused_the_scan_waits(
    watcher: Watcher, scans: Scans, clock: Clock, conn: sqlite3.Connection
):
    scans.state = "paused"
    watcher.notice()
    clock.now += QUIET

    watcher.tick()

    assert scans.started == 0


def test_what_cant_be_told_of_today_keeps_nothing_waiting(
    conn: sqlite3.Connection, watcher: Watcher, monkeypatch: pytest.MonkeyPatch
):
    def busy(*_: object) -> list[object]:
        raise sqlite3.OperationalError("database is locked")

    def told(title: str, body: str, *, link: str | None = None) -> None:
        raise AssertionError(title)

    monkeypatch.setattr("maku.watch.coming.out_today", busy)
    asked: list[bool] = []
    monkeypatch.setattr(watcher, "refresh", lambda: asked.append(True) or 0)
    monkeypatch.setattr(watcher, "_notify", told)

    watcher.tick()

    assert asked == [True]


def test_a_new_video_in_a_watched_folder_is_noticed(
    watcher: Watcher, scans: Scans, clock: Clock, conn: sqlite3.Connection, tmp_path: Path
):
    folder = tmp_path / "Videos"
    set_up(conn, folder)
    watcher.tick()  # starts watching the folder
    time.sleep(0.5)  # Windows takes a moment to start telling

    (folder / "Glass Orchard - S01E01.mkv").write_bytes(b"new")
    for _ in range(50):  # Windows tells the watcher within moments
        if watcher.pending:
            break
        time.sleep(0.1)
    time.sleep(0.5)  # "created" comes with "modified" just after; both count
    clock.now += QUIET
    watcher.tick()

    assert scans.started == 1


def wait_for(happened: Callable[[], bool]) -> bool:
    """Windows tells the watcher within moments."""
    for _ in range(50):
        if happened():
            return True
        time.sleep(0.1)
    return False


def test_a_folder_of_videos_moved_out_of_the_library_is_noticed(
    watcher: Watcher, conn: sqlite3.Connection, tmp_path: Path
):
    folder = tmp_path / "Videos"
    set_up(conn, folder)
    library(conn, folder, ["Glass Orchard (2012)/Glass Orchard - S01E01.mkv"])
    watcher.tick()
    time.sleep(0.5)

    (folder / "Glass Orchard (2012)").rename(tmp_path / "Elsewhere")

    assert wait_for(lambda: watcher.pending)


def test_a_folder_that_comes_back_is_watched_again(
    watcher: Watcher, scans: Scans, clock: Clock, conn: sqlite3.Connection, tmp_path: Path
):
    folder = tmp_path / "Videos"
    set_up(conn, folder)
    watcher.tick()
    time.sleep(0.5)
    shutil.rmtree(folder)  # its drive unplugged, say
    time.sleep(0.5)
    watcher.tick()
    folder.mkdir()
    watcher.tick()
    clock.now += QUIET
    watcher.tick()  # a scan for whatever changed while it was away
    assert scans.started == 1
    assert not watcher.pending
    time.sleep(0.5)

    (folder / "Glass Orchard - S01E01.mkv").write_bytes(b"new")

    assert wait_for(lambda: watcher.pending)


def test_a_folder_that_goes_has_its_handle_closed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # watchdog closes a folder's handle itself when the folder goes, and again when it's
    # stopped: by then the number may be another file's (the database's), and closing that
    # crashed the engine.
    closed: list[object] = []

    def closing(handle: Any) -> None:
        closed.append(handle)
        winapi.close_directory_handle(handle)

    monkeypatch.setattr("watchdog.observers.read_directory_changes.close_directory_handle", closing)
    folder = tmp_path / "Videos"
    folder.mkdir()
    observer = observe(str(folder), Changes(lambda: None, holds=lambda _path: True))
    time.sleep(0.3)

    shutil.rmtree(folder)  # its drive unplugged, say
    assert wait_for(lambda: bool(closed))
    observer.stop()
    observer.join(timeout=5)

    assert len(closed) == 1


def test_what_counts_as_a_change_to_the_library():
    show = r"D:\Videos\Glass Orchard (2012)"
    video = rf"{show}\Glass Orchard - S01E01.mkv"
    noticed: list[bool] = []
    changes = Changes(lambda: noticed.append(True), holds=lambda path: path in (show, video))

    def counts(event: FileSystemEvent) -> bool:
        noticed.clear()
        changes.on_any_event(event)
        return bool(noticed)

    assert counts(FileCreatedEvent(rf"{show}\Glass Orchard - S01E02.mkv"))
    assert counts(FileModifiedEvent(video))  # still copying
    assert counts(FileMovedEvent(video, rf"{show}\Glass Orchard - S01E01 (old).mkv"))
    assert counts(DirCreatedEvent(r"D:\Videos\Quiet Hours"))  # a folder moved in
    assert counts(FileDeletedEvent(show))  # how Windows tells of a folder moved out or deleted
    assert counts(FileDeletedEvent(video))
    assert not counts(DirModifiedEvent(show))  # something written in it, Maku's report say
    assert not counts(FileCreatedEvent(rf"{show}\Maku - Gap analysis.md"))
    assert not counts(FileDeletedEvent(r"D:\Videos\Downloads\old.part"))  # never in the library


def test_files_that_arent_videos_go_unnoticed(
    watcher: Watcher, scans: Scans, clock: Clock, conn: sqlite3.Connection, tmp_path: Path
):
    folder = tmp_path / "Videos"
    set_up(conn, folder)
    watcher.tick()
    time.sleep(0.5)

    (folder / "notes.txt").write_text("not a video", encoding="utf-8")
    time.sleep(1)

    assert not watcher.pending


def test_episode_lists_are_asked_for_again_when_due(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path, clock: Clock
):
    with_key(paths)
    library(conn, tmp_path / "Videos", ["Glass Orchard (2012)/Glass Orchard - S01E01.mkv"], 45)
    identify(paths, conn, internet())
    web = internet()

    soon = Watcher(paths, Scans(), web, now=lambda: NOW + timedelta(days=1), clock=clock)
    assert soon.refresh() == 0  # a finished show waits a week
    later = Watcher(paths, Scans(), web, now=lambda: NOW + timedelta(days=8), clock=clock)
    assert later.refresh() == 1

    assert f"GET {TMDB}/tv/4102" in web.paths()
    report = tmp_path / "Videos" / "Glass Orchard (2012)" / "Maku - Gap analysis.md"
    assert report.exists()


def test_a_show_still_airing_is_asked_about_every_hour(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path, clock: Clock
):
    with_key(paths)
    library(conn, tmp_path / "Videos", ["The Harbour Line/The Harbour Line - S03E01.mkv"], 45)
    identify(paths, conn, internet())
    web = internet()

    first = Watcher(paths, Scans(), web, now=lambda: NOW + timedelta(hours=2), clock=clock)
    second = Watcher(paths, Scans(), web, now=lambda: NOW + timedelta(hours=4), clock=clock)

    assert (first.refresh(), second.refresh()) == (1, 1)
    assert web.paths().count(f"GET {TMDB}/tv/4101") == 4  # each time: the show, then its seasons


def test_a_title_whose_files_all_went_isnt_asked_about(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path, clock: Clock
):
    with_key(paths)
    library(conn, tmp_path / "Videos", ["The Harbour Line/The Harbour Line - S03E01.mkv"], 45)
    identify(paths, conn, internet())
    with conn:
        conn.execute("UPDATE files SET gone_at = ?", (NOW.isoformat(),))
    web = internet()

    later = Watcher(paths, Scans(), web, now=lambda: NOW + timedelta(days=8), clock=clock)

    assert later.refresh() == 0
    assert web.asked == []


def test_without_a_key_no_list_is_asked_for(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path, clock: Clock
):
    with_key(paths)
    library(conn, tmp_path / "Videos", ["Glass Orchard (2012)/Glass Orchard - S01E01.mkv"], 45)
    identify(paths, conn, internet())
    (paths.root / "credentials.json").unlink()
    web = internet()

    later = Watcher(paths, Scans(), web, now=lambda: NOW + timedelta(days=8), clock=clock)

    assert (later.refresh(), later.look_further()) == (0, 0)
    assert web.asked == []


def test_offline_the_lists_wait_for_the_next_hour(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path, clock: Clock
):
    with_key(paths)
    library(conn, tmp_path / "Videos", ["Glass Orchard (2012)/Glass Orchard - S01E01.mkv"], 45)
    identify(paths, conn, internet())
    offline = internet()
    offline.offline = True

    later = Watcher(paths, Scans(), offline, now=lambda: NOW + timedelta(days=8), clock=clock)

    assert later.refresh() == 0
    asked = len(offline.asked)
    assert later.refresh() == 0  # the next look around, 15 seconds on
    assert len(offline.asked) == asked


def test_a_show_gone_from_tmdb_waits_until_its_next_due(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path, clock: Clock
):
    with_key(paths)
    library(conn, tmp_path / "Videos", ["Glass Orchard (2012)/Glass Orchard - S01E01.mkv"], 45)
    identify(paths, conn, internet())
    gone = internet()
    del gone.answers[f"GET {TMDB}/tv/4102"]  # TMDB answers 404

    later = Watcher(paths, Scans(), gone, now=lambda: NOW + timedelta(days=8), clock=clock)

    assert later.refresh() == 0
    asked = len(gone.asked)
    assert later.refresh() == 0
    assert len(gone.asked) == asked


def test_a_look_around_looks_further_into_the_collections_too(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path, clock: Clock
):
    with_key(paths)
    library(conn, tmp_path / "Videos", ["Movies/Starfall (2008).mkv"], minutes=118)
    identify(paths, conn, internet())
    web = internet()
    watcher = Watcher(paths, Scans(), web, now=lambda: NOW, clock=clock)
    try:
        watcher.tick()
    finally:
        watcher.stop()

    films = [path for path in web.paths() if "/movie/" in path]
    assert sorted(films) == [f"GET {TMDB}/movie/{n}" for n in (7102, 7103, 7104)]
    assert watcher.look_further() == 0  # none is due again yet


def test_a_change_waiting_for_its_scan_never_waits_on_tmdb(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path, clock: Clock
):
    with_key(paths)
    library(conn, tmp_path / "Videos", ["Movies/Starfall (2008).mkv"], minutes=118)
    identify(paths, conn, internet())
    web = internet()
    watcher = Watcher(paths, Scans(), web, now=lambda: NOW, clock=clock)
    watcher.notice()  # a video added, its folder not quiet yet
    try:
        watcher.tick()
    finally:
        watcher.stop()

    assert web.asked == []


def test_a_refused_key_rests_the_look_ups_for_an_hour(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path, clock: Clock
):
    with_key(paths)
    library(conn, tmp_path / "Videos", ["Movies/Starfall (2008).mkv"], minutes=118)
    identify(paths, conn, internet())
    web = internet()
    web.answers[f"GET {TMDB}/movie/7102"] = reply({"status_message": "Refused."}, 401)
    watcher = Watcher(paths, Scans(), web, now=lambda: NOW, clock=clock)

    assert watcher.look_further() == 0
    asked = len(web.asked)
    assert watcher.look_further() == 0  # the next look around, 15 seconds on
    assert len(web.asked) == asked


def test_offline_the_rest_of_a_collection_waits_for_the_next_hour(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path, clock: Clock
):
    with_key(paths)
    library(conn, tmp_path / "Videos", ["Movies/Starfall (2008).mkv"], minutes=118)
    identify(paths, conn, internet())
    offline = internet()
    offline.offline = True
    watcher = Watcher(paths, Scans(), offline, now=lambda: NOW, clock=clock)

    assert watcher.look_further() == 0
    asked = len(offline.asked)
    assert watcher.look_further() == 0  # the next look around, 15 seconds on
    assert len(offline.asked) == asked


def test_a_films_facts_are_looked_up_again_weekly(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path, clock: Clock
):
    with_key(paths)
    library(conn, tmp_path / "Videos", ["Movies/Starfall (2008).mkv"], minutes=118)
    identify(paths, conn, internet())
    web = internet()

    later = Watcher(paths, Scans(), web, now=lambda: NOW + timedelta(days=8), clock=clock)

    assert later.refresh() == 1
    assert f"GET {TMDB}/movie/7101" in web.paths()
