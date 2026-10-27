"""Searching the library from the title bar: its series and films, their episodes and its videos."""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from maku.api.common import ApiModel, Database
from maku.core.catalog import TitleKind
from maku.search import search

router = APIRouter()


class TitleFound(ApiModel):
    id: int
    name: str
    kind: TitleKind
    year: int | None
    has_poster: bool
    also: str | None  # the other name it was found by, if not its own


class EpisodeFound(ApiModel):
    title_id: int
    title: str
    season: int  # 0 for a special
    number: int
    name: str | None
    file_id: int | None  # its video, or None when the library hasn't it
    coming: bool  # not out yet


class FileFound(ApiModel):
    file_id: int
    path: str
    title_id: int | None
    title: str | None
    season: int | None
    episode: int | None
    episode_end: int | None
    # In a title, waiting for a match, set aside as not a series or film, an extra (a sample, a
    # trailer), under no title for another reason, or still being read.
    place: Literal["title", "match", "aside", "extra", "other", "reading"]


class Found(ApiModel):
    """What a search found, each kind's closest few first, and how many it found in all."""

    titles: list[TitleFound]
    episodes: list[EpisodeFound]
    files: list[FileFound]
    total_titles: int
    total_episodes: int
    total_files: int


@router.get("/search")
def find(conn: Database, q: Annotated[str, Query(max_length=200)] = "") -> Found:
    """The library's series and films by any name they go by, their episodes by code or name,
    and its videos by their files' names: what every word of `q` finds, however it's written."""
    return Found.model_validate(asdict(search(conn, q, datetime.now().astimezone().date())))
