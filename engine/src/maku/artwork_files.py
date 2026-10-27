"""Poster and background pictures next to each show and film, for media servers: `poster.jpg`
and `fanart.jpg` in the folder that holds a title's videos and nothing of another title's (where
its gap analysis goes), when the owner turns them on in Settings > Your data. Maku never writes
over a file that's there, and takes away only the pictures it wrote, as it wrote them
(artwork_files keeps which): turned off, they go; a picture the owner changed stays theirs; and
once the folder's videos are matched to another title, Maku's pictures of the old one make way.
A show whose drive isn't connected waits, and a picture the server refuses (gone, say) is asked
for again only a day later.
"""

import logging
import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from maku.artwork import background_address, large_poster_address
from maku.preferences import artwork_wanted
from maku.reports import own_folder
from maku.web import Send, Service, WebError

log = logging.getLogger(__name__)

POSTER, BACKGROUND = "poster.jpg", "fanart.jpg"
_REFUSED_FOR = timedelta(days=1)  # before a picture the server refused is asked for again
_SERVER_BUSY = (408, 429)  # refusals that say "later", not "no"
_lock = threading.Lock()  # a picture going in, or the pictures being taken away: one at a time


def write_artwork(
    conn: sqlite3.Connection,
    transport: Send,
    *,
    now: datetime,
    refused: dict[str, datetime] | None = None,
) -> int:
    """Writes the pictures still missing next to each title with a folder of its own, when the
    owner wants them. Returns how many it wrote. Offline, the rest wait for next time. `refused`
    keeps, from one look to the next, when each picture the server refused may be asked for
    again."""
    if not artwork_wanted(conn):
        return 0
    refused = refused if refused is not None else {}
    roots = [Path(row["path"]) for row in conn.execute("SELECT path FROM folders")]
    titles = conn.execute(
        """SELECT t.id, COALESCE(t.poster_choice, t.poster) AS poster, t.backdrop
           FROM titles AS t
           WHERE EXISTS (SELECT 1 FROM files AS f WHERE f.title_id = t.id AND f.gone_at IS NULL)
           ORDER BY t.id"""
    ).fetchall()
    service = Service("Artwork", transport)
    written = 0
    for title in titles:
        folder = own_folder(conn, title["id"], roots)
        if folder is None or not folder.is_dir():
            continue  # none of its own, or its drive isn't connected
        wanted = (
            (POSTER, large_poster_address(title["poster"])),
            (BACKGROUND, background_address(title["backdrop"])),
        )
        for name, address in wanted:
            target = folder / name
            if not _free(conn, target, title["id"]) or address is None:
                continue  # Maku's from before, or the owner's own; or the title has none
            if refused.get(address, now) > now:
                continue
            try:
                data = service.raw(address)
            except WebError as error:
                if error.status is None or error.status >= 500 or error.status in _SERVER_BUSY:
                    log.info("A picture for a show couldn't be fetched now: %s", error)
                    return written  # offline, or the server's busy: the rest wait for next time
                log.info("A picture for a show was refused (%s): %s", address, error)
                refused[address] = now + _REFUSED_FOR
                continue
            with _lock:
                if not artwork_wanted(conn):
                    return written  # turned off meanwhile: the rest went with it
                if _write(target, data):
                    with conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO artwork_files"
                            " (path, title_id, size, written_at) VALUES (?, ?, ?, ?)",
                            (str(target), title["id"], len(data), now.isoformat()),
                        )
                    written += 1
    return written


def _free(conn: sqlite3.Connection, target: Path, title_id: int) -> bool:
    """Whether a picture of this title can go at `target`: nothing's there, or Maku's own picture
    of another title is, as Maku wrote it (the videos were matched anew since), and it goes."""
    if not target.exists():
        return True
    row = conn.execute(
        "SELECT title_id, size FROM artwork_files WHERE path = ?", (str(target),)
    ).fetchone()
    if row is None or row["title_id"] == title_id:
        return False  # the owner's own, or Maku's of this title already
    with _lock:
        try:
            if target.stat().st_size != row["size"]:
                return False  # changed since: the owner's now
            target.unlink()
        except OSError:
            return False
        with conn:
            conn.execute("DELETE FROM artwork_files WHERE path = ?", (str(target),))
    return True


def forget_artwork(conn: sqlite3.Connection, folders: Iterable[Path] | None = None) -> int:
    """Takes away the pictures Maku wrote (in `folders`, or everywhere), each only if it's still
    as Maku wrote it. Returns how many went."""
    with _lock:
        return _forget(conn, folders)


def _forget(conn: sqlite3.Connection, folders: Iterable[Path] | None) -> int:
    rows = conn.execute("SELECT path, size FROM artwork_files").fetchall()
    within = [folder.resolve() for folder in folders] if folders is not None else None
    gone = 0
    for row in rows:
        path = Path(row["path"])
        if within is not None and path.parent.resolve() not in within:
            continue
        try:  # only a picture named as Maku names them, whatever a damaged record says
            if path.name in (POSTER, BACKGROUND) and path.stat().st_size == row["size"]:
                path.unlink()
                gone += 1
        except OSError:
            pass  # gone already, or can't be removed: either way no longer Maku's to keep
        with conn:
            conn.execute("DELETE FROM artwork_files WHERE path = ?", (row["path"],))
    return gone


def _write(target: Path, data: bytes) -> bool:
    """Writes a picture where no file is, never over one."""
    try:
        with target.open("xb") as picture:
            picture.write(data)
    except FileExistsError:
        return False
    except OSError as error:
        log.warning("Maku couldn't write %s: %s", target, error)
        target.unlink(missing_ok=True)
        return False
    return True
