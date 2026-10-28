"""Reading video file names: the series or film, the season and episode, and what kind of file
it is.

anitopy, a release-name parser, reads most of a name. Maku adds rules for what it gets wrong, and
for what only the folders know, such as the "Season 03" folder above a bare "05.mkv". A scene
name's title ends where its episode code, its air date, its year or its release's words begin
("Starfall.2008.1080p.BluRay", "glass.orchard.s01e05e06.720p", "The.Harbour.Line.2019.01.15"),
and an episode code says a file is an episode, whatever the episode's own title says. Extras are
known as media server apps file them: in a folder of their own ("Trailers") or by their kind
after a dash ("Starfall (2008)-trailer"); so are their tags of a title's ids ("{tmdb-12345}").
Japanese and Chinese names mark their episodes and seasons their own way (第01話, 第01集, 第2期),
and full-width letters and digits read as plain ones. Names are hints: matching against TMDB
confirms them.
"""

import importlib
import re
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import PurePath

import anitopy


class Kind(StrEnum):
    EPISODE = "episode"
    SPECIAL = "special"  # a show's special: season 0
    MOVIE = "movie"
    EXTRA = "extra"  # trailers, featurettes and other extras, samples, creditless openings
    DVD = "dvd"  # a disc's own files (VTS_01_1.VOB, BDMV\STREAM\00000.m2ts): never taken surely


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
    aired: date | None = None  # a daily show's episode, by its day: "The.Harbour.Line.2019.01.15"
    year: int | None = None
    tmdb_id: int | None = None  # TMDB's id for the show or film, tagged "{tmdb-12345}" in a name
    group: str | None = None
    height: int | None = None
    version: int | None = None
    is_copy: bool = False  # "(copy)", " - Copy", or Maku's own " (2)"

    @property
    def best_title(self) -> str | None:
        return self.title or self.folder_title


def parse_name(path: PurePath) -> ParsedName:
    if _DVD_FILE.match(path.name) or _blu_ray_stream(path):
        title, year, tmdb_id = _disc_name(path)
        return ParsedName(Kind.DVD, folder_title=title, year=year, tmdb_id=tmdb_id)
    folders = _folder_context(path)
    folder_title, folder_season = folders.title, folders.season

    whole = _plain(path.stem)
    stem, is_copy = _without_copy_marker(_without_ids(whole))
    tmdb_id = _tmdb_id(whole) or folders.tmdb_id
    if _extra(path, stem):
        return ParsedName(
            Kind.EXTRA, title=stem, folder_title=folder_title, tmdb_id=tmdb_id, is_copy=is_copy
        )
    stem = _without_film_part(stem)  # "Northern Lights (2004) CD2" is its second part
    # A film in a folder of its own, named as it is ("Paper Kites 2 (2003)", or "… - pt1" for
    # its first part), the way films are filed: the name is the film's, its number too.
    own_folder = bool(folder_title and folders.year) and stem == _without_ids(
        _plain(path.parent.name)
    )
    stem, recap = _japanese_markers(stem)
    found = _anitopy(stem + path.suffix)
    year = _a_year(_number(_first(found, "year"))) or _bracket_year(stem) or folders.year

    if film := _numbered_film(found):
        series, name = film
        return ParsedName(
            kind=Kind.MOVIE,
            title=f"{series}: {name}",
            series=series,
            folder_title=folder_title,
            folder_season=folder_season,
            year=year,
            tmdb_id=tmdb_id,
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
            year=folders.year,
            tmdb_id=tmdb_id,
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
            tmdb_id=tmdb_id,
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
    if not title and folders.kind and not types & _TYPES:
        # "05" in a folder of a show's specials is its fifth special. Which of its films it is,
        # nothing says: that waits for the owner.
        types.add(folders.kind.value)
        if folders.kind is Kind.MOVIE:
            folder_title = None
    if not title and not folder_title and (named := _LENTICULAR.search(stem)):
        title = named["title"].strip()  # anitopy took 【港の灯】, the show's name, for a group's

    season = _number(_first(found, "season"))
    episode_title, part = _title_and_part(stem, _first(found, "episode_title"))
    aired: date | None = None
    scene = _scene(stem)
    if scene is not None and _a_films_number(scene, numbers, folder_season):
        # A film's title ends in it: "Area.51.2015", "Paper Kites 2 (2003)". anitopy took it for
        # an episode's number, and what follows for the episode's title.
        numbers, episode_title = [], None
    # An episode code or an air date says which episode a file is, and that it is one.
    marked = scene is not None and (scene.episode is not None or scene.dated)
    if scene is not None and (marked or not numbers):
        # A scene name, read by its parts: anitopy leaves the year or the release's words in its
        # title ("Starfall 2008"), and misses some episode codes ("s01e05e06").
        cleaned = _clean_title(scene.title, drop=types | _release_words(found))
        # Nothing before its code ("S01E01 - Pilot"): its folders name the show, and what
        # anitopy took for the show's name is the episode's own.
        title = cleaned if marked else cleaned or title
        if scene.dated:
            # A daily show's day: its numbers are no episode's, nor its year the show's.
            numbers, season, aired = [], None, scene.aired
            episode_title, year = scene.episode_title, scene.year or folders.year
        else:
            year = scene.year or year
        if scene.episode is not None:
            numbers = [scene.episode] if scene.end is None else [scene.episode, scene.end]
            season, episode_title = scene.season, scene.episode_title
            # Its code says where it goes: "Part 2" after it is the episode's own title.
            part = _part_of_season(scene.title or "")
    episode = numbers[0] if numbers else None
    if marked:  # whatever the episode's own title says ("… - S02E07 - Special")
        kind = Kind.SPECIAL if season == 0 else Kind.EPISODE
    else:
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
        aired=aired,
        year=year,
        tmdb_id=tmdb_id,
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

# anitopy 2.1.1's search for an episode's own title (Parser.search_for_episode_title) went round
# forever, holding the lock every other name waits on, on a name whose only words after its
# episode are a dash and one more mark ("Glass Orchard - 01 - .x"): ported from Anitomy, it takes
# "no token left" for "start again from the first". Maku puts in the same search, ending there as
# Anitomy's does. anitopy ships no types, hence the import by name. When anitopy moves past
# 2.1.1, the hang test in tests/core/test_names.py says whether its own search still needs this.
_anitopy_parser = importlib.import_module("anitopy.parser")


def _search_for_episode_title(_parser: object) -> None:
    tokens, flags = _anitopy_parser.Tokens, _anitopy_parser.TokenFlags
    helper = _anitopy_parser.parser_helper
    token_end = None
    while True:
        # The first unknown token outside brackets, after the last one tried.
        if token_end:
            token_begin = tokens.find_next(token_end, flags.NOT_ENCLOSED | flags.UNKNOWN)
        else:
            token_begin = tokens.find(flags.NOT_ENCLOSED | flags.UNKNOWN)
        if token_begin is None:
            return
        # On until a bracket or a word anitopy knows.
        token_end = tokens.find_next(token_begin, flags.BRACKET | flags.IDENTIFIER)
        if tokens.distance(token_begin, token_end) <= 2 and helper.is_dash_character(
            token_begin.content
        ):
            if token_end is None:
                return  # a dash and nothing after it: no title (anitopy's own went round again)
            continue  # only a dash
        if token_end and token_end.category == _anitopy_parser.TokenCategory.BRACKET:
            token_end = tokens.find_previous(token_end, flags.VALID)
        helper.build_element(
            _anitopy_parser.ElementCategory.EPISODE_TITLE,
            token_begin,
            token_end,
            keep_delimiters=False,
        )
        return


_anitopy_parser.Parser.search_for_episode_title = _search_for_episode_title

_DVD_FILE = re.compile(r"^(?:VTS_\d{2}_\d|VIDEO_TS)\.(?:VOB|IFO|BUP)$", re.IGNORECASE)
# A Blu-ray's own stream file, in its BDMV\STREAM folder: "00000.m2ts".
_BLU_RAY_STREAM = re.compile(r"^\d{5}\.m2ts$", re.IGNORECASE)
# The folders a disc keeps its videos in: the disc's own folder, above them, names it.
_DISC_FOLDERS = frozenset({"video_ts", "bdmv", "stream"})
_COPY_MARKER = re.compile(
    r"\s*(?:\(copy\)|-\s*copy(?:\s*\(\d+\))?|\((?:[2-9]|[1-9]\d)\))\s*$", re.IGNORECASE
)
# A season's folder: "Season 03", "S03", "Series 3", and "Season 2019", numbered by its year.
_SEASON_FOLDER = re.compile(
    r"^(?:season|series|s)[\s._-]*0*(\d{1,3}|(?:19|20)\d{2})$", re.IGNORECASE
)
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
# A scene name's episode code: "S01E05", "s01e05e06", "S01E05-E06", "S01E05-06", "S01E05.S01E06",
# "1x05", "1x05-06" and "1x05-1x06"; and a season numbered by its year, "S2019E05".
_EPISODE_CODE = re.compile(
    r"(?<![a-z0-9])(?:s(?P<season>\d{1,2}|(?:19|20)\d{2})[\s._-]?e(?P<episode>\d{1,3})"
    r"(?:(?:[\s._-]?e|-|[\s._-]?s(?P=season)[\s._-]?e)(?P<end>\d{1,3}))*"
    r"|(?P<xseason>\d{1,2})x(?P<xepisode>\d{2,3})"
    r"(?:(?:-|[\s._-]?(?P=xseason)x)(?P<xend>\d{2,3}))*)(?![a-z0-9])",
    re.IGNORECASE,
)
# A daily show's air date, after its title: "The.Harbour.Line.2019.01.15", "… - 2019-01-15 - …".
_AIR_DATE = re.compile(
    r"(?<![0-9])(?P<year>(?:19|20)\d{2})(?P<mark>[._ -])(?P<month>0[1-9]|1[0-2])"
    r"(?P=mark)(?P<day>0[1-9]|[12]\d|3[01])(?![0-9])"
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
# A release's words that can follow a scene name's year, beside those: its source, sound and cut
# ("Starfall.2008.EXTENDED", "(2016) [WEB]") and its languages ("Starfall.2008.German.DL").
_RELEASE_TAGS = (
    r"bd|web|dvd|dvdr|dvd[59]|avc|av1|hdr\w*|dv|dovi|sdr|aac\w*|ac3|e?-?ac-?3|dts\w*|truehd"
    r"|atmos|ddp?\d?|extended|unrated|uncut|remastered|theatrical|imax|criterion|director'?s"
    r"|proper|repack|rerip|internal|limited|complete|readnfo|3d|h?sbs|pal|ntsc|ws|fs"
    r"|multi\w*|dl|dual|dubbed|dub|subbed|subs?|hardsubs?|vostfr|vost|vff|vfq|vf|english|eng"
    r"|german|french|truefrench|spanish|castellano|latino|italian|ita|dutch|flemish|nordic"
    r"|swedish|danish|norwegian|finnish|polish|russian|portuguese|japanese|korean|chinese|hindi"
    r"|turkish|czech|hungarian"
)
_AFTER_YEAR = re.compile(
    rf"(?:[\s._-]*[(\[])?[\s._-]*(?:$|[)\]]|(?:{_RELEASE_TAGS})(?![a-z0-9]))", re.IGNORECASE
)
# Brackets in a scene name's title, and a release's words in them: "Starfall [1080p] (2008)".
_BRACKETS = re.compile(r"\s*[\[(](?P<inside>[^\[\]()]*)[\])]")
_RELEASE_TAG_WORD = re.compile(rf"\s*(?:{_RELEASE_TAGS})(?![a-z0-9])", re.IGNORECASE)
_GROUP_AT_END = re.compile(r"-[a-z0-9]+$", re.IGNORECASE)  # the release group: "…x264-GROUP"
# Media server apps' tags of a title's ids and editions in a name: "{tmdb-12345}",
# "{imdb-tt1234567}", "[tmdbid-12345]", "{edition-Director's Cut}".
_ID_TAG = re.compile(
    r"\s*(?:[{\[](?:tmdb|imdb|tvdb)(?:id)?[-=][a-z0-9]+[}\]]|\{edition-[^{}]*\})", re.IGNORECASE
)
_TMDB_ID = re.compile(r"[{\[]tmdb(?:id)?[-=](?P<id>\d+)[}\]]", re.IGNORECASE)


@dataclass(frozen=True)
class _Scene:
    """A scene-style name by its parts."""

    title: str | None  # what comes before its episode code, air date, year or release's words
    year: int | None
    season: int | None
    episode: int | None
    end: int | None  # the last episode, when the file holds several
    episode_title: str | None  # what comes between its code or date and the release's words
    dated: bool = False  # a daily show's name: a day in place of an episode code
    aired: date | None = None  # that day, when there was one: not "2019.02.30"


def _scene(stem: str) -> _Scene | None:
    """A scene-style name read by its parts: its title ends at its episode code ("S01E05",
    "1x05") or a daily show's air date ("2019.01.15"), at a year its release's words or nothing
    follow ("Starfall.2008.1080p", "Northern Lights 2004", "Starfall (2008)"), or at those words
    ("Show.1080p.WEB-DL"). A year followed by another is the title's ("1958.2021.1080p" is 1958,
    of 2021), and so is one past next year ("Starfall 2049"). None for a name with none of
    them."""
    code = _EPISODE_CODE.search(stem)
    mark: re.Match[str] | None = code
    aired: date | None = None
    if code is None and (dated := _air_date(stem)) is not None:
        mark, aired = dated
    cut = mark.start() if mark else len(stem)
    year: int | None = None
    for found in _NAME_YEAR.finditer(stem, 0, cut):
        if found.start() == 0:
            continue  # a title can't be empty: "2087.2009.1080p" is the film 2087
        if not _a_year(int(found["year"])):
            continue  # no film is of that year yet: "Starfall 2049" is a title
        rest = stem[found.end() : cut]
        if _AFTER_YEAR.match(rest) or _RELEASE_START.match(rest.lstrip(" ._-([")):
            year, cut = int(found["year"]), found.start()
            break
    if year is None and (words := _RELEASE_START.search(stem, 0, cut)):
        cut = _opened(stem, words.start())
    if mark is None and year is None and cut == len(stem):
        return None
    title = _scene_words(stem[:cut])
    if mark is None:
        return _Scene(title, year, None, None, None, None)
    after = stem[mark.end() :]
    if words := _RELEASE_START.search(after):
        after = after[: words.start()]
    elif not after.strip().count(" "):
        after = _GROUP_AT_END.sub("", after)  # "S01E02-GROUP"
    episode_title = _scene_words(after)
    if episode_title and _AFTER_YEAR.fullmatch(episode_title):
        episode_title = None
    if code is None:
        return _Scene(title, year, None, None, None, episode_title, dated=True, aired=aired)
    season = code["season"] or code["xseason"]
    end = code["end"] or code["xend"]
    return _Scene(
        title,
        year,
        int(season),
        int(code["episode"] or code["xepisode"]),
        int(end) if end else None,
        episode_title,
    )


def _air_date(stem: str) -> tuple[re.Match[str], date | None] | None:
    """Where a daily show's name gives the day its episode aired ("2019.01.15", "2019-01-15"),
    and the day: None for one that never was ("2019.02.30") or is past next year, though the name
    is still a day's, its numbers no episode's."""
    if (found := _AIR_DATE.search(stem)) is None:
        return None
    try:
        day = date(int(found["year"]), int(found["month"]), int(found["day"]))
    except ValueError:
        return found, None
    return found, day if _a_year(day.year) else None


def _a_films_number(scene: _Scene, numbers: list[int], folder_season: int | None) -> bool:
    """Whether the one number anitopy read is the last word of a film's title, before the film's
    year: "Area.51.2015", "Paper Kites 2 (2003)". Not after a dash ("Glass Orchard - 05 (2012)")
    nor in a season's folder: there it's an episode's."""
    if scene.year is None or scene.episode is not None or scene.dated:
        return False
    if len(numbers) != 1 or folder_season is not None:
        return False
    words = (scene.title or "").split()
    return len(words) > 1 and words[-2] not in ("-", "–") and _number(words[-1]) == numbers[0]


def _without_film_part(stem: str) -> str:
    """A name without the part of a film it ends with, which is no episode: "Northern Lights
    (2004) CD2" is the film's second part, and so is "Paper Kites 2 (2003) - pt2", Maku's own name
    for one. "Part 2" after anything but a film's year may be a title's own ("Glass Orchard - S01E05
    - The Long Night Part 2")."""
    if disc := _DISC.search(stem):
        return stem[: disc.start()]
    if part := _FILM_PART.search(stem):
        film = stem[: part.start()].rstrip(" ._-")
        scene = _scene(film)
        if scene and scene.year and scene.episode is None and not scene.dated:
            return film
    return stem


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
    """A scene name's piece as words: its leading tags and its release's tags gone ("Starfall
    [1080p] (2008)"), its dots and underscores spaces (unless it has spaces of its own), its
    separators at either end taken off. A name all in lenticular brackets is the name:
    【港の灯】."""
    text = _without_release_tags(_LEADING_TAGS.sub("", text)).rstrip(" ([").strip(" ._")
    if " " not in text:
        text = re.sub(r"(?<=[^\s._])[._](?=[^\s._])", " ", text)
    if named := _LENTICULAR.fullmatch(text):
        text = named["title"]
    return _bare(text) or None


def _without_release_tags(text: str) -> str:
    """A name without its brackets that hold a release's words ("[1080p]", "(Director's Cut)");
    a name's own stay: "Glass Orchard [Winter Harvest]"."""

    def tag(found: re.Match[str]) -> str:
        inside = found["inside"]
        release = _RELEASE_START.search(inside) or _RELEASE_TAG_WORD.match(inside)
        return "" if release else found[0]

    return _BRACKETS.sub(tag, text)


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
        "shorts",
        "scenes",
        "temp",
        "tmp",
    }
)


def _blu_ray_stream(path: PurePath) -> bool:
    """Whether a file is a Blu-ray's own stream, in its BDMV\\STREAM folder."""
    folders = [folder.casefold() for folder in path.parts[-3:-1]]
    return bool(_BLU_RAY_STREAM.match(path.name)) and folders == ["bdmv", "stream"]


def _disc_name(path: PurePath) -> tuple[str | None, int | None, int | None]:
    """The title, year and TMDB id a disc's own files go by: its folder's, above VIDEO_TS or
    BDMV\\STREAM ("NORTHERN_LIGHTS_DISC1" is Northern Lights, "Starfall (2008)" Starfall of
    2008). Nothing when that folder is a library's ("Burnt", "DVDs")."""
    folder = path.parent
    while folder.name.casefold() in _DISC_FOLDERS and folder != folder.parent:
        folder = folder.parent
    title, year, _ = _folder_name(_plain(folder.name))
    title = _DISC.sub("", title).strip(" ._-") if title else None
    if not title or title.casefold() in _GENERAL_FOLDERS:
        return None, None, None
    return title, year, _tmdb_id(folder.name)


@dataclass(frozen=True)
class _Folders:
    """What a video's folders say of it."""

    title: str | None = None  # the show's or the film's, from its folder
    year: int | None = None
    season: int | None = None  # from a "Season 03" or "Specials" folder
    kind: Kind | None = None  # what a folder of a show's films or specials says its files are
    tmdb_id: int | None = None  # tagged in the folder that names the show or film


def _folder_context(path: PurePath) -> _Folders:
    """The show folder's title and year, the season folder's number, and what a folder of a
    show's films or specials says its files are. A season's folder named after its show ("The
    Harbour Line Season 02") names it, over a release's folder above. A folder of films or
    specials ("Glass Orchard Movies", "Glass Orchard Specials") is passed over for the one above,
    as a season's is, its own first words the show only when that one names none: they needn't be
    a show's ("Starfall Movies"). A release counts its films and specials its own way, so it's no
    season 0. The folder that names the show or film may tag TMDB's id for it ("{tmdb-12345}")."""
    folder = path.parent
    name = _plain(folder.name)
    own: str | None = None  # the show a season's or a kind's folder names
    own_year: int | None = None
    kind: Kind | None = None
    season = _folder_season(name)
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
    if kind is not None and title is not None:  # the folder above names the show
        return _Folders(title, year, season, kind, _tmdb_id(folder.name))
    if own is not None:
        tmdb_id = _tmdb_id(path.parent.name) or _tmdb_id(folder.name)
        return _Folders(own, own_year or year, season, kind, tmdb_id)
    return _Folders(title, year, season, kind, _tmdb_id(folder.name) if title else None)


def _folder_season(name: str) -> int | None:
    """The season a season's folder gives, a release's tags around it or not: "Season 02",
    "Season 02 [1080p]", "(Season 2)", and "Season 2019", numbered by its year. None for any
    other folder, a show's own among them ("Glass Orchard (Season 2)")."""
    if (season := season_of_folder(name)) is not None:
        return season  # before its number can be read as a year: "Season 2019"
    cleaned, _, tagged = _folder_name(name)
    return season_of_folder(cleaned) if cleaned else tagged


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
    kind after a dash ("Starfall (2008)-trailer"); or a release's sample. An episode's own title
    may end with such a word ("… - S02E07 - Blood Sample"). "Other", "Scenes" and "Shorts" hold
    extras only right inside a title's own folder: a library may keep folders of its own by those
    names ("Animation\\Shorts")."""
    folder = _plain(path.parent.name).casefold()
    if folder in _EXTRA_FOLDERS:
        return True
    if _EXTRA_NAME.search(stem) and not _ends_in_episode_title(stem, path.suffix):
        return True
    if folder not in _EXTRA_FOLDERS_IN_A_TITLE:
        return False
    return _a_titles_folder(_plain(path.parent.parent.name))


def _ends_in_episode_title(stem: str, suffix: str) -> bool:
    """Whether a name ends with its episode's own title, after its episode code ("… - S02E07 -
    Blood Sample") or its air date, or after a dash and its number ("Glass Orchard - 05 -
    Behind-the-Scene"). A release's sample comes after the release's words
    ("….S01E05.720p.HDTV-sample", "glass.orchard.05.720p-sample")."""
    scene = _scene(stem)
    if scene is not None and (scene.episode is not None or scene.dated):
        own = scene.episode_title
        ending = _words(own) if own else None
    else:
        found = _anitopy(stem + suffix)
        own = _first(found, "episode_title") if _all(found, "episode_number") else None
        ending = f"- {_words(own)}" if own else None
    return ending is not None and _words(stem).endswith(ending)


def _words(text: str) -> str:
    """A name's words, to compare: its dots and underscores spaces, in one case."""
    return " ".join(re.sub(r"[._]", " ", text).casefold().split())


def _a_titles_folder(name: str) -> bool:
    """Whether a folder is a title's own: a season's ("Season 01", "Glass Orchard Season 2"), or
    a show's or a film's with its year ("Starfall (2008)"). A library's ("Animation") isn't."""
    if _folder_season(name) is not None or _titled_season(name) is not None:
        return True
    title, year, _ = _folder_name(name)
    return year is not None and title is not None and _a_name(title)


def _folder_name(name: str) -> tuple[str | None, int | None, int | None]:
    """A folder's name without a release's tags around it ("[Group] La Ligne du Port (The
    Harbour Line) (S01-S03+Movies+Specials) [BD]" is "La Ligne du Port (The Harbour Line)"), and
    the year and the season its tags give: "The Harbour Line (2019)" is The Harbour Line of 2019,
    "Glass Orchard (Season 2)" its season 2. A name all in brackets is the name
    ("[Quiet Hours]"). Media server apps' tags of its ids ("{tmdb-12345}") are no part of it."""
    cleaned, year, season = _without_ids(name), None, None
    scene = _scene(cleaned)
    if scene is not None and scene.title and scene.episode is None:
        cleaned, year = scene.title, scene.year  # "Paper Kites 1999 DVDRip XviD-GROUP"
    while (tag := _TRAILING_TAG.search(cleaned)) and _RELEASE_TAG.search(tag["inside"]):
        inside = tag["inside"].strip()
        if year is None and _YEAR.fullmatch(inside):
            year = _a_year(int(inside))
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
    film, "Glass Orchard Movie Night - 05" an episode. anitopy reads the word each time it's
    there, so one more than the title holds says what the file is: "The Special Ones Special 05"
    is a special."""
    said = Counter(word for value in _all(found, "type") if (word := value.casefold()) in _TYPES)
    ending = set(said) | _release_words(found)  # words a title can end with that aren't its own
    words = [word.strip(" -:,.!?").casefold() for word in (_first(found, "title") or "").split()]
    while words and (not words[-1] or words[-1] in ending):
        words.pop()
    own = Counter(words)
    return {word for word, times in said.items() if times > own[word]} | _type_at_end(found)


def _type_at_end(found: dict[str, str | list[str]]) -> set[str]:
    """A kind of file named after a dash at the end of the title, "Glass Orchard - Film",
    "Glass Orchard - Trailer", which anitopy doesn't know for one."""
    title = _first(found, "title") or ""
    if (match := _TYPE_AT_END.search(title)) and (word := match["word"].casefold()) in _TYPES:
        return {word}
    return set()


def _bracket_year(stem: str) -> int | None:
    found = _BRACKET_YEAR.search(stem)
    return _a_year(int(found[1])) if found else None


def _a_year(year: int | None) -> int | None:
    """A year a film or a show can have: none past next year's (a film announced for it)."""
    return year if year is not None and year <= _this_year() + 1 else None


def _this_year() -> int:
    return date.today().year


def _without_ids(name: str) -> str:
    """A name without media server apps' tags of its title's ids and edition: "Starfall (2008)
    {tmdb-4567}" is "Starfall (2008)"."""
    return _ID_TAG.sub("", name).strip()


def _tmdb_id(name: str) -> int | None:
    """TMDB's id a name tags for its show or film: "{tmdb-4567}", "[tmdbid-4567]"."""
    found = _TMDB_ID.search(name)
    return int(found["id"]) if found else None


def _title_and_part(stem: str, episode_title: str | None) -> tuple[str | None, int | None]:
    """The episode title and the part number. anitopy takes "S3 Part 2 - 03" to have the episode
    title "Part 2"; a real title with "part" in it ("Part of It") is no part."""
    if episode_title and (alone := _PART_ALONE.fullmatch(episode_title.strip())):
        return None, int(alone[1])
    before = stem[: stem.find(episode_title)] if episode_title and episode_title in stem else stem
    return episode_title, _part_of_season(before)


def _part_of_season(text: str) -> int | None:
    """The part of a season a name's text gives: "The Harbour Line S3 Part 2" is part 2."""
    found = _PART.search(text)
    return int(found[1]) if found else None


def film_part(stem: str) -> int | None:
    """Which part of a film in several files this is, from the end of its name: "CD1", "cd2",
    "pt1", "Part 2", "disc 2". None for a film in one file."""
    if found := _FILM_PART.search(_without_copy_marker(stem)[0]):
        return int(found[1])
    return None


def season_of_folder(folder: str) -> int | None:
    """The season a folder's name gives: "Season 02", "S02" or "Season_02" is 2, "Specials" is
    0, and "Season 2019" is 2019, a season numbered by its year as a daily show's are. None for
    any other folder."""
    if _SPECIALS_FOLDER.match(folder):
        return 0
    if match := _SEASON_FOLDER.match(folder):
        number = int(match[1])
        return number if number < 1000 or _a_year(number) else None
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
