"""What Maku tells after closing unexpectedly (a crash, a power cut): what it settled as it
started again, once, for a day."""

import sqlite3
from datetime import timedelta

from maku.config import DataPaths
from maku.recovery import Recovery, asked_to_stop, last, note, seen, stopped_on_purpose
from tests.shelf import NOW


def test_what_was_settled_is_told_for_a_day(conn: sqlite3.Connection):
    found = Recovery(NOW.isoformat(), restarted=1, moves=2)

    note(conn, found)

    assert last(conn, NOW + timedelta(hours=10)) == found
    assert last(conn, NOW + timedelta(days=1, minutes=1)) is None


def test_once_seen_it_isnt_told_again(conn: sqlite3.Connection):
    note(conn, Recovery(NOW.isoformat(), finished=1))

    seen(conn)

    assert last(conn, NOW) is None


def test_a_start_with_nothing_to_settle_tells_nothing(conn: sqlite3.Connection):
    note(conn, Recovery(NOW.isoformat(), restarted=1))

    note(conn, Recovery((NOW + timedelta(hours=1)).isoformat()))  # a clean start after

    assert last(conn, NOW + timedelta(hours=1)) == Recovery(NOW.isoformat(), restarted=1)


def test_a_stop_maku_was_asked_for_is_known_once_at_the_next_start(paths: DataPaths):
    paths.root.mkdir(parents=True)
    assert stopped_on_purpose(paths) is False

    asked_to_stop(paths)

    assert stopped_on_purpose(paths) is True
    assert stopped_on_purpose(paths) is False
