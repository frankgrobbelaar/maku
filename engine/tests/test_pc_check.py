"""Checking what this PC can do, and timing it, with ffmpeg and DirectML stood in for."""

import sqlite3
import sys
import threading
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from maku import hardware
from maku.config import DataPaths
from maku.convert import Programs
from maku.core.estimate import Speeds
from maku.core.hardware import GIB, Card, Checked
from maku.hardware import Facts
from maku.pc_check import Checking, PcCheck, check, pace
from tests.converting import programs
from tests.fake_ffprobe import REPORT

NOW = datetime.fromisoformat("2026-10-15T20:00:00+02:00")
GTX = Card("NVIDIA GeForce GTX 1660 SUPER", "nvidia", 6 * GIB, False, "617.42")
RX = Card("AMD Radeon RX 6700 XT", "amd", 12 * GIB, False, "32.0.21025.1024")
DESKTOP = Facts((GTX,), "Intel Core i5-9600K", 6, 24 * GIB)
TOO_OLD = "Driver does not support the required nvenc API version. Required: 13.0 Found: 12.1"
FULL_HD = 1920 * 1080 / 1e6  # megapixels in a frame of the made-up picture timed


def stood_in() -> Programs:
    return programs(REPORT)


def no_directx() -> bool:
    return False


def checked(
    cards: tuple[Card, ...] = (GTX,), *, timing: bool = False, program: Programs | None = None
) -> tuple[tuple[Checked, dict[str, float]], list[Checking]]:
    told: list[Checking] = []
    found = check(program or stood_in(), cards, NOW, timing=timing, told=told.append)
    return found, told


def test_the_cards_own_makers_encoder_goes_first():
    commands: list[Sequence[str]] = []
    program = programs(REPORT, commands)

    (found, speeds), told = checked((RX,), program=program)

    assert (found.encoder, found.encoder_problem, found.directml) == ("amf", None, True)
    assert found.player == "h264_mf"  # Windows' own, for the player
    assert found.at == NOW.isoformat()
    assert "hevc_amf" in commands[0]  # AMD's first, on an AMD card
    assert speeds == {}  # only checked
    assert [each.step for each in told] == ["encoder", "subtitles"]


def test_another_encoder_converts_when_the_cards_own_wont_start(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("MAKU_FAKE_NO_ENCODERS", "hevc_nvenc")
    monkeypatch.setenv("MAKU_FAKE_WHY", TOO_OLD)

    (found, _), _ = checked()

    assert found.encoder == "amf"
    assert found.encoder_problem == f"{TOO_OLD}."  # what NVIDIA's said, for the driver's link


def test_without_an_encoder_converting_is_off_and_says_why(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAKU_FAKE_NO_ENCODERS", "hevc_nvenc,hevc_amf,hevc_qsv")
    monkeypatch.setenv("MAKU_FAKE_WHY", TOO_OLD)

    (found, _), _ = checked()

    assert found.encoder is None
    assert found.encoder_problem == f"{TOO_OLD}."


def test_the_player_takes_a_cards_encoder_without_windows_own(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAKU_FAKE_NO_ENCODERS", "h264_mf")
    assert checked()[0][0].player == "h264_nvenc"  # a Windows N edition, say

    monkeypatch.setenv("MAKU_FAKE_NO_ENCODERS", "h264_mf,h264_nvenc,h264_amf,h264_qsv")
    assert checked()[0][0].player is None


def test_directml_is_tried_on_the_card_for_english_subtitles():
    (found, _), _ = checked(program=replace(stood_in(), directml=no_directx))

    assert (found.encoder, found.directml) == ("nvenc", False)


def test_testing_times_the_encoder_on_this_pc(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAKU_FAKE_FPS", "480")

    (found, speeds), told = checked(timing=True)

    assert found.encoder == "nvenc"
    # From ffmpeg's own progress, as megapixels a second: 480 frames of 1080p.
    assert speeds["megapixels"] == pytest.approx(480 * FULL_HD, rel=0.3)
    assert told[1].fps == pytest.approx(speeds["megapixels"] / FULL_HD)  # shown once timed


def test_a_slow_card_is_timed_by_what_it_managed_in_the_time(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAKU_FAKE_FPS", "100")  # 480 frames would take nearly 5 seconds
    monkeypatch.setattr("maku.pc_check._TIMEOUT", 1.5)

    (_, speeds), _ = checked(timing=True)

    assert speeds["megapixels"] == pytest.approx(100 * FULL_HD, rel=0.35)  # this card's


def test_what_couldnt_be_timed_isnt_kept_as_measured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAKU_FAKE_NO_ENCODERS", "hevc_nvenc,hevc_amf,hevc_qsv")

    (found, speeds), _ = checked(timing=True)

    assert found.encoder is None
    assert speeds == {}


def test_frames_a_second_leave_out_starting_ffmpeg():
    assert pace([(10.0, 0), (10.5, 48), (11.5, 528)]) == pytest.approx(480)
    assert pace([(10.0, 48)]) is None  # one report says nothing of its speed
    assert pace([]) is None


class Looking:
    """Windows' answer about this PC, standing in: None when it doesn't answer."""

    def __init__(self, facts: Facts | None) -> None:
        self.facts = facts

    def __call__(self) -> Facts | None:
        return self.facts


def make_check(
    paths: DataPaths, facts: Facts | None, *, program: Programs | None = None, busy: bool = False
) -> tuple[PcCheck, Looking, list[str]]:
    looking, after = Looking(facts), list[str]()
    pc = PcCheck(
        paths,
        lambda: program,
        now=lambda: NOW,
        busy=lambda: busy,
        after=lambda: after.append("woken"),
        looking=looking,
    )
    return pc, looking, after


def keep_checked(conn: sqlite3.Connection, **found: object) -> None:
    """What checking this PC found before, as kept: as `found` says, else all running."""
    done = check(stood_in(), DESKTOP.cards, NOW, timing=False, told=print)[0]
    hardware.keep(conn, DESKTOP, replace(done, **found))  # pyright: ignore[reportArgumentType]


def test_the_engine_checks_a_pc_it_hasnt_checked(paths: DataPaths, conn: sqlite3.Connection):
    pc, _, after = make_check(paths, DESKTOP, program=stood_in())

    pc.refresh()
    pc.wait()

    facts, found = hardware.stored(conn)
    assert facts == DESKTOP
    assert found is not None
    assert found.encoder == "nvenc"
    assert hardware.measured(conn) is None  # checked, not timed: the times stay a guess
    assert after == ["woken"]  # converting goes on
    assert pc.testing() is None


def test_a_test_shows_as_under_way_the_moment_its_asked_for(
    paths: DataPaths, conn: sqlite3.Connection
):
    going = threading.Event()

    def slowly() -> Facts:  # Windows taking its time to say what the PC has
        going.wait(10)
        return DESKTOP

    pc = PcCheck(paths, lambda: stood_in(), now=lambda: NOW, looking=slowly)

    assert pc.test()
    under_way = pc.testing()  # before Windows has answered: the screen sees it start

    going.set()
    pc.wait(30)
    assert under_way is not None
    assert under_way.timing
    assert pc.testing() is None


def test_converting_waits_while_the_engine_looks_at_the_pc(
    paths: DataPaths, conn: sqlite3.Connection
):
    keep_checked(conn)
    going = threading.Event()

    def slowly() -> Facts:
        going.wait(10)
        return DESKTOP

    pc = PcCheck(paths, lambda: stood_in(), now=lambda: NOW, looking=slowly)

    pc.refresh()
    looking = pc.testing()  # the queue's `checking`: nothing starts on an encoder unknown yet
    going.set()
    pc.wait(30)

    assert looking is not None
    assert pc.testing() is None


def test_a_pc_checked_already_isnt_checked_again(paths: DataPaths, conn: sqlite3.Connection):
    commands: list[Sequence[str]] = []
    program = programs(REPORT, commands)
    hardware.keep(conn, DESKTOP, check(program, DESKTOP.cards, NOW, timing=False, told=print)[0])
    commands.clear()
    pc, _, _ = make_check(paths, DESKTOP, program=program)

    pc.refresh()
    pc.wait()

    assert commands == []


@pytest.mark.parametrize(
    "found",
    [{"encoder": None}, {"directml": False}, {"player": None}],
)
def test_a_check_that_found_a_part_not_running_is_made_again_at_start(
    paths: DataPaths, conn: sqlite3.Connection, found: dict[str, object]
):
    keep_checked(conn, **found)  # a card busy, or a driver mid-update, that once
    pc, _, _ = make_check(paths, DESKTOP, program=stood_in())

    pc.refresh()
    pc.wait()

    again = hardware.checked_here(conn)
    assert again is not None
    assert (again.encoder, again.directml, again.player) == ("nvenc", True, "h264_mf")
    assert hardware.measured(conn) is None  # checked again, not timed


def test_a_new_card_is_timed_anew_and_a_new_driver_only_checked(
    paths: DataPaths, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MAKU_FAKE_FPS", "480")
    keep_checked(conn)
    hardware.keep_speeds(conn, {"megapixels": 999.0}, NOW)

    updated = replace(DESKTOP, cards=(replace(GTX, driver="620.10"),))
    pc, _, _ = make_check(paths, updated, program=stood_in())
    pc.refresh()
    pc.wait()
    assert hardware.stored(conn)[0] == updated
    assert hardware.speeds(conn).megapixels == 999.0  # the same card: its times stay

    pc, _, _ = make_check(paths, replace(DESKTOP, cards=(RX,)), program=stood_in())
    pc.refresh()
    pc.wait()
    assert hardware.speeds(conn).megapixels == pytest.approx(480 * FULL_HD, rel=0.3)  # anew
    measured = hardware.measured(conn)
    assert measured is not None
    assert measured.tested


def test_windows_not_answering_keeps_what_the_pc_measured(
    paths: DataPaths, conn: sqlite3.Connection
):
    keep_checked(conn)
    hardware.keep_speeds(conn, {"megapixels": 200.0}, NOW)
    hardware.learn_hearing(conn, "best", 1440.0, 432.0, NOW)
    pc, _, _ = make_check(paths, None, program=stood_in())  # PowerShell timed out, say

    pc.refresh()
    pc.wait()

    assert hardware.speeds(conn) == Speeds(megapixels=200.0)
    assert hardware.hearing(conn)["best"] == pytest.approx(0.3)
    assert hardware.stored(conn)[0] == DESKTOP  # the cards as they were
    assert pc.facts() == DESKTOP


def test_testing_while_the_queue_has_the_card_only_checks(
    paths: DataPaths, conn: sqlite3.Connection
):
    pc, _, _ = make_check(paths, DESKTOP, program=stood_in(), busy=True)

    assert pc.test()
    pc.wait()

    assert hardware.checked_here(conn) is not None
    assert hardware.measured(conn) is None  # the times would be off with the card shared


def test_a_test_looks_at_windows_again(paths: DataPaths, conn: sqlite3.Connection):
    pc, looking, _ = make_check(paths, DESKTOP, program=stood_in())
    assert pc.facts() == DESKTOP

    looking.facts = replace(DESKTOP, cards=(RX,))
    assert pc.test()
    pc.wait()

    assert pc.facts().cards == (RX,)
    assert hardware.stored(conn)[0] == looking.facts
    measured = hardware.measured(conn)
    assert measured is not None
    assert measured.tested


def test_nothing_is_checked_without_ffmpeg(paths: DataPaths, conn: sqlite3.Connection):
    pc, _, _ = make_check(paths, DESKTOP)

    assert not pc.ready()
    assert not pc.test()
    pc.refresh()
    pc.wait()

    assert pc.testing() is None
    assert hardware.stored(conn) == (None, None)


def test_a_test_asked_for_while_the_pc_is_checked_follows_the_check(
    paths: DataPaths, conn: sqlite3.Connection
):
    started = threading.Event()
    going = threading.Event()

    class Slow:
        """Windows answering slowly, the first time, while the engine's check looks."""

        calls = 0

        def __call__(self) -> Facts:
            Slow.calls += 1
            if Slow.calls == 1:
                started.set()
                going.wait(10)
            return DESKTOP

    pc = PcCheck(paths, lambda: stood_in(), now=lambda: NOW, looking=Slow())
    pc.refresh()
    started.wait(10)

    assert pc.test()  # taken, though a check is under way
    going.set()
    pc.wait(30)

    measured = hardware.measured(conn)
    assert measured is not None
    assert measured.tested


def test_a_test_asked_for_while_the_engine_looks_at_a_checked_pc_runs(
    paths: DataPaths, conn: sqlite3.Connection
):
    keep_checked(conn)
    started, going = threading.Event(), threading.Event()

    def slowly() -> Facts:
        started.set()
        going.wait(10)
        return DESKTOP

    pc = PcCheck(paths, lambda: stood_in(), now=lambda: NOW, looking=slowly)
    pc.refresh()
    started.wait(10)

    assert pc.test()
    going.set()
    pc.wait(30)

    measured = hardware.measured(conn)
    assert measured is not None
    assert measured.tested
    assert pc.testing() is None


FAKE_ENGINE = [sys.executable, str(Path(__file__).parent / "fake_engine.py")]


def apart() -> Programs:
    """The stand-ins, trying DirectML in a process of its own, as the engine does."""

    def never() -> bool:
        raise AssertionError("the engine's own process loaded a model on the card")

    return replace(stood_in(), directml=never, engine=FAKE_ENGINE)


def test_directml_is_tried_in_a_process_of_its_own():
    (found, _), _ = checked(program=apart())  # the engine's own DirectML isn't touched

    assert found.directml


@pytest.mark.parametrize("what", ["no", "crash"])
def test_a_card_that_fails_directml_takes_only_its_own_process(
    monkeypatch: pytest.MonkeyPatch, what: str
):
    monkeypatch.setenv("MAKU_FAKE_DIRECTML", what)

    (found, _), _ = checked(timing=True, program=apart())

    assert not found.directml  # and the check went on: the engine is still here
    assert found.encoder == "nvenc"
