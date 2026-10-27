"""Reading a video's sound for subtitles, and the voice detector that ships inside Maku. Whisper
itself is a download, so the queue's tests stand in for it."""

import json
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from maku import directml
from maku.core.speech import SAMPLE_RATE
from maku.directml import PROVIDER as DIRECTML
from maku.speech import (
    Detector,
    Listener,
    SpeechError,
    Stopped,
    _session,  # pyright: ignore[reportPrivateUsage]
    out_of_memory,
    sound_of,
)
from tests.converting import FAKE_FFMPEG


def test_a_sound_track_is_read_as_the_models_hear_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MAKU_FAKE_SOUND", "2.5")

    sound = sound_of(FAKE_FFMPEG, tmp_path / "Episode 1.mkv", 1, lambda: False)

    assert sound.dtype == np.float32
    assert len(sound) == 2.5 * SAMPLE_RATE


def test_a_sound_track_that_cant_be_read_says_why(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAKU_FAKE_FAIL", "sound")

    with pytest.raises(SpeechError, match=r"ffmpeg couldn't read its sound \(.*invalid data"):
        sound_of(FAKE_FFMPEG, tmp_path / "Episode 1.mkv", 0, lambda: False)


def test_reading_the_sound_stops_when_asked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAKU_FAKE_SOUND", "120")

    with pytest.raises(Stopped):
        sound_of(FAKE_FFMPEG, tmp_path / "Episode 1.mkv", 0, lambda: True)


def test_the_voice_detector_hears_no_one_in_silence_or_a_hum():
    seconds = np.arange(25 * SAMPLE_RATE, dtype=np.float32) / SAMPLE_RATE
    hum = 0.1 * np.sin(2 * np.pi * 50 * seconds).astype(np.float32)
    detector = Detector()

    assert detector.speech(np.zeros(25 * SAMPLE_RATE, np.float32), lambda: False) == []
    assert detector.speech(hum, lambda: False) == []


def test_the_voice_detector_stops_when_asked():
    with pytest.raises(Stopped):
        Detector().speech(np.zeros(25 * SAMPLE_RATE, np.float32), lambda: True)


class Halves:
    """Stands in for ONNX Runtime loading Whisper's encoder and decoder: the card runs the halves
    named in `card`, and the processor the rest. `loads` keeps what was loaded where."""

    def __init__(self, card: set[str]) -> None:
        self.card = card
        self.loads: list[tuple[str, bool]] = []

    def __call__(self, path: Path, *, graphics: bool) -> SimpleNamespace:
        half = path.name.split("_model")[0]
        self.loads.append((half, graphics))
        providers = ["CPUExecutionProvider"]
        if graphics and half in self.card:
            providers.insert(0, "DmlExecutionProvider")
        port = SimpleNamespace(name="past_key_values.0.decoder.key", type="tensor(float16)")
        return SimpleNamespace(
            get_providers=lambda: providers,
            get_inputs=lambda: [port],
            get_outputs=lambda: [SimpleNamespace(name="logits", type="tensor(float16)")],
        )


def whisper_folder(tmp_path: Path) -> Path:
    files = {
        "config.json": {"num_mel_bins": 80, "decoder_attention_heads": 2, "d_model": 8},
        "generation_config.json": {"eos_token_id": 3, "lang_to_id": {"<|ja|>": 1}},
        "vocab.json": {"a": 0},
    }
    for name, content in files.items():
        (tmp_path / name).write_text(json.dumps(content), encoding="utf-8")
    for half in ("encoder_model", "decoder_model_merged"):
        (tmp_path / f"{half}_fp16.onnx").write_bytes(b"")
    return tmp_path


@pytest.mark.parametrize(
    ("card", "loads"),
    [
        ({"encoder", "decoder"}, [("encoder", True), ("decoder", True)]),
        # The card took the encoder but not the decoder: the encoder goes where the decoder runs.
        ({"encoder"}, [("encoder", True), ("decoder", True), ("encoder", False)]),
        # The card took neither: the decoder isn't tried there.
        (set[str](), [("encoder", True), ("decoder", False)]),
    ],
)
def test_whispers_two_halves_run_in_the_same_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, card: set[str], loads: list[tuple[str, bool]]
):
    detector, halves = Detector(), Halves(card)
    monkeypatch.setattr("maku.speech._session", halves)

    Listener(whisper_folder(tmp_path), detector=detector)

    assert halves.loads == loads


def test_whisper_runs_on_the_processor_when_the_card_hasnt_the_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    detector, halves = Detector(), Halves({"encoder", "decoder"})
    monkeypatch.setattr("maku.speech._session", halves)

    Listener(whisper_folder(tmp_path), detector=detector, graphics=False)

    assert halves.loads == [("encoder", False), ("decoder", False)]


def test_the_processor_loads_whisper_below_the_rewrites_that_break_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """ONNX Runtime's highest level breaks half-precision layer norms on the processor."""
    loaded: list[tuple[int, list[object]]] = []

    class Options:
        graph_optimization_level = 0

    def session(path: str, options: Options, providers: list[object]) -> SimpleNamespace:
        loaded.append((options.graph_optimization_level, providers))
        return SimpleNamespace(get_providers=lambda: ["CPUExecutionProvider"])

    onnxruntime = types.ModuleType("onnxruntime")
    vars(onnxruntime).update(
        disable_telemetry_events=lambda: None,
        SessionOptions=Options,
        GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL=99, ORT_ENABLE_EXTENDED=2),
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL=0),
        InferenceSession=session,
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", onnxruntime)

    _session(tmp_path / "encoder_model_fp16.onnx", graphics=False)
    _session(tmp_path / "encoder_model_fp16.onnx", graphics=True)

    assert loaded == [
        (2, ["CPUExecutionProvider"]),
        (99, [DIRECTML, "CPUExecutionProvider"]),
    ]


def test_a_card_out_of_memory_is_told_apart():
    full = RuntimeError(
        "Exception(3) tid(2b4c) 8007000E Not enough memory resources are available to complete "
        "this operation."
    )

    assert out_of_memory(full)
    assert not out_of_memory(RuntimeError("The GPU device instance has been suspended"))


def test_whisper_takes_turns_on_the_card(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Each window it encodes and each token it writes holds DirectML's lock, a step at a time,
    so the AI model can load and run between them (maku/directml.py)."""
    detector, halves = Detector(), Halves({"encoder", "decoder"})
    monkeypatch.setattr("maku.speech._session", halves)
    listener = Listener(whisper_folder(tmp_path), detector=detector)
    held: list[bool] = []

    class SeenError(Exception):
        pass

    def on(_device: str, _array: object) -> object:
        held.append(_held_here())
        raise SeenError

    def stepped(_self: object, *_args: object) -> tuple[object, dict[str, object]]:
        held.append(_held_here())
        return np.zeros((1, 4), np.float32), {}

    monkeypatch.setattr("maku.speech._on", on)
    monkeypatch.setattr(Listener, "_stepped", stepped)

    with pytest.raises(SeenError):
        listener._encode(np.zeros(SAMPLE_RATE, np.float32))  # pyright: ignore[reportPrivateUsage]
    listener._step([1], cast("Any", None), None)  # pyright: ignore[reportPrivateUsage]

    assert held == [True, True]
    assert not _held_here()  # and let go after


def _held_here() -> bool:
    """Whether DirectML's lock is held: another thread can't take it meanwhile."""
    free: list[bool] = []

    def try_it() -> None:
        taken = directml.LOCK.acquire(blocking=False)
        free.append(taken)
        if taken:
            directml.LOCK.release()

    other = threading.Thread(target=try_it)
    other.start()
    other.join()
    return not free[0]
