"""Converting one file, start to finish.

The picture is looked at for interlacing (idet) when ffprobe couldn't tell, then the file is
made by one ffmpeg command, as its recipe says (maku/core/convert.py). The result is checked
(length, streams, its picture and its HDR, Maku's tag, a test play at three points) and only then
takes the original's place, the original going to quarantine on its own drive. Both moves are
journaled (maku/changes.py), so a crash leaves nothing half done, and `restore` puts the original
back.

The work happens beside the original, in a file whose name ends in .maku-converting: no scan or
watcher counts it as a video, and it moves into place on the same drive at once. A crash while
it moves leaves the job "replacing": `settle` finishes it, or puts the original back. When
another app has the original open (a player playing it), the checked result waits beside it
(InUseError) and `put_in` puts it in place once the app lets go.
"""

import json
import logging
import shutil
import sqlite3
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, ExitStack, nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path, PurePath
from typing import IO, Literal, Protocol, cast

from maku import __version__
from maku.changes import (
    ChangeState,
    SavedChange,
    apply_plan,
    changes_of,
    save_plan,
    undo_plan,
)
from maku.core.convert import (
    QUIET_INPUT,
    Recipe,
    check,
    interlace_command,
    interlaced,
    one_command,
    recipe,
)
from maku.core.estimate import FILM, estimate
from maku.core.fields import Json
from maku.core.hardware import NO_ENCODER
from maku.core.languages import track_languages
from maku.core.library import WORKING, drive_of, work_of
from maku.core.media import MediaInfo, media_from_ffprobe
from maku.core.naming import unique_path
from maku.core.plan import (
    Change,
    ChangeKind,
    Plan,
    in_quarantine,
    plan_set_aside,
    quarantine_place,
    sidecars_of,
)
from maku.core.speech import Hearing
from maku.core.standard import Decision, Method, Standard, decide, deinterlaced, size_name
from maku.preferences import originals_deleted
from maku.probe import ProbeError, ProbeToolError
from maku.quarantine import clear_original
from maku.system import in_use

log = logging.getLogger(__name__)

CONVERTED = (Method.REMUX, Method.REENCODE)  # what a job can be
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_PLAY_SECONDS = 5  # how much of the result a test play decodes, at each of three points
_LOOK_TIMEOUT = 300  # seconds for idet or a test play
SPACE_MARGIN = 1.25  # free space wanted, over the estimated size of the result
_SAID_LINES = 400  # of what ffmpeg says, kept for "Copy full log"
_HELD_TRIES = 5  # times Maku tries to take away a result Windows holds a moment
_HELD_PAUSE = 0.2  # seconds between them
IN_USE_WAIT = timedelta(minutes=5)  # before a result waiting for its original is tried again
# What History says of a file given English from another copy, and of that copy, set aside.
MERGED_ASIDE = "Set aside: its copy with the other's English takes its place"
OTHER_ASIDE = "A copy: its English went into the one kept"

type Stage = Literal["looking", "converting", "checking", "replacing"]


@dataclass(frozen=True)
class Progress:
    stage: Stage
    frames: int  # done so far
    total: int  # in all, as far as Maku can tell


class ConvertError(Exception):
    """The file couldn't be converted, and the original is as it was. The message says why, and
    `log` holds what ffmpeg said, when it was ffmpeg that stopped."""

    def __init__(self, message: str, log: str | None = None) -> None:
        super().__init__(message)
        self.log = log


class NoRoomError(ConvertError):
    """There isn't room on the file's drive ("D:") for the result."""

    def __init__(self, drive: str, needed: int, free: int) -> None:
        super().__init__(
            f"There isn't room on {drive} for the next file: it needs about {size_words(needed)},"
            f" and {size_words(free)} is free."
        )
        self.drive = drive
        self.needed = needed


class InUseError(ConvertError):
    """Another app has the original open (a player playing it), so it can't be set aside: the
    checked result waits beside it, and the job is tried again with `put_in`."""


class Stopped(Exception):  # noqa: N818 - not an error: the owner paused or skipped it
    """Converting stopped because the owner asked; nothing changed."""


class Starter(Protocol):
    """Starts a program, as subprocess.Popen does."""

    def __call__(
        self,
        command: Sequence[str],
        *,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> subprocess.Popen[bytes]: ...


def start(
    command: Sequence[str],
    *,
    stdin: int | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
) -> subprocess.Popen[bytes]:
    """A program without a console window (the engine has none), and with nothing on standard
    input unless it's given frames there: the engine's own input is the app's (see QUIET_INPUT)."""
    return subprocess.Popen(  # noqa: S603 - Maku's own ffmpeg, never a shell
        list(command),
        stdin=subprocess.DEVNULL if stdin is None else stdin,
        stdout=stdout,
        stderr=stderr,
        creationflags=_NO_WINDOW,
    )


def _nowhere(_quality: str) -> Path | None:
    return None


def _whisper(folder: Path, graphics: bool) -> Hearing:
    from maku.speech import Listener  # it needs this module first

    return Listener(folder, graphics=graphics)


def _directml() -> bool:
    from maku.directml import runs  # ONNX Runtime loads only when it's asked for

    return runs()


@dataclass(frozen=True)
class Programs:
    """What the queue runs: ffmpeg (a command, so tests can stand in for it) and ffprobe on a
    file; and for English subtitles, where each quality's speech model is once it's downloaded
    ("best"), and Whisper loaded from there."""

    ffmpeg: Sequence[str]
    read: Callable[[Path], Json]
    start: Starter = field(default=start)
    speech: Callable[[str], Path | None] = field(default=_nowhere)
    listener: Callable[[Path, bool], Hearing] = field(default=_whisper)  # on the card?
    # The command that runs this engine again, for the PC check's look at DirectML in a process
    # of its own (maku/directml.py says why); without one (tests), `directml` looks here.
    engine: Sequence[str] = ()
    directml: Callable[[], bool] = field(default=_directml)


def convert(
    conn: sqlite3.Connection,
    job_id: int,
    programs: Programs,
    standard: Standard,
    *,
    now: Callable[[], datetime],
    report: Callable[[Progress], None],
    stop: Callable[[], bool],
    discard: Callable[[], bool],
    hold: Callable[[], AbstractContextManager[None]] = nullcontext,
    encoder: str | None = "nvenc",
) -> None:
    """Converts a job's file and puts the result in its place, `hold` holding scans off while
    it moves. `stop` stops it while the file is being made; once it's made, it's checked and put
    in place unless `discard` says to throw it away (the owner skipped it, say). `encoder` is
    the one this PC has (maku/core/convert.py's ENCODERS), None when it has none. Raises
    ConvertError when it can't (the original stays as it was), or Stopped when asked."""
    if encoder is None:
        raise ConvertError(NO_ENCODER)
    row = _job(conn, job_id)
    source = Path(row["path"])
    still_as_read(source, row["size"], row["modified"])
    media = media_from_ffprobe(json.loads(row["probe"]))
    decision = decide(media, standard)
    if decision.method not in CONVERTED or media.video is None:
        raise ConvertError("It's at your standard already, so there's nothing to convert.")
    total = _frames(media)
    report(Progress("looking", 0, total))
    if media.video.interlaced is None and _looks_interlaced(programs, source, media):
        decision = deinterlaced(decision)
    size = size_name(decision.width, decision.height)
    made = recipe(
        source,
        media,
        decision,
        tag=f"{decision.method} to {size} · Maku {__version__}",
        encoder=encoder,
    )
    name_free(source, Path(made.output))
    _enough_space(source, media, decision)
    work = work_of(source)
    clear_work(work)
    try:
        _in_one_command(programs, source, work, made, total, report, stop)
        report(Progress("checking", total, total))
        try:
            result = programs.read(work)
        except (ProbeError, ProbeToolError) as error:
            raise ConvertError(f"The result couldn't be read back: {error}") from None
        problems = check(media, media_from_ffprobe(result), made)
        problems += test_play(programs, work, media.duration or 0.0)
        if problems:
            raise ConvertError(
                f"The result didn't check out: {problems[0]}. The original is as it was."
            )
    except BaseException:
        discard_result(work)
        raise
    report(Progress("replacing", total, total))
    with ExitStack() as held:
        try:
            held.enter_context(hold())
            if discard():
                raise Stopped
            still_as_read(source, row["size"], row["modified"])  # nothing saved over it since
        except BaseException:
            discard_result(work)  # never put in place: nothing to keep
            raise
        if (held := held_open(row, source)) is not None:
            keep_result(conn, row, result, made.method, work)
            raise InUseError(held)
        replace_original(conn, row, source, work, made.output, made.method, result, now())


def put_in(conn: sqlite3.Connection, job_id: int, *, now: datetime) -> None:
    """Puts a result that waited beside its original (InUseError) in the original's place. The
    caller holds scans off. Raises InUseError while the original is still open, and ConvertError
    when the result can't go in: it went, or the original changed since it was made."""
    row = _job(conn, job_id)
    source = Path(row["path"])
    work = work_of(source)
    if row["output_probe"] is None or not _made_by(work, row["output_size"]):
        if row["kind"] == "merge":
            raise ConvertError("Its copy with the English isn't there any more. Try again.")
        raise ConvertError("Its converted copy isn't there any more. Try again to convert it anew.")
    still_as_read(source, row["source_size"], row["source_modified"])
    if (held := held_open(row, source)) is not None:
        raise InUseError(held)
    result: Json = json.loads(row["output_probe"])
    method = Method(row["method"])
    replace_original(conn, row, source, work, source.with_suffix(".mkv"), method, result, now)


def throw_away_kept(conn: sqlite3.Connection, job_id: int) -> None:
    """Takes away the result a job kept beside its original (InUseError), once the job won't put
    it in place: skipped, taken out of the queue, or failed. A job without one keeps its file."""
    row = conn.execute(
        """SELECT f.path FROM jobs AS j JOIN files AS f ON f.id = j.file_id
           WHERE j.id = ? AND j.retry_at IS NOT NULL""",
        (job_id,),
    ).fetchone()
    if row is None:
        return
    path = Path(row["path"])
    discard_result(work_of(path))


def keep_result(
    conn: sqlite3.Connection, row: sqlite3.Row, result: Json, method: Method, work: Path
) -> None:
    """What `put_in` needs of a result kept beside its original: what it is, how it was made,
    its size (only that file goes in), and the original as it was made from."""
    with conn:
        conn.execute(
            """UPDATE jobs SET method = ?, output_probe = ?, output_size = ?, source_size = ?,
                      source_modified = ?
               WHERE id = ?""",
            (
                method.value,
                json.dumps(result, separators=(",", ":")),
                work.stat().st_size,
                row["size"],
                row["modified"],
                row["id"],
            ),
        )


def _made_by(work: Path, size: int | None) -> bool:
    """Whether the result beside a file is the one its job made (one kept before Maku noted its
    size goes by its name)."""
    try:
        return work.is_file() and size in (None, work.stat().st_size)
    except OSError:
        return False


def held_open(row: sqlite3.Row, source: Path) -> str | None:
    """Why a result can't take its original's place just now, in words: the file open in another
    app, or for English from another copy, that copy, which goes to quarantine with it."""
    if in_use(source):
        return open_elsewhere(row)
    other = row["other_path"] if row["kind"] == "merge" else None
    if other is not None and in_use(Path(other)):
        return open_elsewhere(row, other=True)
    return None


def open_elsewhere(row: sqlite3.Row, *, other: bool = False) -> str:
    minutes = round(IN_USE_WAIT.total_seconds() / 60)
    which = f"The other copy of {label_of(row)}" if other else label_of(row)
    return (
        f"{which} is open in another app, maybe your player. Maku will try again in "
        f"{minutes} minutes."
    )


def restore(conn: sqlite3.Connection, job_id: int, *, now: datetime) -> tuple[SavedChange, ...]:
    """Puts a converted file's original back, and the converted copy away. The original comes
    back where the converted file is now (a tidy-up may have filed it since), under that name with
    its own extension. It works for a conversion that failed after setting its original aside.
    A file changed again since (converted anew, or given another copy's English) has the later
    change put back first. English from another copy brings that copy back too; what couldn't come
    back (its old name taken, its drive away) is returned, and asked again, put back then, as is
    that copy alone once the file as it was is gone from quarantine."""
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    plan_id: int | None = job["plan_id"] if job else None
    set_aside = _set_aside(conn, plan_id)
    if job is None or plan_id is None or set_aside is None:
        raise ConvertError("Maku has no converted file to put back for that.")
    merged = job["kind"] == "merge"
    if merged and (job["state"] == "restored" or set_aside.cleared_at is not None):
        return _other_back(conn, plan_id, now)
    if job["state"] == "restored":
        raise ConvertError("Maku has no converted file to put back for that.")
    if set_aside.cleared_at is not None:
        raise ConvertError("Its original was cleared out of quarantine, so it can't come back.")
    if replaced_since(conn, job):
        raise ConvertError("It was changed again since: put back the later change first.")
    _follow_the_copy(conn, plan_id, job["file_id"])
    moved = _moved(conn, plan_id)
    in_place = moved is not None and moved.state is ChangeState.DONE
    if in_place and moved is not None and not _made_by(moved.target, job["output_size"]):
        raise ConvertError(
            "The file in its place isn't the one Maku made any more, so it was left as it is."
        )
    outcome = undo_plan(conn, plan_id, now=now)
    set_aside, moved = _set_aside(conn, plan_id), _moved(conn, plan_id)
    if set_aside is None or set_aside.state is not ChangeState.UNDONE:
        problem = set_aside.problem if set_aside else None
        raise ConvertError(problem or "Maku couldn't put the original back.")
    if moved is not None:
        _take_away(moved.source)  # the converted copy, taken out of the way
    original = set_aside.source
    probe = json.loads(job["source_probe"])
    _record(conn, job["file_id"], original, job["source_size"], job["source_modified"], probe, now)
    with conn:  # it keeps when it finished: History says how long converting took
        conn.execute("UPDATE jobs SET state = 'restored' WHERE id = ?", (job_id,))
    return outcome.problems


def replaced_since(conn: sqlite3.Connection, job: sqlite3.Row) -> bool:
    """Whether a later job has replaced the file a job made (converted it anew, or given it
    another copy's English): putting the earlier one back would take the later's result away."""
    later = conn.execute(
        """SELECT 1 FROM jobs WHERE file_id = ? AND id != ? AND plan_id > ?
           AND state IN ('done', 'replacing')""",
        (job["file_id"], job["id"], job["plan_id"] or 0),
    ).fetchone()
    return later is not None


def _other_back(conn: sqlite3.Connection, plan_id: int, now: datetime) -> tuple[SavedChange, ...]:
    """English from another copy, the file as it was back already or gone from quarantine: what's
    left in quarantine (the other copy, and the subtitles named after it) comes back, and the
    copy with the English stays in its place."""

    def held(change: SavedChange) -> str | None:
        if change.kind is ChangeKind.MOVE:
            return "The copy with the English stays: the file as it was isn't in quarantine."
        return None

    if not any(
        change.kind is ChangeKind.QUARANTINE
        and change.state is ChangeState.DONE
        and change.cleared_at is None
        for change in changes_of(conn, plan_id)
    ):
        raise ConvertError("Maku has nothing of it left to put back.")
    outcome = undo_plan(conn, plan_id, now=now, held=held)
    return tuple(change for change in outcome.problems if change.kind is not ChangeKind.MOVE)


def settle(
    conn: sqlite3.Connection, job_id: int, read: Callable[[Path], Json] | None, now: datetime
) -> None:
    """A job a crash stopped while its result was taking its original's place (its changes as
    maku/changes.py's `recover` left them): finished when the result can still go in, or else
    the original is put back and the job waits in the queue again. `read` is ffprobe, when
    Maku has it; without it the next scan reads the result."""
    job = conn.execute("SELECT file_id, plan_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
    plan_id: int | None = job["plan_id"] if job else None
    moved = _moved(conn, plan_id)
    carry_on = moved is not None and moved.state is ChangeState.PLANNED and moved.source.exists()
    if plan_id is not None and carry_on:  # the result was checked before the crash
        apply_plan(conn, plan_id, now=now)
        moved = _moved(conn, plan_id)
    elif plan_id is not None and moved is not None and moved.state is ChangeState.DONE:
        if any(change.state is ChangeState.PLANNED for change in changes_of(conn, plan_id)):
            apply_plan(conn, plan_id, now=now)  # what's left: the other copy, its subtitles
    if moved is not None and moved.state is ChangeState.DONE:
        try:
            result = read(moved.target) if read else None
        except ProbeError, ProbeToolError:
            result = None
        if result is not None:
            finish(conn, job_id, result, now)
            _drop_original(conn, plan_id, now)
            return
        with conn:  # in place, but unread: the next scan reads it
            conn.execute(
                "UPDATE files SET path = ?, probed_at = NULL, gone_at = NULL WHERE id = ?",
                (str(moved.target), job["file_id"]),
            )
            conn.execute(
                """UPDATE jobs SET state = 'done', finished_at = COALESCE(finished_at, ?),
                          retry_at = NULL
                   WHERE id = ?""",
                (now.isoformat(), job_id),
            )
        _drop_original(conn, plan_id, now)
        return
    if plan_id is not None:
        undo_plan(conn, plan_id, now=now)
        if moved is not None:
            _take_away(moved.source)  # the result, never in place
    with conn:  # a result kept beside its original (InUseError) that never began going in waits on
        conn.execute(
            """UPDATE jobs SET state = 'queued', plan_id = NULL, started_at = NULL,
                      retry_at = CASE WHEN ? THEN retry_at END,
                      finished_at = CASE WHEN ? THEN finished_at END
               WHERE id = ?""",
            (plan_id is None, plan_id is None, job_id),
        )


def _take_away(result: Path) -> None:
    """Removes a result that never went in, or came back out: only ever a file named as Maku's
    work in progress, whatever a damaged or imported journal says."""
    if result.name.endswith(WORKING):
        discard_result(result)


def discard_result(result: Path) -> None:
    """Takes away a result that won't go in. Windows may hold it a moment after its ffmpeg ends
    (an antivirus looking at it, say), so Maku tries a few times; one still held is left for the
    next try, which takes it away first. Never what decides how a conversion went."""
    for tried in range(1, _HELD_TRIES + 1):
        try:
            result.unlink(missing_ok=True)
            return
        except OSError:
            if tried == _HELD_TRIES:
                log.warning("Couldn't remove %s; the next try takes it away", result)
                return
            time.sleep(_HELD_PAUSE)


def _moved(conn: sqlite3.Connection, plan_id: int | None) -> SavedChange | None:
    """A conversion plan's second change: the result into its original's place."""
    if plan_id is None:
        return None
    return next((c for c in changes_of(conn, plan_id) if c.kind is ChangeKind.MOVE), None)


def _set_aside(conn: sqlite3.Connection, plan_id: int | None) -> SavedChange | None:
    """A conversion plan's first change: the original into quarantine."""
    if plan_id is None:
        return None
    return next((c for c in changes_of(conn, plan_id) if c.kind is ChangeKind.QUARANTINE), None)


def _follow_the_copy(conn: sqlite3.Connection, plan_id: int, file_id: int) -> None:
    """When a tidy-up has moved the converted file since (its record followed it), the plan's
    changes are pointed at where it is now: putting the original back then takes the converted
    file from there, and the original takes its place, with the original's own extension."""
    moved, set_aside = _moved(conn, plan_id), _set_aside(conn, plan_id)
    row = conn.execute("SELECT path FROM files WHERE id = ?", (file_id,)).fetchone()
    if moved is None or set_aside is None or row is None or moved.state is not ChangeState.DONE:
        return
    now_at = Path(row["path"])
    if str(now_at) == str(moved.target):
        return
    with conn:
        conn.execute(
            "UPDATE changes SET source = ?, target = ? WHERE id = ?",
            (str(work_of(now_at)), str(now_at), moved.id),
        )
        conn.execute(
            "UPDATE changes SET source = ? WHERE id = ?",
            (str(now_at.with_suffix(set_aside.source.suffix)), set_aside.id),
        )


def _job(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row:
    row = conn.execute(
        """SELECT j.id, j.kind, j.file_id, j.method, j.output_probe, j.output_size,
                  j.source_size, j.source_modified, f.path, f.size, f.modified, f.probe,
                  f.season, f.episode, t.name AS title, o.path AS other_path,
                  o.size AS other_size, o.modified AS other_modified
           FROM jobs AS j JOIN files AS f ON f.id = j.file_id
           LEFT JOIN titles AS t ON t.id = f.title_id
           LEFT JOIN files AS o ON o.id = j.other_id AND o.gone_at IS NULL
           WHERE j.id = ? AND f.gone_at IS NULL""",
        (job_id,),
    ).fetchone()
    if row is None or row["probe"] is None:
        raise ConvertError("That file isn't in the library any more, or hasn't been read.")
    return row


def still_as_read(source: Path, size: int, modified: int) -> None:
    try:
        now = source.stat()
    except OSError:
        raise ConvertError(f"It isn't at {source} any more.") from None
    if (now.st_size, now.st_mtime_ns) != (size, modified):
        raise ConvertError("It changed since Maku read it: a scan reads it again, then it can go.")


def _frames(media: MediaInfo) -> int:
    rate = media.video.frame_rate if media.video and media.video.frame_rate else FILM
    return round((media.duration or 0.0) * float(rate))


def _looks_interlaced(programs: Programs, source: Path, media: MediaInfo) -> bool:
    """idet's look at a stretch from the middle of the picture."""
    command = interlace_command(programs.ffmpeg, source, at=(media.duration or 0.0) / 2)
    done = _run(programs, command)
    return interlaced(done.stderr.decode("utf-8", "replace"))


def name_free(source: Path, output: Path) -> None:
    """The result takes the original's name as an MKV: a file there already (an MKV beside an
    MP4 of the same name) would only be found once it's made, so it's looked for first."""
    if str(output).casefold() != str(source).casefold() and output.exists():
        raise ConvertError(
            f"{output.name} is beside it already, and the converted file would take that name. "
            "Tidy up first, or move one of them."
        )


def clear_work(work: Path) -> None:
    """Takes away what an earlier try left of the result (a crash, say)."""
    try:
        work.unlink(missing_ok=True)
    except OSError:
        raise ConvertError(
            "Its unfinished copy from an earlier try is still in use, so it can't start over yet."
            " Try again in a minute."
        ) from None


def size_words(count: int) -> str:
    """Bytes as the app writes them: "412 MB", "9.1 GB", "35 GB"."""
    if count >= 10**10:
        return f"{round(count / 10**9)} GB"
    if count >= 10**9:
        return f"{count / 10**9:.1f} GB"
    if count >= 10**6:
        return f"{round(count / 10**6)} MB"
    return f"{max(1, round(count / 10**3)) if count else 0} KB"


def room_for(media: MediaInfo, decision: Decision) -> int:
    """The free space a file's result wants on its drive, in bytes: its size, as estimated, with
    a margin."""
    return round(estimate(media, decision).output_bytes * SPACE_MARGIN)


def _enough_space(source: Path, media: MediaInfo, decision: Decision) -> None:
    needed = room_for(media, decision)
    free = shutil.disk_usage(source.parent).free
    if free < needed:
        raise NoRoomError(drive_of(source) or str(source.parent), needed, free)


def _in_one_command(
    programs: Programs,
    source: Path,
    work: Path,
    made: Recipe,
    total: int,
    report: Callable[[Progress], None],
    stop: Callable[[], bool],
) -> None:
    """One ffmpeg, its progress read from its standard output."""
    command = one_command(programs.ffmpeg, source, work, made)
    process = programs.start(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    said = Said(process.stderr)
    frames = 0
    for line in cast("IO[bytes]", process.stdout):
        if stop():
            _end(process)
            raise Stopped
        if line.startswith(b"frame="):
            frames = int(line.split(b"=", 1)[1].strip() or 0)
            report(Progress("converting", frames, total))
    if process.wait() != 0:
        reached = f" past {_clock(frames / float(made.frame_rate), whole=True)}" if frames else ""
        raise ConvertError(
            f"ffmpeg couldn't convert it{reached}: {said.last() or 'it stopped'}.",
            _log(said, stopped=(frames, total)),
        )


def test_play(programs: Programs, work: Path, duration: float) -> list[str]:
    """A test play of the result at three points: what went wrong, if anything."""
    problems: list[str] = []
    for share in (0.1, 0.5, 0.9):
        at = max(0.0, duration * share - _PLAY_SECONDS / 2)
        command = [
            *programs.ffmpeg,
            *QUIET_INPUT,
            "-v",
            "error",
            "-xerror",
            "-ss",
            f"{at:.1f}",
            "-i",
            str(work),
            "-t",
            str(_PLAY_SECONDS),
            "-map",
            "0:V:0",
            "-map",
            "0:a?",
            # The frames keep the times the file gives them: rounded to the frame rate, two can
            # come out the same at some points of a file that plays well (its original too), and
            # ffmpeg complains of that as if it were damage.
            "-enc_time_base:v",
            "demux",
            "-f",
            "null",
            "-",
        ]
        done = _run(programs, command)
        said = done.stderr.decode("utf-8", "replace").strip()
        if done.returncode != 0 or said:
            first = said.splitlines()[0] if said else f"ffmpeg stopped with {done.returncode}"
            problems.append(f"it didn't play at {_clock(at)} ({first})")
            break
    return problems


def _log(*said: Said, stopped: tuple[int, int]) -> str:
    """What ffmpeg said, for "Copy full log", and where it stopped."""
    reached, total = stopped
    lines = [line for each in said for line in each.lines()]
    return "\n".join([*lines, f"Stopped at frame {reached:,} of {total:,}."])


def replace_original(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    source: Path,
    work: Path,
    output: PurePath,
    method: Method,
    result: Json,
    now: datetime,
) -> None:
    """The original to quarantine and the result into its place, journaled; then the library's
    record of the file describes the result, keeping what it was identified as. English added
    from another copy (a job of kind 'merge') sets that copy aside in the same plan, as a
    tidy-up sets a copy aside: History puts both back together."""
    label = label_of(row)
    place = _free_place(source, now)
    merged = row["kind"] == "merge"
    changes = [
        Change(
            ChangeKind.QUARANTINE,
            source,
            place,
            f"{label} · original",
            MERGED_ASIDE if merged else "Set aside: its converted copy takes its place",
        )
    ]
    if merged:  # first: the result may take its name ("Ep 7.mkv" kept as "Ep 7.mp4")
        changes += _other_aside(row, source, now, taken={str(place).casefold()})
    changes.append(
        Change(
            ChangeKind.MOVE,
            work,
            output,
            label,
            "With the other copy's English" if merged else f"Converted ({method})",
        )
    )
    title = f"Added English from another copy to {label}" if merged else f"Converted {label}"
    plan_id = save_plan(conn, Plan(tuple(changes)), title, now=now, kind="convert")
    original = source.stat()
    with conn:
        conn.execute(
            """UPDATE jobs SET state = 'replacing', plan_id = ?, method = ?, source_size = ?,
                      source_modified = ?, source_probe = ?
               WHERE id = ?""",
            (
                plan_id,
                method.value,
                original.st_size,
                original.st_mtime_ns,
                row["probe"],
                row["id"],
            ),
        )
    outcome = apply_plan(conn, plan_id, now=now)
    if outcome.problems:
        undone = undo_plan(conn, plan_id, now=now)
        held = held_open(row, source) if not undone.problems else None
        if held is not None:  # a player opened it a moment ago
            _forget(conn, plan_id, row["id"])  # nothing moved: it leaves no trace
            keep_result(conn, row, result, method, work)
            raise InUseError(held)
        discard_result(work)
        problem = outcome.problems[0].problem
        if undone.problems:  # the original stays in quarantine: History can still put it back
            raise ConvertError(
                f"Maku couldn't put it in place ({problem}), nor the original back: it's in "
                f"{place}. Put it back from History."
            )
        raise ConvertError(f"Maku couldn't put it in place, so the original is back: {problem}")
    finish(conn, row["id"], result, now)
    _drop_original(conn, plan_id, now)


def _drop_original(conn: sqlite3.Connection, plan_id: int | None, now: datetime) -> None:
    """When the owner chose to delete converted files' originals, this one goes now that its
    result is checked and in place; otherwise it waits in quarantine like any copy. A file that
    only had English added from another copy keeps its original in quarantine, with that copy:
    it wasn't converted."""
    if plan_id is None or not originals_deleted(conn):
        return
    job = conn.execute("SELECT kind FROM jobs WHERE plan_id = ?", (plan_id,)).fetchone()
    if job is None or job["kind"] != "merge":
        clear_original(conn, plan_id, now=now)


def _other_aside(row: sqlite3.Row, kept: Path, now: datetime, *, taken: set[str]) -> list[Change]:
    """English from another copy: that copy to quarantine with the subtitles named after it, as
    a tidy-up sets a copy aside, but not subtitles the kept copy's name fits too (two copies
    side by side, "Ep 7.mkv" and "Ep 7.mp4"). Nothing when it went meanwhile: its English is in."""
    other = Path(row["other_path"]) if row["other_path"] else None
    if other is None or in_quarantine(other) or not _as_read(other, row):
        return []
    try:
        names = [each.name for each in other.parent.iterdir()]
    except OSError:
        names = []
    shared = set(sidecars_of(kept, names)) if other.parent == kept.parent else set[PurePath]()
    sidecars = [each for each in sidecars_of(other, names) if each not in shared]
    day = now.date()
    try:
        there = {
            str(each).casefold() for each in Path(quarantine_place(other, day)).parent.iterdir()
        }
    except OSError:  # not there yet: the first today
        there = set[str]()
    plan = plan_set_aside(
        [(other, f"{label_of(row)} · other copy", sidecars)],
        day=day,
        taken=there | taken,
        reason=OTHER_ASIDE,
    )
    return list(plan.changes)


def _forget(conn: sqlite3.Connection, plan_id: int, job_id: int) -> None:
    """A plan that moved nothing, gone from the journal and History."""
    with conn:
        conn.execute("UPDATE jobs SET plan_id = NULL WHERE id = ?", (job_id,))
        conn.execute("DELETE FROM changes WHERE plan_id = ?", (plan_id,))
        conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))


def _free_place(source: Path, now: datetime) -> Path:
    """Where the original is set aside: today's quarantine folder on its drive, under its name,
    or with (2), (3)… when copies set aside earlier today have those names."""
    place = Path(quarantine_place(source, now.date()))
    try:
        taken = {str(path) for path in place.parent.iterdir()}
    except OSError:  # not there yet: the first today
        taken = set[str]()
    return Path(unique_path(place, taken))


def finish(conn: sqlite3.Connection, job_id: int, result: Json, now: datetime) -> None:
    """A result in its place: the library's record describes it, and the job is done."""
    job = conn.execute("SELECT file_id, plan_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
    moved = next(c for c in changes_of(conn, job["plan_id"]) if c.kind is ChangeKind.MOVE)
    if moved.state is not ChangeState.DONE:
        raise ConvertError("The converted copy isn't in place.")
    stat = moved.target.stat()
    _record(conn, job["file_id"], moved.target, stat.st_size, stat.st_mtime_ns, result, now)
    with conn:
        conn.execute(
            """UPDATE jobs SET state = 'done', finished_at = COALESCE(finished_at, ?),
                      output_size = ?, output_probe = ?, problem = NULL, retry_at = NULL
               WHERE id = ?""",
            (now.isoformat(), stat.st_size, json.dumps(result, separators=(",", ":")), job_id),
        )


def _record(
    conn: sqlite3.Connection,
    file_id: int,
    path: Path,
    size: int,
    modified: int,
    report: Json,
    now: datetime,
) -> None:
    """The library's record of a file, as a scan would have read it. Another record at its
    path (one a scan made meanwhile, or a file once there and gone since) gives way: this one
    knows what the file is."""
    media = media_from_ffprobe(report)
    video = media.video
    with conn:
        conn.execute("DELETE FROM files WHERE path = ? AND id != ?", (str(path), file_id))
        conn.execute(
            """UPDATE files SET path = ?, size = ?, modified = ?, gone_at = NULL, probed_at = ?,
                      probe = ?, problem = NULL, duration = ?, width = ?, height = ?, codec = ?,
                      sound = ?, subtitles = ?, health_at = ?, health_problem = NULL
               WHERE id = ?""",
            (
                str(path),
                size,
                modified,
                now.isoformat(),
                json.dumps(report, separators=(",", ":")),
                media.duration,
                video.width if video else None,
                video.height if video else None,
                video.codec if video else None,
                json.dumps(track_languages(track.language for track in media.audio)),
                json.dumps(track_languages(track.language for track in media.subtitles)),
                now.isoformat(),  # its test play, as it was made, is its health check
                file_id,
            ),
        )


def _as_read(other: Path, row: sqlite3.Row) -> bool:
    """Whether English from another copy's other copy is there as Maku read it."""
    try:
        found = other.stat()
    except OSError:
        return False
    return (found.st_size, found.st_mtime_ns) == (row["other_size"], row["other_modified"])


def label_of(row: sqlite3.Row) -> str:
    """ "Starfall · S01E03", or the film's name, or the file's, from a row with the file's `path`,
    `season` and `episode`, and its title's name (`title`)."""
    title = row["title"] or Path(row["path"]).stem
    if row["season"] is not None and row["episode"] is not None:
        return f"{title} · S{row['season']:02d}E{row['episode']:02d}"
    return title


class Said:
    """What a program writes to its error output, read as it goes so it never blocks: its last
    few hundred lines."""

    def __init__(self, stream: IO[bytes] | None) -> None:
        self._lines: deque[str] = deque(maxlen=_SAID_LINES)
        self._thread = threading.Thread(target=self._read, args=(stream,), daemon=True)
        self._thread.start()

    def _read(self, stream: IO[bytes] | None) -> None:
        if stream is None:
            return
        for line in stream:
            text = line.decode("utf-8", "replace").strip()
            if text:
                self._lines.append(text)

    def last(self) -> str:
        self._thread.join(timeout=5)
        return self._lines[-1] if self._lines else ""

    def lines(self) -> list[str]:
        self._thread.join(timeout=5)
        return list(self._lines)


def _end(*processes: subprocess.Popen[bytes]) -> None:
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.wait()


def _run(programs: Programs, command: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    process = programs.start(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        _, err = process.communicate(timeout=_LOOK_TIMEOUT)
    except subprocess.TimeoutExpired:
        _end(process)
        raise ConvertError("ffmpeg took too long to look at it, so Maku stopped it.") from None
    return subprocess.CompletedProcess(list(command), process.returncode, b"", err)


def _clock(seconds: float, *, whole: bool = False) -> str:
    """ "04:12": to the nearest second, or the whole seconds reached (`whole`)."""
    count = int(seconds) if whole else round(seconds)
    return f"{count // 60:02d}:{count % 60:02d}"
