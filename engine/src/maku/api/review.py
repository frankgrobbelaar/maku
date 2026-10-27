"""Files waiting for a match: what they are, Maku's best guesses, searching TMDB for another,
and the owner's choice (pinned, so a rescan never undoes it) or "not a series or film", which
can be taken back."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import Field

from maku import review, stills
from maku.api.common import ApiModel, CatalogClient, Database, Paths, Toolbox, Web
from maku.catalog import Catalog, NoKeyError
from maku.config import DataPaths
from maku.core.catalog import TitleKind
from maku.core.identify import Guess as FoundGuess
from maku.core.names import Kind
from maku.identify import Identifier, Placed, UnplacedError
from maku.web import Send, WebError

router = APIRouter()


class Guess(ApiModel):
    entry_id: int
    title: str
    kind: TitleKind | None
    year: int | None
    episodes: int | None
    minutes: int | None
    cover: str | None
    confidence: int  # 0 to 100
    reasons: list[str]


class IgnoredFile(ApiModel):
    id: int
    path: str
    size: int


class WaitingFile(ApiModel):
    id: int
    path: str
    size: int
    minutes: float | None
    height: int | None
    codec: str | None
    audio: list[str]
    subtitles: list[str]
    group: str | None  # the release group's tag, such as "subs"
    title: str | None  # the show's name as the file or its folder gives it
    season: int | None
    episode: int | None
    kind: Literal["episode", "special", "movie", "extra", "dvd"]
    guesses: list[Guess]
    alike: list[int]  # other waiting files beside it from the same release


class Choice(ApiModel):
    entry_id: int
    kind: Literal["episode", "movie", "special"] = "episode"
    # Other files that are the same series or film, numbered from their names.
    also: list[int] = Field(default_factory=list[int])
    # The file's number, when its name has none Maku can use.
    episode: int | None = None
    # The title whose match this changes, for every file of it (instead of `also`): the files
    # of this one's kind take `kind`, the others keep theirs.
    title: int | None = None


class Chosen(ApiModel):
    placed: int
    waiting: int  # files that didn't fit the choice, waiting for the owner now
    title_id: int | None  # where the file went


@router.get("/review")
def files_to_review(conn: Database, title: int | None = None) -> list[WaitingFile]:
    """Every file Maku couldn't place surely, folder by folder. With `title`, that title's files
    as one, to change its match: its first file, with the others alike."""
    found: list[WaitingFile] = []
    for item in review.waiting(conn) if title is None else review.of_title(conn, title):
        guesses = [Guess.model_validate(saved) for saved in item.guesses]
        found.append(
            WaitingFile(
                id=item.id,
                path=item.path,
                size=item.size,
                minutes=item.minutes,
                height=item.height,
                codec=item.codec,
                audio=list(item.audio),
                subtitles=list(item.subtitles),
                group=item.parsed.group,
                title=item.parsed.best_title,
                season=item.parsed.season
                if item.parsed.season is not None
                else item.parsed.folder_season,
                episode=item.parsed.episode,
                kind=item.parsed.kind.value,
                guesses=guesses,
                alike=list(item.alike),
            )
        )
    return found


@router.get("/review/{file_id}/search")
def search_catalog(
    file_id: int, q: str, conn: Database, paths: Paths, web: Web, catalog: CatalogClient
) -> list[Guess]:
    """TMDB's shows and films for a name, scored against this file."""
    try:
        found = _identifier(paths, web, catalog).search(conn, file_id, q)
    except NoKeyError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    except WebError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _offline(error)) from None
    return [_guess(guess) for guess in found]


@router.post("/review/{file_id}")
def choose(
    file_id: int, body: Choice, conn: Database, paths: Paths, web: Web, catalog: CatalogClient
) -> Chosen:
    """The owner's choice for this file, and for the others that are the same series or film
    (or, with `title`, every file of that title). An episode Maku can't place is 422: the owner
    gives its number."""
    identifier = _identifier(paths, web, catalog)
    try:
        if body.title is not None:
            done = identifier.rematch(
                conn, body.title, file_id, body.entry_id, Kind(body.kind), episode=body.episode
            )
        else:
            placed = identifier.choose(
                conn,
                file_id,
                body.entry_id,
                Kind(body.kind),
                also=body.also,
                episode=body.episode,
            )
            done = Placed(placed, 0)
    except UnplacedError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    except LookupError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _lost(error)) from None
    except WebError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _offline(error)) from None
    if done.placed == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That file isn't in the library any more.")
    row = conn.execute("SELECT title_id FROM files WHERE id = ?", (file_id,)).fetchone()
    return Chosen(
        placed=done.placed, waiting=done.waiting, title_id=row["title_id"] if row else None
    )


@router.get(
    "/review/{file_id}/stills/{index}",
    response_class=FileResponse,
    responses={200: {"content": {"image/jpeg": {}}}},
)
def file_still(
    file_id: int, index: int, conn: Database, paths: Paths, toolbox: Toolbox
) -> FileResponse:
    """One of three stills from the file (0, 1 or 2: 15%, 50% and 80% of the way in)."""
    row = conn.execute("SELECT path, duration FROM files WHERE id = ?", (file_id,)).fetchone()
    picture = (
        stills.still(paths, toolbox.path("ffmpeg"), Path(row["path"]), row["duration"], index)
        if row is not None
        else None
    )
    if picture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There's no still from this file.")
    return FileResponse(picture, media_type="image/jpeg")


@router.post("/review/{file_id}/ignore", status_code=status.HTTP_204_NO_CONTENT)
def ignore(file_id: int, conn: Database, paths: Paths, web: Web, catalog: CatalogClient) -> None:
    """Not a series or film: Maku leaves it out, and no rescan asks about it again."""
    _identifier(paths, web, catalog).ignore(conn, file_id)


@router.delete("/review/{file_id}/ignore", status_code=status.HTTP_204_NO_CONTENT)
def unignore(file_id: int, conn: Database, paths: Paths, web: Web, catalog: CatalogClient) -> None:
    """A series or film after all: the file waits for a match again, and the next scan looks it
    up afresh."""
    _identifier(paths, web, catalog).unignore(conn, file_id)


@router.get("/review/ignored")
def ignored_files(conn: Database) -> list[IgnoredFile]:
    """The files the owner said aren't a series or film, in name order: left where they are,
    out of the library, each to match after all or delete."""
    return [
        IgnoredFile(id=item.id, path=item.path, size=item.size) for item in review.ignored(conn)
    ]


def _identifier(paths: DataPaths, web: Send, catalog: Catalog) -> Identifier:
    return Identifier(paths, web, now=lambda: datetime.now().astimezone(), catalog=catalog)


def _guess(guess: FoundGuess) -> Guess:
    entry = guess.entry
    return Guess(
        entry_id=entry.id,
        title=entry.title,
        kind=entry.kind,
        year=entry.year,
        episodes=entry.episodes,
        minutes=entry.minutes,
        cover=entry.cover,
        confidence=guess.confidence,
        reasons=list(guess.reasons),
    )


def _lost(error: LookupError) -> str:
    if isinstance(error, NoKeyError):
        return str(error)
    if str(error).startswith("TMDB"):
        return "TMDB no longer has that show or film."
    return "That file isn't one of the title's any more. Look at the title again."


def _offline(error: WebError) -> str:
    return f"{error} Nothing was changed; try again in a moment."
