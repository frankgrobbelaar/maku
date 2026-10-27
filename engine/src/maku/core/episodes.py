"""Episode numbering: seasons and episodes, and the absolute numbers some releases use.

A show's shape is its season sizes, first season first: The Harbour Line is (8, 10, 10).
Specials (season 0) sit outside the absolute numbering.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class EpisodeNumber:
    season: int
    episode: int
    absolute: int

    @property
    def code(self) -> str:
        return f"S{self.season:02d}E{self.episode:02d}"


def to_absolute(season_sizes: Sequence[int], season: int, episode: int) -> int | None:
    if not 1 <= season <= len(season_sizes) or not 1 <= episode <= season_sizes[season - 1]:
        return None
    return sum(season_sizes[: season - 1]) + episode


def to_season_episode(season_sizes: Sequence[int], absolute: int) -> tuple[int, int] | None:
    if absolute < 1:
        return None
    for season, size in enumerate(season_sizes, start=1):
        if absolute <= size:
            return season, absolute
        absolute -= size
    return None


def all_episodes(season_sizes: Sequence[int]) -> list[EpisodeNumber]:
    episodes: list[EpisodeNumber] = []
    for season, size in enumerate(season_sizes, start=1):
        for episode in range(1, size + 1):
            episodes.append(EpisodeNumber(season, episode, len(episodes) + 1))
    return episodes
