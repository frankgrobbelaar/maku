"""Asking ffprobe what a video holds. maku/core/media.py makes sense of the answer."""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from maku.core.media import Json

# Windows would otherwise flash a console window for each file, since the engine has none.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_ARGUMENTS = ("-v", "error", "-print_format", "json", "-show_format", "-show_streams")
_LARGEST_OWN_CODE = 255  # beyond this, Windows ended the program (a crash, a missing DLL…)
_CHECK_TIMEOUT = 30  # seconds for `ffprobe -version`, which answers at once when ffprobe works


class ProbeError(Exception):
    """ffprobe couldn't read a file. The message says why, in words."""


class ProbeToolError(Exception):
    """ffprobe itself doesn't work, whatever the file: it can't start, or can't say its version.

    Nothing is learned about the file, so a scan stops rather than mark it.
    """


def probe(ffprobe: Path | Sequence[str], file: Path, timeout: float = 120) -> Json:
    """ffprobe's report on one file: its format, streams and chapters.

    `ffprobe` is the program, or a whole command that stands in for it in tests.
    """
    command = [str(ffprobe)] if isinstance(ffprobe, Path) else list(ffprobe)
    try:
        result = subprocess.run(  # noqa: S603 - Maku's own ffprobe, and a path, never a shell
            [*command, *_ARGUMENTS, "-show_chapters", str(file)],
            stdin=subprocess.DEVNULL,  # the engine's own input is the app's
            capture_output=True,
            timeout=timeout,
            creationflags=_NO_WINDOW,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ProbeError(
            f"ffprobe spent more than {timeout:.0f} seconds on it without an answer, so Maku "
            "stopped it. The file may be damaged."
        ) from None
    except OSError as error:
        raise ProbeToolError(f"ffprobe couldn't start: {error.strerror or error}") from error
    if result.returncode != 0:
        lines = result.stderr.decode("utf-8", "replace").strip().splitlines()
        said = lines[-1].removeprefix(f"{file}: ").rstrip(".") if lines else ""
        crashed = not 0 < result.returncode <= _LARGEST_OWN_CODE
        if said and not crashed:
            raise ProbeError(f"Maku couldn't read it ({said}). It may be damaged, or not a video.")
        # It crashed, or failed without a word. That may be this file, or ffprobe itself.
        # Windows' own codes are known in hex: 0xC0000135 is a missing DLL, say.
        code = f"0x{result.returncode & 0xFFFFFFFF:08X}" if crashed else result.returncode
        stopped = f"ffprobe stopped with code {code}" + (f": {said}" if said else "")
        if not _works(command):
            raise ProbeToolError(stopped)
        raise ProbeError(f"Maku couldn't read it ({stopped}). It may be damaged, or not a video.")
    try:
        report: Json = json.loads(result.stdout)
    except ValueError:
        raise ProbeError("ffprobe answered something Maku couldn't read.") from None
    return report


def _works(command: Sequence[str]) -> bool:
    """Whether ffprobe runs at all: it can say its version."""
    try:
        result = subprocess.run(  # noqa: S603 - as in probe
            [*command, "-version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=_CHECK_TIMEOUT,
            creationflags=_NO_WINDOW,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return False
    return result.returncode == 0
