"""What the engine asks of Windows: programs it starts never outlive it."""

import ctypes
import subprocess
import sys
from pathlib import Path

import pytest

from maku.system import in_use, on_network

# A stand-in engine: ends its programs with it, starts one that would run a minute, and says
# whether that's so and which program it started.
ENGINE = """
import subprocess, sys, time
from maku.system import end_programs_with_engine
print(end_programs_with_engine(), flush=True)
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print(child.pid, flush=True)
time.sleep(60)
"""
_SYNCHRONIZE = 0x0010_0000


@pytest.mark.skipif(sys.platform != "win32", reason="a Windows job object")
def test_programs_the_engine_starts_end_with_it():
    engine = subprocess.Popen([sys.executable, "-c", ENGINE], stdout=subprocess.PIPE, text=True)
    assert engine.stdout is not None
    assert engine.stdout.readline().strip() == "True"
    child = int(engine.stdout.readline())

    engine.kill()  # as the app ends an engine that won't stop, or a crash
    engine.wait()

    assert _ends(child, within=10)


def _ends(pid: int, *, within: float) -> bool:
    """Whether the program `pid` ends within that many seconds (or has ended)."""
    if sys.platform != "win32":
        return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel.OpenProcess(_SYNCHRONIZE, 0, pid)
    if not handle:
        return True  # gone already
    try:
        return kernel.WaitForSingleObject(handle, int(within * 1000)) == 0  # it ended
    finally:
        kernel.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' sharing rules")
def test_a_file_another_program_has_open_is_in_use(tmp_path: Path):
    video = tmp_path / "Glass Orchard - 03.mkv"
    video.write_bytes(b"an episode")

    assert in_use(video) is False
    with video.open("rb"):  # as a player holds it: reading, and moving it refused
        assert in_use(video) is True
    assert in_use(video) is False
    assert in_use(tmp_path / "not there.mkv") is False


def test_a_network_share_is_on_another_computer(tmp_path: Path):
    assert on_network(Path(r"\\nas\videos\Maku data"))
    assert not on_network(tmp_path)
