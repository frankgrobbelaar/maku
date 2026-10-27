"""The licence check and the notices file that every installer and release carries."""

from pathlib import Path

import pytest
from third_party_notices import (
    MICROSOFT,
    WINDOWS,
    Part,
    allowed,
    cpp_runtime,
    is_licence_file,
    is_windows_runtime,
    render,
    sources_in,
)

MIT = """MIT License

Copyright (c) 2020 Someone

Permission is hereby granted, free of charge, to any person obtaining a copy..."""


@pytest.mark.parametrize(
    "expression",
    [
        "MIT",
        "MIT OR Apache-2.0",
        "MIT/Apache-2.0",  # Cargo's old spelling
        "Apache-2.0 / MIT",
        "(MIT OR Apache-2.0) AND Unicode-3.0",
        "Apache-2.0 WITH LLVM-exception",
        "GPL-2.0-or-later WITH Bootloader-exception",  # PyInstaller
        "MIT OR GPL-3.0-only",  # Maku takes the MIT choice
        "MPL-2.0",
        MICROSOFT,  # not open source, but free to pass on: its C++ runtime
        f"MIT AND {MICROSOFT}",  # ONNX Runtime, with Microsoft's DirectML inside
    ],
)
def test_licences_maku_can_meet(expression: str):
    assert allowed(expression)


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "GPL-3.0-only",
        "LGPL-2.1-or-later",
        "MIT AND GPL-3.0-only",  # both apply, and one can't be met
        "GPL-3.0-only WITH Classpath-exception-2.0",
        "LicenseRef-Proprietary",
        "MIT OR",
        "(MIT",
        "MIT Apache-2.0",  # no operator between them
    ],
)
def test_licences_that_stop_the_build(expression: str):
    assert not allowed(expression)


@pytest.mark.parametrize(
    "name",
    [
        "LICENSE",
        "LICENSE.txt",
        "LICENSE-MIT",
        "license-apache.md",
        "LICENCE",
        "LICENSES.txt",
        "UNLICENSE",
        "COPYING",
        "NOTICE",
        "AUTHORS.md",
        "ThirdPartyNotices.txt",  # ONNX Runtime's, for what's built into it
        "THIRD-PARTY-NOTICES.txt",
    ],
)
def test_licence_files_are_recognised(name: str):
    assert is_licence_file(name)


@pytest.mark.parametrize(
    "name",
    ["license.py", "license.rs", "README.md", "Cargo.toml", "lib.rs", "third_party_notices.py"],
)
def test_other_files_are_not(name: str):
    assert not is_licence_file(name)


def test_files_are_read_from_pyinstallers_records():
    fastapi = r"C:\venv\Lib\site-packages\fastapi\__init__.py"
    record = (
        r"C:\build\PYZ-00.pyz",
        [
            ("fastapi", fastapi, "PYMODULE"),
            ("W ignore", "", "OPTION"),  # not a file
            ("pyi_rth_inspect", ("nested", r"C:\x\pyi_rth_inspect.py", "PYSOURCE"), "X"),
        ],
    )

    assert list(sources_in(record)) == [Path(fastapi), Path(r"C:\x\pyi_rth_inspect.py")]


def test_microsofts_cpp_runtime_is_known_only_as_windows_own_copy():
    """ONNX Runtime needs it; a copy another program left on PATH could be any version."""
    assert is_windows_runtime(WINDOWS / "MSVCP140_1.dll")
    assert is_windows_runtime(Path(str(WINDOWS).upper()) / "vcruntime140.dll")
    assert not is_windows_runtime(Path(r"C:\Program Files\ImageMagick-7.1\MSVCP140_1.dll"))
    assert not is_windows_runtime(Path(r"C:\Program Files\Java\jdk-25\bin\msvcp140.dll"))
    assert not is_windows_runtime(WINDOWS / "d3d12.dll")  # Windows' own, never carried


def test_microsofts_cpp_runtime_is_one_part_of_the_engine():
    (part,) = cpp_runtime(["vcruntime140.dll", "msvcp140_1.dll", "msvcp140.dll"])

    assert (
        part.name == "Microsoft Visual C++ runtime (msvcp140.dll, msvcp140_1.dll, vcruntime140.dll)"
    )
    assert part.licence == MICROSOFT
    assert "Maku's licence doesn't cover it" in " ".join(part.texts[0].split())
    assert cpp_runtime([]) == []


def test_the_notices_show_each_licence_text_once():
    sections = {
        "The shell (Rust)": [
            Part("a", "1.0.0", "MIT", "https://crates.io/crates/a/1.0.0", (MIT,)),
            Part("b", "2.0.0", "MIT", "https://crates.io/crates/b/2.0.0", (MIT + "\n",)),
            Part("NSIS", "", "Zlib", "https://nsis.sourceforge.io"),
        ]
    }

    text = render("0.1.0", sections)

    assert text.startswith("Third-party notices for Maku 0.1.0\n")
    assert "  1. The shell (Rust): 3\n" in text
    assert text.count("Copyright (c) 2020 Someone") == 1
    assert "b 2.0.0\nLicence: MIT\nSource: https://crates.io/crates/b/2.0.0\n" in text
    assert "(The licence text is the same as for a 1.0.0, above.)" in text
    assert "NSIS\nLicence: Zlib\n" in text
    assert "It comes with no licence file; the licence named above applies." in text
    assert "\nLogos\n" in text  # TMDB's, said to be TMDB's
    assert "The TMDB logo (tmdb-logo.svg in the interface) is TMDB's." in text
