"""Playing a video inside Maku's window: what a file offers to play (its sound, its subtitles and
its chapters), and the ffmpeg commands that turn it into what the window plays as it comes.

The window plays H.264 and AAC in MP4; the library is mostly MKV, HEVC 10-bit, AC-3 and styled
subtitles. So the engine hands it the video re-encoded on the fly, as fragmented MP4 from any
point: one sound track, made stereo, and the subtitles drawn into the picture. Seeking starts
it again from there. Text subtitles are drawn from a copy of them taken out of the file once
(reading them takes the whole file), with the file's own fonts; subtitles that are pictures are
laid over the picture straight from the file.

Everything here is a plain function of ffprobe's report and the owner's choices; running ffmpeg
is maku/player.py's job.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal

from maku.core import fields
from maku.core.convert import QUIET_INPUT
from maku.core.fields import Json
from maku.core.filters import filter_path
from maku.core.media import is_font, language_of, media_from_ffprobe, tag

HEIGHT = 1080  # the picture's height at most: the window shows no more

type Kind = Literal["text", "styled", "pictures"]

_STYLED = frozenset({"ass", "ssa"})
_TEXT = frozenset({"subrip", "srt", "webvtt", "mov_text", "text"})
_PICTURES = frozenset({"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"})
_BESIDE = {".ass": "styled", ".ssa": "styled", ".srt": "text", ".vtt": "text"}
_FONTS = (".ttf", ".otf", ".ttc")

# How each encoder makes H.264 for the window, in the order Maku tries them: only encoders
# that come with their licence, Windows' own (Media Foundation's, part of Windows) first, then the
# graphics cards'. Windows' starts in about a second and keeps a steady three times the speed of
# playing at 1080p on the processor, the graphics card busy converting or not (on the owner's PC,
# 2026-10-14); NVENC was as quick, but slower to start while the AI model had the card. OpenH264
# isn't used: Cisco's patent licence for it covers only the builds Cisco publishes.
# The cards' encoders make no B-frames, which fragmented MP4 would show late.
ENCODERS: dict[str, tuple[str, ...]] = {
    "h264_mf": ("-c:v", "h264_mf", "-b:v", "6M", "-g", "48"),
    "h264_nvenc": ("-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23", "-bf", "0", "-g", "48"),
    "h264_amf": ("-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "22",
                 "-qp_p", "24", "-bf", "0", "-g", "48"),
    "h264_qsv": ("-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "23", "-bf", "0",
                 "-g", "48"),
}  # fmt: skip

# The picture made the window's: its height at most HEIGHT, square pixels, 8-bit 4:2:0.
_PICTURE = (
    f"scale=w='trunc(oh*dar/2)*2':h='trunc(min({HEIGHT},ih)/2)*2'",
    "setsar=1",
    "format=yuv420p",
)
_FRAGMENTS = "frag_keyframe+empty_moov+default_base_moof"  # plays as it comes


@dataclass(frozen=True)
class Sound:
    number: int  # among the file's sound tracks: ffmpeg's 0:a:N
    language: str | None
    title: str | None
    channels: int
    default: bool


@dataclass(frozen=True)
class Subtitles:
    """A subtitle track: in the file (numbered among its subtitle tracks, ffmpeg's 0:s:N), or a
    file of its own beside the video (numbered after those)."""

    number: int
    language: str | None
    title: str | None
    kind: Kind  # plain text, text the file styles itself, or pictures
    codec: str = "ass"
    default: bool = False
    forced: bool = False
    beside: PurePath | None = None


@dataclass(frozen=True)
class Chapter:
    start: float  # seconds
    title: str | None


@dataclass(frozen=True)
class Font:
    stream: int  # the attachment's index among all the file's streams
    extension: str  # ".ttf", ".otf" or ".ttc"


@dataclass(frozen=True)
class Playable:
    duration: float | None
    sound: tuple[Sound, ...]
    subtitles: tuple[Subtitles, ...]
    chapters: tuple[Chapter, ...]
    fonts: tuple[Font, ...]
    deinterlace: bool  # the picture is interlaced, or may be: drawn whole while it plays

    def track(self, number: int) -> Subtitles | None:
        return next((each for each in self.subtitles if each.number == number), None)


@dataclass(frozen=True)
class Drawn:
    """Subtitles drawn into the picture: from a text file (with the file's fonts beside it), or
    from one of the file's own tracks of pictures."""

    text: PurePath | None = None
    fonts: PurePath | None = None
    pictures: int | None = None


def playable(report: Json, video: PurePath, beside: Sequence[PurePath] = ()) -> Playable:
    """What the file `video` offers to play, from ffprobe's report on it, with the subtitle files
    `beside` it (named after it, as maku/core/plan.py's sidecars_of finds them)."""
    media = media_from_ffprobe(report)
    sound: list[Sound] = []
    subtitles: list[Subtitles] = []
    fonts: list[Font] = []
    count = 0  # the file's subtitle tracks, those Maku can't draw too: 0:s:N counts them all
    for stream in fields.mappings(report, "streams"):
        kind = fields.text(stream, "codec_type")
        disposition = fields.mapping(stream, "disposition")
        if kind == "audio":
            sound.append(
                Sound(
                    number=len(sound),
                    language=language_of(stream),
                    title=tag(stream, "title"),
                    channels=fields.whole(stream, "channels") or 0,
                    default=fields.whole(disposition, "default") == 1,
                )
            )
        elif kind == "subtitle":
            codec = fields.text(stream, "codec_name") or ""
            drawn = _kind(codec)
            if drawn is not None:
                subtitles.append(
                    Subtitles(
                        number=count,
                        language=language_of(stream),
                        title=tag(stream, "title"),
                        kind=drawn,
                        codec=codec,
                        default=fields.whole(disposition, "default") == 1,
                        forced=fields.whole(disposition, "forced") == 1,
                    )
                )
            count += 1
        elif is_font(stream) and (index := fields.whole(stream, "index")) is not None:
            fonts.append(Font(index, _font_extension(stream)))
    for path in beside:
        if (drawn := _BESIDE.get(path.suffix.casefold())) is not None:
            subtitles.append(
                Subtitles(
                    number=count,
                    language=_language_in_name(path, video),
                    title=None,
                    kind="styled" if drawn == "styled" else "text",
                    codec=path.suffix.casefold().removeprefix("."),
                    beside=path,
                )
            )
            count += 1
    return Playable(
        duration=media.duration,
        sound=tuple(sound),
        subtitles=tuple(subtitles),
        chapters=tuple(_chapters(report)),
        fonts=tuple(fonts),
        deinterlace=media.video is not None and media.video.interlaced is not False,
    )


def first_sound(found: Playable) -> int | None:
    """The sound track to start with: the one the file marks as its default, or else its first."""
    chosen = next((each for each in found.sound if each.default), None)
    chosen = chosen or (found.sound[0] if found.sound else None)
    return chosen.number if chosen else None


def first_subtitles(found: Playable) -> int | None:
    """The subtitles to start with: those the file marks as its default, or else its first
    track, or else a file beside it; None when there are none."""
    chosen = next((each for each in found.subtitles if each.default), None)
    chosen = chosen or (found.subtitles[0] if found.subtitles else None)
    return chosen.number if chosen else None


def stream_command(
    ffmpeg: Sequence[str],
    source: PurePath,
    *,
    at: float,
    sound: int | None,
    drawn: Drawn | None,
    deinterlace: bool,
    encoder: Sequence[str],
) -> list[str]:
    """ffmpeg playing `source` from `at` seconds as fragmented MP4 on its output: H.264 made by
    `encoder` (one of ENCODERS), the `sound` track as AAC stereo, and the subtitles `drawn` in.

    The file's own times are kept (-copyts) so the subtitles line up wherever it starts, and the
    stream's times start from nothing, as the window counts them."""
    # Drawn whole at the file's own rate, one frame for each (maku/core/convert.py).
    first = ["bwdif=mode=send_frame:deint=interlaced"] if deinterlace else []
    if drawn is not None and drawn.text is not None:
        options = f"filename={filter_path(drawn.text)}"
        if drawn.fonts is not None:
            options += f":fontsdir={filter_path(drawn.fonts)}"
        first.append(f"subtitles={options}")
    rest = ["setpts=PTS-STARTPTS", *_PICTURE]
    if drawn is not None and drawn.pictures is not None:
        base = ",".join(first) or "null"
        graph = (
            f"[0:v:0]{base}[base];"
            f"[base][0:s:{drawn.pictures}]overlay=eof_action=pass,{','.join(rest)}[picture]"
        )
        picture = ["-filter_complex", graph, "-map", "[picture]"]
    else:
        picture = ["-map", "0:v:0", "-vf", ",".join([*first, *rest])]
    audio = (
        [
            "-map",
            f"0:a:{sound}",
            "-af",
            "asetpts=PTS-STARTPTS",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-b:a",
            "192k",
        ]
        if sound is not None
        else ["-an"]
    )
    return [
        *ffmpeg,
        *QUIET_INPUT,
        "-v",
        "error",
        "-ss",
        f"{max(at, 0):.3f}",
        "-copyts",
        "-i",
        str(source),
        *picture,
        *audio,
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        *encoder,
        "-f",
        "mp4",
        "-movflags",
        _FRAGMENTS,
        "pipe:1",
    ]


def subtitles_command(
    ffmpeg: Sequence[str],
    source: PurePath,
    track: Subtitles,
    out: PurePath,
    fonts: Sequence[tuple[Font, PurePath]] = (),
) -> list[str]:
    """ffmpeg copying a text subtitle track out of `source` into `out` as ASS, the file's fonts
    to the paths given with them. Each font gets a name of Maku's: a file's own names for its
    attachments could point anywhere."""
    dumps = [
        part for font, path in fonts for part in (f"-dump_attachment:{font.stream}", str(path))
    ]
    return [
        *ffmpeg,
        *QUIET_INPUT,
        "-v",
        "error",
        "-y",
        *dumps,
        "-copyts",
        "-i",
        str(source),
        "-map",
        f"0:s:{track.number}",
        "-c:s",
        "copy" if track.codec == "ass" else "ass",
        "-f",
        "ass",
        str(out),
    ]


def encoder_check_command(ffmpeg: Sequence[str], encoder: Sequence[str]) -> list[str]:
    """ffmpeg making a fifth of a second of black with `encoder`: whether it works on this PC."""
    return [
        *ffmpeg,
        *QUIET_INPUT,
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=320x240:r=24:d=0.2",
        "-pix_fmt",
        "yuv420p",
        *encoder,
        "-f",
        "null",
        "-",
    ]


def _kind(codec: str) -> Kind | None:
    if codec in _STYLED:
        return "styled"
    if codec in _TEXT:
        return "text"
    if codec in _PICTURES:
        return "pictures"
    return None


def _font_extension(stream: Json) -> str:
    name = (tag(stream, "filename") or "").casefold()
    for extension in _FONTS:
        if name.endswith(extension):
            return extension
    mimetype = (tag(stream, "mimetype") or "").casefold()
    if "otf" in mimetype or "opentype" in mimetype:
        return ".otf"
    if "collection" in mimetype:
        return ".ttc"
    return ".ttf"


def _chapters(report: Json) -> list[Chapter]:
    found: list[Chapter] = []
    for chapter in fields.mappings(report, "chapters"):
        start = fields.decimal(chapter, "start_time")
        if start is not None and start >= 0:
            found.append(Chapter(start, tag(chapter, "title")))
    return sorted(found, key=lambda chapter: chapter.start)


def _language_in_name(path: PurePath, video: PurePath) -> str | None:
    """The language a subtitle file's name gives after the video's ("Episode 1.en.srt",
    "Episode 1.eng.forced.ass"): a code of two or three letters there."""
    if not path.name.casefold().startswith(f"{video.stem.casefold()}."):
        return None
    added = path.name[len(video.stem) + 1 : -len(path.suffix) or None]
    for part in added.split("."):
        if 2 <= len(part) <= 3 and part.isascii() and part.isalpha():
            return part.casefold()
    return None
