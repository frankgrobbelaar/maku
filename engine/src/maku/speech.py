"""English subtitles made on this PC from a video's own sound (maku/core/speech.py holds the pure
parts): ffmpeg reads the sound track, pyannote's segmentation model finds where someone speaks,
and Whisper hears it on the graphics card (ONNX Runtime with DirectML, maku/directml.py; the
processor when the card can't), translating to English, or writing English down as it's said.

Whisper's models are downloads (downloads.json lists them): Maku fetches one the first time the
owner asks for subtitles at its quality. The voice detector ships inside Maku (maku/assets).

On the graphics card, Whisper's memory of what it has written so far (the decoder's caches)
stays there between tokens, bound in place, and only the next token's scores come back: handed
back and forth through Python, the card runs out of memory.
"""

import importlib
import json
import logging
import subprocess
import threading
from collections import deque
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast

import numpy as np

from maku import directml
from maku.convert import Stopped, start
from maku.core.speech import (
    CHUNK,
    DETECTOR_SECONDS,
    FRAMES,
    MAX_TOKENS,
    SAMPLE_RATE,
    TEMPERATURES,
    Answer,
    Heard,
    Made,
    Report,
    Segment,
    Stop,
    Tokens,
    Vocabulary,
    best_of,
    cues,
    detector_windows,
    kept,
    log_mel,
    mel_filters,
    next_logprobs,
    overlapped,
    pick,
    segments_of,
    speech_likelihood,
    stretches,
    timed,
    verdict,
    whisper_language,
    windows,
)

log = logging.getLogger(__name__)

DETECTOR = Path(__file__).parent / "assets" / "pyannote-segmentation-3.0.onnx"
_DETECTOR_BATCH = 8  # windows the detector hears at once
_READ = 1 << 20

MODELS: dict[str, str] = {"best": "speech-best", "fast": "speech-fast"}  # their downloads


class SpeechError(Exception):
    """Subtitles couldn't be made: why, in words, and what ffmpeg said (`log`) when reading the
    sound failed."""

    def __init__(self, message: str, log: str | None = None) -> None:
        super().__init__(message)
        self.log = log


# What DirectML says when the graphics card's memory runs out (E_OUTOFMEMORY).
_OUT_OF_MEMORY = ("8007000e", "out of memory", "not enough memory")


def out_of_memory(error: BaseException) -> bool:
    """Whether an error is the graphics card running out of memory."""
    said = str(error).casefold()
    return any(each in said for each in _OUT_OF_MEMORY)


class _Value(Protocol):
    """A tensor where a model runs (ONNX Runtime's OrtValue)."""

    def numpy(self) -> np.ndarray: ...


class _Binding(Protocol):
    """Where a run's inputs come from and its outputs go (ONNX Runtime's IOBinding)."""

    def bind_cpu_input(self, name: str, value: np.ndarray, /) -> None: ...

    def bind_ortvalue_input(self, name: str, value: _Value, /) -> None: ...

    def bind_output(self, name: str, device_type: str = "cpu", device_id: int = 0, /) -> None: ...

    def get_outputs(self) -> list[_Value]: ...


class _Port(Protocol):
    """One of a model's inputs or outputs."""

    @property
    def name(self) -> str: ...

    @property
    def type(self) -> str: ...


class _Session(Protocol):
    """A model loaded in ONNX Runtime: the parts of InferenceSession Maku uses."""

    def get_inputs(self) -> list[_Port]: ...

    def get_outputs(self) -> list[_Port]: ...

    def get_providers(self) -> list[str]: ...

    def io_binding(self) -> _Binding: ...

    def run_with_iobinding(self, binding: _Binding, /) -> None: ...

    def run(
        self, outputs: list[str] | None, feeds: dict[str, np.ndarray], /
    ) -> list[np.ndarray]: ...


def sound_of(
    ffmpeg: Sequence[str], video: Path, track: int, stop: Stop, *, rate: int = SAMPLE_RATE
) -> np.ndarray:
    """A sound track of the video (the `track`th, from 0) as the models hear sound: 16 kHz
    (or `rate` samples a second), one channel, as floats."""
    command = [
        *ffmpeg,
        *("-nostdin", "-v", "error", "-i", str(video), "-map", f"0:a:{track}"),
        *("-ac", "1", "-ar", str(rate), "-f", "f32le", "-"),
    ]
    process = start(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    said: deque[str] = deque(maxlen=20)

    def listen() -> None:
        if process.stderr is not None:
            for line in process.stderr:
                said.append(line.decode("utf-8", "replace").rstrip())

    errors = threading.Thread(target=listen, daemon=True)
    errors.start()
    parts: list[bytes] = []
    try:
        if process.stdout is None:
            raise SpeechError("ffmpeg couldn't be started to read its sound.")
        while chunk := process.stdout.read(_READ):
            parts.append(chunk)
            if stop():
                raise Stopped
    except BaseException:
        if process.poll() is None:
            process.kill()  # stopped part way: ffmpeg goes too
        raise
    finally:
        process.wait()  # at the end of its sound, ffmpeg ends of itself
        errors.join(timeout=5)
    if process.returncode != 0:
        why = said[-1] if said else f"it stopped with code {process.returncode}"
        raise SpeechError(f"ffmpeg couldn't read its sound ({why}).", "\n".join(said) or None)
    data = b"".join(parts)
    return np.frombuffer(data[: len(data) // 4 * 4], np.float32)


def _session(path: Path, *, graphics: bool) -> _Session:
    try:
        import onnxruntime as ort  # loaded when first needed: the engine starts without it
    except ImportError as error:
        raise SpeechError(f"Maku couldn't load ONNX Runtime ({error}).") from error
    ort.disable_telemetry_events()  # its Windows builds report use to Microsoft unless told not to
    levels = ort.GraphOptimizationLevel

    def options(level: ort.GraphOptimizationLevel) -> ort.SessionOptions:
        made = ort.SessionOptions()
        made.graph_optimization_level = level
        made.enable_mem_pattern = False  # DirectML asks for both of these
        made.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        return made

    try:
        if graphics:
            try:
                with directml.LOCK:
                    session = ort.InferenceSession(
                        str(path),
                        options(levels.ORT_ENABLE_ALL),
                        providers=[directml.PROVIDER, "CPUExecutionProvider"],
                    )
                return cast(_Session, session)
            except Exception:  # ONNX Runtime raises plain Exceptions: the card can't, so the CPU
                log.warning("The graphics card couldn't load %s; the processor runs it", path.name)
        # On the processor, the highest level's rewrites break Whisper's half-precision layer
        # norms (ONNX Runtime 1.24 won't load it), so the one below: it loads, as quick.
        session = ort.InferenceSession(
            str(path), options(levels.ORT_ENABLE_EXTENDED), providers=["CPUExecutionProvider"]
        )
        return cast(_Session, session)
    except Exception as error:
        raise SpeechError(f"Maku couldn't load the speech model ({error}).") from error


def _on_card(session: _Session) -> bool:
    """Whether a model runs on the graphics card, rather than the processor."""
    return "DmlExecutionProvider" in session.get_providers()


def _on(device: str, array: np.ndarray) -> _Value:
    """An array copied to where a model runs: "dml", the graphics card, or "cpu"."""
    runtime = importlib.import_module("onnxruntime")  # its OrtValue isn't in its type hints
    value = runtime.OrtValue.ortvalue_from_numpy(np.ascontiguousarray(array), device, 0)
    return cast(_Value, value)


def _model_file(folder: Path, part: str) -> Path:
    """The model's encoder or merged decoder in its folder, in whichever precision it came."""
    for name in (f"{part}_fp16.onnx", f"{part}.onnx"):
        if (folder / name).is_file():
            return folder / name
    raise SpeechError(f"The speech model in {folder} is missing its {part.split('_')[0]}.")


class Detector:
    """pyannote's segmentation model on the processor: where someone speaks in a sound."""

    def __init__(self, path: Path = DETECTOR) -> None:
        self._session = _session(path, graphics=False)

    def speech(self, audio: np.ndarray, stop: Stop) -> list[tuple[float, float]]:
        """The stretches of the sound where someone speaks, in seconds."""
        size = DETECTOR_SECONDS * SAMPLE_RATE
        name = self._session.get_inputs()[0].name
        starts = detector_windows(len(audio))
        parts: list[tuple[int, np.ndarray]] = []
        for at in range(0, len(starts), _DETECTOR_BATCH):
            if stop():
                raise Stopped
            batch = starts[at : at + _DETECTOR_BATCH]
            heard = np.zeros((len(batch), 1, size), np.float32)
            for row, first in enumerate(batch):
                piece = audio[first : first + size]
                heard[row, 0, : len(piece)] = piece
            logits = self._session.run(None, {name: heard})[0]
            parts.extend((first, speech_likelihood(logits[row])) for row, first in enumerate(batch))
        return stretches(overlapped(parts, len(audio)))


class Listener:
    """Whisper loaded and ready, with the voice detector: `hear` makes a video's subtitles."""

    def __init__(
        self, folder: Path, detector: Detector | None = None, *, graphics: bool = True
    ) -> None:
        """Whisper from its folder, on the graphics card unless `graphics` is False (a card
        without the memory for it) or the card can't run it: the processor then."""
        try:
            self._config = json.loads((folder / "generation_config.json").read_text("utf-8"))
            model = json.loads((folder / "config.json").read_text("utf-8"))
            vocab: dict[str, int] = json.loads((folder / "vocab.json").read_text("utf-8"))
        except (OSError, ValueError) as error:
            raise SpeechError(f"The speech model's files can't be read ({error}).") from error
        self._words = Vocabulary(
            {index: piece for piece, index in vocab.items()}, int(self._config["eos_token_id"])
        )
        self._filters = mel_filters(int(model["num_mel_bins"]))
        heads = int(model["decoder_attention_heads"])
        encoder = _model_file(folder, "encoder_model")
        self._encoder = _session(encoder, graphics=graphics)
        self._decoder = _session(
            _model_file(folder, "decoder_model_merged"), graphics=_on_card(self._encoder)
        )
        if _on_card(self._encoder) and not _on_card(self._decoder):
            self._encoder = _session(encoder, graphics=False)  # each half where the other runs
        self._detector = detector or Detector()
        self._device = "dml" if _on_card(self._decoder) else "cpu"
        inputs = {each.name: each for each in self._decoder.get_inputs()}
        self._past = [name for name in inputs if name.startswith("past_key_values")]
        self._outputs = [output.name for output in self._decoder.get_outputs()]
        self._float = np.float16 if "float16" in self._encoder.get_inputs()[0].type else np.float32
        kv = np.float16 if any("float16" in inputs[n].type for n in self._past) else np.float32
        self._empty = np.zeros((1, heads, 0, int(model["d_model"]) // heads), kv)
        self._rng = np.random.default_rng(0)
        self._languages = {name.strip("<|>") for name in self._config["lang_to_id"]}  # "ja"

    def hear(self, audio: np.ndarray, language: str | None, *, report: Report, stop: Stop) -> Made:
        """The subtitles for this sound: English, translated from `language` (a track's tag,
        "jpn") or written down as said when it's English; Whisper tells the language when the
        track doesn't."""
        total = len(audio) / SAMPLE_RATE
        report(Heard("listening", 0.0, total))
        speech = self._detector.speech(audio, stop)
        spoken = whisper_language(language, self._languages) if language else None
        found: list[Segment] = []
        for first, last in windows(speech):
            begin = first
            while begin < last - 0.5:
                if stop():
                    raise Stopped
                report(Heard("listening", begin, total))
                sound = audio[round(begin * SAMPLE_RATE) : round(last * SAMPLE_RATE)]
                seconds = min(len(sound) / SAMPLE_RATE, float(CHUNK))
                hidden = self._encode(sound)
                spoken = spoken or self._language(hidden)
                tokens = self._tokens(spoken)
                answer = self._answer(hidden, tokens, seconds, stop)
                if answer is None:
                    break  # no one speaks there, Whisper says
                pieces, heard = segments_of(answer.made, tokens, begin, seconds, self._words.text)
                found.extend(pieces)
                if heard is None:
                    break
                begin += heard
        report(Heard("listening", total, total))
        heard_for = sum(last - first for first, last in speech)
        subtitles = timed(cues(kept(found)))
        return Made(subtitles, spoken or "", spoken != "en", heard_for)

    def _encode(self, sound: np.ndarray) -> _Value:
        """A window of sound as Whisper's encoder hears it, kept where the model runs."""
        spectrum = log_mel(sound, self._filters)[:, :FRAMES]
        with directml.LOCK:  # taking turns on the card (maku/directml.py)
            heard = _on(self._device, spectrum[None].astype(self._float))
            binding = self._encoder.io_binding()
            binding.bind_ortvalue_input(self._encoder.get_inputs()[0].name, heard)
            binding.bind_output(self._encoder.get_outputs()[0].name, self._device, 0)
            self._encoder.run_with_iobinding(binding)
            return binding.get_outputs()[0]

    def _language(self, hidden: _Value) -> str:
        """The language Whisper hears in a window, by its code ("ja")."""
        logits, _ = self._step([int(self._config["decoder_start_token_id"])], hidden, None)
        languages: dict[str, int] = self._config["lang_to_id"]
        best = max(languages.items(), key=lambda item: logits[0, item[1]])
        return best[0].strip("<|>")

    def _tokens(self, language: str) -> Tokens:
        config = self._config
        translating = language != "en"
        return Tokens(
            start=int(config["decoder_start_token_id"]),
            end=int(config["eos_token_id"]),
            no_timestamps=int(config["no_timestamps_token_id"]),
            language=int(config["lang_to_id"][f"<|{language}|>"]),
            task=int(config["task_to_id"]["translate" if translating else "transcribe"]),
            suppress=tuple(int(token) for token in config.get("suppress_tokens", [])),
            translating=translating,
        )

    def _answer(self, hidden: _Value, tokens: Tokens, seconds: float, stop: Stop) -> Answer | None:
        """What Whisper writes for a window: the first answer that will do, from the lowest
        temperature up, else the surest; None when no one speaks there."""
        tried: list[Answer] = []
        for temperature in TEMPERATURES:
            answer = self._sample(hidden, tokens, seconds, temperature, stop)
            match verdict(answer, tokens):
                case "quiet":
                    return None
                case "good":
                    return answer
                case "again":
                    tried.append(answer)
        return best_of(tried)

    def _sample(
        self,
        hidden: _Value,
        tokens: Tokens,
        seconds: float,
        temperature: float,
        stop: Stop,
    ) -> Answer:
        made: list[int] = []
        total = 0.0
        no_speech = 0.0
        ids = [tokens.start, tokens.language, tokens.task]
        cache: dict[str, _Value] | None = None
        for _ in range(MAX_TOKENS):
            if stop():
                raise Stopped
            logits, cache = self._step(ids, hidden, cache)
            if not made and len(ids) > 1:
                first = logits[0].astype(np.float64)
                weights = np.exp(first - first.max())
                no_speech = float(weights[tokens.no_speech] / weights.sum())
            logprobs = next_logprobs(logits[-1], made, tokens, seconds)
            token = pick(logprobs, temperature, self._rng)
            total += float(max(logprobs[token], -30.0))
            if token == tokens.end:
                break
            made.append(token)
            ids = [token]
        return Answer(tuple(made), total / (len(made) + 1), no_speech, self._words.text(made))

    def _step(
        self, ids: list[int], hidden: _Value, cache: dict[str, _Value] | None
    ) -> tuple[np.ndarray, dict[str, _Value]]:
        """One step of the decoder: the scores of what comes after each of `ids`, and its
        caches for the next step. The cross-attention's caches, made on the first step, are
        kept; the decoder's own grow with each token."""
        with directml.LOCK:  # taking turns on the card (maku/directml.py)
            return self._stepped(ids, hidden, cache)

    def _stepped(
        self, ids: list[int], hidden: _Value, cache: dict[str, _Value] | None
    ) -> tuple[np.ndarray, dict[str, _Value]]:
        binding = self._decoder.io_binding()
        binding.bind_cpu_input("input_ids", np.array([ids], np.int64))
        binding.bind_ortvalue_input("encoder_hidden_states", hidden)
        binding.bind_cpu_input("use_cache_branch", np.array([cache is not None]))
        for name in self._past:
            if cache is None:
                binding.bind_cpu_input(name, self._empty)  # unused on the first step
            else:
                binding.bind_ortvalue_input(name, cache[name])
        for name in self._outputs:
            if name == "logits":
                binding.bind_output(name, "cpu")
            else:
                binding.bind_output(name, self._device, 0)
        self._decoder.run_with_iobinding(binding)
        values = dict(zip(self._outputs, binding.get_outputs(), strict=True))
        kept_cache = {
            name.replace("present", "past_key_values"): value
            for name, value in values.items()
            if name.startswith("present") and (cache is None or ".decoder." in name)
        }
        if cache is not None:
            kept_cache.update({name: value for name, value in cache.items() if ".encoder." in name})
        return values["logits"].numpy()[0].astype(np.float32), kept_cache
