"""The library's shows by the day their episodes air (maku/coming.py): the Library's "Coming up"."""

from datetime import datetime

from fastapi import APIRouter

from maku import artwork, coming
from maku.api.common import ApiModel, Database
from maku.core.catalog import TitleKind

router = APIRouter()


class ComingEpisode(ApiModel):
    """A show's episodes of one season out on one day (one, or a season put out at once), and how
    many of them the library has."""

    title_id: int
    title: str
    kind: TitleKind
    has_poster: bool
    season: int  # 0 for its specials
    number: int  # the first of them
    last: int  # the last of them: the first, for one
    name: str | None  # the episode's own, for one
    aired: str  # the day they air
    episodes: int
    held: int  # of them, in the library


@router.get("/coming")
def coming_up(conn: Database) -> list[ComingEpisode]:
    """The episodes of the library's shows out in the last four weeks or listed from today on, by
    the day they air, each day's saying how many of them the library has."""
    today = datetime.now().astimezone().date()
    return [
        ComingEpisode(
            title_id=each.title_id,
            title=each.title,
            kind=each.kind,
            has_poster=artwork.poster_address(each.poster) is not None,
            season=each.season,
            number=each.number,
            last=each.last,
            name=each.name,
            aired=each.aired.isoformat(),
            episodes=each.episodes,
            held=each.held,
        )
        for each in coming.coming(conn, today)
    ]
