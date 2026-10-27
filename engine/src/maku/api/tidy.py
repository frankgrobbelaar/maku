"""Tidying up: what Maku proposes, applying the changes the owner keeps, and History, where any
tidy-up can be undone. Nothing moves while a scan runs, and no scan starts while files move."""

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import Field

from maku import history, tidy
from maku.api.common import ApiModel, Database, Scans
from maku.changes import SavedChange
from maku.convert import ConvertError
from maku.core.plan import KEPT_BOTH, ChangeKind
from maku.queue import Queue
from maku.scan import ScanBusyError

router = APIRouter()


class CopyFacts(ApiModel):
    path: str
    height: int | None
    codec: str | None
    audio: list[str]  # languages
    subtitles: int  # tracks that can be switched off
    size: int
    plays: bool
    # Its subtitles' languages, in it and in the files beside it ("ger", "en"; "" unsaid).
    subtitle_languages: list[str]


class English(ApiModel):
    """English the copy set aside has in it that the one kept hasn't, which Maku can add."""

    other: str  # the copy set aside
    sound: bool  # its English sound comes
    subtitles: bool  # its English subtitles come
    tried: str | None  # why Maku couldn't, the last time it was asked to


class Duplicate(ApiModel):
    label: str  # "The Harbour Line · S01E01"
    keep: CopyFacts
    drop: list[CopyFacts]
    reason: str
    english: English | None  # two copies: what the one set aside could give the one kept


class Compared(ApiModel):
    """A name another file has: that file, when Maku knows it, and the one coming, to compare."""

    there: CopyFacts | None
    coming: CopyFacts
    # What the file there does in the same tidy-up: stays, leaves (moved or set aside), or
    # arrives there (another video filed to that name).
    there_goes: Literal["stays", "leaves", "arrives"]


class ProposedChange(ApiModel):
    kind: Literal["move", "quarantine"]
    source: str
    target: str
    root: str  # the library folder it's in
    label: str
    reason: str
    category: Literal["rename", "mixed", "duplicate"]
    title_id: int
    title: str
    taken: bool  # its name was another file's, so it gets "(2)": Maku never overwrites a file
    compared: Compared | None  # when it was taken: the file there and this one
    video: str  # the video the change is of: itself, or the one subtitles go with


class SkippedFile(ApiModel):
    path: str
    reason: str


class TidyProposal(ApiModel):
    changes: list[ProposedChange]
    skipped: list[SkippedFile]  # videos that stay where they are, and why
    duplicates: list[Duplicate]
    waiting: int  # videos that need a match first
    broken: int  # videos that won't play


class ReviewedChange(ApiModel):
    """A proposed change, as the owner saw it."""

    source: str
    kind: Literal["move", "quarantine"]
    target: str


class TidyRequest(ApiModel):
    # The changes to make (of videos, and the subtitles that go with them), as reviewed.
    changes: list[ReviewedChange]
    # Copies the owner chose to keep over others of the same episode.
    keep: list[str] = Field(default_factory=list[str])
    # Copies kept that get the English of the copy set aside: it waits in the queue, and that
    # copy stays where it is till it's in.
    english: list[str] = Field(default_factory=list[str])


class ChangeProblem(ApiModel):
    label: str
    source: str
    problem: str


class TidyResult(ApiModel):
    plan_id: int | None  # None when nothing was asked for
    moved: int
    quarantined: int
    problems: list[ChangeProblem]
    english: int = 0  # copies kept whose other copy's English joined the queue


class Picture(ApiModel):
    height: int | None
    codec: str | None
    size: int | None


class Conversion(ApiModel):
    job_id: int
    # A conversion, or English added from another copy, which went to quarantine with the
    # original (`method` is then a remux: nothing was converted).
    kind: Literal["convert", "merge"]
    method: Literal["remux", "reencode"]
    before: Picture
    after: Picture
    seconds: float | None  # how long converting took
    restored: bool  # the original is back in its place
    # A later conversion, or another copy's English, replaced the file since: that's put back
    # first.
    replaced: bool


class PlanDone(ApiModel):
    id: int
    kind: Literal["tidy", "convert"]
    title: str
    applied_at: str
    undone_at: str | None
    moved: int
    quarantined: int
    failed: int
    undone: int
    deleted: bool  # the owner deleted these videos: they went to quarantine
    conversion: Conversion | None  # for a conversion: what the file became
    # English subtitles Maku made, taken away: those set aside and still there to put back.
    taken_away: int


class ScanDone(ApiModel):
    id: int
    started_at: str
    finished_at: str | None
    state: str
    problem: str | None
    note: str | None
    added: int | None  # videos it found new; None for a scan from before Maku counted
    gone: int | None  # videos it found gone


class SubtitlesDone(ApiModel):
    """A batch of English subtitles the owner asked for at once."""

    id: int
    title: str  # what they're for: "Starfall Academy · Season 1"
    quality: Literal["best", "fast"]
    language: str  # the sound they're made from: "jpn"
    made_at: str  # when the latest of them was over
    made: int  # videos that got them
    quiet: int  # videos where no one speaks: none were made
    failed: int  # videos they couldn't be made for
    waiting: int  # videos still in the queue for them
    present: int  # of those made, how many are there now as Maku wrote them


class History(ApiModel):
    plans: list[PlanDone]  # newest first
    scans: list[ScanDone]  # newest first
    subtitles: list[SubtitlesDone]  # newest first
    older: str | None = None  # the day the next page starts before ("2026-10-07"); None: no more


class ClearHistory(ApiModel):
    # What stays: the last day, week or month of it, or nothing.
    keep: Literal["day", "week", "month", "nothing"]


class Cleared(ApiModel):
    cleared: int  # tidy-ups, conversions, batches of subtitles and scans forgotten


KEEPS = {
    "day": timedelta(days=1),
    "week": timedelta(days=7),
    "month": timedelta(days=30),
    "nothing": timedelta(0),
}


Keep = Annotated[list[str], Query(description="Copies to keep over the others of an episode")]


@router.get("/tidy")
def proposal(conn: Database, keep: Keep = []) -> TidyProposal:  # noqa: B006 - FastAPI's way
    """Where every identified video would go, filed for Plex. Nothing changes."""
    found = tidy.propose(conn, day=_now().date(), keep=keep)
    counts = conn.execute(
        """SELECT SUM(matched IN ('unsure', 'none') AND pinned = 0) AS waiting,
                  SUM(problem IS NOT NULL) AS broken
           FROM files WHERE gone_at IS NULL"""
    ).fetchone()
    return TidyProposal(
        changes=[
            ProposedChange(
                kind=p.change.kind.value,
                source=str(p.change.source),
                target=str(p.change.target),
                root=str(p.root),
                label=p.change.label,
                reason=p.change.reason,
                category=p.category,
                title_id=p.title_id,
                title=p.title,
                taken=p.change.reason.endswith(KEPT_BOTH),
                compared=_compared(p.compared),
                video=str(p.video),
            )
            for p in found.changes
        ],
        skipped=[SkippedFile(path=str(path), reason=why) for path, why in found.skipped],
        duplicates=[
            Duplicate(
                label=d.label,
                keep=_copy(d.keep),
                drop=[_copy(copy) for copy in d.drop],
                reason=d.reason,
                english=English(
                    other=str(d.english.other),
                    sound=d.english.sound,
                    subtitles=d.english.subtitles,
                    tried=d.english.tried,
                )
                if d.english
                else None,
            )
            for d in found.duplicates
        ],
        waiting=counts["waiting"] or 0,
        broken=counts["broken"] or 0,
    )


@router.post("/tidy")
def apply_tidy(body: TidyRequest, conn: Database, scans: Scans, request: Request) -> TidyResult:
    """Makes the changes the owner reviewed, journaled so History can undo them, and puts the
    English asked for from other copies in the queue. None is made when Maku proposes any of
    them differently now."""
    reviewed = [tidy.Reviewed(c.source, ChangeKind(c.kind), c.target) for c in body.changes]
    try:
        with scans.hold():
            done = tidy.apply(conn, reviewed, now=_now(), keep=body.keep, english=body.english)
    except ScanBusyError as busy:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{busy} Tidy up once it's done, so Maku knows every file."
        ) from None
    except tidy.ProposalChangedError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Maku's proposal changed since you looked at it. Look it over again before applying.",
        ) from None
    worker: Queue = request.app.state.queue
    queued = sum(1 for kept, other in done.english if worker.add_merge(kept, other))
    return _result(done, english=queued)


class DeleteRequest(ApiModel):
    files: list[int]  # the videos to delete, each with the subtitles named after it


@router.post("/files/delete")
def delete_files(body: DeleteRequest, conn: Database, scans: Scans) -> TidyResult:
    """Deletes videos the way Maku deletes: into the quarantine on their own drive, with their
    subtitles, journaled so History can put them back till the quarantine is cleared out."""
    try:
        with scans.hold():
            done = tidy.delete(conn, body.files, now=_now())
    except ScanBusyError as busy:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{busy} Delete it once that's done."
        ) from None
    except tidy.ConvertingError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    return _result(done)


Day = Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")]


@router.get("/history")
def what_maku_did(
    conn: Database, before: Day = None, q: Annotated[str, Query(max_length=200)] = ""
) -> History:
    """What Maku did on its latest days with anything on them (a week's worth), newest first:
    each tidy-up applied, each conversion, each batch of subtitles made and each scan.
    `before` ("2026-10-07", the page's `older`) asks for the days before that one, and `q` for
    what names a series, a film or a file ("Starfall 03"), on the days it finds anything on."""
    found = history.page(conn, before=before, query=q)
    return History(
        plans=[PlanDone.model_validate(asdict(plan)) for plan in found.plans],
        scans=[ScanDone.model_validate(scan.__dict__) for scan in found.scans],
        subtitles=[SubtitlesDone.model_validate(made.__dict__) for made in found.subtitles],
        older=found.older,
    )


@router.post("/history/clear")
def clear_history(body: ClearHistory, conn: Database) -> Cleared:
    """Forgets what Maku did before the last day, week or month, or all of it. What still has a
    copy in quarantine stays, so it can be put back, and nothing on disk changes."""
    return Cleared(cleared=history.clear(conn, keep=KEEPS[body.keep], now=_now()))


@router.post("/plans/{plan_id}/undo")
def undo_plan(plan_id: int, conn: Database, scans: Scans, request: Request) -> TidyResult:
    """Puts back what a tidy-up moved, or what couldn't go back last time. For a conversion,
    the original comes back in the converted file's place."""
    plan = conn.execute("SELECT kind FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Maku has no such tidy-up.")
    try:
        if plan["kind"] == "convert":
            return _put_back(conn, plan_id, request)
        with scans.hold():
            done = tidy.undo(conn, plan_id, now=_now())
    except ScanBusyError as busy:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{busy} Undo it once that's done.") from None
    return _result(done)


def _put_back(conn: Database, plan_id: int, request: Request) -> TidyResult:
    """A conversion undone: its original back from quarantine (maku/queue.py), and for English
    added from another copy, that copy too."""
    job = conn.execute("SELECT id FROM jobs WHERE plan_id = ?", (plan_id,)).fetchone()
    worker: Queue = request.app.state.queue
    try:
        stayed = worker.restore(job["id"] if job else 0)
    except ConvertError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    return TidyResult(
        plan_id=plan_id, moved=1, quarantined=0, problems=[_problem(change) for change in stayed]
    )


def _result(done: tidy.Tidied, *, english: int = 0) -> TidyResult:
    return TidyResult(
        plan_id=done.plan_id,
        moved=done.moved,
        quarantined=done.quarantined,
        problems=[_problem(change) for change in done.problems],
        english=english,
    )


def _problem(change: SavedChange) -> ChangeProblem:
    return ChangeProblem(
        label=change.label, source=str(change.source), problem=change.problem or "It failed."
    )


def _compared(
    found: tuple[tidy.CopyFacts | None, tidy.CopyFacts, tidy.Goes] | None,
) -> Compared | None:
    if found is None:
        return None
    there, coming, goes = found
    return Compared(there=_copy(there) if there else None, coming=_copy(coming), there_goes=goes)


def _copy(copy: tidy.CopyFacts) -> CopyFacts:
    return CopyFacts(
        path=str(copy.path),
        height=copy.height,
        codec=copy.codec,
        audio=list(copy.audio),
        subtitles=copy.subtitles,
        size=copy.size,
        plays=copy.plays,
        subtitle_languages=list(copy.subtitle_languages),
    )


def _now() -> datetime:
    return datetime.now().astimezone()
