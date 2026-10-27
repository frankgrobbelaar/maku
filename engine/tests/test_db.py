import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from maku import db
from maku.migrations import MIGRATIONS


def test_migrate_brings_a_new_database_to_the_latest_version(tmp_path: Path):
    with closing(db.connect(tmp_path / "maku.db")) as conn:
        assert db.migrate(conn) == len(MIGRATIONS)
        assert db.schema_version(conn) == len(MIGRATIONS)


def test_migrate_is_safe_to_run_again(tmp_path: Path):
    with closing(db.connect(tmp_path / "maku.db")) as conn:
        db.migrate(conn)
        assert db.migrate(conn) == len(MIGRATIONS)


def test_a_database_from_a_newer_maku_is_left_alone(tmp_path: Path):
    with closing(db.connect(tmp_path / "maku.db")) as conn:
        conn.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")

        with pytest.raises(db.NewerDatabaseError):
            db.migrate(conn)

        assert db.schema_version(conn) == len(MIGRATIONS) + 1


def test_a_failing_migration_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    broken = "CREATE TABLE half_done (id INTEGER); THIS IS NOT SQL;"
    monkeypatch.setattr(db, "MIGRATIONS", (*MIGRATIONS, broken))

    with closing(db.connect(tmp_path / "maku.db")) as conn:
        with pytest.raises(sqlite3.OperationalError):
            db.migrate(conn)

        assert db.schema_version(conn) == len(MIGRATIONS)
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert "settings" in tables
        assert "half_done" not in tables
