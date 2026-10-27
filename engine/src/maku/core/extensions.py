"""What a file is by its extension: a video, or subtitles. Shared by scanning and tidying up."""

from pathlib import PureWindowsPath

VIDEO_EXTENSIONS = frozenset(
    {
        ".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".flv", ".webm", ".ogm", ".divx",
        ".ts", ".m2ts", ".mts", ".mpg", ".mpeg", ".vob", ".rm", ".rmvb", ".3gp",
    }
)  # fmt: skip
SUBTITLE_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".sup"})


def is_video(name: str) -> bool:
    """A video by its extension, in any case. Subtitles, reports and pictures aren't."""
    return PureWindowsPath(name).suffix.casefold() in VIDEO_EXTENSIONS


def is_subtitle(name: str) -> bool:
    return PureWindowsPath(name).suffix.casefold() in SUBTITLE_EXTENSIONS
