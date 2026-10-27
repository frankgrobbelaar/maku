# Tauri (the shell)

[Tauri 2](https://v2.tauri.app) turns the web UI into a Windows app: a native window drawn by
WebView2, a small Rust program around it, and the installer and updater. Maku uses Tauri 2.12 with
Rust stable (edition 2024).

## Files

| File | What it holds |
| --- | --- |
| `app/src-tauri/src/main.rs` | The app: plugins, state, commands, start and exit |
| `app/src-tauri/src/engine.rs` | Starting, watching and stopping the engine |
| `app/src-tauri/src/updater.rs` | Updates from the GitHub releases |
| `app/src-tauri/src/tray.rs` | The tray icon, starting with Windows, and notifications |
| `app/src-tauri/src/look.rs` | Making the window in the look chosen: light or dark, and the colour scheme |
| `app/src-tauri/src/links.rs` | The pages the window may open in the browser |
| `app/src-tauri/src/process.rs` | Running console programs without a console window |
| `app/src-tauri/tauri.conf.json` | Name, version source, window, security policy, bundle, updater address and key |
| `app/src-tauri/tauri.bundle.conf.json` | Extra settings for building the installer (see below) |
| `app/src-tauri/capabilities/default.json` | What the window may ask of the shell |
| `app/src-tauri/windows/hooks.nsh` | Maku's additions to the installer |
| `app/src-tauri/icons/` | App icons, generated from `maku.svg` (the mark: a stage curtain drawn back) |

## The window

One window, `main`, 1280 × 832 (at least 720 × 560), with `decorations: false`: Maku draws its own
title bar (`app/src/components/shell/title-bar.tsx`) as the design shows. Elements marked
`data-tauri-drag-region` move the window and maximise it on double-click; the buttons call
`getCurrentWindow().minimize()`, `.toggleMaximize()` and `.close()`. Windows' snap layouts menu
doesn't appear when hovering our maximise button; Win+Z and dragging to the screen's edges still
work.

Light or dark, and the colour scheme (`look.rs`): the shell makes the window itself at start
(`"create": false` in the config, then `WebviewWindowBuilder::from_config`), giving it the look the
owner chose in Settings > General: no theme of its own to follow Windows, or always light or always
dark. WebView2 takes the window's theme as the page's `prefers-color-scheme`, so the page is light
or dark from its first frame, and its colours change with it (`light-dark()` in `tokens.css`). The
scheme (Velvet, Lagoon, Dusk or Graphite) reaches the page before anything else runs, as an
initialization script setting `window.__MAKU_SCHEME__`, which `main.tsx` puts on `<html>` as
`data-scheme`. The window's own colour under the page, seen before it draws, is the scheme's
window colour in the theme (`Scheme::windows`), following a change of theme (`ThemeChanged`) or of
scheme. The UI reads and sets them with the `look`, `set_look`, `scheme` and `set_scheme` commands
(`app/src/lib/look.ts`).

## Commands and events

The UI calls the shell through these commands and listens to two events:

| Name | Kind | Does |
| --- | --- | --- |
| `engine_status` | command | The engine's status now: `starting`, `ready` (with address and token) or `failed` |
| `restart_engine` | command | Start again after a failure |
| `prepare_update` | command | Check for an update and download it; returns its version or nothing |
| `install_update` | command | Stop the engine, run the installer, let it reopen Maku |
| `open_downloads_page`, `open_tmdb_api_page`, `open_tmdb_page` | command | Open the downloads page, TMDB's page of API keys, or a show's or film's page on TMDB (by kind and number), in the browser |
| `pick_folder`, `pick_export` | command | Windows' folder picker, or its file picker for an export; nothing when cancelled |
| `open_folder`, `show_in_folder` | command | Open a folder in Explorer, or show a file there, selected |
| `start_with_windows`, `set_start_with_windows` | command | Whether Maku starts with Windows, in the tray |
| `keep_in_tray`, `set_keep_in_tray` | command | Whether closing the window keeps Maku running in the tray |
| `look`, `set_look` | command | Light or dark: `windows` (as Windows is), `light` or `dark` |
| `scheme`, `set_scheme` | command | The colour scheme: `velvet` (the default), `lagoon`, `dusk` or `graphite` |
| `engine-status` | event | Sent whenever the engine's status changes |
| `notice` | event | What the engine tells of, while the window is open |

A new command is a `#[tauri::command]` function, listed in `generate_handler!` in `main.rs`, with
its types mirrored in `app/src/lib/`. Commands return `Result<T, String>`; the string is shown to
the person, so write it as a sentence.

## Security

- **Capabilities** (`capabilities/default.json`): the window gets `core:default` plus the title bar
  permissions (minimise, maximise, close, dragging). Add a permission only for a feature that needs
  it, and say why in the description.
- **Content security policy** (`app.security.csp`): scripts and styles from the app only,
  connections to the app, Tauri's IPC and the engine on `http://127.0.0.1:*`, and images and
  video from the engine too (its posters and stills, and the player's stream).
- The installed window's origin is `http://tauri.localhost`; in development it is
  `http://localhost:1420`. The engine allows exactly these two (see [fastapi.md](fastapi.md)).

## Plugins

- **single-instance**: opening Maku again focuses the open window, because two copies would share
  one database.
- **updater**: downloads and verifies updates. Configured under `plugins.updater`: the address of
  the newest release's `latest.json`, the public key, and passive install mode. Maku drives it
  from Rust (`updater.rs`), so the window needs no updater permission and the downloaded
  installer waits in the shell until "Restart and update". See [../releasing.md](../releasing.md).
- **dialog**: Windows' folder picker, for "Add a folder". Maku opens it from Rust too
  (`dialogs.rs`, `pick_folder`), so the window needs no dialog permission.
- **opener**: opens web pages in the default browser. Maku drives it from Rust too (`links.rs`):
  the window asks for a page by name (`open_downloads_page`), or for a title's page on TMDB by its
  kind and number (`open_tmdb_page`, which makes the address itself), so it needs no opener
  permission and can't be steered to any other address.
- **The tray** (Tauri's `tray-icon` feature, `tray.rs`): an icon in the notification area while
  Maku runs, with Open Maku and Quit Maku; a click opens the window.
- **autostart**: "Start with Windows" in Settings > General, which Windows keeps in its own list
  of startup apps (the shell asks it, so the switch is always true to it). Windows starts Maku
  with `--in-tray`: the window stays hidden (it's created hidden and shown at start otherwise).
  Don't turn it on from a development build: Windows would start that build at sign-in.
- **Closing the window** quits Maku, unless "Keep Maku running when you close the window" is on
  (Settings > General, `keep_in_tray` in `tray.rs`): then it hides the window and Maku carries on
  in the tray. The shell keeps that choice, light or dark and the scheme, in `window.json` in its
  own folder (`choices.rs`; `%LOCALAPPDATA%\io.github.frankgrobbelaar.maku`, which uninstalling
  removes with "Delete the application data"). Until the owner chooses, it's whatever "Start with
  Windows" is.
- **notification**: Windows notifications for what the engine tells of on its stdout after the
  ready line (`{"event":"notify",...}`: a finished batch, a queue that paused itself), and for an
  engine that can't run (it's then tried again by itself), shown only while the window is away
  (in the tray or minimized); a click on one opens the window. While the window is open, the
  engine's notifications go to it instead, as the `notice` event. All from Rust, so the window
  needs no permission for either.

## The engine process

In development the shell runs `uv run --project engine maku serve --watch-stdin` and points
`MAKU_DATA_DIR` at `engine/.dev-data`. Installed, it runs `engine\maku-engine.exe` from the
resource folder. Either way it hides the console window, reads the ready line (waiting on while
the engine says it's still working, giving up on one silent for a minute), keeps the last 40
error lines for the failure screen, notices if the engine stops on its own, and closes its
stdin on exit. See
[../architecture.md](../architecture.md#start-run-stop).

## Installer

`bundle.targets` is `nsis`: one `Maku_<version>_x64-setup.exe`, installed per user without admin
rights (`installMode: currentUser`). Publisher: Maku. WebView2 is downloaded by the installer if a
PC lacks it (Windows 11 always has it).

`tauri.bundle.conf.json` is merged in only by `pnpm build:installer`. It builds the engine, the UI
and the third-party notices first; adds `engine/dist/maku-engine/` as the `engine/` resource
folder, with `LICENSE.txt` and `THIRD-PARTY-NOTICES.txt` beside Maku; and turns on
`createUpdaterArtifacts` (the `.sig` file). Keeping these out of the main config means
`pnpm tauri dev` and `cargo clippy` work without a PyInstaller build or the signing key.

`windows/hooks.nsh` is included by Tauri's NSIS template:

- `MakuUseProgramsFolder` (run as the installer's window opens) changes the default folder from
  `%LOCALAPPDATA%\Maku`, which is the data folder, to `%LOCALAPPDATA%\Programs\Maku`.
- `NSIS_HOOK_PREUNINSTALL` offers the export and stops if it fails.
- `NSIS_HOOK_POSTUNINSTALL` deletes the data folder only if "Delete the application data" was ticked.
  Data moved to another drive (its home's `location.txt` names it, in UTF-16, read with
  `FileReadUTF16LE`) goes too, but only Maku's own
  parts of it (`maku.db`, `artwork`, `backups`, `cache`, `logs`, `tools`…), and only when it holds
  `maku.db`; its folder goes only if nothing else is left in it.
- `NSIS_HOOK_PREINSTALL` and `NSIS_HOOK_POSTINSTALL` replace the engine whole. NSIS copies a new
  version's files over the old ones and leaves the ones it doesn't have, so Python found both
  versions of whatever changed (updated to 0.2.0, the engine still said 0.1.0, from the old
  version's `maku-0.1.0.dist-info` beside the new one's). Before copying, the old `engine` folder
  becomes `engine-old`; after, `engine-old` goes, with a few tries while an engine that's only
  just stopped lets go of its files. `.onInstFailed` puts it back if the install stops between.
  Windows lets a running program's folder be renamed, so a running engine is set aside too; the
  files it holds stay in `engine-old` until the next install or the uninstall.

Hooks can use the template's variables (`$UpdateMode`, `$PassiveMode`, `$DeleteAppDataCheckboxState`).
After a Tauri upgrade, build an installer and test an install, an update and an uninstall. The
pre-install hook runs before the template checks whether Maku is open, and nothing runs between
that check and the copying. `windows/hooks-test.ps1` checks the engine's replacement on a scratch
folder in `target/` (an update, a first install, a stopped install, a running engine), with the
NSIS that `pnpm build:installer` downloads: run it after changing `hooks.nsh` or upgrading Tauri.

## Commands you'll use

```powershell
cd app
pnpm tauri dev                      # run Maku
pnpm tauri icon src-tauri/icons/maku.svg   # regenerate icons (then delete the non-Windows ones)
pnpm build:installer                # build the installer (needs the signing key)
cd src-tauri; cargo clippy --all-targets -- -D warnings; cargo test
```

## Upgrading

Keep `@tauri-apps/cli` and `@tauri-apps/api` (npm) and `tauri`, `tauri-build` and the plugins
(Cargo) on the same minor version. Read the [release notes](https://v2.tauri.app/release/) for
config changes, rebuild the installer, and test install, update and uninstall.
