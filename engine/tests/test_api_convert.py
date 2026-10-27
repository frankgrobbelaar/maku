"""Converting through the API: what can be converted and what it takes, and the queue."""

import json
import sqlite3
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maku.api import create_app
from maku.backups import ask_to_restore, back_up
from maku.config import DataPaths
from maku.queue import Queue
from maku.recovery import Recovery, asked_to_stop
from maku.scan import Scanner
from tests.conftest import TOKEN
from tests.converting import TAG, open_elsewhere, programs, report
from tests.shelf import NOW, library

WEB_PROBE = json.dumps(report(1920, 1080, codec="h264"))  # a 1080p H.264 episode
EPISODE_ONE = "Starfall (2019)/Season 01/Starfall (2019) - S01E01.mkv"


@pytest.fixture
def shelf(conn: sqlite3.Connection, tmp_path: Path) -> Path:
    """Starfall: two 1080p H.264 episodes, one that won't play, and one at the standard
    already."""
    root = tmp_path / "Videos"
    names = [f"Starfall (2019)/Season 01/Starfall (2019) - S01E0{n}.mkv" for n in (1, 2, 3, 4)]
    library(conn, root, names)
    with conn:
        conn.execute("UPDATE files SET probe = ?", (WEB_PROBE,))
        conn.execute("UPDATE files SET problem = 'damaged' WHERE id = 3")
        conn.execute("UPDATE files SET probe = ? WHERE id = 4", (json.dumps(report(1920, 1080)),))
        conn.execute("INSERT INTO titles (id, kind, name) VALUES (1, 'series', 'Starfall')")
        conn.execute("UPDATE files SET title_id = 1, season = 1, episode = id, matched = 'sure'")
    return root


def free_space(monkeypatch: pytest.MonkeyPatch, free: int) -> None:
    """Every drive has `free` bytes free."""

    def usage(path: object) -> SimpleNamespace:
        return SimpleNamespace(total=10**13, used=10**13 - free, free=free)

    monkeypatch.setattr("maku.convert.shutil.disk_usage", usage)


@pytest.fixture
def converting(client: TestClient, paths: DataPaths, shelf: Path) -> Queue:
    """The engine's queue, converting with stand-ins for ffmpeg and ffprobe."""
    app = cast("FastAPI", client.app)
    queue = Queue(
        paths,
        app.state.scanner,
        lambda: programs(report(1920, 1080, tag=TAG)),
        now=lambda: NOW,
    )
    app.state.queue = queue
    return queue


def test_a_file_maku_converted_is_offered_again_once_the_standard_changes(
    client: TestClient, shelf: Path, conn: sqlite3.Connection
):
    made = json.dumps(report(3840, 2160, tag="reencode to 4K · Maku 0.1.0"))  # Maku's own, 4K
    with conn:
        conn.execute("UPDATE files SET probe = ? WHERE id = 4", (made,))
    chosen = client.get("/settings").json()

    at_4k = client.get("/convert").json()["files"]
    client.put("/settings", json={**chosen, "standard": "1080p"})
    at_1080 = client.get("/convert").json()["files"]

    assert 4 not in [file["fileId"] for file in at_4k]  # done, at that standard
    [again] = [file for file in at_1080 if file["fileId"] == 4]
    assert (again["method"], again["outputWidth"], again["outputHeight"]) == (
        "reencode",
        1920,
        1080,
    )
    assert again["reasons"] == ["4K: brought down to 1080p"]


def test_what_isnt_at_the_standard_is_listed_with_what_it_gets(client: TestClient, shelf: Path):
    found = client.get("/convert").json()

    assert found["standard"] == "4K"
    assert [(f["label"], f["broken"]) for f in found["files"]] == [
        ("Starfall · S01E01", False),
        ("Starfall · S01E02", False),
        ("Starfall · S01E03", True),
    ]
    first = found["files"][0]
    assert (first["width"], first["height"], first["aspect"], first["hdr"]) == (
        1920,
        1080,
        "16:9",
        None,
    )
    assert (first["method"], first["reasons"]) == ("reencode", ["H.264 becomes HEVC 10-bit"])
    assert (first["outputWidth"], first["outputHeight"], first["drive"]) == (
        1920,
        1080,
        shelf.drive,
    )
    assert first["gpuSeconds"] > 0
    assert first["outputBytes"] == 130_000_000  # never more than the original
    broken = found["files"][2]
    assert (broken["gpuSeconds"], broken["outputBytes"]) == (0, 0)
    assert found["free"][shelf.drive] > 0
    assert found["setAside"] == {}  # nothing in quarantine to empty


def test_an_hdr_film_says_its_hdr_is_kept(
    client: TestClient, shelf: Path, conn: sqlite3.Connection
):
    film = cast("dict[str, object]", report(3840, 2160))
    streams = cast("list[dict[str, object]]", film["streams"])
    streams[0].update(color_transfer="smpte2084", color_primaries="bt2020", color_space="bt2020nc")
    with conn:
        conn.execute("UPDATE files SET probe = ? WHERE id = 4", (json.dumps(film),))
    chosen = client.get("/settings").json()
    client.put("/settings", json={**chosen, "standard": "1080p"})

    [down] = [file for file in client.get("/convert").json()["files"] if file["fileId"] == 4]

    assert down["hdr"] == "HDR10"
    assert down["reasons"] == ["4K HDR: brought down to 1080p, HDR kept"]


def test_files_join_the_queue_and_wait_their_turn(client: TestClient, shelf: Path):
    added = client.post("/queue", json={"files": [2, 1, 3, 4]}).json()

    status = client.get("/queue").json()

    assert added == {"added": 2}  # a broken file and one at the standard aren't
    assert [(job["label"], job["method"]) for job in status["queued"]] == [
        ("Starfall · S01E02", "reencode"),
        ("Starfall · S01E01", "reencode"),
    ]
    assert (status["queued"][0]["width"], status["queued"][0]["height"]) == (1920, 1080)
    assert status["gpuSeconds"] == sum(job["gpuSeconds"] for job in status["queued"])
    assert (status["running"], status["gpu"], status["paused"]) == (None, None, False)
    assert [f["waiting"] for f in client.get("/convert").json()["files"]] == [True, True, False]


def test_a_video_waiting_for_english_subtitles_can_still_be_converted(
    client: TestClient, shelf: Path, conn: sqlite3.Connection
):
    with conn:
        conn.execute(
            """INSERT INTO jobs (file_id, kind, method, position, added_at)
               VALUES (1, 'subtitles', 'best', 1, '2026-10-11T09:00:00+00:00')"""
        )

    assert [f["waiting"] for f in client.get("/convert").json()["files"]] == [False, False, False]


def test_the_queue_pauses_resumes_and_waits_for_night(client: TestClient, shelf: Path):
    assert client.post("/queue/pause").json()["paused"] is True
    assert client.post("/queue/resume").json()["paused"] is False

    planned = client.put("/queue/schedule", json={"schedule": "nights"}).json()

    assert planned["schedule"] == "nights"
    client.post("/queue/pause")
    client.post("/queue", json={"files": [2], "when": "after"})
    assert client.get("/queue").json()["paused"] is True  # after the rest: it goes on as it was
    client.post("/queue", json={"files": [1], "when": "now"})
    status = client.get("/queue").json()
    assert (status["paused"], status["schedule"]) == (False, "now")  # start now, it said


def test_tonights_run_can_stop_at_three(client: TestClient, converting: Queue):
    client.put("/queue/schedule", json={"schedule": "nights"})

    status = client.put("/queue/tonight", json={"early": True}).json()

    assert status["early"] is True
    assert status["endsAt"] is None  # 09:30: by day, nothing ends tonight yet
    assert client.put("/queue/tonight", json={"early": False}).json()["early"] is False


def test_files_added_for_the_night_never_start_by_day(
    client: TestClient, shelf: Path, monkeypatch: pytest.MonkeyPatch
):
    schedules: list[str] = []
    add = Queue.add

    def noting(queue: Queue, file_ids: Iterable[int], *, fit: Iterable[str] = ()) -> int:
        schedules.append(queue.status().schedule)
        return add(queue, file_ids, fit=fit)

    monkeypatch.setattr(Queue, "add", noting)
    client.post("/queue/pause")

    client.post("/queue", json={"files": [1], "when": "nights"})

    assert schedules == ["nights"]  # set before they joined: the worker never saw "now"
    status = client.get("/queue").json()
    assert (status["paused"], status["schedule"]) == (False, "nights")  # so it runs tonight


def test_waiting_files_can_be_moved_skipped_removed_and_tried_again(
    client: TestClient, shelf: Path
):
    client.post("/queue", json={"files": [1, 2]})
    first, second = (job["id"] for job in client.get("/queue").json()["queued"])

    assert client.post(f"/queue/{second}/move", json={"before": first}).status_code == 204
    assert [job["id"] for job in client.get("/queue").json()["queued"]] == [second, first]
    assert client.post(f"/queue/{second}/skip").status_code == 204
    assert client.post(f"/queue/{second}/retry").status_code == 204
    assert client.delete(f"/queue/{first}").status_code == 204

    assert [job["id"] for job in client.get("/queue").json()["queued"]] == [second]
    assert client.delete(f"/queue/{first}").status_code == 404
    assert client.post("/queue/99/skip").status_code == 404


def test_several_waiting_files_can_be_moved_and_removed_at_once_and_all_cancelled(
    client: TestClient, shelf: Path
):
    client.post("/queue", json={"files": [1, 2]})
    first, second = (job["id"] for job in client.get("/queue").json()["queued"])

    moved = client.post("/queue/move", json={"ids": [second, 999], "before": first})
    assert moved.json() == {"changed": 1}
    assert [job["id"] for job in client.get("/queue").json()["queued"]] == [second, first]
    removed = client.post("/queue/remove", json={"ids": [second, 999]})
    assert removed.json() == {"changed": 1}
    assert [job["id"] for job in client.get("/queue").json()["queued"]] == [first]

    status = client.post("/queue/cancel").json()

    assert (status["queued"], status["running"]) == ([], None)


def test_the_room_said_is_where_the_files_are(
    client: TestClient, shelf: Path, monkeypatch: pytest.MonkeyPatch
):
    def usage(path: object) -> SimpleNamespace:  # a full volume, mounted into a roomy drive
        free = 10**12 if str(path).rstrip("\\").endswith(":") else 10**6
        return SimpleNamespace(total=10**13, used=10**13 - free, free=free)

    monkeypatch.setattr("maku.convert.shutil.disk_usage", usage)

    assert client.get("/convert").json()["free"] == {shelf.drive: 10**6}


def test_a_drive_without_room_pauses_the_queue_till_it_converts_what_fits(
    client: TestClient, converting: Queue, shelf: Path, monkeypatch: pytest.MonkeyPatch
):
    client.post("/queue", json={"files": [1, 2]})
    free_space(monkeypatch, 10**6)
    converting.work_once()

    room = client.get("/queue").json()["room"]
    assert (room["drive"], room["paused"], room["files"], room["fit"]) == (shelf.drive, True, 2, 0)
    assert (room["free"], room["setAside"]) == (10**6, 0)
    assert room["needed"] > room["free"]

    status = client.post("/queue/fit", json={"drive": shelf.drive}).json()

    assert status["paused"] is False
    assert status["room"]["paused"] is False  # they wait for room while the others go
    assert [job["noRoom"] for job in status["queued"]] == [True, True]


def test_files_queued_to_convert_what_fits_wait_for_room_without_pausing(
    client: TestClient, converting: Queue, shelf: Path, monkeypatch: pytest.MonkeyPatch
):
    free_space(monkeypatch, 10**6)

    client.post("/queue", json={"files": [1, 2], "when": "now", "fit": [shelf.drive]})

    assert converting.work_once() is False
    status = client.get("/queue").json()
    assert status["paused"] is False
    assert [job["noRoom"] for job in status["queued"]] == [True, True]


def test_a_drives_quarantine_can_be_emptied_to_make_room(
    client: TestClient, converting: Queue, shelf: Path
):
    episode = shelf / EPISODE_ONE
    original = episode.stat().st_size
    client.post("/queue", json={"files": [1]})
    converting.work_once()  # its original is set aside
    assert client.get("/convert").json()["setAside"] == {shelf.drive: original}

    emptied = client.post("/quarantine/empty", json={"drive": shelf.drive})

    assert emptied.json() == {"files": 1}
    assert client.get("/convert").json()["setAside"] == {}
    [done] = client.get("/queue").json()["today"]
    again = client.post(f"/queue/{done['id']}/restore")
    assert (
        again.json()["detail"]
        == "Its original was cleared out of quarantine, so it can't come back."
    )


def test_a_file_open_in_another_app_waits_and_can_be_tried_now(
    client: TestClient, converting: Queue, shelf: Path, monkeypatch: pytest.MonkeyPatch
):
    open_in_player = open_elsewhere(monkeypatch)
    client.post("/queue", json={"files": [1]})
    converting.work_once()

    [waiting] = client.get("/queue").json()["queued"]
    assert waiting["retryAt"] == "2026-10-11T09:35:00+00:00"  # in 5 minutes
    assert waiting["problem"].startswith("Starfall · S01E01 is open in another app")
    assert waiting["gpuSeconds"] == 0

    open_in_player[0] = False
    assert client.post(f"/queue/{waiting['id']}/retry").status_code == 204
    converting.try_waiting()

    [done] = client.get("/queue").json()["today"]
    assert (done["state"], done["retryAt"]) == ("done", None)


def test_a_failed_file_can_be_marked_broken(
    client: TestClient, converting: Queue, monkeypatch: pytest.MonkeyPatch
):
    client.post("/queue", json={"files": [1]})
    monkeypatch.setenv("MAKU_FAKE_FAIL", "encode")
    converting.work_once()
    [failed] = client.get("/queue").json()["today"]
    assert "hevc_nvenc" in failed["log"]

    assert client.post(f"/queue/{failed['id']}/broken").status_code == 204

    assert client.post(f"/queue/{failed['id']}/broken").status_code == 404
    assert client.get("/queue").json()["today"][0]["state"] == "skipped"


def test_a_converted_file_is_listed_today_and_its_original_can_come_back(
    client: TestClient, converting: Queue, shelf: Path
):
    client.post("/queue", json={"files": [1]})

    converting.work_once()

    [done] = client.get("/queue").json()["today"]
    assert (done["label"], done["state"]) == ("Starfall · S01E01", "done")
    assert client.post(f"/queue/{done['id']}/restore").status_code == 204
    again = client.post(f"/queue/{done['id']}/restore")
    assert again.status_code == 422
    assert again.json()["detail"] == "Maku has no converted file to put back for that."


def test_history_lists_a_conversion_and_undoing_it_puts_the_original_back(
    client: TestClient, converting: Queue, shelf: Path
):
    episode = shelf / EPISODE_ONE
    original = episode.read_bytes()
    client.post("/queue", json={"files": [1]})
    converting.work_once()

    [plan] = client.get("/history").json()["plans"]

    assert (plan["kind"], plan["title"]) == ("convert", "Converted Starfall · S01E01")
    made = plan["conversion"]
    assert (made["method"], made["restored"]) == ("reencode", False)
    assert made["before"] == {"height": 1080, "codec": "h264", "size": len(original)}
    assert (made["after"]["height"], made["after"]["codec"]) == (1080, "hevc")

    answer = client.post(f"/plans/{plan['id']}/undo")

    assert answer.status_code == 200
    assert episode.read_bytes() == original
    [plan] = client.get("/history").json()["plans"]
    assert plan["conversion"]["restored"] is True


def test_a_frame_is_shown_before_and_after_converting(
    client: TestClient, shelf: Path, monkeypatch: pytest.MonkeyPatch
):
    app = cast("FastAPI", client.app)
    app.state.programs = lambda: programs({})

    before = client.get("/convert/1/preview/before", params={"point": 0})
    after = client.get("/convert/1/preview/after", params={"point": 0})

    assert (before.status_code, before.headers["content-type"]) == (200, "image/png")
    assert b"format=yuv420p" in after.content  # made as converting makes it
    assert client.get("/convert/99/preview/before").status_code == 404


def test_without_ffmpeg_there_is_nothing_to_compare(client: TestClient, shelf: Path):
    answer = client.get("/convert/1/preview/before")

    assert answer.status_code == 503
    assert answer.json()["detail"].startswith("Maku needs ffmpeg")


def test_at_start_a_conversion_a_crash_stopped_is_settled_before_any_scan(
    paths: DataPaths, monkeypatch: pytest.MonkeyPatch
):
    order: list[str] = []

    class Scans:
        """A scanner that only notes when the startup scan is asked for."""

        def recover(self) -> None:
            order.append("scan")

        @contextmanager
        def hold(self) -> Generator[None]:
            yield

    def settled(_queue: Queue) -> Recovery:
        order.append("queue")
        return Recovery()

    monkeypatch.setattr(Queue, "recover", settled)
    app = create_app(TOKEN, paths, scanner=cast("Scanner", Scans()), work=True)

    with TestClient(app, base_url="http://127.0.0.1"):
        pass

    assert order == ["queue", "scan"]  # files settle in place before a scan looks at them


def test_after_a_crash_maku_says_what_it_settled_till_its_seen(
    paths: DataPaths, conn: sqlite3.Connection, shelf: Path
):
    with conn:  # Maku closed unexpectedly while a file converted
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, state, added_at)"
            " VALUES (1, 'reencode', 1, 'running', 'then')"
        )
    app = create_app(TOKEN, paths, work=True)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
        found = client.get("/recovery").json()
        assert (found["restarted"], found["finished"], found["putBack"]) == (1, 0, 0)
        assert client.post("/recovery/seen").status_code == 204
        assert client.get("/recovery").json() is None


def test_after_a_stop_maku_was_asked_for_no_crash_is_told(
    paths: DataPaths, conn: sqlite3.Connection, shelf: Path
):
    with conn:  # the app ended the engine while a file converted, before it could stop
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, state, added_at)"
            " VALUES (1, 'reencode', 1, 'running', 'then')"
        )
    asked_to_stop(paths)
    app = create_app(TOKEN, paths, work=True)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
        assert client.get("/recovery").json() is None
        assert [job["fileId"] for job in client.get("/queue").json()["queued"]] == [1]


def test_restoring_a_backup_made_mid_conversion_tells_of_no_crash(
    paths: DataPaths, conn: sqlite3.Connection, shelf: Path
):
    with conn:  # tonight's backup, made while a file converted
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, state, added_at)"
            " VALUES (1, 'reencode', 1, 'running', 'then')"
        )
    made = back_up(paths, NOW)
    with conn:
        conn.execute("UPDATE jobs SET state = 'done'")
    ask_to_restore(paths, made.name)
    app = create_app(TOKEN, paths, work=True)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
        assert client.get("/recovery").json() is None


def test_a_record_left_at_the_results_name_gives_way(
    client: TestClient, converting: Queue, conn: sqlite3.Connection, tmp_path: Path
):
    root = tmp_path / "Videos"
    library(conn, root, ["Old/Ep01.mp4"])
    with conn:  # a file once at the result's name, gone since
        conn.execute("UPDATE files SET probe = ? WHERE path LIKE '%Ep01.mp4'", (WEB_PROBE,))
        conn.execute(
            """INSERT INTO files (folder_id, path, size, modified, found_at, seen_at, gone_at)
               VALUES (1, ?, 1, 0, 'then', 'then', 'then')""",
            (str(root / "Old" / "Ep01.mkv"),),
        )
    mp4 = conn.execute("SELECT id FROM files WHERE path LIKE '%Ep01.mp4'").fetchone()[0]
    client.post("/queue", json={"files": [mp4]})

    converting.work_once()

    [done] = client.get("/queue").json()["today"]
    assert (done["state"], done["problem"]) == ("done", None)
    paths_now = [row[0] for row in conn.execute("SELECT path FROM files WHERE gone_at IS NULL")]
    assert str(root / "Old" / "Ep01.mkv") in paths_now
