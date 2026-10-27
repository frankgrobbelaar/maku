"""The owner's preferences as the engine uses them (the API's Settings say how they're stored)."""

import json
import sqlite3

from maku.core.standard import STANDARDS, UHD, Standard


def names_kept(conn: sqlite3.Connection) -> bool:
    """Whether files keep their own names when they're filed ("Keep my names"); Plex and
    Jellyfin both read Maku's names."""
    row = conn.execute("SELECT value FROM settings WHERE key = 'naming'").fetchone()
    return row is not None and json.loads(row["value"]) == "keep"


def reports_wanted(conn: sqlite3.Connection) -> bool:
    """Whether Maku writes a gap analysis next to each series (the owner can turn it off)."""
    row = conn.execute("SELECT value FROM settings WHERE key = 'reports'").fetchone()
    return row is None or json.loads(row["value"]) is not False


def library_standard(conn: sqlite3.Connection) -> Standard:
    """The standard the owner chose in setup or Settings: 4K (the first choice) or 1080p, the
    most any picture comes to."""
    row = conn.execute("SELECT value FROM settings WHERE key = 'standard'").fetchone()
    chosen = json.loads(row["value"]) if row else None
    return STANDARDS.get(chosen, UHD) if isinstance(chosen, str) else UHD


def artwork_wanted(conn: sqlite3.Connection) -> bool:
    """Whether Maku keeps poster and background pictures next to each show (off unless the owner
    turns it on: it writes into the library's folders)."""
    row = conn.execute("SELECT value FROM settings WHERE key = 'artwork'").fetchone()
    return row is not None and json.loads(row["value"]) is True


def originals_deleted(conn: sqlite3.Connection) -> bool:
    """Whether a converted file's original is deleted once its result is checked and in place,
    instead of waiting in quarantine (Settings > Your data, and Convert)."""
    row = conn.execute("SELECT value FROM settings WHERE key = 'originals'").fetchone()
    return row is not None and json.loads(row["value"]) == "delete"


def history_days(conn: sqlite3.Connection) -> int | None:
    """How many days History keeps what Maku did before it's cleared out each day (Settings >
    Your data), or None: for good, the first choice."""
    row = conn.execute("SELECT value FROM settings WHERE key = 'history_days'").fetchone()
    days = json.loads(row["value"]) if row else None
    return days if days in (7, 30, 90) else None


def quarantine_days(conn: sqlite3.Connection) -> int | None:
    """How many days what's set aside is kept before it's cleared out (Settings > Your data), or
    None: for good."""
    row = conn.execute("SELECT value FROM settings WHERE key = 'quarantine_days'").fetchone()
    days = json.loads(row["value"]) if row else 30
    return days if days is None or days in (7, 30, 90) else 30
