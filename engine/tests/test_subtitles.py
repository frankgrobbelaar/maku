"""English subtitles Maku makes from a video's sound: written beside it as media servers read them,
checked, kept as Maku's, and taken away again as a batch; Whisper and ffmpeg stood in for."""

import os
import sqlite3
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from maku import tidy
from maku.config import DataPaths
from maku.convert import Programs
from maku.core.plan import in_quarantine
from maku.core.speech import Heard, Made, Report, Segment, Stop
from maku.history import clear, page
from maku.subtitles import (
    NOTHING_SAID,
    SubtitlesError,
    english,
    hearable,
    make,
    new_batch,
    present,
    take_away,
)
from tests.converting import programs, report
from tests.shelf import NOW, library

LINES = [Segment(1.0, 2.5, "Over here!"), Segment(3.0, 5.0, "The comet is falling.")]


class Hearer:
    """Stands in for Whisper: says it heard `lines`, and keeps what it was asked."""

    def __init__(self, lines: Sequence[Segment] = LINES) -> None:
        self.lines = list(lines)
        self.asked: list[tuple[int, str | None]] = []  # samples heard, and in what language

    def hear(self, audio: np.ndarray, language: str | None, *, report: Report, stop: Stop) -> Made:
        self.asked.append((len(audio), language))
        report(Heard("listening", 600.0, 1440.0))
        return Made(self.lines, "ja", translated=True, speech=4.0)


@pytest.fixture
def episodes(conn: sqlite3.Connection, tmp_path: Path) -> Path:
    """Two episodes of a made-up series, read: Japanese sound, no subtitles."""
    root = tmp_path / "Videos"
    names = [f"Starfall (1989)/Season 01/Starfall (1989) - S01E0{n}.mkv" for n in (1, 2)]
    library(conn, root, names)
    with conn:
        conn.execute(
            "INSERT INTO titles (id, kind, name, year) VALUES (1, 'series', 'Starfall', 1989)"
        )
        conn.execute("UPDATE files SET title_id = 1, season = 1, episode = id, matched = 'sure'")
    return root / "Starfall (1989)" / "Season 01"


def job(conn: sqlite3.Connection, file_id: int, batch: int, quality: str = "best") -> int:
    with conn:
        cursor = conn.execute(
            """INSERT INTO jobs (file_id, kind, method, sound, batch_id, position, added_at,
                                 state)
               VALUES (?, 'subtitles', ?, 0, ?, ?, ?, 'running')""",
            (file_id, quality, batch, file_id, NOW.isoformat()),
        )
    return cursor.lastrowid or 0


def kit() -> Programs:
    return programs(report(8, 6))


def made(conn: sqlite3.Connection, job_id: int, hearer: Hearer | None = None) -> list[Heard]:
    heard: list[Heard] = []
    make(
        conn,
        job_id,
        kit(),
        hearer or Hearer(),
        now=lambda: NOW,
        report=heard.append,
        stop=lambda: False,
    )
    return heard


def test_subtitles_are_written_beside_the_video_and_kept_as_makus(
    conn: sqlite3.Connection, episodes: Path
):
    batch = new_batch(conn, "Starfall · Season 1", "best", "jpn", now=NOW)
    hearer = Hearer()

    heard = made(conn, job(conn, 1, batch), hearer)

    written = episodes / "Starfall (1989) - S01E01.en.srt"
    assert written.read_bytes() == (
        b"1\r\n00:00:01,000 --> 00:00:02,500\r\nOver here!\r\n\r\n"
        b"2\r\n00:00:03,000 --> 00:00:05,000\r\nThe comet is falling.\r\n\r\n"
    )
    assert [file.name for file in episodes.iterdir() if "maku" in file.name] == []  # no part left
    assert hearer.asked == [(16_000, "jpn")]  # the fake ffmpeg's second of sound, and its track
    assert [each.stage for each in heard] == ["reading", "listening", "writing", "checking"]
    row = conn.execute("SELECT * FROM made_subtitles").fetchone()
    assert (row["file_id"], row["name"], row["batch_id"], row["language"]) == (
        1,
        ".en.srt",
        batch,
        "ja",
    )
    assert row["size"] == written.stat().st_size
    finished = conn.execute("SELECT state, problem, output_size FROM jobs").fetchone()
    assert tuple(finished) == ("done", None, written.stat().st_size)


def test_a_name_another_file_has_is_left_alone(conn: sqlite3.Connection, episodes: Path):
    theirs = episodes / "Starfall (1989) - S01E01.en.srt"
    theirs.write_text("1\n00:00:01,000 --> 00:00:02,000\nTheirs\n", encoding="utf-8")
    batch = new_batch(conn, "Starfall", "fast", "jpn", now=NOW)

    made(conn, job(conn, 1, batch, "fast"))

    assert theirs.read_text(encoding="utf-8").endswith("Theirs\n")
    assert (episodes / "Starfall (1989) - S01E01.maku.en.srt").is_file()
    assert conn.execute("SELECT name FROM made_subtitles").fetchone()[0] == ".maku.en.srt"


def test_makus_own_subtitles_are_made_anew_in_their_place(conn: sqlite3.Connection, episodes: Path):
    batch = new_batch(conn, "Starfall", "fast", "jpn", now=NOW)
    made(conn, job(conn, 1, batch, "fast"))

    made(conn, job(conn, 1, batch), Hearer([Segment(1.0, 2.0, "Better now.")]))

    assert [file.name for file in episodes.iterdir() if file.suffix == ".srt"] == [
        "Starfall (1989) - S01E01.en.srt"
    ]
    assert "Better now." in (episodes / "Starfall (1989) - S01E01.en.srt").read_text("utf-8")


def test_subtitles_the_owner_changed_are_theirs_and_stay(conn: sqlite3.Connection, episodes: Path):
    batch = new_batch(conn, "Starfall", "fast", "jpn", now=NOW)
    made(conn, job(conn, 1, batch, "fast"))
    ours = episodes / "Starfall (1989) - S01E01.en.srt"
    ours.write_text(ours.read_text("utf-8").replace("Over here!", "Over there!"), "utf-8")

    made(conn, job(conn, 1, batch))

    assert "Over there!" in ours.read_text("utf-8")
    assert (episodes / "Starfall (1989) - S01E01.maku.en.srt").is_file()


def test_an_edit_that_keeps_their_size_makes_them_the_owners_too(
    conn: sqlite3.Connection, episodes: Path
):
    batch = new_batch(conn, "Starfall", "fast", "jpn", now=NOW)
    made(conn, job(conn, 1, batch, "fast"))
    ours = episodes / "Starfall (1989) - S01E01.en.srt"
    ours.write_text(ours.read_text("utf-8").replace("Over here!", "Over there"), "utf-8")
    written = ours.stat()
    os.utime(ours, ns=(written.st_atime_ns, written.st_mtime_ns + 60 * 10**9))  # a minute on

    assert not hearable(conn)[0].made
    assert present(conn, batch) == 0
    made(conn, job(conn, 1, batch))

    assert "Over there" in ours.read_text("utf-8")
    assert (episodes / "Starfall (1989) - S01E01.maku.en.srt").is_file()


def test_subtitles_are_known_as_makus_before_they_take_their_name(
    conn: sqlite3.Connection, episodes: Path, monkeypatch: pytest.MonkeyPatch
):
    """A crash between the two leaves nothing Maku wrote that isn't known as Maku's."""
    batch = new_batch(conn, "Starfall", "fast", "jpn", now=NOW)
    named = Path.replace
    known: list[str | None] = []

    def replace(self: Path, target: Path) -> Path:
        row = conn.execute("SELECT name FROM made_subtitles").fetchone()
        known.append(row["name"] if row else None)
        return named(self, target)

    monkeypatch.setattr(Path, "replace", replace)

    made(conn, job(conn, 1, batch, "fast"))

    assert known == [".en.srt"]


def test_subtitles_that_cant_take_their_name_leave_nothing_behind(
    conn: sqlite3.Connection, episodes: Path, monkeypatch: pytest.MonkeyPatch
):
    batch = new_batch(conn, "Starfall", "fast", "jpn", now=NOW)

    def held(self: Path, target: Path) -> Path:
        raise PermissionError(13, "The file is in use by another program")

    monkeypatch.setattr(Path, "replace", held)

    with pytest.raises(SubtitlesError, match="couldn't write them beside the video"):
        made(conn, job(conn, 1, batch, "fast"))

    assert conn.execute("SELECT COUNT(*) FROM made_subtitles").fetchone()[0] == 0
    assert not any(file.suffix != ".mkv" for file in episodes.iterdir())


def test_with_both_names_taken_maku_makes_none(conn: sqlite3.Connection, episodes: Path):
    for name in ("en", "maku.en"):
        (episodes / f"Starfall (1989) - S01E01.{name}.srt").write_text("theirs", "utf-8")
    batch = new_batch(conn, "Starfall", "fast", "jpn", now=NOW)

    with pytest.raises(SubtitlesError, match="beside it already"):
        made(conn, job(conn, 1, batch))

    assert conn.execute("SELECT COUNT(*) FROM made_subtitles").fetchone()[0] == 0


def test_where_no_one_speaks_none_are_made_and_the_job_says_so(
    conn: sqlite3.Connection, episodes: Path
):
    batch = new_batch(conn, "Starfall", "best", "jpn", now=NOW)

    made(conn, job(conn, 1, batch), Hearer([]))

    assert not any(file.suffix == ".srt" for file in episodes.iterdir())
    assert tuple(conn.execute("SELECT state, problem FROM jobs").fetchone()) == (
        "done",
        NOTHING_SAID,
    )


def test_a_sound_that_cant_be_read_fails_with_what_ffmpeg_said(
    conn: sqlite3.Connection, episodes: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MAKU_FAKE_FAIL", "sound")
    batch = new_batch(conn, "Starfall", "best", "jpn", now=NOW)

    with pytest.raises(SubtitlesError) as failed:
        made(conn, job(conn, 1, batch))

    assert str(failed.value).startswith("ffmpeg couldn't read its sound")
    assert failed.value.log is not None
    assert "invalid data" in failed.value.log
    assert not any(file.suffix == ".srt" for file in episodes.iterdir())


def test_the_library_says_what_each_video_is_heard_and_read_in(
    conn: sqlite3.Connection, episodes: Path
):
    (episodes / "Starfall (1989) - S01E02.de.srt").write_text("Hallo", "utf-8")
    batch = new_batch(conn, "Starfall", "best", "jpn", now=NOW)
    made(conn, job(conn, 1, batch))

    first, second = hearable(conn)

    assert (first.label, first.sound, first.subtitles, first.made) == (
        "Starfall · S01E01",
        ["jpn"],
        ["en"],
        True,
    )
    assert english(first)
    assert (second.subtitles, second.made, english(second)) == (["de"], False, False)
    assert second.seconds == 24 * 60


def test_a_batch_taken_away_goes_to_quarantine_and_history_puts_it_back(
    conn: sqlite3.Connection, episodes: Path, paths: DataPaths
):
    batch = new_batch(conn, "Starfall · Season 1", "best", "jpn", now=NOW)
    made(conn, job(conn, 1, batch))
    made(conn, job(conn, 2, batch))
    changed = episodes / "Starfall (1989) - S01E02.en.srt"
    changed.write_text("the owner's own now", "utf-8")
    assert present(conn, batch) == 1

    plan_id = take_away(conn, batch, now=NOW + timedelta(hours=1))

    assert plan_id is not None
    assert not (episodes / "Starfall (1989) - S01E01.en.srt").exists()
    assert changed.read_text("utf-8") == "the owner's own now"  # not Maku's any more: it stays
    [change] = conn.execute("SELECT target, reason FROM changes WHERE plan_id = ?", (plan_id,))
    assert in_quarantine(Path(change["target"]))
    assert present(conn, batch) == 0
    [shown] = [plan for plan in page(conn).plans if plan.id == plan_id]
    assert shown.title == "Took away the English subtitles Maku made for Starfall · Season 1"
    assert shown.taken_away == 1

    tidy.undo(conn, plan_id, now=NOW + timedelta(hours=2))

    assert (episodes / "Starfall (1989) - S01E01.en.srt").is_file()
    assert present(conn, batch) == 1
    [batch_shown] = page(conn).subtitles
    assert (batch_shown.title, batch_shown.made, batch_shown.present) == (
        "Starfall · Season 1",
        2,
        1,
    )


def test_a_deleted_videos_subtitles_are_neither_counted_nor_taken_away(
    conn: sqlite3.Connection, episodes: Path
):
    batch = new_batch(conn, "Starfall · Season 1", "best", "jpn", now=NOW)
    made(conn, job(conn, 1, batch))
    made(conn, job(conn, 2, batch))
    deleted = tidy.delete(conn, [1], now=NOW + timedelta(hours=1))  # with its subtitles

    assert present(conn, batch) == 1
    plan_id = take_away(conn, batch, now=NOW + timedelta(hours=2))

    taken = conn.execute("SELECT source FROM changes WHERE plan_id = ?", (plan_id,)).fetchall()
    assert [Path(row["source"]).name for row in taken] == ["Starfall (1989) - S01E02.en.srt"]
    tidy.undo(conn, deleted.plan_id or 0, now=NOW + timedelta(hours=3))
    assert (episodes / "Starfall (1989) - S01E01.en.srt").is_file()  # back with its video


def test_a_batch_maku_doesnt_have_cant_be_taken_away(conn: sqlite3.Connection):
    with pytest.raises(LookupError):
        take_away(conn, 99, now=NOW)


def test_clearing_history_forgets_a_batch_but_not_that_its_subtitles_are_makus(
    conn: sqlite3.Connection, episodes: Path
):
    batch = new_batch(conn, "Starfall · Season 1", "best", "jpn", now=NOW)
    made(conn, job(conn, 1, batch))

    cleared = clear(conn, keep=timedelta(0), now=NOW + timedelta(days=1))

    assert cleared == 1
    assert page(conn).subtitles == []
    assert conn.execute("SELECT batch_id FROM made_subtitles").fetchone()[0] is None
    [first, _] = hearable(conn)
    assert first.made
