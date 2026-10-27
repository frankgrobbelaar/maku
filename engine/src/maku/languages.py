"""The subtitle files beside videos, and the languages their names say: maku/core/languages.py
reads the names, this looks in the folders."""

from collections.abc import Iterable
from pathlib import Path

from maku.core.languages import beside_language
from maku.core.plan import sidecars_of


def beside(videos: Iterable[Path]) -> dict[Path, list[str]]:
    """Each video's subtitle files' languages ("en"; "" for a file whose name doesn't say), each
    folder looked in once. A folder that can't be read has none."""
    by_folder: dict[Path, list[Path]] = {}
    for video in videos:
        by_folder.setdefault(video.parent, []).append(video)
    found: dict[Path, list[str]] = {}
    for folder, held in by_folder.items():
        try:
            names = [each.name for each in folder.iterdir()]
        except OSError:
            names = []
        for video in held:
            found[video] = [beside_language(each, video) for each in sidecars_of(video, names)]
    return found
