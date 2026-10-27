"""The picture across the top of a video's or an episode's details: TMDB's picture from the
episode, else a frame from the video itself, else its show's wide picture (TMDB's background).
Each is fetched or taken once, then kept. A picture from the episode can give
its story away, so it says which it is: the window blurs one of an episode not yet watched till the
owner asks."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from maku import artwork, stills
from maku.config import DataPaths
from maku.web import Send


@dataclass(frozen=True)
class Picture:
    path: Path
    from_episode: bool  # TMDB's picture from it, or a frame: not its show's


def of_episode(
    conn: sqlite3.Connection,
    paths: DataPaths,
    transport: Send,
    title_id: int,
    season: int,
    number: int,
) -> Picture | None:
    """One of a title's episodes, the library's or not: TMDB's picture from it, or its show's.
    None when there's neither, or they can't be fetched now."""
    row = conn.execute(
        "SELECT still FROM episodes WHERE title_id = ? AND season = ? AND number = ?",
        (title_id, season, number),
    ).fetchone()
    if row is None:
        return None
    found = artwork.picture(paths, artwork.still_address(row["still"]), transport)
    if found is not None:
        return Picture(found, from_episode=True)
    return _show(conn, paths, transport, title_id)


def of_file(
    conn: sqlite3.Connection,
    paths: DataPaths,
    transport: Send,
    ffmpeg: Path | None,
    file_id: int,
) -> Picture | None:
    """A video in the library: TMDB's picture from its episode, a frame from the file, or its
    show's. A film, or another file that isn't an episode, has its own wide picture first: a
    frame could give its story away, and there's no picture from an episode. None when there's
    none of them."""
    row = conn.execute(
        """SELECT f.path, f.duration, f.problem, f.title_id, f.episode, e.still FROM files AS f
           LEFT JOIN episodes AS e
             ON e.title_id = f.title_id AND e.season = f.season AND e.number = f.episode
           WHERE f.id = ? AND f.gone_at IS NULL""",
        (file_id,),
    ).fetchone()
    if row is None:
        return None
    episode = row["episode"] is not None
    if not episode and row["title_id"] is not None:
        own = _show(conn, paths, transport, row["title_id"])
        if own is not None:
            return own
    found = artwork.picture(paths, artwork.still_address(row["still"]), transport)
    if found is None and row["problem"] is None:
        found = stills.picture(paths, ffmpeg, Path(row["path"]), row["duration"])
    if found is not None:
        return Picture(found, from_episode=True)
    if row["title_id"] is None or not episode:  # a film's own was asked for first
        return None
    return _show(conn, paths, transport, row["title_id"])


def _show(
    conn: sqlite3.Connection, paths: DataPaths, transport: Send, title_id: int
) -> Picture | None:
    """A title's wide picture: TMDB's background."""
    row = conn.execute("SELECT backdrop FROM titles WHERE id = ?", (title_id,)).fetchone()
    if row is None:
        return None
    found = artwork.picture(paths, artwork.background_address(row["backdrop"]), transport)
    return Picture(found, from_episode=False) if found is not None else None
