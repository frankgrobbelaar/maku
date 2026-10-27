"""Write THIRD-PARTY-NOTICES.txt: the open-source software inside Maku, with its licences.

`pnpm build:installer` runs this once the engine and the UI are built. The installer puts the file
next to Maku, and every release carries it (see docs/releasing.md). It lists what actually ships:

- the engine: every file PyInstaller bundled, traced to the package it came from, Python,
  Microsoft's C++ runtime, and the voice detector it carries (engine/src/maku/assets);
- the shell: the Rust standard library and the crates Cargo links into maku.exe on Windows;
- the interface: the packages Vite bundled (from its licence report), the styles and the fonts;
- the installer's own parts;
- and, apart, TMDB's logo, which isn't software: it's TMDB's mark, shown as its terms ask.

Every licence must be one Maku can meet by shipping this file (`ALLOWED`). Anything else stops the
build until someone has checked it, so Maku never ships software it may not share.

    cd engine; uv run python tools/third_party_notices.py
"""

import ast
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from importlib.metadata import Distribution, distributions
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "app/src-tauri/target/THIRD-PARTY-NOTICES.txt"
ENGINE_RECORDS = ROOT / "engine/build/maku-engine"  # PyInstaller's records of what it bundled
ASSETS = ROOT / "engine/src/maku/assets"  # what the engine ships beside its code
UI_REPORT = ROOT / "app/dist/.vite/licenses.json"  # Vite's report of the packages it bundled
NODE_MODULES = ROOT / "app/node_modules"
SHELL = ROOT / "app/src-tauri"
TARGET = "x86_64-pc-windows-msvc"  # the only platform Maku ships for

# Licences Maku meets by shipping this file: it keeps every notice and says where the source code
# is, which is all these ask of a program that includes the software unchanged.
ALLOWED = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "BSL-1.0",
        "CC0-1.0",
        "ISC",
        "MIT",
        "MIT-0",
        "MPL-2.0",
        "OFL-1.1",
        "PSF-2.0",
        "Unicode-3.0",
        "Unicode-DFS-2016",
        "Unlicense",
        "Zlib",
    }
)
# Copyleft made fine by its exception: PyInstaller's lets its bootloader be part of any program.
ALLOWED_WITH = frozenset({"GPL-2.0-or-later WITH Bootloader-exception"})
# Not open source, but free to pass on: Microsoft's redistributable files, which programs may carry
# unchanged, as Python carries vcruntime140.dll. The engine carries two: the Visual C++ runtime,
# which ONNX Runtime needs and Windows doesn't always have, and DirectML, inside ONNX Runtime.
MICROSOFT = "LicenseRef-Microsoft-Redistributable"
_CPP_RUNTIME_TERMS = (
    "Microsoft's Visual C++ runtime ships with the engine unchanged, as Microsoft allows for\n"
    'programs built with its Visual C++ compilers (its "Distributable Code", listed at\n'
    "https://learn.microsoft.com/visualstudio/releases/2022/redistribution). It is Microsoft's,\n"
    "copyright Microsoft Corporation, and stays under Microsoft's terms: Maku's licence doesn't\n"
    "cover it."
)
_DIRECTML_TERMS = (
    "DirectML.dll, in ONNX Runtime's folder, is Microsoft's DirectML Redistributable Library,\n"
    "which runs Whisper on the graphics card. ONNX Runtime ships it unchanged, as Microsoft\n"
    "allows (https://www.nuget.org/packages/Microsoft.AI.DirectML). It is Microsoft's, copyright\n"
    "Microsoft Corporation, and stays under Microsoft's terms: neither the MIT licence above nor\n"
    "Maku's covers it."
)
# The runtime's files, and where the engine takes them from: Windows' own copy, which Microsoft's
# Visual C++ Redistributable installs (maku-engine.spec sees to it, with the same pattern).
CPP_RUNTIME = re.compile(
    r"(concrt140|msvcp140(_\w+)?|vccorlib140|vcruntime140(_\w+)?)\.dll", re.IGNORECASE
)
WINDOWS = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32"

# Python packages whose metadata has no SPDX licence expression, checked by hand.
PYTHON_LICENCES = {
    "anitopy": "MPL-2.0",
    "colorama": "BSD-3-Clause",
    "markdown-it-py": "MIT",
    "mdurl": "MIT",
    "onnxruntime-directml": f"MIT AND {MICROSOFT}",  # ONNX Runtime, and DirectML inside it
    "pyinstaller": "GPL-2.0-or-later WITH Bootloader-exception",
    "shellingham": "ISC",
}
# What a package carries that its own licence files don't speak for, said by hand.
PYTHON_NOTES = {"onnxruntime-directml": _DIRECTML_TERMS}

# Marks Maku shows because their owners ask it to: not software, and not under any licence above.
MARKS = (
    "The TMDB logo (tmdb-logo.svg in the interface) is TMDB's. Maku shows it unchanged beside",
    '"This product uses the TMDB API but is not endorsed or certified by TMDB", as TMDB\'s API',
    "terms ask (https://www.themoviedb.org/about/logos-attribution). Maku's licence doesn't cover",
    "it.",
)

# Packages that ship as CSS and font files, which Vite's report (JavaScript only) doesn't list.
STYLES_AND_FONTS = (
    "tailwindcss",
    "@fontsource-variable/manrope",
    "@fontsource-variable/geist-mono",
)

_LICENCE_FILE = re.compile(
    r"((un)?licen[cs]es?|copying|notice|authors|third[-_]?party[-_]?notices?)([-._].*)?",
    re.IGNORECASE,
)
_CODE = frozenset({".py", ".pyc", ".pyi", ".rs", ".js", ".ts"})


@dataclass(frozen=True)
class Part:
    """A third-party package or program that ships inside Maku."""

    name: str
    version: str
    licence: str  # an SPDX expression, such as "MIT OR Apache-2.0"
    source: str  # where its source code is
    texts: tuple[str, ...] = ()  # its licence files, as its authors wrote them


def main() -> None:
    sections = {
        "The engine (Python)": engine_parts(),
        "The shell (Rust)": shell_parts(),
        "The interface (JavaScript, styles and fonts)": interface_parts(),
        "The installer": installer_parts(),
    }
    refused = [part for parts in sections.values() for part in parts if not allowed(part.licence)]
    if refused:
        names = "\n".join(
            f"  {p.name} {p.version}: {p.licence or 'no licence found'}" for p in refused
        )
        sys.exit(
            f"Maku can't ship these until their licences are checked:\n{names}\n"
            "If a licence allows it, add it to ALLOWED (or the package to PYTHON_LICENCES) in "
            "engine/tools/third_party_notices.py."
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(_maku_version(), sections), encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}: {sum(map(len, sections.values()))} parts.")


def allowed(expression: str) -> bool:
    """Whether Maku may ship software under this SPDX licence expression.

    Of "A OR B" one choice must be allowed, of "A AND B" both. "/" is Cargo's old spelling of OR.
    """
    words = re.findall(r"[()]|[^\s()]+", expression.replace("/", " OR "))
    words.reverse()  # pop() takes the next word

    def either() -> bool:
        result = both()
        while words and words[-1].upper() == "OR":
            words.pop()
            result = both() or result
        return result

    def both() -> bool:
        result = single()
        while words and words[-1].upper() == "AND":
            words.pop()
            result = single() and result
        return result

    def single() -> bool:
        word = words.pop()
        if word == "(":
            result = either()
            return words.pop() == ")" and result
        if words and words[-1].upper() == "WITH":
            words.pop()
            exception = words.pop()  # an exception only ever adds permissions
            return word in ALLOWED or f"{word} WITH {exception}" in ALLOWED_WITH
        return word in ALLOWED or word == MICROSOFT

    try:
        return either() and not words
    except IndexError:  # the expression ended too soon
        return False


def render(version: str, sections: dict[str, list[Part]]) -> str:
    """The notices as plain text. A licence text already shown is referred to, not repeated."""
    lines = [
        f"Third-party notices for Maku {version}",
        "",
        "Maku is free software under the MIT licence (see LICENSE.txt next to this file). It is",
        "built with the software below, which ships inside it: open-source software, and a few",
        "of Microsoft's libraries that programs may carry. Each part keeps its own licence,",
        "reproduced here as its authors wrote it, and the address given for it is where it comes",
        "from: for open-source software, its source code.",
        "",
        "Contents",
    ]
    lines += [
        f"  {n}. {title}: {len(parts)}" for n, (title, parts) in enumerate(sections.items(), 1)
    ]
    shown: dict[str, str] = {}  # a licence text, without its spacing -> the part that showed it
    for n, (title, parts) in enumerate(sections.items(), 1):
        lines += ["", "=" * 78, f"{n}. {title}", "=" * 78]
        for part in parts:
            heading = f"{part.name} {part.version}".strip()
            lines += ["", "-" * 78, heading, f"Licence: {part.licence}", f"Source: {part.source}"]
            if not part.texts:
                lines += ["", "It comes with no licence file; the licence named above applies."]
            for text in part.texts:
                key = " ".join(text.split())
                if key in shown:
                    lines += ["", f"(The licence text is the same as for {shown[key]}, above.)"]
                else:
                    shown[key] = heading
                    lines += ["", text.strip()]
    lines += ["", "=" * 78, "Logos", "=" * 78, "", *MARKS]
    return "\n".join(lines) + "\n"


# The engine


def engine_parts() -> list[Part]:
    """Python, every package that has a file in the engine bundle, and Microsoft's C++ runtime."""
    owners = _installed_files()
    shipped: dict[str, Distribution] = {}
    runtime: set[str] = set()  # the C++ runtime's files
    for file in _bundled_files():
        owner = owners.get(os.path.normcase(file))
        if owner is not None:
            shipped[_normalise(owner.name)] = owner
        elif is_windows_runtime(file):
            runtime.add(file.name.lower())
        elif not (file.is_relative_to(sys.base_prefix) or file.is_relative_to(ROOT)):
            # Neither Python's own files nor Maku's: say so rather than guess its licence.
            sys.exit(f"The engine bundle holds {file}, and it isn't clear where that comes from.")
    shipped.pop("maku", None)
    packages = [_python_package(shipped[name]) for name in sorted(shipped)]
    return [_python(), *packages, *cpp_runtime(runtime), *_assets()]


def is_windows_runtime(file: Path) -> bool:
    """Whether a bundled file is Microsoft's C++ runtime as Windows has it, not a copy that
    another program (ImageMagick, a JDK) keeps on PATH, which could be any version."""
    return file.parent == WINDOWS and CPP_RUNTIME.fullmatch(file.name) is not None


def cpp_runtime(files: Iterable[str]) -> list[Part]:
    """Microsoft's C++ runtime as one part, when the engine carries any of its files."""
    names = sorted(set(files))
    if not names:
        return []
    return [
        Part(
            f"Microsoft Visual C++ runtime ({', '.join(names)})",
            "",
            MICROSOFT,
            "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist",
            (_CPP_RUNTIME_TERMS,),
        )
    ]


def _assets() -> list[Part]:
    """The model the engine carries (see engine/src/maku/assets/README.md)."""
    return [
        Part(
            "pyannote speaker segmentation model (segmentation-3.0)",
            "3.0",
            "MIT",
            "https://huggingface.co/pyannote/segmentation-3.0",
            _read([ASSETS / "pyannote-segmentation-3.0.LICENSE.txt"]),
        ),
    ]


def _bundled_files() -> Iterator[Path]:
    """The source of every file in the engine bundle, from PyInstaller's build records.

    These are the records of what was written: the Python archive (PYZ), the exe and what it
    holds (EXE, PKG), and the folder beside it (COLLECT). Analysis also lists what the spec
    then left out.
    """
    for name in ("PYZ-00.toc", "PKG-00.toc", "EXE-00.toc", "COLLECT-00.toc"):
        record = ENGINE_RECORDS / name
        if not record.exists():
            sys.exit(f"No {record}: build the engine first (pnpm build:engine).")
        yield from sources_in(ast.literal_eval(record.read_text(encoding="utf-8")))


def sources_in(entry: object) -> Iterator[Path]:
    """A record is nested tuples and lists; each file in it is a (name, source, kind) triple."""
    if not isinstance(entry, tuple | list):
        return
    items = list(cast("Iterable[object]", entry))
    match items:
        case [str(), str(source), str()] if Path(source).is_absolute():
            yield Path(source)
        case _:
            for item in items:
                yield from sources_in(item)


def _installed_files() -> dict[str, Distribution]:
    """Every file of every installed Python package, mapped to its package."""
    return {
        os.path.normcase(str(dist.locate_file(file))): dist
        for dist in distributions()
        for file in dist.files or ()
    }


def _python() -> Part:
    """The interpreter, its standard library and the libraries built into it (one licence file)."""
    licence = Path(sys.base_prefix) / "LICENSE.txt"
    return Part(
        "Python",
        platform.python_version(),
        "PSF-2.0",
        "https://www.python.org/downloads/source/",
        (licence.read_text(encoding="utf-8"),),
    )


def _python_package(dist: Distribution) -> Part:
    name, version = dist.name, dist.version
    licence = (
        dist.metadata.get("License-Expression")
        or PYTHON_LICENCES.get(_normalise(name))
        or _spdx_id(dist.metadata.get("License") or "")
    )
    files = [Path(str(dist.locate_file(file))) for file in dist.files or ()]
    note = PYTHON_NOTES.get(_normalise(name))
    return Part(
        name,
        version,
        licence,
        f"https://pypi.org/project/{name}/{version}/",
        _read(file for file in files if is_licence_file(file.name)) + ((note,) if note else ()),
    )


def _normalise(name: str) -> str:
    """A Python package name as PyPI compares them: lower case, runs of -_. as one -."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _spdx_id(text: str) -> str:
    """The text if it is a bare licence identifier ("MIT"), else nothing."""
    return text if re.fullmatch(r"[A-Za-z0-9.+-]+", text) else ""


# The shell


def shell_parts() -> list[Part]:
    """The Rust standard library, and every crate Cargo links into maku.exe on Windows."""
    metadata = json.loads(
        _run("cargo", "metadata", "--format-version=1", "--locked", "--filter-platform", TARGET)
    )
    packages = {package["id"]: package for package in metadata["packages"]}
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    linked: set[str] = set()
    waiting = [metadata["resolve"]["root"]]
    while waiting:
        for dep in nodes[waiting.pop()]["deps"]:
            # Build scripts and tests don't ship, so only normal dependencies count.
            normal = any(kind["kind"] is None for kind in dep["dep_kinds"])
            if normal and dep["pkg"] not in linked:
                linked.add(dep["pkg"])
                waiting.append(dep["pkg"])
    crates = sorted((packages[id_] for id_ in linked), key=lambda c: (c["name"], c["version"]))
    return [_rust_std(), *map(_crate, crates)]


def _rust_std() -> Part:
    # The toolchain ships the licences only as blank templates, so this says it in words.
    notice = (
        "Rust's standard library is compiled into maku.exe. Its copyright stays with the Rust\n"
        "project's contributors, and it is dual-licensed under the MIT licence and the Apache\n"
        "License 2.0, whose texts appear in this file for other parts. Its full notices are at\n"
        "https://github.com/rust-lang/rust/blob/master/COPYRIGHT."
    )
    version = _run("rustc", "--version").split()[1]
    return Part(
        "Rust standard library",
        version,
        "MIT OR Apache-2.0",
        "https://github.com/rust-lang/rust",
        (notice,),
    )


def _crate(crate: dict[str, Any]) -> Part:
    folder = Path(crate["manifest_path"]).parent
    files = [folder / crate["license_file"]] if crate.get("license_file") else []
    files += _licence_files_in(folder)
    name, version = crate["name"], crate["version"]
    return Part(
        name,
        version,
        crate.get("license") or "",
        f"https://crates.io/crates/{name}/{version}",
        _read(dict.fromkeys(files)),  # without repeats, in order
    )


# The interface


def interface_parts() -> list[Part]:
    """What Vite bundled, the styles and fonts, and the components adapted from shadcn/ui."""
    if not UI_REPORT.exists():
        sys.exit(f"No licence report at {UI_REPORT}: build the UI first (pnpm build).")
    parts: dict[str, Part] = {}  # by name@version
    for entry in json.loads(UI_REPORT.read_text(encoding="utf-8")):
        name, version = entry["name"], entry["version"]
        texts = (entry["text"],) if entry.get("text") else ()
        licence = entry.get("identifier", "")
        parts[f"{name}@{version}"] = Part(name, version, licence, _npm(name, version), texts)
    for name in STYLES_AND_FONTS:
        part = _npm_package(NODE_MODULES / name)
        parts.setdefault(f"{part.name}@{part.version}", part)
    shadcn = Part(
        "shadcn/ui",
        "",
        "MIT",
        "https://github.com/shadcn-ui/ui",
        _read([ROOT / "app/src/components/ui/LICENSE-shadcn.txt"]),
    )
    return [*(parts[key] for key in sorted(parts)), shadcn]


def _npm_package(folder: Path) -> Part:
    package = json.loads((folder / "package.json").read_text(encoding="utf-8"))
    name, version = package["name"], package["version"]
    files = _licence_files_in(folder)
    return Part(name, version, package.get("license", ""), _npm(name, version), _read(files))


def _npm(name: str, version: str) -> str:
    return f"https://www.npmjs.com/package/{name}/v/{version}"


# The installer


def installer_parts() -> list[Part]:
    """What Tauri's bundler builds the installer from."""
    return [
        Part(
            "NSIS (Nullsoft Scriptable Install System)", "", "Zlib", "https://nsis.sourceforge.io"
        ),
        Part(
            "nsis-tauri-utils",
            "",
            "MIT OR Apache-2.0",
            "https://github.com/tauri-apps/nsis-tauri-utils",
        ),
    ]


# Helpers


def is_licence_file(name: str) -> bool:
    """LICENSE, LICENSE-MIT, COPYING.txt, NOTICE, AUTHORS and the like, but not code."""
    return bool(_LICENCE_FILE.fullmatch(name)) and Path(name).suffix.lower() not in _CODE


def _licence_files_in(folder: Path) -> list[Path]:
    return [
        file for file in sorted(folder.iterdir()) if file.is_file() and is_licence_file(file.name)
    ]


def _read(files: Iterable[Path]) -> tuple[str, ...]:
    return tuple(file.read_text(encoding="utf-8", errors="replace") for file in files)


def _run(program: str, *args: str) -> str:
    path = shutil.which(program)
    if path is None:
        sys.exit(f"{program} isn't on PATH; the notices need it (see docs/development.md).")
    result = subprocess.run(
        [path, *args], cwd=SHELL, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return result.stdout


def _maku_version() -> str:
    return json.loads((ROOT / "app/package.json").read_text(encoding="utf-8"))["version"]


if __name__ == "__main__":
    main()
