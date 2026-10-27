# Development

How to set up a Windows PC for Maku, run it, check it and keep it current.

## Set up once

| Tool | Why | Get it |
| --- | --- | --- |
| Visual Studio Build Tools 2022, "Desktop development with C++" | Rust's linker and the Windows SDK | `winget install Microsoft.VisualStudio.2022.BuildTools` |
| Rust (stable) | The shell | [rustup.rs](https://rustup.rs), then `rustup component add clippy rustfmt` |
| Node.js LTS | The UI's tooling | `winget install OpenJS.NodeJS.LTS` |
| pnpm 12 | UI packages | `npm install -g pnpm@latest` |
| uv | Python and the engine's packages | `winget install astral-sh.uv` (uv installs Python 3.14 itself) |
| GitHub CLI, signed in | Pushing, releases and watching CI | `winget install GitHub.cli`, then `gh auth login` |

Then, from the repo:

```powershell
cd engine; uv sync          # Python 3.14, the engine and its dev tools
cd ../app; pnpm install     # the UI, Tauri's CLI and Biome
```

WebView2, which draws the window, is part of Windows 11.

## Run Maku

```powershell
cd app; pnpm tauri dev
```

This starts Vite (the UI with hot reload), builds and opens the shell, and the shell starts the
engine from source with `uv run`. Engine data goes to `engine/.dev-data`, never to the real
`%LOCALAPPDATA%\Maku`. Rust and Python changes need a restart; UI changes appear as you save.

To work on the engine alone:

```powershell
cd engine
$env:MAKU_TOKEN = "dev"; $env:MAKU_DATA_DIR = ".dev-data"
uv run maku serve --port 8765        # then call http://127.0.0.1:8765/health with "Authorization: Bearer dev"
uv run maku --help                   # every command
```

## Check your work

CI runs exactly these; run them before every push.

```powershell
cd engine; uv run ruff format --check; uv run ruff check; uv run pyright; uv run pytest
cd app; pnpm check; pnpm build
cd app/src-tauri; cargo fmt --check; cargo clippy --all-targets -- -D warnings; cargo test
cd app; pnpm build:engine; pnpm build:notices
```

`pnpm check` runs Biome, the TypeScript compiler and Vitest. The last line builds the engine as
the installer bundles it and checks every bundled part's licence (it needs `pnpm build` first);
CI then also starts the bundled engine once (`tests/test_cli.py` with `MAKU_ENGINE_EXE` set). To fix formatting:
`uv run ruff format` and `uv run ruff check --fix` in `engine/`, `pnpm fix` in `app/`, `cargo fmt` in
`app/src-tauri/`.

## Common changes

**A new API endpoint.** Add a router module in `engine/src/maku/api/` (see `health.py`) and include
it in `api/__init__.py`. Test it in `engine/tests/`. Run `uv run maku openapi openapi.json`, then add
the matching type and hook to `app/src/lib/engine.tsx`. Commit both sides together.

**A schema change.** Append a migration to `engine/src/maku/migrations.py`; never edit one that has
shipped. Add a test, and include the new data in `export.py`.

**A new screen.** Build it in `app/src/features/<area>/` to its board (Kura's boards, in Maku's
words; see [design.md](design.md)), using Maku's tokens and existing components. Add the route in
`app/src/app.tsx`. Give it its empty, loading and error states, and look at it in each scheme,
light and dark.

**A new tool or library.** Use its latest stable version and add a page (or a section) in
[stack/](stack/) saying how Maku uses it.

## Updating dependencies

Maku stays on the latest versions of everything it uses, packages and speech models alike,
wherever possible, as Kura does. There is no Dependabot (it would open branches), so update on
`main`, ideally every couple of weeks, and look for a newer release whenever you add or touch
something:

```powershell
uv self update; cd engine; uv lock --upgrade; uv sync    # Python packages
cd ../app; pnpm update --latest                          # npm packages
cd src-tauri; rustup update; cargo update                # Rust and crates
```

Raise the minimum versions in `pyproject.toml`, `package.json` and `Cargo.toml` to match, run every
check, skim the changelogs of anything that jumped a major version, and update the versions table in
[docs/README.md](README.md). Pinned GitHub Actions are updated the same way: look up each action's
latest release and change the SHA and the version comment. pnpm refuses packages younger than a day
(a supply-chain safeguard); if the newest release is that fresh, take the one before it.

### Speech models and downloads

The speech models and the programs Maku downloads are pinned (a release or commit, a size and a
SHA-256), so a file never changes under Maku, and so they never update by themselves. At each
update, look for the newest release of each:

| What | Pinned in | Where releases come from |
| --- | --- | --- |
| ffmpeg (an LGPL build) | `engine/src/maku/downloads.json` | the source it names (BtbN's FFmpeg-Builds) |
| Whisper medium and small (ONNX, half precision) | `engine/src/maku/downloads.json` | onnx-community's exports on Hugging Face; OpenAI's Whisper |
| pyannote's segmentation model | `engine/src/maku/assets/` | pyannote, and onnx-community's export, on Hugging Face |

WebView2 is Microsoft's and keeps itself current. A newer model or build is measured before it's
taken: its speed on the owner's PC (the measured speeds are in `engine/src/maku/core/estimate.py`)
and its quality the way its stack page measured it (for speech, against the lines a release's own
English subtitles have). Take it when it's at least as good and fits the time the owner accepted;
then update its pin (version, addresses, sizes, SHA-256), the speeds, its licence in the notices
(`engine/tools/third_party_notices.py`), its page in [stack/](stack/), the versions table in
[README.md](README.md), "The AI inside" in the [project's README](../README.md), and the changelog.
When the newest doesn't fit (a bigger Whisper is too slow on a 6 GB card, say), the one in use
stays, and its stack page says what was tried and why, so the next update doesn't measure it again
for nothing.

Other people's PCs count too: a newer model never raises what a PC needs (README.md's "What your
PC needs"). One that wants more memory or a stronger card than the one it replaces comes as a
choice beside the lighter one, as Best beside Fast, and Maku's check of the PC (Setup's last step,
Settings › About) is told what the new one needs: the memory each quality wants is in
`engine/src/maku/core/hardware.py` ([stack/hardware.md](stack/hardware.md)).

## Troubleshooting

**"Are you sure you have RC.EXE in your $PATH" when building the shell.** Rust finds the Windows
SDK's resource compiler through the registry, and on some PCs that entry points at the wrong
folder. Set the user variable `RC` to rc.exe, then open a new terminal:

```powershell
[Environment]::SetEnvironmentVariable('RC', 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\rc.exe', 'User')
```

**The window says "Maku's engine isn't running".** "Copy details" (when shown) has the engine's last error lines.
In development, run `uv sync` in `engine/`; the engine's own log is `engine/.dev-data/logs/engine.log`.

**Port 1420 is busy.** A previous `pnpm tauri dev` left Vite running; close it or end the `node`
process using that port.
