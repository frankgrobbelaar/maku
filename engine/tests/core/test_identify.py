"""Which series or film a file is: grouping files, and scoring TMDB's shows and films."""

from dataclasses import replace
from datetime import date
from pathlib import PureWindowsPath

from maku.core.catalog import Entry, film_entry, show_entry
from maku.core.identify import (
    SURE,
    FileFacts,
    group_files,
    guesses,
    merged,
    normalize,
    respelled,
    searches,
    similarity,
    spelled_out,
)
from maku.core.names import parse_name
from tests.services import ASCENT, HARBOUR, LANTERN, ORCHARD, QUIET, STARFALL, STARFALL_II
from tests.tmdb_data import movie_details, tv_details


def show(details: dict[str, object]) -> Entry:
    entry = show_entry(details)
    assert entry is not None
    return entry


def film(details: dict[str, object]) -> Entry:
    entry = film_entry(details)
    assert entry is not None
    return entry


def facts(path: str, minutes: float | None = 45.0, number: int = 0) -> FileFacts:
    where = PureWindowsPath(path)
    return FileFacts(number, where, parse_name(where), minutes)


def test_files_named_alike_are_looked_up_together():
    found = group_files(
        [
            facts(r"D:\Videos\Glass Orchard\Glass Orchard - S01E01.mkv", number=1),
            facts(r"D:\Videos\Downloads\Glass.Orchard.S01E02.720p.HDTV.x264-GRP.mkv", number=2),
            facts(r"D:\Videos\Downloads\The.Harbour.Line.S02E05.1080p.WEB-DL-GRP.mkv", number=3),
        ]
    )

    assert [(g.query, [f.id for f in g.files]) for g in found] == [
        ("Glass Orchard", [1, 2]),
        ("The Harbour Line", [3]),
    ]


def test_a_bare_episode_takes_its_show_from_the_folder():
    [group] = group_files([facts(r"D:\Videos\Quiet Hours (2015)\Season 01\05.mkv")])

    assert (group.query, group.year) == ("Quiet Hours", 2015)


def test_films_are_looked_up_apart_from_episodes():
    found = group_files(
        [
            facts(r"D:\Videos\Starfall\Starfall - S01E01.mkv"),
            facts(r"D:\Videos\Movies\Starfall (2008).mkv", minutes=118),
        ]
    )

    assert [(g.query, g.movie) for g in found] == [("Starfall", False), ("Starfall", True)]


def test_films_of_one_name_and_another_year_are_looked_up_apart():
    found = group_files(
        [
            facts(r"D:\Videos\Movies\Starfall (2008).mkv", minutes=118, number=1),
            facts(r"D:\Videos\Movies\Starfall.2027.2160p.WEB-DL-GRP.mkv", minutes=120, number=2),
            facts(r"D:\Videos\Movies\Starfall (2008) CD2.mkv", minutes=60, number=3),
        ]
    )

    assert [(g.query, g.year, [f.id for f in g.files]) for g in found] == [
        ("Starfall", 2008, [1, 3]),
        ("Starfall", 2027, [2]),
    ]


def test_extras_and_dvd_files_arent_looked_up():
    found = group_files(
        [
            facts(r"D:\Videos\Movies\Starfall (2008)\Sample\starfall-sample.mkv"),
            facts(r"D:\Videos\Burnt\VIDEO_TS\VTS_02_1.VOB"),
        ]
    )

    assert found == []


def test_a_show_with_its_name_and_episodes_is_sure():
    [group] = group_files(
        [facts(rf"D:\Videos\Glass Orchard (2012)\Glass Orchard - {n:03}.mkv") for n in (1, 25)]
    )

    best = guesses(group, [show(ORCHARD), show(HARBOUR)])[0]

    assert best.entry.title == "Glass Orchard"
    assert best.confidence >= SURE
    assert best.reasons == (
        "Title matches",
        "2012 fits",
        "25 episodes fit",
        "45 min fits",
    )


def test_more_episodes_than_a_finished_show_has_count_against_it():
    [group] = group_files([facts(r"D:\Videos\Glass Orchard\Glass Orchard - 040.mkv")])

    best = guesses(group, [show(ORCHARD)])[0]

    assert "Only 25 episodes, files go up to 40" in best.reasons
    assert best.confidence < SURE


def test_a_film_file_matches_the_film_not_a_show_of_its_name():
    [group] = group_files([facts(r"D:\Videos\Movies\The Lantern Keeper (2016).mkv", minutes=104)])
    lantern_show = show(tv_details(5501, "The Lantern Keeper", (6,), first_aired=date(1998, 1, 4)))

    found = guesses(group, [lantern_show, film(LANTERN)])

    assert [guess.entry.id for guess in found] == [-7201]  # the show isn't worth offering
    assert found[0].confidence >= SURE
    assert found[0].reasons == (
        "Title matches",
        "2016 fits",
        "A film, like the file",
        "104 min fits",
    )


def test_an_episode_file_matches_the_show_not_a_film_of_its_name():
    [group] = group_files([facts(r"D:\Videos\Starfall\Starfall - S01E02.mkv")])
    starfall_show = show(tv_details(5502, "Starfall", (8,), first_aired=date(2019, 1, 6)))

    best = guesses(group, [film(STARFALL), starfall_show])[0]

    assert best.entry.id == 5502


def test_a_remake_loses_on_its_year():
    [group] = group_files([facts(r"D:\Videos\Movies\Starfall (2008).mkv", minutes=118)])
    remake = film(movie_details(7999, "Starfall", date(2027, 3, 1), 121))

    found = guesses(group, [remake, film(STARFALL)])

    assert found[0].entry.id == -7101
    assert "From 2027, not 2008" in found[1].reasons


def test_a_film_named_as_its_collections_first_is_the_first():
    [group] = group_files([facts(r"D:\Videos\Movies\Starfall.mkv", minutes=118)])

    found = guesses(group, [film(STARFALL), film(STARFALL_II), film(ASCENT)])

    assert (found[0].entry.id, found[0].confidence >= SURE) == (-7101, True)
    assert all(guess.confidence < SURE for guess in found[1:])


def test_a_film_in_two_parts_is_as_long_as_both_together():
    [group] = group_files(
        [facts(rf"D:\Videos\Movies\Starfall (2008) CD{part}.avi", 59, part) for part in (1, 2)]
    )

    best = guesses(group, [film(STARFALL)])[0]

    assert (best.entry.id, best.confidence >= SURE) == (-7101, True)
    assert "118 min fits" in best.reasons


def test_the_wrong_year_counts_against_a_guess():
    right = group_files([facts(r"D:\Videos\Glass Orchard (2012)\Glass Orchard - S01E01.mkv")])[0]
    wrong = group_files([facts(r"D:\Videos\Glass Orchard (2021)\Glass Orchard - S01E01.mkv")])[0]
    orchard = [show(ORCHARD)]

    assert guesses(right, orchard)[0].confidence > guesses(wrong, orchard)[0].confidence
    assert "From 2012, not 2021" in guesses(wrong, orchard)[0].reasons


def test_a_length_far_from_the_entrys_counts_against_it():
    short = group_files([facts(r"D:\Videos\Glass Orchard\Glass Orchard - S01E01.mkv", 4)])[0]

    best = guesses(short, [show(ORCHARD)])[0]

    assert "4 min, not 45" in best.reasons


def test_specials_from_after_their_series_began_still_fit_it():
    group = group_files(
        [
            facts(r"D:\Videos\Quiet Hours\Specials\Quiet Hours (2016) - S00E02.mkv", minutes=60),
        ]
    )[0]

    best = guesses(group, [show(QUIET)])[0]

    # A special's year and length are its own, not its series' episodes'.
    assert best.confidence >= SURE
    assert not [reason for reason in best.reasons if reason.startswith(("From", "60 min"))]


def test_a_series_is_looked_up_by_its_name_alone():
    [group] = group_files([facts(r"D:\Videos\Glass Orchard\Glass Orchard - S01E01.mkv")])

    assert searches(group) == ["Glass Orchard"]


def test_a_name_with_another_in_brackets_is_looked_up_by_either():
    [group] = group_files([facts(r"D:\Videos\La Ligne du Port (The Harbour Line) - S01E01.mkv")])

    assert searches(group) == [
        "La Ligne du Port (The Harbour Line)",
        "La Ligne du Port",
        "The Harbour Line",
    ]


def test_a_name_that_is_a_titles_main_part_fits_it_nearly_as_well():
    [group] = group_files([facts(r"D:\Videos\Movies\Starfall Ascent (2015).mkv", minutes=131)])

    best = guesses(group, [film(ASCENT)])[0]

    assert best.confidence >= SURE


def test_guesses_from_several_lookups_keep_each_entry_at_its_surest():
    [group] = group_files([facts(r"D:\Videos\Glass Orchard\Glass Orchard - S01E01.mkv")])
    found = guesses(group, [show(ORCHARD), show(HARBOUR)])
    lower = [replace(guess, confidence=guess.confidence - 10) for guess in found]

    together = merged(lower, found)

    assert [guess.confidence for guess in together] == [guess.confidence for guess in found]


def test_a_name_tmdb_writes_otherwise_is_put_its_way():
    found = [show(HARBOUR)]  # what TMDB finds for "Harbourline": "The Harbour Line"

    assert respelled("Harbourline", found) == "harbour line"
    assert respelled("Harbour Line", found) is None  # nothing to put otherwise
    assert respelled("Mystery Show", found) is None


def test_only_a_series_initials_are_written_out():
    assert spelled_out("HL Christmas", "The Harbour Line") is None  # "The" starts it
    assert spelled_out("GO Finale", "Glass Orchard") == "Glass Orchard Finale"
    assert spelled_out("Go Finale", "Glass Orchard") is None  # initials are capitals
    assert spelled_out("GOX Finale", "Glass Orchard") is None  # more than the series has


def test_names_compare_without_case_punctuation_or_apostrophes():
    curly = f"Starfall: The Keeper{chr(0x2019)}s Daughter"
    assert normalize(curly) == "starfall the keepers daughter"
    assert normalize("Amélie & Co") == "amelie and co"
    assert similarity("Starfall: Ascent", "Starfall Ascent") == 1.0
    assert similarity("Orchard", "Glass Orchard") >= 0.45
    assert similarity("Starfall", "Starfall II") < 1.0
    assert similarity("", "Anything") == 0.0
