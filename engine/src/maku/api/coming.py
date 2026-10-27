"""What's still to come of the library's shows (maku/coming.py): Home's "Coming up"."""

from datetime import datetime

from fastapi import APIRouter

from maku import artwork, coming
from maku.api.common import ApiModel, Database
from maku.core.catalog import TitleKind

router = APIRouter()


class ComingEpisode(ApiModel):
    """A title's next episode, and how many more its list has after it."""

    title_id: int
    title: str
    kind: TitleKind
    has_poster: bool
    season: int
    number: int
    name: str | None
    aired: str  # the day it airs
    later: int  # episodes listed after it


@router.get("/coming")
def coming_up(conn: Database) -> list[ComingEpisode]:
    """Each of the library's titles with an episode airing today or later that the library hasn't
    got: its next one, the soonest first."""
    today = datetime.now().astimezone().date()
    return [
        ComingEpisode(
            title_id=each.title_id,
            title=each.title,
            kind=each.kind,
            has_poster=artwork.poster_address(each.poster) is not None,
            season=each.season,
            number=each.number,
            name=each.name,
            aired=each.aired.isoformat(),
            later=each.later,
        )
        for each in coming.coming(conn, today)
    ]
