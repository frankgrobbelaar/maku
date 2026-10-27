"""Export: everything Maku knows, in one zip you can open without Maku."""

import csv
import io
import json
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

from maku import __version__, db
from maku.config import DataPaths


def export_data(paths: DataPaths, folder: Path, now: datetime | None = None) -> Path | None:
    """Write `Maku export <date>.zip` into `folder` and return its path.

    Returns None when Maku has no data yet. Never overwrites a file: a second
    export on the same day becomes `Maku export <date> (2).zip`.
    """
    if not paths.database.exists():
        return None
    now = now or datetime.now().astimezone()
    folder.mkdir(parents=True, exist_ok=True)
    target = _unused_name(folder / f"Maku export {now:%Y-%m-%d}.zip")

    with tempfile.TemporaryDirectory() as scratch:
        snapshot = Path(scratch) / "maku.db"
        with (
            closing(db.connect(paths.database)) as source,
            closing(sqlite3.connect(snapshot)) as copy,
        ):
            source.backup(copy)
            copy.execute("PRAGMA journal_mode = DELETE")  # one self-contained file
            settings = _settings(source)
            changes = _changes_csv(source)
            library = _library_csv(source)
            schema_version = db.schema_version(source)

        manifest = {
            "app": "Maku",
            "version": __version__,
            "exportedAt": now.isoformat(timespec="seconds"),
            "schemaVersion": schema_version,
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, "maku.db")
            archive.writestr("settings.json", json.dumps(settings, indent=2))
            if changes is not None:
                # With a byte order mark, so Excel shows Japanese titles and accents.
                archive.writestr("changes.csv", changes.encode("utf-8-sig"))
            if library is not None:
                archive.writestr("library.csv", library.encode("utf-8-sig"))
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    return target


def _settings(conn: sqlite3.Connection) -> dict[str, object]:
    if not _has_table(conn, "settings"):
        return {}
    rows = conn.execute("SELECT key, value FROM settings ORDER BY key")
    return {row["key"]: json.loads(row["value"]) for row in rows}


_CHANGE_COLUMNS = (
    "plan",
    "plan_title",
    "planned_at",
    "applied_at",
    "undone_at",
    "position",
    "kind",
    "state",
    "source",
    "target",
    "label",
    "reason",
    "problem",
)


def _changes_csv(conn: sqlite3.Connection) -> str | None:
    """Every change Maku planned, made or undone, one row each, or None before plans existed."""
    if not _has_table(conn, "changes"):
        return None
    rows = conn.execute(
        "SELECT p.id, p.title, p.created_at, p.applied_at, p.undone_at, c.position, c.kind,"
        " c.state, c.source, c.target, c.label, c.reason, c.problem"
        " FROM changes AS c JOIN plans AS p ON p.id = c.plan_id ORDER BY p.id, c.position"
    )
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(_CHANGE_COLUMNS)
    writer.writerows(tuple(row) for row in rows)
    return text.getvalue()


_LIBRARY_COLUMNS = (
    "folder",
    "path",
    "size",
    "found_at",
    "gone_at",
    "read_at",
    "duration",
    "width",
    "height",
    "codec",
    "problem",
    "title",
    "kind",
    "season",
    "episode",
    "matched",
)


_LIBRARY = (
    "SELECT d.path, f.path, f.size, f.found_at, f.gone_at, f.probed_at, f.duration,"
    " f.width, f.height, f.codec, f.problem, t.name, t.kind, f.season, f.episode, f.matched"
    " FROM files AS f JOIN folders AS d ON d.id = f.folder_id"
    " LEFT JOIN titles AS t ON t.id = f.title_id ORDER BY f.path"
)
_LIBRARY_BEFORE_TITLES = (
    "SELECT d.path, f.path, f.size, f.found_at, f.gone_at, f.probed_at, f.duration,"
    " f.width, f.height, f.codec, f.problem, NULL, NULL, NULL, NULL, NULL"
    " FROM files AS f JOIN folders AS d ON d.id = f.folder_id ORDER BY f.path"
)


def _library_csv(conn: sqlite3.Connection) -> str | None:
    """Every video Maku found, with what reading it showed, or None before the library existed."""
    if not _has_table(conn, "files"):
        return None
    # A database from before identification has no titles: those columns stay empty.
    rows = conn.execute(_LIBRARY if _has_table(conn, "titles") else _LIBRARY_BEFORE_TITLES)
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(_LIBRARY_COLUMNS)
    writer.writerows(tuple(row) for row in rows)
    return text.getvalue()


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    query = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
    return conn.execute(query, (name,)).fetchone() is not None


def _unused_name(path: Path) -> Path:
    candidate, number = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        number += 1
    return candidate
