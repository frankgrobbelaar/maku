"""Running ffprobe on one file, and saying why when it can't read it."""

import sys
from pathlib import Path

import pytest

from maku.core.media import media_from_ffprobe
from maku.probe import ProbeError, ProbeToolError, probe

FAKE = [sys.executable, str(Path(__file__).with_name("fake_ffprobe.py"))]


def test_a_readable_file_gives_ffprobes_report(tmp_path: Path):
    episode = tmp_path / "Quiet Hours - 003 - The Night Train.mkv"

    report = probe(FAKE, episode)

    media = media_from_ffprobe(report)
    assert media.video is not None
    assert (media.video.codec, media.video.width, media.video.height) == ("hevc", 720, 540)
    assert media.duration == pytest.approx(1244.2, abs=0.01)


def test_a_damaged_file_says_what_ffprobe_found(tmp_path: Path):
    with pytest.raises(ProbeError) as raised:
        probe(FAKE, tmp_path / "broken episode.mkv")

    assert str(raised.value) == (
        "Maku couldn't read it (Invalid data found when processing input). "
        "It may be damaged, or not a video."
    )


def test_a_file_ffprobe_hangs_on_is_given_up_on(tmp_path: Path):
    with pytest.raises(ProbeError, match="spent more than 1 seconds on it"):
        probe(FAKE, tmp_path / "stuck.mkv", timeout=1)


def test_a_missing_ffprobe_is_ffprobes_problem_not_the_files(tmp_path: Path):
    with pytest.raises(ProbeToolError, match="ffprobe couldn't start"):
        probe(tmp_path / "ffprobe.exe", tmp_path / "episode.mkv")


def test_an_ffprobe_that_doesnt_work_at_all_is_its_own_problem(tmp_path: Path):
    with pytest.raises(ProbeToolError) as raised:
        probe([*FAKE, "--broken"], tmp_path / "episode.mkv")

    assert str(raised.value) == "ffprobe stopped with code 1"


def test_a_file_that_crashes_ffprobe_is_the_files_problem(tmp_path: Path):
    # ffprobe still answers -version, so it works: this file is what it can't cope with.
    with pytest.raises(ProbeError) as raised:
        probe(FAKE, tmp_path / "fault.mkv")

    assert str(raised.value) == (
        "Maku couldn't read it (ffprobe stopped with code 0xC0000005: Something went wrong "
        "inside ffprobe). It may be damaged, or not a video."
    )
