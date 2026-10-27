"""Looking after Maku in the background: tonight's backup, and the quarantine and History cleared
daily."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from maku import backups
from maku.backups import BackupError
from maku.care import Care
from maku.changes import changes_of
from maku.config import DataPaths
from maku.scan import Scanner
from maku.tools import Tools
from maku.web import Reply
from tests.fake_web import FakeWeb
from tests.shelf import library
from tests.test_quarantine import NOW, set_aside

NIGHT = datetime(2026, 10, 11, 3, 5).astimezone()


def look_after(paths: DataPaths, at: list[datetime], scanner: Scanner | None = None) -> Care:
    """Maku's care, at the time `at` holds (a test moves it on)."""
    return Care(paths, (scanner or Scanner(paths, Tools(paths, items=()))).hold, now=lambda: at[0])


def cleared(conn: sqlite3.Connection, plan_id: int) -> bool:
    copy = changes_of(conn, plan_id)[0]
    return copy.cleared_at is not None


def test_tonights_backup_is_made_once_from_three(paths: DataPaths, conn: sqlite3.Connection):
    at = [NIGHT - timedelta(hours=1)]  # 02:05, and last night's was never made: it is now
    care = look_after(paths, at)

    care.look_after()
    care.look_after()
    at[0] = NIGHT
    care.look_after()
    care.look_after()

    assert [backup.name for backup in backups.backups(paths)] == [
        "maku 2026-10-11 0305.db",
        "maku 2026-10-11 0205.db",
    ]


def test_a_backup_that_fails_is_tried_again_an_hour_later(
    paths: DataPaths, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    tries: list[datetime] = []

    def full(paths: DataPaths, now: datetime) -> backups.Backup:
        tries.append(now)
        raise BackupError("Maku couldn't make a backup: there's no room on the drive")

    monkeypatch.setattr("maku.care.backups.back_up", full)
    at = [NIGHT]
    care = look_after(paths, at)

    care.look_after()
    at[0] += timedelta(minutes=30)
    care.look_after()
    at[0] += timedelta(minutes=31)
    care.look_after()

    assert tries == [NIGHT, NIGHT + timedelta(minutes=61)]


def test_what_was_set_aside_too_long_ago_is_cleared_once_a_day(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path
):
    old = set_aside(conn, tmp_path, "Old", days_ago=31)
    at = [NOW]
    care = look_after(paths, at)

    care.look_after()
    later = set_aside(conn, tmp_path, "Later", days_ago=31)
    care.look_after()

    assert (cleared(conn, old), cleared(conn, later)) == (True, False)
    at[0] += timedelta(days=1)
    care.look_after()
    assert cleared(conn, later)


def test_kept_for_good_nothing_is_cleared(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path
):
    with conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('quarantine_days', 'null')")
    old = set_aside(conn, tmp_path, "Old", days_ago=400)

    look_after(paths, [NOW]).look_after()

    assert not cleared(conn, old)


def test_history_is_cleared_daily_only_when_the_owner_chose_how_long_it_keeps(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path
):
    old = set_aside(conn, tmp_path, "Old", days_ago=40)  # its copy is cleared out first
    at = [NOW]

    look_after(paths, at).look_after()  # History keeps everything at first
    assert conn.execute("SELECT id FROM plans").fetchall() != []

    with conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('history_days', '30')")
    at[0] += timedelta(days=1)
    look_after(paths, at).look_after()
    assert conn.execute("SELECT id FROM plans WHERE id = ?", (old,)).fetchone() is None


def test_the_clear_out_waits_while_files_move(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path
):
    scanner = Scanner(paths, Tools(paths, items=()))
    care = look_after(paths, [NOW], scanner)
    old = set_aside(conn, tmp_path, "Old", days_ago=31)

    with scanner.hold():  # a tidy-up putting files back, say
        care.look_after()
    assert not cleared(conn, old)

    care.look_after()
    assert cleared(conn, old)


def test_the_pictures_next_to_each_show_are_written_as_care_looks_after_things(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path
):
    show = "Glass Orchard (2012)"
    library(conn, tmp_path / "Videos", [f"TV/{show}/{show} - S01E01.mkv"])
    with conn:
        conn.execute(
            "INSERT INTO titles (id, kind, name, poster)"
            " VALUES (1, 'series', 'Glass Orchard', '/p.jpg')"
        )
        conn.execute("UPDATE files SET title_id = 1, matched = 'sure'")
        conn.execute("INSERT INTO settings (key, value) VALUES ('artwork', 'true')")
    web = FakeWeb(answers={"GET https://image.tmdb.org/t/p/w780/p.jpg": Reply(200, {}, b"poster")})
    care = Care(paths, Scanner(paths, Tools(paths, items=())).hold, now=lambda: NOW, transport=web)

    care.look_after()

    assert (tmp_path / "Videos" / "TV" / show / "poster.jpg").read_bytes() == b"poster"


def test_care_looks_after_things_at_once_and_stops_when_asked(
    paths: DataPaths, conn: sqlite3.Connection
):
    care = look_after(paths, [NIGHT])

    care.start()
    care.stop()

    assert [backup.name for backup in backups.backups(paths)] == ["maku 2026-10-11 0305.db"]
