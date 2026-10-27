"""English from another copy: when two copies of an episode are in the library and the one Tidy
up sets aside has English sound or subtitles the one kept hasn't, the owner can have Maku add
them to the copy kept (maku/core/merge.py picks them, maku/core/align.py lines the copies up).

A queue job of kind 'merge': Maku reads a sound track both copies share (the kept copy's first) and
finds how far one runs ahead of the other, checking the same holds at the start, the middle and
the end; copies that aren't the same cut stay as they are, and Maku says so. Then ffmpeg copies
the kept copy whole with the other's English beside it, shifted onto its picture, into a file
beside it. The result is checked (its length, its tracks, a test play) and takes the kept copy's
place as a conversion's does (maku/convert.py), the kept copy and the other going to quarantine
together, as one change History puts back.
"""

import json
import logging
import shutil
import sqlite3
import subprocess
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack, nullcontext
from datetime import datetime
from pathlib import Path

from maku.convert import (
    SPACE_MARGIN,
    ConvertError,
    InUseError,
    Programs,
    Progress,
    Said,
    Stopped,
    clear_work,
    discard_result,
    held_open,
    keep_result,
    replace_original,
    size_words,
    still_as_read,
    test_play,
)
from maku.core.align import AGREE, RATE, envelope, line_up
from maku.core.library import work_of
from maku.core.media import MediaInfo, media_from_ffprobe
from maku.core.merge import Borrowed, borrowed, merge_command, movable, shared_sound
from maku.core.standard import Method
from maku.languages import beside
from maku.probe import ProbeError, ProbeToolError
from maku.speech import SpeechError, sound_of

log = logging.getLogger(__name__)

_LOOK = 0.5  # seconds between looks at how much ffmpeg has written
_LONGER = 15.0  # seconds a result may run past the copy kept: the other's last subtitle, up


def merge(
    conn: sqlite3.Connection,
    job_id: int,
    programs: Programs,
    *,
    now: Callable[[], datetime],
    report: Callable[[Progress], None],
    stop: Callable[[], bool],
    discard: Callable[[], bool],
    hold: Callable[[], AbstractContextManager[None]] = nullcontext,
) -> None:
    """Adds the other copy's English to the kept copy and puts the result in its place, the
    kept copy and the other set aside. Raises ConvertError when it can't (both copies stay as
    they were), InUseError when either copy is open in another app (the result waits beside the
    kept one, as a conversion's does), and Stopped when asked to stop."""
    row = _job(conn, job_id)
    kept, other = Path(row["path"]), Path(row["other_path"])
    still_as_read(kept, row["size"], row["modified"])
    _other_as_read(other, row)
    ours = media_from_ffprobe(json.loads(row["probe"]))
    theirs = media_from_ffprobe(json.loads(row["other_probe"]))
    # What Tidy up offered: English subtitles beside the copy kept count as its own.
    offered = borrowed(ours, theirs, beside([kept]).get(kept, []))
    if not offered.any:
        raise ConvertError("The other copy has no English this one hasn't, so nothing changed.")
    pair = shared_sound(ours, theirs)
    if pair is None:
        raise ConvertError(
            "The two copies share no sound in one language to line them up by, so Maku kept "
            "both as they are."
        )
    total = row["size"] or 1
    report(Progress("looking", 0, total))
    offset = _offset(programs, kept, other, pair, stop)
    take = movable(offered, theirs, offset)
    if take != offered:  # never a copy set aside with English that didn't come
        raise ConvertError(
            "The other copy starts later, and its English subtitles are pictures, which can't be "
            "moved earlier. Maku kept both as they are."
        )
    output = kept.with_suffix(".mkv")
    _name_free(kept, other, output)
    _enough_space(kept, row["size"] + (row["other_size"] or 0))
    work = work_of(kept)
    clear_work(work)
    try:
        _run(
            programs,
            merge_command(programs.ffmpeg, kept, other, offset, take, ours, theirs, work),
            work,
            total,
            report,
            stop,
        )
        report(Progress("checking", total, total))
        try:
            result = programs.read(work)
        except (ProbeError, ProbeToolError) as error:
            raise ConvertError(f"The result couldn't be read back: {error}") from None
        problems = _check(ours, media_from_ffprobe(result), take)
        problems += test_play(programs, work, ours.duration or 0.0)
        if problems:
            raise ConvertError(
                f"The result didn't check out: {problems[0]}. Both copies are as they were."
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
            still_as_read(kept, row["size"], row["modified"])  # nothing saved over it since
            _other_as_read(other, row)
        except BaseException:
            discard_result(work)  # never put in place: nothing to keep
            raise
        if (open_now := held_open(row, kept)) is not None:
            keep_result(conn, row, result, Method.REMUX, work)
            raise InUseError(open_now)
        replace_original(conn, row, kept, work, output, Method.REMUX, result, now())


def _other_as_read(other: Path, row: sqlite3.Row) -> None:
    """The other copy, there as Maku read it: else its tracks may not be what it read."""
    try:
        found = other.stat()
    except OSError:
        raise ConvertError(
            f"The other copy isn't at {other} any more, so its English can't come."
        ) from None
    if (found.st_size, found.st_mtime_ns) != (row["other_size"], row["other_modified"]):
        raise ConvertError(
            "The other copy changed since Maku read it: a scan reads it again, then try again."
        )


def _name_free(kept: Path, other: Path, output: Path) -> None:
    """The result takes the kept copy's name as an MKV: a file there already (an MKV beside an
    MP4 of the same name) is found first, unless it's the other copy, which leaves first."""
    taken = str(output).casefold() not in (str(kept).casefold(), str(other).casefold())
    if taken and output.exists():
        raise ConvertError(
            f"{output.name} is beside it already, and the copy with the English would take that "
            "name. Tidy up first, or move one of them."
        )


def _job(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row:
    """The job with both copies: the one kept (its file's row, as a conversion's) and the
    other."""
    row = conn.execute(
        """SELECT j.id, j.kind, j.file_id, j.method, j.output_probe, j.source_size,
                  j.source_modified, f.path, f.size, f.modified, f.probe, f.season, f.episode,
                  t.name AS title, o.path AS other_path, o.size AS other_size,
                  o.modified AS other_modified, o.probe AS other_probe
           FROM jobs AS j JOIN files AS f ON f.id = j.file_id
           LEFT JOIN titles AS t ON t.id = f.title_id
           LEFT JOIN files AS o ON o.id = j.other_id AND o.gone_at IS NULL
           WHERE j.id = ? AND f.gone_at IS NULL""",
        (job_id,),
    ).fetchone()
    if row is None or row["probe"] is None:
        raise ConvertError("That file isn't in the library any more, or hasn't been read.")
    if row["other_path"] is None or row["other_probe"] is None:
        raise ConvertError(
            "The other copy isn't in the library any more, so its English can't come."
        )
    return row


def _offset(
    programs: Programs, kept: Path, other: Path, pair: tuple[int, int], stop: Callable[[], bool]
) -> float:
    """How many seconds later the other copy runs than the kept one, heard from the sound both
    share; ConvertError when they aren't the same cut."""
    try:
        ours = sound_of(programs.ffmpeg, kept, pair[0], stop, rate=RATE)
        theirs = sound_of(programs.ffmpeg, other, pair[1], stop, rate=RATE)
    except SpeechError as error:
        raise ConvertError(str(error), error.log) from error
    lined = line_up(envelope(ours), envelope(theirs))
    if not lined.same:
        raise ConvertError(
            f"The two copies aren't the same cut, so the English wouldn't line up: {lined.why} "
            "Maku kept both as they are."
        )
    log.info("Lined the copies up: the other runs %.2f s later", lined.offset)
    # No further apart than lining up can tell: copied as they are, nothing made anew.
    return 0.0 if abs(lined.offset) < AGREE else lined.offset


def _enough_space(kept: Path, needed: int) -> None:
    """Room beside the kept copy for the result: about the two copies' size, with a margin."""
    wanted = round(needed * SPACE_MARGIN)
    free = shutil.disk_usage(kept.parent).free
    if free < wanted:
        raise ConvertError(
            f"There isn't room beside it for the copy with the English: it needs about "
            f"{size_words(wanted)}, and {size_words(free)} is free."
        )


def _run(
    programs: Programs,
    command: list[str],
    work: Path,
    total: int,
    report: Callable[[Progress], None],
    stop: Callable[[], bool],
) -> None:
    """ffmpeg copying the streams, its progress the size written so far."""
    process = programs.start(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    said = Said(process.stderr)
    try:
        while process.poll() is None:
            if stop():
                raise Stopped
            try:
                written = work.stat().st_size
            except OSError:
                written = 0
            report(Progress("converting", min(written, total), total))
            time.sleep(_LOOK)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
    if process.returncode != 0:
        raise ConvertError(
            f"ffmpeg couldn't add the English: {said.last() or 'it stopped'}.",
            "\n".join(said.lines()) or None,
        )


def _check(kept: MediaInfo, result: MediaInfo, take: Borrowed) -> list[str]:
    """What's wrong with the result, in words: it runs as long as the kept copy, with its
    picture, its tracks and the English added."""
    problems: list[str] = []
    want, got = kept.duration or 0.0, result.duration or 0.0
    # Never shorter; a little longer when the other's last subtitle stays up past the picture.
    if got < want - max(1.0, want * 0.005) or got > want + _LONGER:
        problems.append(f"it runs {got:.0f} s, not {want:.0f} s")
    if result.video is None:
        problems.append("it has no picture")
    sound, subtitles = len(kept.audio) + len(take.sound), len(kept.subtitles) + len(take.subtitles)
    if len(result.audio) != sound:
        problems.append(f"it has {len(result.audio)} sound tracks, not {sound}")
    if len(result.subtitles) != subtitles:
        problems.append(f"it has {len(result.subtitles)} subtitle tracks, not {subtitles}")
    return problems
