"""The rest of each franchise: every film TMDB keeps in one collection with the library's films,
the library's or not (maku/core/franchise.py), so a franchise's page can show what the library is
missing of it. A series stands alone: TMDB ties no show to another.

Maku asks TMDB about them a few at a time while it's open, at the watcher's look-arounds
(maku/watch.py): the entries it hasn't asked about yet first, a few of each franchise in turn,
nearest the library's first, then each again weekly, or daily while it airs or is still to come,
so a new film of a collection turns up by itself.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from maku import titles
from maku.catalog import Catalog
from maku.core.catalog import Entry, TitleKind
from maku.core.franchise import (
    Kept,
    Member,
    franchises,
    missing,
    nearest,
    own_links,
    story_neighbours,
    taking_turns,
)
from maku.identify import write_entry
from maku.web import WebError

EACH_LOOK = 6  # entries asked about at each look-around: about 24 a minute, well within TMDB's
AIRING_EVERY = timedelta(days=1)  # an entry airing or still to come, or one TMDB didn't give
FINISHED_EVERY = timedelta(days=7)
_CHANGING = ("airing", "coming", "paused")


@dataclass(frozen=True)
class Rest:
    """What TMDB ties to a franchise that the library has no part of."""

    titles: list[Member]  # oldest first
    looking: bool  # some of the franchise is still to be looked up


def look_up(
    conn: sqlite3.Connection, catalog: Catalog, now: datetime, count: int = EACH_LOOK
) -> int:
    """Asks TMDB about the next few entries of the library's franchises, and keeps what it says.
    Returns how many it asked about. Offline or refused, it raises WebError and the rest wait;
    an entry TMDB won't answer about waits a day while the others go on. Without a key there's
    no one to ask."""
    if not catalog.ready:
        return 0
    asked = 0
    for number in next_to_ask(conn, now, count):
        try:
            entry = catalog.entry(number, fresh=True)
        except WebError as error:
            if error.status is None or error.status in (401, 429):
                raise
            _put_off(conn, number, now)
        else:
            save(conn, number, entry, now)
        asked += 1
    return asked


def next_to_ask(conn: sqlite3.Connection, now: datetime, count: int) -> list[int]:
    """The entries of the library's franchises to ask TMDB about next. First the ones not asked
    about yet that the library lacks, what a franchise's page shows: franchises take turns, the
    ones least looked up first, each nearest the library's first. Then the library's own, whose
    links Maku has from identifying them; then the ones due again, longest waiting first."""
    known = {
        row["id"]: row for row in conn.execute("SELECT id, name, status, checked_at FROM entries")
    }
    links = titles.links(conn)
    neighbours = story_neighbours(links)
    held = titles.entries(conn)
    everywhere = set[int]().union(*held.values())
    lacking: list[list[int]] = []
    looked_up: list[int] = []
    owned: list[int] = []
    due: list[tuple[str, int]] = []
    for group in franchises(held, own_links(links, everywhere)):
        own = set[int]().union(*(held[title_id] for title_id in group))
        waiting: list[int] = []
        reach = nearest(own, neighbours, others=everywhere - own)
        for number in reach:
            row = known.get(number)
            if row is None:
                (owned if number in own else waiting).append(number)
            elif _due(row, now):
                due.append((row["checked_at"], number))
        lacking.append(waiting)
        looked_up.append(sum(1 for number in reach if number in known))
    order = [*taking_turns(lacking, looked_up), *owned, *(number for _, number in sorted(due))]
    return list(dict.fromkeys(order))[:count]


def save(conn: sqlite3.Connection, number: int, entry: Entry | None, now: datetime) -> None:
    """Keeps what TMDB says of an entry and how it ties to others, or that TMDB no longer has it
    (None). An entry gone keeps the links it had: they still tie the library's titles."""
    if entry is not None and entry.id != number:
        entry = None  # TMDB answered about another: as good as gone
    with conn:
        write_entry(conn, number, entry, now)


def rest(conn: sqlite3.Connection, franchise: titles.Franchise) -> Rest:
    """What TMDB ties to the franchise that the library has no part of, as far as Maku has looked
    it up."""
    links = titles.links(conn)
    held = titles.entries(conn)
    everywhere = set[int]().union(*held.values())
    own = set[int]().union(*(held.get(title.id, set()) for title in franchise.titles))
    reach = nearest(own, story_neighbours(links), others=everywhere - own)
    marks = ", ".join("?" * len(reach))
    rows = {
        row["id"]: row
        for row in conn.execute(
            f"SELECT * FROM entries WHERE id IN ({marks})",  # noqa: S608 - only placeholders go in
            reach,
        )
    }
    kept = [
        Kept(frozenset(held.get(title.id, set())), show, _videos_in(conn, title.id))
        for title in franchise.titles
        if (show := titles.show_of(conn, title.id)) is not None
    ]
    known = [entry for number in reach if number in rows if (entry := _entry(rows[number]))]
    return Rest(
        missing(known, _matched(conn), kept, links),
        # The library's own are asked about last, and add nothing to what it lacks till then.
        looking=any(number not in rows and number not in own for number in reach),
    )


def _put_off(conn: sqlite3.Connection, number: int, now: datetime) -> None:
    """TMDB wouldn't answer about an entry: what Maku knew of it stays, and it's asked about
    again when due (tomorrow, for one Maku never had an answer about)."""
    with conn:
        conn.execute(
            """INSERT INTO entries (id, checked_at) VALUES (?, ?)
               ON CONFLICT (id) DO UPDATE SET checked_at = excluded.checked_at""",
            (number, now.isoformat()),
        )


def _due(row: sqlite3.Row, now: datetime) -> bool:
    changing = row["status"] in _CHANGING or row["name"] is None
    every = AIRING_EVERY if changing else FINISHED_EVERY
    return now - datetime.fromisoformat(row["checked_at"]) >= every


def _matched(conn: sqlite3.Connection) -> set[int]:
    """The entries the library's videos are matched to."""
    return {
        row["entry_id"]
        for row in conn.execute(
            """SELECT DISTINCT entry_id FROM files
               WHERE gone_at IS NULL AND title_id IS NOT NULL AND entry_id IS NOT NULL"""
        )
    }


def _entry(row: sqlite3.Row) -> Member | None:
    """An entry as Maku kept it, or None while TMDB gives nothing for it."""
    if row["name"] is None:
        return None
    return Member(
        id=row["id"],
        name=row["name"],
        names=tuple(json.loads(row["names"] or "[]")),
        kind=TitleKind(row["kind"]) if row["kind"] in iter(TitleKind) else None,
        status=row["status"],
        start=date.fromisoformat(row["started"]) if row["started"] else None,
        episodes=row["episodes"],
        cover=row["cover"],
        description=row["description"],
        genres=tuple(json.loads(row["genres"] or "[]")),
        studio=row["studio"],
    )


def _videos_in(conn: sqlite3.Connection, title_id: int) -> frozenset[tuple[int, int]]:
    """Each episode of a title the library holds a video of, as (season, episode)."""
    return frozenset(
        (season, number)
        for season, first, last in titles.held(conn, title_id)
        for number in range(first, (last or first) + 1)
    )
