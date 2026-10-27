"""How long converting takes on this PC, and how much space the results need; and how long
making English subtitles takes.

A re-encode works through every pixel of the picture it reads: the processor decodes it and the
graphics card's encoder makes it anew, side by side. So this PC's speed is kept as megapixels of
the original's picture a second, and a file takes its frames times its pixels over that. Until
Maku has measured this PC, it uses what the owner's GTX 1660 Super managed with NVENC's HEVC
10-bit at preset p6 (2026-10-27, made-up grainy clips, decoded on the i5-9600K): 180 frames a
second from 1080p to 1080p, 373 megapixels a second. The others came close to the same rate: 387
frames a second at 720p, 46 at 4K, 56 bringing 4K HDR down to 1080p (decoding 4K is the slow
part), 984 deinterlacing a DVD. Renaming and remuxing only copy, so they cost no card time.

A result's size: its new picture comes to about PICTURE_RATES for its size at the quality Maku
encodes with (live action at constant quality 21 varies most with grain), never more than the
original's picture, as the encoder is held to it; the sound, subtitles and fonts are copied as
they were.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction

from maku.core.media import MediaInfo
from maku.core.standard import Decision, Method, size_name

FILM = Fraction(24000, 1001)  # assumed when a file doesn't say its frame rate
_FULL_HD = 1920 * 1080  # pixels: a picture that doesn't say its size counts as 1080p
# Bits a second of a new picture, by its size: what live action comes to at constant quality 21.
PICTURE_RATES = {"SD": 1_500_000, "720p": 3_500_000, "1080p": 7_000_000, "4K": 20_000_000}
# Bits a second of a sound track that doesn't say: Blu-ray's lossless tracks run about this high.
_LOSSLESS_SOUND = 4_000_000
_SOUND = 640_000  # and a lossy one: Dolby Digital's highest


@dataclass(frozen=True)
class Speeds:
    """What this PC manages re-encoding: megapixels of the original's picture a second, the
    processor decoding it and the graphics card's encoder making it anew."""

    megapixels: float = 373.0


@dataclass(frozen=True)
class Estimate:
    gpu_seconds: float
    output_bytes: int


NOTHING = Estimate(0.0, 0)


def estimate(media: MediaInfo, decision: Decision, speeds: Speeds | None = None) -> Estimate:
    speeds = speeds or Speeds()
    match decision.method:
        case Method.SKIP:
            return NOTHING
        case Method.RENAME | Method.REMUX:
            return Estimate(0.0, media.size or 0)  # streams are copied, not encoded
        case Method.REENCODE:
            seconds = media.duration or 0.0
            video = media.video
            rate = video.frame_rate if video and video.frame_rate else FILM
            pixels = video.width * video.height if video and video.width else _FULL_HD
            work = seconds * float(rate) * pixels / (speeds.megapixels * 1e6)
            return Estimate(work, result_bytes(media, decision))


def result_bytes(media: MediaInfo, decision: Decision) -> int:
    """About how big a re-encoded file comes out, in bytes: its new picture, never more than the
    original's, and everything else as it was."""
    seconds = media.duration or 0.0
    made = PICTURE_RATES.get(size_name(decision.width, decision.height), PICTURE_RATES["4K"])
    picture = made * seconds / 8
    before = picture_rate(media)
    if before is None:
        return round(picture + sound_rate(media) * seconds / 8)
    old = before * seconds / 8
    return round(max(0.0, (media.size or 0) - old) + min(picture, old))


def picture_rate(media: MediaInfo) -> float | None:
    """The original's picture, in bits a second: as the file says, or else the whole file's less
    its sound. None when it can't be told (a file that doesn't say how long it plays)."""
    video = media.video
    if video is not None and video.bit_rate:
        return float(video.bit_rate)
    if not media.size or not media.duration:
        return None
    rest = media.size * 8 / media.duration - sound_rate(media)
    return rest if rest > 0 else None


def sound_rate(media: MediaInfo) -> float:
    """The file's sound tracks together, in bits a second: as each says, or as such a track
    usually runs."""
    return float(
        sum(
            track.bit_rate or (_LOSSLESS_SOUND if track.lossless else _SOUND)
            for track in media.audio
        )
    )


# Seconds of the graphics card's time English subtitles take for each second of a video, as
# the owner's GTX 1660 Super made them for a 21-minute episode (2026-10-15): about 8 minutes with
# Whisper medium (Best) and 3 with small (Fast). They grow with how much is said, so a quiet
# episode is quicker. "fast_processor" is Fast on the processor, where the graphics card hasn't
# the memory for it: Whisper medium heard a minute of an episode in 84 s on the owner's i5-9600K,
# and small is about a third of its work, so about 0.5 there; a laptop's processor is slower.
# Each PC measures its own as it makes them (maku/hardware.py).
HEARING = {"best": 0.4, "fast": 0.15, "fast_processor": 1.0}


def hearing(seconds: float, quality: str, rates: Mapping[str, float] = HEARING) -> float:
    """The time making a video's English subtitles takes, in seconds, at `rates` (this PC's:
    maku/hardware.py's hearing)."""
    return seconds * rates[quality]


# English from another copy: lining the two copies up by their sound takes about this long,
# then the copy kept is copied with the English beside it at about this many bytes a second.
MERGE_LOOK = 20.0
MERGE_RATE = 100_000_000


def merging(size: int) -> float:
    """The time adding English from another copy to a file of `size` bytes takes, in seconds:
    no graphics card, but the queue's time all the same."""
    return MERGE_LOOK + size / MERGE_RATE


def total(estimates: Iterable[Estimate]) -> Estimate:
    gpu_seconds, output_bytes = 0.0, 0
    for part in estimates:
        gpu_seconds += part.gpu_seconds
        output_bytes += part.output_bytes
    return Estimate(gpu_seconds, output_bytes)
