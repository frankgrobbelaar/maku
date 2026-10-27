"""The library's titles, their gaps and posters through the API, and the reports next to them."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from maku import franchises
from maku.catalog import Catalog
from maku.config import DataPaths
from maku.core.report import GAP_ANALYSIS_FILE
from maku.reports import own_folder, write_reports
from maku.web import Reply
from tests.fake_web import FakeWeb
from tests.services import internet, with_key
from tests.shelf import NOW, identify, library

ORCHARD = [
    f"Glass Orchard (2012)/Season 0{season}/Glass Orchard - S0{season}E{number:02}.mkv"
    for season, size in ((1, 12), (2, 13))
    for number in range(1, size + 1)
    if (season, number) != (2, 3)
]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "Videos"


@pytest.fixture
def identified(paths: DataPaths, conn: sqlite3.Connection, root: Path) -> sqlite3.Connection:
    """Glass Orchard without season 2's third episode, The Harbour Line's first episode, and the
    first and third Starfall films."""
    with_key(paths)
    library(conn, root, [*ORCHARD, "The Harbour Line/The Harbour Line - S01E01.mkv"], minutes=45)
    library(conn, root, ["Movies/Starfall (2008).mkv", "Movies/Starfall Ascent (2015).mkv"], 120)
    identify(paths, conn, internet())
    return conn


def ids(client: TestClient) -> dict[str, int]:
    return {t["name"]: t["id"] for t in client.get("/titles").json()}


def test_titles_list_oldest_release_first(client: TestClient, identified: sqlite3.Connection):
    found = client.get("/titles").json()

    assert [(t["name"], t["kind"], t["released"]) for t in found] == [
        ("Starfall", "movie", "2008-05-02"),
        ("Glass Orchard", "series", "2012-01-10"),
        ("Starfall: Ascent", "movie", "2015-07-17"),
        ("The Harbour Line", "series", "2019-03-04"),
    ]


def test_titles_sort_by_name_too(client: TestClient, identified: sqlite3.Connection):
    found = client.get("/titles", params={"sort": "name"}).json()

    assert [t["name"] for t in found] == [
        "Glass Orchard",
        "Starfall",
        "Starfall: Ascent",
        "The Harbour Line",
    ]


def test_a_title_says_how_much_of_it_is_there(client: TestClient, identified: sqlite3.Connection):
    orchard = next(t for t in client.get("/titles").json() if t["name"] == "Glass Orchard")

    assert (orchard["files"], orchard["aired"], orchard["present"], orchard["missing"]) == (
        24,
        25,
        24,
        1,
    )
    assert orchard["specialsMissing"] == 0
    assert orchard["hasPoster"] is True


def test_one_title_lists_its_seasons_and_the_episode_it_lacks(
    client: TestClient, identified: sqlite3.Connection
):
    detail = client.get(f"/titles/{ids(client)['Glass Orchard']}").json()

    assert detail["seasons"][1] == {"season": 2, "present": 12, "aired": 13, "total": 13}
    assert detail["missingEpisodes"] == [
        {"season": 2, "number": 3, "name": "Episode 3", "aired": "2013-01-22"}
    ]
    assert len(detail["videos"]) == 24


def test_a_titles_videos_say_what_they_can_be_heard_and_read_in(
    client: TestClient, identified: sqlite3.Connection, root: Path
):
    beside = root / "The Harbour Line" / "The Harbour Line - S01E01.en.srt"
    beside.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")

    [video] = client.get(f"/titles/{ids(client)['The Harbour Line']}").json()["videos"]

    assert (video["sound"], video["subtitles"]) == (["jpn"], ["en"])


def test_a_franchise_gathers_the_films_of_a_collection(
    client: TestClient, identified: sqlite3.Connection
):
    found = client.get("/franchises").json()

    assert [(f["name"], [t["name"] for t in f["titles"]]) for f in found] == [
        ("The Starfall Collection", ["Starfall", "Starfall: Ascent"]),
        ("Glass Orchard", ["Glass Orchard"]),
        ("The Harbour Line", ["The Harbour Line"]),
    ]
    starfall = found[0]
    assert starfall["id"] == starfall["titles"][0]["id"]  # led by its first film
    assert starfall["kinds"] == {"series": 0, "movie": 2}
    assert (starfall["released"], starfall["files"]) == ("2008-05-02", 2)


def test_franchises_sort_like_titles(client: TestClient, identified: sqlite3.Connection):
    found = client.get("/franchises", params={"sort": "missing"}).json()

    assert [f["name"] for f in found] == [
        "The Harbour Line",
        "Glass Orchard",
        "The Starfall Collection",
    ]


def test_a_franchise_lists_its_titles_and_a_title_names_its_franchise(
    client: TestClient, identified: sqlite3.Connection
):
    found = ids(client)

    franchise = client.get(f"/franchises/{found['Starfall: Ascent']}", params={"sort": "name"})

    assert franchise.json()["name"] == "The Starfall Collection"
    assert [t["name"] for t in franchise.json()["titles"]] == ["Starfall", "Starfall: Ascent"]
    film = client.get(f"/titles/{found['Starfall: Ascent']}").json()
    assert film["franchise"] == {"id": found["Starfall"], "name": "The Starfall Collection"}
    assert client.get(f"/titles/{found['Glass Orchard']}").json()["franchise"] is None
    assert client.get("/franchises/999").status_code == 404


def test_an_unknown_title_is_404(client: TestClient, conn: sqlite3.Connection):
    assert client.get("/titles/999").status_code == 404


def test_a_poster_is_fetched_once_then_kept(
    client: TestClient, identified: sqlite3.Connection, web: FakeWeb
):
    poster = "GET https://image.tmdb.org/t/p/w342/poster-movie-7101.jpg"
    web.answers[poster] = Reply(200, {}, b"jpeg bytes")

    first = client.get(f"/titles/{ids(client)['Starfall']}/poster")
    again = client.get(f"/titles/{ids(client)['Starfall']}/poster")

    assert (first.status_code, first.content, first.headers["content-type"]) == (
        200,
        b"jpeg bytes",
        "image/jpeg",
    )
    assert again.content == b"jpeg bytes"
    assert web.paths().count(poster) == 1


def test_a_poster_that_cant_be_fetched_is_404(client: TestClient, identified: sqlite3.Connection):
    assert client.get(f"/titles/{ids(client)['Starfall']}/poster").status_code == 404


def test_a_report_goes_next_to_a_show_with_a_folder_of_its_own(
    identified: sqlite3.Connection, root: Path
):
    written = write_reports(identified, now=NOW)

    report = (root / "Glass Orchard (2012)" / GAP_ANALYSIS_FILE).read_text(encoding="utf-8")
    assert report.startswith("# Glass Orchard (2012) — gap analysis\n")
    assert "- Present: **24 of 25** episodes (96%)" in report
    assert (root / "The Harbour Line" / GAP_ANALYSIS_FILE).exists()
    assert written.reports == 2
    assert written.problems == ()


def test_no_report_goes_into_a_library_folder_or_a_shared_one(
    paths: DataPaths, conn: sqlite3.Connection, root: Path
):
    with_key(paths)
    library(
        conn,
        root,
        [
            "Glass Orchard - S01E01.mkv",
            "Mixed/Glass Orchard - S01E02.mkv",
            "Mixed/The Harbour Line - S01E01.mkv",
        ],
        minutes=45,
    )
    identify(paths, conn, internet())
    roots = [root]

    found = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM titles")}

    assert own_folder(conn, found["Glass Orchard"], roots) is None  # spread over two folders
    assert own_folder(conn, found["The Harbour Line"], roots) is None  # shares Mixed
    assert write_reports(conn, now=NOW).reports == 0
    assert not list(root.rglob(GAP_ANALYSIS_FILE))


def test_season_folders_named_any_way_belong_to_their_show(
    paths: DataPaths, conn: sqlite3.Connection, root: Path
):
    with_key(paths)
    library(
        conn,
        root,
        [
            "Glass Orchard (2012)/S01/Glass Orchard - S01E01.mkv",
            "Glass Orchard (2012)/Season_02/Glass Orchard - S02E01.mkv",
        ],
        minutes=45,
    )
    identify(paths, conn, internet())

    assert write_reports(conn, now=NOW).reports == 1
    assert [p.relative_to(root) for p in root.rglob(GAP_ANALYSIS_FILE)] == [
        Path("Glass Orchard (2012)") / GAP_ANALYSIS_FILE
    ]


def test_an_unchanged_report_isnt_written_again(identified: sqlite3.Connection, root: Path):
    write_reports(identified, now=NOW)
    report = root / "Glass Orchard (2012)" / GAP_ANALYSIS_FILE
    before = report.stat().st_mtime_ns

    again = write_reports(identified, now=NOW.replace(hour=11))

    assert again.reports == 0
    assert report.stat().st_mtime_ns == before


def test_a_picture_from_tmdb_is_fetched_once_then_kept(client: TestClient, web: FakeWeb):
    picture = "https://image.tmdb.org/t/p/w342/poster-4101.png"
    web.answers[f"GET {picture}"] = Reply(200, {}, b"png bytes")

    first = client.get("/artwork", params={"address": "/poster-4101.png"})
    again = client.get("/artwork", params={"address": picture})

    assert (first.status_code, first.content, first.headers["content-type"]) == (
        200,
        b"png bytes",
        "image/png",
    )
    assert again.content == b"png bytes"
    assert web.paths().count(f"GET {picture}") == 1


def test_a_picture_from_anywhere_else_is_refused_unasked(client: TestClient, web: FakeWeb):
    for address in (
        "https://example.org/tracker.png",
        "https://image.tmdb.org.example.net/cover.png",
    ):
        assert client.get("/artwork", params={"address": address}).status_code == 404
    assert web.asked == []


def test_a_report_says_the_time_on_this_pc(identified: sqlite3.Connection, root: Path):
    # The scan's clock is UTC; the report is read by a person, in their own time.
    write_reports(identified, now=NOW)

    report = (root / "Glass Orchard (2012)" / GAP_ANALYSIS_FILE).read_text(encoding="utf-8")
    local = NOW.astimezone()
    assert f"_Updated {local.day} Oct {local.year}, {local:%H:%M} · library" in report


def test_one_title_has_every_episode_with_its_state_for_the_map(
    client: TestClient, identified: sqlite3.Connection, root: Path
):
    detail = client.get(f"/titles/{ids(client)['Glass Orchard']}").json()

    states = {(e["season"], e["number"]): e["state"] for e in detail["episodes"]}
    assert len(states) == 25
    assert states[(2, 3)] == "missing"
    assert states[(1, 1)] == "ready"  # 720x540 HEVC 10-bit in MKV: nothing is made bigger
    assert detail["folder"] == str(root / "Glass Orchard (2012)")


def test_a_titles_report_can_be_read_once_its_written(
    client: TestClient, identified: sqlite3.Connection, root: Path
):
    orchard = ids(client)["Glass Orchard"]
    assert client.get(f"/titles/{orchard}/report").status_code == 404  # not written yet

    write_reports(identified, now=NOW)
    report = client.get(f"/titles/{orchard}/report").json()

    assert report["path"] == str(root / "Glass Orchard (2012)" / GAP_ANALYSIS_FILE)
    assert report["text"].startswith("# Glass Orchard (2012) — gap analysis")


def test_franchises_form_again_when_maku_lost_their_links(
    client: TestClient, identified: sqlite3.Connection, paths: DataPaths
):
    with identified:
        identified.execute("DELETE FROM entry_links")
        identified.execute("DELETE FROM entries")
    assert [len(f["titles"]) for f in client.get("/franchises").json()] == [1, 1, 1, 1]

    identify(paths, identified, internet())  # the next scan

    assert [len(f["titles"]) for f in client.get("/franchises").json()] == [2, 1, 1]


def test_a_franchise_says_what_the_library_has_no_part_of(
    client: TestClient, identified: sqlite3.Connection, paths: DataPaths
):
    found = ids(client)
    before = client.get(f"/franchises/{found['Starfall']}/missing").json()
    assert before == {"titles": [], "looking": True}  # the others are only links so far

    catalog = Catalog(paths, internet())
    while franchises.look_up(identified, catalog, NOW):
        pass
    missing = client.get(f"/franchises/{found['Starfall: Ascent']}/missing").json()

    assert missing["looking"] is False
    assert [
        (t["entryId"], t["name"], t["kind"], t["released"], t["coming"], t["tmdbId"])
        for t in missing["titles"]
    ] == [
        (-7102, "Starfall II", "movie", "2011-06-10", False, 7102),
        (-7104, "Starfall: Origins", "movie", "2027-11-19", True, 7104),
    ]
    assert missing["titles"][0]["cover"] == "/poster-movie-7102.jpg"
    assert missing["titles"][0]["tmdbType"] == "movie"
    assert client.get("/franchises/999/missing").status_code == 404


def test_a_title_says_what_its_about_panel_shows(
    client: TestClient, identified: sqlite3.Connection
):
    harbour = ids(client)["The Harbour Line"]

    about = client.get(f"/titles/{harbour}").json()["about"]

    assert about["overview"].startswith("A harbour pilot keeps")
    assert about["genres"] == ["Drama", "Crime"]
    assert (about["studio"], about["status"], about["minutes"]) == ("Northwind", "airing", 45)
    assert about["started"] == "2019-03-04"
    assert (about["tmdbType"], about["tmdbId"]) == ("tv", 4101)
    assert "entryId" not in about
    assert client.get(f"/titles/{harbour}/about").json() == about
    assert client.get("/titles/999/about").status_code == 404


def test_a_film_has_no_end_and_its_own_length(client: TestClient, identified: sqlite3.Connection):
    about = client.get(f"/titles/{ids(client)['Starfall']}/about").json()

    assert (about["started"], about["ended"], about["minutes"]) == ("2008-05-02", None, 118)
    assert (about["tmdbType"], about["tmdbId"]) == ("movie", 7101)
