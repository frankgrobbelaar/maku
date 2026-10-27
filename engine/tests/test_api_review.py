"""Files waiting for a match: TMDB searched, the owner's choice, pinned, and "not a series or
film"."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from maku.config import DataPaths
from tests.fake_web import FakeWeb
from tests.services import internet, with_key
from tests.shelf import identify, library


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "Videos"


@pytest.fixture
def waiting(paths: DataPaths, conn: sqlite3.Connection, root: Path, web: FakeWeb) -> FakeWeb:
    """Four [subs] episodes in Downloads that Maku couldn't name, as on the design's board."""
    with_key(paths)
    library(conn, root, [f"Downloads/[subs] ep0{n} final.mkv" for n in (3, 4, 5, 6)])
    identify(paths, conn, internet())
    web.answers.update(internet().answers)
    return web


def test_the_files_maku_couldnt_name_wait_with_their_facts(client: TestClient, waiting: FakeWeb):
    found = client.get("/review").json()

    assert [f["episode"] for f in found] == [3, 4, 5, 6]
    first = found[0]
    assert (first["group"], first["kind"], first["height"], first["codec"]) == (
        "subs",
        "episode",
        540,
        "hevc",
    )
    assert first["audio"] == ["jpn"]
    assert len(first["alike"]) == 3  # the other [subs] files beside it


def test_searching_tmdb_scores_its_shows_and_films_against_the_file(
    client: TestClient, waiting: FakeWeb
):
    [first, *_] = client.get("/review").json()

    found = client.get(f"/review/{first['id']}/search", params={"q": "Glass Orchard"}).json()

    assert (found[0]["entryId"], found[0]["title"], found[0]["kind"]) == (
        4102,
        "Glass Orchard",
        "series",
    )
    assert found[0]["cover"] == "/poster-4102.jpg"
    assert 0 <= found[0]["confidence"] <= 100


def test_searching_by_a_name_tmdb_knows_in_another_language_finds_it(
    client: TestClient, waiting: FakeWeb
):
    [first, *_] = client.get("/review").json()

    found = client.get(f"/review/{first['id']}/search", params={"q": "La Ligne du Port"}).json()

    assert found[0]["title"] == "The Harbour Line"
    assert found[0]["reasons"][0] == "Title matches"


def test_without_a_key_a_search_says_what_maku_needs(
    client: TestClient, waiting: FakeWeb, paths: DataPaths
):
    (paths.root / "credentials.json").unlink()
    [first, *_] = client.get("/review").json()

    answer = client.get(f"/review/{first['id']}/search", params={"q": "Glass Orchard"})

    assert answer.status_code == 409
    assert answer.json()["detail"].startswith("Maku needs your TMDB key")


def test_the_owners_choice_places_the_files_and_sticks(
    client: TestClient, waiting: FakeWeb, paths: DataPaths, conn: sqlite3.Connection
):
    [first, *_] = client.get("/review").json()

    answer = client.post(
        f"/review/{first['id']}", json={"entryId": 4102, "kind": "episode", "also": first["alike"]}
    )

    assert answer.json()["placed"] == 4
    rows = conn.execute(
        "SELECT episode, season, matched, pinned FROM files ORDER BY episode"
    ).fetchall()
    assert [tuple(row) for row in rows] == [(n, 1, "sure", 1) for n in (3, 4, 5, 6)]
    assert client.get("/review").json() == []

    identify(paths, conn, internet())  # a rescan
    assert conn.execute("SELECT COUNT(*) FROM files WHERE pinned = 1").fetchone()[0] == 4


def test_a_choice_maku_cant_place_asks_which_episode(
    client: TestClient, paths: DataPaths, conn: sqlite3.Connection, root: Path, web: FakeWeb
):
    with_key(paths)
    library(conn, root, ["Burnt/ORCHARD_DISC2/VIDEO_TS/VTS_01_1.VOB"])
    identify(paths, conn, internet())
    web.answers.update(internet().answers)
    [found] = client.get("/review").json()

    answer = client.post(f"/review/{found['id']}", json={"entryId": 4102, "kind": "episode"})

    assert answer.status_code == 422
    assert answer.json()["detail"].startswith("Which episode is it?")
    assert len(client.get("/review").json()) == 1

    answer = client.post(
        f"/review/{found['id']}", json={"entryId": 4102, "kind": "episode", "episode": 15}
    )

    assert answer.json()["placed"] == 1
    row = conn.execute("SELECT season, episode, pinned FROM files").fetchone()
    assert tuple(row) == (2, 3, 1)


def test_a_film_chosen_for_a_file_is_its_own_title(
    client: TestClient, paths: DataPaths, conn: sqlite3.Connection, root: Path, web: FakeWeb
):
    with_key(paths)
    library(conn, root, ["Burnt/NORTHERN_LIGHTS/VIDEO_TS/VTS_01_1.VOB"], minutes=97)
    identify(paths, conn, internet())
    web.answers.update(internet().answers)
    [found] = client.get("/review").json()

    answer = client.post(f"/review/{found['id']}", json={"entryId": -7202, "kind": "movie"})

    assert answer.json()["placed"] == 1
    assert client.get(f"/titles/{answer.json()['titleId']}").json()["name"] == "Northern Lights"


def test_a_titles_match_changes_for_all_its_files_at_once(
    client: TestClient, paths: DataPaths, conn: sqlite3.Connection, root: Path, web: FakeWeb
):
    with_key(paths)
    library(conn, root, [f"Harbour/The Harbour Line - S01E0{n}.mkv" for n in (1, 2, 3)], 45)
    identify(paths, conn, internet())
    web.answers.update(internet().answers)
    [harbour] = [row[0] for row in conn.execute("SELECT id FROM titles")]

    [first] = client.get("/review", params={"title": harbour}).json()
    answer = client.post(
        f"/review/{first['id']}", json={"entryId": 4102, "kind": "episode", "title": harbour}
    )

    assert (first["episode"], len(first["alike"]), first["guesses"][0]["title"]) == (
        1,
        2,
        "The Harbour Line",
    )
    assert (answer.json()["placed"], answer.json()["waiting"]) == (3, 0)
    moved_to = answer.json()["titleId"]
    rows = conn.execute("SELECT title_id, season, episode, pinned FROM files ORDER BY episode")
    assert [tuple(row) for row in rows] == [(moved_to, 1, n, 1) for n in (1, 2, 3)]
    assert client.get(f"/titles/{moved_to}").json()["name"] == "Glass Orchard"
    assert client.get("/review", params={"title": harbour}).json() == []


def test_not_a_series_or_film_is_left_out_for_good(
    client: TestClient, waiting: FakeWeb, conn: sqlite3.Connection
):
    [first, *_] = client.get("/review").json()

    assert client.post(f"/review/{first['id']}/ignore").status_code == 204

    assert len(client.get("/review").json()) == 3
    row = conn.execute("SELECT matched, pinned FROM files WHERE id = ?", (first["id"],)).fetchone()
    assert tuple(row) == ("ignored", 1)


def test_whats_set_aside_is_listed_and_can_wait_for_a_match_again(
    client: TestClient, waiting: FakeWeb, conn: sqlite3.Connection
):
    [first, *_] = client.get("/review").json()
    client.post(f"/review/{first['id']}/ignore")

    [listed] = client.get("/review/ignored").json()
    assert (listed["id"], listed["path"], listed["size"]) == (
        first["id"],
        first["path"],
        first["size"],
    )
    assert client.delete(f"/review/{first['id']}/ignore").status_code == 204

    assert client.get("/review/ignored").json() == []
    assert first["id"] in [f["id"] for f in client.get("/review").json()]
    row = conn.execute(
        "SELECT matched, pinned, identified_at FROM files WHERE id = ?", (first["id"],)
    ).fetchone()
    assert tuple(row) == ("none", 0, None)  # looked up afresh at the next scan


def test_offline_a_choice_changes_nothing_and_says_so(
    client: TestClient, waiting: FakeWeb, conn: sqlite3.Connection
):
    [first, *_] = client.get("/review").json()
    waiting.offline = True

    answer = client.post(f"/review/{first['id']}", json={"entryId": 4102})

    assert answer.status_code == 503
    assert answer.json()["detail"].endswith("Nothing was changed; try again in a moment.")
    assert conn.execute("SELECT COUNT(*) FROM files WHERE pinned = 1").fetchone()[0] == 0


def test_a_show_tmdb_no_longer_has_changes_nothing_and_says_so(
    client: TestClient, waiting: FakeWeb, conn: sqlite3.Connection
):
    [first, *_] = client.get("/review").json()

    answer = client.post(f"/review/{first['id']}", json={"entryId": 999999})

    assert (answer.status_code, answer.json()["detail"]) == (
        404,
        "TMDB no longer has that show or film.",
    )


def test_a_titles_specials_keep_their_kind_and_files_that_dont_fit_wait(
    client: TestClient, paths: DataPaths, conn: sqlite3.Connection, root: Path, web: FakeWeb
):
    with_key(paths)
    names = ["Glass Orchard - SP02.mkv", "Glass Orchard - 01.mkv", "Glass Orchard - 02.mkv"]
    library(conn, root, [f"Orchard/{name}" for name in names], minutes=45)
    identify(paths, conn, internet())
    web.answers.update(internet().answers)
    orchard = conn.execute("SELECT title_id FROM files WHERE path LIKE '%- 01.mkv'").fetchone()[0]
    with conn:  # the special, placed by the owner earlier
        conn.execute(
            """UPDATE files SET title_id = ?, season = 0, episode = 2, matched = 'sure',
                      pinned = 1
               WHERE path LIKE '%SP02.mkv'""",
            (orchard,),
        )

    [first] = client.get("/review", params={"title": orchard}).json()
    answer = client.post(
        f"/review/{first['id']}", json={"entryId": 4101, "kind": "episode", "title": orchard}
    ).json()

    assert (first["kind"], first["episode"], len(first["alike"])) == ("episode", 1, 2)
    assert (answer["placed"], answer["waiting"]) == (2, 1)
    rows = conn.execute("SELECT path, title_id, season, episode, matched FROM files ORDER BY path")
    assert [(Path(row[0]).name, *tuple(row)[1:]) for row in rows] == [
        ("Glass Orchard - 01.mkv", answer["titleId"], 1, 1, "sure"),
        ("Glass Orchard - 02.mkv", answer["titleId"], 1, 2, "sure"),
        ("Glass Orchard - SP02.mkv", None, None, None, "unsure"),  # The Harbour Line has one
    ]
    [left] = client.get("/review").json()
    assert Path(left["path"]).name == "Glass Orchard - SP02.mkv"


def test_a_file_from_another_title_cant_change_this_ones_match(
    client: TestClient, paths: DataPaths, conn: sqlite3.Connection, root: Path, web: FakeWeb
):
    with_key(paths)
    library(
        conn,
        root,
        ["Harbour/The Harbour Line - S01E01.mkv", "Orchard/Glass Orchard - S01E01.mkv"],
        minutes=45,
    )
    identify(paths, conn, internet())
    web.answers.update(internet().answers)
    [(harbour, _), (_, orchard_file)] = conn.execute(
        "SELECT title_id, id FROM files ORDER BY path"
    ).fetchall()

    answer = client.post(
        f"/review/{orchard_file}", json={"entryId": 4102, "kind": "episode", "title": harbour}
    )

    assert answer.status_code == 404
