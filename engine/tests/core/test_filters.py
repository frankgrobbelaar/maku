"""Paths written into ffmpeg's filter graphs (a subtitles file, its fonts' folder): escaped once
for the filter's option and again for the graph, so ffmpeg reads back the path as it is."""

from pathlib import PureWindowsPath

import pytest

from maku.core.filters import filter_path


def read_back(text: str, splits: str) -> str:
    """What ffmpeg makes of one level of a filter graph (av_get_token): a backslash keeps the
    next character as it is, and quotes keep what's between them. Any of `splits` left bare
    would end the value there."""
    out: list[str] = []
    quoted = False
    escaped = False
    for char in text:
        if escaped:
            out.append(char)
            escaped = False
        elif quoted:
            if char == "'":
                quoted = False
            else:
                out.append(char)
        elif char == "\\":
            escaped = True
        elif char == "'":
            quoted = True
        else:
            assert char not in splits, f"a bare {char!r} ends the value early"
            out.append(char)
    return "".join(out)


def test_a_windows_path_has_forward_slashes_and_its_colon_escaped():
    assert filter_path(PureWindowsPath(r"C:\Maku\subtitles.ass")) == r"C\\:/Maku/subtitles.ass"


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\O'Brien\AppData\Local\Maku\cache\player\3.ass",
        r"D:\Videos\[Subs] Glass Orchard, part 1; take 2\episode.ass",
        r"E:\It's here\a\fonts",
    ],
)
def test_ffmpeg_reads_back_the_path_as_it_is(path: str):
    written = filter_path(PureWindowsPath(path))

    option = read_back(written, splits=",;[]")  # the graph: these end a filter
    assert read_back(option, splits=":") == path.replace("\\", "/")  # the option: ":" ends it
