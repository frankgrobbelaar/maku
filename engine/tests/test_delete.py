"""Deleting videos the way Maku deletes: into the quarantine, with their subtitles, put back from
History until the quarantine is cleared out."""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

from maku import changes, tidy
from maku.core.library import QUARANTINE_FOLDER
from maku.core.report import GAP_ANALYSIS_FILE
from maku.history import plans
from maku.tidy import ConvertingError, delete, undo
from tests.shelf import NOW, library


@pytest.fixture
def season(conn: sqlite3.Connection, tmp_path: Path) -> Path:
    """Quiet Hours' first two episodes in a season folder of their own, the first with
    subtitles."""
    root = tmp_path / "Videos"
    names = [f"Quiet Hours (2015)/Season 01/Quiet Hours (2015) - S01E0{n}.mkv" for n in (1, 2)]
    library(conn, root, names)
    folder = root / "Quiet Hours (2015)" / "Season 01"
    (folder / "Quiet Hours (2015) - S01E01.en.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nHi\n"
    )
    with conn:
        conn.execute(
            "INSERT INTO titles (id, kind, name, year) VALUES (1, 'series', 'Quiet Hours', 2015)"
        )
        conn.execute("UPDATE files SET title_id = 1, season = 1, episode = id, matched = 'sure'")
    return folder


def quarantined(folder: Path) -> list[str]:
    day = Path(folder.anchor) / QUARANTINE_FOLDER / NOW.date().isoformat()
    return sorted(path.name for path in day.iterdir()) if day.is_dir() else []


def test_a_deleted_video_goes_to_quarantine_with_its_subtitles_and_can_come_back(
    conn: sqlite3.Connection, season: Path
):
    episode = season / "Quiet Hours (2015) - S01E01.mkv"

    done = delete(conn, [1], now=NOW)

    assert (done.moved, done.quarantined, done.problems) == (0, 1, ())
    assert sorted(path.name for path in season.iterdir()) == ["Quiet Hours (2015) - S01E02.mkv"]
    assert quarantined(season) == [
        "Quiet Hours (2015) - S01E01.en.srt",
        "Quiet Hours (2015) - S01E01.mkv",
    ]
    assert conn.execute("SELECT gone_at FROM files WHERE id = 1").fetchone()[0] is not None
    [plan] = plans(conn)
    assert (plan.title, plan.deleted) == ("Deleted Quiet Hours · S01E01", True)

    assert done.plan_id is not None
    undo(conn, done.plan_id, now=NOW)

    assert episode.is_file()
    assert (season / "Quiet Hours (2015) - S01E01.en.srt").is_file()
    assert conn.execute("SELECT gone_at FROM files WHERE id = 1").fetchone()[0] is None


def test_deleting_a_whole_show_takes_the_folders_it_empties_and_its_report(
    conn: sqlite3.Connection, season: Path
):
    show = season.parent
    (show / GAP_ANALYSIS_FILE).write_text("# Quiet Hours (2015) — gap analysis\n", encoding="utf-8")

    done = delete(conn, [1, 2], now=NOW)

    assert not show.exists()
    [plan] = plans(conn)
    assert plan.title == "Deleted 2 Quiet Hours files"
    assert done.plan_id is not None
    undo(conn, done.plan_id, now=NOW)
    assert sorted(path.name for path in season.iterdir() if path.suffix == ".mkv") == [
        "Quiet Hours (2015) - S01E01.mkv",
        "Quiet Hours (2015) - S01E02.mkv",
    ]


# Converting, or made and waiting beside its original for another app to let go of it.
BUSY = pytest.mark.parametrize(
    ("state", "retry_at"), [("running", None), ("queued", "2026-10-11T10:05:00+02:00")]
)


@BUSY
def test_a_video_being_converted_isnt_deleted(
    conn: sqlite3.Connection, season: Path, state: str, retry_at: str | None
):
    with conn:
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, state, added_at, retry_at)"
            " VALUES (1, 'best', 1, ?, 'now', ?)",
            (state, retry_at),
        )

    with pytest.raises(ConvertingError, match=r"^Quiet Hours · S01E01 is being converted"):
        delete(conn, [1, 2], now=NOW)

    assert len(list(season.glob("*.mkv"))) == 2
    assert plans(conn) == []


def test_a_video_getting_english_subtitles_isnt_deleted(conn: sqlite3.Connection, season: Path):
    with conn:
        conn.execute(
            "INSERT INTO jobs (file_id, kind, method, position, state, added_at)"
            " VALUES (1, 'subtitles', 'best', 1, 'running', 'now')"
        )

    with pytest.raises(
        ConvertingError, match=r"^Quiet Hours · S01E01 is getting English subtitles"
    ):
        delete(conn, [1], now=NOW)


def test_a_video_waiting_to_convert_leaves_the_queue(conn: sqlite3.Connection, season: Path):
    with conn:
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, added_at) VALUES (1, 'best', 1, 'now')"
        )

    delete(conn, [1], now=NOW)

    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' sharing rules")
def test_a_video_that_couldnt_go_says_why_and_stays_in_the_queue(
    conn: sqlite3.Connection, season: Path
):
    with conn:
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, added_at) VALUES (1, 'best', 1, 'now')"
        )

    with (season / "Quiet Hours (2015) - S01E01.mkv").open("rb"):  # a player playing it
        done = delete(conn, [1], now=NOW)

    assert done.quarantined == 0
    assert [problem.problem for problem in done.problems][:1] == [
        "It's open in another app, maybe your player. Close it, then try again."
    ]
    assert [row["state"] for row in conn.execute("SELECT state FROM jobs")] == ["queued"]


def test_a_video_being_deleted_cant_start_converting_meanwhile(
    conn: sqlite3.Connection, season: Path, monkeypatch: pytest.MonkeyPatch
):
    with conn:
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, added_at) VALUES (1, 'best', 1, 'now')"
        )
    seen: list[str] = []
    apply_plan = tidy.apply_plan

    def watched(db: sqlite3.Connection, plan_id: int, *, now: datetime) -> changes.Outcome:
        seen.append(db.execute("SELECT state FROM jobs").fetchone()[0])  # as the queue sees it
        return apply_plan(db, plan_id, now=now)

    monkeypatch.setattr("maku.tidy.apply_plan", watched)

    delete(conn, [1], now=NOW)

    assert seen == ["skipped"]  # out of the queue's reach while it moves
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_subtitles_another_copy_shares_stay_with_it(conn: sqlite3.Connection, tmp_path: Path):
    library(conn, tmp_path / "Videos", ["Old/Ep01.mkv", "Old/Ep01.mp4"])
    folder = tmp_path / "Videos" / "Old"
    (folder / "Ep01.en.srt").write_text("subtitles")
    mkv = conn.execute("SELECT id FROM files WHERE path LIKE '%.mkv'").fetchone()[0]

    delete(conn, [mkv], now=NOW)

    assert sorted(path.name for path in folder.iterdir()) == ["Ep01.en.srt", "Ep01.mp4"]


def test_subtitles_both_copies_share_go_once_with_them(conn: sqlite3.Connection, tmp_path: Path):
    library(conn, tmp_path / "Videos", ["Old/Ep01.mkv", "Old/Ep01.mp4"])
    folder = tmp_path / "Videos" / "Old"
    (folder / "Ep01.en.srt").write_text("subtitles")

    done = delete(conn, [1, 2], now=NOW)

    assert done.problems == ()
    assert quarantined(folder) == ["Ep01.en.srt", "Ep01.mkv", "Ep01.mp4"]
