"""The library standard, and what each file needs to reach it.

The standard is a top size, 4K or 1080p, and every picture ends as HEVC 10-bit in an MKV. Nothing
is made bigger than it is: a picture bigger than the standard comes down to it, keeping its shape,
and one at or under it keeps its own size, but for an odd last line or column, which a new picture
can't have. HDR stays HDR. The sound is kept as it is, every track, but for what MKV can't hold:
Blu-ray's and DVD's PCM, and any other such PCM, becomes FLAC, still lossless (float, 32- and
64-bit PCM stay PCM, as MKV holds it), and any other sound MKV can't hold becomes FLAC too. MP4's
text subtitles become SRT; subtitles MKV can't hold any way (teletext, closed captions) are left
out, and the reasons say so. A file already HEVC 10-bit, progressive, in MKV and no bigger than the
standard is only renamed.
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


_MKV = "mkv"  # an MKV's container, as maku/core/media.py calls it: its tracks are ones MKV holds
# Sound MKV holds as it is: Matroska's own codecs, and those ffmpeg's MKV muxer keeps the WAV way
# (each tried with Maku's ffmpeg, 2026-10-28). Any other becomes what MKV holds (`sound_way`).
_MKV_SOUND = frozenset(
    {
        *("aac", "aac_latm", "ac3", "eac3", "dts", "truehd", "mlp", "flac", "alac", "opus"),
        *("vorbis", "mp1", "mp2", "mp3", "tta", "wavpack", "amr_nb"),
        *("wmav1", "wmav2", "wmapro", "wmalossless", "wmavoice"),
        *("pcm_s16le", "pcm_s16be", "pcm_s24le", "pcm_s24be", "pcm_s32le", "pcm_s32be"),
        *("pcm_s64le", "pcm_u8", "pcm_f32le", "pcm_f64le", "pcm_alaw", "pcm_mulaw"),
        *("adpcm_ms", "adpcm_ima_wav", "adpcm_swf", "adpcm_g722", "adpcm_g726", "g723_1"),
        *("ra_144", "ra_288", "cook", "sipr", "atrac1", "atrac3", "qdm2", "qdmc"),
    }
)
_DISC_PCM = {"pcm_bluray": "Blu-ray's PCM", "pcm_dvd": "DVD's PCM"}  # what they're called
# Subtitles MKV holds as they are: Matroska's own (text, ASS, WebVTT, DVD's, Blu-ray's and DVB's
# pictures, Blu-ray's text and ARIB's captions, as Maku's ffmpeg names them).
_MKV_SUBTITLES = frozenset(
    {
        *("subrip", "text", "ass", "webvtt", "dvd_subtitle", "dvb_subtitle"),
        *("hdmv_pgs_subtitle", "hdmv_text_subtitle", "arib_caption"),
    }
)
_MADE_SRT = frozenset({"mov_text"})  # MP4's text subtitles, which ffmpeg makes SRT
# What subtitles MKV can't hold any way are called, as the reasons say they're left out.
_SUBTITLE_NAMES = {
    "dvb_teletext": "Teletext subtitles",
    "eia_608": "Closed captions",
    "ttml": "TTML subtitles",
    "xsub": "DivX subtitles",
}
# The frames a picture is called by, by their 16:9 widths: SD (a DVD, or 1024x576 at most), 720p,
# 1080p, 1440p and 4K; anything bigger is 8K. A picture is called by the smallest frame it fits:
# up to 7% wider (cinema's own widths: 4096 for 4K, 2048 and 1998 for 1080p) and as tall as a
# 16:10 picture as wide as the frame (1920x1200 is 1080p, as is the odd 1920x1088).
_FRAMES = ((1024, "SD"), (1280, "720p"), (1920, "1080p"), (2560, "1440p"), (3840, "4K"))
_WIDER = 1.07
_TALLER = Fraction(10, 16)  # a 16:10 picture's height, for its width


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
        return _made_even(Decision(method, width, height, deinterlace, reasons))
    else:
        already = f"Already {_target_name(standard)} in MKV: only renamed"
        return Decision(Method.RENAME, width, height, reasons=(already,))
    lost = _dolby_vision_lost(video, Method.REENCODE)
    return _made_even(
        Decision(Method.REENCODE, width, height, deinterlace, (reason, *extras, *lost))
    )


def deinterlaced(decision: Decision) -> Decision:
    """A decision for a picture found to be interlaced once converting began (ffprobe couldn't
    tell, idet could): deinterlaced first, and so made anew where it was only to be remuxed."""
    if decision.deinterlace:
        return decision
    method = Method.REENCODE if decision.method is Method.REMUX else decision.method
    reasons = ("Interlaced: deinterlaced first", *decision.reasons)
    return _made_even(replace(decision, method=method, deinterlace=True, reasons=reasons))


def size_name(width: int, height: int) -> str:
    """What a picture's size is called: "SD", "720p", "1080p", "1440p", "4K" or "8K"."""
    for frame_width, name in _FRAMES:
        if _fits(width, height, frame_width):
            return name
    return "8K"


def sound_way(codec: str, container: str) -> str:
    """How a sound track of a file in `container` ("mp4") goes into the MKV: "copy", as it is (an
    MKV's own tracks are ones MKV holds), or the codec it's made into where MKV can't hold it.
    Float PCM stays float ("pcm_f32le"), and 32- or 64-bit PCM stays PCM ("pcm_s32le"): FLAC
    would keep 24 bits of them. Any other becomes FLAC: the same samples, for PCM up to 24 bits
    (measured), and the sound as it plays, for the rest."""
    if container == _MKV or codec in _MKV_SOUND:
        return "copy"
    if codec.startswith("pcm_f"):
        return "pcm_f64le" if "64" in codec else "pcm_f32le"
    if codec.startswith("pcm_") and ("32" in codec or "64" in codec):
        return "pcm_s64le" if "64" in codec else "pcm_s32le"
    return "flac"


def subtitle_way(codec: str, container: str) -> str | None:
    """How a subtitle track of a file in `container` goes into the MKV: "copy", as it is (an
    MKV's own tracks are ones MKV holds); "srt", for MP4's text; or None, left out: MKV can't hold
    it, and ffmpeg can't make it into what MKV holds (teletext, closed captions, TTML, which ffmpeg
    can't read)."""
    if container == _MKV or codec in _MKV_SUBTITLES:
        return "copy"
    return "srt" if codec in _MADE_SRT else None


def _fits(width: int, height: int, frame_width: int) -> bool:
    """Whether a picture fits a frame (see _FRAMES): no more than a few columns wider, and no
    taller than a 16:10 picture as wide as the frame."""
    return width <= frame_width * _WIDER and height <= frame_width * _TALLER


def _bigger(video: Video, standard: Standard) -> bool:
    """Whether the picture is bigger than the standard's frame: a size called bigger than it."""
    return not _fits(video.width, video.height, _box_width(standard))


def _made_even(decision: Decision) -> Decision:
    """A new picture of an odd size loses its last line or column: the encoders make 4:2:0
    pictures in pairs of lines, and NVENC pads an odd one (1920x803 came out 1920x804, measured),
    which the check would fail. A copied picture keeps its own size."""
    if decision.method is not Method.REENCODE:
        return decision
    return replace(decision, width=_even_down(decision.width), height=_even_down(decision.height))


def _hdr_kept(hdr: str | None) -> str:
    return ", HDR kept" if hdr else ""


def _dolby_vision_lost(video: Video, method: Method) -> tuple[str, ...]:
    """What a new picture can't carry over: Dolby Vision's own layer (the picture under it, HDR10
    say, is kept). A copied picture keeps it."""
    if method is not Method.REENCODE or not video.dolby_vision:
        return ()
    under = f"its {video.hdr} picture" if video.hdr else "the picture under it"
    return (f"Dolby Vision's own layer can't be carried over: {under} is kept",)


# Containers by the name people know them by, where ffprobe's isn't it.
_CONTAINER_NAMES = {"mpegts": "TS", "mpeg": "MPEG", "asf": "WMV", "mov": "MOV", "webm": "WebM"}


def container_name(container: str) -> str:
    """A container in words: "MP4", "AVI", "TS" (for ffprobe's mpegts)."""
    return _CONTAINER_NAMES.get(container, container.upper())


def _sound_and_container(media: MediaInfo, standard: Standard) -> tuple[str, ...]:
    """What happens around the picture: another container, sound made FLAC (float PCM in MKV's
    byte order is the same sound, and goes unsaid), subtitles left out."""
    changes: list[str] = []
    if media.container != standard.container:
        changes.append(f"{container_name(media.container)} becomes {standard.container.upper()}")
    for audio in media.audio:
        if sound_way(audio.codec, media.container) == "flac":
            pcm = audio.codec.startswith("pcm_")
            how = "still lossless" if pcm else "as MKV can't hold it"
            changes.append(f"{_sound_name(audio.codec)} sound becomes FLAC, {how}")
    for subtitle in media.subtitles:
        if subtitle_way(subtitle.codec, media.container) is None:
            changes.append(_left_out(subtitle.codec))
    return tuple(dict.fromkeys(changes))


def _left_out(codec: str) -> str:
    """Why a subtitle track isn't in the result, in words."""
    if codec == "unknown":
        return "Subtitles ffmpeg can't read are left out"
    named = _SUBTITLE_NAMES.get(codec, f"{codec.upper()} subtitles")
    return f"{named} are left out: MKV can't hold them"


def _sound_name(codec: str) -> str:
    """What a sound codec is called in a reason: "Blu-ray's PCM", "PCM", "ADPCM", "NELLYMOSER"."""
    if codec in _DISC_PCM:
        return _DISC_PCM[codec]
    if codec.startswith("pcm_"):
        return "PCM"
    return "ADPCM" if codec.startswith("adpcm_") else codec.upper()


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


def _even_down(value: int) -> int:
    return value - value % 2


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
