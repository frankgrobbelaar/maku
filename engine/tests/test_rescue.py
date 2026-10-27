"""Maku's records damaged past opening: the engine starts without them, the newest backup that
opens is offered, and restoring it (or starting afresh) keeps the damaged file beside them."""

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

from maku import db
from maku.backups import back_up, bad_read, damaged, last_restore
from maku.config import DataPaths
from maku.rescue import damage, restore_newest, start_afresh
from tests.damaged import naming_of, records, scribble

NIGHT = datetime(2026, 10, 11, 3, 0).astimezone()
LATER = NIGHT + timedelta(hours=6, minutes=30)  # 09:30


def test_records_that_open_arent_damaged(paths: DataPaths):
    assert damage(paths) is None  # none yet: Maku's first start

    records(paths, "keep")

    assert damage(paths) is None


def test_records_that_wont_open_are_damaged_and_the_newest_backup_that_opens_offered(
    paths: DataPaths,
):
    records(paths, "keep")
    good = back_up(paths, NIGHT)
    records(paths, "plex")
    newer = back_up(paths, NIGHT + timedelta(days=1))
    (paths.root / "backups" / newer.name).write_bytes(b"not a database either")
    scribble(paths)

    found = damage(paths)

    assert found is not None
    assert found.problem == "file is not a database"
    assert found.backup == good


def test_records_that_open_but_dont_check_out_are_damaged_too(paths: DataPaths):
    records(paths, "keep")
    with closing(db.connect(paths.database)) as conn, conn:
        conn.execute("CREATE TABLE filler (x TEXT)")
        conn.executemany("INSERT INTO filler VALUES (?)", [(f"{i:06d}" * 50,) for i in range(3000)])
        conn.execute("CREATE INDEX filler_x ON filler (x)")
    with closing(sqlite3.connect(paths.database)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        page_size, pages = (
            conn.execute(f"PRAGMA {p}").fetchone()[0] for p in ("page_size", "page_count")
        )
    with paths.database.open("r+b") as disk:  # a page in the middle scribbled over
        disk.seek((pages - 5) * page_size + 1000)
        disk.write(b"\x00\x01\x02\x03" * 500)

    found = damage(paths)

    assert found is not None
    assert found.problem != "ok"


def test_a_disk_that_cant_read_the_records_is_damage_and_a_busy_one_isnt():
    bad_sector = sqlite3.DatabaseError("disk I/O error")
    bad_sector.sqlite_errorcode = 266  # SQLITE_IOERR_READ
    busy = sqlite3.OperationalError("database is locked")
    busy.sqlite_errorcode = 5  # SQLITE_BUSY

    assert damaged(bad_sector) is True
    assert damaged(busy) is False
    assert bad_read(bad_sector) is True  # trying again may be all it needs


def test_a_scribbled_file_isnt_a_bad_read(paths: DataPaths):
    records(paths, "keep")
    scribble(paths)

    found = damage(paths)

    assert found is not None
    assert found.bad_read is False  # trying again won't help: it's in the file


def test_with_no_backup_that_opens_none_is_offered(paths: DataPaths):
    records(paths, "keep")
    scribble(paths)

    found = damage(paths)

    assert found is not None
    assert found.backup is None


def test_restoring_the_newest_backup_keeps_the_damaged_file_beside_the_records(
    paths: DataPaths,
):
    records(paths, "keep")
    made = back_up(paths, NIGHT)
    records(paths, "plex")
    damaged = scribble(paths)

    assert restore_newest(paths, LATER) == made

    assert naming_of(paths) == "keep"
    assert (paths.root / "maku (damaged 2026-10-11 0930).db").read_bytes() == damaged
    assert damage(paths) is None
    with closing(db.connect(paths.database)) as conn:  # Settings says how it went
        restored = last_restore(conn)
    assert restored is not None
    assert (restored.name, restored.problem) == (made.name, None)


def test_starting_afresh_keeps_the_damaged_file_and_leaves_no_records(paths: DataPaths):
    records(paths, "keep")
    damaged = scribble(paths)

    start_afresh(paths, LATER)

    assert not paths.database.exists()
    assert (paths.root / "maku (damaged 2026-10-11 0930).db").read_bytes() == damaged
    assert damage(paths) is None  # a first start, again


def test_a_damaged_file_never_takes_another_ones_name(paths: DataPaths):
    records(paths, "keep")
    first = scribble(paths)
    start_afresh(paths, LATER)
    records(paths, "plex")
    second = scribble(paths)

    start_afresh(paths, LATER)

    assert (paths.root / "maku (damaged 2026-10-11 0930).db").read_bytes() == first
    assert (paths.root / "maku (damaged 2026-10-11 0930) (2).db").read_bytes() == second
