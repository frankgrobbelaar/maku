"""Reading video file names: the series or film, the season and episode, and what kind of file
it is.

anitopy, a release-name parser, reads most of a name. Maku adds rules for what it gets wrong, and
for what only the folders know, such as the "Season 03" folder above a bare "05.mkv". A scene
name's title ends where its episode code, its year or its release's words begin
("Starfall.2008.1080p.BluRay", "glass.orchard.s01e05e06.720p"). Extras are known as media server
apps file them: in a folder of their own ("Trailers") or by their kind after a dash
("Starfall (2008)-trailer"). Japanese and Chinese names mark their episodes and seasons their own
way (第01話, 第01集, 第2期), and full-width letters and digits read as plain ones.
Names are hints: matching against TMDB confirms them.
"""

import re
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath

import anitopy


class Kind(StrEnum):
    EPISODE = "episode"
    SPECIAL = "special"  # a show's special: season 0
    MOVIE = "movie"
    EXTRA = "extra"  # trailers, featurettes and other extras, samples, creditless openings
    DVD = "dvd"  # raw DVD files (VTS_01_1.VOB): unknown until matched


@dataclass(frozen=True)
class ParsedName:
    kind: Kind
    title: str | None = None  # from the file name
    series: str | None = None  # a numbered film's series: "The Harbour Line" in "… - Movie 01 - …"
    folder_title: str | None = None  # from the show's folder
    season: int | None = None  # from the file name
    folder_season: int | None = None  # from a "Season 03" or "Specials" folder
    part: int | None = None  # "Season 3 Part 2": a part numbered from 1 again
    episode: int | None = None  # within its season, or absolute when there is none
    episode_end: int | None = None  # the last episode, when a file holds several
    episode_title: str | None = None
    year: int | None = None
    group: str | None = None
    height: int | None = None
    version: int | None = None
    is_copy: bool = False  # "(copy)", " - Copy", or Maku's own " (2)"

    @property
    def best_title(self) -> str | None:
        return self.title or self.folder_title


def parse_name(path: PurePath) -> ParsedName:
    folder_title, folder_year, folder_season, folder_kind = _folder_context(path)
    if _DVD_FILE.match(path.name):
        return ParsedName(Kind.DVD, folder_title=folder_title, folder_season=folder_season)

    stem, is_copy = _without_copy_marker(_plain(path.stem))
    if _extra(path, stem):
        return ParsedName(Kind.EXTRA, title=stem, folder_title=folder_title, is_copy=is_copy)
    stem = _DISC.sub("", stem)  # "Northern Lights (2004) CD2" is its second part, not episode 2
    # A film in a folder of its own, named as it is ("Paper Kites 2 (2003)"), the way films are
    # filed: the name is the film's, its number too.
    own_folder = bool(folder_title and folder_year) and stem == _plain(path.parent.name)
    stem, recap = _japanese_markers(stem)
    found = _anitopy(stem + path.suffix)
    year = _number(_first(found, "year")) or _bracket_year(stem) or folder_year

    if film := _numbered_film(found):
        series, name = film
        return ParsedName(
            kind=Kind.MOVIE,
            title=f"{series}: {name}",
            series=series,
            folder_title=folder_title,
            folder_season=folder_season,
            year=year,
            group=_first(found, "release_group"),
            height=_height(_first(found, "video_resolution")),
            version=_number(_first(found, "release_version")),
            is_copy=is_copy,
        )
    if own_folder:
        return ParsedName(
            Kind.MOVIE,
            title=folder_title,
            folder_title=folder_title,
            year=folder_year,
            group=_first(found, "release_group"),
            height=_height(_first(found, "video_resolution")),
            version=_number(_first(found, "release_version")),
            is_copy=is_copy,
        )

    if special := _named_special(found):
        series, number, name = special
        if number is None:  # "Quiet Hours Special - The Night Train - 02": the named one's second
            number = _number(_first(found, "episode_number"))
        return ParsedName(
            kind=Kind.EXTRA if _CREDITLESS.search(stem) else Kind.SPECIAL,
            title=series,
            folder_title=folder_title,
            folder_season=folder_season,
            episode=number,
            episode_title=name,
            year=year,
            group=_first(found, "release_group"),
            height=_height(_first(found, "video_resolution")),
            version=_number(_first(found, "release_version")),
            is_copy=is_copy,
        )

    types = _types(found)
    if recap:
        types.add("special")
    episodes = [_number(value) for value in _all(found, "episode_number")]
    numbers = [number for number in episodes if number is not None]
    title = _clean_title(_first(found, "title"), drop=types | _release_words(found))
    if title and title.isdecimal() and not numbers:
        numbers, title = [int(title)], None  # "05.mkv": the name is the episode
    title = _spaced(title, stem)
    if not title and folder_kind and not types & _TYPES:
        # "05" in a folder of a show's specials is its fifth special. Which of its films it is,
        # nothing says: that waits for the owner.
        types.add(folder_kind.value)
        if folder_kind is Kind.MOVIE:
            folder_title = None
    if not title and not folder_title and (named := _LENTICULAR.search(stem)):
        title = named["title"].strip()  # anitopy took 【港の灯】, the show's name, for a group's

    season = _number(_first(found, "season"))
    episode_title, part = _title_and_part(stem, _first(found, "episode_title"))
    if (scene := _scene(stem)) and (scene.episode is not None or not numbers):
        # A scene name, read by its parts: anitopy leaves the year or the release's words in its
        # title ("Starfall 2008"), and misses some episode codes ("s01e05e06").
        title = _clean_title(scene.title, drop=types | _release_words(found)) or title
        year = scene.year or year
        if scene.episode is not None:
            numbers = [scene.episode] if scene.end is None else [scene.episode, scene.end]
            season, episode_title = scene.season, scene.episode_title
    episode = numbers[0] if numbers else None
    kind = _kind(types, season if season is not None else folder_season, episode)
    return ParsedName(
        kind=Kind.EXTRA if _CREDITLESS.search(stem) else kind,
        title=title,
        folder_title=folder_title,
        season=season,
        folder_season=folder_season,
        part=part,
        episode=episode,
        episode_end=numbers[-1] if len(numbers) > 1 else None,
        episode_title=_episode_title(episode_title),
        year=year,
        group=_first(found, "release_group"),
        height=_height(_first(found, "video_resolution")),
        version=_number(_first(found, "release_version")),
        is_copy=is_copy,
    )


def _anitopy(name: str) -> dict[str, str | list[str]]:
    """What anitopy reads in a name, under the names Maku gives what it reads ("title", "year",
    "type", "season"). It trips over a few names, such as a bare "Episode.mkv" (a keyword with
    nothing after it): those are read from their folders alone."""
    with _anitopy_lock:
        try:
            found = anitopy.parse(name) or {}
        except AttributeError, IndexError, TypeError, ValueError:
            return {}
    return {_ANITOPY_KEYS.get(key, key): value for key, value in found.items()}


# anitopy keeps its working state in module globals, so only one thread may use it at a time.
_anitopy_lock = threading.Lock()
# anitopy's own names for what it reads, and Maku's.
_ANITOPY_KEYS = {
    "anime_title": "title",
    "anime_year": "year",
    "anime_type": "type",
    "anime_season": "season",
    "anime_season_prefix": "season_prefix",
}

_DVD_FILE = re.compile(r"^(?:VTS_\d{2}_\d|VIDEO_TS)\.(?:VOB|IFO|BUP)$", re.IGNORECASE)
_COPY_MARKER = re.compile(
    r"\s*(?:\(copy\)|-\s*copy(?:\s*\(\d+\))?|\((?:[2-9]|[1-9]\d)\))\s*$", re.IGNORECASE
)
_SEASON_FOLDER = re.compile(r"^(?:season|series|s)[\s._-]*0*(\d{1,3})$", re.IGNORECASE)
_SPECIALS_FOLDER = re.compile(r"^specials?$", re.IGNORECASE)
# A season's folder named after its show: "[Group] The Harbour Line Season 02", "Quiet Hours 2nd
# Season", "Market Street S2".
_TITLED_SEASON = re.compile(
    r"^(?P<title>.+?)[\s._-]+(?:(?:season|series)[\s._-]*0*(?P<season>\d{1,2})"
    r"|(?P<nth>\d{1,2})(?:st|nd|rd|th)[\s._-]+season|s0*(?P<s>\d{1,2}))$",
    re.IGNORECASE,
)
# A folder of a show's films or specials: "Glass Orchard Movies", "3. TV Specials".
_KIND_FOLDER = re.compile(
    r"^(?:(?P<title>.+?)[\s._-]+)?(?P<kind>movies|films|specials)$", re.IGNORECASE
)
# A show and more than its films or specials: "Glass Orchard + Specials", "Market Street with
# Movies".
_AND_MORE = re.compile(r"(?:[+&,]|\b(?:and|with|plus|incl|including))\.?$", re.IGNORECASE)
# A season in a folder's brackets: "Glass Orchard (Season 2)", "[S2]", "(2nd Season)".
_SEASON_TAG = re.compile(
    r"^(?:(?:season|series|s)[\s._-]*0*(?P<season>\d{1,2})|(?P<nth>\d{1,2})(?:st|nd|rd|th)\s+season)$",
    re.IGNORECASE,
)
# A release's tags around a folder's name: "[Group] Show (Other Name) (S01-S07) [BD] [1080p]".
# A tag at the end goes when it holds a release's words or a number, never a name's own brackets
# ("Glass Orchard [Winter Harvest]").
_LEADING_TAGS = re.compile(r"^(?:\s*\[[^\]]*\])+\s*")
_TRAILING_TAG = re.compile(r"\s*[\[(](?P<inside>[^\[\]()]*)[\])]\s*$")
_RELEASE_TAG = re.compile(
    r"\d|\b(?:bd|blu-?ray|web|dvd|dual|multi|audio|aac|flac|eng|english|subs?|subbed|dub|dubbed"
    r"|raw|batch|complete|uncensored|uncut|remux|hevc|avc|tv)\b",
    re.IGNORECASE,
)
_SEASON_RANGE = re.compile(  # a folder of a show's seasons: "Glass Orchard S01-S02"
    r"[\s._-]+(?:s|seasons?[\s._-]*)\d{1,2}\s*-\s*(?:s|seasons?[\s._-]*)?\d{1,2}$", re.IGNORECASE
)
_YEAR = re.compile(r"(?:19|20)\d{2}")
_LIST_NUMBER = re.compile(r"^\d{1,2}[a-z]?\.\s+", re.IGNORECASE)  # "2a. Movies": a list's order
_ARTICLES = frozenset({"the", "a", "an"})
_FILM_PART = re.compile(r"(?:^|[\s._-])(?:cd|dis[ck]|dvd|part|pt)[\s._-]?(\d{1,2})$", re.IGNORECASE)
_DISC = re.compile(r"[\s._-]*\b(?:cd|dis[ck]|dvd)[\s._-]?\d{1,2}$", re.IGNORECASE)
# "S3 Part 2", "Season 3 Part 2": anitopy drops the part, which numbers its episodes from 1 again.
_PART = re.compile(r"\b(?:s\d{1,2}|season\s*\d{1,2})\s*[-:]?\s*part\s*(\d)\b", re.IGNORECASE)
_PART_ALONE = re.compile(r"part\s*(\d)", re.IGNORECASE)
_CODEC_WORDS = re.compile(r"\b(?:x26[45]|h\.?26[45]|hevc|avc|xvid|divx)\b", re.IGNORECASE)

# What a name can say a file is, in words anitopy reads as a kind: a special (season 0), a film,
# or an extra. anitopy knows more such words, which mean nothing to Maku and stay in the title
# ("Must See TV").
_SPECIAL_TYPES = frozenset({"sp", "special", "specials"})
_MOVIE_TYPES = frozenset({"movie", "film"})
_EXTRA_TYPES = frozenset({"preview", "menu", "trailer"})
_TYPES = _SPECIAL_TYPES | _MOVIE_TYPES | _EXTRA_TYPES
# A creditless opening or ending, wherever its name says so: "Creditless Opening",
# "Non-Credit Ending".
_CREDITLESS = re.compile(r"\bcreditless\b|\bnon[\s-]?credit(?:ed)?\b", re.IGNORECASE)
# Extras as media server apps file them, named with their kind after a dash ("Starfall
# (2008)-trailer"), and a release's sample ("starfall.2008.1080p-sample").
_EXTRA_NAME = re.compile(
    r"-(?:trailer|featurette|behindthescenes|deleted|interview|scene|short|other)$"
    r"|(?:^|[\s._-])sample$",
    re.IGNORECASE,
)
# Their folders, wherever they are: beside a film, in a season's folder, or on their own.
_EXTRA_FOLDERS = frozenset(
    {
        "extras",
        "featurettes",
        "behind the scenes",
        "deleted scenes",
        "interviews",
        "trailers",
        "sample",
        "samples",
    }
)
# Their folders a library may keep for itself by the same names ("Shorts" of short films): extras
# only inside a title's folder.
_EXTRA_FOLDERS_IN_A_TITLE = frozenset({"other", "scenes", "shorts"})
# A whole series' release numbers its films: "The Harbour Line - Movie 01 - Fog Bound". anitopy
# reads no number after "Movie", so that's all title to it; with a letter ("Movie 03b") it takes
# the number for an episode's, the title ending at the word, and the film's name for the
# episode's title.
_NUMBERED_FILM = re.compile(
    r"^(?P<series>.+?)\s+(?:-\s+)?(?:the\s+)?(?:movie|film)\s*\d{0,3}[a-z]?\s*[-:]\s+"
    r"(?P<name>.+)$",
    re.IGNORECASE,
)
# A show's special named after it: "The Harbour Line Special - A Harbour Christmas" (anitopy
# leaves it all for the title).
_NAMED_SPECIAL = re.compile(
    r"^(?P<series>.+?)\s+(?:-\s+)?(?:sp|special)\s*(?P<number>\d{1,3})?\s*[-:]\s+"
    r"(?P<name>.+)$",
    re.IGNORECASE,
)
# Japanese and Chinese marks: 第01話 or 第1回 the episode (第01集 or 第01话 in Chinese names), 第2期
# or シーズン2 the season, 総集編 a recap.
_JAPANESE_EPISODE = re.compile(
    r"\s*第\s*(?P<number>\d{1,4}|[〇一二三四五六七八九十百]{1,5})\s*[話回集话]\s*"
)
_JAPANESE_SEASON = re.compile(
    r"\s*(?:第\s*(?P<number>\d{1,2}|[一二三四五六七八九十]{1,3})\s*期|シーズン\s*(?P<plain>\d{1,2}))\s*"
)
_JAPANESE_SPECIAL = re.compile(r"総集編|特別編|特別篇|番外編")
_NO_SHOW = re.compile(r"(?:[\[【][^\]】]*[\]】]\s*)*(?:S\d{1,2})?")  # what may come before 第01話
# A show's name in lenticular brackets, as Japanese names write some: 【港の灯】.
_LENTICULAR = re.compile(r"【(?P<title>[^【】]+)】")
_KANJI_DIGITS = {
    "\u3007": 0,  # the ideographic zero, as its code: it looks like a letter O
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
# A scene name's episode code: "S01E05", "s01e05e06", "S01E05-E06", "S01E05-06", and "1x05".
_EPISODE_CODE = re.compile(
    r"(?<![a-z0-9])(?:s(?P<season>\d{1,2})[\s._-]?e(?P<episode>\d{1,3})"
    r"(?:(?:[\s._-]?e|-)(?P<end>\d{1,3}))*"
    r"|(?P<xseason>\d{1,2})x(?P<xepisode>\d{2,3}))(?![a-z0-9])",
    re.IGNORECASE,
)
# A year in a name, in brackets or not: "Starfall.2008.1080p", "Starfall (2008)"; not one of a
# span of years ("1989-2019").
_NAME_YEAR = re.compile(
    r"[(\[]?(?<![0-9])(?<![0-9]-)(?P<year>(?:19|20)\d{2})(?![0-9])(?!-\d)[)\]]?"
)
# A release's own words: where a scene name's title has ended, whatever follows them.
_RELEASE_START = re.compile(
    r"(?<![a-z0-9])(?:\d{3,4}[pi]|4k|uhd|blu-?ray|bdrip|brrip|bdremux|remux|web-?dl|web-?rip|hdtv"
    r"|pdtv|dvdrip|dvdscr|hdrip|x26[45]|h\.?26[45]|hevc|xvid|divx)(?![a-z0-9])",
    re.IGNORECASE,
)
# What can follow a scene name's year, beside those: "Starfall.2008.EXTENDED", "(2016) [WEB]".
_AFTER_YEAR = re.compile(
    r"(?:[\s._-]*[(\[])?[\s._-]*(?:$|[)\]]|(?:bd|web|dvd|avc|av1|hdr\w*|dv|dovi|sdr|aac\w*|ac3"
    r"|e?-?ac-?3|dts\w*|truehd|atmos|ddp?\d?|extended|unrated|uncut|remastered|theatrical|imax"
    r"|criterion|director'?s|proper|repack|rerip|internal|limited|multi|complete|sample)"
    r"(?![a-z0-9]))",
    re.IGNORECASE,
)
_GROUP_AT_END = re.compile(r"-[a-z0-9]+$", re.IGNORECASE)  # the release group: "…x264-GROUP"


@dataclass(frozen=True)
class _Scene:
    """A scene-style name by its parts."""

    title: str | None  # what comes before its episode code, year or release's words
    year: int | None
    season: int | None
    episode: int | None
    end: int | None  # the last episode, when the file holds several
    episode_title: str | None  # what comes between its episode code and the release's words


def _scene(stem: str) -> _Scene | None:
    """A scene-style name read by its parts: its title ends at its episode code ("S01E05",
    "1x05"), at a year its release's words or nothing follow ("Starfall.2008.1080p", "Northern
    Lights 2004", "Starfall (2008)"), or at those words ("Show.1080p.WEB-DL"). A year followed by
    another is the title's ("1958.2021.1080p" is 1958, of 2021). None for a name with none of
    them."""
    code = _EPISODE_CODE.search(stem)
    cut = code.start() if code else len(stem)
    year: int | None = None
    for found in _NAME_YEAR.finditer(stem, 0, cut):
        if found.start() == 0:
            continue  # a title can't be empty: "2087.2009.1080p" is the film 2087
        rest = stem[found.end() : cut]
        if _AFTER_YEAR.match(rest) or _RELEASE_START.match(rest.lstrip(" ._-([")):
            year, cut = int(found["year"]), found.start()
            break
    if year is None and (words := _RELEASE_START.search(stem, 0, cut)):
        cut = _opened(stem, words.start())
    if code is None and year is None and cut == len(stem):
        return None
    title = _scene_words(stem[:cut])
    if code is None:
        return _Scene(title, year, None, None, None, None)
    after = stem[code.end() :]
    if words := _RELEASE_START.search(after):
        after = after[: words.start()]
    elif not after.strip().count(" "):
        after = _GROUP_AT_END.sub("", after)  # "S01E02-GROUP"
    episode_title = _scene_words(after)
    if episode_title and _AFTER_YEAR.fullmatch(episode_title):
        episode_title = None
    season = code["season"] or code["xseason"]
    end = code["end"]
    return _Scene(
        title,
        year,
        int(season),
        int(code["episode"] or code["xepisode"]),
        int(end) if end else None,
        episode_title,
    )


def _opened(text: str, at: int) -> int:
    """Where the brackets around `at` open, when they do: a release's words in a tag go with it
    ("Show - Season 02 [BD 1080p]")."""
    depth = 0
    for index in range(at - 1, -1, -1):
        if text[index] in ")]":
            depth += 1
        elif text[index] in "([":
            if depth == 0:
                return index
            depth -= 1
    return at


def _scene_words(text: str) -> str | None:
    """A scene name's piece as words: its leading tags gone, its dots and underscores spaces
    (unless it has spaces of its own), its separators at either end taken off."""
    text = _LEADING_TAGS.sub("", text).rstrip(" ([").strip(" ._")
    if " " not in text:
        text = re.sub(r"(?<=[^\s._])[._](?=[^\s._])", " ", text)
    return _bare(text) or None


# Scene words where an episode title would be: "Salt.x.Pepper.S01E01.1080p.WEB.h264".
_SCENE_WORDS = frozenset(
    {"web", "webrip", "web-dl", "webdl", "bluray", "bdrip", "brrip", "hdtv", "dvdrip", "remux"}
)
_FILM_AT_END = re.compile(r"^(?P<series>.+?)\s+-\s+(?:movie|film)$", re.IGNORECASE)
_TYPE_AT_END = re.compile(r"\s+-\s+(?P<word>[a-z]+)$", re.IGNORECASE)
_AKA = re.compile(r"\s+aka\s+", re.IGNORECASE)
# A year opening brackets with more in them, "(2004 BluRay - 1080p)", which anitopy passes over;
# not a span of years ("1989-2019") or a checksum ("[2016ABCD]").
_BRACKET_YEAR = re.compile(r"[(\[]\s*((?:19|20)\d{2})\b(?!-\d)[^)\]]*[)\]]")

# Folders that say where files are kept, not which show they are.
_GENERAL_FOLDERS = frozenset(
    {
        "tv",
        "tv shows",
        "shows",
        "series",
        "movies",
        "films",
        "downloads",
        "download",
        "completed",
        "complete",
        "torrents",
        "incoming",
        "unsorted",
        "videos",
        "video",
        "my videos",
        "media",
        "tv series",
        "tv-shows",
        "movies and tv",
        "films and series",
        "series and films",
        "documentaries",
        "4k",
        "uhd",
        "hd",
        "1080p",
        "720p",
        "bluray",
        "blu-ray",
        "dvd",
        "dvds",
        "rips",
        "burnt",
        "burned",
        "discs",
        "backups",
        "library",
        "new folder",
        "extras",
        "extra",
        "bonus",
        "featurettes",
        "misc",
        "other",
        "others",
        "temp",
        "tmp",
    }
)


def _folder_context(path: PurePath) -> tuple[str | None, int | None, int | None, Kind | None]:
    """The show folder's title and year, the season folder's number, and what a folder of a
    show's films or specials says its files are. A season's folder named after its show ("The
    Harbour Line Season 02") names it, over a release's folder above. A folder of films or
    specials ("Glass Orchard Movies", "Glass Orchard Specials") is passed over for the one above,
    as a season's is, its own first words the show only when that one names none: they needn't be
    a show's ("Starfall Movies"). A release counts its films and specials its own way, so it's no
    season 0."""
    folder = path.parent
    name = _plain(folder.name)
    own: str | None = None  # the show a season's or a kind's folder names
    own_year: int | None = None
    kind: Kind | None = None
    cleaned, _, tagged = _folder_name(name)
    season = season_of_folder(cleaned) if cleaned else tagged  # "Season 02 [1080p]", "(Season 2)"
    if season is None and (titled := _titled_season(name)) is not None:
        own, own_year, season = titled
    elif season is None and (holds := _kind_folder(name)) is not None:
        own, own_year, kind = holds
    if season is not None or kind is not None:
        folder = folder.parent
    title, year, _ = _folder_name(_plain(folder.name))  # empty at the top of a drive
    if title is None or title.casefold() in _GENERAL_FOLDERS or season_of_folder(title) is not None:
        title, year = None, None
    if own is not None and not _a_name(own):
        own = None  # "TV Season 2", "The Specials": no show's name
    if kind is not None and title is not None:
        return title, year, season, kind  # the folder above names the show
    if own is not None:
        return own, own_year or year, season, kind
    return title, year, season, kind


def _titled_season(name: str) -> tuple[str, int | None, int] | None:
    """A season's folder named after its show, as the show, its year and the season: "[Group]
    The Harbour Line Season 02" and "Glass Orchard (Season 2)" are seasons 2. None for any other
    folder."""
    title, year, tagged = _folder_name(name)
    if title is None:
        return None
    if tagged is not None:
        return title, year, tagged
    if not (match := _TITLED_SEASON.match(title)):
        return None
    show, show_year, _ = _folder_name(match["title"])  # "Show (2019) Season 2"
    if show is None:
        return None
    return show, show_year or year, int(match["season"] or match["nth"] or match["s"])


def _kind_folder(name: str) -> tuple[str | None, int | None, Kind] | None:
    """A folder of a show's films or specials: the show its name gives, if it gives one, its
    year, and what its files are. "Glass Orchard Movies" holds films, "Glass Orchard Specials"
    specials, and so does a release's "2a. Movies". A bare "Movies" is a library's, any film's,
    and "Glass Orchard + Specials" holds the show as well: neither is one of these."""
    title, year, _ = _folder_name(name)
    numbered = _LIST_NUMBER.match(title or "")
    if numbered and title:
        title = title[numbered.end() :]  # "3. TV Specials": the release's order
    if title is None or not (match := _KIND_FOLDER.match(title)):
        return None
    films = match["kind"].casefold() in ("movies", "films")
    if films and not match["title"] and not numbered:
        return None
    show = (match["title"] or "").strip(" ._-")
    if _AND_MORE.search(show):
        return None
    show_name, show_year, _ = _folder_name(show) if show else (None, None, None)
    return show_name, show_year or year, Kind.MOVIE if films else Kind.SPECIAL


def _a_name(words: str) -> bool:
    """Whether a folder's words can be a show's name: not a library's ("TV") nor an article."""
    return words.casefold() not in _GENERAL_FOLDERS | _ARTICLES


def _extra(path: PurePath, stem: str) -> bool:
    """Whether a video is an extra, as media server apps file them: in a folder of their own
    ("Trailers", "Behind The Scenes", beside a film or in a season's folder) or named with its
    kind after a dash ("Starfall (2008)-trailer"); or a release's sample. "Other", "Scenes" and
    "Shorts" hold extras only inside a title's folder: a library may keep folders of its own by
    those names."""
    folder = _plain(path.parent.name).casefold()
    if _EXTRA_NAME.search(stem) or folder in _EXTRA_FOLDERS:
        return True
    if folder not in _EXTRA_FOLDERS_IN_A_TITLE:
        return False
    above, _, _ = _folder_name(_plain(path.parent.parent.name))
    return above is not None and _a_name(above)


def _folder_name(name: str) -> tuple[str | None, int | None, int | None]:
    """A folder's name without a release's tags around it ("[Group] La Ligne du Port (The
    Harbour Line) (S01-S03+Movies+Specials) [BD]" is "La Ligne du Port (The Harbour Line)"), and
    the year and the season its tags give: "The Harbour Line (2019)" is The Harbour Line of 2019,
    "Glass Orchard (Season 2)" its season 2. A name all in brackets is the name
    ("[Quiet Hours]")."""
    cleaned, year, season = name, None, None
    scene = _scene(name)
    if scene is not None and scene.title and scene.episode is None:
        cleaned, year = scene.title, scene.year  # "Paper Kites 1999 DVDRip XviD-GROUP"
    while (tag := _TRAILING_TAG.search(cleaned)) and _RELEASE_TAG.search(tag["inside"]):
        inside = tag["inside"].strip()
        if year is None and _YEAR.fullmatch(inside):
            year = int(inside)
        if season is None and (found := _SEASON_TAG.match(inside)):
            season = int(found["season"] or found["nth"])
        cleaned = cleaned[: tag.start()]
    cleaned = _SEASON_RANGE.sub("", cleaned)
    cleaned = _bare(_LEADING_TAGS.sub("", cleaned)) or _bare(re.sub(r"[\[\]()]", " ", cleaned))
    return (cleaned or None), year, season


def _bare(name: str) -> str:
    """A name without the spaces and separators a tag taken off left at its ends ("Show - "), its
    own marks kept: "Signal -Lost Before Dawn-". Underscores in a name without spaces are its
    spaces ("_Glass_Orchard_")."""
    if " " not in name:
        name = name.replace("_", " ")
    return re.sub(r"^[\s._-]*\s|\s[\s._-]*$", "", " ".join(name.split()))


# Full-width letters, digits and marks (U+FF01 to U+FF5E), as Japanese names have them, and the
# ideographic space: the plain ones they stand for.
_FULL_WIDTH = {code: code - 0xFEE0 for code in range(0xFF01, 0xFF5F)} | {0x3000: 0x20}


def _plain(text: str) -> str:
    """Full-width letters, digits and marks as plain ones: a full-width colon is a colon,
    full-width digits are digits. Nothing else changes: "Apartment 3½" stays as it's written."""
    return text.translate(_FULL_WIDTH)


def _japanese_markers(stem: str) -> tuple[str, bool]:
    """A name's Japanese marks written as anitopy reads them: "港の灯 第2期 第05話 タイトル" is
    "港の灯 S2 - 05 - タイトル". A name that starts with them ("第01話 タイトル") names no show,
    its folder does, and what follows is the episode's own title, left out. True when it says
    it's a recap or a special (総集編, 特別編)."""
    special = bool(_JAPANESE_SPECIAL.search(stem))
    stem = _JAPANESE_SPECIAL.sub(" ", stem)
    stem = _JAPANESE_SEASON.sub(
        lambda found: f" S{_japanese_number(found['number'] or found['plain'])} ", stem
    )
    if found := _JAPANESE_EPISODE.search(stem):
        before, after = stem[: found.start()].strip(), stem[found.end() :]
        if _NO_SHOW.fullmatch(before):
            after = ""
        stem = f"{before} - {_japanese_number(found['number']):02d} - {after}"
    return " ".join(stem.split()).strip(" -"), special


def _japanese_number(text: str) -> int:
    """A number in digits or in kanji: "05" is 5, "二十三" is 23, "百" is 100."""
    if text.isdecimal():
        return int(text)
    total = current = 0
    for char in text:
        if char == "十":
            total, current = total + (current or 1) * 10, 0
        elif char == "百":
            total, current = total + (current or 1) * 100, 0
        else:
            current = current * 10 + _KANJI_DIGITS[char]
    return total + current


def _numbered_film(found: dict[str, str | list[str]]) -> tuple[str, str] | None:
    """A film a release numbers among its series' films, as its series and its own name:
    "The Harbour Line - Movie 01 - Fog Bound" is ("The Harbour Line", "Fog Bound"). The number
    counts the release's films, not TMDB's, so it's left out."""
    title = _first(found, "title")
    if title is None:
        return None
    if match := _NUMBERED_FILM.match(title):
        series, name = match["series"], match["name"]
    elif (match := _FILM_AT_END.match(title)) and _all(found, "episode_number"):
        series, name = match["series"], _first(found, "episode_title") or ""
    else:
        return None
    # What a release adds after the name: "Return 'H' aka Homecoming", "High Water, UNCut"
    # (anitopy takes "UNCut" off, but not the comma).
    name = _AKA.split(name, maxsplit=1)[0].strip(" ,-:")
    series = series.strip(" ,-:")
    if not name or series.casefold() in _ARTICLES:  # "The Movie - Name" names no series
        return None
    return series, name


def _named_special(found: dict[str, str | list[str]]) -> tuple[str, int | None, str] | None:
    """A special named after its show, as its show, its number if it has one, and its own name:
    "The Harbour Line Special - A Harbour Christmas" is ("The Harbour Line", None, "A Harbour
    Christmas")."""
    title = _first(found, "title")
    if title is None or not (match := _NAMED_SPECIAL.match(title)):
        return None
    number = match["number"]
    return match["series"].strip(" -:"), int(number) if number else None, match["name"].strip()


def _spaced(title: str | None, stem: str) -> str | None:
    """A scene name's title with its dots as spaces: anitopy can leave one between short words
    ("Salt.x Pepper")."""
    if title is None or " " in stem or "." not in title:
        return title
    return re.sub(r"(?<=\w)\.(?=\w)", " ", title)


def _types(found: dict[str, str | list[str]]) -> set[str]:
    """What kind of file a name says it is, in the words Maku knows: "Special", "Movie",
    "Trailer". A word the title goes on after is the title's own: "A Very Special Night" is a
    film, "Glass Orchard Movie Night - 05" an episode."""
    said = {value.casefold() for value in _all(found, "type")} & _TYPES
    ending = said | _release_words(found)  # words a title can end with that aren't its own
    words = [word.strip(" -:,.!?").casefold() for word in (_first(found, "title") or "").split()]
    while words and (not words[-1] or words[-1] in ending):
        words.pop()
    return (said - set(words)) | _type_at_end(found)


def _type_at_end(found: dict[str, str | list[str]]) -> set[str]:
    """A kind of file named after a dash at the end of the title, "Glass Orchard - Film",
    "Glass Orchard - Trailer", which anitopy doesn't know for one."""
    title = _first(found, "title") or ""
    if (match := _TYPE_AT_END.search(title)) and (word := match["word"].casefold()) in _TYPES:
        return {word}
    return set()


def _bracket_year(stem: str) -> int | None:
    found = _BRACKET_YEAR.search(stem)
    return int(found[1]) if found else None


def _title_and_part(stem: str, episode_title: str | None) -> tuple[str | None, int | None]:
    """The episode title and the part number. anitopy takes "S3 Part 2 - 03" to have the episode
    title "Part 2"; a real title with "part" in it ("Part of It") is no part."""
    if episode_title and (alone := _PART_ALONE.fullmatch(episode_title.strip())):
        return None, int(alone[1])
    before = stem[: stem.find(episode_title)] if episode_title and episode_title in stem else stem
    found = _PART.search(before)
    return episode_title, int(found[1]) if found else None


def film_part(stem: str) -> int | None:
    """Which part of a film in several files this is, from the end of its name: "CD1", "cd2",
    "pt1", "Part 2", "disc 2". None for a film in one file."""
    if found := _FILM_PART.search(_without_copy_marker(stem)[0]):
        return int(found[1])
    return None


def season_of_folder(folder: str) -> int | None:
    """The season a folder's name gives: "Season 02", "S02" or "Season_02" is 2, "Specials" is
    0. None for any other folder."""
    if _SPECIALS_FOLDER.match(folder):
        return 0
    if match := _SEASON_FOLDER.match(folder):
        return int(match[1])
    return None


def _without_copy_marker(stem: str) -> tuple[str, bool]:
    cleaned = _COPY_MARKER.sub("", stem)
    return cleaned, cleaned != stem


def _clean_title(title: str | None, drop: set[str] | frozenset[str]) -> str | None:
    """Removes trailing words that describe the file rather than name the show."""
    if title is None:
        return None
    words = title.split()
    dropped = False
    while words and words[-1].strip(" -:").casefold() in drop:
        words.pop()
        dropped = True
    if dropped and words and words[-1].casefold() == "the":
        words.pop()  # "Glass Orchard - The Movie": the article goes with the word it named
    cleaned = " ".join(words).strip(" -:")
    return cleaned or None


def _release_words(found: dict[str, str | list[str]]) -> set[str]:
    """The words anitopy reads as the release's ("Batch", "Final"), which don't name the show.
    Not "End": anitopy reads it so wherever it is, and titles end with it ("Tides of the End")."""
    return {value.casefold() for value in _all(found, "release_information")} - {"end"}


def _kind(types: set[str], season: int | None, episode: int | None) -> Kind:
    if types & _EXTRA_TYPES:
        return Kind.EXTRA
    if types & _SPECIAL_TYPES or season == 0:
        return Kind.SPECIAL
    if types & _MOVIE_TYPES or episode is None:
        return Kind.MOVIE
    return Kind.EPISODE


def _episode_title(title: str | None) -> str | None:
    if title is None or _CODEC_WORDS.search(title) or title.casefold() in _SCENE_WORDS:
        return None  # scene names leave codec, source and group tags where the title would be
    return title


def _height(resolution: str | None) -> int | None:
    if resolution is None:
        return None
    if resolution.casefold() == "4k":
        return 2160
    if match := re.search(r"\d{3,4}x(\d{3,4})", resolution) or re.search(
        r"(\d{3,4})[pi]?$", resolution
    ):
        return int(match[1])
    return None


def _number(value: str | None) -> int | None:
    return int(value) if value is not None and value.isdecimal() else None


def _all(found: dict[str, str | list[str]], key: str) -> list[str]:
    value = found.get(key)
    if value is None:
        return []
    return [value] if isinstance(value, str) else value


def _first(found: dict[str, str | list[str]], key: str) -> str | None:
    values = _all(found, key)
    return values[0].strip() if values else None
