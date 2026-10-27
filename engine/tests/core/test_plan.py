"""Tidy-up plans, for made-up series and films, as the design's tidy board lays them out."""

from datetime import date
from fractions import Fraction
from pathlib import PureWindowsPath

from maku.core.copies import Copy
from maku.core.media import Audio, MediaInfo, Subtitle, Video
from maku.core.plan import (
    DELETED,
    Change,
    ChangeKind,
    EpisodeOf,
    MovieOf,
    PlacedFile,
    in_quarantine,
    plan_set_aside,
    plan_tidy,
    quarantine_place,
    sidecars_of,
)

LIBRARY = PureWindowsPath(r"D:\Videos")
DAY = date(2026, 10, 10)


def media(height: int, *, audio: int = 1, subtitles: bool = False) -> MediaInfo:
    video = Video("h264", round(height * 4 / 3), height, Fraction(4, 3), None, 8, False)
    tracks = tuple(Audio("aac", 2, "eng", False) for _ in range(audio))
    subs = (Subtitle("ass", "eng", True, False),) if subtitles else ()
    return MediaInfo("mkv", 1400.0, height * 500_000, video, tracks, subs)


def placed(
    path: str, identity: EpisodeOf | MovieOf, media_info: MediaInfo | None = None
) -> PlacedFile:
    return PlacedFile(Copy(LIBRARY / path, media_info or media(480)), identity)


HARBOUR_1 = EpisodeOf("The Harbour Line", 2019, season=1, episode=1, title="Pilot")
HARBOUR_2 = EpisodeOf("The Harbour Line", 2019, season=1, episode=2, title="Low Tide")
ORCHARD_1 = EpisodeOf("Glass Orchard", 2012, season=1, episode=1, title="First Frost")
ORCHARD_7 = EpisodeOf("Glass Orchard", 2012, season=1, episode=7, title="Windfall")
QUIET_3 = EpisodeOf("Quiet Hours", 2015, season=1, episode=3, title="The Last Bus")
ASCENT = MovieOf("Starfall: Ascent", 2015)


def test_the_tidy_boards_downloads_folder():
    files = [
        placed(r"Downloads\[GRP] The_Harbour_Line_-_01_(BD_720p).mkv", HARBOUR_1),
        placed(r"Downloads\[GRP] The_Harbour_Line_-_02_(BD_720p).mkv", HARBOUR_2),
        placed(r"Downloads\Glass Orchard 01.avi", ORCHARD_1),
        placed(
            r"Downloads\[GRP] Glass_Orchard_07 (720p).mkv",
            ORCHARD_7,
            media(720, audio=2, subtitles=True),
        ),
        placed(r"Downloads\Glass Orchard 07.avi", ORCHARD_7, media(480)),
        placed(r"Downloads\quiet_hours_03.mp4", QUIET_3),
        placed(r"Downloads\Starfall Ascent.mkv", ASCENT),
    ]

    changes = plan_tidy(files, LIBRARY, day=DAY).changes

    assert [(c.kind, str(c.source.name), str(c.target)) for c in changes] == [
        (
            ChangeKind.QUARANTINE,
            "Glass Orchard 07.avi",
            r"D:\Maku quarantine\2026-10-10\Glass Orchard 07.avi",
        ),
        (
            ChangeKind.MOVE,
            "Starfall Ascent.mkv",
            r"D:\Videos\Movies\Starfall - Ascent (2015)\Starfall - Ascent (2015).mkv",
        ),
        (
            ChangeKind.MOVE,
            "Glass Orchard 01.avi",
            r"D:\Videos\TV\Glass Orchard (2012)\Season 01"
            r"\Glass Orchard (2012) - S01E01 - First Frost.avi",
        ),
        (
            ChangeKind.MOVE,
            "[GRP] Glass_Orchard_07 (720p).mkv",
            r"D:\Videos\TV\Glass Orchard (2012)\Season 01"
            r"\Glass Orchard (2012) - S01E07 - Windfall.mkv",
        ),
        (
            ChangeKind.MOVE,
            "quiet_hours_03.mp4",
            r"D:\Videos\TV\Quiet Hours (2015)\Season 01"
            r"\Quiet Hours (2015) - S01E03 - The Last Bus.mp4",
        ),
        (
            ChangeKind.MOVE,
            "[GRP] The_Harbour_Line_-_01_(BD_720p).mkv",
            r"D:\Videos\TV\The Harbour Line (2019)\Season 01"
            r"\The Harbour Line (2019) - S01E01 - Pilot.mkv",
        ),
        (
            ChangeKind.MOVE,
            "[GRP] The_Harbour_Line_-_02_(BD_720p).mkv",
            r"D:\Videos\TV\The Harbour Line (2019)\Season 01"
            r"\The Harbour Line (2019) - S01E02 - Low Tide.mkv",
        ),
    ]


def test_a_duplicate_says_which_copy_was_kept_and_why():
    files = [
        placed(r"Downloads\[GRP] Glass_Orchard_07 (720p).mkv", ORCHARD_7, media(720, audio=2)),
        placed(r"Downloads\Glass Orchard 07.avi", ORCHARD_7, media(480)),
    ]

    quarantine = plan_tidy(files, LIBRARY, day=DAY).changes[0]

    assert quarantine.label == "Glass Orchard · S01E07 · duplicate"
    assert quarantine.reason == (
        "Kept [GRP] Glass_Orchard_07 (720p).mkv instead: higher resolution and an extra audio track"
    )


def test_labels_name_the_episode_or_movie():
    changes = plan_tidy(
        [placed(r"x\a.mkv", HARBOUR_1), placed(r"x\b.mkv", ASCENT)], LIBRARY, day=DAY
    ).changes

    assert {c.label for c in changes} == {"The Harbour Line · S01E01", "Starfall: Ascent"}


def test_a_file_already_in_place_needs_nothing():
    path = r"TV\Quiet Hours (2015)\Season 01\Quiet Hours (2015) - S01E03 - The Last Bus.mp4"

    assert plan_tidy([placed(path, QUIET_3)], LIBRARY, day=DAY).changes == ()


def test_a_name_differing_only_in_case_is_renamed():
    path = r"TV\Quiet Hours (2015)\Season 01\quiet hours (2015) - s01e03 - the last bus.mp4"

    changes = plan_tidy([placed(path, QUIET_3)], LIBRARY, day=DAY).changes

    assert [c.target.name for c in changes] == ["Quiet Hours (2015) - S01E03 - The Last Bus.mp4"]


def test_a_name_another_file_already_has_gets_2():
    existing = (
        r"D:\Videos\TV\Quiet Hours (2015)\Season 01\Quiet Hours (2015) - S01E03 - The Last Bus.mp4"
    )

    changes = plan_tidy(
        [placed(r"Downloads\quiet_hours_03.mp4", QUIET_3)], LIBRARY, day=DAY, taken={existing}
    ).changes

    assert changes[0].target.name == "Quiet Hours (2015) - S01E03 - The Last Bus (2).mp4"
    assert (
        changes[0].reason
        == "Named and filed. A file with this name is already there; both are kept"
    )


def test_quarantine_never_overwrites_either():
    already = r"D:\Maku quarantine\2026-10-10\Glass Orchard 07.avi"
    files = [
        placed(r"Downloads\[GRP] Glass_Orchard_07 (720p).mkv", ORCHARD_7, media(720)),
        placed(r"Downloads\Glass Orchard 07.avi", ORCHARD_7, media(480)),
    ]

    quarantine = plan_tidy(files, LIBRARY, day=DAY, taken={already}).changes[0]

    assert str(quarantine.target) == r"D:\Maku quarantine\2026-10-10\Glass Orchard 07 (2).avi"


def test_three_copies_keep_one():
    files = [
        placed(rf"x\{n}.mkv", HARBOUR_1, media(h)) for n, h in (("a", 480), ("b", 720), ("c", 576))
    ]

    changes = plan_tidy(files, LIBRARY, day=DAY).changes

    kinds = sorted((c.kind, c.source.name) for c in changes)
    assert kinds == [
        (ChangeKind.MOVE, "b.mkv"),
        (ChangeKind.QUARANTINE, "a.mkv"),
        (ChangeKind.QUARANTINE, "c.mkv"),
    ]


def test_a_file_whose_place_can_never_fit_is_left_alone_with_a_reason():
    deep = PureWindowsPath("D:\\" + "\\".join(["Folder"] * 40))
    file = PlacedFile(Copy(deep.parent / "x.mkv", media(480)), HARBOUR_1)

    plan = plan_tidy([file], deep, day=DAY)

    assert plan.changes == ()
    assert plan.skipped == ((file.copy.path, "The new name would be too long for Windows"),)


def test_a_change_is_a_plain_value():
    change = Change(ChangeKind.MOVE, LIBRARY / "a", LIBRARY / "b", "label", "reason")

    assert change == Change(ChangeKind.MOVE, LIBRARY / "a", LIBRARY / "b", "label", "reason")


def test_subtitles_beside_a_video_move_and_rename_with_it():
    video = LIBRARY / "Downloads" / "Glass Orchard 01.avi"
    subtitles = (
        video.with_name("Glass Orchard 01.en.srt"),
        video.with_name("Glass Orchard 01.fr.ass"),
    )
    files = [PlacedFile(Copy(video, media(480)), ORCHARD_1, sidecars=subtitles)]

    changes = plan_tidy(files, LIBRARY, day=DAY).changes

    season = r"D:\Videos\TV\Glass Orchard (2012)\Season 01"
    assert [(c.source.name, str(c.target), c.label, c.reason) for c in changes] == [
        (
            "Glass Orchard 01.avi",
            season + r"\Glass Orchard (2012) - S01E01 - First Frost.avi",
            "Glass Orchard · S01E01",
            "Named and filed",
        ),
        (
            "Glass Orchard 01.en.srt",
            season + r"\Glass Orchard (2012) - S01E01 - First Frost.en.srt",
            "Glass Orchard · S01E01 · subtitles",
            "Follows its video",
        ),
        (
            "Glass Orchard 01.fr.ass",
            season + r"\Glass Orchard (2012) - S01E01 - First Frost.fr.ass",
            "Glass Orchard · S01E01 · subtitles",
            "Follows its video",
        ),
    ]


def test_a_quarantined_copys_subtitles_go_with_it():
    better = placed(r"Downloads\[GRP] Glass_Orchard_07 (720p).mkv", ORCHARD_7, media(720))
    worse = LIBRARY / "Downloads" / "Glass Orchard 07.avi"
    files = [
        better,
        PlacedFile(Copy(worse, media(480)), ORCHARD_7, (worse.with_suffix(".srt"),)),
    ]

    changes = plan_tidy(files, LIBRARY, day=DAY).changes

    quarantined = [str(c.target) for c in changes if c.kind is ChangeKind.QUARANTINE]
    assert quarantined == [
        r"D:\Maku quarantine\2026-10-10\Glass Orchard 07.avi",
        r"D:\Maku quarantine\2026-10-10\Glass Orchard 07.srt",
    ]


def test_only_subtitles_named_after_the_video_belong_to_it():
    video = LIBRARY / "Show" / "Episode 1.mkv"
    names = [
        "Episode 1.mkv",
        "Episode 1.srt",
        "Episode 1.en.forced.ass",
        "EPISODE 1.EN.SRT",
        "Episode 10.en.srt",  # another episode's
        "Episode 1.nfo",  # not subtitles
        "Episode 1 extra.srt",  # not named after it
    ]

    assert [path.name for path in sidecars_of(video, names)] == [
        "Episode 1.en.forced.ass",
        "EPISODE 1.EN.SRT",
        "Episode 1.srt",
    ]


def test_subtitles_go_to_the_video_whose_name_fits_them_best():
    folder = LIBRARY / "Show"
    names = ["Show - 12.mkv", "Show - 12.5.mkv", "Show - 12.en.srt", "Show - 12.5.en.srt"]

    assert [p.name for p in sidecars_of(folder / "Show - 12.mkv", names)] == ["Show - 12.en.srt"]
    assert [p.name for p in sidecars_of(folder / "Show - 12.5.mkv", names)] == [
        "Show - 12.5.en.srt"
    ]


def test_a_change_of_case_alone_renames_the_subtitles_too():
    season = LIBRARY / "TV" / "The Harbour Line (2019)" / "Season 01"
    video = season / "the harbour line (2019) - s01e01 - pilot.mkv"
    subtitles = video.with_name("the harbour line (2019) - s01e01 - pilot.en.srt")
    files = [PlacedFile(Copy(video, media(480)), HARBOUR_1, (subtitles,))]

    changes = plan_tidy(files, LIBRARY, day=DAY, taken=[str(video), str(subtitles)]).changes

    assert {c.target.name for c in changes} == {
        "The Harbour Line (2019) - S01E01 - Pilot.mkv",
        "The Harbour Line (2019) - S01E01 - Pilot.en.srt",  # not "… (2).en.srt"
    }


def test_the_owner_can_keep_the_other_copy():
    better = placed(r"Downloads\[GRP] Glass_Orchard_07 (720p).mkv", ORCHARD_7, media(720))
    chosen = placed(r"Downloads\Glass Orchard 07.avi", ORCHARD_7, media(480))

    changes = plan_tidy([better, chosen], LIBRARY, day=DAY, keep={chosen.copy.path}).changes

    assert [(c.kind, c.source.name) for c in changes] == [
        (ChangeKind.QUARANTINE, "[GRP] Glass_Orchard_07 (720p).mkv"),
        (ChangeKind.MOVE, "Glass Orchard 07.avi"),
    ]
    assert changes[0].reason == "Kept Glass Orchard 07.avi instead: you chose it"


def test_each_file_goes_under_its_own_library_folder():
    other = PureWindowsPath("F:/More videos")
    files = [
        placed(r"Downloads\quiet_hours_03.mp4", QUIET_3),
        PlacedFile(Copy(other / "Harbour" / "01.mkv", media(480)), HARBOUR_1, root=other),
    ]

    targets = sorted(str(c.target) for c in plan_tidy(files, LIBRARY, day=DAY).changes)

    assert targets == [
        r"D:\Videos\TV\Quiet Hours (2015)\Season 01\Quiet Hours (2015) - S01E03 - The Last Bus.mp4",
        r"F:\More videos\TV\The Harbour Line (2019)\Season 01"
        r"\The Harbour Line (2019) - S01E01 - Pilot.mkv",
    ]


def test_a_file_holding_more_episodes_isnt_a_copy_of_one_holding_fewer():
    both = EpisodeOf("The Harbour Line", 2019, season=1, episode=1, last_episode=2)
    files = [
        placed(r"x\The Harbour Line - 01-02.mkv", both, media(480)),
        placed(r"x\The Harbour Line - 01.mkv", HARBOUR_1, media(720)),
    ]

    changes = plan_tidy(files, LIBRARY, day=DAY).changes

    assert {c.kind for c in changes} == {ChangeKind.MOVE}
    assert len(changes) == 2


def test_the_parts_of_a_film_are_filed_together_not_set_aside():
    files = [
        placed(r"x\Northern Lights (2004) CD1.avi", MovieOf("Northern Lights", 2004, part=1)),
        placed(r"x\Northern Lights (2004) CD2.avi", MovieOf("Northern Lights", 2004, part=2)),
    ]

    changes = plan_tidy(files, LIBRARY, day=DAY).changes

    assert [(c.kind, str(c.target)) for c in changes] == [
        (
            ChangeKind.MOVE,
            r"D:\Videos\Movies\Northern Lights (2004)\Northern Lights (2004) - pt1.avi",
        ),
        (
            ChangeKind.MOVE,
            r"D:\Videos\Movies\Northern Lights (2004)\Northern Lights (2004) - pt2.avi",
        ),
    ]
    assert [c.label for c in changes] == ["Northern Lights · part 1", "Northern Lights · part 2"]


def test_two_titles_of_one_name_and_year_are_never_copies_of_each_other():
    one = EpisodeOf("Signal", 2016, season=1, episode=1, title_id=1)
    other = EpisodeOf("Signal", 2016, season=1, episode=1, title_id=2)

    changes = plan_tidy(
        [placed(r"x\a.mkv", one), placed(r"y\b.mkv", other)], LIBRARY, day=DAY
    ).changes

    assert {c.kind for c in changes} == {ChangeKind.MOVE}


def test_two_copies_sharing_one_subtitle_file_leave_it_with_the_one_kept():
    kept, copy = LIBRARY / "Downloads" / "Ep.mkv", LIBRARY / "Downloads" / "Ep.mp4"
    subtitles = (kept.with_suffix(".srt"),)
    files = [
        PlacedFile(Copy(kept, media(720)), HARBOUR_1, subtitles),
        PlacedFile(Copy(copy, media(480)), HARBOUR_1, subtitles),
    ]

    changes = plan_tidy(files, LIBRARY, day=DAY).changes

    assert [(c.kind, c.source.name) for c in changes] == [
        (ChangeKind.QUARANTINE, "Ep.mp4"),
        (ChangeKind.MOVE, "Ep.mkv"),
        (ChangeKind.MOVE, "Ep.srt"),
    ]


def test_a_subtitle_two_videos_names_fit_goes_with_one_of_them_only():
    first, second = LIBRARY / "x" / "Ep.mkv", LIBRARY / "x" / "Ep.mp4"
    subtitles = (first.with_suffix(".srt"),)
    files = [
        PlacedFile(Copy(first, media(720)), HARBOUR_1, subtitles),
        PlacedFile(Copy(second, media(720)), EpisodeOf("The Harbour Line", 2019, 1, 2), subtitles),
    ]

    changes = plan_tidy(files, LIBRARY, day=DAY).changes

    assert sorted(c.source.name for c in changes) == ["Ep.mkv", "Ep.mp4", "Ep.srt"]


def test_a_subtitle_whose_new_name_is_too_long_keeps_its_video_where_it_is():
    deep = PureWindowsPath("D:\\" + "\\".join(["Folder"] * 26))
    video = deep / "x.mkv"
    subtitle = video.with_name("x." + "a" * 40 + ".en.srt")
    file = PlacedFile(Copy(video, media(480)), HARBOUR_1, (subtitle,))

    plan = plan_tidy([file], deep, day=DAY)

    assert plan.changes == ()
    assert plan.skipped == ((video, "The new name would be too long for Windows"),)


def test_a_folder_scans_never_look_into_is_never_a_place_to_file():
    hidden = EpisodeOf("System Volume Information", None, season=1, episode=1)

    plan = plan_tidy([placed(r"x\a.mkv", hidden)], LIBRARY, day=DAY)

    assert plan.changes == ()
    assert plan.skipped == ((LIBRARY / "x" / "a.mkv", "Scans never look in a folder named so"),)


def test_kept_names_go_into_the_shows_folders_as_they_are():
    files = [
        placed(r"Downloads\[GRP] The_Harbour_Line_-_01_(BD_720p).mkv", HARBOUR_1),
        placed(r"Movies\starfall ascent.mkv", ASCENT),
    ]

    changes = plan_tidy(files, LIBRARY, day=DAY, keep_names=True).changes

    assert [str(c.target) for c in changes] == [
        r"D:\Videos\Movies\Starfall - Ascent (2015)\starfall ascent.mkv",
        r"D:\Videos\TV\The Harbour Line (2019)\Season 01"
        r"\[GRP] The_Harbour_Line_-_01_(BD_720p).mkv",
    ]


def test_deleting_sets_a_video_aside_with_its_subtitles_under_names_still_free():
    video = LIBRARY / "TV" / "Quiet Hours (2015)" / "Season 01" / "Quiet Hours (2015) - S01E03.mkv"
    subtitles = (video.with_name("Quiet Hours (2015) - S01E03.en.srt"),)
    earlier = quarantine_place(video, DAY)  # one set aside earlier today has its name

    plan = plan_set_aside(
        [(video, "Quiet Hours · S01E03", subtitles)], day=DAY, taken={str(earlier)}
    )

    assert [(c.kind, c.source.name, str(c.target), c.label, c.reason) for c in plan.changes] == [
        (
            ChangeKind.QUARANTINE,
            "Quiet Hours (2015) - S01E03.mkv",
            r"D:\Maku quarantine\2026-10-10\Quiet Hours (2015) - S01E03 (2).mkv",
            "Quiet Hours · S01E03",
            DELETED,
        ),
        (
            ChangeKind.QUARANTINE,
            "Quiet Hours (2015) - S01E03.en.srt",
            r"D:\Maku quarantine\2026-10-10\Quiet Hours (2015) - S01E03 (2).en.srt",
            "Quiet Hours · S01E03 · subtitles",
            DELETED,
        ),
    ]


def test_only_a_file_in_a_days_folder_of_a_drives_quarantine_counts_as_set_aside():
    set_aside = quarantine_place(LIBRARY / "Quiet Hours - 03.mkv", DAY)

    assert in_quarantine(set_aside)
    assert in_quarantine(set_aside.with_name("Quiet Hours - 03 (2).mkv"))
    assert in_quarantine(PureWindowsPath(r"f:\maku QUARANTINE\2026-10-10\x.mkv"))
    for elsewhere in (
        r"C:\Users\Frank\Documents\thesis.docx",
        r"D:\Maku quarantine\thesis.docx",
        r"D:\Maku quarantine\not a day\x.mkv",
        r"D:\Videos\Maku quarantine\2026-10-10\x.mkv",
        r"D:\Maku quarantine\2026-10-10\..",
        r"D:\Users\..\Maku quarantine\2026-10-10\x.mkv",
    ):
        assert not in_quarantine(PureWindowsPath(elsewhere)), elsewhere
