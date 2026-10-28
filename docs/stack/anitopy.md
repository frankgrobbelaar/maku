# anitopy (reading file names)

[anitopy](https://github.com/igorcmoura/anitopy) 2.1.1 turns a release's file name into its parts:
title, episode number, season, year, release group, resolution. It is a Python port of Anitomy, a
release-name parser, and knows how releases number and tag their files. Maku wraps it in
[`maku/core/names.py`](../../engine/src/maku/core/names.py) (`parse_name`) and adds its own rules:
for scene names, for what only the folders know, and for what anitopy gets wrong. A name is a
hint: matching it against TMDB confirms it ([tmdb.md](tmdb.md)).

## Why anitopy

Maku kept its sibling Kura's parser, with the rules and tests built on it. anitopy reads numbers
counted straight through a show (`The Harbour Line - 112`), release groups and resolutions well,
and it is small and pure Python. guessit, the usual parser for scene names, read such numbers as
seasons (`112` as S01E12, `(2011)` as season 2011) when Kura compared the two on 2026-10-10.
Scene names are what anitopy reads least well (it leaves a film's year and a release's words in
the title, and misses `s01e05e06`), so Maku reads those itself (below).

anitopy hasn't had a release since 2022, but Maku's rules cover its gaps, and the tests pin the
behaviour, so swapping parsers later is safe.

## What Maku adds

- **Scene names.** A scene name's title ends where its episode code, its air date, its year or
  its release's words begin (`_scene`). `The.Harbour.Line.S01E02.1080p.WEB-DL.DDP5.1.H.264-GROUP`
  is The Harbour Line, season 1, episode 2; `glass.orchard.s01e05e06.1080p.bluray.x265-grp` holds
  episodes 5 and 6 (so do `S01E05-E06`, `S01E05-06`, `S01E05.S01E06`, `1x05-06` and `1x05-1x06`;
  `1x05` is an episode code too, and `S2019E05` one of a season numbered by its year);
  `Show.Name.2019.S01E01` is Show Name of 2019. `Starfall.2008.EXTENDED.1080p.BluRay.x264` is the
  film Starfall of 2008, and so are `Starfall (2008) Director's Cut`, `Starfall.2008.1080p`,
  `Starfall.2008.German.DL.1080p` and `Starfall [1080p] (2008)`; `Northern Lights 2004` is
  Northern Lights of 2004. A year ends the title only when nothing, its own bracket or the
  release's words follow it (its source, sound, cut or languages: `EXTENDED`, `German`, `DL`,
  `MULTi`, `VOSTFR`, `NORDiC`…), and a release's word before a year is the title's (`The Web of
  Lies (2006)`); a year followed by another is the title's too (`Blade.Line.2049.2017.1080p` is
  Blade Line 2049, of 2017), and so is one past next year by the PC's clock (`Starfall 2049`). A
  release's words in brackets inside a title go (`[1080p]`, `(Extended)`); a name's own brackets
  stay. What comes between an episode code and the release's words is the episode's title
  (`Harbour Line S03E08 Finale`), but source words (`WEB`, `BluRay`), codecs and languages never
  are. Dots and underscores are spaces when the name has none of its own.
- **Episode codes decide.** A name with an episode code is an episode (a special in season 0),
  whatever its episode's own title says: `Glass Orchard (2012) - S02E07 - Special`, `… - Movie`
  and `… - Blood Sample` are episodes 7 of season 2. A name that is its code alone (`S01E01 -
  Pilot.mkv`, `s01e05.720p.hdtv.x264-grp.mkv`) has no title of its own: its folders name the show,
  and what follows the code is the episode's title.
- **Daily shows.** A daily show's episode goes by the day it aired: in
  `The.Harbour.Line.2019.01.15.Guest.One.720p.HDTV-GRP` and `The Harbour Line - 2019-01-15 - Guest
  One` the title ends at the date, the episode's title follows it, and the day is kept as `aired`
  for placing it by TMDB's air dates, never read as an episode number (anitopy took the month for
  one) nor its year as the show's. A day that never was (`2019.02.30`) gives no `aired`, and the
  file waits for the owner. A season's folder may be numbered by its year (`Season 2019`).
- **Folders.** A `Season 03` (`S03`, `Series 3`, `Season_03`) or `Specials` folder gives
  `folder_season`; the show folder above it (`The Harbour Line (2019)`) gives `folder_title` and the
  year. A season's folder named after its show gives both: `The Harbour Line Season 02`, `The
  Harbour Line 2nd Season`, `The Harbour Line S2` and `Glass Orchard (Season 2)` are the show and
  its season (`Glass Orchard S01-S04` holds several, so it gives none). A release's folder is read
  as its files are: `Quiet.Hours.S02.1080p.BluRay.x264-GROUP` is Quiet Hours' season 2, and `Paper
  Kites 1999 DVDRip XviD-GROUP` is Paper Kites of 1999. A folder name's tags at its end go when
  they hold a release's words or a number (`[Group] The Harbour Line (S01-S03) [BD]` is `The
  Harbour Line`), a year among them kept; a name's own brackets stay. General folders
  (`Downloads`, `Movies`, `TV`, `Burnt`, `Rips`, `Extras`, `Shorts`…) never count as titles. A
  folder of a show's films or specials (`The Harbour Line Specials`, a release's `2a. Movies`) is
  passed over for the folder above, and a bare number in one is a special, or a film no name says
  which of, which waits for the owner.
- **Id tags.** Media server apps' tags in a folder's or a file's name (`{tmdb-12345}`,
  `[tmdbid-12345]`, `{imdb-tt1234567}`, `{tvdb-98765}`, `{edition-Director's Cut}`) are no part of
  the title. TMDB's id, from the file's name or the folder that names its show or film, is kept as
  `tmdb_id`, for identifying it.
- **Films.** A film in a folder of its own, named as the folder is (`Starfall (2008)\Starfall
  (2008).mkv`, or Maku's own `… - pt1` for its first part), is that film, the way films are filed,
  whatever its name holds. A film in parts (`CD1`, `CD2`, `Disc 2`, `pt1`, `Part 2` at the end of
  its name: `film_part`) is one film, and the part is no episode and no part of its title; a
  `Part 2` after anything but a film's year may be a title's own (`… - The Long Night Part 2`). A
  film's title can end in a number, which anitopy takes for an episode's: before the film's year
  (`Area.51.2015`, `Paper Kites 2 (2003)`), the number is the title's, unless a dash comes before
  it (`Glass Orchard - 05 (2012)`) or the file is in a season's folder. A series' release that
  numbers its films (`The Harbour Line - Movie 02 - Low Tide`) makes each a film titled `The
  Harbour Line: Low Tide`, with `series` The Harbour Line; the release's number counts its own
  films, not TMDB's, so it's left out.
- **Specials.** `The Harbour Line - Special 05 - The Night Train` is a special of The Harbour Line
  named The Night Train, which places it among the show's specials by name; season 0 in a name
  (`S00E03`) or a `Specials` folder is a special too. A show whose name has the word keeps it as
  its name's: anitopy reads the word each time it's there, so `The Special Ones Special 05` is a
  special (one more than the name holds) and `A Very Special Night (2015)` a film.
- **Copies and samples.** `(copy)`, ` - Copy` and ` (2)` are removed before parsing and set
  `is_copy`. A release's sample (`starfall.2008.1080p-sample.mkv`, `Starfall 2008 sample.mkv`,
  `glass.orchard.s01e05.720p.hdtv-sample.mkv`, or anything in a `Sample` folder) is an extra, never
  the film or the episode; an episode's own title may end with such a word, after its code or
  after a dash and its number (`… - S02E07 - Blood Sample`, `Glass Orchard - 05 -
  Behind-the-Scene`). `Other`, `Scenes` and `Shorts` folders hold extras only right inside a
  title's own folder (a season's, or one with its year: `Starfall (2008)\Shorts`); a library's
  own (`Animation\Shorts`) holds films.
- **Discs.** A disc's own files, as a burnt DVD (`VIDEO_TS\VTS_01_1.VOB`) or a Blu-ray copied whole
  (`BDMV\STREAM\00000.m2ts`) keeps them, go by the disc's folder above those: `NORTHERN_LIGHTS_DISC1`
  is Northern Lights, `Starfall (2008)` Starfall of 2008; a library's folder (`DVDs`, `Burnt`) names
  none. They're looked up as a film and offered on "Which title is this?", never taken on their own:
  which part of a disc a file is, no name says.
- **Kinds.** Episode (an episode code, a number, or a daily show's day), special (season 0, or a
  name that says so), movie (no episode number nor day), extra (a sample, a trailer, a menu, a
  creditless opening or ending) or a disc's own file.
- **Clean titles.** Type and release words at the end of a title (`Movie`, `Final`) are removed,
  but not `End`, which anitopy reads as a release's word wherever it is and titles end with; a
  title that is only a number becomes the episode (`05.mkv` in a season's folder). A year in
  brackets with more in them (`(2016 BluRay - 1080p)`) gives the year, which anitopy passes over;
  a span (`1999-2004`) or a checksum doesn't.
- File-name values (`title`, `season`) and folder values (`folder_title`, `folder_season`) stay
  apart, because they can disagree: `Season 02\The Harbour Line - 14.mkv` may be counted straight
  through the show. Matching decides: a season's folder whose files count on from the seasons
  before it places them by their numbers (`numbered_through` in
  [maku/core/placing.py](../../engine/src/maku/core/placing.py)).

## Things to know

- anitopy keeps its state in module globals, so `parse_name` takes a lock; never call
  `anitopy.parse` directly.
- anitopy 2.1.1's search for an episode's own title (`Parser.search_for_episode_title`) went round
  forever, holding that lock, on a name whose episode number is followed by a dash and nothing it
  can read (`Glass Orchard - 01 - .x`, `Glass Orchard - 01 - .2`): ported from Anitomy, it takes
  "no token left" for "start again from the first". `names.py` puts in the same search when it's
  imported, ending there as Anitomy's does. When anitopy moves past 2.1.1, the hang test in
  `test_names.py` (run in a child process, so a hang fails it rather than stopping the run) says
  whether its own search still needs it.
- anitopy ships no types; `engine/typings/anitopy/__init__.pyi` declares the one function Maku
  calls, and the search above reaches `anitopy.parser` by name (`importlib`), untyped.
- A year is never past next year's by the PC's clock (`_this_year` in `names.py`; a test fixes it).
- Add every name that parses wrongly to `engine/tests/core/test_names.py` before fixing it, with a
  made-up title in the shape the real one had.
