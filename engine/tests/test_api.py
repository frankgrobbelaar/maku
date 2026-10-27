from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from maku import __version__, db
from maku.api import create_app
from maku.changes import ChangeState, changes_of, save_plan
from maku.config import DataPaths
from maku.core.plan import Change, ChangeKind, Plan
from maku.migrations import MIGRATIONS
from tests.conftest import TOKEN


def test_health_reports_version_data_folder_and_schema(client: TestClient, paths: DataPaths):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "dataDir": str(paths.root),
        "schemaVersion": len(MIGRATIONS),
    }


def test_starting_settles_file_moves_a_crash_interrupted(paths: DataPaths, tmp_path: Path):
    source = tmp_path / "a.mkv"
    source.write_text("video", encoding="utf-8")
    change = Change(ChangeKind.MOVE, source, tmp_path / "Videos" / "a.mkv", "A", "Named and filed")
    with closing(db.connect(paths.database)) as conn:
        db.migrate(conn)
        plan_id = save_plan(conn, Plan((change,)), "Tidy up", now=datetime.now(UTC))
        with conn:  # the engine stopped mid-move, before the file had moved
            conn.execute("UPDATE changes SET state = 'moving'")

    with TestClient(create_app(TOKEN, paths), base_url="http://127.0.0.1"):
        pass

    with closing(db.connect(paths.database)) as conn:
        assert [c.state for c in changes_of(conn, plan_id)] == [ChangeState.PLANNED]


def test_requests_without_the_token_are_refused(client: TestClient):
    response = client.get("/health", headers={"Authorization": ""})

    assert response.status_code == 401


def test_requests_with_a_wrong_token_are_refused(client: TestClient):
    response = client.get("/health", headers={"Authorization": "Bearer guess"})

    assert response.status_code == 401


def test_requests_addressed_to_another_host_are_refused(paths: DataPaths):
    app = create_app(TOKEN, paths)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app, base_url="http://maku.example", headers=headers) as client:
        response = client.get("/health")

    assert response.status_code == 400


def test_the_app_window_may_call_the_api(client: TestClient):
    response = client.options(
        "/health",
        headers={
            "Origin": "http://tauri.localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"


def test_the_app_window_may_read_whether_a_picture_is_from_the_episode(client: TestClient):
    response = client.get("/health", headers={"Origin": "http://tauri.localhost"})

    assert response.headers["access-control-expose-headers"] == "Maku-Picture"


def test_other_web_pages_may_not(client: TestClient):
    response = client.options(
        "/health",
        headers={
            "Origin": "https://somewhere.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
