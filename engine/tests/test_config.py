from pathlib import Path

import pytest

from maku.config import DataPaths


def test_data_lives_in_local_app_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("MAKU_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert DataPaths.default().root == tmp_path / "Maku"


def test_maku_data_dir_moves_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("MAKU_DATA_DIR", str(tmp_path / "Elsewhere"))

    assert DataPaths.default().root == tmp_path / "Elsewhere"


def test_a_maku_data_dir_with_dot_dots_is_tidied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("MAKU_DATA_DIR", f"{tmp_path}/app/../Elsewhere")

    assert DataPaths.default().root == tmp_path / "Elsewhere"


def test_the_database_and_logs_sit_inside_the_data_folder(tmp_path: Path):
    paths = DataPaths(tmp_path)

    assert paths.database == tmp_path / "maku.db"
    assert paths.logs == tmp_path / "logs"


def test_data_moved_to_another_drive_is_found_by_the_note_left_behind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    home, moved = tmp_path / "Maku", tmp_path / "F" / "Maku data"
    home.mkdir()
    (home / "location.txt").write_text(str(moved), encoding="utf-8")
    monkeypatch.setenv("MAKU_DATA_DIR", str(home))

    assert DataPaths.home() == home
    assert DataPaths.default().root == moved  # there or not: a drive may be unplugged


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-8"])
def test_the_note_is_read_in_the_uninstallers_encoding_or_an_older_makus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, encoding: str
):
    home, moved = tmp_path / "Maku", tmp_path / "ビデオ" / "Maku data"
    home.mkdir()
    (home / "location.txt").write_bytes(str(moved).encode(encoding))
    monkeypatch.setenv("MAKU_DATA_DIR", str(home))

    assert DataPaths.default().root == moved


def test_data_never_moved_has_no_note(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("MAKU_DATA_DIR", str(tmp_path / "Maku"))

    assert DataPaths.default().root == DataPaths.home() == tmp_path / "Maku"
