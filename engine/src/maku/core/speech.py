"""Making subtitles from a video's sound (maku/speech.py runs the models): where someone speaks,
the sound as Whisper hears it, the rules its answers keep, and how its words become subtitles.
Pure: numpy, and nothing read or written.

pyannote's segmentation model hears 10 seconds at a time and says, about every 17 ms, how likely
it is that someone speaks; it hears voices over music, where Whisper alone would invent lines
and quieter voice detectors hear nothing. The stretches of speech are gathered into windows of
the sound as it is, at most 30 seconds each, and Whisper, OpenAI's speech model, hears each
window as a log-mel spectrogram and answers with tokens: words, and timestamps that pair up
around each stretch of them, counted from the window's start.
"""

import itertools
import re
import zlib
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np

SAMPLE_RATE = 16_000
CHUNK = 30  # seconds Whisper hears at once
N_FFT = 400
HOP = 160
FRAMES = CHUNK * SAMPLE_RATE // HOP  # 3000 spectrogram frames to a chunk
STEP = 0.02  # seconds between timestamp tokens
MAX_TOKENS = 224  # tokens Whisper writes for one chunk, at most
MAX_INITIAL = 50  # the first timestamp comes within a second of the chunk's start
TEMPERATURES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)  # tried in turn while an answer won't do
LINE = 42  # characters to a subtitle line

DETECTOR_SECONDS = 10  # what the voice detector hears at once
DETECTOR_HOP = 5  # seconds between the starts of its windows: each overlaps the next by half
DETECTOR_STEP = 270  # samples between its frames
ONSET = 0.5  # how sure the detector is that someone speaks, for a stretch to start
OFFSET = 0.35  # and below which it ends

SHORTEST = 1.0  # seconds a subtitle stays, at least
LONGEST = 7.0  # and at most
READING = 0.4  # seconds a subtitle stays after the words, for reading, where there's room

# ISO 639-2 codes, as files tag their tracks, to Whisper's.
WHISPER_LANGUAGES = {
    "jpn": "ja",
    "eng": "en",
    "ger": "de",
    "deu": "de",
    "fre": "fr",
    "fra": "fr",
    "spa": "es",
    "ita": "it",
    "por": "pt",
    "rus": "ru",
    "chi": "zh",
    "zho": "zh",
    "kor": "ko",
    "ara": "ar",
    "dut": "nl",
    "nld": "nl",
    "pol": "pl",
    "swe": "sv",
    "tur": "tr",
}

# Lines Whisper is known to make up where there's nothing to hear.
_INVENTED = re.compile(
    r"^(thanks? (you )?for watching|please subscribe|subtitles by|amara\.org|"
    r"see you (in the )?next (time|video))\W*$",
    re.IGNORECASE,
)


type Quality = Literal["best", "fast"]  # Whisper medium, or small
type Stage = Literal["reading", "listening", "writing", "checking"]


@dataclass(frozen=True)
class Heard:
    """How far making a video's subtitles has got: in seconds of the video, for listening."""

    stage: Stage
    done: float
    total: float


type Report = Callable[[Heard], None]
type Stop = Callable[[], bool]


@dataclass(frozen=True)
class Made:
    """A video's subtitles, and what Whisper heard."""

    subtitles: list[Segment]
    language: str  # what the speech was in, as Whisper names it: "ja"
    translated: bool  # into English; else written down as said, in English
    speech: float  # seconds of speech the detector heard


class Hearing(Protocol):
    """Whisper, ready to make the subtitles for a sound (maku/speech.py's Listener)."""

    def hear(
        self, audio: np.ndarray, language: str | None, *, report: Report, stop: Stop
    ) -> Made: ...


def whisper_language(language: str, known: Collection[str]) -> str | None:
    """Whisper's code for a track's language ("jpn" → "ja"; `known` holds the codes it knows),
    or None when it doesn't know it by that name: it tells then which it hears."""
    code = language.casefold().replace("_", "-").split("-")[0]  # "en-US" is "en"
    if len(code) != 2:  # Whisper's codes are two letters
        code = WHISPER_LANGUAGES.get(code, "")
    return code if code in known else None


def speech_likelihood(logits: np.ndarray) -> np.ndarray:
    """How likely it is that someone speaks, for each of the detector's frames, from its answer
    (a row per frame of 7: no one, each of three speakers, and each two of them together)."""
    weights = np.exp(logits - logits.max(axis=1, keepdims=True))
    return 1.0 - weights[:, 0] / weights.sum(axis=1)


def detector_windows(samples: int) -> list[int]:
    """Where each of the detector's windows starts, in samples: every 5 s."""
    return list(range(0, max(samples, 1), DETECTOR_HOP * SAMPLE_RATE))


def overlapped(parts: Sequence[tuple[int, np.ndarray]], samples: int) -> np.ndarray:
    """The detector's windows (where each starts, in samples, and its likelihoods) as one
    likelihood per frame of the whole sound, averaged where windows overlap."""
    total = max(1, samples // DETECTOR_STEP)
    summed = np.zeros(total, np.float32)
    counted = np.zeros(total, np.float32)
    for start, likelihood in parts:
        first = start // DETECTOR_STEP
        count = min(len(likelihood), total - first)
        if count <= 0:
            continue
        summed[first : first + count] += likelihood[:count]
        counted[first : first + count] += 1
    return summed / np.maximum(counted, 1)


def stretches(
    likelihood: np.ndarray,
    *,
    gap: float = 0.3,
    shortest: float = 0.2,
    pad: float = 0.2,
) -> list[tuple[float, float]]:
    """Where someone speaks, in seconds: from where the detector is sure (ONSET) till it's
    unsure (OFFSET), pauses shorter than `gap` closed, blips shorter than `shortest` dropped,
    and `pad` seconds either side."""
    frame = DETECTOR_STEP / SAMPLE_RATE
    found: list[list[float]] = []
    talking = False
    start = 0.0
    for index, value in enumerate(likelihood):
        if not talking and value >= ONSET:
            talking, start = True, index * frame
        elif talking and value < OFFSET:
            talking = False
            found.append([start, index * frame])
    if talking:
        found.append([start, len(likelihood) * frame])
    joined: list[list[float]] = []
    for first, last in found:
        if joined and first - joined[-1][1] < gap:
            joined[-1][1] = last
        else:
            joined.append([first, last])
    padded: list[tuple[float, float]] = []
    for first, last in joined:
        if last - first < shortest:
            continue
        first, last = max(0.0, first - pad), last + pad
        if padded and first <= padded[-1][1]:
            padded[-1] = (padded[-1][0], last)
        else:
            padded.append((first, last))
    return padded


def windows(speech: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """The stretches of speech gathered into windows for Whisper, in seconds of the sound as it
    is: as many in each as fit in 30 s, the pauses between them included; a longer stretch is
    cut into windows of 30 s."""
    found: list[tuple[float, float]] = []
    for first, last in speech:
        if found and last - found[-1][0] <= CHUNK:
            found[-1] = (found[-1][0], last)
            continue
        while last - first > CHUNK:
            found.append((first, first + CHUNK))
            first += CHUNK
        found.append((first, last))
    return found


def mel_filters(n_mels: int) -> np.ndarray:
    """The mel filter bank Whisper was trained with (librosa's, Slaney's scale and areas)."""
    freqs = np.linspace(0, SAMPLE_RATE / 2, N_FFT // 2 + 1)
    f_sp, min_log_hz = 200.0 / 3, 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0

    def to_mel(hz: float) -> float:
        return float(
            min_log_mel + np.log(hz / min_log_hz) / logstep if hz >= min_log_hz else hz / f_sp
        )

    mels = np.linspace(to_mel(0.0), to_mel(SAMPLE_RATE / 2), n_mels + 2)
    points = np.where(
        mels >= min_log_mel, min_log_hz * np.exp(logstep * (mels - min_log_mel)), f_sp * mels
    )
    gaps = np.diff(points)
    ramps = points[:, None] - freqs[None, :]
    weights = np.zeros((n_mels, len(freqs)))
    for i in range(n_mels):
        weights[i] = np.maximum(0, np.minimum(-ramps[i] / gaps[i], ramps[i + 2] / gaps[i + 1]))
    weights *= (2.0 / (points[2 : n_mels + 2] - points[:n_mels]))[:, None]
    return weights.astype(np.float32)


def log_mel(audio: np.ndarray, filters: np.ndarray) -> np.ndarray:
    """The sound as Whisper hears it: its log-mel spectrogram, 100 frames a second, with 30 s of
    silence after it so the last chunk is whole."""
    sound = np.concatenate([audio.astype(np.float32), np.zeros(CHUNK * SAMPLE_RATE, np.float32)])
    window = np.hanning(N_FFT + 1)[:-1].astype(np.float32)  # periodic, as Whisper's
    padded = np.pad(sound, (N_FFT // 2, N_FFT // 2), mode="reflect")
    count = 1 + (len(padded) - N_FFT) // HOP - 1  # Whisper drops the last frame
    out = np.empty((filters.shape[0], count), np.float32)
    step = 20_000  # frames at a time, to keep memory in hand
    for start in range(0, count, step):
        stop = min(start + step, count)
        index = np.arange(N_FFT)[None, :] + HOP * np.arange(start, stop)[:, None]
        power = np.abs(np.fft.rfft(padded[index] * window, axis=1)) ** 2
        out[:, start:stop] = filters @ power.T.astype(np.float32)
    spectrum = np.log10(np.maximum(out, 1e-10))
    spectrum = np.maximum(spectrum, spectrum.max() - 8.0)
    return (spectrum + 4.0) / 4.0


def _byte_map() -> dict[str, int]:
    """GPT-2's byte-level alphabet, reversed: the character each byte is written as, to it."""
    shown = [*range(ord("!"), ord("~") + 1), *range(ord("¡"), ord("¬") + 1), *range(ord("®"), 256)]
    codes = shown[:]
    extra = 0
    for byte in range(256):
        if byte not in shown:
            shown.append(byte)
            codes.append(256 + extra)
            extra += 1
    return {chr(code): byte for byte, code in zip(shown, codes, strict=True)}


_BYTES = _byte_map()


@dataclass(frozen=True)
class Vocabulary:
    """Whisper's tokens as words: each a piece of GPT-2's byte-level alphabet, every byte of the
    text written as a character ("Ġ" for a space)."""

    pieces: Mapping[int, str]  # each token's piece
    end: int  # <|endoftext|>: it and every token after it (timestamps and the like) aren't words

    def text(self, made: Sequence[int]) -> str:
        written = "".join(self.pieces.get(token, "") for token in made if token < self.end)
        return bytes(_BYTES.get(char, 32) for char in written).decode("utf-8", "replace")


@dataclass(frozen=True)
class Tokens:
    """The model's special tokens, as its generation config numbers them."""

    start: int  # <|startoftranscript|>
    end: int  # <|endoftext|>
    no_timestamps: int
    language: int  # the speech's language, <|ja|>
    task: int  # <|translate|> or <|transcribe|>
    suppress: tuple[int, ...]  # tokens never written (symbols that aren't speech)
    translating: bool

    @property
    def timestamp(self) -> int:
        """The first timestamp token, <|0.00|>."""
        return self.no_timestamps + 1

    @property
    def no_speech(self) -> int:
        return self.no_timestamps - 1


def next_logprobs(
    logits: np.ndarray, made: Sequence[int], tokens: Tokens, seconds: float
) -> np.ndarray:
    """How likely each token is to come next, as log-probabilities, once Whisper's rules are
    kept: timestamps come in pairs and never go back or past the `seconds` of sound there are,
    the first comes within a second, and when timestamps together are likelier than any word,
    it's a timestamp."""
    logits = logits.astype(np.float64)
    logits[list(tokens.suppress)] = -np.inf
    if not made:
        logits[[220, tokens.end]] = -np.inf  # a chunk doesn't start with a space, or end at once
    first = tokens.timestamp
    logits[tokens.end + 1 : first] = -np.inf  # its own signs: start, language, task and the like
    logits[first + round(seconds / STEP) + 1 :] = -np.inf
    last_was = len(made) >= 1 and made[-1] >= first
    before_was = len(made) < 2 or made[-2] >= first
    if last_was:
        if before_was:
            logits[first:] = -np.inf  # a pair ended: words, or the end
        else:
            logits[: tokens.end] = -np.inf  # a pair is open: its second timestamp, or the end
    stamps = [token for token in made if token >= first]
    if stamps:
        floor = stamps[-1] if last_was and not before_was else stamps[-1] + 1
        logits[first:floor] = -np.inf
    if not made:
        logits[:first] = -np.inf
        logits[first + MAX_INITIAL + 1 :] = -np.inf
    logprobs = _log_softmax(logits)
    stamped = np.logaddexp.reduce(logprobs[first:])
    if stamped > logprobs[:first].max():
        logprobs[:first] = -np.inf
        logprobs = logprobs - stamped
    return logprobs


def _log_softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max()
    return shifted - np.log(np.exp(shifted).sum())


def pick(logprobs: np.ndarray, temperature: float, rng: np.random.Generator) -> int:
    """The likeliest token, or at a temperature, one drawn by chance as the model weighs them."""
    if temperature == 0:
        return int(np.argmax(logprobs))
    weights = np.exp((logprobs - logprobs.max()) / temperature)
    return int(rng.choice(len(weights), p=weights / weights.sum()))


def repeats_itself(text: str) -> bool:
    """An answer stuck in a loop: text that compresses too well."""
    raw = text.encode("utf-8")
    return len(raw) > 0 and len(raw) / len(zlib.compress(raw)) > 2.4


@dataclass(frozen=True)
class Answer:
    """What Whisper wrote for a window, and how sure it was."""

    made: tuple[int, ...]  # its tokens, words and timestamps, without the end
    average: float  # the average log-probability of its tokens, the end's included
    no_speech: float  # how likely it thought it that no one speaks there
    text: str  # its words


def verdict(answer: Answer, tokens: Tokens) -> Literal["quiet", "good", "again"]:
    """Whether an answer will do: no one speaks there ("quiet"), it's sure enough and doesn't
    loop ("good"), or it's to be tried again at a higher temperature. Translating, Whisper is
    less sure of the words than writing them down, so it takes less certainty."""
    sure = -1.5 if tokens.translating else -1.0
    if answer.no_speech > 0.6 and answer.average < sure:
        return "quiet"
    if answer.average >= sure and not repeats_itself(answer.text):
        return "good"
    return "again"


def best_of(answers: Sequence[Answer]) -> Answer:
    """When no temperature gave an answer that will do: the surest one that doesn't loop, or
    the surest."""
    calm = [answer for answer in answers if not repeats_itself(answer.text)]
    return max(calm or answers, key=lambda answer: answer.average)


@dataclass(frozen=True)
class Segment:
    """Words and when they're said, in seconds."""

    start: float
    end: float
    text: str


def segments_of(
    made: Sequence[int],
    tokens: Tokens,
    offset: float,
    seconds: float,
    text: Callable[[Sequence[int]], str],
) -> tuple[list[Segment], float | None]:
    """An answer as segments (`offset`: when the sound it heard starts, `seconds`: how long it
    is), and where to go on hearing from, in seconds after `offset`: after the last whole pair
    of timestamps when the answer stopped short of the end, or None when it heard it all."""
    first = tokens.timestamp
    stamped = [token >= first for token in made]
    single_end = len(made) >= 2 and not stamped[-2] and stamped[-1]
    cuts = [i + 1 for i in range(len(made) - 1) if stamped[i] and stamped[i + 1]]
    if not cuts:
        stamps = [token for token in made if token >= first]
        end = (stamps[-1] - first) * STEP if stamps and stamps[-1] != first else seconds
        words = text(made).strip()
        return ([Segment(offset, offset + min(end, seconds), words)] if words else []), None
    if single_end:
        cuts.append(len(made))
    found: list[Segment] = []
    last = 0
    for cut in cuts:
        piece = made[last:cut]
        words = text(piece).strip()
        start = offset + (piece[0] - first) * STEP
        end = offset + min((piece[-1] - first) * STEP, seconds)
        if words and end > start:
            found.append(Segment(start, end, words))
        last = cut
    if single_end:
        return found, None
    heard = (made[last - 1] - first) * STEP
    return found, heard if 0 < heard < seconds - 1 else None


def kept(segments: Sequence[Segment]) -> list[Segment]:
    """The segments worth showing: not empty, not a repeat of the one before, not a line Whisper
    makes up from nothing."""
    found: list[Segment] = []
    for segment in segments:
        words = segment.text.strip()
        if not re.search(r"\w", words) or _INVENTED.match(words):
            continue
        if found and found[-1].text == words:
            continue
        found.append(Segment(segment.start, segment.end, words))
    return found


def timed(segments: Sequence[Segment]) -> list[Segment]:
    """Segments as long as subtitles stay: a second at least and seven at most, a little longer
    than the words for reading where the next leaves room, and never over the next."""
    found: list[Segment] = []
    for index, segment in enumerate(segments):
        start = segment.start
        if found and start < found[-1].end:
            start = found[-1].end
        following = segments[index + 1].start if index + 1 < len(segments) else float("inf")
        end = max(segment.end + READING, start + SHORTEST)
        end = min(end, start + LONGEST, max(following, segment.end))
        found.append(Segment(start, max(end, start + 0.1), segment.text))
    return found


def cues(segments: Sequence[Segment]) -> list[Segment]:
    """Segments as subtitles: at most two lines of 42 characters each, as even as they'll go.
    A segment too long for one is shared among as few as hold it, as evenly as the words allow
    (at the end of a sentence or clause, where one is near), each taking its share of the time
    by its length."""
    found: list[Segment] = []
    for segment in segments:
        words = segment.text.split()
        parts = _parts(words)
        sizes = [len(" ".join(part)) for part in parts]
        at = segment.start
        for part, size in zip(parts, sizes, strict=True):
            length = (segment.end - segment.start) * size / max(1, sum(sizes))
            found.append(Segment(at, at + length, "\n".join(_two_lines(part) or [" ".join(part)])))
            at += length
    return found


def _parts(words: list[str]) -> list[list[str]]:
    """The words in as few subtitles as hold them, each part about as long as the others."""
    for count in range(1, len(words) + 1):
        parts = _even(words, count)
        if all(_two_lines(part) is not None for part in parts):
            return parts
    return [[word] for word in words]  # a word longer than a line has a subtitle of its own


def _even(words: list[str], count: int) -> list[list[str]]:
    """The words cut into `count` parts of about the same length, a cut moved to the end of a
    sentence or clause when one is within a few characters."""
    ends: list[int] = []  # where each word ends, counting characters
    at = 0
    for word in words:
        at += len(word) + (1 if ends else 0)
        ends.append(at)
    cuts: list[int] = []
    for share in range(1, count):
        target = at * share / count
        after = cuts[-1] + 1 if cuts else 0
        choices = range(after, len(words) - (count - share))

        def distance(index: int, target: float = target) -> float:
            pause = 8 if words[index][-1] in ".!?,;:…" else 0
            return abs(ends[index] - target) - pause

        cuts.append(min(choices, key=distance))
    bounds = [0, *(cut + 1 for cut in cuts), len(words)]
    return [words[first:last] for first, last in itertools.pairwise(bounds)]


def _two_lines(words: list[str]) -> list[str] | None:
    """The words as one line, or two of about the same length, each at most 42 characters; None
    when they don't fit."""
    text = " ".join(words)
    if len(text) <= LINE:
        return [text]
    best: list[str] | None = None
    for cut in range(1, len(words)):
        first, second = " ".join(words[:cut]), " ".join(words[cut:])
        if len(first) > LINE or len(second) > LINE:
            continue
        if best is None or max(len(first), len(second)) < max(len(best[0]), len(best[1])):
            best = [first, second]
    return best


def srt(subtitles: Sequence[Segment]) -> str:
    """Subtitles as an SRT file's text."""

    def stamp(seconds: float) -> str:
        ms = max(0, round(seconds * 1000))
        return (
            f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
        )

    return "".join(
        f"{number}\r\n{stamp(cue.start)} --> {stamp(cue.end)}\r\n"
        f"{cue.text.replace(chr(10), chr(13) + chr(10))}\r\n\r\n"
        for number, cue in enumerate(subtitles, start=1)
    )
