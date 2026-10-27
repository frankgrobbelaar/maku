"""What Maku did, newest first, for the History screen: each tidy-up applied (and whether it was
undone), each file converted (and whether its original is back), each batch of English subtitles
made (and whether they're still there), and each scan. History comes a few days at a time, and
the owner can clear it, all or what's older than a day, a week or a month, by hand or every day
(Settings > Your data). A search finds the tidy-ups, conversions and batches of subtitles that
name a series, a film or a file, a few days at a time the same way."""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import PureWindowsPath
from typing import Literal

from maku.changes import ChangeState, changes_of, tally
from maku.convert import replaced_since
from maku.core.media import media_from_ffprobe
from maku.core.plan import DELETED
from maku.core.search import found, words
from maku.subtitles import NOTHING_SAID, TAKEN_AWAY, present

log = logging.getLogger(__name__)

DAYS_A_PAGE = 7  # days with something on them, a page of History


@dataclass(frozen=True)
class Picture:
    """A video's picture and size, before or after converting."""

    height: int | None
    codec: str | None
    size: int | None


@dataclass(frozen=True)
class Conversion:
    job_id: int
    kind: str  # convert, or merge: English added from another copy, nothing converted
    method: str  # remux or reencode
    before: Picture
    after: Picture
    seconds: float | None  # how long converting took
    restored: bool  # the original is back in its place
    replaced: bool = False  # a later job replaced the file since: that's put back first


@dataclass(frozen=True)
class PlanDone:
    id: int
    kind: Literal["tidy", "convert"]
    title: str  # "Renamed 26 Glass Orchard files", "Converted Quiet Hours · S01E03"
    applied_at: str
    undone_at: str | None
    moved: int  # videos and subtitles filed, and still there
    # Copies set aside, and still there (their subtitles uncounted): a conversion's original
    # is gone once cleared out, or at once when the owner chose to delete originals.
    quarantined: int
    failed: int  # changes that couldn't be made
    undone: int  # changes put back
    deleted: bool = False  # the owner deleted these videos: they went to quarantine
    conversion: Conversion | None = None  # what a conversion made of its file
    # English subtitles Maku made, taken away: those set aside and still there to put back.
    taken_away: int = 0


@dataclass(frozen=True)
class SubtitlesDone:
    """A batch of English subtitles the owner asked for at once."""

    id: int
    title: str  # what they're for: "Starfall Academy · Season 1"
    quality: str  # best or fast
    language: str  # the sound they're made from: "jpn"
    made_at: str  # when the latest of them was over
    made: int  # videos that got them
    quiet: int  # videos where no one speaks: none were made
    failed: int  # videos they couldn't be made for
    waiting: int  # videos still in the queue for them
    present: int  # of those made, how many are there now as Maku wrote them


@dataclass(frozen=True)
class ScanDone:
    id: int
    started_at: str
    finished_at: str | None
    state: str  # running, paused, done or failed
    problem: str | None
    note: str | None
    added: int | None = None  # videos it found new; None for a scan from before Maku counted
    gone: int | None = None  # videos it found gone


@dataclass(frozen=True)
class Page:
    """What Maku did on a few days, newest first, and where the page after it starts."""

    plans: list[PlanDone]
    scans: list[ScanDone]
    older: str | None  # the day the next page starts before ("2026-10-07"); None: that's all
    subtitles: list[SubtitlesDone] = field(default_factory=list["SubtitlesDone"])


def page(
    conn: sqlite3.Connection,
    *,
    before: str | None = None,
    days: int = DAYS_A_PAGE,
    query: str = "",
) -> Page:
    """Everything on the `days` latest days that have anything on them, before the day `before`
    ("2026-10-14"; None: from today). A day is the local one a thing happened on (scans keep UTC
    times, tidy-ups local ones). A tidy-up undone on a later day is on that day's page too, so
    the undo shows where it happened, whichever page its tidy-up is on. With a `query`, only
    what it finds (`_found_page`)."""
    wanted = words(query)
    if wanted:
        return _found_page(conn, wanted, before, days)
    on = [
        row[0]
        for row in conn.execute(
            f"""SELECT day FROM (
                   SELECT date(applied_at, 'localtime') AS day FROM plans
                   UNION SELECT date(undone_at, 'localtime') FROM plans
                   UNION SELECT date(started_at, 'localtime') FROM scans
                   UNION SELECT date(made_at, 'localtime') FROM ({_BATCHES}))
               WHERE day IS NOT NULL AND (?1 IS NULL OR day < ?1)
               ORDER BY day DESC LIMIT ?2""",  # noqa: S608 - a constant query goes in
            (before, days + 1),
        )
    ]
    shown = on[:days]
    if not shown:
        return Page(plans=[], scans=[], older=None, subtitles=[])
    first, last = shown[-1], shown[0]
    rows = conn.execute(
        """SELECT id, kind, title, applied_at, undone_at FROM plans
           WHERE applied_at IS NOT NULL
             AND (date(applied_at, 'localtime') BETWEEN ?1 AND ?2
                  OR date(undone_at, 'localtime') BETWEEN ?1 AND ?2)
           ORDER BY applied_at DESC, id DESC""",
        (first, last),
    ).fetchall()
    scanned = conn.execute(
        """SELECT id, started_at, finished_at, state, problem, note, added, gone FROM scans
           WHERE date(started_at, 'localtime') BETWEEN ? AND ? ORDER BY id DESC""",
        (first, last),
    )
    made = conn.execute(
        f"""SELECT * FROM ({_BATCHES})
            WHERE date(made_at, 'localtime') BETWEEN ? AND ?
            ORDER BY made_at DESC, id DESC""",  # noqa: S608 - a constant query goes in
        (first, last),
    ).fetchall()
    return Page(
        plans=_done(conn, rows),
        scans=[ScanDone(**dict(row)) for row in scanned],
        older=first if len(on) > days else None,
        subtitles=[_made(conn, row) for row in made],
    )


def _found_page(conn: sqlite3.Connection, wanted: list[str], before: str | None, days: int) -> Page:
    """What a search finds, on the `days` latest days it finds anything on: the tidy-ups and
    conversions whose title or a change has every word (its label, or its file's name before or
    after), and the batches of subtitles whose title or a video has. Scans name nothing."""
    plan_ids = _plans_with(conn, wanted)
    batch_ids = _batches_with(conn, wanted)
    plan_days = [
        (row["id"], row["applied"], row["undone"])
        for row in conn.execute(
            """SELECT id, date(applied_at, 'localtime') AS applied,
                      date(undone_at, 'localtime') AS undone
               FROM plans WHERE applied_at IS NOT NULL"""
        )
        if row["id"] in plan_ids
    ]
    batches = [
        row
        for row in conn.execute(
            f"""SELECT *, date(made_at, 'localtime') AS day FROM ({_BATCHES})
                ORDER BY made_at DESC, id DESC"""  # noqa: S608 - a constant query goes in
        )
        if row["id"] in batch_ids
    ]
    on = sorted(
        {day for _, *both in plan_days for day in both if day}
        | {row["day"] for row in batches if row["day"]},
        reverse=True,
    )
    on = [day for day in on if before is None or day < before]
    shown = on[:days]
    if not shown:
        return Page(plans=[], scans=[], older=None, subtitles=[])
    first, last = shown[-1], shown[0]

    def within(day: str | None) -> bool:
        return day is not None and first <= day <= last

    ids = [plan for plan, applied, undone in plan_days if within(applied) or within(undone)]
    rows = conn.execute(
        f"""SELECT id, kind, title, applied_at, undone_at FROM plans
            WHERE id IN ({", ".join("?" * len(ids))})
            ORDER BY applied_at DESC, id DESC""",  # noqa: S608 - placeholders only
        ids,
    ).fetchall()
    return Page(
        plans=_done(conn, rows),
        scans=[],
        older=first if len(on) > days else None,
        subtitles=[_made(conn, row) for row in batches if within(row["day"])],
    )


def _plans_with(conn: sqlite3.Connection, wanted: list[str]) -> set[int]:
    """The tidy-ups and conversions whose title, or one change, has every word."""
    ids = {
        row["id"]
        for row in conn.execute("SELECT id, title FROM plans")
        if found(wanted, row["title"])
    }
    for row in conn.execute("SELECT plan_id, label, source, target FROM changes"):
        if row["plan_id"] not in ids and found(
            wanted, row["label"], _name(row["source"]), _name(row["target"])
        ):
            ids.add(row["plan_id"])
    return ids


def _batches_with(conn: sqlite3.Connection, wanted: list[str]) -> set[int]:
    """The batches of subtitles whose title, or one video's file, has every word."""
    ids = {
        row["id"]
        for row in conn.execute("SELECT id, title FROM subtitle_batches")
        if found(wanted, row["title"])
    }
    for row in conn.execute(
        """SELECT j.batch_id, f.path FROM jobs AS j JOIN files AS f ON f.id = j.file_id
           WHERE j.batch_id IS NOT NULL"""
    ):
        if found(wanted, _name(row["path"])):
            ids.add(row["batch_id"])
    return ids


def _name(path: str) -> str:
    return PureWindowsPath(path).name


def clear(conn: sqlite3.Connection, *, keep: timedelta, now: datetime) -> int:
    """Forgets what Maku did more than `keep` ago: tidy-ups and conversions applied (and undone,
    if they were) before then, and scans. What has a copy still in quarantine stays, since
    History puts it back and the clear-out finds it through it, and so does a change still under
    way, the latest scan and one not over yet. Nothing on disk changes. Returns how many went."""
    cutoff = now - keep
    plans = [
        row["id"]
        for row in conn.execute(
            """SELECT p.id, COALESCE(p.undone_at, p.applied_at) AS last FROM plans AS p
               WHERE p.applied_at IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM changes AS c WHERE c.plan_id = p.id AND (
                         (c.kind = 'quarantine' AND c.state = 'done' AND c.cleared_at IS NULL)
                         OR c.state IN (?, ?, ?)))
                 AND NOT EXISTS (
                     SELECT 1 FROM jobs AS j WHERE j.plan_id = p.id AND j.state = 'replacing')""",
            (ChangeState.PLANNED, ChangeState.MOVING, ChangeState.UNDOING),
        )
        if _before(row["last"], cutoff)
    ]
    latest = conn.execute("SELECT MAX(id) FROM scans").fetchone()[0]
    scans = [
        row["id"]
        for row in conn.execute(
            "SELECT id, started_at FROM scans WHERE state IN ('done', 'failed') AND id != ?",
            (latest,),
        )
        if _before(row["started_at"], cutoff)
    ]
    batches = [
        row["id"]
        for row in conn.execute(
            f"""SELECT b.id, b.made_at FROM ({_BATCHES}) AS b
                WHERE NOT EXISTS (SELECT 1 FROM jobs AS j
                                  WHERE j.batch_id = b.id
                                    AND j.state IN ('queued', 'running'))"""  # noqa: S608 - as above
        )
        if _before(row["made_at"], cutoff)
    ]
    with conn:
        for plan_id in plans:
            conn.execute("UPDATE jobs SET plan_id = NULL WHERE plan_id = ?", (plan_id,))
            conn.execute("DELETE FROM changes WHERE plan_id = ?", (plan_id,))
            conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
        conn.executemany("DELETE FROM scans WHERE id = ?", [(scan_id,) for scan_id in scans])
        # Maku still knows the subtitles it made as its own; History forgets the batch.
        conn.executemany(
            "DELETE FROM subtitle_batches WHERE id = ?", [(batch,) for batch in batches]
        )
    if plans or scans or batches:
        log.info(
            "Cleared %d tidy-ups and conversions, %d batches of subtitles and %d scans from "
            "History",
            len(plans),
            len(batches),
            len(scans),
        )
    return len(plans) + len(scans) + len(batches)


def _before(stamp: str, cutoff: datetime) -> bool:
    """Whether a stored time is before `cutoff`: one without an offset is this PC's local time,
    and one Maku can't read stays."""
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return False
    return (moment if moment.tzinfo else moment.astimezone()) < cutoff


def plans(conn: sqlite3.Connection) -> list[PlanDone]:
    """Every tidy-up and conversion that was applied, newest first."""
    rows = conn.execute(
        """SELECT id, kind, title, applied_at, undone_at FROM plans
           WHERE applied_at IS NOT NULL
           ORDER BY applied_at DESC, id DESC"""
    ).fetchall()
    return _done(conn, rows)


def _done(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[PlanDone]:
    """The plans those rows are, with what became of their changes."""
    done: list[PlanDone] = []
    for row in rows:
        changes = changes_of(conn, row["id"])
        states = [change.state for change in changes]
        moved, quarantined = tally(
            c for c in changes if c.state is ChangeState.DONE and c.cleared_at is None
        )
        done.append(
            PlanDone(
                **dict(row),
                moved=moved,
                quarantined=quarantined,
                failed=states.count(ChangeState.FAILED),
                undone=states.count(ChangeState.UNDONE),
                deleted=bool(changes) and all(change.reason == DELETED for change in changes),
                conversion=_conversion(conn, row["id"]) if row["kind"] == "convert" else None,
                taken_away=sum(
                    1
                    for change in changes
                    if change.reason == TAKEN_AWAY
                    and change.state is ChangeState.DONE
                    and change.cleared_at is None
                ),
            )
        )
    return done


# Each batch of subtitles with anything over: when the latest of its videos was.
_BATCHES = """SELECT b.*, MAX(j.finished_at) AS made_at FROM subtitle_batches AS b
   JOIN jobs AS j ON j.batch_id = b.id
   WHERE j.state IN ('done', 'failed') AND j.finished_at IS NOT NULL
   GROUP BY b.id"""


def _made(conn: sqlite3.Connection, row: sqlite3.Row) -> SubtitlesDone:
    counts = conn.execute(
        """SELECT
               SUM(state = 'done' AND (problem IS NULL OR problem != ?)) AS made,
               SUM(state = 'done' AND problem = ?) AS quiet,
               SUM(state = 'failed') AS failed,
               SUM(state IN ('queued', 'running')) AS waiting
           FROM jobs WHERE batch_id = ?""",
        (NOTHING_SAID, NOTHING_SAID, row["id"]),
    ).fetchone()
    return SubtitlesDone(
        id=row["id"],
        title=row["title"],
        quality=row["quality"],
        language=row["language"],
        made_at=row["made_at"],
        made=counts["made"] or 0,
        quiet=counts["quiet"] or 0,
        failed=counts["failed"] or 0,
        waiting=counts["waiting"] or 0,
        present=present(conn, row["id"]),
    )


def _conversion(conn: sqlite3.Connection, plan_id: int) -> Conversion | None:
    job = conn.execute("SELECT * FROM jobs WHERE plan_id = ?", (plan_id,)).fetchone()
    if job is None:
        return None
    took = None
    if job["started_at"] and job["finished_at"]:
        began, ended = (datetime.fromisoformat(job[key]) for key in ("started_at", "finished_at"))
        took = (ended - began).total_seconds()
    return Conversion(
        job_id=job["id"],
        kind="merge" if job["kind"] == "merge" else "convert",
        method=job["method"],
        before=_picture(job["source_probe"], job["source_size"]),
        after=_picture(job["output_probe"], job["output_size"]),
        seconds=took,
        restored=job["state"] == "restored",
        replaced=replaced_since(conn, job),
    )


def _picture(probe: str | None, size: int | None) -> Picture:
    video = media_from_ffprobe(json.loads(probe)).video if probe else None
    return Picture(video.height if video else None, video.codec if video else None, size)


def scans(conn: sqlite3.Connection, count: int = 50) -> list[ScanDone]:
    """The latest scans, newest first."""
    rows = conn.execute(
        """SELECT id, started_at, finished_at, state, problem, note, added, gone
           FROM scans ORDER BY id DESC LIMIT ?""",
        (count,),
    )
    return [ScanDone(**dict(row)) for row in rows]
