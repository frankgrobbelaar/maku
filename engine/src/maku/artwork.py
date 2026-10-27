"""Posters and pictures: downloaded once from TMDB's image server, and kept in the data folder's
`artwork` folder. No other host is ever asked for a picture.
"""

import hashlib
import logging
from contextlib import suppress
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from uuid import uuid4

from maku.config import DataPaths
from maku.tmdb import IMAGES
from maku.web import Send, Service, WebError

log = logging.getLogger(__name__)

POSTER_SIZE = "w342"  # TMDB's poster width that suits a card
_HOSTS = ("image.tmdb.org",)
_KINDS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def poster_address(poster: str | None, size: str = POSTER_SIZE) -> str | None:
    """Where a title's poster is: a TMDB image path becomes its address on the image server, at
    `size`. Anything from another host is refused."""
    if not poster:
        return None
    return _trusted(f"{IMAGES}/{size}{poster}" if poster.startswith("/") else poster)


def large_poster_address(poster: str | None) -> str | None:
    """A poster big enough for a media server: TMDB's at 780 wide."""
    return poster_address(poster, "w780")


def background_address(backdrop: str | None) -> str | None:
    """Where a title's wide background picture is: TMDB's at 1280 wide."""
    if not backdrop:
        return None
    return _trusted(f"{IMAGES}/w1280{backdrop}" if backdrop.startswith("/") else backdrop)


def still_address(still: str | None) -> str | None:
    """Where a picture from an episode is on TMDB's image server, at its own size: TMDB's other
    sizes of one are 300 wide at most, too small across the top of its details."""
    if not still or not still.startswith("/"):
        return None
    return _trusted(f"{IMAGES}/original{still}")


def _trusted(address: str) -> str | None:
    """The address, when it's on TMDB's image server over HTTPS."""
    parts = urlsplit(address)
    host = parts.hostname or ""
    trusted = any(host == known or host.endswith(f".{known}") for known in _HOSTS)
    return address if parts.scheme == "https" and trusted else None


def media_type(path: Path) -> str:
    return _KINDS.get(path.suffix.casefold(), "application/octet-stream")


def poster(paths: DataPaths, source: str | None, transport: Send) -> Path | None:
    """The poster's file, downloaded the first time it's asked for. None when there's none, or
    it can't be fetched now (Maku asks again next time)."""
    return picture(paths, poster_address(source), transport)


def picture(paths: DataPaths, address: str | None, transport: Send) -> Path | None:
    """The picture at an address on TMDB's image server, downloaded the first time it's asked
    for. None when there's none, or it can't be fetched now (Maku asks again next time)."""
    if address is None or _trusted(address) is None:
        return None
    suffix = PurePosixPath(urlsplit(address).path).suffix.casefold()
    if suffix not in _KINDS:
        suffix = ".jpg"
    name = hashlib.sha256(address.encode()).hexdigest()[:24] + suffix
    kept = paths.artwork / name
    if kept.is_file():
        return kept
    try:
        data = Service("Artwork", transport).raw(address)
    except WebError as error:
        log.info("A picture couldn't be fetched (%s): %s", address, error)
        return None
    # Each its own unfinished file, so two asking at once never write the same one.
    partial = kept.with_name(f"{name}.{uuid4().hex[:8]}.partial")
    try:
        paths.artwork.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(data)
        partial.replace(kept)
    except OSError as error:
        with suppress(OSError):
            partial.unlink(missing_ok=True)
        if kept.is_file():  # another asking at the same time kept it first
            return kept
        log.warning("Maku couldn't keep a picture: %s", error)
        return None
    return kept
