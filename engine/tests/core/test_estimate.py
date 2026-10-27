"""Time and space estimates, from speeds measured on the owner's GTX 1660 Super (2026-10-27:
NVENC's HEVC 10-bit at preset p6, made-up grainy clips decoded on the i5-9600K)."""

from fractions import Fraction

import pytest

from maku.core.estimate import (
    PICTURE_RATES,
    Estimate,
    Speeds,
    estimate,
    hearing,
    picture_rate,
    result_bytes,
    sound_rate,
    total,
)
from maku.core.media import Audio, MediaInfo, Video
from maku.core.standard import Decision, Method

FILM = Fraction(24000, 1001)
HOUR = 3600.0
TRUEHD = Audio("truehd", 8, "eng", True, bit_rate=4_000_000)
EAC3 = Audio("eac3", 6, "eng", False, bit_rate=640_000)


def video(
    width: int = 1920,
    height: int = 1080,
    *,
    seconds: float = HOUR,
    size: int = 3_000_000_000,
    rate: Fraction | None = FILM,
    picture: int | None = None,
    audio: tuple[Audio, ...] = (EAC3,),
) -> MediaInfo:
    shape = Fraction(width, height)
    found = Video("h264", width, height, shape, rate, 8, False, bit_rate=picture)
    return MediaInfo("mkv", seconds, size, found, audio)


def reencoded(media: MediaInfo, width: int = 0, height: int = 0) -> Decision:
    picture = media.video
    assert picture is not None
    return Decision(Method.REENCODE, width or picture.width, height or picture.height)


@pytest.mark.parametrize(
    ("width", "height", "rate", "fps"),
    [
        (720, 480, Fraction(30000, 1001), 984),  # a DVD, deinterlaced as it was
        (1280, 720, FILM, 387),
        (1920, 1080, FILM, 180),
        (3840, 2160, FILM, 46),
    ],
)
def test_each_size_takes_about_what_was_measured(
    width: int, height: int, rate: Fraction, fps: float
):
    source = video(width, height, rate=rate)

    result = estimate(source, reencoded(source))

    frames = HOUR * float(rate)
    assert result.gpu_seconds == pytest.approx(frames / fps, rel=0.1)


def test_bringing_4k_down_takes_what_reading_4k_takes():
    source = video(3840, 2160)

    down = estimate(source, reencoded(source, 1920, 1080))

    assert down.gpu_seconds == estimate(source, reencoded(source)).gpu_seconds


def test_a_measured_pc_replaces_the_guess():
    source = video()
    twice_as_fast = Speeds(megapixels=Speeds().megapixels * 2)

    measured = estimate(source, reencoded(source), twice_as_fast)

    assert measured.gpu_seconds == pytest.approx(
        estimate(source, reencoded(source)).gpu_seconds / 2
    )


def test_a_new_picture_comes_to_its_sizes_rate_with_the_sound_as_it_was():
    two_hours = 7200.0
    sound = TRUEHD.bit_rate or 0
    picture = 25_000_000  # a Blu-ray's
    remux = video(
        seconds=two_hours,
        size=round((picture + sound) * two_hours / 8),
        picture=picture,
        audio=(TRUEHD,),
    )

    result = estimate(remux, reencoded(remux))

    new_picture = PICTURE_RATES["1080p"] * two_hours / 8
    assert result.output_bytes == pytest.approx(new_picture + sound * two_hours / 8)
    assert result.output_bytes / 1e9 == pytest.approx(9.9, abs=0.1)  # from 26.1 GB


def test_a_new_picture_is_never_bigger_than_the_originals():
    web = video(size=2_700_000_000, picture=5_000_000)  # 6 Mb/s all told, 5 of it the picture

    assert result_bytes(web, reencoded(web)) == 2_700_000_000


def test_4k_brought_down_comes_to_1080ps_rate():
    film = video(3840, 2160, size=30_000_000_000, picture=60_000_000)

    down = result_bytes(film, reencoded(film, 1920, 1080))

    old_picture = 60_000_000 * HOUR / 8
    assert down == round(30_000_000_000 - old_picture + PICTURE_RATES["1080p"] * HOUR / 8)


def test_a_picture_that_doesnt_say_its_rate_is_the_file_less_its_sound():
    quiet = video(size=3_600_000_000)  # 8 Mb/s all told, Dolby Digital Plus at 640 kb/s

    assert picture_rate(quiet) == pytest.approx(8_000_000 - 640_000)


def test_sound_that_doesnt_say_counts_as_such_sound_usually_runs():
    unsaid = (Audio("truehd", 8, "eng", True), Audio("aac", 2, "eng", False))

    assert sound_rate(video(audio=unsaid)) == 4_000_000 + 640_000
    assert sound_rate(video(audio=(TRUEHD, EAC3))) == 4_640_000


def test_a_file_that_doesnt_say_how_long_it_plays_is_reckoned_by_its_picture_alone():
    unknown = MediaInfo(
        "avi", None, None, Video("mpeg4", 640, 352, Fraction(20, 11), None, 8, False)
    )

    assert picture_rate(unknown) is None
    assert estimate(unknown, reencoded(unknown)) == Estimate(0.0, 0)


def test_renaming_and_remuxing_need_no_graphics_card_and_keep_the_size():
    source = video(size=1_000_000)
    for method in (Method.RENAME, Method.REMUX):
        result = estimate(source, Decision(method, 1920, 1080))

        assert result == Estimate(gpu_seconds=0.0, output_bytes=1_000_000)


def test_a_skipped_file_costs_nothing():
    assert estimate(video(), Decision(Method.SKIP)) == Estimate(0.0, 0)


def test_an_unknown_frame_rate_counts_as_film():
    unknown = video(rate=None)

    assert estimate(unknown, reencoded(unknown)).gpu_seconds == pytest.approx(
        estimate(video(), reencoded(video())).gpu_seconds
    )


def test_total_of_nothing_is_nothing():
    assert total([]) == Estimate(0.0, 0)


@pytest.mark.parametrize(("quality", "minutes"), [("best", 9.6), ("fast", 3.6)])
def test_english_subtitles_take_about_what_was_measured(quality: str, minutes: float):
    assert hearing(24 * 60, quality) / 60 == pytest.approx(minutes)
