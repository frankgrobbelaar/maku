"""Playing a video inside Maku's window: tickets, subtitles copied out once, and the stream, with
ffmpeg stood in for (tests/fake_ffmpeg.py)."""

import string
import time
from collections.abc import Callable
from pathlib import Path

import anyio
import pytest

from maku.config import DataPaths
from maku.core.fields import Json
from maku.player import KEPT, TICKETS, Player, PlayerError, State, UnknownTicketError
from tests.converting import FAKE_FFMPEG

REPORT: Json = {
    "streams": [
        {"index": 0, "codec_type": "video", "codec_name": "hevc", "field_order": "progressive"},
        {"index": 1, "codec_type": "audio", "codec_name": "flac", "channels": 2,
         "tags": {"language": "jpn"}, "disposition": {"default": 1}},
        {"index": 2, "codec_type": "audio", "codec_name": "ac3", "channels": 6,
         "tags": {"language": "eng"}},
        {"index": 3, "codec_type": "subtitle", "codec_name": "ass", "tags": {"language": "eng"}},
        {"index": 4, "codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle"},
        {"index": 5, "codec_type": "attachment", "codec_name": "ttf",
         "tags": {"filename": "Gandhi Sans.ttf", "mimetype": "application/x-truetype-font"}},
    ],
    "format": {"format_name": "matroska,webm", "duration": "1440.0"},
}  # fmt: skip


@pytest.fixture
def player(paths: DataPaths) -> Player:
    return Player(paths, lambda: FAKE_FFMPEG)


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "Videos" / "Quiet Hours (2015) - S01E03.mkv"
    path.parent.mkdir()
    path.write_bytes(b"an episode")
    return path


def wait_for(happened: Callable[[], bool]) -> bool:
    for _ in range(100):
        if happened():
            return True
        time.sleep(0.05)
    return False


def settled(player: Player, ticket: str) -> State:
    """The ticket's state once no subtitles are being copied out."""
    assert wait_for(lambda: not player.state(ticket).preparing)
    return player.state(ticket)


def played(player: Player, ticket: str, **choices: object) -> bytes:
    """Everything the stream gave, start to end."""

    async def watch() -> bytes:
        out = b""
        async for chunk in player.stream(ticket, **choices):  # type: ignore[arg-type]
            out += chunk
        return out

    return anyio.run(watch)


def test_a_video_opened_starts_with_its_own_picks_and_its_subtitles_copied_out(
    player: Player, video: Path
):
    opened = player.open(video, REPORT)

    assert len(opened.ticket) >= 32
    assert (opened.sound, opened.subtitles) == (0, 0)  # the Japanese it marks, its first subtitles
    assert player.state(opened.ticket).ready == (1,)  # the pictures need no copy
    assert player.prepare(opened.ticket, 0).preparing == (0,)
    state = settled(player, opened.ticket)
    assert state.ready == (0, 1)  # the copy, and the pictures, which need none
    [copied] = player.folder.iterdir()
    assert sorted(path.name for path in copied.iterdir()) == ["0.ass", "fonts"]
    assert [font.name for font in (copied / "fonts").iterdir()] == ["0.ttf"]  # Maku's own name


def test_subtitle_files_beside_the_video_are_ready_at_once(player: Player, video: Path):
    beside = video.with_name(f"{video.stem}.en.srt")
    beside.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")

    opened = player.open(video, REPORT)

    track = opened.playable.track(2)
    assert track is not None
    assert (track.beside, track.language) == (beside, "en")
    assert player.state(opened.ticket).ready == (1, 2)


def test_subtitles_copied_once_are_ready_the_next_time(player: Player, video: Path):
    first = player.open(video, REPORT)
    player.prepare(first.ticket, 0)
    settled(player, first.ticket)

    again = player.open(video, REPORT)

    assert player.state(again.ticket).ready == (0, 1)


def test_nothing_plays_without_ffmpeg(paths: DataPaths, video: Path):
    with pytest.raises(PlayerError, match="no ffmpeg"):
        Player(paths, lambda: None).open(video, REPORT)


def test_only_the_latest_videos_tickets_work(player: Player, video: Path):
    tickets = [player.open(video, REPORT).ticket for _ in range(TICKETS + 1)]

    with pytest.raises(UnknownTicketError):
        player.state(tickets[0])
    assert player.state(tickets[-1]) is not None


def test_subtitles_that_cant_be_copied_say_why(
    player: Player, video: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MAKU_FAKE_FAIL", "subtitles")
    opened = player.open(video, REPORT)

    player.prepare(opened.ticket, 0)

    state = settled(player, opened.ticket)
    assert state.ready == (1,)
    [(number, problem)] = state.failed
    assert number == 0
    assert problem.startswith("ffmpeg couldn't copy them out (Subtitle encoding")
    with pytest.raises(PlayerError, match="no such subtitles"):
        player.prepare(opened.ticket, 7)


def test_the_stream_plays_from_the_point_asked_with_the_sound_and_subtitles_chosen(
    player: Player, video: Path
):
    opened = player.open(video, REPORT)
    player.prepare(opened.ticket, 0)
    settled(player, opened.ticket)

    out = played(player, opened.ticket, at=192.5, sound=1, subtitles=0).decode()

    assert out.count("fmp4") == 3
    assert "-ss 192.500 -copyts" in out
    assert "-map 0:a:1" in out
    assert "subtitles=filename=" in out
    assert "fontsdir=" in out
    assert "h264_mf" in out  # Windows' own encoder first


def test_picture_subtitles_are_laid_over_and_none_can_be_chosen(player: Player, video: Path):
    opened = player.open(video, REPORT)

    out = played(player, opened.ticket, at=0, sound=None, subtitles=1).decode()

    assert "[base][0:s:1]overlay" in out
    assert "-an" in out


def test_subtitles_not_ready_yet_wait(player: Player, video: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAKU_FAKE_SLOW", "2")
    opened = player.open(video, REPORT)
    player.prepare(opened.ticket, 0)

    with pytest.raises(PlayerError, match="aren't ready yet"):
        played(player, opened.ticket, at=0, sound=0, subtitles=0)
    with pytest.raises(PlayerError, match="no such sound"):
        played(player, opened.ticket, at=0, sound=5, subtitles=None)


def test_a_video_that_wont_play_says_why_before_any_bytes(
    player: Player, video: Path, monkeypatch: pytest.MonkeyPatch
):
    opened = player.open(video, REPORT)
    monkeypatch.setenv("MAKU_FAKE_FAIL", "stream")

    with pytest.raises(PlayerError, match="damaged there"):
        played(player, opened.ticket, at=0, sound=0, subtitles=None)
    stopped = player.state(opened.ticket).stopped
    assert stopped is not None
    assert stopped.why == "damaged"
    assert stopped.detail == "[matroska @ 0] Invalid data found when processing input"


def test_an_encoder_this_pc_hasnt_is_passed_over(
    player: Player, video: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MAKU_FAKE_NO_ENCODERS", "h264_mf")  # Windows without its media pack
    opened = player.open(video, REPORT)

    out = played(player, opened.ticket, at=0, sound=0, subtitles=None).decode()

    assert "h264_nvenc" in out
    assert "h264_mf" not in out
    assert player.state(opened.ticket).stopped is None


def test_a_stream_that_stops_part_way_says_why(
    player: Player, video: Path, monkeypatch: pytest.MonkeyPatch
):
    opened = player.open(video, REPORT)
    monkeypatch.setenv("MAKU_FAKE_FAIL", "midstream")

    assert played(player, opened.ticket, at=0, sound=0, subtitles=None)

    stopped = player.state(opened.ticket).stopped
    assert stopped is not None
    assert stopped.why == "damaged"


def test_a_video_gone_while_it_plays_says_so(
    player: Player, video: Path, monkeypatch: pytest.MonkeyPatch
):
    opened = player.open(video, REPORT)
    video.unlink()
    monkeypatch.setenv("MAKU_FAKE_FAIL", "midstream")

    played(player, opened.ticket, at=0, sound=0, subtitles=None)

    stopped = player.state(opened.ticket).stopped
    assert stopped is not None
    assert stopped.why == "gone"


def test_a_video_gone_though_ffmpeg_ends_as_if_all_were_well_says_so(player: Player, video: Path):
    # ffmpeg takes a read that fails for the file's end, and ends without a word of trouble.
    opened = player.open(video, REPORT)
    video.unlink()

    played(player, opened.ticket, at=0, sound=0, subtitles=None)

    stopped = player.state(opened.ticket).stopped
    assert stopped is not None
    assert stopped.why == "gone"


def test_a_video_whose_drive_went_says_so(player: Player):
    letter = next(c for c in reversed(string.ascii_uppercase) if not Path(f"{c}:\\").exists())
    opened = player.open(Path(f"{letter}:\\Videos\\Quiet Hours - 01.mkv"), REPORT)

    played(player, opened.ticket, at=0, sound=0, subtitles=None)

    stopped = player.state(opened.ticket).stopped
    assert stopped is not None
    assert stopped.why == "drive"


def test_a_stream_played_to_its_end_tells_of_nothing(player: Player, video: Path):
    opened = player.open(video, REPORT)

    played(player, opened.ticket, at=0, sound=0, subtitles=None)

    assert player.state(opened.ticket).stopped is None


def test_a_new_stream_stops_the_one_before_and_closing_stops_the_last(
    player: Player, video: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MAKU_FAKE_CHUNKS", "endless")
    opened = player.open(video, REPORT)

    async def seek_then_close() -> int:
        before = player.stream(opened.ticket, at=0, sound=0, subtitles=None)
        await anext(before)
        after = player.stream(opened.ticket, at=600, sound=0, subtitles=None)
        await anext(after)
        with anyio.fail_after(10):
            async for _ in before:  # it ends: its ffmpeg was stopped
                pass
        player.close(opened.ticket)
        read = 0
        with anyio.fail_after(10):
            async for _ in after:
                read += 1
        await after.aclose()
        return read

    anyio.run(seek_then_close)
    with pytest.raises(UnknownTicketError):
        player.state(opened.ticket)


def test_the_cache_keeps_the_subtitles_of_the_last_few_videos(player: Player, tmp_path: Path):
    for n in range(KEPT + 2):
        video = tmp_path / "Videos" / f"Quiet Hours (2015) - S01E{n:02}.mkv"
        video.parent.mkdir(exist_ok=True)
        video.write_bytes(b"an episode")
        ticket = player.open(video, REPORT).ticket
        player.prepare(ticket, 0)
        settled(player, ticket)
        time.sleep(0.02)  # each a moment after the last

    assert len(list(player.folder.iterdir())) == KEPT
