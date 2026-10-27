"""What the owner has watched, and where each video stopped (maku/core/watched.py says how): the
player says where it is as it plays, and Home's "Continue watching" picks up from there, with
the video stopped part way, or the one after the last seen."""

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from maku.core.catalog import TitleKind
from maku.core.watched import Video, following, furthest, resume_at, seen, up_next

FOLLOWING = 30  # videos after the one to continue with, for the player's next


@dataclass(frozen=True)
class Watch:
    """How far one video has been watched."""

    watched: bool
    resume: float | None  # where Play picks it up, in seconds; None for from the top


@dataclass(frozen=True)
class Next:
    """A video to play from "Continue watching", and what plays after it."""

    file_id: int
    season: int | None
    episode: int | None
    episode_end: int | None
    name: str | None  # its episode's, as TMDB names it
    path: str
    duration: float | None
    resume: float | None


@dataclass(frozen=True)
class Continuing:
    """A title to go on with: the video stopped part way, or the one after the last seen."""

    title_id: int
    title: str
    kind: TitleKind
    poster: str | None
    played_at: str
    up_next: bool  # the one after the last seen, rather than one stopped part way
    video: Next
    following: list[Next]


def note(
    conn: sqlite3.Connection, file_id: int, position: float, duration: float | None, now: str
) -> None:
    """Where a video is, as the player says while it plays and as it stops. Seen to its last
    tenth, it's watched, and stays so when played again."""
    with conn:
        conn.execute(
            """INSERT INTO watched (file_id, position, duration, played_at, watched_at)
               SELECT id, ?, ?, ?, ? FROM files WHERE id = ?
               ON CONFLICT (file_id) DO UPDATE SET position = excluded.position,
                   duration = COALESCE(excluded.duration, watched.duration),
                   played_at = excluded.played_at,
                   watched_at = COALESCE(excluded.watched_at, watched.watched_at)""",
            (position, duration, now, now if seen(position, duration) else None, file_id),
        )


def mark(conn: sqlite3.Connection, file_ids: Iterable[int], watched: bool, now: str) -> None:
    """Videos marked watched, or not: either way each starts from the top next time. Marked
    watched, they're where the owner is, so "Continue watching" goes on after them."""
    ids = [(file_id,) for file_id in file_ids]
    with conn:
        if watched:
            conn.executemany(
                """INSERT INTO watched (file_id, position, duration, played_at, watched_at)
                   SELECT id, 0, duration, :now, :now FROM files WHERE id = :id
                   ON CONFLICT (file_id) DO UPDATE SET position = 0, played_at = :now,
                       watched_at = :now""",
                [{"id": file_id, "now": now} for (file_id,) in ids],
            )
        else:
            conn.executemany(
                "UPDATE watched SET position = 0, watched_at = NULL WHERE file_id = ?", ids
            )


def forget(conn: sqlite3.Connection, title_id: int) -> None:
    """A title out of "Continue watching" till one of its videos plays again. Where each video
    stopped, and which were watched, stay."""
    with conn:
        conn.execute(
            """UPDATE watched SET played_at = NULL
               WHERE file_id IN (SELECT id FROM files WHERE title_id = ?)""",
            (title_id,),
        )


def of_title(conn: sqlite3.Connection, title_id: int) -> dict[int, Watch]:
    """How far each of a title's videos has been watched, by its file's id."""
    rows = conn.execute(
        """SELECT w.file_id, w.position, COALESCE(w.duration, f.duration) AS duration,
                  w.watched_at
           FROM watched AS w JOIN files AS f ON f.id = w.file_id
           WHERE f.title_id = ? AND f.gone_at IS NULL""",
        (title_id,),
    )
    return {
        row["file_id"]: Watch(
            watched=row["watched_at"] is not None,
            resume=resume_at(row["position"], row["duration"]),
        )
        for row in rows
    }


def continuing(conn: sqlite3.Connection, limit: int = 12) -> list[Continuing]:
    """The titles to go on with, the latest played first: each title's latest video if it
    stopped part way, else the one after it not watched yet, once it was seen. A video only
    looked at, a moment from its start, leaves its title's place as it was; a title all seen
    isn't listed."""
    rows = conn.execute(
        """SELECT f.title_id, w.position, COALESCE(w.duration, f.duration) AS duration,
                  w.played_at, w.watched_at
           FROM watched AS w JOIN files AS f ON f.id = w.file_id
           WHERE w.played_at IS NOT NULL AND f.gone_at IS NULL AND f.problem IS NULL
             AND f.title_id IS NOT NULL""",
    ).fetchall()
    latest: dict[int, str] = {}
    for row in rows:
        if _counts(row) and row["played_at"] > latest.get(row["title_id"], ""):
            latest[row["title_id"]] = row["played_at"]
    found: list[Continuing] = []
    for title_id, played_at in sorted(latest.items(), key=lambda item: item[1], reverse=True):
        if len(found) == limit:
            break
        going = _continuing(conn, title_id, played_at)
        if going:
            found.append(going)
    return found


def _continuing(conn: sqlite3.Connection, title_id: int, played_at: str) -> Continuing | None:
    title = conn.execute(
        "SELECT name, kind, COALESCE(poster_choice, poster) AS poster FROM titles WHERE id = ?",
        (title_id,),
    ).fetchone()
    rows = conn.execute(
        """SELECT f.id, f.season, f.episode, f.episode_end, f.path,
                  COALESCE(w.duration, f.duration) AS duration, w.position, w.played_at,
                  w.watched_at, e.name
           FROM files AS f LEFT JOIN watched AS w ON w.file_id = f.id
           LEFT JOIN episodes AS e
             ON e.title_id = f.title_id AND e.season = f.season AND e.number = f.episode
           WHERE f.title_id = ? AND f.gone_at IS NULL AND f.problem IS NULL""",
        (title_id,),
    ).fetchall()
    by_id = {row["id"]: row for row in rows}
    # Two copies of an episode are one step: the one played last stands for both, watched once
    # either is.
    kept, watched = _one_copy(rows)
    videos = [Video(row["id"], row["season"], row["episode"], row["path"]) for row in kept]
    last = [
        video
        for video in videos
        if by_id[video.id]["played_at"] == played_at and _counts(by_id[video.id])
    ]
    if title is None or not last:
        return None
    latest = furthest(last)
    if resume_at(by_id[latest.id]["position"], by_id[latest.id]["duration"]) is not None:
        chosen, up = latest, False
    else:
        after = up_next(videos, latest, watched)
        if after is None:
            return None
        chosen, up = after, True
    return Continuing(
        title_id=title_id,
        title=title["name"],
        kind=TitleKind(title["kind"]),
        poster=title["poster"],
        played_at=played_at,
        up_next=up,
        video=_next(by_id[chosen.id]),
        following=[_next(by_id[each.id]) for each in following(videos, chosen)[:FOLLOWING]],
    )


def _one_copy(rows: list[sqlite3.Row]) -> tuple[list[sqlite3.Row], set[int]]:
    """A title's videos with one copy of each episode (the one last watched or stopped part way,
    else the one last looked at, else the first found), and which of those count as watched: an
    episode is, once any copy of it is."""
    copies: dict[tuple[int, int], list[sqlite3.Row]] = {}
    kept: list[sqlite3.Row] = []
    for row in rows:
        if row["season"] is None or row["episode"] is None:
            kept.append(row)
        else:
            copies.setdefault((row["season"], row["episode"]), []).append(row)
    watched = {row["id"] for row in kept if _watched(row)}
    for same in copies.values():
        best = max(same, key=lambda row: (_counts(row), row["played_at"] or "", -row["id"]))
        kept.append(best)
        if any(_watched(row) for row in same):
            watched.add(best["id"])
    return kept, watched


def _counts(row: sqlite3.Row) -> bool:
    """Watched, or stopped part way: more than a look a moment from its start."""
    return _watched(row) or resume_at(row["position"] or 0.0, row["duration"]) is not None


def _watched(row: sqlite3.Row) -> bool:
    return row["watched_at"] is not None or seen(row["position"] or 0.0, row["duration"])


def _next(row: sqlite3.Row) -> Next:
    return Next(
        file_id=row["id"],
        season=row["season"],
        episode=row["episode"],
        episode_end=row["episode_end"],
        name=row["name"],
        path=row["path"],
        duration=row["duration"],
        resume=resume_at(row["position"] or 0.0, row["duration"]),
    )
