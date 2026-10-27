"""Settings > Your data > Backups: the nightly backups of Maku's records, one made now, and one
restored, which happens as the engine starts again (the app starts it again right after)."""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from maku import backups
from maku.api.common import ApiModel, Database, Paths

router = APIRouter()


class Backup(ApiModel):
    name: str  # "maku 2026-10-11 0300.db"
    made: str  # local time, to the minute: "2026-10-11T03:00"
    size: int
    before_restoring: bool  # made just before another backup was restored
    from_export: bool  # the database an imported export held
    by_hand: bool  # made when the owner asked ("Back up now")


class Restored(ApiModel):
    name: str  # the backup
    at: str  # when
    problem: str | None  # why it couldn't be restored, if it couldn't


class Backups(ApiModel):
    backups: list[Backup]  # newest first
    restored: Restored | None  # how the last restore went


@router.get("/backups")
def list_backups(conn: Database, paths: Paths) -> Backups:
    last = backups.last_restore(conn)
    return Backups(
        backups=[_backup(backup) for backup in backups.backups(paths)],
        restored=Restored(name=last.name, at=last.at, problem=last.problem) if last else None,
    )


@router.post("/backups")
def back_up_now(paths: Paths) -> Backup:
    """Makes a backup now, checked like the nightly ones (and kept apart from them)."""
    try:
        made = backups.back_up(paths, datetime.now().astimezone(), by_hand=True)
    except backups.BackupError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    return _backup(made)


class ImportRequest(ApiModel):
    path: str  # a Maku export: the zip `maku export` and Settings write


@router.post("/backups/import", status_code=status.HTTP_204_NO_CONTENT)
def import_export(body: ImportRequest, paths: Paths) -> None:
    """Puts an export's records in place as the engine starts again, the way a backup is
    restored: the app starts it again right after asking."""
    try:
        backups.ask_to_import(paths, Path(body.path), datetime.now().astimezone())
    except backups.BackupError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None


@router.post("/backups/{name}/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_backup(name: str, paths: Paths) -> None:
    """Restores a backup as the engine starts again: the app starts it again right after."""
    try:
        backups.ask_to_restore(paths, name)
    except backups.BackupError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None


def _backup(backup: backups.Backup) -> Backup:
    return Backup(
        name=backup.name,
        made=backup.made.isoformat(timespec="minutes"),
        size=backup.size,
        before_restoring=backup.before_restoring,
        from_export=backup.from_export,
        by_hand=backup.by_hand,
    )
