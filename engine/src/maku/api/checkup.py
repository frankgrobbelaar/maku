"""The health check (maku/checkup.py): how it stands, the videos that didn't play, and what the
owner says of each: play it again now, it plays after all, or it's broken."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status

from maku import checkup
from maku.api.common import ApiModel, Database
from maku.convert import Programs

router = APIRouter()


class UnplayedVideo(ApiModel):
    file_id: int
    path: str
    title_id: int | None
    title: str | None
    season: int | None
    episode: int | None
    episode_end: int | None
    problem: str  # "It didn't play at 12:05 (…)"
    at: str | None  # when it was checked; None: it's to be played again


class Checkup(ApiModel):
    on: bool
    checked: int  # of the library's videos that play, checked within the month
    total: int
    unplayed: list[UnplayedVideo]


class Played(ApiModel):
    problem: str | None  # what went wrong, or None: it played


@router.get("/checkup")
def health_check(conn: Database) -> Checkup:
    """How the health check stands, and the videos that didn't play."""
    found = checkup.checkup(conn, _now())
    return Checkup(
        on=found.on,
        checked=found.checked,
        total=found.total,
        unplayed=[
            UnplayedVideo(
                file_id=each.file_id,
                path=each.path,
                title_id=each.title_id,
                title=each.title,
                season=each.season,
                episode=each.episode,
                episode_end=each.episode_end,
                problem=each.problem,
                at=each.at,
            )
            for each in found.unplayed
        ],
    )


@router.post("/checkup/again", status_code=status.HTTP_204_NO_CONTENT)
def check_again(conn: Database) -> None:
    """Every video is played again, from tonight."""
    checkup.again(conn)


@router.post("/files/{file_id}/check")
def check_one(file_id: int, conn: Database, request: Request) -> Played:
    """Test-plays one video now, as the night's check does."""
    programs: Programs | None = request.app.state.programs()
    if programs is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Maku can't play it till ffmpeg is here.")
    row = conn.execute(
        """SELECT id, path, duration, probe, health_problem FROM files
           WHERE id = ? AND gone_at IS NULL""",
        (file_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That video isn't in the library any more.")
    if not checkup.check(conn, programs, row, _now()):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Maku can't reach it now: is its drive connected?"
        )
    found = conn.execute("SELECT health_problem FROM files WHERE id = ?", (file_id,)).fetchone()
    return Played(problem=found["health_problem"])


@router.post("/files/{file_id}/plays", status_code=status.HTTP_204_NO_CONTENT)
def plays_after_all(file_id: int, conn: Database) -> None:
    """The owner played it and it's fine: off the list, till next month's check."""
    checkup.plays_after_all(conn, file_id, _now())


@router.post("/files/{file_id}/broken", status_code=status.HTTP_204_NO_CONTENT)
def mark_broken(file_id: int, conn: Database) -> None:
    """The owner says it's broken: from now on it's a broken file, the check saying why."""
    if not checkup.mark_broken(conn, file_id, _now()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That video isn't on the list.")


def _now() -> datetime:
    return datetime.now().astimezone()
