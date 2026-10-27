"""Maku's database: one SQLite file, upgraded in place by numbered migrations."""

import sqlite3
from pathlib import Path

from maku.migrations import MIGRATIONS


class NewerDatabaseError(Exception):
    """The database was written by a newer Maku than this one."""


def connect(path: Path) -> sqlite3.Connection:
    """Open the database the way Maku always uses it.

    WAL lets readers work while a write is in progress, and foreign keys are on.
    The connection may be handed between threads, but never used by two at once.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    return version


def migrate(conn: sqlite3.Connection) -> int:
    """Bring the schema up to date and return its version.

    Each migration runs once, in order, inside its own transaction, so a failure
    leaves the database exactly as it was before that migration.
    """
    current = schema_version(conn)
    if current > len(MIGRATIONS):
        raise NewerDatabaseError(
            f"This database is at version {current}, but this Maku only knows up to "
            f"{len(MIGRATIONS)}. Update Maku to open it."
        )
    for number, sql in enumerate(MIGRATIONS[current:], start=current + 1):
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        except sqlite3.Error:
            conn.rollback()
            raise
    return schema_version(conn)
