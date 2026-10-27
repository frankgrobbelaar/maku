"""The library: its folders (adding and forgetting them) and what's in it at a glance."""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response, status

from maku.api.common import ApiModel, Database
from maku.core.library import picture_size
from maku.library import FolderError, add_folder, folders, remove_folder

router = APIRouter()


class LibraryFolder(ApiModel):
    id: int
    path: str
    added_at: str
    available: bool  # False while its drive is unplugged
    files: int
    unread: int  # still to read with ffprobe
    problems: int  # files that couldn't be read


class NewFolder(ApiModel):
    path: str


class Library(ApiModel):
    """The whole library at a glance: what Home shows before titles are identified."""

    folders: int
    files: int
    size: int  # bytes
    unread: int
    problems: int
    sd: int
    hd720: int
    hd1080: int
    larger: int


class TitleSpace(ApiModel):
    title_id: int
    name: str
    files: int
    size: int  # bytes


class Converted(ApiModel):
    """What converting has done to the space the library takes."""

    files: int
    before: int  # bytes the originals took
    after: int  # bytes their results take


class Glance(ApiModel):
    """The library in a few numbers: how long it plays, how much of that was watched, what
    converting did to its size, and the titles that take the most room."""

    seconds: float  # how long it all plays
    watched: float  # seconds of it watched
    converted: Converted
    biggest: list[TitleSpace]  # the titles taking the most room, the biggest first
    size: int  # bytes, all of it


BIGGEST = 5  # titles named in "the most room"


@router.get("/folders")
def list_folders(conn: Database) -> list[LibraryFolder]:
    counts = {
        row["folder_id"]: row
        for row in conn.execute(
            """SELECT folder_id, COUNT(*) AS files,
                      COUNT(*) FILTER (WHERE probed_at IS NULL) AS unread,
                      COUNT(*) FILTER (WHERE problem IS NOT NULL) AS problems
               FROM files WHERE gone_at IS NULL GROUP BY folder_id"""
        )
    }
    result: list[LibraryFolder] = []
    for folder in folders(conn):
        count = counts.get(folder.id)
        result.append(
            LibraryFolder(
                id=folder.id,
                path=str(folder.path),
                added_at=folder.added_at,
                available=folder.path.is_dir(),
                files=count["files"] if count else 0,
                unread=count["unread"] if count else 0,
                problems=count["problems"] if count else 0,
            )
        )
    return result


@router.post("/folders", status_code=status.HTTP_201_CREATED)
def new_folder(body: NewFolder, conn: Database) -> LibraryFolder:
    """Adds a folder to the library. Nothing in it changes; the next scan looks inside."""
    if not body.path.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a folder to add.")
    try:
        folder = add_folder(conn, Path(body.path.strip()), now=datetime.now().astimezone())
    except FolderError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    return next(each for each in list_folders(conn) if each.id == folder.id)


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def forget_folder(folder_id: int, conn: Database) -> Response:
    """Takes a folder out of the library. Its files stay exactly where they are. Not while a
    file in it is converting, or made and waiting for another app to let go of its original:
    its result is about to take the original's place."""
    busy = conn.execute(
        """SELECT j.kind FROM jobs AS j JOIN files AS f ON f.id = j.file_id
           WHERE f.folder_id = ?
             AND (j.state IN ('running', 'replacing')
                  OR (j.state = 'queued' AND j.retry_at IS NOT NULL))""",
        (folder_id,),
    ).fetchone()
    if busy is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Maku is making English subtitles for a file in it. Forget the folder once they're "
            "made, or skip it first."
            if busy["kind"] == "subtitles"
            else "A file in it is converting. Forget the folder once that's done, or skip it "
            "first.",
        )
    if not remove_folder(conn, folder_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That folder isn't in your library.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/library/glance")
def glance(conn: Database) -> Glance:
    """The library in a few numbers, for Home."""
    plays = conn.execute(
        """SELECT COALESCE(SUM(f.duration), 0) AS seconds, COALESCE(SUM(f.size), 0) AS size,
                  COALESCE(SUM(CASE WHEN w.watched_at IS NOT NULL THEN f.duration END), 0)
                    AS watched
           FROM files AS f LEFT JOIN watched AS w ON w.file_id = f.id
           WHERE f.gone_at IS NULL"""
    ).fetchone()
    # Each video's latest conversion that's still in place (not put back from History).
    done = conn.execute(
        """SELECT COUNT(*) AS files, COALESCE(SUM(j.source_size), 0) AS before,
                  COALESCE(SUM(j.output_size), 0) AS after
           FROM jobs AS j JOIN files AS f ON f.id = j.file_id
           LEFT JOIN plans AS p ON p.id = j.plan_id
           WHERE j.kind = 'convert' AND j.state = 'done' AND j.problem IS NULL
             AND j.source_size IS NOT NULL AND j.output_size IS NOT NULL
             AND f.gone_at IS NULL AND p.undone_at IS NULL
             AND j.id = (SELECT MAX(id) FROM jobs AS k
                         WHERE k.file_id = j.file_id AND k.kind = 'convert' AND k.state = 'done')"""
    ).fetchone()
    biggest = conn.execute(
        """SELECT t.id, t.name, COUNT(*) AS files, SUM(f.size) AS size
           FROM files AS f JOIN titles AS t ON t.id = f.title_id
           WHERE f.gone_at IS NULL
           GROUP BY t.id ORDER BY size DESC, t.name LIMIT ?""",
        (BIGGEST,),
    ).fetchall()
    return Glance(
        seconds=plays["seconds"],
        watched=plays["watched"],
        converted=Converted(files=done["files"], before=done["before"], after=done["after"]),
        biggest=[
            TitleSpace(title_id=row["id"], name=row["name"], files=row["files"], size=row["size"])
            for row in biggest
        ],
        size=plays["size"],
    )


@router.get("/library")
def library(conn: Database) -> Library:
    sizes = {"sd": 0, "720p": 0, "1080p": 0, "larger": 0, "unknown": 0}
    files = total = unread = problems = 0
    for row in conn.execute(
        "SELECT size, width, height, probed_at, problem FROM files WHERE gone_at IS NULL"
    ):
        files += 1
        total += row["size"]
        unread += row["probed_at"] is None
        problems += row["problem"] is not None
        sizes[picture_size(row["width"], row["height"])] += 1
    return Library(
        folders=len(folders(conn)),
        files=files,
        size=total,
        unread=unread,
        problems=problems,
        sd=sizes["sd"],
        hd720=sizes["720p"],
        hd1080=sizes["1080p"],
        larger=sizes["larger"],
    )
