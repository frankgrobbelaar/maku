# Conventions

How Maku's code is written. The aim is code a newcomer can read top to bottom and trust.

## Everywhere

- **Small, obvious pieces.** One job per module, function or component. Names say what a thing is
  or does (`export_data`, `useHealth`, `NavRail`), not how. No abbreviations a reader has to decode.
- **Comments explain why**, not what. Every module starts with one or two lines on its job. Skip
  comments the code already says.
- **No speculative code.** No unused options, placeholder abstractions or "for later" parameters.
  Add the second implementation when it exists.
- **Errors are for people.** A message names the problem, says what Maku already did, and offers
  the next step: "The export didn't work, so Maku was not removed." Never swallow an error silently;
  log it, show it, or both.
- **Plain language** in UI text, logs, docs and commit messages. British or American spelling is
  fine; be consistent within a file.
- **Latest stable versions** of tools and libraries (see [development.md](development.md)).
- **Secrets never touch the repo.** The signing key lives in `%USERPROFILE%\.tauri` and GitHub
  secrets; the engine's token exists only in memory for one launch.

## Python (the engine)

- Python 3.14, run through `uv`. Type hints everywhere; Pyright runs in strict mode, so the types
  are real. Ruff formats (100 columns) and lints.
- Keep `maku/core` pure: functions that take values and return values. No `open()`, `sqlite3`,
  `httpx` or `subprocess` in there; the caller does the I/O and passes plain data in.
- Prefer frozen `dataclass`es for internal data, Pydantic models (`ApiModel`) only at the API edge.
- Paths are `pathlib.Path`. Text files are written as UTF-8 with `\n` line endings.
- Raise specific exceptions (`NewerDatabaseError`) with a message a person can act on; the CLI
  and API turn them into exit codes and status codes.
- One `APIRouter` module per feature in `maku/api/`; share dependencies through `api/common.py`.
- Log with the standard `logging` module (`logging.getLogger(__name__)`); the engine writes
  `logs/engine.log`. Nothing but the events in `maku/events.py` (the ready line, "working"
  while a long job keeps it starting, notifications) goes to stdout while serving.

## TypeScript and React (the UI)

- TypeScript in strict mode, including `noUncheckedIndexedAccess`. No `any`; at the edges, cast
  once and say why.
- Function components and hooks only. A component file exports one main component; small helpers
  it alone uses live below it.
- Folders: `components/` for shared pieces (`ui/` holds the primitives, `shell/` the window frame),
  `features/<area>/` for screens and their parts, `lib/` for non-visual code.
- **Server data goes through TanStack Query** (`useEngineQuery` in `lib/engine.tsx`): it handles
  loading, errors, caching and refetching. Local UI state stays in `useState`. Add a global store
  only when two distant screens truly share client state.
- Every screen designs its **loading, empty and error** states, following the "small things" board.
- Style with Tailwind classes built from Maku's tokens (see [design.md](design.md)), never a
  scheme's colour by value: the classes follow the scheme chosen. Inline `style` only for values
  computed at runtime (a progress width, say).
- Accessibility is part of done: real `<button>` and `<a>`, labels on icon-only buttons, visible
  focus, keyboard paths, `role="alert"` or `role="status"` for messages that appear.
- Imports use the `@/` alias for anything outside the current folder.

## Rust (the shell)

- Keep the shell thin: the window, the engine process, updates. Anything else belongs in the engine.
- Commands return `Result<T, String>` with a sentence the UI can show.
- `cargo fmt` and `cargo clippy -D warnings` are clean; edition 2024.
- Start other programs with `process::hidden()` so no console window flashes.

## Tests

- **Test first** for behaviour: write the failing test, make it pass, tidy up. Fix bugs by first
  writing the test that shows them.
- Test names are sentences about behaviour: `test_a_failing_migration_changes_nothing`,
  `it("never lets a late answer overwrite a newer event")`.
- The engine: pytest, with a fresh data folder per test (`paths` fixture). Pure core functions get
  plain unit tests with names as releases and rips write them, made-up titles only
  (`The.Harbour.Line.S02E03.1080p.WEB-DL.mkv`, `Starfall (2008)`), and the clean names Maku files
  them under.
- The UI: Vitest and Testing Library. Test what the person sees and does (roles, text, clicks),
  not implementation details. Mock the Tauri APIs at the module edge.
- The shell: `cargo test` for the parts that don't need a window (the handshake parsing).
- Contracts between the parts have a test on each side (see [architecture.md](architecture.md)).
- See [stack/testing.md](stack/testing.md) for the tools.

## Git

- One branch: `main`. Commit small, working steps; every commit passes the checks.
- Commit messages: a short summary in the imperative ("Add the export command"), then why, if it
  isn't obvious. No email addresses anywhere: commits carry only the owner's GitHub no-reply
  address, and Claude's co-author line has none (`Co-Authored-By: Claude Opus 5.5`).
- Never commit generated output (`dist/`, `target/`, `.venv/`) or anything secret. Generated files
  that are part of a contract (`engine/openapi.json`, `docs/design/`) are committed on purpose.
- Docs change in the same commit as the code they describe, and a change the owner would notice
  adds a line under "Unreleased" in `CHANGELOG.md` (see [releasing.md](releasing.md)).
