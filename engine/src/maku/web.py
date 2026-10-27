"""Asking web services (TMDB) for JSON and pictures: timeouts, waiting out rate limits,
and errors in words a person can act on.

Everything goes through one `Send` function, so tests can stand in for the internet.
"""

import email.utils
import http.client
import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.message import Message
from typing import Literal, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from maku import __version__
from maku.core import fields
from maku.core.fields import Json

log = logging.getLogger(__name__)

type Method = Literal["GET"]


@dataclass(frozen=True)
class Reply:
    status: int
    headers: Mapping[str, str]  # names in lower case
    body: bytes


type Send = Callable[[Method, str, Mapping[str, str], bytes | None], Reply]


class WebError(Exception):
    """A service couldn't be reached, or answered with an error. The message says which."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status  # the service's HTTP status, when it answered


_TIMEOUT = 30  # seconds for one request
_RETRY = frozenset({429, 500, 502, 503, 504})  # worth another try after a pause
_LONGEST_WAIT = 120.0  # seconds; a service asking for longer is treated as down


def send(method: Method, url: str, headers: Mapping[str, str], body: bytes | None) -> Reply:
    """The real thing: one HTTPS request with urllib."""
    if not url.startswith("https://"):
        raise WebError(f"Maku only talks to web services over HTTPS, and {url} isn't.")
    request = Request(url, data=body, headers=dict(headers), method=method)  # noqa: S310
    host = urlsplit(url).hostname or url
    try:
        # The address is HTTPS (checked above) and built by Maku from a fixed service address.
        with urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310
            return Reply(response.status, _lower(response.headers), response.read())
    except HTTPError as error:
        return Reply(error.code, _lower(error.headers), error.read())
    except URLError as error:
        raise WebError(f"Maku couldn't reach {host} ({error.reason}).") from error
    except (TimeoutError, OSError, http.client.HTTPException) as error:
        raise WebError(f"Maku couldn't reach {host} ({error}).") from error


class Service:
    """One web service, such as TMDB: asks it for JSON, politely.

    A busy or failing service gets a few more tries, as long as it asks Maku to wait (429, with
    Retry-After) or says it's briefly down (5xx). When a service says no requests are left in
    this minute (X-RateLimit-Remaining: 0), the next request waits for its reset.
    """

    def __init__(
        self,
        name: str,
        transport: Send = send,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        attempts: int = 4,
    ) -> None:
        self.name = name
        self._send = transport
        self._sleep = sleep
        self._clock = clock
        self._attempts = attempts
        self._lock = threading.Lock()
        self._not_before = 0.0  # when the next request may go, after the limit ran out

    def json(self, method: Method, url: str, *, headers: Mapping[str, str] | None = None) -> Json:
        """The service's JSON answer to one request, after any pauses it asked for."""
        reply = self._ask(method, url, {"Accept": "application/json", **(headers or {})})
        answer = _object(reply.body)
        if answer is None:
            raise WebError(f"{self.name} answered something Maku couldn't read.", reply.status)
        return answer

    def raw(self, url: str) -> bytes:
        """The bytes at an address, such as a poster."""
        return self._ask("GET", url, {}).body

    def _ask(self, method: Method, url: str, headers: Mapping[str, str]) -> Reply:
        sent = {"User-Agent": f"Maku/{__version__}", **headers}
        for attempt in range(1, self._attempts + 1):
            self._wait_for_limit()
            reply = self._send(method, url, sent, None)
            self._note_limit(reply)
            if 200 <= reply.status < 300:
                return reply
            pause = _pause(reply, attempt, self._clock())
            if reply.status not in _RETRY or attempt == self._attempts or pause is None:
                raise WebError(self._refusal(reply), reply.status)
            log.info("%s answered %d; trying again in %.0f s", self.name, reply.status, pause)
            self._sleep(pause)
        raise AssertionError("unreachable: the last attempt returns or raises")

    def _wait_for_limit(self) -> None:
        with self._lock:
            wait = self._not_before - self._clock()
        if wait > 0:
            self._sleep(min(wait, _LONGEST_WAIT))

    def _note_limit(self, reply: Reply) -> None:
        if reply.headers.get("x-ratelimit-remaining") != "0":
            return
        reset = _number(reply.headers.get("x-ratelimit-reset"))
        if reset is not None:
            with self._lock:
                self._not_before = max(self._not_before, reset)

    def _refusal(self, reply: Reply) -> str:
        said = _message(reply.body)
        if reply.status in (401, 403):
            return f"{self.name} didn't accept the key{f' ({said})' if said else ''}."
        if reply.status == 404:
            return f"{self.name} has nothing at that address."
        if reply.status == 429:
            return f"{self.name} is busy and asked Maku to slow down. Maku tries again later."
        if reply.status >= 500:
            return f"{self.name} isn't working right now ({reply.status}). Maku tries again later."
        return f"{self.name} answered {reply.status}{f': {said}' if said else ''}."


def _pause(reply: Reply, attempt: int, now: float) -> float | None:
    """How long to wait before trying again, or None when the wait would be too long."""
    asked = reply.headers.get("retry-after")
    if asked is None:
        return 2.0**attempt  # 2, 4, 8 seconds
    seconds = _number(asked)
    if seconds is None:
        when = email.utils.parsedate_to_datetime(asked) if asked else None
        seconds = when.timestamp() - now if when else 2.0**attempt
    return max(0.0, seconds) if seconds <= _LONGEST_WAIT else None


def _object(body: bytes) -> Json | None:
    """The JSON object in a reply's body, or None when it holds something else."""
    try:
        answer: object = json.loads(body)
    except ValueError:
        return None
    return cast("Json", answer) if isinstance(answer, Mapping) else None


def _message(body: bytes) -> str | None:
    """What the service said went wrong: TMDB's status_message."""
    answer = _object(body)
    if answer is None:
        return None
    said = fields.text(answer, "status_message")
    return said.rstrip(".") if said else None


def _number(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def _lower(headers: Message | None) -> dict[str, str]:
    return {name.lower(): value for name, value in (headers or Message()).items()}
