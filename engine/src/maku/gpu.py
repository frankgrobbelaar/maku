"""How busy and how warm the graphics card is while files convert, as the queue shows it.

nvidia-smi, which NVIDIA's driver installs, says. Without it (another card, or no driver) there
is no reading, and the queue shows none. A reading is kept for a few seconds, however often the
queue is looked at.
"""

import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_FRESH = 5.0  # seconds a reading is kept
_TIMEOUT = 3.0  # seconds nvidia-smi gets to answer
_ASK = ("--query-gpu=utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits")


@dataclass(frozen=True)
class Reading:
    busy: int  # percent of the time the card was working
    celsius: int


class Gpu:
    def __init__(
        self,
        command: Sequence[str] = ("nvidia-smi",),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._command = list(command)
        self._clock = clock
        self._lock = threading.Lock()
        self._kept: tuple[float, Reading | None] | None = None
        self._missing = False  # there's no nvidia-smi: not asked again

    def reading(self) -> Reading | None:
        with self._lock:
            if self._missing:
                return None
            if self._kept is not None and self._clock() - self._kept[0] < _FRESH:
                return self._kept[1]
        found = self._ask()
        with self._lock:
            self._kept = (self._clock(), found)
        return found

    def _ask(self) -> Reading | None:
        try:
            done = subprocess.run(  # noqa: S603 - the driver's nvidia-smi, never a shell
                [*self._command, *_ASK],
                stdin=subprocess.DEVNULL,  # the engine's own input is the app's
                capture_output=True,
                timeout=_TIMEOUT,
                creationflags=_NO_WINDOW,
                check=False,
            )
        except FileNotFoundError:
            with self._lock:
                self._missing = True
            return None
        except OSError, subprocess.TimeoutExpired:
            return None
        lines = done.stdout.decode("utf-8", "replace").strip().splitlines()
        if done.returncode != 0 or not lines:
            return None
        try:
            busy, celsius = (int(part.strip()) for part in lines[0].split(","))
        except ValueError:
            return None
        return Reading(busy, celsius)
