"""Maku's records, and damage to them, as the tests of rescuing them need."""

import json
import sqlite3
from contextlib import closing

from maku import db
from maku.config import DataPaths


def records(paths: DataPaths, naming: str) -> None:
    """Maku's records, with one ("naming": "keep" or "plex") that tells one moment's from
    another's."""
    with closing(db.connect(paths.database)) as conn:
        db.migrate(conn)
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


def scribble(paths: DataPaths) -> bytes:
    """maku.db's header scribbled over (a disk fault): SQLite can't tell it's a database."""
    with closing(sqlite3.connect(paths.database)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    damaged = b"\x00" * 100 + paths.database.read_bytes()[100:]
    paths.database.write_bytes(damaged)
    return damaged
