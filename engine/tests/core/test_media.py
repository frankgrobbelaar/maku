"""Reading ffprobe's report. Fixtures mirror real `ffprobe -show_format -show_streams` output."""

from fractions import Fraction
from typing import cast

from maku.core.media import media_from_ffprobe

DVD_RIP_MKV: dict[str, object] = {
    "streams": [
        {
            "index": 0,
            "codec_name": "h264",
            "codec_type": "video",
            "width": 720,
            "height": 480,
            "sample_aspect_ratio": "8:9",
            "display_aspect_ratio": "4:3",
            "pix_fmt": "yuv420p",
            "field_order": "progressive",
            "avg_frame_rate": "24000/1001",
            "r_frame_rate": "24000/1001",
            "disposition": {"default": 1, "attached_pic": 0},
        },
        {
            "index": 1,
            "codec_name": "aac",
            "codec_type": "audio",
            "channels": 2,
            "tags": {"language": "jpn"},
        },
        {
            "index": 2,
            "codec_name": "ass",
            "codec_type": "subtitle",
            "tags": {"language": "eng", "title": "Full Subtitles"},
            "disposition": {"default": 1, "forced": 0},
        },
        {
            "index": 3,
            "codec_name": "ttf",
            "codec_type": "attachment",
            "tags": {"filename": "arial.ttf", "mimetype": "application/x-truetype-font"},
        },
        {
            "index": 4,
            "codec_name": "otf",
            "codec_type": "attachment",
            "tags": {"filename": "title.otf", "mimetype": "font/otf"},
        },
    ],
    "chapters": [{"id": 0}, {"id": 1}, {"id": 2}],
    "format": {
        "format_name": "matroska,webm",
        "duration": "1440.064000",
        "size": "244318208",
        "tags": {"ENCODER": "libebml v1.4.2"},
    },
}

BLURAY_HEVC_FLAC: dict[str, object] = {
    "streams": [
        {
            "codec_name": "hevc",
            "codec_type": "video",
            "width": 1920,
            "height": 1080,
            "sample_aspect_ratio": "1:1",
            "display_aspect_ratio": "16:9",
            "pix_fmt": "yuv420p10le",
            "avg_frame_rate": "24000/1001",
        },
        {"codec_name": "flac", "codec_type": "audio", "channels": 2, "tags": {"language": "jpn"}},
        {"codec_name": "aac", "codec_type": "audio", "channels": 2, "tags": {"language": "eng"}},
        {
            "codec_name": "hdmv_pgs_subtitle",
            "codec_type": "subtitle",
            "tags": {"language": "eng"},
            "disposition": {"forced": 1},
        },
    ],
    "format": {"format_name": "matroska,webm", "duration": "1420.5", "size": "1181116006"},
}

XVID_AVI: dict[str, object] = {
    "streams": [
        {
            "codec_name": "mpeg4",
            "codec_type": "video",
            "width": 640,
            "height": 480,
            "pix_fmt": "yuv420p",
            "avg_frame_rate": "2997/125",
        },
        {"codec_name": "mp3", "codec_type": "audio", "channels": 2},
    ],
    "format": {"format_name": "avi", "duration": "1380.2", "size": "183500800"},
}

INTERLACED_VOB: dict[str, object] = {
    "streams": [
        {
            "codec_name": "mpeg2video",
            "codec_type": "video",
            "width": 720,
            "height": 576,
            "sample_aspect_ratio": "16:15",
            "display_aspect_ratio": "4:3",
            "pix_fmt": "yuv420p",
            "field_order": "tt",
            "avg_frame_rate": "25/1",
        },
        {"codec_name": "ac3", "codec_type": "audio", "channels": 6},
        {"codec_name": "pcm_s16be", "codec_type": "audio", "channels": 2},
        {"codec_name": "dvd_subtitle", "codec_type": "subtitle"},
    ],
    "format": {"format_name": "mpeg", "duration": "5520.0", "size": "1073741824"},
}

MP4_WITH_COVER: dict[str, object] = {
    "streams": [
        {
            "codec_name": "mjpeg",
            "codec_type": "video",
            "width": 600,
            "height": 900,
            "disposition": {"attached_pic": 1},
        },
        {
            "codec_name": "h264",
            "codec_type": "video",
            "width": 1280,
            "height": 720,
            "pix_fmt": "yuv420p",
            "avg_frame_rate": "0/0",
            "r_frame_rate": "24000/1001",
        },
        {"codec_name": "aac", "codec_type": "audio", "channels": 2, "tags": {"language": "und"}},
    ],
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "1420.0", "size": "419430400"},
}


def test_a_dvd_rip_in_mkv():
    media = media_from_ffprobe(DVD_RIP_MKV)

    assert media.container == "mkv"
    assert media.duration == 1440.064
    assert media.size == 244_318_208
    assert media.video is not None
    assert (media.video.codec, media.video.width, media.video.height) == ("h264", 720, 480)
    assert media.video.display_aspect == Fraction(4, 3)
    assert media.video.frame_rate == Fraction(24000, 1001)
    assert (media.video.bit_depth, media.video.interlaced) == (8, False)
    assert [(audio.codec, audio.language, audio.lossless) for audio in media.audio] == [
        ("aac", "jpn", False)
    ]
    assert [(sub.codec, sub.language, sub.text) for sub in media.subtitles] == [
        ("ass", "eng", True)
    ]
    assert (media.fonts, media.chapters) == (2, 3)


def test_a_bluray_rip_with_lossless_audio_and_picture_subtitles():
    media = media_from_ffprobe(BLURAY_HEVC_FLAC)

    assert media.video is not None
    assert (media.video.codec, media.video.bit_depth) == ("hevc", 10)
    assert media.video.display_aspect == Fraction(16, 9)
    assert media.video.interlaced is None  # ffprobe didn't say; checked later
    assert [audio.lossless for audio in media.audio] == [True, False]
    assert [(sub.text, sub.forced) for sub in media.subtitles] == [(False, True)]


def test_an_old_xvid_avi():
    media = media_from_ffprobe(XVID_AVI)

    assert media.container == "avi"
    assert media.video is not None
    assert media.video.codec == "mpeg4"
    assert media.video.display_aspect == Fraction(4, 3)  # no aspect given: square pixels
    assert media.video.frame_rate == Fraction(2997, 125)
    assert media.audio[0].language is None
    assert media.subtitles == ()


def test_an_interlaced_dvd_vob():
    media = media_from_ffprobe(INTERLACED_VOB)

    assert media.container == "mpeg"
    assert media.video is not None
    assert (media.video.height, media.video.interlaced) == (576, True)
    assert media.video.display_aspect == Fraction(4, 3)
    assert [(audio.codec, audio.channels, audio.lossless) for audio in media.audio] == [
        ("ac3", 6, False),
        ("pcm_s16be", 2, True),
    ]
    assert [sub.text for sub in media.subtitles] == [False]


def test_cover_art_is_not_the_video_and_a_missing_average_rate_falls_back():
    media = media_from_ffprobe(MP4_WITH_COVER)

    assert media.container == "mp4"
    assert media.video is not None
    assert (media.video.codec, media.video.height) == ("h264", 720)
    assert media.video.frame_rate == Fraction(24000, 1001)
    assert media.audio[0].language is None  # "und" means unknown


def test_a_file_ffprobe_can_barely_read():
    media = media_from_ffprobe({"format": {"format_name": "matroska,webm"}})

    assert (media.video, media.duration, media.size) == (None, None, None)
    assert media.audio == ()


def test_makus_own_tag_is_found_whatever_its_case():
    report: dict[str, object] = {
        "format": {"format_name": "matroska,webm", "tags": {"maku": "reencode to 1080p · Maku"}}
    }

    assert media_from_ffprobe(report).maku_tag == "reencode to 1080p · Maku"
    assert media_from_ffprobe(DVD_RIP_MKV).maku_tag is None


UHD_HDR10_REMUX: dict[str, object] = {
    "streams": [
        {
            "codec_name": "hevc",
            "codec_type": "video",
            "width": 3840,
            "height": 2160,
            "display_aspect_ratio": "16:9",
            "pix_fmt": "yuv420p10le",
            "color_range": "tv",
            "color_space": "bt2020nc",
            "color_transfer": "smpte2084",
            "color_primaries": "bt2020",
            "avg_frame_rate": "24000/1001",
            "tags": {"BPS": "58000000", "NUMBER_OF_BYTES": "52200000000"},
            "side_data_list": [
                {
                    "side_data_type": "DOVI configuration record",
                    "dv_version_major": 1,
                    "dv_version_minor": 0,
                    "dv_profile": 8,
                    "dv_level": 6,
                    "rpu_present_flag": 1,
                    "el_present_flag": 0,
                    "bl_present_flag": 1,
                    "dv_bl_signal_compatibility_id": 1,
                }
            ],
        },
        {
            "codec_name": "truehd",
            "codec_type": "audio",
            "channels": 8,
            "tags": {"language": "eng", "BPS-eng": "4210000"},
        },
        {"codec_name": "ac3", "codec_type": "audio", "channels": 6, "bit_rate": "640000"},
    ],
    "format": {"format_name": "matroska,webm", "duration": "7200.0", "size": "56000000000"},
}


def test_a_4k_hdr10_film_says_its_colours_and_bit_rates():
    media = media_from_ffprobe(UHD_HDR10_REMUX)

    video = media.video
    assert video is not None
    assert (video.color_transfer, video.color_primaries, video.color_space) == (
        "smpte2084",
        "bt2020",
        "bt2020nc",
    )
    assert video.hdr == "HDR10"
    assert video.bit_rate == 58_000_000  # from MKVToolNix's statistics
    assert [audio.bit_rate for audio in media.audio] == [4_210_000, 640_000]


def test_dolby_vision_is_read_from_its_configuration_record_or_its_mp4_tag():
    hdr10_base = media_from_ffprobe(UHD_HDR10_REMUX).video
    streams = cast("list[dict[str, object]]", UHD_HDR10_REMUX["streams"])
    record = cast("list[dict[str, object]]", streams[0]["side_data_list"])[0]
    alone = {
        **streams[0],
        "side_data_list": [{**record, "dv_profile": 5, "dv_bl_signal_compatibility_id": 0}],
    }
    in_mp4: dict[str, object] = {**streams[0], "side_data_list": [], "codec_tag_string": "dvh1"}

    assert hdr10_base is not None
    assert (hdr10_base.dolby_vision, hdr10_base.needs_dolby_vision) == (True, False)
    profile_5 = media_from_ffprobe({"streams": [alone]}).video
    assert profile_5 is not None
    assert (profile_5.dolby_vision, profile_5.needs_dolby_vision) == (True, True)
    tagged = media_from_ffprobe({"streams": [in_mp4]}).video
    assert tagged is not None
    assert (tagged.dolby_vision, tagged.needs_dolby_vision) == (True, False)


def test_colours_ffprobe_calls_unknown_are_unsaid_and_sdr():
    media = media_from_ffprobe(DVD_RIP_MKV)
    unknown = {
        "codec_name": "hevc",
        "codec_type": "video",
        "width": 1920,
        "height": 1080,
        "color_transfer": "unknown",
        "color_primaries": "unknown",
    }

    assert media.video is not None
    assert (media.video.color_transfer, media.video.hdr, media.video.bit_rate) == (None, None, None)
    found = media_from_ffprobe({"streams": [unknown]}).video
    assert found is not None
    assert (found.color_transfer, found.color_primaries, found.hdr) == (None, None, None)
