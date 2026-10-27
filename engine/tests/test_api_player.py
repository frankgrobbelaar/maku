"""Playing a video inside Maku's window through the API: opening it, the stream (which the
ticket opens, not the token), its subtitles getting ready, and closing it."""

import json
import sqlite3
import string
import time
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maku.config import DataPaths
from maku.player import Player
from tests.converting import FAKE_FFMPEG
from tests.shelf import library
from tests.test_player import REPORT


@pytest.fixture
def videos(client: TestClient, paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path) -> Path:
    """Two episodes in the library, read, and the engine's player with ffmpeg stood in for."""
    root = tmp_path / "Videos"
    library(conn, root, ["Glass Orchard - 01.mkv", "Glass Orchard - 02.mkv"])
    with conn:
        conn.execute("UPDATE files SET probe = ?", (json.dumps(REPORT),))
    app = cast("FastAPI", client.app)
    app.state.player = Player(paths, lambda: FAKE_FFMPEG)
    return root


def opened(client: TestClient, file: int = 1) -> dict[str, Any]:
    answer = client.post("/player", json={"file": file})
    assert answer.status_code == 200
    return answer.json()


def ready(client: TestClient, ticket: str) -> dict[str, Any]:
    for _ in range(100):
        state = client.get(f"/player/{ticket}").json()
        if not state["preparing"]:
            return state
        time.sleep(0.05)
    raise AssertionError("the subtitles never got ready")


def test_opening_a_video_gives_a_ticket_and_what_it_offers(client: TestClient, videos: Path):
    video = opened(client)

    assert isinstance(video["ticket"], str)
    assert video["missing"] is None
    assert video["drive"] == videos.drive
    assert video["duration"] == 1440.0
    assert video["sound"] == [
        {"number": 0, "language": "jpn", "title": None, "channels": 2, "default": True},
        {"number": 1, "language": "eng", "title": None, "channels": 6, "default": False},
    ]
    assert [(each["number"], each["kind"]) for each in video["subtitles"]] == [
        (0, "styled"),
        (1, "pictures"),
    ]
    assert (video["chosenSound"], video["chosenSubtitles"]) == (0, 0)
    assert video["ready"] == [1]  # the pictures, at once; the text once copied out
    asked = client.post(f"/player/{video['ticket']}/subtitles/0").json()
    assert asked["preparing"] == [0]
    assert ready(client, video["ticket"])["ready"] == [0, 1]


def test_a_video_that_isnt_there_has_no_ticket_and_says_why(
    client: TestClient, videos: Path, conn: sqlite3.Connection
):
    (videos / "Glass Orchard - 02.mkv").unlink()
    gone = opened(client, 2)
    assert (gone["ticket"], gone["missing"]) == (None, "file")

    letter = next(c for c in reversed(string.ascii_uppercase) if not Path(f"{c}:\\").exists())
    with conn:
        conn.execute(
            "UPDATE files SET path = ? WHERE id = 1",
            (f"{letter}:\\Videos\\Glass Orchard - 01.mkv",),
        )
    unplugged = opened(client, 1)
    assert (unplugged["ticket"], unplugged["missing"], unplugged["drive"]) == (
        None,
        "drive",
        f"{letter}:",
    )
    assert client.post("/player", json={"file": 99}).status_code == 404


def test_the_stream_needs_its_ticket_not_the_token(client: TestClient, videos: Path):
    ticket = opened(client)["ticket"]
    client.post(f"/player/{ticket}/subtitles/0")
    ready(client, ticket)
    window = TestClient(client.app, base_url="http://127.0.0.1")  # a <video>: no token

    played = window.get(f"/stream/{ticket}", params={"at": 90, "sound": 1, "subtitles": 0})

    assert played.status_code == 200
    assert played.headers["content-type"] == "video/mp4"
    assert played.headers["cache-control"] == "no-store"
    assert "-ss 90.000" in played.text
    assert "subtitles=filename=" in played.text
    assert window.get("/stream/not-a-ticket").status_code == 404
    assert window.get(f"/player/{ticket}").status_code == 401  # everything else wants the token
    assert window.get(f"/stream/{ticket}", params={"at": -1}).status_code == 422


def test_a_video_that_wont_play_says_why(
    client: TestClient, videos: Path, monkeypatch: pytest.MonkeyPatch
):
    ticket = opened(client)["ticket"]
    monkeypatch.setenv("MAKU_FAKE_FAIL", "stream")

    refused = client.get(f"/stream/{ticket}")

    assert refused.status_code == 422
    assert refused.json()["detail"] == "The video is damaged there, so it won't play."
    stopped = client.get(f"/player/{ticket}").json()["stopped"]
    assert stopped == {
        "why": "damaged",
        "detail": "[matroska @ 0] Invalid data found when processing input",
    }


def test_subtitles_get_ready_on_asking_and_closing_forgets_the_video(
    client: TestClient, videos: Path, monkeypatch: pytest.MonkeyPatch
):
    ticket = opened(client)["ticket"]
    client.post(f"/player/{ticket}/subtitles/0")
    ready(client, ticket)

    asked = client.post(f"/player/{ticket}/subtitles/1").json()  # pictures: ready already
    assert asked["ready"] == [0, 1]
    assert client.post(f"/player/{ticket}/subtitles/9").status_code == 422

    assert client.delete(f"/player/{ticket}").status_code == 204
    assert client.get(f"/player/{ticket}").status_code == 404
    assert client.get(f"/stream/{ticket}").status_code == 404
