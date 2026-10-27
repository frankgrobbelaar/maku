"""Moving Maku's data folder to another drive: asked for in Settings, done as the engine starts
again, the home folder keeping a note of where it went."""

import os
import shutil
from collections.abc import Generator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from maku import db
from maku.config import LOCATION, DataPaths
from maku.relocate import Moved, MoveError, ask_to_move, last_move, move_asked

NOW = datetime(2026, 10, 11, 21, 0, tzinfo=UTC)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Maku's data in its home folder: the database with a setting, a poster and a log."""
    root = tmp_path / "Maku"
    paths = DataPaths(root)
    with closing(db.connect(paths.database)) as conn, conn:
        db.migrate(conn)
        conn.execute("INSERT INTO settings (key, value) VALUES ('naming', '\"keep\"')")
    (paths.artwork / "1.jpg").parent.mkdir(parents=True)
    (paths.artwork / "1.jpg").write_bytes(b"a poster")
    (paths.logs / "engine.log").parent.mkdir(parents=True)
    (paths.logs / "engine.log").write_text("started\n", encoding="utf-8")
    return root


def setting(root: Path) -> object:
    with closing(db.connect(root / "maku.db")) as conn:
        return conn.execute("SELECT value FROM settings WHERE key = 'naming'").fetchone()[0]


def test_the_data_moves_as_the_engine_starts_and_the_home_keeps_a_note(home: Path, tmp_path: Path):
    target = tmp_path / "F" / "Maku data"
    ask_to_move(DataPaths(home), target)

    moved = move_asked(home, NOW)

    assert moved.root == target
    assert (target / "artwork" / "1.jpg").read_bytes() == b"a poster"
    assert (target / "logs" / "engine.log").is_file()
    assert setting(target) == '"keep"'
    assert sorted(path.name for path in home.iterdir()) == [LOCATION]  # the old copy went
    # In UTF-16, which the uninstaller reads whatever the path's letters.
    assert (home / LOCATION).read_bytes().decode("utf-16-le") == str(target)
    with closing(db.connect(target / "maku.db")) as conn:
        assert last_move(conn) == Moved(str(home), str(target), NOW.isoformat(), None)


def test_moving_back_home_leaves_no_note(home: Path, tmp_path: Path):
    target = tmp_path / "F" / "Maku data"
    ask_to_move(DataPaths(home), target)
    move_asked(home, NOW)

    ask_to_move(DataPaths(target), home)
    back = move_asked(home, NOW)

    assert back.root == home
    assert not (home / LOCATION).exists()
    assert not target.exists()
    assert setting(home) == '"keep"'


def test_nothing_asked_for_moves_nothing(home: Path):
    assert move_asked(home, NOW).root == home


def test_a_move_that_fails_leaves_everything_where_it_was_and_says_why(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "F" / "Maku data"
    ask_to_move(DataPaths(home), target)
    copy = shutil.copy2

    def full(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> object:
        if os.fspath(source).endswith("1.jpg"):  # copytree hands over each file's DirEntry
            raise OSError(28, "There is not enough space on the disk")
        return copy(source, destination)

    monkeypatch.setattr("maku.relocate.shutil.copy2", full)

    stayed = move_asked(home, NOW)

    assert stayed.root == home
    assert not target.exists()
    assert (home / "artwork" / "1.jpg").is_file()
    assert not (home / LOCATION).exists()
    with closing(db.connect(home / "maku.db")) as conn:
        found = last_move(conn)
    assert found is not None
    assert found.problem is not None
    assert "not enough space" in found.problem


def test_only_an_empty_or_new_folder_outside_makus_own_takes_the_data(home: Path, tmp_path: Path):
    busy = tmp_path / "Busy"
    busy.mkdir()
    (busy / "something.txt").write_text("mine", encoding="utf-8")

    with pytest.raises(MoveError, match="isn't empty"):
        ask_to_move(DataPaths(home), busy)
    with pytest.raises(MoveError, match="inside Maku's data folder"):
        ask_to_move(DataPaths(home), home / "artwork" / "new")
    with pytest.raises(MoveError, match="there already"):
        ask_to_move(DataPaths(home), home)


def test_a_drive_without_room_for_it_isnt_taken(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def small(path: object) -> SimpleNamespace:
        return SimpleNamespace(total=10**9, used=10**9 - 10, free=10)

    monkeypatch.setattr("maku.relocate.shutil.disk_usage", small)

    with pytest.raises(MoveError) as refused:
        ask_to_move(DataPaths(home), tmp_path / "F" / "Maku data")

    assert str(refused.value).startswith(f"There isn't room on {tmp_path.drive} for Maku's data:")


def test_a_move_cut_short_leaves_the_data_where_it_was_and_says_so(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "F" / "Maku data"
    ask_to_move(DataPaths(home), target)
    copy = shutil.copy2

    def power_cut(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> object:
        if os.fspath(source).endswith("1.jpg"):
            raise KeyboardInterrupt  # Maku stopped part-way: a power cut, or the app ending it
        return copy(source, destination)

    monkeypatch.setattr("maku.relocate.shutil.copy2", power_cut)
    with pytest.raises(KeyboardInterrupt):
        move_asked(home, NOW)
    monkeypatch.undo()

    stayed = move_asked(home, NOW)  # the next start

    assert stayed.root == home
    assert setting(home) == '"keep"'
    assert (home / "artwork" / "1.jpg").is_file()
    assert not target.exists()  # the part-made copy went, so the folder can be chosen again
    with closing(db.connect(home / "maku.db")) as conn:
        found = last_move(conn)
    assert found is not None
    assert found.problem == "Maku stopped while it moved the data, so it stayed where it was."


def test_a_move_cut_short_once_the_copy_was_in_place_is_finished_at_the_next_start(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "F" / "Maku data"
    ask_to_move(DataPaths(home), target)

    def power_cut(path: Path) -> None:
        raise KeyboardInterrupt  # as the old copy began to go

    monkeypatch.setattr("maku.relocate._remove", power_cut)
    with pytest.raises(KeyboardInterrupt):
        move_asked(home, NOW)
    monkeypatch.undo()

    moved = move_asked(home, NOW)  # the next start

    assert moved.root == target
    assert setting(target) == '"keep"'
    assert sorted(path.name for path in home.iterdir()) == [LOCATION]  # the old copy went
    with closing(db.connect(target / "maku.db")) as conn:
        assert last_move(conn) == Moved(str(home), str(target), NOW.isoformat(), None)


def test_while_the_data_moves_the_app_is_told_the_engine_is_still_starting(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "F" / "Maku data"
    ask_to_move(DataPaths(home), target)
    told: list[str] = []
    monkeypatch.setattr("maku.relocate.events.working", lambda: still(told))

    move_asked(home, NOW)

    assert told == ["working", "done"] * 2  # as it copies, and as the old copy goes


@contextmanager
def still(told: list[str]) -> Generator[None]:
    told.append("working")
    yield
    told.append("done")


def test_a_folder_on_another_computer_isnt_taken(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    with pytest.raises(MoveError, match="on another computer"):
        ask_to_move(DataPaths(home), Path(r"\\nas\videos\Maku data"))

    def mapped(path: Path) -> bool:  # a drive mapped to one
        return True

    monkeypatch.setattr("maku.relocate.on_network", mapped)

    with pytest.raises(MoveError, match="on another computer"):
        ask_to_move(DataPaths(home), tmp_path / "Z" / "Maku data")
