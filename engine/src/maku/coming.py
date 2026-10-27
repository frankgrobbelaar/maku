"""What's still to come of the library's shows: each one's next episode by the day it airs, for
Home's "Coming up", from the episode lists Maku keeps (refreshed hourly while a show airs). On the
day one airs, the owner is told once, unless the library has it already."""

import sqlite3
from dataclasses import dataclass
from datetime import date

from maku.core.catalog import TitleKind

SHOWN = 20  # titles listed at most


@dataclass(frozen=True)
class Coming:
    """A title's next episode, and how many more its list has after it."""

    title_id: int
    title: str
    kind: TitleKind
    poster: str | None
    season: int
    number: int
    name: str | None
    aired: date
    later: int


def coming(conn: sqlite3.Connection, today: date, limit: int = SHOWN) -> list[Coming]:
    """Each of the library's titles with an episode airing today or later that the library
    hasn't got: its next one, the soonest first."""
    titles: dict[int, list[sqlite3.Row]] = {}
    for row in _ahead(conn, today):
        titles.setdefault(row["title_id"], []).append(row)
    found = [_coming(first, len(rest)) for first, *rest in titles.values()]
    return sorted(found, key=lambda each: (each.aired, each.title))[:limit]


def out_today(conn: sqlite3.Connection, today: date, now: str) -> list[Coming]:
    """The episodes airing today that the library hasn't got, and the owner wasn't told of yet:
    told now, so each is told once."""
    rows = [
        row
        for row in _ahead(conn, today)
        if row["aired"] == today.isoformat() and row["told"] is None
    ]
    with conn:
        conn.executemany(
            """INSERT OR IGNORE INTO aired_told (title_id, season, number, told_at)
               VALUES (?, ?, ?, ?)""",
            [(row["title_id"], row["season"], row["number"], now) for row in rows],
        )
    return [_coming(row, 0) for row in rows]


def _ahead(conn: sqlite3.Connection, today: date) -> list[sqlite3.Row]:
    """The episodes airing from today on of titles the library holds a video of, that no video
    of the library's covers, in order."""
    return conn.execute(
        """SELECT e.title_id, e.season, e.number, e.name, e.aired, t.name AS title, t.kind,
                  COALESCE(t.poster_choice, t.poster) AS poster, a.told_at AS told
           FROM episodes AS e JOIN titles AS t ON t.id = e.title_id
           LEFT JOIN aired_told AS a
             ON a.title_id = e.title_id AND a.season = e.season AND a.number = e.number
           WHERE e.aired >= ?
             AND EXISTS (SELECT 1 FROM files AS f WHERE f.title_id = t.id AND f.gone_at IS NULL)
             AND NOT EXISTS (
                 SELECT 1 FROM files AS f
                 WHERE f.title_id = e.title_id AND f.season = e.season AND f.gone_at IS NULL
                   AND e.number BETWEEN f.episode AND COALESCE(f.episode_end, f.episode))
           ORDER BY e.aired, e.season = 0, e.season, e.number""",
        (today.isoformat(),),
    ).fetchall()


def _coming(row: sqlite3.Row, later: int) -> Coming:
    return Coming(
        title_id=row["title_id"],
        title=row["title"],
        kind=TitleKind(row["kind"]),
        poster=row["poster"],
        season=row["season"],
        number=row["number"],
        name=row["name"],
        aired=date.fromisoformat(row["aired"]),
        later=later,
    )


def told(found: list[Coming]) -> tuple[str, str, str] | None:
    """The notification for episodes out today: its title, its line, and where it leads (the
    title's page for one, Home's "Coming up" for more)."""
    if not found:
        return None
    names = [f"{each.title} {_code(each)}" for each in found]
    if len(found) == 1:
        [only] = found
        line = f"{names[0]} · {only.name}" if only.name else names[0]
        return "Out today", line, f"/titles/{only.title_id}"
    if len(found) == 2:
        line = f"{names[0]} and {names[1]}"
    else:
        line = f"{names[0]}, {names[1]} and {len(names) - 2} more"
    return f"{len(found)} episodes out today", line, "/"


def _code(each: Coming) -> str:
    return f"S{each.season:02d}E{each.number:02d}"
