"""Converting one file to the library standard: what it becomes, the ffmpeg command that makes it,
and checking the result before it takes the original's place.

One ffmpeg command makes it (maku/core/standard.py decides what it needs). A remux copies the
picture as it is, Dolby Vision and all. A re-encode deinterlaces the picture first when it's
interlaced (bwdif), brings it down to the standard when it's bigger (scale: it resizes without
touching the colours) or cuts an odd last line or column (crop), and makes it HEVC 10-bit on the
graphics card's encoder (NVIDIA's NVENC, AMD's AMF or Intel's Quick Sync: whichever this PC has,
maku/hardware.py finds). An HDR picture stays HDR: its colours are set on its frames (setparams),
which ffmpeg hands to the encoder and the MKV, and its mastering display and light levels go with
the frames. Whatever the method, the MKV keeps every sound track (as it is, or as MKV can hold it:
Blu-ray's and DVD's PCM become FLAC), the subtitles MKV can hold (MP4's text ones become SRT),
fonts and chapters, tagged as Maku's, and none of the original's statistics.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise
from pathlib import PurePath

from maku.core.estimate import FILM, picture_rate
from maku.core.media import MediaInfo, Video
from maku.core.standard import Decision, Method, size_name, sound_way, subtitle_way

# NVENC's HEVC 10-bit, set for live action and measured on the owner's GTX 1660 Super
# (2026-10-27, docs/stack/encoding.md): constant quality 21, preset p6, spatial AQ. Its VBR mode
# quietly holds the bit rate to its preset's own (about 10 Mb/s at 1080p) unless it's given a
# ceiling of its own, so each file gets one (`Recipe.peak`).
NVENC = (
    "-c:v",
    "hevc_nvenc",
    "-preset",
    "p6",
    "-tune",
    "hq",
    "-rc",
    "vbr",
    "-cq",
    "21",
    "-b:v",
    "0",
    "-spatial-aq",
    "1",
    "-profile:v",
    "main10",
)
# AMD's and Intel's HEVC 10-bit, set to look as good: constant quality, their slowest presets.
AMF = (
    "-c:v",
    "hevc_amf",
    "-usage",
    "transcoding",
    "-quality",
    "quality",
    "-rc",
    "cqp",
    "-qp_i",
    "20",
    "-qp_p",
    "22",
    "-profile:v",
    "main10",
)
QSV = (
    "-c:v",
    "hevc_qsv",
    "-preset",
    "slower",
    "-global_quality",
    "21",
    "-profile:v",
    "main10",
)
# Each encoder Maku converts with, best first: the first this PC starts is the one it uses.
ENCODERS: dict[str, tuple[str, ...]] = {"nvenc": NVENC, "amf": AMF, "qsv": QSV}
DEINTERLACE = "bwdif=mode=send_frame"  # a frame for each frame: the frame rate stays as it was
# The most a new picture's bit rate may reach, by its size, whatever its original's: as much as
# the HEVC levels players expect allow (NVENC made 1080p at 40 level 4.1, and 1440p at 40 to 80
# and 4K at 100 level 5.0, measured on the owner's card).
_TOPS = {
    "SD": 15_000_000,
    "720p": 25_000_000,
    "1080p": 40_000_000,
    "1440p": 60_000_000,
    "4K": 100_000_000,
}
_SAMPLE_FRAMES = 600  # frames idet looks at to tell whether a picture is interlaced
_HDR_PRIMARIES = "bt2020"  # what an HDR picture that doesn't say its own has
_HDR_MATRIX = "bt2020nc"
# What MKVToolNix (and MakeMKV) write of each track as they mux, in either spelling. ffmpeg copies
# a stream's tags into what it makes, where they'd describe the original (a 25 Mb/s picture made
# 3 Mb/s still said 25, and a scan would believe it), so the result carries none of them. ffmpeg
# writes its own DURATION.
_STATISTICS = (
    *(
        f"{name}{spelling}"
        for name in (
            "BPS",
            "NUMBER_OF_BYTES",
            "NUMBER_OF_FRAMES",
            "_STATISTICS_WRITING_APP",
            "_STATISTICS_WRITING_DATE_UTC",
            "_STATISTICS_TAGS",
        )
        for spelling in ("", "-eng")
    ),
    "DURATION-eng",
)


@dataclass(frozen=True)
class Colours:
    """An HDR picture's colours, as ffmpeg names them: set on its frames as it's made anew."""

    primaries: str  # "bt2020"
    transfer: str  # "smpte2084" (PQ) or "arib-std-b67" (HLG)
    matrix: str  # "bt2020nc"


@dataclass(frozen=True)
class Recipe:
    """What one file becomes."""

    method: Method  # REMUX or REENCODE
    width: int
    height: int
    scaled: bool  # brought down to the standard
    deinterlace: bool
    frame_rate: Fraction
    # Per sound track: "copy", or what it's made into where MKV can't hold it ("flac").
    audio: tuple[str, ...]
    # Per subtitle track: "copy", "srt" for MP4's text, or None: left out, as MKV can't hold it.
    subtitles: tuple[str | None, ...]
    fonts: bool  # the file carries fonts (MKV attachments), which go with it
    output: PurePath  # where the result goes: the original's name as an MKV
    tag: str  # written as the MAKU tag
    encoder: str = "nvenc"  # which of ENCODERS makes the picture
    colours: Colours | None = None  # an HDR picture's, kept as it's made anew
    peak: int = 0  # bits a second the new picture never goes over (NVENC's ceiling)
    dolby_vision: bool = False  # Dolby Vision rides on the picture, and doesn't survive anew
    cropped: bool = False  # an odd last line or column cut off, the size otherwise its own


def recipe(
    source: PurePath, media: MediaInfo, decision: Decision, *, tag: str, encoder: str = "nvenc"
) -> Recipe:
    if decision.method not in (Method.REMUX, Method.REENCODE):
        raise ValueError(f"A {decision.method} file isn't converted.")
    if encoder not in ENCODERS:
        raise ValueError(f"Maku has no encoder called {encoder}.")
    video = media.video
    reencoded = decision.method is Method.REENCODE
    size = (decision.width, decision.height)
    own = (video.width, video.height) if video else size
    even = (own[0] - own[0] % 2, own[1] - own[1] % 2)  # what standard.py makes of an odd size
    cropped = even != own and size == even
    return Recipe(
        method=decision.method,
        width=decision.width,
        height=decision.height,
        scaled=size not in (own, even),
        deinterlace=decision.deinterlace,
        frame_rate=(video.frame_rate if video and video.frame_rate else FILM),
        audio=tuple(sound_way(audio.codec, media.container) for audio in media.audio),
        subtitles=tuple(subtitle_way(each.codec, media.container) for each in media.subtitles),
        fonts=media.fonts > 0,
        output=source.with_suffix(".mkv"),
        tag=tag,
        encoder=encoder,
        colours=_colours(video) if reencoded and video else None,
        peak=_peak(media, decision) if reencoded else 0,
        dolby_vision=reencoded and video is not None and video.dolby_vision,
        cropped=cropped,
    )


def _colours(video: Video) -> Colours | None:
    """An HDR picture's colours, with BT.2020's where the file leaves them unsaid."""
    if video.hdr is None or video.color_transfer is None:
        return None
    return Colours(
        video.color_primaries or _HDR_PRIMARIES,
        video.color_transfer,
        video.color_space or _HDR_MATRIX,
    )


def _peak(media: MediaInfo, decision: Decision) -> int:
    """The new picture's ceiling, in bits a second: its original picture's rate, so it never
    comes out bigger (where the picture doesn't say its own, the whole file's less its sound, or
    the whole file's where its sound can't be told apart); and never over what players expect of
    its size."""
    top = _TOPS.get(size_name(decision.width, decision.height), _TOPS["4K"])
    found = picture_rate(media)
    if found is None and media.size and media.duration:
        found = media.size * 8 / media.duration
    return round(min(found or top, top))


# ffmpeg looks for key presses (q to quit) on standard input. Under Maku's window that's the
# engine's own input, which the engine waits on to know when the app closes, and Windows makes
# ffmpeg's look wait behind that read: ffmpeg would stop for good. Every command turns it off.
QUIET_INPUT = ("-nostdin",)


def one_command(ffmpeg: Sequence[str], source: PurePath, work: PurePath, made: Recipe) -> list[str]:
    """The whole conversion in one ffmpeg command; its progress goes to standard output, as
    ffmpeg's key=value lines."""
    filters = _picture(made, depth="p010le")
    if made.method is Method.REMUX:
        picture = ["-c:v", "copy"]
    else:
        picture = [*ENCODERS[made.encoder], *_ceiling(made)]
        if made.dolby_vision:  # nothing of it may claim to be Dolby Vision without its layer
            picture += ["-bsf:v", "dovi_rpu=strip=1"]
    return [
        *ffmpeg,
        *QUIET_INPUT,
        "-v",
        "error",
        "-y",
        "-i",
        str(source),
        *_maps(made),
        *(["-vf", ",".join(filters)] if filters else []),
        *picture,
        *_streams(made),
        "-progress",
        "pipe:1",
        "-nostats",
        "-f",
        "matroska",
        str(work),
    ]


def _picture(made: Recipe, *, depth: str) -> list[str]:
    """The filters that make a new picture, in `depth` (p010le for the encoder, yuv420p for a
    picture to look at); none for a remux, which copies it."""
    if made.method is Method.REMUX:
        return []
    filters: list[str] = [DEINTERLACE] if made.deinterlace else []
    if made.scaled:
        filters += [f"scale={made.width}:{made.height}:flags=lanczos", "setsar=1"]
    elif made.cropped:  # its last line or column: pixels and shape otherwise as they were
        filters.append(f"crop={made.width}:{made.height}:0:0")
    filters.append(f"format={depth}")
    if made.colours is not None:
        colours = made.colours
        filters.append(
            f"setparams=color_primaries={colours.primaries}:color_trc={colours.transfer}:"
            f"colorspace={colours.matrix}:range=tv"
        )
    return filters


def _ceiling(made: Recipe) -> list[str]:
    """NVENC's ceiling for the new picture (see NVENC); the other encoders keep to their quality
    without one."""
    if made.encoder != "nvenc" or made.peak <= 0:
        return []
    return ["-maxrate", str(made.peak), "-bufsize", str(made.peak * 2)]


def still_command(
    ffmpeg: Sequence[str], source: PurePath, out: PurePath, *, at: float, deinterlace: bool
) -> list[str]:
    """One frame of the original as it is, `at` seconds in: the comparison's before. `out`
    names the picture's file (PNG, so nothing is lost on the way)."""
    return [
        *ffmpeg,
        *QUIET_INPUT,
        "-v",
        "error",
        "-y",
        "-ss",
        f"{at:.2f}",
        "-i",
        str(source),
        "-map",
        "0:V:0",
        *(["-vf", DEINTERLACE] if deinterlace else []),
        "-frames:v",
        "1",
        str(out),
    ]


def preview_command(
    ffmpeg: Sequence[str], source: PurePath, out: PurePath, made: Recipe, *, at: float
) -> list[str]:
    """One frame made the way `made` says, `at` seconds in: the comparison's after."""
    filters = _picture(made, depth="yuv420p")
    return [
        *ffmpeg,
        *QUIET_INPUT,
        "-v",
        "error",
        "-y",
        "-ss",
        f"{at:.2f}",
        "-i",
        str(source),
        "-map",
        "0:V:0",
        *(["-vf", ",".join(filters)] if filters else []),
        "-frames:v",
        "1",
        str(out),
    ]


def interlace_command(ffmpeg: Sequence[str], source: PurePath, *, at: float) -> list[str]:
    """ffmpeg's idet looking at a stretch of the picture from `at` seconds; it reports how many
    frames look interlaced (see `interlaced`)."""
    return [
        *ffmpeg,
        *QUIET_INPUT,
        "-v",
        "info",
        "-nostats",
        "-ss",
        f"{at:.0f}",
        "-i",
        str(source),
        "-map",
        "0:V:0",
        "-frames:v",
        str(_SAMPLE_FRAMES),
        "-vf",
        "idet",
        "-an",
        "-sn",
        "-f",
        "null",
        "-",
    ]


def interlaced(report: str) -> bool:
    """Whether idet's report says the picture is interlaced: more of its frames look it than
    look progressive."""
    for line in report.splitlines():
        if "Multi frame detection" in line:
            counts = _counts(line)
            return counts.get("TFF", 0) + counts.get("BFF", 0) > counts.get("Progressive", 0)
    return False


def check(source: MediaInfo, output: MediaInfo, made: Recipe) -> list[str]:
    """What's wrong with a converted file, in words; nothing when it may replace the original."""
    video = output.video
    if video is None:
        return ["It has no picture"]
    problems: list[str] = []
    want, got = source.duration or 0.0, output.duration or 0.0
    if abs(want - got) > max(1.0, want * 0.005):
        problems.append(f"It's {_clock(got)} long, not {_clock(want)}")
    if made.method is not Method.REMUX and (
        (video.codec, video.bit_depth, video.width, video.height)
        != ("hevc", 10, made.width, made.height)
    ):
        problems.append(
            f"Its picture is {video.codec} {video.bit_depth}-bit {video.width}x{video.height},"
            f" not hevc 10-bit {made.width}x{made.height}"
        )
    if made.colours is not None and video.color_transfer != made.colours.transfer:
        problems.append("Its HDR didn't come through")
    kept = sum(1 for way in made.subtitles if way is not None)  # MKV can't hold the others
    problems += _count("sound track", len(output.audio), len(source.audio))
    problems += _count("subtitle track", len(output.subtitles), kept)
    problems += _count("font", output.fonts, source.fonts)
    if output.maku_tag != made.tag:
        problems.append("Maku's tag isn't in it")
    return problems


def _maps(made: Recipe) -> list[str]:
    """The picture, sound, subtitles MKV can hold, fonts, chapters and tags of the original."""
    subtitles = [
        part
        for number, way in enumerate(made.subtitles)
        if way is not None
        for part in ("-map", f"0:s:{number}")
    ]
    return [
        "-map",
        "0:V:0",  # V: the picture, never a cover image
        "-map",
        "0:a?",
        *subtitles,
        "-map",
        "0:t?",
        "-map_chapters",
        "0",
        "-map_metadata",
        "0",
    ]


def _streams(made: Recipe) -> list[str]:
    """How the sound, subtitles and fonts are carried, Maku's tag, and none of the original's
    statistics on any stream."""
    parts: list[str] = []
    for number, way in enumerate(made.audio):
        parts += [f"-c:a:{number}", way]
    kept = [way for way in made.subtitles if way is not None]  # numbered as they come out
    for number, way in enumerate(kept):
        parts += [f"-c:s:{number}", way]
    for name in _STATISTICS:
        parts += ["-metadata:s", f"{name}="]  # nothing after "=": the tag goes
    return [*parts, "-c:t", "copy", "-metadata", f"MAKU={made.tag}"]


def _counts(line: str) -> dict[str, int]:
    """ "TFF: 420 BFF: 2 Progressive: 150" as {"TFF": 420, ...}."""
    words = line.replace(":", " ").split()
    found: dict[str, int] = {}
    for name, value in pairwise(words):
        if value.isdigit():
            found[name] = int(value)
    return found


def _count(thing: str, got: int, want: int) -> Sequence[str]:
    if got == want:
        return []
    return [f"It has {got} {thing}{'' if got == 1 else 's'}, not {want}"]


def _clock(seconds: float) -> str:
    whole = round(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"
