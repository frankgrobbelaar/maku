"""Runs the command line for `python -m maku` and the bundled maku-engine.exe."""

from maku.cli import app

if __name__ == "__main__":
    app(prog_name="maku")
