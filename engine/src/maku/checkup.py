"""The health check: every video test-played overnight, a few at a time, a few seconds at three
points as a player would from there, so a file damaged since Maku read it shows before it's
wanted. A video plays when its pictures come: an original can say a little as it starts from a
point (a frame that leans on one before it) and still play well. A video is played again a month
on, or once it changes; one Maku made was test-played as it was made. A folder whose drive isn't
connected waits. What didn't play waits for the owner: nothing changes till they say.
"""

import json
import logging
import re
import sqlite3
import subprocess
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from maku.convert import Programs
from maku.core.convert import QUIET_INPUT
from maku.core.media import media_from_ffprobe
from maku.queue import NIGHT

log = logging.getLogger(__name__)

AGAIN = timedelta(days=30)  # how long a video's check holds before it's played again
SETTING = "health_check"  # in settings: whether the check runs, on unless turned off
POINTS = (0.1, 0.5, 0.9)  # how far into the video each stretch is played
SECONDS = 5.0  # of each stretch
ENOUGH = 0.5  # of a stretch's pictures that must come for it to have played
TIMEOUT = 120  # seconds for one stretch: a damaged file can make ffmpeg hang
_ADDRESS = re.compile(r" @ (?:0x)?[0-9a-fA-F]+\]")  # "[h264 @ 000002345]": which decoder, in memory


def at_night(moment: datetime) -> bool:
    """The night the check plays videos in: the one the queue's nights-only schedule uses."""
    start, end = NIGHT
    return moment.time() >= start or moment.time() < end


@dataclass(frozen=True)
class Unplayed:
    """A video the check couldn't play, and where it stopped."""

    file_id: int
    path: str
    title_id: int | None
    title: str | None
    season: int | None
    episode: int | None
    episode_end: int | None
    problem: str
    at: str | None  # when it was checked; None: it's to be played again


@dataclass(frozen=True)
class Checkup:
    on: bool
    checked: int  # of the library's videos that play, checked within the month
    total: int
    unplayed: list[Unplayed]


def is_on(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (SETTING,)).fetchone()
    return row is None or row["value"] != "false"


def there(conn: sqlite3.Connection) -> list[int]:
    """The library folders that are there now: one whose drive isn't connected waits."""
    rows = conn.execute("SELECT id, path FROM folders").fetchall()
    return [row["id"] for row in rows if Path(row["path"]).is_dir()]


def due(
    conn: sqlite3.Connection,
    now: datetime,
    limit: int,
    *,
    skip: Collection[int] = (),
    folders: Collection[int] | None = None,
) -> list[sqlite3.Row]:
    """The videos to play next, in the folders that are there (`folders`, else every one there
    now), leaving out `skip`: never checked first, then the longest since. A video that couldn't
    be read, or that Maku has marked broken, is broken already: it isn't played."""
    return conn.execute(
        """SELECT id, path, duration, probe, health_problem FROM files
           WHERE gone_at IS NULL AND probe IS NOT NULL AND problem IS NULL
             AND (health_at IS NULL OR health_at < ?)
             AND folder_id IN (SELECT value FROM json_each(?))
             AND id NOT IN (SELECT value FROM json_each(?))
           ORDER BY health_at IS NOT NULL, health_at, id LIMIT ?""",
        (
            (now - AGAIN).isoformat(),
            json.dumps(list(there(conn) if folders is None else folders)),
            json.dumps(list(skip)),
            limit,
        ),
    ).fetchall()


def check(conn: sqlite3.Connection, programs: Programs, row: sqlite3.Row, now: datetime) -> bool:
    """Test-plays one video and keeps what it found. False when it couldn't be played now: it's
    gone, which a scan tells. True when it was played, well or not."""
    path = Path(row["path"])
    if not path.is_file():
        return False
    media = media_from_ffprobe(json.loads(row["probe"])) if row["probe"] else None
    video = media.video if media else None
    rate = float(video.frame_rate) if video and video.frame_rate else 24.0
    try:
        problem = plays(programs, path, row["duration"] or 0.0, rate)
    except OSError as error:
        log.info("Maku couldn't test-play %s: %s", path, error)
        return False
    with conn:
        conn.execute(
            "UPDATE files SET health_at = ?, health_problem = ? WHERE id = ?",
            (now.isoformat(), problem, row["id"]),
        )
    return True


def plays(programs: Programs, path: Path, duration: float, rate: float) -> str | None:
    """Plays a few seconds of the video at three points, its picture decoded as a player would
    from there: what went wrong, or None when it played."""
    for share in POINTS:
        at = max(0.0, duration * share - SECONDS / 2)
        left = duration - at if duration > 0 else SECONDS
        wanted = max(1.0, min(SECONDS, left) * rate * ENOUGH)
        command = [
            *programs.ffmpeg,
            *QUIET_INPUT,
            "-v",
            "error",
            "-nostats",
            "-progress",
            "pipe:1",
            "-ss",
            f"{at:.1f}",
            "-i",
            str(path),
            "-t",
            str(SECONDS),
            "-map",
            "0:V:0",
            "-f",
            "null",
            "-",
        ]
        process = programs.start(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            out, err = process.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return f"It didn't play at {_clock(at)}: ffmpeg took too long, so Maku stopped it."
        if _frames(out.decode("utf-8", "replace")) < wanted:
            return f"It didn't play at {_clock(at)} ({_last_word(err)})"
    return None


def _last_word(said: bytes) -> str:
    """ffmpeg's last word on it, its addresses left out ("[h264] error while decoding MB 62
    36"), passing over its "Last message repeated" lines."""
    lines = [
        _ADDRESS.sub("]", line.strip())
        for line in said.decode("utf-8", "replace").splitlines()
        if line.strip() and not line.strip().startswith("Last message repeated")
    ]
    return lines[-1] if lines else "no picture came"


def _frames(progress: str) -> int:
    """The pictures ffmpeg's progress says it decoded: its last "frame=" line."""
    found = [line[6:].strip() for line in progress.splitlines() if line.startswith("frame=")]
    return int(found[-1]) if found and found[-1].isdigit() else 0


def _clock(seconds: float) -> str:
    whole = round(seconds)
    return f"{whole // 60:02d}:{whole % 60:02d}"


@dataclass(frozen=True)
class Night:
    """A stretch of the night's check: the videos that newly didn't play, and whether more are
    due."""

    unplayed: list[int]
    more: bool


def night(
    conn: sqlite3.Connection,
    programs: Programs,
    now: Callable[[], datetime],
    *,
    until: datetime,
    stop: Callable[[], bool],
) -> Night:
    """Test-plays the videos that are due till `until`, or till `stop` says. A video gone from
    its folder waits for the scan that tells."""
    found: list[int] = []
    tried: set[int] = set()
    folders = there(conn)
    while now() < until and not stop():
        rows = due(conn, now(), 20, skip=tried, folders=folders)
        if not rows:
            break
        for row in rows:
            if now() >= until or stop():
                break
            tried.add(row["id"])
            if check(conn, programs, row, now()) and row["health_problem"] is None:
                after = conn.execute(
                    "SELECT health_problem FROM files WHERE id = ?", (row["id"],)
                ).fetchone()
                if after["health_problem"] is not None:
                    found.append(row["id"])
    return Night(found, bool(due(conn, now(), 1, skip=tried, folders=folders)))


def checkup(conn: sqlite3.Connection, now: datetime) -> Checkup:
    """How the check stands: how many of the videos it plays were checked within the month, and
    the ones that didn't play."""
    counts = conn.execute(
        """SELECT COUNT(*) AS total, COUNT(CASE WHEN health_at >= ? THEN 1 END) AS checked
           FROM files WHERE gone_at IS NULL AND probe IS NOT NULL AND problem IS NULL""",
        ((now - AGAIN).isoformat(),),
    ).fetchone()
    rows = conn.execute(
        """SELECT f.id, f.path, f.title_id, t.name AS title, f.season, f.episode, f.episode_end,
                  f.health_problem, f.health_at
           FROM files AS f LEFT JOIN titles AS t ON t.id = f.title_id
           WHERE f.gone_at IS NULL AND f.problem IS NULL AND f.health_problem IS NOT NULL
           ORDER BY t.name, f.season, f.episode, f.path"""
    ).fetchall()
    return Checkup(
        on=is_on(conn),
        checked=counts["checked"],
        total=counts["total"],
        unplayed=[
            Unplayed(
                file_id=row["id"],
                path=row["path"],
                title_id=row["title_id"],
                title=row["title"],
                season=row["season"],
                episode=row["episode"],
                episode_end=row["episode_end"],
                problem=row["health_problem"],
                at=row["health_at"],
            )
            for row in rows
        ],
    )


def again(conn: sqlite3.Connection) -> None:
    """Every video is played again, from the next night."""
    with conn:
        conn.execute("UPDATE files SET health_at = NULL")


def plays_after_all(conn: sqlite3.Connection, file_id: int, now: datetime) -> None:
    """The owner played it and it's fine: it's taken off the list, till next month's check."""
    with conn:
        conn.execute(
            "UPDATE files SET health_problem = NULL, health_at = ? WHERE id = ?",
            (now.isoformat(), file_id),
        )


def mark_broken(conn: sqlite3.Connection, file_id: int, now: datetime) -> bool:
    """The owner says it's broken: it's a broken file from now on, as one that couldn't be read
    is, what the check found saying why. False when it isn't on the list."""
    with conn:
        done = conn.execute(
            """UPDATE files SET problem = health_problem, marked_at = ?, health_problem = NULL
               WHERE id = ? AND health_problem IS NOT NULL""",
            (now.isoformat(), file_id),
        )
    return done.rowcount > 0
