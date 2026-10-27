r"""Moving Maku's data folder to another drive, all of it: the database, artwork, cache, backups,
logs and tools. The owner asks in Settings; the move happens as the engine starts again, before
anything opens a file there (the app starts it again right after asking). The data is copied and
checked, and only then does the old copy go. The home folder (%LOCALAPPDATA%\Maku) keeps a note
of where the data went (config.LOCATION), which is how Maku, `maku export` and the uninstaller
find it. A move that fails leaves everything where it was, and says why. While it moves, the home
keeps another note (moving.json), so a move cut short (a power cut) is settled at the next start:
finished when the data had switched to its new place, else the part-made copy goes.
"""

import json
import logging
import shutil
import sqlite3
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from maku import db, events
from maku.config import LOCATION, NOTE_ENCODING, DataPaths
from maku.core.library import drive_of
from maku.system import on_network

log = logging.getLogger(__name__)

_ASKED = "move.txt"  # in the data folder: where the owner asked it to go, till the next start
_MOVING = "moving.json"  # in the home folder while the data moves: where from, and where to
_CUT_SHORT = "Maku stopped while it moved the data, so it stayed where it was."
_MOVED = "data_moved"  # the settings row saying how the last move went
_ROOM = 1.1  # free space wanted on the new drive, over the data's size


class MoveError(Exception):
    """The data can't go there, or didn't get there. The message says why."""


@dataclass(frozen=True)
class Moved:
    """How the last move went."""

    source: str  # the folder the data left
    target: str  # the folder it went to (or was to go to)
    at: str
    problem: str | None  # why it stayed, if it did


def ask_to_move(paths: DataPaths, target: Path) -> None:
    """Checks the folder can take Maku's data (on this PC, empty or new, outside the data folder,
    with room), then asks for the move as the engine next starts. A folder on another computer
    won't do: the database's write-ahead log needs a drive of this PC's own."""
    if on_network(target):
        raise MoveError(
            f"{target} is on another computer. Maku's data needs a drive of this PC's own "
            "(an external one is fine)."
        )
    root, target = paths.root.resolve(), target.resolve()
    if target == root:
        raise MoveError("Maku's data is there already.")
    if target.is_relative_to(root):
        raise MoveError("That folder is inside Maku's data folder: choose one outside it.")
    if target.exists() and (not target.is_dir() or _contents(target)):
        raise MoveError(f"{target} isn't empty: choose an empty folder, or a new one.")
    needed = _size(root)
    free = shutil.disk_usage(_nearest(target)).free
    if free < needed * _ROOM:
        raise MoveError(
            f"There isn't room on {drive_of(target) or target.anchor} for Maku's data: it takes"
            f" {_words(needed)}, and {_words(free)} is free."
        )
    (root / _ASKED).write_text(str(target), encoding="utf-8")


def move_asked(home: Path, now: datetime) -> DataPaths:
    """As the engine starts, before anything opens a file in the data folder: settles a move a
    stop cut short, then moves the data where the owner asked, if they did. Returns where the
    data is now."""
    _settle(home, now)
    paths = DataPaths.at(home)
    asked = paths.root / _ASKED
    try:
        target = Path(asked.read_text(encoding="utf-8").strip())
    except OSError:
        return paths  # none asked for, or the data's drive isn't there
    asked.unlink(missing_ok=True)  # asked once, tried once
    source = paths.root
    moving = home / _MOVING
    home.mkdir(parents=True, exist_ok=True)
    moving.write_text(json.dumps({"source": str(source), "target": str(target)}), encoding="utf-8")
    copied: list[str] = []
    try:
        with events.working():  # it can take minutes: the app waits while it's told so
            _checkpoint(paths.database)
            _copy(source, target, copied)
    except (OSError, sqlite3.Error, MoveError) as error:
        for name in copied:  # only what the move made
            _remove(target / name)
        with suppress(OSError):
            target.rmdir()  # when the move made it, and nothing else is there
        moving.unlink(missing_ok=True)
        problem = error.strerror if isinstance(error, OSError) and error.strerror else str(error)
        log.warning("Maku's data stayed in %s: %s", source, problem)
        _note(paths.database, Moved(str(source), str(target), now.isoformat(), problem))
        return paths
    _switch(home, target)
    with events.working():  # the old copy can take a while to go, too
        _clear_away(source, [target / name for name in copied], home)
    moving.unlink(missing_ok=True)
    moved = DataPaths(target)
    _note(moved.database, Moved(str(source), str(target), now.isoformat(), None))
    return moved


def _settle(home: Path, now: datetime) -> None:
    """A move a stop cut short (a power cut, or the app ending the engine): when the data had
    switched to its new place, what's left of the old copy goes; else the part-made new copy
    goes, and the data stays where it was. Either way, Settings says how it went."""
    moving = home / _MOVING
    try:
        found = json.loads(moving.read_text(encoding="utf-8"))
        source, target = Path(found["source"]), Path(found["target"])
    except OSError, ValueError, KeyError, TypeError:
        return  # no move under way
    switched = DataPaths.at(home).root.resolve() == target.resolve()
    kept, left = (target, source) if switched else (source, target)
    if not kept.is_dir():
        return  # its drive isn't there: settled once it's back
    with events.working():
        _clear_away(left, _parts(kept), home)
    moving.unlink(missing_ok=True)
    problem = None if switched else _CUT_SHORT
    if problem:
        log.warning("Maku's data stayed in %s: a stop cut the move to %s short", source, target)
    _note(DataPaths(kept).database, Moved(str(source), str(target), now.isoformat(), problem))


def _switch(home: Path, target: Path) -> None:
    """The home's note points at the data's new place (none when it's the home itself)."""
    if target.resolve() == home.resolve():
        (home / LOCATION).unlink(missing_ok=True)
    else:
        (home / LOCATION).write_text(str(target), encoding=NOTE_ENCODING)


def _clear_away(folder: Path, parts: list[Path], home: Path) -> None:
    """Takes the data's parts (by name) out of a folder it left or never got to, then the folder
    itself once nothing of anyone else's is in it (the home stays)."""
    for part in parts:
        _remove(folder / part.name)
    if folder.resolve() != home.resolve():
        with suppress(OSError):
            folder.rmdir()


def last_move(conn: sqlite3.Connection) -> Moved | None:
    """How the last move went, if the data was ever asked to move."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (_MOVED,)).fetchone()
    if row is None:
        return None
    found = json.loads(row["value"])
    return Moved(found["source"], found["target"], found["at"], found.get("problem"))


def _copy(source: Path, target: Path, copied: list[str]) -> None:
    """Every part of the data folder into `target`, each name noted in `copied` as it goes;
    then the copy is checked: the same size, and a database that reads as sound."""
    target.mkdir(parents=True, exist_ok=True)
    parts = _parts(source)
    for item in parts:
        copied.append(item.name)
        if item.is_dir():
            shutil.copytree(item, target / item.name, copy_function=shutil.copy2)
        else:
            shutil.copy2(item, target / item.name)
    if sum(_size(item) for item in parts) != sum(_size(target / item.name) for item in parts):
        raise MoveError("The copy came out a different size, so the data stayed where it was.")
    database = target / DataPaths(target).database.name
    if database.is_file():
        with closing(sqlite3.connect(database)) as conn:
            [verdict] = conn.execute("PRAGMA integrity_check").fetchone()
        if verdict != "ok":
            raise MoveError(f"The copied database didn't check out ({verdict}).")


def _parts(root: Path) -> list[Path]:
    """What a data folder holds that moves: everything but the home's notes."""
    return [item for item in root.iterdir() if item.name not in (LOCATION, _ASKED, _MOVING)]


def _checkpoint(database: Path) -> None:
    """The database in one file: what its write-ahead log holds goes into it first."""
    if database.is_file():
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _note(database: Path, moved: Moved) -> None:
    """Keeps how the move went in the database it ended up with, for Settings to show."""
    if not database.is_file():
        return
    try:
        with closing(db.connect(database)) as conn, conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (_MOVED, json.dumps(moved.__dict__)),
            )
    except sqlite3.Error:
        log.exception("Maku couldn't note how moving its data went")


def _contents(folder: Path) -> list[Path]:
    """What's in a folder, but a note left by a move (a home folder holds only that)."""
    return [item for item in folder.iterdir() if item.name != LOCATION]


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _nearest(path: Path) -> Path:
    """The folder itself, or the nearest one above it that's there: where its drive is asked
    how much room it has."""
    while not path.exists() and path.parent != path:
        path = path.parent
    return path


def _words(size: int) -> str:
    if size >= 10**9:
        return f"{size / 10**9:.1f} GB"
    return f"{max(1, round(size / 10**6))} MB"
