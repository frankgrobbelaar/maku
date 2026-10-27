"""The reports Maku writes next to each series: "Maku - Gap analysis.md", worded by
maku/core/report.py. Plex ignores .md files.

A report only goes into a folder of the title's own: never a library folder itself, and never a
folder that holds another title's videos (a mixed Downloads folder gets none; once tidied, each
show has its folder and its report). A report whose news hasn't changed isn't rewritten.
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath

from maku import hardware
from maku.core.catalog import Show
from maku.core.episodes import EpisodeNumber
from maku.core.estimate import Estimate, estimate, total
from maku.core.names import season_of_folder
from maku.core.report import (
    GAP_ANALYSIS_FILE,
    EpisodeState,
    GapAnalysis,
    SpecialState,
    Status,
    conversion_summary,
    gap_analysis_markdown,
)
from maku.core.standard import Standard
from maku.preferences import library_standard, reports_wanted
from maku.titles import episode_statuses, show_of

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Written:
    reports: int
    problems: tuple[str, ...]  # folders Maku couldn't write to, in words


def write_reports(conn: sqlite3.Connection, *, now: datetime) -> Written:
    """Writes or refreshes the gap analysis of every series that has a folder of its own, or,
    when the owner turned the reports off, takes Maku's out of those folders."""
    standard = library_standard(conn)
    wanted = reports_wanted(conn)
    roots = [Path(row["path"]) for row in conn.execute("SELECT path FROM folders")]
    written = 0
    problems: list[str] = []
    for row in conn.execute("SELECT id, name, year FROM titles WHERE kind != 'movie'").fetchall():
        folder = own_folder(conn, row["id"], roots)
        if folder is not None and not wanted:
            _remove(folder / GAP_ANALYSIS_FILE)
            continue
        show = show_of(conn, row["id"])
        if folder is None or show is None:
            continue
        root = next(r for r in roots if folder.is_relative_to(r))
        analysis = _analysis(conn, row, show, root, standard, now)
        try:
            if _write(folder / GAP_ANALYSIS_FILE, gap_analysis_markdown(analysis)):
                written += 1
        except OSError as error:
            log.warning("Maku couldn't write a report in %s: %s", folder, error)
            problems.append(
                f"Maku couldn't write the report in {folder}: {error.strerror or error}."
            )
    return Written(written, tuple(problems))


def _remove(report: Path) -> None:
    try:
        report.unlink(missing_ok=True)
    except OSError as error:
        log.warning("Maku couldn't take its report out of %s: %s", report.parent, error)


def own_folder(conn: sqlite3.Connection, title_id: int, roots: list[Path]) -> Path | None:
    """The folder that holds a title's videos and nothing of another title's, or None."""
    paths = [
        Path(row["path"])
        for row in conn.execute(
            "SELECT path FROM files WHERE title_id = ? AND gone_at IS NULL", (title_id,)
        )
    ]
    folders = {_show_folder(path.parent) for path in paths}
    if len(folders) != 1:
        return None
    [folder] = folders
    if not any(folder != root and folder.is_relative_to(root) for root in roots):
        return None  # a library folder itself, or a folder outside the library
    # Another title's video in it, found by the database rather than by reading every path: a
    # title's page asks this each time it opens, and a big library has thousands.
    inside = str(folder).rstrip("\\/") + "\\"
    shared = conn.execute(
        """SELECT 1 FROM files
           WHERE gone_at IS NULL AND title_id IS NOT NULL AND title_id != ?
             AND lower(substr(path, 1, ?)) = lower(?)
           LIMIT 1""",
        (title_id, len(inside), inside),
    ).fetchone()
    if shared is not None:
        return None  # shared with another title
    return folder


def _analysis(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    show: Show,
    root: Path,
    standard: Standard,
    now: datetime,
) -> GapAnalysis:
    local = now.astimezone()  # the report is read in the time of this PC
    statuses = episode_statuses(conn, row["id"], show, standard, local.date())
    speeds = hardware.speeds(conn)  # the time converting takes here
    states: list[EpisodeState] = []
    to_convert: list[Estimate] = []
    pictures: list[tuple[int, int]] = []
    absolute = 0
    for status in statuses:
        episode = status.episode
        if episode.season == 0 or status.state == "upcoming":
            continue
        absolute += 1
        where = EpisodeNumber(episode.season, episode.number, absolute)
        states.append(EpisodeState(where, _REPORTED[status.state], status.problem))
        if status.state == "to convert" and status.media and status.decision:
            to_convert.append(estimate(status.media, status.decision, speeds))
            if video := status.media.video:
                pictures.append((video.width, video.height))
    specials = [s.episode for s in statuses if s.episode.season == 0 and s.state == "missing"]
    name = f"{row['name']} ({row['year']})" if row["year"] else row["name"]
    return GapAnalysis(
        show=name,
        library=PureWindowsPath(root),
        updated=local,
        episodes=tuple(states),
        conversion=conversion_summary(pictures, standard) if pictures else None,
        to_convert=total(to_convert),
        specials=tuple(SpecialState(e.number, e.title, e.aired) for e in specials),
    )


_REPORTED = {
    "ready": Status.READY,
    "to convert": Status.TO_CONVERT,
    "broken": Status.BROKEN,
    "missing": Status.MISSING,
    "upcoming": Status.MISSING,  # never reported: left out above
}


def _show_folder(folder: Path) -> Path:
    """A season's folder ("Season 02", "S02", "Specials") belongs to the show folder above it."""
    return folder.parent if season_of_folder(folder.name) is not None else folder


def _write(path: Path, text: str) -> bool:
    """Writes the report unless only its "Updated" line would change. True if it wrote."""
    try:
        before = path.read_text(encoding="utf-8")
    except OSError:
        before = None
    if before is not None and _news(before) == _news(text):
        return False
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def _news(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.startswith("_Updated ")]
