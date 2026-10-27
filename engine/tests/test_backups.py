"""Backups of the database: one a night from 03:00, the last seven kept, checked, restorable."""

import json
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from maku import db
from maku.backups import (
    BackupError,
    Restored,
    ask_to_import,
    ask_to_restore,
    back_up,
    backups,
    due,
    last_restore,
    restore,
    restore_asked,
)
from maku.config import DataPaths
from maku.export import export_data

NIGHT = datetime(2026, 10, 11, 3, 0).astimezone()


def test_a_backup_is_a_checked_copy_of_the_database(paths: DataPaths, conn: sqlite3.Connection):
    with conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('naming', '\"keep\"')")

    made = back_up(paths, NIGHT)

    assert made.name == "maku 2026-10-11 0300.db"
    copy = sqlite3.connect(paths.root / "backups" / made.name)
    assert copy.execute("SELECT value FROM settings WHERE key = 'naming'").fetchone() == ('"keep"',)
    copy.close()


def test_tonights_backup_is_due_from_three_until_its_made(
    paths: DataPaths, conn: sqlite3.Connection
):
    assert due(paths, NIGHT - timedelta(hours=2)) is True  # last night's isn't there either
    back_up(paths, NIGHT - timedelta(hours=2))
    assert due(paths, NIGHT - timedelta(minutes=1)) is False
    assert due(paths, NIGHT) is True

    back_up(paths, NIGHT + timedelta(minutes=5))

    assert due(paths, NIGHT + timedelta(hours=20)) is False


def test_only_the_last_seven_are_kept(paths: DataPaths, conn: sqlite3.Connection):
    for night in range(9):
        back_up(paths, NIGHT + timedelta(days=night))

    kept = backups(paths)

    assert len(kept) == 7
    assert kept[0].made == (NIGHT + timedelta(days=8)).replace(tzinfo=None)


def test_restoring_puts_that_nights_records_back_and_keeps_todays_aside(
    paths: DataPaths, conn: sqlite3.Connection
):
    with conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('naming', '\"keep\"')")
    made = back_up(paths, NIGHT)
    with conn:
        conn.execute("UPDATE settings SET value = '\"plex\"' WHERE key = 'naming'")

    restore(paths, made.name, NIGHT + timedelta(hours=10))

    naming = conn.execute("SELECT value FROM settings WHERE key = 'naming'").fetchone()[0]
    assert naming == '"keep"'
    before = [b for b in backups(paths) if b.before_restoring]
    assert [b.name for b in before] == ["maku 2026-10-11 1300 before restoring.db"]


def test_a_backup_that_isnt_there_cant_be_restored(paths: DataPaths, conn: sqlite3.Connection):
    with pytest.raises(BackupError, match="no such backup"):
        restore(paths, "maku 2026-01-01 0300.db", NIGHT)
    with pytest.raises(BackupError, match="no such backup"):
        restore(paths, "..\\maku.db", NIGHT)


def test_a_backup_asked_for_is_restored_at_the_engines_next_start(
    paths: DataPaths, conn: sqlite3.Connection
):
    with conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('naming', '\"keep\"')")
    made = back_up(paths, NIGHT)
    with conn:
        conn.execute("UPDATE settings SET value = '\"plex\"' WHERE key = 'naming'")

    ask_to_restore(paths, made.name)
    restored = restore_asked(paths, NIGHT + timedelta(hours=10))

    assert restored is True
    naming = conn.execute("SELECT value FROM settings WHERE key = 'naming'").fetchone()[0]
    assert naming == '"keep"'
    at = (NIGHT + timedelta(hours=10)).isoformat(timespec="seconds")
    assert last_restore(conn) == Restored(made.name, at, None)
    assert restore_asked(paths, NIGHT + timedelta(hours=11)) is False  # asked once, done once


def test_a_backup_gone_by_the_next_start_isnt_restored_and_says_why(
    paths: DataPaths, conn: sqlite3.Connection
):
    made = back_up(paths, NIGHT)
    ask_to_restore(paths, made.name)
    (paths.root / "backups" / made.name).unlink()

    assert restore_asked(paths, NIGHT + timedelta(hours=10)) is False

    found = last_restore(conn)
    assert found is not None
    assert (found.name, found.problem) == (made.name, "Maku has no such backup.")


def test_only_a_backup_there_is_can_be_asked_for(paths: DataPaths, conn: sqlite3.Connection):
    with pytest.raises(BackupError, match="no such backup"):
        ask_to_restore(paths, "maku 2026-01-01 0300.db")


def test_the_last_seven_copies_made_before_restoring_are_kept_too(
    paths: DataPaths, conn: sqlite3.Connection
):
    for hour in range(9):
        back_up(paths, NIGHT + timedelta(hours=hour), before_restoring=True)

    kept = backups(paths)

    assert len(kept) == 7
    assert all(backup.before_restoring for backup in kept)


def test_an_export_is_imported_as_the_engine_starts_again(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path
):
    elsewhere = DataPaths(tmp_path / "Another PC")
    with closing(db.connect(elsewhere.database)) as other, other:
        db.migrate(other)
        other.execute("INSERT INTO settings (key, value) VALUES ('naming', '\"keep\"')")
    archive = export_data(elsewhere, tmp_path / "Exports", now=NIGHT)
    assert archive is not None

    ask_to_import(paths, archive, NIGHT + timedelta(hours=10))
    assert restore_asked(paths, NIGHT + timedelta(hours=10)) is True

    naming = conn.execute("SELECT value FROM settings WHERE key = 'naming'").fetchone()[0]
    assert naming == '"keep"'
    kept = backups(paths)
    assert [(b.from_export, b.before_restoring) for b in kept] == [(True, False), (False, True)]


def test_a_zip_that_isnt_a_maku_export_isnt_imported(paths: DataPaths, tmp_path: Path):
    archive = tmp_path / "photos.zip"
    with zipfile.ZipFile(archive, "w") as photos:
        photos.writestr("holiday.jpg", b"a photo")

    with pytest.raises(BackupError, match="isn't a Maku export"):
        ask_to_import(paths, archive, NIGHT)


def test_an_export_from_a_newer_maku_waits_for_an_update(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path
):
    archive = tmp_path / "Maku export 2030-01-01.zip"
    with zipfile.ZipFile(archive, "w") as newer:
        newer.writestr("manifest.json", json.dumps({"app": "Maku", "schemaVersion": 999}))
        newer.writestr("maku.db", b"")

    with pytest.raises(BackupError, match="newer Maku"):
        ask_to_import(paths, archive, NIGHT)


def name_it(conn: sqlite3.Connection, naming: str) -> None:
    """A record that tells one moment's records from another's."""
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('naming', ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (json.dumps(naming),),
        )


def naming_of(paths: DataPaths) -> str:
    with closing(db.connect(paths.database)) as conn:
        return json.loads(
            conn.execute("SELECT value FROM settings WHERE key = 'naming'").fetchone()[0]
        )


def test_restores_in_one_minute_each_keep_what_they_replaced(
    paths: DataPaths, conn: sqlite3.Connection
):
    name_it(conn, "wrong night")
    wrong = back_up(paths, NIGHT)
    name_it(conn, "right night")
    right = back_up(paths, NIGHT + timedelta(days=1))
    name_it(conn, "today")
    at = NIGHT + timedelta(days=1, hours=7, minutes=15)

    restore(paths, wrong.name, at)
    restore(paths, right.name, at + timedelta(seconds=40))  # the one meant

    before = [b.name for b in backups(paths) if b.before_restoring]
    assert before == [
        "maku 2026-10-12 1015 before restoring (2).db",
        "maku 2026-10-12 1015 before restoring.db",
    ]
    restore(paths, before[1], at + timedelta(minutes=1))
    assert naming_of(paths) == "today"


def test_the_oldest_copy_made_before_restoring_can_be_restored(
    paths: DataPaths, conn: sqlite3.Connection
):
    name_it(conn, "oldest")
    for hour in range(7):
        back_up(paths, NIGHT + timedelta(hours=hour), before_restoring=True)
        name_it(conn, f"later {hour}")
    oldest = [b for b in backups(paths) if b.before_restoring][-1]

    restore(paths, oldest.name, NIGHT + timedelta(hours=8))

    assert naming_of(paths) == "oldest"
    assert (paths.root / "backups" / oldest.name).is_file()


def test_damaged_records_are_kept_aside_and_a_backup_restored_over_them(paths: DataPaths):
    with closing(db.connect(paths.database)) as conn:
        db.migrate(conn)
        name_it(conn, "good")
    good = back_up(paths, NIGHT)
    with closing(db.connect(paths.database)) as conn, conn:
        conn.execute("CREATE TABLE filler (x TEXT)")
        conn.executemany("INSERT INTO filler VALUES (?)", [(f"{i:06d}" * 50,) for i in range(3000)])
        conn.execute("CREATE INDEX filler_x ON filler (x)")
    with closing(sqlite3.connect(paths.database)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        page_size, pages = (
            conn.execute(f"PRAGMA {p}").fetchone()[0] for p in ("page_size", "page_count")
        )
    with paths.database.open("r+b") as damaged:  # a page in the middle scribbled over
        damaged.seek((pages - 5) * page_size + 1000)
        damaged.write(b"\x00\x01\x02\x03" * 500)

    restore(paths, good.name, NIGHT + timedelta(hours=10))

    assert naming_of(paths) == "good"
    assert [b.name for b in backups(paths) if b.before_restoring] == [
        "maku 2026-10-11 1300 before restoring.db"
    ]


def test_a_backup_that_doesnt_check_out_isnt_restored(paths: DataPaths, conn: sqlite3.Connection):
    name_it(conn, "today")
    made = back_up(paths, NIGHT)
    (paths.root / "backups" / made.name).write_bytes(b"not a database any more")

    with pytest.raises(BackupError, match="couldn't restore that backup"):
        restore(paths, made.name, NIGHT + timedelta(hours=10))

    assert naming_of(paths) == "today"


def test_backups_made_by_hand_leave_the_nightly_ones_be(paths: DataPaths, conn: sqlite3.Connection):
    for night in range(2):
        back_up(paths, NIGHT + timedelta(days=night))
    for minute in range(9):  # the next morning, before that night's
        back_up(paths, NIGHT + timedelta(days=2, hours=7, minutes=minute), by_hand=True)

    kept = backups(paths)

    assert len([b for b in kept if b.by_hand]) == 7
    assert len([b for b in kept if not b.by_hand]) == 2
    assert kept[0].name == "maku 2026-10-13 1008 by hand.db"
    assert due(paths, NIGHT + timedelta(days=2, hours=8)) is True  # by hand isn't tonight's
