"""GET /health: is the engine up, which version is it, and where is its data."""

from contextlib import closing
from typing import Literal

from fastapi import APIRouter, Request

from maku import __version__, db
from maku.api.common import ApiModel, Paths

router = APIRouter()


class Health(ApiModel):
    status: Literal["ok"]
    version: str
    data_dir: str
    schema_version: int  # 0 while Maku's records are damaged


@router.get("/health")
def health(request: Request, paths: Paths) -> Health:
    version = 0
    if request.app.state.damage is None:
        with closing(db.connect(paths.database)) as conn:
            version = db.schema_version(conn)
    return Health(
        status="ok", version=__version__, data_dir=str(paths.root), schema_version=version
    )
