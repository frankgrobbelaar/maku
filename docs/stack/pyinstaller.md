# PyInstaller (bundling the engine)

The installed Maku can't assume Python is on the PC, so [PyInstaller](https://pyinstaller.org)
bundles the engine with its own Python into a folder: `maku-engine.exe` plus `_internal/` (the
interpreter, the packages, about 35 MB, 60 files). The installer copies that folder next to
Maku's window as `engine\`.

A folder ("onedir") rather than a single exe because a single exe unpacks itself into a temporary
folder on every start: slower, and it upsets antivirus tools.

## Files

| File | What it holds |
| --- | --- |
| `engine/maku-engine.spec` | The recipe: entry point, package metadata, console program, no UPX |
| `engine/src/maku/__main__.py` | The entry point (also `python -m maku`) |
| `engine/dist/maku-engine/` | The output (ignored by git) |

## Building

```powershell
cd engine; uv run pyinstaller maku-engine.spec --noconfirm
dist\maku-engine\maku-engine.exe version
```

`pnpm build:installer` does this first, through `tauri.bundle.conf.json`.

## How the spec works

- `Analysis` starts at `__main__.py` and follows imports; `pathex=["src"]` finds the package.
- `copy_metadata("maku")` includes the package's metadata, which `maku.__version__` reads.
- Packages that load modules by name (Uvicorn) are covered by the hooks in
  `pyinstaller-hooks-contrib`, which comes with PyInstaller.
- `console=True`: the engine is a console program (the uninstaller and the CLI read its output);
  the shell starts it with no console window.
- UPX compression is off: it saves little and causes antivirus false alarms.
- `excludes` drops packages that only optional imports reach: setuptools (through `distutils`)
  and pytest (anyio's test runner). The filter after `Analysis` drops the Universal C Runtime
  DLLs, which Windows 10 and 11 have built in; otherwise PyInstaller copies whichever ones it
  finds on PATH (a JDK's, on the owner's PC), and builds would differ between PCs.
- Microsoft's Visual C++ runtime (`msvcp140.dll` and its kin), which ONNX Runtime needs and not
  every PC has, ships with the engine from Windows' own copy in `System32`, which Microsoft's Visual
  C++ Redistributable installs. Left alone, PyInstaller takes the first copy on PATH (ImageMagick's
  on GitHub's runners, a JDK's on the owner's PC), which could be any version, and the notices
  couldn't say what it is. A PC that builds the engine needs the Redistributable; GitHub's runners
  have it.
- PyInstaller's records of what it bundled (`build/maku-engine/*.toc`) feed the third-party
  notices (see [../releasing.md](../releasing.md#third-party-notices)).

## When something is missing

If the bundled engine fails with `ModuleNotFoundError` while `uv run maku` works, PyInstaller
didn't see an import made by name. Add it to `hiddenimports=[...]` in `Analysis`, or collect a
whole package with `collect_submodules("name")`, then rebuild and run
`dist\maku-engine\maku-engine.exe serve` with `MAKU_TOKEN` set to check. Data files a package
reads at run time go in `datas`.

ffmpeg won't go in this bundle: Maku downloads it on first setup (the "Tools and this PC" step in
the setup screen), which keeps the installer and every update smaller, and Whisper's models come
the first time the owner makes subtitles at their quality ([speech.md](speech.md)). ONNX Runtime
with DirectML and pyannote's voice detector (`engine/src/maku/assets/`, 6 MB) are small and ship
inside Maku.

## Upgrading

`uv lock --upgrade` updates PyInstaller and its hooks. Rebuild, then run the engine's handshake test
against the bundle, as the release workflow does before publishing:

```powershell
cd engine; $env:MAKU_ENGINE_EXE = "dist\maku-engine\maku-engine.exe"; uv run pytest tests/test_cli.py -k announces
```
