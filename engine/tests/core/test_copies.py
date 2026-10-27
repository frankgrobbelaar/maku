"""Choosing the better of two copies, as the tidy board's example shows."""

from fractions import Fraction
from pathlib import PureWindowsPath

from maku.core.copies import Copy, choose_copy
from maku.core.media import Audio, MediaInfo, Subtitle, Video

ENGLISH = Audio("aac", 2, "eng", False)
FRENCH = Audio("aac", 2, "fra", False)
ENGLISH_SUBS = Subtitle("ass", "eng", text=True, forced=False)


def copy(
    name: str,
    height: int,
    *,
    codec: str = "h264",
    audio: tuple[Audio, ...] = (ENGLISH,),
    subtitles: tuple[Subtitle, ...] = (),
    size: int = 300_000_000,
    broken: bool = False,
    bit_depth: int = 8,
    maku_tag: str | None = None,
) -> Copy:
    width = round(height * 16 / 9)
    video = Video(codec, width, height, Fraction(16, 9), Fraction(24000, 1001), bit_depth, False)
    media = MediaInfo("mkv", 1400.0, size, video, audio, subtitles, maku_tag=maku_tag)
    return Copy(PureWindowsPath(rf"D:\Videos\Downloads\{name}"), media, broken)


def test_the_tidy_boards_example():
    better = copy(
        "[GRP] Glass_Orchard_07 (720p).mkv",
        720,
        audio=(ENGLISH, FRENCH),
        subtitles=(ENGLISH_SUBS,),
        size=352_000_000,
    )
    worse = copy("Glass Orchard 07.avi", 480, codec="mpeg4", size=175_000_000)

    choice = choose_copy([worse, better])

    assert choice.keep == better
    assert choice.drop == (worse,)
    assert (
        choice.reason == "Higher resolution, an extra audio track and subtitles you can switch off"
    )


def test_a_broken_copy_always_loses():
    broken = copy("big.mkv", 1080, broken=True)
    working = copy("small.mkv", 480)

    choice = choose_copy([broken, working])

    assert (choice.keep, choice.reason) == (working, "The other copy doesn't play")


def test_a_copy_maku_already_converted_wins_at_the_same_size():
    plain = copy("a.mkv", 1080, size=900_000_000)
    converted = copy("b.mkv", 1080, codec="hevc", bit_depth=10, maku_tag="Cinema 1080p")

    choice = choose_copy([plain, converted])

    assert (choice.keep, choice.reason) == (converted, "Already converted by Maku")


def test_otherwise_the_larger_file_wins():
    small = copy("a.mkv", 1080, size=300_000_000)
    large = copy("b.mkv", 1080, size=900_000_000)

    choice = choose_copy([small, large])

    assert (choice.keep, choice.reason) == (large, "A larger file, so more detail")


def test_three_copies_keep_one_and_drop_two():
    copies = [copy("a.mkv", 480), copy("b.mkv", 1080), copy("c.mkv", 720)]

    choice = choose_copy(copies)

    assert choice.keep == copies[1]
    assert set(choice.drop) == {copies[0], copies[2]}


def test_identical_copies_keep_the_first():
    first, second = copy("a.mkv", 720), copy("b.mkv", 720)

    choice = choose_copy([first, second])

    assert (choice.keep, choice.reason) == (first, "The copies are the same; the first is kept")


def test_an_unreadable_copy_loses_to_a_readable_one():
    unreadable = Copy(PureWindowsPath(r"D:\x.mkv"), None)
    readable = copy("y.mkv", 480)

    assert choose_copy([unreadable, readable]).keep == readable


def test_the_original_wins_over_a_copy_of_it():
    copied, original = copy("Glass Orchard 07 (copy).mkv", 480), copy("Glass Orchard 07.mkv", 480)

    choice = choose_copy([copied, original])

    assert choice.keep is original
    assert choice.reason == "The other is named as a copy"
