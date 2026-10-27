"""Lining two copies of an episode up by their sound, made-up sound standing in for theirs."""

import numpy as np
import pytest

from maku.core.align import FRAME, RATE, best_offset, envelope, line_up


def episode(seconds: float, seed: int = 1) -> np.ndarray:
    """Sound that rises and falls like an episode's: bursts of noise at made-up moments."""
    rng = np.random.default_rng(seed)
    loudness = np.repeat(rng.uniform(0.01, 1.0, round(seconds * 4)), RATE // 4)
    return (rng.standard_normal(len(loudness)) * loudness).astype(np.float32)


def test_the_envelope_follows_the_sound_a_hundred_frames_a_second():
    sound = episode(10)

    shape = envelope(sound)

    assert len(shape) == round(10 / FRAME)
    assert abs(float(shape.mean())) < 1e-3
    assert float(shape.std()) == pytest.approx(1.0, abs=1e-3)
    assert len(envelope(np.zeros(10, np.float32))) == 0


@pytest.mark.parametrize("seconds", [3.21, -1.5, 0.0])
def test_the_offset_is_where_the_two_copies_are_most_alike(seconds: float):
    ours = episode(300)
    lead = episode(abs(seconds) + 1, seed=9)[: round(abs(seconds) * RATE)]
    # Theirs runs `seconds` later: it has that much more at its start (or less, when earlier).
    theirs = np.concatenate([lead, ours]) if seconds > 0 else ours[round(-seconds * RATE) :]

    found, alike = best_offset(envelope(ours), envelope(theirs))

    assert found == pytest.approx(seconds, abs=FRAME)
    assert alike > 0.9


def test_two_copies_of_the_same_cut_line_up_with_another_mix():
    ours = episode(600)
    noise = np.random.default_rng(5).standard_normal(len(ours)).astype(np.float32) * 0.05
    theirs = np.concatenate([episode(2.5, seed=7), ours * 0.6 + noise])

    lined = line_up(envelope(ours), envelope(theirs))

    assert lined.same
    assert lined.offset == pytest.approx(2.5, abs=FRAME)
    assert lined.why is None


def test_a_copy_with_a_scene_cut_doesnt_line_up():
    ours = episode(600)
    cut = np.concatenate([ours[: 250 * RATE], ours[262 * RATE :]])  # 12 s gone mid-way

    lined = line_up(envelope(ours), envelope(cut))

    assert not lined.same
    assert lined.why is not None


def test_a_copy_at_another_speed_doesnt_line_up():
    ours = episode(600)
    faster = np.interp(  # 4% faster, as a European release runs
        np.arange(0, len(ours), 1.04), np.arange(len(ours)), ours
    ).astype(np.float32)

    lined = line_up(envelope(ours), envelope(faster))

    assert not lined.same


def test_sound_that_isnt_alike_doesnt_line_up():
    lined = line_up(envelope(episode(300, seed=1)), envelope(episode(300, seed=2)))

    assert not lined.same
    assert lined.why == "Their sound isn't alike enough to line them up."
