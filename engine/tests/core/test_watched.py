"""Where the owner is in a title: picked up where a video stopped, watched near its end, and the
one after it up next, in the order a title's page plays them."""

from maku.core.watched import Video, following, furthest, resume_at, seen, up_next

E1 = Video(1, 1, 1, "S01E01.mkv")
E2 = Video(2, 1, 2, "S01E02.mkv")
E3 = Video(3, 2, 1, "S02E01.mkv")
SPECIAL_1 = Video(4, 0, 1, "S00E01.mkv")
SPECIAL_2 = Video(5, 0, 2, "S00E02.mkv")
LOOSE = Video(6, None, None, "Extra.mkv")
ALL = [SPECIAL_2, E3, LOOSE, E1, SPECIAL_1, E2]


def test_a_video_is_watched_once_seen_to_its_last_tenth():
    assert seen(1296, 1440)
    assert not seen(1295, 1440)
    assert not seen(1440, None)  # its length unknown: never by position alone


def test_a_video_picks_up_where_it_stopped_unless_near_its_start_or_end():
    assert resume_at(600, 1440) == 600
    assert resume_at(29, 1440) is None
    assert resume_at(1300, 1440) is None
    assert resume_at(600, None) == 600


def test_an_episode_is_followed_by_the_rest_of_its_season_and_the_seasons_after():
    assert following(ALL, E1) == [E2, E3]
    assert following(ALL, E3) == []


def test_specials_and_files_without_a_season_keep_to_themselves():
    assert following(ALL, SPECIAL_1) == [SPECIAL_2]
    assert following(ALL, LOOSE) == []


def test_up_next_skips_what_was_watched_already():
    assert up_next(ALL, E1, watched={2}) == E3
    assert up_next(ALL, E1, watched={2, 3}) is None


def test_of_videos_played_together_the_furthest_in_is_where_the_owner_is():
    assert furthest([E2, E1, E3]) == E3
    assert furthest([SPECIAL_2, E1]) == E1  # a season's episode over a special
