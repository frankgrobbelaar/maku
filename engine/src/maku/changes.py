"""Carrying out tidy-up plans on disk, journaled so every change can be undone.

A plan from maku.core.plan is saved first (`save_plan`) and shown for review; nothing moves until
it is applied (`apply_plan`). Each change is written to the database before and after its file
moves, so after a crash `recover` can tell where every file is. `undo_plan` puts files back,
newest first, and can be asked again for any that couldn't go back.

Nothing here overwrites a file or deletes one outright. A move onto a name that is taken fails and
says so. A move to another drive copies the file beside its new place, checks the copy, renames it
into place, and only then removes the original.

The library's record of a video goes with it (`files.path`), so it keeps what it was identified
as; a quarantined one counts as gone from the library until it comes back.
"""

import json
import logging
import shutil
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from itertools import takewhile
from pathlib import Path
from typing import Literal

from maku.core.extensions import is_subtitle, is_video
from maku.core.plan import ChangeKind, Plan

PARTIAL = ".maku-partial"  # added to a copy's name until the copy is complete
_IN_USE = (32, 33)  # Windows' ERROR_SHARING_VIOLATION and ERROR_LOCK_VIOLATION: another app has it

_log = logging.getLogger(__name__)


class ChangeState(StrEnum):
    PLANNED = "planned"
    MOVING = "moving"  # the file may be on its way; after a crash, `recover` settles it
    DONE = "done"
    FAILED = "failed"  # it couldn't be made, `problem` says why, and the file is where it was
    UNDOING = "undoing"
    UNDONE = "undone"


@dataclass(frozen=True)
class SavedChange:
    id: int
    plan_id: int
    position: int
    kind: ChangeKind
    source: Path
    target: Path
    label: str
    reason: str
    state: ChangeState
    problem: str | None  # why it failed, or why it couldn't be undone
    created_dirs: tuple[Path, ...]  # folders this change created, outermost first
    cleared_at: str | None = None  # what it set aside went from quarantine then, for good


@dataclass(frozen=True)
class Outcome:
    """What applying or undoing a plan did this time."""

    changed: tuple[SavedChange, ...]  # changes made, or put back
    problems: tuple[SavedChange, ...]  # changes that couldn't be, each with its problem

    @property
    def count(self) -> int:
        return len(self.changed)


def tally(changes: Iterable[SavedChange]) -> tuple[int, int]:
    """How many of these changes filed a file (a video or its subtitles), and how many set a
    copy aside. A copy's subtitles go with it, but only the copy counts."""
    moved = quarantined = 0
    for change in changes:
        if change.kind is ChangeKind.MOVE:
            moved += 1
        elif is_video(change.source.name):
            quarantined += 1
    return moved, quarantined


def save_plan(
    conn: sqlite3.Connection,
    plan: Plan,
    title: str,
    *,
    now: datetime,
    kind: Literal["tidy", "convert"] = "tidy",
) -> int:
    """Store a plan for review and return its id. Nothing on disk changes. `kind` says what it's
    for: tidying up, or putting a converted file in its original's place."""
    with conn:
        row = conn.execute(
            "INSERT INTO plans (title, created_at, kind) VALUES (?, ?, ?) RETURNING id",
            (title, _stamp(now), kind),
        ).fetchone()
        plan_id: int = row["id"]
        conn.executemany(
            "INSERT INTO changes (plan_id, position, kind, source, target, label, reason)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (plan_id, position, c.kind.value, str(c.source), str(c.target), c.label, c.reason)
                for position, c in enumerate(plan.changes, start=1)
            ],
        )
    return plan_id


def changes_of(conn: sqlite3.Connection, plan_id: int) -> list[SavedChange]:
    rows = conn.execute("SELECT * FROM changes WHERE plan_id = ? ORDER BY position", (plan_id,))
    return [_saved(row) for row in rows]


def apply_plan(conn: sqlite3.Connection, plan_id: int, *, now: datetime) -> Outcome:
    """Make every planned change, in order.

    The plan counts as applied from the start, so History has it even if Maku stops mid-way. A
    change that can't be made is marked failed with the reason, and the rest go ahead, except a
    video's subtitles: they stay with a video that couldn't move.
    """
    stamp = _stamp(now)
    with conn:
        conn.execute(
            "UPDATE plans SET applied_at = ? WHERE id = ? AND applied_at IS NULL", (stamp, plan_id)
        )
    made: list[int] = []
    failed: list[int] = []
    planned = changes_of(conn, plan_id)
    for change in _subtitles_last(planned):
        if change.state is not ChangeState.PLANNED:
            continue
        video = _video_of(change, planned)
        if video is not None and video.id in failed:
            _record(conn, change, ChangeState.FAILED, problem=_STAYED_WITH)
            failed.append(change.id)
            continue
        _record(conn, change, ChangeState.MOVING)
        problem = _why_not(change.source, change.target)
        created: list[Path] = []
        if problem is None:
            try:
                created = _make_folders(change.target.parent)
                _record(conn, change, ChangeState.MOVING, created_dirs=created)
                problem = _move(change.source, change.target)
            except OSError as error:
                _remove_empty(created)
                created = []
                problem = _could_not(error)
            else:
                _settled(conn, change, ChangeState.DONE, problem, created, stamp=stamp)
                made.append(change.id)
                continue
        _log.warning("Couldn't move %s to %s: %s", change.source, change.target, problem)
        _record(conn, change, ChangeState.FAILED, problem=problem, created_dirs=created)
        failed.append(change.id)
    after = changes_of(conn, plan_id)
    remove_emptied(conn, (change.source.parent for change in _these(after, made)))
    return Outcome(_these(after, made), _these(after, failed))


_STAYED_WITH = "Its video stayed where it was, so it did too."


def _subtitles_last(planned: Iterable[SavedChange]) -> list[SavedChange]:
    """The changes in their order, each video's subtitles after every video: a subtitle file
    knows by then whether its video moved."""
    return sorted(planned, key=lambda change: is_subtitle(change.source.name))


def _video_of(change: SavedChange, planned: list[SavedChange]) -> SavedChange | None:
    """The change moving the video a subtitle file is named after, when the plan moves it: the
    longest name that fits (`Show - 12.5.en.srt` is 12.5's, not 12's)."""
    if not is_subtitle(change.source.name):
        return None
    name = change.source.name.casefold()
    fits = [
        other
        for other in planned
        if is_video(other.source.name)
        and other.source.parent == change.source.parent
        and name.startswith(other.source.stem.casefold() + ".")
    ]
    return max(fits, key=lambda other: len(other.source.stem), default=None)


def undo_plan(
    conn: sqlite3.Connection,
    plan_id: int,
    *,
    now: datetime,
    held: Callable[[SavedChange], str | None] = lambda _change: None,
) -> Outcome:
    """Put back every change that was made, newest first.

    A file that can't go back (it has gone, or its old name is taken now) stays where it is, and
    its change says why; so does one `held` gives a reason for (it's being converted, say), and a
    video's subtitles stay with a video that stays. The plan counts as undone once nothing is
    left to put back. What was cleared out of quarantine is gone for good, and isn't asked about.
    """
    stamp = _stamp(now)
    back: list[int] = []
    kept: list[int] = []
    done = changes_of(conn, plan_id)
    for change in _subtitles_last(reversed(done)):
        if change.state is not ChangeState.DONE or change.cleared_at is not None:
            continue
        video = _video_of(change, done)
        reason = _STAYED_WITH if video is not None and video.id in kept else held(change)
        if reason is not None:
            _record(conn, change, ChangeState.DONE, problem=f"Maku couldn't put it back. {reason}")
            kept.append(change.id)
            continue
        _record(conn, change, ChangeState.UNDOING)
        problem = _why_not(change.target, change.source)
        if problem is None:
            try:
                change.source.parent.mkdir(parents=True, exist_ok=True)
                problem = _move(change.target, change.source)
            except OSError as error:
                problem = _could_not(error)
            else:
                _remove_empty(change.created_dirs)
                if change.kind is ChangeKind.QUARANTINE:
                    # The day's folder and the quarantine itself are Maku's own: whichever change
                    # made them, they go once nothing is left in them.
                    _remove_empty([change.target.parent, change.target.parent.parent])
                _settled(conn, change, ChangeState.UNDONE, problem, None, stamp=stamp)
                back.append(change.id)
                continue
        _log.warning("Couldn't put %s back to %s: %s", change.target, change.source, problem)
        _record(conn, change, ChangeState.DONE, problem=f"Maku couldn't put it back. {problem}")
        kept.append(change.id)
    after = changes_of(conn, plan_id)
    if not any(c.state is ChangeState.DONE and c.cleared_at is None for c in after):
        with conn:
            conn.execute("UPDATE plans SET undone_at = ? WHERE id = ?", (stamp, plan_id))
    return Outcome(_these(after, back), _these(after, kept))


def recover(conn: sqlite3.Connection, *, now: datetime | None = None) -> int:
    """Settle the changes a crash interrupted, and return how many of them were a tidy-up's (or
    a delete's): a conversion's are the queue's to tell of.

    Run it at start, before anything else uses the plans. A move that happened is done, one that
    didn't is planned again (or done again, for an undo), and anything else is marked with what
    Maku found. The changes of a tidy-up Maku hadn't got to are closed (tidying up proposes them
    again); a conversion's are left to the queue, which finishes or undoes its replacement.
    """
    stamp = _stamp(now or datetime.now(UTC))
    rows = conn.execute(
        """SELECT c.*, p.kind AS plan_kind FROM changes AS c JOIN plans AS p ON p.id = c.plan_id
           WHERE c.state IN ('moving', 'undoing')"""
    ).fetchall()
    for change in map(_saved, rows):
        if change.state is ChangeState.MOVING:
            _settle(conn, change, change.source, change.target, forward=True, stamp=stamp)
        else:
            _settle(conn, change, change.target, change.source, forward=False, stamp=stamp)
    if rows:
        _log.warning("Settled %d file changes that Maku stopped in the middle of", len(rows))
    with conn:
        closed = conn.execute(
            """UPDATE changes SET state = 'failed', problem = ?
               WHERE state = 'planned' AND plan_id IN
                     (SELECT id FROM plans WHERE kind = 'tidy' AND applied_at IS NOT NULL)""",
            (_STOPPED,),
        ).rowcount
    if closed:
        _log.warning("Closed %d changes of a tidy-up Maku stopped before making", closed)
    return sum(1 for row in rows if row["plan_kind"] == "tidy")


_STOPPED = "Maku stopped before making this change. Tidy up proposes it again."


def _settle(
    conn: sqlite3.Connection,
    change: SavedChange,
    old: Path,
    new: Path,
    *,
    forward: bool,
    stamp: str,
) -> None:
    """Find out whether an interrupted move from `old` to `new` happened, and record it."""
    _partial(new).unlink(missing_ok=True)  # an unfinished copy to another drive
    at_old, at_new = _is_there(old), _is_there(new)
    if at_old and at_new and _copy_of(new, old):
        old.unlink()  # a copy to another drive was in place; only the original was left to remove
        at_old = False
    if at_new and not at_old:
        state = ChangeState.DONE if forward else ChangeState.UNDONE
        if not forward:
            _remove_empty(change.created_dirs)
        _settled(conn, change, state, None, None, stamp=stamp)
    elif at_old and not at_new:
        if forward:
            _remove_empty(change.created_dirs)
            _record(conn, change, ChangeState.PLANNED, created_dirs=[])
        else:
            _record(conn, change, ChangeState.DONE)
    else:
        where = "both places hold a file" if at_old else "it is in neither place"
        problem = f"Maku stopped while moving it, and {where}: {old} and {new}."
        state = ChangeState.FAILED if forward else ChangeState.DONE
        _record(conn, change, state, problem=problem)


def _settled(
    conn: sqlite3.Connection,
    change: SavedChange,
    state: ChangeState,
    problem: str | None,
    created_dirs: Iterable[Path] | None,
    *,
    stamp: str,
) -> None:
    """Records a change made (DONE) or put back (UNDONE), and moves the video's record with it,
    together: a crash can't leave the one without the other."""
    with conn:
        _write(conn, change, state, problem, created_dirs)
        _follow(conn, change, forward=state is ChangeState.DONE, stamp=stamp)


def _follow(conn: sqlite3.Connection, change: SavedChange, *, forward: bool, stamp: str) -> None:
    """Moves the library's record of a video with it. A record a scan made at the new place
    meanwhile gives way: it knows nothing the moved one doesn't. Part of the caller's
    transaction."""
    old, new = (change.source, change.target) if forward else (change.target, change.source)
    gone = stamp if forward and change.kind is ChangeKind.QUARANTINE else None
    conn.execute(
        """DELETE FROM files
           WHERE path = :new AND id != (SELECT id FROM files WHERE path = :old)""",
        {"new": str(new), "old": str(old)},
    )
    conn.execute(
        "UPDATE files SET path = ?, gone_at = ? WHERE path = ?", (str(new), gone, str(old))
    )


def _why_not(source: Path, target: Path) -> str | None:
    """Why a file can't move from `source` to `target`, or None if it can."""
    if not source.is_file():
        return f"It isn't at {source} any more."
    if target.exists() and not _same_file(source, target):  # not just a change of case
        return f"{target.name} is already in {target.parent}, and Maku never overwrites a file."
    return None


def _move(source: Path, target: Path) -> str | None:
    """Move a file without replacing another. Returns a note if the move needed one."""
    if _same_drive(source, target.parent):
        source.rename(target)  # on Windows this fails rather than replace a file
        return None
    partial = _partial(target)
    try:
        shutil.copy2(source, partial)
        if partial.stat().st_size != source.stat().st_size:
            raise OSError(f"The copy of {source.name} came out the wrong size")
        partial.rename(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    try:
        source.unlink()
    except OSError as error:
        return f"It was copied, but the original is still at {source}: {_could_not(error)}"
    return None


def _same_drive(file: Path, folder: Path) -> bool:
    return file.stat().st_dev == folder.stat().st_dev


def _make_folders(folder: Path) -> list[Path]:
    """Create `folder` and its missing parents; return those created, outermost first."""
    missing = list(takewhile(lambda path: not path.exists(), (folder, *folder.parents)))
    folder.mkdir(parents=True, exist_ok=True)
    return missing[::-1]


def _remove_empty(folders: Iterable[Path]) -> None:
    """Remove folders Maku created, deepest first, if nothing else is in them now."""
    for folder in sorted(folders, key=lambda path: len(path.parts), reverse=True):
        with suppress(OSError):  # not empty, or already gone
            folder.rmdir()


def remove_emptied(conn: sqlite3.Connection, folders: Iterable[Path]) -> None:
    """Remove the folders that moves left empty, and parents they leave empty in turn.

    Only inside a library folder, never the library folder itself, and only when there is truly
    nothing left in them. Undoing moves the files back and makes the folders again.
    """
    roots = [Path(row["path"]) for row in conn.execute("SELECT path FROM folders")]
    for folder in sorted(set(folders), key=lambda path: len(path.parts), reverse=True):
        current = folder
        while any(current != root and current.is_relative_to(root) for root in roots):
            if current.is_junction() or current.is_symlink():
                break  # removing a link would cut off whatever it leads to
            try:
                current.rmdir()  # fails unless it's empty
            except OSError:
                break
            current = current.parent


def _is_there(path: Path) -> bool:
    """Whether a file has exactly this name. Windows ignores case, but a rename may change only
    the case, so this compares names as they are written in the folder."""
    try:
        return any(entry.name == path.name for entry in path.parent.iterdir())
    except OSError:
        return False


def _copy_of(copy: Path, original: Path) -> bool:
    """Whether `copy` is a finished copy of `original`: same size and modification time."""
    if _same_file(copy, original):
        return False
    a, b = copy.stat(), original.stat()
    return a.st_size == b.st_size and abs(a.st_mtime - b.st_mtime) < 2


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.samefile(b)
    except OSError:
        return False


def _partial(target: Path) -> Path:
    return target.with_name(target.name + PARTIAL)


def _could_not(error: OSError) -> str:
    if getattr(error, "winerror", None) in _IN_USE:
        return "It's open in another app, maybe your player. Close it, then try again."
    return f"{error.strerror or error}."


def _record(
    conn: sqlite3.Connection,
    change: SavedChange,
    state: ChangeState,
    *,
    problem: str | None = None,
    created_dirs: Iterable[Path] | None = None,
) -> None:
    with conn:
        _write(conn, change, state, problem, created_dirs)


def _write(
    conn: sqlite3.Connection,
    change: SavedChange,
    state: ChangeState,
    problem: str | None,
    created_dirs: Iterable[Path] | None,
) -> None:
    conn.execute(
        "UPDATE changes SET state = ?, problem = ? WHERE id = ?", (state.value, problem, change.id)
    )
    if created_dirs is not None:
        conn.execute(
            "UPDATE changes SET created_dirs = ? WHERE id = ?",
            (json.dumps([str(path) for path in created_dirs]), change.id),
        )


def _these(changes: Iterable[SavedChange], ids: Iterable[int]) -> tuple[SavedChange, ...]:
    wanted = set(ids)
    return tuple(change for change in changes if change.id in wanted)


def _saved(row: sqlite3.Row) -> SavedChange:
    return SavedChange(
        id=row["id"],
        plan_id=row["plan_id"],
        position=row["position"],
        kind=ChangeKind(row["kind"]),
        source=Path(row["source"]),
        target=Path(row["target"]),
        label=row["label"],
        reason=row["reason"],
        state=ChangeState(row["state"]),
        problem=row["problem"],
        created_dirs=tuple(Path(path) for path in json.loads(row["created_dirs"])),
        cleared_at=row["cleared_at"],
    )


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")
