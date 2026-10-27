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

- **Scene names.** A scene name's title ends where its episode code, its year or its release's
  words begin (`_scene`). `The.Harbour.Line.S01E02.1080p.WEB-DL.DDP5.1.H.264-GROUP` is The Harbour
  Line, season 1, episode 2; `glass.orchard.s01e05e06.1080p.bluray.x265-grp` holds episodes 5 and
  6 (so do `S01E05-E06` and `S01E05-06`; `1x05` is an episode code too); `Show.Name.2019.S01E01`
  is Show Name of 2019. `Starfall.2008.EXTENDED.1080p.BluRay.x264` is the film Starfall of 2008, and
  so are `Starfall (2008) Director's Cut` and `Starfall.2008.1080p`; `Northern Lights 2004` is
  Northern Lights of 2004. A year ends the title only when nothing, its own bracket or the
  release's words follow it, and a release's word before a year is the title's (`The Web of Lies
  (2006)`); a year followed by another is the title's too (`Blade.Line.2049.2017.1080p` is Blade
  Line 2049, of 2017). What comes
  between an episode code and the release's words is the episode's title (`Harbour Line S03E08
  Finale`), but source words (`WEB`, `BluRay`) and codecs never are. Dots and underscores are
  spaces when the name has none of its own.
- **Folders.** A `Season 03` (`S03`, `Series 3`, `Season_03`) or `Specials` folder gives
  `folder_season`; the show folder above it (`The Harbour Line (2019)`) gives `folder_title` and the
  year. A season's folder named after its show gives both: `The Harbour Line Season 02`, `The
  Harbour Line 2nd Season`, `The Harbour Line S2` and `Glass Orchard (Season 2)` are the show and
  its season (`Glass Orchard S01-S04` holds several, so it gives none). A release's folder is read
  as its files are: `Quiet.Hours.S02.1080p.BluRay.x264-GROUP` is Quiet Hours' season 2, and `Paper
  Kites 1999 DVDRip XviD-GROUP` is Paper Kites of 1999. A folder name's tags at its end go when
  they hold a release's words or a number (`[Group] The Harbour Line (S01-S03) [BD]` is `The
  Harbour Line`), a year among them kept; a name's own brackets stay. General folders
  (`Downloads`, `Movies`, `TV`, `Burnt`, `Rips`, `Extras`…) never count as titles. A folder of a
  show's films or specials (`The Harbour Line Specials`, a release's `2a. Movies`) is passed over
  for the folder above, and a bare number in one is a special, or a film no name says which of,
  which waits for the owner.
- **Films.** A film in a folder of its own, named as the folder is (`Starfall (2008)\Starfall
  (2008).mkv`), is that film, the way films are filed, whatever its name holds. A film in parts
  (`CD1`, `CD2`, `Disc 2`, `pt1`, `Part 2` at the end of its name: `film_part`) is one film, and the
  part is no episode and no part of its title. A series' release that numbers its films (`The
  Harbour Line - Movie 02 - Low Tide`) makes each a film titled `The Harbour Line: Low Tide`, with
  `series` The Harbour Line; the release's number counts its own films, not TMDB's, so it's left
  out.
- **Specials.** `The Harbour Line - Special 05 - The Night Train` is a special of The Harbour Line
  named The Night Train, which places it among the show's specials by name; season 0 in a name
  (`S00E03`) or a `Specials` folder is a special too.
- **Copies and samples.** `(copy)`, ` - Copy` and ` (2)` are removed before parsing and set
  `is_copy`. A release's sample (`starfall.2008.1080p-sample.mkv`, `Starfall 2008 sample.mkv`, or
  anything in a `Sample` folder) is an extra, never the film.
- **Kinds.** Episode, special (season 0, or a name that says so), movie (no episode number), extra
  (a sample, a trailer, a menu, a creditless opening or ending) or DVD file (`VTS_01_1.VOB`, unknown
  until matched).
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
- anitopy ships no types; `engine/typings/anitopy/__init__.pyi` declares the one function Maku uses.
- Add every name that parses wrongly to `engine/tests/core/test_names.py` before fixing it, with a
  made-up title in the shape the real one had.
