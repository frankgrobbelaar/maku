"""What this PC has and can do, as Setup, About in Settings, and Convert show it."""

import sqlite3
from datetime import datetime
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maku import hardware
from maku.config import DataPaths
from maku.convert import Programs
from maku.core.hardware import GIB, Card, Checked
from maku.hardware import Facts
from maku.pc_check import PcCheck
from tests.converting import programs
from tests.fake_ffprobe import REPORT

NOW = datetime.fromisoformat("2026-10-15T20:00:00+02:00")
GTX = Card("NVIDIA GeForce GTX 1660 SUPER", "nvidia", 6 * GIB, False, "617.42")
DESKTOP = Facts((GTX,), "Intel Core i5-9600K", 6, 24 * GIB)


def stand_in(client: TestClient, paths: DataPaths, program: Programs | None) -> PcCheck:
    """The engine's look at this PC, with Windows and ffmpeg standing in."""
    pc = PcCheck(paths, lambda: program, now=lambda: NOW, looking=lambda: DESKTOP)
    cast("FastAPI", client.app).state.pc = pc
    return pc


def test_before_its_checked_this_pc_is_what_windows_says(client: TestClient, paths: DataPaths):
    stand_in(client, paths, None)

    found = client.get("/system").json()

    assert found["graphicsCard"] == "NVIDIA GeForce GTX 1660 SUPER"
    assert found["card"] == {
        "name": "NVIDIA GeForce GTX 1660 SUPER",
        "maker": "nvidia",
        "memory": 6 * GIB,
        "integrated": False,
        "driver": "617.42",
    }
    assert (found["processor"], found["cores"], found["memory"]) == (
        "Intel Core i5-9600K",
        6,
        24 * GIB,
    )
    assert (found["checkedAt"], found["encoder"], found["abilities"]) == (None, None, [])
    assert found["subtitles"] == {  # as on the PC first measured
        "best": "card",
        "fast": "card",
        "bestWants": None,
    }
    assert (found["measured"], found["testing"], found["driverLink"]) == (None, None, None)


def test_testing_this_pc_checks_and_times_each_part(client: TestClient, paths: DataPaths):
    pc = stand_in(client, paths, programs(REPORT))

    started = client.post("/system/test")
    pc.wait()

    assert started.status_code == 202
    found = client.get("/system").json()
    assert found["checkedAt"] == NOW.isoformat()
    assert found["encoder"] == "nvenc"
    assert [(each["part"], each["state"]) for each in found["abilities"]] == [
        ("convert", "ready"),
        ("subtitles", "ready"),
        ("player", "ready"),
    ]
    convert = found["abilities"][0]
    assert convert["how"] == "HEVC 10-bit on NVIDIA's encoder (NVENC)"
    one, four = convert["seconds"]  # an hour of 1080p, and of 4K, at the speed timed
    assert four == pytest.approx(one * 4)
    assert found["measured"] == {
        "at": NOW.isoformat(),
        "tested": True,
        "conversions": 0,
        "subtitles": 0,
    }
    assert found["testing"] is None


def test_a_pc_is_tested_once_maku_has_ffmpeg(client: TestClient, paths: DataPaths):
    stand_in(client, paths, None)

    refused = client.post("/system/test")

    assert refused.status_code == 409
    assert refused.json()["detail"] == "Maku tests this PC once ffmpeg is downloaded."


def test_a_card_whose_encoder_wont_start_links_its_makers_drivers(
    client: TestClient, paths: DataPaths, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MAKU_FAKE_NO_ENCODERS", "hevc_nvenc,hevc_amf,hevc_qsv")
    monkeypatch.setenv("MAKU_FAKE_WHY", "Driver does not support the required nvenc API version")
    pc = stand_in(client, paths, programs(REPORT))

    client.post("/system/test")
    pc.wait()

    found = client.get("/system").json()
    assert found["encoder"] is None
    assert found["driverLink"] == "https://www.nvidia.com/Download/index.aspx"
    assert found["encoderProblem"] == "Driver does not support the required nvenc API version."
    convert = found["abilities"][0]
    assert (convert["state"], convert["how"]) == ("no", "Not on this PC")


def test_fast_on_the_processor_shows_the_time_this_pc_measured(
    client: TestClient, paths: DataPaths, conn: sqlite3.Connection
):
    laptop = Facts(
        (Card("Intel(R) UHD Graphics 620", "intel", 128 * 1024**2, True, None),), None, 4, 16 * GIB
    )
    hardware.keep(conn, laptop, Checked("qsv", None, directml=True, at=NOW.isoformat()))
    hardware.learn_hearing(conn, "fast_processor", 1440.0, 2880.0, NOW)  # two seconds a second
    stand_in(client, paths, None)

    subtitles = client.get("/system").json()["abilities"][1]

    assert (subtitles["state"], subtitles["how"]) == ("limited", "Fast on the processor")
    assert subtitles["seconds"] == [7200.0]  # an hour of sound, as measured here


def test_what_best_wants_on_this_pc(client: TestClient, paths: DataPaths, conn: sqlite3.Connection):
    small = Facts((Card("NVIDIA GeForce GTX 1050", "nvidia", 2 * GIB, False, None),), None, 4, None)
    hardware.keep(conn, small, Checked("nvenc", None, directml=True, at=NOW.isoformat()))
    stand_in(client, paths, None)

    assert client.get("/system").json()["subtitles"] == {
        "best": None,
        "fast": "card",
        "bestWants": "memory",
    }

    no_directx = Checked("nvenc", None, directml=False, at=NOW.isoformat())
    hardware.keep(conn, DESKTOP, no_directx)

    assert client.get("/system").json()["subtitles"] == {
        "best": None,
        "fast": "processor",
        "bestWants": "directx",
    }
