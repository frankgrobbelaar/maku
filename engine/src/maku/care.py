"""Looking after Maku while it's open, on a background thread: tonight's backup of its records
(from 03:00, or the first chance after: maku/backups.py), once a day clearing out of the
quarantine what has waited longer than the owner keeps it (maku/quarantine.py) and of History
what's older than the owner keeps it (maku/history.py), the poster and background pictures
next to each show when the owner wants them (maku/artwork_files.py), and at night the health
check, a few videos test-played at a time (maku/checkup.py). The clear-out waits while files
move (Scanner.hold), so a tidy-up putting a copy back never meets it.
"""

import logging
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager, closing
from datetime import date, datetime, timedelta

from maku import backups, checkup, db, history
from maku.artwork_files import write_artwork
from maku.backups import BackupError
from maku.config import DataPaths
from maku.convert import Programs
from maku.events import Notify
from maku.preferences import history_days, quarantine_days
from maku.quarantine import clear_out
from maku.scan import ScanBusyError
from maku.web import Send

log = logging.getLogger(__name__)

EVERY = 300.0  # seconds between looks
SOON = 5.0  # seconds between looks at night while videos wait for the health check
CHECK_FOR = timedelta(minutes=4)  # of the health check at a time, so the rest isn't kept waiting
_REST = timedelta(hours=1)  # after a backup fails, before it's tried again


class Care:
    def __init__(
        self,
        paths: DataPaths,
        hold: Callable[[], AbstractContextManager[None]],
        *,
        now: Callable[[], datetime],
        transport: Send | None = None,
        programs: Callable[[], Programs | None] | None = None,
        notify: Notify | None = None,
        busy: Callable[[], bool] = lambda: False,
    ) -> None:
        """`hold` holds scans and file moves off (Scanner.hold); `transport` fetches pictures;
        `programs` is the ffmpeg the health check plays videos with, `notify` tells of the ones
        that didn't play, and `busy` says the queue has a job, which the check waits for."""
        self._paths = paths
        self._hold = hold
        self._now = now
        self._transport = transport
        self._programs = programs
        self._notify = notify
        self._busy = busy
        self._checking = False  # the health check has more to play tonight
        self._unplayed: list[int] = []  # what tonight's check found, told once it's done
        self._wake = threading.Event()
        self._cleared_on: date | None = None  # the day the quarantine was last cleared out
        self._resting_until: datetime | None = None  # after a backup failed
        self._refused: dict[str, datetime] = {}  # pictures refused, and when to ask again
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Looks after what's due now, then every few minutes until `stop`."""
        self._thread = threading.Thread(target=self._loop, name="care", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def wake(self) -> None:
        """Looks after things now rather than at the next look (the owner turned the pictures
        on, say)."""
        self._wake.set()

    def look_after(self) -> None:
        """Does what's due: tonight's backup, the pictures next to each show, and today's
        clear-out."""
        now = self._now()
        resting = self._resting_until is not None and now < self._resting_until
        if not resting and backups.due(self._paths, now):
            try:
                backups.back_up(self._paths, now)
            except BackupError as error:
                log.warning("%s", error)
                self._resting_until = now + _REST
        if self._transport is not None:
            with closing(db.connect(self._paths.database)) as conn:
                write_artwork(conn, self._transport, now=now, refused=self._refused)
        if self._cleared_on != now.date():
            try:
                with self._hold(), closing(db.connect(self._paths.database)) as conn:
                    clear_out(conn, days=quarantine_days(conn), now=now)
                    # Then History, so what the clear-out just emptied can go from it too.
                    days = history_days(conn)
                    if days is not None:
                        history.clear(conn, keep=timedelta(days=days), now=now)
            except ScanBusyError:
                return  # a scan runs, or files move: next time
            self._cleared_on = now.date()
        self.check_health()

    def check_health(self) -> int:
        """At night, while the queue has no job, test-plays the videos the health check is due
        to, for a few minutes. Once the night's check is done (or the night is), tells of those
        that didn't play, in one notification. Returns how many didn't, this time."""
        self._checking = False
        programs = self._programs() if self._programs else None
        now = self._now()
        if programs is None or not checkup.at_night(now):
            self._tell_unplayed()
            return 0
        if self._busy():
            return 0  # converting or making subtitles: the check waits for the queue's job
        with closing(db.connect(self._paths.database)) as conn:
            if not checkup.is_on(conn):
                return 0
            found = checkup.night(
                conn, programs, self._now, until=now + CHECK_FOR, stop=self._stopping.is_set
            )
        self._unplayed += found.unplayed
        self._checking = found.more
        if not found.more:
            self._tell_unplayed()
        return len(found.unplayed)

    def _tell_unplayed(self) -> None:
        """Tells of the videos tonight's check found that didn't play, once."""
        count, self._unplayed = len(self._unplayed), []
        if count == 0 or self._notify is None:
            return
        them = "them" if count > 1 else "it"
        self._notify(
            f"{count} {'videos' if count > 1 else 'video'} didn't play",
            f"Tonight's health check found {them}: Home lists what didn't play.",
            link="/",
        )

    def _loop(self) -> None:
        while True:
            try:
                self.look_after()
            except Exception:  # care must outlive any one problem
                log.exception("Looking after Maku hit a problem")
            self._wake.wait(SOON if self._checking else EVERY)
            self._wake.clear()
            if self._stopping.is_set():
                return
