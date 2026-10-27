"""See it first: a frame before converting and after, with ffmpeg stood in for."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from maku.config import DataPaths
from maku.core.media import media_from_ffprobe
from maku.core.standard import FULL_HD, UHD
from maku.preview import PreviewError, frame
from tests.converting import programs, report


@pytest.fixture
def film(tmp_path: Path) -> Path:
    path = tmp_path / "Quiet Hours (2021).mkv"
    path.write_bytes(b"a film")
    return path


WEB = media_from_ffprobe(report(1920, 1080, codec="h264"))
UHD_FILM = media_from_ffprobe(report(3840, 2160))
AT_STANDARD = media_from_ffprobe(report(1920, 1080, tag="someone's"))


def test_before_is_the_original_frame(paths: DataPaths, film: Path):
    commands: list[Sequence[str]] = []

    picture = frame(paths, programs({}, commands), film, WEB, UHD, side="before", point=1)

    assert picture.suffix == ".png"
    [command] = commands
    assert command[command.index("-ss") + 1] == "720.00"  # halfway through 24 minutes
    assert "-vf" not in command


def test_after_is_made_as_converting_makes_it_and_kept(paths: DataPaths, film: Path):
    commands: list[Sequence[str]] = []
    kit = programs({}, commands)

    first = frame(paths, kit, film, UHD_FILM, FULL_HD, side="after", point=2)
    again = frame(paths, kit, film, UHD_FILM, FULL_HD, side="after", point=2)

    assert first == again
    [command] = commands  # made once
    assert command[command.index("-vf") + 1] == (
        "scale=1920:1080:flags=lanczos,setsar=1,format=yuv420p"
    )
    assert first.read_bytes().startswith(b"png of ")


def test_a_picture_converting_only_copies_looks_the_same_after(paths: DataPaths, film: Path):
    commands: list[Sequence[str]] = []
    kit = programs({}, commands)
    remuxed = media_from_ffprobe(
        {**report(1920, 1080), "format": {"format_name": "mp4", "duration": "1440.0"}}
    )

    before = frame(paths, kit, film, remuxed, UHD, side="before", point=0)
    after = frame(paths, kit, film, remuxed, UHD, side="after", point=0)

    assert after == before  # the picture is copied as it is
    assert len(commands) == 1


def test_a_frame_ffmpeg_cant_make_says_why(
    paths: DataPaths, film: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MAKU_FAKE_FAIL", "frame")

    with pytest.raises(PreviewError, match="Invalid data found when processing input"):
        frame(paths, programs({}), film, WEB, UHD, side="before", point=0)

    assert not list((paths.cache / "previews").glob("*.png"))


def test_a_file_without_a_picture_has_no_frame(paths: DataPaths, film: Path):
    sound = media_from_ffprobe({"format": {"duration": "60"}, "streams": []})

    with pytest.raises(PreviewError):
        frame(paths, programs({}), film, sound, UHD, side="before", point=0)


def test_a_file_at_the_standard_shows_itself_on_both_sides(paths: DataPaths, film: Path):
    commands: list[Sequence[str]] = []

    after = frame(paths, programs({}, commands), film, AT_STANDARD, UHD, side="after", point=1)

    [command] = commands
    assert "-vf" not in command
    assert after.read_bytes().startswith(b"png of ")
