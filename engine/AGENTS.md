# Engine: guide for coding agents

The engine is everything Maku does except draw the window: scanning, identifying, planning,
converting, reports, export, the database, and the local API the UI calls. Python 3.14, run with uv.
Start with [../AGENTS.md](../AGENTS.md) and [../CLAUDE.md](../CLAUDE.md).

## Where things go

| What | Where |
| --- | --- |
| Library rules: parsing names, matching titles, plans, checks, estimates | `src/maku/core/`, pure functions only |
| Reaching the world: files, ffprobe and ffmpeg, TMDB | modules beside `core/`, one per outside thing, each small and replaceable |
| The API the UI calls | `src/maku/api/<feature>.py`, one `APIRouter` per feature, included in `api/__init__.py` |
| Shared API pieces | `src/maku/api/common.py` (`ApiModel`, `Paths`, `Database`) |
| The schema | `src/maku/migrations.py`, append-only |
| Commands | `src/maku/cli.py` |
| Build tools that run on the engine's Python (the third-party notices) | `tools/`, tested in `tests/` |
| Tests | `tests/test_<module>.py`, and `tests/core/test_<module>.py` for the core; fixtures in `tests/conftest.py` |

## Building a feature

1. **Core first, test first.** Write the pure function with tests built from names as releases
   and rips write them, with made-up titles (`The.Harbour.Line.S02E03.1080p.WEB-DL.mkv`,
   `Starfall (2008)\Starfall (2008).mkv`), the clean names Maku files them under, and TMDB's
   episode counts.
2. **Wrap it in I/O.** Read what the core needs, call it, store the result. Keep that code thin.
3. **Expose it.** An `ApiModel` response and a route; test through the `client` fixture.
4. **Update the contract.** `uv run maku openapi openapi.json`, then mirror the types in
   `app/src/lib/engine.tsx`, in the same commit.
5. **Schema change?** Append a migration (never edit a shipped one), test it, and add the new data
   to `export.py`.

## Rules

- `core/` imports nothing that does I/O: no `sqlite3`, `subprocess`, `httpx`, file reads or writes,
  and nothing from `api/`. It takes values and returns values.
- Files in the library change only by applying a plan the owner approved. Every applied change is
  journaled so it can be undone; replaced and duplicate files go to quarantine, never deleted.
- Never print to stdout while serving: the shell reads the one ready line. Log with `logging`.
- Pyright strict passes without ignores. Data inside the engine is frozen dataclasses; Pydantic
  models live only at the API edge.
- Errors carry a sentence a person can act on, and say what Maku already did.
- Long jobs (scans, conversions) report their stage, percentage and time left, can pause, and pick
  up where they stopped after a restart or a crash.
- Maku runs on other people's PCs too: work on the graphics card uses what this PC has, never one
  card by name (the encoder the PC check found, `hardware.speeds(conn)` and `hardware.hearing(conn)`
  for times), and a new kind of job measures its own speed as it finishes (see
  [docs/stack/hardware.md](../docs/stack/hardware.md)).
- Every new package must survive PyInstaller: after adding one, build the engine and run the
  handshake test against the bundle (see [docs/stack/pyinstaller.md](../docs/stack/pyinstaller.md)).
- Add a dependency only for a clear need, at its latest stable version (`uv add`), with a licence
  on the allowed list in `tools/third_party_notices.py`, and give it a page or a section in
  `docs/stack/`. An AI model, too, starts at its newest release that runs well enough on the
  owner's PC, and moves up as newer ones measure as well (see "Updating dependencies" in
  [docs/development.md](../docs/development.md)).

## Commands

```powershell
uv sync                                   # set up or update the environment
uv run pytest                             # tests (add -k <words> to pick some)
uv run ruff format; uv run ruff check --fix; uv run pyright
uv run maku serve --port 8765             # run alone (set MAKU_TOKEN and MAKU_DATA_DIR first)
uv run pyinstaller maku-engine.spec --noconfirm   # build the bundled engine
```

## Done means

Ruff, Pyright and pytest are green; new behaviour has tests; `openapi.json` and the UI's types
match; the export includes any new data; docs are updated. Guides:
[python.md](../docs/stack/python.md), [fastapi.md](../docs/stack/fastapi.md),
[sqlite.md](../docs/stack/sqlite.md), [testing.md](../docs/stack/testing.md).
