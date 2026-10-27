"""Playing a video inside Maku's window: what a file offers to play, and the ffmpeg commands that
make it something the window plays as it comes."""

from pathlib import PureWindowsPath

from maku.core import fields
from maku.core.fields import Json
from maku.core.player import (
    ENCODERS,
    Chapter,
    Drawn,
    Font,
    Sound,
    Subtitles,
    encoder_check_command,
    first_sound,
    first_subtitles,
    playable,
    stream_command,
    subtitles_command,
)

FF = ["ffmpeg.exe"]
VIDEO = PureWindowsPath(r"D:\Videos\Quiet Hours (2015)\Season 01\Quiet Hours (2015) - S01E03.mkv")
WINDOWS = ENCODERS["h264_mf"]  # Windows' own encoder


def stream(index: int, kind: str, codec: str, **more: object) -> Json:
    return {"index": index, "codec_type": kind, "codec_name": codec, **more}


REPORT: Json = {
    "streams": [
        stream(0, "video", "hevc", width=1920, height=1080, field_order="progressive"),
        stream(1, "audio", "flac", channels=2, tags={"language": "jpn"}),
        stream(2, "audio", "ac3", channels=6, tags={"language": "eng", "title": "Dub"},
               disposition={"default": 1}),
        stream(3, "subtitle", "ass", tags={"language": "eng", "title": "Signs"},
               disposition={"forced": 1}),
        stream(4, "subtitle", "eia_608"),  # captions Maku can't draw: they still count
        stream(5, "subtitle", "hdmv_pgs_subtitle", tags={"language": "eng"},
               disposition={"default": 1}),
        stream(6, "subtitle", "subrip", tags={"language": "ger"}),
        stream(7, "attachment", "ttf", tags={"filename": "Gandhi Sans.TTF",
                                             "mimetype": "application/x-truetype-font"}),
        stream(8, "attachment", "otf", tags={"filename": "font", "mimetype": "font/otf"}),
        stream(9, "attachment", "png", tags={"filename": "cover.png", "mimetype": "image/png"}),
    ],
    "format": {"format_name": "matroska,webm", "duration": "1440.5"},
    "chapters": [
        {"start_time": "90.0", "tags": {"title": "Part A"}},
        {"start_time": "0.000000", "tags": {"title": "Opening"}},
        {"start_time": "1350.25"},
    ],
}  # fmt: skip


def test_a_file_offers_its_sound_subtitles_chapters_and_fonts():
    found = playable(REPORT, VIDEO)

    assert found.duration == 1440.5
    assert found.sound == (
        Sound(0, "jpn", None, channels=2, default=False),
        Sound(1, "eng", "Dub", channels=6, default=True),
    )
    assert found.subtitles == (
        Subtitles(0, "eng", "Signs", "styled", codec="ass", forced=True),
        Subtitles(2, "eng", None, "pictures", codec="hdmv_pgs_subtitle", default=True),
        Subtitles(3, "ger", None, "text", codec="subrip"),
    )
    assert found.chapters == (
        Chapter(0, "Opening"),
        Chapter(90, "Part A"),
        Chapter(1350.25, None),
    )
    assert found.fonts == (Font(7, ".ttf"), Font(8, ".otf"))
    assert not found.deinterlace


def test_subtitle_files_beside_it_come_after_its_own():
    beside = [VIDEO.with_name(f"{VIDEO.stem}.en.srt"), VIDEO.with_name(f"{VIDEO.stem}.ass")]

    found = playable(REPORT, VIDEO, beside)

    assert found.subtitles[-2:] == (
        Subtitles(4, "en", None, "text", codec="srt", beside=beside[0]),
        Subtitles(5, None, None, "styled", codec="ass", beside=beside[1]),
    )
    assert found.track(4) == found.subtitles[-2]
    assert found.track(1) is None  # the captions it can't draw


def test_a_language_is_read_from_a_subtitle_files_name_only_after_the_videos():
    video = PureWindowsPath(r"D:\Videos\La.Ligne.du.Port - 01.mkv")  # "la", "du": the name's own
    names = [
        "La.Ligne.du.Port - 01.srt",
        "La.Ligne.du.Port - 01.eng.forced.ass",
        "La.Ligne.du.Port - 01.Japanese.srt",
    ]

    found = playable(REPORT, video, [video.with_name(name) for name in names])

    assert [track.language for track in found.subtitles[-3:]] == [None, "eng", None]


def test_it_starts_with_the_files_own_picks_or_else_its_first():
    found = playable(REPORT, VIDEO)

    assert first_sound(found) == 1  # the dub, marked as the default
    assert first_subtitles(found) == 2  # the pictures, marked as the default

    unmarked: list[Json] = [
        {**each, "disposition": {}} for each in fields.mappings(REPORT, "streams")
    ]
    nothing_marked: Json = {**REPORT, "streams": unmarked}
    plain = playable(nothing_marked, VIDEO)
    assert (first_sound(plain), first_subtitles(plain)) == (0, 0)

    bare = playable({"streams": [stream(0, "video", "h264")], "format": {}}, VIDEO)
    assert (first_sound(bare), first_subtitles(bare)) == (None, None)


def test_a_picture_that_isnt_said_to_be_progressive_is_drawn_whole():
    unknown = {**REPORT, "streams": [stream(0, "video", "mpeg2video", width=720, height=480)]}

    assert playable(unknown, VIDEO).deinterlace


def test_it_streams_from_any_point_with_one_sound_track_made_stereo():
    command = stream_command(
        FF, VIDEO, at=192.5, sound=1, drawn=None, deinterlace=False, encoder=WINDOWS
    )

    assert command == [
        "ffmpeg.exe",
        "-nostdin",
        "-v",
        "error",
        "-ss",
        "192.500",
        "-copyts",
        "-i",
        str(VIDEO),
        "-map",
        "0:v:0",
        "-vf",
        "setpts=PTS-STARTPTS,scale=w='trunc(oh*dar/2)*2':h='trunc(min(1080,ih)/2)*2',"
        "setsar=1,format=yuv420p",
        "-map",
        "0:a:1",
        "-af",
        "asetpts=PTS-STARTPTS",
        "-c:a",
        "aac",
        "-ac",
        "2",
        "-b:a",
        "192k",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        *WINDOWS,
        "-f",
        "mp4",
        "-movflags",
        "frag_keyframe+empty_moov+default_base_moof",
        "pipe:1",
    ]


def test_text_subtitles_are_drawn_with_the_files_fonts_after_the_picture_is_made_whole():
    drawn = Drawn(
        text=PureWindowsPath(r"C:\Users\O'Brien\Maku\cache\player\ab\0.ass"),
        fonts=PureWindowsPath(r"C:\Users\O'Brien\Maku\cache\player\ab\fonts"),
    )

    command = stream_command(
        FF, VIDEO, at=0, sound=0, drawn=drawn, deinterlace=True, encoder=WINDOWS
    )

    assert command[command.index("-vf") + 1].split(",")[:2] == [
        "bwdif=mode=send_frame:deint=interlaced",
        r"subtitles=filename=C\\:/Users/O\\\'Brien/Maku/cache/player/ab/0.ass"
        r":fontsdir=C\\:/Users/O\\\'Brien/Maku/cache/player/ab/fonts",
    ]


def test_picture_subtitles_are_laid_over_straight_from_the_file():
    command = stream_command(
        FF, VIDEO, at=10, sound=None, drawn=Drawn(pictures=2), deinterlace=False, encoder=WINDOWS
    )

    assert "-vf" not in command
    graph = command[command.index("-filter_complex") + 1]
    assert graph == (
        "[0:v:0]null[base];[base][0:s:2]overlay=eof_action=pass,setpts=PTS-STARTPTS,"
        "scale=w='trunc(oh*dar/2)*2':h='trunc(min(1080,ih)/2)*2',setsar=1,format=yuv420p"
        "[picture]"
    )
    assert command[command.index("-filter_complex") + 2 :][:2] == ["-map", "[picture]"]
    assert "-an" in command  # no sound chosen


def test_subtitles_are_copied_out_with_the_fonts_under_makus_own_names():
    track = Subtitles(0, "eng", None, "styled", codec="ass")
    out = PureWindowsPath(r"C:\Maku\cache\player\ab\0.part")
    fonts = [
        (Font(7, ".ttf"), PureWindowsPath(r"C:\Maku\cache\player\ab\f\0.ttf")),
        (Font(8, ".otf"), PureWindowsPath(r"C:\Maku\cache\player\ab\f\1.otf")),
    ]

    command = subtitles_command(FF, VIDEO, track, out, fonts)

    assert command == [
        "ffmpeg.exe",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-dump_attachment:7",
        str(fonts[0][1]),
        "-dump_attachment:8",
        str(fonts[1][1]),
        "-copyts",
        "-i",
        str(VIDEO),
        "-map",
        "0:s:0",
        "-c:s",
        "copy",
        "-f",
        "ass",
        str(out),
    ]
    srt = subtitles_command(FF, VIDEO, Subtitles(3, "ger", None, "text", codec="subrip"), out)
    assert srt[srt.index("-map") + 1 : srt.index("-f")] == ["0:s:3", "-c:s", "ass"]


def test_an_encoder_shows_it_works_on_a_moment_of_black():
    command = encoder_check_command(FF, ENCODERS["h264_nvenc"])

    assert command[command.index("-i") + 1].startswith("color=c=black")
    assert "h264_nvenc" in command
    assert command[-3:] == ["-f", "null", "-"]
