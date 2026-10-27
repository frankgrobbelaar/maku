"""Maku's engine: everything except the window.

The desktop app starts the engine as a local process and talks to it over HTTP.
See docs/architecture.md for how the parts fit together.
"""

from importlib.metadata import version

__version__ = version("maku")
