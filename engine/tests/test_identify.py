"""Identifying the library, the scan's third stage, with TMDB stood in for (tests/services.py)."""

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from maku.config import DataPaths
from maku.core.names import Kind
from maku.identify import Identifier, UnplacedError
from maku.library import find_files, folders, read_file, unread
from maku.titles import franchises
from maku.tmdb import API as TMDB
from tests.fake_ffprobe import REPORT
from tests.services import HARBOUR_1985, NAMESAKES, internet, with_key
from tests.shelf import NOW, identify, library
from tests.tmdb_data import tv_details


def placed(conn: sqlite3.Connection) -> dict[str, tuple[object, ...]]:
    rows = conn.execute(
        """SELECT f.path, f.matched, t.name, t.kind, f.season, f.episode
           FROM files f LEFT JOIN titles t ON t.id = f.title_id"""
    )
    return {Path(row["path"]).name: tuple(row)[1:] for row in rows}


def ids(conn: sqlite3.Connection) -> dict[str, int]:
    return {Path(row["path"]).name: row["id"] for row in conn.execute("SELECT id, path FROM files")}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "Videos"


@pytest.fixture
def keyed(paths: DataPaths) -> DataPaths:
    return with_key(paths)


def test_episodes_land_in_tmdbs_seasons_however_theyre_named(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(
        conn,
        root,
        [
            "TV/The Harbour Line (2019)/Season 01/The Harbour Line (2019) - S01E01 - Pilot.mkv",
            "TV/The Harbour Line (2019)/Season 01/02.mkv",
            "Downloads/The.Harbour.Line.S02E03.1080p.WEB-DL.DDP5.1.H.264-GROUP.mkv",
            "Downloads/the.harbour.line.s03e01e02.720p.hdtv.x264-grp.mkv",
        ],
        minutes=45,
    )

    done = identify(keyed, conn, internet())

    show = "The Harbour Line"
    assert placed(conn) == {
        "The Harbour Line (2019) - S01E01 - Pilot.mkv": ("sure", show, "series", 1, 1),
        "02.mkv": ("sure", show, "series", 1, 2),
        "The.Harbour.Line.S02E03.1080p.WEB-DL.DDP5.1.H.264-GROUP.mkv": (
            "sure",
            show,
            "series",
            2,
            3,
        ),
        "the.harbour.line.s03e01e02.720p.hdtv.x264-grp.mkv": ("sure", show, "series", 3, 1),
    }
    assert conn.execute("SELECT episode_end FROM files WHERE season = 3").fetchone()[0] == 2
    title = conn.execute("SELECT * FROM titles").fetchone()
    assert (title["tmdb_type"], title["tmdb_id"], title["entry_id"]) == ("tv", 4101, 4101)
    assert (title["year"], title["released"]) == (2019, "2019-03-04")
    assert (title["poster"], title["backdrop"]) == ("/poster-4101.jpg", "/backdrop-4101.jpg")
    assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 29  # a special too
    assert done.sure == 4


def test_a_show_numbered_straight_through_lands_in_its_seasons(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    # Glass Orchard's seasons have 12 and 13 episodes: its 15th is season 2's third.
    library(
        conn,
        root,
        [f"Glass Orchard/Glass Orchard - {n:03}.mkv" for n in (1, 15, 25)],
        minutes=45,
    )

    identify(keyed, conn, internet())

    assert placed(conn) == {
        "Glass Orchard - 001.mkv": ("sure", "Glass Orchard", "series", 1, 1),
        "Glass Orchard - 015.mkv": ("sure", "Glass Orchard", "series", 2, 3),
        "Glass Orchard - 025.mkv": ("sure", "Glass Orchard", "series", 2, 13),
    }


def test_a_show_is_found_by_a_name_tmdb_knows_it_by_in_another_language(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["Séries/La Ligne du Port - S01E02.mkv"], minutes=45)

    identify(keyed, conn, internet())

    assert placed(conn) == {
        "La Ligne du Port - S01E02.mkv": ("sure", "The Harbour Line", "series", 1, 2)
    }


def test_a_film_is_its_own_title(keyed: DataPaths, conn: sqlite3.Connection, root: Path):
    library(conn, root, ["Movies/The.Lantern.Keeper.2016.1080p.BluRay.x264-GRP.mkv"], minutes=104)

    identify(keyed, conn, internet())

    assert placed(conn) == {
        "The.Lantern.Keeper.2016.1080p.BluRay.x264-GRP.mkv": (
            "sure",
            "The Lantern Keeper",
            "movie",
            None,
            None,
        )
    }
    title = conn.execute("SELECT * FROM titles").fetchone()
    assert (title["tmdb_type"], title["tmdb_id"], title["entry_id"]) == ("movie", 7201, -7201)


def test_the_films_of_a_collection_are_one_franchise_named_after_it(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(
        conn,
        root,
        [
            "Movies/Starfall (2008)/Starfall (2008).mkv",
            "Movies/Starfall.Ascent.2015.2160p.UHD.BluRay.REMUX.HDR.HEVC.Atmos-GRP.mkv",
        ],
        minutes=120,
    )
    library(conn, root, ["Movies/Northern Lights 2004.mkv"], minutes=97)

    identify(keyed, conn, internet())

    found = placed(conn)
    assert found["Starfall (2008).mkv"] == ("sure", "Starfall", "movie", None, None)
    assert found["Starfall.Ascent.2015.2160p.UHD.BluRay.REMUX.HDR.HEVC.Atmos-GRP.mkv"] == (
        "sure",
        "Starfall: Ascent",
        "movie",
        None,
        None,
    )
    shelf = {f.name: [t.name for t in f.titles] for f in franchises(conn, NOW.date())}
    assert shelf == {
        "Northern Lights": ["Northern Lights"],
        "The Starfall Collection": ["Starfall", "Starfall: Ascent"],
    }


def test_two_films_of_one_name_but_not_one_year_are_looked_up_apart(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(
        conn,
        root,
        ["Movies/Starfall (2008).mkv", "Movies/Starfall II (2011).mkv"],
        minutes=120,
    )

    identify(keyed, conn, internet())

    assert placed(conn) == {
        "Starfall (2008).mkv": ("sure", "Starfall", "movie", None, None),
        "Starfall II (2011).mkv": ("sure", "Starfall II", "movie", None, None),
    }


def test_without_a_key_nothing_is_looked_up_and_the_files_wait(
    paths: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["TV/The Harbour Line/The Harbour Line - S01E01.mkv"], minutes=45)
    web = internet()

    done = identify(paths, conn, web)

    assert web.asked == []
    assert done.note == "Maku needs your TMDB key to find series and films: add it in Settings."
    row = conn.execute("SELECT matched, identified_at FROM files").fetchone()
    assert (row["matched"], row["identified_at"]) == (None, None)

    identify(with_key(paths), conn, web)  # the key, added later

    assert placed(conn) == {
        "The Harbour Line - S01E01.mkv": ("sure", "The Harbour Line", "series", 1, 1)
    }


def test_a_name_maku_cant_match_waits_for_the_owner(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["Downloads/Mystery Show - S01E03.mkv"])

    identify(keyed, conn, internet())

    row = conn.execute("SELECT matched, title_id, guesses FROM files").fetchone()
    assert (row["matched"], row["title_id"], json.loads(row["guesses"])) == ("none", None, [])


def test_a_film_a_show_shares_its_name_with_is_offered_but_not_taken(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    # "Starfall" alone, as an episode: there's no show of that name, only films.
    library(conn, root, ["Downloads/Starfall - S01E01.mkv"], minutes=45)

    identify(keyed, conn, internet())

    row = conn.execute("SELECT matched, guesses FROM files").fetchone()
    assert row["matched"] == "unsure"
    assert json.loads(row["guesses"])[0]["entryId"] < 0  # films' entries are negative


def test_extras_are_marked_and_never_looked_up(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["Movies/Starfall (2008)/Sample/starfall-sample.mkv"])
    web = internet()

    identify(keyed, conn, web)

    assert placed(conn) == {"starfall-sample.mkv": ("extra", None, None, None, None)}
    assert web.asked == []


def test_offline_the_files_wait_for_the_next_scan(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["TV/Glass Orchard/Glass Orchard - S01E01.mkv"])
    web = internet()
    web.offline = True

    done = identify(keyed, conn, web)

    assert "Titles wait for the next scan: TMDB couldn't be asked" in str(done.note)
    row = conn.execute("SELECT matched, identified_at FROM files").fetchone()
    assert (row["matched"], row["identified_at"]) == (None, None)


def test_a_file_the_owner_placed_is_left_alone(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["TV/Glass Orchard/Glass Orchard - S01E01.mkv"])
    with conn:
        conn.execute("UPDATE files SET pinned = 1")
    web = internet()

    identify(keyed, conn, web)

    assert web.asked == []
    assert conn.execute("SELECT matched FROM files").fetchone()[0] is None


def test_a_second_scan_asks_nobody_again(keyed: DataPaths, conn: sqlite3.Connection, root: Path):
    library(conn, root, ["TV/Glass Orchard/Glass Orchard - S01E01.mkv"], minutes=45)
    identify(keyed, conn, internet())
    (root / "TV" / "Glass Orchard" / "Glass Orchard - S01E02.mkv").write_bytes(b"new")
    [folder] = folders(conn)
    find_files(conn, folder, stamp=(NOW + timedelta(hours=1)).isoformat())
    for file_id, path in unread(conn):
        read_file(conn, file_id, path, lambda _: REPORT, now=NOW)
    web = internet()

    identify(keyed, conn, web)

    assert placed(conn)["Glass Orchard - S01E02.mkv"] == ("sure", "Glass Orchard", "series", 1, 2)
    assert web.asked == []  # TMDB's search and details were kept; the episode list is fresh


def test_a_special_goes_into_its_shows_season_0(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(
        conn,
        root,
        [
            "TV/Quiet Hours (2015)/Season 01/Quiet Hours (2015) - S01E01.mkv",
            "TV/Quiet Hours (2015)/Specials/Quiet Hours (2015) - S00E02 - The Night Train.mkv",
        ],
        minutes=30,
    )

    identify(keyed, conn, internet())

    assert placed(conn)["Quiet Hours (2015) - S00E02 - The Night Train.mkv"] == (
        "sure",
        "Quiet Hours",
        "series",
        0,
        2,
    )


def test_a_special_numbered_otherwise_is_found_by_its_name(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    # The release counts its specials its own way: its "Special 05" is TMDB's second.
    library(
        conn,
        root,
        [
            "TV/Quiet Hours/Quiet Hours - 01.mkv",
            "TV/Quiet Hours/Quiet Hours - Special 05 - The Night Train.mkv",
        ],
        minutes=30,
    )

    identify(keyed, conn, internet())

    assert placed(conn)["Quiet Hours - Special 05 - The Night Train.mkv"] == (
        "sure",
        "Quiet Hours",
        "series",
        0,
        2,
    )


def test_the_same_episode_named_two_ways_isnt_a_clash(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(
        conn,
        root,
        [
            "TV/Glass Orchard (2012)/Season 01/05.mkv",
            "TV/Glass Orchard (2012)/Glass Orchard - S01E05.mkv",
        ],
        minutes=45,
    )

    identify(keyed, conn, internet())

    assert set(placed(conn).values()) == {("sure", "Glass Orchard", "series", 1, 5)}


def test_two_files_claiming_one_episode_with_different_numbers_wait_for_the_owner(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(
        conn,
        root,
        [
            "TV/Glass Orchard/Glass Orchard - 013.mkv",  # straight through: season 2, episode 1
            "TV/Glass Orchard/Season 02/Glass Orchard - 01.mkv",  # season 2, episode 1 by number
        ],
        minutes=45,
    )

    identify(keyed, conn, internet())

    assert {row[0] for row in conn.execute("SELECT matched FROM files")} == {"unsure"}


def test_the_owner_says_which_episode_when_its_name_doesnt(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["Burnt/HARBOUR_DISC1/VIDEO_TS/VTS_01_1.VOB"])
    identify(keyed, conn, internet())
    [file_id] = ids(conn).values()
    owner = Identifier(keyed, internet(), now=lambda: NOW)

    with pytest.raises(UnplacedError, match="Which episode is it"):
        owner.choose(conn, file_id, 4101, Kind.EPISODE)
    assert placed(conn)["VTS_01_1.VOB"] == ("none", None, None, None, None)

    assert owner.choose(conn, file_id, 4101, Kind.EPISODE, episode=10) == 1
    assert placed(conn)["VTS_01_1.VOB"] == ("sure", "The Harbour Line", "series", 2, 2)


def test_the_owner_makes_a_burnt_disc_a_film(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["Burnt/NORTHERN_LIGHTS/VIDEO_TS/VTS_01_1.VOB"], minutes=97)
    identify(keyed, conn, internet())
    [file_id] = ids(conn).values()

    Identifier(keyed, internet(), now=lambda: NOW).choose(conn, file_id, -7202, Kind.MOVIE)

    assert placed(conn)["VTS_01_1.VOB"] == ("sure", "Northern Lights", "movie", None, None)


def test_look_alikes_maku_cant_place_keep_waiting(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["Downloads/[subs] ep03 final.mkv", "Downloads/[subs] ep999 final.mkv"])
    identify(keyed, conn, internet())
    found = ids(conn)
    owner = Identifier(keyed, internet(), now=lambda: NOW)

    count = owner.choose(
        conn,
        found["[subs] ep03 final.mkv"],
        4102,
        Kind.EPISODE,
        also=[found["[subs] ep999 final.mkv"]],
    )

    assert count == 1
    assert placed(conn)["[subs] ep03 final.mkv"] == ("sure", "Glass Orchard", "series", 1, 3)
    assert placed(conn)["[subs] ep999 final.mkv"][0] != "sure"


def test_a_special_maku_cant_number_still_belongs_to_its_show(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["Burnt/QUIET_HOURS_EXTRAS/VIDEO_TS/VTS_02_1.VOB"])
    identify(keyed, conn, internet())
    [file_id] = ids(conn).values()

    Identifier(keyed, internet(), now=lambda: NOW).choose(conn, file_id, 4103, Kind.SPECIAL)

    assert placed(conn)["VTS_02_1.VOB"] == ("sure", "Quiet Hours", "series", 0, None)


def test_the_entry_is_kept_with_its_names_and_its_collection(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["Movies/Starfall II (2011).mkv"], minutes=124)

    identify(keyed, conn, internet())

    entry = conn.execute("SELECT * FROM entries WHERE id = -7102").fetchone()
    assert (entry["name"], entry["kind"], entry["status"]) == ("Starfall II", "movie", "finished")
    assert entry["collection"] == "The Starfall Collection"
    links = conn.execute(
        "SELECT related_id, relation FROM entry_links WHERE entry_id = -7102 ORDER BY related_id"
    ).fetchall()
    assert [tuple(link) for link in links] == [
        (-7104, "SEQUEL"),
        (-7103, "SEQUEL"),
        (-7101, "PREQUEL"),
    ]


def test_a_sure_match_spares_tmdb_the_other_kinds_search(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["TV/Glass Orchard/Glass Orchard - S01E01.mkv"], minutes=45)
    web = internet()

    identify(keyed, conn, web)

    assert placed(conn)["Glass Orchard - S01E01.mkv"][0] == "sure"
    searched = [path for path in web.paths() if "/search/" in path]
    assert searched == ["GET https://api.themoviedb.org/3/search/tv"]


def harbour_airing(listed: int) -> dict[str, object]:
    """The Harbour Line as TMDB lists it while its third season airs: `listed` of it so far."""
    return tv_details(
        4101,
        "The Harbour Line",
        (8, 10, listed),
        first_aired=date(2019, 3, 4),
        status="Returning Series",
        aired={(2, 1): date(2021, 4, 5), (3, 1): date(2026, 9, 14)},
    )


NEWEST = "The.Harbour.Line.S03E05.1080p.WEB-DL-GRP.mkv"


def test_the_newest_episode_is_looked_for_in_tmdbs_list_afresh(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["Downloads/The.Harbour.Line.S03E04.1080p.WEB-DL-GRP.mkv"], minutes=45)
    identify(keyed, conn, internet(shows={4101: harbour_airing(4)}))
    # Within the hour, so Maku's list isn't due again; TMDB lists the fifth by now.
    library(conn, root, [f"Downloads/{NEWEST}"], minutes=45)

    identify(keyed, conn, internet(shows={4101: harbour_airing(5)}))

    assert placed(conn)[NEWEST] == ("sure", "The Harbour Line", "series", 3, 5)


def test_an_episode_tmdb_doesnt_list_even_when_asked_afresh_waits(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    first = "The.Harbour.Line.S01E05.HDTV.x264-GRP.mkv"
    library(conn, root, [f"TV/The Harbour Line (2019)/Season 01/{first}"], minutes=45)
    identify(keyed, conn, internet(shows={4101: harbour_airing(4)}))
    library(conn, root, [f"Downloads/{NEWEST}"], minutes=45)
    web = internet(shows={4101: harbour_airing(4)})

    identify(keyed, conn, web)

    assert placed(conn)[first] == ("sure", "The Harbour Line", "series", 1, 5)
    assert placed(conn)[NEWEST] == ("unsure", None, None, None, None)  # not season 1's fifth
    assert f"GET {TMDB}/tv/4101" in web.paths()  # its list was asked for again


def test_the_owners_choice_looks_for_the_episode_in_tmdbs_list_afresh(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["Downloads/The.Harbour.Line.S03E04.1080p.WEB-DL-GRP.mkv"], minutes=45)
    library(conn, root, ["Downloads/THL.S03E05.1080p.WEB-DL-GRP.mkv"], minutes=45)
    identify(keyed, conn, internet(shows={4101: harbour_airing(4)}))
    owner = Identifier(keyed, internet(shows={4101: harbour_airing(5)}), now=lambda: NOW)

    owner.choose(conn, ids(conn)["THL.S03E05.1080p.WEB-DL-GRP.mkv"], 4101, Kind.EPISODE)

    assert placed(conn)["THL.S03E05.1080p.WEB-DL-GRP.mkv"] == (
        "sure",
        "The Harbour Line",
        "series",
        3,
        5,
    )


def test_the_owners_choice_of_a_show_that_doesnt_list_the_episode_asks_which_it_is(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["Downloads/THL.S03E05.1080p.WEB-DL-GRP.mkv"], minutes=45)
    identify(keyed, conn, internet(shows={4101: harbour_airing(4)}))
    owner = Identifier(keyed, internet(shows={4101: harbour_airing(4)}), now=lambda: NOW)
    [file_id] = ids(conn).values()

    with pytest.raises(UnplacedError) as raised:
        owner.choose(conn, file_id, 4101, Kind.EPISODE)

    assert str(raised.value) == "Which episode is it? The Harbour Line has no season 3 episode 5."
    assert placed(conn)["THL.S03E05.1080p.WEB-DL-GRP.mkv"] == ("none", None, None, None, None)


def test_a_series_and_its_remake_are_told_apart_by_their_years(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(
        conn,
        root,
        [
            "Downloads/The.Harbour.Line.1985.S01E01.DVDRip.x264-GRP.mkv",
            "Downloads/The.Harbour.Line.2019.S01E01.1080p.WEB-DL-GRP.mkv",
            "Downloads/The.Harbour.Line.S01E02.HDTV.x264-GRP.mkv",  # which of the two, who knows
        ],
        minutes=45,
    )
    web = internet(shows={4199: HARBOUR_1985})

    identify(keyed, conn, web)

    rows = conn.execute(
        """SELECT f.path, f.matched, t.tmdb_id, t.year, f.season, f.episode
           FROM files f LEFT JOIN titles t ON t.id = f.title_id"""
    )
    assert {Path(row["path"]).name: tuple(row)[1:] for row in rows} == {
        "The.Harbour.Line.1985.S01E01.DVDRip.x264-GRP.mkv": ("sure", 4199, 1985, 1, 1),
        "The.Harbour.Line.2019.S01E01.1080p.WEB-DL-GRP.mkv": ("sure", 4101, 2019, 1, 1),
        "The.Harbour.Line.S01E02.HDTV.x264-GRP.mkv": ("unsure", None, None, None, None),
    }
    years = {
        asked.query.get("first_air_date_year") for asked in web.asked if "/search/" in asked.url
    }
    assert {"1985", "2019"} <= years  # TMDB was asked for each year's


def test_a_year_tmdb_doesnt_give_the_title_is_looked_up_without_it(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    # Glass Orchard began in 2012, not 2013: nothing that year, so it's asked for without one.
    library(conn, root, ["TV/Glass Orchard (2013)/Glass Orchard - S01E01.mkv"], minutes=45)

    identify(keyed, conn, internet())

    assert placed(conn) == {"Glass Orchard - S01E01.mkv": ("sure", "Glass Orchard", "series", 1, 1)}


def test_a_film_named_without_its_year_waits_while_a_namesake_fits_as_well(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    # The 2004 film is 97 minutes; TMDB ranks the 2024 one (112 minutes) first.
    library(conn, root, ["Movies/Northern Lights.mkv"], minutes=97)

    identify(keyed, conn, internet(films={7203: NAMESAKES[7203]}))

    row = conn.execute("SELECT matched, guesses FROM files").fetchone()
    assert row["matched"] == "unsure"
    assert [(guess["year"], guess["minutes"]) for guess in json.loads(row["guesses"])] == [
        (2004, 97),
        (2024, 112),
    ]


def test_a_film_tmdb_ranks_past_its_first_five_is_found_by_its_year(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    # Seven films called Northern Lights; the 1962 one is TMDB's sixth.
    library(conn, root, ["Movies/Northern.Lights.1962.1080p.BluRay.x264-GRP.mkv"], minutes=110)
    web = internet(films=NAMESAKES)

    identify(keyed, conn, web)

    title = conn.execute("SELECT tmdb_id, year FROM titles").fetchone()
    assert placed(conn)["Northern.Lights.1962.1080p.BluRay.x264-GRP.mkv"][0] == "sure"
    assert (title["tmdb_id"], title["year"]) == (7208, 1962)
    searched = [asked.query for asked in web.asked if asked.url.startswith(f"{TMDB}/search/movie")]
    assert searched[0]["primary_release_year"] == "1962"


def test_a_daily_shows_episode_named_by_its_day_lands_on_that_days_episode(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    # Season 2 aired weekly from 5 April 2021: the 12th was its second.
    dated = "The.Harbour.Line.2021.04.12.1080p.WEB.h264-GRP.mkv"
    numbered = "The.Harbour.Line.S02E02.720p.HDTV.x264-GRP.mkv"  # the same, named the other way
    library(conn, root, [f"Downloads/{dated}", f"TV/The Harbour Line/{numbered}"], minutes=45)

    identify(keyed, conn, internet())

    assert placed(conn) == {
        dated: ("sure", "The Harbour Line", "series", 2, 2),
        numbered: ("sure", "The Harbour Line", "series", 2, 2),
    }


def test_a_film_whose_name_gives_tmdbs_id_is_that_film_whatever_shares_its_name(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["Movies/Northern Lights {tmdb-7206}.mkv"], minutes=98)
    web = internet(films=NAMESAKES)

    identify(keyed, conn, web)

    title = conn.execute("SELECT tmdb_id, year FROM titles").fetchone()
    assert placed(conn)["Northern Lights {tmdb-7206}.mkv"][0] == "sure"
    assert (title["tmdb_id"], title["year"]) == (7206, 1987)
    assert not [path for path in web.paths() if "/search/" in path]  # looked up by its id alone


def test_a_shows_folder_that_gives_tmdbs_id_tells_a_series_from_its_remake(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(
        conn, root, ["TV/The Harbour Line {tmdb-4199}/The Harbour Line - S01E02.mkv"], minutes=45
    )

    identify(keyed, conn, internet(shows={4199: HARBOUR_1985}))

    title = conn.execute("SELECT tmdb_id, year FROM titles").fetchone()
    assert placed(conn)["The Harbour Line - S01E02.mkv"] == (
        "sure",
        "The Harbour Line",
        "series",
        1,
        2,
    )
    assert (title["tmdb_id"], title["year"]) == (4199, 1985)


def test_a_tmdb_id_in_a_name_is_the_show_or_film_of_that_number_its_names_fit(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    # TMDB numbers its shows and its films apart, so 7102 is a show's number as well as Starfall
    # II's. Without its year the name reads like an episode's, but the show numbered 7102 is no
    # Starfall: the film is the one.
    library(conn, root, ["Movies/Starfall 2 {tmdb-7102}.mkv"], minutes=124)
    other = tv_details(7102, "Quiet Waters", (5,), first_aired=date(2003, 1, 6))

    identify(keyed, conn, internet(shows={7102: other}))

    title = conn.execute("SELECT tmdb_type, tmdb_id, name FROM titles").fetchone()
    assert placed(conn)["Starfall 2 {tmdb-7102}.mkv"][0] == "sure"
    assert tuple(title) == ("movie", 7102, "Starfall II")


def test_a_tmdb_id_whose_show_and_film_are_both_other_titles_is_left_for_a_search(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    # A slip of the id: 7101 is the film Starfall, and a show called Quiet Waters. The name is
    # searched for instead.
    library(
        conn,
        root,
        ["TV/The Harbour Line (2019) {tmdb-7101}/Season 01/The Harbour Line - S01E02.mkv"],
        minutes=45,
    )
    other = tv_details(7101, "Quiet Waters", (5,), first_aired=date(2003, 1, 6))

    identify(keyed, conn, internet(shows={7101: other}))

    assert placed(conn)["The Harbour Line - S01E02.mkv"] == (
        "sure",
        "The Harbour Line",
        "series",
        1,
        2,
    )


def test_a_special_named_after_its_show_lands_on_the_special_of_its_name(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(
        conn,
        root,
        [
            "TV/Quiet Hours/Quiet Hours - S01E01.mkv",
            "TV/Quiet Hours/Quiet Hours - Christmas Special.mkv",
        ],
        minutes=30,
    )

    identify(keyed, conn, internet())

    assert placed(conn)["Quiet Hours - Christmas Special.mkv"] == (
        "sure",
        "Quiet Hours",
        "series",
        0,
        1,
    )


def test_a_british_series_and_episode_land_in_that_season(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    name = "Glass Orchard - Series 2 - Episode 1.mkv"
    library(conn, root, [f"TV/Glass Orchard/Series 2/{name}"], minutes=45)

    identify(keyed, conn, internet())

    assert placed(conn)[name] == ("sure", "Glass Orchard", "series", 2, 1)


def test_a_burnt_discs_film_is_offered_but_never_taken(
    keyed: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["Burnt/NORTHERN_LIGHTS/VIDEO_TS/VTS_01_1.VOB"], minutes=97)

    identify(keyed, conn, internet())

    row = conn.execute("SELECT matched, title_id, guesses FROM files").fetchone()
    assert (row["matched"], row["title_id"]) == ("unsure", None)
    assert json.loads(row["guesses"])[0]["title"] == "Northern Lights"
