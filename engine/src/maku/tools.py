"""The tools Maku downloads, as listed in downloads.json: ffmpeg on first run, and Whisper's
speech models the first time the owner makes subtitles at their quality.

A download is used only when its size and SHA-256 match the list. An archive is unpacked into
the data folder's tools folder, replacing an older build, keeping only the listed folder of the
archive; a download that comes as several files (a model's) is saved there file by file, each
checked, a file fetched whole already kept when a download starts again. Downloads run on a
background thread and say how far they are. In development, MAKU_FFMPEG_DIR (or
MAKU_SPEECH_BEST_DIR, and so on) can point at a copy that's already on the PC instead.
"""

import errno
import hashlib
import http.client
import json
import logging
import os
import shutil
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Any, Literal, Protocol, Self, cast
from urllib.error import URLError
from urllib.request import urlopen

from maku.config import DataPaths

log = logging.getLogger(__name__)

_CHUNK = 1 << 20
_MARKER = "maku-download.json"  # which build is unpacked, to notice when the list moves on


@dataclass(frozen=True)
class File:
    """One file of a download that comes as several, saved as `name` in the tool's folder."""

    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Download:
    """One entry of downloads.json."""

    id: str
    name: str
    version: str
    purpose: str
    licence: str
    home: str
    url: str | None  # an archive's address; None for a download that comes as `files`
    size: int | None  # in all
    sha256: str | None
    keep: str | None  # the folder inside the archive that Maku keeps
    by: Literal["maku", "installer"]  # who fetches it: Maku, or the installer
    # When Maku fetches it: on the setup's Tools step, or the first time the owner asks for
    # what needs it.
    when: Literal["setup", "asked"] = "setup"
    files: tuple[File, ...] = ()


def manifest() -> tuple[Download, ...]:
    """Everything Maku downloads to a PC, in the order the installer lists it."""
    text = resources.files("maku").joinpath("downloads.json").read_text(encoding="utf-8")
    items: list[dict[str, Any]] = json.loads(text)["downloads"]
    return tuple(_entry(item) for item in items)


def _entry(item: dict[str, Any]) -> Download:
    """One entry of the list, with its files when it comes as several."""
    listed = {key: value for key, value in item.items() if key != "files"}
    return Download(**listed, files=tuple(File(**each) for each in item.get("files", [])))


type State = Literal["missing", "downloading", "unpacking", "ready", "failed"]


@dataclass(frozen=True)
class Progress:
    state: State
    done: int = 0  # bytes downloaded
    total: int = 0
    problem: str | None = None


class Response(Protocol):
    def read(self, amount: int, /) -> bytes: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
        /,
    ) -> object: ...


type Fetch = Callable[[str], Response]


def _fetch(url: str) -> Response:
    if not url.startswith("https://"):
        raise DownloadError(f"Maku only downloads over HTTPS, and {url} isn't.")
    # The address comes from downloads.json and is HTTPS. urlopen follows GitHub's redirect.
    return urlopen(url, timeout=30)  # noqa: S310


class DownloadError(Exception):
    """A download Maku won't use, with a sentence saying why."""


class _DroppedError(Exception):
    """The connection failed partway through a download."""


class Tools:
    """Maku's downloaded tools: which are ready, fetching the rest, and where each program is."""

    def __init__(
        self, paths: DataPaths, items: tuple[Download, ...] | None = None, fetch: Fetch = _fetch
    ) -> None:
        listed = manifest() if items is None else items
        self._paths = paths
        self._items = {item.id: item for item in listed if item.by == "maku"}
        self._fetch = fetch
        self._lock = threading.Lock()
        self._progress: dict[str, Progress] = {}
        self._threads: dict[str, threading.Thread] = {}

    def status(self) -> list[tuple[Download, Progress]]:
        with self._lock:
            return [(item, self._now(item)) for item in self._items.values()]

    def start(self, tool: str) -> None:
        """Starts downloading a tool unless it's ready or already on its way."""
        item = self._items[tool]  # KeyError: not one of Maku's downloads
        with self._lock:
            running = self._threads.get(tool)
            if (running and running.is_alive()) or self._now(item).state == "ready":
                return
            self._progress[tool] = Progress("downloading", 0, item.size or 0)
            thread = threading.Thread(
                target=self._download, args=(item,), name=f"download-{tool}", daemon=True
            )
            self._threads[tool] = thread
        thread.start()

    def wait(self, tool: str, timeout: float | None = None) -> None:
        if thread := self._threads.get(tool):
            thread.join(timeout)

    def folder(self, tool: str) -> Path | None:
        """Where a tool's files are, once it's ready: `folder("speech-best")`."""
        item = self._items[tool]
        if (override := self._override(item)) is not None:
            return override
        return self._folder(item) if self._installed(item) else None

    def path(self, program: str) -> Path | None:
        """Where one of the tools' programs is, once its tool is ready: `path("ffprobe")`."""
        for item in self._items.values():
            folder = self._override(item)
            if folder is None and self._installed(item):
                folder = self._folder(item)
            name = f"{program}.exe" if os.name == "nt" else program
            if folder is not None and (folder / name).is_file():
                return folder / name
        return None

    def broken(self, tool: str) -> None:
        """A tool that stopped working goes back to missing, so it can be downloaded again.
        A development copy (MAKU_FFMPEG_DIR) is left alone."""
        item = self._items[tool]
        if self._override(item) is not None:
            return
        log.warning("%s stopped working, so it is to be downloaded again", item.name)
        try:
            (self._folder(item) / _MARKER).unlink(missing_ok=True)
        except OSError as error:
            log.warning("Couldn't mark %s to download again: %s", item.name, error)

    def _now(self, item: Download) -> Progress:
        progress = self._progress.get(item.id)
        if progress and progress.state in ("downloading", "unpacking", "failed"):
            return progress
        total = item.size or 0
        if self._override(item) or self._installed(item):
            return Progress("ready", total, total)
        return Progress("missing", 0, total)

    def _folder(self, item: Download) -> Path:
        return self._paths.tools / item.id

    def _installed(self, item: Download) -> bool:
        """The listed build is unpacked, and every file of it is still there."""
        folder = self._folder(item)
        try:
            marker = json.loads((folder / _MARKER).read_text(encoding="utf-8"))
            sha256: object = marker["sha256"]
            files: object = marker["files"]
        except OSError, ValueError, KeyError, TypeError:
            return False
        if sha256 != _identity(item) or not isinstance(files, list):
            return False
        return all((folder / str(name)).is_file() for name in cast(list[object], files))

    @staticmethod
    def _override(item: Download) -> Path | None:
        folder = os.environ.get(f"MAKU_{item.id.upper().replace('-', '_')}_DIR")
        return Path(folder) if folder and Path(folder).is_dir() else None

    def _set(self, item: Download, state: State, done: int = 0, problem: str | None = None) -> None:
        with self._lock:
            self._progress[item.id] = Progress(state, done, item.size or 0, problem)

    def _download(self, item: Download) -> None:
        try:
            if item.files:
                self._fetch_files(item)
            else:
                archive = self._fetch_checked(item)
                try:
                    self._set(item, "unpacking", item.size or 0)
                    self._unpack(item, archive)
                finally:
                    archive.unlink(missing_ok=True)
        except DownloadError as error:
            self._set(item, "failed", problem=str(error))
        except URLError as error:
            self._set(item, "failed", problem=_offline(item, error.reason))
        except _DroppedError as error:
            self._set(item, "failed", problem=_offline(item, f"the connection dropped ({error})"))
        except (TimeoutError, ConnectionError) as error:
            self._set(item, "failed", problem=_offline(item, error.strerror or error))
        except OSError as error:
            self._set(item, "failed", problem=_unsaved(item, error, self._paths.tools))
        except Exception as error:  # whatever it was, the download ends and can be tried again
            log.exception("Downloading %s failed", item.name)
            self._set(
                item, "failed", problem=f"Maku couldn't get {item.name} ({error}). Try again."
            )
        else:
            with self._lock:
                self._progress.pop(item.id, None)
            log.info("Downloaded %s %s", item.name, item.version)

    def _fetch_files(self, item: Download) -> None:
        """A download that comes as several files: each fetched into a folder beside the tools'
        own and checked, then the folder takes the tool's place. A file fetched whole before (a
        download cut short, then started again) is kept."""
        staging = self._paths.tools / f"{item.id}.downloading"
        staging.mkdir(parents=True, exist_ok=True)
        done = 0
        for each in item.files:
            target = staging / each.name
            if not _whole(target, each):
                self._fetch_file(item, each, target, done)
            done += each.size
            self._set(item, "downloading", done)
        marker = {"version": item.version, "sha256": _identity(item), "files": _names(item)}
        (staging / _MARKER).write_text(json.dumps(marker), encoding="utf-8")
        final = self._folder(item)
        shutil.rmtree(final, ignore_errors=True)
        staging.rename(final)

    def _fetch_file(self, item: Download, each: File, target: Path, before: int) -> None:
        part = target.with_name(f"{target.name}.part")
        digest = hashlib.sha256()
        done = 0
        try:
            with self._fetch(each.url) as response, part.open("wb") as out:
                while chunk := _read(response):
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    self._set(item, "downloading", before + done)
            if done != each.size or digest.hexdigest() != each.sha256:
                raise DownloadError(
                    f"The {item.name} download didn't match what Maku expects, so Maku didn't "
                    "use it. Try again; if it happens again, the file online has changed."
                )
            part.replace(target)
        except BaseException:
            part.unlink(missing_ok=True)
            raise

    def _fetch_checked(self, item: Download) -> Path:
        if item.url is None:
            raise DownloadError(f"The list doesn't say where to get {item.name}.")
        self._paths.tools.mkdir(parents=True, exist_ok=True)
        part = self._paths.tools / f"{item.id}.download"
        digest = hashlib.sha256()
        done = 0
        try:
            with self._fetch(item.url) as response, part.open("wb") as out:
                while chunk := _read(response):
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    self._set(item, "downloading", done)
            if done != item.size or digest.hexdigest() != item.sha256:
                raise DownloadError(
                    f"The {item.name} download didn't match what Maku expects, so Maku didn't "
                    "use it. Try again; if it happens again, the file online has changed."
                )
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        return part

    def _unpack(self, item: Download, archive: Path) -> None:
        staging = self._paths.tools / f"{item.id}.unpacking"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        files: list[str] = []  # what was unpacked, so a file that goes missing later is noticed
        try:
            with zipfile.ZipFile(archive) as zipped:
                for member in zipped.infolist():
                    name = member.filename.replace("\\", "/")
                    parts = PurePosixPath(name).parts
                    if ".." in parts or name.startswith("/") or ":" in name:
                        raise DownloadError(
                            f"The {item.name} download holds an unsafe file name, so Maku didn't "
                            "use it."
                        )
                    if member.is_dir() or len(parts) < 3 or parts[1] != item.keep:
                        continue  # only the listed folder, below the archive's top folder
                    target = staging.joinpath(*parts[2:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zipped.open(member) as source, target.open("wb") as out:
                        shutil.copyfileobj(source, out)
                    files.append("/".join(parts[2:]))
            marker = {"version": item.version, "sha256": item.sha256, "files": files}
            (staging / _MARKER).write_text(json.dumps(marker), encoding="utf-8")
            final = self._folder(item)
            shutil.rmtree(final, ignore_errors=True)
            staging.rename(final)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def _identity(item: Download) -> str | None:
    """What says which build of a tool is unpacked: its archive's SHA-256, or its files'."""
    if item.files:
        return hashlib.sha256(" ".join(each.sha256 for each in item.files).encode()).hexdigest()
    return item.sha256


def _names(item: Download) -> list[str]:
    return [each.name for each in item.files]


def _whole(target: Path, each: File) -> bool:
    """A file fetched before, whole and as listed."""
    try:
        if target.stat().st_size != each.size:
            return False
        digest = hashlib.sha256()
        with target.open("rb") as file:
            while chunk := file.read(_CHUNK):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == each.sha256


def _read(response: Response) -> bytes:
    """The next part of a download. A network failure here isn't a full disk."""
    try:
        return response.read(_CHUNK)
    except (OSError, http.client.HTTPException) as error:
        reason = error.strerror if isinstance(error, OSError) and error.strerror else error
        raise _DroppedError(reason) from error


def _offline(item: Download, reason: object) -> str:
    return (
        f"Maku couldn't download {item.name}: {reason}. "
        "Check the internet connection, then try again."
    )


def _unsaved(item: Download, error: OSError, folder: Path) -> str:
    if error.errno == errno.ENOSPC:
        size = f" ({(item.size or 0) / 1e6:.0f} MB)" if item.size else ""
        return (
            f"There isn't enough space for {item.name}{size} in {folder}. "
            "Free some, then try again."
        )
    return f"Maku couldn't save {item.name} in {folder}: {error.strerror or error}."
