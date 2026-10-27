"""Where the owner is in each title: a video stopped part way picks up where it stopped, and one
seen to its last tenth counts as watched, with the one after it up next. Pure: maku/watched.py
keeps the record."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass

WATCHED = 0.9  # seen this far through, a video counts as watched: what's left is mostly credits
STARTED = 30.0  # seconds: stopped sooner than this, a video starts from the top again


def seen(position: float, duration: float | None) -> bool:
    """Seen to its last tenth: watched."""
    return duration is not None and duration > 0 and position >= duration * WATCHED


def resume_at(position: float, duration: float | None) -> float | None:
    """Where a video picks up: where it stopped, unless that was near its start or its end."""
    if position < STARTED or seen(position, duration):
        return None
    return position


@dataclass(frozen=True)
class Video:
    """One of a title's videos, as the order of watching sees it."""

    id: int
    season: int | None  # 0 for a special, None for a file without one
    episode: int | None
    path: str


def following(videos: Sequence[Video], video: Video) -> list[Video]:
    """What plays after a video, as a title's page plays them: the rest of its season and the
    seasons after it, for an episode; the specials after it, for a special; and the files
    without a season after it, for one of those."""
    group = _group(video)
    same = sorted((each for each in videos if _group(each) == group), key=_order)
    return same[same.index(video) + 1 :] if video in same else []


def up_next(videos: Sequence[Video], video: Video, watched: Collection[int]) -> Video | None:
    """The video to watch after this one: the first of those that follow it not watched yet."""
    return next((each for each in following(videos, video) if each.id not in watched), None)


def furthest(videos: Sequence[Video]) -> Video:
    """Of videos played at the same moment (a season marked watched), the one furthest in."""
    return max(videos, key=lambda video: (_group(video) == "season", _order(video)))


def _group(video: Video) -> str:
    if video.season is None:
        return "other"
    return "special" if video.season == 0 else "season"


def _order(video: Video) -> tuple[int, int, str]:
    return (video.season or 0, video.episode or 0, video.path)
