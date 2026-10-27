r"""Where a file belongs and what it's called: Plex's layout, made safe for Windows.

TV\The Harbour Line (2019)\Season 01\The Harbour Line (2019) - S01E01 - Pilot.mkv
Movies\Starfall - Ascent (2015)\Starfall - Ascent (2015).mkv
"""

import re
from pathlib import PurePath

MAX_PATH = 259  # Windows allows 260 characters, counting the closing null
SHORTEST_TITLE = 8  # a shortened episode title shorter than this is dropped instead


class PathTooLongError(ValueError):
    """Even the shortest name would make the path longer than Windows allows."""


def episode_path(
    root: PurePath,
    show: str,
    year: int | None,
    *,
    season: int,
    episode: int,
    last_episode: int | None = None,
    title: str | None = None,
    extension: str,
) -> PurePath:
    """An episode's place in the library. Season 0 holds the specials."""
    show_name = _with_year(show, year)
    numbers = f"S{season:02d}E{episode:02d}"
    if last_episode is not None:
        numbers += f"-E{last_episode:02d}"
    folder = root / "TV" / show_name / f"Season {season:02d}"
    return _fit(folder, f"{show_name} - {numbers}", safe_name(title) if title else None, extension)


def movie_path(
    root: PurePath, title: str, year: int | None, *, extension: str, part: int | None = None
) -> PurePath:
    """A movie's place in the library, in a folder of its own. A film in several files has its
    parts named the way Plex stacks them ("- pt1", "- pt2")."""
    name = _with_year(title, year)
    path = root / "Movies" / name / f"{name}{f' - pt{part}' if part else ''}{extension}"
    if len(str(path)) > MAX_PATH:
        raise PathTooLongError(f"{path} is longer than Windows allows.")
    return path


def safe_name(text: str) -> str:
    """One file or folder name that Windows accepts, kept as close to the original as possible.

    Colons and question marks inside a name become dashes ("Starfall: Ascent" becomes
    "Starfall - Ascent", "Signal:Zero" becomes "Signal-Zero"); a question mark at the end goes.
    Slashes and bars become dashes, double quotes single ones, and the other characters Windows
    refuses are dropped, as are trailing dots and spaces.
    """
    name = re.sub(r"[\x00-\x1f]", " ", text)
    name = re.sub(r"\s*[:?]\s+", " - ", name)
    name = re.sub(r"[:/\\|]", "-", name).replace('"', "'")
    name = re.sub(r"[?*<>]", "", name)
    name = re.sub(r"\s+", " ", name).strip(" -").rstrip(". -").lstrip(". ")
    if not name:
        raise ValueError(f"{text!r} has nothing Windows can use as a name.")
    if name.split(".")[0].casefold() in _RESERVED:
        name += "_"
    return name


def unique_path(path: PurePath, taken: set[str]) -> PurePath:
    """The path, or the same name with (2), (3)… added, so no file is ever overwritten.

    `taken` holds the paths already in use. Windows ignores case in names, so this does too.
    """
    used = {name.casefold() for name in taken}
    candidate, number = path, 2
    while str(candidate).casefold() in used:
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        number += 1
    return candidate


_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)


def _with_year(title: str, year: int | None) -> str:
    name = safe_name(title)
    return f"{name} ({year})" if year else name


def _fit(folder: PurePath, stem: str, episode_title: str | None, extension: str) -> PurePath:
    """The file name with as much of the episode title as fits within MAX_PATH."""

    def path(title: str | None) -> PurePath:
        return folder / (f"{stem} - {title}{extension}" if title else f"{stem}{extension}")

    if episode_title:
        full = path(episode_title)
        if len(str(full)) <= MAX_PATH:
            return full
        room = len(episode_title) - (len(str(full)) - MAX_PATH)
        if shortened := _shorten(episode_title, room):
            return path(shortened)

    bare = path(None)
    if len(str(bare)) > MAX_PATH:
        raise PathTooLongError(f"{bare} is longer than Windows allows.")
    return bare


def _shorten(text: str, length: int) -> str | None:
    """Cuts text to at most `length` characters, at a word boundary."""
    if length < SHORTEST_TITLE:
        return None
    cut = text[:length]
    if len(text) > length and text[length] != " " and " " in cut:
        cut = cut.rsplit(" ", 1)[0]  # don't end in the middle of a word
    cut = cut.rstrip(" -,.;")
    return cut if len(cut) >= SHORTEST_TITLE else None
