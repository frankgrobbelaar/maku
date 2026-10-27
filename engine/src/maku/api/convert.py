"""Converting the library to its standard: what can be converted, with what each file gets and
what it takes, the queue that converts it, one file at a time, and making room for it."""

import json
import shutil
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import Field

from maku import hardware, preview
from maku import queue as conversions
from maku.api.common import ApiModel, Database, Paths, Scans
from maku.convert import CONVERTED, ConvertError, Programs, label_of
from maku.core.estimate import estimate
from maku.core.library import drive_of
from maku.core.media import media_from_ffprobe
from maku.core.standard import decide
from maku.gpu import Gpu
from maku.preferences import library_standard
from maku.quarantine import empty, set_aside_by_drive
from maku.scan import ScanBusyError

router = APIRouter()


class Convertible(ApiModel):
    """A video not at the library's standard yet."""

    file_id: int
    label: str  # "The Harbour Line · S01E06"
    title_id: int | None
    title: str | None
    season: int | None
    episode: int | None
    seconds: float  # how long it plays
    width: int
    height: int
    aspect: str  # "4:3", "16:9"
    hdr: Literal["HDR10", "HLG"] | None  # an HDR picture, which stays HDR
    size: int
    drive: str  # "D:"
    # What it gets: a new picture (re-encoded), or its own in an MKV (remuxed), and why.
    method: Literal["remux", "reencode"]
    reasons: list[str]  # "4K HDR: brought down to 1080p, HDR kept"
    output_width: int  # the result's picture: its own, or brought down to the standard
    output_height: int
    gpu_seconds: float  # how long it takes on this PC, about; none for a broken file
    output_bytes: int  # the result's size, about
    waiting: bool  # in the queue already, or converting
    broken: bool  # it won't play: it can't be converted


class ConvertOptions(ApiModel):
    standard: str  # "4K": the most any picture comes to
    files: list[Convertible]
    free: dict[str, int]  # bytes free on each drive the files are on
    set_aside: dict[str, int]  # bytes emptying each drive's quarantine would free


class Job(ApiModel):
    id: int
    file_id: int
    path: str
    label: str
    title_id: int | None
    title: str | None
    season: int | None
    episode: int | None
    # What it gets: a conversion "remux" or "reencode"; subtitles their quality, "best" or "fast".
    method: Literal["remux", "reencode", "fast", "best"]
    state: Literal["queued", "running", "replacing", "done", "failed", "skipped", "restored"]
    gpu_seconds: float
    added_at: str
    started_at: str | None
    finished_at: str | None
    problem: str | None
    source_size: int
    output_size: int | None
    width: int | None  # the result's picture, for a file still to finish
    height: int | None
    drive_missing: bool  # waiting, and its drive isn't connected
    # Made, and waiting beside its original for another app (a player) to let go of it: when
    # Maku tries again to put it in place.
    retry_at: str | None
    log: str | None  # what ffmpeg said, when a conversion failed ("Copy full log")
    no_room: bool  # waiting for room on its drive while the others go
    # A conversion, English subtitles, or English from another copy added to the file.
    kind: Literal["convert", "subtitles", "merge"]
    language: str | None  # subtitles: the sound they're made from ("jpn"; "" when it's unsaid)
    model_missing: bool  # subtitles waiting for their speech model to download
    fast_instead: bool  # subtitles at Best that failed where Fast would go ("Make them with Fast")


class Room(ApiModel):
    """A drive without room for the files waiting to convert on it."""

    drive: str  # "D:"
    paused: bool  # the queue paused for it; else the files that don't fit wait while others go
    files: int  # files waiting to convert on it
    needed: int  # the free space their results want, in bytes
    free: int  # bytes free on it now
    fit: int  # how many of them fit now, in turn
    set_aside: int  # bytes its quarantine would free, emptied now


class Running(ApiModel):
    job: Job
    stage: Literal[
        "looking", "converting", "checking", "replacing", "reading", "listening", "writing"
    ]
    # Converted so far: frames; for subtitles, seconds of the video heard; for English from
    # another copy, bytes written.
    frames: int
    total: int
    seconds_left: float | None
    fps: float | None


class GpuReading(ApiModel):
    busy: int  # percent
    celsius: int


class QueueStatus(ApiModel):
    paused: bool
    schedule: Literal["now", "nights"]
    waits_for_night: bool  # nights only, and it's day (or tonight's run is over)
    problem: str | None  # why nothing converts though files wait
    running: Running | None
    queued: list[Job]  # in the order they'll go
    gpu_seconds: float  # the work left
    today: list[Job]  # finished today, newest first
    gpu: GpuReading | None  # the card's load and temperature, while a file converts
    room: Room | None  # a drive without room for what waits on it
    # Nights only, at night: when tonight's run takes its last file (07:00, or earlier when the
    # owner said to stop early), local time; and whether they did.
    ends_at: str | None
    early: bool


class AddRequest(ApiModel):
    files: list[int]  # each gets what suits it: a new picture, or its own in an MKV
    # When they convert: "now" or "nights" set the schedule and resume the queue if it was
    # paused; "after" leaves the queue as it is, so they go after what waits.
    when: Literal["now", "nights", "after"] = "after"
    # Drives ("D:") without room for them all: the files that fit there convert, and the rest
    # wait for room while the others go.
    fit: list[str] = Field(default_factory=list[str])


class DriveRequest(ApiModel):
    drive: str  # "D:"


class Emptied(ApiModel):
    files: int  # files deleted from the drive's quarantine


class Added(ApiModel):
    added: int


class MoveRequest(ApiModel):
    before: int | None = Field(default=None, description="The job to go before; None: last")


class JobsRequest(ApiModel):
    """Several files in the queue at once, by their jobs."""

    ids: list[int]


class MoveJobsRequest(JobsRequest):
    before: int | None = Field(default=None, description="The job to go before; None: last")


class Changed(ApiModel):
    changed: int  # how many files it changed: the others weren't waiting any more


class ScheduleRequest(ApiModel):
    schedule: Literal["now", "nights"]


class TonightRequest(ApiModel):
    early: bool  # stop at 03:00 tonight (past it, after the file converting), or go on till 07:00


def _queue(request: Request) -> conversions.Queue:
    worker: conversions.Queue = request.app.state.queue
    return worker


def _gpu(request: Request) -> Gpu:
    gpu: Gpu = request.app.state.gpu
    return gpu


Queue = Annotated[conversions.Queue, Depends(_queue)]
Card = Annotated[Gpu, Depends(_gpu)]


@router.get("/convert")
def what_to_convert(conn: Database) -> ConvertOptions:
    """Every video not at the standard yet, with what it gets, and what that takes on this
    PC."""
    standard = library_standard(conn)
    speeds = hardware.speeds(conn)
    rows = conn.execute(
        """SELECT f.id, f.path, f.probe, f.problem, f.season, f.episode, f.title_id,
                  t.name AS title,
                  EXISTS (SELECT 1 FROM jobs AS j WHERE j.file_id = f.id AND j.kind = 'convert'
                          AND j.state IN ('queued', 'running', 'replacing')) AS waiting
           FROM files AS f LEFT JOIN titles AS t ON t.id = f.title_id
           WHERE f.gone_at IS NULL AND f.probe IS NOT NULL AND f.matched != 'ignored'
             AND f.id NOT IN (SELECT m.other_id FROM jobs AS m
                              WHERE m.kind = 'merge' AND m.other_id IS NOT NULL
                                AND m.state IN ('queued', 'running', 'replacing'))
           ORDER BY t.released, t.name, f.season, f.episode, f.path"""
    ).fetchall()
    found: list[Convertible] = []
    places: dict[str, str] = {}  # each drive, by where a file on it is
    for row in rows:
        media = media_from_ffprobe(json.loads(row["probe"]))
        video = media.video
        decision = decide(media, standard)
        if video is None or decision.method not in CONVERTED:
            continue
        broken = row["problem"] is not None
        places.setdefault(drive_of(row["path"]), str(Path(row["path"]).parent))
        made = estimate(media, decision, speeds) if not broken else None
        found.append(
            Convertible(
                file_id=row["id"],
                label=label_of(row),
                title_id=row["title_id"],
                title=row["title"],
                season=row["season"],
                episode=row["episode"],
                seconds=media.duration or 0.0,
                width=video.width,
                height=video.height,
                aspect=f"{video.display_aspect.numerator}:{video.display_aspect.denominator}",
                hdr=cast("Literal['HDR10', 'HLG'] | None", video.hdr),
                size=media.size or 0,
                drive=drive_of(row["path"]),
                method=decision.method.value,
                reasons=list(decision.reasons),
                output_width=decision.width,
                output_height=decision.height,
                gpu_seconds=made.gpu_seconds if made else 0.0,
                output_bytes=made.output_bytes if made else 0,
                waiting=bool(row["waiting"]),
                broken=broken,
            )
        )
    return ConvertOptions(
        standard=standard.name,
        files=found,
        free=_free(places),
        set_aside=set_aside_by_drive(conn),
    )


@router.get(
    "/convert/{file_id}/preview/{side}",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}}}},
)
def see_it_first(
    file_id: int,
    side: Literal["before", "after"],
    conn: Database,
    paths: Paths,
    request: Request,
    point: int = 1,
) -> FileResponse:
    """One side of the comparison: a frame of the file as it is (`before`), or as converting
    makes it (`after`), taken at one of three points (0, 1 or 2: 15%, 50% and 80% of the way
    in)."""
    kit: Programs | None = request.app.state.programs()
    if kit is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, conversions.NO_FFMPEG)
    row = conn.execute(
        "SELECT path, probe FROM files WHERE id = ? AND gone_at IS NULL", (file_id,)
    ).fetchone()
    if row is None or row["probe"] is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That file isn't in the library any more.")
    media = media_from_ffprobe(json.loads(row["probe"]))
    try:
        picture = preview.frame(
            paths,
            kit,
            Path(row["path"]),
            media,
            library_standard(conn),
            side=side,
            point=point,
        )
    except preview.PreviewError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    return FileResponse(picture, media_type="image/png")


@router.get("/queue")
def queue_status(queue: Queue, card: Card) -> QueueStatus:
    return _status(queue.status(), card)


@router.post("/queue")
def add_to_queue(body: AddRequest, queue: Queue) -> Added:
    """Puts files at the end of the queue, to convert now, at night, or after what waits."""
    if body.when != "after":
        queue.plan(body.when)  # before they join: the worker never sees the old schedule
        queue.resume()
    added = queue.add(body.files, fit=body.fit)
    return Added(added=added)


@router.post("/queue/pause")
def pause_queue(queue: Queue, card: Card) -> QueueStatus:
    """Stops the file converting now (it starts over on resuming) and takes no other."""
    queue.pause()
    return _status(queue.status(), card)


@router.post("/queue/resume")
def resume_queue(queue: Queue, card: Card) -> QueueStatus:
    queue.resume()
    return _status(queue.status(), card)


@router.post("/queue/fit")
def convert_what_fits(body: DriveRequest, queue: Queue, card: Card) -> QueueStatus:
    """On a drive without room for all that waits on it, the files that fit convert, and the
    rest wait for room while the others go. The queue goes on if it paused."""
    queue.convert_what_fits(body.drive)
    queue.resume()
    return _status(queue.status(), card)


@router.post("/quarantine/empty")
def empty_quarantine(body: DriveRequest, conn: Database, scans: Scans, queue: Queue) -> Emptied:
    """Deletes everything set aside on a drive now, however recently, to make room there: it
    can't be put back after. Maku asks the owner first. Files waiting for room look again."""
    try:
        with scans.hold():
            cleared = empty(conn, body.drive, now=datetime.now().astimezone())
    except ScanBusyError as busy:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{busy} Empty it once that's done."
        ) from None
    queue.wake()
    return Emptied(files=cleared)


@router.put("/queue/schedule")
def plan_queue(body: ScheduleRequest, queue: Queue, card: Card) -> QueueStatus:
    """Converts whenever files wait, or only at night (23:00 to 07:00)."""
    queue.plan(body.schedule)
    return _status(queue.status(), card)


@router.put("/queue/tonight")
def plan_tonight(body: TonightRequest, queue: Queue, card: Card) -> QueueStatus:
    """On the nights-only schedule: tonight's run stops taking files at 03:00, so Windows' sleep
    comes back sooner, or goes on till 07:00."""
    queue.stop_early(early=body.early)
    return _status(queue.status(), card)


@router.post("/queue/remove")
def remove_jobs(body: JobsRequest, queue: Queue) -> Changed:
    """Takes several waiting files out of the queue; one no longer waiting is passed over."""
    return Changed(changed=queue.remove_all(body.ids))


@router.post("/queue/move")
def move_jobs(body: MoveJobsRequest, queue: Queue) -> Changed:
    """Puts several waiting files together before another, or last, in the order they wait in."""
    return Changed(changed=queue.move_all(body.ids, body.before))


@router.post("/queue/cancel")
def cancel_queue(queue: Queue, card: Card) -> QueueStatus:
    """Cancels everything: every file waiting leaves the queue, and the one converting stops. The
    files themselves stay as they are."""
    queue.cancel_all()
    return _status(queue.status(), card)


@router.post("/queue/{job_id}/skip", status_code=status.HTTP_204_NO_CONTENT)
def skip_job(job_id: int, queue: Queue) -> None:
    """Passes over a file: the one converting stops, one waiting leaves the line."""
    with _known():
        queue.skip(job_id)


@router.delete("/queue/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_job(job_id: int, queue: Queue) -> None:
    with _known():
        queue.remove(job_id)


@router.post("/queue/{job_id}/move", status_code=status.HTTP_204_NO_CONTENT)
def move_job(job_id: int, body: MoveRequest, queue: Queue) -> None:
    with _known():
        queue.move(job_id, body.before)


@router.post("/queue/{job_id}/broken", status_code=status.HTTP_204_NO_CONTENT)
def mark_broken(job_id: int, queue: Queue) -> None:
    """Marks a file whose conversion failed as broken: the library counts it among the files
    that won't play, and it isn't converted again till it changes."""
    with _known():
        queue.mark_broken(job_id)


class RetryRequest(ApiModel):
    quality: Literal["best", "fast"] | None = None  # subtitles: made at this quality instead


@router.post("/queue/{job_id}/retry", status_code=status.HTTP_204_NO_CONTENT)
def retry_job(job_id: int, queue: Queue, body: RetryRequest | None = None) -> None:
    """A failed or skipped file goes back in the queue, last; one made and waiting for another
    app to let go of its original is tried again now ("Try now"). Subtitles go at `quality`
    when it's given: Fast, after the card ran out of memory for Best ("Make them with Fast")."""
    with _known():
        queue.retry(job_id, body.quality if body else None)


@router.post("/queue/{job_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_original(job_id: int, queue: Queue) -> None:
    """Puts a converted file's original back in its place, from quarantine."""
    try:
        queue.restore(job_id)
    except ScanBusyError as busy:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{busy} Put it back once that's done."
        ) from None
    except ConvertError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None


@contextmanager
def _known() -> Generator[None]:
    """A job the queue doesn't have (or not in that state) is a 404."""
    try:
        yield
    except LookupError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None


def _status(found: conversions.QueueStatus, card: Gpu) -> QueueStatus:
    reading = card.reading() if found.running is not None else None
    return QueueStatus(
        paused=found.paused,
        schedule=found.schedule,
        waits_for_night=found.waits_for_night,
        problem=found.problem,
        running=Running(
            job=_job(found.running.job),
            stage=found.running.stage,
            frames=found.running.frames,
            total=found.running.total,
            seconds_left=found.running.seconds_left,
            fps=found.running.fps,
        )
        if found.running
        else None,
        queued=[_job(job) for job in found.queued],
        gpu_seconds=found.gpu_seconds,
        today=[_job(job) for job in found.today],
        gpu=GpuReading(busy=reading.busy, celsius=reading.celsius) if reading else None,
        room=Room.model_validate(found.room.__dict__) if found.room else None,
        ends_at=found.ends_at,
        early=found.early,
    )


def _job(job: conversions.Job) -> Job:
    return Job.model_validate({**job.__dict__, "method": str(job.method)})


def _free(places: dict[str, str]) -> dict[str, int]:
    """Bytes free on each drive, measured where a file on it is (a folder can be another volume,
    mounted there), as converting measures."""
    free: dict[str, int] = {}
    for drive, folder in sorted(places.items()):
        try:
            free[drive] = shutil.disk_usage(folder).free
        except OSError:
            continue  # unplugged
    return free
