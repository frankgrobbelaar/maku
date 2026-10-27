"""History: what Maku did, a few days at a time, and clearing it, by hand or each day. Clearing
forgets records only: what still has a copy in quarantine stays, and no file changes."""

import sqlite3
from datetime import timedelta
from pathlib import Path

from maku import history
from maku.changes import apply_plan, changes_of, save_plan, undo_plan
from maku.core.plan import Change, ChangeKind, Plan
from maku.quarantine import clear_out
from tests.test_quarantine import NOW, set_aside


def filed(conn: sqlite3.Connection, tmp_path: Path, name: str, days_ago: float) -> int:
    """A tidy-up applied `days_ago` that filed one video, and nothing set aside."""
    video = tmp_path / f"{name}.mkv"
    video.write_bytes(b"video")
    plan = Plan((Change(ChangeKind.MOVE, video, tmp_path / "Filed" / video.name, name, "Filed"),))
    plan_id = save_plan(conn, plan, f"Renamed {name}", now=NOW)
    apply_plan(conn, plan_id, now=NOW - timedelta(days=days_ago))
    return plan_id


def scanned(conn: sqlite3.Connection, days_ago: float, state: str = "done") -> int:
    started = (NOW - timedelta(days=days_ago)).isoformat()
    with conn:
        row = conn.execute(
            "INSERT INTO scans (started_at, finished_at, state, stage) VALUES (?, ?, ?, 'done')"
            " RETURNING id",
            (started, started, state),
        ).fetchone()
    return row[0]


def plan_ids(conn: sqlite3.Connection) -> set[int]:
    return {row[0] for row in conn.execute("SELECT id FROM plans")}


def scan_ids(conn: sqlite3.Connection) -> set[int]:
    return {row[0] for row in conn.execute("SELECT id FROM scans")}


def test_history_comes_a_week_of_days_at_a_time(conn: sqlite3.Connection, tmp_path: Path):
    # Something on nine days, some of them twice; nothing on the days between.
    made = {
        days_ago: filed(conn, tmp_path, f"Day {days_ago}", days_ago) for days_ago in range(0, 18, 2)
    }
    early_scan = scanned(conn, 16.1)
    late_scan = scanned(conn, 0.1)

    first = history.page(conn)

    assert [plan.id for plan in first.plans] == [made[days] for days in (0, 2, 4, 6, 8, 10, 12)]
    assert [scan.id for scan in first.scans] == [late_scan]
    assert first.older == (NOW - timedelta(days=12)).date().isoformat()

    rest = history.page(conn, before=first.older)

    assert [plan.id for plan in rest.plans] == [made[14], made[16]]
    assert [scan.id for scan in rest.scans] == [early_scan]
    assert rest.older is None


def test_nothing_done_yet_is_an_empty_page(conn: sqlite3.Connection):
    assert history.page(conn) == history.Page(plans=[], scans=[], older=None)


def test_an_undo_is_on_the_page_of_the_day_it_happened(conn: sqlite3.Connection, tmp_path: Path):
    undone = filed(conn, tmp_path, "Undone", days_ago=10)
    undo_plan(conn, undone, now=NOW - timedelta(days=1))

    first = history.page(conn, days=1)
    rest = history.page(conn, before=first.older, days=1)

    assert first.older == (NOW - timedelta(days=1)).date().isoformat()
    assert [plan.id for plan in first.plans] == [undone]  # its undo, yesterday
    assert [plan.id for plan in rest.plans] == [undone]  # and the tidy-up itself, before
    assert rest.older is None


def test_a_search_finds_what_names_a_title_or_file_a_week_of_days_at_a_time(
    conn: sqlite3.Connection, tmp_path: Path
):
    filed(conn, tmp_path, "Moonlit Harbour 01", days_ago=0)
    scanned(conn, 0.1)
    # Starfall's on nine days: by the tidy-up's own words, and once by a file's name alone.
    named = {days: filed(conn, tmp_path, f"Starfall Academy {days:02d}", days) for days in (1, 3)}
    video = tmp_path / "[Group] starfall_extra.mkv"
    video.write_bytes(b"video")
    plan = Plan(
        (Change(ChangeKind.MOVE, video, tmp_path / "Extras" / "Extra 1.mkv", "Extra 1", "Filed"),)
    )
    by_file = save_plan(conn, plan, "Tidied 1 file", now=NOW)
    apply_plan(conn, by_file, now=NOW - timedelta(days=2))
    named |= {
        days: filed(conn, tmp_path, f"Starfall Academy {days:02d}", days)
        for days in (5, 7, 9, 11, 13)
    }
    # And a batch of English subtitles for one of its videos.
    with conn:
        folder_id = conn.execute(
            "INSERT INTO folders (path, added_at) VALUES (?, 'then') RETURNING id", (str(tmp_path),)
        ).fetchone()[0]
        file_id = conn.execute(
            """INSERT INTO files (folder_id, path, size, modified, found_at, seen_at)
               VALUES (?, ?, 1, 1, 'then', 'then') RETURNING id""",
            (folder_id, str(tmp_path / "Starfall Academy - S01E04.mkv")),
        ).fetchone()[0]
        batch_id = conn.execute(
            """INSERT INTO subtitle_batches (title, quality, language, added_at)
               VALUES ('Season 1', 'fast', 'jpn', 'then') RETURNING id"""
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO jobs (file_id, kind, method, batch_id, position, state, added_at,
                                 finished_at)
               VALUES (?, 'subtitles', 'fast', ?, 1, 'done', 'then', ?)""",
            (file_id, batch_id, (NOW - timedelta(days=4)).isoformat()),
        )

    first = history.page(conn, query="STARFALL")

    assert [plan.id for plan in first.plans] == [
        named[1],
        by_file,
        named[3],
        named[5],
        named[7],
        named[9],
    ]
    assert [made.id for made in first.subtitles] == [batch_id]
    assert first.scans == []  # a scan names nothing
    assert first.older == (NOW - timedelta(days=9)).date().isoformat()

    rest = history.page(conn, before=first.older, query="starfall")

    assert [plan.id for plan in rest.plans] == [named[11], named[13]]
    assert rest.older is None
    assert (
        history.page(conn, query="starfall 05").plans
        == history.page(conn, query="05 starfall").plans
    )
    assert history.page(conn, query="Lantern") == history.Page(plans=[], scans=[], older=None)


def test_clearing_keeps_what_was_undone_lately(conn: sqlite3.Connection, tmp_path: Path):
    undone = filed(conn, tmp_path, "Undone", days_ago=10)
    undo_plan(conn, undone, now=NOW - timedelta(days=1))

    assert history.clear(conn, keep=timedelta(days=7), now=NOW) == 0
    assert history.clear(conn, keep=timedelta(hours=1), now=NOW) == 1
    assert plan_ids(conn) == set()


def test_clearing_keeps_the_last_day_week_or_month_and_moves_no_file(
    conn: sqlite3.Connection, tmp_path: Path
):
    today = filed(conn, tmp_path, "Today", 0.2)
    last_week = filed(conn, tmp_path, "Last week", 5)
    last_month = filed(conn, tmp_path, "Last month", 20)
    old = filed(conn, tmp_path, "Old", 40)
    on_disk = sorted(path.name for path in (tmp_path / "Filed").iterdir())

    assert history.clear(conn, keep=timedelta(days=30), now=NOW) == 1
    assert plan_ids(conn) == {today, last_week, last_month}
    assert changes_of(conn, old) == []  # its journal went with it
    assert history.clear(conn, keep=timedelta(days=7), now=NOW) == 1
    assert history.clear(conn, keep=timedelta(days=1), now=NOW) == 1
    assert plan_ids(conn) == {today}
    assert history.clear(conn, keep=timedelta(0), now=NOW) == 1
    assert plan_ids(conn) == set()
    assert sorted(path.name for path in (tmp_path / "Filed").iterdir()) == on_disk


def test_what_still_has_a_copy_in_quarantine_stays_till_the_clear_out(
    conn: sqlite3.Connection, tmp_path: Path
):
    waiting = set_aside(conn, tmp_path, "Waiting", days_ago=40)

    assert history.clear(conn, keep=timedelta(0), now=NOW) == 0  # History can still put it back
    assert plan_ids(conn) == {waiting}

    clear_out(conn, days=30, now=NOW)  # its copy goes: nothing left to put back
    assert history.clear(conn, keep=timedelta(0), now=NOW) == 1
    assert plan_ids(conn) == set()


def test_a_conversion_cleared_leaves_the_queues_record_of_it(
    conn: sqlite3.Connection, tmp_path: Path
):
    plan_id = filed(conn, tmp_path, "Converted", 40)
    with conn:
        conn.execute("UPDATE plans SET kind = 'convert' WHERE id = ?", (plan_id,))
        folder_id = conn.execute(
            "INSERT INTO folders (path, added_at) VALUES (?, 'then') RETURNING id", (str(tmp_path),)
        ).fetchone()[0]
        file_id = conn.execute(
            """INSERT INTO files (folder_id, path, size, modified, found_at, seen_at)
               VALUES (?, ?, 1, 1, 'then', 'then') RETURNING id""",
            (folder_id, str(tmp_path / "Filed" / "Converted.mkv")),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO jobs (file_id, method, position, state, added_at, plan_id)
               VALUES (?, 'reencode', 1, 'done', 'then', ?)""",
            (file_id, plan_id),
        )

    assert history.clear(conn, keep=timedelta(days=7), now=NOW) == 1
    assert conn.execute("SELECT state, plan_id FROM jobs").fetchone()[:] == ("done", None)


def test_the_latest_scan_and_one_not_over_stay(conn: sqlite3.Connection):
    old = scanned(conn, 40)
    paused = scanned(conn, 39, state="paused")
    latest = scanned(conn, 35)

    assert history.clear(conn, keep=timedelta(days=7), now=NOW) == 1
    assert old not in scan_ids(conn)
    assert scan_ids(conn) == {paused, latest}


def test_a_time_without_an_offset_is_local_and_one_unreadable_stays(conn: sqlite3.Connection):
    with conn:
        conn.execute(
            "INSERT INTO scans (started_at, state, stage) VALUES (?, 'done', 'done')",
            ((NOW - timedelta(days=40)).astimezone().replace(tzinfo=None).isoformat(),),
        )
        conn.execute("INSERT INTO scans (started_at, state, stage) VALUES ('then', 'done', 'done')")
    latest = scanned(conn, 0)

    assert history.clear(conn, keep=timedelta(days=7), now=NOW) == 1
    assert len(scan_ids(conn)) == 2  # the unreadable one, and the latest
    assert latest in scan_ids(conn)
