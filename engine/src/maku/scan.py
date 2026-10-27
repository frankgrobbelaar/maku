"""The scan: finds every video in the library folders, reads each one with ffprobe, identifies
which series or film and episode it is (maku/identify.py), then checks the library.

One scan runs at a time, on a background thread with its own database connection. The scans
table holds where it is, and everything it learns is saved as it goes, so a scan that's paused, or
stopped by an exit or a crash, carries on where it was (`recover` at start). Later scans only read
new and changed files. Nothing in the folders changes: a scan only looks. While Maku moves files
(a tidy-up, a converted file taking its original's place), no scan starts (`hold`): it would see
them half moved.
"""

import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Generator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Literal

from maku import db
from maku.catalog import Catalog
from maku.config import DataPaths
from maku.core.library import time_left
from maku.core.media import Json
from maku.identify import Identifier
from maku.leftovers import sweep
from maku.library import find_files, folders, read_file, unread
from maku.probe import ProbeToolError, probe
from maku.reports import write_reports
from maku.tools import Tools
from maku.web import Send, send

log = logging.getLogger(__name__)

_STOPPING = 0.5  # seconds a resume waits for a scan that's still stopping for a pause
_SETTLING = 3.0  # seconds after Maku moves files that what Windows tells of them is Maku's doing

type State = Literal["idle", "running", "paused", "done", "failed"]
type Stage = Literal["finding", "reading", "identifying", "checking", "done"]


class ScanBusyError(Exception):
    """A scan is running, so another can't start and files can't move."""

    def __init__(self, message: str = "A scan is running.") -> None:
        super().__init__(message)


class MovingFilesError(ScanBusyError):
    """Maku is moving files, so no scan starts until they're in place."""

    def __init__(self) -> None:
        super().__init__("Maku is moving files.")


class _NoReaderError(Exception):
    """There's no ffprobe to read the files with."""


@dataclass(frozen=True)
class ScanStatus:
    state: State
    stage: Stage | None
    started_at: str | None
    finished_at: str | None
    found: int  # videos this scan found
    to_read: int  # of those, the new and changed ones to read
    read: int
    problems: int  # files in the library that couldn't be read
    current: str | None  # the file being looked at now
    seconds_left: float | None
    unavailable: tuple[str, ...]  # library folders that aren't there (a drive unplugged)
    problem: str | None  # why the scan stopped, when it failed
    titles: int = 0  # series and films identified in the library
    waiting: int = 0  # files that need the owner to say which series or film they are
    note: str | None = None  # what the scan couldn't do, though it finished
    mixed: int = 0  # folders holding more than one series or film
    # Videos this scan found that weren't there before, and videos it found gone; None for a
    # scan from before Maku counted.
    added: int | None = None
    gone: int | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Scanner:
    """Runs scans and says how the latest one is going. One per engine."""

    def __init__(
        self,
        paths: DataPaths,
        tools: Tools,
        *,
        read: Callable[[Path], Json] | None = None,
        now: Callable[[], datetime] = _utc_now,
        transport: Send = send,
        catalog: Catalog | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._paths = paths
        self._tools = tools
        self._read = read
        self._now = now
        self._clock = clock
        self._settled_at = 0.0  # what Windows tells of before this is Maku's own doing
        self._identifier = Identifier(paths, transport, now=now, catalog=catalog)
        self._lock = threading.Lock()
        self._pause = threading.Event()
        self._thread: threading.Thread | None = None
        self._held = False  # Maku is moving files
        self._current: str | None = None  # the file, or the title, being looked at
        self._reading_since: float | None = None
        self._read_live = 0
        self._to_read_live = 0

    def status(self) -> ScanStatus:
        with closing(db.connect(self._paths.database)) as conn:
            return self._status(conn)

    def start(self) -> ScanStatus:
        """Starts a new scan of every library folder."""
        with self._lock:
            self._not_busy()
            self._pause.clear()
            started = self._now().isoformat()
            with closing(db.connect(self._paths.database)) as conn, conn:
                # Files that couldn't be read get another try: the cause may have passed. One
                # the owner marked broken stays so till it changes.
                conn.execute(
                    "UPDATE files SET probed_at = NULL"
                    " WHERE problem IS NOT NULL AND gone_at IS NULL AND marked_at IS NULL"
                )
                scan_id: int = conn.execute(
                    "INSERT INTO scans (started_at, state, stage) VALUES (?, 'running', 'finding') "
                    "RETURNING id",
                    (started,),
                ).fetchone()[0]
            self._launch(scan_id, started, "finding")
        return self.status()

    def pause(self) -> None:
        """Stops the running scan after the file it's on. `resume` carries on from there."""
        self._pause.set()

    def resume(self) -> ScanStatus:
        """Carries on a paused scan, or keeps a running one going."""
        with self._lock:
            if self._held:
                raise MovingFilesError
            was_paused = self._pause.is_set()
            self._pause.clear()
            if was_paused and self._thread is not None:
                # It may have seen the pause just before it was cleared, and be stopping now:
                # let it finish (one file at most), then start it again if it did stop.
                self._thread.join(timeout=_STOPPING)
            if not self._running():
                self._carry_on(states=("paused", "running"))
        return self.status()

    def recover(self) -> None:
        """At start: carries on a scan an exit or a crash stopped. A paused one stays paused."""
        with self._lock:
            self._carry_on(states=("running",))

    @contextmanager
    def hold(self) -> Generator[None]:
        """Keeps scans from starting while Maku moves files. Raises ScanBusyError when a scan is
        running, or when files are moving already."""
        with self._lock:
            self._not_busy()
            self._held = True
        try:
            yield
        finally:
            with self._lock:
                self._held = False
                self._settled_at = self._clock() + _SETTLING

    def moving(self) -> bool:
        """Whether Maku is moving files, or was a moment ago: what Windows tells of them then is
        Maku's own doing, which its records follow already (the watcher starts no scan for it)."""
        with self._lock:
            return self._held or self._clock() < self._settled_at

    def wait(self, timeout: float | None = None) -> None:
        if thread := self._thread:
            thread.join(timeout)

    def _running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _not_busy(self) -> None:
        if self._held:
            raise MovingFilesError
        if self._running():
            raise ScanBusyError

    def _carry_on(self, states: tuple[str, ...]) -> None:
        with closing(db.connect(self._paths.database)) as conn:
            latest = conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
            if latest is None or latest["state"] not in states:
                return
            with conn:
                conn.execute("UPDATE scans SET state = 'running' WHERE id = ?", (latest["id"],))
        self._launch(latest["id"], latest["started_at"], latest["stage"])

    def _launch(self, scan_id: int, started: str, stage: Stage) -> None:
        self._thread = threading.Thread(
            target=self._run, args=(scan_id, started, stage), name="scan", daemon=True
        )
        self._thread.start()

    def _run(self, scan_id: int, started: str, stage: Stage) -> None:
        with closing(db.connect(self._paths.database)) as conn:
            try:
                if stage == "finding":
                    if not self._find(conn, started):
                        return self._stop(conn, scan_id, "finding")
                    stage = "reading"
                    _set(conn, scan_id, stage=stage)
                if stage == "reading":
                    if not self._read_all(conn):
                        return self._stop(conn, scan_id, "reading")
                    stage = "identifying"
                    _set(conn, scan_id, stage=stage)
                if stage == "identifying":
                    identified = self._identifier.run(
                        conn, stop=self._pause.is_set, looking_at=self._looking_at
                    )
                    if identified is None:
                        return self._stop(conn, scan_id, "identifying")
                    _set(conn, scan_id, stage="checking", note=identified.note)
                # Checking: the gap analysis next to each series that has a folder of its own.
                written = write_reports(conn, now=self._now())
                note = " ".join(written.problems) or None
                added, gone = _changes(conn, started)
                _set(
                    conn,
                    scan_id,
                    state="done",
                    stage="done",
                    finished_at=self._now().isoformat(),
                    note=note,
                    added=added,
                    gone=gone,
                )
            except _NoReaderError:
                _set(conn, scan_id, state="failed", problem=_NEEDS_FFMPEG)
            except ProbeToolError as error:
                log.error("ffprobe didn't work: %s", error)
                self._tools.broken("ffmpeg")  # so Setup offers to download it again
                _set(conn, scan_id, state="failed", problem=_ffprobe_broke(error))
            except Exception as error:
                log.exception("The scan stopped")
                _set(conn, scan_id, state="failed", problem=_stopped_by(error))
            finally:
                self._current = None
                self._reading_since = None
        return None

    def _find(self, conn: sqlite3.Connection, started: str) -> bool:
        """Walks every library folder, including any added while it walks. False when a pause
        stopped it."""
        walked: set[int] = set()
        while waiting := [folder for folder in folders(conn) if folder.id not in walked]:
            for folder in waiting:
                walked.add(folder.id)
                found = find_files(
                    conn, folder, stamp=started, on_file=self._looking_at, stop=self._pause.is_set
                )
                if self._pause.is_set():
                    return False
                if found is not None:
                    for problem in found.problems:
                        log.warning("%s", problem)
                    sweep(conn, found.leftovers)
        return True

    def _read_all(self, conn: sqlite3.Connection) -> bool:
        """Reads every file still to read. False when a pause stopped it."""
        missing = [
            PureWindowsPath(folder.path) for folder in folders(conn) if not folder.path.is_dir()
        ]
        todo = [
            (file_id, path)
            for file_id, path in unread(conn)
            if not any(PureWindowsPath(path).is_relative_to(folder) for folder in missing)
        ]
        if not todo:
            return True
        read = self._reader()
        self._to_read_live, self._read_live = len(todo), 0
        self._reading_since = time.monotonic()
        for file_id, path in todo:
            if self._pause.is_set():
                return False
            self._looking_at(path)
            if path.is_file():
                read_file(conn, file_id, path, read, now=self._now())
            elif path.parent.is_dir():  # its folder is there and it isn't: it's gone
                with conn:
                    conn.execute(
                        "UPDATE files SET gone_at = ? WHERE id = ?",
                        (self._now().isoformat(), file_id),
                    )
            # else its folder went too (a drive dropping out, say): the next scan looks again
            self._read_live += 1
        return True

    def _reader(self) -> Callable[[Path], Json]:
        if self._read is not None:
            return self._read
        ffprobe = self._tools.path("ffprobe")
        if ffprobe is None:
            raise _NoReaderError
        return lambda path: probe(ffprobe, path)

    def _looking_at(self, what: Path | str) -> None:
        self._current = str(what)

    def _stop(self, conn: sqlite3.Connection, scan_id: int, stage: Stage) -> None:
        _set(conn, scan_id, state="paused", stage=stage)

    def _status(self, conn: sqlite3.Connection) -> ScanStatus:
        latest = conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        unavailable = tuple(str(f.path) for f in folders(conn) if not f.path.is_dir())
        problems: int = conn.execute(
            "SELECT COUNT(*) FROM files WHERE problem IS NOT NULL AND gone_at IS NULL"
        ).fetchone()[0]
        titles, waiting_owner = conn.execute(
            """SELECT (SELECT COUNT(DISTINCT title_id) FROM files
                       WHERE title_id IS NOT NULL AND gone_at IS NULL),
                      (SELECT COUNT(*) FROM files
                       WHERE matched IN ('unsure', 'none') AND gone_at IS NULL)"""
        ).fetchone()
        if latest is None:
            return ScanStatus(
                "idle", None, None, None, 0, 0, 0, problems, None, None, unavailable, None
            )
        started: str = latest["started_at"]
        found, read, waiting, added, gone = conn.execute(
            f"""SELECT
                  COUNT(*) FILTER (WHERE seen_at = :started AND gone_at IS NULL),
                  COUNT(*) FILTER (WHERE probed_at >= :started AND seen_at = :started),
                  COUNT(*) FILTER (WHERE probed_at IS NULL AND gone_at IS NULL),
                  {_CHANGES}
                FROM files""",  # noqa: S608 - a fixed fragment, no values
            {"started": started},
        ).fetchone()
        if latest["added"] is not None:  # kept when it finished
            added, gone = latest["added"], latest["gone"]
        elif latest["state"] not in ("running", "paused"):
            added = gone = None  # finished before Maku counted

        running = latest["state"] == "running" and self._running()
        state: State = latest["state"] if latest["state"] != "running" or running else "paused"
        left = None
        if running and self._reading_since is not None:
            elapsed = time.monotonic() - self._reading_since
            left = time_left(self._read_live, self._to_read_live, elapsed)
        current = self._current if running else None
        return ScanStatus(
            state=state,
            stage=latest["stage"],
            started_at=started,
            finished_at=latest["finished_at"],
            found=found,
            to_read=read + waiting,
            read=read,
            problems=problems,
            current=current,
            seconds_left=left,
            unavailable=unavailable,
            problem=latest["problem"],
            titles=titles,
            waiting=waiting_owner,
            note=latest["note"],
            mixed=_mixed_folders(conn),
            added=added,
            gone=gone,
        )


_NEEDS_FFMPEG = "Maku needs ffmpeg to read the files it found. Download it, then scan again."


# What the scan that started at :started changed: the videos it found that weren't there
# before and still are, and those it found gone (a video that came and went while it ran is
# neither).
_CHANGES = """COUNT(*) FILTER (WHERE found_at = :started AND gone_at IS NULL),
              COUNT(*) FILTER (WHERE gone_at = :started)"""


def _changes(conn: sqlite3.Connection, started: str) -> tuple[int, int]:
    """What the scan that started at `started` changed: videos new, and videos gone."""
    added, gone = conn.execute(
        f"SELECT {_CHANGES} FROM files",  # noqa: S608 - a fixed fragment, no values
        {"started": started},
    ).fetchone()
    return added, gone


def _mixed_folders(conn: sqlite3.Connection) -> int:
    """Folders whose videos belong to more than one series or film, as a mixed Downloads folder
    does."""
    titles_in: dict[str, set[int]] = {}
    for row in conn.execute(
        "SELECT path, title_id FROM files WHERE title_id IS NOT NULL AND gone_at IS NULL"
    ):
        titles_in.setdefault(str(PureWindowsPath(row["path"]).parent), set()).add(row["title_id"])
    return sum(1 for titles in titles_in.values() if len(titles) > 1)


def _ffprobe_broke(error: ProbeToolError) -> str:
    return (
        f"ffprobe couldn't run ({error}), so Maku stopped the scan without marking any file. "
        "Get ffmpeg again in Setup, then scan again."
    )


def _stopped_by(error: Exception) -> str:
    return (
        f"The scan stopped: {error}. Nothing in your folders was touched; scan again to carry on."
    )


def _set(
    conn: sqlite3.Connection,
    scan_id: int,
    *,
    state: str | None = None,
    stage: str | None = None,
    finished_at: str | None = None,
    problem: str | None = None,
    note: str | None = None,
    added: int | None = None,
    gone: int | None = None,
) -> None:
    with conn:
        conn.execute(
            """UPDATE scans SET state = COALESCE(?, state), stage = COALESCE(?, stage),
                                finished_at = COALESCE(?, finished_at), problem = ?,
                                note = COALESCE(?, note), added = COALESCE(?, added),
                                gone = COALESCE(?, gone)
               WHERE id = ?""",
            (state, stage, finished_at, problem, note, added, gone, scan_id),
        )
