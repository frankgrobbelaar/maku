"""English subtitles Maku makes from a video's sound (maku/subtitles.py): the videos that could
have them, asking for a batch (they wait in the queue with the conversions), and taking a batch
away again."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status

from maku import hardware, subtitles
from maku.api.common import ApiModel, Database, Scans
from maku.api.convert import Added, Queue
from maku.scan import ScanBusyError

router = APIRouter()


class Hearable(ApiModel):
    """A video Maku could make English subtitles for."""

    file_id: int
    label: str  # "Starfall Academy · S01E05"
    title_id: int
    title: str
    season: int | None
    episode: int | None
    seconds: float  # how long it plays
    sound: list[str]  # each sound track's language ("jpn"; "" when one doesn't say)
    subtitles: list[str]  # its subtitles' languages, in it and beside it
    english: bool  # it can be heard or read in English already
    made: bool  # English subtitles Maku made are beside it
    waiting: bool  # in the queue for them, or being made


class SubtitleOptions(ApiModel):
    files: list[Hearable]
    # Seconds of the graphics card's time each second of a video takes, at each quality.
    rates: dict[str, float]


class SubtitlesRequest(ApiModel):
    file_ids: list[int]
    quality: Literal["best", "fast"]
    language: str  # the sound to make them from: "jpn"
    title: str  # what History calls the batch: "Starfall Academy · Season 1"
    # When they're made: "now" or "nights" set the queue's schedule and resume it if it was
    # paused; "after" leaves the queue as it is, so they go after what waits.
    when: Literal["now", "nights", "after"] = "after"


class TakenAway(ApiModel):
    plan_id: int | None  # the tidy-up that set them aside; None when none were there


@router.get("/subtitles")
def subtitle_options(conn: Database) -> SubtitleOptions:
    """The library's videos that have sound, with what they can be heard and read in: what
    Maku could make English subtitles for, and how long that takes."""
    return SubtitleOptions(
        files=[
            Hearable.model_validate({**video.__dict__, "english": subtitles.english(video)})
            for video in subtitles.hearable(conn)
        ],
        rates=hardware.hearing(conn),
    )


@router.post("/subtitles")
def make_subtitles(body: SubtitlesRequest, queue: Queue) -> Added:
    """Puts videos in the queue for English subtitles, as one batch, to make now, at night, or
    after what waits. A video waiting for them already, or one without sound, is passed over."""
    if body.when != "after":
        queue.plan(body.when)  # before they join: the worker never sees the old schedule
        queue.resume()
    return Added(added=queue.add_subtitles(body.file_ids, body.quality, body.language, body.title))


@router.post("/subtitles/batches/{batch_id}/take-away")
def take_away(batch_id: int, conn: Database, scans: Scans) -> TakenAway:
    """Sets aside the subtitles a batch made that are there as Maku wrote them, to the
    quarantine, as a tidy-up History can undo."""
    try:
        with scans.hold():
            plan_id = subtitles.take_away(conn, batch_id, now=datetime.now().astimezone())
    except LookupError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None
    except ScanBusyError as busy:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{busy} Take them away once that's done."
        ) from None
    return TakenAway(plan_id=plan_id)
