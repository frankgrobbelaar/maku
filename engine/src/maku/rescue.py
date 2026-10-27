"""When Maku's records are damaged (maku.db scribbled over by a disk fault, or cut short by a power
cut mid-write), the engine starts without them: nothing else can work, so the app asks only what
to do. It offers the newest backup that opens, which brings Maku back to when it was made; with
none, new records, as on Maku's first day. Either way the damaged file is kept beside them as it
is, never deleted (maku/backups.py, `set_aside`). The files in the library aren't touched.
"""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime

from maku import db
from maku.backups import (
    Backup,
    BackupError,
    backups,
    bad_read,
    checks_out,
    damaged,
    note_restored,
    restore,
    set_aside,
)
from maku.config import DataPaths


@dataclass(frozen=True)
class Damage:
    """Maku's records are damaged: what's wrong, and the backup to restore."""

    problem: str  # in SQLite's words: "file is not a database"
    backup: Backup | None  # the newest backup that opens, if there is one
    bad_read: bool = False  # the disk couldn't read them: trying again may be all it needs


def damage(paths: DataPaths) -> Damage | None:
    """As the engine starts: what's wrong with Maku's records, if they're damaged, and the newest
    backup that opens. None when they're fine, or there are none yet (a first start)."""
    found = _fault(paths)
    if found is None:
        return None
    problem, unread = found
    newest = next((b for b in backups(paths) if checks_out(paths, b)), None)
    return Damage(problem, newest, bad_read=unread)


def restore_newest(paths: DataPaths, now: datetime) -> Backup:
    """Restores the newest backup that opens over damaged records, setting them aside as they
    are, and notes how it went for Settings. Raises BackupError when it can't."""
    found = next((b for b in backups(paths) if checks_out(paths, b)), None)
    if found is None:
        raise BackupError("No backup opens, so there's none to restore.")
    restore(paths, found.name, now, damaged=True)
    note_restored(paths, found.name, now, None)
    return found


def start_afresh(paths: DataPaths, now: datetime) -> None:
    """Sets damaged records aside as they are, so Maku starts again with new ones, as on its
    first day. Raises BackupError when they can't be moved."""
    set_aside(paths, now)


def _fault(paths: DataPaths) -> tuple[str, bool] | None:
    """What's wrong with Maku's records, in SQLite's words, and whether it's the disk that
    couldn't read them; None when they open and check out, or aren't there yet."""
    if not paths.database.exists():
        return None
    try:
        with closing(sqlite3.connect(paths.database)) as conn:  # its first page, as it is
            conn.execute("PRAGMA schema_version").fetchone()
        with closing(db.connect(paths.database)) as conn:
            [verdict] = conn.execute("PRAGMA quick_check(1)").fetchone()
    except sqlite3.DatabaseError as error:
        if not damaged(error):
            raise  # not damage (another program holding it, say): the engine says why
        return str(error), bad_read(error)
    return None if verdict == "ok" else (str(verdict), False)
