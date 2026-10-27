"""The tools Maku downloads (downloads.json): how each one is, and fetching it. ffmpeg comes on
first run; a speech model the first time the owner makes subtitles at its quality."""

from typing import Literal

from fastapi import APIRouter, HTTPException, status

from maku.api.common import ApiModel, Toolbox
from maku.tools import Download, Progress, State

router = APIRouter()


class Tool(ApiModel):
    id: str
    name: str
    version: str
    purpose: str
    licence: str
    size: int
    # Fetched on the setup's Tools step, or the first time the owner asks for what needs it.
    when: Literal["setup", "asked"]
    state: State
    done: int  # bytes downloaded so far
    problem: str | None


def _tool(item: Download, progress: Progress) -> Tool:
    return Tool(
        id=item.id,
        name=item.name,
        version=item.version,
        purpose=item.purpose,
        licence=item.licence,
        size=item.size or 0,
        when=item.when,
        state=progress.state,
        done=progress.done,
        problem=progress.problem,
    )


@router.get("/tools")
def tools(toolbox: Toolbox) -> list[Tool]:
    """What Maku downloads to work with, and whether each is ready."""
    return [_tool(item, progress) for item, progress in toolbox.status()]


@router.post("/tools/{tool_id}/download", status_code=status.HTTP_202_ACCEPTED)
def download(tool_id: str, toolbox: Toolbox) -> Tool:
    """Starts downloading a tool, unless it's ready or already on its way."""
    try:
        toolbox.start(tool_id)
    except KeyError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Maku doesn't download anything called {tool_id}."
        ) from None
    return next(_tool(item, progress) for item, progress in toolbox.status() if item.id == tool_id)
