"""What converting tests share: ffprobe's report on a result, and ffmpeg and ffprobe stood in for
(tests/fake_ffmpeg.py)."""

import subprocess
import sys
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

from maku import __version__
from maku.convert import Programs, start
from maku.core.fields import Json
from tests.fake_ffprobe import REPORT

FAKE_FFMPEG = [sys.executable, str(Path(__file__).parent / "fake_ffmpeg.py")]
TAG = f"reencode to 1080p · Maku {__version__}"  # a 1080p H.264 film made HEVC 10-bit


def report(width: int, height: int, *, codec: str = "hevc", tag: str | None = None) -> Json:
    """ffprobe's report on a 24-minute file like REPORT, at this size: HEVC 10-bit, or 8-bit in
    another codec."""
    made = cast("dict[str, object]", deepcopy(REPORT))
    streams = cast("list[dict[str, object]]", made["streams"])
    depth = "yuv420p10le" if codec == "hevc" else "yuv420p"
    streams[0].update({"width": width, "height": height, "codec_name": codec, "pix_fmt": depth})
    streams[0].pop("display_aspect_ratio", None)
    format_ = {**cast("dict[str, object]", made["format"]), "duration": "1440.0"}
    made["format"] = {**format_, "tags": {"MAKU": tag}} if tag else format_
    return made


def open_elsewhere(monkeypatch: pytest.MonkeyPatch, only: Path | None = None) -> list[bool]:
    """Windows saying another app has an original open (a player playing it: `only` that one,
    when given) till the list's one item is set False."""
    still = [True]

    def in_use(path: Path) -> bool:
        return still[0] and only in (None, path)

    monkeypatch.setattr("maku.convert.in_use", in_use)
    return still


def programs(converted: Json, commands: list[Sequence[str]] | None = None) -> Programs:
    """ffmpeg and ffprobe stand-ins; ffprobe reports `converted` for the result. DirectML runs."""

    def read(path: Path) -> Json:
        return converted

    def started(
        command: Sequence[str],
        *,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> subprocess.Popen[bytes]:
        if commands is not None:
            commands.append(command)
        return start(command, stdin=stdin, stdout=stdout, stderr=stderr)

    return Programs(FAKE_FFMPEG, read, start=started, directml=lambda: True)
