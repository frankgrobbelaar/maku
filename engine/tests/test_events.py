"""What the engine tells the app on its standard output, after the ready line."""

import json
import time

import pytest

from maku.events import notify, working


def test_a_notification_is_one_json_line_in_plain_ascii(capsys: pytest.CaptureFixture[str]):
    notify("Glass Orchard, season 1 is done", "12 episodes · all checked · 6.1 GB → 4.2 GB")

    line = capsys.readouterr().out
    assert line.endswith("\n")
    assert line.isascii()  # whatever code page Windows gives the pipe
    assert json.loads(line) == {
        "event": "notify",
        "title": "Glass Orchard, season 1 is done",
        "body": "12 episodes · all checked · 6.1 GB → 4.2 GB",
    }


def test_a_notification_can_lead_somewhere_in_maku(capsys: pytest.CaptureFixture[str]):
    notify("Glass Orchard, season 1 is done", "12 episodes", link="/titles/12")

    assert json.loads(capsys.readouterr().out)["link"] == "/titles/12"


def test_while_it_works_at_starting_the_engine_says_so_every_few_seconds(
    capsys: pytest.CaptureFixture[str],
):
    with working(every=0.02):
        time.sleep(0.2)
    said = capsys.readouterr().out.splitlines()
    time.sleep(0.1)

    assert len(said) >= 2
    assert all(json.loads(line) == {"event": "working"} for line in said)
    assert capsys.readouterr().out == ""  # nothing once it's done
