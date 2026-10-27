"""Preferences chosen during setup."""

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient


def test_a_new_maku_starts_from_the_recommended_choices(client: TestClient):
    assert client.get("/settings").json() == {
        "standard": "4k",  # the most a picture comes to: nothing is made bigger
        "naming": "plex",
        "setUp": False,
        "reports": True,
        "quarantineDays": 30,
        "originals": "quarantine",
        "artwork": False,
        "historyDays": None,  # History keeps everything till the owner chooses
        "healthCheck": True,  # every video test-played overnight
    }


def test_turning_the_pictures_off_takes_away_the_ones_maku_wrote(
    client: TestClient, conn: sqlite3.Connection, tmp_path: Path
):
    picture = tmp_path / "Starfall (2019)" / "poster.jpg"
    picture.parent.mkdir()
    picture.write_bytes(b"a poster")
    with conn:
        conn.execute("INSERT INTO titles (id, kind, name) VALUES (1, 'series', 'Starfall')")
        conn.execute(
            "INSERT INTO artwork_files (path, title_id, size, written_at) VALUES (?, 1, 8, 'now')",
            (str(picture),),
        )
    on = {**client.get("/settings").json(), "artwork": True}
    client.put("/settings", json=on)

    client.put("/settings", json={**on, "artwork": False})

    assert not picture.exists()


def test_choices_are_kept(client: TestClient, conn: sqlite3.Connection):
    chosen = {
        "standard": "1080p",
        "naming": "jellyfin",
        "setUp": True,
        "reports": True,
        "quarantineDays": None,
        "originals": "delete",
        "artwork": True,
        "historyDays": 30,
        "healthCheck": False,
    }

    saved = client.put("/settings", json=chosen)

    assert saved.status_code == 200
    assert client.get("/settings").json() == chosen
    stored = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    assert json.loads(stored["standard"]) == "1080p"  # what the export carries


def test_a_choice_maku_doesnt_offer_is_refused(client: TestClient):
    response = client.put("/settings", json={"standard": "8k-ultra"})

    assert response.status_code == 422


def test_a_stored_value_this_maku_doesnt_know_falls_back_to_the_default(
    client: TestClient, conn: sqlite3.Connection
):
    with conn:
        conn.execute("INSERT INTO settings VALUES ('naming', ?)", (json.dumps("emby"),))

    assert client.get("/settings").json()["naming"] == "plex"
