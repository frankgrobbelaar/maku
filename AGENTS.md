# Maku: guide for coding agents

Maku is a personal, single-user Windows app for one library of TV series and movies: a Tauri
shell, a React UI and a Python engine. It began as its sibling Kura and keeps Kura's layout and
stack. The code is public under the MIT licence; the repo takes no contributions. This file and
the `AGENTS.md` in each area tell any coding agent how to work here.

**Read [CLAUDE.md](CLAUDE.md) first.** It holds the ground rules and every decision made so far,
and it is written for every agent, not only Claude.

## Area guides

Read the guide for the area you are about to change. It says what belongs there, the patterns to
copy, and what "done" means.

| Working in | Guide |
| --- | --- |
| `engine/` (Python: core logic, API, CLI, database) | [engine/AGENTS.md](engine/AGENTS.md) |
| `app/src/` (React UI) | [app/AGENTS.md](app/AGENTS.md) |
| `app/src-tauri/` (Rust shell, installer, updates) | [app/src-tauri/AGENTS.md](app/src-tauri/AGENTS.md) |
| `docs/` | [docs/AGENTS.md](docs/AGENTS.md) |

## The rules that matter most

1. **One branch.** Work on `main`; commit and push once every check passes. No branches, worktrees
   or PRs unless the owner asks. Releases are Claude's call until 1.0.0, the owner's from then on.
2. **Maku's look is fixed.** Build screens to their boards (Kura's, in Maku's words) with the
   tokens in `app/src/styles/tokens.css`: four colour schemes, each light and dark. Never add or
   change a colour, size or font unasked.
3. **Nothing in the library changes without review.** Maku proposes; the owner approves; every
   change is logged and undoable; nothing is deleted outright (quarantine).
4. **Small things are designed.** Every screen has loading, empty and error states, and every
   message names the problem, says what Maku did and offers the next step.
5. **The core stays pure, the shell stays thin.** Library logic is pure Python in
   `engine/src/maku/core`; the Rust shell only handles the window, the engine process and updates.
6. **Contracts change on both sides at once.** The engine API (`engine/openapi.json` ↔
   `app/src/lib/engine.tsx`) and the shell handshake (`engine.rs` ↔ `test_cli.py`).
7. **Test first.** New behaviour and every bug fix start with a failing test.
8. **Latest stable versions** of every package, tool and AI model, wherever possible. Look for a
   newer release whenever you add or touch one, and run the update routine in
   [docs/development.md](docs/development.md) every couple of weeks: it covers the packages, the
   speech models and what Maku downloads (`engine/src/maku/downloads.json`,
   `engine/src/maku/assets/`).
   A model or a downloaded tool moves to its newest release once it measures at least as good,
   and fast enough, on the owner's PC; if it doesn't, the one in use stays and its page in
   `docs/stack/` says why. It never raises what a PC needs to run Maku: a heavier model comes as
   a choice beside the lighter one (as Best beside Fast), and every part says what it needs on
   the PC it runs on. A page in `docs/stack/` for every tool and model.
9. **Docs move with code**, in the same commit. Decisions go in CLAUDE.md.
10. **No personal details.** No email addresses, no employer or company behind Maku, and no
    personal details beyond the owner's name, anywhere: files, test data, commit messages. The
    publisher is "Maku"; commits carry only the owner's GitHub no-reply address, and Claude's
    co-author line has no address.
11. **Only ship what Maku may share.** A new dependency's licence must be on the allowed list in
    `engine/tools/third_party_notices.py`; adapted code keeps its notice; no media in the repo.
    Tests, examples and pictures use made-up titles only (The Harbour Line, Glass Orchard, the
    Starfall films), never a real series or film.
12. **Changelog and versions.** A change the owner would notice adds one plain sentence under
    "Unreleased" in `CHANGELOG.md`, in the same commit. Versions are semantic and only
    `scripts/release.mjs` changes them; every release must be newer than the last, so installed
    copies update. See [docs/releasing.md](docs/releasing.md).

When the owner is scoping ("is it possible…"), answer in the conversation; don't build.

## Checks

Every change passes these before it is committed (each line from the repo root):

```powershell
cd engine; uv run ruff format --check; uv run ruff check; uv run pyright; uv run pytest
cd app; pnpm check; pnpm build
cd app/src-tauri; cargo fmt --check; cargo clippy --all-targets -- -D warnings; cargo test
```

Run the app with `cd app; pnpm tauri dev` and look at what you changed. Setup and troubleshooting
are in [docs/development.md](docs/development.md).

## Done means

- The change works in the running app, and its states (loading, empty, error) are there.
- Tests cover the new behaviour; all checks above are green; CI is green after the push.
- Contracts, docs and CLAUDE.md are updated in the same commit.
- Nothing was left as a known fault: fix what you find, or say clearly why it can't be fixed now.
