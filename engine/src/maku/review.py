"""The files waiting for the owner to say which series or film they are, with everything that
helps decide: the file's facts, Maku's best guesses, and the other files beside it that look the
same, so one choice can settle them all. A title's files can be asked about again too, to change
its match, and the files the owner said aren't a series or film are listed, to take that back.
"""

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import cast

from maku.core.media import media_from_ffprobe
from maku.core.names import Kind, ParsedName, parse_name


@dataclass(frozen=True)
class Waiting:
    id: int
    path: str
    size: int
    minutes: float | None
    height: int | None
    codec: str | None
    audio: tuple[str, ...]  # languages, as the file names them
    subtitles: tuple[str, ...]
    parsed: ParsedName
    guesses: tuple[Mapping[str, object], ...]  # as maku/identify.py saved them
    alike: tuple[int, ...]  # other waiting files beside it from the same release


def waiting(conn: sqlite3.Connection) -> list[Waiting]:
    """Every file Maku couldn't place surely, folder by folder, in name order."""
    rows = conn.execute(
        """SELECT id, path, size, duration, height, codec, probe, guesses FROM files
           WHERE matched IN ('unsure', 'none') AND gone_at IS NULL AND pinned = 0
           ORDER BY path"""
    ).fetchall()
    parsed = {row["id"]: parse_name(PureWindowsPath(row["path"])) for row in rows}
    found: list[Waiting] = []
    for row in rows:
        path = PureWindowsPath(row["path"])
        mine = parsed[row["id"]]
        alike = tuple(
            other["id"]
            for other in rows
            if other["id"] != row["id"]
            and PureWindowsPath(other["path"]).parent == path.parent
            and _same_release(mine, parsed[other["id"]])
        )
        found.append(_waiting(row, mine, alike))
    return found


@dataclass(frozen=True)
class Ignored:
    id: int
    path: str
    size: int


def ignored(conn: sqlite3.Connection) -> list[Ignored]:
    """The files the owner said aren't a series or film, in name order: left where they are,
    out of the library."""
    rows = conn.execute(
        """SELECT id, path, size FROM files WHERE matched = 'ignored' AND gone_at IS NULL
           ORDER BY path"""
    ).fetchall()
    return [Ignored(row["id"], row["path"], row["size"]) for row in rows]


def of_title(conn: sqlite3.Connection, title_id: int) -> list[Waiting]:
    """A title's files as one choice, to change what it's matched to: its first episode (or
    its first file, when it has none), with all the others alike. Empty when the library holds
    none."""
    rows = conn.execute(
        """SELECT id, path, size, duration, height, codec, probe, guesses FROM files
           WHERE title_id = ? AND gone_at IS NULL
           ORDER BY season IS NULL, season = 0, season, episode, path""",
        (title_id,),
    ).fetchall()
    if not rows:
        return []
    first, *others = rows
    mine = parse_name(PureWindowsPath(first["path"]))
    return [_waiting(first, mine, tuple(other["id"] for other in others))]


def _waiting(row: sqlite3.Row, parsed: ParsedName, alike: tuple[int, ...]) -> Waiting:
    audio, subtitles = _languages(row["probe"])
    return Waiting(
        id=row["id"],
        path=row["path"],
        size=row["size"],
        minutes=row["duration"] / 60 if row["duration"] else None,
        height=row["height"],
        codec=row["codec"],
        audio=audio,
        subtitles=subtitles,
        parsed=parsed,
        guesses=_guesses(row["guesses"]),
        alike=alike,
    )


def _same_release(one: ParsedName, other: ParsedName) -> bool:
    """Files from one release: the same group tag, or the same title when there's no tag, and
    numbered episodes both (a film or an extra beside them is something else)."""
    if one.kind is not Kind.EPISODE or other.kind is not Kind.EPISODE:
        return False
    if one.group or other.group:
        return (one.group or "").casefold() == (other.group or "").casefold()
    return (one.best_title or "").casefold() == (other.best_title or "").casefold()


def _languages(probe: str | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not probe:
        return (), ()
    media = media_from_ffprobe(json.loads(probe))
    audio = tuple(dict.fromkeys(a.language or "unknown" for a in media.audio))
    subtitles = tuple(dict.fromkeys(s.language or "unknown" for s in media.subtitles))
    return audio, subtitles


def _guesses(saved: str | None) -> tuple[Mapping[str, object], ...]:
    if not saved:
        return ()
    found: object = json.loads(saved)
    if not isinstance(found, list):
        return ()
    items = cast("list[object]", found)
    return tuple(cast("Mapping[str, object]", item) for item in items if isinstance(item, dict))
