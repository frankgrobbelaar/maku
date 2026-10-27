"""Where a file sits in a TMDB show: which season and episode, numbered the way Plex shows them.

Releases number episodes in three ways, and all of them land in TMDB's seasons:

- by season: "S02E05", or "05" in a "Season 02" folder;
- straight through: "The Harbour Line - 020" is the 20th episode, wherever TMDB's seasons break,
  even in a season's folder ("Season 02/Glass Orchard - 13", after season 1's 12);
- from the start of a part: an entry that is only part of a show, such as a season's second part
  numbered from 1 again ("The Harbour Line S2 Part 2 - 03"), places its files by the day it began.

Specials go to season 0 by the date they first aired, or by their own name ("Quiet Hours - Special
05 - The Night Train"). Anything Maku can't place surely is left for the owner to review.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from pathlib import PurePath

from maku.core.catalog import Entry, Episode, Show, TitleKind
from maku.core.identify import FileFacts, similarity
from maku.core.names import Kind, ParsedName

_SAME_DAY = timedelta(days=3)  # air dates differ by time zone and listing, never by much more
_SAME_NAME = 0.85  # how alike a file's own name and a special's must be, at the least


class How(StrEnum):
    NUMBERED = "numbered"  # by its season and episode numbers
    STRAIGHT = "straight"  # its number counted through every season
    BY_DATE = "by date"  # from the day its entry began: part of a show, or a special
    BY_NAME = "by name"  # a special by its own name, among the show's


@dataclass(frozen=True)
class Placement:
    season: int
    episode: int
    last: int | None  # the last episode, for a file that holds several
    how: How


def place(parsed: ParsedName, show: Show, entry: Entry | None = None) -> Placement | None:
    """The file's season and episode in `show`, or None when Maku can't tell surely.

    `entry` is the entry the file matched. One that is only part of the show (a season's later
    part, or a special of its own) places it by the day it began.
    """
    number = parsed.episode
    if parsed.kind is Kind.SPECIAL or parsed.season == 0 or parsed.folder_season == 0:
        return _special(parsed, show, entry)
    if number is None or parsed.kind is not Kind.EPISODE:
        return None
    numbered = show_episodes(show)
    season = parsed.season if parsed.season is not None else parsed.folder_season

    start = _start_of(entry, numbered)
    if (
        start is not None
        and start > 0
        and entry
        and entry.episodes
        and 1 <= number <= entry.episodes
    ):
        # A later part with its own numbering: count on from its first episode.
        return _from(numbered, start + number - 1, parsed, How.BY_DATE)
    if season is not None:
        in_season = [e for e in numbered if e.season == season]
        if 1 <= number <= len(in_season):
            last = parsed.episode_end
            if last is not None and not number < last <= len(in_season):
                last = None
            return Placement(season, number, last, How.NUMBERED)
    # Counted straight through, from the show's first episode.
    return _from(numbered, number - 1, parsed, How.STRAIGHT)


def numbered_through(files: Iterable[FileFacts], show: Show) -> set[int]:
    """The files (by id) in a season's folder that count straight through the show, not from 1
    in each season: "Season 02/Glass Orchard - 13" after season 1's 12 is season 2's first.
    One number can't tell, so a folder's files tell together: theirs start past the seasons
    before it and run on past its own. Numbers that would fit either way (past the seasons before
    it, yet within its own) go as the release's other seasons beside it do, and keep their season
    when those don't tell. A name that says its season ("S02E14") goes by it."""
    numbered = show_episodes(show)
    folders: dict[tuple[PurePath, int], dict[int, int]] = defaultdict(dict)
    for facts in files:
        parsed = facts.parsed
        number, season = parsed.episode, parsed.folder_season
        if parsed.kind is Kind.EPISODE and parsed.season is None and number and season:
            folders[(facts.path.parent, season)][facts.id] = number
    told: dict[tuple[PurePath, int], bool | None] = {}  # None: either way
    for (folder, season), numbers in folders.items():
        before = sum(1 for episode in numbered if episode.season < season)
        own = sum(1 for episode in numbered if episode.season == season)
        if not before:
            continue  # season 1's numbers are the same either way, and tell nothing
        first, last = min(numbers.values()), max(numbers.values())
        if first <= before:
            told[(folder, season)] = False  # from 1 in its season
        else:
            told[(folder, season)] = True if last > own else None
    straight: set[int] = set()
    for (folder, season), says in told.items():
        if says is None:
            beside = {
                other_says
                for (other, _), other_says in told.items()
                if other != folder and other.parent == folder.parent
            }
            says = True in beside and False not in beside
        if says:
            straight.update(folders[(folder, season)])
    return straight


def show_episodes(show: Show) -> list[Episode]:
    """The show's numbered episodes, season 1 onwards, in order: what straight-through numbers
    count along."""
    return [episode for episode in show.episodes if episode.season > 0]


def _from(numbered: list[Episode], index: int, parsed: ParsedName, how: How) -> Placement | None:
    if not 0 <= index < len(numbered):
        return None
    first = numbered[index]
    last = None
    if parsed.episode is not None and parsed.episode_end is not None:
        end = index + parsed.episode_end - parsed.episode
        # Several episodes in one file stay in one season, as Plex names them.
        if index < end < len(numbered) and numbered[end].season == first.season:
            last = numbered[end].number
    return Placement(first.season, first.number, last, how)


def _start_of(entry: Entry | None, numbered: list[Episode]) -> int | None:
    """Where an entry begins among the show's episodes, by its first air date."""
    if entry is None or entry.start is None or entry.kind not in (TitleKind.SERIES, None):
        return None
    for index, episode in enumerate(numbered):
        if episode.aired is not None and same_day(episode.aired, entry.start):
            return index
    return None


def lists_special(show: Show, day: date) -> bool:
    """Whether the show's specials (season 0) hold one that first aired on this day."""
    return any(
        episode.aired is not None and same_day(episode.aired, day) for episode in show.season(0)
    )


def _special(parsed: ParsedName, show: Show, entry: Entry | None) -> Placement | None:
    specials = show.season(0)
    if not specials:
        return None
    number = parsed.episode or 1
    known = any(episode.number == number for episode in specials)
    if parsed.season == 0 and known:
        return Placement(0, number, None, How.NUMBERED)  # named the Plex way: "S00E03"
    # A special's own entry is the special that first aired on its day. A series' first day
    # says nothing about which of its specials a file is.
    if entry is not None and entry.start is not None and entry.kind not in (TitleKind.SERIES, None):
        # A one-off is its day's special, whatever a release numbers it ("Special 05").
        offset = 0 if entry.episodes == 1 else number - 1
        for index, episode in enumerate(specials):
            if episode.aired is not None and same_day(episode.aired, entry.start):
                at = index + offset
                if 0 <= at < len(specials):
                    return Placement(0, specials[at].number, None, How.BY_DATE)
    # "Quiet Hours - Special 05 - The Night Train": the release's own count says nothing of
    # TMDB's, but the name does.
    if parsed.episode_title and (named := _named(parsed.episode_title, specials)):
        return Placement(0, named.number, None, How.BY_NAME)
    if parsed.folder_season == 0 and known:
        return Placement(0, number, None, How.NUMBERED)  # "03" in a "Specials" folder
    return None


def named_special(names: Iterable[str], show: Show) -> Placement | None:
    """The special an entry's own names name among the show's, with or without the show's name
    before them ("Quiet Hours: The Night-Train!" is TMDB's "The Night Train"), when they all
    name the same one."""
    specials = show.season(0)
    found = {
        named.number
        for name in names
        for part in dict.fromkeys((name, name.split(": ", 1)[-1]))
        if (named := _named(part, specials))
    }
    if len(found) != 1:
        return None
    return Placement(0, found.pop(), None, How.BY_NAME)


def fits_special(names: Iterable[str], special: Episode) -> bool:
    """Whether one of an entry's names is this special's, read as `named_special` reads them:
    "The Harbour Line: The Long Crossing" fits both of TMDB's "The Long Crossing (1)" and
    "(2)"."""
    if not special.title:
        return False
    theirs = _part_number(_plain(special.title))
    return any(
        similarity(_part_number(_plain(part)), theirs) >= _SAME_NAME
        for name in names
        for part in dict.fromkeys((name, name.split(": ", 1)[-1]))
    )


def _named(title: str, specials: Sequence[Episode]) -> Episode | None:
    """The special a file's own name names, when one fits it clearly better than the rest:
    "The Keeper, Father of the Light" is "The Keeper - Father of the Light". A part goes by its
    number ("Part 1 of 2" is TMDB's "(1)"), a name with an "aka" by either name, and the words any
    special could carry don't count ("Summer Vacation" is "Summer Vacation Special")."""
    names = [_part_number(_plain(name)) for name in _AKA.split(title)]
    scored = sorted(
        (
            (max(similarity(name, _part_number(_plain(special.title))) for name in names), special)
            for special in specials
            if special.title
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not scored or scored[0][0] < _SAME_NAME:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None  # two fit as well: it could be either
    return scored[0][1]


_AKA = re.compile(r"\s+aka\s+", re.IGNORECASE)
_ANY_SPECIAL = re.compile(r"\b(?:tv\s+)?specials?\b", re.IGNORECASE)


def _plain(name: str) -> str:
    """A special's name without the words any special could carry ("Special", "TV Special")."""
    return _ANY_SPECIAL.sub(" ", name).strip() or name


_PART = re.compile(r"\bpart\s*(\d+)(?:\s*of\s*\d+)?\b", re.IGNORECASE)


def _part_number(name: str) -> str:
    return _PART.sub(r"\1", name)


def same_day(a: date, b: date) -> bool:
    """Whether two listings' days are the same air date: they differ by a few days at most."""
    return abs(a - b) <= _SAME_DAY
