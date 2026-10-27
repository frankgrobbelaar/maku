"""Seasons and absolute numbers, on a long made-up show: Market Street's nine seasons."""

import pytest

from maku.core.episodes import EpisodeNumber, all_episodes, to_absolute, to_season_episode

MARKET_STREET = (39, 35, 33, 32, 26, 29, 25, 34, 38)  # 291 episodes in 9 seasons


@pytest.mark.parametrize(
    ("absolute", "season", "episode"),
    [(1, 1, 1), (39, 1, 39), (40, 2, 1), (118, 4, 11), (163, 5, 24), (254, 9, 1), (291, 9, 38)],
)
def test_absolute_numbers_and_seasons_convert_both_ways(absolute: int, season: int, episode: int):
    assert to_season_episode(MARKET_STREET, absolute) == (season, episode)
    assert to_absolute(MARKET_STREET, season, episode) == absolute


@pytest.mark.parametrize("absolute", [0, -3, 292])
def test_numbers_outside_the_show_have_no_place(absolute: int):
    assert to_season_episode(MARKET_STREET, absolute) is None


@pytest.mark.parametrize(("season", "episode"), [(0, 1), (10, 1), (1, 40), (2, 0)])
def test_seasons_and_episodes_outside_the_show_have_no_number(season: int, episode: int):
    assert to_absolute(MARKET_STREET, season, episode) is None


def test_every_episode_in_order():
    episodes = all_episodes(MARKET_STREET)

    assert len(episodes) == 291
    assert episodes[0] == EpisodeNumber(1, 1, 1)
    assert episodes[117] == EpisodeNumber(4, 11, 118)
    assert episodes[-1] == EpisodeNumber(9, 38, 291)
    assert episodes[117].code == "S04E11"
