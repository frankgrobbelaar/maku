"""English from another copy (maku/merge.py does it): which of the other copy's tracks are English
the copy kept hasn't, which sound both share to line them up by, and the ffmpeg command that adds
those tracks to the copy kept, shifted onto its picture. Pure.

Only what the kept copy lacks is taken: its English sound when it has none, its English subtitles
when it has none. The kept copy's own tracks stay first and as they were (its default ones
still the default); the added ones follow, never the default.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePath

from maku.core.languages import is_english
from maku.core.media import MediaInfo

# Subtitles ffmpeg can't copy into an MKV as they are: written anew as SRT.
_AS_SRT = frozenset({"mov_text", "text", "webvtt"})
_STYLED = frozenset({"ass", "ssa"})  # written anew as ASS when they're moved, styles and all
_PAST = 0.5  # seconds the result may run past the copy kept's length, for its last frame's sake


@dataclass(frozen=True)
class Borrowed:
    """The other copy's tracks to take, by number among its own of that kind (from 0)."""

    sound: tuple[int, ...]
    subtitles: tuple[int, ...]

    @property
    def any(self) -> bool:
        return bool(self.sound or self.subtitles)


def borrowed(kept: MediaInfo, other: MediaInfo, beside: Iterable[str] = ()) -> Borrowed:
    """The English the other copy has in it that the kept one hasn't, in it or beside it
    (`beside`: the languages of the subtitle files named after it, "en")."""
    sound = (
        ()
        if any(is_english(track.language or "") for track in kept.audio)
        else tuple(n for n, track in enumerate(other.audio) if is_english(track.language or ""))
    )
    read = [*(track.language or "" for track in kept.subtitles), *beside]
    subtitles = (
        ()
        if any(is_english(language) for language in read)
        else tuple(n for n, track in enumerate(other.subtitles) if is_english(track.language or ""))
    )
    return Borrowed(sound, subtitles)


def shared_sound(kept: MediaInfo, other: MediaInfo) -> tuple[int, int] | None:
    """A sound track each copy has in the same language, to line them up by: the kept copy's
    first whose language the other has too, no language preferred. Their numbers among each
    copy's sound; None when they share none (sound in two languages doesn't line up)."""
    ours = [(track.language or "").casefold() for track in kept.audio]
    theirs = [(track.language or "").casefold() for track in other.audio]
    language = next((each for each in ours if each and each in theirs), None)
    if language is None:
        return None
    return ours.index(language), theirs.index(language)


def movable(take: Borrowed, other: MediaInfo, offset: float) -> Borrowed:
    """What of the borrowed tracks can be lined up: everything when the other copy runs as late
    as the kept one or earlier (its tracks wait, as they are); when it runs later, its sound
    (made anew from just the right moment) and its text subtitles, but not subtitles drawn as
    pictures, which can't be moved earlier."""
    if offset <= 0:
        return take
    return Borrowed(take.sound, tuple(n for n in take.subtitles if other.subtitles[n].text))


def merge_command(
    ffmpeg: Sequence[str],
    kept: PurePath,
    other: PurePath,
    offset: float,
    take: Borrowed,
    kept_media: MediaInfo,
    other_media: MediaInfo,
    output: PurePath,
) -> list[str]:
    """ffmpeg's command for the kept copy with the other's English added: every stream of the
    kept copy as it is, then the borrowed sound and subtitles (and the other copy's fonts, which
    its styled subtitles may need), lined up with the kept copy's picture. When the other copy
    runs as late or earlier (`offset` at most 0), its tracks are copied as they are and wait
    till their moment; when it runs later, they're read from just the right moment instead, so
    its sound is made anew (AAC) and its text subtitles written anew (`take` from `movable`).
    Text subtitles an MKV can't hold as they are become SRT."""
    later = offset > 0
    command = [
        *ffmpeg,
        *("-nostdin", "-v", "error", "-y", "-i", str(kept)),
        *(("-ss", f"{offset:.3f}") if later else ("-itsoffset", f"{0.0 - offset:.3f}")),
        *("-i", str(other)),
        # The kept copy's picture (never a cover image), sound, subtitles and fonts.
        *("-map", "0:V", "-map", "0:a?", "-map", "0:s?", "-map", "0:t?"),
    ]
    for number in take.sound:
        command += ["-map", f"1:a:{number}"]
    for number in take.subtitles:
        command += ["-map", f"1:s:{number}"]
    if take.subtitles and other_media.fonts:
        command += ["-map", "1:t?"]
    command += ["-c", "copy"]
    for number, track in enumerate(kept_media.subtitles):
        if track.codec in _AS_SRT:
            command += [f"-c:s:{number}", "srt"]
    sounds = len(kept_media.audio)
    for added, number in enumerate(take.sound):
        where = sounds + added
        command += [f"-disposition:a:{where}", "0"]
        if later:
            channels = max(1, other_media.audio[number].channels)
            command += [f"-c:a:{where}", "aac", f"-b:a:{where}", f"{min(96 * channels, 512)}k"]
        if not other_media.audio[number].language:
            command += [f"-metadata:s:a:{where}", "language=eng"]
    subtitles = len(kept_media.subtitles)
    for added, number in enumerate(take.subtitles):
        where = subtitles + added
        command += [f"-disposition:s:{where}", "0"]
        codec = other_media.subtitles[number].codec
        if codec in _AS_SRT or (later and codec not in _STYLED):
            command += [f"-c:s:{where}", "srt"]
        elif later:
            command += [f"-c:s:{where}", "ass"]
    if kept_media.duration:  # the other copy's English ends with this picture, not after it
        command += ["-t", f"{kept_media.duration + _PAST:.3f}"]
    command += ["-map_metadata", "0", "-map_chapters", "0", "-f", "matroska", str(output)]
    return command
