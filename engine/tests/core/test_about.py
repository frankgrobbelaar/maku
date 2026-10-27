from datetime import date

from maku.core.about import About, Said, about

TITLE = Said(
    overview="A harbour pilot keeps the port's secrets.",
    genres=("Drama",),
    studio="Northwind",
    status="airing",
    started=date(2019, 3, 4),
    minutes=None,
)
ENTRY = Said(
    overview="The port's pilot, and the port's secrets.",
    genres=("Drama", "Crime"),
    studio="Tidewater Pictures",
    status="airing",
    started=date(2019, 3, 4),
    ended=date(2021, 6, 7),
    minutes=52,
)


def test_what_the_title_says_comes_first():
    found = about(TITLE, ENTRY, [45, 45, 47])

    assert found == About(
        overview="A harbour pilot keeps the port's secrets.",
        genres=("Drama",),
        studio="Northwind",
        status="airing",
        started=date(2019, 3, 4),
        ended=date(2021, 6, 7),
        minutes=45,  # what most of its episodes last
    )


def test_either_fills_in_what_the_other_doesnt_say():
    found = about(Said(started=date(2019, 3, 4)), ENTRY)

    assert (found.overview, found.genres, found.minutes) == (
        "The port's pilot, and the port's secrets.",
        ("Drama", "Crime"),
        52,
    )
    assert about(TITLE, None).genres == ("Drama",)
