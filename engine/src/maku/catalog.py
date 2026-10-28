"""Series and films to weigh files against: TMDB's shows and films as entries (core/catalog.py),
with every name they go by and, for a film, the others in its collection.

It needs the owner's TMDB key (maku/credentials.py keeps it): without one there's nothing to ask,
and NoKeyError says so. Answers are kept a week (maku/tmdb.py), so a rescan asks nothing again.
"""

from maku import credentials
from maku.cache import Cache
from maku.config import DataPaths
from maku.core import catalog
from maku.core.catalog import Entry, Media, tmdb_of
from maku.tmdb import Tmdb
from maku.web import Send, Service, send

# Of what a search finds, the most of each kind looked into: the kind the files look like first.
_FIRST = 5
_SECOND = 3


class NoKeyError(LookupError):
    """There's no TMDB key yet: Maku can't look anything up till the owner gives one."""

    def __init__(self) -> None:
        super().__init__("Maku needs your TMDB key to find series and films: add it in Settings.")


class Catalog:
    def __init__(
        self,
        paths: DataPaths,
        transport: Send = send,
        cache: Cache | None = None,
        service: Service | None = None,
    ) -> None:
        """`service` is how TMDB is reached: one for the engine, so its waits are shared."""
        self._paths = paths
        self._transport = transport
        self._cache = cache
        self._service = service or Service("TMDB", transport)

    def tmdb(self) -> Tmdb:
        """TMDB with the owner's key; NoKeyError without one."""
        key = credentials.load(self._paths, "tmdb")
        if not key:
            raise NoKeyError
        return Tmdb(key, self._transport, service=self._service, cache=self._cache)

    @property
    def ready(self) -> bool:
        """Whether there's a key to ask TMDB with."""
        return bool(credentials.load(self._paths, "tmdb"))

    def search(
        self, text: str, *, films_first: bool = False, year: int | None = None
    ) -> list[Entry]:
        """Shows and films whose names fit `text`, as entries: those of the kind the files look
        like first (films for a film), then the other kind, each as TMDB ranks them. With a
        `year`, that year's first (see `search_kind`)."""
        first, second = search_order(films_first=films_first)
        return [
            *self.search_kind(text, first, year=year),
            *self.search_kind(text, second, first=False, year=year),
        ]

    def search_kind(
        self, text: str, media: Media, *, first: bool = True, year: int | None = None
    ) -> list[Entry]:
        """The shows, or the films, whose names fit `text`, as entries, as TMDB ranks them: as
        many as the kind the files look like deserves (`first`), fewer of the other. With a
        `year` (a film's release, a show's first episode), TMDB is asked for that year's, so a
        film of a name many share is found however far down the rest it comes; when that year
        has none (a name's year can be a season's or a special's), for any year's."""
        tmdb = self.tmdb()
        hits = tmdb.search(media, text, year) if year is not None else []
        if not hits:
            hits = tmdb.search(media, text)
        found: list[Entry] = []
        for hit in hits[: _FIRST if first else _SECOND]:
            entry = self._entry(tmdb, media, hit.id)
            if entry is not None:
                found.append(entry)
        return found

    def entry(self, number: int, *, fresh: bool = False) -> Entry | None:
        """One entry by its id (a show's TMDB number, or a film's negated), or None when TMDB has
        no such one. `fresh` asks again anyway (how far a show still airing has got, the films
        a film's collection has now)."""
        media, item = tmdb_of(number)
        return self._entry(self.tmdb(), media, item, fresh=fresh)

    def _entry(self, tmdb: Tmdb, media: Media, item: int, *, fresh: bool = False) -> Entry | None:
        """An entry from TMDB's details of a show or film, with a film's collection."""
        details = tmdb.details(media, item, fresh=fresh)
        if details is None:
            return None
        if media == "tv":
            return catalog.show_entry(details)
        collection = catalog.collection_of(details)
        parts = tmdb.collection(collection, fresh=fresh) if collection is not None else None
        return catalog.film_entry(details, parts)


def search_order(*, films_first: bool) -> tuple[Media, Media]:
    """The kind files look like, then the other: films for a film, shows for an episode."""
    return ("movie", "tv") if films_first else ("tv", "movie")
