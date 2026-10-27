"""What the engine tells the app besides the ready line, on its standard output: one JSON object
a line, which the shell reads (app/src-tauri/src/engine.rs). Before the ready line, that it's
still working at starting (moving the data takes minutes): the app waits rather than give up on
it. After it, notifications: something worth telling the owner, such as a finished batch: a
Windows notification while Maku's window is away, a note in the window while it's open.
"""

import json
import sys
import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import Protocol

_lock = threading.Lock()  # one line at a time, from whichever thread
_EVERY = 5.0  # seconds between the lines saying the engine is still working at starting


class Notify(Protocol):
    """Tells the app something worth a notification (see `notify`)."""

    def __call__(self, title: str, body: str, /, *, link: str | None = None) -> None: ...


def notify(title: str, body: str, *, link: str | None = None) -> None:
    """Asks the app for a notification: a title, a line under it, and where in Maku it leads
    (`link`, a page such as "/titles/12"). In plain ASCII (JSON's escapes), so it reads the same
    whatever code page Windows gives the pipe."""
    event = {"event": "notify", "title": title, "body": body}
    _say({**event, "link": link} if link else event)


@contextmanager
def working(every: float = _EVERY) -> Generator[None]:
    """While it lasts, tells the app every few seconds that the engine is still working at
    starting, so it waits however long that takes (the app gives up on an engine silent for a
    minute)."""
    done = threading.Event()

    def tell() -> None:
        while not done.wait(every):
            _say({"event": "working"})

    teller = threading.Thread(target=tell, name="working", daemon=True)
    teller.start()
    try:
        yield
    finally:
        done.set()
        teller.join()


def _say(event: dict[str, str]) -> None:
    with _lock:
        try:
            sys.stdout.write(json.dumps(event) + "\n")
            sys.stdout.flush()
        except OSError, ValueError:  # the app has gone, or its pipe closed: nobody to tell
            pass
