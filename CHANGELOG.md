# Changelog

Every change to Maku you'd notice, newest first. Versions follow
[semantic versioning](https://semver.org): a new major number means something you have to act on,
a new minor number brings features, a new patch number fixes things. Every version can be
downloaded from the [downloads page](https://frankgrobbelaar.github.io/maku/), and an installed Maku
shows these notes when it offers the update.

## Unreleased

## 1.2.0 - 2026-10-28

### Changed

- The engine is built with the newest versions of the libraries it uses: FastAPI 0.162 and
  Starlette 1.10. The window has Lucide's newest icons, 1.62.

## 1.1.0 - 2026-10-28

### Changed

- The window is built with the newest versions of the libraries it uses: React Router 8.5,
  TanStack Query 5.105, Lucide's icons 1.61 and Vite 8.3.5.

## 1.0.0 - 2026-10-28

Maku 1.0, the first version meant for everyday use. There's nothing to do on your part: it
updates as any version does, and keeps everything you have.

### Changed

- Setup goes on without a folder, for a PC with no videos on it yet: "Skip for now", then
  "Finish" opens Home, whose "Add a folder" adds one and scans it there and then.
- Convert and Tidy up say "No videos yet" while there's no folder, rather than that everything
  is done.
- Setup's examples of clean names are an episode and a film, named as releases name them.

## 0.2.0 - 2026-10-28

### Added

- Burnt DVDs and Blu-rays copied whole: their files (`VIDEO_TS`, `BDMV\STREAM`) are named by the
  disc's own folder ("NORTHERN_LIGHTS_DISC1" is Northern Lights), so "Which title is this?" offers
  the right film first. Maku never takes one on its own, as no name says which part of a disc a
  file is.
- A daily show's episodes named by their day ("The.Harbour.Line.2021.04.12") go to the episode
  TMDB dates that day; a day with none, or with two, waits for you.
- A name tagged with TMDB's id ("{tmdb-7206}", as media server apps write it) is that series or
  film, found without a search: the series or the film of that number whose names are the
  file's, as TMDB numbers each kind apart.

### Changed

- Home's tile of pictures larger than 1080p says what converting does to them by your standard:
  "kept at its size, up to 4K", or "brought down to 1080p". English sound reads "in the files",
  not "dubbed".
- A collection of films no longer offers "Most missing" as an order: a film misses no episodes.
- Pictures are named as people call them: 1440p is 1440p, not 4K, and a 1920x1200 picture is
  1080p, kept at its size. A TS file's change reads "TS becomes MKV".

### Fixed

- Names Maku read wrongly:
  - A name like "Glass Orchard - 01 - .x.mkv" no longer stops the scan for good.
  - An episode named by its code alone ("S01E01 - Pilot.mkv") takes its show from its folder.
  - Films whose titles end in a number ("Orchard 12 (2015)", "Paper Kites 2 (2003)") stay films,
    and a film in parts ("pt1", "Part 2") is one film.
  - An episode titled "Blood Sample" is an episode, not a sample, and one titled "Part 2" is
    that episode, not the second part of its season.
  - A daily show's episodes ("2019.01.15") are no longer taken for episode 1.
  - Language and release words after a year ("2008.German.DL") and in brackets ("[1080p]")
    leave the title, and a year past next year isn't taken for one.
  - "S01E05.S01E06" and "1x05-06" hold two episodes, and a code decides an episode's kind
    whatever its title says ("- Special").
  - Folders named Shorts, Other or Scenes are extras only inside a title's own folder, and
    `{tmdb-12345}` tags are left out of titles.
  - A film's edition ("Aliens (1986) Special Edition", "Starfall.2008.Special.Extended.Edition")
    is no part of its title, and no longer makes it a special.
  - A number inside a film's title stays in it: "Paper Kites 2 The Long Way Home (2003)" is a
    film, not episode 2.
  - "Series 2 - Episode 1", as British shows name them, and "Season.2.Episode.1" are season 2's
    first episode.
  - "Quiet Hours - Christmas Special" is the show's special of that name.
- Finding titles:
  - A show's newest episode no longer lands in season 1 while Maku's episode list hasn't caught
    up: Maku asks TMDB again first, and an episode TMDB doesn't list yet waits for you, so Tidy
    up never sets the real season 1 episode aside.
  - A series and its remake are told apart by the year in their names, and the year is searched
    with, so a film many others share a name with is found, in a scan and when you type
    "Northern Lights 1962" on "Which title is this?".
  - A film named without its year waits for you when another film of that name fits as well,
    the one closer in length first.
  - A disc's film is scored as a film when you search for it.
  - Files are no longer one episode out when TMDB gives a show's first episode no date.
  - A film that joins a collection after Maku first looked turns up by itself.
- Converting:
  - Old bit-rate tags in a file no longer set its result's ceiling or its estimate: Maku's
    results carry none, and a stale one is ignored.
  - A picture of an odd width or height (1920x803) is made one line smaller, so its result
    passes the check.
  - Sound and subtitles an MKV can't hold no longer stop a conversion: PCM becomes FLAC (32-bit
    stays PCM), float PCM stays as it is, teletext and closed captions are left out, saying so.
  - A queued file that's at your standard by its turn is passed over, not failed.
- The look:
  - Maku starts in your scheme from its first frame, with no flash of Velvet, and a reload keeps
    the scheme you chose last.
  - The notes in the window are readable in every scheme's light (Graphite's and Lagoon's were
    faint), and the queue's pictures and the empty shelf follow your scheme.
  - A light-or-dark or colours choice that couldn't be kept goes back to the one that is.

## 0.1.0 - 2026-10-27

### Added

- Maku: one app for your TV series and movies, wherever they came from (discs you ripped or
  burnt, downloads you bought, recordings). Point it at your folders, in any layout, and it reads
  every video, finds each series and film on TMDB, says what's missing or broken, tidies the
  names and folders, and converts the whole library to one standard.
- Finding your series and films on TMDB with your own free key, asked for in Setup's own step.
  Release names read as releases write them ("The.Harbour.Line.S02E03.1080p.WEB-DL",
  "Starfall.2008.EXTENDED.1080p.BluRay", "glass.orchard.s01e05e06"), with their folders, seasons
  numbered or counted straight through, specials, films in parts, and names TMDB knows in other
  languages. What Maku isn't sure of waits on "Which title is this?", with its best guesses.
- Collections: the films TMDB keeps together, on Home and on a page of their own, named as TMDB
  names them, with the films you don't have yet ("Missing films"), new ones turning up by
  themselves.
- The converting standard, 4K or 1080p: what's 4K stays 4K with its HDR, nothing is made bigger
  than it is, every sound track is kept as it is, and interlaced discs are made progressive. HEVC
  10-bit on your graphics card (NVIDIA, AMD or Intel), every result checked before it takes its
  original's place.
- Four colour schemes, each in light and dark: Velvet (wine and crimson, the default), Lagoon,
  Dusk and Graphite, in Settings › General.
- Everything Maku's sibling Kura does for its library, for yours: the gap analysis next to each
  series, clean names and tidy folders with undo, the queue and its nights, English subtitles made
  on your PC, the player, watched and Continue watching, Coming up, the overnight health check,
  search, History, backups, the tray and updates.

