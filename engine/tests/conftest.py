"""Shared test setup: every test gets its own empty data folder, and a small library of series
and films."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, suppress
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from maku import db
from maku.api import create_app
from maku.config import DataPaths
from maku.core.library import QUARANTINE_FOLDER
from tests.fake_web import FakeWeb

TOKEN = "test-token"


@pytest.fixture
def paths(tmp_path: Path) -> DataPaths:
    return DataPaths(tmp_path / "Maku")


@pytest.fixture
def web() -> FakeWeb:
    """The internet as the engine sees it in tests: nothing answers until a test says what."""
    return FakeWeb()


@pytest.fixture
def client(paths: DataPaths, web: FakeWeb) -> Iterator[TestClient]:
    """A client that talks to the API the way the app does: on 127.0.0.1, with the token."""
    app = create_app(TOKEN, paths, transport=web)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def quarantine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Copies set aside go to the drive's own "Maku quarantine" folder, outside the test's folder:
    whatever a test leaves there, in any day's folder, a failing one say, goes afterwards."""
    root = Path(tmp_path_factory.getbasetemp().anchor) / QUARANTINE_FOLDER
    there = root.exists()
    before = set(root.rglob("*"))
    yield
    for item in sorted(set(root.rglob("*")) - before, reverse=True):  # a folder's files first
        if item.is_dir():
            with suppress(OSError):
                item.rmdir()  # only when nothing else is there
        else:
            item.unlink(missing_ok=True)
    if not there:
        with suppress(OSError):
            root.rmdir()


@pytest.fixture
def conn(paths: DataPaths) -> Iterator[sqlite3.Connection]:
    """The data folder's database, migrated to the latest schema."""
    with closing(db.connect(paths.database)) as connection:
        db.migrate(connection)
        yield connection


@pytest.fixture
def videos(tmp_path: Path) -> Path:
    """A small library in any layout, with things a scan should pass over: a series in a folder
    of its own, a film without one, and another series' episode mixed in with downloads."""
    root = tmp_path / "Videos"
    files = {
        "The Harbour Line/The Harbour Line - S01E01 - Pilot.mkv": b"episode one",
        "The Harbour Line/The Harbour Line - S01E01 - Pilot.en.srt": b"subtitles",
        "The Harbour Line/folder.jpg": b"art",
        "Northern Lights 2004.avi": b"a film without a folder",
        "Maku quarantine/2026-10-10/old copy.mkv": b"set aside",
        ".thumbnails/preview.mp4": b"hidden",
        "Downloads/Glass.Orchard.S01E01.720p.HDTV.x264-GRP.MKV": b"mixed in",
    }
    for name, data in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    return root
