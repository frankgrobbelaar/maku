"""Stills: three frames from a video, so the owner can recognise it on the review screen, and a
bigger one for its details when TMDB has no picture from its episode. ffmpeg takes each once, at
15%, 50% and 80% of the way in (the bigger one at 15%), and they're kept in the data folder's
cache. One ffmpeg couldn't take isn't asked for again till the video changes.
"""

import hashlib
import logging
import subprocess
from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from maku.config import DataPaths
from maku.core.convert import QUIET_INPUT

log = logging.getLogger(__name__)

POINTS = (0.15, 0.5, 0.8)  # how far into the video each still is taken
# The review screen's stills are small, three side by side. A video's picture goes across the top
# of its details: a card's width, never wider than the video, its pixels made square, as an SD
# video's often aren't. Each with ffmpeg's JPEG quality (2 is the best, 31 the worst).
_SMALL = ("scale=360:-2", "5")
_PICTURE = ("scale=w='trunc(min(1280,iw*sar)/2)*2':h='trunc(ow/dar/2)*2',setsar=1", "3")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_TIMEOUT = 30  # seconds for one frame; a damaged file can make ffmpeg hang

type Run = Callable[[Sequence[str]], None]


def _run(command: Sequence[str]) -> None:
    subprocess.run(  # noqa: S603 - Maku's own ffmpeg, a path and fixed arguments, no shell
        list(command),
        stdin=subprocess.DEVNULL,  # the engine's own input is the app's: see core/convert.py
        capture_output=True,
        timeout=_TIMEOUT,
        creationflags=_NO_WINDOW,
        check=True,
    )


def still(
    paths: DataPaths,
    ffmpeg: Path | None,
    video: Path,
    seconds: float | None,
    index: int,
    run: Run = _run,
) -> Path | None:
    """The still's picture, taken the first time it's asked for. None when there's no ffmpeg
    yet, the video's length isn't known, or ffmpeg couldn't take it."""
    if not 0 <= index < len(POINTS):
        return None
    return _frame(paths, ffmpeg, video, seconds, POINTS[index], _SMALL, str(index), run)


def picture(
    paths: DataPaths,
    ffmpeg: Path | None,
    video: Path,
    seconds: float | None,
    run: Run = _run,
) -> Path | None:
    """A picture of the video for its details, at the first still's moment: taken the first time
    it's asked for. None as for a still."""
    return _frame(paths, ffmpeg, video, seconds, POINTS[0], _PICTURE, "picture", run)


def _frame(
    paths: DataPaths,
    ffmpeg: Path | None,
    video: Path,
    seconds: float | None,
    point: float,
    size: tuple[str, str],
    name: str,
    run: Run,
) -> Path | None:
    """One frame, `point` of the way in, at `size` (its scaling and quality), kept under `name`
    for this video as it is now."""
    if ffmpeg is None or not seconds or not video.is_file():
        return None
    stat = video.stat()
    key = f"{video}|{stat.st_size}|{stat.st_mtime_ns}|{name}"
    kept = paths.cache / "stills" / f"{hashlib.sha256(key.encode()).hexdigest()[:24]}.jpg"
    failed = kept.with_suffix(".failed")
    if kept.is_file():
        return kept
    if failed.is_file():
        return None
    kept.parent.mkdir(parents=True, exist_ok=True)
    # Each its own unfinished file, so two asking at once never write the same one.
    partial = kept.with_name(f"{kept.stem}.{uuid4().hex[:8]}.partial.jpg")
    at = f"{seconds * point:.2f}"
    command = [
        str(ffmpeg),
        *QUIET_INPUT,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        at,
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-vf",
        size[0],
        "-q:v",
        size[1],
        "-y",
        str(partial),
    ]
    try:
        run(command)
        partial.replace(kept)
    except (OSError, subprocess.SubprocessError) as error:
        with suppress(OSError):
            partial.unlink(missing_ok=True)
        if kept.is_file():  # another asking at the same time kept it first
            return kept
        log.info("No still from %s at %s s: %s", video, at, error)
        if isinstance(error, subprocess.SubprocessError):  # ffmpeg itself couldn't, or hung
            with suppress(OSError):
                failed.touch()
        return None
    return kept
