"""What a title's About panel says: its synopsis, genres, studio, where it stands, when it aired
and how long an episode lasts, from what TMDB says of it: as kept with the title and its episode
list, and as kept of its entry (maku/identify.py), which fills in what the other doesn't say.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from maku.core.catalog import Status


@dataclass(frozen=True)
class Said:
    """What one record says of a title (or nothing, for one it doesn't know)."""

    overview: str | None = None
    genres: tuple[str, ...] = ()
    studio: str | None = None
    status: Status | None = None
    started: date | None = None
    ended: date | None = None
    minutes: int | None = None


@dataclass(frozen=True)
class About:
    overview: str | None
    genres: tuple[str, ...]
    studio: str | None
    status: Status | None
    started: date | None  # its first episode, or the film's release
    ended: date | None  # its latest episode so far: None for a film, or while unknown
    minutes: int | None  # an episode's usual length, or the film's


def about(title: Said, entry: Said | None, episode_minutes: Iterable[int | None] = ()) -> About:
    """A title's About panel, from what its own row says and what's kept of its entry, if Maku
    has asked. An episode's length, when neither says, is the one most of its episodes last."""
    other = entry or Said()
    lengths = Counter(minutes for minutes in episode_minutes if minutes)
    usual = lengths.most_common(1)[0][0] if lengths else None
    return About(
        overview=title.overview or other.overview,
        genres=title.genres or other.genres,
        studio=title.studio or other.studio,
        status=title.status or other.status,
        started=title.started or other.started,
        ended=title.ended or other.ended,
        minutes=title.minutes or usual or other.minutes,
    )
