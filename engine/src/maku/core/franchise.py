"""Which titles make one franchise: the films TMDB keeps in one collection. And the rest of a
franchise: every film of the collection, and which of them the library has no part of.

A film's collection ties it to the films that go with it ("The Harbour Line Collection"): each
names the ones before it (PREQUEL) and after it (SEQUEL), so a collection is one franchise. A
series stands alone, as TMDB ties no show to another, and a film TMDB keeps among a show's
specials is the show's, not missing. An entry the library lacks still ties its neighbours: the
first and third films of a collection are one franchise without the second.
"""

from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import zip_longest

from maku.core.catalog import Episode, Show, Status, TitleKind
from maku.core.placing import fits_special, same_day, show_episodes

# How entries of one story relate: a film before or after another of its collection.
STORY = frozenset({"PREQUEL", "SEQUEL"})
# How the parts of one telling relate.
_TELLING = frozenset({"PREQUEL", "SEQUEL"})

LIMIT = 200  # entries of one franchise Maku looks into at most
_REMADE = timedelta(days=366)  # a special named alike years later is a remake, not the same one


@dataclass(frozen=True)
class Link:
    """What TMDB says of one entry: it's the `relation` of entry `related`."""

    entry_id: int
    related: int
    relation: str


@dataclass(frozen=True)
class Member:
    """What Maku knows of one entry of a franchise, the library's or not."""

    id: int
    name: str  # TMDB's title, in English
    names: tuple[str, ...]  # every name it goes by
    kind: TitleKind | None
    status: Status | None
    start: date | None
    episodes: int | None
    cover: str | None  # its poster's path on TMDB's image server
    description: str | None = None  # its synopsis
    genres: tuple[str, ...] = ()
    studio: str | None = None  # the first company or network TMDB names for it

    @property
    def coming(self) -> bool:
        """Not out yet."""
        return self.status == "coming"

    @property
    def airing(self) -> bool:
        """Out, and more of it still to come."""
        return self.status == "airing"


@dataclass(frozen=True)
class Kept:
    """A show of the franchise the library has: the entries its videos are matched to, its
    episode list, and where its videos sit in it."""

    entries: frozenset[int]
    show: Show
    held: frozenset[tuple[int, int]]  # (season, episode) of each episode with a video


def franchises(titles: Mapping[int, Iterable[int]], links: Iterable[Link]) -> list[list[int]]:
    """The titles grouped by franchise. `titles` maps each title to the entries its files
    matched, and `links` are those entries' own: what Maku looks up of the rest of a franchise
    never ties two of the library's together. Groups come in the order of their first titles,
    and keep the titles' order."""
    parent: dict[int, int] = {}

    def root(entry: int) -> int:
        parent.setdefault(entry, entry)
        while parent[entry] != entry:
            parent[entry] = parent[parent[entry]]  # halve the path as it goes
            entry = parent[entry]
        return entry

    def join(a: int, b: int) -> None:
        parent[root(a)] = root(b)

    for entries in titles.values():
        known = list(entries)
        for entry in known:
            join(entry, known[0])  # a title's entries are one story
    for link in links:
        if link.relation in STORY:
            join(link.entry_id, link.related)

    groups: dict[object, list[int]] = {}
    for title_id, entries in titles.items():
        known = list(entries)
        key: object = root(known[0]) if known else ("alone", title_id)
        groups.setdefault(key, []).append(title_id)
    return list(groups.values())


def own_links(links: Iterable[Link], held: Collection[int]) -> list[Link]:
    """The links of the library's own entries: all that ties its titles into franchises."""
    return [link for link in links if link.entry_id in held]


def story_neighbours(links: Iterable[Link]) -> dict[int, list[int]]:
    """Each entry's neighbours by story, whichever of the two says how they relate."""
    neighbours: dict[int, list[int]] = defaultdict(list)
    for link in links:
        if link.relation in STORY:
            neighbours[link.entry_id].append(link.related)
            neighbours[link.related].append(link.entry_id)
    return neighbours


def nearest(
    held: Iterable[int],
    neighbours: Mapping[int, Sequence[int]],
    limit: int = LIMIT,
    others: Collection[int] = (),
) -> list[int]:
    """The rest of a franchise: the entries tied by story (`story_neighbours`) to the library's
    `held` ones, those first and then the nearest, as far as Maku knows the links, at most
    `limit` of them. It stops at the entries of the library's `others` franchises, so one
    reached through a crossover isn't taken for this one's."""
    order = sorted(set(held))[:limit]
    seen = {*order, *others}
    for entry in order:  # grows as it goes: each entry's neighbours join the end
        for other in neighbours.get(entry, ()):
            if len(order) >= limit:
                return order
            if other not in seen:
                seen.add(other)
                order.append(other)
    return order


def taking_turns(waiting: Sequence[Sequence[int]], looked_up: Sequence[int]) -> list[int]:
    """The entries each franchise waits to have looked up, one of each in turn, the franchises
    least looked up so far first: a new one isn't kept waiting behind a big one, and none waits
    behind three others."""
    order = sorted(range(len(waiting)), key=lambda at: looked_up[at])
    turns = zip_longest(*(waiting[at] for at in order))
    return [entry for turn in turns for entry in turn if entry is not None]


def missing(
    entries: Iterable[Member], held: Collection[int], kept: Sequence[Kept], links: Iterable[Link]
) -> list[Member]:
    """The entries the library has no part of, oldest first: no video is matched to one, and
    none sits where it would in a show the library has (a film TMDB keeps among a show's
    specials, say). Cancelled entries and ones TMDB gives no kind yet aren't titles anyone
    keeps."""
    tellings = _tellings(links)
    found = [
        entry
        for entry in entries
        if entry.kind is not None
        and entry.status != "cancelled"
        and entry.id not in held
        and not any(_inside(entry, show, tellings) for show in kept)
    ]
    return sorted(found, key=lambda e: (e.start is None, e.start or date.max, e.name.casefold()))


def _inside(entry: Member, kept: Kept, tellings: Mapping[int, int]) -> bool:
    """Whether a video of the library sits where the entry would in a show it has."""
    if entry.kind is TitleKind.SERIES:
        told = {tellings.get(other, other) for other in kept.entries}
        if tellings.get(entry.id, entry.id) not in told:
            return False  # a series of another telling that aired alongside, say
    return any(spot in kept.held for spot in _spots(entry, kept.show))


def _spots(entry: Member, show: Show) -> list[tuple[int, int]]:
    """Where the entry's episodes would sit in the show: a series' later part among the
    numbered episodes from its first day on, as Maku places a file (maku/core/placing.py); a
    film or special among the specials, from its day on or by its names."""
    if entry.kind is TitleKind.SERIES:
        listed = show_episodes(show)
        first = next(
            (
                at
                for at, episode in enumerate(listed)
                if entry.start and episode.aired and same_day(episode.aired, entry.start)
            ),
            None,
        )
        if first is None:
            return []
        count = entry.episodes or len(listed) - first  # still airing: all from its first day on
        return [(episode.season, episode.number) for episode in listed[first : first + count]]
    specials = show.season(0)
    named = [
        (0, special.number)
        for special in specials
        if _near(entry.start, special.aired, _REMADE) and fits_special(entry.names, special)
    ]
    return named or _from_its_day(entry, specials)


def _from_its_day(entry: Member, specials: Sequence[Episode]) -> list[tuple[int, int]]:
    """The special nearest the entry's first day, when one aired on it, and the ones after it
    for its other episodes: for one its names don't name (TMDB's "One Last Crossing - The
    Movie")."""
    start = entry.start
    if start is None:
        return []
    near = [
        (abs(special.aired - start), at)
        for at, special in enumerate(specials)
        if special.aired and same_day(special.aired, start)
    ]
    if not near:
        return []
    first = min(near)[1]
    return [(0, special.number) for special in specials[first : first + (entry.episodes or 1)]]


def _near(day: date | None, other: date | None, within: timedelta) -> bool:
    """Whether two days are within so long of each other; an unknown day could be either."""
    return day is None or other is None or abs(day - other) <= within


def _tellings(links: Iterable[Link]) -> dict[int, int]:
    """Each entry's telling, by one entry of it: the entries joined as prequel and sequel."""
    parent: dict[int, int] = {}

    def root(entry: int) -> int:
        parent.setdefault(entry, entry)
        while parent[entry] != entry:
            parent[entry] = parent[parent[entry]]
            entry = parent[entry]
        return entry

    for link in links:
        if link.relation in _TELLING:
            parent[root(link.entry_id)] = root(link.related)
    return {entry: root(entry) for entry in parent}
