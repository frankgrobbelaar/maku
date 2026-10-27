import codecs
import csv
import io
import json
import sqlite3
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from maku import db
from maku.changes import apply_plan, save_plan
from maku.config import DataPaths
from maku.core.plan import Change, ChangeKind, Plan
from maku.export import export_data
from maku.library import add_folder, find_files, read_file, unread
from maku.migrations import MIGRATIONS
from tests.fake_ffprobe import REPORT

NOW = datetime(2026, 10, 10, 14, 20, tzinfo=UTC)


def _library_with_one_setting(paths: DataPaths) -> None:
    with closing(db.connect(paths.database)) as conn:
        db.migrate(conn)
        with conn:
            conn.execute(
                "INSERT INTO settings VALUES ('standard', ?)", [json.dumps("Cinema 1080p")]
            )


def test_export_writes_one_zip_with_the_database_settings_and_manifest(
    paths: DataPaths, tmp_path: Path
):
    _library_with_one_setting(paths)

    archive = export_data(paths, tmp_path / "exports", now=NOW)

    expected = tmp_path / "exports" / "Maku export 2026-10-10.zip"
    assert archive == expected
    with zipfile.ZipFile(expected) as zipped:
        assert sorted(zipped.namelist()) == [
            "changes.csv",
            "library.csv",
            "maku.db",
            "manifest.json",
            "settings.json",
        ]
        assert json.loads(zipped.read("settings.json")) == {"standard": "Cinema 1080p"}
        manifest = json.loads(zipped.read("manifest.json"))
        assert manifest["exportedAt"] == "2026-10-10T14:20:00+00:00"
        assert manifest["schemaVersion"] == len(MIGRATIONS)


def test_the_exported_database_opens_on_its_own(paths: DataPaths, tmp_path: Path):
    _library_with_one_setting(paths)
    archive = export_data(paths, tmp_path / "exports", now=NOW)
    assert archive is not None

    with zipfile.ZipFile(archive) as zipped:
        zipped.extract("maku.db", tmp_path / "unzipped")
    with closing(sqlite3.connect(tmp_path / "unzipped" / "maku.db")) as conn:
        assert conn.execute("SELECT key FROM settings").fetchall() == [("standard",)]


def test_the_export_lists_every_change_maku_made(paths: DataPaths, tmp_path: Path):
    source = tmp_path / "Downloads" / "La.Linea.del.Puerto.S01E07.720p.WEB-DL.x264-GRP.mkv"
    source.parent.mkdir()
    source.write_text("video", encoding="utf-8")
    target = (
        tmp_path
        / "Videos"
        / "La Línea del Puerto (2019)"
        / "La Línea del Puerto (2019) - S01E07.mkv"
    )
    with closing(db.connect(paths.database)) as conn:
        db.migrate(conn)
        change = Change(
            ChangeKind.MOVE, source, target, "La Línea del Puerto · S01E07", "Named and filed"
        )
        plan_id = save_plan(conn, Plan((change,)), "Tidy up: La Línea del Puerto", now=NOW)
        apply_plan(conn, plan_id, now=NOW)

    archive = export_data(paths, tmp_path / "exports", now=NOW)

    assert archive is not None
    with zipfile.ZipFile(archive) as zipped:
        raw = zipped.read("changes.csv")
    assert raw.startswith(codecs.BOM_UTF8)  # so Excel reads the title's accent
    assert list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))) == [
        {
            "plan": "1",
            "plan_title": "Tidy up: La Línea del Puerto",
            "planned_at": "2026-10-10T14:20:00+00:00",
            "applied_at": "2026-10-10T14:20:00+00:00",
            "undone_at": "",
            "position": "1",
            "kind": "move",
            "state": "done",
            "source": str(source),
            "target": str(target),
            "label": "La Línea del Puerto · S01E07",
            "reason": "Named and filed",
            "problem": "",
        }
    ]


def test_the_export_lists_every_video_in_the_library(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    folder = add_folder(conn, videos, now=NOW)
    find_files(conn, folder, stamp=NOW.isoformat())
    for file_id, path in unread(conn):
        read_file(conn, file_id, path, lambda _: REPORT, now=NOW)

    archive = export_data(paths, paths.root.parent / "exports", now=NOW)

    assert archive is not None
    with zipfile.ZipFile(archive) as zipped:
        raw = zipped.read("library.csv")
    assert raw.startswith(codecs.BOM_UTF8)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    movie = videos / "Northern Lights 2004.avi"
    assert {row["path"] for row in rows} == {
        str(movie),
        str(videos / "Downloads" / "Glass.Orchard.S01E01.720p.HDTV.x264-GRP.MKV"),
        str(videos / "The Harbour Line" / "The Harbour Line - S01E01 - Pilot.mkv"),
    }
    assert next(row for row in rows if row["path"] == str(movie)) == {
        "folder": str(videos),
        "path": str(movie),
        "size": str(movie.stat().st_size),
        "found_at": "2026-10-10T14:20:00+00:00",
        "gone_at": "",
        "read_at": "2026-10-10T14:20:00+00:00",
        "duration": "1244.202",
        "width": "720",
        "height": "540",
        "codec": "hevc",
        "problem": "",
        "title": "",
        "kind": "",
        "season": "",
        "episode": "",
        "matched": "",
    }


def test_the_library_list_says_what_each_video_is(
    paths: DataPaths, conn: sqlite3.Connection, videos: Path
):
    folder = add_folder(conn, videos, now=NOW)
    find_files(conn, folder, stamp=NOW.isoformat())
    with conn:
        conn.execute(
            "INSERT INTO titles (id, kind, name, year) VALUES (1, 'series', 'Glass Orchard', 2012)"
        )
        conn.execute(
            "UPDATE files SET title_id = 1, season = 1, episode = 1, matched = 'sure'"
            " WHERE path LIKE '%Glass.Orchard.S01E01%'"
        )

    archive = export_data(paths, paths.root.parent / "exports", now=NOW)

    assert archive is not None
    with zipfile.ZipFile(archive) as zipped:
        rows = list(csv.DictReader(io.StringIO(zipped.read("library.csv").decode("utf-8-sig"))))
    orchard = next(row for row in rows if "Glass.Orchard" in row["path"])
    assert (
        orchard["title"],
        orchard["kind"],
        orchard["season"],
        orchard["episode"],
        orchard["matched"],
    ) == ("Glass Orchard", "series", "1", "1", "sure")


def test_a_second_export_on_the_same_day_keeps_both(paths: DataPaths, tmp_path: Path):
    _library_with_one_setting(paths)

    first = export_data(paths, tmp_path, now=NOW)
    second = export_data(paths, tmp_path, now=NOW)

    assert first == tmp_path / "Maku export 2026-10-10.zip"
    assert second == tmp_path / "Maku export 2026-10-10 (2).zip"


def test_there_is_nothing_to_export_before_maku_has_data(paths: DataPaths, tmp_path: Path):
    assert export_data(paths, tmp_path, now=NOW) is None
    assert list(tmp_path.iterdir()) == []
