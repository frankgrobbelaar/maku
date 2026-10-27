"""Identifying the library: which series or film, and which episode, every video is.

The scan's third stage. Files are grouped and looked up on TMDB with the owner's key (maku/
catalog.py); a show's episode lists say where each file sits and what's missing. A special its
show's list doesn't name the way the file does is looked up by its own name. maku/core/
identify.py and maku/core/placing.py decide, this module asks TMDB and keeps the answers. Without
a key nothing is looked up: the files wait. A file Maku isn't sure about waits for the owner, and
files the owner placed by hand (pinned) are never identified again.
"""

import json
import logging
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import PurePath, PureWindowsPath

from maku.cache import Cache
from maku.catalog import Catalog, NoKeyError, search_order
from maku.config import DataPaths
from maku.core.catalog import Entry, Film, Media, Show, TitleKind, tmdb_of
from maku.core.identify import (
    SURE,
    FileFacts,
    Group,
    Guess,
    group_files,
    guesses,
    respelled,
    searches,
)
from maku.core.names import Kind, ParsedName, parse_name
from maku.core.placing import Placement, named_special, numbered_through, place
from maku.titles import show_of
from maku.tmdb import Tmdb
from maku.web import Send, WebError

log = logging.getLogger(__name__)

AIRING_EVERY = timedelta(hours=1)  # how often a show still airing has its episode list refreshed
FINISHED_EVERY = timedelta(days=7)  # and a finished one
_SHOWN_GUESSES = 3  # how many guesses the review screen offers


@dataclass(frozen=True)
class Identified:
    sure: int  # files placed without asking
    unsure: int  # files waiting for the owner
    note: str | None  # what couldn't be done this time, in words


class UnplacedError(ValueError):
    """The owner's choice for a file Maku can't place as an episode: it needs the number."""


@dataclass(frozen=True)
class Placed:
    """What the owner's choice did."""

    placed: int  # files placed as chosen
    waiting: int  # files that didn't fit it, waiting for the owner now


@dataclass(frozen=True)
class _Home:
    """Where an entry's files go: a title, with its TMDB show when it's a show."""

    title_id: int
    show: Show | None = None
    film: bool = False  # the title is a film: a file is the whole of it
    specials: bool = False  # unused: TMDB keeps a show's specials in its season 0


class Identifier:
    def __init__(
        self,
        paths: DataPaths,
        transport: Send,
        *,
        now: Callable[[], datetime],
        catalog: Catalog | None = None,
    ) -> None:
        """`catalog` is the engine's one, sharing its kept answers."""
        self._paths = paths
        self._transport = transport
        self._now = now
        self._catalog = catalog or Catalog(paths, transport, cache=Cache(paths.cache))

    def run(
        self,
        conn: sqlite3.Connection,
        *,
        stop: Callable[[], bool] = lambda: False,
        looking_at: Callable[[str], None] = lambda _: None,
    ) -> Identified | None:
        """Identifies every file still to identify. None when `stop` asked to stop. Without a
        TMDB key nothing is looked up, and the note says so."""
        try:
            tmdb = self._catalog.tmdb()
        except NoKeyError as missing:
            return Identified(0, 0, str(missing))
        try:
            self._link_unlinked(conn)
        except WebError as error:  # the franchises form at the next scan
            log.warning("TMDB couldn't say which films go together: %s", error)
        files, others = _to_identify(conn)
        stamp = self._now().isoformat()
        _mark_unlookable(conn, others, stamp)

        found: list[tuple[Group, list[Guess]]] = []
        for group in group_files(files):
            if stop():
                return None
            looking_at(group.query)
            try:
                found.append((group, self._look_up(group)))
            except WebError as error:
                log.warning("TMDB couldn't be asked about %s: %s", group.query, error)
                return Identified(0, 0, _waiting("TMDB", error))

        sure = unsure = 0
        note: str | None = None
        # Series first, so the specials after them find their show already there.
        found.sort(key=lambda item: _series_last(item[1]))
        for group, ranked in found:
            if stop():
                return None
            looking_at(group.query)
            try:
                placed, waiting = self._settle(conn, group, ranked, tmdb)
            except WebError as error:
                log.warning("TMDB couldn't be asked about %s: %s", group.query, error)
                note = _waiting("TMDB", error)
                break
            sure, unsure = sure + placed, unsure + waiting
        return Identified(sure, unsure, note)

    def _look_up(self, group: Group, *, series: bool = True) -> list[Guess]:
        """TMDB's shows and films for a group, as guesses: the kind the files look like first
        (films for a film), the other only while none is sure, which spares TMDB half the asking.
        While none is sure, shorter forms of a numbered film's name are asked for too
        (core/identify.py's `searches`; its series alone unless `series` is False). When nothing
        at all is found, the name may be one TMDB writes otherwise ("Harbourline"): what its first
        word finds says how ("Harbour Line"), and the name is asked for that way."""
        entries: dict[int, Entry] = {}
        ranked: list[Guess] = []
        likely, other = search_order(films_first=group.movie)
        order: tuple[tuple[Media, bool], ...] = ((likely, True), (other, False))
        for text in searches(group, series=series):
            for media, first in order:
                for entry in self._catalog.search_kind(text, media, first=first):
                    entries.setdefault(entry.id, entry)
                ranked = guesses(group, list(entries.values()))
                if ranked and ranked[0].confidence >= SURE:
                    return ranked
        first, *rest = group.query.split()
        if not ranked and rest:
            near = self._catalog.search(first, films_first=group.movie)
            if again := respelled(group.query, near):
                ranked = guesses(group, self._catalog.search(again, films_first=group.movie))
        return ranked

    def choose(
        self,
        conn: sqlite3.Connection,
        file_id: int,
        entry_id: int,
        as_kind: Kind,
        *,
        also: Sequence[int] = (),
        episode: int | None = None,
    ) -> int:
        """The owner's choice: this file, and the others that are the same one (`also`), are
        this TMDB show or film (`entry_id`, core/catalog.py), as episodes, a film, or specials.
        `episode` is the file's number when its name has none Maku can use. It's pinned, so no
        rescan undoes it. Returns how many files it placed; one of `also` that Maku can't place
        keeps waiting. A special Maku can't number still belongs to its show (an extra, say).

        Raises UnplacedError when the file is an episode Maku can't place, LookupError when TMDB
        has no such show or film (NoKeyError without a key), and WebError when TMDB can't be
        asked right now.
        """
        ids = [file_id, *(other for other in also if other != file_id)]
        return self._place(conn, file_id, entry_id, dict.fromkeys(ids, as_kind), episode).placed

    def rematch(
        self,
        conn: sqlite3.Connection,
        title_id: int,
        file_id: int,
        entry_id: int,
        as_kind: Kind,
        *,
        episode: int | None = None,
    ) -> Placed:
        """The owner's new match for a whole title, chosen for one of its files (`file_id`, its
        first episode as maku/review.py shows it): every file of the title is this show or film.
        The files of that file's kind become `as_kind`; the others keep theirs, so a series'
        specials stay specials. A file that doesn't fit the entry waits for the owner.

        Raises LookupError when the file isn't the title's, and otherwise as `choose` does.
        """
        rows = conn.execute(
            """SELECT f.id, f.season, t.kind FROM files AS f
               JOIN titles AS t ON t.id = f.title_id
               WHERE f.title_id = ? AND f.gone_at IS NULL""",
            (title_id,),
        ).fetchall()
        now = {row["id"]: _kind_of(row) for row in rows}
        if file_id not in now:
            raise LookupError("That file isn't one of the title's.")
        shown = now[file_id]
        kept = {other for other, kind in now.items() if kind is not shown}
        kinds = {file_id: as_kind} | {
            other: kind if other in kept else as_kind for other, kind in now.items()
        }
        return self._place(conn, file_id, entry_id, kinds, episode, kept=kept)

    def _place(
        self,
        conn: sqlite3.Connection,
        file_id: int,
        entry_id: int,
        kinds: dict[int, Kind],
        episode: int | None,
        *,
        kept: Collection[int] = (),
    ) -> Placed:
        """Places the files (`kinds`, the owner's file first) in a show or film, pinned. An
        episode Maku can't place keeps waiting, or waits now; so does a file that keeps its own
        kind (`kept`, in a whole title's change) and doesn't fit."""
        entry = self._catalog.entry(entry_id)
        home = self._title_for(conn, entry, self._catalog.tmdb()) if entry else None
        if entry is None or home is None:
            raise LookupError("TMDB no longer has that show or film.")
        film = home.film or entry.kind is TitleKind.MOVIE or kinds[file_id] is Kind.MOVIE
        files = _facts(conn, list(kinds))
        through: set[int] = set() if film else _numbered_through(conn, files, home)
        chosen: list[tuple[FileFacts, Placement | None, Kind]] = []
        unfit: list[int] = []
        for facts in files:
            as_kind = kinds[facts.id]
            parsed = replace(facts.parsed, kind=as_kind)
            if facts.id == file_id and episode is not None:
                parsed = replace(parsed, episode=episode, episode_end=None)
                if as_kind is Kind.SPECIAL:
                    parsed = replace(parsed, season=0)
            elif facts.id in through:
                parsed = replace(parsed, folder_season=None)  # its number places it
            where = None if film else _placement(parsed, entry, home)
            if where is None and not film and (as_kind is Kind.EPISODE or facts.id in kept):
                if facts.id == file_id:
                    raise UnplacedError(_which_episode(entry, parsed.episode))
                unfit.append(facts.id)
                continue
            chosen.append((facts, where, as_kind))
        stamp = self._now().isoformat()
        with conn:
            for facts, where, as_kind in chosen:
                conn.execute(
                    """UPDATE files SET title_id = ?, entry_id = ?, season = ?, episode = ?,
                              episode_end = ?, matched = 'sure', confidence = 100,
                              pinned = 1, identified_at = ?
                       WHERE id = ?""",
                    (
                        home.title_id,
                        entry.id,
                        where.season if where else (0 if as_kind is Kind.SPECIAL else None),
                        where.episode if where else None,
                        where.last if where else None,
                        stamp,
                        facts.id,
                    ),
                )
            for unplaced in unfit:  # one placed before (in a title changed whole) waits now
                conn.execute(
                    """UPDATE files SET title_id = NULL, season = NULL, episode = NULL,
                              episode_end = NULL, matched = 'unsure', pinned = 0,
                              identified_at = ?
                       WHERE id = ? AND matched = 'sure'""",
                    (stamp, unplaced),
                )
        return Placed(len(chosen), len(unfit))

    def ignore(self, conn: sqlite3.Connection, file_id: int) -> None:
        """The owner says it's no series or film: Maku leaves it out, and no rescan asks
        again."""
        with conn:
            conn.execute(
                """UPDATE files SET title_id = NULL, season = NULL, episode = NULL,
                          episode_end = NULL, matched = 'ignored', pinned = 1, identified_at = ?
                   WHERE id = ?""",
                (self._now().isoformat(), file_id),
            )

    def unignore(self, conn: sqlite3.Connection, file_id: int) -> None:
        """The owner takes that back: the file waits for a match again, and the next scan looks
        it up afresh."""
        with conn:
            conn.execute(
                """UPDATE files SET matched = 'none', pinned = 0, identified_at = NULL
                   WHERE id = ? AND matched = 'ignored'""",
                (file_id,),
            )

    def search(self, conn: sqlite3.Connection, file_id: int, text: str) -> list[Guess]:
        """TMDB's shows and films for `text`, scored against one file, for the owner to pick
        from."""
        facts = _facts(conn, [file_id])
        if not facts or not text.strip():
            return []
        movie = facts[0].parsed.kind is Kind.MOVIE
        group = Group(text.strip(), facts[0].parsed.year, movie, tuple(facts))
        return guesses(group, self._catalog.search(text.strip(), films_first=movie))

    def _link_unlinked(self, conn: sqlite3.Connection) -> None:
        """The entries files are matched to that Maku has no links of, linked now so their
        franchises form: a film's collection. One in none is asked about again, from the kept
        answers while they last."""
        rows = conn.execute(
            """SELECT DISTINCT entry_id FROM files
               WHERE entry_id IS NOT NULL AND gone_at IS NULL
                 AND entry_id NOT IN (SELECT id FROM entries)"""
        ).fetchall()
        for row in rows:
            if entry := self._catalog.entry(row["entry_id"]):
                save_entry(conn, entry, self._now())

    def _settle(
        self,
        conn: sqlite3.Connection,
        group: Group,
        ranked: list[Guess],
        tmdb: Tmdb,
    ) -> tuple[int, int]:
        """Matches one group's files, or leaves them for the owner. Returns (sure, unsure)."""
        stamp = self._now().isoformat()
        best = ranked[0] if ranked else None
        sure = best is not None and best.confidence >= SURE and not group.disc
        home = self._title_for(conn, best.entry, tmdb) if best and sure else None
        if best is None or home is None:
            _mark_unsure(conn, group.files, ranked, stamp)
            return 0, len(group.files)

        entry = best.entry
        film = home.film or entry.kind is TitleKind.MOVIE  # a file is the whole title
        through: set[int] = set() if film else _numbered_through(conn, group.files, home)
        placements: dict[int, Placement | None] = {}
        for facts in group.files:
            parsed = facts.parsed
            if facts.id in through:
                parsed = replace(parsed, folder_season=None)  # its number places it
            placements[facts.id] = None if film else _placement(parsed, entry, home)
        clashing = _clashes(group.files, placements)
        own = (
            {} if film else self._by_own_names(conn, group, home, placements, clashing, entry, tmdb)
        )

        sure = unsure = 0
        with conn:
            for facts in group.files:
                where = placements[facts.id]
                if facts.id in own:
                    found, home_of, ranked_of, where = own[facts.id]
                    _place(conn, facts, home_of, found, where, ranked_of, stamp)
                    sure += 1
                    continue
                if facts.id in clashing or (where is None and not film):
                    _mark_unsure(conn, [facts], ranked, stamp, commit=False)
                    unsure += 1
                    continue
                _place(conn, facts, home, best, where, ranked, stamp)
                sure += 1
        return sure, unsure

    def _by_own_names(
        self,
        conn: sqlite3.Connection,
        group: Group,
        home: _Home,
        placements: dict[int, Placement | None],
        clashing: set[int],
        series: Entry,
        tmdb: Tmdb,
    ) -> dict[int, tuple[Guess, _Home, list[Guess], Placement | None]]:
        """The group's specials its show's list doesn't name the way the files do ("Special 05
        - The Night Train"), each looked up by its own name: the show or film TMDB knows it as,
        sure, and where that goes (its show's specials, by its names there, or a title of its
        own). A special that two files land on stays with neither."""
        found: dict[int, tuple[Guess, _Home, list[Guess], Placement | None]] = {}
        for facts in group.files:
            title = facts.parsed.episode_title
            if placements[facts.id] is not None or facts.id in clashing or not title:
                continue
            if facts.parsed.kind is not Kind.SPECIAL:
                continue
            try:
                lookup = self._own_name(conn, group, facts, title, series, tmdb)
            except WebError as error:
                log.warning("Couldn't look %s up by its own name: %s", title, error)
                continue
            if lookup is not None:
                found[facts.id] = lookup
        taken: dict[tuple[int, int, int], list[int]] = defaultdict(list)
        for file_id, where in placements.items():  # what the show's list placed already
            if where is not None:
                taken[(home.title_id, where.season, where.episode)].append(file_id)
        for file_id, (_, its_home, _, where) in found.items():
            if where is not None:
                taken[(its_home.title_id, where.season, where.episode)].append(file_id)
        crowded = {file_id for spot in taken.values() if len(spot) > 1 for file_id in spot}
        return {file_id: lookup for file_id, lookup in found.items() if file_id not in crowded}

    def _own_name(
        self,
        conn: sqlite3.Connection,
        group: Group,
        facts: FileFacts,
        title: str,
        series: Entry,
        tmdb: Tmdb,
    ) -> tuple[Guess, _Home, list[Guess], Placement | None] | None:
        """One special looked up by its own name, read as the series' ("The Harbour Line: The
        Night Train"). The release's count of its specials ("Special 05", or "03" in a specials
        folder) says nothing of TMDB's, so only a film, or a one-episode show, is placed: a title
        of its own, or its show's special by the names TMDB gives it."""
        parsed = replace(facts.parsed, episode=None, episode_end=None, folder_season=None)
        alone = replace(facts, parsed=parsed)
        named = Group(f"{group.query}: {title}", parsed.year, False, (alone,), group.query)
        ranked = self._look_up(named, series=False)
        best = ranked[0] if ranked else None
        if best is None or best.confidence < SURE or best.entry.id == series.id:
            return None
        if best.entry.kind is not TitleKind.MOVIE and best.entry.episodes != 1:
            return None  # which of its episodes the file is, its name doesn't say
        home = self._title_for(conn, best.entry, tmdb)
        if home is None:
            return None
        if home.film or best.entry.kind is TitleKind.MOVIE:
            return best, home, ranked, None
        where = _placement(parsed, best.entry, home)
        if where is None and home.show is not None:
            where = named_special(best.entry.titles, home.show)
        return (best, home, ranked, where) if where is not None else None

    def _title_for(self, conn: sqlite3.Connection, entry: Entry, tmdb: Tmdb) -> _Home | None:
        """The library's title for an entry, made or refreshed, with its TMDB show's episodes;
        None when TMDB no longer has it."""
        save_entry(conn, entry, self._now())
        media, number = tmdb_of(entry.id)
        return self._tmdb_title(conn, entry, media, number, tmdb)

    def _tmdb_title(
        self, conn: sqlite3.Connection, entry: Entry, media: Media, number: int, tmdb: Tmdb
    ) -> _Home | None:
        row = conn.execute(
            "SELECT * FROM titles WHERE tmdb_type = ? AND tmdb_id = ?", (media, number)
        ).fetchone()
        if media == "movie":
            film = tmdb.film(number)
            if film is None:
                return None
            return _Home(_save_film(conn, row, film, entry, self._now()), film=True)
        if row is not None and not due(row, self._now()):
            return _Home(row["id"], show_of(conn, row["id"]))
        found = tmdb.show(number)
        if found is None:
            return None
        return _Home(save_show(conn, found, TitleKind.SERIES, entry.id, self._now()), found)


def save_show(
    conn: sqlite3.Connection,
    show: Show,
    kind: TitleKind,
    entry_id: int | None,
    now: datetime,
) -> int:
    """Stores a TMDB show and its whole episode list. A title's kind is never narrowed: a show
    first found as a series stays one when its specials turn up."""
    with conn:
        row = conn.execute(
            f"""INSERT INTO titles (kind, name, year, released, tmdb_type, tmdb_id, entry_id,
                                    airing, poster, backdrop, checked_at, {_ABOUT})
                VALUES (?, ?, ?, ?, 'tv', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (tmdb_type, tmdb_id) DO UPDATE SET
                    name = excluded.name, year = excluded.year, released = excluded.released,
                    airing = excluded.airing, poster = excluded.poster,
                    backdrop = excluded.backdrop, checked_at = excluded.checked_at,
                    entry_id = COALESCE(titles.entry_id, excluded.entry_id),
                    kind = CASE WHEN titles.kind = 'series' THEN 'series' ELSE excluded.kind END,
                    {_ABOUT_UPDATED}
                RETURNING id""",  # noqa: S608 - only column names go in
            (
                kind.value,
                show.title,
                show.year,
                show.first_aired.isoformat() if show.first_aired else None,
                show.id,
                entry_id,
                int(show.airing),
                show.poster,
                show.backdrop,
                now.isoformat(),
                *_about(
                    show.overview,
                    show.genres,
                    show.studio,
                    show.status,
                    show.last_aired,
                    show.minutes,
                ),
            ),
        ).fetchone()
        title_id: int = row["id"]
        conn.execute("DELETE FROM episodes WHERE title_id = ?", (title_id,))
        conn.executemany(
            "INSERT INTO episodes (title_id, season, number, name, aired, minutes, overview, still)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    title_id,
                    e.season,
                    e.number,
                    e.title,
                    e.aired.isoformat() if e.aired else None,
                    e.minutes,
                    e.overview,
                    e.still,
                )
                for e in show.episodes
            ],
        )
    return title_id


# What a title's About panel shows, as kept on its row (migration 23).
_ABOUT = "overview, genres, studio, status, ended, minutes"
_ABOUT_UPDATED = ", ".join(f"{column} = excluded.{column}" for column in _ABOUT.split(", "))


def _about(
    overview: str | None,
    genres: tuple[str, ...],
    studio: str | None,
    status: str | None,
    ended: date | None,
    minutes: int | None,
) -> tuple[str | None, str | None, str | None, str | None, str | None, int | None]:
    """A title's About columns, as stored."""
    return (
        overview,
        json.dumps(list(genres), ensure_ascii=False) if genres else None,
        studio,
        status,
        ended.isoformat() if ended else None,
        minutes,
    )


def _save_film(
    conn: sqlite3.Connection,
    row: sqlite3.Row | None,
    film: Film,
    entry: Entry,
    now: datetime,
) -> int:
    return save_film(conn, film, entry.id if row is None else row["entry_id"], now)


def save_film(conn: sqlite3.Connection, film: Film, entry_id: int | None, now: datetime) -> int:
    """Stores a TMDB film, as identifying finds it or a weekly look again brings it up to date."""
    with conn:
        saved = conn.execute(
            f"""INSERT INTO titles (kind, name, year, released, tmdb_type, tmdb_id, entry_id,
                                    poster, backdrop, checked_at, {_ABOUT})
                VALUES ('movie', ?, ?, ?, 'movie', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (tmdb_type, tmdb_id) DO UPDATE SET
                    name = excluded.name, year = excluded.year, released = excluded.released,
                    poster = excluded.poster, backdrop = excluded.backdrop,
                    checked_at = excluded.checked_at,
                    entry_id = COALESCE(titles.entry_id, excluded.entry_id),
                    {_ABOUT_UPDATED}
                RETURNING id""",  # noqa: S608 - only column names go in
            (
                film.title,
                film.year,
                film.released.isoformat() if film.released else None,
                film.id,
                entry_id,
                film.poster,
                film.backdrop,
                now.isoformat(),
                *_about(film.overview, film.genres, film.studio, film.status, None, film.minutes),
            ),
        ).fetchone()
    title_id: int = saved["id"]
    return title_id


def save_entry(conn: sqlite3.Connection, entry: Entry, now: datetime) -> None:
    """Keeps what TMDB says of an entry (its names, for search; the rest for a franchise's page)
    and how it relates to others, the films of its collection: what ties a franchise together
    (maku/core/franchise.py)."""
    with conn:
        write_entry(conn, entry.id, entry, now)


def write_entry(conn: sqlite3.Connection, number: int, entry: Entry | None, now: datetime) -> None:
    """`save_entry`, within the caller's transaction. None keeps that TMDB no longer has entry
    `number`; the links it had stay, as they still tie the library's titles."""
    conn.execute(
        """INSERT OR REPLACE INTO entries
           (id, name, names, kind, status, started, episodes, cover, checked_at,
            description, genres, studio, ended, minutes, collection)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            number,
            entry.title if entry else None,
            json.dumps(entry.titles, ensure_ascii=False) if entry else None,
            entry.kind.value if entry and entry.kind else None,
            entry.status if entry else None,
            entry.start.isoformat() if entry and entry.start else None,
            entry.episodes if entry else None,
            entry.cover if entry else None,
            now.isoformat(),
            entry.description if entry else None,
            json.dumps(list(entry.genres), ensure_ascii=False) if entry and entry.genres else None,
            entry.studio if entry else None,
            entry.end.isoformat() if entry and entry.end else None,
            entry.minutes if entry else None,
            entry.collection if entry else None,
        ),
    )
    if entry is None:
        return
    conn.execute("DELETE FROM entry_links WHERE entry_id = ?", (entry.id,))
    conn.executemany(
        """INSERT OR IGNORE INTO entry_links (entry_id, related_id, relation)
           VALUES (?, ?, ?)""",
        [(entry.id, related.id, related.relation) for related in entry.related],
    )


def _kind_of(row: sqlite3.Row) -> Kind:
    """What a placed file is now, from its record and its title's (`season` and `kind`): a film,
    a special (season 0), or an episode."""
    if row["kind"] == "movie" or row["season"] is None:
        return Kind.MOVIE
    return Kind.SPECIAL if row["season"] == 0 else Kind.EPISODE


def _placement(parsed: ParsedName, entry: Entry, home: _Home) -> Placement | None:
    """Where a file of `entry` sits in its title, or None when Maku can't tell surely."""
    if parsed.kind is Kind.EPISODE and parsed.episode is None and entry.episodes == 1:
        parsed = replace(parsed, episode=1)  # a one-off: its only episode
    if home.show is not None:
        return place(parsed, home.show, entry)
    return None


def _numbered_through(
    conn: sqlite3.Connection, files: Sequence[FileFacts], home: _Home
) -> set[int]:
    """The files in a season's folder that count straight through their show (see
    numbered_through), told by every video of the show in their release's season folders: those
    placed before too, so a file identified on its own goes as they did."""
    if home.show is None:
        return set()
    ids = {facts.id for facts in files}
    releases = {  # the folders above a season's whose files go without it: "S01E05" says all
        facts.path.parent.parent
        for facts in files
        if facts.parsed.folder_season and facts.parsed.season is None
    }
    beside: list[FileFacts] = []
    for release in releases:
        beside += [facts for facts in _placed_in(conn, release, home) if facts.id not in ids]
    return numbered_through([*files, *beside], home.show) & ids


def _placed_in(conn: sqlite3.Connection, release: PurePath, home: _Home) -> list[FileFacts]:
    """The title's videos in the folders of a release's folder ("[Group] Show (S01-S07)\\Show
    Season 02"), by their names. Only the title's: other shows' share a library's folder."""
    inside = str(release).rstrip("\\/") + "\\"
    rows = conn.execute(
        """SELECT id, path FROM files
           WHERE gone_at IS NULL AND title_id = ? AND lower(substr(path, 1, ?)) = lower(?)""",
        (home.title_id, len(inside), inside),
    ).fetchall()
    paths = [(row["id"], PureWindowsPath(row["path"])) for row in rows]
    return [
        FileFacts(file_id, path, parse_name(path), None)
        for file_id, path in paths
        if str(path.parent.parent).casefold() == str(release).casefold()
    ]


def _which_episode(entry: Entry, number: int | None) -> str:
    if number is None:
        return "Which episode is it? Maku can't tell from its name."
    return f"Which episode is it? {entry.title} has no episode {number}."


def due(row: sqlite3.Row, now: datetime) -> bool:
    """Whether a show's episode list is old enough to ask TMDB again."""
    checked = row["checked_at"]
    if checked is None:
        return True
    every = AIRING_EVERY if row["airing"] else FINISHED_EVERY
    return now - datetime.fromisoformat(checked) >= every


def _clashes(files: Sequence[FileFacts], placements: dict[int, Placement | None]) -> set[int]:
    """Files placed on the same episode though their own numbers differ: one of them is placed
    wrongly, so neither is trusted. Copies of one episode carry the same numbers, and stay."""
    by_spot: dict[tuple[int, int], list[FileFacts]] = defaultdict(list)
    for facts in files:
        where = placements.get(facts.id)
        if where is not None:
            by_spot[(where.season, where.episode)].append(facts)
    clashing: set[int] = set()
    for together in by_spot.values():
        numbers = {(_season(f.parsed), f.parsed.episode, f.parsed.part) for f in together}
        if len(numbers) > 1:
            clashing.update(f.id for f in together)
    return clashing


def _season(parsed: ParsedName) -> int | None:
    """A file's season, from its name or else its folder ("Season 01/05.mkv")."""
    return parsed.season if parsed.season is not None else parsed.folder_season


def _facts(conn: sqlite3.Connection, file_ids: Sequence[int]) -> list[FileFacts]:
    """What Maku knows about these files, whatever their state."""
    marks = ",".join("?" * len(file_ids))
    rows = conn.execute(
        f"SELECT id, path, duration FROM files WHERE id IN ({marks}) AND gone_at IS NULL",  # noqa: S608 - only question marks
        tuple(file_ids),
    ).fetchall()
    return [
        FileFacts(
            row["id"],
            PureWindowsPath(row["path"]),
            parse_name(PureWindowsPath(row["path"])),
            row["duration"] / 60 if row["duration"] else None,
        )
        for row in rows
    ]


def _to_identify(conn: sqlite3.Connection) -> tuple[list[FileFacts], list[tuple[int, Kind]]]:
    """Files read and not yet identified (the owner's own choices excepted): the ones to look up,
    and the extras and the files with no name to look up that can't be."""
    rows = conn.execute(
        """SELECT id, path, duration FROM files
           WHERE gone_at IS NULL AND probed_at IS NOT NULL AND identified_at IS NULL
             AND pinned = 0
           ORDER BY path"""
    ).fetchall()
    files: list[FileFacts] = []
    others: list[tuple[int, Kind]] = []
    for row in rows:
        path = PureWindowsPath(row["path"])
        parsed = parse_name(path)
        if parsed.kind is Kind.EXTRA or not parsed.best_title:
            others.append((row["id"], parsed.kind))
            continue
        minutes = row["duration"] / 60 if row["duration"] else None
        files.append(FileFacts(row["id"], path, parsed, minutes))
    return files, others


def _mark_unlookable(
    conn: sqlite3.Connection, others: Iterable[tuple[int, Kind]], stamp: str
) -> None:
    with conn:
        conn.executemany(
            "UPDATE files SET matched = ?, identified_at = ? WHERE id = ?",
            [
                ("extra" if kind is Kind.EXTRA else "none", stamp, file_id)
                for file_id, kind in others
            ],
        )


def _place(
    conn: sqlite3.Connection,
    facts: FileFacts,
    home: _Home,
    best: Guess,
    where: Placement | None,
    ranked: list[Guess],
    stamp: str,
) -> None:
    """A file matched surely: its title, entry and place there (none for a film). Part of the
    caller's transaction."""
    conn.execute(
        """UPDATE files SET title_id = ?, entry_id = ?, season = ?, episode = ?,
                  episode_end = ?, matched = 'sure', confidence = ?, guesses = ?,
                  identified_at = ?
           WHERE id = ? AND pinned = 0""",
        (
            home.title_id,
            best.entry.id,
            where.season if where else None,
            where.episode if where else None,
            where.last if where else None,
            best.confidence,
            _guesses_json(ranked),
            stamp,
            facts.id,
        ),
    )


def _mark_unsure(
    conn: sqlite3.Connection,
    files: Iterable[FileFacts],
    ranked: list[Guess],
    stamp: str,
    *,
    commit: bool = True,
) -> None:
    state = "unsure" if ranked else "none"
    rows = [
        (state, ranked[0].confidence if ranked else None, _guesses_json(ranked), stamp, f.id)
        for f in files
    ]
    sql = """UPDATE files SET title_id = NULL, season = NULL, episode = NULL, episode_end = NULL,
                    matched = ?, confidence = ?, guesses = ?, identified_at = ?
             WHERE id = ? AND pinned = 0"""
    if commit:
        with conn:
            conn.executemany(sql, rows)
    else:
        conn.executemany(sql, rows)


def _guesses_json(ranked: list[Guess]) -> str:
    return json.dumps(
        [
            {
                "entryId": guess.entry.id,
                "title": guess.entry.title,
                "kind": guess.entry.kind.value if guess.entry.kind else None,
                "year": guess.entry.year,
                "episodes": guess.entry.episodes,
                "minutes": guess.entry.minutes,
                "cover": guess.entry.cover,
                "confidence": guess.confidence,
                "reasons": list(guess.reasons),
            }
            for guess in ranked[:_SHOWN_GUESSES]
        ]
    )


def _series_last(ranked: list[Guess]) -> int:
    """Sort key: series first (0), everything else after (1)."""
    best = ranked[0].entry.kind if ranked else None
    return 0 if best is TitleKind.SERIES else 1


def _waiting(service: str, error: WebError) -> str:
    return f"Titles wait for the next scan: {service} couldn't be asked ({error})"
