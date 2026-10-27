"""Stills from a video for the review screen, and a bigger picture of it for its details: taken
once with ffmpeg, then kept."""

import subprocess
from collections.abc import Sequence
from io import BufferedReader
from pathlib import Path

from fastapi.testclient import TestClient

from maku.config import DataPaths
from maku.stills import picture, still

FFMPEG = Path("C:/Maku/tools/ffmpeg/ffmpeg.exe")


class Frames:
    """Stands in for ffmpeg: writes a picture where it's told to, and counts the calls."""

    def __init__(self, fail: bool = False) -> None:
        self.commands: list[list[str]] = []
        self.fail = fail

    def __call__(self, command: Sequence[str]) -> None:
        self.commands.append(list(command))
        if self.fail:
            raise subprocess.CalledProcessError(1, list(command), stderr=b"Invalid data")
        Path(command[-1]).write_bytes(b"jpeg")


def video(tmp_path: Path) -> Path:
    file = tmp_path / "Downloads" / "[subs] ep03 final.mkv"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"a video")
    return file


def test_a_still_is_taken_at_its_point_then_kept(paths: DataPaths, tmp_path: Path):
    frames = Frames()
    file = video(tmp_path)

    first = still(paths, FFMPEG, file, 1450.0, 1, run=frames)
    again = still(paths, FFMPEG, file, 1450.0, 1, run=frames)

    assert first is not None
    assert first.read_bytes() == b"jpeg"
    assert again == first
    assert len(frames.commands) == 1
    command = frames.commands[0]
    assert command[:2] == [str(FFMPEG), "-nostdin"]  # no key reading: see core/convert.py
    assert command[command.index("-ss") + 1] == "725.00"  # halfway through 24:10


def test_no_ffmpeg_no_length_or_a_damaged_file_gives_no_still(paths: DataPaths, tmp_path: Path):
    file = video(tmp_path)

    assert still(paths, None, file, 1450.0, 0, run=Frames()) is None
    assert still(paths, FFMPEG, file, None, 0, run=Frames()) is None
    assert still(paths, FFMPEG, file, 1450.0, 5, run=Frames()) is None
    assert still(paths, FFMPEG, file, 1450.0, 0, run=Frames(fail=True)) is None
    assert not list((paths.cache / "stills").glob("*.partial.jpg"))


def test_a_videos_picture_is_a_bigger_frame_kept_apart_from_the_stills(
    paths: DataPaths, tmp_path: Path
):
    frames = Frames()
    file = video(tmp_path)

    small = still(paths, FFMPEG, file, 1450.0, 0, run=frames)
    big = picture(paths, FFMPEG, file, 1450.0, run=frames)
    again = picture(paths, FFMPEG, file, 1450.0, run=frames)

    assert big is not None
    assert big != small
    assert again == big
    assert len(frames.commands) == 2
    command = frames.commands[1]
    assert command[command.index("-ss") + 1] == "217.50"  # as the first still: 15% in
    # A card's width at most, its pixels square: an SD video's are often wider or narrower.
    scale = command[command.index("-vf") + 1]
    assert scale == "scale=w='trunc(min(1280,iw*sar)/2)*2':h='trunc(ow/dar/2)*2',setsar=1"
    assert picture(paths, None, file, 1450.0, run=frames) is None


def test_a_still_ffmpeg_couldnt_take_isnt_asked_for_again_till_the_video_changes(
    paths: DataPaths, tmp_path: Path
):
    file = video(tmp_path)

    assert picture(paths, FFMPEG, file, 1450.0, run=Frames(fail=True)) is None
    again = Frames()
    assert picture(paths, FFMPEG, file, 1450.0, run=again) is None
    assert again.commands == []  # not asked: it failed on this very file

    file.write_bytes(b"a video, repaired")
    assert picture(paths, FFMPEG, file, 1450.0, run=again) is not None
    assert len(again.commands) == 1


def test_two_asking_at_once_share_the_picture_the_first_kept(paths: DataPaths, tmp_path: Path):
    file = video(tmp_path)
    first = picture(paths, FFMPEG, file, 1450.0, run=Frames())
    assert first is not None
    first.unlink()
    held: list[BufferedReader] = []

    def beaten(command: Sequence[str]) -> None:
        """Takes its frame as another asking at the same time keeps theirs and holds it open,
        so this one's can't take its place."""
        Path(command[-1]).write_bytes(b"jpeg")
        first.write_bytes(b"the other's")
        held.append(first.open("rb"))

    try:
        found = picture(paths, FFMPEG, file, 1450.0, run=beaten)
    finally:
        for handle in held:
            handle.close()

    assert found == first
    assert first.read_bytes() == b"the other's"
    assert not list((paths.cache / "stills").glob("*.partial.jpg"))


def test_the_review_screen_gets_no_still_before_ffmpeg_is_there(client: TestClient):
    assert client.get("/review/1/stills/0").status_code == 404
