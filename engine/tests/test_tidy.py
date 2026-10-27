"""Tidying up a real library in a temporary folder: what Maku proposes, applying it, undoing it."""

import sqlite3
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

from maku.config import DataPaths
from maku.reports import write_reports
from maku.tidy import ProposalChangedError, Proposed, Reviewed, apply, propose, undo
from tests.services import internet, with_key
from tests.shelf import NOW, identify, library


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "Videos"


@pytest.fixture
def downloads(paths: DataPaths, conn: sqlite3.Connection, root: Path) -> sqlite3.Connection:
    """A Downloads folder holding two series, as on the tidy board, and a show of its own."""
    library(
        conn,
        root,
        [
            "Downloads/[Group] The_Harbour_Line_-_01_(BD_720p).mkv",
            "Downloads/[Group] The_Harbour_Line_-_02_(BD_720p).mkv",
            "Downloads/Glass Orchard - 015.mkv",
            "Glass Orchard/Glass Orchard - 001.mkv",
        ],
        minutes=45,
    )
    identify(with_key(paths), conn, internet())
    return conn


def harbour(paths: DataPaths, conn: sqlite3.Connection, root: Path, names: list[str]) -> None:
    """These videos of The Harbour Line in the library, identified."""
    library(conn, root, names, minutes=45)
    identify(with_key(paths), conn, internet())


def reviewed(changes: Iterable[Proposed]) -> list[Reviewed]:
    """Changes as the owner saw them, which is what applying is given."""
    return [Reviewed(str(p.change.source), p.change.kind, str(p.change.target)) for p in changes]


def where(root: Path) -> list[str]:
    """Every file under the library folder, relative to it."""
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


LINE = r"TV\The Harbour Line (2019)\Season 01\The Harbour Line (2019)"
ORCHARD = r"TV\Glass Orchard (2012)"


def test_maku_proposes_plexs_layout_and_says_which_moves_leave_a_mixed_folder(
    downloads: sqlite3.Connection, root: Path
):
    proposal = propose(downloads, day=NOW.date())

    found = [
        (p.category, p.title, p.change.source.name, str(p.change.target.relative_to(root)))
        for p in proposal.changes
    ]
    assert found == [
        (
            "rename",
            "Glass Orchard",
            "Glass Orchard - 001.mkv",
            rf"{ORCHARD}\Season 01\Glass Orchard (2012) - S01E01.mkv",
        ),
        (
            "mixed",
            "Glass Orchard",
            "Glass Orchard - 015.mkv",
            rf"{ORCHARD}\Season 02\Glass Orchard (2012) - S02E03.mkv",
        ),
        (
            "mixed",
            "The Harbour Line",
            "[Group] The_Harbour_Line_-_01_(BD_720p).mkv",
            rf"{LINE} - S01E01 - Pilot.mkv",
        ),
        (
            "mixed",
            "The Harbour Line",
            "[Group] The_Harbour_Line_-_02_(BD_720p).mkv",
            rf"{LINE} - S01E02 - Low Tide.mkv",
        ),
    ]
    assert proposal.changes[0].root == root
    assert proposal.skipped == ()


def test_applying_files_the_videos_and_keeps_what_they_are(
    downloads: sqlite3.Connection, root: Path
):
    (root / "Glass Orchard" / "Glass Orchard - 001.en.srt").write_text("subtitles", "utf-8")
    write_reports(downloads, now=NOW)  # a gap analysis in the show's own folder
    changes = reviewed(propose(downloads, day=NOW.date()).changes)

    done = apply(downloads, changes, now=NOW)

    assert (done.moved, done.quarantined, done.problems) == (5, 0, ())
    assert where(root) == [
        rf"{ORCHARD}\Maku - Gap analysis.md",
        rf"{ORCHARD}\Season 01\Glass Orchard (2012) - S01E01.en.srt",
        rf"{ORCHARD}\Season 01\Glass Orchard (2012) - S01E01.mkv",
        rf"{ORCHARD}\Season 02\Glass Orchard (2012) - S02E03.mkv",
        r"TV\The Harbour Line (2019)\Maku - Gap analysis.md",
        rf"{LINE} - S01E01 - Pilot.mkv",
        rf"{LINE} - S01E02 - Low Tide.mkv",
    ]  # the emptied folders went, the old report with them
    rows = downloads.execute(
        "SELECT path, matched, season, episode FROM files WHERE gone_at IS NULL ORDER BY path"
    ).fetchall()
    assert [(Path(row[0]).name, *tuple(row)[1:]) for row in rows] == [
        ("Glass Orchard (2012) - S01E01.mkv", "sure", 1, 1),
        ("Glass Orchard (2012) - S02E03.mkv", "sure", 2, 3),
        ("The Harbour Line (2019) - S01E01 - Pilot.mkv", "sure", 1, 1),
        ("The Harbour Line (2019) - S01E02 - Low Tide.mkv", "sure", 1, 2),
    ]
    assert propose(downloads, day=NOW.date()).changes == ()  # nothing left to tidy


def test_a_video_left_out_keeps_its_subtitles_with_it(downloads: sqlite3.Connection, root: Path):
    (root / "Glass Orchard" / "Glass Orchard - 001.en.srt").write_text("subtitles", "utf-8")
    proposal = propose(downloads, day=NOW.date()).changes
    [video] = [p for p in proposal if p.change.source.name == "Glass Orchard - 001.mkv"]
    [subtitles] = [p for p in proposal if p.change.source.name.endswith(".en.srt")]
    assert (video.video, subtitles.video) == (video.change.source, video.change.source)

    apply(downloads, reviewed(p for p in proposal if p is not video), now=NOW)  # skipped

    assert (root / "Glass Orchard" / "Glass Orchard - 001.mkv").exists()
    assert (root / "Glass Orchard" / "Glass Orchard - 001.en.srt").exists()  # stayed with it


def test_subtitles_two_copies_share_go_with_the_copy_kept(
    paths: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(
        conn,
        root,
        ["Glass Orchard/Glass Orchard - 001.mkv", "Glass Orchard/Glass Orchard - 001.mp4"],
        minutes=45,
    )
    (root / "Glass Orchard" / "Glass Orchard - 001.en.srt").write_text("subtitles", "utf-8")
    identify(with_key(paths), conn, internet())
    proposal = propose(conn, day=NOW.date()).changes
    [kept] = [p for p in proposal if p.change.source.suffix == ".mkv"]
    [subtitles] = [p for p in proposal if p.change.source.name.endswith(".en.srt")]
    assert subtitles.video == kept.change.source  # not the copy set aside, whose name fits too

    apply(conn, reviewed(p for p in proposal if p.category != "duplicate"), now=NOW)

    assert rf"{ORCHARD}\Season 01\Glass Orchard (2012) - S01E01.en.srt" in where(root)


def test_undo_puts_it_all_back(downloads: sqlite3.Connection, root: Path):
    before = where(root)
    done = apply(downloads, reviewed(propose(downloads, day=NOW.date()).changes), now=NOW)
    assert done.plan_id is not None

    back = undo(downloads, done.plan_id, now=NOW)

    assert (back.moved, back.problems) == (4, ())
    assert where(root) == before
    paths = {Path(row[0]).name for row in downloads.execute("SELECT path FROM files")}
    assert "Glass Orchard - 015.mkv" in paths


def test_undo_leaves_a_video_being_converted_where_it_is(downloads: sqlite3.Connection, root: Path):
    done = apply(downloads, reviewed(propose(downloads, day=NOW.date()).changes), now=NOW)
    assert done.plan_id is not None
    pilot = downloads.execute("SELECT id FROM files WHERE path LIKE '%Line (2019) - S01E01%'")
    with downloads:
        downloads.execute(
            "INSERT INTO jobs (file_id, method, position, state, added_at)"
            " VALUES (?, 'best', 1, 'running', 'now')",
            (pilot.fetchone()[0],),
        )

    back = undo(downloads, done.plan_id, now=NOW)

    assert back.moved == 3
    assert [p.problem for p in back.problems] == [
        "Maku couldn't put it back. It's being converted: put it back once it's done."
    ]


def test_undo_leaves_a_video_getting_english_subtitles_where_it_is(
    downloads: sqlite3.Connection, root: Path
):
    done = apply(downloads, reviewed(propose(downloads, day=NOW.date()).changes), now=NOW)
    assert done.plan_id is not None
    pilot = downloads.execute("SELECT id FROM files WHERE path LIKE '%Line (2019) - S01E01%'")
    with downloads:
        downloads.execute(
            "INSERT INTO jobs (file_id, kind, method, position, state, added_at)"
            " VALUES (?, 'subtitles', 'best', 1, 'running', 'now')",
            (pilot.fetchone()[0],),
        )

    back = undo(downloads, done.plan_id, now=NOW)

    assert [p.problem for p in back.problems] == [
        "Maku couldn't put it back. Its English subtitles are being made: put it back once "
        "they're done."
    ]


def test_only_the_files_asked_for_move(downloads: sqlite3.Connection, root: Path):
    proposal = propose(downloads, day=NOW.date())
    orchard = reviewed(p for p in proposal.changes if p.title == "Glass Orchard")

    done = apply(downloads, orchard, now=NOW)

    assert done.moved == 2
    assert r"Downloads\[Group] The_Harbour_Line_-_01_(BD_720p).mkv" in where(root)
    title = downloads.execute("SELECT title FROM plans WHERE id = ?", (done.plan_id,)).fetchone()
    assert title[0] == "Tidied 2 files: Glass Orchard"


def test_a_change_proposed_differently_now_stops_them_all(
    downloads: sqlite3.Connection, root: Path
):
    before = where(root)
    changes = reviewed(propose(downloads, day=NOW.date()).changes)
    changes[-1] = Reviewed(changes[-1].source, changes[-1].kind, str(root / "Elsewhere.mkv"))

    with pytest.raises(ProposalChangedError):
        apply(downloads, changes, now=NOW)

    assert where(root) == before


def test_nothing_asked_for_changes_nothing(downloads: sqlite3.Connection, root: Path):
    before = where(root)

    done = apply(downloads, [], now=NOW)

    assert (done.plan_id, done.moved) == (None, 0)
    assert where(root) == before


def test_a_second_copy_is_set_aside_unless_the_owner_keeps_it(
    paths: DataPaths, conn: sqlite3.Connection, root: Path
):
    harbour(
        paths,
        conn,
        root,
        ["Harbour/The Harbour Line - 01.mkv", "Harbour/The Harbour Line - 01 (copy).mkv"],
    )

    proposal = propose(conn, day=NOW.date())

    [duplicate] = proposal.duplicates
    assert duplicate.label == "The Harbour Line · S01E01"
    assert duplicate.keep.path.name == "The Harbour Line - 01.mkv"
    assert [copy.path.name for copy in duplicate.drop] == ["The Harbour Line - 01 (copy).mkv"]
    assert duplicate.reason == (
        "Kept The Harbour Line - 01.mkv instead: the other is named as a copy"
    )
    first = proposal.changes[0]
    assert (first.category, first.change.kind.value) == ("duplicate", "quarantine")

    swapped = propose(conn, day=NOW.date(), keep=[str(duplicate.drop[0].path)])

    assert swapped.duplicates[0].keep.path.name == "The Harbour Line - 01 (copy).mkv"
    assert swapped.duplicates[0].reason.endswith("instead: you chose it")


def test_a_quarantined_copy_leaves_the_library_until_its_put_back(
    paths: DataPaths, conn: sqlite3.Connection, root: Path, tmp_path: Path
):
    harbour(
        paths,
        conn,
        root,
        ["Harbour/The Harbour Line - 01.mkv", "Harbour/The Harbour Line - 01 (copy).mkv"],
    )
    done = apply(conn, reviewed(propose(conn, day=NOW.date()).changes), now=NOW)

    assert (done.moved, done.quarantined) == (1, 1)
    gone = conn.execute("SELECT path FROM files WHERE gone_at IS NOT NULL").fetchone()
    set_aside = Path(gone[0])
    assert set_aside.parent.parent.name == "Maku quarantine"
    assert set_aside.is_file()
    assert done.plan_id is not None

    undo(conn, done.plan_id, now=NOW)

    assert conn.execute("SELECT COUNT(*) FROM files WHERE gone_at IS NULL").fetchone()[0] == 2
    assert not set_aside.exists()
    assert (root / "Harbour" / "The Harbour Line - 01 (copy).mkv").is_file()


def test_a_special_maku_cant_number_stays_where_it_is(
    paths: DataPaths, conn: sqlite3.Connection, root: Path
):
    harbour(paths, conn, root, ["Harbour/The Harbour Line - 01.mkv"])
    with conn:
        conn.execute("UPDATE files SET season = 0, episode = NULL")

    proposal = propose(conn, day=NOW.date())

    assert proposal.changes == ()
    assert [(path.name, why) for path, why in proposal.skipped] == [
        ("The Harbour Line - 01.mkv", "Maku doesn't know which episode it is")
    ]


def test_a_film_in_two_files_is_filed_as_its_two_parts(
    paths: DataPaths, conn: sqlite3.Connection, root: Path
):
    names = [f"Movies/The Lantern Keeper (2016) CD{part}.mkv" for part in (1, 2)]
    library(conn, root, names, minutes=52)
    identify(with_key(paths), conn, internet())

    proposal = propose(conn, day=NOW.date())

    film = r"Movies\The Lantern Keeper (2016)\The Lantern Keeper (2016)"
    assert [str(p.change.target.relative_to(root)) for p in proposal.changes] == [
        f"{film} - pt1.mkv",
        f"{film} - pt2.mkv",
    ]
    assert proposal.duplicates == ()


def test_one_file_named_part_2_is_a_whole_film(
    paths: DataPaths, conn: sqlite3.Connection, root: Path
):
    library(conn, root, ["Movies/The Lantern Keeper (2016) Part 2.mkv"], minutes=104)
    identify(with_key(paths), conn, internet())

    [proposed] = propose(conn, day=NOW.date()).changes

    assert proposed.change.target.name == "The Lantern Keeper (2016).mkv"


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows'")
def test_a_folder_that_is_a_link_is_never_a_place_to_file(
    paths: DataPaths, conn: sqlite3.Connection, root: Path, tmp_path: Path
):
    harbour(paths, conn, root, ["Harbour/The Harbour Line - 01.mkv"])
    (tmp_path / "Elsewhere").mkdir()
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(root / "TV"), str(tmp_path / "Elsewhere")],  # noqa: S607
        check=True,
        capture_output=True,
    )

    proposal = propose(conn, day=NOW.date())

    assert proposal.changes == ()
    assert [(path.name, why) for path, why in proposal.skipped] == [
        ("The Harbour Line - 01.mkv", "Its new folder is a link to another place, which scans skip")
    ]


def test_a_copy_is_never_set_aside_on_top_of_one_set_aside_earlier(
    paths: DataPaths, conn: sqlite3.Connection, root: Path
):
    harbour(
        paths,
        conn,
        root,
        ["Harbour/The Harbour Line - 01.mkv", "Harbour/The Harbour Line - 01 (copy).mkv"],
    )
    earlier = Path(root.anchor) / "Maku quarantine" / NOW.date().isoformat()
    earlier.mkdir(parents=True, exist_ok=True)
    (earlier / "The Harbour Line - 01 (copy).mkv").write_bytes(b"set aside this morning")

    first = propose(conn, day=NOW.date()).changes[0]

    assert first.change.target == earlier / "The Harbour Line - 01 (copy) (2).mkv"


def test_a_folder_already_there_keeps_its_own_spelling(
    paths: DataPaths, conn: sqlite3.Connection, root: Path
):
    (root / "tv" / "the harbour line (2019)" / "season 01").mkdir(parents=True)
    harbour(paths, conn, root, ["Downloads/The Harbour Line - 01.mkv"])

    [proposed] = propose(conn, day=NOW.date()).changes

    assert str(proposed.change.target) == str(
        root
        / "tv"
        / "the harbour line (2019)"
        / "season 01"
        / "The Harbour Line (2019) - S01E01 - Pilot.mkv"
    )


# Converting, or made and waiting beside its original for another app to let go of it.
BUSY = pytest.mark.parametrize(
    ("state", "retry_at"), [("running", None), ("queued", "2026-10-11T10:05:00+02:00")]
)
FIRST = "[Group] The_Harbour_Line_-_01_(BD_720p).mkv"


@BUSY
def test_a_video_being_converted_stays_where_it_is_till_its_done(
    downloads: sqlite3.Connection, root: Path, state: str, retry_at: str | None
):
    pilot = downloads.execute("SELECT id FROM files WHERE path LIKE '%Line_-_01%'").fetchone()[0]
    with downloads:
        downloads.execute(
            "INSERT INTO jobs (file_id, method, position, state, added_at, retry_at)"
            " VALUES (?, 'best', 1, ?, ?, ?)",
            (pilot, state, NOW.isoformat(), retry_at),
        )

    proposal = propose(downloads, day=NOW.date())

    assert FIRST not in {p.change.source.name for p in proposal.changes}
    assert (FIRST, "It's being converted") in {(path.name, why) for path, why in proposal.skipped}


def test_a_video_getting_english_subtitles_stays_where_it_is_till_theyre_made(
    downloads: sqlite3.Connection, root: Path
):
    pilot = downloads.execute("SELECT id FROM files WHERE path LIKE '%Line_-_01%'").fetchone()[0]
    with downloads:
        downloads.execute(
            "INSERT INTO jobs (file_id, kind, method, position, state, added_at)"
            " VALUES (?, 'subtitles', 'best', 1, 'running', ?)",
            (pilot, NOW.isoformat()),
        )

    proposal = propose(downloads, day=NOW.date())

    assert (FIRST, "Its English subtitles are being made") in {
        (path.name, why) for path, why in proposal.skipped
    }


def test_copies_of_a_video_being_converted_wait_for_it_too(
    paths: DataPaths, conn: sqlite3.Connection, root: Path
):
    harbour(
        paths,
        conn,
        root,
        ["Harbour/The Harbour Line - 01.mp4", "Downloads/The Harbour Line - 01.mkv"],
    )
    with conn:  # the MP4 becomes an MKV of the name the other copy would be filed under
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, state, added_at)"
            " SELECT id, 'best', 1, 'running', 'now' FROM files WHERE path LIKE '%.mp4'"
        )

    proposal = propose(conn, day=NOW.date())

    assert [p.change.source.name for p in proposal.changes] == []
    assert {(path.name, why) for path, why in proposal.skipped} == {
        ("The Harbour Line - 01.mp4", "It's being converted"),
        ("The Harbour Line - 01.mkv", "A copy of it is being converted"),
    }
    with conn:  # its English subtitles being made instead: they take no name a copy would
        conn.execute("UPDATE jobs SET kind = 'subtitles'")
    assert {path.name for path, _ in propose(conn, day=NOW.date()).skipped} == {
        "The Harbour Line - 01.mp4"
    }


def test_with_names_kept_a_video_moves_into_its_folder_under_its_own_name(
    downloads: sqlite3.Connection, root: Path
):
    with downloads:
        downloads.execute("INSERT INTO settings (key, value) VALUES ('naming', '\"keep\"')")

    proposal = propose(downloads, day=NOW.date())

    pilot = next(p for p in proposal.changes if p.change.source.name.startswith("[Group]"))
    assert str(pilot.change.target.relative_to(root)) == (
        rf"TV\The Harbour Line (2019)\Season 01\{FIRST}"
    )
