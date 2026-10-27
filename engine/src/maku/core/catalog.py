"""What TMDB says of series and films: its shows with their seasons and episodes, its films and the
collections they belong to, and both as entries, the shape identifying weighs files against.

Parsed here from TMDB's JSON answers, as plain values; asking TMDB is maku/tmdb.py's job, and
maku/catalog.py turns its answers into entries. A show is one entry with every season (TMDB keeps
them together), and a film is one too. A film's collection ties it to the films that go with it
("The Harbour Line Collection"): Maku shows them as one franchise.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Literal

from maku.core import fields
from maku.core.fields import Json

IMAGES = "https://image.tmdb.org/t/p"  # TMDB's image server: a size and a path follow


class TitleKind(StrEnum):
    """What a title is, in the words Maku shows: a TV series or a movie. A show's specials stay
    among its episodes, in season 0."""

    SERIES = "series"
    MOVIE = "movie"


# Where a title stands, in Maku's words: its episodes are all out, more are coming, none is out
# yet, it was stopped, or it's resting before it goes on.
type Status = Literal["finished", "airing", "coming", "cancelled", "paused"]

type Media = Literal["tv", "movie"]


@dataclass(frozen=True)
class Related:
    """Another entry an entry links to: a film before or after it in its collection."""

    id: int
    relation: str  # PREQUEL or SEQUEL
    kind: TitleKind | None
    title: str
    start: date | None


@dataclass(frozen=True)
class Entry:
    """A show, every season of it, or a film, as TMDB knows it: what a group of files is weighed
    against. Its id is the show's TMDB number, or the film's negated (`entry_id`), so a show and
    a film never share one."""

    id: int
    title: str  # TMDB's title, in English
    titles: tuple[str, ...]  # every name it goes by: TMDB's, the original, the others TMDB knows
    kind: TitleKind | None
    episodes: int | None  # every episode TMDB lists of a show; a film is one
    minutes: int | None  # an episode's length, or the film's
    start: date | None
    end: date | None  # a finished show's last day, a film's release
    airing: bool
    cover: str | None  # the poster's path on TMDB's image server
    related: tuple[Related, ...]  # a film's: the others in its collection
    status: Status | None = None
    description: str | None = None  # its synopsis
    genres: tuple[str, ...] = ()
    studio: str | None = None  # the first company or network TMDB names for it
    collection: str | None = None  # a film's collection's name: "The Starfall Collection"

    @property
    def year(self) -> int | None:
        return self.start.year if self.start else None

    @property
    def media(self) -> Media:
        return tmdb_of(self.id)[0]


def entry_id(media: Media, number: int) -> int:
    """An entry's id: a show's TMDB number as it is, a film's negated."""
    return number if media == "tv" else -number


def tmdb_of(entry: int) -> tuple[Media, int]:
    """Which TMDB show or film an entry id is."""
    return ("tv", entry) if entry > 0 else ("movie", -entry)


@dataclass(frozen=True)
class Hit:
    """One TMDB search result."""

    id: int
    media: Media
    title: str
    original_title: str
    first_aired: date | None  # a show's first episode, or a film's release

    @property
    def year(self) -> int | None:
        return self.first_aired.year if self.first_aired else None


@dataclass(frozen=True)
class Episode:
    season: int  # 0 holds the specials
    number: int
    title: str | None
    aired: date | None
    minutes: int | None
    overview: str | None = None  # what happens in it
    still: str | None = None  # a picture from it: a path on TMDB's image server


@dataclass(frozen=True)
class Show:
    """A TMDB TV show with every episode of every season, specials (season 0) included."""

    id: int
    title: str
    original_title: str
    first_aired: date | None
    airing: bool  # more episodes are coming
    poster: str | None  # a path on TMDB's image server
    episodes: tuple[Episode, ...]  # in season order, then episode order
    backdrop: str | None = None  # the wide background picture's path on TMDB's image server
    overview: str | None = None  # its synopsis
    genres: tuple[str, ...] = ()
    studio: str | None = None  # the first company TMDB names for it
    status: Status | None = None
    last_aired: date | None = None
    minutes: int | None = None  # an episode's usual length

    @property
    def year(self) -> int | None:
        return self.first_aired.year if self.first_aired else None

    def season(self, number: int) -> tuple[Episode, ...]:
        return tuple(episode for episode in self.episodes if episode.season == number)

    @property
    def seasons(self) -> tuple[int, ...]:
        """The numbered seasons, without the specials."""
        return tuple(sorted({e.season for e in self.episodes if e.season > 0}))


@dataclass(frozen=True)
class Film:
    id: int
    title: str
    original_title: str
    released: date | None
    minutes: int | None
    poster: str | None
    backdrop: str | None = None  # the wide background picture's path on TMDB's image server
    overview: str | None = None  # its synopsis
    genres: tuple[str, ...] = ()
    studio: str | None = None  # the first company TMDB names for it
    status: Status | None = None

    @property
    def year(self) -> int | None:
        return self.released.year if self.released else None


def show_entry(details: Json) -> Entry | None:
    """A TMDB show (/tv/{id}, its other names appended) as an entry."""
    number = fields.whole(details, "id")
    title = fields.text(details, "name")
    if number is None or not title:
        return None
    status = fields.text(details, "status")
    airing = bool(details.get("in_production")) or status in _AIRING
    lengths = fields.numbers(details, "episode_run_time")
    latest = fields.mapping(details, "last_episode_to_air")
    minutes = lengths[0] if lengths and lengths[0] > 0 else fields.whole(latest, "runtime")
    original = fields.text(details, "original_name")
    names = alternative_titles(fields.mapping(details, "alternative_titles"))
    return Entry(
        id=entry_id("tv", number),
        title=title,
        titles=_distinct([title, original, *names]),
        kind=TitleKind.SERIES,
        episodes=fields.whole(details, "number_of_episodes") or None,
        minutes=minutes or None,
        start=fields.day(fields.text(details, "first_air_date")),
        end=None if airing else fields.day(fields.text(details, "last_air_date")),
        airing=airing,
        cover=fields.text(details, "poster_path"),
        related=(),
        status=_TMDB_STATUS.get(status or "") or ("airing" if airing else None),
        description=fields.text(details, "overview") or None,
        genres=_genres(details),
        studio=_network(details) or _company(details),
    )


def film_entry(details: Json, collection: Json | None = None) -> Entry | None:
    """A TMDB film (/movie/{id}, its other names appended) as an entry, with the others in its
    `collection` (/collection/{id}) before and after it."""
    number = fields.whole(details, "id")
    title = fields.text(details, "title")
    if number is None or not title:
        return None
    released = fields.day(fields.text(details, "release_date"))
    original = fields.text(details, "original_title")
    names = alternative_titles(fields.mapping(details, "alternative_titles"))
    status = _FILM_STATUS.get(fields.text(details, "status") or "")
    belongs = fields.mapping(details, "belongs_to_collection")
    return Entry(
        id=entry_id("movie", number),
        title=title,
        titles=_distinct([title, original, *names]),
        kind=TitleKind.MOVIE,
        episodes=1,
        minutes=fields.whole(details, "runtime") or None,
        start=released,
        end=released,
        airing=status == "coming",
        cover=fields.text(details, "poster_path"),
        related=tuple(_collection_links(number, released, collection)) if collection else (),
        status=status,
        description=fields.text(details, "overview") or None,
        genres=_genres(details),
        studio=_company(details),
        collection=fields.text(belongs, "name") or fields.text(collection or {}, "name"),
    )


def collection_of(details: Json) -> int | None:
    """The number of the collection a film (/movie/{id}) belongs to, if it does."""
    return fields.whole(fields.mapping(details, "belongs_to_collection"), "id")


def hits(answer: Json, media: Media) -> list[Hit]:
    """TMDB's search results, from /search/tv or /search/movie."""
    found: list[Hit] = []
    for result in fields.mappings(answer, "results"):
        number = fields.whole(result, "id")
        title = fields.text(result, "name" if media == "tv" else "title")
        if number is None or not title:
            continue
        original = fields.text(result, "original_name" if media == "tv" else "original_title")
        aired = fields.text(result, "first_air_date" if media == "tv" else "release_date")
        found.append(
            Hit(
                id=number,
                media=media,
                title=title,
                original_title=original or title,
                first_aired=fields.day(aired),
            )
        )
    return found


@dataclass(frozen=True)
class Picture:
    """One of the posters TMDB has of a show or film."""

    path: str  # TMDB's image path: "/abc.jpg"
    language: str | None  # "en"; None for one without words (TMDB is asked for no others)
    width: int
    height: int
    votes: float  # how TMDB's users rate it, 0 to 10


def pictures(answer: Json) -> list[Picture]:
    """The posters from /tv/{id}/images or /movie/{id}/images, the best rated first."""
    found = [
        Picture(
            path=path,
            language=fields.text(item, "iso_639_1") or None,
            width=fields.whole(item, "width") or 0,
            height=fields.whole(item, "height") or 0,
            votes=fields.decimal(item, "vote_average") or 0.0,
        )
        for item in fields.mappings(answer, "posters")
        if (path := fields.text(item, "file_path"))
    ]
    return sorted(found, key=lambda picture: -picture.votes)


def alternative_titles(answer: Json) -> list[str]:
    """The other names TMDB knows a show or film by, from /tv/{id}/alternative_titles (in
    "results") or /movie/{id}/alternative_titles (in "titles")."""
    found = [*fields.mappings(answer, "results"), *fields.mappings(answer, "titles")]
    return list(dict.fromkeys(title for item in found if (title := fields.text(item, "title"))))


def show(details: Json) -> Show | None:
    """A TMDB show from /tv/{id}, with its seasons appended (`append_to_response=season/1,…`)."""
    number = fields.whole(details, "id")
    title = fields.text(details, "name")
    if number is None or not title:
        return None
    episodes: list[Episode] = []
    for key in details:
        if key.startswith("season/"):  # each season appended to the answer
            episodes.extend(_episodes(fields.mapping(details, key)))
    episodes.sort(key=lambda episode: (episode.season, episode.number))
    status = fields.text(details, "status")
    airing = bool(details.get("in_production")) or status in _AIRING
    lengths = fields.numbers(details, "episode_run_time")
    # Its latest episode so far, of its seasons: TMDB's own date can be a special's, years on.
    latest = fields.day(fields.text(details, "last_air_date"))
    aired = [e.aired for e in episodes if e.season > 0 and e.aired and latest and e.aired <= latest]
    return Show(
        id=number,
        title=title,
        original_title=fields.text(details, "original_name") or title,
        first_aired=fields.day(fields.text(details, "first_air_date")),
        airing=airing,
        poster=fields.text(details, "poster_path"),
        episodes=tuple(episodes),
        backdrop=fields.text(details, "backdrop_path"),
        overview=fields.text(details, "overview") or None,
        genres=_genres(details),
        studio=_network(details) or _company(details),
        status=_TMDB_STATUS.get(status or "") or ("airing" if airing else None),
        last_aired=max(aired, default=latest),
        minutes=lengths[0] if lengths and lengths[0] > 0 else None,
    )


def season_numbers(details: Json) -> list[int]:
    """The seasons a TMDB show lists, specials (0) included, from /tv/{id} alone."""
    seasons = fields.mappings(details, "seasons")
    return sorted({n for s in seasons if (n := fields.whole(s, "season_number")) is not None})


def film(details: Json) -> Film | None:
    """A TMDB film from /movie/{id}."""
    number = fields.whole(details, "id")
    title = fields.text(details, "title")
    if number is None or not title:
        return None
    return Film(
        id=number,
        title=title,
        original_title=fields.text(details, "original_title") or title,
        released=fields.day(fields.text(details, "release_date")),
        minutes=fields.whole(details, "runtime") or None,
        poster=fields.text(details, "poster_path"),
        backdrop=fields.text(details, "backdrop_path"),
        overview=fields.text(details, "overview") or None,
        genres=_genres(details),
        studio=_company(details),
        status=_FILM_STATUS.get(fields.text(details, "status") or ""),
    )


_AIRING = frozenset({"Returning Series", "In Production", "Planned", "Pilot"})
_TMDB_STATUS: dict[str, Status] = {
    "Returning Series": "airing",
    "In Production": "airing",
    "Planned": "coming",
    "Pilot": "coming",
    "Post Production": "coming",
    "Rumored": "coming",
    "Ended": "finished",
    "Released": "finished",
    "Canceled": "cancelled",
}
# A film being made isn't airing: it's still to come.
_FILM_STATUS: dict[str, Status] = {
    "Rumored": "coming",
    "Planned": "coming",
    "In Production": "coming",
    "Post Production": "coming",
    "Released": "finished",
    "Canceled": "cancelled",
}


def _collection_links(number: int, released: date | None, collection: Json) -> list[Related]:
    """The other films of a film's collection, as the ones before it (PREQUEL) and after it
    (SEQUEL) by release, those with no day yet after everything."""
    links: list[Related] = []
    for part in fields.mappings(collection, "parts"):
        other = fields.whole(part, "id")
        title = fields.text(part, "title")
        if other is None or other == number or not title:
            continue
        day = fields.day(fields.text(part, "release_date"))
        before = day is not None and released is not None and day < released
        links.append(
            Related(
                id=entry_id("movie", other),
                relation="PREQUEL"
                if before or (day is not None and released is None)
                else "SEQUEL",
                kind=TitleKind.MOVIE,
                title=title,
                start=day,
            )
        )
    return links


def _genres(details: Json) -> tuple[str, ...]:
    """TMDB's genres, by name."""
    names = [fields.text(genre, "name") for genre in fields.mappings(details, "genres")]
    return _distinct([name for name in names if name])


def _company(details: Json) -> str | None:
    """The first company TMDB names as making a show or film."""
    companies = fields.mappings(details, "production_companies")
    return next((name for item in companies if (name := fields.text(item, "name"))), None)


def _network(details: Json) -> str | None:
    """The first network TMDB names as showing a show."""
    networks = fields.mappings(details, "networks")
    return next((name for item in networks if (name := fields.text(item, "name"))), None)


def _episodes(season: Json) -> list[Episode]:
    found: list[Episode] = []
    for item in fields.mappings(season, "episodes"):
        number = fields.whole(item, "episode_number")
        season_number = fields.whole(item, "season_number")
        if number is None or season_number is None:
            continue
        found.append(
            Episode(
                season=season_number,
                number=number,
                title=fields.text(item, "name") or None,
                aired=fields.day(fields.text(item, "air_date")),
                minutes=fields.whole(item, "runtime") or None,
                overview=fields.text(item, "overview") or None,
                still=fields.text(item, "still_path") or None,
            )
        )
    return found


def _distinct(names: Sequence[str | None]) -> tuple[str, ...]:
    seen: set[str] = set()
    kept: list[str] = []
    for name in names:
        if name and name.strip() and name.casefold() not in seen:
            seen.add(name.casefold())
            kept.append(name.strip())
    return tuple(kept)
