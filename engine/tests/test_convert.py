"""Converting one file on disk, with stand-ins for ffmpeg and ffprobe."""

import json
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO, cast

import pytest

from maku import __version__
from maku.convert import (
    WORKING,
    ConvertError,
    InUseError,
    NothingToConvert,
    Programs,
    Progress,
    Stopped,
    convert,
    put_in,
    restore,
    start,
    work_of,
)
from maku.core import fields
from maku.core.fields import Json
from maku.core.library import QUARANTINE_FOLDER
from maku.core.standard import FULL_HD, UHD, Standard
from maku.history import plans
from tests.converting import FAKE_FFMPEG, TAG, open_elsewhere, programs, report
from tests.shelf import NOW, library

EPISODE = "Glass Orchard (2018)/Season 01/Glass Orchard (2018) - S01E03.mkv"
RESULT = report(1920, 1080, tag=TAG)


@pytest.fixture
def episode(conn: sqlite3.Connection, tmp_path: Path) -> Path:
    """A 1080p H.264 episode, read and waiting in the queue."""
    library(conn, tmp_path / "Videos", [EPISODE])
    with conn:
        conn.execute("UPDATE files SET probe = ?", (json.dumps(report(1920, 1080, codec="h264")),))
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, added_at) VALUES (1, 'reencode', 1, ?)",
            (NOW.isoformat(),),
        )
    return tmp_path / "Videos" / EPISODE


def run(
    conn: sqlite3.Connection,
    kit: Programs,
    *,
    seen: list[Progress] | None = None,
    stop: Callable[[], bool] = lambda: False,
    discard: Callable[[], bool] = lambda: False,
    standard: Standard = UHD,
) -> None:
    heard = seen if seen is not None else []
    convert(
        conn, 1, kit, standard, now=lambda: NOW, report=heard.append, stop=stop, discard=discard
    )


def hdr10(made: Json) -> Json:
    """A report whose picture is HDR10: PQ and BT.2020."""
    streams = cast("list[dict[str, object]]", made["streams"])
    colours = {
        "color_transfer": "smpte2084",
        "color_primaries": "bt2020",
        "color_space": "bt2020nc",
    }
    return {**made, "streams": [{**streams[0], **colours}, *streams[1:]]}


def test_an_episode_is_made_anew_and_takes_its_originals_place(
    conn: sqlite3.Connection, episode: Path
):
    original = episode.read_bytes()
    seen: list[Progress] = []
    commands: list[Sequence[str]] = []

    run(conn, programs(RESULT, commands), seen=seen)

    assert episode.read_bytes() == b"converted " + original
    assert not list(episode.parent.glob(f"*{WORKING}"))
    stages = list(dict.fromkeys(progress.stage for progress in seen))
    assert stages == ["looking", "converting", "checking", "replacing"]
    assert [p.frames for p in seen if p.stage == "converting"] == [10, 20, 30, 30]
    [made] = [command for command in commands if "-progress" in command]
    assert made[made.index("-c:v") + 1] == "hevc_nvenc"
    file = conn.execute("SELECT path, probe, gone_at FROM files").fetchone()
    assert (Path(file["path"]), file["gone_at"]) == (episode, None)
    assert json.loads(file["probe"])["streams"][0]["codec_name"] == "hevc"
    job = conn.execute("SELECT state, plan_id, source_size, output_probe FROM jobs").fetchone()
    assert (job["state"], job["source_size"]) == ("done", len(original))
    assert json.loads(job["output_probe"])["format"]["tags"] == {"MAKU": TAG}
    kind = conn.execute("SELECT kind FROM plans WHERE id = ?", (job["plan_id"],)).fetchone()
    assert kind[0] == "convert"


def test_4k_hdr_comes_down_to_1080p_with_its_hdr(conn: sqlite3.Connection, episode: Path):
    with conn:
        conn.execute("UPDATE files SET probe = ?", (json.dumps(hdr10(report(3840, 2160))),))
    commands: list[Sequence[str]] = []

    run(conn, programs(hdr10(RESULT), commands), standard=FULL_HD)

    [made] = [command for command in commands if "-progress" in command]
    assert made[made.index("-vf") + 1].startswith("scale=1920:1080:flags=lanczos")
    assert "color_trc=smpte2084" in made[made.index("-vf") + 1]
    assert conn.execute("SELECT state FROM jobs").fetchone()[0] == "done"


def test_a_result_that_lost_its_hdr_never_replaces_the_original(
    conn: sqlite3.Connection, episode: Path
):
    original = episode.read_bytes()
    with conn:
        conn.execute("UPDATE files SET probe = ?", (json.dumps(hdr10(report(3840, 2160))),))

    with pytest.raises(ConvertError, match="Its HDR didn't come through"):
        run(conn, programs(RESULT), standard=FULL_HD)

    assert episode.read_bytes() == original


def set_aside(conn: sqlite3.Connection) -> sqlite3.Row:
    found: sqlite3.Row = conn.execute(
        "SELECT target, cleared_at FROM changes WHERE kind = 'quarantine'"
    ).fetchone()
    return found


def test_an_original_waits_in_quarantine_unless_the_owner_chose_to_delete_it(
    conn: sqlite3.Connection, episode: Path
):
    run(conn, programs(RESULT))

    kept = set_aside(conn)
    assert kept["cleared_at"] is None
    assert Path(kept["target"]).is_file()
    [plan] = plans(conn)
    assert (plan.moved, plan.quarantined) == (1, 1)  # History can put it back


def test_an_original_the_owner_chose_to_delete_goes_once_its_result_is_in_place(
    conn: sqlite3.Connection, episode: Path
):
    with conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('originals', '\"delete\"')")

    run(conn, programs(RESULT))

    assert episode.read_text().startswith("converted")  # the result is in place
    gone = set_aside(conn)
    assert gone["cleared_at"] is not None
    assert not Path(gone["target"]).exists()
    [plan] = plans(conn)
    assert (plan.moved, plan.quarantined) == (1, 0)  # nothing left to put back
    with pytest.raises(ConvertError, match="cleared out of quarantine"):
        restore(conn, 1, now=NOW + timedelta(hours=1))


def test_a_failed_conversion_never_deletes_the_original(conn: sqlite3.Connection, episode: Path):
    original = episode.read_bytes()
    with conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('originals', '\"delete\"')")

    with pytest.raises(ConvertError):
        run(conn, programs(report(1920, 1080, tag="someone else's")))  # it doesn't check out

    assert episode.read_bytes() == original
    assert conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0] == 0


def test_restoring_puts_the_original_back(conn: sqlite3.Connection, episode: Path):
    original = episode.read_bytes()
    run(conn, programs(RESULT))

    finished = conn.execute("SELECT finished_at FROM jobs").fetchone()[0]
    restore(conn, 1, now=NOW + timedelta(hours=3))

    assert episode.read_bytes() == original
    assert not list(episode.parent.glob(f"*{WORKING}"))
    file = conn.execute("SELECT path, probe FROM files").fetchone()
    assert Path(file["path"]) == episode
    assert json.loads(file["probe"])["streams"][0]["codec_name"] == "h264"  # the original's
    job = conn.execute("SELECT state, finished_at FROM jobs").fetchone()
    # History still says how long converting took, not how long till it was put back.
    assert (job["state"], job["finished_at"]) == ("restored", finished)


def test_a_failed_encode_leaves_the_original_as_it_was(
    conn: sqlite3.Connection, episode: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MAKU_FAKE_FAIL", "encode")
    original = episode.read_bytes()

    with pytest.raises(ConvertError, match="No capable devices found"):
        run(conn, programs(RESULT))

    assert episode.read_bytes() == original
    assert not list(episode.parent.glob(f"*{WORKING}"))


def test_a_file_that_fails_part_way_says_how_far_it_got_and_what_ffmpeg_said(
    conn: sqlite3.Connection, episode: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MAKU_FAKE_FAIL", "convert")
    original = episode.read_bytes()

    with pytest.raises(ConvertError) as failed:
        run(conn, programs(RESULT))

    assert str(failed.value) == (
        "ffmpeg couldn't convert it past 00:50: Error while decoding stream #0:0: Invalid data "
        "found."
    )
    assert failed.value.log is not None
    assert failed.value.log.splitlines()[-2:] == [
        "Error while decoding stream #0:0: Invalid data found",
        "Stopped at frame 1,200 of 34,525.",
    ]
    assert episode.read_bytes() == original


def test_a_result_that_doesnt_play_never_replaces_the_original(
    conn: sqlite3.Connection, episode: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MAKU_FAKE_FAIL", "play")
    original = episode.read_bytes()

    with pytest.raises(ConvertError, match="didn't play"):
        run(conn, programs(RESULT))

    assert episode.read_bytes() == original


def test_a_test_play_keeps_the_frames_own_times(
    conn: sqlite3.Connection, episode: Path, monkeypatch: pytest.MonkeyPatch
):
    # Rounded to the frame rate, two frames' times can come out the same at some points of a file
    # that plays well, its original too: 42 results were thrown away for it on the PC this was
    # first built on (2026-10-14, "it didn't play at 21:46 ... non monotonically increasing dts").
    monkeypatch.setenv("MAKU_FAKE_ROUNDS", "1")

    run(conn, programs(RESULT))

    assert episode.read_text().startswith("converted")  # the result is in place


def test_a_result_that_isnt_right_never_replaces_the_original(
    conn: sqlite3.Connection, episode: Path
):
    with pytest.raises(ConvertError, match="not hevc 10-bit 1920x1080"):
        run(conn, programs(report(1280, 720, tag=TAG)))

    assert not episode.read_bytes().startswith(b"converted")


def test_stopping_leaves_everything_as_it_was(conn: sqlite3.Connection, episode: Path):
    original = episode.read_bytes()

    with pytest.raises(Stopped):
        run(conn, programs(RESULT), stop=lambda: True)

    assert episode.read_bytes() == original
    assert not list(episode.parent.glob(f"*{WORKING}"))


def test_a_result_held_a_moment_as_it_goes_never_changes_the_outcome(
    conn: sqlite3.Connection, episode: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("maku.convert._HELD_PAUSE", 0)
    stopping = [False]
    unlink = Path.unlink

    def held(path: Path, missing_ok: bool = False) -> None:
        if stopping[0] and path.name.endswith(WORKING):  # an antivirus looking at it, say
            raise PermissionError(13, "The process cannot access the file", str(path))
        unlink(path, missing_ok=missing_ok)

    def stop() -> bool:
        stopping[0] = True
        return True

    monkeypatch.setattr(Path, "unlink", held)

    with pytest.raises(Stopped):  # paused, as asked: not a failure
        run(conn, programs(RESULT), stop=stop)


def test_a_result_made_but_skipped_before_it_goes_in_is_thrown_away(
    conn: sqlite3.Connection, episode: Path
):
    original = episode.read_bytes()

    with pytest.raises(Stopped):
        run(conn, programs(RESULT), discard=lambda: True)

    assert episode.read_bytes() == original
    assert not list(episode.parent.glob(f"*{WORKING}"))
    assert conn.execute("SELECT plan_id FROM jobs").fetchone()[0] is None  # nothing journaled


def test_a_file_whose_results_name_is_taken_fails_before_anything_is_made(
    conn: sqlite3.Connection, tmp_path: Path
):
    library(conn, tmp_path / "Videos", ["Old/Ep01.mp4"])
    (tmp_path / "Videos" / "Old" / "Ep01.mkv").write_bytes(b"another file, beside it")
    with conn:
        conn.execute("UPDATE files SET probe = ?", (json.dumps(report(1920, 1080, codec="h264")),))
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, added_at) "
            "VALUES (1, 'reencode', 1, 'now')"
        )
    commands: list[Sequence[str]] = []

    with pytest.raises(ConvertError, match=r"^Ep01\.mkv is beside it already"):
        run(conn, programs(RESULT, commands))

    assert commands == []


def test_an_original_set_aside_takes_a_name_still_free_in_quarantine(
    conn: sqlite3.Connection, episode: Path
):
    day = Path(episode.anchor) / QUARANTINE_FOLDER / NOW.date().isoformat()
    day.mkdir(parents=True, exist_ok=True)
    for name in (episode.name, f"{episode.stem} (2).mkv"):  # two set aside earlier today
        (day / name).write_bytes(b"set aside earlier")
    original = episode.read_bytes()

    run(conn, programs(RESULT))

    assert (day / f"{episode.stem} (3).mkv").read_bytes() == original
    assert episode.read_bytes().startswith(b"converted")


def test_a_copy_an_earlier_try_left_open_says_so(
    conn: sqlite3.Connection, episode: Path, monkeypatch: pytest.MonkeyPatch
):
    unlink = Path.unlink

    def open_still(path: Path, missing_ok: bool = False) -> None:
        if path.name.endswith(WORKING):  # an ffmpeg a crash left still writes it
            raise PermissionError(13, "The process cannot access the file", str(path))
        unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", open_still)

    with pytest.raises(ConvertError, match="still in use"):
        run(conn, programs(RESULT))


def test_a_file_that_changed_since_it_was_read_waits_for_a_scan(
    conn: sqlite3.Connection, episode: Path
):
    episode.write_bytes(b"a different file now")

    with pytest.raises(ConvertError, match="changed since Maku read it"):
        run(conn, programs(RESULT))


def test_a_file_saved_over_while_it_converted_keeps_what_was_saved(
    conn: sqlite3.Connection, episode: Path
):
    def heard(progress: Progress) -> None:
        if progress.stage == "checking":  # a better copy saved over it meanwhile
            episode.write_bytes(b"a better copy")

    with pytest.raises(ConvertError, match="changed since Maku read it"):
        convert(
            conn,
            1,
            programs(RESULT),
            UHD,
            now=lambda: NOW,
            report=heard,
            stop=lambda: False,
            discard=lambda: False,
        )

    assert episode.read_bytes() == b"a better copy"
    assert not list(episode.parent.glob(f"*{WORKING}"))


def test_a_result_whose_original_is_open_in_another_app_waits_beside_it(
    conn: sqlite3.Connection, episode: Path, monkeypatch: pytest.MonkeyPatch
):
    open_in_player = open_elsewhere(monkeypatch)
    original = episode.read_bytes()
    kept = work_of(episode)

    with pytest.raises(
        InUseError, match=r"^Glass Orchard \(2018\) - S01E03 is open in another app"
    ):
        run(conn, programs(RESULT))

    assert episode.read_bytes() == original
    assert kept.read_bytes().startswith(b"converted")
    with pytest.raises(InUseError):
        put_in(conn, 1, now=NOW)  # still open

    open_in_player[0] = False
    put_in(conn, 1, now=NOW)

    assert episode.read_bytes().startswith(b"converted")
    assert not kept.exists()
    job = conn.execute("SELECT state, output_probe FROM jobs").fetchone()
    assert job["state"] == "done"
    assert json.loads(job["output_probe"])["format"]["tags"] == {"MAKU": TAG}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' sharing rules")
def test_a_player_opening_the_original_as_it_goes_in_keeps_the_result(
    conn: sqlite3.Connection, episode: Path, monkeypatch: pytest.MonkeyPatch
):
    held: list[BinaryIO] = []

    def in_use(path: Path) -> bool:
        if not held:  # free as Maku looks, and opened a moment after
            held.append(path.open("rb"))
            return False
        return True

    monkeypatch.setattr("maku.convert.in_use", in_use)
    try:
        with pytest.raises(InUseError):
            run(conn, programs(RESULT))
        assert work_of(episode).read_bytes().startswith(b"converted")  # kept, to go in later
    finally:
        for handle in held:
            handle.close()


def test_a_picture_ffprobe_couldnt_place_is_looked_at_for_interlacing(
    conn: sqlite3.Connection, tmp_path: Path
):
    library(conn, tmp_path / "Videos", ["Old/interlaced episode.mkv"])
    unsure = report(1920, 1080, codec="h264")
    cast("list[dict[str, object]]", unsure["streams"])[0].pop("field_order")
    with conn:
        conn.execute("UPDATE files SET probe = ?", (json.dumps(unsure),))
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, added_at) "
            "VALUES (1, 'reencode', 1, 'now')"
        )
    commands: list[Sequence[str]] = []

    run(conn, programs(RESULT, commands))

    [made] = [command for command in commands if "-progress" in command]
    assert made[made.index("-vf") + 1] == "bwdif=mode=send_frame,format=p010le"


def test_a_file_to_remux_found_interlaced_is_encoded_anew(conn: sqlite3.Connection, tmp_path: Path):
    library(conn, tmp_path / "Videos", ["Old/interlaced episode.mp4"])
    unsure = dict(report(1920, 1080))  # the standard's picture, in an MP4
    cast("list[dict[str, object]]", unsure["streams"])[0].pop("field_order")
    unsure["format"] = {
        **cast("dict[str, object]", unsure["format"]),
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
    }
    with conn:
        conn.execute("UPDATE files SET probe = ?", (json.dumps(unsure),))
        conn.execute(
            "INSERT INTO jobs (file_id, method, position, added_at) VALUES (1, 'remux', 1, 'now')"
        )
    commands: list[Sequence[str]] = []

    run(conn, programs(RESULT, commands))

    [made] = [command for command in commands if "-progress" in command]
    assert made[made.index("-c:v") + 1] == "hevc_nvenc"  # a filtered picture can't be copied
    assert any("bwdif=mode=send_frame" in part for part in made)


def test_a_file_at_the_standard_by_now_has_nothing_to_convert(
    conn: sqlite3.Connection, episode: Path
):
    original = episode.read_bytes()
    commands: list[Sequence[str]] = []
    with conn:  # the standard changed since it joined: 4K HEVC 10-bit is at 4K
        conn.execute("UPDATE files SET probe = ?", (json.dumps(report(3840, 2160)),))

    with pytest.raises(NothingToConvert, match="at your standard now"):  # not a failure
        run(conn, programs(RESULT, commands))

    assert commands == []
    assert episode.read_bytes() == original


def odd_sized(width: int, height: int) -> Json:
    """A report whose picture is AV1 at an odd size, as encodes of films cropped to their picture
    often are (1920x803)."""
    found = report(width, height, codec="av1")
    cast("list[dict[str, object]]", found["streams"])[0]["pix_fmt"] = "yuv420p10le"
    return found


def test_an_odd_size_is_made_even_and_checks_out(conn: sqlite3.Connection, episode: Path):
    with conn:
        conn.execute("UPDATE files SET probe = ?", (json.dumps(odd_sized(1920, 803)),))
    commands: list[Sequence[str]] = []

    run(conn, programs(report(1920, 802, tag=TAG), commands))

    [made] = [command for command in commands if "-progress" in command]
    assert made[made.index("-vf") + 1] == "crop=1920:802:0:0,format=p010le"
    assert episode.read_text().startswith("converted")  # the result is in place
    assert conn.execute("SELECT state FROM jobs").fetchone()[0] == "done"


def with_subtitles(made: Json, *codecs: str) -> Json:
    """A report with these subtitle tracks after its picture and sound."""
    tracks = [{"codec_type": "subtitle", "codec_name": codec} for codec in codecs]
    return {**made, "streams": [*cast("list[object]", made["streams"]), *tracks]}


def test_a_recordings_teletext_is_left_out_and_the_rest_checks_out(
    conn: sqlite3.Connection, episode: Path
):
    recorded = report(1920, 1080, codec="h264")
    in_ts = {**recorded, "format": {**fields.mapping(recorded, "format"), "format_name": "mpegts"}}
    recording = with_subtitles(in_ts, "dvb_subtitle", "dvb_teletext")
    with conn:
        conn.execute("UPDATE files SET probe = ?", (json.dumps(recording),))
    commands: list[Sequence[str]] = []

    run(conn, programs(with_subtitles(RESULT, "dvb_subtitle"), commands))

    [made] = [command for command in commands if "-progress" in command]
    assert "0:s:1" not in made  # MKV can't hold teletext
    assert conn.execute("SELECT state FROM jobs").fetchone()[0] == "done"


def test_programs_start_with_nothing_on_standard_input(monkeypatch: pytest.MonkeyPatch):
    started: dict[str, object] = {}

    def popen(command: list[str], **options: object) -> object:
        started.update(options)
        return object()

    monkeypatch.setattr(subprocess, "Popen", popen)

    start(["ffmpeg", "-version"])

    assert started["stdin"] == subprocess.DEVNULL


def test_a_test_play_reads_no_keys(conn: sqlite3.Connection, episode: Path):
    commands: list[Sequence[str]] = []

    run(conn, programs(RESULT, commands))

    plays = [command for command in commands if "null" in command]
    assert plays
    assert all(command[len(FAKE_FFMPEG)] == "-nostdin" for command in plays)


def test_an_original_comes_back_where_a_tidy_up_filed_its_converted_file(
    conn: sqlite3.Connection, episode: Path
):
    original = episode.read_bytes()
    run(conn, programs(RESULT))
    filed = episode.parent / "Glass Orchard (2018) - S01E03 - The Long Field.mkv"
    episode.rename(filed)  # a tidy-up named it, and its record followed
    with conn:
        conn.execute("UPDATE files SET path = ?", (str(filed),))

    restore(conn, 1, now=NOW)

    assert filed.read_bytes() == original  # the original, under the name it's filed by now
    assert not episode.exists()
    assert not list(episode.parent.glob(f"*{WORKING}"))
    assert Path(conn.execute("SELECT path FROM files").fetchone()[0]) == filed
    assert conn.execute("SELECT state FROM jobs").fetchone()[0] == "restored"


def test_an_original_set_aside_by_a_conversion_that_failed_can_come_back(
    conn: sqlite3.Connection, episode: Path
):
    original = episode.read_bytes()
    run(conn, programs(RESULT))
    with conn:  # it went wrong after the original was set aside
        conn.execute("UPDATE jobs SET state = 'failed'")

    restore(conn, 1, now=NOW)

    assert episode.read_bytes() == original


def test_putting_an_original_back_twice_says_theres_nothing_to_put_back(
    conn: sqlite3.Connection, episode: Path
):
    run(conn, programs(RESULT))
    restore(conn, 1, now=NOW)

    with pytest.raises(ConvertError, match="no converted file to put back"):
        restore(conn, 1, now=NOW)


def test_the_tag_says_what_the_file_became(conn: sqlite3.Connection, episode: Path):
    commands: list[Sequence[str]] = []

    run(conn, programs(RESULT, commands))

    [made] = [command for command in commands if "-progress" in command]
    assert f"MAKU=reencode to 1080p · Maku {__version__}" in made


def test_a_1440p_picture_is_called_1440p(conn: sqlite3.Connection, episode: Path):
    tag = f"reencode to 1440p · Maku {__version__}"  # not 4K
    with conn:
        conn.execute("UPDATE files SET probe = ?", (json.dumps(report(2560, 1440, codec="h264")),))
    commands: list[Sequence[str]] = []

    run(conn, programs(report(2560, 1440, tag=tag), commands))

    [made] = [command for command in commands if "-progress" in command]
    assert f"MAKU={tag}" in made
