"""Settings > Your data: where Maku keeps its data and how big each part is, moving it to
another drive, and the export."""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from maku import data
from maku.api.common import ApiModel, Database, Paths
from maku.export import export_data
from maku.relocate import MoveError, ask_to_move, last_move

router = APIRouter()


class Quarantined(ApiModel):
    folder: str  # D:\Maku quarantine
    bytes: int
    files: int


class Moved(ApiModel):
    source: str  # the folder the data left
    target: str  # the folder it went to, or was to go to
    at: str
    problem: str | None  # why it stayed, if it did


class DataSizes(ApiModel):
    folder: str  # the data folder
    database: int
    artwork: int
    cache: int  # answers from TMDB, stills and comparison frames
    logs: int
    backups: int
    tools: int
    quarantine: list[Quarantined]  # on each drive the library is on
    moved: Moved | None  # how the last move to another folder went


class MoveRequest(ApiModel):
    folder: str  # where Maku's data goes: an empty or new folder


class ExportRequest(ApiModel):
    folder: str  # where the zip goes


class Exported(ApiModel):
    path: str
    size: int


@router.get("/data")
def your_data(conn: Database, paths: Paths) -> DataSizes:
    """How big each part of Maku's data is, and the quarantine on each drive."""
    folders = [Path(row["path"]) for row in conn.execute("SELECT path FROM folders")]
    found = data.sizes(paths, folders)
    return DataSizes(
        folder=str(found.folder),
        database=found.database,
        artwork=found.artwork,
        cache=found.cache,
        logs=found.logs,
        backups=found.backups,
        tools=found.tools,
        quarantine=[
            Quarantined(folder=str(q.folder), bytes=q.bytes, files=q.files)
            for q in found.quarantine
        ],
        moved=Moved.model_validate(last.__dict__) if (last := last_move(conn)) else None,
    )


@router.post("/data/move", status_code=status.HTTP_204_NO_CONTENT)
def move_data(body: MoveRequest, paths: Paths) -> None:
    """Moves Maku's data to another folder as the engine starts again: the app starts it again
    right after asking."""
    try:
        ask_to_move(paths, Path(body.folder))
    except MoveError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None


@router.post("/export")
def export(body: ExportRequest, paths: Paths) -> Exported:
    """Writes the export zip (the database, settings, file changes and a manifest) into a
    folder, never over another file."""
    try:
        written = export_data(paths, Path(body.folder), now=datetime.now().astimezone())
    except OSError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Maku couldn't write the export there: {error.strerror or error}.",
        ) from None
    if written is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Maku has no data to export yet.")
    return Exported(path=str(written), size=written.stat().st_size)
