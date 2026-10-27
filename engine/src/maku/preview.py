"""See it first: one frame of a video before converting and after, made as converting would make
it, for the Convert screen's comparison.

The frames are taken at the stills' three points (maku/stills.py) and kept in the data folder's
cache as PNG, so nothing is lost on the way and a second look is instant. The after is made by the
filters the conversion runs (maku/core/convert.py builds both commands): deinterlaced, brought
down to the standard, or only made 10-bit, so a re-encode can be judged before it's queued. A
picture converting copies (a remux) looks as it is on both sides.
"""

import hashlib
import subprocess
from pathlib import Path
from typing import Literal

from maku.config import DataPaths
from maku.convert import Programs
from maku.core.convert import preview_command, recipe, still_command
from maku.core.media import MediaInfo
from maku.core.standard import Method, Standard, decide
from maku.stills import POINTS

type Side = Literal["before", "after"]

_TIMEOUT = 120  # seconds for one frame (a 4K film's included)


class PreviewError(Exception):
    """The frame couldn't be made. The message says why, in words."""


def frame(
    paths: DataPaths,
    programs: Programs,
    source: Path,
    media: MediaInfo,
    standard: Standard,
    *,
    side: Side,
    point: int,
) -> Path:
    """The picture of one side of the comparison, made the first time it's asked for: the
    original as it is (`before`), or as converting makes it (`after`). Raises PreviewError when
    it can't be made."""
    video = media.video
    if video is None or not media.duration or not 0 <= point < len(POINTS):
        raise PreviewError("There's no picture to show from this file.")
    decision = decide(media, standard)
    if decision.method is not Method.REENCODE:
        side = "before"  # nothing is made anew: it looks as it is
    at = media.duration * POINTS[point]
    stat = source.stat()
    what = side if side == "before" else f"{decision.method}-{decision.width}x{decision.height}"
    key = f"{source}|{stat.st_size}|{stat.st_mtime_ns}|{point}|{what}"
    kept = paths.cache / "previews" / f"{hashlib.sha256(key.encode()).hexdigest()[:24]}.png"
    if kept.is_file():
        return kept
    kept.parent.mkdir(parents=True, exist_ok=True)
    partial = kept.with_name(f"{kept.stem}.partial.png")
    try:
        if side == "before":
            command = still_command(programs.ffmpeg, source, partial, at=at, deinterlace=False)
        else:
            made = recipe(source, media, decision, tag="")
            command = preview_command(programs.ffmpeg, source, partial, made, at=at)
        _run(programs, command)
        partial.replace(kept)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return kept


def _run(programs: Programs, command: list[str]) -> None:
    """Runs ffmpeg for one frame."""
    process = programs.start(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        _, err = process.communicate(timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise PreviewError("ffmpeg took too long over one frame, so Maku stopped it.") from None
    if process.returncode != 0:
        said = err.decode("utf-8", "replace").strip().splitlines()
        raise PreviewError(f"ffmpeg couldn't make the frame: {said[-1] if said else 'it stopped'}.")
