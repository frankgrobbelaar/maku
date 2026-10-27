"""Reading TMDB's answers: shows and films as entries, their episodes, collections and pictures."""

from datetime import date
from typing import cast

from maku.core.catalog import (
    TitleKind,
    alternative_titles,
    collection_of,
    entry_id,
    film,
    film_entry,
    hits,
    pictures,
    season_numbers,
    show,
    show_entry,
    tmdb_of,
)
from tests.services import ASCENT, ORIGINS, STARFALL, STARFALL_II
from tests.tmdb_data import collection, movie_details, movie_search, tv_details, tv_search


def test_a_show_and_a_film_never_share_an_entry():
    assert (entry_id("tv", 4101), entry_id("movie", 4101)) == (4101, -4101)
    assert (tmdb_of(4101), tmdb_of(-4101)) == (("tv", 4101), ("movie", 4101))


def test_a_show_is_an_entry_with_every_name_it_goes_by():
    details: dict[str, object] = {
        **tv_details(4101, "The Harbour Line", (8, 10), first_aired=date(2019, 3, 4)),
        "original_name": "Harbour Line",
        "alternative_titles": {
            "results": [{"title": "La Ligne du Port"}, {"title": "harbour line"}]
        },
    }

    entry = show_entry(details)

    assert entry is not None
    assert (entry.id, entry.title, entry.kind, entry.episodes) == (
        4101,
        "The Harbour Line",
        TitleKind.SERIES,
        18,
    )
    assert entry.titles == ("The Harbour Line", "Harbour Line", "La Ligne du Port")
    assert (entry.start, entry.end, entry.airing, entry.minutes) == (
        date(2019, 3, 4),
        date(2019, 7, 1),
        False,
        45,
    )
    assert (entry.cover, entry.related, entry.media) == ("/poster-4101.jpg", (), "tv")


def test_a_show_still_airing_has_no_end_yet():
    details = tv_details(
        4101, "The Harbour Line", (8,), first_aired=date(2019, 3, 4), status="Returning Series"
    )

    entry = show_entry(details)

    assert entry is not None
    assert (entry.airing, entry.end, entry.status) == (True, None, "airing")


def test_a_film_in_a_collection_knows_the_films_before_and_after_it():
    parts = collection(9101, "The Starfall Collection", STARFALL, STARFALL_II, ASCENT, ORIGINS)

    entry = film_entry(STARFALL_II, parts)

    assert entry is not None
    assert (entry.id, entry.title, entry.kind, entry.episodes, entry.minutes) == (
        -7102,
        "Starfall II",
        TitleKind.MOVIE,
        1,
        124,
    )
    assert entry.collection == "The Starfall Collection"
    assert [(r.id, r.relation, r.title) for r in entry.related] == [
        (-7101, "PREQUEL", "Starfall"),
        (-7103, "SEQUEL", "Starfall: Ascent"),
        (-7104, "SEQUEL", "Starfall: Origins"),
    ]
    assert collection_of(STARFALL_II) == 9101


def test_a_film_on_its_own_ties_to_nothing():
    details = movie_details(7201, "The Lantern Keeper", date(2016, 10, 7), 104)

    entry = film_entry(details)

    assert entry is not None
    assert (entry.related, entry.collection, collection_of(details)) == ((), None, None)


def test_a_film_being_made_is_still_to_come():
    entry = film_entry(ORIGINS)

    assert entry is not None
    assert (entry.status, entry.airing, entry.minutes) == ("coming", True, None)

    def standing(status: str) -> str | None:
        found = film({**movie_details(5, "Starfall", date(2027, 8, 1), 0), "status": status})
        return found.status if found else None

    assert [standing(s) for s in ("In Production", "Post Production", "Released")] == [
        "coming",
        "coming",
        "finished",
    ]


def test_search_results_are_read_whatever_their_kind():
    shows = hits(tv_search((4101, "The Harbour Line", date(2019, 3, 4))), "tv")
    films = hits(movie_search((7101, "Starfall", None)), "movie")

    assert [(h.id, h.media, h.title, h.year) for h in shows] == [
        (4101, "tv", "The Harbour Line", 2019)
    ]
    assert [(h.id, h.media, h.title, h.year) for h in films] == [(7101, "movie", "Starfall", None)]


def test_odd_answers_are_skipped_rather_than_crash():
    assert hits({"results": [{"id": "x"}, {"name": "No id"}, 7]}, "tv") == []
    assert show_entry({"id": 1}) is None
    assert film_entry({"title": "No id"}) is None
    assert show({}) is None


def test_a_show_has_every_episode_in_season_order():
    details = tv_details(
        4103,
        "Quiet Hours",
        (2,),
        first_aired=date(2015, 9, 1),
        specials=1,
        titles={(1, 1): "Lights Out"},
    )

    found = show(details)

    assert found is not None
    assert [(e.season, e.number, e.title) for e in found.episodes] == [
        (0, 1, "Episode 1"),
        (1, 1, "Lights Out"),
        (1, 2, "Episode 2"),
    ]
    assert (found.seasons, season_numbers(details)) == ((1,), [0, 1])


def test_a_show_still_in_production_is_airing():
    details = tv_details(
        4101, "The Harbour Line", (2,), first_aired=date(2019, 3, 4), status="Returning Series"
    )

    found = show(details)

    assert found is not None
    assert found.airing


def test_a_show_says_what_its_about_panel_shows():
    details: dict[str, object] = {
        **tv_details(4101, "The Harbour Line", (2,), first_aired=date(2019, 3, 4)),
        "overview": "A harbour pilot keeps the port's secrets.",
        "genres": [{"id": 18, "name": "Drama"}, {"id": 80, "name": "Crime"}],
        "networks": [{"name": "Northwind"}],
        "production_companies": [{"name": "Tidewater Pictures"}],
        "episode_run_time": [52],
        "last_air_date": "2019-03-11",
    }
    season = cast("dict[str, list[dict[str, object]]]", details["season/1"])
    season["episodes"][0]["overview"] = "Mara takes her first ship in."

    found = show(details)

    assert found is not None
    assert (found.overview, found.genres, found.studio) == (
        "A harbour pilot keeps the port's secrets.",
        ("Drama", "Crime"),
        "Northwind",  # where it's shown, before who made it
    )
    assert (found.status, found.last_aired, found.minutes) == ("finished", date(2019, 3, 11), 52)
    assert [episode.overview for episode in found.episodes] == [
        "Mara takes her first ship in.",
        None,
    ]


def test_an_episode_has_a_picture_from_it_when_tmdb_does():
    details = tv_details(4102, "Glass Orchard", (2,), first_aired=date(2012, 1, 10))
    season = cast("dict[str, list[dict[str, object]]]", details["season/1"])
    season["episodes"][1]["still_path"] = None

    found = show(details)

    assert found is not None
    assert [episode.still for episode in found.episodes] == ["/still-4102-1-1.jpg", None]


def test_a_status_is_said_in_makus_words():
    def standing(status: str) -> str | None:
        details = tv_details(9, "Glass Orchard", (1,), first_aired=date(2012, 1, 10), status=status)
        found = show(details)
        return found.status if found else None

    assert [standing(s) for s in ("Ended", "Canceled", "Planned", "Returning Series")] == [
        "finished",
        "cancelled",
        "coming",
        "airing",
    ]


def test_a_show_ends_with_its_seasons_latest_episode_not_a_special_years_on():
    details: dict[str, object] = {
        **tv_details(
            9,
            "Glass Orchard",
            (2,),
            first_aired=date(2012, 1, 10),
            specials=1,
            special_dates=(date(2024, 12, 24),),
        ),
        "last_air_date": "2024-12-24",
    }

    found = show(details)

    assert found is not None
    assert found.last_aired == date(2012, 1, 17)


def test_a_film_says_what_its_about_panel_shows():
    details = {
        **movie_details(7201, "The Lantern Keeper", date(2016, 10, 7), 104),
        "overview": "A keeper's last winter on the rock.",
        "genres": [{"id": 18, "name": "Drama"}, {"id": 16, "name": "Animation"}],
        "production_companies": [{"name": "Tidewater Pictures"}],
    }

    found = film(details)

    assert found is not None
    assert (found.overview, found.genres, found.studio, found.status, found.minutes) == (
        "A keeper's last winter on the rock.",
        ("Drama", "Animation"),
        "Tidewater Pictures",
        "finished",
        104,
    )


def test_posters_come_best_rated_first():
    answer = {
        "posters": [
            {
                "file_path": "/a.jpg",
                "iso_639_1": "en",
                "width": 1000,
                "height": 1500,
                "vote_average": 5.1,
            },
            {
                "file_path": "/b.jpg",
                "iso_639_1": None,
                "width": 2000,
                "height": 3000,
                "vote_average": 5.6,
            },
            {"iso_639_1": "fr"},  # no picture
        ]
    }

    found = pictures(answer)

    assert [(p.path, p.language, p.width) for p in found] == [
        ("/b.jpg", None, 2000),
        ("/a.jpg", "en", 1000),
    ]


def test_other_names_come_from_a_show_or_a_film():
    assert alternative_titles({"results": [{"title": "La Ligne du Port"}]}) == ["La Ligne du Port"]
    assert alternative_titles({"titles": [{"title": "Sternenfall"}, {"title": "Sternenfall"}]}) == [
        "Sternenfall"
    ]
