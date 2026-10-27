"""Choosing a title's poster (maku/posters.py): what there is to choose from, and the choice."""

from fastapi import APIRouter, HTTPException, Request, status

from maku import credentials, posters
from maku.api.common import ApiModel, Database, Paths, Web
from maku.artwork import poster_address
from maku.cache import Cache
from maku.care import Care
from maku.tmdb import Tmdb

router = APIRouter()


class PosterOption(ApiModel):
    poster: str  # what's kept: TMDB's image path
    address: str  # where the picture is, to show it (GET /artwork?address=)
    language: str | None  # "en"; None for one without words
    width: int | None
    height: int | None


class PosterChoices(ApiModel):
    found: str | None  # the poster TMDB gave it
    chosen: str | None  # the owner's, when they chose one
    options: list[PosterOption]  # the one it has first
    problem: str | None  # why TMDB's couldn't be asked for now


class Chosen(ApiModel):
    poster: str | None  # None: back to the one TMDB gave it


@router.get("/titles/{title_id}/posters")
def poster_choices(title_id: int, conn: Database, paths: Paths, web: Web) -> PosterChoices:
    """The posters TMDB has of a title, to choose from (with the owner's key)."""
    key = credentials.load(paths, "tmdb")
    tmdb = Tmdb(key, web, cache=Cache(paths.cache)) if key else None
    found = posters.choices(conn, title_id, tmdb)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Maku has no such title.")
    return PosterChoices(
        found=found.found,
        chosen=found.chosen,
        options=[
            PosterOption(
                poster=each.poster,
                address=poster_address(each.poster) or "",
                language=each.language,
                width=each.width,
                height=each.height,
            )
            for each in found.options
        ],
        problem=found.problem,
    )


@router.put("/titles/{title_id}/poster", status_code=status.HTTP_204_NO_CONTENT)
def choose_poster(title_id: int, body: Chosen, conn: Database, request: Request) -> None:
    """Keeps the owner's choice of poster, or goes back to the one found. The poster next to the
    show follows, when the owner has those."""
    if not posters.choose(conn, title_id, body.poster):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That isn't a poster from TMDB.")
    care: Care = request.app.state.care
    care.wake()  # the poster next to the show, written anew
