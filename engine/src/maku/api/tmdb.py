"""TMDB's key: whether Maku has one, and adding or removing it. A key is kept only once TMDB has
accepted it."""

import sqlite3

from fastapi import APIRouter, HTTPException, Request, status

from maku import credentials
from maku.api.common import ApiModel, Database, Paths, Web, scan_soon
from maku.config import DataPaths
from maku.tmdb import Tmdb
from maku.web import WebError

router = APIRouter()


class TmdbStatus(ApiModel):
    connected: bool
    key_end: str | None  # the key's last four characters, to tell which key it is


class NewKey(ApiModel):
    key: str


def _status(paths: DataPaths) -> TmdbStatus:
    key = credentials.load(paths, "tmdb")
    return TmdbStatus(connected=key is not None, key_end=key[-4:] if key else None)


@router.get("/tmdb")
def tmdb(paths: Paths) -> TmdbStatus:
    """Whether Maku has a TMDB key, for episode lists, titles and artwork."""
    return _status(paths)


@router.put("/tmdb")
def connect_tmdb(
    body: NewKey, request: Request, paths: Paths, conn: Database, web: Web
) -> TmdbStatus:
    """Checks the key with TMDB, then keeps it on this PC. The videos waiting for it are then
    looked up, at a scan; in Setup none has been read yet, so none starts."""
    key = body.key.strip()
    if not key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _WHERE)
    try:
        Tmdb(key, web).check()
    except WebError as error:
        if error.status in (401, 403):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"TMDB didn't accept this key. {_WHERE}"
            ) from None
        if error.status is None:
            reason = f"{error} The key isn't saved yet: try again when you're online."
        else:
            reason = (
                f"TMDB couldn't check the key just now ({error.status}). "
                "The key isn't saved yet: try again in a moment."
            )
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, reason) from None
    credentials.save(paths, "tmdb", key)
    if _waiting_for_a_key(conn):
        scan_soon(request)
    return _status(paths)


@router.delete("/tmdb")
def disconnect_tmdb(paths: Paths) -> TmdbStatus:
    """Forgets the key. Titles Maku already looked up stay."""
    credentials.forget(paths, "tmdb")
    return _status(paths)


def _waiting_for_a_key(conn: sqlite3.Connection) -> bool:
    """Whether a video has been read but not looked up, as happens while there's no key."""
    row = conn.execute(
        """SELECT 1 FROM files
           WHERE gone_at IS NULL AND probed_at IS NOT NULL AND identified_at IS NULL
             AND pinned = 0
           LIMIT 1"""
    ).fetchone()
    return row is not None


_WHERE = (
    "Copy the API Read Access Token from your TMDB account (themoviedb.org, Settings, API), "
    "then paste it here."
)
