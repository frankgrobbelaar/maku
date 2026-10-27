"""Reading file names: made-up series and films, named the ways releases, rips and people name
them."""

from pathlib import PureWindowsPath
from typing import Any

import pytest

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
        ],
    )
    def test_a_film_in_a_librarys_own_folder_of_such_a_name_is_a_film(self, path: str):
        # "Other", "Shorts" and "Scenes" hold extras only inside a title's folder, and a word
        # for an extra is one only at the end of a name, after a dash.
        assert parsed(path).kind is Kind.MOVIE


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
