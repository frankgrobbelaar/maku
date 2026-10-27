"""Tidying up through the API: the proposal, applying it, History, and undoing it."""

import sqlite3
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maku.api import create_app
from maku.config import DataPaths
from maku.scan import ScanBusyError, Scanner, ScanStatus
from tests.conftest import TOKEN
from tests.services import internet, with_key
from tests.shelf import identify, library


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "Videos"


@pytest.fixture
def mixed(paths: DataPaths, conn: sqlite3.Connection, root: Path) -> sqlite3.Connection:
    """Downloads holding two series, one episode twice, and a file that waits for a match."""
    library(
        conn,
        root,
        [
            "Downloads/The Harbour Line - 01.mkv",
            "Downloads/The Harbour Line - 01 (copy).mkv",
            "Downloads/Glass Orchard - 015.mkv",
            "Downloads/Mystery Show - 03.mkv",
        ],
        minutes=45,
    )
    identify(with_key(paths), conn, internet())
    return conn


def test_maku_proposes_and_counts_what_waits(client: TestClient, mixed: sqlite3.Connection):
    proposal = client.get("/tidy").json()

    # The copies set aside first, then the moves by where they go.
    assert [(c["kind"], c["category"], c["title"], c["label"]) for c in proposal["changes"]] == [
        (
            "quarantine",
            "duplicate",
            "The Harbour Line",
            "The Harbour Line · S01E01 · duplicate",
        ),
        ("move", "mixed", "Glass Orchard", "Glass Orchard · S02E03"),
        ("move", "mixed", "The Harbour Line", "The Harbour Line · S01E01"),
    ]
    [duplicate] = proposal["duplicates"]
    assert duplicate["keep"]["path"].endswith("The Harbour Line - 01.mkv")
    assert (duplicate["keep"]["height"], duplicate["keep"]["plays"]) == (540, True)
    assert (proposal["waiting"], proposal["broken"]) == (1, 0)


def test_the_english_of_the_copy_set_aside_can_go_into_the_one_kept(
    client: TestClient, mixed: sqlite3.Connection
):
    with mixed:  # the copy has English sound the better one hasn't
        mixed.execute(
            """UPDATE files SET probe = json_insert(probe, '$.streams[#]',
                   json('{"index": 2, "codec_type": "audio", "codec_name": "aac",
                          "channels": 2, "tags": {"language": "eng"}}'))
               WHERE path LIKE '%(copy).mkv'"""
        )
        mixed.execute(
            """UPDATE files SET probe = json_set(probe, '$.streams[0].height', 1080)
               WHERE path LIKE '%Line - 01.mkv'"""
        )
    proposal = client.get("/tidy").json()
    [duplicate] = proposal["duplicates"]
    english = duplicate["english"]
    assert english["other"].endswith("The Harbour Line - 01 (copy).mkv")
    assert (english["sound"], english["subtitles"], english["tried"]) == (True, False, None)
    changes = [c for c in proposal["changes"] if c["kind"] == "move"]

    done = client.post(
        "/tidy", json={"changes": changes, "english": [duplicate["keep"]["path"]]}
    ).json()

    assert (done["moved"], done["quarantined"], done["english"]) == (2, 0, 1)
    [waiting] = client.get("/queue").json()["queued"]
    assert (waiting["kind"], waiting["label"]) == ("merge", "The Harbour Line · S01E01")
    assert client.get("/tidy").json()["duplicates"] == []


def test_a_name_another_file_has_gets_2_and_the_proposal_says_so(
    client: TestClient, mixed: sqlite3.Connection, root: Path
):
    [_, _, pilot] = client.get("/tidy").json()["changes"]
    assert (pilot["taken"], pilot["compared"]) == (False, None)
    there = Path(pilot["target"]).relative_to(root)
    library(mixed, root, [str(there)])  # another file at that name, not this episode

    [_, _, pilot] = client.get("/tidy").json()["changes"]

    assert pilot["taken"] is True
    assert Path(pilot["target"]).name.endswith(" (2).mkv")
    assert pilot["video"] == pilot["source"]
    compared = pilot["compared"]  # the file there, and this one
    assert compared["there"]["path"] == str(root / there)
    assert (compared["there"]["height"], compared["there"]["plays"]) == (540, True)
    assert compared["coming"]["path"] == pilot["source"]
    assert compared["thereGoes"] == "stays"


def test_comparing_says_when_the_file_at_the_name_moves_too(
    client: TestClient, mixed: sqlite3.Connection, root: Path
):
    [_, orchard, pilot] = client.get("/tidy").json()["changes"]
    there = Path(pilot["target"]).relative_to(root)
    library(mixed, root, [str(there)])
    with mixed:  # the file there, matched to another episode by hand, goes to its own name
        mixed.execute(
            """UPDATE files SET title_id = (SELECT title_id FROM files WHERE path = ?),
                      season = 2, episode = 4, matched = 'sure', pinned = 1
               WHERE path = ?""",
            (orchard["source"], str(root / there)),
        )

    [pilot] = [c for c in client.get("/tidy").json()["changes"] if c["source"] == pilot["source"]]

    assert pilot["taken"] is True
    assert pilot["compared"]["thereGoes"] == "leaves"


def reviewed(changes: list[dict[str, str]]) -> list[dict[str, str]]:
    """The changes as the owner saw them, which is what applying sends."""
    return [{key: change[key] for key in ("source", "kind", "target")} for change in changes]


def test_applying_lists_the_plan_in_history_and_undo_puts_it_back(
    client: TestClient, mixed: sqlite3.Connection, root: Path
):
    changes = reviewed(client.get("/tidy").json()["changes"])

    done = client.post("/tidy", json={"changes": changes}).json()

    assert (done["moved"], done["quarantined"], done["problems"]) == (2, 1, [])
    assert client.get("/tidy").json()["changes"] == []
    [plan] = client.get("/history").json()["plans"]
    assert plan["id"] == done["planId"]
    assert plan["title"] == "Tidied 3 files: The Harbour Line and Glass Orchard"
    assert (plan["moved"], plan["quarantined"], plan["undoneAt"]) == (2, 1, None)

    # A search finds it by any of its files, and nothing else.
    [found] = client.get("/history", params={"q": "harbour 01"}).json()["plans"]
    assert found["id"] == done["planId"]
    assert client.get("/history", params={"q": "Quiet Hours"}).json()["plans"] == []

    back = client.post(f"/plans/{done['planId']}/undo").json()

    assert (back["moved"], back["quarantined"]) == (2, 1)
    assert (root / "Downloads" / "The Harbour Line - 01 (copy).mkv").exists()
    [plan] = client.get("/history").json()["plans"]
    assert plan["undoneAt"] is not None
    assert plan["undone"] == 3


def test_history_pages_by_days_and_clears_what_the_owner_lets_go(
    client: TestClient, conn: sqlite3.Connection
):
    with conn:
        for days_ago in range(8, -1, -1):  # a scan a day for nine days, the latest today
            at = (datetime.now().astimezone() - timedelta(days=days_ago)).isoformat()
            conn.execute(
                "INSERT INTO scans (started_at, finished_at, state, stage)"
                " VALUES (?, ?, 'done', 'done')",
                (at, at),
            )

    first = client.get("/history").json()
    assert len(first["scans"]) == 7
    rest = client.get("/history", params={"before": first["older"]}).json()
    assert (len(rest["scans"]), rest["older"]) == (2, None)
    assert client.get("/history", params={"before": "last week"}).status_code == 422

    cleared = client.post("/history/clear", json={"keep": "week"}).json()

    assert cleared == {"cleared": 2}
    assert client.post("/history/clear", json={"keep": "nothing"}).json() == {"cleared": 6}
    [latest] = client.get("/history").json()["scans"]  # the latest scan stays: Home tells of it
    assert latest["id"] == 9
    assert client.post("/history/clear", json={"keep": "year"}).status_code == 422


def test_a_copys_subtitles_go_with_it_and_count_as_no_copy_of_their_own(
    client: TestClient, mixed: sqlite3.Connection, root: Path
):
    (root / "Downloads" / "The Harbour Line - 01 (copy).en.srt").write_text("1", encoding="utf-8")
    changes = reviewed(client.get("/tidy").json()["changes"])

    done = client.post("/tidy", json={"changes": changes}).json()

    assert len(changes) == 4
    assert (done["moved"], done["quarantined"]) == (2, 1)
    [plan] = client.get("/history").json()["plans"]
    assert (plan["moved"], plan["quarantined"]) == (2, 1)


def test_the_owner_can_keep_the_other_copy(client: TestClient, mixed: sqlite3.Connection):
    copied = next(
        c["source"] for c in client.get("/tidy").json()["changes"] if c["kind"] == "quarantine"
    )

    proposal = client.get("/tidy", params={"keep": copied}).json()
    kept = [c for c in proposal["changes"] if c["source"] == copied]
    done = client.post("/tidy", json={"changes": reviewed(kept), "keep": [copied]}).json()

    assert proposal["duplicates"][0]["keep"]["path"] == copied
    assert done["moved"] == 1


def test_an_unknown_plan_cant_be_undone(client: TestClient, conn: sqlite3.Connection):
    assert client.post("/plans/99/undo").status_code == 404


class Busy:
    """A scanner in the middle of a scan."""

    def status(self) -> ScanStatus:
        return ScanStatus("running", "reading", None, None, 3, 3, 1, 0, None, None, (), None)

    def recover(self) -> None:
        pass

    def hold(self) -> AbstractContextManager[None]:
        raise ScanBusyError


@pytest.fixture
def scanning(paths: DataPaths) -> Iterator[TestClient]:
    app = create_app(TOKEN, paths, scanner=cast("Scanner", Busy()))
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
        yield client


def test_nothing_moves_while_a_scan_runs(scanning: TestClient, conn: sqlite3.Connection):
    move = {"source": "D:/Videos/a.mkv", "kind": "move", "target": "D:/Videos/TV/a.mkv"}

    answer = scanning.post("/tidy", json={"changes": [move]})

    assert answer.status_code == 409
    assert answer.json()["detail"] == (
        "A scan is running. Tidy up once it's done, so Maku knows every file."
    )


def test_changes_maku_no_longer_proposes_are_never_made(
    client: TestClient, mixed: sqlite3.Connection, root: Path
):
    changes = reviewed(client.get("/tidy").json()["changes"])
    changes[2]["target"] = str(root / "Somewhere else.mkv")

    answer = client.post("/tidy", json={"changes": changes})

    assert answer.status_code == 409
    assert answer.json()["detail"] == (
        "Maku's proposal changed since you looked at it. Look it over again before applying."
    )
    assert (root / "Downloads" / "The Harbour Line - 01.mkv").exists()
    assert (root / "Downloads" / "The Harbour Line - 01 (copy).mkv").exists()


def test_a_tidy_up_not_all_put_back_can_be_undone_again(
    client: TestClient, mixed: sqlite3.Connection, root: Path
):
    changes = reviewed(client.get("/tidy").json()["changes"])
    done = client.post("/tidy", json={"changes": changes}).json()
    blocker = root / "Downloads" / "Glass Orchard - 015.mkv"
    blocker.write_bytes(b"a new file with the old name")

    back = client.post(f"/plans/{done['planId']}/undo").json()

    assert (back["moved"], back["quarantined"]) == (1, 1)
    assert [problem["label"] for problem in back["problems"]] == ["Glass Orchard · S02E03"]
    [plan] = client.get("/history").json()["plans"]
    assert (plan["undoneAt"], plan["moved"], plan["undone"]) == (None, 1, 2)
    blocker.unlink()

    again = client.post(f"/plans/{done['planId']}/undo").json()

    assert (again["moved"], again["quarantined"], again["problems"]) == (1, 0, [])
    [plan] = client.get("/history").json()["plans"]
    assert plan["undoneAt"] is not None


def test_videos_on_a_drive_that_isnt_there_stay_put(
    client: TestClient, mixed: sqlite3.Connection, root: Path, tmp_path: Path
):
    root.rename(tmp_path / "Unplugged")

    proposal = client.get("/tidy").json()

    assert proposal["changes"] == []
    assert {(Path(s["path"]).name, s["reason"]) for s in proposal["skipped"]} == {
        ("The Harbour Line - 01.mkv", "Its library folder isn't connected"),
        ("The Harbour Line - 01 (copy).mkv", "Its library folder isn't connected"),
        ("Glass Orchard - 015.mkv", "Its library folder isn't connected"),
    }


def test_no_scan_starts_while_maku_moves_files(client: TestClient, conn: sqlite3.Connection):
    scanner = cast("Scanner", cast("FastAPI", client.app).state.scanner)

    with scanner.hold():
        answer = client.post("/scan")

    assert answer.status_code == 409
    assert answer.json()["detail"] == "Maku is moving files. Scan once they're in place."


EPISODE = "Quiet Hours (2015)/Quiet Hours (2015) - S01E01.mkv"


def test_videos_deleted_go_to_quarantine_and_history_puts_them_back(
    client: TestClient, conn: sqlite3.Connection, root: Path
):
    library(conn, root, [EPISODE])
    episode = root / "Quiet Hours (2015)" / "Quiet Hours (2015) - S01E01.mkv"

    answer = client.post("/files/delete", json={"files": [1]})

    assert answer.status_code == 200
    assert (answer.json()["quarantined"], answer.json()["moved"]) == (1, 0)
    assert not episode.exists()
    [plan] = client.get("/history").json()["plans"]
    assert (plan["title"], plan["deleted"]) == ("Deleted Quiet Hours (2015) - S01E01", True)
    assert client.post(f"/plans/{plan['id']}/undo").status_code == 200
    assert episode.is_file()


def test_nothing_is_deleted_while_files_move(
    client: TestClient, conn: sqlite3.Connection, root: Path
):
    library(conn, root, [EPISODE])
    scanner = cast("Scanner", cast("FastAPI", client.app).state.scanner)

    with scanner.hold():
        answer = client.post("/files/delete", json={"files": [1]})

    assert answer.status_code == 409
    assert answer.json()["detail"].endswith("Delete it once that's done.")


def test_a_video_being_converted_isnt_deleted_through_the_api(
    client: TestClient, conn: sqlite3.Connection, root: Path
):
    library(conn, root, [EPISODE])
    with conn:
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, state, added_at)"
            " VALUES (1, 'best', 1, 'running', 'now')"
        )

    answer = client.post("/files/delete", json={"files": [1]})

    assert answer.status_code == 409
    assert answer.json()["detail"].startswith("Quiet Hours (2015) - S01E01 is being converted.")
