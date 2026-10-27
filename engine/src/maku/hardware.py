"""What Maku knows about this PC: what Windows says it has (its graphics cards, each with its own
memory as the registry has it, its processor and its memory), what checking it found, and how
fast re-encoding and making English subtitles go on it. maku/pc_check.py checks and times it;
maku/core/hardware.py decides from both.

All of it is kept in the settings: "pc" (what it has, and what checking found) and "pc_speeds"
(the times). Every job that finishes measures its speed again, blended into the speed kept, so
the times stay this PC's own.
"""

import ctypes
import json
import sqlite3
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import cast

from maku.core.estimate import HEARING, Speeds
from maku.core.hardware import Card, Checked, Place, cards_from, hearing_places, processor_name
from maku.core.media import MediaInfo
from maku.core.standard import Method

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Windows' display adapters and the processor's cores, as one JSON object.
_ASK = (
    "$cards = @(Get-CimInstance Win32_VideoController | "
    "Select-Object Name, PNPDeviceID, DriverVersion, AdapterRAM); "
    "$cores = (Get-CimInstance Win32_Processor | Measure-Object NumberOfCores -Sum).Sum; "
    "@{cards = $cards; cores = $cores} | ConvertTo-Json -Compress -Depth 3"
)
_DISPLAY = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_PROCESSOR = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
_BLEND = 0.3  # how far a finished job's speed moves the one kept
_PC, _SPEEDS = "pc", "pc_speeds"


@dataclass(frozen=True)
class Facts:
    """What this PC has, as Windows says."""

    cards: tuple[Card, ...]
    processor: str | None  # "Intel Core i5-9600K"
    cores: int | None
    memory: int | None  # bytes installed


@dataclass(frozen=True)
class Measured:
    """How this PC's times were measured: by a test (`tested`, at `at`) or by the jobs since
    `at`, and by how many of each since."""

    at: str
    tested: bool
    conversions: int
    subtitles: int


def look() -> Facts | None:
    """This PC's graphics cards, processor and memory, as Windows has them, or None when Windows
    didn't answer (what was known before stays). Nothing off Windows."""
    if sys.platform != "win32":
        return Facts((), None, None, None)
    asked = _asked()
    if asked is None:
        return None
    listed, cores = asked
    return Facts(cards_from(listed, _memories()), processor_name(_processor()), cores, _memory())


def stored(conn: sqlite3.Connection) -> tuple[Facts | None, Checked | None]:
    """What Maku found when it last looked at this PC, and what checking it found."""
    kept = _setting(conn, _PC)
    facts, checked = kept.get("facts"), kept.get("checked")
    if not isinstance(facts, dict) or not isinstance(checked, dict):
        return None, None
    try:
        found = Checked(**cast("dict[str, object]", checked))  # pyright: ignore[reportArgumentType]
        return _facts(cast("dict[str, object]", facts)), found
    except TypeError, ValueError:  # not as Maku wrote it
        return None, None


def keep(conn: sqlite3.Connection, facts: Facts, checked: Checked) -> None:
    _save(conn, _PC, {"facts": asdict(facts), "checked": asdict(checked)})


def checked_here(conn: sqlite3.Connection) -> Checked | None:
    """What checking this PC found, or None before it's checked."""
    return stored(conn)[1]


def speeds(conn: sqlite3.Connection) -> Speeds:
    """How fast re-encoding goes here: as measured, or the guess till it is."""
    kept = _setting(conn, _SPEEDS)
    return Speeds(megapixels=_number(kept, "megapixels") or Speeds().megapixels)


def rates(conn: sqlite3.Connection) -> dict[str, float]:
    """Seconds of work English subtitles take for each second of sound, by quality and place
    ("best", "fast", "fast_processor"): as measured here, the guess for any not yet."""
    return {**HEARING, **_heard(conn)}


def hearing(conn: sqlite3.Connection) -> dict[str, float]:
    """Seconds of work English subtitles take here for each second of sound, by quality
    ("best", "fast"), where each runs on this PC; the guess for any not measured yet."""
    facts, checked = stored(conn)
    places = hearing_places(facts.cards if facts else (), checked)
    found = rates(conn)
    fast = "fast_processor" if places["fast"] == "processor" else "fast"
    return {"best": found["best"], "fast": found[fast]}


def hearing_place(conn: sqlite3.Connection, quality: str) -> Place | None:
    """Where English subtitles of a quality are made on this PC: the graphics card, the
    processor, or None when this PC can't make them at that quality."""
    facts, checked = stored(conn)
    return hearing_places(facts.cards if facts else (), checked).get(quality)


def measured(conn: sqlite3.Connection) -> Measured | None:
    """How this PC's times were measured, or None while they're a guess."""
    kept = _setting(conn, _SPEEDS)
    at = kept.get("at")
    if not isinstance(at, str):
        return None
    return Measured(
        at,
        kept.get("tested") is True,
        int(_number(kept, "conversions") or 0),
        int(_number(kept, "subtitles") or 0),
    )


def keep_speeds(conn: sqlite3.Connection, found: Mapping[str, float], now: datetime) -> None:
    """A test's times ("megapixels", when it could time the encoder) in place of the ones kept;
    subtitles' stay as they were, measured or a guess (a test doesn't time them). Nothing changes
    when it timed nothing."""
    if not found:
        return
    kept = _setting(conn, _SPEEDS)
    times = {**found, "at": now.isoformat(), "tested": True, "conversions": 0, "subtitles": 0}
    _save(conn, _SPEEDS, {**kept, **times})


def forget_speeds(conn: sqlite3.Connection) -> None:
    """Back to the guesses: the times were another graphics card's."""
    with conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (_SPEEDS,))


def learn_conversion(
    conn: sqlite3.Connection, method: Method, media: MediaInfo, seconds: float, now: datetime
) -> None:
    """A finished conversion's speed (the whole of it took `seconds`), blended into the one kept:
    megapixels of its original's picture a second. A remux only copies: it measures nothing."""
    video = media.video
    if method is not Method.REENCODE or seconds <= 0 or video is None or not media.duration:
        return
    rate = float(video.frame_rate) if video.frame_rate else 24000 / 1001
    value = media.duration * rate * video.width * video.height / seconds / 1e6
    if value <= 0:
        return
    kept = _setting(conn, _SPEEDS)
    old = _number(kept, "megapixels")
    blended = value if old is None else old * (1 - _BLEND) + value * _BLEND
    done = int(_number(kept, "conversions") or 0) + 1
    _save(conn, _SPEEDS, {**_since(kept, now), "megapixels": blended, "conversions": done})


def learn_hearing(
    conn: sqlite3.Connection, key: str, sound: float, seconds: float, now: datetime
) -> None:
    """A video's English subtitles took `seconds` for `sound` seconds of it: blended into the
    rate kept for that quality where it ran ("best", "fast", "fast_processor")."""
    if sound <= 0 or seconds <= 0:
        return
    kept = _setting(conn, _SPEEDS)
    rates = _heard(conn)
    value = seconds / sound
    old = rates.get(key)
    rates[key] = value if old is None else old * (1 - _BLEND) + value * _BLEND
    done = int(_number(kept, "subtitles") or 0) + 1
    _save(conn, _SPEEDS, {**_since(kept, now), "hearing": rates, "subtitles": done})


def _since(kept: dict[str, object], now: datetime) -> dict[str, object]:
    """The times kept, saying since when they're measured: the first job's time when nothing
    was measured before."""
    return kept if isinstance(kept.get("at"), str) else {**kept, "at": now.isoformat()}


def _heard(conn: sqlite3.Connection) -> dict[str, float]:
    found = _setting(conn, _SPEEDS).get("hearing")
    if not isinstance(found, dict):
        return {}
    rates = cast("dict[str, object]", found)
    return {key: float(value) for key, value in rates.items() if isinstance(value, int | float)}


def _number(kept: dict[str, object], key: str) -> float | None:
    value = kept.get(key)
    return float(value) if isinstance(value, int | float) and value > 0 else None


def _setting(conn: sqlite3.Connection, key: str) -> dict[str, object]:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    try:
        found: object = json.loads(row["value"]) if row else None
    except ValueError:
        return {}
    return cast("dict[str, object]", found) if isinstance(found, dict) else {}


def _save(conn: sqlite3.Connection, key: str, value: dict[str, object]) -> None:
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )


def _facts(kept: dict[str, object]) -> Facts:
    cards = tuple(
        Card(**cast("dict[str, object]", card))  # pyright: ignore[reportArgumentType]
        for card in cast("list[object]", kept.get("cards") or [])
    )
    processor, cores, memory = kept.get("processor"), kept.get("cores"), kept.get("memory")
    return Facts(
        cards,
        processor if isinstance(processor, str) else None,
        cores if isinstance(cores, int) else None,
        memory if isinstance(memory, int) else None,
    )


def _asked() -> tuple[list[dict[str, object]], int | None] | None:
    """Windows' display adapters (Win32_VideoController) and the processor's cores, or None when
    PowerShell didn't answer."""
    try:
        result = subprocess.run(  # noqa: S603 - a fixed command, no shell
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _ASK],  # noqa: S607
            stdin=subprocess.DEVNULL,  # the engine's own input is the app's
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_NO_WINDOW,
            check=False,
        )
        found: object = json.loads(result.stdout)
    except OSError, subprocess.TimeoutExpired, ValueError:
        return None
    if not isinstance(found, dict):
        return None
    answer = cast("dict[str, object]", found)
    listed = answer.get("cards")
    entries = cast("list[object]", listed) if isinstance(listed, list) else [listed]
    cards = [cast("dict[str, object]", each) for each in entries if isinstance(each, dict)]
    cores = answer.get("cores")
    return cards, cores if isinstance(cores, int) and cores > 0 else None


def _memories() -> dict[str, int]:
    """Each display adapter's own memory, by name, as its driver wrote it in the registry."""
    if sys.platform != "win32":
        return {}
    import winreg

    found: dict[str, int] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY) as adapters:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(adapters, index)
                except OSError:
                    break
                index += 1
                if not name.isdigit():
                    continue
                try:
                    with winreg.OpenKey(adapters, name) as adapter:
                        desc = str(winreg.QueryValueEx(adapter, "DriverDesc")[0])
                        size = winreg.QueryValueEx(adapter, "HardwareInformation.qwMemorySize")[0]
                except OSError:
                    continue
                if isinstance(size, int) and size > 0:
                    found[desc] = size
    except OSError:
        return {}
    return found


def _processor() -> str | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _PROCESSOR) as key:
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0])
    except OSError:
        return None


def _memory() -> int | None:
    """The memory installed, in bytes (Windows keeps a little of it for itself, so what it
    reports as there is a shade less)."""
    if sys.platform != "win32":
        return None
    kilobytes = ctypes.c_ulonglong(0)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    if not kernel.GetPhysicallyInstalledSystemMemory(ctypes.byref(kilobytes)):
        return None
    return int(kilobytes.value) * 1024
