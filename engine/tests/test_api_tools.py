"""GET /tools and POST /tools/{id}/download: ffmpeg on first run, and the speech models when
asked for, through the API."""

import hashlib
import io
from collections.abc import Iterator
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from maku.api import create_app
from maku.config import DataPaths
from maku.tools import Tools, manifest
from tests.conftest import TOKEN
from tests.test_tools import BUILD


@pytest.fixture
def toolbox(paths: DataPaths) -> Tools:
    ffmpeg = next(item for item in manifest() if item.id == "ffmpeg")
    item = replace(ffmpeg, size=len(BUILD), sha256=hashlib.sha256(BUILD).hexdigest())
    return Tools(paths, items=(item,), fetch=lambda url: io.BytesIO(BUILD))


@pytest.fixture
def api(paths: DataPaths, toolbox: Tools) -> Iterator[TestClient]:
    app = create_app(TOKEN, paths, toolbox)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
        yield client


def test_the_tools_say_what_they_are_and_that_ffmpeg_is_still_to_fetch(api: TestClient):
    response = api.get("/tools")

    assert response.status_code == 200
    [ffmpeg] = response.json()
    assert ffmpeg == {
        "id": "ffmpeg",
        "name": "ffmpeg",
        "version": "9.0.2",
        "purpose": (
            "Reads what each video holds, and converts it. "
            "Maku fetches it the first time it starts."
        ),
        "licence": "LGPL-2.1-or-later",
        "size": len(BUILD),
        "when": "setup",
        "state": "missing",
        "done": 0,
        "problem": None,
    }


def test_downloading_ffmpeg_makes_it_ready(api: TestClient, toolbox: Tools):
    started = api.post("/tools/ffmpeg/download")
    toolbox.wait("ffmpeg", timeout=10)

    assert started.status_code == 202
    assert started.json()["id"] == "ffmpeg"
    assert api.get("/tools").json()[0]["state"] == "ready"


def test_an_unknown_tool_is_named_in_the_answer(api: TestClient):
    response = api.post("/tools/winamp/download")

    assert response.status_code == 404
    assert response.json() == {"detail": "Maku doesn't download anything called winamp."}


def test_the_speech_models_are_listed_to_fetch_when_asked_for(paths: DataPaths):
    app = create_app(TOKEN, paths, Tools(paths))
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
        listed = {tool["id"]: tool for tool in client.get("/tools").json()}

    assert listed["ffmpeg"]["when"] == "setup"
    assert (listed["speech-best"]["when"], listed["speech-best"]["name"]) == (
        "asked",
        "Whisper medium",
    )
    assert listed["speech-fast"]["size"] < listed["speech-best"]["size"]
