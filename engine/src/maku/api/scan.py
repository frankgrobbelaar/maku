"""The scan: how the latest one is going, and starting, pausing and resuming it."""

from fastapi import APIRouter, HTTPException, status

from maku.api.common import ApiModel, Scans
from maku.scan import MovingFilesError, ScanBusyError, ScanStatus, Stage, State

router = APIRouter()


class Scan(ApiModel):
    state: State
    stage: Stage | None
    started_at: str | None
    finished_at: str | None
    found: int
    to_read: int
    read: int
    problems: int
    current: str | None
    seconds_left: float | None
    unavailable: list[str]
    problem: str | None
    titles: int  # series and films identified in the library
    waiting: int  # files that need the owner to say which series or film they are
    note: str | None  # what the scan couldn't do, though it finished
    mixed: int  # folders holding more than one series or film
    added: int | None  # videos this scan found new; None for a scan from before Maku counted
    gone: int | None  # videos this scan found gone


def _scan(now: ScanStatus) -> Scan:
    return Scan(
        state=now.state,
        stage=now.stage,
        started_at=now.started_at,
        finished_at=now.finished_at,
        found=now.found,
        to_read=now.to_read,
        read=now.read,
        problems=now.problems,
        current=now.current,
        seconds_left=now.seconds_left,
        unavailable=list(now.unavailable),
        problem=now.problem,
        titles=now.titles,
        waiting=now.waiting,
        note=now.note,
        mixed=now.mixed,
        added=now.added,
        gone=now.gone,
    )


@router.get("/scan")
def scan(scans: Scans) -> Scan:
    return _scan(scans.status())


@router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
def start_scan(scans: Scans) -> Scan:
    """Starts scanning every library folder. Nothing in them changes."""
    try:
        return _scan(scans.start())
    except MovingFilesError as busy:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{busy} {_ONCE_MOVED}") from None
    except ScanBusyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "A scan is already running.") from None


@router.post("/scan/pause", status_code=status.HTTP_202_ACCEPTED)
def pause_scan(scans: Scans) -> Scan:
    """Stops the scan after the file it's on; resuming carries on from there."""
    scans.pause()
    return _scan(scans.status())


@router.post("/scan/resume", status_code=status.HTTP_202_ACCEPTED)
def resume_scan(scans: Scans) -> Scan:
    try:
        return _scan(scans.resume())
    except MovingFilesError as busy:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{busy} {_ONCE_MOVED}") from None


_ONCE_MOVED = "Scan once they're in place."
