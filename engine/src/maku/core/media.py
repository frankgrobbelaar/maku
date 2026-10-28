"""What a video file holds: its picture, sound, subtitles and fonts, read from ffprobe's report.

The report is ffprobe's JSON (`-show_format -show_streams -show_chapters`); running ffprobe is
someone else's job, so everything here is a plain function of that data.
"""

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

from maku.core import fields
from maku.core.fields import Json

MAKU_TAG = "MAKU"  # the tag Maku writes into every file it converts
# What a file ffmpeg wrote says made it ("Lavf61.7.100"): its statistics (BPS) are copies.
_FFMPEG = "lavf"
# The transfers that make a picture HDR: PQ (HDR10, and Dolby Vision's HDR10 base) and HLG.
HDR_TRANSFERS = {"smpte2084": "HDR10", "arib-std-b67": "HLG"}


@dataclass(frozen=True)
class Video:
    codec: str
    width: int
    height: int
    display_aspect: Fraction  # 4/3, 16/9…: the shape on screen, whatever the pixels' shape
    frame_rate: Fraction | None
    bit_depth: int
    interlaced: bool | None  # None: ffprobe couldn't tell; a picture check decides later
    # Its colours as the file says them, as ffprobe names them; None when it doesn't say.
    color_transfer: str | None = None  # "smpte2084" (PQ), "arib-std-b67" (HLG), "bt709"…
    color_primaries: str | None = None  # "bt2020", "bt709"…
    color_space: str | None = None  # the matrix: "bt2020nc", "bt709"…
    dolby_vision: bool = False  # Dolby Vision's own layer rides on the picture
    # ...and the picture under it has no colours of its own (profile 5): it only looks right
    # with Dolby Vision, so it's never made anew.
    needs_dolby_vision: bool = False
    bit_rate: int | None = None  # bits a second, when the file says

    @property
    def hdr(self) -> str | None:
        """ "HDR10" or "HLG" for an HDR picture; None for SDR."""
        return HDR_TRANSFERS.get(self.color_transfer or "")


@dataclass(frozen=True)
class Audio:
    codec: str
    channels: int
    language: str | None
    lossless: bool
    bit_rate: int | None = None  # bits a second, when the file says


@dataclass(frozen=True)
class Subtitle:
    codec: str
    language: str | None
    text: bool  # text (ASS, SRT) rather than pictures (PGS, DVD)
    forced: bool


@dataclass(frozen=True)
class MediaInfo:
    container: str  # "mkv", "mp4", "avi", "mpeg"…
    duration: float | None  # seconds
    size: int | None  # bytes
    video: Video | None
    audio: tuple[Audio, ...] = ()
    subtitles: tuple[Subtitle, ...] = ()
    fonts: int = 0
    chapters: int = 0
    maku_tag: str | None = None


def media_from_ffprobe(report: Json) -> MediaInfo:
    streams = fields.mappings(report, "streams")
    format_ = fields.mapping(report, "format")
    pictures = [s for s in streams if fields.text(s, "codec_type") == "video" and not _is_cover(s)]
    duration, size = fields.decimal(format_, "duration"), fields.whole(format_, "size")
    rate = _bit_rates(format_, duration, size)
    return MediaInfo(
        container=_container(fields.text(format_, "format_name")),
        duration=duration,
        size=size,
        video=_video(pictures[0], rate) if pictures else None,
        audio=tuple(_audio(s, rate) for s in streams if fields.text(s, "codec_type") == "audio"),
        subtitles=tuple(
            _subtitle(s) for s in streams if fields.text(s, "codec_type") == "subtitle"
        ),
        fonts=sum(1 for s in streams if is_font(s)),
        chapters=len(fields.mappings(report, "chapters")),
        maku_tag=tag(format_, MAKU_TAG),
    )


_LOSSLESS_AUDIO = frozenset({"flac", "alac", "truehd", "mlp", "wavpack", "tta", "ape"})
_TEXT_SUBTITLES = frozenset({"ass", "ssa", "subrip", "srt", "webvtt", "mov_text", "text"})
_INTERLACED_FIELDS = frozenset({"tt", "bb", "tb", "bt"})
_DOLBY_VISION_TAGS = frozenset({"dvhe", "dvh1", "dvav", "dva1", "dav1"})  # in MP4
_DOLBY_VISION_RECORD = "DOVI configuration record"


type _Rate = Callable[[Json], int | None]  # a stream's bits a second, as its file lets them be


def _video(stream: Json, rate: _Rate) -> Video:
    width = fields.whole(stream, "width") or 0
    height = fields.whole(stream, "height") or 0
    record = _dolby_vision(stream)
    return Video(
        codec=fields.text(stream, "codec_name") or "unknown",
        width=width,
        height=height,
        display_aspect=_display_aspect(stream, width, height),
        frame_rate=_ratio(fields.text(stream, "avg_frame_rate"))
        or _ratio(fields.text(stream, "r_frame_rate")),
        bit_depth=_bit_depth(stream),
        interlaced=_interlaced(fields.text(stream, "field_order")),
        color_transfer=_said(fields.text(stream, "color_transfer")),
        color_primaries=_said(fields.text(stream, "color_primaries")),
        color_space=_said(fields.text(stream, "color_space")),
        dolby_vision=record is not None
        or (fields.text(stream, "codec_tag_string") or "") in _DOLBY_VISION_TAGS,
        needs_dolby_vision=record is not None and _without_base(record),
        bit_rate=rate(stream),
    )


def _audio(stream: Json, rate: _Rate) -> Audio:
    codec = fields.text(stream, "codec_name") or "unknown"
    lossless = codec in _LOSSLESS_AUDIO or codec.startswith("pcm_")
    if codec == "dts" and "MA" in (fields.text(stream, "profile") or ""):
        lossless = True  # DTS-HD Master Audio
    return Audio(
        codec=codec,
        channels=fields.whole(stream, "channels") or 0,
        language=language_of(stream),
        lossless=lossless,
        bit_rate=rate(stream),
    )


def _said(value: str | None) -> str | None:
    """A colour property as the file says it; None for ffprobe's "unknown" and the like."""
    return None if value in (None, "", "unknown", "unspecified", "reserved") else value


def _dolby_vision(stream: Json) -> Json | None:
    """The stream's Dolby Vision configuration (ffprobe's side data), or None."""
    for data in fields.mappings(stream, "side_data_list"):
        if fields.text(data, "side_data_type") == _DOLBY_VISION_RECORD:
            return data
    return None


def _without_base(record: Json) -> bool:
    """Whether Dolby Vision's picture has nothing a player without it shows right: profile 5,
    whose base layer is in Dolby's own colours (signal compatibility 0)."""
    compatibility = fields.whole(record, "dv_bl_signal_compatibility_id")
    if compatibility is not None:
        return compatibility == 0
    return fields.whole(record, "dv_profile") == 5


def _bit_rates(format_: Json, duration: float | None, size: int | None) -> _Rate:
    """How a file's streams' bits a second are read: ffprobe's own, or the statistics MKVToolNix
    and MakeMKV count as they write a file ("BPS"). ffmpeg never counts them, but copies them
    into what it makes, where they're the original's (a picture made 3 Mb/s still saying the 25
    of its Blu-ray's), so in a file ffmpeg wrote they're no one's. Nor is a rate that would make a
    stream bigger than its whole file."""
    most = size * 8 / duration if size and duration else None
    counted = not (tag(format_, "encoder") or "").casefold().startswith(_FFMPEG)

    def rate(stream: Json) -> int | None:
        found = fields.whole(stream, "bit_rate")
        if found is None and counted:
            for name in ("BPS", "BPS-eng"):
                said = tag(stream, name)
                if said is not None and said.isdigit():
                    found = int(said)
                    break
        if found is None or found <= 0 or (most is not None and found > most):
            return None
        return found

    return rate


def _subtitle(stream: Json) -> Subtitle:
    codec = fields.text(stream, "codec_name") or "unknown"
    return Subtitle(
        codec=codec,
        language=language_of(stream),
        text=codec in _TEXT_SUBTITLES,
        forced=fields.whole(fields.mapping(stream, "disposition"), "forced") == 1,
    )


def _container(format_name: str | None) -> str:
    names = (format_name or "unknown").split(",")
    if "matroska" in names:
        return "mkv"
    if "mp4" in names:
        return "mp4"
    return names[0]


def _display_aspect(stream: Json, width: int, height: int) -> Fraction:
    if (shape := _ratio(fields.text(stream, "display_aspect_ratio"))) is not None:
        return shape
    pixel = _ratio(fields.text(stream, "sample_aspect_ratio")) or Fraction(1)
    return Fraction(width, height) * pixel if height else Fraction(1)


def _bit_depth(stream: Json) -> int:
    pixels = fields.text(stream, "pix_fmt") or ""
    for depth in (16, 12, 10):
        if f"p{depth}" in pixels:
            return depth
    return fields.whole(stream, "bits_per_raw_sample") or 8


def _interlaced(field_order: str | None) -> bool | None:
    if field_order == "progressive":
        return False
    if field_order in _INTERLACED_FIELDS:
        return True
    return None


def language_of(stream: Json) -> str | None:
    """A stream's language as its tag says ("jpn"), or None when it doesn't say."""
    language = tag(stream, "language")
    return None if language in (None, "und") else language


def _is_cover(stream: Json) -> bool:
    return fields.whole(fields.mapping(stream, "disposition"), "attached_pic") == 1


def is_font(stream: Json) -> bool:
    """A font attached to the file, for its styled subtitles."""
    if fields.text(stream, "codec_type") != "attachment":
        return False
    mimetype = (tag(stream, "mimetype") or "").casefold()
    return "font" in mimetype or (tag(stream, "filename") or "").casefold().endswith(
        (".ttf", ".otf", ".ttc")
    )


def tag(data: Json, name: str) -> str | None:
    """One of a stream's or the file's tags, in any case ("language", "title")."""
    tags = fields.mapping(data, "tags")
    for key, value in tags.items():
        if key.casefold() == name.casefold() and isinstance(value, str):
            return value
    return None


def _ratio(value: str | None) -> Fraction | None:
    """ffprobe's "24000/1001" or "4:3"; None for "0/0", "0:1" and anything unreadable."""
    if not value:
        return None
    top, _, bottom = value.replace(":", "/").partition("/")
    try:
        ratio = Fraction(int(top), int(bottom or 1))
    except ValueError, ZeroDivisionError:
        return None
    return ratio if ratio > 0 else None
