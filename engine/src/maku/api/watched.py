"""What the owner has watched, and where each video stopped (maku/watched.py): the player says
where it is as it plays, a video's menu marks it watched or not, and Home's "Continue watching"
goes on from the latest played."""

from datetime import UTC, datetime

from fastapi import APIRouter, status
from pydantic import Field

from maku import artwork, watched
from maku.api.common import ApiModel, Database
from maku.core.catalog import TitleKind

router = APIRouter()


class Position(ApiModel):
    position: float = Field(ge=0)  # seconds in
    duration: float | None = Field(default=None, gt=0)  # how long it plays, as the player has it


class Marked(ApiModel):
    files: list[int] = Field(min_length=1)
    watched: bool


class NextVideo(ApiModel):
    file_id: int
    season: int | None
    episode: int | None
    episode_end: int | None
    name: str | None  # its episode's, as TMDB names it
    path: str
    duration: float | None
    resume: float | None  # where Play picks it up; None for from the top


class Continuing(ApiModel):
    """A title to go on with: the video stopped part way, or the one after the last seen."""

    title_id: int
    title: str
    kind: TitleKind
    has_poster: bool
    played_at: str
    up_next: bool  # the one after the last seen, rather than one stopped part way
    video: NextVideo
    following: list[NextVideo]  # what plays after it, in order


@router.put("/files/{file_id}/position", status_code=status.HTTP_204_NO_CONTENT)
def note_position(file_id: int, body: Position, conn: Database) -> None:
    """Where a video is: the player says so as it plays, and as it stops."""
    watched.note(conn, file_id, body.position, body.duration, _now())


@router.post("/files/watched", status_code=status.HTTP_204_NO_CONTENT)
def mark_watched(body: Marked, conn: Database) -> None:
    """Videos marked watched, or not watched: either way each starts from the top next time."""
    watched.mark(conn, body.files, body.watched, _now())


@router.get("/continue")
def continue_watching(conn: Database) -> list[Continuing]:
    """The titles to go on with, the latest played first: Home's "Continue watching"."""
    return [
        Continuing(
            title_id=going.title_id,
            title=going.title,
            kind=going.kind,
            has_poster=artwork.poster_address(going.poster) is not None,
            played_at=going.played_at,
            up_next=going.up_next,
            video=_video(going.video),
            following=[_video(each) for each in going.following],
        )
        for going in watched.continuing(conn)
    ]


@router.delete("/continue/{title_id}", status_code=status.HTTP_204_NO_CONTENT)
def stop_continuing(title_id: int, conn: Database) -> None:
    """A title out of "Continue watching" till one of its videos plays again."""
    watched.forget(conn, title_id)


def _video(video: watched.Next) -> NextVideo:
    return NextVideo(
        file_id=video.file_id,
        season=video.season,
        episode=video.episode,
        episode_end=video.episode_end,
        name=video.name,
        path=video.path,
        duration=video.duration,
        resume=video.resume,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
