"""What Maku tells after it closed unexpectedly (a crash, a power cut, Task Manager): what it
settled as it started again. Files that were converting start over from their beginning, a result
that was taking its original's place is finished or its original put back (maku/queue.py), and
file moves a tidy-up or a delete was making are settled (maku/changes.py). A clean stop leaves
none of these, so finding any is how Maku knows it closed unexpectedly. Home tells the owner,
until they've seen it, for a day. A stop the app asked for, even one cut short before the engine
had stopped (the app waits only a few seconds), isn't told of; nor is a start that restored a
backup, whose records may have been mid-way.
"""

import json
import sqlite3
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from maku.config import DataPaths

_KEY = "recovery"  # the settings row holding the last one
_TOLD_FOR = timedelta(days=1)
_STOPPING = "stopping.txt"  # in the data folder: the app asked the engine to stop


@dataclass(frozen=True)
class Recovery:
    """What Maku settled as it started again after closing unexpectedly."""

    at: str = ""  # when Maku started again
    restarted: int = 0  # files that were converting: in line again, from their beginning
    finished: int = 0  # results that were taking their original's place: in it now
    put_back: int = 0  # originals put back, their results never in place
    moves: int = 0  # a tidy-up's or a delete's file moves, settled

    def anything(self) -> bool:
        return any((self.restarted, self.finished, self.put_back, self.moves))


def note(conn: sqlite3.Connection, found: Recovery) -> None:
    """Keeps what a start settled, when it settled anything, for the owner to see."""
    if not found.anything():
        return
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (_KEY, json.dumps(asdict(found))),
        )


def last(conn: sqlite3.Connection, now: datetime) -> Recovery | None:
    """The last recovery, while it's news: not seen yet, and less than a day old."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (_KEY,)).fetchone()
    if row is None:
        return None
    found = Recovery(**json.loads(row["value"]))
    if now - datetime.fromisoformat(found.at) > _TOLD_FOR:
        return None
    return found


def asked_to_stop(paths: DataPaths) -> None:
    """Notes that the app asked the engine to stop, before it starts stopping."""
    with suppress(OSError):  # the data's drive went: nothing to tell then either
        (paths.root / _STOPPING).write_text("", encoding="utf-8")


def stopped_on_purpose(paths: DataPaths) -> bool:
    """As the engine starts: whether the last one was asked to stop. Asked once."""
    note = paths.root / _STOPPING
    try:
        note.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def seen(conn: sqlite3.Connection) -> None:
    """The owner has seen it: it isn't told again."""
    with conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (_KEY,))
