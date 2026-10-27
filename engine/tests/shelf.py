"""A library on disk for tests: files found, read, and identified with TMDB stood in for
(tests/services.py)."""

import itertools
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from maku.config import DataPaths
from maku.core.fields import Json
from maku.identify import Identified, Identifier
from maku.library import add_folder, find_files, folders, read_file, unread
from tests.fake_ffprobe import REPORT
from tests.fake_web import FakeWeb

NOW = datetime(2026, 10, 11, 9, 30, tzinfo=UTC)


def library(conn: sqlite3.Connection, root: Path, names: list[str], minutes: float = 24) -> None:
    """Puts these files in a library folder, found and read (each `minutes` long). Called again,
    it adds more files to the same folder."""
    conn.execute("PRAGMA synchronous = OFF")  # hundreds of commits; no power cuts in tests
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(name.encode())
    if not folders(conn):
        add_folder(conn, root, now=NOW)
    [folder] = folders(conn)
    find_files(conn, folder, stamp=NOW.isoformat())
    format_ = cast("dict[str, object]", REPORT["format"])
    report: Json = {**REPORT, "format": {**format_, "duration": str(minutes * 60)}}
    for file_id, path in unread(conn):
        read_file(conn, file_id, path, lambda _: report, now=NOW)


def identify(paths: DataPaths, conn: sqlite3.Connection, web: FakeWeb) -> Identified:
    clock = itertools.count()
    identifier = Identifier(paths, web, now=lambda: NOW + timedelta(seconds=next(clock)))
    done = identifier.run(conn)
    assert done is not None
    return done
