"""Keeping the library current while Maku is open.

- At start, a scan catches up on what changed while Maku was closed (once setup is done).
- The library folders are watched: when a video is added, removed or renamed, a scan starts once
  the folder has been quiet for a few seconds (a season still copying waits until it's done),
  looked for every second while a change waits.
- Episode lists are asked for again on schedule: every hour for shows still airing, every week
  for finished ones (maku/identify.py decides when one is due), and the gap reports follow.
- The rest of each film's collection is looked up on TMDB a few entries at a time, and each
  entry asked about again weekly, or daily while it airs (maku/franchises.py).
- On the day an episode of one of the library's shows airs, the owner is told (maku/coming.py).

Nothing here runs while a scan does, and a scan the owner paused stays paused.
"""

import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers.api import DEFAULT_OBSERVER_TIMEOUT, BaseObserver
from watchdog.observers.read_directory_changes import WindowsApiEmitter

from maku import coming, credentials, db, franchises
from maku.cache import Cache
from maku.catalog import Catalog
from maku.config import DataPaths
from maku.core.catalog import TitleKind
from maku.core.extensions import is_video
from maku.events import Notify
from maku.identify import AIRING_EVERY, due, save_film, save_show
from maku.reports import write_reports
from maku.scan import ScanBusyError, ScanStatus
from maku.tmdb import Tmdb
from maku.web import Send, WebError

log = logging.getLogger(__name__)

QUIET = 5.0  # seconds without a change before a scan starts
TICK = 15.0  # how often the watcher looks around
SOON = 1.0  # how often, while a change waits for its scan


class Scans(Protocol):
    """What the watcher needs of the scanner (maku/scan.py)."""

    def start(self) -> ScanStatus: ...

    def status(self) -> ScanStatus: ...

    def moving(self) -> bool: ...


class Watcher:
    def __init__(
        self,
        paths: DataPaths,
        scanner: Scans,
        transport: Send,
        *,
        now: Callable[[], datetime],
        clock: Callable[[], float] = time.monotonic,
        catalog: Catalog | None = None,
        notify: Notify | None = None,
    ) -> None:
        self._paths = paths
        self._notify = notify
        self._scanner = scanner
        self._transport = transport
        self._now = now
        self._catalog = catalog or Catalog(paths, transport, cache=Cache(paths.cache))
        self._clock = clock
        self._lock = threading.Lock()
        self._changed_at: float | None = None  # when a video last changed, not yet scanned
        self._watched: dict[str, BaseObserver] = {}
        self._resting_until: datetime | None = None  # after a failed refresh, asked again then
        self._looking_rests_until: datetime | None = None  # the same, for the franchises' rest
        self._stopping = threading.Event()
        self._wake = threading.Event()  # a change noticed, or stopping
        self._refreshed_at = float("-inf")  # when episode lists were last looked at
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Catches up, then watches until `stop`."""
        self.catch_up()
        self._thread = threading.Thread(target=self._loop, name="watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        for observer in self._watched.values():
            observer.stop()
        self._watched.clear()

    def catch_up(self) -> bool:
        """Starts a scan for what changed while Maku was closed. False when it didn't: setup isn't
        done, there are no folders, or a scan is running or paused."""
        with closing(db.connect(self._paths.database)) as conn:
            set_up = conn.execute("SELECT value FROM settings WHERE key = 'set_up'").fetchone()
            has_folders = conn.execute("SELECT 1 FROM folders LIMIT 1").fetchone() is not None
        if set_up is None or set_up["value"] != "true" or not has_folders:
            return False
        if self._scanner.status().state in ("running", "paused"):
            return False
        return self._start_scan()

    def notice(self) -> None:
        """A video changed in a library folder. Maku's own moves (a tidy-up, a converted file
        taking its original's place) start no scan: the library's records follow them already."""
        if self._scanner.moving():
            return
        self._changed()

    def _changed(self) -> None:
        with self._lock:
            self._changed_at = self._clock()
        self._wake.set()

    @property
    def pending(self) -> bool:
        """A change was noticed and hasn't been scanned yet."""
        with self._lock:
            return self._changed_at is not None

    @property
    def settling(self) -> bool:
        """A change was noticed and its folder hasn't been quiet long enough to scan yet."""
        with self._lock:
            changed = self._changed_at
        return changed is not None and self._clock() - changed < QUIET

    def tick(self) -> None:
        """One look around: follow the folders, scan after changes, refresh due episode lists."""
        self._follow_folders()
        with self._lock:
            changed = self._changed_at
        if changed is not None and self._clock() - changed >= QUIET:
            state = self._scanner.status().state
            if state == "paused":
                return  # the owner paused it: the changes wait for them
            if self._start_scan():
                with self._lock:
                    if self._changed_at == changed:
                        self._changed_at = None
            return
        # Episode lists, at most once a look-around, a folder still changing or not.
        if self._clock() - self._refreshed_at < TICK:
            return
        self._refreshed_at = self._clock()
        if self._scanner.status().state != "running":
            self.refresh()
            if not self.pending:  # a change's scan never waits on TMDB
                self.look_further()
        try:
            self.tell_aired()
        except sqlite3.Error as error:  # the records busy a moment: told at the next look
            log.info("What's out today couldn't be told now: %s", error)

    def refresh(self) -> int:
        """Asks again for the episode lists that are due, of the titles the library holds a
        video of, then refreshes the reports. Returns how many lists were asked for. Offline or
        refused, every list waits an hour; a show TMDB no longer has waits until it's due
        again."""
        if self._resting_until is not None and self._now() < self._resting_until:
            return 0
        key = credentials.load(self._paths, "tmdb")
        cache = Cache(self._paths.cache)
        tmdb = Tmdb(key, self._transport, cache=cache) if key else None
        asked = 0
        with closing(db.connect(self._paths.database)) as conn:
            rows = conn.execute(
                """SELECT * FROM titles AS t
                   WHERE checked_at IS NOT NULL
                     AND EXISTS (SELECT 1 FROM files AS f
                                 WHERE f.title_id = t.id AND f.gone_at IS NULL)"""
            ).fetchall()
            for row in rows:
                if not due(row, self._now()):
                    continue
                try:
                    found = self._ask(conn, row, tmdb)
                except WebError as error:
                    log.info("An episode list couldn't be refreshed now: %s", error)
                    self._resting_until = self._now() + AIRING_EVERY
                    break  # offline or busy: everything waits for the next hour
                if found:
                    asked += 1
                elif found is False:  # gone from TMDB: not again until it's due
                    with conn:
                        conn.execute(
                            "UPDATE titles SET checked_at = ? WHERE id = ?",
                            (self._now().isoformat(), row["id"]),
                        )
            if asked:
                write_reports(conn, now=self._now())
        return asked

    def tell_aired(self) -> int:
        """Tells the owner of the episodes out today that the library hasn't got, once each.
        Returns how many."""
        if self._notify is None:
            return 0
        now = self._now()
        with closing(db.connect(self._paths.database)) as conn:
            found = coming.out_today(conn, now.date(), now.isoformat())
        said = coming.told(found)
        if said:
            title, line, link = said
            self._notify(title, line, link=link)
        return len(found)

    def look_further(self) -> int:
        """Asks TMDB about a few more entries of the library's franchises
        (maku/franchises.py). Returns how many. Offline or refused, they wait an hour, as
        episode lists do."""
        resting = self._looking_rests_until
        if resting is not None and self._now() < resting:
            return 0
        with closing(db.connect(self._paths.database)) as conn:
            try:
                return franchises.look_up(conn, self._catalog, self._now())
            except WebError as error:
                log.info("The rest of a franchise couldn't be looked up now: %s", error)
                self._looking_rests_until = self._now() + AIRING_EVERY
                return 0

    def _ask(self, conn: sqlite3.Connection, row: sqlite3.Row, tmdb: Tmdb | None) -> bool | None:
        """Asks again for one title's episode list, or a film's facts: True when it came, False
        when TMDB no longer has it, None when there's no one to ask (while Maku has no key)."""
        if tmdb is None or row["tmdb_id"] is None:
            return None
        if row["tmdb_type"] == "tv":
            show = tmdb.show(row["tmdb_id"])
            if show is None:
                return False
            save_show(conn, show, TitleKind(row["kind"]), row["entry_id"], self._now())
            return True
        film = tmdb.film(row["tmdb_id"])
        if film is None:
            return False
        save_film(conn, film, row["entry_id"], self._now())
        return True

    def _loop(self) -> None:
        while not self._stopping.is_set():
            # A change wakes the watcher; it then looks every second till the folder is quiet.
            # A change that can't be scanned yet (a scan running, or paused by the owner) is
            # looked at again with everything else.
            if self.settling:
                if self._stopping.wait(SOON):
                    return
            else:
                self._wake.wait(TICK)
            self._wake.clear()
            if self._stopping.is_set():
                return
            try:
                self.tick()
            except Exception:  # the watcher must outlive any one bad look around
                log.exception("Watching the library hit a problem")

    def _start_scan(self) -> bool:
        try:
            self._scanner.start()
        except ScanBusyError:
            return False
        return True

    def _follow_folders(self) -> None:
        """Watches every library folder that's there, stops watching forgotten ones, and watches
        a folder again when it comes back (a drive plugged in again): Windows stops telling
        about a folder once it goes."""
        with closing(db.connect(self._paths.database)) as conn:
            wanted = {row["path"] for row in conn.execute("SELECT path FROM folders")}
        for path, observer in list(self._watched.items()):
            if path not in wanted:
                self._watched.pop(path).stop()
            elif not Path(path).is_dir() or not all(e.is_alive() for e in observer.emitters):
                self._watched.pop(path).stop()
                self._changed()  # its videos went with it
        for path in wanted - set(self._watched):
            if not Path(path).is_dir():
                continue  # its drive is unplugged: watched once it's back
            try:
                observer = observe(path, Changes(self.notice, self._holds))
            except OSError as error:
                log.warning("Maku can't watch %s: %s", path, error)
                continue
            self._watched[path] = observer

    def _holds(self, path: str) -> bool:
        """Whether the library has a video at this path, or in a folder there."""
        folder = path.rstrip("\\/") + "\\"
        with closing(db.connect(self._paths.database)) as conn:
            row = conn.execute(
                """SELECT 1 FROM files
                   WHERE gone_at IS NULL
                     AND (lower(path) = lower(?) OR lower(substr(path, 1, ?)) = lower(?))
                   LIMIT 1""",
                (path, len(folder), folder),
            ).fetchone()
        return row is not None


def observe(path: str, changes: FileSystemEventHandler) -> BaseObserver:
    """Starts watching a folder and everything in it."""
    observer = BaseObserver(_Emitter, timeout=DEFAULT_OBSERVER_TIMEOUT)
    observer.schedule(changes, path, recursive=True)
    observer.start()
    return observer


class _Emitter(WindowsApiEmitter):
    """watchdog's watcher of a folder on Windows, closing the folder's handle once only. watchdog
    closes it when the folder goes (its drive unplugged, say) and again when it's stopped; by
    then Windows may have given the number to another file (the database's), and closing that
    crashed the engine."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._closing = threading.Lock()
        self._closed = False

    def on_thread_stop(self) -> None:
        with self._closing:
            if self._closed:
                return
            self._closed = True
        super().on_thread_stop()
        self._whandle = None  # nothing reads it again


class Changes(FileSystemEventHandler):
    """Tells the watcher when a video, or a folder that holds or may hold videos, comes or goes.
    Something written inside a folder (Maku's own report, say) isn't a change: files tell for
    themselves. Windows tells of a folder moved out or deleted as a file gone, so a gone
    path counts when the library has videos there (`holds`)."""

    def __init__(self, notice: Callable[[], None], holds: Callable[[str], bool]) -> None:
        self._notice = notice
        self._holds = holds

    def on_any_event(self, event: FileSystemEvent) -> None:
        source = str(event.src_path)
        target = str(event.dest_path) if event.dest_path else ""
        match event.event_type:
            case "created":
                changed = event.is_directory or is_video(source)
            case "modified" | "closed":
                changed = not event.is_directory and is_video(source)
            case "deleted":
                changed = is_video(source) or self._holds(source)
            case "moved":
                changed = (
                    event.is_directory
                    or is_video(source)
                    or is_video(target)
                    or self._holds(source)
                )
            case _:
                changed = False  # opened, or closed without writing
        if changed:
            self._notice()
