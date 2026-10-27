"""Missing episodes: what TMDB lists as aired that the library doesn't hold."""

from collections.abc import Sequence
from datetime import date

from maku.core.catalog import Episode, Show, show
from maku.core.gaps import SeasonCount, find_gaps
from tests.services import HARBOUR, ORCHARD, QUIET

TODAY = date(2026, 10, 11)


def tmdb_show(details: dict[str, object]) -> Show:
    found = show(details)
    assert found is not None
    return found


GLASS_ORCHARD = tmdb_show(ORCHARD)  # finished: seasons of 12 and 13
QUIET_HOURS = tmdb_show(QUIET)  # finished: a season of 6, and two specials
HARBOUR_LINE = tmdb_show(HARBOUR)  # seasons of 8, 10 and 10, the third airing now


def every_episode_but(
    seasons: Sequence[int], *left_out: tuple[int, int]
) -> list[tuple[int, int, int | None]]:
    return [
        (season, number, None)
        for season, size in enumerate(seasons, start=1)
        for number in range(1, size + 1)
        if (season, number) not in left_out
    ]


def test_episodes_the_library_lacks_are_missing():
    held = every_episode_but((12, 13), (1, 5), (1, 6), (2, 1), (2, 13))

    gaps = find_gaps(GLASS_ORCHARD, held, TODAY)

    assert [(e.season, e.number) for e in gaps.missing] == [(1, 5), (1, 6), (2, 1), (2, 13)]
    assert (gaps.present, gaps.aired) == (21, 25)
    assert gaps.seasons == (SeasonCount(1, 10, 12, 12), SeasonCount(2, 11, 13, 13))


def test_specials_are_listed_apart_and_never_count_as_missing():
    gaps = find_gaps(QUIET_HOURS, every_episode_but((6,)), TODAY)

    assert gaps.missing == ()
    assert [(e.season, e.number) for e in gaps.specials_missing] == [(0, 1), (0, 2)]


def test_a_file_with_two_episodes_covers_both():
    held = [*every_episode_but((12, 13), (1, 1), (1, 2)), (1, 1, 2)]

    assert find_gaps(GLASS_ORCHARD, held, TODAY).missing == ()


def test_episodes_still_to_air_arent_missing():
    # Its third season airs weekly from 21 September: episode 3 aired on 5 October, so 4 to 10
    # are still to come.
    held = [*every_episode_but((8, 10)), (3, 1, None)]

    gaps = find_gaps(HARBOUR_LINE, held, TODAY)

    assert [(e.season, e.number) for e in gaps.missing] == [(3, 2), (3, 3)]
    assert [e.number for e in gaps.upcoming] == [4, 5, 6, 7, 8, 9, 10]
    assert gaps.seasons == (
        SeasonCount(1, 8, 8, 8),
        SeasonCount(2, 10, 10, 10),
        SeasonCount(3, 1, 3, 10),
    )


def test_a_finished_shows_undated_episodes_still_count():
    undated = tuple(Episode(1, number, None, None, 24) for number in (1, 2, 3))
    old = Show(1, "Old Show", "Old Show", date(1980, 1, 1), False, None, undated)

    assert len(find_gaps(old, [], TODAY).missing) == 3


def test_an_airing_shows_undated_episodes_are_still_to_come():
    undated = tuple(Episode(1, number, None, None, 24) for number in (1, 2))
    airing = Show(2, "New Show", "New Show", None, True, None, undated)

    gaps = find_gaps(airing, [], TODAY)

    assert gaps.missing == ()
    assert len(gaps.upcoming) == 2
