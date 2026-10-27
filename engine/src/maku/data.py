"""Where Maku keeps its data, and how big each part is, for Settings > Your data: the database,
posters, the cache, logs, backups and the tools in the data folder, and the quarantine folder on
each drive the library is on (copies set aside and converted files' originals)."""

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from maku.config import DataPaths
from maku.core.library import QUARANTINE_FOLDER


@dataclass(frozen=True)
class Quarantined:
    folder: Path  # D:\Maku quarantine
    bytes: int
    files: int


@dataclass(frozen=True)
class DataSizes:
    folder: Path
    database: int  # maku.db with its write-ahead log
    artwork: int
    cache: int  # answers from TMDB, stills and comparison frames
    logs: int
    backups: int
    tools: int  # ffmpeg
    quarantine: tuple[Quarantined, ...]


def sizes(paths: DataPaths, library_folders: Iterable[Path]) -> DataSizes:
    """How big each part of Maku's data is now. The quarantine folders are looked for on the
    drives the library folders are on; a drive that isn't connected is left out."""
    database = sum(
        _size(paths.database.with_name(paths.database.name + end)) for end in ("", "-wal", "-shm")
    )
    quarantines: list[Quarantined] = []
    for drive in sorted({Path(folder.anchor) for folder in library_folders}):
        folder = drive / QUARANTINE_FOLDER
        if folder.is_dir():
            total, count = _tree(folder)
            quarantines.append(Quarantined(folder, total, count))
    return DataSizes(
        folder=paths.root,
        database=database,
        artwork=_tree(paths.artwork)[0],
        cache=_tree(paths.cache)[0],
        logs=_tree(paths.logs)[0],
        backups=_tree(paths.root / "backups")[0],
        tools=_tree(paths.tools)[0],
        quarantine=tuple(quarantines),
    )


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _tree(folder: Path) -> tuple[int, int]:
    """The bytes and files under a folder, nothing when it isn't there."""
    total = count = 0
    for parent, _, names in os.walk(folder):
        for name in names:
            total += _size(Path(parent) / name)
            count += 1
    return total, count
