"""Maku's records damaged past use (maku/rescue.py): what's wrong, and the way back. While they're
damaged, the engine answers only this and /health; the app starts it again once a way is taken.
"""

import threading
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status

from maku import rescue
from maku.api.common import ApiModel, Paths
from maku.backups import BackupError

router = APIRouter()

_taking = threading.Lock()  # one way back at a time, and only once


class Damage(ApiModel):
    """Maku's records are damaged: what's wrong, and the newest backup that opens."""

    problem: str  # in SQLite's words: "file is not a database"
    bad_read: bool  # the disk couldn't read them: trying again may be all it needs
    backup: str | None  # the backup's name: "maku 2026-10-11 0300.db"
    made: str | None  # when it was made, local time: "2026-10-11T03:00:00"


@router.get("/records")
def records(request: Request) -> Damage | None:
    """Whether Maku's records are damaged, and what can bring them back; null while they're
    fine."""
    found: rescue.Damage | None = request.app.state.damage
    if found is None:
        return None
    backup = found.backup
    return Damage(
        problem=found.problem,
        bad_read=found.bad_read,
        backup=backup.name if backup else None,
        made=backup.made.isoformat() if backup else None,
    )


@router.post("/records/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_records(request: Request, paths: Paths) -> None:
    """Restores the newest backup that opens over the damaged records, which are kept beside it
    as they are. The app starts the engine again right after."""
    with _taking:
        _still_damaged(request)
        try:
            rescue.restore_newest(paths, datetime.now().astimezone())
        except BackupError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
        request.app.state.rescued = True


@router.post("/records/new", status_code=status.HTTP_204_NO_CONTENT)
def new_records(request: Request, paths: Paths) -> None:
    """Sets the damaged records aside as they are, so Maku starts again with new ones, as on its
    first day. The app starts the engine again right after."""
    with _taking:
        _still_damaged(request)
        try:
            rescue.start_afresh(paths, datetime.now().astimezone())
        except BackupError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
        request.app.state.rescued = True


def _still_damaged(request: Request) -> None:
    if request.app.state.damage is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Maku's records aren't damaged. A backup can be restored from Settings.",
        )
    if request.app.state.rescued:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Maku has its records back: it's starting again."
        )
