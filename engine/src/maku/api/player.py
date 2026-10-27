"""Playing a video inside Maku's window (maku/player.py): opening it, its subtitles getting ready,
the stream itself, and closing it.

The stream is the one address the window asks for without the token: its <video> can't send
one, so the ticket that opening a video gives stands in for it (`streams`, which create_app
includes without the token's check).
"""

import json
import sqlite3
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from maku.api.common import ApiModel, Database
from maku.core.fields import Json
from maku.core.player import Playable
from maku.player import Player, PlayerError, State, UnknownTicketError
from maku.subtitles import is_made

router = APIRouter()
streams = APIRouter()  # no token: each stream's ticket is its key


class SoundTrack(ApiModel):
    number: int
    language: str | None  # "jpn"
    title: str | None  # the file's name for it
    channels: int
    default: bool  # the file's own pick


class SubtitleTrack(ApiModel):
    number: int
    language: str | None
    title: str | None
    kind: Literal["text", "styled", "pictures"]  # styled: as the file styles them
    default: bool
    forced: bool
    beside: bool  # a file of its own beside the video
    made: bool  # English subtitles Maku made from the sound (names and jokes can be off)


class ChapterMark(ApiModel):
    start: float  # seconds
    title: str | None


class OpenVideo(ApiModel):
    file: int


class Opened(ApiModel):
    ticket: str | None  # None when the file isn't there to play
    missing: Literal["drive", "file"] | None  # its drive isn't connected, or the file went
    drive: str  # "F:"
    duration: float | None
    sound: list[SoundTrack]
    subtitles: list[SubtitleTrack]
    chapters: list[ChapterMark]
    chosen_sound: int | None  # what the file starts with
    chosen_subtitles: int | None
    ready: list[int]  # subtitles ready to draw in now


class SubtitleProblem(ApiModel):
    number: int
    problem: str


class Stopped(ApiModel):
    why: Literal["drive", "gone", "damaged", "failed"]
    detail: str | None  # what ffmpeg said last


class PlayerState(ApiModel):
    ready: list[int]  # subtitles ready to draw in
    preparing: list[int]  # subtitles being copied out of the file
    failed: list[SubtitleProblem]
    stopped: Stopped | None  # why the latest stream ended early


@router.post("/player")
def open_video(body: OpenVideo, conn: Database, request: Request) -> Opened:
    """Opens a video to play: a ticket for its stream, with its sound, subtitles and chapters.
    A video whose drive isn't connected, or that went, has no ticket, and says which."""
    row = conn.execute(
        """SELECT f.path, f.probe, m.name AS made, m.size AS made_size,
                  m.modified AS made_modified
           FROM files AS f LEFT JOIN made_subtitles AS m ON m.file_id = f.id
           WHERE f.id = ? AND f.gone_at IS NULL""",
        (body.file,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That video isn't in the library any more.")
    path = Path(row["path"])
    drive = path.drive
    if not path.is_file():
        missing = "drive" if not Path(path.anchor).exists() else "file"
        return Opened(
            ticket=None,
            missing=missing,
            drive=drive,
            duration=None,
            sound=[],
            subtitles=[],
            chapters=[],
            chosen_sound=None,
            chosen_subtitles=None,
            ready=[],
        )
    if row["probe"] is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Maku hasn't read this video yet. Play it once a scan has."
        )
    player: Player = request.app.state.player
    try:
        opened = player.open(path, _report(row["probe"]))
    except PlayerError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from None
    return Opened(
        ticket=opened.ticket,
        missing=None,
        drive=drive,
        duration=opened.playable.duration,
        sound=_sound(opened.playable),
        subtitles=_subtitles(opened.playable, _made(path, row)),
        chapters=[ChapterMark(start=c.start, title=c.title) for c in opened.playable.chapters],
        chosen_sound=opened.sound,
        chosen_subtitles=opened.subtitles,
        ready=list(player.state(opened.ticket).ready),
    )


@router.get("/player/{ticket}")
def video_state(ticket: str, request: Request) -> PlayerState:
    """How the open video's subtitles are getting on, and why its stream stopped if it did."""
    return _state(lambda player: player.state(ticket), request)


@router.post("/player/{ticket}/subtitles/{number}")
def prepare_subtitles(ticket: str, number: int, request: Request) -> PlayerState:
    """Gets subtitles ready to draw in: text in the file is copied out of it first, which reads
    the whole file."""
    return _state(lambda player: player.prepare(ticket, number), request)


@router.delete("/player/{ticket}", status_code=status.HTTP_204_NO_CONTENT)
def close_video(ticket: str, request: Request) -> None:
    """Closes the video: its stream stops, and so does any copy of its subtitles."""
    player: Player = request.app.state.player
    player.close(ticket)


@streams.get(
    "/stream/{ticket}",
    response_class=StreamingResponse,
    responses={200: {"content": {"video/mp4": {}}}},
)
async def stream(
    ticket: str,
    request: Request,
    at: Annotated[float, Query(ge=0)] = 0,
    sound: int | None = None,
    subtitles: int | None = None,
) -> StreamingResponse:
    """The open video from `at` seconds, as fragmented MP4 the window plays as it comes: the
    `sound` track in stereo, and the `subtitles` drawn in once they're ready. The ticket is the
    key: no token. A new stream of the same video stops this one."""
    player: Player = request.app.state.player
    chunks = player.stream(ticket, at=at, sound=sound, subtitles=subtitles)
    try:
        first = await anext(chunks)
    except UnknownTicketError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None
    except (PlayerError, StopAsyncIteration) as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(error) or "It won't play."
        ) from None

    async def body() -> AsyncIterator[bytes]:
        try:
            yield first
            async for chunk in chunks:
                yield chunk
        finally:
            await chunks.aclose()

    return StreamingResponse(body(), media_type="video/mp4", headers={"Cache-Control": "no-store"})


def _state(ask: Callable[[Player], State], request: Request) -> PlayerState:
    player: Player = request.app.state.player
    try:
        found = ask(player)
    except UnknownTicketError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None
    except PlayerError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    return PlayerState(
        ready=list(found.ready),
        preparing=list(found.preparing),
        failed=[SubtitleProblem(number=n, problem=why) for n, why in found.failed],
        stopped=Stopped(why=found.stopped.why, detail=found.stopped.detail)
        if found.stopped
        else None,
    )


def _sound(found: Playable) -> list[SoundTrack]:
    return [
        SoundTrack(
            number=track.number,
            language=track.language,
            title=track.title,
            channels=track.channels,
            default=track.default,
        )
        for track in found.sound
    ]


def _subtitles(found: Playable, made: Path | None) -> list[SubtitleTrack]:
    return [
        SubtitleTrack(
            number=track.number,
            language=track.language,
            title=track.title,
            kind=track.kind,
            default=track.default,
            forced=track.forced,
            beside=track.beside is not None,
            made=made is not None and track.beside is not None and Path(track.beside) == made,
        )
        for track in found.subtitles
    ]


def _made(video: Path, row: sqlite3.Row) -> Path | None:
    """The English subtitles Maku made for the video, when they're beside it as it wrote them."""
    name: str | None = row["made"]
    if name and is_made(video, name, row["made_size"], row["made_modified"]):
        return video.with_name(video.stem + name)
    return None


def _report(probe: str) -> Json:
    found: Json = json.loads(probe)
    return found
