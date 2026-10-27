"""What a scan counts as a video, where it never looks, and how folders may sit together."""

from pathlib import PureWindowsPath

import pytest

from maku.core.extensions import is_video
from maku.core.library import (
    Covered,
    Holds,
    Picture,
    fits,
    picture_size,
    skipped_folder,
    time_left,
    work_of,
)


@pytest.mark.parametrize(
    "name",
    [
        "[Group] Glass Orchard - 001 [480p].mkv",
        "Quiet Hours - 003 - The Night Train.MKV",
        "The Lantern Keeper.avi",
        "Starfall (2008).mp4",
        "VTS_01_1.VOB",
        "episode.m2ts",
        "old.rmvb",
        "show.ogm",
    ],
)
def test_videos_are_found_whatever_the_case_of_their_extension(name: str):
    assert is_video(name)


@pytest.mark.parametrize(
    "name",
    [
        "Quiet Hours - 001.en.srt",
        "Maku - Gap analysis.md",
        "folder.jpg",
        "The Harbour Line (2019) - S01E01.mkv.maku-partial",  # a copy Maku is still making
        "release.nfo",
        "mkv",
    ],
)
def test_subtitles_reports_pictures_and_unfinished_copies_are_not_videos(name: str):
    assert not is_video(name)


@pytest.mark.parametrize(
    ("name", "skipped"),
    [
        ("Maku quarantine", True),
        ("maku QUARANTINE", True),
        ("$RECYCLE.BIN", True),
        ("System Volume Information", True),
        (".thumbnails", True),
        ("Season 01", False),
        ("The Harbour Line (2019)", False),
        ("Specials", False),
    ],
)
def test_a_scan_never_looks_in_quarantine_or_windows_own_folders(name: str, skipped: bool):
    assert skipped_folder(name) is skipped


VIDEOS = PureWindowsPath(r"D:\Videos")


def test_a_new_folder_fits_beside_unrelated_ones():
    assert fits(PureWindowsPath(r"F:\More films"), [VIDEOS]) is None
    assert fits(PureWindowsPath(r"D:\Videos films"), [VIDEOS]) is None  # a prefix isn't a parent


def test_a_folder_already_covered_isnt_added_twice():
    assert fits(PureWindowsPath(r"d:\videos"), [VIDEOS]) == Covered(VIDEOS)
    assert fits(PureWindowsPath(r"D:\Videos\Drama\Harbour Line"), [VIDEOS]) == Covered(VIDEOS)


def test_a_parent_folder_takes_in_the_folders_below_it():
    drama, films = PureWindowsPath(r"D:\Videos\Drama"), PureWindowsPath(r"D:\Videos\Films")

    assert fits(VIDEOS, [drama, PureWindowsPath(r"F:\Other"), films]) == Holds((drama, films))


@pytest.mark.parametrize(
    ("done", "total", "elapsed", "left"),
    [
        (0, 100, 0.0, None),  # no pace yet
        (3, 100, 9.0, None),  # too few files to tell
        (50, 100, 100.0, 100.0),
        (100, 100, 200.0, 0.0),
    ],
)
def test_time_left_follows_the_pace_so_far(
    done: int, total: int, elapsed: float, left: float | None
):
    assert time_left(done, total, elapsed) == left


@pytest.mark.parametrize(
    ("width", "height", "size"),
    [
        (720, 540, "sd"),  # an old 4:3 series' episodes
        (720, 576, "sd"),  # PAL DVD
        (640, 480, "sd"),
        (1280, 720, "720p"),
        (960, 720, "720p"),  # 4:3 at 720p
        (1440, 1080, "1080p"),
        (1920, 800, "1080p"),  # a wide film at 1080p
        (3840, 2160, "larger"),
        (None, None, "unknown"),
    ],
)
def test_a_picture_is_sorted_by_its_size(width: int | None, height: int | None, size: Picture):
    assert picture_size(width, height) == size


def test_a_files_result_is_made_beside_it_under_its_whole_name():
    folder = PureWindowsPath(r"D:\Videos\Old")

    assert work_of(folder / "Ep01.avi") == folder / "Ep01.avi.maku-converting"
    assert work_of(folder / "Ep01.avi") != work_of(folder / "Ep01.mp4")
