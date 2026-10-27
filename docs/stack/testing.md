# Testing (pytest, Vitest, Testing Library, cargo test)

Each part is tested with its own language's standard tool. All of them run in CI on every push,
and all of them run locally with the commands in [../development.md](../development.md).

| Part | Tool | Where | Run |
| --- | --- | --- | --- |
| Engine | [pytest](https://docs.pytest.org) 9 | `engine/tests/` | `cd engine; uv run pytest` |
| UI | [Vitest](https://vitest.dev) 5 + [Testing Library](https://testing-library.com) | next to the code, `*.test.ts(x)` | `cd app; pnpm test` (or `pnpm test:watch`) |
| Shell | `cargo test` | `#[cfg(test)]` modules in the Rust files | `cd app/src-tauri; cargo test` |

## Engine (pytest)

- Settings live in `pyproject.toml` (`[tool.pytest]`, strict mode).
- `conftest.py` gives each test a fresh data folder (`paths`) and a `client` that calls the API
  the way the app does: on `127.0.0.1`, with the token. Use `with TestClient(...)` so start-up
  (migrations) runs.
- The engine's handshake with the shell (`test_cli.py`) starts a real `maku serve` process. Point
  `MAKU_ENGINE_EXE` at a PyInstaller build to run the same test against the bundle.
- `test_openapi.py` compares the API with `engine/openapi.json`. When it fails on purpose, rewrite
  the snapshot (`uv run maku openapi openapi.json`) and update the UI's types.
- For the core: plain functions in, plain values out, with names as releases and rips write
  them, made-up titles only (`The.Harbour.Line.S01E02.1080p.WEB-DL.mkv` → `The Harbour Line
  (2019) - S01E02`). A video in a test is made up too: ffprobe's and ffmpeg's answers come from
  `tests/fake_ffprobe.py` and `tests/fake_ffmpeg.py`, TMDB's from `tests/fake_web.py`.

## UI (Vitest and Testing Library)

- Vitest reuses `vite.config.ts` (the `test` section): jsdom as the browser, `src/test/setup.ts`
  for the jest-dom matchers and cleanup.
- Find things the way a person does: `getByRole("button", { name: "Try again" })`,
  `findByText(...)` for what appears later. Avoid test IDs and implementation details.
- Mock Tauri at the module edge: `vi.mock("@tauri-apps/api/core", ...)` and
  `vi.mock("@tauri-apps/api/event", ...)`; stub `fetch` with `vi.stubGlobal` for engine answers.
  `home-page.test.tsx` shows both.
- Render with a fresh `QueryClient` (retries off) per test.
- `utils.test.ts` reads `tokens.css` to check `cn()` knows every size and radius there; Vitest is
  told to load that one CSS file (`test.css.include`).

## Shell (cargo test)

Test the parts that don't need a window: parsing the engine's ready line, keeping its error lines,
the token. Pass `std::io::Cursor` where the code reads a pipe.

## What to test

- Behaviour a person relies on, and every "small thing" a screen promises (empty, error, recovery).
- Every contract between the parts, from both sides.
- Every bug, with a test that fails before the fix.

Not worth testing: styling, and code that only passes values through.
