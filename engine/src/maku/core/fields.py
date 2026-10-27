"""Reading values out of JSON that may not be shaped as promised: ffprobe's reports and TMDB's
answers. Each helper returns None, an empty mapping or an empty list for anything missing
or of the wrong type, so a parser never crashes on an odd answer.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import cast

type Json = Mapping[str, object]


def text(data: Json, key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def whole(data: Json, key: str) -> int | None:
    value = data.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def decimal(data: Json, key: str) -> float | None:
    value = data.get(key)
    if isinstance(value, bool):
        return None
    try:
        return float(value) if isinstance(value, (str, int, float)) else None
    except ValueError:
        return None


def mapping(data: Json, key: str) -> Json:
    value = data.get(key)
    return cast("Json", value) if isinstance(value, Mapping) else {}


def mappings(data: Json, key: str) -> list[Json]:
    """The objects in a list, skipping anything that isn't one."""
    return [cast("Json", item) for item in _sequence(data, key) if isinstance(item, Mapping)]


def texts(data: Json, key: str) -> list[str]:
    """The strings in a list, skipping anything that isn't one."""
    return [item for item in _sequence(data, key) if isinstance(item, str)]


def numbers(data: Json, key: str) -> list[int]:
    """The whole numbers in a list, skipping anything that isn't one."""
    items = _sequence(data, key)
    return [item for item in items if isinstance(item, int) and not isinstance(item, bool)]


def day(value: str | None) -> date | None:
    """An ISO date ("2026-10-11"), or None when it's missing or not a date."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _sequence(data: Json, key: str) -> Sequence[object]:
    value = data.get(key)
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    return cast("Sequence[object]", value)
