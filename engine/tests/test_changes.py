"""Applying, undoing and recovering tidy-up plans, on real files in a temporary folder."""

import json
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maku import changes, db
from maku.changes import (
    PARTIAL,
    ChangeState,
    apply_plan,
    changes_of,
    recover,
    save_plan,
    undo_plan,
)
from maku.core.plan import Change, ChangeKind, Plan

NOW = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "Maku" / "maku.db")) as connection:
        db.migrate(connection)
        yield connection


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    (tmp_path / "Downloads").mkdir()
    return tmp_path / "Downloads"


@pytest.fixture
def library(tmp_path: Path) -> Path:
    (tmp_path / "Videos").mkdir()
    return tmp_path / "Videos"


def video(path: Path, content: str = "video") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def move(source: Path, target: Path) -> Change:
    return Change(ChangeKind.MOVE, source, target, "Glass Orchard · S01E07", "Named and filed")


def saved(conn: sqlite3.Connection, *planned: Change) -> int:
    return save_plan(conn, Plan(planned), "Tidy up", now=NOW)


def states(conn: sqlite3.Connection, plan_id: int) -> list[ChangeState]:
    return [change.state for change in changes_of(conn, plan_id)]


def on_other_drives(file: Path, folder: Path) -> bool:
    return False


def crash_while(conn: sqlite3.Connection, state: ChangeState, created_dirs: list[Path]) -> None:
    """Leave every change the way a crash would: mid-way, with the folders it had made."""
    folders = json.dumps([str(folder) for folder in created_dirs])
    with conn:
        conn.execute("UPDATE changes SET state = ?, created_dirs = ?", (state.value, folders))


def test_a_saved_plan_waits_for_review(conn: sqlite3.Connection, downloads: Path, library: Path):
    source = video(downloads / "[GRP] Glass_Orchard_07 (720p).mkv")
    target = library / "Glass Orchard (2012)" / "Season 01" / "Glass Orchard (2012) - S01E07.mkv"

    plan_id = saved(conn, move(source, target))

    [change] = changes_of(conn, plan_id)
    assert (change.position, change.kind, change.state) == (1, ChangeKind.MOVE, ChangeState.PLANNED)
    assert (change.source, change.target, change.created_dirs) == (source, target, ())
    assert source.exists()
    assert not (library / "Glass Orchard (2012)").exists()


def test_applying_moves_each_file_and_makes_its_folders(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    source = video(downloads / "[GRP] Glass_Orchard_07 (720p).mkv")
    show = library / "Glass Orchard (2012)"
    target = show / "Season 01" / "Glass Orchard (2012) - S01E07.mkv"
    plan_id = saved(conn, move(source, target))

    outcome = apply_plan(conn, plan_id, now=NOW)

    assert (outcome.count, outcome.problems) == (1, ())
    assert target.read_text(encoding="utf-8") == "video"
    assert not source.exists()
    [change] = changes_of(conn, plan_id)
    assert change.state is ChangeState.DONE
    assert change.created_dirs == (show, show / "Season 01")
    applied = conn.execute("SELECT applied_at FROM plans WHERE id = ?", (plan_id,)).fetchone()
    assert applied["applied_at"] == "2026-10-10T20:00:00+00:00"


def test_a_taken_name_is_never_overwritten_and_the_rest_go_ahead(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    first = video(downloads / "a.mkv", "first")
    taken = video(library / "Show" / "a.mkv", "already there")
    second = video(downloads / "b.mkv", "second")
    plan_id = saved(conn, move(first, taken), move(second, library / "Show" / "b.mkv"))

    outcome = apply_plan(conn, plan_id, now=NOW)

    assert outcome.count == 1
    [failed] = outcome.problems
    assert failed.state is ChangeState.FAILED
    assert failed.problem == (
        f"a.mkv is already in {library / 'Show'}, and Maku never overwrites a file."
    )
    assert first.read_text(encoding="utf-8") == "first"
    assert taken.read_text(encoding="utf-8") == "already there"
    assert (library / "Show" / "b.mkv").read_text(encoding="utf-8") == "second"


def test_a_file_that_has_gone_is_reported(conn: sqlite3.Connection, downloads: Path, library: Path):
    gone = downloads / "gone.mkv"
    plan_id = saved(conn, move(gone, library / "Show" / "gone.mkv"))

    outcome = apply_plan(conn, plan_id, now=NOW)

    assert [change.problem for change in outcome.problems] == [f"It isn't at {gone} any more."]
    assert not (library / "Show").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' sharing rules")
def test_a_file_open_in_another_app_stays_and_says_so(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    source = video(downloads / "[GRP] Glass_Orchard_07 (720p).mkv")
    plan_id = saved(conn, move(source, library / "Glass Orchard (2012)" / "Glass Orchard - 07.mkv"))

    with source.open("rb"):  # a player playing it
        outcome = apply_plan(conn, plan_id, now=NOW)

    assert [change.problem for change in outcome.problems] == [
        "It's open in another app, maybe your player. Close it, then try again."
    ]
    assert source.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' sharing rules")
def test_subtitles_stay_with_a_video_that_couldnt_move(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    source = video(downloads / "Glass Orchard - 07.mkv")
    subtitles = video(downloads / "Glass Orchard - 07.en.srt", "subtitles")
    other = video(downloads / "Glass Orchard - 08.en.srt", "another episode's")
    show = library / "Glass Orchard (2012)"
    plan_id = saved(
        conn,
        move(source, show / "Glass Orchard (2012) - S01E07.mkv"),
        move(subtitles, show / "Glass Orchard (2012) - S01E07.en.srt"),
        move(other, show / "Glass Orchard (2012) - S01E08.en.srt"),
    )

    with source.open("rb"):  # a player playing it
        outcome = apply_plan(conn, plan_id, now=NOW)

    assert [change.source.name for change in outcome.changed] == ["Glass Orchard - 08.en.srt"]
    assert [(change.source.name, change.problem) for change in outcome.problems] == [
        (
            "Glass Orchard - 07.mkv",
            "It's open in another app, maybe your player. Close it, then try again.",
        ),
        ("Glass Orchard - 07.en.srt", "Its video stayed where it was, so it did too."),
    ]
    assert subtitles.read_text(encoding="utf-8") == "subtitles"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' sharing rules")
def test_subtitles_planned_before_their_video_still_wait_for_it(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    source = video(downloads / "Glass Orchard - 07.mkv")
    subtitles = video(downloads / "Glass Orchard - 07.en.srt", "subtitles")
    show = library / "Glass Orchard (2012)"
    plan_id = saved(  # by target, ".en.srt" sorts before ".mkv"
        conn,
        move(subtitles, show / "Glass Orchard (2012) - S01E07.en.srt"),
        move(source, show / "Glass Orchard (2012) - S01E07.mkv"),
    )

    with source.open("rb"):  # a player playing it
        outcome = apply_plan(conn, plan_id, now=NOW)

    assert outcome.changed == ()
    assert subtitles.read_text(encoding="utf-8") == "subtitles"


def test_undo_leaves_a_video_held_back_with_its_subtitles(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    source = video(downloads / "Glass Orchard - 07.mkv")
    subtitles = video(downloads / "Glass Orchard - 07.en.srt", "subtitles")
    show = library / "Glass Orchard (2012)"
    plan_id = saved(
        conn,
        move(source, show / "Glass Orchard (2012) - S01E07.mkv"),
        move(subtitles, show / "Glass Orchard (2012) - S01E07.en.srt"),
    )
    apply_plan(conn, plan_id, now=NOW)

    def converting(change: changes.SavedChange) -> str | None:
        return "It's being converted." if change.target.suffix == ".mkv" else None

    outcome = undo_plan(conn, plan_id, now=NOW, held=converting)

    assert outcome.changed == ()
    assert [change.problem for change in outcome.problems] == [
        "Maku couldn't put it back. It's being converted.",
        "Maku couldn't put it back. Its video stayed where it was, so it did too.",
    ]
    assert (show / "Glass Orchard (2012) - S01E07.en.srt").exists()


def test_a_change_of_case_alone_renames_the_file(conn: sqlite3.Connection, library: Path):
    source = video(library / "Show" / "show - s01e01.mkv")
    target = library / "Show" / "Show - S01E01.mkv"
    plan_id = saved(conn, move(source, target))

    apply_plan(conn, plan_id, now=NOW)

    assert [path.name for path in (library / "Show").iterdir()] == ["Show - S01E01.mkv"]
    assert states(conn, plan_id) == [ChangeState.DONE]


def test_applying_again_changes_nothing_more(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    source = video(downloads / "a.mkv")
    plan_id = saved(conn, move(source, library / "a.mkv"))
    apply_plan(conn, plan_id, now=NOW)

    assert apply_plan(conn, plan_id, now=NOW).count == 0


def test_a_duplicate_goes_to_quarantine_and_comes_back(
    conn: sqlite3.Connection, downloads: Path, tmp_path: Path
):
    duplicate = video(downloads / "Glass Orchard 07.avi")
    place = tmp_path / "Maku quarantine" / "2026-10-10" / "Glass Orchard 07.avi"
    reason = "Kept [GRP] Glass_Orchard_07 (720p).mkv instead: higher resolution"
    quarantine = Change(
        ChangeKind.QUARANTINE, duplicate, place, "Glass Orchard · duplicate", reason
    )
    plan_id = saved(conn, quarantine)

    apply_plan(conn, plan_id, now=NOW)
    assert place.exists()
    assert not duplicate.exists()

    undo_plan(conn, plan_id, now=NOW)
    assert duplicate.exists()
    assert not (tmp_path / "Maku quarantine").exists()


def test_undo_puts_everything_back_and_removes_only_the_folders_maku_made(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    already = video(library / "Other show" / "x.mkv")
    first, second = video(downloads / "07.mkv"), video(downloads / "08.mkv")
    season = library / "Glass Orchard (2012)" / "Season 01"
    plan_id = saved(conn, move(first, season / "07.mkv"), move(second, season / "08.mkv"))
    apply_plan(conn, plan_id, now=NOW)

    outcome = undo_plan(conn, plan_id, now=NOW)

    assert (outcome.count, outcome.problems) == (2, ())
    assert first.exists()
    assert second.exists()
    assert not (library / "Glass Orchard (2012)").exists()
    assert already.exists()
    assert states(conn, plan_id) == [ChangeState.UNDONE, ChangeState.UNDONE]
    undone = conn.execute("SELECT undone_at FROM plans WHERE id = ?", (plan_id,)).fetchone()
    assert undone["undone_at"] == "2026-10-10T20:00:00+00:00"


def test_undo_leaves_a_file_where_it_is_when_its_old_name_is_taken(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    source = video(downloads / "a.mkv", "the first")
    target = library / "Show" / "a.mkv"
    plan_id = saved(conn, move(source, target))
    apply_plan(conn, plan_id, now=NOW)
    video(source, "a new file with the old name")

    outcome = undo_plan(conn, plan_id, now=NOW)

    [kept] = outcome.problems
    assert kept.state is ChangeState.DONE
    assert kept.problem == (
        f"Maku couldn't put it back. a.mkv is already in {downloads}, and Maku never overwrites"
        " a file."
    )
    assert target.read_text(encoding="utf-8") == "the first"
    assert source.read_text(encoding="utf-8") == "a new file with the old name"


def test_undo_says_so_when_a_file_was_moved_away(
    conn: sqlite3.Connection, downloads: Path, library: Path, tmp_path: Path
):
    target = library / "a.mkv"
    plan_id = saved(conn, move(video(downloads / "a.mkv"), target))
    apply_plan(conn, plan_id, now=NOW)
    target.rename(tmp_path / "elsewhere.mkv")

    outcome = undo_plan(conn, plan_id, now=NOW)

    assert [change.problem for change in outcome.problems] == [
        f"Maku couldn't put it back. It isn't at {target} any more."
    ]


def test_a_move_to_another_drive_copies_then_removes_the_original(
    conn: sqlite3.Connection, downloads: Path, library: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(changes, "_same_drive", on_other_drives)
    source = video(downloads / "a.mkv")
    target = library / "Show" / "a.mkv"
    plan_id = saved(conn, move(source, target))

    assert apply_plan(conn, plan_id, now=NOW).count == 1

    assert target.read_text(encoding="utf-8") == "video"
    assert not source.exists()
    assert sorted(path.name for path in target.parent.iterdir()) == ["a.mkv"]


def test_a_copy_that_fails_leaves_the_original_and_no_trace(
    conn: sqlite3.Connection, downloads: Path, library: Path, monkeypatch: pytest.MonkeyPatch
):
    def disk_full(source: Path, destination: Path) -> None:
        destination.write_text("half a file", encoding="utf-8")
        raise OSError(28, "There is not enough space on the disk")

    monkeypatch.setattr(changes, "_same_drive", on_other_drives)
    monkeypatch.setattr(changes.shutil, "copy2", disk_full)
    source = video(downloads / "a.mkv")
    plan_id = saved(conn, move(source, library / "Show" / "a.mkv"))

    outcome = apply_plan(conn, plan_id, now=NOW)

    assert [change.problem for change in outcome.problems] == [
        "There is not enough space on the disk."
    ]
    assert source.read_text(encoding="utf-8") == "video"
    assert not (library / "Show").exists()


def test_recover_finds_a_move_that_happened(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    source = video(downloads / "a.mkv")
    target = library / "a.mkv"
    plan_id = saved(conn, move(source, target))
    source.rename(target)
    crash_while(conn, ChangeState.MOVING, [])

    assert recover(conn) == 1

    assert states(conn, plan_id) == [ChangeState.DONE]


def test_recover_counts_only_a_tidy_ups_moves(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    source = video(downloads / "a.mkv")
    plan = Plan((move(source, library / "a.mkv"),))
    save_plan(conn, plan, "Converted a", now=NOW, kind="convert")
    crash_while(conn, ChangeState.MOVING, [])

    assert recover(conn) == 0  # the queue settles a conversion, and says so


def test_recover_plans_again_a_move_that_had_not_started(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    source = video(downloads / "a.mkv")
    season = library / "Show" / "Season 01"
    plan_id = saved(conn, move(source, season / "a.mkv"))
    season.mkdir(parents=True)
    crash_while(conn, ChangeState.MOVING, [library / "Show", season])

    recover(conn)

    [change] = changes_of(conn, plan_id)
    assert (change.state, change.created_dirs) == (ChangeState.PLANNED, ())
    assert not (library / "Show").exists()
    assert apply_plan(conn, plan_id, now=NOW).count == 1  # and applying carries on


def test_recover_removes_an_unfinished_copy(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    source = video(downloads / "a.mkv")
    target = library / "a.mkv"
    plan_id = saved(conn, move(source, target))
    partial = video(library / f"a.mkv{PARTIAL}", "half a file")
    crash_while(conn, ChangeState.MOVING, [])

    recover(conn)

    assert not partial.exists()
    assert source.exists()
    assert states(conn, plan_id) == [ChangeState.PLANNED]


def test_recover_finishes_a_copy_that_was_already_in_place(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    source = video(downloads / "a.mkv")
    target = library / "a.mkv"
    plan_id = saved(conn, move(source, target))
    shutil.copy2(source, target)  # the copy was in place; the original wasn't removed yet
    crash_while(conn, ChangeState.MOVING, [])

    recover(conn)

    assert not source.exists()
    assert target.exists()
    assert states(conn, plan_id) == [ChangeState.DONE]


def test_recover_keeps_both_files_when_they_differ(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    source = video(downloads / "a.mkv", "the original")
    target = video(library / "a.mkv", "a different file that appeared meanwhile")
    plan_id = saved(conn, move(source, target))
    crash_while(conn, ChangeState.MOVING, [])

    recover(conn)

    [change] = changes_of(conn, plan_id)
    assert change.state is ChangeState.FAILED
    assert change.problem == (
        f"Maku stopped while moving it, and both places hold a file: {source} and {target}."
    )
    assert source.exists()
    assert target.exists()


@pytest.mark.parametrize(("moved_back", "state"), [(True, "undone"), (False, "done")])
def test_recover_settles_an_interrupted_undo(
    conn: sqlite3.Connection, downloads: Path, library: Path, moved_back: bool, state: str
):
    source = video(downloads / "a.mkv")
    target = library / "Show" / "a.mkv"
    plan_id = saved(conn, move(source, target))
    apply_plan(conn, plan_id, now=NOW)
    if moved_back:
        target.rename(source)
    crash_while(conn, ChangeState.UNDOING, [library / "Show"])

    recover(conn)

    assert states(conn, plan_id) == [ChangeState(state)]
    assert (library / "Show").exists() is not moved_back


def test_there_is_nothing_to_recover_after_a_clean_stop(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    plan_id = saved(conn, move(video(downloads / "a.mkv"), library / "a.mkv"))
    apply_plan(conn, plan_id, now=NOW)

    assert recover(conn) == 0


def in_library(conn: sqlite3.Connection, folder: Path) -> None:
    with conn:
        conn.execute("INSERT INTO folders (path, added_at) VALUES (?, ?)", (str(folder), "now"))


def test_folders_a_tidy_up_empties_are_removed_and_come_back_on_undo(
    conn: sqlite3.Connection, library: Path
):
    in_library(conn, library)
    release = library / "[Group] The Harbour Line [480p]" / "Extras"
    source = video(release / "The Harbour Line - 001.mkv")
    target = (
        library
        / "TV"
        / "The Harbour Line (2019)"
        / "Season 01"
        / "The Harbour Line (2019) - S01E01.mkv"
    )
    plan_id = saved(conn, move(source, target))

    apply_plan(conn, plan_id, now=NOW)

    assert not (library / "[Group] The Harbour Line [480p]").exists()  # emptied, so removed
    assert library.exists()  # the library folder itself always stays

    undo_plan(conn, plan_id, now=NOW)

    assert source.read_text(encoding="utf-8") == "video"
    assert not (library / "TV").exists()


def test_a_folder_with_anything_else_in_it_stays(conn: sqlite3.Connection, library: Path):
    in_library(conn, library)
    release = library / "[Group] The Harbour Line [480p]"
    source = video(release / "The Harbour Line - 001.mkv")
    (release / "folder.jpg").write_bytes(b"cover")
    target = (
        library
        / "TV"
        / "The Harbour Line (2019)"
        / "Season 01"
        / "The Harbour Line (2019) - S01E01.mkv"
    )

    apply_plan(conn, saved(conn, move(source, target)), now=NOW)

    assert (release / "folder.jpg").exists()


def test_a_folder_outside_the_library_is_left_alone(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    in_library(conn, library)
    source = video(downloads / "Season 1" / "Glass Orchard 07.mkv")
    target = (
        library / "TV" / "Glass Orchard (2012)" / "Season 01" / "Glass Orchard (2012) - S01E07.mkv"
    )

    apply_plan(conn, saved(conn, move(source, target)), now=NOW)

    assert (downloads / "Season 1").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows'")
def test_a_junction_is_never_removed_by_a_tidy_up(
    conn: sqlite3.Connection, library: Path, tmp_path: Path
):
    in_library(conn, library)
    elsewhere = tmp_path / "Films on another drive"
    video(elsewhere / "Northern Lights.mkv")
    movies = library / "Movies"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(movies), str(elsewhere)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    plan_id = saved(
        conn,
        move(
            movies / "Northern Lights.mkv",
            movies / "Northern Lights (2004)" / "Northern Lights (2004).mkv",
        ),
    )

    apply_plan(conn, plan_id, now=NOW)

    assert movies.is_junction()
    assert (elsewhere / "Northern Lights (2004)" / "Northern Lights (2004).mkv").exists()


def recorded(conn: sqlite3.Connection, folder: Path, *files: Path) -> None:
    """The library's records of these videos, as a scan leaves them."""
    with conn:
        conn.execute("INSERT INTO folders (path, added_at) VALUES (?, ?)", (str(folder), "now"))
        conn.executemany(
            """INSERT INTO files (folder_id, path, size, modified, found_at, seen_at)
               VALUES (1, ?, 5, 0, 'now', 'now')""",
            [(str(file),) for file in files],
        )


def where(conn: sqlite3.Connection) -> list[tuple[str, str | None]]:
    rows = conn.execute("SELECT path, gone_at FROM files ORDER BY id")
    return [(Path(row["path"]).name, row["gone_at"]) for row in rows]


def test_a_videos_record_goes_with_it_and_back(
    conn: sqlite3.Connection, downloads: Path, library: Path, tmp_path: Path
):
    kept, duplicate = video(downloads / "07.mkv"), video(downloads / "07.avi")
    recorded(conn, tmp_path, kept, duplicate)
    place = tmp_path / "Maku quarantine" / "2026-10-10" / "07.avi"
    plan_id = saved(
        conn,
        Change(ChangeKind.QUARANTINE, duplicate, place, "Glass Orchard · duplicate", "Kept 07.mkv"),
        move(kept, library / "Glass Orchard (2012)" / "Season 01" / "S01E07.mkv"),
    )

    apply_plan(conn, plan_id, now=NOW)

    assert where(conn) == [("S01E07.mkv", None), ("07.avi", "2026-10-10T20:00:00+00:00")]
    assert conn.execute("SELECT path FROM files WHERE id = 1").fetchone()[0] == str(
        library / "Glass Orchard (2012)" / "Season 01" / "S01E07.mkv"
    )

    undo_plan(conn, plan_id, now=NOW)

    assert where(conn) == [("07.mkv", None), ("07.avi", None)]


def test_a_record_follows_a_move_recover_finds(
    conn: sqlite3.Connection, downloads: Path, library: Path, tmp_path: Path
):
    source = video(downloads / "a.mkv")
    recorded(conn, tmp_path, source)
    plan_id = saved(conn, move(source, library / "a.mkv"))
    source.rename(library / "a.mkv")
    crash_while(conn, ChangeState.MOVING, [])

    recover(conn)

    assert states(conn, plan_id) == [ChangeState.DONE]
    assert where(conn) == [("a.mkv", None)]
    assert conn.execute("SELECT path FROM files").fetchone()[0] == str(library / "a.mkv")


def test_a_record_a_scan_made_at_the_new_place_gives_way(
    conn: sqlite3.Connection, downloads: Path, library: Path, tmp_path: Path
):
    source = video(downloads / "a.mkv")
    recorded(conn, tmp_path, source, library / "a.mkv")  # a scan saw it land, unidentified
    with conn:
        conn.execute("UPDATE files SET pinned = 1 WHERE id = 1")
    plan_id = saved(conn, move(source, library / "a.mkv"))

    apply_plan(conn, plan_id, now=NOW)

    rows = conn.execute("SELECT id, path, pinned FROM files").fetchall()
    assert [tuple(row) for row in rows] == [(1, str(library / "a.mkv"), 1)]


def test_putting_back_copies_set_aside_on_one_day_leaves_no_empty_quarantine(
    conn: sqlite3.Connection, downloads: Path, tmp_path: Path
):
    day = tmp_path / "Maku quarantine" / "2026-10-10"
    first, second = video(downloads / "a.avi"), video(downloads / "b.avi")
    plans = [
        saved(conn, Change(ChangeKind.QUARANTINE, file, day / file.name, "Copy", "Kept the other"))
        for file in (first, second)
    ]
    for plan_id in plans:
        apply_plan(conn, plan_id, now=NOW)

    for plan_id in plans:  # the first made the folders, and is put back first
        undo_plan(conn, plan_id, now=NOW)

    assert first.exists()
    assert second.exists()
    assert not (tmp_path / "Maku quarantine").exists()


def applied_at(conn: sqlite3.Connection, plan_id: int) -> str | None:
    row = conn.execute("SELECT applied_at FROM plans WHERE id = ?", (plan_id,)).fetchone()
    return row["applied_at"]


def undone_at(conn: sqlite3.Connection, plan_id: int) -> str | None:
    row = conn.execute("SELECT undone_at FROM plans WHERE id = ?", (plan_id,)).fetchone()
    return row["undone_at"]


def test_a_crash_while_applying_leaves_the_plan_in_history_and_closes_the_rest(
    conn: sqlite3.Connection, downloads: Path, library: Path, monkeypatch: pytest.MonkeyPatch
):
    first, second = video(downloads / "a.mkv"), video(downloads / "b.mkv")
    plan_id = saved(conn, move(first, library / "a.mkv"), move(second, library / "b.mkv"))
    renames = 0
    rename = Path.rename

    def stop_at_the_second(path: Path, target: Path) -> Path:
        nonlocal renames
        renames += 1
        if renames == 2:
            raise KeyboardInterrupt  # the engine stopping mid-way
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", stop_at_the_second)
    with pytest.raises(KeyboardInterrupt):
        apply_plan(conn, plan_id, now=NOW)
    monkeypatch.undo()

    assert applied_at(conn, plan_id) == "2026-10-10T20:00:00+00:00"
    recover(conn, now=NOW)

    [made, closed] = changes_of(conn, plan_id)
    assert made.state is ChangeState.DONE
    assert (closed.state, closed.problem) == (
        ChangeState.FAILED,
        "Maku stopped before making this change. Tidy up proposes it again.",
    )
    assert second.exists()


def test_a_change_is_done_only_once_its_record_has_moved_too(
    conn: sqlite3.Connection,
    downloads: Path,
    library: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = video(downloads / "a.mkv")
    recorded(conn, tmp_path, source)
    plan_id = saved(conn, move(source, library / "a.mkv"))

    def stop(*_: object, **__: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(changes, "_follow", stop)
    with pytest.raises(KeyboardInterrupt):
        apply_plan(conn, plan_id, now=NOW)
    monkeypatch.undo()

    assert states(conn, plan_id) == [ChangeState.MOVING]  # so recover settles it
    recover(conn, now=NOW)
    assert states(conn, plan_id) == [ChangeState.DONE]
    assert conn.execute("SELECT path FROM files").fetchone()[0] == str(library / "a.mkv")


def test_a_plan_stays_undoable_until_everything_is_back(
    conn: sqlite3.Connection, downloads: Path, library: Path
):
    a, b = video(downloads / "a.mkv"), video(downloads / "b.mkv")
    plan_id = saved(conn, move(a, library / "a.mkv"), move(b, library / "b.mkv"))
    apply_plan(conn, plan_id, now=NOW)
    blocker = video(a, "a new file with the old name")

    first = undo_plan(conn, plan_id, now=NOW)

    assert [change.source.name for change in first.changed] == ["b.mkv"]
    assert [change.source.name for change in first.problems] == ["a.mkv"]
    assert undone_at(conn, plan_id) is None
    blocker.unlink()

    second = undo_plan(conn, plan_id, now=NOW)

    assert ([c.source.name for c in second.changed], second.problems) == (["a.mkv"], ())
    assert undone_at(conn, plan_id) == "2026-10-10T20:00:00+00:00"
