# Maku

Maku (幕, "curtain") is a personal Windows app for one person's library of **TV series and
movies**. It maps folders in any layout, identifies every file on TMDB, reports what is missing or
broken, renames for media servers, and converts the whole library to one standard, up to 4K with
its HDR. The library is a mix: discs ripped or burnt, downloads bought, recordings. It is the
owner's own tool: one user, one PC, never commercial, no sign-in. The code is shared under the MIT
licence: anyone may fork it, but the repo takes no contributions.

Maku is the sibling of **Kura** (`C:\GitHub\kura`, the owner's other library app): it began as Kura
1.3.0, and keeps its layout, stack, pipelines, shapes, type and motion. Kura's decisions stand for
Maku unless this file says otherwise. **Maku is purely for TV series and movies** (the owner,
2026-10-28: "this is purely for tv series and movies"): nothing in the app, the code, the tests or
the docs is about any other kind of library.

**Where it stands (2026-10-28):** built from Kura, made Maku's own: TMDB-only identification with
scene names, collections, the four colour schemes and the curtain logo, the live-action standard
(4K or 1080p, never bigger, HDR and every sound track kept), its own repo, pipelines, downloads
page and docs. Reviewed, tested end to end on made-up files (a library of tiny real videos, TMDB
stood in for) and released by Claude, as the owner asked (2026-10-27: "As you work and develop, I
want you to make releases as well ... until you are happy to release 1.0.0", "You are in control
of the releases"): 0.1.0 on 2026-10-27, then 0.2.0 and 1.0.0, the first meant for everyday use,
on 2026-10-28. From 1.0.0 on, releasing is the owner's call. CHANGELOG.md has every release.

## Ground rules

- **One branch.** Work on `main` in `C:\GitHub\maku`. No feature branches, worktrees or PRs unless
  the owner asks. Commit and push to `main` once every check passes. If another session is working
  at the same time, stage only your own files (never `git add -A`).
- **Never change Maku's look unasked.** Its four schemes, type, shapes and motion live in
  [app/src/styles/tokens.css](app/src/styles/tokens.css); Kura's Cinema stays Kura's.
- **Nothing changes until the owner reviews it.** Renames, moves, deletions and conversions are
  proposed first, applied only when approved, logged, and undoable. Duplicates and replaced
  originals go to quarantine (30 days), never straight to deletion; the one exception is the
  owner's own choice to delete converted files' originals once each result is checked and in
  place. Video files are never touched by uninstalling.
- **Maku is personal.** No email address, no company name (no employer, no organisation behind
  Maku) and no personal details beyond the owner's name (LICENSE, commit author), anywhere in the
  project: files, test data, commit messages, publisher, accounts, signing. The publisher name is
  "Maku". Commits carry only the owner's GitHub no-reply address (the clone's `user.email`), and
  Claude's co-author line has no address.
- **Only ship what Maku may share.** Maku is MIT. A dependency's licence must be on the allowed
  list in [engine/tools/third_party_notices.py](engine/tools/third_party_notices.py) (the
  installer build stops otherwise); code adapted from elsewhere keeps its notice (shadcn/ui:
  `app/src/components/ui/LICENSE-shadcn.txt`); no video, artwork or other media in the repo or the
  installer. Tests, examples, the README's pictures and the design boards use **made-up titles
  only** (The Harbour Line, Glass Orchard, Quiet Hours, the Starfall films in The Starfall
  Collection, The Lantern Keeper, Northern Lights), never a real series or film. The one exception
  is TMDB's logo, which its terms ask for beside its credit line (`app/src/assets/README.md`).
- **Every change you'd notice goes in CHANGELOG.md**, in the same commit, under "Unreleased"
  (see [docs/releasing.md](docs/releasing.md)). Versions are semantic, and every release must be
  newer than the last so installed copies see it as an update.
- **Latest versions.** Use the newest stable release of every package, tool and model, and keep
  them current (see "Updating dependencies" in [docs/development.md](docs/development.md)),
  without raising what a PC needs.
- **Fix what you find.** A real fault found while working is fixed in the same piece of work, test
  first. Ask only about what is genuinely the owner's call: scope, money, anything irreversible or
  public.
- **Scoping means talking.** When the owner asks "is it possible…" or is scoping, answer in the
  conversation: no code, scripts or long checks.
- **Simple beats clever.** The bar is Revolut or Linear: few elements, one clear primary action,
  plain language, motion that explains. Code follows the same bar: small modules, obvious names.

## Layout

```
AGENTS.md       the guide for coding agents; each area below has its own AGENTS.md
CHANGELOG.md    every change you'd notice, by version
LICENSE         MIT
app/            the desktop app
  src/            React UI (TypeScript): components/, features/, lib/, styles/
  src-tauri/      Tauri shell (Rust): window, engine process, look, updates, installer config
engine/         the engine (Python): src/maku/, tests/, tools/ (build tools), maku-engine.spec,
                openapi.json
docs/           how it all works; one page per tool in docs/stack/
scripts/        release.mjs (versions, notes, the downloads page), installer notes
.github/        CI and release workflows
```

## Commands

Run the app (Vite, the Rust shell, and the engine from source):

```powershell
cd app; pnpm tauri dev
```

Check everything CI checks (each line from the repo root):

```powershell
cd engine; uv run ruff format --check; uv run ruff check; uv run pyright; uv run pytest
cd app; pnpm check; pnpm build
cd app/src-tauri; cargo fmt --check; cargo clippy --all-targets -- -D warnings; cargo test
node --test "scripts/*.test.mjs"
cd app; pnpm build:engine; pnpm build:notices
```

Fix formatting: `uv run ruff format` (engine), `pnpm fix` (app), `cargo fmt` (shell).
Build the installer locally: `cd app; pnpm build:installer` (needs the signing key, see
[docs/releasing.md](docs/releasing.md)). Release: on GitHub, Actions › Release › Run workflow on
`main` (patch, minor, major or an exact version); from a PC,
`node scripts/release.mjs patch|minor|major` (commits and tags), then
`git push --atomic origin main v1.2.3`.

## How it fits together

- **Shell** (`app/src-tauri`, Tauri 2, Rust): the window with its own title bar, one instance only.
  It starts the engine with a fresh token, tells the UI where it is, stops it on exit, keeps the
  look (light or dark, and the scheme) and installs updates. Keep it thin.
- **UI** (`app/src`, React 19, Tailwind 4): talks to the engine over HTTP on 127.0.0.1 with the
  token. Server data goes through TanStack Query; screens live in `features/`.
- **Engine** (`engine/`, Python 3.14): everything else. A FastAPI app (`maku serve`) and a CLI,
  bundled by PyInstaller as a folder with its own Python. Library logic goes in `maku/core` as
  pure functions with no I/O; the code around it does files, network and database.
- **Data**: one SQLite file, `%LOCALAPPDATA%\Maku\maku.db`, upgraded by append-only migrations in
  `maku/migrations.py` (Maku's first is Kura's schema at 1.3.0, made TMDB's). Development uses
  `engine/.dev-data`, never the real folder.
- **Contracts**: the engine's API is snapshotted in `engine/openapi.json` (a test fails when it
  drifts); the UI's types in `app/src/lib/engine.tsx` mirror it by hand. Change both together.

Details: [docs/architecture.md](docs/architecture.md).

## Decisions

Everything decided so far. Don't ask again; change only with the owner.

**The product**
- A separate app from Kura, with its own name, repo and releases (the owner, 2026-10-27: "It would
  be a separate app with its own name, repo etc."). Maku was the owner's pick of six names ("Maku
  sounds awesome!").
- Point Maku at folders in any layout: one series per folder, season folders, films in folders of
  their own or loose, or everything mixed in Downloads. Files live on local drives. Setup's
  folders can wait, as the owner had no series or films on the PC at first (2026-10-27: "Is it a
  problem if I dont have any films, tv series on here now?"): "Skip for now", "Finish" opens Home,
  and Home's "Add a folder" adds one and scans it.
- **TMDB identifies everything**, with the owner's own free key: Maku asks for it in a Setup step of
  its own ("Find your series and films") and in Settings › Titles and artwork, and keeps it on the
  PC (Windows' DPAPI), never in the code or an export. Without a key Maku reads the videos but
  identifies nothing; Home, "Which title is this?" and the scan say so, with the way to add one.
- Names are read as releases write them: scene names end their title at the episode code, the
  year or the release's words ("The.Harbour.Line.S02E03.1080p.WEB-DL", "Starfall.2008.EXTENDED",
  "glass.orchard.s01e05e06"); season folders, specials (season 0), absolute numbers, daily
  shows' days ("2021.04.12"), films in parts (CD1) and samples (extras) are understood. The year
  in a name groups a film or a series apart from its remake (and is searched with), and a name
  tagged with TMDB's id (`{tmdb-12345}`) is that title. An episode the show's list doesn't have
  yet waits, once Maku has asked TMDB again, and is never counted into an earlier season; a film
  another of its name fits as well waits too. What Maku isn't sure of waits on **"Which title is
  this?"**, with its guesses; a video that is neither is "set aside". The owner's choices are
  pinned so a rescan never undoes them.
- **Collections**: the films TMDB keeps in one collection make one shelf item and a page of their
  own, named as TMDB names the collection ("The Starfall Collection"), with "Missing films" (the
  collection's films the library lacks, looked up in the background, a coming one marked so). A
  series stands alone. Kinds are "TV series" and "Movie".
- Everything else Kura does stays, for series and movies: the gap analysis per series (a Markdown
  report), clean names (Plex's layout, never named in the app: "Clean names" or "Keep my names"),
  tidy folders with undo, quarantine, the queue with nights only, English subtitles made on the PC
  with Whisper (from a video's own language: English is written down, other languages translated),
  the player, watched and Continue watching, Coming up, the overnight health check, search,
  History, backups, the tray, notifications and updates.
- **The converting standard** (the owner, 2026-10-27: "We would need higher quality conversion,
  perhaps to 4k"): **4K** (the default) or **1080p**, chosen on Convert and in Settings. The
  standard is a top size: a picture bigger than it comes down to it, and **nothing is made bigger
  than it is** (without a model good at real faces and fast enough on the owner's card, enlarging
  only makes files bigger; a TV upscales as well). HDR (PQ and HLG) is kept, its colours set with
  ffmpeg's `setparams` (ffmpeg 9 ignores them as options) and checked in the result; Dolby
  Vision's own layer only while a file needs no new picture, and profile 5 is never made anew.
  Every sound track is kept as it is (TrueHD, DTS-HD, Atmos); only sound MKV can't hold changes:
  integer PCM becomes FLAC (32-bit stays PCM), float PCM stays as it is, and subtitles MKV can't
  hold (teletext, closed captions) are left out, saying so. Old bit-rate tags are cleared from
  results and never trusted; a picture of an odd size is made one line smaller. Interlaced discs
  are deinterlaced (telecined film too, not restored to 24 frames). A picture is named as people
  call it: 1440p is 1440p, and 1920x1200 is 1080p. The result is HEVC 10-bit in MKV, on the
  card's encoder (NVENC, AMF or Quick Sync), checked before it replaces its original.
- NVENC's settings (measured 2026-10-27 on the owner's card): preset p6, constant quality 21, with
  a maxrate of the original's own bit rate, at most 15/25/40/60/100 Mb/s for
  SD/720p/1080p/1440p/4K (without a maxrate NVENC's VBR quietly caps at its preset's figure, about
  10 Mb/s at 1080p: Kura's settings have that cap too). On the GTX 1660 Super an hour of 1080p converts in about 8
  minutes and an hour of 4K in about 32. Setup's last step and Settings › About test the encoder,
  the player and DirectML (for the speech models), and time this PC. See docs/stack/encoding.md.
- No piracy, in any form (as Kura): Maku looks after video already on the PC and plays it only in
  its own window; it never searches for, downloads or shares video, never streams it over the
  internet, never gets around copy protection (it reads ripped files, it doesn't decrypt discs),
  and downloads no sound tracks or subtitle files. The README, the downloads page and Settings ›
  About say it's for videos you have the right to keep and watch.
- Kura's words never name Plex, Jellyfin or any media server; Maku's don't either. The README and
  the downloads page say "media server apps".
- Maku is purely for TV series and movies (the owner, 2026-10-28), in the app, the code, the
  tests and the docs alike.

**Design**
- **Four colour schemes**, each in light and dark (the owner asked for four, 2026-10-27; Velvet
  the default): **Velvet** (wine and crimson, brass for ready), **Lagoon** (deep teal, a coral
  sun), **Dusk** (indigo and coral pink), **Graphite** (black and white). Picked in Settings ›
  General ("Colours", beside "Light or dark"); the shell keeps the choice and tells the page before
  its first frame. Every colour token reads its scheme's (`--scheme-*` in tokens.css); light or
  dark works as in Kura ("Same as Windows", "Light", "Dark").
- Kura's shapes, type and motion: Manrope for words, Geist Mono for paths, sizes and times; pill
  buttons; panels 16 to 24 px round; status by shape first (ready solid, converting pulsing, to
  convert solid blue, broken hatched, missing hollow); one curve `cubic-bezier(.2,.8,.2,1)`, none
  when Windows' animation effects are off.
- The logo is a stage curtain drawn back, cream on a crimson tile (`app/src-tauri/icons/maku.svg`,
  `app/src/components/maku-logo.tsx`), Claude's design at the owner's word ("I will let you
  choose").
- Canvases: [Maku Design](https://claude.ai/artifact/1pVuwSLdjXnp4gPJygp8B8) (the names and the
  schemes). Kura's canvases are the source for every screen's layout.

**Architecture**
- As Kura: Tauri 2 shell, React + Tailwind + shadcn/ui UI, Python engine sidecar built with
  PyInstaller as a folder, a local API with a per-launch token, SQLite.
- Identification: anitopy (a release-name parser) with Maku's rules reads names
  (`maku/core/names.py`); TMDB's search finds shows and films (`maku/catalog.py`, the kind the
  files look like first), each with its other names and, for a film, its collection; scoring in
  `maku/core/identify.py` (name, year, kind, episodes, length); placing in TMDB's seasons in
  `maku/core/placing.py`. An entry is a TMDB show (its id) or film (its id negated). Answers are
  kept a week. See docs/stack/tmdb.md and docs/stack/anitopy.md.
- Conversion: ffmpeg decodes (deinterlacing detected with idet), scales down when needed and
  encodes HEVC 10-bit on the card; Maku's own mux keeps the sound, subtitles, fonts and chapters
  and tags the result. No AI upscaling.
- Speech (English subtitles) as Kura's: Whisper's ONNX exports on DirectML, pyannote's
  segmentation model to find who speaks.

**Data**
- `%LOCALAPPDATA%\Maku`: maku.db, artwork cache, nightly backups (keep 7), logs (30 days), and
  `tools\` (ffmpeg, downloaded on first run). The folder can be moved to another drive.
- Next to the files: `Maku - Gap analysis.md` per series, a tag inside every converted MKV,
  optional poster and fanart for media servers (off unless turned on), and the English subtitles
  Maku made when asked (`.en.srt`).
- Export, records damaged past use, uninstall: as Kura.

**Tooling** (all latest stable): as Kura's. Python 3.14 (uv), Ruff, Pyright (strict), pytest,
FastAPI, Typer, PyInstaller; Node LTS, pnpm, Vite, React 19, TypeScript 7, Tailwind 4, Vitest,
Biome; Rust stable (edition 2024), Tauri 2 with the single-instance, updater, dialog, opener,
notification and autostart plugins. No Dependabot.

**Delivery**
- GitHub repo `frankgrobbelaar/maku`, public under the MIT licence, with Kura's settings (the
  owner, 2026-10-27: "Same repo rules for Maku as Kura - only forks no contributions"): forking
  on, issues, projects, wiki and discussions off, only collaborators can open pull requests,
  secret scanning with push protection on. The app's identifier is `io.github.frankgrobbelaar.maku`.
- Semantic versions and a changelog; `scripts/release.mjs` and the Release workflow refuse a
  version that isn't newer than the last. A `v*` tag builds the NSIS installer, signs it for the
  updater, publishes a release with its notes, `latest.json` and `THIRD-PARTY-NOTICES.txt`, and
  refreshes the downloads page: https://frankgrobbelaar.github.io/maku/.
- **Every download is listed in the installer** (`engine/src/maku/downloads.json`), as Kura.
- Per-user install (no admin) into `%LOCALAPPDATA%\Programs\Maku`, apart from the data.
- The update-signing key is `%USERPROFILE%\.tauri\maku-updater.key` (no password) and the
  `TAURI_SIGNING_PRIVATE_KEY` repo secret. Lose it and installed copies can't update.
- Not code-signed (Windows SmartScreen warns once on first install).

**The owner's PC**
- GTX 1660 Super 6 GB (Turing NVENC, no AV1 encode), i5-9600K (6 cores), 24 GB RAM. Graphics
  driver 617.42 (fine as it is; never install drivers). No system ffmpeg: Maku fetches its own.
  GitHub CLI signed in as frankgrobbelaar. The owner has no series or films on the PC yet: test
  with made-up files (the owner, 2026-10-27: "Yes you can use made up files if possible").
- Its Windows SDK registry entry points at the wrong folder, so the user variable `RC` names
  rc.exe for Rust builds (see docs/development.md, "Troubleshooting").

## Guides and docs

- **Area guides.** [AGENTS.md](AGENTS.md) is the entry for any coding agent, and each area has its
  own: [engine/AGENTS.md](engine/AGENTS.md), [app/AGENTS.md](app/AGENTS.md) (the UI),
  [app/src-tauri/AGENTS.md](app/src-tauri/AGENTS.md) (the shell) and [docs/AGENTS.md](docs/AGENTS.md).
  Read the guide for an area before changing it.
- **Docs.** [docs/README.md](docs/README.md) is the map: architecture, development, conventions,
  design, releasing, and one page per tool in [docs/stack/](docs/stack/). Read the stack page before
  changing how a tool is used, and update docs in the same commit as the code they describe.
