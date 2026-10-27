"""English from another copy: Tidy up offers it for two copies of an episode, the queue adds the
English to the copy kept, checks it and puts it in place with both copies set aside together,
and History puts them back; copies that aren't the same cut stay as they are. ffmpeg, ffprobe and
the two copies' sound are stood in for."""

import json
import sqlite3
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

import maku.changes
from maku import __version__
from maku.changes import changes_of, recover
from maku.config import DataPaths
from maku.convert import ConvertError, Programs
from maku.core.align import RATE
from maku.core.fields import Json
from maku.core.plan import ChangeKind, in_quarantine
from maku.history import plans
from maku.queue import Queue
from maku.scan import Scanner
from maku.subtitles import hearable
from maku.tidy import ConvertingError, English, Reviewed, apply, delete, propose
from maku.tools import Tools
from tests.converting import FAKE_FFMPEG, programs
from tests.shelf import NOW, library

KEPT = "Starfall (1989)/Season 02/Starfall (1989) - S02E07 - Glass and Thunder.mkv"
OTHER = "Downloads/starfall_academy_07_dvd.mkv"
KEPT_ID, OTHER_ID = 2, 1  # the library finds them in the order of their names


def probe(height: int, codec: str, sound: list[str], subtitles: list[tuple[str, str]]) -> Json:
    """ffprobe's report on a 24-minute copy with this picture, sound and subtitles."""
    streams: list[Json] = [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": codec,
            "width": height * 16 // 9,
            "height": height,
            "sample_aspect_ratio": "1:1",
            "r_frame_rate": "24000/1001",
            "avg_frame_rate": "24000/1001",
            "pix_fmt": "yuv420p10le",
            "field_order": "progressive",
        }
    ]
    for language in sound:
        streams.append(
            {
                "index": len(streams),
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "tags": {"language": language},
            }
        )
    for kind, language in subtitles:
        streams.append(
            {
                "index": len(streams),
                "codec_type": "subtitle",
                "codec_name": kind,
                "tags": {"language": language},
            }
        )
    return {
        "streams": streams,
        "format": {"format_name": "matroska,webm", "duration": "1440.0", "size": "1100000000"},
        "chapters": [],
    }


KEPT_PROBE = probe(1080, "hevc", ["jpn"], [("ass", "ger")])
OTHER_PROBE = probe(480, "h264", ["jpn", "eng"], [("subrip", "eng")])
MERGED = probe(1080, "hevc", ["jpn", "eng"], [("ass", "ger"), ("subrip", "eng")])


@pytest.fixture
def copies(conn: sqlite3.Connection, tmp_path: Path) -> Path:
    """Two copies of an episode of a made-up series: the 1080p one Maku keeps, Japanese with
    German subtitles, and a DVD copy with English sound and subtitles too."""
    root = tmp_path / "Videos"
    library(conn, root, [KEPT, OTHER])
    with conn:
        conn.execute(
            "INSERT INTO titles (id, kind, name, year) VALUES (1, 'series', 'Starfall', 1989)"
        )
        conn.execute("UPDATE files SET title_id = 1, season = 2, episode = 7, matched = 'sure'")
        for name, report in ((KEPT, KEPT_PROBE), (OTHER, OTHER_PROBE)):
            conn.execute(
                "UPDATE files SET probe = ? WHERE path = ?", (json.dumps(report), str(root / name))
            )
    return root


def episode(seconds: float, seed: int = 1) -> np.ndarray:
    """Sound that rises and falls like an episode's: bursts of noise at made-up moments."""
    rng = np.random.default_rng(seed)
    loudness = np.repeat(rng.uniform(0.01, 1.0, round(seconds * 4)), RATE // 4)
    return (rng.standard_normal(len(loudness)) * loudness).astype(np.float32)


def hear(monkeypatch: pytest.MonkeyPatch, *, later: float = 3.0, same: bool = True) -> None:
    """The copies' sound as Maku reads it: the other copy runs `later` seconds behind the one
    kept (a studio card first), or it's another cut altogether."""
    ours = episode(300)
    theirs = np.concatenate([episode(later, seed=9), ours]) if same else episode(300, seed=2)

    def sound_of(
        ffmpeg: Sequence[str], video: Path, track: int, stop: object, *, rate: int
    ) -> np.ndarray:
        assert rate == RATE
        return theirs if "dvd" in video.name else ours

    monkeypatch.setattr("maku.merge.sound_of", sound_of)


def kit(commands: list[Sequence[str]] | None = None) -> Programs:
    return programs(MERGED, commands)


def reading() -> Programs:
    """ffprobe reading what the stand-in ffmpeg made: the copy with the English (H.264, still to
    convert), or a conversion, of the copy kept as it was or of the one with the English."""

    def read(path: Path) -> Json:
        made = path.read_bytes()
        if not made.startswith(b"converted"):
            return probe(1080, "h264", ["jpn", "eng"], [("ass", "ger"), ("subrip", "eng")])
        found = json.loads(json.dumps(MERGED if b"English" in made else KEPT_PROBE))
        found["format"]["tags"] = {"MAKU": f"reencode to 1080p · Maku {__version__}"}
        return found

    return Programs(FAKE_FFMPEG, read)


def player(monkeypatch: pytest.MonkeyPatch, *, playing: str = "Glass and Thunder") -> list[bool]:
    """A player holding a file open (one whose name holds `playing`: the copy kept, unless told)
    till the list's one item is set False."""
    still = [True]

    def in_use(path: Path) -> bool:
        return still[0] and playing in path.name

    monkeypatch.setattr("maku.convert.in_use", in_use)
    return still


def h264(conn: sqlite3.Connection, copies: Path) -> None:
    """The copy kept is H.264, so converting it to the standard is asked for too."""
    with conn:
        conn.execute(
            "UPDATE files SET probe = ? WHERE path = ?",
            (json.dumps(probe(1080, "h264", ["jpn"], [("ass", "ger")])), str(copies / KEPT)),
        )


def make_queue(
    paths: DataPaths, kit: Programs, told: list[tuple[str, str, str | None]] | None = None
) -> Queue:
    """A queue on the test's data; what it tells the app goes into `told`."""
    clock = iter(range(1, 10_000))
    heard = told if told is not None else []
    return Queue(
        paths,
        Scanner(paths, Tools(paths, items=())),
        lambda: kit,
        now=lambda: NOW + timedelta(seconds=next(clock)),
        notify=lambda title, body, link=None: heard.append((title, body, link)),
    )


def test_tidy_up_offers_the_english_of_the_copy_it_sets_aside(
    conn: sqlite3.Connection, copies: Path
):
    [duplicate] = propose(conn, day=NOW.date()).duplicates

    assert duplicate.keep.path == copies / KEPT
    assert duplicate.keep.subtitle_languages == ("ger",)
    assert duplicate.drop[0].subtitle_languages == ("eng",)
    assert duplicate.english == English(copies / OTHER, sound=True, subtitles=True)


def test_english_the_kept_copy_has_beside_it_isnt_asked_for(conn: sqlite3.Connection, copies: Path):
    (copies / KEPT).with_suffix(".en.srt").write_text("1\n", encoding="utf-8")

    [duplicate] = propose(conn, day=NOW.date()).duplicates

    assert duplicate.english == English(copies / OTHER, sound=True, subtitles=False)


def test_applied_with_its_english_the_copy_set_aside_waits_for_the_queue(
    conn: sqlite3.Connection, copies: Path
):
    changes = propose(conn, day=NOW.date()).changes
    reviewed = [
        Reviewed(str(p.change.source), p.change.kind, str(p.change.target)) for p in changes
    ]

    done = apply(conn, reviewed, now=NOW, english=[str(copies / KEPT)])

    assert done.english == ((KEPT_ID, OTHER_ID),)
    assert (copies / OTHER).is_file()  # it stays till its English is in
    assert done.quarantined == 0


def test_the_other_copys_english_goes_into_the_copy_kept_with_both_set_aside_together(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    hear(monkeypatch, later=3.0)
    commands: list[Sequence[str]] = []
    told: list[tuple[str, str, str | None]] = []
    queue = make_queue(paths, kit(commands), told)
    original = (copies / KEPT).read_bytes()

    assert queue.add_merge(KEPT_ID, OTHER_ID)
    assert queue.work_once()

    job = conn.execute("SELECT state, problem FROM jobs").fetchone()
    assert tuple(job) == ("done", None)
    assert (copies / KEPT).read_bytes() == b"kept " + original + b" with the other's English"
    assert not (copies / OTHER).exists()
    [merging] = [command for command in commands if "matroska" in command]
    assert "-ss 3.000" in " ".join(merging)  # the other copy's English, from its moment
    [plan] = plans(conn)
    assert plan.title == "Added English from another copy to Starfall · S02E07"
    assert plan.conversion is not None
    assert plan.conversion.kind == "merge"
    assert plan.quarantined == 2  # the copy kept as it was, and the other
    aside = conn.execute(
        "SELECT source, target FROM changes WHERE kind = 'quarantine' ORDER BY id"
    ).fetchall()
    assert [Path(row["source"]).name for row in aside] == [Path(KEPT).name, Path(OTHER).name]
    assert all(in_quarantine(Path(row["target"])) for row in aside)
    kept = conn.execute("SELECT probe, gone_at FROM files WHERE id = ?", (KEPT_ID,)).fetchone()
    assert (json.loads(kept["probe"]), kept["gone_at"]) == (MERGED, None)
    gone = conn.execute("SELECT gone_at FROM files WHERE id = ?", (OTHER_ID,)).fetchone()[0]
    assert gone is not None
    assert told == [
        (
            "English added from another copy",
            "Starfall · S02E07 · checked, its other copy set aside",
            "/history",
        )
    ]


def lasting(report: Json, seconds: float) -> Json:
    """The same report, for a file this long."""
    found = json.loads(json.dumps(report))
    found["format"]["duration"] = str(seconds)
    return found


def test_english_subtitles_ending_a_moment_after_the_picture_still_go_in(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    hear(monkeypatch)
    queue = make_queue(paths, programs(lasting(MERGED, 1450.0)))  # its last line, 10 s more
    queue.add_merge(KEPT_ID, OTHER_ID)

    queue.work_once()

    assert conn.execute("SELECT state FROM jobs").fetchone()[0] == "done"


def test_a_result_cut_short_never_goes_in(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    hear(monkeypatch)
    queue = make_queue(paths, programs(lasting(MERGED, 1400.0)))
    queue.add_merge(KEPT_ID, OTHER_ID)

    queue.work_once()

    job = conn.execute("SELECT state, problem FROM jobs").fetchone()
    assert job["state"] == "failed"
    assert job["problem"] == (
        "The result didn't check out: it runs 1400 s, not 1440 s. Both copies are as they were."
    )
    assert (copies / OTHER).is_file()


def test_history_puts_both_copies_back_as_they_were(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    hear(monkeypatch)
    queue = make_queue(paths, kit())
    original, other = (copies / KEPT).read_bytes(), (copies / OTHER).read_bytes()
    queue.add_merge(KEPT_ID, OTHER_ID)
    queue.work_once()
    job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]

    queue.restore(job_id)

    assert (copies / KEPT).read_bytes() == original
    assert (copies / OTHER).read_bytes() == other
    gone = conn.execute("SELECT gone_at FROM files WHERE id = ?", (OTHER_ID,)).fetchone()[0]
    assert gone is None
    probed = conn.execute("SELECT probe FROM files WHERE id = ?", (KEPT_ID,)).fetchone()[0]
    assert json.loads(probed) == KEPT_PROBE


def test_copies_that_arent_the_same_cut_stay_as_they_are_and_tidy_up_says_so(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    hear(monkeypatch, same=False)
    queue = make_queue(paths, kit())
    original = (copies / KEPT).read_bytes()
    queue.add_merge(KEPT_ID, OTHER_ID)

    queue.work_once()

    job = conn.execute("SELECT state, problem FROM jobs").fetchone()
    assert job["state"] == "failed"
    assert job["problem"].startswith("The two copies aren't the same cut")
    assert (copies / KEPT).read_bytes() == original
    assert (copies / OTHER).is_file()
    assert plans(conn) == []
    [duplicate] = propose(conn, day=NOW.date()).duplicates
    assert duplicate.english is not None
    assert duplicate.english.tried == job["problem"]
    with pytest.raises(LookupError):  # the copy kept isn't broken: it plays as it did
        queue.mark_broken(conn.execute("SELECT id FROM jobs").fetchone()[0])


def test_a_copy_kept_open_in_another_app_gets_its_english_once_its_free(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    hear(monkeypatch)
    still = player(monkeypatch)
    queue = make_queue(paths, kit())
    queue.add_merge(KEPT_ID, OTHER_ID)
    queue.work_once()
    [waiting] = queue.status().queued
    assert waiting.retry_at is not None
    assert waiting.problem is not None
    assert waiting.problem.startswith("Starfall · S02E07 is open in another app")
    assert (copies / OTHER).is_file()

    still[0] = False
    queue.retry(waiting.id)
    queue.try_waiting()

    assert conn.execute("SELECT state FROM jobs").fetchone()[0] == "done"
    assert not (copies / OTHER).exists()
    [plan] = plans(conn)
    assert plan.title == "Added English from another copy to Starfall · S02E07"


def test_the_english_goes_in_though_the_other_copy_went_while_it_waited(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    hear(monkeypatch)
    still = player(monkeypatch)
    queue = make_queue(paths, kit())
    queue.add_merge(KEPT_ID, OTHER_ID)
    queue.work_once()  # made, and waiting for the player to let go of the copy kept
    (copies / OTHER).unlink()  # the owner deleted the other copy meanwhile

    still[0] = False
    [waiting] = queue.status().queued
    queue.retry(waiting.id)
    queue.try_waiting()

    assert conn.execute("SELECT state FROM jobs").fetchone()[0] == "done"
    [plan] = plans(conn)
    assert plan.quarantined == 1  # the copy kept, as it was


def test_english_from_another_copy_goes_next_and_the_others_waiting_jobs_leave(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path
):
    queue = make_queue(paths, kit())
    with conn:  # a conversion of each copy waits already
        conn.execute("UPDATE files SET probe = ?", (json.dumps(OTHER_PROBE),))
    queue.add([KEPT_ID, OTHER_ID])

    assert queue.add_merge(KEPT_ID, OTHER_ID)
    assert not queue.add_merge(KEPT_ID, OTHER_ID)  # waiting already

    queued = queue.status().queued
    assert [(job.kind, job.file_id) for job in queued] == [
        ("merge", KEPT_ID),
        ("convert", KEPT_ID),
    ]
    assert queued[0].gpu_seconds > 0


def test_a_copy_whose_english_waits_isnt_proposed_again(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path
):
    make_queue(paths, kit()).add_merge(KEPT_ID, OTHER_ID)

    proposal = propose(conn, day=NOW.date())

    assert proposal.duplicates == ()
    assert (copies / OTHER, "Its English goes into the copy kept first") in proposal.skipped
    assert all(p.change.kind is ChangeKind.MOVE for p in proposal.changes)


def test_the_other_copy_open_in_a_player_waits_too(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    hear(monkeypatch)
    still = player(monkeypatch, playing="dvd")  # checking the dub, say
    queue = make_queue(paths, kit())
    queue.add_merge(KEPT_ID, OTHER_ID)
    queue.work_once()

    [waiting] = queue.status().queued
    assert waiting.retry_at is not None
    assert waiting.problem is not None
    assert waiting.problem.startswith("The other copy of Starfall · S02E07 is open in another app")
    still[0] = False
    queue.retry(waiting.id)
    queue.try_waiting()

    assert conn.execute("SELECT state FROM jobs").fetchone()[0] == "done"
    assert not (copies / OTHER).exists()


def test_a_conversion_of_the_copy_kept_waits_while_its_english_waits_for_the_player(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    """Both make their result beside the file: one waiting there is never thrown away, nor put
    in place as the other's."""
    hear(monkeypatch)
    h264(conn, copies)
    still = player(monkeypatch)
    queue = make_queue(paths, reading())
    queue.add([KEPT_ID])
    queue.add_merge(KEPT_ID, OTHER_ID)  # goes first

    assert queue.work_once()  # the English: made, waiting for the player
    assert not queue.work_once()  # the conversion waits for it

    still[0] = False
    [waiting, converting] = queue.status().queued
    queue.retry(waiting.id)
    queue.try_waiting()
    assert (copies / KEPT).read_bytes().endswith(b"with the other's English")
    assert queue.work_once()  # now the conversion, of the copy with the English

    assert [tuple(row) for row in conn.execute("SELECT kind, state FROM jobs ORDER BY id")] == [
        ("convert", "done"),
        ("merge", "done"),
    ]
    assert converting.kind == "convert"
    assert (copies / KEPT).read_bytes().startswith(b"converted kept ")


def test_a_result_that_isnt_the_one_made_never_goes_in(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    hear(monkeypatch)
    still = player(monkeypatch)
    queue = make_queue(paths, kit())
    queue.add_merge(KEPT_ID, OTHER_ID)
    queue.work_once()
    work = (copies / KEPT).with_name((copies / KEPT).name + ".maku-converting")
    work.write_bytes(b"something else under its name")
    still[0] = False

    [waiting] = queue.status().queued
    queue.retry(waiting.id)
    queue.try_waiting()

    job = conn.execute("SELECT state, problem FROM jobs").fetchone()
    assert job["state"] == "failed"
    assert job["problem"] == "Its copy with the English isn't there any more. Try again."
    assert (copies / OTHER).is_file()
    assert plans(conn) == []


def chain(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, *, english_first: bool
) -> tuple[Queue, dict[str, int]]:
    """The copy kept given the other's English and converted, in either order."""
    h264(conn, copies)
    queue = make_queue(paths, reading())
    for step in ("merge", "convert") if english_first else ("convert", "merge"):
        if step == "merge":
            queue.add_merge(KEPT_ID, OTHER_ID)
        else:
            queue.add([KEPT_ID])
        assert queue.work_once()
    jobs = {row["kind"]: row["id"] for row in conn.execute("SELECT id, kind FROM jobs")}
    return queue, jobs


@pytest.mark.parametrize("english_first", [True, False])
def test_an_earlier_change_waits_for_the_later_one_to_be_put_back(
    paths: DataPaths,
    conn: sqlite3.Connection,
    copies: Path,
    monkeypatch: pytest.MonkeyPatch,
    english_first: bool,
):
    hear(monkeypatch)
    original = (copies / KEPT).read_bytes()
    queue, jobs = chain(paths, conn, copies, english_first=english_first)
    first, later = ("merge", "convert") if english_first else ("convert", "merge")
    shown = {plan.conversion.kind: plan.conversion for plan in plans(conn) if plan.conversion}
    assert shown[first].replaced  # History offers to put back the later one first
    assert not shown[later].replaced

    with pytest.raises(ConvertError, match="put back the later change first"):
        queue.restore(jobs[first])
    queue.restore(jobs[later])
    queue.restore(jobs[first])

    assert (copies / KEPT).read_bytes() == original
    assert (copies / OTHER).is_file()


def test_putting_back_says_what_couldnt_come_back_and_tries_it_again(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    hear(monkeypatch)
    queue = make_queue(paths, kit())
    original = (copies / KEPT).read_bytes()
    queue.add_merge(KEPT_ID, OTHER_ID)
    queue.work_once()
    job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]
    (copies / OTHER).parent.mkdir()  # emptied, it went: a new download with the same name
    (copies / OTHER).write_bytes(b"a new download with the same name")

    stayed = queue.restore(job_id)

    assert (copies / KEPT).read_bytes() == original
    assert [Path(change.source).name for change in stayed] == [Path(OTHER).name]
    [plan] = plans(conn)
    assert (plan.undone_at, plan.quarantined) == (None, 1)  # History still offers Put back
    (copies / OTHER).unlink()

    assert queue.restore(job_id) == ()
    assert (copies / OTHER).is_file()


def test_the_other_copy_comes_back_on_its_own_when_the_copy_as_it_was_is_gone(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    hear(monkeypatch)
    queue = make_queue(paths, kit())
    queue.add_merge(KEPT_ID, OTHER_ID)
    queue.work_once()
    job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]
    [original] = [  # its drive's quarantine emptied early, to make room
        change for change in changes_of(conn, 1) if Path(change.source).name == Path(KEPT).name
    ]
    original.target.unlink()
    with conn:
        conn.execute(
            "UPDATE changes SET cleared_at = ? WHERE id = ?", (NOW.isoformat(), original.id)
        )

    queue.restore(job_id)

    assert (copies / OTHER).is_file()
    assert (copies / KEPT).read_bytes().endswith(b"with the other's English")  # it stays


def test_picture_subtitles_from_a_later_copy_leave_both_copies_as_they_are(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    dvd = probe(480, "mpeg2video", ["jpn", "eng"], [("dvd_subtitle", "eng")])
    with conn:
        conn.execute("UPDATE files SET probe = ? WHERE id = ?", (json.dumps(dvd), OTHER_ID))
    hear(monkeypatch, later=3.0)  # a studio card first
    queue = make_queue(paths, kit())
    queue.add_merge(KEPT_ID, OTHER_ID)

    queue.work_once()

    job = conn.execute("SELECT state, problem FROM jobs").fetchone()
    assert job["state"] == "failed"
    assert job["problem"].startswith("The other copy starts later, and its English subtitles")
    assert (copies / OTHER).is_file()


def test_copies_a_moment_apart_are_lined_up_as_they_are(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    hear(monkeypatch, later=0.03)  # no further apart than lining up can tell
    commands: list[Sequence[str]] = []
    queue = make_queue(paths, kit(commands))
    queue.add_merge(KEPT_ID, OTHER_ID)

    queue.work_once()

    [merging] = [command for command in commands if "matroska" in command]
    assert "-itsoffset 0.000" in " ".join(merging)  # copied as it is: no sound made anew
    assert conn.execute("SELECT state FROM jobs").fetchone()[0] == "done"


def test_english_subtitles_beside_the_copy_kept_arent_added_to_it(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    (copies / KEPT).with_suffix(".en.srt").write_text("1\n", encoding="utf-8")
    hear(monkeypatch)
    commands: list[Sequence[str]] = []
    sound_only = probe(1080, "hevc", ["jpn", "eng"], [("ass", "ger")])
    queue = make_queue(paths, programs(sound_only, commands))
    queue.add_merge(KEPT_ID, OTHER_ID)

    queue.work_once()

    [merging] = [command for command in commands if "matroska" in command]
    assert "1:a:1" in merging
    assert "1:s:0" not in merging
    assert conn.execute("SELECT state FROM jobs").fetchone()[0] == "done"


class Crash(BaseException):
    """Maku stopping all at once: the power going, say."""


def test_after_a_crash_the_other_copy_still_goes_aside_with_its_subtitles(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    subtitles = (copies / OTHER).with_suffix(".en.srt")
    subtitles.write_text("1\n", encoding="utf-8")
    hear(monkeypatch)
    moving = maku.changes._move  # pyright: ignore[reportPrivateUsage]

    def crashing(source: Path, target: Path) -> str | None:
        if source.suffix == ".srt":  # the other copy's subtitles go last
            raise Crash
        return moving(source, target)

    monkeypatch.setattr("maku.changes._move", crashing)
    queue = make_queue(paths, kit())
    queue.add_merge(KEPT_ID, OTHER_ID)
    with pytest.raises(Crash):
        queue.work_once()
    monkeypatch.setattr("maku.changes._move", moving)

    recover(conn)  # the next start
    make_queue(paths, kit()).recover()

    assert conn.execute("SELECT state FROM jobs").fetchone()[0] == "done"
    assert not (copies / OTHER).exists()
    assert not subtitles.exists()
    assert all(change.state.value == "done" for change in changes_of(conn, 1))


def test_a_copy_kept_as_an_mp4_takes_the_name_of_the_mkv_beside_it(
    paths: DataPaths, conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "Videos"
    season = "TV/Starfall (1989)/Season 02/Starfall (1989) - S02E07"
    library(conn, root, [f"{season}.mkv", f"{season}.mp4"])
    with conn:
        conn.execute(
            "INSERT INTO titles (id, kind, name, year) VALUES (1, 'series', 'Starfall', 1989)"
        )
        conn.execute("UPDATE files SET title_id = 1, season = 2, episode = 7, matched = 'sure'")
        conn.execute(
            "UPDATE files SET probe = ? WHERE path LIKE '%.mp4'", (json.dumps(KEPT_PROBE),)
        )
        conn.execute(
            "UPDATE files SET probe = ? WHERE path LIKE '%.mkv'", (json.dumps(OTHER_PROBE),)
        )
    kept, other = (
        conn.execute("SELECT id FROM files WHERE path LIKE ?", (f"%{suffix}",)).fetchone()[0]
        for suffix in (".mp4", ".mkv")
    )
    hear(monkeypatch)
    queue = make_queue(paths, kit())
    queue.add_merge(kept, other)

    queue.work_once()

    assert conn.execute("SELECT state, problem FROM jobs").fetchone()[0] == "done"
    there = sorted(path.name for path in (root / season).parent.iterdir())
    assert there == ["Starfall (1989) - S02E07.mkv"]
    assert (root / f"{season}.mkv").read_bytes().endswith(b"with the other's English")


def test_the_other_copy_changed_since_it_was_read_isnt_used(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    (copies / OTHER).write_bytes(b"made anew since Maku read it")
    hear(monkeypatch)
    queue = make_queue(paths, kit())
    queue.add_merge(KEPT_ID, OTHER_ID)

    queue.work_once()

    job = conn.execute("SELECT state, problem FROM jobs").fetchone()
    assert job["state"] == "failed"
    assert job["problem"].startswith("The other copy changed since Maku read it")
    assert (copies / OTHER).is_file()


def test_the_other_copy_is_neither_converted_nor_given_subtitles_while_its_english_waits(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path
):
    with conn:
        conn.execute(
            "UPDATE files SET probe = ?, sound = ?",
            (json.dumps(OTHER_PROBE), json.dumps(["jpn", "eng"])),
        )
    queue = make_queue(paths, kit())
    queue.add_merge(KEPT_ID, OTHER_ID)

    assert queue.add([OTHER_ID]) == 0
    assert queue.add_subtitles([OTHER_ID], "best", "jpn", "Starfall") == 0
    assert OTHER_ID not in [video.file_id for video in hearable(conn)]


def test_the_other_copy_isnt_deleted_while_its_english_goes_in(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    hear(monkeypatch)
    player(monkeypatch)
    queue = make_queue(paths, kit())
    queue.add_merge(KEPT_ID, OTHER_ID)
    queue.work_once()  # made, waiting for the player

    with pytest.raises(ConvertingError, match="is giving its English to the copy kept"):
        delete(conn, [OTHER_ID], now=NOW + timedelta(minutes=1))


def test_a_copy_gone_from_the_library_while_its_english_waits_stays_where_it_is(
    paths: DataPaths, conn: sqlite3.Connection, copies: Path, monkeypatch: pytest.MonkeyPatch
):
    hear(monkeypatch)
    still = player(monkeypatch)
    queue = make_queue(paths, kit())
    queue.add_merge(KEPT_ID, OTHER_ID)
    queue.work_once()
    gone = copies / "Deleted" / "starfall_academy_07_dvd.mkv"  # where a delete took it
    gone.parent.mkdir()
    (copies / OTHER).replace(gone)
    with conn:
        conn.execute(
            "UPDATE files SET path = ?, gone_at = ? WHERE id = ?",
            (str(gone), NOW.isoformat(), OTHER_ID),
        )

    still[0] = False
    [waiting] = queue.status().queued
    queue.retry(waiting.id)
    queue.try_waiting()

    assert conn.execute("SELECT state FROM jobs").fetchone()[0] == "done"
    assert gone.read_bytes()  # left as it was
