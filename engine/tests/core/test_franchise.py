"""Which titles make one franchise: the films TMDB keeps in one collection."""

from collections.abc import Sequence
from datetime import date, timedelta

from maku.core.catalog import Episode, Show, Status, TitleKind
from maku.core.franchise import (
    Kept,
    Link,
    Member,
    franchises,
    missing,
    nearest,
    own_links,
    story_neighbours,
    taking_turns,
)

# The Starfall films' entries (TMDB's numbers, negated), and two shows'.
STARFALL, STARFALL_II, ASCENT, ORIGINS = -7101, -7102, -7103, -7104
LANTERN, HARBOUR, ORCHARD = -7201, 4101, 4102


def collection(*films: int) -> list[Link]:
    """The links each film of a collection has: the ones before it and after it."""
    return [
        Link(film, other, "PREQUEL" if at_other < at else "SEQUEL")
        for at, film in enumerate(films)
        for at_other, other in enumerate(films)
        if other != film
    ]


def test_the_films_of_a_collection_make_one_franchise():
    titles = {1: {STARFALL}, 2: {ASCENT}, 3: {HARBOUR}, 4: {LANTERN}}

    assert franchises(titles, collection(STARFALL, STARFALL_II, ASCENT)) == [[1, 2], [3], [4]]


def test_a_film_the_library_lacks_still_ties_its_neighbours():
    # Starfall II isn't in the library, but the first and third films each name it.
    titles = {1: {STARFALL}, 2: {ASCENT}}
    links = [Link(STARFALL, STARFALL_II, "SEQUEL"), Link(ASCENT, STARFALL_II, "PREQUEL")]

    assert franchises(titles, links) == [[1, 2]]


def test_franchises_keep_the_order_of_their_first_titles():
    titles = {7: {HARBOUR}, 3: {STARFALL}, 9: {ASCENT}}

    assert franchises(titles, collection(STARFALL, ASCENT)) == [[7], [3, 9]]


def test_the_rest_of_a_franchise_is_what_its_collection_ties_to_the_library():
    links = collection(STARFALL, STARFALL_II, ASCENT, ORIGINS)

    assert nearest({STARFALL_II}, story_neighbours(links)) == [
        STARFALL_II,
        STARFALL,
        ASCENT,
        ORIGINS,
    ]


def test_the_rest_of_a_franchise_stops_at_its_limit():
    neighbours = story_neighbours([Link(n, n + 1, "SEQUEL") for n in range(1, 10)])

    assert nearest({1}, neighbours, limit=3) == [1, 2, 3]
    assert nearest({5, 1}, neighbours, limit=1) == [1]


def test_the_rest_of_a_franchise_stops_at_another_franchise_the_library_has():
    neighbours = story_neighbours([Link(1, 2, "SEQUEL"), Link(2, 3, "SEQUEL")])

    assert nearest({1}, neighbours, others={3}) == [1, 2]


def test_franchises_are_tied_by_the_librarys_own_links_only():
    # What Maku looked up past the library (another film's links) ties nothing of it together.
    links = [Link(STARFALL, STARFALL_II, "SEQUEL"), Link(STARFALL_II, LANTERN, "SEQUEL")]
    titles = {1: {STARFALL}, 2: {LANTERN}}

    assert franchises(titles, own_links(links, {STARFALL, LANTERN})) == [[1], [2]]


def member(
    number: int,
    name: str,
    kind: TitleKind | None = TitleKind.MOVIE,
    start: date | None = None,
    episodes: int | None = 1,
    status: Status | None = "finished",
    names: Sequence[str] = (),
) -> Member:
    return Member(number, name, (name, *names), kind, status, start, episodes, None)


def test_missing_is_what_the_library_has_no_part_of_oldest_release_first():
    entries = [
        member(STARFALL, "Starfall", start=date(2008, 5, 2)),
        member(ORIGINS, "Starfall: Origins", start=date(2027, 11, 19), status="coming"),
        member(STARFALL_II, "Starfall II", start=date(2011, 6, 10)),
        member(-1, "Starfall: Undated"),
        member(-2, "Starfall: Never Made", start=date(2019, 1, 1), status="cancelled"),
        member(-3, "Starfall: Rumoured", kind=None),
    ]

    found = missing(entries, {STARFALL}, [], [])

    assert [e.name for e in found] == [
        "Starfall II",
        "Starfall: Origins",
        "Starfall: Undated",  # undated last
    ]
    assert (found[1].coming, found[1].airing) == (True, False)


def weekly(season: int, first: date, count: int) -> list[Episode]:
    """A season airing once a week from `first`."""
    return [
        Episode(season, n, None, first + timedelta(weeks=n - 1), 45) for n in range(1, count + 1)
    ]


def show(*episodes: Episode) -> Show:
    return Show(1, "A show", "A show", episodes[0].aired, False, None, episodes)


def test_a_film_among_a_shows_specials_counts_once_the_library_has_it():
    # TMDB keeps the show's TV film among its specials too.
    harbour = show(
        *weekly(1, date(2019, 3, 4), 2),
        Episode(0, 1, "The Harbour Line: Night Crossing", date(2020, 12, 20), 95),
    )
    night_crossing = member(-7301, "The Harbour Line: Night Crossing", start=date(2020, 12, 20))

    held = [Kept(frozenset({HARBOUR}), harbour, frozenset({(0, 1)}))]
    not_held = [Kept(frozenset({HARBOUR}), harbour, frozenset({(1, 1)}))]

    assert missing([night_crossing], {HARBOUR}, held, []) == []
    assert missing([night_crossing], {HARBOUR}, not_held, []) == [night_crossing]


def test_a_film_isnt_held_by_a_special_shown_a_fortnight_from_its_premiere():
    harbour = show(
        *weekly(1, date(2019, 3, 4), 2), Episode(0, 1, "A Special", date(2020, 7, 24), 45)
    )
    film = member(-7302, "The Harbour Line: Ebb", start=date(2020, 7, 10))

    kept = [Kept(frozenset({HARBOUR}), harbour, frozenset({(0, 1)}))]
    assert missing([film], {HARBOUR}, kept, []) == [film]


def test_franchises_take_turns_the_least_looked_up_first():
    # Five franchises waiting; the last two newly added, nothing of them looked up yet.
    waiting = [[11, 12, 13], [21, 22, 23], [31, 32, 33], [41, 42], [51]]
    looked_up = [9, 9, 9, 0, 0]

    assert taking_turns(waiting, looked_up)[:3] == [41, 51, 11]  # never behind three others
    assert taking_turns(waiting, looked_up) == [41, 51, 11, 21, 31, 42, 12, 22, 32, 13, 23, 33]
