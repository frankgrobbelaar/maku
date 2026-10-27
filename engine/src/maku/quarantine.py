"""Clearing out the quarantine: what was set aside (copies of an episode, and converted files'
originals) goes once it has waited as many days as the owner keeps it (Settings > Your data; 30
unless they choose otherwise, or for good), or all at once from one drive when the owner empties
it there to make room for converting (`empty`), or, when the owner chose to delete converted
files' originals, each as soon as its result is checked and in place (`clear_original`). Its
change in the journal says when, and it can't be put back after that; the rest of its tidy-up
still can.
"""

import logging
import sqlite3
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path

from maku.core.library import drive_of
from maku.core.plan import in_quarantine

log = logging.getLogger(__name__)

# What was set aside and is still there. A converted file's original goes only once the result
# took its place: if it never did, the original is the only copy of the episode there is.
_SET_ASIDE = """SELECT c.id, c.target, p.applied_at FROM changes AS c
   JOIN plans AS p ON p.id = c.plan_id
   WHERE c.kind = 'quarantine' AND c.state = 'done' AND c.cleared_at IS NULL
     AND p.applied_at IS NOT NULL
     AND (p.kind = 'tidy' OR EXISTS (
         SELECT 1 FROM changes AS m
         WHERE m.plan_id = c.plan_id AND m.kind = 'move' AND m.state = 'done'))"""


def clear_out(conn: sqlite3.Connection, *, days: int | None, now: datetime) -> int:
    """Deletes what was set aside more than `days` ago; nothing when `days` is None. Returns how
    many files went."""
    if days is None:
        return 0
    cutoff = now - timedelta(days=days)
    rows = conn.execute(_SET_ASIDE).fetchall()
    old = [row for row in rows if datetime.fromisoformat(row["applied_at"]) < cutoff]
    cleared = _delete(conn, old, now)
    if cleared:
        log.info("Cleared %d files set aside more than %d days ago", cleared, days)
    return cleared


def empty(conn: sqlite3.Connection, drive: str, *, now: datetime) -> int:
    """Deletes everything set aside on a drive ("D:") now, however recently: the owner asked, to
    make room there. Returns how many files went."""
    rows = conn.execute(_SET_ASIDE).fetchall()
    there = [row for row in rows if drive_of(row["target"]).casefold() == drive.casefold()]
    cleared = _delete(conn, there, now)
    if cleared:
        log.info("Emptied the quarantine on %s: %d files", drive, cleared)
    return cleared


def clear_original(conn: sqlite3.Connection, plan_id: int, *, now: datetime) -> int:
    """Deletes a conversion's original from quarantine now, once its result took its place: the
    owner chose to delete originals rather than keep them. Returns how many files went."""
    rows = conn.execute(f"{_SET_ASIDE} AND c.plan_id = ?", (plan_id,)).fetchall()
    cleared = _delete(conn, rows, now)
    if cleared:
        log.info("Deleted a converted file's original, as the owner chose (plan %d)", plan_id)
    return cleared


def set_aside_by_drive(conn: sqlite3.Connection) -> dict[str, int]:
    """What emptying each drive's quarantine now would free, in bytes, by drive ("D:")."""
    found: dict[str, int] = {}
    for row in conn.execute(_SET_ASIDE):
        target = Path(row["target"])
        if not in_quarantine(target):
            continue
        try:
            size = target.stat().st_size
        except OSError:  # gone already, or its drive isn't connected
            continue
        drive = drive_of(target)
        found[drive] = found.get(drive, 0) + size
    return found


def _delete(conn: sqlite3.Connection, rows: list[sqlite3.Row], now: datetime) -> int:
    cleared = 0
    emptied: set[Path] = set()
    for row in rows:
        target = Path(row["target"])
        if not in_quarantine(target):  # a damaged or imported record: never Maku's to delete
            log.warning("Maku didn't clear %s out: it isn't in a quarantine folder", target)
            continue
        try:
            target.unlink(missing_ok=True)
        except OSError as error:
            log.warning("Maku couldn't clear %s out of quarantine: %s", target, error)
            continue
        with conn:
            conn.execute(
                "UPDATE changes SET cleared_at = ? WHERE id = ?",
                (now.isoformat(timespec="seconds"), row["id"]),
            )
        cleared += 1
        emptied.add(target.parent)
    for day in emptied:  # a day's folder, then the quarantine itself, once nothing's in them
        with suppress(OSError):
            day.rmdir()
            day.parent.rmdir()
    return cleared
