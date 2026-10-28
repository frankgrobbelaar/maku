"""The reports Maku writes next to each series, starting with "Maku - Gap analysis.md".

They are plain Markdown, readable without Maku (Plex ignores .md files), and match the title
board in the design word for word.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import PurePath

from maku.core.episodes import EpisodeNumber
from maku.core.estimate import NOTHING, Estimate
from maku.core.standard import Standard, size_name

GAP_ANALYSIS_FILE = "Maku - Gap analysis.md"


class Status(StrEnum):
    READY = "ready"  # at the standard
    CONVERTING = "converting"
    TO_CONVERT = "to convert"
    BROKEN = "broken"
    MISSING = "missing"


@dataclass(frozen=True)
class EpisodeState:
    number: EpisodeNumber
    status: Status
    problem: str | None = None  # what's wrong with a broken file


@dataclass(frozen=True)
class SpecialState:
    """A special (season 0) the library doesn't hold. Listed apart: never missing."""

    number: int
    title: str | None
    aired: date | None


@dataclass(frozen=True)
class GapAnalysis:
    show: str  # "The Harbour Line (2019)"
    library: PurePath
    updated: datetime
    episodes: tuple[EpisodeState, ...]
    conversion: str | None = None  # "SD and 1080p → HEVC 10-bit"
    to_convert: Estimate = NOTHING
    specials: tuple[SpecialState, ...] = ()  # specials not in the library


def gap_analysis_markdown(analysis: GapAnalysis) -> str:
    by_status = {status: [e for e in analysis.episodes if e.status == status] for status in Status}
    present = len(analysis.episodes) - len(by_status[Status.MISSING])

    lines = [
        f"# {analysis.show} — gap analysis",
        f"_Updated {_date(analysis.updated)} · library {analysis.library}_",
        "",
        "## Summary",
        f"- Present: **{present} of {len(analysis.episodes)}** episodes"
        f" ({share(present, len(analysis.episodes))}%)",
        f"- Missing: **{len(by_status[Status.MISSING])}**"
        f" · Broken: **{len(by_status[Status.BROKEN])}**"
        f" · At standard: **{len(by_status[Status.READY])}**",
    ]
    if missing := by_status[Status.MISSING]:
        rows = [_missing_row(run) for run in runs([e.number for e in missing])]
        lines += ["", "## Missing", *_table(["Episode", "Absolute", "Folder"], rows)]
    if broken := by_status[Status.BROKEN]:
        lines += ["", "## Broken"]
        lines += [
            f"- {e.number.code} ({e.number.absolute}): {e.problem or "doesn't play"}, replace it"
            for e in broken
        ]
    if waiting := by_status[Status.TO_CONVERT]:
        what = f" · {analysis.conversion}" if analysis.conversion else ""
        lines += ["", "## To convert", f"- {len(waiting)} episodes{what}"]
        if analysis.to_convert.gpu_seconds:
            gpu = describe_gpu_time(analysis.to_convert.gpu_seconds)
            lines.append(f"- About {gpu} and {describe_size(analysis.to_convert.output_bytes)}")
    if analysis.specials:
        lines += ["", "## Specials not in the library"]
        lines += [_special(special) for special in analysis.specials]
    return "\n".join(lines) + "\n"


def share(present: int, total: int) -> int:
    """How much of a show is there, in whole percent: never 100 while an episode is missing, and
    never 0 once one is there."""
    if total <= 0:
        return 0
    percent = round(present / total * 100)
    if present < total:
        percent = min(percent, 99)
    if present > 0:
        percent = max(percent, 1)
    return percent


def runs(numbers: Sequence[EpisodeNumber]) -> list[tuple[EpisodeNumber, EpisodeNumber]]:
    """Episodes in a row within a season, as (first, last): three or more read as one range, a
    shorter run as each episode on its own (first is last)."""
    together: list[list[EpisodeNumber]] = []
    for number in numbers:
        before = together[-1][-1] if together else None
        if (
            before is not None
            and before.season == number.season
            and before.episode + 1 == number.episode
        ):
            together[-1].append(number)
        else:
            together.append([number])
    found: list[tuple[EpisodeNumber, EpisodeNumber]] = []
    for run in together:
        if len(run) >= 3:
            found.append((run[0], run[-1]))
        else:
            found.extend((number, number) for number in run)
    return found


def _missing_row(run: tuple[EpisodeNumber, EpisodeNumber]) -> list[str]:
    first, last = run
    folder = f"Season {first.season:02d}"
    if first == last:
        return [first.code, str(first.absolute), folder]
    return [f"{first.code}–E{last.episode:02d}", f"{first.absolute}–{last.absolute}", folder]


def _special(special: SpecialState) -> str:
    parts = [f"S00E{special.number:02d}"]
    if special.title:
        parts.append(special.title)
    if special.aired:
        parts.append(f"{special.aired.day} {_MONTHS[special.aired.month - 1]} {special.aired.year}")
    return "- " + " · ".join(parts)


_SIZE_ORDER = ("SD", "720p", "1080p", "1440p", "4K", "8K")


def conversion_summary(pictures: Iterable[tuple[int, int]], standard: Standard) -> str:
    """ "SD and 1080p → HEVC 10-bit", or "1080p and 4K → HEVC 10-bit, 4K brought down to 1080p":
    the sizes of the pictures to convert (width, height), and what they become."""
    found = {size_name(width, height) for width, height in pictures}
    sizes = [name for name in _SIZE_ORDER if name in found]
    top = _SIZE_ORDER.index(standard.name) if standard.name in _SIZE_ORDER else len(_SIZE_ORDER)
    bigger = [name for name in sizes if _SIZE_ORDER.index(name) > top]
    target = f"{standard.codec.upper()} {standard.bit_depth}-bit"
    brought = f", {_listed(bigger)} brought down to {standard.name}" if bigger else ""
    return f"{_listed(sizes)} → {target}{brought}"


def _listed(names: Sequence[str]) -> str:
    """ "SD", "SD and 1080p", "SD, 720p and 1080p"."""
    if len(names) < 2:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def describe_size(size: int) -> str:
    if size < 1e9:
        return f"{round(size / 1e6)} MB"
    if size < 10e9:
        return f"{size / 1e9:.1f} GB"
    if size < 1e12:
        return f"{int(float(f'{size / 1e9:.2g}'))} GB"  # two significant figures
    return f"{size / 1e12:.1f} TB"


def describe_gpu_time(seconds: float) -> str:
    """ "35 GPU hours", "11.7 GPU days": hours up to two days, as the convert board shows."""
    if seconds >= 2 * 86_400:
        return f"{_short(seconds / 86_400)} GPU days"
    if seconds >= 3_600:
        hours = seconds / 3_600
        return f"{round(hours) if hours >= 10 else _short(hours)} GPU hours"
    minutes = max(1, round(seconds / 60))
    return f"{minutes} GPU minute{'s' if minutes != 1 else ''}"


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _date(moment: datetime) -> str:
    """10 Oct 2026, 14:20 (English month names whatever Windows' language)."""
    return f"{moment.day} {_MONTHS[moment.month - 1]} {moment.year}, {moment:%H:%M}"


def _short(value: float) -> str:
    return f"{value:.1f}".removesuffix(".0")


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    widths = [max(len(cell) for cell in column) for column in zip(header, *rows, strict=True)]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True)) + " |"

    return [line(header), "|" + "|".join("-" * (w + 2) for w in widths) + "|", *map(line, rows)]
