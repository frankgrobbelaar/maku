"""The local HTTP API the app talks to.

Only the app can use it: the engine listens on 127.0.0.1, and every request must
carry the per-launch token the app passes in MAKU_TOKEN. Each feature adds its
routes as an APIRouter in its own module, included below.
"""

import logging
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, closing
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from maku import __version__, changes, db
from maku.api import (
    backups,
    checkup,
    coming,
    convert,
    data,
    files,
    health,
    library,
    player,
    posters,
    records,
    recovery,
    review,
    scan,
    search,
    settings,
    subtitles,
    system,
    tidy,
    titles,
    tmdb,
    tools,
    watched,
)
from maku.backups import restore_asked
from maku.cache import Cache
from maku.care import Care
from maku.catalog import Catalog
from maku.config import DataPaths
from maku.events import Notify
from maku.gpu import Gpu
from maku.pc_check import PcCheck
from maku.player import Player
from maku.queue import Queue, programs_from
from maku.recovery import Recovery, stopped_on_purpose
from maku.recovery import note as note_recovery
from maku.rescue import Damage, damage
from maku.scan import Scanner
from maku.tools import Tools
from maku.watch import Watcher
from maku.web import Send, send

# The app's own pages: the installed app, and the Vite dev server in development.
APP_ORIGINS = ["http://tauri.localhost", "http://localhost:1420"]
LOCAL_HOSTS = ["127.0.0.1", "localhost"]

_bearer = HTTPBearer(auto_error=False)

log = logging.getLogger(__name__)


def create_app(
    token: str,
    paths: DataPaths,
    toolbox: Tools | None = None,
    scanner: Scanner | None = None,
    transport: Send = send,
    *,
    watch: bool = False,
    work: bool = False,
    notify: Notify = lambda _title, _body, link=None: None,
) -> FastAPI:
    """The API, with its parts. Tests pass their own tools, scanner and transport (the
    internet as TMDB sees it). `watch` keeps the library current while the engine
    runs (maku/watch.py), and `work` converts the queue (maku/queue.py): `maku serve` turns
    both on, and passes `notify`, which tells the app what's worth a notification."""
    expected = token.encode()

    def require_token(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> None:
        given = credentials.credentials.encode() if credentials else b""
        if not secrets.compare_digest(given, expected):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Missing or wrong token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def require_records(request: Request) -> None:
        """While Maku's records are damaged, only the way back (and the health check) answers."""
        if request.app.state.damage is not None and not request.url.path.startswith(
            ("/records", "/health")
        ):
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Maku's records are damaged, so it can't do that till they're back.",
            )

    @asynccontextmanager
    async def lifespan(running: FastAPI) -> AsyncGenerator[None]:
        restored = restore_asked(paths, _now())  # a backup chosen, before anything opens it
        on_purpose = stopped_on_purpose(paths)  # the last engine was asked to stop
        found = damage(paths)  # records damaged past use: nothing else can start
        running.state.damage = found
        if found is not None:
            log.error("Maku's records are damaged: %s", found.problem)
            notify("Maku's records are damaged", _way_back(found), link="/")
            yield
            return
        with closing(db.connect(paths.database)) as conn:
            db.migrate(conn)
            moves = changes.recover(conn)  # settle file moves that a crash interrupted
        worker: Queue = running.state.queue
        settled = Recovery()
        if work:
            # A conversion a crash stopped while its result was taking the original's place is
            # finished or undone before any scan looks at the folders.
            settled = worker.recover()
        if not (restored or on_purpose):
            with closing(db.connect(paths.database)) as conn:  # Home tells what a crash left
                note_recovery(conn, replace(settled, at=_now().isoformat(), moves=moves))
        scans: Scanner = running.state.scanner
        scans.recover()  # carry on a scan that an exit or a crash stopped
        catalog: Catalog = running.state.catalog
        watcher = (
            Watcher(paths, scans, transport, now=_now, catalog=catalog, notify=notify)
            if watch
            else None
        )
        running.state.watcher = watcher
        if watcher is not None:
            watcher.start()
        care: Care = running.state.care
        if work:
            pc: PcCheck = running.state.pc
            pc.refresh()  # checks this PC when it hasn't been, or its cards have changed
            worker.start()  # converts what waits
            care.start()  # tonight's backup, and the quarantine cleared out daily
        yield
        playing: Player = running.state.player
        playing.stop()  # the video playing in the window, if one is
        if work:
            care.stop()
            worker.stop()  # the file converting now is first in line next time
        if watcher is not None:
            watcher.stop()

    app = FastAPI(
        title="Maku engine",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.paths = paths
    app.state.damage = None  # Maku's records damaged past use, found as the engine starts
    app.state.rescued = False  # a way back was taken: the app starts the engine again
    app.state.transport = transport
    app.state.tools = toolbox or Tools(paths)
    # One catalogue for the engine: TMDB with the owner's key, its answers kept a week.
    app.state.catalog = Catalog(paths, transport, cache=Cache(paths.cache))
    app.state.scanner = scanner or Scanner(
        paths, app.state.tools, transport=transport, catalog=app.state.catalog
    )
    app.state.watcher = None  # set while it runs
    # What converting runs: Maku's ffmpeg and ffprobe (tests stand in).
    app.state.programs = lambda: programs_from(app.state.tools)
    app.state.queue = Queue(
        paths,
        app.state.scanner,
        lambda: app.state.programs(),
        now=_now,
        notify=notify,
        checking=lambda: app.state.pc.testing() is not None,
    )
    # What this PC can do, checked in the background; converting waits while it's checked.
    app.state.pc = PcCheck(
        paths,
        lambda: app.state.programs(),
        now=_now,
        busy=lambda: app.state.queue.busy(),
        after=lambda: app.state.queue.wake(),
    )
    app.state.gpu = Gpu()
    app.state.player = Player(paths, lambda: _ffmpeg(app.state.tools))
    app.state.care = Care(
        paths,
        app.state.scanner.hold,
        now=_now,
        transport=transport,
        programs=lambda: app.state.programs(),
        notify=notify,
        busy=lambda: app.state.queue.busy(),
    )
    # The middleware added last runs first: CORS answers the webview's preflight
    # checks, then only requests addressed to this PC get through.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=APP_ORIGINS,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=[files.PICTURE_HEADER],
    )
    guarded = [Depends(require_token), Depends(require_records)]
    for part in (
        health,
        tools,
        library,
        scan,
        settings,
        system,
        tmdb,
        titles,
        files,
        watched,
        coming,
        checkup,
        posters,
        search,
        review,
        tidy,
        player,
        convert,
        subtitles,
        data,
        backups,
        recovery,
        records,
    ):
        app.include_router(part.router, dependencies=guarded)
    # A video playing in the window: its <video> can't send the token, so the ticket that opening
    # the video gave is the key to its stream (maku/api/player.py).
    app.include_router(player.streams, dependencies=[Depends(require_records)])
    return app


def _now() -> datetime:
    return datetime.now().astimezone()


def _ffmpeg(toolbox: Tools) -> list[str] | None:
    """Maku's ffmpeg as a command, once it's downloaded."""
    found = toolbox.path("ffmpeg")
    return [str(found)] if found else None


def _way_back(found: Damage) -> str:
    """What a notification says to do about damaged records."""
    if found.backup is None:
        return "Open Maku to start again with new records."
    made = found.backup.made
    return f"Open Maku to restore the backup from {made.day} {made:%B}, {made:%H:%M}."


def openapi_schema() -> dict[str, Any]:
    """The API's OpenAPI schema. It doesn't depend on the token or the data folder."""
    return create_app(secrets.token_hex(), DataPaths(Path())).openapi()
