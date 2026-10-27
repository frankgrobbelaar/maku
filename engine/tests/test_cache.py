"""Answers kept for a while, so the same question isn't asked twice."""

from pathlib import Path

from maku.cache import DAY, Cache
from maku.tmdb import API, Tmdb
from tests.fake_web import FakeWeb
from tests.services import KEY


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def test_an_answer_comes_back_until_it_is_too_old(tmp_path: Path):
    clock = Clock()
    cache = Cache(tmp_path / "cache", clock)

    cache.put("tmdb search tv glass orchard None", {"page": 1, "results": []})

    assert cache.get("tmdb search tv glass orchard None", DAY) == {"page": 1, "results": []}
    clock.now += DAY + 1
    assert cache.get("tmdb search tv glass orchard None", DAY) is None


def test_nothing_saved_or_a_damaged_file_is_nothing(tmp_path: Path):
    cache = Cache(tmp_path / "cache")
    assert cache.get("never asked", DAY) is None

    cache.put("asked", {"answer": 1})
    for saved in (tmp_path / "cache").iterdir():
        saved.write_text("not json", encoding="utf-8")
    assert cache.get("asked", DAY) is None


def test_a_search_asked_twice_reaches_tmdb_once(tmp_path: Path):
    web = FakeWeb({f"GET {API}/search/tv": {"page": 1, "results": []}})
    tmdb = Tmdb(KEY, web, cache=Cache(tmp_path / "cache"))

    tmdb.search("tv", "Glass Orchard")
    tmdb.search("tv", "GLASS ORCHARD")  # the same question, whatever the case

    assert len(web.asked) == 1
