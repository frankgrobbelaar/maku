from pathlib import PurePath

from maku.core.languages import (
    beside_language,
    heard_in,
    is_english,
    listed,
    track_languages,
)


def test_english_is_known_however_a_file_names_it():
    assert all(is_english(code) for code in ("eng", "en", "English", "EN", "en-US", "en_GB"))
    assert not any(is_english(code) for code in ("jpn", "ger", "fre", ""))


def test_a_subtitle_file_beside_a_video_names_its_language():
    video = PurePath("Show (1989) - S01E01.mkv")

    assert beside_language(PurePath("Show (1989) - S01E01.en.srt"), video) == "en"
    assert beside_language(PurePath("Show (1989) - S01E01.English.forced.ass"), video) == "english"
    assert beside_language(PurePath("Show (1989) - S01E01.forced.de.srt"), video) == "de"
    assert beside_language(PurePath("Show (1989) - S01E01.srt"), video) == ""
    # The name Maku gives its own when another file has the first.
    assert beside_language(PurePath("Show (1989) - S01E01.maku.en.srt"), video) == "en"


def test_each_track_keeps_its_language_or_none():
    assert track_languages(["JPN", None, "eng"]) == ["jpn", "", "eng"]


def test_each_language_is_listed_once_in_the_order_first_met():
    assert listed(["jpn", "eng", "jpn", "", ""]) == ["jpn", "eng", ""]


def test_a_track_that_doesnt_say_its_language_has_the_one_whisper_heard_in_it():
    assert heard_in(["jpn", ""], 1, "ja") == ["jpn", "ja"]
    assert heard_in([""], None, "ja") == [""]  # Maku doesn't know which track it heard
    # A track that says its language keeps it, and one Maku heard nothing in stays as it is.
    assert heard_in(["jpn", ""], 0, "ja") == ["jpn", ""]
    assert heard_in(["", ""], 0, None) == ["", ""]
    assert heard_in([""], 3, "ja") == [""]  # a track the video doesn't have now
