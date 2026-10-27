"""What every API module shares: the payload base class and the dependencies."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from maku import db
from maku.catalog import Catalog
from maku.config import DataPaths
from maku.scan import ScanBusyError, Scanner
from maku.tools import Tools
from maku.watch import Watcher
from maku.web import Send


class ApiModel(BaseModel):
    """Base for everything the API sends and receives: snake_case here, camelCase in JSON."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        serialize_by_alias=True,
    )


def scan_soon(request: Request) -> None:
    """Scans the library now or, while a scan runs, has the watcher start one once it's done. A
    paused scan sees to it when the owner resumes it."""
    scanner: Scanner = request.app.state.scanner
    if scanner.status().state == "paused":
        return
    try:
        scanner.start()
    except ScanBusyError:
        watcher: Watcher | None = request.app.state.watcher
        if watcher is not None:
            watcher.notice()


def _paths(request: Request) -> DataPaths:
    paths: DataPaths = request.app.state.paths
    return paths


def _database(paths: Annotated[DataPaths, Depends(_paths)]) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(paths.database)) as conn:
        yield conn


def _toolbox(request: Request) -> Tools:
    toolbox: Tools = request.app.state.tools
    return toolbox


def _scanner(request: Request) -> Scanner:
    scanner: Scanner = request.app.state.scanner
    return scanner


def _transport(request: Request) -> Send:
    transport: Send = request.app.state.transport
    return transport


def _catalog(request: Request) -> Catalog:
    catalog: Catalog = request.app.state.catalog
    return catalog


# Use these as parameter types in routes, e.g. `def route(conn: Database) -> ...`.
Paths = Annotated[DataPaths, Depends(_paths)]
Database = Annotated[sqlite3.Connection, Depends(_database)]
Toolbox = Annotated[Tools, Depends(_toolbox)]
Scans = Annotated[Scanner, Depends(_scanner)]
Web = Annotated[Send, Depends(_transport)]  # how Maku reaches TMDB
CatalogClient = Annotated[Catalog, Depends(_catalog)]  # the engine's one, sharing kept answers
