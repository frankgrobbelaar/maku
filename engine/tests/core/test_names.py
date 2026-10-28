"""Reading file names: made-up series and films, named the ways releases, rips and people name
them."""

import subprocess
import sys
from datetime import date
from pathlib import PureWindowsPath
from typing import Any

import pytest

from maku.core import names
from maku.core.names import Kind, ParsedName, film_part, parse_name


def parsed(path: str) -> ParsedName:
    return parse_name(PureWindowsPath(path))


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            r"D:\Videos\Downloads\[Group] Glass Orchard - 001 [480p].mkv",
            {
                "title": "Glass Orchard",
                "episode": 1,
                "group": "Group",
                "height": 480,
                "folder_title": None,
            },
        ),
        (
            r"D:\Videos\Downloads\[BD] Glass_Orchard_-_01_(720p).mkv",
            {"title": "Glass Orchard", "episode": 1, "height": 720, "group": None},
        ),
        (r"D:\Videos\Downloads\Quiet Hours 01.avi", {"title": "Quiet Hours", "episode": 1}),
        (
            r"D:\Videos\Downloads\[GRP] Quiet_Hours_07 (720p).mkv",
            {"title": "Quiet Hours", "episode": 7, "group": "GRP", "height": 720},
        ),
        (r"D:\Videos\Downloads\harbour_03.mp4", {"title": "harbour", "episode": 3}),
        (
            r"D:\Videos\[Group] The Harbour Line - 01 (1080p) [ABCD1234].mkv",
            {"title": "The Harbour Line", "episode": 1, "group": "Group", "height": 1080},
        ),
        (
            r"D:\Videos\[Some-Group] Glass Orchard - 20 [1080p][Multiple Subtitle].mkv",
            {"title": "Glass Orchard", "episode": 20, "group": "Some-Group"},
        ),
        (
            r"D:\Videos\[Group]_Northern_Coast_Patrol_01_(640x480_DVD_h264)_[ABCD1234].mkv",
            {"title": "Northern Coast Patrol", "episode": 1, "height": 480},
        ),
        (
            r"D:\Videos\Glass Orchard - 01v2.mkv",
            {"title": "Glass Orchard", "episode": 1, "version": 2},
        ),
        (
            r"D:\Videos\Market Street\Market Street 112.avi",
            {"title": "Market Street", "episode": 112},
        ),
        (
            r"D:\Videos\[Group] Market Street - 64 (DVD 576p).mkv",
            {"title": "Market Street", "episode": 64, "height": 576},
        ),
    ],
)
def test_names_with_absolute_episode_numbers(path: str, expected: dict[str, Any]):
    result = parsed(path)

    assert result.kind == Kind.EPISODE
    assert {key: getattr(result, key) for key in expected} == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            r"D:\Videos\TV\The Harbour Line (2019)\Season 01"
            r"\The Harbour Line (2019) - S01E05.mkv",
            {
                "title": "The Harbour Line",
                "year": 2019,
                "season": 1,
                "episode": 5,
                "folder_season": 1,
            },
        ),
        (
            r"D:\Videos\Glass Orchard\Season 01\Glass Orchard - S01E01 - The First Frost.mkv",
            {"season": 1, "episode": 1, "episode_title": "The First Frost"},
        ),
        (
            r"D:\Videos\[Group] Quiet Hours S2 - 01 [720p].mkv",
            {"title": "Quiet Hours", "season": 2, "episode": 1},
        ),
        (
            r"D:\Videos\Market.Street.S01E131.1080p.BluRay.x264-GROUP.mkv",
            {"title": "Market Street", "season": 1, "episode": 131, "episode_title": None},
        ),
    ],
)
def test_season_and_episode_names(path: str, expected: dict[str, Any]):
    result = parsed(path)

    assert result.kind == Kind.EPISODE
    assert {key: getattr(result, key) for key in expected} == expected


def test_a_year_in_brackets_is_a_year_not_a_season():
    result = parsed(r"D:\Videos\[Group] The Harbour Line (2019) - 14 [BD 1080p Hi10 FLAC].mkv")

    assert (result.title, result.year, result.season, result.episode) == (
        "The Harbour Line",
        2019,
        None,
        14,
    )


def test_episode_titles_are_kept():
    result = parsed(r"D:\Videos\Glass Orchard\Glass Orchard - 001 - The Well.mkv")

    assert (result.title, result.episode, result.episode_title) == ("Glass Orchard", 1, "The Well")


def test_a_title_with_final_in_its_episode_title_keeps_both():
    result = parsed(r"D:\Videos\Market Street - 98 - The Final Battle.mkv")

    assert (result.title, result.episode, result.episode_title) == (
        "Market Street",
        98,
        "The Final Battle",
    )


def test_two_episodes_in_one_file():
    result = parsed(r"D:\Videos\Glass Orchard - 01-02 [720p].mkv")

    assert (result.episode, result.episode_end) == (1, 2)


def test_a_part_number_is_kept_though_anitopy_drops_it():
    # Season 3 Part 2 numbers its episodes from 1 again, so "Part 2" decides where they go.
    result = parsed(r"D:\Videos\[Group] The Harbour Line S3 Part 2 - 03 (1080p).mkv")

    assert (result.title, result.season, result.part, result.episode) == (
        "The Harbour Line",
        3,
        2,
        3,
    )
    assert parsed(r"D:\Videos\The Harbour Line S3 - 03.mkv").part is None
    assert parsed(r"D:\Videos\Glass Orchard\Glass Orchard - 05 - Part of It.mkv").part is None


@pytest.mark.parametrize(
    "name", ["Glass Orchard - Episode 05 - The Well.mkv", "Glass Orchard EP 5 - The Well.mkv"]
)
def test_words_like_episode_are_not_part_of_the_title(name: str):
    result = parsed(rf"D:\Videos\Glass Orchard\{name}")

    assert (result.title, result.episode, result.episode_title) == ("Glass Orchard", 5, "The Well")


def test_a_show_named_with_a_word_some_shows_use_for_episodes_keeps_it():
    result = parsed(r"D:\Videos\The Session\The Session - 05.mkv")

    assert (result.title, result.episode) == ("The Session", 5)


class TestFolders:
    def test_a_bare_episode_number_takes_show_year_and_season_from_its_folders(self):
        result = parsed(r"D:\Videos\TV\The Harbour Line (2019)\Season 03\05.mkv")

        assert result.title is None
        assert (result.folder_title, result.year, result.folder_season, result.episode) == (
            "The Harbour Line",
            2019,
            3,
            5,
        )
        assert result.best_title == "The Harbour Line"

    def test_absolute_numbers_keep_the_season_folder_apart(self):
        result = parsed(r"D:\Videos\Soaps\Market Street\Season 07\Market Street - 143 [720p].mkv")

        assert (result.title, result.season, result.folder_season, result.episode) == (
            "Market Street",
            None,
            7,
            143,
        )
        assert result.folder_title == "Market Street"

    def test_a_specials_folder_is_season_zero(self):
        result = parsed(r"D:\Videos\TV\Quiet Hours (2015)\Specials\Quiet Hours (2015) - S00E01.mkv")

        assert (result.season, result.folder_season, result.kind) == (0, 0, Kind.SPECIAL)

    @pytest.mark.parametrize("folder", ["Downloads", "Videos", "TV", "Extras", "New folder"])
    def test_general_folders_are_not_titles(self, folder: str):
        assert parsed(rf"D:\{folder}\01.mkv").folder_title is None

    def test_a_file_at_the_top_of_a_drive_has_no_folder_title(self):
        assert parsed(r"D:\Glass Orchard 01.mkv").folder_title is None


class TestKinds:
    def test_a_name_without_an_episode_number_is_a_movie(self):
        result = parsed(r"D:\Videos\Movies\The Lantern Keeper.avi")

        assert (result.kind, result.title, result.episode) == (
            Kind.MOVIE,
            "The Lantern Keeper",
            None,
        )

    def test_movie_in_the_name_marks_a_movie(self):
        result = parsed(r"D:\Videos\Downloads\Glass Orchard Movie.mkv")

        assert (result.kind, result.title) == (Kind.MOVIE, "Glass Orchard")

    def test_the_movie_goes_as_a_whole(self):
        result = parsed(r"D:\Videos\Movies\Glass Orchard - The Movie (2019).mkv")

        assert (result.kind, result.title, result.year) == (Kind.MOVIE, "Glass Orchard", 2019)

    def test_a_year_and_no_episode_is_a_movie(self):
        result = parsed(r"D:\Videos\[Group] Glass Orchard - The Last Harvest (2018) [1080p].mkv")

        assert (result.kind, result.title, result.year) == (
            Kind.MOVIE,
            "Glass Orchard - The Last Harvest",
            2018,
        )

    def test_a_movie_title_with_brackets_survives(self):
        result = parsed(r"D:\Videos\Signal 1.11 The Way (Not) Taken (2007).mkv")

        assert (result.kind, result.title, result.year) == (
            Kind.MOVIE,
            "Signal 1.11 The Way (Not) Taken",
            2007,
        )

    @pytest.mark.parametrize(
        "name", ["Quiet Hours Special 01.mkv", "Quiet Hours - Specials - 01.mkv"]
    )
    def test_a_special_says_so(self, name: str):
        result = parsed(rf"D:\Videos\{name}")

        assert (result.kind, result.title, result.episode) == (Kind.SPECIAL, "Quiet Hours", 1)

    @pytest.mark.parametrize(
        ("name", "title"),
        [
            ("The Special Ones Special 05.mkv", "The Special Ones"),
            ("Special Branch Special 05.mkv", "Special Branch"),
            ("Special Branch - Special 05.mkv", "Special Branch"),
            ("Special Branch SP05.mkv", "Special Branch"),
        ],
    )
    def test_a_special_of_a_show_with_the_word_in_its_name_is_a_special(
        self, name: str, title: str
    ):
        # The show's own "Special" is its name's; the one after it says what the file is.
        result = parsed(rf"D:\TV\{name}")

        assert (result.kind, result.title, result.episode) == (Kind.SPECIAL, title, 5)

    @pytest.mark.parametrize(
        ("name", "kind"),
        [
            ("Glass Orchard - Film.mkv", Kind.MOVIE),
            ("Glass Orchard - Trailer.mkv", Kind.EXTRA),
            ("Glass Orchard - Menu.mkv", Kind.EXTRA),
        ],
    )
    def test_a_kind_named_after_a_dash_at_the_end_is_the_files(self, name: str, kind: Kind):
        result = parsed(rf"D:\Videos\Glass Orchard\{name}")

        assert (result.kind, result.title) == (kind, "Glass Orchard")

    @pytest.mark.parametrize(
        ("name", "kind", "title"),
        [
            ("A Very Special Night (2015).mkv", Kind.MOVIE, "A Very Special Night"),
            ("Movie Night (2010).mkv", Kind.MOVIE, "Movie Night"),
            ("Glass Orchard Movie Night - 05.mkv", Kind.EPISODE, "Glass Orchard Movie Night"),
            (
                "Glass Orchard Special Edition - 05.mkv",
                Kind.EPISODE,
                "Glass Orchard Special Edition",
            ),
        ],
    )
    def test_a_word_for_a_kind_inside_a_title_is_the_titles_own(
        self, name: str, kind: Kind, title: str
    ):
        result = parsed(rf"D:\Videos\{name}")

        assert (result.kind, result.title) == (kind, title)

    @pytest.mark.parametrize(
        ("name", "title"),
        [
            ("A Harbour Ending (2019).mkv", "A Harbour Ending"),
            ("The Ending (2019).mkv", "The Ending"),
            ("Opening Night Blues (2007).mkv", "Opening Night Blues"),
            ("Must See TV (2010).mkv", "Must See TV"),
        ],
    )
    def test_words_anitopy_reads_as_other_kinds_of_video_are_part_of_the_name(
        self, name: str, title: str
    ):
        # anitopy takes "Ending", "Opening" and "TV" for kinds of video of its own; here they're
        # a film's words.
        result = parsed(rf"D:\Videos\Movies\{name}")

        assert (result.kind, result.title) == (Kind.MOVIE, title)

    def test_a_creditless_ending_is_an_extra(self):
        result = parsed(r"D:\Videos\[Group] Glass Orchard - Creditless Ending [1080p].mkv")

        assert result.kind is Kind.EXTRA

    def test_dvd_files_are_recognised(self):
        result = parsed(r"D:\Videos\Old DVDs\VTS_02_1.VOB")

        assert (result.kind, result.title, result.episode) == (Kind.DVD, None, None)


class TestExtras:
    """Extras as media server apps file them: in a folder of their own, beside a film or in a
    season's folder, or named with their kind after a dash. They're never looked up."""

    @pytest.mark.parametrize(
        "path",
        [
            r"D:\Videos\Movies\Starfall (2008)\Extras\Trailer.mkv",
            r"D:\Videos\Movies\Starfall (2008)\Extras\Trailer 1.mkv",
            r"D:\Videos\Movies\Starfall (2008)\Featurettes\Behind the Scenes.mkv",
            r"D:\Videos\Movies\Starfall (2008)\Behind The Scenes\Building the Ship.mkv",
            r"D:\Videos\Movies\Starfall (2008)\Deleted Scenes\The Lost Farewell.mkv",
            r"D:\Videos\Movies\Starfall (2008)\Interviews\The Director.mkv",
            r"D:\Videos\Movies\Starfall (2008)\Scenes\The Launch.mkv",
            r"D:\Videos\Movies\Starfall (2008)\Shorts\Starfall Zero.mkv",
            r"D:\Videos\Movies\Starfall (2008)\TRAILERS\Teaser 2.mkv",
            r"D:\Videos\Movies\Starfall (2008)\other\Premiere Night.mkv",
            r"D:\Videos\TV\Glass Orchard (2012)\Season 01\Extras\Glass Orchard - S01E01.mkv",
            r"D:\Videos\TV\Glass Orchard (2012)\Season 01\Other\Bloopers.mkv",
            r"D:\Videos\TV\Glass Orchard (2012)\Other\Bloopers.mkv",
            r"D:\Videos\TV\Glass Orchard (2012)\Featurettes\Glass Orchard - 01.mkv",
            r"D:\Videos\Extras\Starfall Premiere.mkv",
        ],
    )
    def test_a_video_in_a_folder_of_extras_is_an_extra(self, path: str):
        assert parsed(path).kind is Kind.EXTRA

    @pytest.mark.parametrize(
        "name",
        [
            "Starfall (2008)-trailer.mkv",
            "Starfall (2008)-Trailer (2).mkv",
            "Starfall (2008)-featurette.mkv",
            "Building the Ship-behindthescenes.mkv",
            "The Lost Farewell-deleted.mkv",
            "The Director-interview.mkv",
            "The Launch-scene.mkv",
            "Starfall Zero-short.mkv",
            "Premiere Night-other.mkv",
        ],
    )
    def test_a_video_named_with_its_kind_of_extra_is_an_extra(self, name: str):
        assert parsed(rf"D:\Videos\Movies\Starfall (2008)\{name}").kind is Kind.EXTRA

    @pytest.mark.parametrize(
        "path",
        [
            r"D:\Videos\Other\Northern Lights (2004).mkv",
            r"D:\Videos\Movies\Shorts\Paper Kites (1999).mkv",
            r"D:\Scenes\The Lantern Keeper (2016).mkv",
            r"D:\Videos\Movies\Trailer Park Nights (2009).mkv",
            r"D:\Videos\Movies\A Short Goodbye (2010).mkv",
            # A library's own folders, by kind of film, keep films in such folders too.
            r"D:\Media\Animation\Shorts\Paper Kites (1999).mkv",
            r"D:\Videos\Drama\Other\Northern Lights (2004).mkv",
            r"D:\Videos\Nature\Scenes\The Lantern Keeper (2016).mkv",
        ],
    )
    def test_a_film_in_a_librarys_own_folder_of_such_a_name_is_a_film(self, path: str):
        # "Other", "Shorts" and "Scenes" hold extras only inside a title's own folder (one with
        # its year, or a season's), and a word for an extra is one only at the end of a name,
        # after a dash.
        assert parsed(path).kind is Kind.MOVIE

    @pytest.mark.parametrize(
        "path",
        [r"D:\Media\Animation\Shorts\05.mkv", r"D:\Videos\Scenes\05.mkv"],
    )
    def test_a_librarys_folder_of_such_a_name_names_no_title(self, path: str):
        assert parsed(path).folder_title is None


class TestNumberedFilmsAndSpecials:
    """A whole series' release numbers its films and specials: "The Harbour Line - Movie 01 -
    Fog Bound". The number counts the release's films, so a film goes by its own name."""

    FOLDER = r"D:\Videos\THE HARBOUR LINE (2019-2026) - The COMPLETE Series\2a. Movies (2020-2025)"

    @pytest.mark.parametrize(
        ("name", "title", "year"),
        [
            (
                "The Harbour Line - Movie 01 - Fog Bound (2020 BluRay - 1080p TRI AUDIO).mkv",
                "The Harbour Line: Fog Bound",
                2020,
            ),
            (
                "The Harbour Line - Movie 02 - Storm, The Night Crossing (2021 BluRay - 1080p TRI"
                " AUDIO).mkv",
                "The Harbour Line: Storm, The Night Crossing",
                2021,
            ),
            (
                "The Harbour Line - Movie 03b - High Water, UNCut (2022 BluRay - 1080p DUAL"
                " AUDIO).mkv",
                "The Harbour Line: High Water",
                2022,
            ),
            (
                "The Harbour Line - Movie 04a (Theatrical Cut) - Return 'H' aka Homecoming (2023"
                " BluRay - 1080p DUAL AUDIO).mkv",
                "The Harbour Line: Return 'H'",
                2023,
            ),
            (
                "The Harbour Line - Movie 04b (Captain's Special Edition) - Return 'H' (2024"
                " WebRip - 1080p ENG Audio).mp4",
                "The Harbour Line: Return 'H'",
                2024,
            ),
            (
                "The Harbour Line - Movie 05 - HL Northbound, Northwind Version (2025 BluRay -"
                " 1080p DUAL Audio).mkv",
                "The Harbour Line: HL Northbound, Northwind Version",
                2025,
            ),
        ],
    )
    def test_a_numbered_film_goes_by_its_own_name(self, name: str, title: str, year: int):
        result = parsed(rf"{self.FOLDER}\{name}")

        assert (result.kind, result.title, result.series, result.year) == (
            Kind.MOVIE,
            title,
            "The Harbour Line",
            year,
        )
        assert (result.episode, result.episode_title) == (None, None)

    def test_a_film_with_no_number_has_no_series_of_its_own(self):
        result = parsed(r"D:\Videos\Movies\Glass Orchard - The Movie (2019).mkv")

        assert (result.title, result.series) == ("Glass Orchard", None)

    def test_a_numbered_special_keeps_its_series_and_its_own_name(self):
        result = parsed(
            r"D:\Videos\THE HARBOUR LINE\3. TV Specials (2019-2025)\The Harbour Line - Special 02"
            r" - A Harbour Christmas (2021 BluRay - 1080p TRI Audio).mkv"
        )

        assert (result.kind, result.title, result.episode_title, result.year) == (
            Kind.SPECIAL,
            "The Harbour Line",
            "A Harbour Christmas",
            2021,
        )

    def test_a_year_in_brackets_with_other_words_is_the_year(self):
        result = parsed(r"D:\Videos\Northern Lights (2004 BluRay - 1080p).mkv")

        assert (result.title, result.year) == ("Northern Lights", 2004)

    def test_a_span_of_years_is_no_year(self):
        assert parsed(r"D:\Videos\Northern Lights (2004-2019 BluRay).mkv").year is None


class TestNamesThatNeedAMatch:
    def test_a_group_and_an_episode_but_no_title(self):
        result = parsed(r"D:\Videos\Downloads\[subs] ep03 final.mkv")

        assert (result.title, result.episode, result.group, result.best_title) == (
            None,
            3,
            "subs",
            None,
        )

    def test_a_movie_named_movie(self):
        result = parsed(r"D:\Videos\Misc\movie_final_v2.mp4")

        assert (result.kind, result.title, result.version) == (Kind.MOVIE, None, 2)

    @pytest.mark.parametrize("name", ["Ep.mkv", "Episode.mkv", "Vol.mkv"])
    def test_a_name_anitopy_trips_over_still_has_its_folders(self, name: str):
        result = parsed(rf"D:\Videos\Glass Orchard\{name}")

        assert (result.folder_title, result.episode) == ("Glass Orchard", None)


class TestCopies:
    @pytest.mark.parametrize(
        "name",
        [
            "Market Street 042 (copy).mkv",
            "Market Street 042 - Copy.mkv",
            "Market Street 042 - Copy (2).mkv",
            "Market Street 042 (2).mkv",
        ],
    )
    def test_copies_are_marked_and_still_read(self, name: str):
        result = parsed(rf"D:\Videos\Market Street\{name}")

        assert (result.title, result.episode, result.is_copy, result.group) == (
            "Market Street",
            42,
            True,
            None,
        )

    def test_makus_own_keep_both_names_are_copies(self):
        result = parsed(
            r"D:\TV\The Harbour Line (2019)\Season 01\The Harbour Line (2019) - S01E05 (2).mkv"
        )

        assert (result.is_copy, result.season, result.episode) == (True, 1, 5)

    def test_an_ordinary_name_is_not_a_copy(self):
        assert parsed(r"D:\Videos\Quiet Hours 01.avi").is_copy is False


def test_parsing_from_many_threads_at_once_gives_the_same_answers():
    from concurrent.futures import ThreadPoolExecutor

    paths = [
        r"D:\Videos\[Group] Glass Orchard - 001 [480p].mkv",
        r"D:\Videos\[Group] Market Street (2011) - 148 [BD 1080p Hi10 FLAC].mkv",
    ] * 200
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(parsed, paths))

    assert {(r.title, r.episode) for r in results} == {("Glass Orchard", 1), ("Market Street", 148)}


@pytest.mark.parametrize(
    ("name", "part"),
    [
        ("Northern Lights (2004) CD1", 1),
        ("Northern.Lights.2004.cd2", 2),
        ("Northern Lights (2004) - pt1", 1),
        ("Northern Lights (2004) - Part 2", 2),
        ("Northern Lights (2004) - disc 2", 2),
        ("Northern Lights (2004) CD1 (copy)", 1),
        ("Northern Lights (2004)", None),
        ("Orbit Station 0083", None),
    ],
)
def test_a_films_part_is_read_from_the_end_of_its_name(name: str, part: int | None):
    assert film_part(name) == part


@pytest.mark.parametrize(
    "name", ["Northern Lights (2004).cd2.avi", "Northern Lights (2004) - disc 2.mkv"]
)
def test_a_films_part_isnt_part_of_its_title(name: str):
    result = parsed(rf"D:\Videos\Movies\{name}")

    assert (result.kind, result.title, result.year, result.episode) == (
        Kind.MOVIE,
        "Northern Lights",
        2004,
        None,
    )


PACK = (
    r"F:\Videos\[Group] La Ligne du Port (The Harbour Line) (S01-S03+Movies+Specials) [BD]"
    r" [Dual Audio][1080p][HEVC 10bit x265][AAC][Eng Sub]"
)


class TestReleasePacks:
    """A whole show in one release: its seasons in folders named after it, its films and
    specials numbered and named after the show, its creditless openings beside them."""

    def test_a_season_folder_named_after_its_show_gives_the_season_and_the_show(self):
        season = r"[Group] The Harbour Line Season 02"
        result = parsed(rf"{PACK}\{season}\[Group] The Harbour Line - 14.mkv")

        assert (result.title, result.folder_title, result.folder_season, result.episode) == (
            "The Harbour Line",
            "The Harbour Line",
            2,
            14,
        )

    @pytest.mark.parametrize(
        ("folder", "season"),
        [
            ("Glass Orchard Season 3", 3),
            ("Quiet Hours 2nd Season", 2),
            ("Market Street S2", 2),
            ("Market Street - Season 02 [BD 1080p]", 2),
        ],
    )
    def test_season_folders_name_their_show_in_many_ways(self, folder: str, season: int):
        result = parsed(rf"D:\Videos\{folder}\01.mkv")

        assert (result.folder_season, result.episode) == (season, 1)
        assert result.folder_title is not None
        assert "season" not in result.folder_title.casefold()

    def test_a_release_packs_folder_is_read_for_the_shows_names(self):
        result = parsed(rf"{PACK}\01.mkv")

        assert result.folder_title == "La Ligne du Port (The Harbour Line)"

    @pytest.mark.parametrize(
        ("folder", "title"),
        [
            ("Glass Orchard [Winter Harvest]", "Glass Orchard [Winter Harvest]"),
            ("[Quiet Hours]", "Quiet Hours"),
            ("Glass Orchard (Complete Series) [BD 1080p] [Dual Audio]", "Glass Orchard"),
            ("[Group]_Glass_Orchard_[1080p]", "Glass Orchard"),
        ],
    )
    def test_a_folders_brackets_go_only_when_they_hold_a_releases_words(
        self, folder: str, title: str
    ):
        assert parsed(rf"D:\Videos\{folder}\01.mkv").folder_title == title

    def test_a_folders_own_marks_stay(self):
        # A name's own marks, as the show writes them.
        show = "Signal -Lost Before Dawn- (2016)"
        result = parsed(rf"D:\Videos\TV\{show}\Season 02\{show} - S02E01.mkv")

        assert (result.folder_title, result.year) == ("Signal -Lost Before Dawn-", 2016)

    @pytest.mark.parametrize(
        "folder",
        [
            "Glass Orchard (Season 2)",
            "Glass Orchard [S2]",
            "Glass Orchard (2nd Season)",
            r"Glass Orchard\(Season 2)",
            r"Glass Orchard\Season 2 [1080p]",
        ],
    )
    def test_a_season_in_a_folders_brackets_is_its_season(self, folder: str):
        result = parsed(rf"D:\Videos\{folder}\01.mkv")

        assert (result.folder_title, result.folder_season) == ("Glass Orchard", 2)

    def test_a_folder_of_a_shows_seasons_gives_no_season(self):
        result = parsed(r"D:\Videos\Glass Orchard S01-S02\Glass Orchard - 05.mkv")

        assert (result.folder_title, result.folder_season) == ("Glass Orchard", None)

    @pytest.mark.parametrize(
        ("name", "title"),
        [
            ("[Group] The Harbour Line Movie 01 - Fog Bound.mkv", "Fog Bound"),
            (
                "[Group] The Harbour Line Movie 03 - Return to the Harbour.mkv",
                "Return to the Harbour",
            ),
            ("[Group] The Harbour Line Movie 04 - Captain's Log.mkv", "Captain's Log"),
        ],
    )
    def test_a_numbered_film_without_a_dash_before_movie(self, name: str, title: str):
        result = parsed(rf"{PACK}\[Group] The Harbour Line Movies\{name}")

        assert (result.kind, result.title, result.series) == (
            Kind.MOVIE,
            f"The Harbour Line: {title}",
            "The Harbour Line",
        )
        # The release's folder names the show, above its films' own.
        assert result.folder_title == "La Ligne du Port (The Harbour Line)"

    @pytest.mark.parametrize(
        ("folder", "title", "kind"),
        [
            (r"D:\Videos\Glass Orchard\Glass Orchard Specials", "Glass Orchard", Kind.SPECIAL),
            (r"D:\Videos\Quiet Hours Specials", "Quiet Hours", Kind.SPECIAL),
            (r"D:\Videos\Show (2019) - Specials", "Show", Kind.SPECIAL),
            (r"D:\Videos\TV Specials", None, Kind.SPECIAL),
            (
                r"D:\Videos\The Harbour Line (2019)\3. TV Specials (2019-2025)",
                "The Harbour Line",
                Kind.SPECIAL,
            ),
            # Which of a show's films a bare number is, nothing says: it waits for the owner.
            (r"D:\Videos\Glass Orchard\Glass Orchard Movies", None, Kind.MOVIE),
            (r"D:\Videos\TV Movies", None, Kind.MOVIE),
        ],
    )
    def test_a_folder_of_films_or_specials_says_what_a_bare_number_in_it_is(
        self, folder: str, title: str | None, kind: Kind
    ):
        # The show is the folder above's, or the folder's own first words when there's none
        # (but not "TV" of "TV Specials"). A release counts its films and specials its own way,
        # so the folder is no season 0.
        result = parsed(rf"{folder}\05.mkv")

        assert (result.kind, result.best_title, result.folder_season) == (kind, title, None)

    def test_a_folder_of_specials_leaves_a_named_file_as_it_is(self):
        result = parsed(r"D:\Videos\Glass Orchard\Glass Orchard Specials\Glass Orchard - 05.mkv")

        assert (result.kind, result.title, result.episode) == (Kind.EPISODE, "Glass Orchard", 5)

    @pytest.mark.parametrize(
        "folder",
        [
            "[Group] Glass Orchard + Specials [BD][Dual Audio][1080p]",
            "Lamplighters! & Specials",
            "Glass Orchard and Specials",
            "Market Street with Movies",
        ],
    )
    def test_a_folder_of_a_show_and_its_specials_holds_its_episodes(self, folder: str):
        result = parsed(rf"D:\Videos\{folder}\05.mkv")

        assert (result.kind, result.episode) == (Kind.EPISODE, 5)

    @pytest.mark.parametrize(
        ("folder", "title"),
        [
            ("Q S2", "Q"),  # a show's name can be one letter
            ("Tide Specials", "Tide"),
            ("The Specials", None),
            ("2a. Movies (2020-2025)", None),
        ],
    )
    def test_a_folders_first_words_name_a_show_unless_they_cant(self, folder: str, title: str):
        assert parsed(rf"D:\Videos\{folder}\05.mkv").folder_title == title

    def test_a_folder_of_specials_doesnt_change_a_name_that_says_what_it_is(self):
        result = parsed(
            r"D:\Videos\Glass Orchard\Glass Orchard Specials\Glass Orchard - The Movie.mkv"
        )

        assert result.kind is Kind.MOVIE

    @pytest.mark.parametrize(
        ("name", "title", "series"),
        [
            (
                "Glass Orchard: The Movie - Winter Harvest.mkv",
                "Glass Orchard: Winter Harvest",
                "Glass Orchard",
            ),
            ("The Movie - Winter Harvest.mkv", "The Movie - Winter Harvest", None),
        ],
    )
    def test_a_films_series_is_a_name(self, name: str, title: str, series: str | None):
        result = parsed(rf"D:\Videos\Glass Orchard\{name}")

        assert (result.kind, result.title, result.series) == (Kind.MOVIE, title, series)

    def test_a_film_named_after_its_series_without_a_number(self):
        result = parsed(r"D:\Videos\Glass Orchard Movie - Winter Harvest.mkv")

        assert (result.kind, result.title, result.series) == (
            Kind.MOVIE,
            "Glass Orchard: Winter Harvest",
            "Glass Orchard",
        )

    @pytest.mark.parametrize(
        ("name", "own"),
        [
            (
                "[Group] The Harbour Line Special - A Harbour Christmas.mkv",
                "A Harbour Christmas",
            ),
            (
                "[Group] The Harbour Line Special - Rescue! Rescue at Sea!.mkv",
                "Rescue! Rescue at Sea!",
            ),
            (
                "[Group] The Harbour Line Special - Make It! Do-or-Die Crossing, Part 1.mkv",
                "Make It! Do-or-Die Crossing, Part 1",
            ),
            (
                "[Group] The Harbour Line Special - HLB (Harbour League Baseball).mkv",
                "HLB (Harbour League Baseball)",
            ),
        ],
    )
    def test_a_named_special_is_its_shows_special_by_its_own_name(self, name: str, own: str):
        result = parsed(rf"{PACK}\[Group] The Harbour Line Specials\{name}")

        assert (result.kind, result.title, result.episode, result.episode_title) == (
            Kind.SPECIAL,
            "The Harbour Line",
            None,
            own,
        )
        # A release counts its specials its own way: their folder is no season 0.
        assert result.folder_season is None

    @pytest.mark.parametrize(
        ("name", "title", "number", "own"),
        [
            (
                "Quiet Hours Special - The Night Train - 02.mkv",
                "Quiet Hours",
                2,
                "The Night Train",
            ),
            (
                "[Group] Glass Orchard Special: Harvest XX - 02.mkv",
                "Glass Orchard",
                2,
                "Harvest XX",
            ),
        ],
    )
    def test_a_named_specials_episodes_keep_their_numbers(
        self, name: str, title: str, number: int, own: str
    ):
        result = parsed(rf"D:\Videos\{name}")

        assert (result.kind, result.title, result.episode, result.episode_title) == (
            Kind.SPECIAL,
            title,
            number,
            own,
        )

    @pytest.mark.parametrize(
        "name", ["Quiet Hours - Christmas Special.mkv", "Quiet.Hours.Christmas.Special.mkv"]
    )
    def test_a_special_named_after_its_show_with_the_word_last(self, name: str):
        result = parsed(rf"D:\TV\Quiet Hours\{name}")

        assert (result.kind, result.title, result.episode, result.episode_title) == (
            Kind.SPECIAL,
            "Quiet Hours",
            None,
            "Christmas Special",
        )

    @pytest.mark.parametrize(
        "name",
        [
            "The Harbour Line - Creditless Opening.mkv",
            "Glass Orchard - Non-Credit Opening.mkv",
            "Quiet Hours S2 - Creditless Ending 1.mkv",
            "[Group] Market Street - Noncredited Closing Titles [1080p].mkv",
        ],
    )
    def test_creditless_openings_and_endings_are_extras_however_named(self, name: str):
        assert parsed(rf"{PACK}\{name}").kind is Kind.EXTRA

    def test_an_episode_whose_title_has_credit_in_it_is_an_episode(self):
        result = parsed(r"D:\Videos\Show\Show - 01 - A Noncreditable Story.mkv")

        assert (result.kind, result.episode) == (Kind.EPISODE, 1)


class TestJapaneseNames:
    """Names in Japanese, as Japanese releases and recordings write them: 第01話 is episode 1,
    第2期 season 2; full-width letters and digits read as plain ones. Chinese names' 第01集 and
    第01话 are episodes too."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("港の灯 第01話.mkv", {"title": "港の灯", "episode": 1}),
            ("港の灯 第１話.mkv", {"title": "港の灯", "episode": 1}),
            (
                "硝子の果樹園 第01話 冬の始まり.mkv",
                {"title": "硝子の果樹園", "episode": 1, "episode_title": "冬の始まり"},
            ),
            ("港の灯 第2期 第05話.mkv", {"title": "港の灯", "season": 2, "episode": 5}),
            ("静かな時間 第二期 第三話.mkv", {"title": "静かな時間", "season": 2, "episode": 3}),
            (
                "[Group] 硝子の果樹園 #14 (1080p).mkv",
                {"title": "硝子の果樹園", "episode": 14},
            ),
            (
                f"Port{chr(0xFF1A)}港の灯 - 01.mkv",  # a full-width colon
                {"title": "Port:港の灯", "episode": 1},
            ),
            ("港口之光 第01集.mp4", {"title": "港口之光", "episode": 1}),
            ("玻璃果园 第01话.mkv", {"title": "玻璃果园", "episode": 1}),
        ],
    )
    def test_japanese_episode_and_season_markers(self, name: str, expected: dict[str, Any]):
        result = parsed(rf"D:\Videos\{name}")

        assert result.kind is Kind.EPISODE
        assert {key: getattr(result, key) for key in expected} == expected

    def test_a_recap_is_a_special(self):
        result = parsed(r"D:\Videos\港の灯 総集編.mkv")

        assert (result.kind, result.title) == (Kind.SPECIAL, "港の灯")

    def test_a_name_that_starts_with_a_groups_brackets_and_its_marks_too(self):
        result = parsed(r"D:\Videos\硝子の果樹園\【Group】 第01話 冬の始まり.mkv")

        assert (result.kind, result.best_title, result.episode) == (
            Kind.EPISODE,
            "硝子の果樹園",
            1,
        )

    @pytest.mark.parametrize(
        ("name", "season", "episode"),
        [("第01話 冬の始まり.mkv", None, 1), ("第2期 第05話 冬の始まり.mkv", 2, 5)],
    )
    def test_a_name_that_starts_with_its_marks_takes_its_show_from_the_folder(
        self, name: str, season: int | None, episode: int
    ):
        # What follows the episode's mark is its own title, not the show's.
        result = parsed(rf"D:\Videos\硝子の果樹園\{name}")

        assert (result.kind, result.best_title, result.season, result.episode) == (
            Kind.EPISODE,
            "硝子の果樹園",
            season,
            episode,
        )

    @pytest.mark.parametrize(
        "name", ["[Group] 【港の灯】 - 01 [1080p].mkv", "【港の灯】 第01話.mkv"]
    )
    def test_a_title_in_lenticular_brackets_is_the_title(self, name: str):
        # anitopy reads 【】 as a group's brackets; 【港の灯】 is the show's own name.
        result = parsed(rf"D:\Videos\{name}")

        assert (result.kind, result.title, result.episode) == (Kind.EPISODE, "港の灯", 1)

    def test_lenticular_brackets_beside_a_shows_folder_are_a_groups(self):
        result = parsed(r"D:\Videos\Minato no Akari\【GRP】 - 01.mkv")

        assert (result.best_title, result.episode) == ("Minato no Akari", 1)


class TestOddNames:
    def test_a_film_named_as_its_own_folder_keeps_its_number(self):
        result = parsed(r"D:\Videos\Movies\Paper Kites 2 (2003)\Paper Kites 2 (2003).mkv")

        assert (result.kind, result.title, result.year, result.episode) == (
            Kind.MOVIE,
            "Paper Kites 2",
            2003,
            None,
        )

    def test_a_film_in_a_folder_of_its_own_keeps_what_its_name_says_of_the_release(self):
        film = "Northern Lights (2004) [1080p]"
        result = parsed(rf"D:\Videos\Movies\{film}\{film}.mkv")

        assert (result.kind, result.title, result.year, result.height) == (
            Kind.MOVIE,
            "Northern Lights",
            2004,
            1080,
        )

    def test_a_numbered_film_in_a_folder_of_its_own_is_found_by_its_own_name(self):
        film = "The Harbour Line - Movie 01 - Fog Bound (2020)"
        result = parsed(rf"D:\Videos\Movies\{film}\{film}.mkv")

        assert (result.kind, result.title, result.series, result.year) == (
            Kind.MOVIE,
            "The Harbour Line: Fog Bound",
            "The Harbour Line",
            2020,
        )

    def test_a_circled_number_is_no_number(self):
        # It's a digit to Python, but not one int() reads.
        assert parsed(r"D:\Videos\Show\Show - ①.mkv").episode is None

    def test_only_full_width_letters_and_digits_are_read_as_plain(self):
        # "½" stays as it is, as the show's name has it: Apartment 3½.
        assert parsed(r"D:\Videos\Apartment 3½\Apartment 3½ - 01.mkv").title == "Apartment 3½"

    def test_a_title_ending_in_end_keeps_it(self):
        # anitopy reads "End" as a release's word, as in "- 12 END".
        result = parsed(r"D:\Videos\Tides of the End\Tides of the End - 01.mkv")

        assert (result.title, result.episode) == ("Tides of the End", 1)

    def test_scene_dots_dont_stay_in_the_title_nor_release_words_in_the_episodes(self):
        result = parsed(r"D:\Videos\Salt x Pepper\Salt.x.Pepper.S01E01.1080p.WEB.h264-GRP.mkv")

        assert (result.title, result.season, result.episode, result.episode_title) == (
            "Salt x Pepper",
            1,
            1,
            None,
        )


class TestSceneNames:
    """Series and films as releases name them: the title ends where the episode code, the year or
    the release's own words begin."""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            (
                r"D:\Videos\TV\The.Harbour.Line.S01E02.1080p.WEB-DL.DDP5.1.H.264-GROUP.mkv",
                {"title": "The Harbour Line", "season": 1, "episode": 2, "episode_title": None},
            ),
            (
                r"D:\Videos\TV\glass.orchard.s01e05e06.1080p.bluray.x265-grp.mkv",
                {"title": "glass orchard", "season": 1, "episode": 5, "episode_end": 6},
            ),
            (
                r"D:\Videos\TV\Glass Orchard - S01E05-E06 - Two Wells.mkv",
                {"episode": 5, "episode_end": 6, "episode_title": "Two Wells"},
            ),
            (
                r"D:\Videos\TV\Show.Name.2019.S01E01.720p.HDTV.x264-GRP.mkv",
                {"title": "Show Name", "year": 2019, "season": 1, "episode": 1},
            ),
            (
                r"D:\Videos\TV\Harbour Line S03E08 Finale.mkv",
                {"title": "Harbour Line", "episode": 8, "episode_title": "Finale"},
            ),
            (
                r"D:\Videos\Movies\Starfall.2008.1080p.BluRay.x264-GROUP.mkv",
                {"kind": Kind.MOVIE, "title": "Starfall", "year": 2008, "height": 1080},
            ),
            (
                r"D:\Videos\Movies\Starfall.Ascent.2015.2160p.UHD.BluRay.REMUX.HDR.HEVC.Atmos-GRP.mkv",
                {"kind": Kind.MOVIE, "title": "Starfall Ascent", "year": 2015, "height": 2160},
            ),
            (
                r"D:\Videos\Movies\Starfall.2008.EXTENDED.1080p.BluRay.x264.mkv",
                {"kind": Kind.MOVIE, "title": "Starfall", "year": 2008},
            ),
            (
                r"D:\Videos\Movies\Starfall (2008) Director's Cut.mkv",
                {"kind": Kind.MOVIE, "title": "Starfall", "year": 2008},
            ),
            (
                r"D:\Videos\Burnt\Northern Lights 2004.mkv",
                {"kind": Kind.MOVIE, "title": "Northern Lights", "year": 2004},
            ),
            (  # a year followed by another is the title's
                r"D:\Videos\Movies\1958.2021.1080p.mkv",
                {"kind": Kind.MOVIE, "title": "1958", "year": 2021},
            ),
            (
                r"D:\Videos\Movies\Iron.Harbour.2049.2017.1080p.mkv",
                {"kind": Kind.MOVIE, "title": "Iron Harbour 2049", "year": 2017},
            ),
            (  # the release's folder, its words gone
                r"D:\Videos\Movies\Paper Kites 1999 DVDRip XviD-GROUP\paper.kites.1999.dvdrip.avi",
                {"kind": Kind.MOVIE, "title": "paper kites", "folder_title": "Paper Kites"},
            ),
            (
                r"D:\Videos\TV\Quiet.Hours.S02.1080p.BluRay.x264-GROUP\Quiet.Hours.S02E10.mkv",
                {"title": "Quiet Hours", "folder_title": "Quiet Hours", "folder_season": 2},
            ),
            (  # a title that's a word a release uses, before its year
                r"D:\Videos\Movies\The Web of Lies (2006).mkv",
                {"kind": Kind.MOVIE, "title": "The Web of Lies", "year": 2006},
            ),
        ],
    )
    def test_a_scene_names_parts(self, path: str, expected: dict[str, Any]):
        result = parsed(path)

        assert {key: getattr(result, key) for key in expected} == expected

    @pytest.mark.parametrize(
        "path",
        [
            r"D:\Videos\Movies\Starfall 2008 sample.mkv",
            r"D:\Videos\Movies\starfall.2008.1080p-sample.mkv",
            r"D:\Videos\Movies\Starfall (2008)\Sample\starfall.mkv",
        ],
    )
    def test_a_releases_sample_is_an_extra(self, path: str):
        assert parsed(path).kind is Kind.EXTRA


class TestDiscs:
    """A disc's own files, as a burnt DVD or a Blu-ray copied whole keeps them: the disc's folder
    names it."""

    @pytest.mark.parametrize(
        ("path", "title", "year"),
        [
            (r"D:\Videos\Burnt\NORTHERN_LIGHTS\VIDEO_TS\VTS_01_1.VOB", "NORTHERN LIGHTS", None),
            (
                r"D:\Videos\Burnt\NORTHERN_LIGHTS_DISC1\VIDEO_TS\VTS_02_3.VOB",
                "NORTHERN LIGHTS",
                None,
            ),
            (r"D:\Videos\Movies\Starfall (2008)\BDMV\STREAM\00000.m2ts", "Starfall", 2008),
            (r"D:\Videos\Starfall (2008)\VTS_01_1.VOB", "Starfall", 2008),
        ],
    )
    def test_a_discs_folder_names_it(self, path: str, title: str, year: int | None):
        result = parsed(path)

        assert (result.kind, result.folder_title, result.year) == (Kind.DVD, title, year)

    def test_a_library_folder_names_no_disc(self):
        assert parsed(r"D:\Videos\DVDs\VIDEO_TS\VTS_01_1.VOB").best_title is None

    def test_a_stream_file_outside_a_blu_rays_folders_is_a_video(self):
        assert parsed(r"D:\Videos\Starfall (2008)\00000.m2ts").kind is not Kind.DVD


def test_a_name_with_only_a_mark_after_its_episode_is_read_without_hanging():
    # anitopy's own search for an episode's title went round forever on these, holding the
    # lock every other name waits on. Read in a child, so a hang fails here and never holds up
    # the rest of the run.
    paths = [
        r"D:\TV\Glass Orchard\Glass Orchard - 01 - .x.mkv",
        r"D:\TV\Glass Orchard\Glass Orchard - S01E01 - .x.mkv",
        r"D:\TV\Glass Orchard\Glass Orchard - 1x01 - .x.mkv",
        r"D:\TV\Glass Orchard\Glass Orchard - 01 - .2.mkv",
        r"D:\TV\Glass Orchard\Glass Orchard 01 - .x.x.mkv",
    ]
    code = (
        "import sys\n"
        "from pathlib import PureWindowsPath\n"
        "from maku.core.names import parse_name\n"
        "for path in sys.argv[1:]:\n"
        "    found = parse_name(PureWindowsPath(path))\n"
        "    print(found.title, found.episode)\n"
    )

    done = subprocess.run(
        [sys.executable, "-c", code, *paths],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )

    assert done.stdout.splitlines() == ["Glass Orchard 1"] * len(paths)


class TestEpisodeCodes:
    """An episode code ("S01E05", "1x05") says which episode a file is, and that it's an
    episode: the words after it are the episode's own title, whatever they say."""

    @pytest.mark.parametrize(
        ("name", "episode", "own"),
        [
            ("S01E01 - Pilot.mkv", 1, "Pilot"),
            ("s01e05.720p.hdtv.x264-grp.mkv", 5, None),
            ("1x04 - Low Tide.mkv", 4, "Low Tide"),
        ],
    )
    def test_a_code_alone_takes_its_show_from_its_folders(
        self, name: str, episode: int, own: str | None
    ):
        result = parsed(rf"D:\TV\The Harbour Line (2019)\Season 01\{name}")

        assert (result.kind, result.title, result.best_title, result.year) == (
            Kind.EPISODE,
            None,
            "The Harbour Line",
            2019,
        )
        assert (result.season, result.episode, result.episode_title) == (1, episode, own)

    @pytest.mark.parametrize("own", ["Special", "Movie", "The Movie", "Preview", "Trailer", "Menu"])
    def test_the_code_decides_the_kind_not_the_episodes_own_title(self, own: str):
        show = r"D:\TV\Glass Orchard (2012)\Season 02"
        result = parsed(rf"{show}\Glass Orchard (2012) - S02E07 - {own}.mkv")

        assert (result.kind, result.title, result.season, result.episode) == (
            Kind.EPISODE,
            "Glass Orchard",
            2,
            7,
        )
        assert result.episode_title == own

    def test_a_code_in_season_0_is_a_special_whatever_its_title(self):
        show = r"D:\TV\Glass Orchard (2012)\Specials"
        result = parsed(rf"{show}\Glass Orchard (2012) - S00E03 - Movie.mkv")

        assert (result.kind, result.season, result.episode) == (Kind.SPECIAL, 0, 3)

    @pytest.mark.parametrize(
        ("name", "own"),
        [
            ("Glass.Orchard.S01E05.S01E06.720p.HDTV.x264-GRP.mkv", None),
            ("Glass Orchard - S01E05-S01E06 - Two Wells.mkv", "Two Wells"),
            ("Glass Orchard - 1x05-06 - Two Wells.mkv", "Two Wells"),
            ("Glass Orchard - 1x05-1x06 - Two Wells.mkv", "Two Wells"),
        ],
    )
    def test_two_episodes_written_as_two_codes_or_a_range(self, name: str, own: str | None):
        result = parsed(rf"D:\TV\{name}")

        assert (result.title, result.season, result.episode, result.episode_end) == (
            "Glass Orchard",
            1,
            5,
            6,
        )
        assert result.episode_title == own

    def test_a_season_folder_numbered_by_its_year(self):
        # Daily shows' seasons go by their years.
        result = parsed(r"D:\TV\The Harbour Line\Season 2019\05.mkv")

        assert (result.folder_title, result.year, result.folder_season, result.episode) == (
            "The Harbour Line",
            None,
            2019,
            5,
        )

    def test_a_code_with_a_years_season(self):
        result = parsed(
            r"D:\TV\The Harbour Line\Season 2019\The Harbour Line - S2019E05 - Guest One.mkv"
        )

        assert (result.kind, result.title, result.year) == (Kind.EPISODE, "The Harbour Line", None)
        assert (result.season, result.episode, result.episode_title) == (2019, 5, "Guest One")

    def test_a_title_in_lenticular_brackets_before_a_code_is_the_title(self):
        result = parsed(r"D:\Videos\【港の灯】 S01E01.mkv")

        assert (result.title, result.season, result.episode) == ("港の灯", 1, 1)


class TestFilmsWithANumberInTheirTitles:
    """A film's title can end in a number, which is no episode's: "Area 51", "Paper Kites 2"."""

    @pytest.mark.parametrize(
        ("path", "title", "year"),
        [
            (r"D:\Movies\Area.51.2015.1080p.WEB-DL.mkv", "Area 51", 2015),
            (r"D:\Movies\Paper Kites 2 (2003).mkv", "Paper Kites 2", 2003),
            (r"D:\Movies\Paper Kites 3 (2005).mkv", "Paper Kites 3", 2005),
            (r"D:\Movies\Paper Kites 2 (2003) - pt2.mkv", "Paper Kites 2", 2003),
            (r"D:\Movies\Paper Kites 2 (2003) - Part 2.mkv", "Paper Kites 2", 2003),
            # Inside the title too, its subtitle after it.
            (
                r"D:\Movies\Paper Kites 2 The Long Way Home (2003).mkv",
                "Paper Kites 2 The Long Way Home",
                2003,
            ),
            (
                r"D:\Movies\Paper.Kites.2.The.Long.Way.Home.2003.1080p.BluRay.x264-GRP.mkv",
                "Paper Kites 2 The Long Way Home",
                2003,
            ),
            (
                r"D:\Movies\2 Kites 2 Paper (2007)\2 Kites 2 Paper (2007).mkv",
                "2 Kites 2 Paper",
                2007,
            ),
        ],
    )
    def test_a_number_before_a_films_year_is_its_titles(self, path: str, title: str, year: int):
        result = parsed(path)

        assert (result.kind, result.title, result.year) == (Kind.MOVIE, title, year)
        assert (result.episode, result.episode_title) == (None, None)

    @pytest.mark.parametrize("part", ["pt1", "Part 1", "CD1", "Disc 1"])
    def test_makus_own_name_for_a_part_of_such_a_film(self, part: str):
        film = "Paper Kites 2 (2003)"
        result = parsed(rf"D:\Movies\{film}\{film} - {part}.mkv")

        assert (result.kind, result.title, result.year, result.episode) == (
            Kind.MOVIE,
            "Paper Kites 2",
            2003,
            None,
        )

    @pytest.mark.parametrize(
        "path",
        [
            r"D:\Videos\Glass Orchard\Glass Orchard - 05 (2012).mkv",
            r"D:\TV\Glass Orchard\Season 01\Glass Orchard 05 (2012).mkv",
            # Numbered as episodes are, its title after it.
            r"D:\Videos\Glass Orchard\Glass Orchard 05 The Well (2012).mkv",
        ],
    )
    def test_an_episodes_number_stays_after_a_dash_or_in_a_seasons_folder(self, path: str):
        result = parsed(path)

        assert (result.kind, result.title, result.episode) == (Kind.EPISODE, "Glass Orchard", 5)

    def test_a_part_after_an_episodes_title_stays_in_it(self):
        result = parsed(r"D:\TV\Glass Orchard\Glass Orchard - S01E05 - The Long Night Part 2.mkv")

        assert (result.episode, result.episode_title) == (5, "The Long Night Part 2")

    def test_an_episode_titled_part_2_is_no_part_of_a_season(self):
        # Its code says where it goes; "Part 2" after it is the episode's own title, so it and a
        # copy named "S01E05" alone are the same episode.
        result = parsed(r"D:\TV\The Harbour Line\The Harbour Line - S01E05 - Part 2.mkv")

        assert (result.season, result.part, result.episode, result.episode_title) == (
            1,
            None,
            5,
            "Part 2",
        )


class TestEpisodeTitlesEndingInAnExtrasWord:
    """An episode's own title may end with a word extras are named with ("Blood Sample"): only a
    release's sample, after its words, is one."""

    @pytest.mark.parametrize(
        "own",
        ["Blood Sample", "Sample", "Behind-the-Scene", "Cross-Other", "Cut-Short", "The Interview"],
    )
    def test_an_episode_whose_own_title_ends_in_it(self, own: str):
        # Maku's own clean name.
        show = r"D:\TV\Glass Orchard (2012)\Season 02"
        result = parsed(rf"{show}\Glass Orchard (2012) - S02E07 - {own}.mkv")

        assert (result.kind, result.season, result.episode, result.episode_title) == (
            Kind.EPISODE,
            2,
            7,
            own,
        )

    def test_a_numbered_episode_whose_own_title_ends_in_it(self):
        result = parsed(r"D:\TV\Glass Orchard\Glass Orchard - 05 - Blood Sample.mkv")

        assert (result.kind, result.episode, result.episode_title) == (
            Kind.EPISODE,
            5,
            "Blood Sample",
        )

    @pytest.mark.parametrize(
        "name",
        [
            "Glass.Orchard.S01E05.720p.HDTV.x264-GRP-sample.mkv",
            "glass.orchard.s01e05-sample.mkv",
            "Glass.Orchard.S01E05.Pilot.720p.HDTV-sample.mkv",
            "glass.orchard.05.720p-sample.mkv",
            "glass.orchard.05.sample.mkv",
        ],
    )
    def test_a_releases_sample_of_an_episode_is_still_an_extra(self, name: str):
        assert parsed(rf"D:\TV\{name}").kind is Kind.EXTRA


class TestDailyShows:
    """A daily show's episodes go by the day they aired: "The.Harbour.Line.2019.01.15"."""

    @pytest.mark.parametrize(
        "name",
        [
            "The.Harbour.Line.2019.01.15.Guest.One.720p.HDTV.x264-GRP.mkv",
            "The Harbour Line - 2019-01-15 - Guest One.mkv",
        ],
    )
    def test_an_air_date_after_the_title(self, name: str):
        result = parsed(rf"D:\TV\{name}")

        assert (result.kind, result.title, result.year, result.aired) == (
            Kind.EPISODE,
            "The Harbour Line",
            None,
            date(2019, 1, 15),
        )
        assert (result.season, result.episode, result.episode_title) == (None, None, "Guest One")

    def test_an_air_date_alone_takes_its_show_from_its_folder(self):
        result = parsed(r"D:\TV\The Harbour Line\2019-01-15 - Guest One.mkv")

        assert (result.kind, result.best_title, result.episode, result.aired) == (
            Kind.EPISODE,
            "The Harbour Line",
            None,
            date(2019, 1, 15),
        )

    def test_a_day_that_never_was_is_no_air_date_nor_its_numbers_an_episodes(self):
        # Which episode it is waits for the owner.
        result = parsed(r"D:\TV\The.Harbour.Line.2019.02.30.720p.HDTV.x264-GRP.mkv")

        assert (result.kind, result.title, result.aired, result.episode) == (
            Kind.EPISODE,
            "The Harbour Line",
            None,
            None,
        )


@pytest.fixture
def in_2026(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(names, "_this_year", lambda: 2026)


class TestYears:
    @pytest.mark.parametrize(
        "words",
        [
            "German.DL",
            "FRENCH",
            "TRUEFRENCH",
            "SPANiSH",
            "iTALiAN",
            "NORDiC",
            "MULTi",
            "VOSTFR",
            "DUBBED",
            "SUBBED",
        ],
    )
    def test_a_releases_language_after_the_year_ends_the_title(self, words: str):
        result = parsed(rf"D:\Movies\Starfall.2008.{words}.1080p.BluRay.x264-GRP.mkv")

        assert (result.kind, result.title, result.year) == (Kind.MOVIE, "Starfall", 2008)

    def test_a_releases_words_in_brackets_before_the_year_go(self):
        result = parsed(r"D:\Movies\Starfall [1080p] (2008).mkv")

        assert (result.title, result.year, result.height) == ("Starfall", 2008, 1080)

    @pytest.mark.usefixtures("in_2026")
    @pytest.mark.parametrize(
        ("name", "title", "year"),
        [
            ("Starfall 2049.mkv", "Starfall 2049", None),
            ("Starfall 2028.mkv", "Starfall 2028", None),
            ("Starfall 2027.mkv", "Starfall", 2027),  # next year's film, announced
            ("Starfall (2027).mkv", "Starfall", 2027),
        ],
    )
    def test_a_year_past_next_year_is_the_titles_own(self, name: str, title: str, year: int | None):
        result = parsed(rf"D:\Movies\{name}")

        assert (result.kind, result.title, result.year) == (Kind.MOVIE, title, year)


class TestIdTags:
    """Media server apps' tags of a title's ids in a folder's or a file's name ("{tmdb-12345}")
    are no part of its title; TMDB's is kept, for identifying it."""

    def test_a_shows_folder_with_its_tmdb_id(self):
        show = "The Harbour Line (2019) {tmdb-12345}"
        result = parsed(rf"D:\TV\{show}\Season 01\The Harbour Line (2019) - S01E01.mkv")

        assert (result.title, result.folder_title, result.year, result.tmdb_id) == (
            "The Harbour Line",
            "The Harbour Line",
            2019,
            12345,
        )

    @pytest.mark.parametrize(
        ("folder", "name"),
        [
            ("Starfall (2008) {tmdb-4567}", "Starfall (2008) {tmdb-4567}"),
            ("Starfall (2008) {tmdb-4567}", "Starfall (2008)"),
            ("Starfall (2008) [tmdbid-4567]", "Starfall (2008) [tmdbid-4567]"),
            ("Movies", "Starfall (2008) {tmdb-4567}"),
        ],
    )
    def test_a_film_with_its_tmdb_id(self, folder: str, name: str):
        result = parsed(rf"D:\Videos\{folder}\{name}.mkv")

        assert (result.kind, result.title, result.year, result.group, result.tmdb_id) == (
            Kind.MOVIE,
            "Starfall",
            2008,
            None,
            4567,
        )

    @pytest.mark.parametrize(
        "tag",
        ["{imdb-tt1234567}", "{tvdb-98765}", "[imdbid-tt1234567]", "{edition-Director's Cut}"],
    )
    def test_other_tags_are_left_out_of_the_title(self, tag: str):
        film = f"Starfall (2008) {tag}"
        result = parsed(rf"D:\Movies\{film}\{film}.mkv")

        assert (result.kind, result.title, result.folder_title, result.year) == (
            Kind.MOVIE,
            "Starfall",
            "Starfall",
            2008,
        )
        assert (result.group, result.tmdb_id) == (None, None)


class TestEditions:
    """A film's edition ("Special Edition", "Director's Cut") is no part of its title, and its
    "Special" makes it no show's special."""

    @pytest.mark.parametrize(
        "name",
        [
            "Starfall (2008) Special Edition",
            "Starfall Special Edition (2008)",
            "Starfall (2008) - Collector's Edition",
            "Starfall.2008.Special.Extended.Edition.1080p.BluRay.x264-GRP",
            "Starfall.2008.Directors.Cut.1080p.BluRay.x264-GRP",
            "Starfall (2008) Theatrical Version",
        ],
    )
    def test_a_films_edition_is_left_out(self, name: str):
        result = parsed(rf"D:\Movies\{name}.mkv")

        assert (result.kind, result.title, result.year) == (Kind.MOVIE, "Starfall", 2008)

    def test_a_film_in_a_folder_named_with_its_edition_is_named_as_its_folder(self):
        film = "Starfall (2008) Special Edition"
        result = parsed(rf"D:\Movies\{film}\{film}.mkv")

        assert (result.kind, result.title, result.folder_title, result.year) == (
            Kind.MOVIE,
            "Starfall",
            "Starfall",
            2008,
        )

    def test_a_title_that_is_an_edition_stays_whole(self):
        result = parsed(r"D:\Movies\Director's Cut (2016).mkv")

        assert (result.kind, result.title, result.year) == (Kind.MOVIE, "Director's Cut", 2016)

    def test_a_shows_special_is_still_one(self):
        result = parsed(r"D:\TV\Quiet Hours\Specials\Quiet Hours - Special - The Night Train.mkv")

        assert result.kind is Kind.SPECIAL


class TestBritishSeries:
    """British shows say "Series" for a season: "Series 2, Episode 1"."""

    @pytest.mark.parametrize(
        "name",
        [
            r"Series 2\Glass Orchard - Series 2 - Episode 1 - The Well",
            r"Glass Orchard Series 2 Episode 1",
            r"Glass.Orchard.Series.2.Episode.1.720p.HDTV.x264-GRP",
            r"Series 2\Glass Orchard - Season 2 - Episode 1 - The Well",
        ],
    )
    def test_a_series_number_and_an_episode_number(self, name: str):
        result = parsed(rf"D:\TV\Glass Orchard\{name}.mkv")

        assert (result.kind, result.title, result.season, result.episode) == (
            Kind.EPISODE,
            "Glass Orchard",
            2,
            1,
        )

    def test_a_series_folder_is_its_season(self):
        result = parsed(r"D:\TV\Glass Orchard\Series 2\03.mkv")

        assert (result.folder_title, result.folder_season, result.episode) == (
            "Glass Orchard",
            2,
            3,
        )

    def test_a_film_whose_title_has_series_and_a_number_keeps_it(self):
        result = parsed(r"D:\Movies\Series 7 The Contenders (2001).mkv")

        assert (result.kind, result.title, result.year) == (
            Kind.MOVIE,
            "Series 7 The Contenders",
            2001,
        )
