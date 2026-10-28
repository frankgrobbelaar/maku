"""Working out which series or film each video is: grouping files that look like the same one,
and scoring TMDB's shows and films (entries, core/catalog.py) against them.

Every guess gets a confidence from 0 to 100 and the reasons for it, in the words the review screen
shows. Maku accepts a guess on its own only when it's sure; the rest wait for the owner.
"""

import itertools
import re
import statistics
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import PurePath

from maku.core.catalog import Entry, TitleKind
from maku.core.names import Kind, ParsedName, film_part

SURE = 75  # a guess at least this confident is taken without asking
WORTH_SHOWING = 15  # guesses below this aren't shown on the review screen
CLEAR = 10  # how far ahead of a namesake a guess must be to be taken without asking


@dataclass(frozen=True)
class FileFacts:
    """What Maku knows about one video before identifying it."""

    id: int
    path: PurePath
    parsed: ParsedName
    minutes: float | None  # its length, once ffprobe has read it


@dataclass(frozen=True)
class Group:
    """Files that look like the same series or film, looked up together."""

    query: str  # the name to search for: "The Harbour Line"
    year: int | None
    movie: bool  # every file looks like a film
    files: tuple[FileFacts, ...]
    series: str | None = None  # a numbered film's series, whose name its own follows
    # A disc's own files (VIDEO_TS): its folder names a film, offered to the owner, never taken
    # surely, as which part of a disc a file is no name says.
    disc: bool = False
    # TMDB's id for the show or film, when the files' names give it: "{tmdb-4101}".
    tmdb_id: int | None = None

    @property
    def longest_episode(self) -> int | None:
        numbers = [f.parsed.episode_end or f.parsed.episode for f in self.files]
        known = [n for n in numbers if n is not None]
        return max(known) if known else None

    @property
    def minutes(self) -> float | None:
        lengths = [f.minutes for f in self.files if f.minutes]
        if not lengths:
            return None
        parts = {film_part(f.path.stem) for f in self.files} - {None}
        if self.movie and len(parts) > 1:
            return sum(lengths)  # a film in parts (CD1, CD2) is as long as they are together
        return statistics.median(lengths)


@dataclass(frozen=True)
class Guess:
    entry: Entry
    confidence: int  # 0 to 100
    reasons: tuple[str, ...]  # "Title matches", "2019 fits", …
    alike: float = 0.0  # how alike the entry's names and the files' are, 0 to 1


@dataclass(frozen=True)
class _Key:
    """What files have in common to be looked up together."""

    name: str  # normalized
    movie: bool
    year: int | None
    disc: bool
    tmdb_id: int | None


def group_files(files: Iterable[FileFacts]) -> list[Group]:
    """Files that look like the same series or film, by their title (from the name or the
    folder), by whether they're films, and by the year their names give, as a remake takes its
    name again; and by TMDB's id when their names give it ("{tmdb-4101}"). A series' files
    without a year go with the one year its other files give; beside two (a series and its
    remake), they're looked up alone. Files without any title can't be looked up, so they're
    left out."""
    grouped: dict[_Key, list[FileFacts]] = {}
    names: dict[_Key, Counter[str]] = {}
    for facts in files:
        parsed = facts.parsed
        title = parsed.best_title
        if not title or parsed.kind is Kind.EXTRA:
            continue
        disc = parsed.kind is Kind.DVD
        movie = disc or parsed.kind is Kind.MOVIE
        key = _Key(normalize(title), movie, parsed.year, disc, parsed.tmdb_id)
        grouped.setdefault(key, []).append(facts)
        names.setdefault(key, Counter())[title] += 1
    for key in [key for key in grouped if key.year is None and not key.movie]:
        dated = [o for o in grouped if o.year is not None and replace(o, year=None) == key]
        if len(dated) == 1:  # "The.Harbour.Line.S02E03" beside "The Harbour Line (2019)"
            grouped[dated[0]] += grouped.pop(key)
            names[dated[0]] += names.pop(key)
    groups: list[Group] = []
    for key, members in grouped.items():
        series = Counter(f.parsed.series for f in members if f.parsed.series)
        groups.append(
            Group(
                query=names[key].most_common(1)[0][0],  # the spelling most files use
                year=key.year,
                movie=key.movie,
                files=tuple(members),
                series=series.most_common(1)[0][0] if series else None,
                disc=key.disc,
                tmdb_id=key.tmdb_id,
            )
        )
    return sorted(
        groups,
        key=lambda group: (
            group.query.casefold(),
            group.movie,
            group.year or 0,
            group.tmdb_id or 0,
        ),
    )


def names(group: Group) -> list[str]:
    """The ways a group's name reads, to score what's found against: its name; each of two names
    when it gives one in brackets after the other ("La Ligne du Port (The Harbour Line)"); and for
    a numbered film ("Glass Orchard: High Water, UNCut", or a series' special looked up by its own
    name) also its name up to a comma and its own name alone, with the series' initials written
    out: "GO Finale" among Glass Orchard's films is "Glass Orchard Finale"."""
    texts = [group.query]
    if both := _OTHER_NAME.match(group.query):
        texts += [both["name"], both["other"]]
    own = group.query.removeprefix(f"{group.series}: ") if group.series else group.query
    if group.series and own != group.query:
        first = own.split(",")[0].strip()
        texts += [f"{group.series} {first}", own, first]
        texts += [text for part in (own, first) if (text := spelled_out(part, group.series))]
    return _unique(texts)


# A name with another after it in brackets: "La Ligne du Port (The Harbour Line)".
_OTHER_NAME = re.compile(r"^(?P<name>[^()]+?)\s*\((?P<other>[^()]*[^\W\d_][^()]*)\)$")


def searches(group: Group, *, series: bool = True) -> list[str]:
    """What to ask TMDB for a group, in turn while nothing it finds is sure: the ways its name
    reads (`names`), then a numbered film's series (unless `series` is False). A search finds
    little for a name with a word none of a title's names has, such as a release's own "UNCut"."""
    texts = names(group)
    if series and group.series and len(texts) > 1:
        texts.append(group.series)
    return _unique(texts)


def spelled_out(text: str, series: str) -> str | None:
    """`text` with the series' initials at its start written out: "GO Finale" in Glass Orchard
    is "Glass Orchard Finale", "NCP Rescue" in Northern Coast Patrol "Northern Coast Patrol
    Rescue". None without them."""
    first, _, rest = text.partition(" ")
    words = series.split()
    if not (first.isalpha() and first.isupper() and 2 <= len(first) <= len(words)):
        return None
    if first != "".join(word[0] for word in words[: len(first)]).upper():
        return None
    return " ".join([*words[: len(first)], rest]).strip()


def _unique(texts: Iterable[str]) -> list[str]:
    unique: dict[str, str] = {}
    for text in texts:
        if words := normalize(text):  # each asked once, and nothing asked for no name
            unique.setdefault(words, text)
    return list(unique.values())


def respelled(text: str, entries: Sequence[Entry]) -> str | None:
    """`text` with a word that the entries' names write as two written their way: "Harbourline"
    is "harbour line" beside an entry called "The Harbour Line". None when nothing changes."""
    split: dict[str, str] = {}
    for entry in entries:
        for title in entry.titles:
            for first, second in itertools.pairwise(normalize(title).split()):
                split.setdefault(first + second, f"{first} {second}")
    words = normalize(text).split()
    put = [split.get(word, word) for word in words]
    return " ".join(put) if put != words else None


def guesses(group: Group, entries: Sequence[Entry]) -> list[Guess]:
    """TMDB's shows and films as guesses for a group, most confident first."""
    found = [_guess(group, entry, rank) for rank, entry in enumerate(entries)]
    found.sort(key=lambda guess: guess.confidence, reverse=True)
    return [guess for guess in found if guess.confidence >= WORTH_SHOWING]


def sure_of(ranked: Sequence[Guess]) -> Guess | None:
    """The guess Maku takes without asking, if any: the best (`ranked` comes most confident
    first) when it's SURE or more and clearly ahead of every namesake, a guess whose names fit as
    well (a film of the same name from another year, a series and its remake). A namesake that's
    sure too, or less than CLEAR behind, could as well be the one: the owner says which."""
    if not ranked or ranked[0].confidence < SURE:
        return None
    best, *others = ranked
    for other in others:
        namesake = abs(other.alike - best.alike) <= _SAME_NAME
        if namesake and (other.confidence >= SURE or best.confidence - other.confidence < CLEAR):
            return None
    return best


_SAME_NAME = 0.02  # names this alike are the same name, as far as telling titles apart goes


def tagged(group: Group, entry: Entry) -> Guess | None:
    """The guess for the show or film whose TMDB id the files' names give ("{tmdb-7206}"): sure,
    as the id says which it is, however many others share its name. None when its names aren't
    the files': TMDB numbers its shows and films apart, so an id is a show's and a film's, and
    only one of them is likely the files' (none, for a slip of the id)."""
    alike = name_fit(names(group), entry.titles, main_part=not group.movie)
    if alike < _TAG_FITS:
        return None
    return Guess(entry, 100, ("Its TMDB id is in its name",), alike)


# How alike a tagged title's names and the files' must be: "Starfall II" and "Starfall" are.
_TAG_FITS = 0.6


def with_year(text: str) -> tuple[str, int | None]:
    """A name typed with a year after it, as the name and the year: "Starfall 1962" and
    "Starfall (1962)" are ("Starfall", 1962). A name without one, or that is a year ("1962"),
    comes back as it is."""
    if found := _TYPED_YEAR.match(text.strip()):
        return found["name"], int(found["year"])
    return text.strip(), None


_TYPED_YEAR = re.compile(r"^(?P<name>.*\S)(?:\s*[(\[]|\s+|\.)(?P<year>(?:19|20)\d{2})[)\]]?$")


def merged(*rankings: Sequence[Guess]) -> list[Guess]:
    """Guesses from several lookups as one ranking, most confident first: each entry once, at its
    surest."""
    best: dict[int, Guess] = {}
    for ranking in rankings:
        for guess in ranking:
            known = best.get(guess.entry.id)
            if known is None or guess.confidence > known.confidence:
                best[guess.entry.id] = guess
    return sorted(best.values(), key=lambda guess: guess.confidence, reverse=True)


def _guess(group: Group, entry: Entry, rank: int) -> Guess:
    name = name_fit(names(group), entry.titles, main_part=not group.movie)
    score = name * 70
    reasons: list[str] = ["Title matches" if name >= 0.95 else f"Title {round(name * 100)}% alike"]
    # A series' specials came after it began, and are as long as they are.
    its_specials = entry.kind is TitleKind.SERIES and all(
        f.parsed.kind is Kind.SPECIAL for f in group.files
    )

    if group.year and entry.year:
        if group.year == entry.year:
            score += 15
            reasons.append(f"{entry.year} fits")
        elif abs(group.year - entry.year) == 1:
            score += 5
        elif not (its_specials and group.year > entry.year):
            score -= 25
            reasons.append(f"From {entry.year}, not {group.year}")

    score += _kind_fit(group, entry, reasons)

    longest = group.longest_episode
    if longest is not None and entry.episodes and not group.movie:
        if longest <= entry.episodes:
            score += 10
            reasons.append(
                f"{_episodes(entry.episodes)} {'fits' if entry.episodes == 1 else 'fit'}"
            )
        elif not entry.airing:
            score -= 20
            reasons.append(f"Only {_episodes(entry.episodes)}, files go up to {longest}")

    minutes = group.minutes
    if minutes and entry.minutes and not its_specials:
        score += _length_fit(minutes, entry.minutes, film=group.movie, reasons=reasons)

    if rank == 0:
        score += 5  # TMDB ranked it first
    return Guess(entry, max(0, min(100, round(score))), tuple(reasons), name)


def _length_fit(minutes: float, expected: int, *, film: bool, reasons: list[str]) -> float:
    """How well a length fits the entry's. A film's is its own, so the closer the better: a
    98-minute file fits a 98-minute film better than a 112-minute one of the same name. An
    episode's varies around the show's, and near enough is all it says."""
    off = abs(minutes - expected)
    fits, not_it = f"{round(minutes)} min fits", f"{round(minutes)} min, not {expected}"
    if not film:
        near = off <= max(3, expected * 0.25)
        reasons.append(fits if near else not_it)
        return 5 if near else -15
    if off <= max(2, expected * 0.02):  # as long as it, give or take its logos
        reasons.append(fits)
        return 10
    if off <= max(3, expected * 0.1):  # a disc that runs a little faster, a cut of a minute
        reasons.append(fits)
        return 5
    reasons.append(not_it)
    return 0 if off <= expected * 0.25 else -15


def _kind_fit(group: Group, entry: Entry, reasons: list[str]) -> float:
    if entry.kind is None:
        return -10
    if group.movie:
        if entry.kind is TitleKind.MOVIE:
            reasons.append("A film, like the file")
            return 10
        return -30 if entry.kind is TitleKind.SERIES else -10
    if entry.kind is TitleKind.MOVIE:
        return -40
    specials = all(f.parsed.kind is Kind.SPECIAL for f in group.files)
    return -5 if specials else 5


def normalize(text: str) -> str:
    """A name reduced to what matters for comparing: letters and digits in lower case, without
    the accents of Latin letters ("Étoile du Nord" is "etoile du nord", "Tōkyō" is "tokyo")."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(char for char in decomposed if not _ACCENT.match(char))
    folded = unicodedata.normalize("NFKC", plain).casefold().replace("&", " and ")
    folded = re.sub(r"['\u2019`]", "", folded)  # apostrophes, straight or curly: "Captain's"
    return " ".join(re.sub(r"[^\w]+", " ", folded).split())


_ACCENT = re.compile("[\u0300-\u036f]")  # the marks Latin letters carry


def name_fit(texts: Sequence[str], titles: Sequence[str], *, main_part: bool = True) -> float:
    """How alike the files' names (`texts`) and a show's (`titles`) are, the closest two. A name
    that is a title's main part, before its subtitle, is nearly the title: "Glass Orchard" is
    "Glass Orchard: The Second Harvest" at least `_MAIN_PART` alike, more the closer the rest. Not
    for a film (`main_part` False): a series' films share its name before theirs, so a film
    named for its series alone is any of them."""
    best = 0.0
    for title in titles:
        main = normalize(title.split(":", 1)[0]) if main_part and ":" in title else ""
        for text in texts:
            alike = similarity(text, title)
            if len(main) > 3 and main == normalize(text):  # not "Nox" of "Nox: Night Shift"
                alike = _MAIN_PART + (1 - _MAIN_PART) * alike
            best = max(best, alike)
    return best


_MAIN_PART = 0.75


def similarity(a: str, b: str) -> float:
    """How alike two names are, from 0 to 1. One name's words all inside the other's count too:
    "Orchard" is in "Glass Orchard", though less than the full name."""
    left, right = normalize(a), normalize(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    ratio = SequenceMatcher(None, left, right).ratio()
    words_left, words_right = set(left.split()), set(right.split())
    shorter, longer = sorted((words_left, words_right), key=len)
    contained = 0.9 * len(shorter) / len(longer) if shorter <= longer else 0.0
    return max(ratio, contained)


def _episodes(count: int) -> str:
    return f"{count} episode" if count == 1 else f"{count} episodes"
