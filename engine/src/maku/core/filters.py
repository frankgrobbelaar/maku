"""Writing a path into an ffmpeg filter graph, as a filter's option (a subtitles file the player
draws into the picture, and its fonts' folder).

ffmpeg reads such a value twice: the graph first, where `,`, `;`, `[` and `]` end a filter, then
the filter's options, where `:` ends one. Each reading takes away one level of backslashes and
quotes, so the path is escaped for the option and then again for the graph.
"""

from pathlib import PurePath

_OPTION = "\\':"  # what the options' reading takes as its own
_GRAPH = "\\',;[]"  # what the graph's reading does


def filter_path(path: PurePath) -> str:
    r"""A path as a filter's option value: forward slashes, and escaped so ffmpeg reads it back as
    it is (C:\Maku\subtitles.ass is C\\:/Maku/subtitles.ass)."""
    return _escape(_escape(str(path).replace("\\", "/"), _OPTION), _GRAPH)


def _escape(text: str, special: str) -> str:
    return "".join(f"\\{char}" if char in special else char for char in text)
