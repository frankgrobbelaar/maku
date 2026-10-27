"""Maku's preferences, chosen during setup and changed later in Settings."""

import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import ValidationError

from maku.api.common import ApiModel, Database
from maku.artwork_files import forget_artwork
from maku.care import Care
from maku.reports import write_reports

router = APIRouter()


class Settings(ApiModel):
    # The most a picture comes to: 4K, or 1080p to save room. Nothing is made bigger than it is.
    standard: Literal["4k", "1080p"] = "4k"
    naming: Literal["plex", "jellyfin", "keep"] = "plex"
    set_up: bool = False  # the first-run steps are done
    reports: bool = True  # a gap analysis next to each series with a folder of its own
    # Days copies set aside and converted files' originals are kept, or None: for good.
    quarantine_days: Literal[7, 30, 90] | None = 30
    # What a converted file's original becomes once its result is checked and in place: set
    # aside in quarantine like any copy, or deleted for good (the owner's choice).
    originals: Literal["quarantine", "delete"] = "quarantine"
    artwork: bool = False  # poster and background pictures next to each show, for media servers
    # Days History keeps what Maku did before it's cleared out each day, or None: for good.
    history_days: Literal[7, 30, 90] | None = None
    health_check: bool = True  # every video test-played overnight (maku/checkup.py)


@router.get("/settings")
def settings(conn: Database) -> Settings:
    stored = {
        row["key"]: json.loads(row["value"]) for row in conn.execute("SELECT * FROM settings")
    }
    chosen = Settings()
    for key in Settings.model_fields:
        if key in stored:
            try:
                values = {**chosen.model_dump(by_alias=False), key: stored[key]}
                chosen = Settings.model_validate(values)
            except ValidationError:
                pass  # a value this Maku doesn't know: keep the default
    return chosen


@router.put("/settings")
def save_settings(body: Settings, conn: Database, request: Request) -> Settings:
    """Keeps the owner's choices. Turning the reports off takes them out of the video folders at
    once; turning them on writes them again. So with the pictures next to each show: off, the
    ones Maku wrote go at once; on, Maku's care writes them now."""
    before = settings(conn)
    with conn:
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            [(key, json.dumps(value)) for key, value in body.model_dump(by_alias=False).items()],
        )
    if body.reports != before.reports:
        write_reports(conn, now=datetime.now().astimezone())
    if body.artwork != before.artwork:
        if body.artwork:
            care: Care = request.app.state.care
            care.wake()
        else:
            forget_artwork(conn)
    return settings(conn)
