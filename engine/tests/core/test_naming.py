"""Where files go and what they're called, with made-up series and films."""

from pathlib import PureWindowsPath

import pytest

from maku.core.naming import (
    MAX_PATH,
    PathTooLongError,
    episode_path,
    movie_path,
    safe_name,
    unique_path,
)

LIBRARY = PureWindowsPath(r"D:\Videos")


class TestEpisodes:
    def test_an_episode_goes_into_its_show_and_season_folders(self):
        path = episode_path(
            LIBRARY,
            "The Harbour Line",
            2019,
            season=1,
            episode=1,
            title="Pilot",
            extension=".mkv",
        )

        assert path == LIBRARY / (
            r"TV\The Harbour Line (2019)\Season 01\The Harbour Line (2019) - S01E01 - Pilot.mkv"
        )

    def test_without_an_episode_title(self):
        path = episode_path(
            LIBRARY, "The Harbour Line", 2019, season=1, episode=5, extension=".mkv"
        )

        assert path.name == "The Harbour Line (2019) - S01E05.mkv"

    def test_without_a_year(self):
        path = episode_path(LIBRARY, "Glass Orchard", None, season=1, episode=3, extension=".mp4")

        assert path == LIBRARY / r"TV\Glass Orchard\Season 01\Glass Orchard - S01E03.mp4"

    def test_three_digit_episode_numbers(self):
        path = episode_path(LIBRARY, "Market Street", 2015, season=1, episode=131, extension=".mkv")

        assert path.name == "Market Street (2015) - S01E131.mkv"

    def test_two_episodes_in_one_file(self):
        path = episode_path(
            LIBRARY, "Glass Orchard", 2012, season=1, episode=1, last_episode=2, extension=".mkv"
        )

        assert path.name == "Glass Orchard (2012) - S01E01-E02.mkv"

    def test_specials_go_to_season_00(self):
        path = episode_path(
            LIBRARY,
            "Quiet Hours",
            2015,
            season=0,
            episode=1,
            title="Christmas Special",
            extension=".mkv",
        )

        assert path == LIBRARY / (
            r"TV\Quiet Hours (2015)\Season 00\Quiet Hours (2015) - S00E01 - Christmas Special.mkv"
        )

    def test_titles_are_made_safe_for_windows(self):
        path = episode_path(
            LIBRARY,
            "Signal:Zero",
            2016,
            season=1,
            episode=1,
            title="Where Does the Signal Go When the Lights Go Out?",
            extension=".mkv",
        )

        assert path == LIBRARY / (
            r"TV\Signal-Zero (2016)\Season 01"
            r"\Signal-Zero (2016) - S01E01 - Where Does the Signal Go When the Lights Go Out.mkv"
        )


class TestMovies:
    def test_a_movie_gets_its_own_folder(self):
        path = movie_path(LIBRARY, "Starfall: Ascent - The Long Climb", 2015, extension=".avi")

        assert path == LIBRARY / (
            r"Movies\Starfall - Ascent - The Long Climb (2015)"
            r"\Starfall - Ascent - The Long Climb (2015).avi"
        )

    def test_a_movie_without_a_year(self):
        path = movie_path(LIBRARY, "Glass Orchard: The Movie", None, extension=".mkv")

        assert path == LIBRARY / r"Movies\Glass Orchard - The Movie\Glass Orchard - The Movie.mkv"


class TestSafeNames:
    @pytest.mark.parametrize(
        ("name", "safe"),
        [
            ("Starfall: Ascent", "Starfall - Ascent"),
            ("Hart-Lowe: The Inquiry", "Hart-Lowe - The Inquiry"),
            ("Signal:Zero", "Signal-Zero"),
            ("Who Keeps the Light? A Harbour Story", "Who Keeps the Light - A Harbour Story"),
            ("Where Did the Orchard Go?", "Where Did the Orchard Go"),
            ("Day/Night", "Day-Night"),
            ('The "Keeper" Returns', "The 'Keeper' Returns"),
            ("Quiet Hours*", "Quiet Hours"),
            ("Salt;Pepper", "Salt;Pepper"),
            ("Ahoy! Harbour Days", "Ahoy! Harbour Days"),
            ("Mr. Lantern.", "Mr. Lantern"),
            ("Glass  Orchard\tTwo", "Glass Orchard Two"),
            ("  Quiet Hours  ", "Quiet Hours"),
        ],
    )
    def test_characters_windows_cant_use_are_replaced(self, name: str, safe: str):
        assert safe_name(name) == safe

    @pytest.mark.parametrize("reserved", ["CON", "nul", "Com1", "LPT9", "aux"])
    def test_names_windows_reserves_get_an_underscore(self, reserved: str):
        assert safe_name(reserved) == f"{reserved}_"

    def test_a_leading_dot_goes_so_the_folder_isnt_hidden(self):
        assert safe_name(".signal//North") == "signal--North"

    def test_a_name_with_nothing_usable_is_refused(self):
        with pytest.raises(ValueError, match="nothing Windows can use"):
            safe_name("???")


class TestLongPaths:
    def test_a_long_episode_title_is_shortened_at_a_word_to_fit(self):
        title = "A Very Long Episode Title " * 12
        path = episode_path(
            LIBRARY, "The Harbour Line", 2019, season=1, episode=1, title=title, extension=".mkv"
        )

        assert len(str(path)) <= MAX_PATH
        assert path.name.startswith("The Harbour Line (2019) - S01E01 - A Very Long Episode Title")
        assert path.suffix == ".mkv"
        assert not path.stem.endswith((" ", "-"))

    def test_the_episode_title_goes_entirely_when_nothing_else_fits(self):
        deep = PureWindowsPath("D:\\" + "\\".join(["Folder"] * 26))
        path = episode_path(
            deep,
            "The Harbour Line",
            2019,
            season=1,
            episode=1,
            title="The Long Night",
            extension=".mkv",
        )

        assert len(str(path)) <= MAX_PATH
        assert path.name == "The Harbour Line (2019) - S01E01.mkv"

    def test_a_path_that_can_never_fit_is_refused(self):
        deep = PureWindowsPath("D:\\" + "\\".join(["Folder"] * 40))

        with pytest.raises(PathTooLongError):
            episode_path(deep, "The Harbour Line", 2019, season=1, episode=1, extension=".mkv")


class TestTakenNames:
    def test_a_free_name_is_kept(self):
        path = LIBRARY / "Show - S01E05.mkv"

        assert unique_path(path, taken=set()) == path

    def test_a_taken_name_gets_2_and_then_3(self):
        path = LIBRARY / "Show - S01E05.mkv"
        taken = {str(path), str(LIBRARY / "Show - S01E05 (2).mkv")}

        assert unique_path(path, taken=taken) == LIBRARY / "Show - S01E05 (3).mkv"

    def test_windows_names_differ_only_by_case_count_as_taken(self):
        path = LIBRARY / "Show - S01E05.mkv"

        assert unique_path(path, taken={r"d:\videos\show - s01e05.MKV"}).name == (
            "Show - S01E05 (2).mkv"
        )
