"""The queue: the files waiting to be converted, or to have English subtitles made, in the owner's
order, and the worker that works on them one at a time on a background thread (maku/convert.py
converts each; maku/subtitles.py makes subtitles). Both use the graphics card, so one waits for the
other. Whisper stays loaded while subtitles follow subtitles, and is let go before a conversion and
once nothing waits.

Jobs live in the jobs table (migration 6; subtitles since 20): queued, running, replacing (a
conversion's result taking its original's place), then done, failed, skipped or restored. Subtitles
at a quality whose speech model isn't downloaded wait for it while the others go. The worker takes
the first queued job while the queue isn't paused, and on the nights-only schedule only between
23:00 and 07:00 (a file started before 07:00 finishes), or till 03:00 on a night the owner says to
stop then (`stop_early`). Pausing or skipping stops a file being made at once (ffmpeg is stopped,
and the original is as it was); paused, the file is first in line again and starts over when the
queue resumes. An exit does the same. A file made already is checked and put in place though the
queue pauses, and thrown away when it's skipped. A file whose drive isn't connected waits while the
others go; a drive without room for a result pauses the queue, saying what its files need (`Room`),
till the owner makes room (emptying its quarantine, say) or says to convert what fits
(`convert_what_fits`): then a file there that doesn't fit waits for room while the others go, till
none waits there. While a result takes its original's place no scan runs (Scanner.hold): the worker
waits for one that's running. While a file converts, Windows doesn't put the PC to sleep. After a
crash, `recover` puts a job that was converting back in line and settles one whose result was taking
its original's place. Once nothing waits, the app is told what the batch came to, and it's told when
the queue pauses itself: a Windows notification while Maku is in the tray.

When another app has an original open as its result is ready (a player playing it), the result waits
beside it and the next file goes. A second thread puts such results in place, five minutes after
each try or at once when the owner asks (`retry`), though another file is converting: `try_waiting`.
Skipping the file, or taking it out of the queue, throws its result away.

Each file converts with the encoder this PC has (maku/hardware.py keeps what checking it found);
without one, conversions wait and the queue says why, while subtitles and English from another
copy go on. Nothing starts while the PC is being checked. Whisper runs where this PC has room for
it: Fast on the processor when the graphics card hasn't the memory. Every file done measures its
way's speed on this PC, so the queue's times are this PC's own.
"""

import ctypes
import json
import logging
import shutil
import sqlite3
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Generator, Iterable
from contextlib import ExitStack, closing, contextmanager, suppress
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from datetime import time as clock_time
from pathlib import Path
from typing import Literal, cast

from maku import db, hardware
from maku.changes import SavedChange
from maku.config import DataPaths
from maku.convert import (
    CONVERTED,
    IN_USE_WAIT,
    SPACE_MARGIN,
    ConvertError,
    InUseError,
    NoRoomError,
    NothingToConvert,
    Programs,
    Progress,
    Stopped,
    convert,
    label_of,
    put_in,
    restore,
    room_for,
    settle,
    size_words,
    throw_away_kept,
    work_of,
)
from maku.core.estimate import HEARING, Speeds, estimate, hearing, merging
from maku.core.hardware import (
    BEST_WANTS_DIRECTX,
    BEST_WANTS_MEMORY,
    best_wants,
    why_not_converting,
)
from maku.core.library import drive_of
from maku.core.media import MediaInfo, media_from_ffprobe
from maku.core.speech import Heard, Hearing, Quality
from maku.core.standard import Method, Standard, decide
from maku.events import Notify
from maku.merge import merge
from maku.preferences import library_standard, originals_deleted
from maku.probe import probe
from maku.quarantine import set_aside_by_drive
from maku.recovery import Recovery
from maku.scan import ScanBusyError, Scanner
from maku.speech import MODELS, SpeechError
from maku.subtitles import (
    SHORT_OF_MEMORY,
    OutOfMemory,
    SubtitlesError,
    new_batch,
    track_for,
    unfinished,
)
from maku.subtitles import make as make_subtitles
from maku.system import own_command
from maku.tools import Tools

log = logging.getLogger(__name__)

type JobState = Literal["queued", "running", "replacing", "done", "failed", "skipped", "restored"]
type Stage = Literal[
    "looking", "converting", "checking", "replacing", "reading", "listening", "writing"
]
type Kind = Literal["convert", "subtitles", "merge"]
type Schedule = Literal["now", "nights"]  # convert whenever files wait, or only at night

_IDLE = 30.0  # seconds the worker rests with nothing to do; adding or resuming wakes it at once
_HOLD_RETRY = 2.0  # seconds between asks for scans to hold off
_WAITING_LOOK = 30.0  # seconds between looks for results due to go in; `retry` wakes it at once
_SPEED_WINDOW = 600.0  # seconds of frames the speed is measured over, as the queue board shows
_PAUSED = "queue_paused"  # the settings rows that keep the queue's state across restarts
_SCHEDULE = "queue_schedule"
_SHORT = "queue_short_of_room"  # the drive ("D:") the queue paused for, till it's resumed
_FITTING = "queue_fitting"  # drives where a file without room waits while the others go
_EARLY = "queue_stops_early"  # when tonight's run takes its last file, stopping early
NIGHT = (clock_time(23, 0), clock_time(7, 0))  # when the nights-only schedule converts
EARLY = clock_time(3, 0)  # "Stop at 03:00"
NO_FFMPEG = "Maku needs ffmpeg to convert. It's downloaded on the setup's Tools step."
# Why Best failed where Fast would go: its card ran out of memory, or this PC can't run it.
_FAST_INSTEAD = (SHORT_OF_MEMORY["best"], BEST_WANTS_MEMORY, BEST_WANTS_DIRECTX)


@dataclass(frozen=True)
class Job:
    id: int
    file_id: int
    path: str
    label: str  # "The Harbour Line · S01E06"
    title_id: int | None
    title: str | None
    season: int | None
    episode: int | None
    # What it gets: a conversion, what suits its file (a new picture, or its own in an MKV);
    # subtitles, their quality.
    method: Method | Quality
    state: JobState
    position: int
    gpu_seconds: float  # how long it takes, as estimated
    added_at: str
    started_at: str | None
    finished_at: str | None
    problem: str | None  # why it failed, in words
    source_size: int  # the original, in bytes
    output_size: int | None  # the result, once there
    width: int | None = None  # the result's picture, for a file still to finish
    height: int | None = None
    drive_missing: bool = False  # waiting, and its library folder's drive isn't connected
    # Made, and waiting beside its original for another app to let go of it: when Maku tries
    # again to put it in place.
    retry_at: str | None = None
    log: str | None = None  # what ffmpeg said, when a conversion failed
    no_room: bool = False  # waiting for room on its drive while the others go
    # A conversion, English subtitles (`method`: their quality), or English from another copy.
    kind: Kind = "convert"
    language: str | None = None  # subtitles: the sound they're made from ("jpn"; "" unsaid)
    model_missing: bool = False  # subtitles waiting for their speech model to download
    fast_instead: bool = False  # subtitles at Best that failed where Fast would go


@dataclass(frozen=True)
class Room:
    """A drive without room for the files waiting to convert on it."""

    drive: str  # "D:"
    paused: bool  # the queue paused for it; else the files that don't fit wait while others go
    files: int  # files waiting to convert on it
    needed: int  # the free space their results want, in bytes
    free: int  # bytes free on it now
    fit: int  # how many of them fit now, in turn
    set_aside: int  # bytes its quarantine would free, emptied now


@dataclass(frozen=True)
class Running:
    """The job running now, and how it's going: frames converted, or for subtitles, seconds of
    the video heard."""

    job: Job
    stage: Stage
    frames: int
    total: int
    seconds_left: float | None
    fps: float | None  # frames a second, over the last ten minutes


@dataclass(frozen=True)
class QueueStatus:
    paused: bool
    schedule: Schedule
    waits_for_night: bool  # nights only, and it's day (or tonight's run is over): from 23:00
    problem: str | None  # why nothing converts though files wait (no ffmpeg, say)
    running: Running | None
    queued: tuple[Job, ...]  # in the order they'll go
    gpu_seconds: float  # the work left: the running file's and the queued ones'
    today: tuple[Job, ...]  # finished today (done, failed or skipped), newest first
    room: Room | None = None  # a drive without room for what waits on it
    # Nights only, at night: when tonight's run takes its last file (07:00, or earlier when the
    # owner said to stop early), ISO local time.
    ends_at: str | None = None
    early: bool = False  # the owner said to stop early tonight


class Queue:
    """The conversion queue and its worker. One per engine."""

    def __init__(
        self,
        paths: DataPaths,
        scanner: Scanner,
        programs: Callable[[], Programs | None],
        *,
        now: Callable[[], datetime],
        clock: Callable[[], float] = time.monotonic,
        notify: Notify = lambda _title, _body, link=None: None,
        checking: Callable[[], bool] = lambda: False,
    ) -> None:
        """`programs` gives what converting runs, or None while Maku has no ffmpeg. `notify`
        tells the app something worth a notification: a title, a line, and where it leads.
        `checking` says whether the PC is being checked (maku/pc_check.py): nothing starts
        meanwhile."""
        self._paths = paths
        self._notify = notify
        self._batch: list[int] = []  # files converted (or failed) since nothing last waited
        self._noting = threading.Lock()  # both threads add to the batch
        self._scanner = scanner
        self._programs = programs
        self._checking = checking
        self._now = now
        self._clock = clock
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._try_now = threading.Event()  # wakes the thread that puts waiting results in place
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._waiting: threading.Thread | None = None
        self._job_id: int | None = None  # the job converting now
        self._stop_for: Literal["pause", "skip"] | None = None
        self._progress: Progress | None = None
        self._frames: deque[tuple[float, int]] = deque()  # (when, frames done) while converting
        self._speech: Heard | None = None  # how far the subtitles being made have got
        self._hearing: tuple[float, float] | None = None  # (when, seconds heard) as they began
        # Whisper, loaded from that folder, on the graphics card (True) or the processor.
        self._listener: tuple[Path, bool, Hearing] | None = None
        self._made_at: float | None = None  # when the file converting now was made, to measure
        self._problem: str | None = None
        # The room files were found to want as converting began, more than the queue reckoned
        # (a picture found interlaced is made anew rather than copied), and what it reckoned
        # then: (job id, when it was added) -> (bytes, bytes).
        self._needs: dict[tuple[int, str], tuple[int, int]] = {}

    def start(self) -> None:
        """Converts until `stop`. Call `recover` first, before any scan starts."""
        self._thread = threading.Thread(target=self._loop, name="queue", daemon=True)
        self._thread.start()
        self._waiting = threading.Thread(target=self._loop_waiting, name="waiting", daemon=True)
        self._waiting.start()

    def stop(self) -> None:
        """Stops the worker: the file converting now is first in line at the next start."""
        self._stopping.set()
        self._wake.set()
        self._try_now.set()
        for thread in (self._thread, self._waiting):
            if thread is not None:
                thread.join(timeout=30)

    def recover(self) -> Recovery:
        """At start: a job a crash stopped while converting waits in line again (its unfinished
        result goes), and one whose result was taking its original's place is settled: finished,
        or its original put back. Says how many of each there were (a clean stop leaves none)."""
        programs = self._programs()
        read = programs.read if programs else None
        with closing(db.connect(self._paths.database)) as conn:
            running = conn.execute(
                """SELECT j.kind, f.path FROM jobs AS j JOIN files AS f ON f.id = j.file_id
                   WHERE j.state = 'running'"""
            ).fetchall()
            for row in running:
                path = Path(row["path"])
                left = unfinished(path) if row["kind"] == "subtitles" else [work_of(path)]
                for each in left:
                    try:
                        each.unlink(missing_ok=True)
                    except OSError:  # still open: working on the file again takes it away
                        log.warning("Couldn't remove %s", each)
            with conn:
                conn.execute(
                    "UPDATE jobs SET state = 'queued', started_at = NULL WHERE state = 'running'"
                )
            finished = put_back = 0
            for row in conn.execute("SELECT id FROM jobs WHERE state = 'replacing'").fetchall():
                settle(conn, row["id"], read, self._now())
                after = conn.execute(
                    "SELECT state, retry_at FROM jobs WHERE id = ?", (row["id"],)
                ).fetchone()
                if after["state"] == "done":
                    finished += 1
                elif after["retry_at"] is None:  # one still waiting for its player just waits
                    put_back += 1
        return Recovery(restarted=len(running), finished=finished, put_back=put_back)

    def add(self, file_ids: Iterable[int], *, fit: Iterable[str] = ()) -> int:
        """Puts files at the end of the queue, in the order given, each to get what suits it. A
        file already in it, or one with nothing to convert (at the standard already, unreadable,
        or gone), is passed over. On the drives in `fit` ("D:"), the files that fit convert and
        the rest wait for room (`convert_what_fits`), from the moment they join. Returns how many
        joined."""
        stamp = self._now().isoformat()
        added = 0
        # Under the lock the worker takes files under: it never sees them without `fit`.
        with self._lock, closing(db.connect(self._paths.database)) as conn, conn:
            fitting = _fitting(conn)
            if more := [drive for drive in dict.fromkeys(fit) if not _among(drive, fitting)]:
                _save(conn, _FITTING, [*fitting, *more])
            standard = library_standard(conn)
            waiting = {
                row[0]
                for row in conn.execute(
                    """SELECT file_id FROM jobs
                       WHERE state IN ('queued', 'running', 'replacing') AND kind = 'convert'"""
                )
            }
            waiting |= _giving(conn)  # set aside once its English is in: not worth converting
            last: int = conn.execute("SELECT COALESCE(MAX(position), 0) FROM jobs").fetchone()[0]
            for file_id in dict.fromkeys(file_ids):
                row = conn.execute(
                    """SELECT probe FROM files
                       WHERE id = ? AND gone_at IS NULL AND problem IS NULL""",
                    (file_id,),
                ).fetchone()
                if file_id in waiting or row is None or row["probe"] is None:
                    continue
                decided = decide(media_from_ffprobe(json.loads(row["probe"])), standard).method
                if decided not in CONVERTED:
                    continue  # at the standard already: tidying up renames it
                last += 1
                conn.execute(
                    "INSERT INTO jobs (file_id, method, position, added_at) VALUES (?, ?, ?, ?)",
                    (file_id, decided.value, last, stamp),
                )
                added += 1
        self._wake.set()
        return added

    def add_subtitles(
        self, file_ids: Iterable[int], quality: str, language: str, title: str
    ) -> int:
        """Puts videos at the end of the queue for English subtitles at `quality` ("best"), made
        from their sound in `language` ("jpn"; a video without it, from its first), as one
        batch History calls `title`. A video waiting for them already, one without sound, or
        another copy whose English goes into the one kept, is passed over. Returns how many
        joined."""
        stamp = self._now()
        added = 0
        with self._lock, closing(db.connect(self._paths.database)) as conn:
            waiting = {
                row[0]
                for row in conn.execute(
                    """SELECT file_id FROM jobs
                       WHERE state IN ('queued', 'running') AND kind = 'subtitles'"""
                )
            }
            waiting |= _giving(conn)
            chosen = "fast" if quality == "fast" else "best"
            batch = new_batch(conn, title, chosen, language, now=stamp)
            with conn:
                last: int = conn.execute("SELECT COALESCE(MAX(position), 0) FROM jobs").fetchone()[
                    0
                ]
                for file_id in dict.fromkeys(file_ids):
                    row = conn.execute(
                        """SELECT sound FROM files
                           WHERE id = ? AND gone_at IS NULL AND problem IS NULL""",
                        (file_id,),
                    ).fetchone()
                    sound = _languages(row["sound"]) if row else []
                    if file_id in waiting or not sound:
                        continue
                    last += 1
                    conn.execute(
                        """INSERT INTO jobs (file_id, kind, method, sound, batch_id, position,
                                             added_at)
                           VALUES (?, 'subtitles', ?, ?, ?, ?, ?)""",
                        (
                            file_id,
                            chosen,
                            track_for(sound, language),
                            batch,
                            last,
                            stamp.isoformat(),
                        ),
                    )
                    added += 1
                if not added:
                    conn.execute("DELETE FROM subtitle_batches WHERE id = ?", (batch,))
        self._wake.set()
        return added

    def add_merge(self, file_id: int, other_id: int) -> bool:
        """Puts English from another copy (`other_id`) into a file kept (`file_id`) next in the
        queue: it's quick, and a conversion of the file waiting after it then keeps the English.
        What waits in the queue for the other copy leaves it: that copy is set aside once its
        English is in. False when the same is waiting already."""
        stamp = self._now().isoformat()
        with self._lock, closing(db.connect(self._paths.database)) as conn, conn:
            waiting = conn.execute(
                """SELECT 1 FROM jobs WHERE kind = 'merge' AND file_id = ?
                   AND state IN ('queued', 'running', 'replacing')""",
                (file_id,),
            ).fetchone()
            if waiting is not None:
                return False
            first: int = conn.execute(
                "SELECT COALESCE(MIN(position), 1) FROM jobs WHERE state = 'queued'"
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO jobs (file_id, kind, method, other_id, position, added_at)
                   VALUES (?, 'merge', 'remux', ?, ?, ?)""",
                (file_id, other_id, first - 1, stamp),
            )
            conn.execute(
                """DELETE FROM jobs
                   WHERE file_id = ? AND state = 'queued' AND retry_at IS NULL""",
                (other_id,),
            )
        self._wake.set()
        return True

    def pause(self) -> None:
        """Stops the file converting now and takes no other until `resume`."""
        self._set_paused(paused=True)
        with self._lock:
            if self._job_id is not None:
                self._stop_for = "pause"

    def resume(self) -> None:
        self._set_paused(paused=False)
        with closing(db.connect(self._paths.database)) as conn, conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (_SHORT,))
        self._wake.set()

    def busy(self) -> bool:
        """Whether a job is running now: the card is the queue's."""
        with self._lock:
            return self._job_id is not None

    def wake(self) -> None:
        """Looks for a file to convert now rather than at the next look: room was made, say."""
        self._wake.set()

    def convert_what_fits(self, drive: str) -> None:
        """On a drive ("D:") without room for all that waits on it, the files that fit convert,
        and the rest wait for room while the others go, till none waits there. It doesn't resume
        the queue."""
        with closing(db.connect(self._paths.database)) as conn, conn:
            fitting = _fitting(conn)
            if not _among(drive, fitting):
                _save(conn, _FITTING, [*fitting, drive])
        self._wake.set()

    def plan(self, schedule: Schedule) -> None:
        """Converts whenever files wait ("now"), or only at night ("nights")."""
        with closing(db.connect(self._paths.database)) as conn, conn:
            _save(conn, _SCHEDULE, schedule)
        self._wake.set()

    def stop_early(self, *, early: bool) -> None:
        """On the nights-only schedule: tonight's run takes no file after 03:00 (past 03:00,
        none after the one converting), so Windows' sleep comes back once that one's done; or,
        not `early`, it goes on till 07:00 again."""
        with closing(db.connect(self._paths.database)) as conn, conn:
            if early:
                _save(conn, _EARLY, _early_stop(self._now()).isoformat())
            else:
                conn.execute("DELETE FROM settings WHERE key = ?", (_EARLY,))
        self._wake.set()

    def skip(self, job_id: int) -> None:
        """Passes over a file: the one converting now stops, and one waiting leaves the line,
        with its result when one waited beside it. Raises LookupError when it's neither."""
        with self._lock:
            if self._job_id == job_id:
                self._stop_for = "skip"
                return
            with closing(db.connect(self._paths.database)) as conn:
                if _waiting_job(conn, job_id):
                    throw_away_kept(conn, job_id)
                with conn:
                    done = conn.execute(
                        """UPDATE jobs SET state = 'skipped', finished_at = ?, retry_at = NULL
                           WHERE id = ? AND state = 'queued'""",
                        (self._now().isoformat(), job_id),
                    ).rowcount
        if not done:
            raise LookupError("That file isn't waiting or converting.")

    def remove(self, job_id: int) -> None:
        """Takes a waiting file out of the queue, as if it had never been added: a result that
        waited beside it goes too."""
        if not self.remove_all([job_id]):
            raise LookupError("That file isn't waiting in the queue.")

    def remove_all(self, job_ids: Iterable[int]) -> int:
        """Takes waiting files out of the queue, as `remove` does one. A file no longer waiting
        (it started, say) is passed over. Returns how many went."""
        gone = 0
        with self._lock, closing(db.connect(self._paths.database)) as conn:
            for job_id in dict.fromkeys(job_ids):
                if _waiting_job(conn, job_id):
                    throw_away_kept(conn, job_id)
                with conn:
                    gone += conn.execute(
                        "DELETE FROM jobs WHERE id = ? AND state = 'queued'", (job_id,)
                    ).rowcount
        return gone

    def move(self, job_id: int, before: int | None) -> None:
        """Puts a waiting file before another (`before`), or last when that's None."""
        if not self.move_all([job_id], before):
            raise LookupError("That file isn't waiting in the queue.")

    def move_all(self, job_ids: Iterable[int], before: int | None) -> int:
        """Puts waiting files together before another (`before`), or last when that's None or
        among them, in the order they wait in. A file no longer waiting is passed over. Returns
        how many moved."""
        moving = set(job_ids)
        with closing(db.connect(self._paths.database)) as conn, conn:
            order = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM jobs WHERE state = 'queued' ORDER BY position, id"
                )
            ]
            block = [job for job in order if job in moving]
            rest = [job for job in order if job not in moving]
            at = rest.index(before) if before in rest else len(rest)
            first: int = conn.execute(
                "SELECT COALESCE(MIN(position), 1) FROM jobs WHERE state = 'queued'"
            ).fetchone()[0]
            conn.executemany(
                "UPDATE jobs SET position = ? WHERE id = ?",
                [
                    (first + index, job)
                    for index, job in enumerate([*rest[:at], *block, *rest[at:]])
                ],
            )
        return len(block)

    def cancel_all(self) -> int:
        """Cancels everything: every file waiting leaves the queue, then the one converting stops
        as skipping it does (the waiting ones first, so no other starts meanwhile). The files
        themselves stay as they are. Returns how many were cancelled."""
        with closing(db.connect(self._paths.database)) as conn:
            waiting = [row[0] for row in conn.execute("SELECT id FROM jobs WHERE state = 'queued'")]
        cancelled = self.remove_all(waiting)
        with self._lock:
            running = self._job_id
        if running is not None:
            with suppress(LookupError):  # it finished meanwhile
                self.skip(running)
                cancelled += 1
        return cancelled

    def retry(self, job_id: int, quality: Quality | None = None) -> None:
        """A failed or skipped file goes back in the queue, last, unless it waits there for the
        same again already; subtitles at `quality` when it's given ("fast", after Best ran out of
        the card's memory). One made and waiting for its original to be free is tried again now.
        One marked broken is passed over: it's broken."""
        with closing(db.connect(self._paths.database)) as conn, conn:
            if quality is not None:
                conn.execute(
                    """UPDATE jobs SET method = ?
                       WHERE id = ? AND kind = 'subtitles' AND state IN ('failed', 'skipped')""",
                    (quality, job_id),
                )
            due = conn.execute(
                """UPDATE jobs SET retry_at = ?
                   WHERE id = ? AND state = 'queued' AND retry_at IS NOT NULL""",
                (self._now().isoformat(), job_id),
            ).rowcount
            if due:
                self._try_now.set()
                return
            if conn.execute(
                """SELECT 1 FROM jobs AS j JOIN jobs AS other
                       ON other.file_id = j.file_id AND other.kind = j.kind AND other.id != j.id
                   WHERE j.id = ? AND j.state IN ('failed', 'skipped')
                     AND other.state IN ('queued', 'running', 'replacing')""",
                (job_id,),
            ).fetchone():
                return  # asked for again meanwhile: it waits in the queue already
            last: int = conn.execute("SELECT COALESCE(MAX(position), 0) FROM jobs").fetchone()[0]
            again = conn.execute(
                """UPDATE jobs SET state = 'queued', position = ?, problem = NULL, log = NULL,
                          started_at = NULL, finished_at = NULL
                   WHERE id = ? AND state IN ('failed', 'skipped')
                     AND file_id IN (SELECT id FROM files WHERE problem IS NULL)""",
                (last + 1, job_id),
            ).rowcount
        if not again:
            raise LookupError("That file didn't fail and wasn't skipped, or it's broken.")
        self._wake.set()

    def mark_broken(self, job_id: int) -> None:
        """A file whose conversion failed is marked broken: the library counts it among the files
        that won't play, saying why, and it isn't converted again till it changes (a scan reads
        it anew then). Raises LookupError when it didn't fail."""
        with self._lock, closing(db.connect(self._paths.database)) as conn, conn:
            job = conn.execute(
                """UPDATE jobs SET state = 'skipped'
                   WHERE id = ? AND state = 'failed' AND kind = 'convert'
                   RETURNING file_id, problem""",
                (job_id,),
            ).fetchone()
            if job is None:
                raise LookupError("That file didn't fail converting.")
            conn.execute(
                "UPDATE files SET problem = ?, marked_at = ? WHERE id = ?",
                (
                    job["problem"] or "Maku couldn't convert it.",
                    self._now().isoformat(),
                    job["file_id"],
                ),
            )

    def restore(self, job_id: int) -> tuple[SavedChange, ...]:
        """Puts a converted file's original back in its place, and for English from another
        copy, that copy too: returns what couldn't come back. Raises ScanBusyError while a scan
        runs or files move, and ConvertError when it can't."""
        with self._scanner.hold(), closing(db.connect(self._paths.database)) as conn:
            return restore(conn, job_id, now=self._now())

    def status(self) -> QueueStatus:
        with closing(db.connect(self._paths.database)) as conn:
            standard = library_standard(conn)
            speeds, rates = hardware.speeds(conn), hardware.hearing(conn)
            paused = _paused(conn)
            schedule = _schedule(conn)
            stop = _early(conn)
            short = _saved(conn, _SHORT)
            start_of_day = self._now().replace(hour=0, minute=0, second=0, microsecond=0)
            rows = conn.execute(
                f"""{_JOBS}
                    WHERE j.state IN ('queued', 'running', 'replacing') OR j.finished_at >= ?
                    ORDER BY j.position, j.id""",
                (start_of_day.isoformat(),),
            ).fetchall()
            connected = _Drives()
            unmade = [
                row
                for row in rows
                if row["state"] == "queued"
                and row["retry_at"] is None
                and row["kind"] == "convert"
                and connected(row["root"])
            ]
            held = short if paused and isinstance(short, str) else None
            # Paused by the owner, or waiting for the night, files waiting for room don't say
            # so: that's what the queue says.
            resting = schedule == "nights" and not _converting_tonight(self._now(), stop)
            fitting = [] if paused or resting else _fitting(conn)
            with self._lock:
                known = dict(self._needs)
            deleting = originals_deleted(conn)
            room, no_room = _room(unmade, standard, held, fitting, known, deleting=deleting)
            if room is not None:
                found = set_aside_by_drive(conn)
                aside = next((n for d, n in found.items() if _among(d, [room.drive])), 0)
                room = replace(room, set_aside=aside)
        programs = self._programs()
        ready = {
            quality: programs is not None and programs.speech(quality) is not None
            for quality in MODELS
        }
        jobs = [
            replace(
                _job(row, standard, speeds, rates),
                drive_missing=not connected(row["root"]),
                no_room=row["id"] in no_room,
                model_missing=row["kind"] == "subtitles" and not ready.get(row["method"], False),
            )
            if row["state"] == "queued"
            else _job(row, standard, speeds, rates)
            for row in rows
        ]
        with self._lock:
            progress, heard, running_id = self._progress, self._speech, self._job_id
            fps, left = self._fps(), self._hearing_left()
        running: Running | None = None
        for job in jobs:  # the worker's file, before one that waited going in meanwhile
            if job.state in ("running", "replacing") and (running is None or job.id == running_id):
                if job.kind == "subtitles":
                    running = _hearing_now(job, heard if job.id == running_id else None, left)
                else:
                    running = self._running(job, progress if job.id == running_id else None, fps)
        queued = tuple(job for job in jobs if job.state == "queued")
        today = sorted(
            (job for job in jobs if job.finished_at is not None and job.state != "queued"),
            key=lambda job: job.finished_at or "",
            reverse=True,
        )
        left = sum(job.gpu_seconds for job in queued)
        if running is not None:
            left += running.seconds_left if running.seconds_left is not None else 0.0
        problem = self._problem if queued and not paused else None
        now = self._now()
        nights = schedule == "nights"
        ends_at = _tonight_ends(now, stop) if nights and _at_night(now) else None
        return QueueStatus(
            paused,
            schedule,
            nights and not _converting_tonight(now, stop),
            problem,
            running,
            queued,
            left,
            tuple(today),
            room,
            ends_at.isoformat() if ends_at else None,
            nights and _stopping(now, stop),
        )

    def work_once(self) -> bool:
        """Converts the first file waiting, unless the queue is paused or waits for the night.
        False when there was none to convert (or no ffmpeg to convert it with)."""
        with closing(db.connect(self._paths.database)) as conn:
            nights = _schedule(conn) == "nights"
            if _paused(conn) or (nights and not _converting_tonight(self._now(), _early(conn))):
                return False
            programs = self._programs()
            self._problem = None if programs else NO_FFMPEG
            if programs is None or self._checking():
                return False
            # The encoder this PC's check found; before it's checked, NVIDIA's, as Maku always used.
            facts, checked = hardware.stored(conn)
            encoder = checked.encoder if checked is not None else "nvenc"
            # Taken under the lock skip and remove take too, so a file skipped or taken out a
            # moment before never converts; one whose drive isn't connected waits, one made
            # already waits for its original (try_waiting), and one without room waits on a
            # drive where the owner said to convert what fits.
            with self._lock:
                connected, free = _Drives(), _Free()
                waiting = conn.execute(
                    """SELECT j.id, j.kind, j.added_at, j.method, j.file_id, j.other_id, f.path,
                              f.probe, d.path AS root
                       FROM jobs AS j
                       JOIN files AS f ON f.id = j.file_id
                       JOIN folders AS d ON d.id = f.folder_id
                       WHERE j.state = 'queued' AND j.retry_at IS NULL
                       ORDER BY j.position, j.id"""
                ).fetchall()
                fitting = _still_fitting(conn, [job for job in waiting if job["kind"] == "convert"])
                standard = library_standard(conn)
                keys = {(job["id"], job["added_at"]) for job in waiting}
                self._needs = {key: need for key, need in self._needs.items() if key in keys}
                # A result waiting beside its file for another app to let go, or going in: no
                # other is made beside that file (they'd share its name), nor is a copy waiting
                # so given away for its English.
                held = {
                    row[0]
                    for row in conn.execute(
                        """SELECT file_id FROM jobs WHERE state = 'replacing'
                           OR (state = 'queued' AND retry_at IS NOT NULL)"""
                    )
                }

                def goes(job: sqlite3.Row) -> bool:
                    if not connected(job["root"]):
                        return False
                    if job["kind"] == "convert" and encoder is None:
                        return False  # this PC can't: the queue says so
                    if job["kind"] == "subtitles":  # they want next to no room, but their model
                        return programs.speech(job["method"]) is not None
                    if job["file_id"] in held or job["other_id"] in held:
                        return False
                    if job["kind"] == "merge":  # it looks for room itself, as it begins
                        return True
                    if not _among(drive_of(job["path"]), fitting):
                        return True  # converting checks for room, and pauses without it
                    room = free(str(Path(job["path"]).parent))  # where converting measures
                    return room is None or room >= _wanted(job, standard, self._needs)

                converts = any(job["kind"] == "convert" for job in waiting)
                if checked is not None and encoder is None and converts:
                    self._problem = why_not_converting(facts.cards if facts else (), checked)
                first = next((job["id"] for job in waiting if goes(job)), None)
                if first is None:
                    return False
                with conn:
                    row = conn.execute(
                        """UPDATE jobs SET state = 'running', started_at = ?, problem = NULL,
                                  finished_at = NULL
                           WHERE id = ? AND state = 'queued' RETURNING id""",
                        (self._now().isoformat(), first),
                    ).fetchone()
                if row is None:
                    return False
                self._job_id, self._stop_for, self._progress = row["id"], None, None
                self._speech, self._hearing, self._made_at = None, None, None
                self._frames.clear()
            kind = next(job["kind"] for job in waiting if job["id"] == row["id"])
            if kind == "subtitles":
                self._make(conn, row["id"], programs)
            else:
                if kind == "convert":
                    self._listener = None  # the card's memory goes to the conversion
                self._work(conn, row["id"], programs, encoder)
        return True

    def _work(
        self, conn: sqlite3.Connection, job_id: int, programs: Programs, encoder: str | None
    ) -> None:
        merging = conn.execute("SELECT kind FROM jobs WHERE id = ?", (job_id,)).fetchone()[0] == (
            "merge"
        )
        began = self._clock()
        try:
            made = None if merging else _making(conn, job_id)
            with _awake():
                if merging:
                    merge(
                        conn,
                        job_id,
                        programs,
                        now=self._now,
                        report=self._heard,
                        stop=self._stop_asked,
                        discard=self._discard_asked,
                        hold=self._hold,
                    )
                else:
                    convert(
                        conn,
                        job_id,
                        programs,
                        library_standard(conn),
                        now=self._now,
                        report=self._heard,
                        stop=self._stop_asked,
                        discard=self._discard_asked,
                        hold=self._hold,
                        encoder=encoder,
                    )
                    with self._lock:
                        made_at = self._made_at
                    if made is not None and made_at is not None:
                        self._learn_conversion(conn, made, made_at - began)
        except Stopped:
            self._stopped(conn, job_id)
        except NothingToConvert as passed:  # at the standard by its turn: passed over, saying why
            self._finished(conn, job_id, "skipped", str(passed))
        except InUseError as error:
            self._waits(conn, job_id, str(error))
        except NoRoomError as error:
            self._found_wanting(conn, job_id, error.needed)
            self._back_in_line(conn, job_id)  # it, and the rest, wait for room
            if not _among(error.drive, _fitting(conn)):  # there, it waits while the others go
                with conn:
                    _save(conn, _PAUSED, True)
                    _save(conn, _SHORT, error.drive)
                self._notify("The queue paused", str(error), link="/convert/queue")
        except ConvertError as error:
            self._finished(conn, job_id, "failed", str(error), error.log)
        except Exception:
            log.exception("Job %d hit a problem", job_id)
            problem = (
                "Maku hit a problem adding the English."
                if merging
                else "Maku hit a problem converting it."
            )
            self._finished(conn, job_id, "failed", problem)
        finally:
            with self._lock:
                self._job_id, self._stop_for, self._progress = None, None, None
        self._noted(conn, job_id)

    def _learn_conversion(
        self, conn: sqlite3.Connection, made: tuple[Method, MediaInfo], took: float
    ) -> None:
        """How long a file took to make, kept for this PC; the file is done whatever happens."""
        method, media = made
        try:
            hardware.learn_conversion(conn, method, media, took, self._now())
        except Exception:
            log.exception("Keeping how long the file took hit a problem")

    def _make(self, conn: sqlite3.Connection, job_id: int, programs: Programs) -> None:
        quality = conn.execute("SELECT method FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]
        place = hardware.hearing_place(conn, quality)
        began = self._clock()
        try:
            if place is None:
                raise SubtitlesError(best_wants(hardware.checked_here(conn)))
            with _awake():
                make_subtitles(
                    conn,
                    job_id,
                    programs,
                    self._whisper(programs, quality, graphics=place == "card"),
                    now=self._now,
                    report=self._heard_speech,
                    stop=self._stop_asked,
                )
            self._learn_hearing(conn, job_id, quality, place, self._clock() - began)
        except Stopped:
            self._stopped(conn, job_id)
        except OutOfMemory as error:  # Whisper is loaded anew, the card's memory let go
            self._listener = None
            self._finished(conn, job_id, "failed", str(error), error.log)
        except SubtitlesError as error:
            self._finished(conn, job_id, "failed", str(error), error.log)
        except SpeechError as error:  # Whisper couldn't load
            self._listener = None
            self._finished(conn, job_id, "failed", str(error), error.log)
        except Exception:
            log.exception("Making subtitles for job %d hit a problem", job_id)
            self._listener = None  # loaded anew for the next: the card may have gone meanwhile
            self._finished(conn, job_id, "failed", "Maku hit a problem making its subtitles.")
        finally:
            with self._lock:
                self._job_id, self._stop_for, self._speech = None, None, None
        self._noted(conn, job_id)

    def _whisper(self, programs: Programs, quality: str, *, graphics: bool) -> Hearing:
        """Whisper at this quality, on the graphics card or the processor, loaded once while
        subtitles follow subtitles."""
        folder = programs.speech(quality)
        if folder is None:
            raise SubtitlesError("Maku needs its speech model first: download it, then try again.")
        if self._listener is None or self._listener[:2] != (folder, graphics):
            self._listener = None  # one at a time on the card
            self._listener = (folder, graphics, programs.listener(folder, graphics))
        return self._listener[2]

    def _learn_hearing(
        self, conn: sqlite3.Connection, job_id: int, quality: str, place: str, took: float
    ) -> None:
        """How long a video's subtitles took for its sound, kept for this PC: unless no one
        speaks in it, which takes next to no time. They're made whatever happens here."""
        try:
            self._keep_hearing(conn, job_id, quality, place, took)
        except Exception:
            log.exception("Keeping how long the subtitles took hit a problem")

    def _keep_hearing(
        self, conn: sqlite3.Connection, job_id: int, quality: str, place: str, took: float
    ) -> None:
        row = conn.execute(
            """SELECT j.problem, f.probe FROM jobs AS j JOIN files AS f ON f.id = j.file_id
               WHERE j.id = ? AND j.state = 'done'""",
            (job_id,),
        ).fetchone()
        if row is None or row["problem"] is not None or not row["probe"]:
            return
        sound = media_from_ffprobe(json.loads(row["probe"])).duration or 0.0
        key = f"{quality}_processor" if place == "processor" else quality
        hardware.learn_hearing(conn, key, sound, took, self._now())

    def _found_wanting(self, conn: sqlite3.Connection, job_id: int, needed: int) -> None:
        """Remembers the room a file was found to want as converting began, though the queue
        reckoned less: till the reckoning changes (another standard, say), or it leaves."""
        row = conn.execute(
            """SELECT j.id, j.added_at, j.method, f.probe FROM jobs AS j
               JOIN files AS f ON f.id = j.file_id WHERE j.id = ?""",
            (job_id,),
        ).fetchone()
        if row is None:
            return
        reckoned = _reckoned(row, library_standard(conn))
        with self._lock:
            self._needs[(row["id"], row["added_at"])] = (needed, reckoned)

    def _noted(self, conn: sqlite3.Connection, job_id: int) -> None:
        """A file converted (or failed) joins the batch, and once nothing waits, the app is told
        what the batch came to."""
        with self._noting:
            row = conn.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is not None and row["state"] in ("done", "failed"):
                self._batch.append(job_id)
            if self._going_on(conn) or not self._batch:
                return
            marks = ", ".join("?" * len(self._batch))
            rows = conn.execute(
                f"""SELECT j.state, j.kind, j.problem, j.source_size, j.output_size, f.season,
                           f.episode, f.title_id, t.name AS title
                    FROM jobs AS j JOIN files AS f ON f.id = j.file_id
                    LEFT JOIN titles AS t ON t.id = f.title_id
                    WHERE j.id IN ({marks})""",  # noqa: S608 - only placeholders go in
                self._batch,
            ).fetchall()
            self._batch.clear()
        title, body, link = _told(rows)
        self._notify(title, body, link=link)

    def _going_on(self, conn: sqlite3.Connection) -> bool:
        """Whether a job in the queue is still to go: subtitles waiting for a speech model
        that isn't on this PC don't count, nor do conversions on a PC that can't convert, so
        what's done is told meanwhile."""
        programs = self._programs()
        checked = hardware.checked_here(conn)
        stuck = checked is not None and checked.encoder is None

        def waits(row: sqlite3.Row) -> bool:
            if row["kind"] == "subtitles":
                return programs is not None and programs.speech(row["method"]) is not None
            return not (stuck and row["kind"] == "convert" and row["state"] == "queued")

        return any(
            waits(row)
            for row in conn.execute(
                """SELECT kind, method, state FROM jobs
                   WHERE state IN ('queued', 'running', 'replacing')"""
            )
        )

    def try_waiting(self) -> bool:
        """Puts in place each result waiting beside its original for another app to let go of
        it, once it's due: five minutes after the last try, or now when the owner asked. It goes
        in though the queue pauses (it's made), and the worker may be converting another file
        meanwhile. False when none was due."""
        with closing(db.connect(self._paths.database)) as conn:
            due = conn.execute(
                """SELECT j.id, d.path AS root FROM jobs AS j
                   JOIN files AS f ON f.id = j.file_id
                   JOIN folders AS d ON d.id = f.folder_id
                   WHERE j.state = 'queued' AND j.retry_at <= ?
                   ORDER BY j.position, j.id""",
                (self._now().isoformat(),),
            ).fetchall()
            connected = _Drives()
            tried = [job["id"] for job in due if connected(job["root"])]
            for job_id in tried:
                self._put_in(conn, job_id)
        return bool(tried)

    def _put_in(self, conn: sqlite3.Connection, job_id: int) -> None:
        try:
            with self._scanner.hold():
                with self._lock, conn:  # never one skipped or taken out a moment before
                    claimed = conn.execute(
                        """UPDATE jobs SET state = 'replacing'
                           WHERE id = ? AND state = 'queued' AND retry_at IS NOT NULL
                           RETURNING id""",
                        (job_id,),
                    ).fetchone()
                if claimed is None:
                    return
                put_in(conn, job_id, now=self._now())
        except ScanBusyError:
            return  # a scan, or files moving: the next look tries again
        except InUseError as error:
            self._waits(conn, job_id, str(error))
            return
        except ConvertError as error:
            throw_away_kept(conn, job_id)
            self._finished(conn, job_id, "failed", str(error))
        except Exception:
            log.exception("Putting job %d's result in place hit a problem", job_id)
            throw_away_kept(conn, job_id)
            self._finished(conn, job_id, "failed", "Maku hit a problem putting it in place.")
        self._noted(conn, job_id)

    def _waits(self, conn: sqlite3.Connection, job_id: int, problem: str) -> None:
        """A result whose original another app has open waits beside it, its file keeping its
        place in the line, and is tried again in a few minutes. It finished when it was made:
        History says how long that took, not how long it waited."""
        now = self._now()
        with conn:
            conn.execute(
                """UPDATE jobs SET state = 'queued', problem = ?, retry_at = ?,
                          finished_at = COALESCE(finished_at, ?)
                   WHERE id = ?""",
                (problem, (now + IN_USE_WAIT).isoformat(), now.isoformat(), job_id),
            )

    def _stopped(self, conn: sqlite3.Connection, job_id: int) -> None:
        """A file stopped on purpose: skipped, or first in line again (paused, or Maku closing)."""
        with self._lock:
            skipped = self._stop_for == "skip"
        if skipped:
            self._finished(conn, job_id, "skipped", None)
            return
        self._back_in_line(conn, job_id)

    def _back_in_line(self, conn: sqlite3.Connection, job_id: int) -> None:
        """A file that stopped goes back to the queue, first in line."""
        with conn:
            first: int = conn.execute(
                "SELECT COALESCE(MIN(position), 1) FROM jobs WHERE state = 'queued'"
            ).fetchone()[0]
            conn.execute(
                """UPDATE jobs SET state = 'queued', started_at = NULL, position = ?
                   WHERE id = ?""",
                (first - 1, job_id),
            )

    def _finished(
        self,
        conn: sqlite3.Connection,
        job_id: int,
        state: JobState,
        problem: str | None,
        said: str | None = None,
    ) -> None:
        """A job over: done with, failed (why, and what ffmpeg `said`), or skipped."""
        with conn:
            conn.execute(
                """UPDATE jobs SET state = ?, problem = ?, log = ?, finished_at = ?,
                          retry_at = NULL
                   WHERE id = ?""",
                (state, problem, said, self._now().isoformat(), job_id),
            )

    def _heard(self, progress: Progress) -> None:
        with self._lock:
            self._progress = progress
            if progress.stage == "checking" and self._made_at is None:
                self._made_at = self._clock()
            if progress.stage == "converting":
                moment = self._clock()
                self._frames.append((moment, progress.frames))
                while self._frames and moment - self._frames[0][0] > _SPEED_WINDOW:
                    self._frames.popleft()

    def _heard_speech(self, heard: Heard) -> None:
        with self._lock:
            self._speech = heard
            if heard.stage == "listening" and self._hearing is None:
                self._hearing = (self._clock(), heard.done)

    def _hearing_left(self) -> float | None:
        """Seconds the subtitles being made want still, at the pace they've been heard."""
        heard, began = self._speech, self._hearing
        if heard is not None and heard.stage in ("writing", "checking"):
            return 0.0
        if heard is None or began is None or heard.stage != "listening":
            return None
        moment, start = began
        pace = (heard.done - start) / max(self._clock() - moment, 1e-6)
        if pace <= 0:
            return None
        return max(heard.total - heard.done, 0.0) / pace

    def _fps(self) -> float | None:
        """Frames a second over the last ten minutes, once there's a second of them."""
        if len(self._frames) < 2:
            return None
        (began, first), (now, last) = self._frames[0], self._frames[-1]
        return (last - first) / (now - began) if now - began >= 1 and last > first else None

    def _running(self, job: Job, progress: Progress | None, fps: float | None) -> Running:
        if progress is None:
            return Running(
                job, "replacing" if job.state == "replacing" else "looking", 0, 0, None, None
            )
        left: float | None = None
        if progress.stage == "converting" and fps:
            left = max(progress.total - progress.frames, 0) / fps
        elif progress.stage in ("checking", "replacing"):
            left = 0.0
        return Running(job, progress.stage, progress.frames, progress.total, left, fps)

    def _stop_asked(self) -> bool:
        with self._lock:
            return self._stop_for is not None or self._stopping.is_set()

    def _discard_asked(self) -> bool:
        """Whether a result made already is thrown away: skipped, or Maku is closing. Paused,
        it's put in place."""
        with self._lock:
            return self._stop_for == "skip" or self._stopping.is_set()

    @contextmanager
    def _hold(self) -> Generator[None]:
        """Holds scans off while a result takes its original's place, waiting while one runs
        (or a tidy-up moves files)."""
        with ExitStack() as held:
            while True:
                try:
                    held.enter_context(self._scanner.hold())
                    break
                except ScanBusyError:
                    if self._discard_asked():
                        raise Stopped from None
                    self._stopping.wait(_HOLD_RETRY)
            yield

    def _set_paused(self, *, paused: bool) -> None:
        with closing(db.connect(self._paths.database)) as conn, conn:
            _save(conn, _PAUSED, paused)

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                worked = self.work_once()
            except Exception:  # the worker must outlive any one bad file
                log.exception("The conversion queue hit a problem")
                worked = False
            if not worked:
                self._listener = None  # nothing to hear: the card's memory goes back
                self._wake.wait(_IDLE)
                self._wake.clear()

    def _loop_waiting(self) -> None:
        while not self._stopping.is_set():
            try:
                self.try_waiting()
            except Exception:
                log.exception("Putting a waiting result in place hit a problem")
            self._try_now.wait(_WAITING_LOOK)
            self._try_now.clear()


def _told(rows: list[sqlite3.Row]) -> tuple[str, str, str]:
    """What a finished batch is called, what it came to, and where to see it: "The Harbour Line,
    season 1 is done", "39 episodes · all checked · 9.1 GB → 17.5 GB", its title's page (or
    History, for several titles'). Conversions come first, then subtitles, then English from
    other copies; what else the batch held is counted after them."""
    made = [row for row in rows if row["kind"] == "subtitles"]
    merged = [row for row in rows if row["kind"] == "merge"]
    converted = [row for row in rows if row["kind"] == "convert"]
    if converted:
        title, words, link = _told_conversions(converted)
        first = converted
    elif made:
        title, words, link = _told_subtitles(made)
        first = made
    else:
        return _told_merges(merged)
    others = [row for row in rows if row not in first]
    subtitled = sum(1 for row in made if row["state"] == "done" and row["problem"] is None)
    if subtitled and first is not made:
        words += f" · English subtitles for {subtitled}"
    added = sum(1 for row in merged if row["state"] == "done")
    if added:
        words += f" · English added to {added} from another copy"
    if {row["title_id"] for row in others} - {row["title_id"] for row in first}:
        link = "/history"  # they're for another title too
    return title, words, link


def _told_merges(rows: list[sqlite3.Row]) -> tuple[str, str, str]:
    """ "English added from another copy", "Starfall Academy · S02E07 · checked, its other copy
    set aside", History, where both can be put back."""
    done = [row for row in rows if row["state"] == "done"]
    failed = len(rows) - len(done)
    if len(rows) == 1:
        only = rows[0]
        if done:
            return (
                "English added from another copy",
                f"{label_of(only)} · checked, its other copy set aside",
                "/history",
            )
        return (
            "No English added",
            f"{label_of(only)} · {only['problem'] or 'it could not be added'}",
            "/convert/queue",
        )
    count = f"{len(done)} {'video' if len(done) == 1 else 'videos'} · checked"
    words = f"{count} · {failed} couldn't be" if failed else count
    title = "English added from other copies" if done else "No English added"
    return title, words, "/history" if done else "/convert/queue"


def _told_subtitles(rows: list[sqlite3.Row]) -> tuple[str, str, str]:
    """ "Starfall Academy, season 1 has English subtitles", "37 episodes · made from their
    sound", its title's page (or History, for several titles'). A batch that made none says so:
    "No English subtitles for Starfall Academy, season 1", "2 couldn't be made"."""
    titles = {row["title_id"] for row in rows}
    seasons = {row["season"] for row in rows}
    name = rows[0]["title"]
    where: str | None = None
    if len(titles) == 1 and name and len(seasons) == 1 and None not in seasons:
        season = rows[0]["season"]
        where = f"{name}, season {season}" if season else f"{name}, the specials"
    elif len(titles) == 1 and name:
        where = name
    made = [row for row in rows if row["state"] == "done" and row["problem"] is None]
    quiet = sum(1 for row in rows if row["state"] == "done" and row["problem"] is not None)
    failed = len(rows) - len(made) - quiet
    if made:
        title = f"{where} has English subtitles" if where else "English subtitles are ready"
    else:
        title = f"No English subtitles for {where}" if where else "No English subtitles were made"
    what = "episode" if all(row["episode"] is not None for row in rows) else "video"
    parts = [f"{len(made)} {what}{'' if len(made) == 1 else 's'} · made from their sound"]
    if quiet:
        parts.append(f"{quiet} with no one speaking")
    if failed:
        parts.append(f"{failed} couldn't be made")
    words = " · ".join(parts if made else parts[1:])
    [only] = titles if len(titles) == 1 else [None]
    return title, words, f"/titles/{only}" if only is not None else "/history"


def _told_conversions(rows: list[sqlite3.Row]) -> tuple[str, str, str]:
    titles = {row["title_id"] for row in rows}
    seasons = {row["season"] for row in rows}
    name = rows[0]["title"]
    if len(titles) == 1 and name and len(seasons) == 1 and None not in seasons:
        season = rows[0]["season"]
        title = f"{name}, season {season} is done" if season else f"{name}, the specials are done"
    elif len(titles) == 1 and name:
        title = f"{name} is done"
    else:
        title = "The queue is done"
    done = [row for row in rows if row["state"] == "done"]
    failed = len(rows) - len(done)
    what = "episode" if all(row["episode"] is not None for row in rows) else "file"
    if failed:
        count = f"{len(done)} converted, {failed} failed"
    else:
        count = f"{len(done)} {what}{'' if len(done) == 1 else 's'} · all checked"
    before = sum(row["source_size"] or 0 for row in done)
    after = sum(row["output_size"] or 0 for row in done)
    [only] = titles if len(titles) == 1 else [None]
    link = f"/titles/{only}" if only is not None else "/history"
    words = f"{count} · {size_words(before)} → {size_words(after)}"
    return title, words if done else count, link


def programs_from(tools: Tools) -> Programs | None:
    """What the queue runs: Maku's ffmpeg and ffprobe (None until they're downloaded), and the
    speech models, once downloaded."""
    ffmpeg, ffprobe = tools.path("ffmpeg"), tools.path("ffprobe")
    if ffmpeg is None or ffprobe is None:
        return None
    return Programs(
        ffmpeg=[str(ffmpeg)],
        read=lambda path: probe(ffprobe, path),
        speech=lambda quality: tools.folder(MODELS[quality]) if quality in MODELS else None,
        engine=own_command(),
    )


_JOBS = """SELECT j.*, j.sound AS track, f.path, f.probe, f.size, f.season, f.episode,
                  f.title_id, f.sound AS languages, t.name AS title, d.path AS root
           FROM jobs AS j JOIN files AS f ON f.id = j.file_id
           JOIN folders AS d ON d.id = f.folder_id
           LEFT JOIN titles AS t ON t.id = f.title_id"""


def _giving(conn: sqlite3.Connection) -> set[int]:
    """The copies whose English waits to go into the one kept: they're set aside then."""
    return {row[0] for row in conn.execute(GIVING)}


GIVING = """SELECT other_id FROM jobs
   WHERE kind = 'merge' AND other_id IS NOT NULL AND state IN ('queued', 'running', 'replacing')"""


def _waiting_job(conn: sqlite3.Connection, job_id: int) -> bool:
    """Whether a job's result waits beside its original (see try_waiting)."""
    row = conn.execute(
        "SELECT 1 FROM jobs WHERE id = ? AND state = 'queued' AND retry_at IS NOT NULL", (job_id,)
    ).fetchone()
    return row is not None


def _room(
    unmade: list[sqlite3.Row],
    standard: Standard,
    held: str | None,
    fitting: list[str],
    known: dict[tuple[int, str], tuple[int, int]],
    *,
    deleting: bool = False,
) -> tuple[Room | None, set[int]]:
    """The drive without room for what waits on it, of those that matter: the one the queue
    paused for (`held`), else one where files that don't fit wait while the others go
    (`fitting`). With the jobs waiting for room there. `known` holds what files were found to
    want as converting began."""
    by_drive: dict[str, list[sqlite3.Row]] = {}
    for row in unmade:
        by_drive.setdefault(drive_of(row["path"]), []).append(row)
    free = _Free()
    found: Room | None = None
    no_room: set[int] = set()
    for drive, rows in by_drive.items():
        paused = held is not None and _among(drive, [held])
        room = free(str(Path(rows[0]["path"]).parent))  # where converting measures
        if room is None or not (paused or _among(drive, fitting)):
            continue
        needed, fits = _fits(rows, standard, room, known, deleting=deleting)
        if len(fits) == len(rows):
            continue  # room for them all now
        if not paused:
            no_room.update(row["id"] for row in rows if row["id"] not in fits)
        if found is None or (paused and not found.paused):
            found = Room(drive, paused, len(rows), needed, room, len(fits), 0)
    return found, no_room


def _fits(
    rows: list[sqlite3.Row],
    standard: Standard,
    free: int,
    known: dict[tuple[int, str], tuple[int, int]],
    *,
    deleting: bool = False,
) -> tuple[int, set[int]]:
    """Of the files waiting on one drive, in turn: the free space their results all want, and
    those that fit in `free` now, each result taking its size of what's left. When originals
    are deleted as their results take their place (`deleting`), a result wants its room only
    while it's made, and keeps just what it adds over its original: the space wanted is the
    most wanted at any one time."""
    needed, fits, left, kept = 0, set[int](), free, 0
    for row in rows:
        wanted = _wanted(row, standard, known)
        result = round(wanted / SPACE_MARGIN)
        stays = max(0, result - (row["size"] or 0)) if deleting else result
        needed = max(needed, kept + wanted) if deleting else needed + wanted
        kept += stays
        if left >= wanted:
            fits.add(row["id"])
            left -= stays
    return needed, fits


def _wanted(
    row: sqlite3.Row, standard: Standard, known: dict[tuple[int, str], tuple[int, int]]
) -> int:
    """The free space a waiting file's result wants on its drive, as converting checks; or what
    converting found it wants (`known`), when that's more and the reckoning hasn't changed."""
    reckoned = _reckoned(row, standard)
    found = known.get((row["id"], row["added_at"]))
    if found is not None and found[1] == reckoned:
        return max(reckoned, found[0])
    return reckoned


def _reckoned(row: sqlite3.Row, standard: Standard) -> int:
    """The free space a waiting file's result wants on its drive, as the queue reckons it."""
    if row["probe"] is None:
        return 0
    media = media_from_ffprobe(json.loads(row["probe"]))
    return room_for(media, decide(media, standard))


def _fitting(conn: sqlite3.Connection) -> list[str]:
    saved = _saved(conn, _FITTING)
    drives = cast("list[object]", saved) if isinstance(saved, list) else []
    return [drive for drive in drives if isinstance(drive, str)]


def _still_fitting(conn: sqlite3.Connection, waiting: list[sqlite3.Row]) -> list[str]:
    """The drives where files without room wait while the others go, but only those where one
    still waits: on the others, a file without room pauses the queue again, to ask."""
    fitting = _fitting(conn)
    there = [drive_of(row["path"]) for row in waiting]
    kept = [drive for drive in fitting if _among(drive, there)]
    if kept != fitting:
        with conn:
            _save(conn, _FITTING, kept)
    return kept


def _among(drive: str, drives: Iterable[str]) -> bool:
    return drive.casefold() in {other.casefold() for other in drives}


class _Free:
    """Bytes free where files are (a file's folder can be another volume, mounted there), each
    folder looked at once; None for one that isn't there."""

    def __init__(self) -> None:
        self._seen: dict[str, int | None] = {}

    def __call__(self, folder: str) -> int | None:
        if folder not in self._seen:
            try:
                self._seen[folder] = shutil.disk_usage(folder).free
            except OSError:
                self._seen[folder] = None
        return self._seen[folder]


class _Drives:
    """Whether library folders are there (a drive plugged in), each looked at once."""

    def __init__(self) -> None:
        self._seen: dict[str, bool] = {}

    def __call__(self, folder: str) -> bool:
        if folder not in self._seen:
            self._seen[folder] = Path(folder).is_dir()
        return self._seen[folder]


def _job(
    row: sqlite3.Row,
    standard: Standard,
    speeds: Speeds | None = None,
    rates: dict[str, float] | None = None,
) -> Job:
    """A job as the queue shows it. One still to finish gets what suits its file, with an
    estimate at this PC's `speeds` (or `rates`, for subtitles); a finished one says what it got
    (its file's record is the result's now), and so does one whose file is at the standard by
    now (the standard changed since it joined): it's passed over when its turn comes."""
    if row["kind"] == "subtitles":
        return _subtitles_job(row, rates)
    if row["kind"] == "merge":
        return _merge_job(row)
    method = Method(row["method"])
    gpu_seconds = 0.0
    width = height = None
    if row["probe"] and row["state"] in ("queued", "running", "replacing"):
        media = media_from_ffprobe(json.loads(row["probe"]))
        decision = decide(media, standard)
        if decision.method in CONVERTED:
            method, width, height = decision.method, decision.width, decision.height
            if row["retry_at"] is None:  # one waiting for its original is made already
                gpu_seconds = estimate(media, decision, speeds).gpu_seconds
    return Job(
        id=row["id"],
        file_id=row["file_id"],
        path=row["path"],
        label=label_of(row),
        title_id=row["title_id"],
        title=row["title"],
        season=row["season"],
        episode=row["episode"],
        method=method,
        state=row["state"],
        position=row["position"],
        gpu_seconds=gpu_seconds,
        added_at=row["added_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        problem=row["problem"],
        source_size=row["source_size"] or row["size"],
        output_size=row["output_size"],
        width=width,
        height=height,
        retry_at=row["retry_at"],
        log=row["log"] if row["state"] == "failed" else None,
    )


def _subtitles_job(row: sqlite3.Row, rates: dict[str, float] | None = None) -> Job:
    """English subtitles as the queue shows them, with how long hearing the video takes here."""
    seconds = 0.0
    if row["probe"]:
        seconds = media_from_ffprobe(json.loads(row["probe"])).duration or 0.0
    sound = _languages(row["languages"])
    track = row["track"] or 0
    return Job(
        id=row["id"],
        file_id=row["file_id"],
        path=row["path"],
        label=label_of(row),
        title_id=row["title_id"],
        title=row["title"],
        season=row["season"],
        episode=row["episode"],
        method=_quality(row["method"]),
        state=row["state"],
        position=row["position"],
        gpu_seconds=hearing(seconds, row["method"], rates or HEARING)
        if row["state"] in ("queued", "running")
        else 0,
        added_at=row["added_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        problem=row["problem"],
        source_size=row["size"] or 0,
        output_size=row["output_size"],
        log=row["log"] if row["state"] == "failed" else None,
        kind="subtitles",
        language=sound[track] if track < len(sound) else "",
        fast_instead=row["state"] == "failed"
        and row["method"] == "best"
        and row["problem"] in _FAST_INSTEAD,
    )


def _merge_job(row: sqlite3.Row) -> Job:
    """English from another copy as the queue shows it: a minute or two, on no graphics card."""
    going = row["state"] in ("queued", "running", "replacing") and row["retry_at"] is None
    return Job(
        id=row["id"],
        file_id=row["file_id"],
        path=row["path"],
        label=label_of(row),
        title_id=row["title_id"],
        title=row["title"],
        season=row["season"],
        episode=row["episode"],
        method=Method.REMUX,
        state=row["state"],
        position=row["position"],
        gpu_seconds=merging(row["size"] or 0) if going else 0.0,
        added_at=row["added_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        problem=row["problem"],
        source_size=row["source_size"] or row["size"] or 0,
        output_size=row["output_size"],
        retry_at=row["retry_at"],
        log=row["log"] if row["state"] == "failed" else None,
        kind="merge",
    )


def _making(conn: sqlite3.Connection, job_id: int) -> tuple[Method, MediaInfo] | None:
    """What a conversion is about to make: its way, and its original."""
    row = conn.execute(
        """SELECT f.probe FROM jobs AS j JOIN files AS f ON f.id = j.file_id WHERE j.id = ?""",
        (job_id,),
    ).fetchone()
    if row is None or not row["probe"]:
        return None
    media = media_from_ffprobe(json.loads(row["probe"]))
    return decide(media, library_standard(conn)).method, media


def _quality(stored: str) -> Quality:
    """Subtitles' quality, as their job keeps it in its method."""
    return "fast" if stored == "fast" else "best"


def _hearing_now(job: Job, heard: Heard | None, left: float | None) -> Running:
    """Subtitles being made, and how far: seconds of the video heard."""
    if heard is None:
        return Running(job, "looking", 0, 0, None, None)
    return Running(job, heard.stage, round(heard.done), round(heard.total), left, None)


def _languages(stored: str | None) -> list[str]:
    try:
        found: object = json.loads(stored) if stored else []
    except ValueError:
        return []
    return [str(each) for each in cast("list[object]", found)] if isinstance(found, list) else []


def _paused(conn: sqlite3.Connection) -> bool:
    return _saved(conn, _PAUSED) is True


def _schedule(conn: sqlite3.Connection) -> Schedule:
    return "nights" if _saved(conn, _SCHEDULE) == "nights" else "now"


def _at_night(moment: datetime) -> bool:
    start, end = NIGHT
    return moment.time() >= start or moment.time() < end


def _early(conn: sqlite3.Connection) -> datetime | None:
    """When a night's run stops early, as the owner asked, if they did."""
    saved = _saved(conn, _EARLY)
    return datetime.fromisoformat(saved) if isinstance(saved, str) else None


def _early_stop(now: datetime) -> datetime:
    """When "Stop at 03:00" ends a night's run: this morning's 03:00, now when that's past, or by
    day the coming night's."""
    three = now.replace(hour=EARLY.hour, minute=EARLY.minute, second=0, microsecond=0)
    if now.time() < EARLY:
        return three
    if now.time() < NIGHT[1]:
        return now
    return three + timedelta(days=1)


def _stopping(now: datetime, stop: datetime | None) -> bool:
    """Whether the night `now` is in stops early: `stop` falls in it, before its 07:00. Nights
    are told apart by their dates, so a clock change that night doesn't lose it."""
    return stop is not None and _morning(now).date() == _morning(stop).date()


def _converting_tonight(now: datetime, stop: datetime | None) -> bool:
    """Whether the nights-only schedule starts files now: at night, and not past an early stop."""
    return _at_night(now) and not (_stopping(now, stop) and stop is not None and now >= stop)


def _tonight_ends(now: datetime, stop: datetime | None) -> datetime:
    """When the night `now` is in takes its last file: its 07:00, or an early stop in it."""
    return stop if stop is not None and _stopping(now, stop) else _morning(now)


def _morning(moment: datetime) -> datetime:
    """The 07:00 that ends the night a moment is in (or, by day, the coming night)."""
    seven = moment.replace(hour=NIGHT[1].hour, minute=0, second=0, microsecond=0)
    return seven if moment.time() < NIGHT[1] else seven + timedelta(days=1)


def _saved(conn: sqlite3.Connection, key: str) -> object:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None


def _save(conn: sqlite3.Connection, key: str, value: object) -> None:
    """One of the queue's settings rows, inside the caller's transaction."""
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )


@contextmanager
def _awake() -> Generator[None]:
    """Keeps Windows from sleeping while a file converts (the display may still turn off)."""
    if sys.platform != "win32":
        yield
        return
    continuous, system = 0x80000000, 0x00000001  # ES_CONTINUOUS, ES_SYSTEM_REQUIRED
    kernel = ctypes.windll.kernel32
    kernel.SetThreadExecutionState(continuous | system)
    try:
        yield
    finally:
        kernel.SetThreadExecutionState(continuous)
