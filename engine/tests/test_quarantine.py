"""Clearing out what was set aside once the owner's days are up: copies, and converted files'
originals; or all of it on one drive at once, when the owner empties it to make room. What's
cleared can't be put back; the rest of its tidy-up can."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from maku.changes import ChangeState, apply_plan, changes_of, save_plan, undo_plan
from maku.core.library import QUARANTINE_FOLDER
from maku.core.plan import Change, ChangeKind, Plan
from maku.quarantine import clear_out, empty, set_aside_by_drive

NOW = datetime(2026, 10, 11, 9, 30, tzinfo=UTC)


def set_aside(conn: sqlite3.Connection, tmp_path: Path, name: str, days_ago: int) -> int:
    """A tidy-up, applied `days_ago`, that set a copy aside and filed the kept one."""
    copy, kept = tmp_path / f"{name} (copy).mkv", tmp_path / f"{name}.mkv"
    copy.write_bytes(b"copy")
    kept.write_bytes(b"kept")
    place = Path(tmp_path.anchor) / QUARANTINE_FOLDER / NOW.date().isoformat() / copy.name
    plan = Plan(
        (
            Change(ChangeKind.QUARANTINE, copy, place, f"{name} · duplicate", "Kept the other"),
            Change(ChangeKind.MOVE, kept, tmp_path / "Filed" / kept.name, name, "Named and filed"),
        )
    )
    plan_id = save_plan(conn, plan, f"Tidied {name}", now=NOW)
    when = NOW - timedelta(days=days_ago)
    apply_plan(conn, plan_id, now=when)
    return plan_id


def test_what_was_set_aside_longer_than_the_owner_keeps_it_goes(
    conn: sqlite3.Connection, tmp_path: Path
):
    old = set_aside(conn, tmp_path, "Old", days_ago=31)
    recent = set_aside(conn, tmp_path, "Recent", days_ago=10)

    cleared = clear_out(conn, days=30, now=NOW)

    assert cleared == 1
    [old_copy, _] = changes_of(conn, old)
    [recent_copy, _] = changes_of(conn, recent)
    assert not old_copy.target.exists()
    assert old_copy.cleared_at is not None
    assert recent_copy.target.exists()
    assert recent_copy.cleared_at is None


def test_emptying_a_drive_takes_all_it_set_aside_however_recent(
    conn: sqlite3.Connection, tmp_path: Path
):
    yesterday = set_aside(conn, tmp_path, "Yesterday", days_ago=1)
    drive = tmp_path.drive
    assert set_aside_by_drive(conn) == {drive: len(b"copy")}  # what emptying it would free

    assert empty(conn, drive, now=NOW) == 1

    [copy, filed] = changes_of(conn, yesterday)
    assert not copy.target.exists()
    assert copy.cleared_at is not None
    assert filed.target.exists()  # only what was set aside goes
    assert set_aside_by_drive(conn) == {}


def test_emptying_another_drive_leaves_this_one_as_it_is(conn: sqlite3.Connection, tmp_path: Path):
    plan_id = set_aside(conn, tmp_path, "Yesterday", days_ago=1)
    other = "Q:" if tmp_path.drive.upper() != "Q:" else "R:"

    assert empty(conn, other, now=NOW) == 0

    [copy, _] = changes_of(conn, plan_id)
    assert copy.target.exists()


def test_kept_for_good_nothing_goes(conn: sqlite3.Connection, tmp_path: Path):
    set_aside(conn, tmp_path, "Old", days_ago=400)

    assert clear_out(conn, days=None, now=NOW) == 0


def test_undoing_puts_back_what_it_can_once_a_copy_is_cleared(
    conn: sqlite3.Connection, tmp_path: Path
):
    plan_id = set_aside(conn, tmp_path, "Old", days_ago=31)
    clear_out(conn, days=30, now=NOW)

    outcome = undo_plan(conn, plan_id, now=NOW)

    assert ([c.kind for c in outcome.changed], outcome.problems) == ([ChangeKind.MOVE], ())
    assert (tmp_path / "Old.mkv").exists()
    states = [c.state for c in changes_of(conn, plan_id)]
    assert states == [ChangeState.DONE, ChangeState.UNDONE]  # the copy is gone for good
    undone = conn.execute("SELECT undone_at FROM plans WHERE id = ?", (plan_id,)).fetchone()[0]
    assert undone is not None  # nothing more can come back


def test_an_original_whose_converted_file_never_went_in_is_kept(
    conn: sqlite3.Connection, tmp_path: Path
):
    original, work = tmp_path / "Ep01.mkv", tmp_path / "Ep01.maku-converting"
    original.write_bytes(b"the original")
    work.write_bytes(b"the result")
    (tmp_path / "Ep01 taken.mkv").write_bytes(b"in the way")
    place = Path(tmp_path.anchor) / QUARANTINE_FOLDER / NOW.date().isoformat() / original.name
    plan = Plan(
        (
            Change(ChangeKind.QUARANTINE, original, place, "Ep01 · original", "Converted"),
            Change(ChangeKind.MOVE, work, tmp_path / "Ep01 taken.mkv", "Ep01", "Converted"),
        )
    )
    plan_id = save_plan(conn, plan, "Converted Ep01", now=NOW, kind="convert")
    apply_plan(conn, plan_id, now=NOW - timedelta(days=40))  # the result couldn't go in

    assert clear_out(conn, days=30, now=NOW) == 0
    assert empty(conn, tmp_path.drive, now=NOW) == 0
    assert set_aside_by_drive(conn) == {}
    assert place.exists()  # the only copy of the episode now


def test_only_whats_in_a_quarantine_folder_is_ever_cleared_out(
    conn: sqlite3.Connection, tmp_path: Path
):
    precious = tmp_path / "Documents" / "thesis.docx"
    precious.parent.mkdir()
    precious.write_text("years of work")
    # A record naming it as set aside, as a damaged database or an imported one could hold.
    plan = Plan(
        (Change(ChangeKind.QUARANTINE, tmp_path / "x.mkv", precious, "x", "Kept the other"),)
    )
    save_plan(conn, plan, "Tidied x", now=NOW)
    with conn:
        conn.execute("UPDATE changes SET state = 'done'")
        conn.execute("UPDATE plans SET applied_at = ?", ((NOW - timedelta(days=60)).isoformat(),))

    assert clear_out(conn, days=30, now=NOW) == 0
    assert empty(conn, tmp_path.drive, now=NOW) == 0

    assert precious.read_text() == "years of work"
