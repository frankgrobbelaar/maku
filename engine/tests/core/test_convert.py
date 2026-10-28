"""Converting one file: what it becomes, the ffmpeg command that makes it, and checking it."""

from dataclasses import replace
from fractions import Fraction
from pathlib import PureWindowsPath

from maku.core.convert import (
    Colours,
    check,
    interlace_command,
    interlaced,
    one_command,
    preview_command,
    recipe,
    still_command,
)
from maku.core.media import Audio, MediaInfo, Subtitle, Video
from maku.core.standard import FULL_HD, UHD, Decision, Method, decide

SOURCE = PureWindowsPath(r"D:\Videos\TV\Starfall (2019)\Season 01\Starfall (2019) - S01E05.mkv")
WORK = PureWindowsPath(
    r"D:\Videos\TV\Starfall (2019)\Season 01\Starfall (2019) - S01E05.maku-converting"
)
FFMPEG = "ffmpeg.exe"
FF = [FFMPEG]  # the command that runs it
TAG = "reencode to 1080p · Maku 0.1.0"
FILM = Fraction(24000, 1001)
EPISODE = Video("h264", 1920, 1080, Fraction(16, 9), FILM, 8, False, bit_rate=6_000_000)


def hdr10(video: Video) -> Video:
    """The picture as HDR10 says its colours: PQ, BT.2020."""
    return replace(
        video, color_transfer="smpte2084", color_primaries="bt2020", color_space="bt2020nc"
    )


def episode() -> MediaInfo:
    """A 1080p H.264 episode, 45 minutes: English and French sound, styled subtitles, fonts."""
    return MediaInfo(
        "mkv",
        2700.0,
        2_250_000_000,
        EPISODE,
        (Audio("eac3", 6, "eng", False), Audio("ac3", 2, "fra", False)),
        (Subtitle("ass", "eng", True, False),),
        fonts=2,
        chapters=4,
    )


FILM_4K = hdr10(Video("hevc", 3840, 2160, Fraction(16, 9), FILM, 10, False))


def film_4k() -> MediaInfo:
    """A 4K HDR10 film in HEVC 10-bit, in its Blu-ray's M2TS, with its sound as it came."""
    return MediaInfo(
        "mpegts",
        7200.0,
        60_000_000_000,
        FILM_4K,
        (Audio("truehd", 8, "eng", True), Audio("pcm_bluray", 6, "eng", True)),
    )


def test_an_episode_keeps_its_sound_subtitles_and_fonts():
    media = episode()

    made = recipe(SOURCE, media, decide(media, UHD), tag=TAG)

    assert (made.method, made.width, made.height, made.scaled, made.deinterlace) == (
        Method.REENCODE,
        1920,
        1080,
        False,
        False,
    )
    assert made.audio == ("copy", "copy")  # copied as they are
    assert made.subtitles == ("copy",)
    assert (made.fonts, made.output.name) == (True, "Starfall (2019) - S01E05.mkv")


def maps(command: list[str]) -> list[str]:
    return [command[at + 1] for at, part in enumerate(command) if part == "-map"]


def test_a_new_picture_at_its_own_size_is_only_made_10_bit():
    media = episode()
    made = recipe(SOURCE, media, decide(media, UHD), tag=TAG)

    command = one_command(FF, SOURCE, WORK, made)

    assert command[:7] == [FFMPEG, "-nostdin", "-v", "error", "-y", "-i", str(SOURCE)]
    assert command[command.index("-vf") + 1] == "format=p010le"
    assert command[command.index("-c:v") + 1] == "hevc_nvenc"
    assert maps(command) == ["0:V:0", "0:a?", "0:s:0", "0:t?"]
    assert command[command.index("-c:a:0") + 1] == "copy"
    assert f"MAKU={TAG}" in command
    assert command[-3:] == ["-f", "matroska", str(WORK)]


# What MKVToolNix writes of each track as it muxes (and MakeMKV too), in either spelling: ffmpeg
# copies a stream's tags into what it makes, where they'd describe the original, not the result.
STATISTICS = (
    "BPS",
    "NUMBER_OF_BYTES",
    "NUMBER_OF_FRAMES",
    "_STATISTICS_WRITING_APP",
    "_STATISTICS_WRITING_DATE_UTC",
    "_STATISTICS_TAGS",
)


def test_the_result_carries_none_of_the_originals_statistics():
    for media in (episode(), film_4k()):  # a new picture, and one copied
        command = one_command(FF, SOURCE, WORK, recipe(SOURCE, media, decide(media, UHD), tag=TAG))

        cleared = {command[at + 1] for at, part in enumerate(command) if part == "-metadata:s"}

        wanted = {f"{name}{spelling}=" for name in STATISTICS for spelling in ("", "-eng")}
        assert {*wanted, "DURATION-eng="} <= cleared  # ffmpeg writes its own DURATION


def test_nvenc_is_set_for_live_action_and_held_to_the_originals_bit_rate():
    made = recipe(SOURCE, episode(), decide(episode(), UHD), tag=TAG)

    command = one_command(FF, SOURCE, WORK, made)

    encoder = command[command.index("-c:v") : command.index("-c:a:0")]
    assert encoder == [
        "-c:v",
        "hevc_nvenc",
        "-preset",
        "p6",
        "-tune",
        "hq",
        "-rc",
        "vbr",
        "-cq",
        "21",
        "-b:v",
        "0",
        "-spatial-aq",
        "1",
        "-profile:v",
        "main10",
        # Without a ceiling of its own, NVENC holds the bit rate to its preset's: about 10 Mb/s.
        "-maxrate",
        "6000000",
        "-bufsize",
        "12000000",
    ]


def test_a_picture_that_doesnt_say_its_bit_rate_is_held_to_the_whole_files_less_its_sound():
    media = replace(episode(), video=replace(EPISODE, bit_rate=None))

    made = recipe(SOURCE, media, decide(media, UHD), tag=TAG)

    # 6.7 Mb/s in all, less two Dolby Digital tracks that don't say theirs (640 kb/s each)
    assert made.peak == round(2_250_000_000 * 8 / 2700.0 - 2 * 640_000)


def test_a_file_whose_sound_can_t_be_told_apart_is_held_to_the_whole_files():
    sound = (Audio("truehd", 8, "eng", True), Audio("truehd", 8, "fra", True))
    small = replace(
        episode(), size=900_000_000, video=replace(EPISODE, bit_rate=None), audio=sound
    )  # 2.7 Mb/s in all, less than its sound usually runs

    made = recipe(SOURCE, small, decide(small, UHD), tag=TAG)

    assert made.peak == round(900_000_000 * 8 / 2700.0)


def test_no_ceiling_reaches_past_what_players_expect_of_its_size():
    made = recipe(SOURCE, film_4k(), decide(film_4k(), FULL_HD), tag=TAG)

    assert made.peak == 40_000_000  # 1080p's most, though the 4K original ran far higher


def test_1440p_has_a_ceiling_of_its_own_between_1080ps_and_4ks():
    video = Video("h264", 2560, 1440, Fraction(16, 9), FILM, 8, False, bit_rate=80_000_000)
    media = replace(episode(), video=video, size=30_000_000_000)

    made = recipe(SOURCE, media, decide(media, UHD), tag=TAG)

    assert (made.width, made.height, made.peak) == (2560, 1440, 60_000_000)


def test_4k_hdr_comes_down_to_1080p_with_its_colours_set_on_every_frame():
    media = film_4k()
    made = recipe(SOURCE, media, decide(media, FULL_HD), tag=TAG)

    command = one_command(FF, SOURCE, WORK, made)

    assert made.colours == Colours("bt2020", "smpte2084", "bt2020nc")
    assert command[command.index("-vf") + 1] == (
        "scale=1920:1080:flags=lanczos,setsar=1,format=p010le,"
        "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc:range=tv"
    )


def test_an_hdr_picture_that_leaves_its_colours_unsaid_gets_bt_2020s():
    video = Video(
        "av1", 1920, 1080, Fraction(16, 9), FILM, 10, False, color_transfer="arib-std-b67"
    )
    media = replace(episode(), video=video)

    made = recipe(SOURCE, media, decide(media, UHD), tag=TAG)

    assert made.colours == Colours("bt2020", "arib-std-b67", "bt2020nc")


def test_blu_ray_pcm_becomes_flac_and_the_rest_of_the_sound_is_copied():
    media = film_4k()
    made = recipe(SOURCE, media, decide(media, UHD), tag=TAG)

    command = one_command(FF, SOURCE, WORK, made)

    assert made.method is Method.REMUX
    assert made.audio == ("copy", "flac")
    assert command[command.index("-c:a:0") + 1] == "copy"  # TrueHD as it is
    assert command[command.index("-c:a:1") + 1] == "flac"


def test_sound_mkv_cant_hold_is_made_into_sound_it_holds():
    sound = (
        Audio("pcm_s8", 2, "eng", True),
        Audio("pcm_f32be", 2, "eng", True),
        Audio("pcm_u32le", 2, "eng", True),
        Audio("truehd", 8, "eng", True),
    )
    media = replace(episode(), container="mov", audio=sound, subtitles=(), fonts=0)
    source = SOURCE.with_suffix(".mov")

    command = one_command(FF, source, WORK, recipe(source, media, decide(media, UHD), tag=TAG))

    ways = [command[command.index(f"-c:a:{number}") + 1] for number in range(4)]
    assert ways == ["flac", "pcm_f32le", "pcm_s32le", "copy"]
    assert "0:a?" in maps(command)  # every sound track is kept


def test_mp4s_text_subtitles_become_srt():
    media = replace(
        episode(), container="mp4", subtitles=(Subtitle("mov_text", "eng", True, False),), fonts=0
    )
    source = SOURCE.with_suffix(".mp4")

    made = recipe(source, media, decide(media, UHD), tag=TAG)

    assert made.subtitles == ("srt",)
    assert made.output == SOURCE  # an MKV beside it


RECORDING_SUBTITLES = (
    Subtitle("dvb_subtitle", "eng", False, False),
    Subtitle("dvb_teletext", "eng", False, False),
    Subtitle("mov_text", "fra", True, False),
    Subtitle("eia_608", "eng", False, False),
)


def test_subtitles_mkv_cant_hold_are_left_out_of_the_result():
    media = replace(episode(), container="mpegts", subtitles=RECORDING_SUBTITLES, fonts=0)
    source = SOURCE.with_suffix(".ts")
    made = recipe(source, media, decide(media, UHD), tag=TAG)

    command = one_command(FF, source, WORK, made)

    assert made.subtitles == ("copy", None, "srt", None)
    assert maps(command) == ["0:V:0", "0:a?", "0:s:0", "0:s:2", "0:t?"]
    assert command[command.index("-c:s:0") + 1] == "copy"
    assert command[command.index("-c:s:1") + 1] == "srt"
    assert "-c:s:2" not in command


def test_the_check_counts_the_subtitles_kept():
    media = replace(episode(), container="mpegts", subtitles=RECORDING_SUBTITLES, fonts=0)
    made = recipe(SOURCE, media, decide(media, UHD), tag=TAG)
    picture = Video("hevc", 1920, 1080, Fraction(16, 9), FILM, 10, False)
    result = replace(media, container="mkv", video=picture, maku_tag=TAG)

    kept = replace(result, subtitles=(RECORDING_SUBTITLES[0], RECORDING_SUBTITLES[2]))

    assert check(media, kept, made) == []
    assert check(media, result, made) == ["It has 4 subtitle tracks, not 2"]


def test_an_odd_size_loses_its_last_line_not_its_shape():
    video = Video("av1", 1920, 803, Fraction(1920, 803), FILM, 10, False)
    media = replace(episode(), video=video)
    made = recipe(SOURCE, media, decide(media, UHD), tag=TAG)
    made_up = Video("hevc", 1920, 802, Fraction(960, 401), FILM, 10, False)

    command = one_command(FF, SOURCE, WORK, made)
    after = preview_command(FF, SOURCE, PNG, made, at=60.0)

    assert (made.width, made.height, made.scaled, made.cropped) == (1920, 802, False, True)
    assert command[command.index("-vf") + 1] == "crop=1920:802:0:0,format=p010le"
    assert after[after.index("-vf") + 1] == "crop=1920:802:0:0,format=yuv420p"
    assert check(media, replace(media, video=made_up, maku_tag=TAG), made) == []


def test_an_interlaced_picture_is_deinterlaced_before_anything_else():
    video = Video("mpeg2video", 720, 576, Fraction(4, 3), Fraction(25), 8, True)
    media = replace(episode(), video=video)
    made = recipe(SOURCE, media, decide(media, UHD), tag=TAG)

    command = one_command(FF, SOURCE, WORK, made)

    assert (made.method, made.width, made.height) == (Method.REENCODE, 720, 576)
    assert command[command.index("-vf") + 1] == "bwdif=mode=send_frame,format=p010le"


def test_a_remux_copies_the_picture():
    video = hdr10(Video("hevc", 1920, 1080, Fraction(16, 9), FILM, 10, False))
    media = replace(episode(), container="mp4", video=video, subtitles=(), fonts=0)
    made = recipe(SOURCE.with_suffix(".mp4"), media, decide(media, UHD), tag=TAG)

    command = one_command(FF, SOURCE.with_suffix(".mp4"), WORK, made)

    assert made.method is Method.REMUX
    assert (made.colours, made.peak) == (None, 0)  # nothing is made anew
    assert "-vf" not in command
    assert command[command.index("-c:v") + 1] == "copy"
    assert "-maxrate" not in command


def test_dolby_vision_leaves_no_trace_on_a_new_picture_and_stays_on_a_copied_one():
    dolby = replace(FILM_4K, dolby_vision=True)
    media = replace(film_4k(), video=dolby)

    down = one_command(FF, SOURCE, WORK, recipe(SOURCE, media, decide(media, FULL_HD), tag=TAG))
    kept = one_command(FF, SOURCE, WORK, recipe(SOURCE, media, decide(media, UHD), tag=TAG))

    assert down[down.index("-bsf:v") + 1] == "dovi_rpu=strip=1"
    assert "-bsf:v" not in kept


def test_interlacing_is_told_from_a_look_at_the_picture():
    command = interlace_command(FF, SOURCE, at=600.0)
    report = (
        "[Parsed_idet_0 @ 0000] Single frame detection: TFF: 280 BFF: 0 Progressive: 300\n"
        "[Parsed_idet_0 @ 0000] Multi frame detection: TFF: 420 BFF: 2 Progressive: 150"
        " Undetermined: 28\n"
    )

    assert command[command.index("-vf") + 1] == "idet"
    assert interlaced(report) is True
    assert interlaced(report.replace("TFF: 420", "TFF: 12")) is False
    assert interlaced("no report") is False


def test_a_result_that_matches_passes_and_one_that_doesnt_says_why():
    made = recipe(SOURCE, episode(), Decision(Method.REENCODE, 1920, 1080), tag=TAG)
    good = replace(
        episode(),
        video=Video("hevc", 1920, 1080, Fraction(16, 9), FILM, 10, False),
        duration=2699.6,
        maku_tag=TAG,
    )

    assert check(episode(), good, made) == []
    assert check(episode(), replace(good, duration=1200.0), made) == ["It's 20:00 long, not 45:00"]
    assert check(episode(), replace(good, audio=good.audio[:1]), made) == [
        "It has 1 sound track, not 2"
    ]
    assert check(episode(), replace(good, video=None), made) == ["It has no picture"]


def test_a_result_that_lost_its_hdr_never_passes():
    media = film_4k()
    made = recipe(SOURCE, media, decide(media, FULL_HD), tag=TAG)
    flat = Video("hevc", 1920, 1080, Fraction(16, 9), FILM, 10, False)
    result = replace(media, video=flat, maku_tag=TAG)

    assert check(media, result, made) == ["Its HDR didn't come through"]
    kept = hdr10(flat)
    assert check(media, replace(result, video=kept), made) == []


def test_no_ffmpeg_maku_starts_reads_keys_from_its_standard_input():
    """ffmpeg looks for key presses on standard input. Under Maku's window that's the engine's own
    input, which the engine waits on, and Windows makes ffmpeg's look wait too: it would stop."""
    made = recipe(SOURCE, episode(), Decision(Method.REENCODE, 1920, 1080), tag=TAG)
    commands = [
        one_command(FF, SOURCE, WORK, made),
        interlace_command(FF, SOURCE, at=60.0),
        still_command(FF, SOURCE, PNG, at=60.0, deinterlace=False),
        preview_command(FF, SOURCE, PNG, made, at=60.0),
    ]

    assert all(command[1] == "-nostdin" for command in commands)


PNG = PureWindowsPath(r"C:\Maku\cache\previews\after.png")


def test_the_comparison_shows_one_frame_before_and_after():
    media = film_4k()
    made = recipe(SOURCE, media, decide(media, FULL_HD), tag=TAG)

    before = still_command(FF, SOURCE, PNG, at=192.0, deinterlace=False)
    after = preview_command(FF, SOURCE, PNG, made, at=192.0)

    assert before == [
        FFMPEG,
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-ss",
        "192.00",
        "-i",
        str(SOURCE),
        "-map",
        "0:V:0",
        "-frames:v",
        "1",
        str(PNG),
    ]
    assert after[after.index("-vf") + 1] == (
        "scale=1920:1080:flags=lanczos,setsar=1,format=yuv420p,"
        "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc:range=tv"
    )
    assert after[-3:] == ["-frames:v", "1", str(PNG)]


def test_amd_and_intel_encoders_make_the_same_standard():
    media = episode()
    for encoder, name in (("amf", "hevc_amf"), ("qsv", "hevc_qsv")):
        made = recipe(
            SOURCE, media, Decision(Method.REENCODE, 1920, 1080), tag=TAG, encoder=encoder
        )

        command = one_command(FF, SOURCE, WORK, made)

        assert command[command.index("-c:v") + 1] == name
        assert command[command.index("-profile:v") + 1] == "main10"
        assert command[command.index("-vf") + 1].endswith("format=p010le")
        assert "-maxrate" not in command  # they keep to their quality without one
