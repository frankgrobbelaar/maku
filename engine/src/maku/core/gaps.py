"""Which episodes a show is missing: the ones TMDB lists as aired that no file in the library holds.

Specials (season 0) are listed apart and never count as missing, and episodes still to air
aren't missing either. A finished show's episodes all count as aired, dated or not.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from maku.core.catalog import Episode, Show


@dataclass(frozen=True)
class SeasonCount:
    season: int
    present: int
    aired: int  # out of these
    total: int  # with the ones still to air


@dataclass(frozen=True)
class Gaps:
    missing: tuple[Episode, ...]  # aired, in a numbered season, and not in the library
    specials_missing: tuple[Episode, ...]  # season 0: listed apart, never counted as missing
    upcoming: tuple[Episode, ...]  # not aired yet
    seasons: tuple[SeasonCount, ...]  # the numbered seasons

    @property
    def present(self) -> int:
        return sum(season.present for season in self.seasons)

    @property
    def aired(self) -> int:
        return sum(season.aired for season in self.seasons)


def find_gaps(show: Show, held: Iterable[tuple[int, int, int | None]], today: date) -> Gaps:
    """`held` is where each file sits: (season, first episode, last episode or None)."""
    covered: set[tuple[int, int]] = set()
    for season, first, last in held:
        covered.update((season, number) for number in range(first, (last or first) + 1))

    def aired(episode: Episode) -> bool:
        if episode.aired is None:
            return not show.airing
        return episode.aired <= today

    missing: list[Episode] = []
    specials: list[Episode] = []
    upcoming: list[Episode] = []
    counts: list[SeasonCount] = []
    for number in show.seasons:
        episodes = show.season(number)
        out = [episode for episode in episodes if aired(episode)]
        upcoming.extend(episode for episode in episodes if not aired(episode))
        gone = [episode for episode in out if (number, episode.number) not in covered]
        missing.extend(gone)
        have = sum(1 for episode in episodes if (number, episode.number) in covered)
        counts.append(SeasonCount(number, have, len(out), len(episodes)))
    specials.extend(
        episode
        for episode in show.season(0)
        if aired(episode) and (0, episode.number) not in covered
    )
    return Gaps(tuple(missing), tuple(specials), tuple(upcoming), tuple(counts))
