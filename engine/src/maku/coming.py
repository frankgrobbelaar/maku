"""The library's shows by the day their episodes air, for the Library's "Coming up": the last four
weeks and all that's listed ahead, from the episode lists Maku keeps (refreshed hourly while a show
airs), each day's saying how much of it the library has. On the day one airs, the owner is told
once, unless the library has it already."""

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

from maku.core.catalog import TitleKind

BACK = timedelta(weeks=4)  # how far back what aired goes
AHEAD = 100  # what's listed from today on, kept to the soonest (with each show's next)


@dataclass(frozen=True)
class Coming:
    """A show's episodes of one season out on one day (one, or a season put out at once), and how
    many of them the library has."""

    title_id: int
    title: str
    kind: TitleKind
    poster: str | None
    season: int
    number: int  # the first of them
    last: int  # the last of them: the first, for one
    name: str | None  # the episode's own, for one
    aired: date
    episodes: int
    held: int  # of them, in the library


def coming(conn: sqlite3.Connection, today: date) -> list[Coming]:
    """The episodes of the library's shows out in the last four weeks or listed from today on, by
    the day they air: a show's of one season out one after another on a day together."""
    found = [_together(run) for run in _runs(_episodes(conn, today - BACK))]
    aired = [each for each in found if each.aired < today]
    return aired + _soonest([each for each in found if each.aired >= today])


def out_today(conn: sqlite3.Connection, today: date, now: str) -> list[Coming]:
    """The episodes airing today that the library hasn't got, and the owner wasn't told of yet:
    told now, so each is told once."""
    rows = [row for row in _episodes(conn, today, today) if not row["held"] and row["told"] is None]
    with conn:
        conn.executemany(
            """INSERT OR IGNORE INTO aired_told (title_id, season, number, told_at)
               VALUES (?, ?, ?, ?)""",
            [(row["title_id"], row["season"], row["number"], now) for row in rows],
        )
    return [_together([row]) for row in rows]


def _soonest(ahead: list[Coming]) -> list[Coming]:
    """What's listed from today on, kept to the soonest (the last day of them whole), and each
    show's next however far off, so no show's is crowded out."""
    kept = set(range(min(AHEAD, len(ahead))))
    if kept:
        last = ahead[max(kept)].aired
        kept.update(at for at, each in enumerate(ahead) if each.aired == last)
    shows: set[int] = set()
    for at, each in enumerate(ahead):
        if each.title_id not in shows:
            shows.add(each.title_id)
            kept.add(at)
    return [each for at, each in enumerate(ahead) if at in kept]


def _runs(rows: list[sqlite3.Row]) -> Iterator[list[sqlite3.Row]]:
    """The episodes in runs: a show's of one season out one after another on one day."""
    run: list[sqlite3.Row] = []
    for row in rows:
        if run and not (
            row["aired"] == run[-1]["aired"]
            and row["title_id"] == run[-1]["title_id"]
            and row["season"] == run[-1]["season"]
            and row["number"] == run[-1]["number"] + 1
        ):
            yield run
            run = []
        run.append(row)
    if run:
        yield run


def _episodes(
    conn: sqlite3.Connection, since: date, until: date | None = None
) -> list[sqlite3.Row]:
    """The episodes airing from `since` on (to `until`, when given) of titles the library holds a
    video of, by day, show, season and number, each saying whether a video of the library's
    holds it."""
    last = until.isoformat() if until else None
    return conn.execute(
        """SELECT e.title_id, e.season, e.number, e.name, e.aired, t.name AS title, t.kind,
                  COALESCE(t.poster_choice, t.poster) AS poster, a.told_at AS told,
                  EXISTS (
                      SELECT 1 FROM files AS f
                      WHERE f.title_id = e.title_id AND f.season = e.season AND f.gone_at IS NULL
                        AND e.number BETWEEN f.episode AND COALESCE(f.episode_end, f.episode)
                  ) AS held
           FROM episodes AS e JOIN titles AS t ON t.id = e.title_id
           LEFT JOIN aired_told AS a
             ON a.title_id = e.title_id AND a.season = e.season AND a.number = e.number
           WHERE e.aired >= ? AND (? IS NULL OR e.aired <= ?)
             AND EXISTS (SELECT 1 FROM files AS f WHERE f.title_id = t.id AND f.gone_at IS NULL)
           ORDER BY e.aired, t.name, e.title_id, e.season = 0, e.season, e.number""",
        (since.isoformat(), last, last),
    ).fetchall()


def _together(rows: list[sqlite3.Row]) -> Coming:
    """A show's episodes of one season on one day, in order, as one."""
    first, last = rows[0], rows[-1]
    return Coming(
        title_id=first["title_id"],
        title=first["title"],
        kind=TitleKind(first["kind"]),
        poster=first["poster"],
        season=first["season"],
        number=first["number"],
        last=last["number"],
        name=first["name"] if len(rows) == 1 else None,
        aired=date.fromisoformat(first["aired"]),
        episodes=len(rows),
        held=sum(1 for row in rows if row["held"]),
    )


def told(found: list[Coming]) -> tuple[str, str, str] | None:
    """The notification for episodes out today: its title, its line, and where it leads (the
    title's page for one, the Library's "Coming up" for more)."""
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
    return f"{len(found)} episodes out today", line, "/library"


def _code(each: Coming) -> str:
    return f"S{each.season:02d}E{each.number:02d}"
