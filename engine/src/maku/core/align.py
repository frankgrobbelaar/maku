"""Lining two copies of an episode up by their sound (maku/merge.py reads it): how far one runs
ahead of the other, and whether they're the same cut at all. Pure: numpy.

Two copies rarely start at the same moment: one has a few seconds of logos, or its studio card
cut. Their sound is compared as it changes over time (its loudness rising and falling, frame to
frame), which two copies share whatever their mix or language, and the offset is where the two
are most alike. The same offset must hold at the start, the middle and the end, else they aren't
the same cut (a scene cut, or a copy running at another speed), and English lined up at the start
would drift.
"""

from dataclasses import dataclass

import numpy as np

RATE = 8_000  # samples a second the sound is read at
FRAME = 0.01  # seconds of sound to a frame of its envelope: 100 a second
MOST = 120.0  # seconds one copy may run ahead of the other
PIECE = 90.0  # seconds of the episode each check hears
AGREE = 0.08  # seconds the offsets heard at the start, middle and end may differ by
SURE = 0.25  # how alike the two have to be at the offset, from 0 to 1


@dataclass(frozen=True)
class Lined:
    """Two copies lined up: how many seconds later the other's sound runs than ours (negative:
    earlier), how alike they are there, and whether they're the same cut."""

    offset: float
    likeness: float
    same: bool
    why: str | None  # what tells them apart, when they aren't the same cut


def envelope(sound: np.ndarray, rate: int = RATE) -> np.ndarray:
    """How the sound changes over time, 100 frames a second: its loudness, frame to frame,
    as rises and falls of equal weight (what two copies share whatever their mix)."""
    size = round(rate * FRAME)
    count = len(sound) // size
    if count < 2:  # there's no change to see in less
        return np.zeros(0, np.float32)
    frames = sound[: count * size].astype(np.float64).reshape(count, size)
    loudness = np.log10(np.square(frames).mean(axis=1) + 1e-10)
    change = np.diff(loudness, prepend=loudness[0])
    spread = change.std()
    return ((change - change.mean()) / (spread if spread > 0 else 1.0)).astype(np.float32)


def best_offset(ours: np.ndarray, theirs: np.ndarray, most: float = MOST) -> tuple[float, float]:
    """Where the two envelopes are most alike: how many seconds later theirs runs than ours, at
    most `most` either way, and how alike they are there (0 to 1)."""
    if len(ours) == 0 or len(theirs) == 0:
        return 0.0, 0.0
    size = 1 << (len(ours) + len(theirs)).bit_length()
    alike = np.fft.irfft(np.fft.rfft(theirs, size) * np.conj(np.fft.rfft(ours, size)), size)
    reach = min(round(most / FRAME), size // 2 - 1)
    lags = np.concatenate([np.arange(0, reach + 1), np.arange(-reach, 0)])
    values = np.concatenate([alike[: reach + 1], alike[size - reach :]])
    # Each lag's sum covers only the frames both have there: weigh it by their number.
    overlap = np.array(
        [max(1, min(len(ours), len(theirs) - lag) - max(0, -lag)) for lag in lags], np.float64
    )
    scores = values / overlap
    best = int(np.argmax(scores))
    return float(lags[best] * FRAME), float(np.clip(scores[best], 0.0, 1.0))


def line_up(ours: np.ndarray, theirs: np.ndarray) -> Lined:
    """Two copies' envelopes lined up: the offset over all of it, checked again at the start,
    the middle and the end of ours."""
    offset, likeness = best_offset(ours, theirs)
    if likeness < SURE:
        return Lined(offset, likeness, False, "Their sound isn't alike enough to line them up.")
    piece = round(PIECE / FRAME)
    shift = round(offset / FRAME)
    heard: list[float] = []
    for where in (0.1, 0.5, 0.85):
        start = max(0, min(len(ours) - piece, round(len(ours) * where)))
        mine = ours[start : start + piece]
        # The same stretch of theirs, with room either side to find it again.
        first = max(0, start + shift - round(5 / FRAME))
        other = theirs[first : first + piece + round(10 / FRAME)]
        if len(mine) < piece // 2 or len(other) < len(mine):
            continue
        found, alike = best_offset(mine, other, most=10.0)
        if alike < SURE:
            return Lined(offset, likeness, False, "Part of one isn't in the other.")
        heard.append(found + (first - start) * FRAME)
    if any(abs(each - offset) > AGREE for each in heard):
        return Lined(
            offset,
            likeness,
            False,
            "They drift apart: one is cut differently, or runs at another speed.",
        )
    return Lined(offset, likeness, True, None)
