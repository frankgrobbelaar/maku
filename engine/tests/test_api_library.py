"""The library and scan routes: adding folders, scanning them, and the library at a glance."""

import itertools
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from maku.api import create_app
from maku.config import DataPaths
from maku.scan import Scanner
from maku.tools import Tools
from tests.conftest import TOKEN
from tests.fake_ffprobe import REPORT
from tests.fake_web import FakeWeb

START = datetime(2026, 10, 11, 9, 30, tzinfo=UTC)


@pytest.fixture
def scanner(paths: DataPaths) -> Scanner:
    seconds = itertools.count(1)
    return Scanner(
        paths,
        Tools(paths, items=()),
        read=lambda _: REPORT,
        now=lambda: START + timedelta(seconds=next(seconds)),
        transport=FakeWeb(),
    )


@pytest.fixture
def api(paths: DataPaths, scanner: Scanner) -> Iterator[TestClient]:
    app = create_app(TOKEN, paths, Tools(paths, items=()), scanner)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
        yield client


def test_a_new_library_has_no_folders_and_has_never_been_scanned(api: TestClient):
    assert api.get("/folders").json() == []
    assert api.get("/scan").json()["state"] == "idle"
    assert api.get("/library").json() == {
        "folders": 0,
        "files": 0,
        "size": 0,
        "unread": 0,
        "problems": 0,
        "sd": 0,
        "hd720": 0,
        "hd1080": 0,
        "larger": 0,
    }


def test_adding_a_folder_then_scanning_fills_the_library(
    api: TestClient, scanner: Scanner, videos: Path
):
    added = api.post("/folders", json={"path": str(videos)})
    assert added.status_code == 201
    assert added.json()["path"] == str(videos)
    assert added.json()["files"] == 0

    started = api.post("/scan")
    scanner.wait(timeout=10)

    assert started.status_code == 202
    scan = api.get("/scan").json()
    assert (scan["state"], scan["found"], scan["read"], scan["toRead"]) == ("done", 3, 3, 3)
    [folder] = api.get("/folders").json()
    assert (folder["files"], folder["unread"], folder["problems"], folder["available"]) == (
        3,
        0,
        0,
        True,
    )
    library = api.get("/library").json()
    assert (library["folders"], library["files"], library["sd"]) == (1, 3, 3)
    files = [
        videos / "Northern Lights 2004.avi",
        videos / "Downloads" / "Glass.Orchard.S01E01.720p.HDTV.x264-GRP.MKV",
        videos / "The Harbour Line" / "The Harbour Line - S01E01 - Pilot.mkv",
    ]
    assert library["size"] == sum(video.stat().st_size for video in files)


def test_a_folder_that_cant_be_added_says_why(api: TestClient, videos: Path):
    api.post("/folders", json={"path": str(videos)})

    again = api.post("/folders", json={"path": str(videos)})
    blank = api.post("/folders", json={"path": "  "})

    assert again.status_code == 400
    assert again.json() == {"detail": f"{videos} is already in your library."}
    assert blank.json() == {"detail": "Choose a folder to add."}


def test_forgetting_a_folder_leaves_its_files_alone(api: TestClient, videos: Path):
    folder = api.post("/folders", json={"path": str(videos)}).json()

    assert api.delete(f"/folders/{folder['id']}").status_code == 204
    assert api.delete(f"/folders/{folder['id']}").status_code == 404
    assert api.get("/folders").json() == []
    assert (videos / "Northern Lights 2004.avi").exists()


def test_a_scan_can_be_paused_and_resumed_through_the_api(
    api: TestClient, scanner: Scanner, videos: Path
):
    api.post("/folders", json={"path": str(videos)})
    api.post("/scan")
    scanner.wait(timeout=10)

    paused = api.post("/scan/pause")
    resumed = api.post("/scan/resume")
    scanner.wait(timeout=10)

    assert paused.status_code == 202
    assert resumed.status_code == 202
    assert api.get("/scan").json()["state"] == "done"


def test_only_one_scan_at_a_time(
    api: TestClient, scanner: Scanner, videos: Path, monkeypatch: pytest.MonkeyPatch
):
    api.post("/folders", json={"path": str(videos)})
    monkeypatch.setattr(scanner, "_running", lambda: True)

    busy = api.post("/scan")

    assert busy.status_code == 409
    assert busy.json() == {"detail": "A scan is already running."}


@pytest.mark.parametrize(  # converting, or made and waiting for another app to let go of it
    ("state", "retry_at"), [("running", None), ("queued", "2026-10-11T10:05:00+02:00")]
)
def test_a_folder_with_a_file_converting_isnt_forgotten(
    client: TestClient, conn: sqlite3.Connection, videos: Path, state: str, retry_at: str | None
):
    folder = client.post("/folders", json={"path": str(videos)}).json()
    with conn:
        conn.execute(
            """INSERT INTO files (folder_id, path, size, modified, found_at, seen_at)
               VALUES (?, ?, 1, 0, 'now', 'now')""",
            (folder["id"], str(videos / "x.mkv")),
        )
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, state, added_at, retry_at)"
            " VALUES (last_insert_rowid(), 'best', 1, ?, 'now', ?)",
            (state, retry_at),
        )

    answer = client.delete(f"/folders/{folder['id']}")

    assert answer.status_code == 409
    assert answer.json()["detail"] == (
        "A file in it is converting. Forget the folder once that's done, or skip it first."
    )


def test_a_folder_with_a_file_getting_english_subtitles_isnt_forgotten(
    client: TestClient, conn: sqlite3.Connection, videos: Path
):
    folder = client.post("/folders", json={"path": str(videos)}).json()
    with conn:
        conn.execute(
            """INSERT INTO files (folder_id, path, size, modified, found_at, seen_at)
               VALUES (?, ?, 1, 0, 'now', 'now')""",
            (folder["id"], str(videos / "x.mkv")),
        )
        conn.execute(
            "INSERT INTO jobs (file_id, kind, method, position, state, added_at)"
            " VALUES (last_insert_rowid(), 'subtitles', 'best', 1, 'running', 'now')"
        )

    answer = client.delete(f"/folders/{folder['id']}")

    assert answer.status_code == 409
    assert answer.json()["detail"] == (
        "Maku is making English subtitles for a file in it. Forget the folder once they're "
        "made, or skip it first."
    )
