"""Home's notice after Maku closed unexpectedly (a crash, a power cut): what it settled as it
started again, until the owner has seen it, for a day (maku/recovery.py)."""

from datetime import datetime

from fastapi import APIRouter, status

from maku import recovery
from maku.api.common import ApiModel, Database

router = APIRouter()


class Recovery(ApiModel):
    at: str  # when Maku started again
    restarted: int  # files that were converting: in line again, from their beginning
    finished: int  # results that were taking their original's place: in it now
    put_back: int  # originals put back, their results never in place
    moves: int  # a tidy-up's or a delete's file moves, settled


@router.get("/recovery")
def last_recovery(conn: Database) -> Recovery | None:
    """What Maku settled as it started again after closing unexpectedly, while it's news."""
    found = recovery.last(conn, datetime.now().astimezone())
    return Recovery.model_validate(found.__dict__) if found else None


@router.post("/recovery/seen", status_code=status.HTTP_204_NO_CONTENT)
def recovery_seen(conn: Database) -> None:
    """The owner has seen it: Home doesn't tell it again."""
    recovery.seen(conn)
