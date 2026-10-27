"""The gap analysis file, word for word as Maku writes it next to a series."""

from datetime import date, datetime
from fractions import Fraction
from pathlib import PureWindowsPath

import pytest

from maku.core.episodes import EpisodeNumber, all_episodes
from maku.core.estimate import Estimate, estimate, total
from maku.core.media import MediaInfo, Video
from maku.core.report import (
    EpisodeState,
    GapAnalysis,
    SpecialState,
    Status,
    conversion_summary,
    describe_gpu_time,
    describe_size,
    gap_analysis_markdown,
    share,
)
from maku.core.standard import FULL_HD, UHD, Decision, Method

MARKET_STREET = (39, 35, 33, 32, 26, 29, 25, 34, 38)  # a long made-up show: 291 episodes
GLASS_ORCHARD = (12, 13)
SD_EPISODE = MediaInfo(
    "mkv",
    1440.0,
    240_000_000,
    Video("h264", 720, 480, Fraction(4, 3), Fraction(24000, 1001), 8, False),
)

# The board said 11.7 GPU days, for upscaling every SD episode; made HEVC 10-bit at their own
# size, at the speed measured on the GTX 1660 Super on 2026-10-27, they take 2.5 GPU hours.
BOARD_TEXT = """\
# Market Street (1989) — gap analysis
_Updated 10 Oct 2026, 14:20 · library D:\\Videos_

## Summary
- Present: **287 of 291** episodes (99%)
- Missing: **4** · Broken: **1** · At standard: **4**

## Missing
| Episode | Absolute | Folder    |
|---------|----------|-----------|
| S04E11  | 118      | Season 04 |
| S04E12  | 119      | Season 04 |
| S07E13  | 207      | Season 07 |
| S09E01  | 254      | Season 09 |

## Broken
- S05E24 (163): stops decoding at 12:41, replace it

## To convert
- 281 episodes · SD → HEVC 10-bit
- About 2.5 GPU hours and 67 GB
"""


def board_status(number: EpisodeNumber) -> EpisodeState:
    """The design's sample: 4 converted, 1 converting, 1 broken, 4 missing, the rest to convert."""
    if number.absolute in {118, 119, 207, 254}:
        return EpisodeState(number, Status.MISSING)
    if number.absolute == 163:
        return EpisodeState(number, Status.BROKEN, "stops decoding at 12:41")
    if number.absolute <= 4:
        return EpisodeState(number, Status.READY)
    if number.absolute == 5:
        return EpisodeState(number, Status.CONVERTING)
    return EpisodeState(number, Status.TO_CONVERT)


def test_a_long_shows_gap_analysis_reads_as_written():
    reencoded = Decision(Method.REENCODE, 720, 480)
    analysis = GapAnalysis(
        show="Market Street (1989)",
        library=PureWindowsPath(r"D:\Videos"),
        updated=datetime(2026, 10, 10, 14, 20),
        episodes=tuple(board_status(number) for number in all_episodes(MARKET_STREET)),
        conversion=conversion_summary([(720, 480)], UHD),
        to_convert=total(estimate(SD_EPISODE, reencoded) for _ in range(281)),
    )

    assert gap_analysis_markdown(analysis) == BOARD_TEXT


def test_a_complete_show_with_nothing_to_do_says_so_briefly():
    analysis = GapAnalysis(
        show="Glass Orchard (2012)",
        library=PureWindowsPath(r"D:\Videos"),
        updated=datetime(2026, 10, 10, 9, 5),
        episodes=tuple(
            EpisodeState(number, Status.READY) for number in all_episodes(GLASS_ORCHARD)
        ),
    )

    assert gap_analysis_markdown(analysis) == (
        "# Glass Orchard (2012) — gap analysis\n"
        "_Updated 10 Oct 2026, 09:05 · library D:\\Videos_\n"
        "\n"
        "## Summary\n"
        "- Present: **25 of 25** episodes (100%)\n"
        "- Missing: **0** · Broken: **0** · At standard: **25**\n"
    )


def test_specials_the_library_lacks_are_listed_apart():
    analysis = GapAnalysis(
        show="Quiet Hours (2015)",
        library=PureWindowsPath(r"D:\Videos"),
        updated=datetime(2026, 10, 10, 9, 5),
        episodes=tuple(EpisodeState(number, Status.READY) for number in all_episodes((6,))),
        specials=(
            SpecialState(1, "Christmas Special", date(2015, 12, 24)),
            SpecialState(2, None, None),
        ),
    )

    text = gap_analysis_markdown(analysis)

    assert "- Missing: **0** · Broken: **0** · At standard: **6**\n" in text
    assert text.endswith(
        "\n## Specials not in the library\n- S00E01 · Christmas Special · 24 Dec 2015\n- S00E02\n"
    )


@pytest.mark.parametrize(
    ("size", "text"),
    [
        (412_000_000, "412 MB"),
        (8_200_000_000, "8.2 GB"),
        (15_380_000_000, "15 GB"),
        (126_450_000_000, "130 GB"),
        (1_300_000_000_000, "1.3 TB"),
    ],
)
def test_sizes_read_like_the_boards(size: int, text: str):
    assert describe_size(size) == text


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (1_010_580, "11.7 GPU days"),
        (126_000, "35 GPU hours"),
        (5_400, "1.5 GPU hours"),
        (720, "12 GPU minutes"),
    ],
)
def test_gpu_times_read_like_the_boards(seconds: float, text: str):
    assert describe_gpu_time(seconds) == text


def test_mixed_sources_are_listed_from_small_to_large():
    pictures = [(1280, 720), (720, 480), (720, 576), (1920, 800), (720, 480)]
    assert conversion_summary(pictures, UHD) == "SD, 720p and 1080p → HEVC 10-bit"
    assert conversion_summary([(1920, 1080), (3840, 2160), (3840, 1600)], FULL_HD) == (
        "1080p and 4K → HEVC 10-bit, 4K brought down to 1080p"
    )


def test_a_report_never_divides_by_zero():
    analysis = GapAnalysis("Empty", PureWindowsPath(r"D:\Videos"), datetime(2026, 1, 1), ())

    assert "- Present: **0 of 0** episodes (0%)" in gap_analysis_markdown(analysis)


def test_estimates_default_to_nothing():
    analysis = GapAnalysis("Empty", PureWindowsPath(r"D:\Videos"), datetime(2026, 1, 1), ())

    assert analysis.to_convert == Estimate(0.0, 0)


def test_missing_episodes_in_a_row_read_as_one_range():
    held = {1, 2, 3, 6, 61, 63, 64}
    analysis = GapAnalysis(
        show="Northwind Station (1986)",
        library=PureWindowsPath(r"D:\Videos"),
        updated=datetime(2026, 10, 11, 15, 30),
        episodes=tuple(
            EpisodeState(number, Status.TO_CONVERT if number.absolute in held else Status.MISSING)
            for number in all_episodes((153,))
        ),
    )

    text = gap_analysis_markdown(analysis)

    assert (
        "## Missing\n"
        "| Episode     | Absolute | Folder    |\n"
        "|-------------|----------|-----------|\n"
        "| S01E04      | 4        | Season 01 |\n"
        "| S01E05      | 5        | Season 01 |\n"
        "| S01E07–E60  | 7–60     | Season 01 |\n"
        "| S01E62      | 62       | Season 01 |\n"
        "| S01E65–E153 | 65–153   | Season 01 |\n"
    ) in text


def test_a_range_stops_at_the_end_of_a_season():
    analysis = GapAnalysis(
        show="Market Street (1989)",
        library=PureWindowsPath(r"D:\Videos"),
        updated=datetime(2026, 10, 11, 15, 30),
        episodes=tuple(
            EpisodeState(number, Status.MISSING if 37 <= number.absolute <= 42 else Status.READY)
            for number in all_episodes(MARKET_STREET)
        ),
    )

    text = gap_analysis_markdown(analysis)

    assert "| S01E37–E39 | 37–39    | Season 01 |\n" in text
    assert "| S02E01–E03 | 40–42    | Season 02 |\n" in text


@pytest.mark.parametrize(
    ("present", "total", "percent"),
    [
        (287, 291, 99),
        (3, 153, 2),
        (290, 291, 99),  # never 100 while one is missing
        (1, 300, 1),  # never 0 once one is there
        (26, 26, 100),
        (0, 12, 0),
        (0, 0, 0),
    ],
)
def test_how_much_is_there_rounds_but_never_overstates(present: int, total: int, percent: int):
    assert share(present, total) == percent
