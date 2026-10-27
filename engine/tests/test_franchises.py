"""The rest of each franchise: the films of the library's collections, looked up a few at a time
and kept current, and what the library has no part of."""

import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from maku import franchises, titles
from maku.catalog import Catalog
from maku.config import DataPaths
from maku.core.catalog import TitleKind
from maku.tmdb import API as TMDB
from maku.web import Service
from tests.fake_web import FakeWeb, reply
from tests.services import internet, with_key
from tests.shelf import NOW, identify, library

STARFALL, STARFALL_II, ASCENT, ORIGINS = -7101, -7102, -7103, -7104


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "Videos"


@pytest.fixture
def starfall(paths: DataPaths, conn: sqlite3.Connection, root: Path) -> sqlite3.Connection:
    """The first and third Starfall films, and The Harbour Line's first episode, identified."""
    with_key(paths)
    library(conn, root, ["Movies/Starfall (2008).mkv", "Movies/Starfall Ascent (2015).mkv"], 120)
    library(conn, root, ["TV/The Harbour Line/The Harbour Line - S01E01.mkv"], minutes=45)
    identify(paths, conn, internet())
    return conn


def asked_about(web: FakeWeb) -> list[int]:
    """The films TMDB was asked about, in order, as entries."""
    found = (re.search(r"/movie/(\d+)$", request.path) for request in web.asked)
    return [-int(match[1]) for match in found if match]


def look_up_everything(conn: sqlite3.Connection, catalog: Catalog) -> None:
    while franchises.look_up(conn, catalog, NOW):
        pass


def rest_of(conn: sqlite3.Connection, name: str) -> franchises.Rest:
    [title_id] = [
        row["id"] for row in conn.execute("SELECT id FROM titles WHERE name = ?", (name,))
    ]
    franchise = titles.franchise_of(conn, title_id, NOW.date())
    assert franchise is not None
    return franchises.rest(conn, franchise)


def test_a_collection_is_looked_up_a_few_films_at_a_time_what_the_library_lacks_first(
    paths: DataPaths, starfall: sqlite3.Connection
):
    web = internet()
    catalog = Catalog(paths, web)

    assert franchises.look_up(starfall, catalog, NOW, count=1) == 1
    shown = rest_of(starfall, "Starfall")
    assert len(shown.titles) == 1
    assert shown.looking  # Origins is still to be asked about
    look_up_everything(starfall, catalog)

    assert sorted(asked_about(web)) == [ORIGINS, STARFALL_II]  # the library's own were kept
    kept = {row["id"]: row for row in starfall.execute("SELECT * FROM entries")}
    assert (kept[ORIGINS]["name"], kept[ORIGINS]["kind"], kept[ORIGINS]["status"]) == (
        "Starfall: Origins",
        "movie",
        "coming",
    )
    assert kept[ORIGINS]["collection"] == "The Starfall Collection"


def test_what_the_library_has_no_part_of_once_its_looked_up(
    paths: DataPaths, starfall: sqlite3.Connection
):
    before = rest_of(starfall, "Starfall: Ascent")
    assert (before.titles, before.looking) == ([], True)  # the others are only links so far

    look_up_everything(starfall, Catalog(paths, internet()))
    after = rest_of(starfall, "Starfall: Ascent")

    assert not after.looking
    assert [(entry.name, entry.kind, entry.start, entry.coming) for entry in after.titles] == [
        ("Starfall II", TitleKind.MOVIE, date(2011, 6, 10), False),
        ("Starfall: Origins", TitleKind.MOVIE, date(2027, 11, 19), True),
    ]


def test_a_series_alone_misses_nothing(paths: DataPaths, starfall: sqlite3.Connection):
    look_up_everything(starfall, Catalog(paths, internet()))

    rest = rest_of(starfall, "The Harbour Line")

    assert (rest.titles, rest.looking) == ([], False)


def test_each_entry_is_asked_about_again_weekly_or_daily_while_its_still_to_come(
    paths: DataPaths, starfall: sqlite3.Connection
):
    look_up_everything(starfall, Catalog(paths, internet()))

    assert franchises.next_to_ask(starfall, NOW + timedelta(hours=23), 6) == []
    assert franchises.next_to_ask(starfall, NOW + timedelta(days=1), 6) == [ORIGINS]
    assert sorted(
        franchises.next_to_ask(starfall, NOW + timedelta(days=7, minutes=1), 6)
    ) == sorted([STARFALL, STARFALL_II, ASCENT, ORIGINS, 4101])


def test_a_film_tmdb_no_longer_has_is_left_out_and_asked_about_again_the_next_day(
    paths: DataPaths, starfall: sqlite3.Connection
):
    web = internet()
    del web.answers[f"GET {TMDB}/movie/7104"]

    look_up_everything(starfall, Catalog(paths, web))

    assert [entry.name for entry in rest_of(starfall, "Starfall").titles] == ["Starfall II"]
    assert not rest_of(starfall, "Starfall").looking
    assert franchises.next_to_ask(starfall, NOW + timedelta(hours=23), 6) == []
    assert franchises.next_to_ask(starfall, NOW + timedelta(days=1), 6) == [ORIGINS]


def test_a_film_tmdb_wont_answer_about_waits_a_day_while_the_rest_go_on(
    paths: DataPaths, starfall: sqlite3.Connection
):
    web = internet()
    web.answers[f"GET {TMDB}/movie/7102"] = reply({"status_message": "Internal error."}, 500)

    no_waits = Service("TMDB", web, sleep=lambda _: None)  # no waits between tries
    look_up_everything(starfall, Catalog(paths, web, service=no_waits))

    assert [entry.name for entry in rest_of(starfall, "Starfall").titles] == ["Starfall: Origins"]
    assert not rest_of(starfall, "Starfall").looking  # nothing waits forever on the one that failed
    assert franchises.next_to_ask(starfall, NOW + timedelta(days=1), 6) == [ORIGINS, STARFALL_II]


def test_without_a_key_nothing_is_asked(paths: DataPaths, starfall: sqlite3.Connection):
    (paths.root / "credentials.json").unlink()
    web = internet()

    assert franchises.look_up(starfall, Catalog(paths, web), NOW) == 0
    assert web.asked == []
