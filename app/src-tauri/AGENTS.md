# Shell: guide for coding agents

The shell is Maku's Rust side (Tauri 2): the window, the engine process, single-instance,
updates, and the installer. It is thin on purpose. Anything that isn't about the window, the
process or updating belongs in the engine. Start with [../../AGENTS.md](../../AGENTS.md) and
[../../CLAUDE.md](../../CLAUDE.md).

## Where things go

| What | Where |
| --- | --- |
| App setup: plugins, state, commands, exit | `src/main.rs` |
| Starting, watching and stopping the engine | `src/engine.rs` |
| Updates from the GitHub releases | `src/updater.rs` |
| The tray icon, starting with Windows, notifications | `src/tray.rs` |
| Making the window in the look chosen: light or dark, and the colour scheme | `src/look.rs` |
| The shell's own choices (`window.json`) | `src/choices.rs` |
| Pages opened in the browser (the downloads page, TMDB's API page, a title's page on TMDB) | `src/links.rs` |
| Windows' dialogs (the folder picker) | `src/dialogs.rs` |
| Showing a folder or file in Explorer | `src/explorer.rs` |
| Running console programs without a window | `src/process.rs` |
| Window, security policy, bundle, updater key | `tauri.conf.json` (installer-only extras: `tauri.bundle.conf.json`) |
| What the window may call | `capabilities/default.json` |
| Installer additions | `windows/hooks.nsh` |

## Rules

- **A new command** is a `#[tauri::command]` returning `Result<T, String>` (the string is a sentence
  for the person), registered in `generate_handler!`, with its types mirrored in `app/src/lib/`.
  Unit-test the parts that don't need a window.
- **Least privilege.** Add a permission to `capabilities/default.json` only for a feature that needs
  it. Loosen the content security policy only with a reason in the commit.
- **Never block the main thread.** Waiting and process work go on their own threads or async tasks.
- **Start programs with `process::hidden()`** so no console window flashes.
- **The engine handshake is a contract**: the ready line, `MAKU_TOKEN`, stdin closing. Change
  `engine.rs` and `engine/tests/test_cli.py` together.
- **The look is the shell's to keep.** Light or dark and the colour scheme (`Look`, `Scheme` in
  `look.rs`) mirror `app/src/lib/look.ts`, and each scheme's window colours (`Scheme::windows`)
  match its `--scheme-window` in `app/src/styles/tokens.css`: change them together. The page is
  told the scheme before its first frame (`window.__MAKU_SCHEME__`), so it never shows another
  first.
- **No secrets in the binary.** Updates need no login (the releases are public); the signing key
  never leaves `%USERPROFILE%\.tauri` and the GitHub secret; only the public key is in the config.
- **Installer changes** (`hooks.nsh`, bundle settings): build an installer, then test a fresh
  install, an update over it, and an uninstall, keeping the owner's real data folder out of it
  (launch the test install with `MAKU_DATA_DIR` set).
- Keep the Rust crates (`tauri`, `tauri-build`, plugins) and the npm packages (`@tauri-apps/*`) on
  the same minor version.

## Commands

```powershell
cargo fmt; cargo clippy --all-targets -- -D warnings; cargo test
cd ..; pnpm tauri dev           # run Maku
cd ..; pnpm build:installer     # build the installer (signing key in the environment)
```

## Done means

`cargo fmt --check`, Clippy (no warnings) and `cargo test` are green; the app runs; for installer or
updater changes, install, update and uninstall were tried. Guides:
[tauri.md](../../docs/stack/tauri.md), [releasing.md](../../docs/releasing.md).
