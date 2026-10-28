"""What each file needs to reach the library standard: a top size, 4K or 1080p, in HEVC 10-bit."""

from dataclasses import replace
from fractions import Fraction

import pytest

from maku.core.media import Audio, MediaInfo, Subtitle, Video
from maku.core.standard import (
    FULL_HD,
    UHD,
    Method,
    decide,
    deinterlaced,
    size_name,
    sound_way,
    subtitle_way,
)

AC3 = Audio("ac3", 6, "eng", lossless=False)
FOUR_THREE = Fraction(4, 3)
WIDE = Fraction(16, 9)
PQ = ("smpte2084", "bt2020", "bt2020nc")  # HDR10's colours, as ffprobe names them


def media(
    width: int,
    height: int,
    *,
    codec: str = "h264",
    bit_depth: int = 8,
    aspect: Fraction = WIDE,
    container: str = "mkv",
    audio: tuple[Audio, ...] = (AC3,),
    interlaced: bool | None = False,
    colours: tuple[str, str, str] | None = None,
    dolby_vision: bool = False,
    needs_dolby_vision: bool = False,
) -> MediaInfo:
    transfer, primaries, matrix = colours or (None, None, None)
    video = Video(
        codec,
        width,
        height,
        aspect,
        Fraction(24000, 1001),
        bit_depth,
        interlaced,
        color_transfer=transfer,
        color_primaries=primaries,
        color_space=matrix,
        dolby_vision=dolby_vision,
        needs_dolby_vision=needs_dolby_vision,
    )
    return MediaInfo(container, 2700.0, 2_000_000_000, video, audio)


def hevc(
    width: int,
    height: int,
    *,
    container: str = "mkv",
    audio: tuple[Audio, ...] = (AC3,),
    interlaced: bool | None = False,
    colours: tuple[str, str, str] | None = None,
    dolby_vision: bool = False,
    needs_dolby_vision: bool = False,
) -> MediaInfo:
    """A picture in HEVC 10-bit already."""
    return media(
        width,
        height,
        codec="hevc",
        bit_depth=10,
        container=container,
        audio=audio,
        interlaced=interlaced,
        colours=colours,
        dolby_vision=dolby_vision,
        needs_dolby_vision=needs_dolby_vision,
    )


class TestNothingIsMadeBigger:
    def test_a_dvd_keeps_its_own_size(self):
        decision = decide(media(720, 480, codec="mpeg2video", aspect=FOUR_THREE), UHD)

        assert (decision.method, decision.width, decision.height) == (Method.REENCODE, 720, 480)
        assert decision.reasons == ("MPEG-2 becomes HEVC 10-bit",)

    def test_720p_stays_720p_at_either_standard(self):
        for standard in (UHD, FULL_HD):
            decision = decide(media(1280, 720), standard)

            assert (decision.method, decision.width, decision.height) == (
                Method.REENCODE,
                1280,
                720,
            )
            assert decision.reasons == ("H.264 becomes HEVC 10-bit",)

    def test_1080p_in_another_codec_is_made_hevc_10_bit_at_its_size(self):
        decision = decide(media(1920, 1080), UHD)

        assert (decision.method, decision.width, decision.height) == (Method.REENCODE, 1920, 1080)

    def test_4k_stays_4k_at_the_4k_standard(self):
        decision = decide(media(3840, 2160), UHD)

        assert (decision.method, decision.width, decision.height) == (Method.REENCODE, 3840, 2160)

    def test_cinemas_own_widths_count_as_their_size(self):
        assert decide(hevc(4096, 2160), UHD).method == Method.RENAME  # DCI 4K
        assert decide(hevc(1998, 1080), FULL_HD).method == Method.RENAME  # DCI flat
        assert decide(hevc(1920, 1088), FULL_HD).method == Method.RENAME


class TestBroughtDown:
    def test_4k_hdr_comes_down_to_1080p_with_its_hdr(self):
        decision = decide(hevc(3840, 2160, colours=PQ), FULL_HD)

        assert (decision.method, decision.width, decision.height) == (Method.REENCODE, 1920, 1080)
        assert decision.reasons == ("4K HDR: brought down to 1080p, HDR kept",)

    def test_a_4k_film_in_scope_keeps_its_shape(self):
        decision = decide(media(3840, 1600, aspect=Fraction(12, 5)), FULL_HD)

        assert (decision.width, decision.height) == (1920, 800)
        assert decision.reasons == ("4K: brought down to 1080p",)

    def test_8k_comes_down_to_4k(self):
        decision = decide(hevc(7680, 4320), UHD)

        assert (decision.method, decision.width, decision.height) == (Method.REENCODE, 3840, 2160)
        assert decision.reasons == ("8K: brought down to 4K",)

    def test_hlg_counts_as_hdr(self):
        hlg = ("arib-std-b67", "bt2020", "bt2020nc")

        decision = decide(media(3840, 2160, codec="vp9", colours=hlg), FULL_HD)

        assert decision.reasons == ("4K HDR: brought down to 1080p, HDR kept",)

    def test_1440p_comes_down_to_1080p_and_stays_as_it_is_at_4k(self):
        down = decide(media(2560, 1440), FULL_HD)
        kept = decide(media(2560, 1440), UHD)

        assert (down.width, down.height) == (1920, 1080)
        assert down.reasons == ("1440p: brought down to 1080p",)
        assert (kept.width, kept.height) == (2560, 1440)
        assert kept.reasons == ("H.264 becomes HEVC 10-bit",)

    def test_a_16_10_picture_1080p_wide_is_1080p_and_keeps_its_size(self):
        decision = decide(media(1920, 1200, aspect=Fraction(16, 10)), FULL_HD)

        assert (decision.method, decision.width, decision.height) == (Method.REENCODE, 1920, 1200)
        assert decision.reasons == ("H.264 becomes HEVC 10-bit",)


class TestOddSizes:
    """The encoders make 4:2:0 pictures in pairs of lines: NVENC pads an odd one (1920x803 came
    out 1920x804, measured), so a new picture of an odd size loses its last line or column."""

    def test_a_new_picture_of_an_odd_size_loses_its_last_line_or_column(self):
        scope = decide(media(1920, 803, codec="av1", aspect=Fraction(1920, 803)), UHD)
        small = decide(media(721, 405, aspect=Fraction(721, 405)), FULL_HD)

        assert (scope.method, scope.width, scope.height) == (Method.REENCODE, 1920, 802)
        assert (small.width, small.height) == (720, 404)

    def test_a_copied_picture_keeps_its_odd_size_till_its_made_anew(self):
        remux = decide(hevc(1920, 803, container="mp4"), UHD)

        assert (remux.method, remux.width, remux.height) == (Method.REMUX, 1920, 803)
        assert (deinterlaced(remux).width, deinterlaced(remux).height) == (1920, 802)


class TestThePicture:
    def test_a_file_already_at_the_standard_is_only_renamed(self):
        decision = decide(hevc(3840, 2160, colours=PQ), UHD)

        assert decision.method == Method.RENAME
        assert decision.reasons == ("Already HEVC 10-bit in MKV: only renamed",)

    def test_8_bit_hevc_is_made_10_bit(self):
        decision = decide(media(1920, 1080, codec="hevc", bit_depth=8), UHD)

        assert decision.method == Method.REENCODE
        assert decision.reasons == ("HEVC 8-bit becomes HEVC 10-bit",)

    def test_an_hdr_picture_in_another_codec_keeps_its_hdr(self):
        decision = decide(media(1920, 1080, codec="av1", bit_depth=10, colours=PQ), UHD)

        assert decision.reasons == ("AV1 becomes HEVC 10-bit, HDR kept",)

    def test_an_interlaced_picture_at_the_standard_is_made_anew_not_copied(self):
        decision = decide(hevc(1920, 1080, container="mp4", interlaced=True), UHD)

        assert (decision.method, decision.deinterlace) == (Method.REENCODE, True)
        assert decision.reasons == ("Interlaced: deinterlaced first", "MP4 becomes MKV")

    def test_an_interlaced_dvd_is_deinterlaced_first(self):
        dvd = media(720, 576, codec="mpeg2video", aspect=FOUR_THREE, interlaced=True)

        decision = decide(dvd, UHD)

        assert (decision.method, decision.deinterlace) == (Method.REENCODE, True)
        assert "Interlaced: deinterlaced first" in decision.reasons


class TestSound:
    @pytest.mark.parametrize("codec", ["truehd", "dts", "flac", "pcm_s24le", "eac3"])
    def test_every_sound_track_is_kept_as_it_is(self, codec: str):
        track = Audio(codec, 8, "eng", lossless=codec != "eac3")

        assert decide(hevc(1920, 1080, audio=(track, AC3)), UHD).method == Method.RENAME

    def test_blu_ray_pcm_becomes_flac_as_mkv_cant_hold_it(self):
        bluray = Audio("pcm_bluray", 6, "eng", lossless=True)

        decision = decide(hevc(1920, 1080, container="mpegts", audio=(bluray, AC3)), UHD)

        assert decision.method == Method.REMUX
        assert decision.reasons == (
            "TS becomes MKV",
            "Blu-ray's PCM sound becomes FLAC, still lossless",
        )

    def test_an_mkvs_own_tracks_are_ones_mkv_holds_and_stay(self):
        unlisted = Audio("gsm_ms", 1, "eng", lossless=False)  # kept the WAV way
        unread = Subtitle("unknown", "eng", False, False)  # ffmpeg can't read it, but it's there
        film = replace(hevc(1920, 1080, audio=(unlisted,)), subtitles=(unread,))

        decision = decide(film, UHD)

        assert decision.method == Method.RENAME  # never remuxed for what's in it

    def test_dvd_pcm_becomes_flac_beside_the_new_picture(self):
        dvd = media(720, 480, codec="mpeg2video", aspect=FOUR_THREE, container="mpeg")
        pcm = Audio("pcm_dvd", 2, "eng", lossless=True)

        decision = decide(MediaInfo(dvd.container, 2700.0, 1, dvd.video, (pcm,)), UHD)

        assert decision.reasons == (
            "MPEG-2 becomes HEVC 10-bit",
            "MPEG becomes MKV",
            "DVD's PCM sound becomes FLAC, still lossless",
        )

    def test_the_right_picture_in_another_container_is_moved_to_mkv(self):
        decision = decide(hevc(1920, 1080, container="mp4"), UHD)

        assert decision.method == Method.REMUX
        assert decision.reasons == ("MP4 becomes MKV",)

    def test_any_pcm_mkv_cant_hold_becomes_flac(self):
        eight_bit = Audio("pcm_s8", 2, "eng", lossless=True)

        decision = decide(hevc(1920, 1080, container="mov", audio=(eight_bit,)), UHD)

        assert decision.reasons == ("MOV becomes MKV", "PCM sound becomes FLAC, still lossless")

    def test_other_sound_mkv_cant_hold_becomes_flac_as_it_plays(self):
        adpcm = Audio("adpcm_ima_qt", 2, "eng", lossless=False)

        decision = decide(hevc(1920, 1080, container="mov", audio=(adpcm,)), UHD)

        assert decision.reasons == (
            "MOV becomes MKV",
            "ADPCM sound becomes FLAC, as MKV can't hold it",
        )

    def test_float_pcm_stays_float_pcm_saying_nothing_of_it(self):
        float_pcm = Audio("pcm_f32be", 2, "eng", lossless=True)

        decision = decide(hevc(1920, 1080, container="mov", audio=(float_pcm,)), UHD)

        assert decision.reasons == ("MOV becomes MKV",)


class TestSubtitles:
    def test_subtitles_mkv_cant_hold_are_left_out_saying_so(self):
        recording = replace(
            media(1920, 1080, container="mpegts"),
            subtitles=(
                Subtitle("dvb_subtitle", "eng", False, False),
                Subtitle("dvb_teletext", "eng", False, False),
                Subtitle("dvb_teletext", "fra", False, False),
                Subtitle("eia_608", "eng", False, False),
            ),
        )

        decision = decide(recording, UHD)

        assert decision.reasons == (
            "H.264 becomes HEVC 10-bit",
            "TS becomes MKV",
            "Teletext subtitles are left out: MKV can't hold them",
            "Closed captions are left out: MKV can't hold them",
        )

    def test_mp4s_text_subtitles_become_srt_and_ttml_is_left_out(self):
        web = replace(
            hevc(1920, 1080, container="mp4"),
            subtitles=(
                Subtitle("mov_text", "eng", True, False),
                Subtitle("ttml", "eng", True, False),
            ),
        )

        decision = decide(web, UHD)

        assert decision.reasons == (
            "MP4 becomes MKV",
            "TTML subtitles are left out: MKV can't hold them",
        )


@pytest.mark.parametrize(
    ("codec", "way"),
    [
        *((codec, "copy") for codec in ("truehd", "dts", "eac3", "ac3", "aac", "aac_latm", "opus")),
        *((codec, "copy") for codec in ("flac", "alac", "mp3", "mp2", "vorbis", "wmav2", "wmapro")),
        *((codec, "copy") for codec in ("pcm_s16le", "pcm_s24be", "pcm_s32le", "pcm_u8")),
        *((codec, "copy") for codec in ("pcm_f32le", "pcm_f64le", "pcm_alaw", "adpcm_ms")),
        # Integer PCM MKV can't hold: FLAC, the same samples (measured up to 24 bits)...
        *((codec, "flac") for codec in ("pcm_bluray", "pcm_dvd", "pcm_s8", "pcm_u16le")),
        *((codec, "flac") for codec in ("pcm_u24be", "pcm_s16le_planar", "pcm_s24le_planar")),
        # ...but FLAC keeps 24 of 32 bits, so 32- and 64-bit PCM stays PCM, as MKV holds it.
        ("pcm_u32le", "pcm_s32le"),
        ("pcm_s32le_planar", "pcm_s32le"),
        ("pcm_s64be", "pcm_s64le"),
        # Float PCM stays float, in the byte order MKV holds.
        ("pcm_f32be", "pcm_f32le"),
        ("pcm_f16le", "pcm_f32le"),
        ("pcm_f64be", "pcm_f64le"),
        # Any other sound MKV can't hold becomes FLAC, from what it plays as.
        ("adpcm_ima_qt", "flac"),
        ("nellymoser", "flac"),
    ],
)
def test_sound_goes_into_the_mkv_as_it_is_or_as_mkv_holds_it(codec: str, way: str):
    assert sound_way(codec, "mov") == way
    assert sound_way(codec, "mkv") == "copy"  # in an MKV already: one MKV holds


@pytest.mark.parametrize(
    ("codec", "way"),
    [
        *((codec, "copy") for codec in ("subrip", "ass", "webvtt", "text", "hdmv_text_subtitle")),
        *((codec, "copy") for codec in ("hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle")),
        ("arib_caption", "copy"),
        ("mov_text", "srt"),
        *((codec, None) for codec in ("dvb_teletext", "eia_608", "ttml", "xsub", "unknown")),
    ],
)
def test_subtitles_go_into_the_mkv_as_they_are_as_srt_or_not_at_all(codec: str, way: str | None):
    assert subtitle_way(codec, "mpegts") == way
    assert subtitle_way(codec, "mkv") == "copy"  # in an MKV already: one MKV holds


def test_subtitles_ffmpeg_cant_read_are_left_out_saying_only_that():
    recording = replace(
        media(1920, 1080, container="mpegts"), subtitles=(Subtitle("unknown", None, False, False),)
    )

    assert decide(recording, UHD).reasons == (
        "H.264 becomes HEVC 10-bit",
        "TS becomes MKV",
        "Subtitles ffmpeg can't read are left out",
    )


class TestDolbyVision:
    def test_a_copied_picture_keeps_it(self):
        decision = decide(hevc(3840, 2160, colours=PQ, container="mp4", dolby_vision=True), UHD)

        assert decision.method == Method.REMUX
        assert decision.reasons == ("MP4 becomes MKV",)

    def test_a_new_picture_keeps_the_hdr10_under_it(self):
        decision = decide(hevc(3840, 2160, colours=PQ, dolby_vision=True), FULL_HD)

        assert (decision.method, decision.width) == (Method.REENCODE, 1920)
        assert decision.reasons == (
            "4K HDR: brought down to 1080p, HDR kept",
            "Dolby Vision's own layer can't be carried over: its HDR10 picture is kept",
        )

    def test_a_picture_only_right_with_it_is_never_made_anew(self):
        alone = hevc(3840, 2160, dolby_vision=True, needs_dolby_vision=True)

        decision = decide(alone, FULL_HD)

        assert (decision.method, decision.width, decision.height) == (Method.RENAME, 3840, 2160)
        assert decision.reasons == (
            "4K Dolby Vision: kept as it is, as a new picture would spoil its colours",
        )


def test_a_picture_found_interlaced_later_is_deinterlaced_and_made_anew():
    remux = decide(hevc(1920, 1080, container="mp4", interlaced=None), UHD)
    dvd = decide(media(720, 480, codec="mpeg2video", aspect=FOUR_THREE, interlaced=None), UHD)

    assert remux.method == Method.REMUX
    assert (deinterlaced(remux).method, deinterlaced(remux).deinterlace) == (Method.REENCODE, True)
    assert deinterlaced(remux).reasons == ("Interlaced: deinterlaced first", "MP4 becomes MKV")
    assert (deinterlaced(dvd).method, deinterlaced(dvd).deinterlace) == (Method.REENCODE, True)


def test_a_file_without_a_picture_is_skipped():
    decision = decide(MediaInfo("mkv", 1440.0, 1000, None, (AC3,)), UHD)

    assert decision.method == Method.SKIP
    assert decision.reasons == ("No picture to convert",)


@pytest.mark.parametrize(
    ("width", "height", "aspect", "expected"),
    [
        (3840, 2160, Fraction(16, 9), (1920, 1080)),
        (3840, 1608, Fraction(3840, 1608), (1920, 804)),  # scope
        (2880, 2160, Fraction(4, 3), (1440, 1080)),  # a 4:3 picture keeps its sides
        (3840, 2076, Fraction(37, 20), (1920, 1038)),  # flat, 1.85 to 1
    ],
)
def test_a_picture_brought_down_keeps_its_shape_on_screen(
    width: int, height: int, aspect: Fraction, expected: tuple[int, int]
):
    decision = decide(media(width, height, aspect=aspect), FULL_HD)

    assert (decision.width, decision.height) == expected


@pytest.mark.parametrize(
    ("width", "height", "name"),
    [
        (720, 480, "SD"),
        (1024, 576, "SD"),
        (1280, 720, "720p"),
        (1280, 536, "720p"),
        (960, 720, "720p"),  # 4:3 at 720 lines
        (1920, 1080, "1080p"),
        (1920, 800, "1080p"),
        (2048, 1080, "1080p"),
        (1440, 1080, "1080p"),  # 4:3 at 1080 lines
        (1920, 1200, "1080p"),  # 16:10, as wide as 1080p
        (2560, 1440, "1440p"),
        (2560, 1080, "1440p"),  # as wide as 1440p
        (3840, 2160, "4K"),
        (4096, 1716, "4K"),
        (5120, 2880, "8K"),  # bigger than 4K
        (7680, 4320, "8K"),
    ],
)
def test_sizes_are_called_by_the_frame_they_fit(width: int, height: int, name: str):
    assert size_name(width, height) == name
