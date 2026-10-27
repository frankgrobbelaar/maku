"""Backups of Maku's database: one a night (the first chance after 03:00), the last seven kept,
each checked as it's written, in the data folder's `backups`. The owner can make one by hand too
(seven of those are kept apart). One can be restored: Maku's records go back to that night, and
the files themselves stay as they are. The owner asks for it in Settings, and it's done as the
engine starts again, before anything opens the database; the backup is checked first, and what
Maku knew till then is backed up before it's replaced, even when it doesn't check out (it's what
there was). Importing an export (`maku export`'s zip, from this PC or another) is restoring the
database it holds, kept beside the backups as one "from an export". No backup is ever written
over: two made in one minute are "(2)" apart. Records damaged past opening can't be backed up,
so they're set aside as they are instead, "maku (damaged 2026-10-12 0930).db" (maku/rescue.py).
"""

import itertools
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from maku import changes, db
from maku.config import DataPaths
from maku.migrations import MIGRATIONS

log = logging.getLogger(__name__)

BACKUP_HOUR = 3  # a night's backup is made from 03:00
KEEP = 7  # nightly backups, and as many of each other kind

_NAME = re.compile(
    r"^maku (\d{4}-\d{2}-\d{2}) (\d{2})(\d{2})( before restoring| from an export| by hand)?"
    r"(?: \((\d+)\))?\.db$"
)
_ASKED = "restore.txt"  # names the backup to restore when the engine next starts
_RESTORED = "backup_restored"  # the settings row saying how the last restore went
_DAMAGE = (11, 26)  # SQLite's codes for a database that's corrupt, or isn't one any more
_BAD_READS = (266, 522)  # and for a disk that can't read it (SQLITE_IOERR_READ, _SHORT_READ)


class BackupError(Exception):
    """A backup couldn't be made or restored. The message says why, in words."""


@dataclass(frozen=True)
class Backup:
    name: str  # "maku 2026-10-11 0300.db"
    made: datetime  # local time, to the minute
    size: int
    before_restoring: bool  # made just before another backup was restored
    from_export: bool = False  # the database an imported export held
    by_hand: bool = False  # made when the owner asked ("Back up now")
    copy: int = 1  # 2, 3… for one made in the same minute as another of its kind


@dataclass(frozen=True)
class Restored:
    """How the last restore went."""

    name: str  # the backup
    at: str  # when, as the engine started
    problem: str | None  # why it couldn't be restored, if it couldn't


def backups(paths: DataPaths) -> list[Backup]:
    """Every backup there is, newest first."""
    found: list[Backup] = []
    folder = _folder(paths)
    if not folder.is_dir():
        return found
    for path in folder.iterdir():
        match = _NAME.match(path.name)
        if not match or not path.is_file():
            continue
        made = datetime.fromisoformat(f"{match[1]}T{match[2]}:{match[3]}")
        kind = match[4] or ""
        found.append(
            Backup(
                path.name,
                made,
                path.stat().st_size,
                before_restoring=kind == " before restoring",
                from_export=kind == " from an export",
                by_hand=kind == " by hand",
                copy=int(match[5] or 1),
            )
        )
    return sorted(found, key=lambda b: (b.made, b.copy, b.name), reverse=True)


def due(paths: DataPaths, now: datetime) -> bool:
    """Whether tonight's backup is still to make: none since the last 03:00."""
    night = now.replace(hour=BACKUP_HOUR, minute=0, second=0, microsecond=0, tzinfo=None)
    if now.replace(tzinfo=None) < night:
        night -= timedelta(days=1)
    return not any(b.made >= night and _nightly(b) for b in backups(paths))


def back_up(
    paths: DataPaths,
    now: datetime,
    *,
    before_restoring: bool = False,
    by_hand: bool = False,
    keep: str | None = None,
) -> Backup:
    """Copies the live database into a backup, checks the copy, and keeps the last seven of its
    kind (and `keep`, the one about to be restored, whatever its age). A copy that doesn't check
    out isn't kept, unless it's made before restoring: then it's what Maku had."""
    folder = _folder(paths)
    folder.mkdir(parents=True, exist_ok=True)
    kind = " before restoring" if before_restoring else " by hand" if by_hand else ""
    handle, made = tempfile.mkstemp(prefix="maku ", suffix=".partial", dir=folder)
    os.close(handle)
    partial = Path(made)
    try:
        with closing(db.connect(paths.database)) as live, closing(sqlite3.connect(partial)) as copy:
            live.backup(copy)
            copy.execute("PRAGMA journal_mode = DELETE")  # one self-contained file
            [verdict] = copy.execute("PRAGMA integrity_check").fetchone()
        if verdict != "ok" and not before_restoring:
            raise BackupError(f"The backup didn't check out ({verdict}), so Maku didn't keep it.")
        if verdict != "ok":
            log.warning("Maku's records didn't check out before restoring (%s)", verdict)
        name = _name_free(partial, f"maku {now:%Y-%m-%d %H%M}{kind}")
    except (OSError, sqlite3.Error) as error:
        raise BackupError(f"Maku couldn't make a backup: {error}") from error
    finally:
        partial.unlink(missing_ok=True)
    _prune(paths, keep=keep)
    return next(backup for backup in backups(paths) if backup.name == name)


def _name_free(partial: Path, stem: str) -> str:
    """Gives a finished copy its name, never another backup's: one made in the same minute as
    another of its kind is "(2)", "(3)"…"""
    for count in itertools.count(1):
        name = f"{stem}.db" if count == 1 else f"{stem} ({count}).db"
        target = partial.with_name(name)
        if target.exists():
            continue
        try:
            partial.rename(target)  # Windows never renames over a file
        except FileExistsError:
            continue
        return name
    raise AssertionError  # never reached: the count goes on


def ask_to_import(paths: DataPaths, archive: Path, now: datetime) -> None:
    """Checks a zip is a Maku export this Maku can read, keeps the database it holds beside the
    backups, and asks for it to be restored as the engine next starts."""
    folder = _folder(paths)
    folder.mkdir(parents=True, exist_ok=True)
    handle, made = tempfile.mkstemp(prefix="maku ", suffix=".partial", dir=folder)
    os.close(handle)
    target = Path(made)
    try:
        with zipfile.ZipFile(archive) as export:
            found = json.loads(export.read("manifest.json"))
            manifest = cast("dict[str, object]", found) if isinstance(found, dict) else {}
            if manifest.get("app") != "Maku":
                raise BackupError("That zip isn't a Maku export.")
            version = manifest.get("schemaVersion")
            if not isinstance(version, int):
                raise BackupError("That zip isn't a Maku export Maku can read.")
            if version > len(MIGRATIONS):
                raise BackupError("That export is from a newer Maku. Update Maku, then import it.")
            with export.open("maku.db") as source, target.open("wb") as copy:
                shutil.copyfileobj(source, copy)
        with closing(sqlite3.connect(target)) as conn:
            [verdict] = conn.execute("PRAGMA integrity_check").fetchone()
        if verdict != "ok":
            raise BackupError(f"The export's database didn't check out ({verdict}).")
        name = _name_free(target, f"maku {now:%Y-%m-%d %H%M} from an export")
    except OSError, KeyError, ValueError, zipfile.BadZipFile, sqlite3.Error:
        raise BackupError("That zip isn't a Maku export Maku can read.") from None
    finally:
        target.unlink(missing_ok=True)
    _prune(paths, keep=name)
    ask_to_restore(paths, name)


def ask_to_restore(paths: DataPaths, name: str) -> None:
    """Asks for a backup to be restored when the engine next starts, with nothing else using the
    database: the app starts it again right after."""
    if not _NAME.match(name) or not (_folder(paths) / name).is_file():
        raise BackupError("Maku has no such backup.")
    (_folder(paths) / _ASKED).write_text(name, encoding="utf-8")


def restore_asked(paths: DataPaths, now: datetime) -> bool:
    """As the engine starts: restores the backup the owner asked for, if they did, and keeps how
    it went for Settings to show (`last_restore`). True when one was restored."""
    asked = _folder(paths) / _ASKED
    try:
        name = asked.read_text(encoding="utf-8").strip()
    except OSError:
        return False  # none asked for
    asked.unlink(missing_ok=True)  # asked once, tried once
    problem: str | None = None
    try:
        restore(paths, name, now)
    except BackupError as error:
        problem = str(error)
        log.warning("The backup %s wasn't restored: %s", name, problem)
    note_restored(paths, name, now, problem)
    return problem is None


def note_restored(paths: DataPaths, name: str, now: datetime, problem: str | None) -> None:
    """Keeps how a restore went, for Settings to show (`last_restore`)."""
    outcome = {"name": name, "at": now.isoformat(timespec="seconds"), "problem": problem}
    try:
        with closing(db.connect(paths.database)) as conn, conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (_RESTORED, json.dumps(outcome)),
            )
    except sqlite3.Error:
        log.exception("Maku couldn't note how restoring %s went", name)


def last_restore(conn: sqlite3.Connection) -> Restored | None:
    """How the last restore went, if there was one."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (_RESTORED,)).fetchone()
    if row is None:
        return None
    found = json.loads(row["value"])
    return Restored(str(found["name"]), str(found["at"]), found.get("problem"))


def restore(paths: DataPaths, name: str, now: datetime, *, damaged: bool = False) -> None:
    """Puts a backup's records in place of the live ones, once the backup checks out and the live
    ones are kept: backed up, or set aside as they are when they're `damaged` or won't open at
    all. The caller makes sure nothing else is writing (no scan, nothing converting)."""
    source = _folder(paths) / name
    if not _NAME.match(name) or not source.is_file():
        raise BackupError("Maku has no such backup.")
    try:
        # Opened only to read: a backup that went meanwhile is never made anew, empty.
        with closing(sqlite3.connect(f"{source.absolute().as_uri()}?mode=ro", uri=True)) as backup:
            [verdict] = backup.execute("PRAGMA integrity_check").fetchone()
            if verdict != "ok":
                raise BackupError(
                    f"That backup didn't check out ({verdict}), so Maku left its "
                    "records as they are."
                )
            if damaged or unreadable(paths.database) is not None:
                set_aside(paths, now)
            else:
                back_up(paths, now, before_restoring=True, keep=name)
            with closing(db.connect(paths.database)) as live:
                backup.backup(live)
                db.migrate(live)  # a backup from an older Maku is brought up to date
                changes.recover(live, now=now)
    except (OSError, sqlite3.Error) as error:
        raise BackupError(f"Maku couldn't restore that backup: {error}") from error


def checks_out(paths: DataPaths, backup: Backup) -> bool:
    """Whether a backup opens and checks out, as restoring it asks."""
    path = (_folder(paths) / backup.name).absolute()
    try:
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as conn:
            [verdict] = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error:
        return False
    return verdict == "ok"


def unreadable(database: Path) -> str | None:
    """Why a database won't open at all (its first page scribbled over, say), in SQLite's words;
    None when it opens, or isn't there. Only damage counts: one another program holds a moment is
    still fine."""
    if not database.exists():
        return None
    try:
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("PRAGMA schema_version").fetchone()
    except sqlite3.DatabaseError as error:
        if damaged(error):
            return str(error)
        raise
    return None


def bad_read(error: sqlite3.Error) -> bool:
    """Whether SQLite failed because the disk couldn't read the database (a bad sector, a drive
    that went a moment): trying again may be all it needs."""
    return error.sqlite_errorcode in _BAD_READS


def damaged(error: sqlite3.Error) -> bool:
    """Whether SQLite failed because the database is corrupt, isn't one any more, or can't be
    read off the disk (a bad sector)."""
    code = error.sqlite_errorcode
    return code & 0xFF in _DAMAGE or code in _BAD_READS


def set_aside(paths: DataPaths, now: datetime) -> Path | None:
    """Moves damaged records out of the way as they are, never deleting them or writing over
    another file: maku.db, with its -wal and -shm, becomes "maku (damaged 2026-10-12 0930).db"
    beside where it was. Its -wal goes first, so a new maku.db never meets it. None when there
    were none."""
    live = paths.database
    if not live.exists():
        return None
    for count in itertools.count(1):
        name = f"maku (damaged {now:%Y-%m-%d %H%M})" + ("" if count == 1 else f" ({count})")
        target = live.with_name(f"{name}.db")
        moves = [
            (live.with_name(live.name + end), target.with_name(target.name + end))
            for end in ("-wal", "-shm")
        ]
        if target.exists() or any(moved.exists() for _, moved in moves):
            continue
        done: list[tuple[Path, Path]] = []
        try:
            for source, moved in [*moves, (live, target)]:
                if source.exists():
                    source.rename(moved)
                    done.append((source, moved))
        except OSError as error:
            for source, moved in reversed(done):  # as it was, as far as it can be
                with suppress(OSError):
                    moved.rename(source)
            raise BackupError(f"Maku couldn't set its damaged records aside: {error}") from error
        log.warning("Maku's damaged records were set aside as %s", target.name)
        return target
    raise AssertionError  # never reached: the count goes on


def _prune(paths: DataPaths, *, keep: str | None = None) -> None:
    """Keeps the last seven of each kind (nightly backups, those made by hand, those made before
    restoring, and the databases imported exports held), and `keep`."""
    found = backups(paths)
    kinds = {(backup.before_restoring, backup.from_export, backup.by_hand) for backup in found}
    for kind in kinds:
        same = [b for b in found if (b.before_restoring, b.from_export, b.by_hand) == kind]
        for old in same[KEEP:]:
            if old.name != keep:
                (_folder(paths) / old.name).unlink(missing_ok=True)


def _nightly(backup: Backup) -> bool:
    return not (backup.before_restoring or backup.from_export or backup.by_hand)


def _folder(paths: DataPaths) -> Path:
    return paths.root / "backups"
