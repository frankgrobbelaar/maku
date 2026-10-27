"""English from another copy: what's taken, what lines the copies up, and ffmpeg's command."""

from fractions import Fraction
from pathlib import PureWindowsPath

from maku.core.media import Audio, MediaInfo, Subtitle, Video
from maku.core.merge import Borrowed, borrowed, merge_command, movable, shared_sound

PICTURE = Video("hevc", 1920, 1080, Fraction(16, 9), None, 10, False)


def copy(
    sound: list[str | None], subtitles: list[tuple[str, str | None]], fonts: int = 0
) -> MediaInfo:
    return MediaInfo(
        "mkv",
        1440.0,
        1_000_000_000,
        PICTURE,
        tuple(Audio("aac", 2, language, False) for language in sound),
        tuple(
            Subtitle(codec, language, codec != "hdmv_pgs_subtitle", False)
            for codec, language in subtitles
        ),
        fonts,
    )


KEPT = copy(["jpn"], [("ass", "ger")])
OTHER = copy(["jpn", "eng"], [("hdmv_pgs_subtitle", "eng"), ("mov_text", "en")], fonts=2)


def test_the_english_the_kept_copy_lacks_is_taken():
    assert borrowed(KEPT, OTHER) == Borrowed(sound=(1,), subtitles=(0, 1))


def test_english_the_kept_copy_has_already_isnt():
    subtitled = copy(["jpn"], [("ass", "eng")])
    dubbed = copy(["jpn", "eng"], [])

    assert borrowed(subtitled, OTHER) == Borrowed(sound=(1,), subtitles=())
    assert borrowed(dubbed, OTHER) == Borrowed(sound=(), subtitles=(0, 1))
    assert not borrowed(copy(["jpn", "eng"], [("ass", "eng")]), OTHER).any
    # English subtitles beside the kept copy count as its own.
    assert borrowed(KEPT, OTHER, beside=["en"]) == Borrowed(sound=(1,), subtitles=())


def test_the_copies_line_up_by_the_kept_copys_first_language_the_other_has_too():
    assert shared_sound(KEPT, OTHER) == (0, 0)
    # The kept copy's order decides: no language goes first of its own.
    assert shared_sound(copy(["ger", "jpn"], []), copy(["eng", "ger", "jpn"], [])) == (0, 1)
    assert shared_sound(copy(["fre", "ger"], []), copy(["ger", "fre"], [])) == (0, 1)
    assert shared_sound(copy([None, "ger"], []), copy(["eng", "ger"], [])) == (1, 1)
    assert shared_sound(copy(["ger"], []), copy(["eng", "ger"], [])) == (0, 1)
    assert shared_sound(copy(["jpn"], []), copy(["eng"], [])) is None
    assert shared_sound(copy([None], []), copy([None], [])) is None


def command_for(offset: float) -> str:
    return " ".join(
        merge_command(
            ["ffmpeg"],
            PureWindowsPath("D:/Videos/Ep 7.mkv"),
            PureWindowsPath("D:/Videos/ep07 dvd.mkv"),
            offset,
            movable(borrowed(KEPT, OTHER), OTHER, offset),
            KEPT,
            OTHER,
            PureWindowsPath("D:/Videos/Ep 7.mkv.maku-converting"),
        )
    )


def test_an_earlier_copys_english_is_copied_as_it_is_and_waits_till_its_moment():
    text = command_for(-2.5)  # the other copy runs 2.5 s earlier

    assert r"-itsoffset 2.500 -i D:\Videos\ep07 dvd.mkv" in text
    assert "-map 0:V -map 0:a? -map 0:s? -map 0:t?" in text
    assert "-map 1:a:1 -map 1:s:0 -map 1:s:1 -map 1:t?" in text
    assert "-c copy" in text
    assert "-disposition:a:1 0" in text  # the English sound follows the kept copy's one
    assert "-disposition:s:1 0 -disposition:s:2 0 -c:s:2 srt" in text  # MP4 text, as SRT
    assert "aac" not in text
    assert "-t 1440.500" in text  # ending with the copy kept, not with the other's English
    assert text.endswith(r"-f matroska D:\Videos\Ep 7.mkv.maku-converting")


def test_a_later_copys_english_is_read_from_its_moment_its_sound_made_anew():
    text = command_for(4.0)  # the other copy runs 4 s later

    assert r"-ss 4.000 -i D:\Videos\ep07 dvd.mkv" in text
    assert "itsoffset" not in text
    # Subtitles drawn as pictures can't be moved: only the text ones come.
    assert "-map 1:a:1 -map 1:s:1 -map 1:t?" in text
    assert "-c:a:1 aac -b:a:1 192k" in text
    assert "-disposition:s:1 0 -c:s:1 srt" in text


def test_only_text_subtitles_move_earlier():
    take = borrowed(KEPT, OTHER)

    assert movable(take, OTHER, -1.0) == take
    assert movable(take, OTHER, 0.0) == take
    assert movable(take, OTHER, 1.0) == Borrowed(sound=(1,), subtitles=(1,))
