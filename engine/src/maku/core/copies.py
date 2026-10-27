"""When two files are the same episode, which one Maku keeps.

The better copy plays, then has the higher resolution, then the work Maku already did, more
audio tracks, subtitles you can switch off, a deeper picture, more bytes, and finally a name that
isn't a copy's ("(copy)", " - Copy", "(2)"). The others go to quarantine, never straight to
deletion.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath

from maku.core.media import MediaInfo
from maku.core.names import parse_name


@dataclass(frozen=True)
class Copy:
    path: PurePath
    media: MediaInfo | None  # None when ffprobe couldn't read the file
    broken: bool = False


@dataclass(frozen=True)
class Choice:
    keep: Copy
    drop: tuple[Copy, ...]
    reason: str  # why, in the words the tidy board uses


def choose_copy(copies: Sequence[Copy]) -> Choice:
    if not copies:
        raise ValueError("There are no copies to choose from.")
    keep = max(copies, key=_strength)  # max keeps the first of equals
    drop = tuple(c for c in copies if c is not keep)
    runner_up = max(drop, key=_strength) if drop else keep
    return Choice(keep, drop, _sentence(_advantages(keep, runner_up)))


@dataclass(frozen=True)
class _Facts:
    """What decides between copies, in order of importance."""

    height: int
    converted: bool
    audio_tracks: int
    subtitles: bool
    bit_depth: int
    size: int


def _facts(copy: Copy) -> _Facts | None:
    """None for a copy that doesn't play."""
    media = copy.media
    if copy.broken or media is None or media.video is None:
        return None
    return _Facts(
        height=media.video.height,
        converted=media.maku_tag is not None,
        audio_tracks=len(media.audio),
        subtitles=bool(media.subtitles),
        bit_depth=media.video.bit_depth,
        size=media.size or 0,
    )


def _strength(copy: Copy) -> tuple[bool, int, bool, int, bool, int, int, bool]:
    facts = _facts(copy)
    original = not parse_name(copy.path).is_copy
    if facts is None:
        return (False, 0, False, 0, False, 0, 0, original)
    return (
        True,
        facts.height,
        facts.converted,
        facts.audio_tracks,
        facts.subtitles,
        facts.bit_depth,
        facts.size,
        original,
    )


def _advantages(keep: Copy, other: Copy) -> list[str]:
    ours, theirs = _facts(keep), _facts(other)
    if theirs is None:
        return ["The other copy doesn't play"]
    if ours is None:
        return ["Neither copy plays; the first is kept"]
    reasons: list[str] = []
    if ours.height > theirs.height:
        reasons.append("Higher resolution")
    if (extra := ours.audio_tracks - theirs.audio_tracks) > 0:
        reasons.append("an extra audio track" if extra == 1 else f"{extra} more audio tracks")
    if ours.subtitles and not theirs.subtitles:
        reasons.append("subtitles you can switch off")
    if reasons:
        return reasons
    if ours.converted and not theirs.converted:
        return ["Already converted by Maku"]
    if ours.size > theirs.size:
        return ["A larger file, so more detail"]
    if parse_name(other.path).is_copy and not parse_name(keep.path).is_copy:
        return ["The other is named as a copy"]
    return ["The copies are the same; the first is kept"]


def _sentence(parts: list[str]) -> str:
    text = parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
    return text[0].upper() + text[1:]
