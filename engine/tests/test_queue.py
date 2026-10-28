"""The queue: files added in order, converted one at a time, paused, skipped, reordered, tried
again, put back, and settled after a crash; and English subtitles made in turn with them."""

import json
import sqlite3
import subprocess
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from maku import changes, hardware
from maku.changes import changes_of, save_plan
from maku.config import DataPaths
from maku.convert import WORKING, ConvertError, Programs, room_for, work_of
from maku.convert import room_for as converting_reckons
from maku.core.estimate import HEARING, Speeds
from maku.core.fields import Json
from maku.core.hardware import (
    BEST_WANTS_DIRECTX,
    BEST_WANTS_MEMORY,
    GIB,
    NO_ENCODER,
    Card,
    Checked,
)
from maku.core.media import media_from_ffprobe
from maku.core.plan import Change, ChangeKind, Plan
from maku.core.speech import Made, Segment
from maku.core.standard import Method, decide
from maku.hardware import Facts
from maku.history import plans
from maku.preferences import library_standard
from maku.queue import Queue, Room
from maku.scan import ScanBusyError, Scanner
from maku.tools import Tools
from tests.converting import TAG, open_elsewhere, programs, report
from tests.fake_web import FakeWeb
from tests.shelf import NOW, library

type Told = tuple[str, str, str | None]  # a notification: its title, its line, where it leads

RESULT = report(1920, 1080, tag=TAG)


@pytest.fixture
def shows(conn: sqlite3.Connection, tmp_path: Path) -> Path:
    """Three 1080p H.264 episodes of Glass Orchard, read."""
    root = tmp_path / "Videos"
    names = [
        f"Glass Orchard (2018)/Season 01/Glass Orchard (2018) - S01E0{n}.mkv" for n in (1, 2, 3)
    ]
    library(conn, root, names)
    with conn:
        conn.execute("UPDATE files SET probe = ?", (json.dumps(report(1920, 1080, codec="h264")),))
        conn.execute(
            "INSERT INTO titles (id, kind, name, year) VALUES (1, 'series', 'Glass Orchard', 2018)"
        )
        conn.execute("UPDATE files SET title_id = 1, season = 1, episode = id, matched = 'sure'")
    return root / "Glass Orchard (2018)" / "Season 01"


def make_queue(
    paths: DataPaths,
    kit: Programs | None = None,
    scanner: Scanner | None = None,
    told: list[Told] | None = None,
) -> Queue:
    """A queue on the test's data; what it tells the app (a notification: a title, a line and
    where in Maku it leads) goes into `told`."""
    clock = iter(range(1, 10_000))
    heard = told if told is not None else []
    return Queue(
        paths,
        scanner or Scanner(paths, Tools(paths, items=())),
        lambda: kit,
        now=lambda: NOW + timedelta(seconds=next(clock)),
        notify=lambda title, body, link=None: heard.append((title, body, link)),
    )


@pytest.fixture
def queue(paths: DataPaths, shows: Path) -> Iterator[Queue]:
    worker = make_queue(paths, programs(RESULT))
    yield worker
    worker.stop()


def states(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    return [tuple(row) for row in conn.execute("SELECT file_id, state FROM jobs ORDER BY id")]


def free_space(monkeypatch: pytest.MonkeyPatch, free: int) -> None:
    """Every drive has `free` bytes free."""

    def usage(path: object) -> SimpleNamespace:
        return SimpleNamespace(total=10**13, used=10**13 - free, free=free)

    monkeypatch.setattr("maku.convert.shutil.disk_usage", usage)


def room_of(conn: sqlite3.Connection, file_id: int) -> int:
    """The free space a file's result wants on its drive, as converting checks."""
    standard = library_standard(conn)
    row = conn.execute("SELECT probe FROM files WHERE id = ?", (file_id,)).fetchone()
    media = media_from_ffprobe(json.loads(row["probe"]))
    return room_for(media, decide(media, standard))


def two_hours(made: Json) -> Json:
    """ffprobe's report on a file, playing two hours instead."""
    longer = json.loads(json.dumps(made))
    longer["format"]["duration"] = "7200.0"
    return longer


def a_film(conn: sqlite3.Connection, file_id: int) -> None:
    """The file plays two hours, so its result takes five episodes' room."""
    with conn:
        conn.execute(
            "UPDATE files SET probe = ? WHERE id = ?",
            (json.dumps(two_hours(report(1920, 1080, codec="h264"))), file_id),
        )


def test_files_join_in_order_and_once(queue: Queue, conn: sqlite3.Connection):
    assert queue.add([2, 1, 2]) == 2
    assert queue.add([1, 3]) == 1  # 1 is waiting already

    assert [job.file_id for job in queue.status().queued] == [2, 1, 3]
    assert {job.method for job in queue.status().queued} == {Method.REENCODE}


def test_each_file_gets_what_suits_it(queue: Queue, conn: sqlite3.Connection):
    in_mp4 = {**report(1920, 1080), "format": {"format_name": "mp4", "duration": "1440.0"}}
    with conn:  # the standard's picture already, in an MP4
        conn.execute("UPDATE files SET probe = ? WHERE id = 3", (json.dumps(in_mp4),))

    queue.add([1, 3])

    assert [job.method for job in queue.status().queued] == [Method.REENCODE, Method.REMUX]


def test_a_file_at_the_standard_by_the_time_its_shown_says_what_it_was_to_get(
    queue: Queue, conn: sqlite3.Connection
):
    queue.add([1])
    with conn:  # the standard changed since it joined: what it is now needs nothing
        conn.execute("UPDATE files SET probe = ? WHERE id = 1", (json.dumps(report(1920, 1080)),))

    [waiting] = queue.status().queued

    assert (waiting.method, waiting.gpu_seconds) == (Method.REENCODE, 0.0)


def test_a_file_at_the_standard_by_its_turn_is_passed_over_not_failed(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    told: list[Told] = []
    queue = make_queue(paths, programs(RESULT), told=told)
    queue.add([1])
    with conn:  # the standard changed since it joined: what it is now needs nothing
        conn.execute("UPDATE files SET probe = ? WHERE id = 1", (json.dumps(report(1920, 1080)),))

    assert queue.work_once() is True

    [passed] = queue.status().today
    assert (passed.state, passed.problem) == (
        "skipped",
        "It's at your standard now, so there's nothing to convert.",
    )
    with pytest.raises(LookupError):
        queue.mark_broken(passed.id)  # it isn't broken: nothing went wrong
    assert told == []  # nothing was converted, and nothing failed
    assert not (shows / "Glass Orchard (2018) - S01E01.mkv").read_text().startswith("converted")


def test_files_with_nothing_to_convert_are_passed_over(queue: Queue, conn: sqlite3.Connection):
    with conn:
        at_standard = report(1920, 1080)
        conn.execute("UPDATE files SET probe = ? WHERE id = 1", (json.dumps(at_standard),))
        conn.execute("UPDATE files SET problem = 'damaged' WHERE id = 2")

    assert queue.add([1, 2, 3]) == 1


def test_the_first_file_waiting_is_converted_and_listed_today(
    queue: Queue, conn: sqlite3.Connection, shows: Path
):
    queue.add([1, 2])

    assert queue.work_once() is True

    assert states(conn) == [(1, "done"), (2, "queued")]
    assert (shows / "Glass Orchard (2018) - S01E01.mkv").read_text().startswith("converted")
    status = queue.status()
    assert [job.label for job in status.today] == ["Glass Orchard · S01E01"]
    assert status.today[0].output_size is not None
    assert [job.label for job in status.queued] == ["Glass Orchard · S01E02"]
    assert status.gpu_seconds > 0


def test_a_file_that_fails_says_why_and_can_be_tried_again(
    queue: Queue, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    queue.add([1, 2])
    monkeypatch.setenv("MAKU_FAKE_FAIL", "encode")

    queue.work_once()

    [failed] = queue.status().today
    assert (failed.state, failed.problem) == (
        "failed",
        "ffmpeg couldn't convert it: hevc_nvenc: No capable devices found.",
    )
    queue.retry(failed.id)
    assert [job.file_id for job in queue.status().queued] == [2, 1]  # back in line, last


def test_a_failed_file_keeps_what_ffmpeg_said_and_can_be_marked_broken(
    queue: Queue, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    queue.add([1])
    monkeypatch.setenv("MAKU_FAKE_FAIL", "encode")
    queue.work_once()
    [failed] = queue.status().today
    assert failed.log is not None
    assert "hevc_nvenc: No capable devices found" in failed.log

    queue.mark_broken(failed.id)

    assert states(conn) == [(1, "skipped")]
    file = conn.execute("SELECT problem FROM files WHERE id = 1").fetchone()
    assert file["problem"] == failed.problem
    assert queue.add([1]) == 0  # broken: it isn't converted again
    with pytest.raises(LookupError):
        queue.mark_broken(failed.id)  # only a file that failed


def test_a_file_marked_broken_stays_so_through_scans_till_it_changes(
    queue: Queue,
    paths: DataPaths,
    shows: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
):
    queue.add([1])
    monkeypatch.setenv("MAKU_FAKE_FAIL", "encode")
    queue.work_once()
    [failed] = queue.status().today
    queue.mark_broken(failed.id)
    scanner = Scanner(
        paths,
        Tools(paths, items=()),
        read=lambda path: report(
            1920, 1080, codec="h264"
        ),  # ffprobe reads it fine: it's the picture
        transport=FakeWeb(),
    )

    scanner.start()
    scanner.wait(30)
    assert conn.execute("SELECT problem FROM files WHERE id = 1").fetchone()[0] == failed.problem

    (shows / "Glass Orchard (2018) - S01E01.mkv").write_bytes(b"a better copy, saved over it")
    scanner.start()
    scanner.wait(30)
    assert conn.execute("SELECT problem FROM files WHERE id = 1").fetchone()[0] is None


def test_a_paused_queue_converts_nothing_until_resumed(
    queue: Queue, paths: DataPaths, conn: sqlite3.Connection
):
    queue.add([1])
    queue.pause()

    assert queue.work_once() is False
    assert queue.status().paused is True
    assert make_queue(paths).status().paused is True  # it stays paused, after a restart too

    queue.resume()
    assert queue.work_once() is True


def converting(queue: Queue, monkeypatch: pytest.MonkeyPatch) -> threading.Thread:
    """Starts the first file converting slowly, and waits until its frames are flowing."""
    monkeypatch.setenv("MAKU_FAKE_SLOW", "1")
    worker = threading.Thread(target=queue.work_once)
    worker.start()
    for _ in range(200):
        running = queue.status().running
        if running is not None and running.stage == "converting":
            return worker
        threading.Event().wait(0.05)
    pytest.fail("The file never started converting")


def test_pausing_stops_the_file_and_puts_it_first_in_line(
    queue: Queue, conn: sqlite3.Connection, shows: Path, monkeypatch: pytest.MonkeyPatch
):
    original = (shows / "Glass Orchard (2018) - S01E01.mkv").read_bytes()
    queue.add([1, 2])
    worker = converting(queue, monkeypatch)

    queue.pause()
    worker.join(timeout=20)

    assert states(conn) == [(1, "queued"), (2, "queued")]
    assert [job.file_id for job in queue.status().queued] == [1, 2]
    assert (shows / "Glass Orchard (2018) - S01E01.mkv").read_bytes() == original
    assert not list(shows.glob(f"*{WORKING}"))


def test_skipping_the_file_converting_goes_on_to_the_next(
    queue: Queue, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    queue.add([1, 2])
    worker = converting(queue, monkeypatch)
    running = queue.status().running
    assert running is not None

    queue.skip(running.job.id)
    worker.join(timeout=20)

    assert states(conn) == [(1, "skipped"), (2, "queued")]


def owner_asks_while_checking(paths: DataPaths, ask: Callable[[Queue, int], None]) -> Queue:
    """A queue whose owner does `ask` (given the job's id) while a result is being checked."""
    queue: Queue | None = None

    def read(path: Path) -> Json:
        assert queue is not None
        running = queue.status().running
        assert running is not None
        assert running.stage == "checking"
        ask(queue, running.job.id)
        return RESULT

    queue = make_queue(paths, replace(programs(RESULT), read=read))
    return queue


def test_a_file_skipped_while_its_result_is_checked_isnt_put_in_place(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    episode = shows / "Glass Orchard (2018) - S01E01.mkv"
    original = episode.read_bytes()
    queue = owner_asks_while_checking(paths, Queue.skip)
    queue.add([1, 2])

    queue.work_once()

    assert states(conn) == [(1, "skipped"), (2, "queued")]
    assert episode.read_bytes() == original
    assert not list(shows.glob(f"*{WORKING}"))


def test_a_file_paused_while_its_result_is_checked_still_goes_in(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    queue = owner_asks_while_checking(paths, lambda queue, _job: queue.pause())
    queue.add([1, 2])

    queue.work_once()

    assert states(conn) == [(1, "done"), (2, "queued")]  # it was made: only the next waits
    assert queue.status().paused is True
    assert queue.work_once() is False


def test_a_file_paused_while_it_waits_for_a_scan_goes_in_once_the_scan_is_done(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("maku.queue._HOLD_RETRY", 0.05)
    scanner = Scanner(paths, Tools(paths, items=()))
    queue = make_queue(paths, programs(RESULT), scanner)
    queue.add([1])
    with scanner.hold():  # a scan running as the result is ready to go in
        worker = threading.Thread(target=queue.work_once)
        worker.start()
        for _ in range(200):
            running = queue.status().running
            if running is not None and running.stage == "replacing":
                break
            threading.Event().wait(0.05)
        queue.pause()
        worker.join(timeout=0.3)
        assert worker.is_alive()  # waiting for the scan, paused or not
    worker.join(timeout=20)

    assert states(conn) == [(1, "done")]


def test_files_waiting_can_be_skipped_moved_and_removed(queue: Queue, conn: sqlite3.Connection):
    queue.add([1, 2, 3])
    first, second, third = (job.id for job in queue.status().queued)

    queue.move(third, before=first)
    assert [job.file_id for job in queue.status().queued] == [3, 1, 2]
    queue.move(third, before=None)
    assert [job.file_id for job in queue.status().queued] == [1, 2, 3]

    queue.skip(second)
    queue.remove(third)

    assert states(conn) == [(1, "queued"), (2, "skipped")]
    with pytest.raises(LookupError):
        queue.remove(second)


def test_several_files_waiting_can_be_moved_and_removed_at_once(
    queue: Queue, conn: sqlite3.Connection
):
    queue.add([1, 2, 3])
    first, second, third = (job.id for job in queue.status().queued)

    assert queue.move_all([third, second], before=first) == 2  # together, in the order they wait
    assert [job.file_id for job in queue.status().queued] == [2, 3, 1]
    assert queue.move_all([second, 999], before=None) == 1  # one not waiting is passed over
    assert [job.file_id for job in queue.status().queued] == [3, 1, 2]
    assert queue.move_all([first, third], before=first) == 2  # before one of them: last
    assert [job.file_id for job in queue.status().queued] == [2, 3, 1]

    assert queue.remove_all([first, third, 999]) == 2
    assert states(conn) == [(2, "queued")]


def test_cancelling_all_takes_every_file_out_and_stops_the_one_converting(
    queue: Queue, conn: sqlite3.Connection, shows: Path, monkeypatch: pytest.MonkeyPatch
):
    original = (shows / "Glass Orchard (2018) - S01E01.mkv").read_bytes()
    queue.add([1, 2, 3])
    worker = converting(queue, monkeypatch)

    assert queue.cancel_all() == 3
    worker.join(timeout=20)

    assert states(conn) == [(1, "skipped")]  # it can be tried again from today's list
    assert queue.status().running is None
    assert not queue.status().queued
    assert (shows / "Glass Orchard (2018) - S01E01.mkv").read_bytes() == original
    assert not list(shows.glob(f"*{WORKING}"))


def test_cancelling_all_with_nothing_converting_takes_out_what_waits(
    queue: Queue, conn: sqlite3.Connection
):
    queue.add([1, 2])

    assert queue.cancel_all() == 2
    assert states(conn) == []
    assert queue.cancel_all() == 0


def test_without_ffmpeg_files_wait_and_the_queue_says_why(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    queue = make_queue(paths, None)
    queue.add([1])

    assert queue.work_once() is False

    assert queue.status().problem == (
        "Maku needs ffmpeg to convert. It's downloaded on the setup's Tools step."
    )
    assert states(conn) == [(1, "queued")]


def test_putting_back_an_original_waits_for_no_scan(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    scanner = Scanner(paths, Tools(paths, items=()))
    queue = make_queue(paths, programs(RESULT), scanner)
    queue.add([1])
    queue.work_once()
    [done] = queue.status().today

    with scanner.hold(), pytest.raises(ScanBusyError):
        queue.restore(done.id)

    queue.restore(done.id)

    assert states(conn) == [(1, "restored")]
    with pytest.raises(ConvertError):
        queue.restore(done.id)


def test_after_a_crash_a_file_converting_waits_again_and_its_result_goes(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    queue = make_queue(paths, programs(RESULT))
    queue.add([1])
    with conn:
        conn.execute("UPDATE jobs SET state = 'running'")
    unfinished = work_of(shows / "Glass Orchard (2018) - S01E01.mkv")
    unfinished.write_bytes(b"half made")

    settled = queue.recover()

    assert states(conn) == [(1, "queued")]
    assert not unfinished.exists()
    assert (settled.restarted, settled.finished, settled.put_back) == (1, 0, 0)


def test_at_start_a_copy_still_open_doesnt_keep_maku_from_starting(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    queue = make_queue(paths, programs(RESULT))
    queue.add([1])
    with conn:
        conn.execute("UPDATE jobs SET state = 'running'")

    def open_still(path: Path, missing_ok: bool = False) -> None:  # an ffmpeg a crash left
        raise PermissionError(13, "The process cannot access the file", str(path))

    monkeypatch.setattr(Path, "unlink", open_still)

    queue.recover()

    assert states(conn) == [(1, "queued")]


def test_after_a_crash_a_result_half_in_place_is_finished(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    queue = make_queue(paths, programs(RESULT))
    queue.add([1])
    episode = shows / "Glass Orchard (2018) - S01E01.mkv"
    renames = 0
    rename = Path.rename

    def stop_at_the_second(path: Path, target: Path) -> Path:
        nonlocal renames
        renames += 1
        if renames == 2:
            raise KeyboardInterrupt  # the engine stopping between the original and the result
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", stop_at_the_second)
    with pytest.raises(KeyboardInterrupt):
        queue.work_once()
    monkeypatch.undo()
    assert states(conn) == [(1, "replacing")]
    assert not episode.exists()  # the original set aside, the result not in place yet

    changes.recover(conn)  # at the next start, as the engine does
    settled = queue.recover()

    assert states(conn) == [(1, "done")]
    assert (settled.restarted, settled.finished, settled.put_back) == (0, 1, 0)
    assert episode.read_text().startswith("converted")
    plan = conn.execute("SELECT plan_id FROM jobs").fetchone()[0]
    assert [c.state.value for c in changes_of(conn, plan)] == ["done", "done"]


def test_on_nights_only_files_start_between_23_and_7(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    at = [NOW.replace(hour=12)]
    queue = Queue(
        paths, Scanner(paths, Tools(paths, items=())), lambda: programs(RESULT), now=lambda: at[0]
    )
    queue.add([1])
    queue.plan("nights")

    assert queue.work_once() is False
    assert (queue.status().schedule, queue.status().waits_for_night) == ("nights", True)

    at[0] = NOW.replace(hour=23, minute=30)
    assert queue.work_once() is True
    assert queue.status().waits_for_night is False


def test_stopping_at_three_takes_no_file_after_it_tonight_only(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    at = [
        (NOW + timedelta(days=1)).replace(hour=1, minute=0)
    ]  # 01:00, a night of the nights-only queue
    queue = Queue(
        paths, Scanner(paths, Tools(paths, items=())), lambda: programs(RESULT), now=lambda: at[0]
    )
    queue.add([1, 2, 3])
    queue.plan("nights")
    morning = at[0].replace(hour=7)
    assert (queue.status().ends_at, queue.status().early) == (morning.isoformat(), False)

    queue.stop_early(early=True)

    three = at[0].replace(hour=3)
    assert (queue.status().ends_at, queue.status().early) == (three.isoformat(), True)
    at[0] = three - timedelta(minutes=1)
    assert queue.work_once() is True  # one started before 03:00 goes, and finishes
    at[0] = three
    assert queue.work_once() is False  # none starts after
    assert queue.status().waits_for_night is True

    at[0] = three.replace(hour=23)  # the next night is a whole night again
    assert queue.status().ends_at == (morning + timedelta(days=1)).isoformat()
    assert queue.work_once() is True


def test_stopping_at_three_holds_though_the_clocks_change_that_night(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    summer, winter = timezone(timedelta(hours=2)), timezone(timedelta(hours=1))
    at = [datetime(2026, 10, 24, 23, 30, tzinfo=summer)]
    queue = Queue(
        paths, Scanner(paths, Tools(paths, items=())), lambda: programs(RESULT), now=lambda: at[0]
    )
    queue.add([1])
    queue.plan("nights")
    queue.stop_early(early=True)

    at[0] = datetime(2026, 10, 25, 2, 10, tzinfo=winter)  # the clocks went back at 03:00

    assert queue.status().early is True
    assert queue.work_once() is False  # 03:00 summer time has come and gone


def test_going_on_till_seven_undoes_stopping_early(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    at = [(NOW + timedelta(days=1)).replace(hour=2)]
    queue = Queue(
        paths, Scanner(paths, Tools(paths, items=())), lambda: programs(RESULT), now=lambda: at[0]
    )
    queue.add([1])
    queue.plan("nights")
    queue.stop_early(early=True)

    queue.stop_early(early=False)

    at[0] = at[0].replace(hour=4)
    assert (queue.status().early, queue.status().waits_for_night) == (False, False)
    assert queue.work_once() is True


def test_stopping_early_past_three_takes_no_file_after_the_one_converting(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    at = [(NOW + timedelta(days=1)).replace(hour=4, minute=10)]
    queue = Queue(
        paths, Scanner(paths, Tools(paths, items=())), lambda: programs(RESULT), now=lambda: at[0]
    )
    queue.add([1])
    queue.plan("nights")

    queue.stop_early(early=True)

    assert queue.status().ends_at == at[0].isoformat()
    assert queue.work_once() is False


def test_by_day_nothing_ends_tonight_yet(queue: Queue):
    queue.plan("nights")  # 09:30

    assert queue.status().ends_at is None


def test_a_file_on_a_drive_that_isnt_connected_waits_and_the_next_goes(
    queue: Queue, conn: sqlite3.Connection
):
    with conn:  # the first file's library folder is on a drive that's unplugged now
        conn.execute("INSERT INTO folders (path, added_at) VALUES ('Z:\\Videos', 'now')")
        conn.execute(
            "UPDATE files SET folder_id = 2, path = 'Z:\\Videos\\Orchard - 01.mkv' WHERE id = 1"
        )
    queue.add([1, 2])

    assert queue.work_once() is True

    assert states(conn) == [(1, "queued"), (2, "done")]
    [waiting] = queue.status().queued
    assert (waiting.file_id, waiting.drive_missing) == (1, True)
    assert queue.work_once() is False  # nothing else it can take


def test_a_full_drive_pauses_the_queue_and_says_what_it_needs(
    queue: Queue, conn: sqlite3.Connection, shows: Path, monkeypatch: pytest.MonkeyPatch
):
    queue.add([1, 2])
    free_space(monkeypatch, 10**6)  # a megabyte left

    assert queue.work_once() is True

    status = queue.status()
    assert states(conn) == [(1, "queued"), (2, "queued")]
    assert [job.file_id for job in status.queued] == [1, 2]  # still first in line
    assert status.paused is True
    assert status.problem is None  # the room it wants says it all
    assert status.room == Room(
        drive=shows.drive,
        paused=True,
        files=2,
        needed=room_of(conn, 1) + room_of(conn, 2),
        free=10**6,
        fit=0,
        set_aside=0,
    )

    queue.resume()  # the owner made room some other way

    assert queue.status().room is None


def test_converting_what_fits_passes_over_what_doesnt_and_goes_on(
    paths: DataPaths, conn: sqlite3.Connection, shows: Path, monkeypatch: pytest.MonkeyPatch
):
    def read(path: Path) -> Json:  # each result plays as long as its original
        return two_hours(RESULT) if "S01E01" in path.name else RESULT

    queue = make_queue(paths, replace(programs(RESULT), read=read))
    a_film(conn, 1)
    film, episode = room_of(conn, 1), room_of(conn, 2)
    original = (shows / "Glass Orchard (2018) - S01E02.mkv").stat().st_size
    queue.add([1, 2])
    free_space(monkeypatch, episode)  # room for the episode, not the film
    queue.work_once()
    assert queue.status().room == Room(shows.drive, True, 2, film + episode, episode, 1, 0)

    queue.convert_what_fits(shows.drive)
    queue.resume()

    assert queue.work_once() is True  # the episode goes
    assert states(conn) == [(1, "queued"), (2, "done")]
    status = queue.status()
    assert status.paused is False
    assert [(job.file_id, job.no_room) for job in status.queued] == [(1, True)]
    # Its original is in quarantine now: emptying it would make room too.
    assert status.room == Room(shows.drive, False, 1, film, episode, 0, original)

    assert queue.work_once() is False  # the film waits for room; the queue doesn't pause
    assert queue.status().paused is False

    free_space(monkeypatch, 10**12)
    assert queue.work_once() is True  # room at last
    assert states(conn) == [(1, "done"), (2, "done")]
    assert queue.status().room is None


@pytest.mark.parametrize(
    ("originals", "waiting_for_room"),
    [("quarantine", [False, True]), ("delete", [False, False])],
)
def test_a_drive_wants_room_for_every_result_unless_originals_are_deleted(
    queue: Queue,
    conn: sqlite3.Connection,
    shows: Path,
    monkeypatch: pytest.MonkeyPatch,
    originals: str,
    waiting_for_room: list[bool],
):
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('originals', ?)", (f'"{originals}"',)
        )
        conn.execute("UPDATE files SET size = 3000000000")  # originals bigger than their results
    free_space(monkeypatch, max(room_of(conn, 1), room_of(conn, 2)))  # room for one result

    queue.add([1, 2], fit=[shows.drive])

    assert [job.no_room for job in queue.status().queued] == waiting_for_room


def test_files_added_to_convert_what_fits_wait_for_room_without_pausing(
    queue: Queue, conn: sqlite3.Connection, shows: Path, monkeypatch: pytest.MonkeyPatch
):
    free_space(monkeypatch, 10**6)
    queue.work_once()  # the worker looks as the owner adds them: nothing waits yet

    queue.add([1, 2], fit=[shows.drive])

    assert queue.work_once() is False
    status = queue.status()
    assert status.paused is False
    assert [job.no_room for job in status.queued] == [True, True]


def test_paused_by_the_owner_files_waiting_for_room_say_nothing_of_it(
    queue: Queue, conn: sqlite3.Connection, shows: Path, monkeypatch: pytest.MonkeyPatch
):
    free_space(monkeypatch, 10**6)
    queue.add([1], fit=[shows.drive])

    queue.pause()

    status = queue.status()
    assert status.room is None  # the queue is paused: that's what it says
    assert [job.no_room for job in status.queued] == [False]


def mounted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The library folder is a full volume mounted into a drive that has plenty of room."""

    def usage(path: object) -> SimpleNamespace:
        free = 10**12 if str(path).rstrip("\\").endswith(":") else 10**6
        return SimpleNamespace(total=10**13, used=10**13 - free, free=free)

    monkeypatch.setattr("maku.convert.shutil.disk_usage", usage)


def test_room_is_measured_where_the_file_is_as_converting_measures_it(
    queue: Queue, conn: sqlite3.Connection, shows: Path, monkeypatch: pytest.MonkeyPatch
):
    mounted(monkeypatch)
    queue.add([1], fit=[shows.drive])

    assert queue.work_once() is False  # it waits for room, rather than failing to start
    status = queue.status()  # and says so
    assert status.room is not None
    assert status.room.free == 10**6
    assert [job.no_room for job in status.queued] == [True]


def test_a_mounted_volume_without_room_pauses_the_queue_and_says_why(
    queue: Queue, conn: sqlite3.Connection, shows: Path, monkeypatch: pytest.MonkeyPatch
):
    mounted(monkeypatch)
    queue.add([1])

    queue.work_once()

    status = queue.status()
    assert status.paused is True
    assert status.room is not None  # the card, with its ways on
    assert (status.room.paused, status.room.free) == (True, 10**6)


def test_what_a_removed_file_wanted_is_forgotten_though_its_number_comes_again(
    queue: Queue, conn: sqlite3.Connection, shows: Path, monkeypatch: pytest.MonkeyPatch
):
    free_space(monkeypatch, 10**9)  # room for an episode, not a film
    a_film(conn, 1)
    queue.add([1], fit=[shows.drive])

    def reckoned(*_: object) -> int:  # the queue reckons the film fits
        return 1

    monkeypatch.setattr("maku.queue.room_for", reckoned)
    queue.work_once()  # converting finds it doesn't
    monkeypatch.setattr("maku.queue.room_for", converting_reckons)
    [film] = queue.status().queued
    queue.remove(film.id)

    queue.add([2], fit=[shows.drive])  # an episode, which SQLite numbers as the film was

    [episode] = queue.status().queued
    assert episode.id == film.id
    assert queue.work_once() is True  # what the film wanted isn't held against it


def test_a_file_converting_finds_without_room_waits_rather_than_starting_again_and_again(
    queue: Queue, conn: sqlite3.Connection, shows: Path, monkeypatch: pytest.MonkeyPatch
):
    """Converting can want more room than the queue reckoned (a picture found interlaced is
    made anew, not copied): the file then waits for that much room."""
    free_space(monkeypatch, 10**6)
    queue.add([1], fit=[shows.drive])

    def reckoned(*_: object) -> int:  # the queue reckons it fits
        return 1

    monkeypatch.setattr("maku.queue.room_for", reckoned)

    assert queue.work_once() is True  # taken, and converting finds no room
    assert queue.work_once() is False  # it waits for room, not taken again at once
    status = queue.status()
    assert status.paused is False
    assert [job.no_room for job in status.queued] == [True]


def test_by_day_on_nights_only_files_waiting_for_room_wait_for_the_night_first(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    queue = make_queue(paths, programs(RESULT))
    free_space(monkeypatch, 10**6)
    queue.plan("nights")  # 09:30
    queue.add([1], fit=[shows.drive])

    status = queue.status()

    assert status.waits_for_night is True
    assert status.room is None  # the night comes first: that's what the queue says
    assert [job.no_room for job in status.queued] == [False]


def test_once_nothing_waits_for_room_a_full_drive_pauses_the_queue_again(
    queue: Queue, conn: sqlite3.Connection, shows: Path, monkeypatch: pytest.MonkeyPatch
):
    queue.add([1])
    free_space(monkeypatch, 10**6)
    queue.work_once()
    queue.convert_what_fits(shows.drive)
    queue.resume()
    free_space(monkeypatch, 10**12)
    assert queue.work_once() is True
    assert queue.work_once() is False  # nothing waits on it: converting what fits is over

    queue.add([2])
    free_space(monkeypatch, 10**6)
    queue.work_once()

    status = queue.status()
    assert status.paused is True  # asked again
    assert status.room is not None
    assert status.room.paused is True


def test_once_nothing_waits_the_batch_is_told_of(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    told: list[Told] = []
    queue = make_queue(paths, programs(RESULT), told=told)
    queue.add([1, 2])

    queue.work_once()
    assert told == []  # one still waits
    queue.work_once()

    [(title, body, link)] = told
    assert title == "Glass Orchard, season 1 is done"
    assert body.startswith("2 episodes · all checked · ")
    assert " → " in body
    assert link == "/titles/1"


def test_a_batch_with_a_failure_says_so(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    told: list[Told] = []
    queue = make_queue(paths, programs(RESULT), told=told)
    with conn:  # one from another show
        conn.execute("INSERT INTO titles (id, kind, name) VALUES (2, 'series', 'Northern Lights')")
        conn.execute("UPDATE files SET title_id = 2 WHERE id = 2")
    queue.add([1, 2])
    queue.work_once()
    monkeypatch.setenv("MAKU_FAKE_FAIL", "encode")

    queue.work_once()

    [(title, body, link)] = told
    assert title == "The queue is done"
    assert body.startswith("1 converted, 1 failed · ")
    assert link == "/history"


def test_a_full_drive_is_told_of(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    told: list[Told] = []
    queue = make_queue(paths, programs(RESULT), told=told)
    queue.add([1])

    free_space(monkeypatch, 10**6)

    queue.work_once()

    [(title, body, link)] = told
    assert title == "The queue paused"
    assert body == (
        f"There isn't room on {shows.drive} for the next file: it needs about 162 MB, and 1 MB"
        " is free."
    )
    assert link == "/convert/queue"


def test_a_file_open_in_another_app_waits_its_result_kept_and_goes_in_later(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    episode = shows / "Glass Orchard (2018) - S01E01.mkv"
    open_in_player = open_elsewhere(monkeypatch, episode)
    commands: list[Sequence[str]] = []
    told: list[Told] = []
    queue = make_queue(paths, programs(RESULT, commands), told=told)
    queue.add([1, 2])
    kept = work_of(shows / "Glass Orchard (2018) - S01E01.mkv")

    queue.work_once()  # made and checked, but the player has the original
    [waiting, _] = queue.status().queued
    assert waiting.file_id == 1
    assert waiting.problem == (
        "Glass Orchard · S01E01 is open in another app, maybe your player. Maku will try again "
        "in 5 minutes."
    )
    assert waiting.retry_at is not None
    assert waiting.gpu_seconds == 0  # made already
    assert kept.is_file()  # the result, kept beside it

    queue.work_once()  # the next file goes meanwhile
    assert states(conn) == [(1, "queued"), (2, "done")]
    assert queue.work_once() is False  # the waiting one is never made again
    assert told == []  # one still waits

    open_in_player[0] = False
    assert queue.try_waiting() is False  # not due for 5 minutes
    queue.retry(waiting.id)  # Try now
    assert queue.try_waiting() is True

    assert states(conn) == [(1, "done"), (2, "done")]
    assert episode.read_text().startswith("converted")
    assert not kept.exists()
    made = [command for command in commands if command[-1] == str(kept)]
    assert len(made) == 1  # made once: the kept result went in
    [(title, _, _)] = told
    assert title == "Glass Orchard, season 1 is done"


def test_history_times_a_result_that_waited_by_its_making(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    open_in_player = open_elsewhere(monkeypatch)
    at = [NOW]
    kit = programs(RESULT)

    def slowly(
        command: Sequence[str],
        *,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> subprocess.Popen[bytes]:  # each ffmpeg takes ten minutes, by the queue's clock
        at[0] += timedelta(minutes=10)
        return kit.start(command, stdin=stdin, stdout=stdout, stderr=stderr)

    scanner = Scanner(paths, Tools(paths, items=()))
    queue = Queue(paths, scanner, lambda: replace(kit, start=slowly), now=lambda: at[0])
    queue.add([1])
    queue.work_once()
    made = at[0]
    open_in_player[0] = False
    at[0] += timedelta(hours=2)  # the player let go two hours later

    queue.try_waiting()

    [plan] = plans(conn)
    assert plan.conversion is not None
    assert plan.conversion.seconds == (made - NOW).total_seconds()


def test_a_file_still_open_when_tried_again_waits_again(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    open_elsewhere(monkeypatch)
    queue = make_queue(paths, programs(RESULT))
    queue.add([1])
    queue.work_once()
    [waiting] = queue.status().queued

    queue.retry(waiting.id)
    queue.try_waiting()

    [still] = queue.status().queued
    assert still.retry_at is not None
    assert waiting.retry_at is not None
    assert still.retry_at > waiting.retry_at  # 5 minutes from this try
    assert still.problem == waiting.problem
    assert (work_of(shows / "Glass Orchard (2018) - S01E01.mkv")).is_file()


def test_a_file_waiting_for_its_player_can_be_skipped_and_its_result_goes(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    open_elsewhere(monkeypatch)
    queue = make_queue(paths, programs(RESULT))
    queue.add([1, 2])
    queue.work_once()
    [first, second] = queue.status().queued

    queue.skip(first.id)
    assert states(conn) == [(1, "skipped"), (2, "queued")]
    assert not list(shows.glob(f"*{WORKING}"))

    queue.work_once()  # waits for its player too
    queue.remove(second.id)
    assert states(conn) == [(1, "skipped")]
    assert not list(shows.glob(f"*{WORKING}"))


def test_a_file_changed_while_its_result_waited_isnt_replaced(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    open_in_player = open_elsewhere(monkeypatch)
    queue = make_queue(paths, programs(RESULT))
    queue.add([1])
    queue.work_once()
    [waiting] = queue.status().queued
    episode = shows / "Glass Orchard (2018) - S01E01.mkv"
    episode.write_bytes(b"a better copy, saved over it")
    with conn:  # and a scan read it since
        stat = episode.stat()
        conn.execute(
            "UPDATE files SET size = ?, modified = ? WHERE id = 1",
            (stat.st_size, stat.st_mtime_ns),
        )

    open_in_player[0] = False
    queue.retry(waiting.id)
    queue.try_waiting()

    [failed] = queue.status().today
    assert failed.state == "failed"
    assert failed.problem is not None
    assert failed.problem.startswith("It changed since Maku read it")
    assert episode.read_bytes() == b"a better copy, saved over it"
    assert not list(shows.glob(f"*{WORKING}"))


def test_after_a_crash_a_result_going_in_from_waiting_waits_again(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    open_elsewhere(monkeypatch)
    queue = make_queue(paths, programs(RESULT))
    queue.add([1])
    queue.work_once()
    with conn:  # the engine stopped as it began putting it in place
        conn.execute("UPDATE jobs SET state = 'replacing'")

    changes.recover(conn)
    queue.recover()

    [waiting] = queue.status().queued
    assert waiting.retry_at is not None
    assert (work_of(shows / "Glass Orchard (2018) - S01E01.mkv")).is_file()


def test_after_a_crash_only_makus_own_unfinished_result_is_removed(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    queue = make_queue(paths, programs(RESULT))
    queue.add([1])
    precious = shows / "thesis.docx"
    precious.write_text("years of work")
    episode = shows / "Glass Orchard (2018) - S01E01.mkv"
    # A journal naming it as the result, as a damaged database or an imported one could hold.
    plan = Plan(
        (
            Change(ChangeKind.QUARANTINE, episode, shows / "aside" / episode.name, "x", "y"),
            Change(ChangeKind.MOVE, precious, episode, "x", "y"),
        )
    )
    plan_id = save_plan(conn, plan, "Converted x", now=NOW, kind="convert")
    with conn:
        conn.execute("UPDATE changes SET state = 'failed'")
        conn.execute("UPDATE jobs SET state = 'replacing', plan_id = ?", (plan_id,))

    queue.recover()

    assert precious.read_text() == "years of work"
    assert states(conn) == [(1, "queued")]


def test_after_a_crash_a_waiting_result_in_place_but_unread_waits_no_more(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    open_in_player = open_elsewhere(monkeypatch)
    queue = make_queue(paths, programs(RESULT))
    queue.add([1])
    queue.work_once()
    [waiting] = queue.status().queued
    open_in_player[0] = False
    queue.retry(waiting.id)

    def crash(*args: object, **kwargs: object) -> None:  # once both moves are made
        raise KeyboardInterrupt

    monkeypatch.setattr("maku.convert.finish", crash)
    with pytest.raises(KeyboardInterrupt):
        queue.try_waiting()
    monkeypatch.undo()

    make_queue(paths, None).recover()  # the next start, without ffprobe to read it

    job = conn.execute("SELECT state, retry_at FROM jobs").fetchone()
    assert (job["state"], job["retry_at"]) == ("done", None)


def test_a_file_converted_anew_is_timed_by_this_conversion(queue: Queue, conn: sqlite3.Connection):
    queue.add([1])
    with conn:  # left from an earlier try, its result put back since
        conn.execute("UPDATE jobs SET finished_at = '2020-01-01T00:00:00+00:00'")

    queue.work_once()

    [plan] = plans(conn)
    assert plan.conversion is not None
    assert plan.conversion.seconds is not None
    assert plan.conversion.seconds >= 0


class Whisper:
    """Stands in for Whisper loaded from a folder, on the graphics card or the processor: hears
    two lines in anything."""

    loaded: ClassVar[list[Path]] = []
    graphics: ClassVar[list[bool]] = []

    def __init__(self, folder: Path, graphics: bool) -> None:
        Whisper.loaded.append(folder)
        Whisper.graphics.append(graphics)

    def hear(self, audio: object, language: str | None, *, report: object, stop: object) -> Made:
        return Made([Segment(1.0, 2.0, "Over here!")], "ja", translated=True, speech=1.0)


def hearing(tmp_path: Path, *, models: Sequence[str] = ("best", "fast")) -> Programs:
    """The stand-ins for converting, and Whisper at the qualities in `models`, downloaded."""
    Whisper.loaded, Whisper.graphics = [], []
    folders = {quality: tmp_path / f"speech-{quality}" for quality in models}
    return replace(programs(RESULT), speech=folders.get, listener=Whisper)


def test_videos_join_for_subtitles_in_order_once_as_a_batch(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, tmp_path: Path
):
    queue = make_queue(paths, hearing(tmp_path))

    assert queue.add_subtitles([2, 1, 2], "best", "jpn", "Glass Orchard · Season 1") == 2
    assert queue.add_subtitles([1, 3], "fast", "jpn", "Glass Orchard") == 1  # 1 waits already
    assert queue.add([1]) == 1  # converting it is another job

    queued = queue.status().queued
    assert [(job.file_id, job.kind, job.method) for job in queued] == [
        (2, "subtitles", "best"),
        (1, "subtitles", "best"),
        (3, "subtitles", "fast"),
        (1, "convert", Method.REENCODE),
    ]
    assert queued[0].language == "jpn"
    assert queued[0].gpu_seconds == pytest.approx(24 * 60 * 0.4)
    batches = conn.execute("SELECT title, quality, language FROM subtitle_batches").fetchall()
    assert [tuple(row) for row in batches] == [
        ("Glass Orchard · Season 1", "best", "jpn"),
        ("Glass Orchard", "fast", "jpn"),
    ]


def test_a_batch_nothing_joins_is_forgotten(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, tmp_path: Path
):
    queue = make_queue(paths, hearing(tmp_path))
    queue.add_subtitles([1], "best", "jpn", "Glass Orchard")

    assert queue.add_subtitles([1], "best", "jpn", "Glass Orchard again") == 0
    assert conn.execute("SELECT COUNT(*) FROM subtitle_batches").fetchone()[0] == 1


def test_subtitles_are_made_in_turn_with_conversions_and_said_when_done(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, tmp_path: Path
):
    told: list[Told] = []
    queue = make_queue(paths, hearing(tmp_path), told=told)
    queue.add_subtitles([1, 2], "best", "jpn", "Glass Orchard · Season 1")

    assert queue.work_once()
    assert queue.work_once()

    assert states(conn) == [(1, "done"), (2, "done")]
    assert (shows / "Glass Orchard (2018) - S01E01.en.srt").is_file()
    assert (shows / "Glass Orchard (2018) - S01E02.en.srt").is_file()
    assert Whisper.loaded == [tmp_path / "speech-best"]  # loaded once for both
    assert told == [
        (
            "Glass Orchard, season 1 has English subtitles",
            "2 episodes · made from their sound",
            "/titles/1",
        )
    ]


def test_whisper_is_let_go_before_a_conversion_and_loaded_again_after(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, tmp_path: Path
):
    queue = make_queue(paths, hearing(tmp_path))
    queue.add_subtitles([1], "fast", "jpn", "Glass Orchard")
    queue.add([2])
    queue.add_subtitles([3], "fast", "jpn", "Glass Orchard")

    while queue.work_once():
        pass

    assert states(conn) == [(1, "done"), (2, "done"), (3, "done")]
    assert Whisper.loaded == [tmp_path / "speech-fast"] * 2


def test_subtitles_wait_for_their_speech_model_while_the_others_go(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, tmp_path: Path
):
    queue = make_queue(paths, hearing(tmp_path, models=("fast",)))
    queue.add_subtitles([1], "best", "jpn", "Glass Orchard")
    queue.add_subtitles([2], "fast", "jpn", "Glass Orchard")

    [waiting, ready] = queue.status().queued
    assert (waiting.model_missing, ready.model_missing) == (True, False)
    assert queue.work_once()
    assert not queue.work_once()  # Best's model isn't here
    assert states(conn) == [(1, "queued"), (2, "done")]


def test_whats_done_is_told_though_subtitles_wait_for_their_speech_model(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, tmp_path: Path
):
    told: list[Told] = []
    queue = make_queue(paths, hearing(tmp_path, models=("fast",)), told=told)
    queue.add_subtitles([1], "best", "jpn", "Glass Orchard")
    queue.add([2])

    assert queue.work_once()

    assert states(conn) == [(1, "queued"), (2, "done")]
    assert [title for title, _, _ in told] == ["Glass Orchard, season 1 is done"]


class Troubled(Whisper):
    """Whisper whose graphics card goes away while it hears the first video."""

    def hear(self, audio: object, language: str | None, *, report: object, stop: object) -> Made:
        if len(Whisper.loaded) == 1:
            raise RuntimeError("The GPU device instance has been suspended")
        return super().hear(audio, language, report=report, stop=stop)


def test_whisper_that_hit_a_problem_is_loaded_anew_for_the_next_video(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, tmp_path: Path
):
    queue = make_queue(paths, replace(hearing(tmp_path), listener=Troubled))
    queue.add_subtitles([1, 2], "best", "jpn", "Glass Orchard")

    queue.work_once()
    queue.work_once()

    assert states(conn) == [(1, "failed"), (2, "done")]
    assert Whisper.loaded == [tmp_path / "speech-best"] * 2


def test_a_batch_that_made_no_subtitles_doesnt_say_it_did(
    paths: DataPaths,
    shows: Path,
    conn: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("MAKU_FAKE_FAIL", "sound")
    told: list[Told] = []
    queue = make_queue(paths, hearing(tmp_path), told=told)
    queue.add_subtitles([1, 2], "best", "jpn", "Glass Orchard · Season 1")

    queue.work_once()
    queue.work_once()

    assert told == [
        ("No English subtitles for Glass Orchard, season 1", "2 couldn't be made", "/titles/1")
    ]


def test_trying_again_never_puts_a_video_in_the_queue_twice(
    paths: DataPaths,
    shows: Path,
    conn: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("MAKU_FAKE_FAIL", "sound")
    queue = make_queue(paths, hearing(tmp_path))
    queue.add_subtitles([1], "best", "jpn", "Glass Orchard")
    queue.work_once()
    [failed] = queue.status().today
    monkeypatch.delenv("MAKU_FAKE_FAIL")
    queue.add_subtitles([1], "best", "jpn", "Glass Orchard")  # asked for again, on its title's page

    queue.retry(failed.id)  # and "Try again" on the queue

    assert [job.file_id for job in queue.status().queued] == [1]


def test_subtitles_that_cant_be_made_fail_saying_why(
    paths: DataPaths,
    shows: Path,
    conn: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("MAKU_FAKE_FAIL", "sound")
    queue = make_queue(paths, hearing(tmp_path))
    queue.add_subtitles([1], "best", "jpn", "Glass Orchard")

    queue.work_once()

    [job] = queue.status().today
    assert (job.kind, job.state) == ("subtitles", "failed")
    assert job.problem is not None
    assert job.problem.startswith("ffmpeg couldn't read its sound")
    assert job.log is not None


def test_after_a_crash_subtitles_being_made_wait_again_and_their_part_goes(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, tmp_path: Path
):
    queue = make_queue(paths, hearing(tmp_path))
    queue.add_subtitles([1], "best", "jpn", "Glass Orchard")
    with conn:
        conn.execute("UPDATE jobs SET state = 'running'")
    part = shows / "Glass Orchard (2018) - S01E01.en.srt.maku-partial"
    part.write_text("half", "utf-8")

    settled = queue.recover()

    assert states(conn) == [(1, "queued")]
    assert not part.exists()
    assert settled.restarted == 1


GTX = Card("NVIDIA GeForce GTX 1660 SUPER", "nvidia", 6 * GIB, False, "617.42")
SMALL = Card("NVIDIA GeForce GTX 1050", "nvidia", 2 * GIB, False, "551.86")
UHD = Card("Intel(R) UHD Graphics 620", "intel", 128 * 1024**2, True, "31.0.101.2111")


def this_pc(
    conn: sqlite3.Connection,
    card: Card,
    encoder: str | None = "nvenc",
    *,
    directml: bool = True,
    problem: str | None = None,
) -> None:
    """What checking this PC found: its card, the encoder that started on it (and what the
    card's own said when it didn't), and whether DirectML ran."""
    facts = Facts((card,), "Intel Core i5-9600K", 6, 24 * GIB)
    found = Checked(encoder, problem, directml=directml, at=NOW.isoformat())
    hardware.keep(conn, facts, found)


def test_without_an_encoder_files_wait_to_convert_while_subtitles_go(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, tmp_path: Path
):
    this_pc(conn, GTX, encoder=None)
    queue = make_queue(paths, hearing(tmp_path))
    queue.add([1])
    queue.add_subtitles([2], "fast", "jpn", "Glass Orchard")

    while queue.work_once():
        pass

    assert states(conn) == [(1, "queued"), (2, "done")]
    assert queue.status().problem == NO_ENCODER


def test_files_convert_with_the_encoder_this_pc_has(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    this_pc(conn, Card("AMD Radeon RX 6700 XT", "amd", 12 * GIB, False, "32.0"), "amf")
    commands: list[Sequence[str]] = []
    queue = make_queue(paths, programs(RESULT, commands))
    queue.add([1])

    queue.work_once()

    assert states(conn) == [(1, "done")]
    assert any("hevc_amf" in command for command in commands)
    assert not any("hevc_nvenc" in command for command in commands)


def test_each_file_done_measures_its_way_on_this_pc(queue: Queue, conn: sqlite3.Connection):
    assert hardware.measured(conn) is None

    queue.add([1])
    queue.work_once()

    measured = hardware.measured(conn)
    assert measured is not None
    assert (measured.tested, measured.conversions) == (False, 1)
    assert hardware.speeds(conn).megapixels != Speeds().megapixels  # this PC's own now


def test_nothing_starts_while_this_pc_is_checked(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    checking = [True]
    queue = Queue(
        paths,
        Scanner(paths, Tools(paths, items=())),
        lambda: programs(RESULT),
        now=lambda: NOW,
        checking=lambda: checking[0],
    )
    queue.add([1])

    assert not queue.work_once()

    checking[0] = False
    assert queue.work_once()
    assert states(conn) == [(1, "done")]


class OutOfCardMemory(Whisper):
    """Whisper on a card that runs out of memory as it hears the first video."""

    def hear(self, audio: object, language: str | None, *, report: object, stop: object) -> Made:
        if len(Whisper.loaded) == 1:
            raise RuntimeError(
                "Exception(3) tid(2b4c) 8007000E Not enough memory resources are available to "
                "complete this operation."
            )
        return super().hear(audio, language, report=report, stop=stop)


def test_best_that_ran_out_of_the_cards_memory_can_be_made_with_fast(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, tmp_path: Path
):
    queue = make_queue(paths, replace(hearing(tmp_path), listener=OutOfCardMemory))
    queue.add_subtitles([1], "best", "jpn", "Glass Orchard")

    queue.work_once()

    [failed] = queue.status().today
    assert failed.problem == "The graphics card ran out of memory for Best."
    assert failed.fast_instead

    queue.retry(failed.id, "fast")
    queue.work_once()

    [made] = queue.status().today
    assert (made.state, made.method) == ("done", "fast")
    assert Whisper.loaded == [tmp_path / "speech-best", tmp_path / "speech-fast"]


def test_best_on_a_card_without_the_memory_for_it_says_fast_runs_here(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, tmp_path: Path
):
    this_pc(conn, SMALL)
    queue = make_queue(paths, hearing(tmp_path))
    queue.add_subtitles([1], "best", "jpn", "Glass Orchard")

    queue.work_once()

    [failed] = queue.status().today
    assert failed.problem == BEST_WANTS_MEMORY
    assert failed.fast_instead
    assert Whisper.loaded == []


def test_fast_runs_on_the_processor_where_the_card_hasnt_the_memory(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, tmp_path: Path
):
    this_pc(conn, UHD, "qsv")
    queue = make_queue(paths, hearing(tmp_path))
    queue.add_subtitles([1], "fast", "jpn", "Glass Orchard")
    waiting = queue.status().queued[0].gpu_seconds

    queue.work_once()

    assert states(conn) == [(1, "done")]
    assert Whisper.graphics == [False]
    assert waiting == pytest.approx(1440 * HEARING["fast_processor"])  # the processor's time
    measured = hardware.measured(conn)
    assert measured is not None
    assert measured.subtitles == 1


def test_a_card_whose_driver_is_too_old_says_so_in_the_queue(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection
):
    too_old = "Driver does not support the required nvenc API version."
    this_pc(conn, GTX, encoder=None, problem=too_old)
    queue = make_queue(paths, programs(RESULT))
    queue.add([1])

    assert not queue.work_once()

    assert queue.status().problem == (
        "NVIDIA's encoder (NVENC) didn't start: the graphics card's driver may be too old for "
        "it. Update it, then test this PC again under About in Settings."
    )


def test_subtitles_done_are_told_while_conversions_wait_for_an_encoder(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, tmp_path: Path
):
    this_pc(conn, GTX, encoder=None)
    told: list[Told] = []
    queue = make_queue(paths, hearing(tmp_path), told=told)
    queue.add([1])
    queue.add_subtitles([2], "fast", "jpn", "Glass Orchard")

    while queue.work_once():
        pass

    assert states(conn) == [(1, "queued"), (2, "done")]
    assert [title for title, _, _ in told] == ["Glass Orchard, season 1 has English subtitles"]


def test_a_file_done_stays_done_when_keeping_its_time_fails(
    queue: Queue, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    def locked(*_args: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("maku.hardware.learn_conversion", locked)
    queue.add([1])

    queue.work_once()

    assert states(conn) == [(1, "done")]


def test_subtitles_made_stay_made_when_keeping_their_time_fails(
    paths: DataPaths,
    shows: Path,
    conn: sqlite3.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def locked(*_args: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("maku.hardware.learn_hearing", locked)
    queue = make_queue(paths, hearing(tmp_path))
    queue.add_subtitles([1], "fast", "jpn", "Glass Orchard")

    queue.work_once()

    assert states(conn) == [(1, "done")]


def test_best_where_directx_doesnt_run_says_so(
    paths: DataPaths, shows: Path, conn: sqlite3.Connection, tmp_path: Path
):
    this_pc(conn, GTX, directml=False)  # the card has the memory: DirectML is what's missing
    queue = make_queue(paths, hearing(tmp_path))
    queue.add_subtitles([1], "best", "jpn", "Glass Orchard")

    queue.work_once()

    [failed] = queue.status().today
    assert failed.problem == BEST_WANTS_DIRECTX
    assert failed.fast_instead
