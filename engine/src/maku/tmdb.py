"""TMDB: series and films, the seasons and episode titles media servers show, collections, and
artwork.

It needs the owner's own key (maku/credentials.py keeps it). Both kinds TMDB hands out work: the
API Read Access Token (sent as a bearer token) and the shorter API key (sent in the address).
"""

import re
from urllib.parse import urlencode

from maku.cache import DAY, Cache
from maku.core import catalog
from maku.core.catalog import IMAGES, Film, Hit, Media, Picture, Show
from maku.core.fields import Json
from maku.web import Send, Service, WebError, send

API = "https://api.themoviedb.org/3"
_APPENDED = 20  # seasons TMDB adds to one answer at most
_V3_KEY = re.compile(r"[0-9a-fA-F]{32}")

__all__ = ["API", "IMAGES", "Tmdb"]


class Tmdb:
    def __init__(
        self,
        key: str,
        transport: Send = send,
        service: Service | None = None,
        cache: Cache | None = None,
    ) -> None:
        self._key = key.strip()
        self._service = service or Service("TMDB", transport)
        self._cache = cache

    def check(self) -> None:
        """Raises WebError unless TMDB accepts the key."""
        self._get("/authentication")

    def search(self, media: Media, query: str, year: int | None = None) -> list[Hit]:
        """Shows or films whose name fits `query`, best first, as TMDB ranks them. An answer is
        kept for a week."""
        key = f"tmdb search {media} {query.casefold()} {year}"
        answer = self._cache.get(key, 7 * DAY) if self._cache else None
        if answer is None:
            options: dict[str, str] = {"query": query, "include_adult": "false"}
            if year is not None:
                field = "first_air_date_year" if media == "tv" else "primary_release_year"
                options[field] = str(year)
            answer = self._get(f"/search/{media}", options)
            if self._cache:
                self._cache.put(key, answer)
        return catalog.hits(answer, media)

    def details(self, media: Media, item_id: int, *, fresh: bool = False) -> Json | None:
        """A show's or film's details (/tv/{id} or /movie/{id}) with the other names TMDB knows
        it by, or None when TMDB has no such one. An answer is kept for a week; `fresh` asks
        again anyway."""
        key = f"tmdb details {media} {item_id}"
        answer = self._cache.get(key, 7 * DAY) if self._cache and not fresh else None
        if answer is None:
            try:
                answer = self._get(
                    f"/{media}/{item_id}", {"append_to_response": "alternative_titles"}
                )
            except WebError as error:
                if error.status == 404:
                    return None
                raise
            if self._cache:
                self._cache.put(key, answer)
        return answer

    def collection(self, collection_id: int) -> Json | None:
        """A collection of films (/collection/{id}), its parts in it, or None when TMDB has no
        such one. An answer is kept for a week."""
        key = f"tmdb collection {collection_id}"
        answer = self._cache.get(key, 7 * DAY) if self._cache else None
        if answer is None:
            try:
                answer = self._get(f"/collection/{collection_id}")
            except WebError as error:
                if error.status == 404:
                    return None
                raise
            if self._cache:
                self._cache.put(key, answer)
        return answer

    def alternative_titles(self, media: Media, item_id: int) -> list[str]:
        """The other names TMDB knows a show or film by: in other languages, other spellings.
        An answer is kept for a week."""
        key = f"tmdb names {media} {item_id}"
        answer = self._cache.get(key, 7 * DAY) if self._cache else None
        if answer is None:
            answer = self._get(f"/{media}/{item_id}/alternative_titles")
            if self._cache:
                self._cache.put(key, answer)
        return catalog.alternative_titles(answer)

    def pictures(self, media: Media, item_id: int) -> list[Picture]:
        """The posters TMDB has of a show or film, in English or without words, the best rated
        first. An answer is kept for a day."""
        key = f"tmdb posters {media} {item_id}"
        answer = self._cache.get(key, DAY) if self._cache else None
        if answer is None:
            answer = self._get(f"/{media}/{item_id}/images", {"include_image_language": "en,null"})
            if self._cache:
                self._cache.put(key, answer)
        return catalog.pictures(answer)

    def show(self, show_id: int) -> Show | None:
        """A show with every episode of every season, specials included, or None if it's gone."""
        try:
            details = self._get(f"/tv/{show_id}")
        except WebError as error:
            if error.status == 404:
                return None
            raise
        numbers = catalog.season_numbers(details)
        merged: dict[str, object] = dict(details)
        for start in range(0, len(numbers), _APPENDED):
            chunk = numbers[start : start + _APPENDED]
            seasons = ",".join(f"season/{number}" for number in chunk)
            answer = self._get(f"/tv/{show_id}", {"append_to_response": seasons})
            merged.update(
                {key: value for key, value in answer.items() if key.startswith("season/")}
            )
        return catalog.show(merged)

    def film(self, movie_id: int) -> Film | None:
        try:
            return catalog.film(self._get(f"/movie/{movie_id}"))
        except WebError as error:
            if error.status == 404:
                return None
            raise

    def poster(self, path: str, size: str = "w342") -> bytes:
        """A poster or other picture from TMDB's image server; `path` comes from a show or film."""
        return self._service.raw(f"{IMAGES}/{size}{path}")

    def _get(self, path: str, options: dict[str, str] | None = None) -> Json:
        query = dict(options or {})
        headers: dict[str, str] = {}
        if _V3_KEY.fullmatch(self._key):
            query["api_key"] = self._key
        else:
            headers["Authorization"] = f"Bearer {self._key}"
        address = f"{API}{path}" + (f"?{urlencode(query)}" if query else "")
        return self._service.json("GET", address, headers=headers)
