"""Asking web services politely: retries, rate limits, and errors in words."""

import pytest

from maku.web import Reply, Service, WebError
from tests.fake_web import FakeWeb, reply

URL = "https://api.example.org/3/thing"


class Clock:
    """A clock that moves only when something sleeps."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def service(web: FakeWeb, clock: Clock) -> Service:
    return Service("TMDB", web, sleep=clock.sleep, clock=clock.time)


def test_a_json_answer_comes_back_as_it_was_sent():
    clock = Clock()
    web = FakeWeb({f"GET {URL}": {"success": True}})

    assert service(web, clock).json("GET", URL) == {"success": True}
    assert web.asked[0].headers["Accept"] == "application/json"
    assert web.asked[0].headers["User-Agent"].startswith("Maku/")
    assert clock.slept == []


def test_a_busy_service_is_given_the_pause_it_asks_for():
    clock = Clock()
    answers = iter([reply({}, 429, {"Retry-After": "7"}), reply({"ok": 1})])
    web = FakeWeb({f"GET {URL}": lambda asked: next(answers)})

    assert service(web, clock).json("GET", URL) == {"ok": 1}
    assert clock.slept == [7.0]


def test_a_service_that_stays_down_says_so_after_a_few_tries():
    clock = Clock()
    web = FakeWeb({f"GET {URL}": reply({}, 503)})

    with pytest.raises(WebError) as raised:
        service(web, clock).json("GET", URL)

    assert str(raised.value) == "TMDB isn't working right now (503). Maku tries again later."
    assert raised.value.status == 503
    assert len(web.asked) == 4
    assert clock.slept == [2.0, 4.0, 8.0]


def test_a_refused_key_says_what_the_service_said():
    web = FakeWeb(
        {
            f"GET {URL}": reply(
                {
                    "status_code": 7,
                    "status_message": "Invalid API key: You must be granted a valid key.",
                },
                401,
            )
        }
    )

    with pytest.raises(WebError) as raised:
        service(web, Clock()).json("GET", URL)

    assert str(raised.value) == (
        "TMDB didn't accept the key (Invalid API key: You must be granted a valid key)."
    )
    assert raised.value.status == 401
    assert len(web.asked) == 1  # never retried


def test_once_the_minutes_requests_run_out_the_next_one_waits_for_the_reset():
    clock = Clock()
    spent = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1030"}
    web = FakeWeb({f"GET {URL}": reply({"ok": 1}, headers=spent)})
    asking = service(web, clock)

    asking.json("GET", URL)
    asking.json("GET", URL)

    assert clock.slept == [30.0]


def test_a_wait_longer_than_two_minutes_isnt_sat_out():
    clock = Clock()
    web = FakeWeb({f"GET {URL}": reply({}, 429, {"Retry-After": "3600"})})

    with pytest.raises(WebError, match="busy and asked Maku to slow down"):
        service(web, clock).json("GET", URL)
    assert clock.slept == []


def test_an_answer_that_isnt_json_is_an_error():
    web = FakeWeb({f"GET {URL}": Reply(200, {}, b"<html>Cloudflare</html>")})

    with pytest.raises(WebError, match="answered something Maku couldn't read"):
        service(web, Clock()).json("GET", URL)


def test_no_internet_is_an_error_in_words():
    web = FakeWeb(offline=True)

    with pytest.raises(WebError, match="couldn't reach"):
        service(web, Clock()).json("GET", URL)
