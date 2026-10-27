"""The languages a video can be heard and read in: its sound tracks', its subtitle tracks', and
those of subtitle files beside it ("Episode 1.en.srt"), and whether English is among them."""

from collections.abc import Iterable, Sequence
from pathlib import PurePath

_ENGLISH = frozenset({"eng", "en", "english"})
# Words a subtitle file's name carries besides its language: "Episode 1.en.forced.srt", and
# "Episode 1.maku.en.srt", Maku's own when another file has the first name.
_FLAGS = frozenset({"forced", "sdh", "cc", "hi", "default", "full", "signs", "maku"})


def is_english(language: str) -> bool:
    """English, however a file names it: "eng", "en", "English", "en-US"."""
    code = language.casefold()
    return code in _ENGLISH or code.startswith(("en-", "en_"))


def track_languages(languages: Iterable[str | None]) -> list[str]:
    """Each track's language as Maku keeps it: "jpn", or "" for one that doesn't say."""
    return [(language or "").casefold() for language in languages]


def beside_language(subtitle: PurePath, video: PurePath) -> str:
    """The language a subtitle file beside `video` names: "en" for "Episode 1.en.srt", "english"
    for "Episode 1.English.forced.ass", and "" for "Episode 1.srt"."""
    parts = subtitle.name[len(video.stem) :].split(".")[1:-1]
    return next((part.casefold() for part in parts if part and part.casefold() not in _FLAGS), "")


def heard_in(sound: Sequence[str], track: int | None, heard: str | None) -> list[str]:
    """Each sound track's language, with the one Whisper heard (`heard`, "ja") in the track Maku
    made English subtitles from (`track`, from 0) when that track doesn't say its own."""
    languages = list(sound)
    if heard and track is not None and 0 <= track < len(languages) and not languages[track]:
        languages[track] = heard
    return languages


def listed(languages: Sequence[str]) -> list[str]:
    """Each language once, in the order first met."""
    return list(dict.fromkeys(languages))
