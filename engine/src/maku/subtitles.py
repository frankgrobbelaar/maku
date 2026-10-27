"""English subtitles Maku makes from a video's own sound (maku/speech.py hears it): the videos
that could have them, making one video's as a job in the queue, and taking a batch away again.

Maku writes a video's subtitles beside it, named after it as media servers read them ("Episode
1.en.srt"; "Episode 1.maku.en.srt" when another file has that name), first under a name of its
own till they're whole and checked. The video itself never changes. made_subtitles keeps which
files are Maku's: the player says so, and History takes a batch of them away, to the quarantine
like any copy set aside, from where they come back till it's cleared out. Only subtitles still
there as Maku wrote them (their size, and the time they were written) are Maku's: one the owner
changed is theirs, and stays.
"""

import itertools
import json
import logging
import os
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import cast

from maku.changes import PARTIAL, apply_plan, save_plan
from maku.convert import Programs, label_of
from maku.core.languages import is_english, listed
from maku.core.media import media_from_ffprobe
from maku.core.naming import unique_path
from maku.core.plan import Change, ChangeKind, Plan, quarantine_place
from maku.core.speech import Heard, Hearing, Quality, Report, Stop, srt
from maku.languages import beside
from maku.speech import SpeechError, out_of_memory, sound_of

log = logging.getLogger(__name__)

ENGLISH = ".en.srt"
OURS = ".maku.en.srt"  # when another file has the first name
TAKEN_AWAY = "Made by Maku, taken away"  # the reason of a change that set Maku's subtitles aside
NOTHING_SAID = "No one speaks in it, so there was nothing to write: Maku made no subtitles."
SHORT_OF_MEMORY = {  # by quality: the graphics card ran out of memory making them
    "best": "The graphics card ran out of memory for Best.",
    "fast": "The graphics card ran out of memory for Fast.",
}


class SubtitlesError(Exception):
    """A video's subtitles couldn't be made, and nothing beside it changed. The message says why,
    and `log` holds what ffmpeg said, when it was ffmpeg that stopped."""

    def __init__(self, message: str, log: str | None = None) -> None:
        super().__init__(message)
        self.log = log


class OutOfMemory(SubtitlesError):  # noqa: N818 - said as it is
    """The graphics card ran out of memory hearing the video: Whisper is loaded anew for the
    next."""


@dataclass(frozen=True)
class Hearable:
    """A video Maku could make English subtitles for."""

    file_id: int
    label: str  # "Starfall Academy · S01E05"
    title_id: int
    title: str
    season: int | None
    episode: int | None
    seconds: float  # how long it plays
    sound: list[str]  # each sound track's language ("jpn"; "" when one doesn't say)
    subtitles: list[str]  # the languages of its subtitles, in it and beside it, each once
    made: bool  # English subtitles Maku made are beside it
    waiting: bool  # in the queue for them, or being made


def hearable(conn: sqlite3.Connection) -> list[Hearable]:
    """The library's videos that have sound: matched to a title, there, and not broken, nor
    another copy whose English goes into the one kept (it's set aside then)."""
    rows = conn.execute(
        """SELECT f.id, f.path, f.season, f.episode, f.probe, f.sound, f.subtitles, f.title_id,
                  t.name AS title, m.name AS made, m.size AS made_size,
                  m.modified AS made_modified,
                  EXISTS (SELECT 1 FROM jobs AS j
                          WHERE j.file_id = f.id AND j.kind = 'subtitles'
                            AND j.state IN ('queued', 'running')) AS waiting
           FROM files AS f JOIN titles AS t ON t.id = f.title_id
           LEFT JOIN made_subtitles AS m ON m.file_id = f.id
           WHERE f.gone_at IS NULL AND f.problem IS NULL AND f.probe IS NOT NULL
             AND f.id NOT IN (SELECT g.other_id FROM jobs AS g
                              WHERE g.kind = 'merge' AND g.other_id IS NOT NULL
                                AND g.state IN ('queued', 'running', 'replacing'))
           ORDER BY t.name, f.season, f.episode, f.path"""
    ).fetchall()
    rows = [row for row in rows if _languages(row["sound"])]
    files = {row["id"]: Path(row["path"]) for row in rows}
    besides = beside(files.values())
    found: list[Hearable] = []
    for row in rows:
        video = files[row["id"]]
        media = media_from_ffprobe(json.loads(row["probe"]))
        found.append(
            Hearable(
                file_id=row["id"],
                label=label_of(row),
                title_id=row["title_id"],
                title=row["title"],
                season=row["season"],
                episode=row["episode"],
                seconds=media.duration or 0.0,
                sound=_languages(row["sound"]),
                subtitles=listed([*_languages(row["subtitles"]), *besides.get(video, [])]),
                made=is_made(video, row["made"], row["made_size"], row["made_modified"]),
                waiting=bool(row["waiting"]),
            )
        )
    return found


def is_made(video: Path, name: str | None, size: int | None, modified: int | None) -> bool:
    """Whether the English subtitles Maku made for a video (`name`: ".en.srt", None when it made
    none) are beside it as Maku wrote them: `size` bytes, written at `modified`."""
    return name is not None and _as_written(video.with_name(video.stem + name), size, modified)


def english(video: Hearable) -> bool:
    """Whether a video can be heard or read in English already."""
    return any(is_english(language) for language in [*video.sound, *video.subtitles])


def track_for(sound: Sequence[str], language: str) -> int:
    """The sound track to make subtitles from: the first in `language` ("jpn"), else the
    first."""
    return next((number for number, each in enumerate(sound) if each == language), 0)


def new_batch(
    conn: sqlite3.Connection, title: str, quality: Quality, language: str, *, now: datetime
) -> int:
    """A batch the owner asked for at once, as History shows it."""
    with conn:
        cursor = conn.execute(
            """INSERT INTO subtitle_batches (title, quality, language, added_at)
               VALUES (?, ?, ?, ?)""",
            (title, quality, language, now.isoformat()),
        )
    return cursor.lastrowid or 0


def make(
    conn: sqlite3.Connection,
    job_id: int,
    programs: Programs,
    listener: Hearing,
    *,
    now: Callable[[], datetime],
    report: Report,
    stop: Stop,
) -> None:
    """Makes a job's English subtitles: reads the sound track, has Whisper hear it, writes the
    subtitles beside the video, checks them, and records them as Maku's. A video where no one
    speaks gets none, and says so. Raises SubtitlesError when they can't be made, and Stopped
    when asked to stop; either way nothing beside the video changes."""
    row = conn.execute(
        """SELECT j.sound AS track, j.batch_id, j.method, f.id AS file_id, f.path, f.probe, f.sound,
                  m.name AS made, m.size AS made_size, m.modified AS made_modified
           FROM jobs AS j JOIN files AS f ON f.id = j.file_id
           LEFT JOIN made_subtitles AS m ON m.file_id = f.id
           WHERE j.id = ?""",
        (job_id,),
    ).fetchone()
    video = Path(row["path"])
    if not video.is_file():
        raise SubtitlesError("The video isn't there any more.")
    media = media_from_ffprobe(json.loads(row["probe"])) if row["probe"] else None
    seconds = (media.duration if media else None) or 0.0
    tracks = _languages(row["sound"])
    track = row["track"] or 0
    language = tracks[track] if track < len(tracks) else ""
    report(Heard("reading", 0.0, seconds))
    try:
        audio = sound_of(programs.ffmpeg, video, track, stop)
        made = listener.hear(audio, language or None, report=report, stop=stop)
    except SpeechError as error:
        raise SubtitlesError(str(error), error.log) from error
    except Exception as error:  # ONNX Runtime's own kinds are plain Exceptions
        if not out_of_memory(error):
            raise
        log.warning("Whisper ran out of the graphics card's memory: %s", error)
        raise OutOfMemory(SHORT_OF_MEMORY.get(row["method"], SHORT_OF_MEMORY["fast"])) from error
    if not made.subtitles:
        _done(conn, job_id, now(), size=0, problem=NOTHING_SAID)
        return
    report(Heard("writing", seconds, seconds))
    name = row["made"]
    ours = name is not None and _ours_or_free(
        video.with_name(video.stem + name), row["made_size"], row["made_modified"]
    )
    if name is None or not ours:
        name = _free_name(video)
    target = video.with_name(video.stem + name)
    partial = target.with_name(target.name + PARTIAL)
    text = srt(made.subtitles)
    before = conn.execute(
        "SELECT * FROM made_subtitles WHERE file_id = ?", (row["file_id"],)
    ).fetchone()
    try:
        partial.write_text(text, encoding="utf-8", newline="")
        report(Heard("checking", seconds, seconds))
        _check(partial.read_text(encoding="utf-8"), len(made.subtitles), seconds)
        written = partial.stat()  # as Maku wrote them, the same once they have their name
        # Known as Maku's before they take their name: a crash in between leaves nothing Maku
        # wrote that isn't known as its own.
        _record(conn, row["file_id"], name, row["batch_id"], track, made.language, written, now())
        partial.replace(target)
    except OSError as error:
        _put_back(conn, row["file_id"], before)
        partial.unlink(missing_ok=True)
        raise SubtitlesError(
            f"Maku couldn't write them beside the video ({error.strerror or error})."
        ) from error
    except SubtitlesError:
        partial.unlink(missing_ok=True)
        raise
    _done(conn, job_id, now(), size=written.st_size, problem=None)
    log.info("Made English subtitles for %s", video.name)


def _record(
    conn: sqlite3.Connection,
    file_id: int,
    name: str,
    batch_id: int | None,
    track: int,
    language: str,
    written: os.stat_result,
    moment: datetime,
) -> None:
    """A video's subtitles as Maku wrote them, its own while they're there that way, from sound
    track `track`, in which Whisper heard `language` ("ja")."""
    with conn:
        conn.execute(
            """INSERT INTO made_subtitles
                   (file_id, name, batch_id, sound, language, size, modified, made_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (file_id) DO UPDATE SET name = excluded.name,
                   batch_id = excluded.batch_id, sound = excluded.sound,
                   language = excluded.language, size = excluded.size,
                   modified = excluded.modified, made_at = excluded.made_at""",
            (
                file_id,
                name,
                batch_id,
                track,
                language,
                written.st_size,
                written.st_mtime_ns,
                moment.isoformat(),
            ),
        )


def _put_back(conn: sqlite3.Connection, file_id: int, before: sqlite3.Row | None) -> None:
    """The record of a video's subtitles as it was before Maku tried to make them anew."""
    with conn:
        conn.execute("DELETE FROM made_subtitles WHERE file_id = ?", (file_id,))
        if before is not None:
            conn.execute(
                """INSERT INTO made_subtitles
                       (file_id, name, batch_id, sound, language, size, modified, made_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(before[key] for key in _RECORDED),
            )


_RECORDED = ("file_id", "name", "batch_id", "sound", "language", "size", "modified", "made_at")


def unfinished(video: Path) -> list[Path]:
    """Where a job's unfinished subtitles may be beside its video, to remove after a crash."""
    return [video.with_name(f"{video.stem}{name}{PARTIAL}") for name in (ENGLISH, OURS)]


def take_away(conn: sqlite3.Connection, batch_id: int, *, now: datetime) -> int | None:
    """Sets aside the subtitles a batch made that are still there as Maku wrote them, to the
    quarantine on each one's drive, as a tidy-up History can undo. Returns the tidy-up's id, or
    None when none were there. Raises LookupError for a batch Maku doesn't have."""
    batch = conn.execute("SELECT title FROM subtitle_batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise LookupError("Maku has no such subtitles.")
    rows = conn.execute(
        """SELECT m.name, m.size, m.modified, f.path, f.season, f.episode, t.name AS title
           FROM made_subtitles AS m JOIN files AS f ON f.id = m.file_id
           LEFT JOIN titles AS t ON t.id = f.title_id
           WHERE m.batch_id = ? AND f.gone_at IS NULL ORDER BY f.path""",
        (batch_id,),
    ).fetchall()
    day = now.date()
    used: set[str] = set()
    changes: list[Change] = []
    for row in rows:
        video = Path(row["path"])
        path = video.with_name(video.stem + row["name"])
        if not _as_written(path, row["size"], row["modified"]):
            continue  # gone, or changed since: not Maku's to take
        place = unique_path(quarantine_place(path, day), used | _there(path, day))
        used.add(str(place).casefold())
        changes.append(Change(ChangeKind.QUARANTINE, path, place, label_of(row), TAKEN_AWAY))
    if not changes:
        return None
    title = f"Took away the English subtitles Maku made for {batch['title']}"
    plan_id = save_plan(conn, Plan(tuple(changes)), title, now=now)
    apply_plan(conn, plan_id, now=now)
    return plan_id


def present(conn: sqlite3.Connection, batch_id: int) -> int:
    """How many of the subtitles a batch made are there now, as Maku wrote them, beside videos
    in the library (a deleted video took its subtitles to quarantine with it)."""
    rows = conn.execute(
        """SELECT m.name, m.size, m.modified, f.path FROM made_subtitles AS m
           JOIN files AS f ON f.id = m.file_id WHERE m.batch_id = ? AND f.gone_at IS NULL""",
        (batch_id,),
    ).fetchall()
    return sum(1 for row in rows if _as_written(_beside_video(row), row["size"], row["modified"]))


def _beside_video(row: sqlite3.Row) -> Path:
    video = Path(row["path"])
    return video.with_name(video.stem + row["name"])


def _done(
    conn: sqlite3.Connection, job_id: int, moment: datetime, *, size: int, problem: str | None
) -> None:
    with conn:
        conn.execute(
            """UPDATE jobs SET state = 'done', finished_at = ?, problem = ?, output_size = ?,
                      log = NULL
               WHERE id = ?""",
            (moment.isoformat(), problem, size, job_id),
        )


def _free_name(video: Path) -> str:
    """The name Maku's subtitles take after the video's: ".en.srt", unless another file has it.
    Raises SubtitlesError when both names Maku gives subtitles are taken."""
    for name in (ENGLISH, OURS):
        if not video.with_name(video.stem + name).exists():
            return name
    raise SubtitlesError(
        f"There are files named {video.stem}{ENGLISH} and {video.stem}{OURS} beside it already, "
        "so Maku left them as they are."
    )


def _check(text: str, count: int, seconds: float) -> None:
    """Subtitles as written: every one there, in order, and within the video's length."""
    cues: list[tuple[float, float]] = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        lines = block.split("\n")
        if len(lines) < 3 or " --> " not in lines[1]:  # its number, its times and its words
            raise SubtitlesError("The subtitles Maku wrote didn't read back as written.")
        start, end = (_seconds(part) for part in lines[1].split(" --> "))
        cues.append((start, end))
    if len(cues) != count:
        raise SubtitlesError("The subtitles Maku wrote didn't read back as written.")
    in_order = all(earlier[0] <= later[0] for earlier, later in itertools.pairwise(cues))
    if not in_order or any(end <= start for start, end in cues):
        raise SubtitlesError("The subtitles Maku made weren't in order, so it didn't keep them.")
    if seconds and cues[-1][1] > seconds + 2:
        raise SubtitlesError("The subtitles Maku made ran past the end of the video.")


def _seconds(stamp: str) -> float:
    hours, minutes, rest = stamp.strip().split(":")
    whole, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(whole) + int(millis) / 1000


def _languages(stored: str | None) -> list[str]:
    try:
        found: object = json.loads(stored) if stored else []
    except ValueError:
        return []
    return [str(each) for each in cast("list[object]", found)] if isinstance(found, list) else []


def _as_written(path: Path, size: int | None, modified: int | None) -> bool:
    """Whether a file is there as Maku wrote it: its size, and when it was written."""
    try:
        found = path.stat()
    except OSError:
        return False
    return path.is_file() and (found.st_size, found.st_mtime_ns) == (size, modified)


def _ours_or_free(path: Path, size: int | None, modified: int | None) -> bool:
    """A name Maku can write its subtitles under: free, or Maku's own as it wrote them."""
    return not path.exists() or _as_written(path, size, modified)


def _there(path: Path, day: date) -> set[str]:
    """What the quarantine holds today on the file's drive, so a file set aside now never takes
    an earlier one's name."""
    try:
        return {str(each).casefold() for each in Path(quarantine_place(path, day)).parent.iterdir()}
    except OSError:
        return set()
