"""English subtitles through the API: what the library could have them for, asking for a batch,
seeing it in the queue, on the title's page, in the player and in History, and taking it away."""

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maku.config import DataPaths
from maku.core.speech import Made, Segment
from maku.player import Player
from maku.queue import Queue
from tests.converting import FAKE_FFMPEG, TAG, programs, report
from tests.shelf import NOW, library


class Whisper:
    def __init__(self, folder: Path, graphics: bool) -> None:
        self.folder = folder

    def hear(self, audio: object, language: str | None, *, report: object, stop: object) -> Made:
        return Made([Segment(1.0, 2.0, "Over here!")], "ja", translated=True, speech=1.0)


@pytest.fixture
def shelf(conn: sqlite3.Connection, tmp_path: Path) -> Path:
    """Two episodes of a made-up series with Japanese sound; the second has German subtitles
    beside it, and the third English ones."""
    root = tmp_path / "Videos"
    names = [f"Starfall (1989)/Season 01/Starfall (1989) - S01E0{n}.mkv" for n in (1, 2, 3)]
    library(conn, root, names)
    season = root / "Starfall (1989)" / "Season 01"
    (season / "Starfall (1989) - S01E02.de.srt").write_text("Hallo", "utf-8")
    (season / "Starfall (1989) - S01E03.en.srt").write_text("Hello", "utf-8")
    with conn:
        conn.execute("INSERT INTO titles (id, kind, name) VALUES (1, 'series', 'Starfall')")
        conn.execute("UPDATE files SET title_id = 1, season = 1, episode = id, matched = 'sure'")
    return season


@pytest.fixture
def hearing(client: TestClient, paths: DataPaths, shelf: Path, tmp_path: Path) -> Queue:
    """The engine's queue and player, with stand-ins for ffmpeg and Whisper (Best's model
    downloaded)."""
    app = cast("FastAPI", client.app)
    kit = replace(
        programs(report(1920, 1080, tag=TAG)),
        speech={"best": tmp_path / "speech-best"}.get,
        listener=Whisper,
    )
    queue = Queue(paths, app.state.scanner, lambda: kit, now=lambda: NOW)
    app.state.queue = queue
    app.state.player = Player(paths, lambda: FAKE_FFMPEG)
    return queue


def test_the_library_says_what_it_could_have_english_subtitles_for(client: TestClient, shelf: Path):
    options = client.get("/subtitles").json()

    assert [
        (video["label"], video["sound"], video["subtitles"], video["english"])
        for video in options["files"]
    ] == [
        ("Starfall · S01E01", ["jpn"], [], False),
        ("Starfall · S01E02", ["jpn"], ["de"], False),
        ("Starfall · S01E03", ["jpn"], ["en"], True),
    ]
    assert options["files"][0]["seconds"] == 24 * 60
    assert options["rates"] == {"best": 0.4, "fast": 0.15}


def test_a_batch_joins_the_queue_is_made_and_shows_everywhere(
    client: TestClient, hearing: Queue, shelf: Path
):
    asked = {"fileIds": [1, 2], "quality": "best", "language": "jpn", "title": "Starfall"}

    assert client.post("/subtitles", json=asked).json() == {"added": 2}
    queued = client.get("/queue").json()["queued"]
    assert [(job["kind"], job["method"], job["language"]) for job in queued] == [
        ("subtitles", "best", "jpn"),
        ("subtitles", "best", "jpn"),
    ]
    videos = client.get("/titles/1").json()["videos"]
    assert [video["subtitlesJob"] for video in videos] == ["queued", "queued", None]

    while hearing.work_once():
        pass

    videos = client.get("/titles/1").json()["videos"]
    assert [(video["made"], video["subtitles"]) for video in videos] == [
        (True, ["en"]),
        (True, ["de", "en"]),
        (False, ["en"]),
    ]
    opened = client.post("/player", json={"file": 1}).json()
    [track] = opened["subtitles"]
    assert (track["language"], track["beside"], track["made"]) == ("en", True, True)
    client.delete(f"/player/{opened['ticket']}")
    [batch] = client.get("/history").json()["subtitles"]
    assert (batch["title"], batch["made"], batch["present"]) == ("Starfall", 2, 2)

    taken = client.post(f"/subtitles/batches/{batch['id']}/take-away").json()

    assert taken["planId"] is not None
    assert not (shelf / "Starfall (1989) - S01E01.en.srt").exists()
    [batch] = client.get("/history").json()["subtitles"]
    assert batch["present"] == 0
    [plan] = [p for p in client.get("/history").json()["plans"] if p["id"] == taken["planId"]]
    assert plan["takenAway"] == 2


def test_a_sound_track_that_doesnt_say_its_language_shows_the_one_whisper_heard(
    client: TestClient, conn: sqlite3.Connection, hearing: Queue
):
    with conn:
        conn.execute("""UPDATE files SET sound = '["", "eng"]' WHERE id = 1""")
    asked = {"fileIds": [1, 2], "quality": "best", "language": "", "title": "Starfall"}
    client.post("/subtitles", json=asked)

    while hearing.work_once():
        pass

    videos = client.get("/titles/1").json()["videos"]
    # Whisper heard Japanese in the first's first track; the second's says it is Japanese.
    assert [(video["sound"], video["heard"]) for video in videos] == [
        (["ja", "eng"], "ja"),
        (["jpn"], None),
        (["jpn"], None),
    ]


def test_a_batch_maku_doesnt_have_cant_be_taken_away(client: TestClient):
    assert client.post("/subtitles/batches/9/take-away").status_code == 404
