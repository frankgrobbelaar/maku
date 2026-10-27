"""The TMDB key: kept on this PC, encrypted by Windows, and never in the database or an export."""

import sqlite3
import zipfile
from pathlib import Path

from maku import credentials
from maku.config import DataPaths
from maku.export import export_data

KEY = "maku-test-token.the-owners-read-access-token.signature"


def test_a_key_is_kept_and_read_back(paths: DataPaths):
    credentials.save(paths, "tmdb", KEY)

    assert credentials.load(paths, "tmdb") == KEY


def test_the_file_never_holds_the_key_as_it_was_typed(paths: DataPaths):
    credentials.save(paths, "tmdb", KEY)

    stored = (paths.root / credentials.FILE).read_text(encoding="utf-8")
    assert "the-owners-read-access-token" not in stored
    assert "maku-test-token" not in stored


def test_forgetting_a_key_removes_it(paths: DataPaths):
    credentials.save(paths, "tmdb", KEY)

    credentials.forget(paths, "tmdb")

    assert credentials.load(paths, "tmdb") is None


def test_no_key_yet_is_none(paths: DataPaths):
    assert credentials.load(paths, "tmdb") is None


def test_a_file_from_another_pc_or_a_damaged_one_reads_as_no_key(paths: DataPaths):
    paths.root.mkdir(parents=True)
    (paths.root / credentials.FILE).write_text('{"tmdb": "bm90IG91cnM="}', encoding="utf-8")

    assert credentials.load(paths, "tmdb") is None

    (paths.root / credentials.FILE).write_text("not json", encoding="utf-8")
    assert credentials.load(paths, "tmdb") is None


def test_an_export_never_carries_the_key(
    paths: DataPaths, tmp_path: Path, conn: sqlite3.Connection
):
    credentials.save(paths, "tmdb", KEY)

    archive = export_data(paths, tmp_path / "exports")

    assert archive is not None
    with zipfile.ZipFile(archive) as exported:
        for name in exported.namelist():
            data = exported.read(name)
            assert KEY.encode() not in data
            assert b"the-owners-read-access-token" not in data
        assert credentials.FILE not in exported.namelist()
