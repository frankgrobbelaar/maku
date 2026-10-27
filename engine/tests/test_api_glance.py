"""The library in a few numbers: how long it plays, how much was watched, what converting did to
its size, and the titles taking the most room."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from tests.shelf import library


def test_the_library_at_a_glance(client: TestClient, conn: sqlite3.Connection, tmp_path: Path):
    root = tmp_path / "Videos"
    library(
        conn,
        root,
        [
            "Starfall (2019)/Season 01/Starfall (2019) - S01E01.mkv",
            "Starfall (2019)/Season 01/Starfall (2019) - S01E02.mkv",
            "Lanterns (2021)/Lanterns (2021).mkv",
        ],
    )
    with conn:
        conn.execute("INSERT INTO titles (id, kind, name) VALUES (1, 'series', 'Starfall')")
        conn.execute("INSERT INTO titles (id, kind, name) VALUES (2, 'movie', 'Lanterns')")
        conn.execute("UPDATE files SET title_id = 1 WHERE id IN (1, 2)")
        conn.execute("UPDATE files SET title_id = 2, size = 9000 WHERE id = 3")
        conn.execute(
            """INSERT INTO watched (file_id, position, duration, played_at, watched_at)
               VALUES (1, 1440, 1440, 'then', 'then')"""
        )
        conn.execute(
            "INSERT INTO plans (id, title, created_at, undone_at) VALUES (5, 'x', 'a', 'b')"
        )
        conn.executemany(
            """INSERT INTO jobs (file_id, kind, method, position, state, added_at, source_size,
                                 output_size, plan_id)
               VALUES (?, 'convert', 'reencode', ?, 'done', 'then', ?, ?, ?)""",
            [
                (1, 1, 400, 300, None),
                (2, 2, 500, 450, 5),  # put back from History: the original is in place again
            ],
        )

    found = client.get("/library/glance").json()

    assert found["seconds"] == 3 * 1440
    assert found["watched"] == 1440
    assert found["converted"] == {"files": 1, "before": 400, "after": 300}
    assert [(each["name"], each["files"]) for each in found["biggest"]] == [
        ("Lanterns", 1),
        ("Starfall", 2),
    ]
    assert found["size"] == sum(row[0] for row in conn.execute("SELECT size FROM files"))
