"""Maku's command line. The app runs `maku serve`; the uninstaller runs `maku export`; `maku
subtitles` makes one video's English subtitles, to try the speech models out."""

import json
import logging
import os
import socket
import sys
import threading
import time
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from maku import __version__, events
from maku.api import create_app, openapi_schema
from maku.config import DataPaths
from maku.core.speech import SAMPLE_RATE, srt
from maku.directml import runs
from maku.export import export_data
from maku.player import Player
from maku.recovery import asked_to_stop
from maku.relocate import move_asked
from maku.speech import MODELS, Listener, SpeechError, sound_of
from maku.system import end_programs_with_engine
from maku.tools import Tools

app = typer.Typer(help="Maku's engine.", no_args_is_help=True, add_completion=False)


@app.command()
def version() -> None:
    """Print the engine's version."""
    typer.echo(__version__)


@app.command()
def serve(
    port: Annotated[int, typer.Option(help="Port on 127.0.0.1; 0 picks a free one.")] = 0,
    watch_stdin: Annotated[
        bool, typer.Option(help="Stop when stdin closes. The app holds it open while it runs.")
    ] = False,
) -> None:
    """Run the local API for the Maku app.

    Prints one JSON line, {"event": "ready", "port": N}, once it accepts connections.
    """
    token = os.environ.get("MAKU_TOKEN")
    if not token:
        typer.echo(
            "MAKU_TOKEN is not set. The Maku app sets it when it starts the engine.", err=True
        )
        raise typer.Exit(2)
    home = DataPaths.home()
    # Moved to another drive, if the owner asked, before anything opens a file there.
    paths = move_asked(home, datetime.now().astimezone())
    if paths.root != home and not paths.root.is_dir():
        missing = f"Maku's data is in {paths.root}, which isn't there."
        typer.echo(f"{missing} Connect its drive, then try again.", err=True)
        raise typer.Exit(1)
    _log_to_file(paths)
    end_programs_with_engine()  # no ffmpeg it starts outlives it, however it ends

    sock = socket.socket()
    sock.bind(("127.0.0.1", port))
    sock.listen()  # early requests wait in the queue until the server is up
    # While it runs, the engine keeps the library current and converts the queue.
    app = create_app(token, paths, watch=True, work=True, notify=events.notify)
    # A stop waits this long for open answers to end (a video playing), then ends them, so
    # Maku's care and queue stop cleanly before the app's patience runs out.
    config = uvicorn.Config(app, log_config=None, access_log=False, timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    if watch_stdin:
        stop = threading.Thread(
            target=stop_when_stdin_closes, args=(server, paths, app.state.player), daemon=True
        )
        stop.start()
    typer.echo(json.dumps({"event": "ready", "port": sock.getsockname()[1]}))
    server.run(sockets=[sock])  # one that can't start (its records damaged) ends with 3


@app.command()
def export(folder: Annotated[Path, typer.Argument(help="Folder to write the zip into.")]) -> None:
    """Export everything Maku knows to one zip in FOLDER."""
    try:
        archive = export_data(DataPaths.default(), folder)
    except Exception as error:
        typer.echo(f"The export failed: {error}", err=True)
        raise typer.Exit(1) from error
    if archive is None:
        typer.echo("Maku has no data yet, so there is nothing to export.")
    else:
        typer.echo(f"Saved Maku's data to {archive}")


@app.command()
def subtitles(
    video: Annotated[Path, typer.Argument(help="The video to hear.")],
    out: Annotated[Path, typer.Argument(help="The SRT file to write.")],
    quality: Annotated[str, typer.Option(help="best or fast.")] = "best",
    track: Annotated[int, typer.Option(help="Its sound track to hear, from 0.")] = 0,
    language: Annotated[
        str, typer.Option(help="What it's spoken in, as files tag it (jpn). Whisper tells if not.")
    ] = "",
) -> None:
    """Make English subtitles for VIDEO from its sound, into OUT, as the queue makes them: with
    Maku's ffmpeg and speech model, which must be downloaded already."""
    if quality not in MODELS:
        typer.echo("The quality is best or fast.", err=True)
        raise typer.Exit(2)
    tools = Tools(DataPaths.default())
    ffmpeg, model = tools.path("ffmpeg"), tools.folder(MODELS[quality])
    if ffmpeg is None or model is None:
        typer.echo("Maku needs ffmpeg and its speech model downloaded first.", err=True)
        raise typer.Exit(1)
    began = time.monotonic()
    try:
        sound = sound_of([str(ffmpeg)], video, track, lambda: False)
        made = Listener(model).hear(
            sound, language or None, report=lambda _heard: None, stop=lambda: False
        )
    except SpeechError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    out.write_text(srt(made.subtitles), encoding="utf-8", newline="")
    typer.echo(
        f"{len(made.subtitles)} subtitles from {made.speech:.0f} s of speech in "
        f"{len(sound) / SAMPLE_RATE:.0f} s ({made.language}), in {time.monotonic() - began:.0f} s"
    )


@app.command(name="check-directml", hidden=True)
def check_directml() -> None:
    """Whether DirectML runs on this PC's graphics card, as English subtitles at Best want: one
    JSON line. The PC check runs this in a process of its own, so a graphics driver that fails
    takes only it."""
    typer.echo(json.dumps({"runs": runs()}))


@app.command()
def openapi(path: Annotated[Path, typer.Argument(help="Where to write the schema.")]) -> None:
    """Write the API's OpenAPI schema: the contract the app's engine types follow."""
    path.write_text(json.dumps(openapi_schema(), indent=2) + "\n", encoding="utf-8", newline="\n")


def stop_when_stdin_closes(server: uvicorn.Server, paths: DataPaths, player: Player) -> None:
    """Stops the engine once the app exits and its end of the pipe closes, noting the stop was
    asked for: the app may end the engine before it's done. A video playing stops first: its
    stream would otherwise hold the stop up. Read straight from the pipe, with no buffer
    between: Python can't end cleanly while a thread holds one."""
    stdin = sys.stdin.fileno()
    while os.read(stdin, 4096):
        pass
    asked_to_stop(paths)
    player.stop()
    server.should_exit = True


def _log_to_file(paths: DataPaths) -> None:
    paths.logs.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        paths.logs / "engine.log", when="midnight", backupCount=30, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
