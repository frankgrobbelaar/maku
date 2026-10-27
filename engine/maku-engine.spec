# PyInstaller recipe for the engine the installer ships: a folder holding
# maku-engine.exe and its own Python, so the PC needs nothing else installed.
#
#   uv run pyinstaller maku-engine.spec --noconfirm   ->   dist/maku-engine/
#
# See docs/stack/pyinstaller.md.
import os
import re
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

a = Analysis(
    ["src/maku/__main__.py"],
    pathex=["src"],
    datas=[
        *copy_metadata("maku"),  # maku.__version__ reads the package's metadata
        ("src/maku/downloads.json", "maku"),  # what Maku downloads on first run
        ("src/maku/assets", "maku/assets"),  # the voice detector, with its licence
    ],
    # Never used at run time, though optional imports would pull them in: setuptools (through
    # distutils) and pytest (anyio's test runner).
    excludes=["setuptools", "_distutils_hack", "distutils", "pkg_resources", "_pytest", "pytest"],
)
# Windows 10 and 11 have the Universal C Runtime built in. Without this, PyInstaller copies it from
# whichever folder on PATH happens to hold it (a JDK's, say), so builds would differ between PCs.
a.binaries = [b for b in a.binaries if not b[0].lower().startswith(("api-ms-win-", "ucrtbase"))]
# Microsoft's Visual C++ runtime, which ONNX Runtime needs, isn't on every PC, so the engine carries
# it: Windows' own copy, which Microsoft's Visual C++ Redistributable installs, never one that
# another program keeps on PATH (ImageMagick's, a JDK's), which could be any version. The notices
# list it as Microsoft's (tools/third_party_notices.py matches the same names).
CPP_RUNTIME = re.compile(
    r"(concrt140|msvcp140(_\w+)?|vccorlib140|vcruntime140(_\w+)?)\.dll", re.IGNORECASE
)
WINDOWS = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32"


def windows_copy(binary):
    name, source, kind = binary
    if not CPP_RUNTIME.fullmatch(name):
        return binary
    if not (WINDOWS / name).is_file():
        raise SystemExit(f"No {WINDOWS / name}: install Microsoft's Visual C++ Redistributable.")
    return name, str(WINDOWS / name), kind


a.binaries = [windows_copy(b) for b in a.binaries]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="maku-engine",
    console=True,  # a console program; the app starts it without a window
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="maku-engine", upx=False)
