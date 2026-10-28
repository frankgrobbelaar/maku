"""Where a file sits in a TMDB show: numbered by season, counted straight through, a daily show's
by the day it aired, or a special by its name or the day its own entry began."""

from dataclasses import replace
from datetime import date
from pathlib import PureWindowsPath
from typing import cast

import pytest

from maku.core.catalog import Entry, Show, TitleKind, show, show_entry
from maku.core.identify import FileFacts
from maku.core.names import Kind, ParsedName, parse_name
from maku.core.placing import (
    How,
    Placement,
    lists_special,
    named_special,
    numbered_through,
    place,
)
from tests.services import HARBOUR, ORCHARD
from tests.tmdb_data import tv_details


def tmdb_show(details: dict[str, object]) -> Show:
    found = show(details)
    assert found is not None
    return found


def whole(details: dict[str, object]) -> Entry:
    """A TMDB show as the entry its files match: the whole of it, from its first episode."""
    entry = show_entry(details)
    assert entry is not None
    return entry


def entry_for(name: str, start: date, episodes: int) -> Entry:
    """A special's own entry, as a film: the day it first aired and how many episodes it has say
    which of the show's specials it is."""
    return Entry(
        id=0,
        title=name,
        titles=(name,),
        kind=TitleKind.MOVIE,
        episodes=episodes,
        minutes=None,
        start=start,
        end=None,
        airing=False,
        cover=None,
        related=(),
    )


# The Harbour Line: seasons of 8, 10 and 10 episodes, and a special.
LINE = tmdb_show(HARBOUR)

# Glass Orchard: two seasons, no specials.
ORCHARD_SHOW = tmdb_show(ORCHARD)

# Coldwater Bay with its specials in season 0: the first aired the day the show began, the
# second on 26 June 2016, the third years on.
COLDWATER_DETAILS = tv_details(
    5103,
    "Coldwater Bay",
    (12,),
    first_aired=date(2016, 1, 10),
    specials=3,
    special_dates=(date(2016, 1, 10), date(2016, 6, 26), date(2022, 12, 21)),
)
COLDWATER = tmdb_show(COLDWATER_DETAILS)
SUMMER_SPECIAL = entry_for("Coldwater Bay: Summer Special", date(2016, 6, 26), 1)


def placed(path: str, where: Show, entry: Entry | None = None) -> Placement | None:
    return place(parse_name(PureWindowsPath(path)), where, entry)


def test_a_number_counted_straight_through_finds_its_season():
    # 8 + 10 = 18 episodes in seasons 1 and 2: episode 20 is season 3's second.
    assert placed(r"D:\Videos\The Harbour Line\The Harbour Line - 020.mkv", LINE) == Placement(
        3, 2, None, How.STRAIGHT
    )
    assert placed(r"D:\Videos\[Group] Harbour Line - 001 [480p].mkv", LINE) == Placement(
        1, 1, None, How.STRAIGHT
    )
    assert placed(r"D:\Videos\The Harbour Line\The Harbour Line - 028.mkv", LINE) == Placement(
        3, 10, None, How.STRAIGHT
    )


def test_a_number_past_the_last_episode_isnt_placed():
    assert placed(r"D:\Videos\The Harbour Line\The Harbour Line - 029.mkv", LINE) is None


def test_a_season_and_episode_are_taken_as_they_are():
    assert placed(r"D:\Videos\The Harbour Line - S02E05 - Title.mkv", LINE) == Placement(
        2, 5, None, How.NUMBERED
    )
    assert placed(r"D:\Videos\The Harbour Line\Season 02\05.mkv", LINE) == Placement(
        2, 5, None, How.NUMBERED
    )


def test_a_name_that_says_its_season_is_numbered_within_it():
    # "S3 - 21" is season 3's 21st, which TMDB doesn't list: it waits, rather than being taken
    # for the 21st counted through the show (season 3's third), as it might be a newer one.
    assert placed(r"D:\Videos\[Group] The Harbour Line S3 - 21 [720p].mkv", LINE) is None
    assert placed(r"D:\Videos\[Group] The Harbour Line S3 - 03 [720p].mkv", LINE) == Placement(
        3, 3, None, How.NUMBERED
    )


# The Harbour Line as TMDB listed it before its third season's fifth episode: four so far.
AIRING = tmdb_show(
    tv_details(
        4101,
        "The Harbour Line",
        (8, 10, 4),
        first_aired=date(2019, 3, 4),
        status="Returning Series",
        aired={(2, 1): date(2021, 4, 5), (3, 1): date(2026, 9, 14)},
    )
)


def test_an_episode_its_season_doesnt_list_yet_isnt_counted_from_the_first_season():
    # The fifth of season 3 isn't the show's fifth, season 1's: it waits for TMDB to list it.
    assert placed(r"D:\Videos\The.Harbour.Line.S03E05.1080p.WEB-DL-GRP.mkv", AIRING) is None
    assert placed(r"D:\Videos\The.Harbour.Line.S04E01.1080p.WEB-DL-GRP.mkv", AIRING) is None
    # Nor in its season's folder: counted through the show, it never lands before that season.
    assert placed(r"D:\Videos\The Harbour Line\Season 03\05.mkv", AIRING) is None


def test_a_releases_one_folder_of_every_season_counts_straight_through():
    found = placed(r"D:\Videos\The Harbour Line\Season 1\The Harbour Line - 020.mkv", LINE)

    assert found == Placement(3, 2, None, How.STRAIGHT)


def test_a_shows_own_entry_doesnt_shift_its_numbers():
    show_itself = whole(HARBOUR)  # starts with the show's first episode

    found = placed(r"D:\Videos\The Harbour Line\The Harbour Line - S02E05.mkv", LINE, show_itself)

    assert found == Placement(2, 5, None, How.NUMBERED)


def test_a_first_episode_tmdb_gives_no_date_shifts_nothing():
    # TMDB has no day for Glass Orchard's first episode, and its second aired the day it began.
    details = tv_details(
        4102,
        "Glass Orchard",
        (12,),
        first_aired=date(2012, 1, 10),
        aired={(1, 2): date(2012, 1, 10)},
    )
    season = cast("dict[str, list[dict[str, object]]]", details["season/1"])
    season["episodes"][0]["air_date"] = None
    orchard, entry = tmdb_show(details), whole(details)

    assert placed(r"D:\Videos\Glass.Orchard.S01E01.mkv", orchard, entry) == Placement(
        1, 1, None, How.NUMBERED
    )
    assert placed(r"D:\Videos\Glass Orchard\Glass Orchard - 05.mkv", orchard, entry) == Placement(
        1, 5, None, How.STRAIGHT
    )


def aired_on(day: date) -> ParsedName:
    """A daily show's file, named by the day its episode aired ("The.Harbour.Line.2021.04.12")."""
    return ParsedName(Kind.EPISODE, title="The Harbour Line", aired=day)


def test_a_daily_shows_episode_goes_by_the_day_it_aired():
    # Season 2 aired weekly from 5 April 2021: its second on the 12th.
    assert place(aired_on(date(2021, 4, 12)), LINE) == Placement(2, 2, None, How.BY_DATE)


def test_a_day_no_episode_or_two_aired_places_nothing():
    double_bill = tmdb_show(
        tv_details(
            4101,
            "The Harbour Line",
            (8,),
            first_aired=date(2019, 3, 4),
            aired={(1, 2): date(2019, 3, 4)},  # its first two aired the same night
        )
    )

    assert place(aired_on(date(2021, 4, 13)), LINE) is None
    assert place(aired_on(date(2019, 3, 4)), double_bill) is None


def test_two_episodes_in_one_file_stay_in_one_season():
    assert placed(r"D:\Videos\The Harbour Line - 001-002.mkv", LINE) == Placement(
        1, 1, 2, How.STRAIGHT
    )
    # 8 and 9 straddle seasons 1 and 2: only the first is placed.
    assert placed(r"D:\Videos\The Harbour Line - 008-009.mkv", LINE) == Placement(
        1, 8, None, How.STRAIGHT
    )


def test_a_special_goes_to_season_zero_by_the_date_it_first_aired():
    found = placed(
        r"D:\Videos\Coldwater Bay\Coldwater Bay - Special.mkv", COLDWATER, SUMMER_SPECIAL
    )

    assert found == Placement(0, 2, None, How.BY_DATE)


def test_a_special_already_numbered_keeps_its_number():
    found = placed(r"D:\Videos\Coldwater Bay\Specials\Coldwater Bay - 03.mkv", COLDWATER)

    assert found == Placement(0, 3, None, How.NUMBERED)


def test_a_special_maku_cant_date_or_number_isnt_placed():
    assert placed(r"D:\Videos\Coldwater Bay\Coldwater Bay - Special.mkv", COLDWATER) is None
    assert placed(r"D:\Videos\Glass Orchard\Specials\Glass Orchard - 01.mkv", ORCHARD_SHOW) is None


def test_films_and_extras_arent_episodes():
    assert placed(r"D:\Videos\Coldwater Bay - The Movie (2019).mkv", COLDWATER) is None
    extra = r"D:\Videos\Coldwater Bay\Extras\Opening Titles (Creditless).mkv"
    assert placed(extra, COLDWATER) is None


def test_a_special_named_the_plex_way_keeps_its_number_whatever_its_entry():
    # The entry first aired on 26 June 2016, TMDB's S00E02; the file says S00E03.
    found = placed(
        "D:/Videos/Coldwater Bay (2016)/Specials/Coldwater Bay (2016) - S00E03.mkv",
        COLDWATER,
        SUMMER_SPECIAL,
    )

    assert found == Placement(0, 3, None, How.NUMBERED)


def test_a_series_says_nothing_about_which_special_a_file_is():
    series = whole(COLDWATER_DETAILS)  # first aired 10 January 2016, the day TMDB's S00E01 did

    assert placed("D:/Videos/Coldwater Bay/Coldwater Bay - Special.mkv", COLDWATER, series) is None


# Coldwater Bay with six of its specials, named as TMDB names them.
NAMED_DETAILS = tv_details(
    5103,
    "Coldwater Bay",
    (12,),
    first_aired=date(2016, 1, 10),
    specials=6,
    titles={
        (0, 1): "Marta - The Keeper of the Light",
        (0, 2): "Summer Holiday Special",
        (0, 3): "The Last Ferry",
        (0, 4): "Night of the Long Storm (1)",
        (0, 5): "Night of the Long Storm (2)",
        (0, 6): "Episode of Marta",
    },
)
NAMED = tmdb_show(NAMED_DETAILS)
SPECIALS = r"D:\Videos\COLDWATER BAY (2016-2022) - The COMPLETE Series\3. TV Specials (2016-2022)"


@pytest.mark.parametrize(
    ("name", "number"),
    [
        ("Coldwater Bay - Special 01 - Marta, The Keeper of the Light (2016 BluRay).mkv", 1),
        ("Coldwater Bay - Special 02a - Summer Holiday aka Series Overview (2017).mkv", 2),
        ("Coldwater Bay - Special 06 - The Last Ferry (2018 BluRay).mkv", 3),
        ("Coldwater Bay - Special 07a - Night of the Long Storm, Part 1 of 2 (2017).mkv", 4),
        ("Coldwater Bay - Special 07b - Night of the Long Storm, Part 2 of 2 (2017).mkv", 5),
        ("Coldwater Bay - Special 08 - The Episode of Marta (2021 - 1080p ENG Audio).mkv", 6),
    ],
)
def test_a_special_goes_by_its_own_name_among_the_shows_specials(name: str, number: int):
    found = placed(rf"{SPECIALS}\{name}", NAMED, whole(NAMED_DETAILS))

    assert found == Placement(0, number, None, How.BY_NAME)


@pytest.mark.parametrize(
    "name",
    [
        "Coldwater Bay - Special 02b - Summer Holiday COMMERCIALS (2017).mkv",
        "Coldwater Bay - Special 05 (Reunion) - A Keeper's Legacy (2016 DVDRip).mkv",
    ],
)
def test_a_special_whose_name_fits_none_of_the_shows_well_isnt_placed(name: str):
    assert placed(rf"{SPECIALS}\{name}", NAMED, whole(NAMED_DETAILS)) is None


def test_an_entry_found_by_a_specials_own_name_goes_by_its_names_among_the_shows():
    names = ("Coldwater Bay: Gather Round! Marta's World", "La Baie Froide : Le Monde de Marta")
    show_ = tmdb_show(
        tv_details(
            5103,
            "Coldwater Bay",
            (12,),
            first_aired=date(2016, 1, 10),
            specials=3,
            titles={
                (0, 1): "Marta",
                (0, 2): "Summer Holiday Special",
                (0, 3): "Gather Round Marta World",
            },
        )
    )

    assert named_special(names, show_) == Placement(0, 3, None, How.BY_NAME)
    assert named_special(("Coldwater Bay: Something Else",), show_) is None


def test_a_one_off_special_is_the_one_from_its_day_whatever_the_release_numbers_it():
    legacy = entry_for("Coldwater Bay: A Keeper's Legacy", date(2016, 6, 26), 1)

    found = placed(
        rf"{SPECIALS}\Coldwater Bay - Special 05 (Reunion) - A Keeper's Legacy.mkv",
        COLDWATER,
        legacy,
    )

    assert found == Placement(0, 2, None, How.BY_DATE)


def test_a_show_lists_a_special_by_the_day_it_first_aired():
    assert lists_special(COLDWATER, date(2016, 6, 27))  # a day out, as listings are
    assert not lists_special(COLDWATER, date(2016, 7, 10))
    assert not lists_special(ORCHARD_SHOW, date(2012, 1, 10))  # no specials at all


# Ember Court's first three seasons as TMDB has them, for a release's own pack.
EMBER = tmdb_show(tv_details(5105, "Ember Court", (13, 25, 25), first_aired=date(2016, 4, 3)))
EMBER_PACK = r"F:\Videos\[Group] La Cour des Braises (Ember Court)"


def ember(season: int, *numbers: int, named: str = "{n:02}") -> list[FileFacts]:
    """The pack's files in its "Season 0N" folder, each with its number as its id."""
    folder = rf"{EMBER_PACK}\[Group] Ember Court Season 0{season}"
    files: list[FileFacts] = []
    for n in numbers:
        file = PureWindowsPath(rf"{folder}\[Group] Ember Court - {named.format(n=n)}.mkv")
        files.append(FileFacts(n, file, parse_name(file), 45.0))
    return files


def test_a_season_folder_numbered_straight_through_the_show_goes_by_its_numbers():
    # Season 02 holds episodes 14 to 38: the show's 14th is its season 2's first.
    files = ember(2, *range(14, 39))

    straight = numbered_through(files, EMBER)

    assert straight == set(range(14, 39))
    first, last = (place(replace(files[i].parsed, folder_season=None), EMBER) for i in (0, -1))
    assert (first, last) == (
        Placement(2, 1, None, How.STRAIGHT),
        Placement(2, 25, None, How.STRAIGHT),
    )


def test_a_season_folder_numbered_from_one_keeps_its_season():
    assert numbered_through(ember(2, *range(1, 26)), EMBER) == set()
    assert numbered_through(ember(1, *range(1, 14)), EMBER) == set()  # the same either way


def test_a_season_folder_missing_its_first_file_still_counts_straight_through():
    # 15 to 38: past season 1's 13, and on past season 2's own 25.
    assert numbered_through(ember(2, *range(15, 39)), EMBER) == set(range(15, 39))


@pytest.mark.parametrize("first", [14, 15])
def test_a_season_folder_whose_numbers_could_be_either_keeps_its_season(first: int):
    # 14 to 25 are season 2's own numbers as well: nothing says they count straight through.
    assert numbered_through(ember(2, *range(first, 26)), EMBER) == set()


def test_a_releases_other_seasons_tell_how_it_numbers_one_that_could_be_either():
    files = [*ember(2, *range(14, 21)), *ember(3, *range(39, 46))]

    assert numbered_through(files, EMBER) == {*range(14, 21), *range(39, 46)}


def test_each_folder_tells_its_own_numbering():
    files = [*ember(2, *range(14, 39)), *ember(3, *range(1, 26))]

    assert numbered_through(files, EMBER) == set(range(14, 39))


def test_a_name_that_says_its_season_goes_by_it():
    files = ember(2, *range(14, 26), named="S02E{n:02}")

    assert numbered_through(files, EMBER) == set()
