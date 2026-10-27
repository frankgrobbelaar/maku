"""The library's folders and files: where a scan never looks, how folders may sit together, how
big a picture is, and how long a scan has left. Pure rules; maku/library.py does the looking.
What counts as a video is in maku/core/extensions.py.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePath, PureWindowsPath
from typing import Literal

QUARANTINE_FOLDER = "Maku quarantine"  # on each drive: copies set aside, never scanned
WORKING = ".maku-converting"  # the end of a result's name while it's made beside its original

# Maku's own quarantine, and the folders Windows keeps on every drive.
_SKIPPED = frozenset(
    name.casefold()
    for name in (QUARANTINE_FOLDER, "$RECYCLE.BIN", "RECYCLER", "System Volume Information")
)
_MIN_FILES_FOR_PACE = 5


def work_of[P: PurePath](source: P) -> P:
    """Where a file's converted result is made: beside it, named after it whole
    ("Ep01.avi.maku-converting"), so a same-named file of another kind (Ep01.mp4) has its own."""
    return source.with_name(source.name + WORKING)


def drive_of(path: str | PurePath) -> str:
    r"""The drive a path is on, as Maku writes it: "D:" (or "\\server\share")."""
    return PureWindowsPath(path).drive


def skipped_folder(name: str) -> bool:
    """Folders a scan never looks into: Maku's quarantine, Windows' own, and hidden ones."""
    folded = name.casefold()
    return folded in _SKIPPED or folded.startswith(".")


@dataclass(frozen=True)
class Covered:
    """The new folder is already in the library, or inside a folder that is."""

    by: PureWindowsPath


@dataclass(frozen=True)
class Holds:
    """The new folder holds folders already in the library, which it takes in."""

    folders: tuple[PureWindowsPath, ...]


def fits(new: PureWindowsPath, existing: Iterable[PureWindowsPath]) -> Covered | Holds | None:
    """How a new library folder sits beside the ones already there. None: on its own."""
    folders = list(existing)
    for folder in folders:
        if new == folder or new.is_relative_to(folder):
            return Covered(folder)
    held = tuple(folder for folder in folders if folder.is_relative_to(new))
    return Holds(held) if held else None


type Picture = Literal["sd", "720p", "1080p", "larger", "unknown"]


def picture_size(width: int | None, height: int | None) -> Picture:
    """The picture's size class, by height or, for wide films, by width: 1920x800 is 1080p."""
    if not width or not height:
        return "unknown"
    lines = max(height, width * 9 / 16)
    if lines <= 576:
        return "sd"
    if lines <= 800:
        return "720p"
    if lines <= 1200:
        return "1080p"
    return "larger"


def time_left(done: int, total: int, elapsed: float) -> float | None:
    """Seconds left at the pace so far, or None until there's enough of a pace to go by."""
    if done >= total:
        return 0.0
    if done < _MIN_FILES_FOR_PACE:
        return None
    return (total - done) * elapsed / done
