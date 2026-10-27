"""Converting one file: what it becomes, the ffmpeg command that makes it, and checking it."""

from dataclasses import replace
from fractions import Fraction
from pathlib import PureWindowsPath

from maku.core.convert import (
    AudioPlan,
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
    """A 4K HDR10 film in HEVC 10-bit, with its Blu-ray sound as it came."""
    return MediaInfo(
        "mkv",
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
    assert made.audio == (AudioPlan(0, False), AudioPlan(1, False))  # copied as they are
    assert made.subtitles == ("copy",)
    assert (made.fonts, made.output.name) == (True, "Starfall (2019) - S01E05.mkv")


def test_a_new_picture_at_its_own_size_is_only_made_10_bit():
    media = episode()
    made = recipe(SOURCE, media, decide(media, UHD), tag=TAG)

    command = one_command(FF, SOURCE, WORK, made)

    assert command[:7] == [FFMPEG, "-nostdin", "-v", "error", "-y", "-i", str(SOURCE)]
    assert command[command.index("-vf") + 1] == "format=p010le"
    assert command[command.index("-c:v") + 1] == "hevc_nvenc"
    assert [part for part in command if part in ("-map", "0:V:0", "0:a?", "0:s?", "0:t?")] == [
        "-map",
        "0:V:0",
        "-map",
        "0:a?",
        "-map",
        "0:s?",
        "-map",
        "0:t?",
    ]
    assert command[command.index("-c:a:0") + 1] == "copy"
    assert f"MAKU={TAG}" in command
    assert command[-3:] == ["-f", "matroska", str(WORK)]


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


def test_a_picture_that_doesnt_say_its_bit_rate_is_held_to_the_whole_files():
    media = replace(episode(), video=replace(EPISODE, bit_rate=None))

    made = recipe(SOURCE, media, decide(media, UHD), tag=TAG)

    assert made.peak == round(2_250_000_000 * 8 / 2700.0)  # 6.7 Mb/s, sound and all


def test_no_ceiling_reaches_past_what_players_expect_of_its_size():
    made = recipe(SOURCE, film_4k(), decide(film_4k(), FULL_HD), tag=TAG)

    assert made.peak == 40_000_000  # 1080p's most, though the 4K original ran far higher


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
    assert made.audio == (AudioPlan(0, False), AudioPlan(1, True))
    assert command[command.index("-c:a:0") + 1] == "copy"  # TrueHD as it is
    assert command[command.index("-c:a:1") + 1] == "flac"


def test_mp4s_text_subtitles_become_srt():
    media = replace(
        episode(), container="mp4", subtitles=(Subtitle("mov_text", "eng", True, False),), fonts=0
    )
    source = SOURCE.with_suffix(".mp4")

    made = recipe(source, media, decide(media, UHD), tag=TAG)

    assert made.subtitles == ("srt",)
    assert made.output == SOURCE  # an MKV beside it


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
