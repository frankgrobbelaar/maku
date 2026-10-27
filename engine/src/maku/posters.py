"""Choosing a title's poster: the ones TMDB has of it (in English or without words), the owner's
choice kept over the one Maku found (`titles.poster_choice`), and the poster next to the show
(maku/artwork_files.py) following it. Every reader of a title's poster takes the choice first:
`COALESCE(poster_choice, poster)`.
"""

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from maku.artwork import poster_address
from maku.artwork_files import POSTER
from maku.tmdb import Tmdb
from maku.web import WebError

log = logging.getLogger(__name__)

SHOWN = 24  # TMDB's posters offered at most


@dataclass(frozen=True)
class Option:
    """A poster the owner can choose."""

    poster: str  # what's kept: TMDB's image path
    language: str | None  # "en"; None for one without words
    width: int | None
    height: int | None


@dataclass(frozen=True)
class Choices:
    found: str | None  # the poster TMDB gave it
    chosen: str | None  # the owner's, when they chose one
    options: list[Option]
    problem: str | None  # why TMDB's couldn't be asked for now


def choices(conn: sqlite3.Connection, title_id: int, tmdb: Tmdb | None) -> Choices | None:
    """The posters to choose from for a title, the one it has first. None when Maku has no such
    title."""
    row = conn.execute(
        "SELECT poster, poster_choice, tmdb_type, tmdb_id FROM titles WHERE id = ?", (title_id,)
    ).fetchone()
    if row is None:
        return None
    options: list[Option] = []
    problem: str | None = None
    media = row["tmdb_type"]
    if tmdb is not None and media in ("tv", "movie") and row["tmdb_id"] is not None:
        try:
            pictures = tmdb.pictures(media, row["tmdb_id"])
        except WebError as error:
            problem = f"TMDB's posters couldn't be asked for now: {error}"
            pictures = []
        options += [
            Option(each.path, each.language, each.width, each.height) for each in pictures[:SHOWN]
        ]
    # The poster it has, first, even when TMDB lists it no longer.
    current = row["poster_choice"] or row["poster"]
    if current and poster_address(current):
        have = next((each for each in options if each.poster == current), None)
        options = [
            have or Option(current, None, None, None),
            *(each for each in options if each.poster != current),
        ]
    return Choices(row["poster"], row["poster_choice"], options, problem)


def choose(conn: sqlite3.Connection, title_id: int, poster: str | None) -> bool:
    """Keeps the owner's choice of poster (None: back to the one found). The poster next to the
    show that Maku wrote, as it wrote it, goes, so the next look writes the new one. False when
    there's no such title, or the poster isn't TMDB's."""
    if poster is not None and poster_address(poster) is None:
        return False
    with conn:
        done = conn.execute("UPDATE titles SET poster_choice = ? WHERE id = ?", (poster, title_id))
    if done.rowcount == 0:
        return False
    _make_way(conn, title_id)
    return True


def _make_way(conn: sqlite3.Connection, title_id: int) -> None:
    """Takes away the poster Maku wrote next to the show, if it's still as Maku wrote it."""
    rows = conn.execute(
        "SELECT path, size FROM artwork_files WHERE title_id = ?", (title_id,)
    ).fetchall()
    for row in rows:
        path = Path(row["path"])
        if path.name != POSTER:
            continue
        try:
            if path.stat().st_size != row["size"]:
                continue  # the owner's now
            path.unlink()
        except OSError as error:
            log.info("Maku couldn't take away %s: %s", path, error)
            continue
        with conn:
            conn.execute("DELETE FROM artwork_files WHERE path = ?", (row["path"],))
