"""Subtitles from a video's sound: where speech is, Whisper's rules, and subtitles from words."""

from collections.abc import Sequence
from dataclasses import replace

import numpy as np
import pytest

from maku.core.speech import (
    CHUNK,
    DETECTOR_STEP,
    LONGEST,
    MAX_INITIAL,
    READING,
    SAMPLE_RATE,
    SHORTEST,
    Answer,
    Segment,
    Tokens,
    Vocabulary,
    best_of,
    cues,
    detector_windows,
    kept,
    next_logprobs,
    overlapped,
    pick,
    repeats_itself,
    segments_of,
    speech_likelihood,
    srt,
    stretches,
    timed,
    verdict,
    whisper_language,
    windows,
)

FRAME = DETECTOR_STEP / SAMPLE_RATE
VOCABULARY = 400
TOKENS = Tokens(
    start=300,
    end=200,
    no_timestamps=302,
    language=301,
    task=299,
    suppress=(5,),
    translating=True,
)
FIRST = TOKENS.timestamp  # <|0.00|>, 303; the last timestamp is 399, <|1.92|>


def stamp(seconds: float) -> int:
    return FIRST + round(seconds / 0.02)


def words(tokens: Sequence[int]) -> str:
    return " ".join(f"w{token}" for token in tokens if token < TOKENS.end)


def test_a_tracks_language_is_named_as_whisper_names_it():
    known = {"ja", "de", "en", "he"}

    assert whisper_language("jpn", known) == "ja"
    assert whisper_language("ger", known) == "de"
    assert whisper_language("ja", known) == "ja"
    assert whisper_language("en-US", known) == "en"
    # One Whisper doesn't know by that name: it tells which language it hears instead.
    assert whisper_language("xyz", known) is None
    assert whisper_language("jp", known) is None
    assert whisper_language("iw", known) is None


def test_the_detector_says_speech_is_likely_where_no_one_is_unlikely():
    nobody, someone = [8.0, 0, 0, 0, 0, 0, 0], [0, 8.0, 0, 0, 0, 0, 0]
    two_at_once = [0, 0, 0, 0, 8.0, 0, 0]

    likelihood = speech_likelihood(np.array([nobody, someone, two_at_once]))

    assert likelihood[0] < 0.01
    assert likelihood[1] > 0.99
    assert likelihood[2] > 0.99


def test_the_detectors_windows_start_every_five_seconds_and_overlap():
    assert detector_windows(12 * SAMPLE_RATE) == [0, 5 * SAMPLE_RATE, 10 * SAMPLE_RATE]

    half = 5 * SAMPLE_RATE // DETECTOR_STEP
    first = np.ones(2 * half, np.float32)
    second = np.zeros(2 * half, np.float32)
    merged = overlapped([(0, first), (5 * SAMPLE_RATE, second)], 15 * SAMPLE_RATE)

    assert merged[: half - 1] == pytest.approx(1.0)
    assert merged[half + 1 : 2 * half - 1] == pytest.approx(0.5)
    assert merged[2 * half + 1 :] == pytest.approx(0.0)


def likelihood_of(*spans: tuple[float, float, float], seconds: float = 60.0) -> np.ndarray:
    """A detector's likelihood: `spans` of (from, to, how likely), the rest unlikely."""
    values = np.full(round(seconds / FRAME), 0.05, np.float32)
    for first, last, value in spans:
        values[round(first / FRAME) : round(last / FRAME)] = value
    return values


def test_speech_runs_from_where_the_detector_is_sure_till_it_is_unsure():
    found = stretches(likelihood_of((10, 12, 0.9), (12, 14, 0.4), (20, 22, 0.6)), pad=0)

    assert found == [
        pytest.approx((10, 14), abs=FRAME * 2),  # 0.4 keeps it going once begun
        pytest.approx((20, 22), abs=FRAME * 2),
    ]


def test_short_pauses_close_blips_go_and_speech_is_padded():
    found = stretches(
        likelihood_of((10, 12, 0.9), (12.1, 13, 0.9), (30, 30.1, 0.9)), gap=0.3, shortest=0.2
    )

    assert found == [pytest.approx((9.8, 13.2), abs=FRAME * 2)]


def test_windows_gather_speech_into_thirty_seconds_or_less_of_the_sound_as_it_is():
    speech = [(1.0, 5.0), (8.0, 20.0), (25.0, 32.0), (40.0, 110.0)]

    assert windows(speech) == [
        (1.0, 20.0),  # pauses and all
        (25.0, 32.0),
        (40.0, 70.0),  # a long stretch is cut
        (70.0, 100.0),
        (100.0, 110.0),
    ]
    assert all(last - first <= CHUNK for first, last in windows(speech))


def scores(likely: int) -> np.ndarray:
    logits = np.zeros(VOCABULARY)
    logits[likely] = 10.0
    return logits


def test_whispers_first_token_is_a_timestamp_within_a_second():
    logprobs = next_logprobs(scores(7), [], TOKENS, seconds=30.0)

    allowed = np.isfinite(logprobs)
    assert not allowed[:FIRST].any()
    assert allowed[FIRST : FIRST + MAX_INITIAL + 1].all()
    assert not allowed[FIRST + MAX_INITIAL + 1 :].any()
    assert np.exp(logprobs).sum() == pytest.approx(1.0)


def test_timestamps_pair_up_never_go_back_and_never_pass_the_sound():
    after_words = np.isfinite(next_logprobs(scores(7), [stamp(0.2), 7, 8], TOKENS, seconds=1.0))
    assert after_words[7]  # more words
    assert not after_words[FIRST : stamp(0.2) + 1].any()  # the end comes after the start
    assert after_words[stamp(0.2) + 1 : stamp(1.0) + 1].all()
    assert not after_words[stamp(1.0) + 1 :].any()  # and never past the sound's 1 s

    after_an_end = np.isfinite(
        next_logprobs(scores(7), [stamp(0.2), 7, stamp(0.6)], TOKENS, seconds=1.0)
    )
    assert not after_an_end[: TOKENS.end].any()  # the next start, or the end: no words
    assert not after_an_end[FIRST : stamp(0.6)].any()
    assert after_an_end[stamp(0.6) : stamp(1.0) + 1].all()

    after_a_pair = np.isfinite(
        next_logprobs(scores(7), [stamp(0.2), 7, stamp(0.6), stamp(0.6)], TOKENS, seconds=1.0)
    )
    assert after_a_pair[7]
    assert not after_a_pair[FIRST:].any()  # words come between a start and an end


def test_whisper_never_writes_its_own_signs_but_may_end():
    allowed = np.isfinite(next_logprobs(scores(7), [stamp(0.2), 7], TOKENS, seconds=1.0))

    assert not allowed[TOKENS.end + 1 : FIRST].any()  # its start, language, task and the like
    assert allowed[TOKENS.end]


def test_suppressed_tokens_never_come():
    assert next_logprobs(scores(5), [stamp(0)], TOKENS, seconds=30.0)[5] == -np.inf


def test_when_timestamps_together_are_likelier_than_any_word_one_comes():
    logits = np.zeros(VOCABULARY)
    logits[FIRST:] = 2.0  # each less likely than the word, all together far likelier
    logits[7] = 4.0

    logprobs = next_logprobs(logits, [stamp(0.0), 7], TOKENS, seconds=1.92)

    assert not np.isfinite(logprobs[:FIRST]).any()
    assert np.exp(logprobs).sum() == pytest.approx(1.0)


def test_the_likeliest_token_is_picked_unless_warmed():
    logprobs = np.log(np.array([0.1, 0.7, 0.2]))
    rng = np.random.default_rng(1)

    assert pick(logprobs, 0.0, rng) == 1
    drawn = {pick(logprobs, 1.0, rng) for _ in range(200)}
    assert drawn == {0, 1, 2}


def test_an_answer_stuck_in_a_loop_compresses_too_well():
    assert repeats_itself("I can't do it! " * 20)
    assert not repeats_itself("The harbour's old lantern has been lit again!")
    assert not repeats_itself("")


def answer(average: float, no_speech: float = 0.0, text: str = "Over here!") -> Answer:
    return Answer((stamp(0), 7, stamp(1)), average, no_speech, text)


def test_translating_takes_less_certainty_than_writing_down():
    writing_down = replace(TOKENS, translating=False)

    assert verdict(answer(-1.2), TOKENS) == "good"
    assert verdict(answer(-1.2), writing_down) == "again"
    assert verdict(answer(-1.7), TOKENS) == "again"
    assert verdict(answer(-0.5, text="Yes! " * 40), TOKENS) == "again"
    assert verdict(answer(-1.7, no_speech=0.8), TOKENS) == "quiet"
    assert verdict(answer(-0.3, no_speech=0.8), TOKENS) == "good"  # sure of the words


def test_when_no_temperature_will_do_the_surest_answer_that_doesnt_loop_is_kept():
    looping = answer(-0.2, text="Yes! " * 40)
    unsure, surer = answer(-2.5), answer(-1.8)

    assert best_of([looping, unsure, surer]) == surer
    assert best_of([looping]) == looping


def test_an_answer_becomes_segments_timed_from_its_windows_start():
    made = [stamp(0.0), 7, 8, stamp(0.5), stamp(0.6), 9, stamp(1.2), stamp(1.4)]

    found, heard = segments_of(made, TOKENS, 100.0, 30.0, words)

    assert [(each.start, each.end, each.text) for each in found] == [
        (100.0, 100.5, "w7 w8"),
        (100.6, pytest.approx(101.2), "w9"),
    ]
    assert heard == pytest.approx(1.2)  # it stopped short: go on after the last whole segment


def test_an_answer_that_ends_on_a_lone_timestamp_heard_its_window_through():
    made = [stamp(0.0), 7, stamp(0.5), stamp(0.6), 9, stamp(1.0)]

    found, heard = segments_of(made, TOKENS, 0.0, 1.5, words)

    assert [segment.text for segment in found] == ["w7", "w9"]
    assert heard is None


def test_an_answer_without_timestamp_pairs_spans_its_sound():
    found, heard = segments_of([stamp(0.0), 7, 8], TOKENS, 10.0, 4.0, words)

    assert found == [Segment(10.0, 14.0, "w7 w8")]
    assert heard is None


def test_empty_repeated_and_invented_lines_are_left_out():
    found = kept(
        [
            Segment(0, 1, "Over here!"),
            Segment(1, 2, "Over here!"),
            Segment(2, 3, " ... "),
            Segment(3, 4, "Thanks for watching!"),
            Segment(4, 5, "Run!"),
        ]
    )

    assert [segment.text for segment in found] == ["Over here!", "Run!"]


def test_subtitles_stay_long_enough_to_read_and_never_overlap():
    found = timed(
        [
            Segment(10.0, 10.3, "Run!"),  # too short: a second at least
            Segment(20.0, 21.0, "Over here!"),  # reading time after it
            Segment(21.2, 40.0, "On and on"),  # the one before stops for it; this one's cut
            Segment(40.0, 41.0, "Last"),
        ]
    )

    assert found[0] == Segment(10.0, 10.0 + SHORTEST, "Run!")
    assert found[1].end == pytest.approx(21.2)  # reading time, up to the next
    assert found[2].end == pytest.approx(21.2 + LONGEST)
    assert found[3].end == pytest.approx(41.0 + READING)


def test_long_lines_split_into_subtitles_of_two_lines_sharing_the_time():
    text = " ".join(["word"] * 40)  # 199 characters

    found = cues([Segment(0.0, 10.0, text)])

    assert len(found) == 3
    assert all(len(line) <= 42 for cue in found for line in cue.text.split("\n"))
    assert all(cue.text.count("\n") <= 1 for cue in found)
    assert found[0].start == 0.0
    assert found[-1].end == pytest.approx(10.0)


def test_subtitles_are_written_as_an_srt_file():
    text = srt([Segment(1.5, 3.25, "Over here!"), Segment(3661.0, 3662.0, "Run!\nNow!")])

    assert text == (
        "1\r\n00:00:01,500 --> 00:00:03,250\r\nOver here!\r\n\r\n"
        "2\r\n01:01:01,000 --> 01:01:02,000\r\nRun!\r\nNow!\r\n\r\n"
    )


def test_a_subtitle_too_long_for_two_lines_is_shared_evenly_at_a_pause():
    text = "After decades of patience, cold rain, frost, storm, sleet, and a lot of lanterns,"

    found = cues([Segment(0.0, 6.0, text)])

    assert [cue.text for cue in found] == [
        "After decades of patience, cold rain,",
        "frost, storm, sleet,\nand a lot of lanterns,",
    ]
    assert found[0].end == pytest.approx(6.0 * 37 / 80)  # each its share of the time


def test_two_lines_are_about_as_long_as_each_other():
    [cue] = cues([Segment(0.0, 3.0, "The little lanterns go flickering over the silent docks.")])

    assert cue.text == "The little lanterns go\nflickering over the silent docks."


def test_whispers_tokens_are_words_written_byte_by_byte():
    pieces = {0: "Over", 1: "Ġhere", 2: "!", 3: "ĠCaf", 4: "Ã©", 5: "<|ja|>"}
    vocabulary = Vocabulary(pieces, end=5)

    assert vocabulary.text([0, 1, 2]) == "Over here!"
    assert vocabulary.text([3, 4]) == " Café"
    assert vocabulary.text([0, 5, 6, 1]) == "Over here"  # its own signs and timestamps aren't words
