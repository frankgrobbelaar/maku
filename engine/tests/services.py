"""TMDB as the tests stand it in: a small made-up world of series and films, answered in TMDB's
shape (tests/tmdb_data.py). No real title appears.

- The Harbour Line (4101): a drama still airing, three seasons (8, 10 and 10 episodes) from 2019,
  its third airing now, and a Christmas special. TMDB knows it as "La Ligne du Port" too.
- Glass Orchard (4102): finished, two seasons (12 and 13) from 2012.
- Quiet Hours (4103): finished, one season of 6 from 2015, and two specials.
- The Starfall Collection (9101): Starfall (7101, 2008), Starfall II (7102, 2011), Starfall:
  Ascent (7103, 2015), and Starfall: Origins (7104), still to come.
- The Lantern Keeper (7201, 2016) and Northern Lights (7202, 2004): films of their own.

TMDB needs the owner's key: `with_key` gives the data folder one.
"""

import re
from collections.abc import Callable, Mapping
from datetime import date

from maku import credentials
from maku.config import DataPaths
from maku.core.identify import normalize
from maku.tmdb import API as TMDB
from tests.fake_web import Answer, Asked, FakeWeb
from tests.tmdb_data import collection, movie_details, movie_search, tv_details, tv_search

KEY = "0123456789abcdef0123456789abcdef"  # shaped like TMDB's shorter key: sent in the address

HARBOUR = {
    **tv_details(
        4101,
        "The Harbour Line",
        (8, 10, 10),
        first_aired=date(2019, 3, 4),
        status="Returning Series",
        specials=1,
        special_dates=(date(2021, 12, 24),),
        aired={(2, 1): date(2021, 4, 5), (3, 1): date(2026, 9, 21)},
        titles={(1, 1): "Pilot", (1, 2): "Low Tide", (0, 1): "A Harbour Christmas"},
    ),
    "overview": "A harbour pilot keeps the port's secrets, and the port keeps hers.",
    "genres": [{"id": 18, "name": "Drama"}, {"id": 80, "name": "Crime"}],
    "networks": [{"id": 1, "name": "Northwind"}],
}
ORCHARD = tv_details(
    4102,
    "Glass Orchard",
    (12, 13),
    first_aired=date(2012, 1, 10),
    aired={(2, 1): date(2013, 1, 8)},
    titles={(1, 5): "The Well"},
)
QUIET = tv_details(
    4103,
    "Quiet Hours",
    (6,),
    first_aired=date(2015, 9, 1),
    specials=2,
    special_dates=(date(2015, 12, 24), date(2016, 12, 24)),
    titles={(0, 1): "Christmas Special", (0, 2): "The Night Train"},
    minutes=30,
)
SHOWS = {4101: HARBOUR, 4102: ORCHARD, 4103: QUIET}
SHOW_NAMES = {4101: ["La Ligne du Port"], 4102: ["Glasgarten"], 4103: []}

STARFALL_COLLECTION = (9101, "The Starfall Collection")
STARFALL = movie_details(7101, "Starfall", date(2008, 5, 2), 118, collection=STARFALL_COLLECTION)
STARFALL_II = movie_details(
    7102, "Starfall II", date(2011, 6, 10), 124, collection=STARFALL_COLLECTION
)
ASCENT = movie_details(
    7103, "Starfall: Ascent", date(2015, 7, 17), 131, collection=STARFALL_COLLECTION
)
ORIGINS = movie_details(
    7104,
    "Starfall: Origins",
    date(2027, 11, 19),
    0,
    collection=STARFALL_COLLECTION,
    status="Post Production",
)
LANTERN = movie_details(7201, "The Lantern Keeper", date(2016, 10, 7), 104)
NORTHERN = movie_details(7202, "Northern Lights", date(2004, 2, 13), 97)
FILMS: dict[int, dict[str, object]] = {
    7101: STARFALL,
    7102: STARFALL_II,
    7103: ASCENT,
    7104: ORIGINS,
    7201: LANTERN,
    7202: NORTHERN,
}
FILM_NAMES: dict[int, list[str]] = {7201: ["Le Gardien de la Lanterne"]}
COLLECTIONS = {9101: collection(*STARFALL_COLLECTION, STARFALL, STARFALL_II, ASCENT, ORIGINS)}


def with_key(paths: DataPaths) -> DataPaths:
    """The data folder, with the owner's TMDB key kept in it."""
    credentials.save(paths, "tmdb", KEY)
    return paths


def internet(*, shows: Mapping[int, dict[str, object]] | None = None) -> FakeWeb:
    """TMDB's searches, shows, films and collections. `shows` stands other answers in for some
    shows: how far one still airing has got by now, say."""
    known = {**SHOWS, **(shows or {})}
    answers: dict[str, Answer] = {
        f"GET {TMDB}/authentication": {"success": True},
        f"GET {TMDB}/search/tv": _search(
            {number: [str(show["name"]), *SHOW_NAMES[number]] for number, show in known.items()},
            lambda found: tv_search(
                *(
                    (n, str(known[n]["name"]), date.fromisoformat(str(known[n]["first_air_date"])))
                    for n in found
                )
            ),
        ),
        f"GET {TMDB}/search/movie": _search(
            {
                number: [str(film["title"]), *FILM_NAMES.get(number, [])]
                for number, film in FILMS.items()
            },
            lambda found: movie_search(
                *(
                    (
                        n,
                        str(FILMS[n]["title"]),
                        date.fromisoformat(str(FILMS[n]["release_date"])),
                    )
                    for n in found
                )
            ),
        ),
    }
    for number, show in known.items():
        answers[f"GET {TMDB}/tv/{number}"] = tmdb_show(show, SHOW_NAMES[number])
    for number, film in FILMS.items():
        answers[f"GET {TMDB}/movie/{number}"] = _film(film, FILM_NAMES.get(number, []))
    for number, parts in COLLECTIONS.items():
        answers[f"GET {TMDB}/collection/{number}"] = parts
    return FakeWeb(answers)


def tmdb_show(details: Mapping[str, object], names: list[str]) -> Callable[[Asked], object]:
    """A /tv/{id} that answers the way TMDB does: the show, with its other names or seasons
    appended when asked."""

    def answer(asked: Asked) -> object:
        shown = {key: value for key, value in details.items() if not key.startswith("season/")}
        for wanted in filter(None, asked.query.get("append_to_response", "").split(",")):
            if wanted == "alternative_titles":
                shown[wanted] = {"results": [{"iso_3166_1": "FR", "title": n} for n in names]}
            elif wanted in details:
                shown[wanted] = details[wanted]
        return shown

    return answer


def _film(details: Mapping[str, object], names: list[str]) -> Callable[[Asked], object]:
    def answer(asked: Asked) -> object:
        shown = dict(details)
        if "alternative_titles" in asked.query.get("append_to_response", ""):
            shown["alternative_titles"] = {
                "titles": [{"iso_3166_1": "FR", "title": n} for n in names]
            }
        return shown

    return answer


def _search(
    names: Mapping[int, list[str]], answer: Callable[[list[int]], object]
) -> Callable[[Asked], object]:
    """A search that finds what has every word asked for among the words of one of its names, as
    TMDB's, more or less: "starfall" finds every Starfall film, "starfall ii" the second."""

    def search(asked: Asked) -> object:
        wanted = set(_words(asked.query["query"]))
        found = [
            number
            for number, its in names.items()
            if wanted and any(wanted <= set(_words(name)) for name in its)
        ]
        return answer(found)

    return search


def _words(text: str) -> list[str]:
    return re.split(r"\s+", normalize(text)) if normalize(text) else []
