"""Playing a video inside Maku's window (maku/core/player.py has the commands): a ticket for each
video the window opens, the stream of it from any point, and its text subtitles copied out once
to draw in.

The window's <video> can't send the engine's token, so each video opened gets a ticket, a long
random name only the window is told, and the stream's address carries it instead. Only the
latest few tickets work, each for one video, and each plays one stream at a time: a new one (a
seek, another sound track) stops the one before, and so does closing the player.

Copying text subtitles out reads the whole file, which takes a while from a hard drive, so the
video plays at once and its subtitles join when they're ready (the window asks). The copies, and
the fonts that go with them, stay in the cache for the last few videos played.
"""

import contextlib
import hashlib
import logging
import os
import secrets
import shutil
import subprocess
import threading
from collections import deque
from collections.abc import AsyncGenerator, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Literal

import anyio

from maku.config import DataPaths
from maku.core.fields import Json
from maku.core.plan import sidecars_of
from maku.core.player import (
    ENCODERS,
    Drawn,
    Playable,
    Subtitles,
    encoder_check_command,
    first_sound,
    first_subtitles,
    playable,
    stream_command,
    subtitles_command,
)

log = logging.getLogger(__name__)

TICKETS = 4  # tickets that work: the window plays one video at a time
KEPT = 6  # videos whose subtitles stay copied out in the cache
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_CHUNK = 1 << 16
_COPYING = 1800  # seconds a copy of subtitles may take: a whole film read from a slow drive
_CHECKING = 30  # seconds for an encoder to show it works
# What ffmpeg says of a file it can't read on from where it is.
_DAMAGE = ("invalid data", "error while decoding", "corrupt", "concealing", "missing picture")

type Ffmpeg = Callable[[], Sequence[str] | None]
type Why = Literal["drive", "gone", "damaged", "failed"]


class PlayerError(Exception):
    """Maku can't play it: the message says why, in words."""


class UnknownTicketError(PlayerError):
    """The ticket isn't one of the latest: the video was closed, or another one opened since."""


@dataclass(frozen=True)
class Opened:
    ticket: str
    playable: Playable
    sound: int | None  # the sound track to start with
    subtitles: int | None  # the subtitles to start with


@dataclass(frozen=True)
class Stopped:
    """Why the latest stream ended before the video did."""

    why: Why  # its drive went, the file went, the file is damaged there, or something else
    detail: str | None  # what ffmpeg said last


@dataclass(frozen=True)
class State:
    ready: tuple[int, ...]  # subtitles ready to draw in
    preparing: tuple[int, ...]  # subtitles being copied out of the file
    failed: tuple[tuple[int, str], ...]  # subtitles that couldn't be, and why
    stopped: Stopped | None


@dataclass
class _Ticket:
    path: Path
    playable: Playable
    folder: Path  # where its subtitles are copied to
    ready: set[int]
    preparing: set[int] = field(default_factory=set[int])
    failed: dict[int, str] = field(default_factory=dict[int, str])
    stopped: Stopped | None = None
    stream: subprocess.Popen[bytes] | None = None
    copies: list[subprocess.Popen[bytes]] = field(default_factory=list[subprocess.Popen[bytes]])


class Player:
    """The videos the window has open, one engine-wide (`app.state.player`)."""

    def __init__(self, paths: DataPaths, ffmpeg: Ffmpeg) -> None:
        """`ffmpeg` gives Maku's ffmpeg as a command, or None while there's none yet."""
        self._paths = paths
        self._ffmpeg = ffmpeg
        self._lock = threading.Lock()
        self._tickets: dict[str, _Ticket] = {}  # the oldest first
        self._working: str | None = None  # the encoder that last worked
        self._broken: set[str] = set()  # encoders that don't work on this PC

    @property
    def folder(self) -> Path:
        return self._paths.cache / "player"

    def open(self, path: Path, report: Json) -> Opened:
        """A ticket for the video at `path`, with what it offers to play (`report` is ffprobe's,
        as the scan stored it). Nothing is copied out of it till the window asks (`prepare`):
        it may want other subtitles than the file's own pick, or none."""
        if self._ffmpeg() is None:
            raise PlayerError("Maku has no ffmpeg yet, so it can't play anything.")
        try:
            names = [each.name for each in path.parent.iterdir()]
        except OSError:
            names = []
        found = playable(report, path, [Path(each) for each in sidecars_of(path, names)])
        folder = self.folder / _key(path)
        held = _Ticket(path, found, folder, ready=_ready(found, folder))
        ticket = secrets.token_urlsafe(24)
        with self._lock:
            self._tickets[ticket] = held
            while len(self._tickets) > TICKETS:
                _close(self._tickets.pop(next(iter(self._tickets))))
        with contextlib.suppress(OSError):
            os.utime(folder)  # played again: kept over older ones
        return Opened(ticket, found, first_sound(found), first_subtitles(found))

    def state(self, ticket: str) -> State:
        held = self._held(ticket)
        with self._lock:
            return State(
                ready=tuple(sorted(held.ready)),
                preparing=tuple(sorted(held.preparing)),
                failed=tuple(sorted(held.failed.items())),
                stopped=held.stopped,
            )

    def prepare(self, ticket: str, number: int) -> State:
        """Has the subtitles `number` copied out of the file, unless they're ready to draw in
        already (pictures are laid over straight from the file; a file beside it is used as
        it is)."""
        held = self._held(ticket)
        track = held.playable.track(number)
        if track is None:
            raise PlayerError("The video has no such subtitles.")
        with self._lock:
            wanted = number not in held.ready and number not in held.preparing
            if wanted:
                held.preparing.add(number)
                held.failed.pop(number, None)
        if wanted:
            threading.Thread(
                target=self._copy, args=(held, track), name="subtitles", daemon=True
            ).start()
        return self.state(ticket)

    async def stream(
        self, ticket: str, *, at: float, sound: int | None, subtitles: int | None
    ) -> AsyncGenerator[bytes]:
        """The video from `at` seconds as fragmented MP4, `sound` its sound track and
        `subtitles` drawn in (ready ones only). Raises PlayerError before the first bytes when
        nothing plays, and says why in the ticket's state."""
        held = self._held(ticket)
        ffmpeg = self._ffmpeg()
        if ffmpeg is None:
            raise PlayerError("Maku has no ffmpeg yet, so it can't play anything.")
        if sound is not None and not 0 <= sound < len(held.playable.sound):
            raise PlayerError("The video has no such sound.")
        drawn = self._drawn(held, subtitles)
        run: _Run | None = None
        first = b""
        for encoder in self._encoders():
            command = stream_command(
                ffmpeg,
                held.path,
                at=at,
                sound=sound,
                drawn=drawn,
                deinterlace=held.playable.deinterlace,
                encoder=ENCODERS[encoder],
            )
            run = self._start(held, command)
            first = await _read(run.process)
            if first:
                self._working = encoder
                break
            await anyio.to_thread.run_sync(run.settle)
            if held.stream is not run.process:
                raise PlayerError("Another stream of the video started.")
            # Nothing came: the file, or the encoder? One that worked before is fine.
            if encoder == self._working or await anyio.to_thread.run_sync(
                self._works, ffmpeg, encoder
            ):
                held.stopped = _why(held.path, run.said)
                raise PlayerError(_words(held.stopped))
            log.info("ffmpeg's %s doesn't work on this PC: %s", encoder, " ".join(run.said))
            self._broken.add(encoder)
        if run is None or not first:
            raise PlayerError("None of ffmpeg's ways of making video for the window works here.")
        ended = False
        try:
            yield first
            while chunk := await _read(run.process):
                yield chunk
            ended = True
            await anyio.to_thread.run_sync(run.settle)
        finally:
            self._finish(held, run, ended=ended)

    def close(self, ticket: str) -> None:
        """Forgets the ticket, stopping its stream and the copies of its subtitles."""
        with self._lock:
            held = self._tickets.pop(ticket, None)
        if held is not None:
            _close(held)

    def stop(self) -> None:
        """Stops every stream and copy: the engine is stopping."""
        with self._lock:
            held = list(self._tickets.values())
            self._tickets.clear()
        for each in held:
            _close(each)

    def _held(self, ticket: str) -> _Ticket:
        with self._lock:
            held = self._tickets.get(ticket)
        if held is None:
            raise UnknownTicketError("That video isn't open any more. Press Play again.")
        return held

    def _drawn(self, held: _Ticket, number: int | None) -> Drawn | None:
        if number is None:
            return None
        track = held.playable.track(number)
        if track is None:
            raise PlayerError("The video has no such subtitles.")
        if number not in held.ready:
            raise PlayerError("Those subtitles aren't ready yet.")
        if track.kind == "pictures":
            return Drawn(pictures=number)
        if track.beside is not None:
            return Drawn(text=track.beside)
        fonts = held.folder / "fonts"
        return Drawn(text=held.folder / f"{number}.ass", fonts=fonts if fonts.is_dir() else None)

    def _encoders(self) -> list[str]:
        ordered = list(ENCODERS)
        if self._working is not None:
            ordered.remove(self._working)
            ordered.insert(0, self._working)
        return [name for name in ordered if name not in self._broken]

    def _works(self, ffmpeg: Sequence[str], encoder: str) -> bool:
        try:
            done = subprocess.run(  # noqa: S603 - Maku's own ffmpeg, fixed arguments, no shell
                encoder_check_command(ffmpeg, ENCODERS[encoder]),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=_CHECKING,
                creationflags=_NO_WINDOW,
                check=False,
            )
        except OSError, subprocess.SubprocessError:
            return False
        return done.returncode == 0

    def _start(self, held: _Ticket, command: Sequence[str]) -> _Run:
        """Starts ffmpeg for the ticket's stream, stopping the one before."""
        process = subprocess.Popen(  # noqa: S603 - Maku's own ffmpeg, a path, no shell
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_NO_WINDOW,
        )
        said: deque[str] = deque(maxlen=12)
        listener = threading.Thread(target=_listen, args=(process.stderr, said), daemon=True)
        listener.start()
        with self._lock:
            before, held.stream = held.stream, process
            held.stopped = None
        _end(before)
        return _Run(process, said, listener)

    def _finish(self, held: _Ticket, run: _Run, *, ended: bool) -> None:
        """A stream over: let go of by the window (a seek, the player closed), or come to its
        end. One that ended on its own with a problem says why in the ticket's state, and so does
        one whose drive or file went: ffmpeg takes a read that fails for the file's end, and
        stops as if all were well."""
        if not ended:
            _end(run.process)
            return
        with self._lock:
            latest = held.stream is run.process
        if not latest:
            return
        if run.process.returncode not in (0, None) or not held.path.is_file():
            held.stopped = _why(held.path, run.said)
            log.info("Playing %s stopped: %s", held.path, " ".join(run.said))

    def _copy(self, held: _Ticket, track: Subtitles) -> None:
        """Copies a text subtitle track out of the file, with the file's fonts the first time,
        then marks it ready (or why it couldn't be)."""
        ffmpeg = self._ffmpeg()
        part = held.folder / f"{track.number}.{secrets.token_hex(4)}.part"
        out = held.folder / f"{track.number}.ass"
        fonts = held.folder / "fonts"
        dumps = held.folder / f"fonts.{secrets.token_hex(4)}.part"
        found = [] if fonts.is_dir() else list(held.playable.fonts)
        problem: str | None = None
        try:
            if ffmpeg is None:
                raise PlayerError("Maku has no ffmpeg yet.")
            dumps.mkdir(parents=True, exist_ok=True)
            command = subtitles_command(
                ffmpeg,
                held.path,
                track,
                part,
                [(font, dumps / f"{n}{font.extension}") for n, font in enumerate(found)],
            )
            problem = self._run_copy(held, command)
            if problem is None:
                part.replace(out)
                if found and not fonts.exists():
                    dumps.rename(fonts)
        except (OSError, PlayerError) as error:
            problem = str(error)
        finally:
            part.unlink(missing_ok=True)
            shutil.rmtree(dumps, ignore_errors=True)
        with self._lock:
            held.preparing.discard(track.number)
            if problem is None:
                held.ready.add(track.number)
            else:
                held.failed[track.number] = problem
        if problem is not None:
            log.info("Couldn't copy subtitles out of %s: %s", held.path, problem)
        self._tidy()

    def _run_copy(self, held: _Ticket, command: Sequence[str]) -> str | None:
        """Runs a copy of subtitles, which closing the ticket stops; why it failed, or None."""
        process = subprocess.Popen(  # noqa: S603 - Maku's own ffmpeg, a path, no shell
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=_NO_WINDOW,
        )
        with self._lock:
            held.copies.append(process)
        try:
            _, errors = process.communicate(timeout=_COPYING)
        except subprocess.TimeoutExpired:
            _end(process)
            return "Copying them out took too long."
        finally:
            with self._lock:
                held.copies.remove(process)
        if process.returncode == 0:
            return None
        lines = errors.decode("utf-8", "replace").strip().splitlines()
        return f"ffmpeg couldn't copy them out ({lines[-1]})." if lines else "ffmpeg stopped."

    def _tidy(self) -> None:
        """Keeps the copies of the last few videos played, and of those open now."""
        with self._lock:
            open_now = {held.folder for held in self._tickets.values()}
        try:
            folders = sorted(
                (each for each in self.folder.iterdir() if each.is_dir()),
                key=lambda each: each.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return
        for old in folders[KEPT:]:
            if old not in open_now:
                shutil.rmtree(old, ignore_errors=True)


@dataclass(frozen=True)
class _Run:
    """One stream's ffmpeg, and what it said last."""

    process: subprocess.Popen[bytes]
    said: deque[str]
    listener: threading.Thread

    def settle(self) -> None:
        """Waits for ffmpeg to finish once its output has ended, and for its last words."""
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _end(self.process)
        self.listener.join(timeout=2)


def _ready(found: Playable, folder: Path) -> set[int]:
    """Subtitles ready to draw in: pictures and files beside the video always, text in the file
    once copied out."""
    return {
        track.number
        for track in found.subtitles
        if track.kind == "pictures"
        or track.beside is not None
        or (folder / f"{track.number}.ass").is_file()
    }


def _key(path: Path) -> str:
    """A name for the video's copies: the same while the file is the same."""
    try:
        stat = path.stat()
        mark = f"{path}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        mark = str(path)
    return hashlib.sha256(mark.casefold().encode()).hexdigest()[:24]


async def _read(process: subprocess.Popen[bytes]) -> bytes:
    """ffmpeg's next bytes, or nothing at its end. A thread waits for them, and is let go at
    once if the window leaves meanwhile: stopping ffmpeg then ends its wait."""
    out = process.stdout
    if out is None:
        return b""
    return await anyio.to_thread.run_sync(out.read1, _CHUNK, abandon_on_cancel=True)  # type: ignore[attr-defined]


def _listen(errors: IO[bytes] | None, said: deque[str]) -> None:
    """Keeps what ffmpeg says last, and keeps it saying: a full pipe would stop it."""
    if errors is None:
        return
    for line in errors:
        if text := line.decode("utf-8", "replace").strip():
            said.append(text)


def _why(path: Path, said: Iterable[str]) -> Stopped:
    lines = list(said)
    last = lines[-1] if lines else None
    if not Path(path.anchor).exists():
        return Stopped("drive", None)
    if not path.is_file():
        return Stopped("gone", None)
    if any(word in line.casefold() for line in lines for word in _DAMAGE):
        return Stopped("damaged", last)
    return Stopped("failed", last)


def _words(stopped: Stopped) -> str:
    match stopped.why:
        case "drive":
            return "The video's drive isn't connected."
        case "gone":
            return "The video isn't where Maku saw it last."
        case "damaged":
            return "The video is damaged there, so it won't play."
        case "failed":
            return f"ffmpeg couldn't play it ({stopped.detail or 'it said nothing'})."


def _close(held: _Ticket) -> None:
    """Stops a closed ticket's stream (which then has nothing to tell) and its copies."""
    stream, held.stream = held.stream, None
    _end(stream)
    for process in list(held.copies):
        _end(process)


def _end(process: subprocess.Popen[bytes] | None) -> None:
    if process is not None and process.poll() is None:
        with contextlib.suppress(OSError):
            process.kill()
