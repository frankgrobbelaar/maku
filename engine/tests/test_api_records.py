"""Maku's records damaged past use, through the API: only the way back answers, and the newest
backup that opens is restored (or Maku starts afresh) before the engine starts again."""

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime

from fastapi.testclient import TestClient

from maku.api import create_app
from maku.backups import back_up
from maku.config import DataPaths
from tests.conftest import TOKEN
from tests.damaged import records, scribble

NIGHT = datetime(2026, 10, 11, 3, 0).astimezone()

type Told = tuple[str, str, str | None]


@contextmanager
def started(paths: DataPaths, told: list[Told] | None = None) -> Generator[TestClient]:
    """The engine, started on the data folder as the app starts it."""
    heard = told if told is not None else []
    app = create_app(
        TOKEN, paths, notify=lambda title, body, link=None: heard.append((title, body, link))
    )
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
        yield client


def test_damaged_records_leave_only_the_way_back(paths: DataPaths):
    records(paths, "keep")
    made = back_up(paths, NIGHT)
    records(paths, "plex")
    scribble(paths)
    told: list[Told] = []

    with started(paths, told) as client:
        assert client.get("/records").json() == {
            "problem": "file is not a database",
            "badRead": False,
            "backup": made.name,
            "made": "2026-10-11T03:00:00",
        }
        refused = client.get("/settings")
        assert refused.status_code == 503
        assert refused.json()["detail"] == (
            "Maku's records are damaged, so it can't do that till they're back."
        )
        assert client.get("/health").json()["schemaVersion"] == 0
        assert told == [
            (
                "Maku's records are damaged",
                "Open Maku to restore the backup from 11 October, 03:00.",
                "/",
            )
        ]

        assert client.post("/records/restore").status_code == 204
        again = client.post("/records/restore")
        assert again.status_code == 409  # done once, till the engine starts again

    with started(paths) as client:  # as the app starts it again
        assert client.get("/records").json() is None
        assert client.get("/settings").json()["naming"] == "keep"
    assert len(list(paths.root.glob("maku (damaged *).db"))) == 1


def test_with_no_backup_maku_starts_again_with_new_records(paths: DataPaths):
    records(paths, "keep")
    scribble(paths)
    told: list[Told] = []

    with started(paths, told) as client:
        assert client.get("/records").json()["backup"] is None
        assert told == [
            ("Maku's records are damaged", "Open Maku to start again with new records.", "/")
        ]
        nothing = client.post("/records/restore")
        assert nothing.status_code == 422
        assert nothing.json()["detail"] == "No backup opens, so there's none to restore."

        assert client.post("/records/new").status_code == 204

    with started(paths) as client:
        assert client.get("/records").json() is None
        assert client.get("/settings").json()["setUp"] is False  # as on Maku's first day
    assert len(list(paths.root.glob("maku (damaged *).db"))) == 1


def test_records_that_are_fine_have_no_way_back_to_take(client: TestClient):
    assert client.get("/records").json() is None
    assert client.post("/records/restore").status_code == 409
    assert client.post("/records/new").status_code == 409
