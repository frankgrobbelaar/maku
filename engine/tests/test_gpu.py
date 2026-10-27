"""Reading the graphics card's load and temperature, with nvidia-smi stood in for."""

import sys
from pathlib import Path

from maku.gpu import Gpu, Reading


def fake(tmp_path: Path, answer: str, code: int = 0) -> list[str]:
    """A stand-in nvidia-smi that answers `answer`, and counts how often it's asked."""
    script = tmp_path / "nvidia_smi.py"
    script.write_text(
        "import sys, pathlib\n"
        f"asked = pathlib.Path({str(tmp_path / 'asked')!r})\n"
        "asked.write_text(str(int(asked.read_text() or 0) + 1) if asked.exists() else '1')\n"
        f"print({answer!r})\n"
        f"sys.exit({code})\n",
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


def test_the_cards_load_and_temperature_are_read(tmp_path: Path):
    assert Gpu(fake(tmp_path, "97, 71")).reading() == Reading(97, 71)


def test_a_reading_is_kept_for_a_few_seconds(tmp_path: Path):
    moment = [0.0]
    gpu = Gpu(fake(tmp_path, "50, 60"), clock=lambda: moment[0])

    gpu.reading()
    gpu.reading()
    moment[0] = 10.0
    gpu.reading()

    assert (tmp_path / "asked").read_text() == "2"


def test_no_nvidia_smi_is_no_reading(tmp_path: Path):
    gpu = Gpu([str(tmp_path / "missing.exe")])

    assert gpu.reading() is None
    assert gpu.reading() is None


def test_an_answer_maku_cant_read_is_no_reading(tmp_path: Path):
    assert Gpu(fake(tmp_path, "[N/A], 40")).reading() is None
    assert Gpu(fake(tmp_path, "", code=9)).reading() is None
