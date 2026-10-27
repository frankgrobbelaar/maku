"""The library searched from the title bar: its series and films by any name they go by, their
episodes by code or name, and its videos by their files' names, the closest first.

An episode or a video is found by something of its own, its code, its name or its file's: every
episode of a show has the show's name, so a search for the show finds the show, not all of them.
"""

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import PureWindowsPath
from typing import Literal

from maku.core.catalog import TitleKind
from maku.core.search import closeness, found, words

type Place = Literal["title", "match", "aside", "extra", "other", "reading"]


@dataclass(frozen=True)
class TitleFound:
    id: int
    name: str
    kind: TitleKind
    year: int | None
    has_poster: bool
    also: str | None  # the other name it was found by ("La Ligne du Port"), if not its own


@dataclass(frozen=True)
class EpisodeFound:
    title_id: int
    title: str
    season: int  # 0 for a special
    number: int
    name: str | None
    file_id: int | None  # its video, or None when the library hasn't it
    coming: bool  # not out yet


@dataclass(frozen=True)
class FileFound:
    file_id: int
    path: str
    title_id: int | None
    title: str | None
    season: int | None
    episode: int | None
    episode_end: int | None
    # Where it is: in a title, waiting for a match, set aside as not a series or film, an extra (an
    # opening, an ending, a preview), under no title for another reason, or still being read.
    place: Place


@dataclass(frozen=True)
class Found:
    titles: list[TitleFound]
    episodes: list[EpisodeFound]
    files: list[FileFound]
    # How many each search found in all, the closest of them listed.
    total_titles: int
    total_episodes: int
    total_files: int


NOTHING = Found([], [], [], 0, 0, 0)


def search(conn: sqlite3.Connection, query: str, today: date, *, limit: int = 6) -> Found:
    """What `query` finds in the library, each kind's closest `limit` first."""
    wanted = words(query)
    if not wanted:
        return NOTHING
    titles = _titles(conn, wanted)
    episodes = _episodes(conn, wanted, today)
    # A video the search found as an episode isn't listed again as a video.
    known = {(each.title_id, each.season, each.number) for each in episodes}
    files = [
        each
        for each in _files(conn, wanted)
        if not any((each.title_id, each.season, number) in known for number in _numbers_of(each))
    ]
    return Found(
        titles=titles[:limit],
        episodes=episodes[:limit],
        files=files[:limit],
        total_titles=len(titles),
        total_episodes=len(episodes),
        total_files=len(files),
    )


def _titles(conn: sqlite3.Connection, wanted: list[str]) -> list[TitleFound]:
    rows = conn.execute(
        """SELECT t.id, t.name, t.kind, t.year, t.released,
                  COALESCE(t.poster_choice, t.poster) AS poster, a.names
           FROM titles AS t LEFT JOIN entries AS a ON a.id = t.entry_id
           WHERE EXISTS (SELECT 1 FROM files AS f WHERE f.title_id = t.id AND f.gone_at IS NULL)"""
    ).fetchall()
    hits: list[tuple[tuple[int, str, str], TitleFound]] = []
    for row in rows:
        others = [name for name in _names(row["names"]) if name != row["name"]]
        if not found(wanted, row["name"], *others):
            continue
        also = None if found(wanted, row["name"]) else _first(wanted, others)
        rank = (closeness(wanted, also or row["name"]), row["released"] or "9999", row["name"])
        hits.append(
            (
                rank,
                TitleFound(
                    id=row["id"],
                    name=row["name"],
                    kind=TitleKind(row["kind"]),
                    year=row["year"],
                    has_poster=row["poster"] is not None,
                    also=also,
                ),
            )
        )
    return [title for _, title in sorted(hits, key=lambda hit: hit[0])]


def _episodes(conn: sqlite3.Connection, wanted: list[str], today: date) -> list[EpisodeFound]:
    held = _held(conn)
    rows = conn.execute(
        """SELECT e.title_id, t.name AS title, e.season, e.number, e.name, e.aired,
                  t.airing AS airing
           FROM episodes AS e JOIN titles AS t ON t.id = e.title_id
           WHERE EXISTS (SELECT 1 FROM files AS f WHERE f.title_id = t.id AND f.gone_at IS NULL)"""
    ).fetchall()
    hits: list[tuple[tuple[int, int, str, int, int], EpisodeFound]] = []
    for row in rows:
        code = _code(row["season"], row["number"])
        if not _own(wanted, row["title"], code, row["name"]):
            continue
        file_id = held.get((row["title_id"], row["season"], row["number"]))
        # As the gap check has it (maku/core/gaps.py): one without a date is out unless its
        # show still airs.
        aired = date.fromisoformat(row["aired"][:10]) if row["aired"] else None
        coming = aired > today if aired else bool(row["airing"])
        rank = (
            file_id is None,  # what the library has first
            closeness(wanted, row["name"] or code),
            row["title"],
            row["season"] or 1_000,  # the specials after the seasons
            row["number"],
        )
        hits.append(
            (
                rank,
                EpisodeFound(
                    title_id=row["title_id"],
                    title=row["title"],
                    season=row["season"],
                    number=row["number"],
                    name=row["name"],
                    file_id=file_id,
                    coming=coming and file_id is None,
                ),
            )
        )
    return [episode for _, episode in sorted(hits, key=lambda hit: hit[0])]


def _files(conn: sqlite3.Connection, wanted: list[str]) -> list[FileFound]:
    rows = conn.execute(
        """SELECT f.id, f.path, f.title_id, t.name AS title, f.season, f.episode, f.episode_end,
                  f.matched, f.pinned, f.identified_at
           FROM files AS f LEFT JOIN titles AS t ON t.id = f.title_id
           WHERE f.gone_at IS NULL"""
    ).fetchall()
    hits: list[tuple[tuple[int, str], FileFound]] = []
    for row in rows:
        name = PureWindowsPath(row["path"]).name
        if not _own(wanted, row["title"], name):
            continue
        hits.append(
            (
                (closeness(wanted, name), row["path"].casefold()),
                FileFound(
                    file_id=row["id"],
                    path=row["path"],
                    title_id=row["title_id"],
                    title=row["title"],
                    season=row["season"],
                    episode=row["episode"],
                    episode_end=row["episode_end"],
                    place=_place(row),
                ),
            )
        )
    return [file for _, file in sorted(hits, key=lambda hit: hit[0])]


def _own(wanted: list[str], title: str | None, *texts: str | None) -> bool:
    """Whether what was typed finds something by what's its own (`texts`), its title's name
    perhaps helping: "starfall lantern" finds Starfall's "Lantern Festival", "starfall" alone
    none of Starfall's episodes."""
    return found(wanted, title, *texts) and not (title and found(wanted, title))


def _held(conn: sqlite3.Connection) -> dict[tuple[int, int, int], int]:
    """The video each episode the library has is in, a video holding several episodes in each."""
    rows = conn.execute(
        """SELECT id, title_id, season, episode, episode_end FROM files
           WHERE gone_at IS NULL AND title_id IS NOT NULL AND season IS NOT NULL
             AND episode IS NOT NULL
           ORDER BY problem IS NOT NULL, id"""  # one that plays first
    )
    held: dict[tuple[int, int, int], int] = {}
    for row in rows:
        for number in range(row["episode"], (row["episode_end"] or row["episode"]) + 1):
            held.setdefault((row["title_id"], row["season"], number), row["id"])
    return held


def _numbers_of(file: FileFound) -> Iterable[int]:
    if file.season is None or file.episode is None:
        return ()
    return range(file.episode, (file.episode_end or file.episode) + 1)


def _place(row: sqlite3.Row) -> Place:
    if row["matched"] == "ignored":
        return "aside"
    if row["title_id"] is not None:
        return "title"
    if row["identified_at"] is None:
        return "reading"
    if row["matched"] == "extra":
        return "extra"
    if row["matched"] in ("unsure", "none") and not row["pinned"]:
        return "match"
    return "other"


def _names(stored: str | None) -> list[str]:
    """The names TMDB says an entry goes by, as kept (JSON; maku/identify.py)."""
    names: list[str] = json.loads(stored or "[]")
    return names


def _first(wanted: list[str], names: Sequence[str]) -> str | None:
    return next((name for name in names if found(wanted, name)), None)


def _code(season: int, number: int) -> str:
    return f"S{season:02d}E{number:02d}"
