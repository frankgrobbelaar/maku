"""Settings > Your data: where Maku keeps it and how big each part is, the export, and what Maku
keeps next to the videos."""

import json
import sqlite3
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from maku.config import DataPaths
from maku.core.library import QUARANTINE_FOLDER
from maku.core.report import GAP_ANALYSIS_FILE
from maku.reports import write_reports
from tests.services import internet, with_key
from tests.shelf import NOW, identify, library


def test_each_part_of_the_data_folder_is_measured(
    client: TestClient, paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path
):
    for folder, size in (("artwork", 1000), ("cache", 500), ("logs", 200), ("tools", 50)):
        (paths.root / folder).mkdir(parents=True, exist_ok=True)
        (paths.root / folder / "a file").write_bytes(bytes(size))
    library(conn, tmp_path / "Videos", ["Harbour/The Harbour Line - 01.mkv"])
    set_aside = Path(tmp_path.anchor) / QUARANTINE_FOLDER / NOW.date().isoformat()
    set_aside.mkdir(parents=True, exist_ok=True)
    (set_aside / "copy.mkv").write_bytes(bytes(300))

    found = client.get("/data").json()

    assert found["folder"] == str(paths.root)
    assert found["database"] > 0
    assert (found["artwork"], found["cache"], found["logs"], found["tools"]) == (1000, 500, 200, 50)
    assert found["backups"] == 0
    [quarantine] = found["quarantine"]
    assert quarantine["folder"] == str(Path(tmp_path.anchor) / QUARANTINE_FOLDER)
    assert quarantine["bytes"] >= 300
    assert quarantine["files"] >= 1


def test_the_export_is_written_where_the_owner_asks(
    client: TestClient, conn: sqlite3.Connection, tmp_path: Path
):
    answer = client.post("/export", json={"folder": str(tmp_path / "Backups")}).json()

    path = Path(answer["path"])
    assert path.parent == tmp_path / "Backups"
    assert answer["size"] == path.stat().st_size
    assert "maku.db" in zipfile.ZipFile(path).namelist()


def test_turning_the_reports_off_takes_them_out_of_the_shows_folders(
    client: TestClient, paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path
):
    root = tmp_path / "Videos"
    library(conn, root, ["The Harbour Line/The Harbour Line - 01.mkv"], minutes=45)
    identify(with_key(paths), conn, internet())
    write_reports(conn, now=NOW)
    report = root / "The Harbour Line" / GAP_ANALYSIS_FILE
    assert report.is_file()
    settings = client.get("/settings").json()

    client.put("/settings", json={**settings, "reports": False})

    assert not report.exists()
    client.put("/settings", json={**settings, "reports": True})
    assert report.is_file()


def test_moving_the_data_is_asked_for_and_happens_as_the_engine_starts_again(
    client: TestClient, paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path
):
    target = tmp_path / "F" / "Maku data"

    answer = client.post("/data/move", json={"folder": str(target)})

    assert answer.status_code == 204
    assert (paths.root / "move.txt").read_text(encoding="utf-8") == str(target)
    assert client.get("/data").json()["moved"] is None  # not till the engine starts again


def test_a_folder_that_cant_take_the_data_says_why(client: TestClient, paths: DataPaths):
    answer = client.post("/data/move", json={"folder": str(paths.root / "artwork")})

    assert answer.status_code == 422
    assert answer.json()["detail"] == (
        "That folder is inside Maku's data folder: choose one outside it."
    )


def test_how_the_last_move_went_is_shown(client: TestClient, conn: sqlite3.Connection):
    moved = {"source": r"C:\Maku", "target": r"F:\Maku data", "at": "now", "problem": None}
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('data_moved', ?)", (json.dumps(moved),)
        )

    found = client.get("/data").json()["moved"]

    assert (found["source"], found["target"], found["problem"]) == (
        r"C:\Maku",
        r"F:\Maku data",
        None,
    )
