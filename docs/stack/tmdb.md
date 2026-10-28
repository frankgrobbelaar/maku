# TMDB (finding series and films)

[TMDB](https://www.themoviedb.org) is the only catalogue Maku asks. It finds every series and film
there: their names in other languages, a show's seasons with their episodes, titles and air dates,
the specials in season 0, a film's collection, the posters, wide pictures and stills. It's how
Maku knows what each video is, which episodes are missing, and what to name files so media server
apps agree.

## The key

TMDB needs a key, and it's the owner's own (the repo is public, so no key is ever in the code).
A free TMDB account has two under **Settings › API**; Maku takes either:

- the **API Read Access Token** (long, the one Maku asks for), sent as `Authorization: Bearer …`;
- the shorter **API Key** (32 hexadecimal characters), sent as `?api_key=…`.

Setup has a step of its own for it ("Find your series and films"), and Settings › Titles and
artwork has the same box (`app/src/components/tmdb-key.tsx`), whose "Settings › API" opens TMDB's
page of keys in the browser. `PUT /tmdb` checks the key with TMDB (`GET /3/authentication`) and
keeps it only if TMDB accepts it; offline, nothing is kept and Maku says to try again online. A
key that's kept starts a scan, so the videos waiting for it are looked up. `DELETE /tmdb` forgets
the key: titles already found keep what TMDB said of them.

[maku/credentials.py](../../engine/src/maku/credentials.py) keeps it in the data folder's
`credentials.json`, encrypted by Windows for the signed-in user (DPAPI, `CryptProtectData`): it is
never in `maku.db`, so no export or backup carries it, and the file is useless on another PC or
account (Maku then asks for the key again). The box shows "Key ending ab12 · kept on this PC
only".

Without a key Maku reads every video (ffprobe) but identifies none: `Catalog.tmdb()` raises
`NoKeyError`, the scan finishes with a note saying so, and Home, "Which title is this?" and the
scan show "Maku needs your TMDB key to find your series and films", with "Add your key"
(`NoTmdbKey`). The videos wait, and the first scan after a key is added looks them up.

## What Maku asks

[maku/tmdb.py](../../engine/src/maku/tmdb.py), through [maku/web.py](../../engine/src/maku/web.py):

| Request | For | Kept |
| --- | --- | --- |
| `GET /3/authentication` | Checking a key | |
| `GET /3/search/tv?query=…`, `GET /3/search/movie?query=…`, with `first_air_date_year` or `primary_release_year` when the name gives a year | Finding a show or a film by a name | a week |
| `GET /3/tv/{id}?append_to_response=alternative_titles`, the same for `/3/movie/{id}` | A show's or film's details, with every other name TMDB knows it by | a week |
| `GET /3/collection/{id}` | The films of a film's collection | a week, and asked again with the film's weekly look |
| `GET /3/tv/{id}`, then again with `append_to_response=season/0,season/1,…` (20 at most per request) | A show with every episode of every season, specials included | asked again when due, or when a file's episode isn't on it |
| `GET /3/movie/{id}` | A film, as its title's row keeps it | asked again weekly |
| `GET /3/tv/{id}/images`, `GET /3/movie/{id}/images` with `include_image_language=en,null` | The posters to choose from for a title | a day |
| `https://image.tmdb.org/t/p/w342{poster_path}` and the like | A poster, a wide picture, an episode's still | once, in `artwork/` |

Answers are kept in the data folder's `cache` folder ([maku/cache.py](../../engine/src/maku/cache.py),
one JSON file per question), so a rescan asks TMDB nothing again; anything there can be deleted at
any time, and Maku asks again. A show's episode list is asked for again hourly while it airs and
weekly once it's finished, and films weekly (with their collections, which a new film may have
joined), so what's kept of them stays current. A file the kept episode list can't place has the
list asked for again at once, however recently it was: an episode can come out, and be listed,
within the hour.

[maku/core/catalog.py](../../engine/src/maku/core/catalog.py) turns the answers into plain values
(`Hit`, `Show`, `Episode`, `Film`) and into **entries**, the shape identifying weighs files against
(`Entry`): a show with all its seasons, or a film. An entry's id is the show's TMDB number, or the
film's negated (`entry_id`, `tmdb_of`), so a show and a film never share one. An entry carries every
name it goes by (TMDB's title, the original, the alternative titles), its kind ("series" or
"movie"), how many episodes, how long one lasts, when it started and ended, where it stands
(finished, airing, coming, cancelled, on a break: a film being made is coming), its synopsis,
genres, its network or first production company, and for a film, its collection's name and the
films before and after it in it (`PREQUEL`, `SEQUEL`, by release). Each episode keeps its own
synopsis (`overview`) and still (`still_path`), which an episode's details show: the still comes
from the image server at its own size (`original`; TMDB's other sizes of a still are 300 wide at
most), once, when a card first shows it.

## Finding a series or a film

[maku/catalog.py](../../engine/src/maku/catalog.py) (`Catalog`, one the engine shares, its waits
shared too) searches both kinds at once: the five best of the kind the files look like (films for
a film), then the three best of the other, each with its details and, for a film, its collection.
With the year the files give, it asks for that year's (`first_air_date_year` for a show,
`primary_release_year` for a film), so a film of a name many share is found however far down the
rest TMDB ranks it; when that year has none (a name's year can be a season's or a special's), it
asks for any year's. [maku/identify.py](../../engine/src/maku/identify.py) groups the files first
([maku/core/identify.py](../../engine/src/maku/core/identify.py), `group_files`): by the title their
names or folders give, by whether they look like a film, and by the year they give, as a remake
takes its name again (`The.Harbour.Line.1985.S01E01` and `The.Harbour.Line.2019.S01E01` are two
shows). A series' files without a year go with the one year its other files give; beside two
years of it, they're looked up on their own. Files whose names or folders give TMDB's id, as media
server apps tag them (`Northern Lights {tmdb-7206}`), are that show or film: it's asked for by
its id and taken, with no search. An id names no kind (TMDB numbers its shows and its films apart,
so 7206 is a show's as well as a film's): the kind the files look like is asked for first, then
the other, and only one whose names are the files' (`tagged`, at least 60% alike) is taken. When
neither is, or TMDB has no such one, the name is searched for. Then, for each other group:

1. **The ways its name reads** are asked in turn (`searches`): the name; each of two names when it
   gives one in brackets after the other (`Glass Orchard (The Orchard)`); and for a series' film
   or special named after it, its own name alone and with the series'. It stops at the first
   that finds a sure guess. When nothing is found at all, the name may be one TMDB writes another
   way (`Harbourline`): what its first word finds says how (`Harbour Line`), and that's asked
   (`respelled`).
2. **Each entry is scored** against the group, 0 to 100, with its reasons in the words the review
   screen shows (`guesses`): how alike the names are (up to 70, the closest of every name the entry
   goes by, a name that's the title's main part, before its subtitle, counting nearly whole), the
   year (+15 the same, +5 a year off, −25 otherwise: "From 2008, not 2011"), the kind (a film for
   films +10, a series for films −30, a film for episodes −40), the episodes (+10 when the files'
   highest number fits, −20 when a finished show has fewer: "Only 8 episodes, files go up to 12"),
   the length, and +5 for TMDB's own first. A film's length is its own, so the closer the better:
   +10 as long as it (give or take 2 minutes, or 2%), +5 within a tenth, nothing within a quarter,
   −15 beyond ("98 min, not 112"). An episode's varies around the show's: +5 within a quarter (or
   3 minutes), −15 beyond.
3. **Sure is 75, and clear of any namesake.** A guess at least that sure is taken, unless a guess
   whose names fit as well (a film of the same name from another year, a series and its remake)
   is sure too or less than 10 behind it: either could be the one (`sure_of`). A guess taken
   joins its title, its files placed in its seasons
   ([maku/core/placing.py](../../engine/src/maku/core/placing.py)). Anything else waits on "Which
   title is this?" with its best three guesses (those under 15 aren't shown), where the owner can
   also type a name: that's searched the same way, scored against the file, and a year typed after
   it ("Starfall 1962", "Starfall (1962)") asks for that year's too. The owner's choice is pinned,
   so no rescan undoes it.

Placing a show's files: by season and number (`S02E05`, or `05` in a `Season 02` folder), or by a
number counted straight through the show (`The Harbour Line - 30` is the 30th episode, wherever
TMDB's seasons break; in a season's folder too, when its files count on from the seasons before
it, `numbered_through`). A name that gives its season is numbered within it: an episode its season
doesn't list (`S03E05` before TMDB has it) is never counted from the show's first instead, nor is a
file in a season's folder counted back into an earlier season. When the kept list can't place a
file, the show's list is asked of TMDB again first; one TMDB still doesn't list waits for the
owner, and choosing its show asks which episode it is ("The Harbour Line has no season 3 episode
5"). A daily show's file, named by the day it aired (`The.Harbour.Line.2021.04.12`), is the
episode TMDB dates that day; when none or two aired that day, it waits. A file holding two
episodes (`s01e05e06`) keeps both. A special goes into season 0 by its number there (`S00E03`, or
`03` in a `Specials` folder) or by its own name among the show's specials (`Special 05 - The Night
Train`). One the show's list doesn't name is looked up by its own name, read as the series' (`The
Harbour Line: The Night Train`), and placed only when TMDB keeps it as a film or a one-off show: a
title of its own, or its show's special by the names TMDB gives it. Two files that land on one
episode with different numbers are both left for the owner.

## Collections

A film's details name the collection it belongs to (`belongs_to_collection`), and Maku asks for the
collection's films. The films of one collection make one franchise (the engine's word; the app says
"collection"), named as TMDB names it ("The Starfall Collection"), with a page of its own; a series
always stands alone, as TMDB ties no show to another. The rest of a collection, the films the
library lacks, is looked up in the background
([maku/franchises.py](../../engine/src/maku/franchises.py)): six entries at each of the watcher's
looks (every 15 seconds, so about 24 a minute), the ones not asked about yet first, then each
again weekly, or daily while it's still to come, its collection asked for afresh with it, so a
film that joins the collection turns up by itself. A collection's page lists them under "Missing
films", a coming one as "Coming".

## Limits and errors

TMDB allows dozens of requests a second; Maku asks far fewer.
[maku/web.py](../../engine/src/maku/web.py) gives a busy (429) or briefly failing (5xx) service a
few more tries, waiting as long as it asks (Retry-After) up to two minutes, and turns everything
else into a sentence: "TMDB didn't accept the key (…)", "Maku couldn't reach api.themoviedb.org
(…)". A scan that can't reach TMDB stops identifying and says so; the files wait for the next
scan.

## Terms and credit

TMDB's API is free for non-commercial use with attribution. Maku shows "This product uses the TMDB
API but is not endorsed or certified by TMDB" with TMDB's logo beside it, smaller than Maku's own,
in Settings, under About and under Titles and artwork: `components/tmdb-credit.tsx`. The logo is
TMDB's "alt short" file from its logos page, unchanged (`app/src/assets/README.md`); it's the one
picture the repo carries that isn't Maku's own, and the third-party notices say it's TMDB's.

## Tests

No test reaches TMDB, and there's no key in the repo: `tests/fake_web.py` answers instead, and
`tests/tmdb_data.py` builds TMDB's answers in TMDB's shape (shows with their seasons, films and
their collections, searches) for the made-up titles each test names. `tests/services.py` is the
made-up world most tests ask, its searches keeping to a year as TMDB's do; a test can add to it,
such as the 1985 series The Harbour Line that the 2019 one remade, or six other films called
Northern Lights, more popular than the 2004 one.
