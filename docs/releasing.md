# Releasing

How a change becomes an installed, self-updating Maku.

## The short version

On GitHub, when `main` is ready: **Actions › Release › Run workflow**, keep "Use workflow from" on
`main`, pick **patch**, **minor** or **major** (or type an exact version), and run it. Maku starts
at `0.0.0`, so **minor** makes the first release `0.1.0`; from there, patch, minor or major picks
the next.

Who releases: Claude, up to and including 1.0.0, once a version is reviewed and tested (the owner
handed Maku's releases over on 2026-10-27: "You are in control of the releases"); from 1.0.0 on,
it's the owner's call, as for Kura. A release reaches every installed copy, so none goes out with
a failing check.

The workflow checks that `main` passed CI, then does what
[scripts/release.mjs](../scripts/release.mjs) does on a PC: moves what's under "Unreleased" in [CHANGELOG.md](../CHANGELOG.md) under the new
version, sets the version everywhere, commits "Release 0.3.0" and tags it. It builds and checks the
installer, and only then pushes the commit and the tag to `main` together and publishes. About
fifteen minutes after starting it, the release is on GitHub and on the
[downloads page](https://frankgrobbelaar.github.io/maku/), and every installed Maku offers
"Maku 0.3.0 is ready", with what changed, within a day. Pull `main` before working on a PC again:
the release commit is on GitHub.

The same from a PC, which publishes when the tag is pushed:

```powershell
node scripts/release.mjs minor          # or patch, major, or an exact version such as 0.3.0
git push --atomic origin main v0.3.0    # this publishes it
```

`--atomic` sends the commit and the tag together or not at all, so a tag never goes out for a
commit that isn't on `main`.

## Versions

Maku follows [semantic versioning](https://semver.org): `major.minor.patch`, nothing more.

- **patch** (0.3.0 to 0.3.1): fixes only.
- **minor** (0.3.1 to 0.4.0): new features, with or without fixes.
- **major** (0.4.0 to 1.0.0): a change the owner has to act on, such as data an older Maku can't
  read. 1.0.0 is the first version meant for everyday use.

Every release must be newer than the last, or installed copies wouldn't see it as an update.
`release.mjs` won't step back or repeat a version, and the release workflow refuses a tag that
isn't newer than every version already out. Maku has one version, written in two places that must
agree: `app/package.json` (the shell and UI; Tauri reads it) and `engine/pyproject.toml`.
`release.mjs` changes both and refreshes `engine/uv.lock` and `engine/openapi.json`, which carry it
too; the release workflow refuses a tag that doesn't match them.

## The changelog

[CHANGELOG.md](../CHANGELOG.md) records every change the owner would notice, in the same commit as
the change: one plain sentence under "## Unreleased" and one of `### Added`, `### Changed`,
`### Fixed` or `### Removed`, about what Maku does now rather than how the code changed. Internal
work (refactoring, tests, docs) stays out. A release moves the entries under
`## 0.3.0 - 2026-10-20`, and `release.mjs` refuses to release when nothing is listed.

From there the notes travel:

- to the GitHub release: the version's entries, then every commit since the last release, then a
  link comparing the two ([scripts/release-notes.mjs](../scripts/release-notes.mjs) writes them);
- to `latest.json`, so the update card shows them under "What's new";
- to the downloads page, every version's notes, newest first.

The rules live in [scripts/versioning.mjs](../scripts/versioning.mjs), tested with
`node --test "scripts/*.test.mjs"` (CI runs it).

## What the release workflow does

Started on `main` from the site, it first checks that CI passed on `main`'s latest commit and makes
the release commit and tag with `release.mjs` (as whoever started it, with their GitHub no-reply
address). Then, for that tag or for one pushed from a PC:

1. Checks that the tag, `package.json` and `pyproject.toml` agree.
2. Writes the notes from CHANGELOG.md, and stops if the version has none, or if a newer version is
   already out.
3. Builds the engine with PyInstaller, the UI with Vite, and the shell with Cargo, and checks the
   bundled engine starts and answers.
4. Bundles them into `Maku_<version>_x64-setup.exe` (NSIS) and signs it for the updater, which
   writes `Maku_<version>_x64-setup.exe.sig`.
5. Started from the site, pushes the release commit and tag to `main` together (`--atomic`):
   if `main` moved on during the run, nothing is pushed or published, and running it again
   releases the newer `main`. Then it starts CI on the release commit, which a push made with
   the workflow's own token doesn't start by itself.
6. Creates a **draft** release with the installer, its signature, `THIRD-PARTY-NOTICES.txt` and the
   notes, writes `latest.json` (the update manifest: version, notes, date, signature, and the
   installer's download address), uploads it, then publishes the release as the latest. Installed
   copies only ever see a complete release.
7. Reads `releases/latest/download/latest.json`, the address every installed Maku checks, and fails
   unless it names the new version, so a release can't silently miss installed copies.
8. Starts the downloads page workflow, which republishes the page with the new version.

Ticking **Dry run** does all of it except pushing and publishing: the installer, the notices and
the notes it would have published are kept as a downloadable workflow artifact. If a release stops
after its tag reached GitHub (publishing failed, say), run the workflow from that tag instead of
`main` ("Use workflow from"): it publishes the tag as it is.

## How updates reach a PC

The releases are public, so updates need no login.

1. At start, once a day, and on Settings › Updates' "Check for a new version", Tauri's updater
   reads `https://github.com/frankgrobbelaar/maku/releases/latest/download/latest.json`
   (`plugins.updater.endpoints` in `tauri.conf.json`): the manifest of the newest published
   release. Until the first release exists GitHub answers 404, which Maku takes as up to date.
2. If the version is newer, it downloads the installer in the background and checks its signature
   against the public key built into Maku.
3. The UI shows "Maku 0.2.0 is ready" with what's new from the notes, and a button for every
   version on the downloads page. "Restart and update" stops the engine, runs the installer in
   passive mode (a progress bar, no questions), and the installer opens Maku again.

If a check fails (no internet, say), Settings › Updates and About say so ("Can't check right
now: …") and Maku tries again the next day, or when asked. Settings › Updates also says when it
last checked, and installs a version it found though its card was put off with Later. The code is
[app/src-tauri/src/updater.rs](../app/src-tauri/src/updater.rs).

## Installing for the first time

Download `Maku_<version>_x64-setup.exe` from the
[downloads page](https://frankgrobbelaar.github.io/maku/) (or the
[releases page](https://github.com/frankgrobbelaar/maku/releases)) and run it. Maku isn't
code-signed, so Windows SmartScreen warns once: choose More info › Run anyway. (Updates don't warn:
the updater downloads them, not a browser.) Maku installs for this user only, without admin rights,
into `%LOCALAPPDATA%\Programs\Maku`; its data stays apart in `%LOCALAPPDATA%\Maku`.

## The downloads page

[frankgrobbelaar.github.io/maku](https://frankgrobbelaar.github.io/maku/), the repo's website, lists
every released version, newest first: the latest with its download button, size, SHA-256 and what's
new, and every earlier one below with its installer and notes. Drafts never appear.
[scripts/downloads-page.mjs](../scripts/downloads-page.mjs) builds it from the GitHub releases, and
[downloads.yml](../.github/workflows/downloads.yml) publishes it on GitHub Pages: after every
release, when the page's code changes, and by hand (Actions › Downloads page › Run workflow, for
example after editing a release's notes on GitHub). In Maku, the update card's "Every version"
and Settings' "Every version" and "Every version and what changed" open it in the browser
(`app/src-tauri/src/links.rs`).

To preview it locally from the current releases:

```powershell
gh api repos/frankgrobbelaar/maku/releases > releases.json
node scripts/downloads-page.mjs site --releases releases.json   # then open site\index.html
```

## Third-party notices

Maku is MIT-licensed and ships other people's open-source software, whose licences ask for their
notices to travel with it, and a few of Microsoft's libraries. `pnpm build:installer` runs
`pnpm build:notices` ([engine/tools/third_party_notices.py](../engine/tools/third_party_notices.py))
after building the engine and the UI. It writes `app/src-tauri/target/THIRD-PARTY-NOTICES.txt` from
what was actually bundled:

- the engine: every file in PyInstaller's records (`engine/build/maku-engine/*.toc`), traced to its
  Python package (with the package's own third-party notices, such as ONNX Runtime's), Python's
  own licence, and Microsoft's C++ runtime, taken from Windows (see
  [stack/pyinstaller.md](stack/pyinstaller.md));
- the shell: the crates Cargo links into `maku.exe` for Windows (normal dependencies only), and
  Rust's standard library;
- the UI: Vite's licence report (`app/dist/.vite/licenses.json`), Tailwind's styles, the fonts, and
  the shadcn/ui notice;
- the installer: NSIS and Tauri's NSIS plugin.

The installer puts it next to Maku with `LICENSE.txt`, and the release workflow attaches it to the
release. If a part's licence isn't on the allowed list (permissive licences, MPL-2.0,
PyInstaller's bootloader exception, and Microsoft's terms for the files it lets programs carry:
its C++ runtime, and DirectML inside ONNX Runtime), the build stops and names it: read the licence,
then add it to `ALLOWED`, or the package to `PYTHON_LICENCES` when its metadata has no SPDX
expression. A file that comes from neither a package, Python nor Maku stops it too. CI's Bundle
job runs the same check on every push, so a release doesn't meet it first.

## The installer

Its first page, before anything is installed, is `BEFORE-YOU-INSTALL.txt`: everything Maku
downloads to the PC (each entry of
[engine/src/maku/downloads.json](../engine/src/maku/downloads.json) with what it's for, its size,
licence, address and SHA-256), then Maku's licence. `pnpm build:installer-notes`
([scripts/installer-notes.mjs](../scripts/installer-notes.mjs)) writes it during
`build:installer`, and NSIS shows it as its licence page (`bundle.licenseFile` in
`tauri.bundle.conf.json`). It's plain ASCII with Windows line endings, which the script checks.

Tauri builds the installer with NSIS; Maku adds three hooks in
[app/src-tauri/windows/hooks.nsh](../app/src-tauri/windows/hooks.nsh):

- Program files go to `%LOCALAPPDATA%\Programs\Maku`, not Tauri's default `%LOCALAPPDATA%\Maku`,
  which is the data folder.
- Uninstalling first asks "Export your Maku data before uninstalling?" and, if yes, runs
  `maku-engine export` into Documents. If the export fails, nothing is removed.
- The data folder (and data moved to another drive) stays unless "Delete the application data"
  is ticked. The library's videos are never touched either way.

Updates skip both questions.

## The signing key

Updates are signed with a minisign key so a tampered installer never runs.

- Private key: `%USERPROFILE%\.tauri\maku-updater.key` (no password), and the
  `TAURI_SIGNING_PRIVATE_KEY` secret in the GitHub repo. **Keep a backup** (a password manager is
  fine). Without it, installed copies can't verify new versions and have to be reinstalled by hand.
- Public key: `plugins.updater.pubkey` in
  [app/src-tauri/tauri.conf.json](../app/src-tauri/tauri.conf.json).

To replace a lost or leaked key: `pnpm tauri signer generate -w <path>`, put the new public key in
`tauri.conf.json`, update the secret (`gh secret set TAURI_SIGNING_PRIVATE_KEY < <path>`), release,
and install that release by hand once.

## Building an installer locally

```powershell
$env:TAURI_SIGNING_PRIVATE_KEY = "$env:USERPROFILE\.tauri\maku-updater.key"
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
cd app; pnpm build:installer
```

The result is in `app/src-tauri/target/release/bundle/nsis/`. `build:installer` uses
`tauri.bundle.conf.json` on top of `tauri.conf.json`, which adds the engine to the bundle and turns
on update signing; `pnpm tauri dev` and CI checks don't need either.
