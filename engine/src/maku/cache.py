"""Answers from web services, kept for a while in the data folder's `cache` folder so Maku doesn't
ask the same question twice: a rescan of a hundred series costs TMDB nothing. Anything in it can
be deleted at any time; Maku asks again.
"""

import hashlib
import json
import logging
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from maku.core import fields
from maku.core.fields import Json

log = logging.getLogger(__name__)

DAY = 86_400.0  # seconds


class Cache:
    def __init__(self, folder: Path, clock: Callable[[], float] = time.time) -> None:
        self._folder = folder
        self._clock = clock

    def get(self, key: str, max_age: float) -> Json | None:
        """The answer saved under `key`, unless it's older than `max_age` seconds."""
        try:
            saved: object = json.loads(self._path(key).read_text(encoding="utf-8"))
        except OSError, ValueError:
            return None
        if not isinstance(saved, Mapping):
            return None
        entry = cast("Json", saved)
        when = fields.decimal(entry, "saved")
        value = entry.get("value")
        if when is None or not isinstance(value, Mapping) or self._clock() - when > max_age:
            return None
        return cast("Json", value)

    def put(self, key: str, value: Json) -> None:
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            text = json.dumps({"key": key, "saved": self._clock(), "value": value})
            self._path(key).write_text(text, encoding="utf-8")
        except OSError as error:  # a full disk only means asking again next time
            log.warning("Maku couldn't keep an answer in its cache: %s", error)

    def _path(self, key: str) -> Path:
        return self._folder / f"{hashlib.sha256(key.encode()).hexdigest()[:32]}.json"
