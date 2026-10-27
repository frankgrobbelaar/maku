"""The library standard, and what each file needs to reach it.

The standard is a top size, 4K or 1080p, and every picture ends as HEVC 10-bit in an MKV. Nothing
is made bigger than it is: a picture bigger than the standard comes down to it, keeping its shape,
and one at or under it keeps its own size. HDR stays HDR. The sound is kept as it is, every track,
but for Blu-ray's and DVD's PCM, which MKV can't hold: that becomes FLAC, still lossless. A file
already HEVC 10-bit, progressive, in MKV and no bigger than the standard is only renamed.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
from fractions import Fraction

from maku.core.media import MediaInfo, Video


@dataclass(frozen=True)
class Standard:
    name: str  # "4K", as the owner chooses it
    height: int  # the top: 2160 or 1080; widths follow the picture's shape
    codec: str = "hevc"
    bit_depth: int = 10
    container: str = "mkv"


UHD = Standard("4K", 2160)
FULL_HD = Standard("1080p", 1080)
STANDARDS: dict[str, Standard] = {"4k": UHD, "1080p": FULL_HD}  # by the setting's value


class Method(StrEnum):
    RENAME = "rename"  # already at the standard: only the name changes
    REMUX = "remux"  # the picture stays; the container, or sound MKV can't hold, changes
    REENCODE = "reencode"  # a new picture: another codec, brought down, or deinterlaced
    SKIP = "skip"  # nothing to convert


@dataclass(frozen=True)
class Decision:
    method: Method
    width: int = 0
    height: int = 0
    deinterlace: bool = False
    reasons: tuple[str, ...] = ()


# Sound MKV can't hold, which becomes FLAC (lossless, as it was), and what it's called.
TO_FLAC = {"pcm_bluray": "Blu-ray's PCM", "pcm_dvd": "DVD's PCM"}
# Up to 7% over a size still counts as it: cinema's own widths (4096 for 4K, 2048 and 1998 for
# 1080p) and the odd 1920x1088.
_SAME_SIZE = 1.07
# The sizes a picture is called by, with the frame each names: SD (a DVD, or 1024x576 at most),
# then 720p, 1080p, 4K and 8K. A picture is called by the smallest frame it fits.
_SIZES = ((1024, 576, "SD"), (1280, 720, "720p"), (1920, 1080, "1080p"), (3840, 2160, "4K"))


def decide(media: MediaInfo, standard: Standard) -> Decision:
    video = media.video
    if video is None:
        return Decision(Method.SKIP, reasons=("No picture to convert",))
    deinterlace = video.interlaced is True
    extras = _sound_and_container(media, standard)
    if deinterlace:
        extras = ("Interlaced: deinterlaced first", *extras)
    bigger = _bigger(video, standard)
    if video.needs_dolby_vision and (bigger or not _picture_matches(video, standard)):
        # Made anew, its colours would come out wrong: it stays as it is, whatever it misses.
        named = f"{size_name(video.width, video.height)} Dolby Vision"
        kept = f"{named}: kept as it is, as a new picture would spoil its colours"
        method = Method.REMUX if extras else Method.RENAME
        return Decision(method, video.width, video.height, reasons=(kept, *extras))
    width, height = (
        _output_size(video.display_aspect, standard) if bigger else (video.width, video.height)
    )
    hdr = video.hdr
    if bigger:
        named = f"{size_name(video.width, video.height)}{' HDR' if hdr else ''}"
        reason = f"{named}: brought down to {standard.name}{_hdr_kept(hdr)}"
    elif not _picture_matches(video, standard):
        reason = f"{_codec_name(video)} becomes {_target_name(standard)}{_hdr_kept(hdr)}"
    elif extras:
        # A deinterlaced picture is a new one: a remux would copy the old one as it is.
        method = Method.REENCODE if deinterlace else Method.REMUX
        reasons = (*extras, *_dolby_vision_lost(video, method))
        return Decision(method, width, height, deinterlace, reasons)
    else:
        already = f"Already {_target_name(standard)} in MKV: only renamed"
        return Decision(Method.RENAME, width, height, reasons=(already,))
    lost = _dolby_vision_lost(video, Method.REENCODE)
    return Decision(Method.REENCODE, width, height, deinterlace, (reason, *extras, *lost))


def deinterlaced(decision: Decision) -> Decision:
    """A decision for a picture found to be interlaced once converting began (ffprobe couldn't
    tell, idet could): deinterlaced first, and so made anew where it was only to be remuxed."""
    if decision.deinterlace:
        return decision
    method = Method.REENCODE if decision.method is Method.REMUX else decision.method
    reasons = ("Interlaced: deinterlaced first", *decision.reasons)
    return replace(decision, method=method, deinterlace=True, reasons=reasons)


def size_name(width: int, height: int) -> str:
    """What a picture's size is called: "SD", "720p", "1080p", "4K" or "8K"."""
    for box_width, box_height, name in _SIZES:
        if width <= box_width * _SAME_SIZE and height <= box_height * _SAME_SIZE:
            return name
    return "8K"


def _bigger(video: Video, standard: Standard) -> bool:
    """Whether the picture is bigger than the standard's 16:9 frame, beyond a few lines."""
    scale = max(video.height / standard.height, video.width / _box_width(standard))
    return scale > _SAME_SIZE


def _hdr_kept(hdr: str | None) -> str:
    return ", HDR kept" if hdr else ""


def _dolby_vision_lost(video: Video, method: Method) -> tuple[str, ...]:
    """What a new picture can't carry over: Dolby Vision's own layer (the picture under it, HDR10
    say, is kept). A copied picture keeps it."""
    if method is not Method.REENCODE or not video.dolby_vision:
        return ()
    under = f"its {video.hdr} picture" if video.hdr else "the picture under it"
    return (f"Dolby Vision's own layer can't be carried over: {under} is kept",)


def _sound_and_container(media: MediaInfo, standard: Standard) -> tuple[str, ...]:
    changes: list[str] = []
    if media.container != standard.container:
        changes.append(f"{media.container.upper()} becomes {standard.container.upper()}")
    for codec in dict.fromkeys(audio.codec for audio in media.audio if audio.codec in TO_FLAC):
        changes.append(f"{TO_FLAC[codec]} sound becomes FLAC, still lossless")
    return tuple(changes)


def _picture_matches(video: Video, standard: Standard) -> bool:
    return video.codec == standard.codec and video.bit_depth == standard.bit_depth


def _output_size(shape: Fraction, standard: Standard) -> tuple[int, int]:
    """The largest size with the picture's shape that fits the standard's 16:9 frame."""
    box_width = _box_width(standard)
    if shape >= Fraction(16, 9):
        return box_width, _even(box_width / shape)
    return _even(standard.height * shape), standard.height


def _box_width(standard: Standard) -> int:
    return _even(Fraction(standard.height * 16, 9))


def _even(value: Fraction | float) -> int:
    return round(value / 2) * 2


_CODEC_NAMES = {
    "h264": "H.264",
    "hevc": "HEVC",
    "mpeg4": "MPEG-4",
    "mpeg2video": "MPEG-2",
    "mpeg1video": "MPEG-1",
    "av1": "AV1",
    "vp9": "VP9",
    "vc1": "VC-1",
}


def _codec_name(video: Video) -> str:
    name = _CODEC_NAMES.get(video.codec, video.codec.upper())
    return f"{name} {video.bit_depth}-bit" if video.codec == "hevc" else name


def _target_name(standard: Standard) -> str:
    return f"{_CODEC_NAMES.get(standard.codec, standard.codec.upper())} {standard.bit_depth}-bit"
