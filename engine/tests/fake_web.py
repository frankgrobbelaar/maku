"""Stands in for the internet in tests: answers requests from a table, and remembers them."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from maku.web import Method, Reply, WebError

type Answer = object | Reply | Callable[[Asked], object | Reply]


@dataclass(frozen=True)
class Asked:
    method: Method
    url: str
    headers: Mapping[str, str]
    body: bytes | None

    @property
    def path(self) -> str:
        """The address without its query: "https://api.themoviedb.org/3/search/tv"."""
        parts = urlsplit(self.url)
        return f"{parts.scheme}://{parts.netloc}{parts.path}"

    @property
    def query(self) -> dict[str, str]:
        return {key: values[0] for key, values in parse_qs(urlsplit(self.url).query).items()}


@dataclass
class FakeWeb:
    """`answers` maps "GET https://…/path" (no query) to the JSON to send back, a Reply, or a
    function of the request. Anything else gets a 404. `offline` makes every request fail the
    way an unreachable service does."""

    answers: dict[str, Answer] = field(default_factory=dict[str, Answer])
    offline: bool = False
    asked: list[Asked] = field(default_factory=list[Asked])

    def __call__(
        self, method: Method, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> Reply:
        request = Asked(method, url, dict(headers), body)
        self.asked.append(request)
        if self.offline:
            raise WebError("Maku couldn't reach the service (no internet).")
        answer = self.answers.get(f"{method} {request.path}")
        if callable(answer):
            answer = answer(request)
        if answer is None:
            return reply({"status_message": "The resource you requested could not be found."}, 404)
        return answer if isinstance(answer, Reply) else reply(answer)

    def paths(self) -> list[str]:
        return [f"{request.method} {request.path}" for request in self.asked]


def reply(answer: object, status: int = 200, headers: Mapping[str, str] | None = None) -> Reply:
    """A JSON reply. Header names go in lower case, as the real `send` gives them."""
    named = {name.lower(): value for name, value in (headers or {}).items()}
    return Reply(status, named, json.dumps(answer).encode())
