"""The tools Maku downloads: ffmpeg on first run, checked, unpacked and found again, and the
speech models, file by file, the first time they're wanted."""

import hashlib
import io
import re
import zipfile
from dataclasses import replace
from pathlib import Path
from urllib.error import URLError

import pytest

from maku.config import DataPaths
from maku.tools import Download, File, Tools, manifest

PROGRAM = "ffprobe.exe"


def archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        for name, data in files.items():
            zipped.writestr(name, data)
    return buffer.getvalue()


BUILD = archive(
    {
        "ffmpeg-n9.0-win64-lgpl-shared/bin/ffprobe.exe": b"probe",
        "ffmpeg-n9.0-win64-lgpl-shared/bin/ffmpeg.exe": b"mpeg",
        "ffmpeg-n9.0-win64-lgpl-shared/bin/avcodec-63.dll": b"codecs",
        "ffmpeg-n9.0-win64-lgpl-shared/doc/ffmpeg.html": b"docs",
    }
)


def listing(data: bytes, version: str = "9.0.2") -> Download:
    """The ffmpeg entry, pointing at `data` instead of the real build."""
    ffmpeg = next(item for item in manifest() if item.id == "ffmpeg")
    return replace(ffmpeg, version=version, size=len(data), sha256=hashlib.sha256(data).hexdigest())


def serving(data: bytes):
    def fetch(url: str) -> io.BytesIO:
        return io.BytesIO(data)

    return fetch


def offline(url: str) -> io.BytesIO:
    raise URLError("No connection could be made")


def downloaded(tools: Tools, tool: str = "ffmpeg") -> None:
    tools.start(tool)
    tools.wait(tool, timeout=10)


def test_the_list_says_what_each_download_is_and_where_it_comes_from():
    items = manifest()

    assert [item.id for item in items] == ["webview2", "ffmpeg", "speech-best", "speech-fast"]
    for item in items:
        addresses = [each.url for each in item.files] if item.files else [item.url]
        assert all((address or "").startswith("https://") for address in addresses)
        assert all((item.name, item.purpose, item.licence, item.home))
    for item in (item for item in items if item.by == "maku" and not item.files):
        assert (item.size or 0) > 0
        assert re.fullmatch(r"[0-9a-f]{64}", item.sha256 or "")
        assert item.keep
    for item in (item for item in items if item.files):
        assert item.size == sum(each.size for each in item.files)
        assert all(re.fullmatch(r"[0-9a-f]{64}", each.sha256) for each in item.files)
        assert all(each.size > 0 for each in item.files)


def test_the_speech_models_are_fetched_when_asked_for_from_one_pinned_version():
    models = [item for item in manifest() if item.id.startswith("speech-")]

    assert [item.when for item in models] == ["asked", "asked"]
    for item in models:
        assert item.licence == "MIT"
        # Hugging Face keeps every commit: a file named by one never changes.
        assert all(re.search(r"/resolve/[0-9a-f]{40}/", each.url) for each in item.files)
        names = {each.name for each in item.files}
        assert {"config.json", "generation_config.json", "vocab.json"} <= names
        assert any(name.startswith("encoder_model") for name in names)
        assert any(name.startswith("decoder_model_merged") for name in names)


def test_ffmpeg_is_pinned_to_one_build_that_stays_online():
    ffmpeg = next(item for item in manifest() if item.id == "ffmpeg")

    # BtbN keeps each month's last build for two years; "latest" changes every day.
    assert ffmpeg.url is not None
    assert "/autobuild-" in ffmpeg.url
    assert "latest" not in ffmpeg.url
    assert ffmpeg.licence == "LGPL-2.1-or-later"


def test_only_makus_own_downloads_are_offered_by_the_engine(paths: DataPaths):
    tools = Tools(paths, fetch=serving(BUILD))

    assert [item.id for item, _ in tools.status()] == ["ffmpeg", "speech-best", "speech-fast"]
    with pytest.raises(KeyError):
        tools.start("webview2")


def test_a_tool_is_downloaded_checked_and_unpacked_into_the_data_folder(paths: DataPaths):
    tools = Tools(paths, items=(listing(BUILD),), fetch=serving(BUILD))
    assert tools.path("ffprobe") is None

    downloaded(tools)

    [(_, progress)] = tools.status()
    assert progress.state == "ready"
    assert progress.done == len(BUILD)
    assert tools.path("ffprobe") == paths.tools / "ffmpeg" / PROGRAM
    assert (paths.tools / "ffmpeg" / "avcodec-63.dll").read_bytes() == b"codecs"
    assert not (paths.tools / "ffmpeg" / "ffmpeg.html").exists()  # only the bin folder is kept
    assert [file.name for file in paths.tools.iterdir()] == ["ffmpeg"]  # no download left behind


def test_a_download_that_doesnt_match_the_list_is_thrown_away(paths: DataPaths):
    tampered = BUILD + b"!"
    tools = Tools(paths, items=(listing(BUILD),), fetch=serving(tampered))

    downloaded(tools)

    [(_, progress)] = tools.status()
    assert progress.state == "failed"
    assert progress.problem == (
        "The ffmpeg download didn't match what Maku expects, so Maku didn't use it. "
        "Try again; if it happens again, the file online has changed."
    )
    assert tools.path("ffprobe") is None
    assert not any(paths.tools.iterdir())


def test_no_connection_says_so_and_a_retry_works(paths: DataPaths):
    item = listing(BUILD)
    tools = Tools(paths, items=(item,), fetch=offline)

    downloaded(tools)

    [(_, progress)] = tools.status()
    assert progress.state == "failed"
    assert progress.problem == (
        "Maku couldn't download ffmpeg: No connection could be made. "
        "Check the internet connection, then try again."
    )

    retry = Tools(paths, items=(item,), fetch=serving(BUILD))
    downloaded(retry)
    assert retry.path("ffprobe") is not None


def test_an_archive_cant_write_outside_the_tools_folder(paths: DataPaths):
    sneaky = archive({"ffmpeg/bin/ffprobe.exe": b"probe", "ffmpeg/bin/../../../escaped.txt": b"x"})
    tools = Tools(paths, items=(listing(sneaky),), fetch=serving(sneaky))

    downloaded(tools)

    [(_, progress)] = tools.status()
    assert progress.state == "failed"
    assert "unsafe" in (progress.problem or "")
    assert not (paths.root / "escaped.txt").exists()
    assert not (paths.root.parent / "escaped.txt").exists()


def test_a_newer_build_in_the_list_replaces_the_one_installed(paths: DataPaths):
    downloaded(Tools(paths, items=(listing(BUILD),), fetch=serving(BUILD)))
    newer = archive({"ffmpeg-n9.1/bin/ffprobe.exe": b"newer probe"})
    tools = Tools(paths, items=(listing(newer, version="9.1.0"),), fetch=serving(newer))

    [(_, before)] = tools.status()
    assert before.state == "missing"  # the installed build isn't the one listed any more
    downloaded(tools)

    assert (paths.tools / "ffmpeg" / PROGRAM).read_bytes() == b"newer probe"
    assert not (paths.tools / "ffmpeg" / "avcodec-63.dll").exists()


def test_a_development_copy_of_ffmpeg_can_stand_in(
    paths: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    own = tmp_path / "ffmpeg-bin"
    own.mkdir()
    (own / PROGRAM).write_bytes(b"probe")
    monkeypatch.setenv("MAKU_FFMPEG_DIR", str(own))

    tools = Tools(paths, items=(listing(BUILD),), fetch=offline)

    [(_, progress)] = tools.status()
    assert progress.state == "ready"
    assert tools.path("ffprobe") == own / PROGRAM


class Dropping(io.BytesIO):
    """A download that stops partway, as when the connection drops."""

    def read(self, size: int | None = -1, /) -> bytes:
        if self.tell() > 0:
            raise ConnectionResetError(10054, "An existing connection was forcibly closed")
        return super().read(10)


def test_a_connection_dropping_mid_download_says_so(paths: DataPaths):
    tools = Tools(paths, items=(listing(BUILD),), fetch=lambda url: Dropping(BUILD))

    downloaded(tools)

    [(_, progress)] = tools.status()
    assert progress.state == "failed"
    assert progress.problem == (
        "Maku couldn't download ffmpeg: the connection dropped "
        "(An existing connection was forcibly closed). "
        "Check the internet connection, then try again."
    )
    assert not any(paths.tools.iterdir())


def test_anything_unexpected_still_ends_the_download_with_a_way_on(paths: DataPaths):
    def odd(url: str) -> io.BytesIO:
        raise ValueError("unknown url type")

    tools = Tools(paths, items=(listing(BUILD),), fetch=odd)

    downloaded(tools)

    [(_, progress)] = tools.status()
    assert progress.state == "failed"  # never stuck at "downloading"
    assert progress.problem == "Maku couldn't get ffmpeg (unknown url type). Try again."


def test_a_tool_that_stopped_working_is_offered_again(paths: DataPaths):
    tools = Tools(paths, items=(listing(BUILD),), fetch=serving(BUILD))
    downloaded(tools)

    tools.broken("ffmpeg")

    [(_, progress)] = tools.status()
    assert progress.state == "missing"
    assert tools.path("ffprobe") is None
    downloaded(tools)
    assert tools.path("ffprobe") == paths.tools / "ffmpeg" / PROGRAM


def test_a_tool_missing_one_of_its_files_is_offered_again(paths: DataPaths):
    tools = Tools(paths, items=(listing(BUILD),), fetch=serving(BUILD))
    downloaded(tools)

    (paths.tools / "ffmpeg" / "avcodec-63.dll").unlink()  # as an antivirus might

    [(_, progress)] = tools.status()
    assert progress.state == "missing"
    assert tools.path("ffprobe") is None


def test_a_development_copy_is_never_thrown_out(
    paths: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    own = tmp_path / "ffmpeg-bin"
    own.mkdir()
    (own / PROGRAM).write_bytes(b"probe")
    monkeypatch.setenv("MAKU_FFMPEG_DIR", str(own))
    tools = Tools(paths, items=(listing(BUILD),), fetch=offline)

    tools.broken("ffmpeg")

    assert (own / PROGRAM).exists()
    assert tools.path("ffprobe") == own / PROGRAM


MODEL_FILES = {"config.json": b"{}", "encoder_model.onnx": b"encoder" * 50, "vocab.json": b"[]"}


def model_listing(files: dict[str, bytes] = MODEL_FILES) -> Download:
    """A speech model that comes as several files, at made-up addresses."""
    listed = tuple(
        File(name, f"https://models.test/{name}", len(data), hashlib.sha256(data).hexdigest())
        for name, data in files.items()
    )
    total = sum(each.size for each in listed)
    return Download(
        "speech-test",
        "Whisper test",
        "1",
        "Hears.",
        "MIT",
        "https://models.test",
        None,
        total,
        None,
        None,
        "maku",
        "asked",
        listed,
    )


class Serving:
    """The model's files by address, counting what's fetched."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.fetched: list[str] = []

    def __call__(self, url: str) -> io.BytesIO:
        name = url.rsplit("/", 1)[1]
        self.fetched.append(name)
        return io.BytesIO(self.files[name])


def test_a_model_is_fetched_file_by_file_each_checked(paths: DataPaths):
    tools = Tools(paths, items=(model_listing(),), fetch=Serving(MODEL_FILES))
    assert tools.folder("speech-test") is None

    downloaded(tools, "speech-test")

    [(_, progress)] = tools.status()
    assert progress.state == "ready"
    assert progress.done == sum(len(data) for data in MODEL_FILES.values())
    folder = paths.tools / "speech-test"
    assert tools.folder("speech-test") == folder
    assert {name: (folder / name).read_bytes() for name in MODEL_FILES} == MODEL_FILES
    assert [file.name for file in paths.tools.iterdir()] == ["speech-test"]


def test_a_file_that_doesnt_match_fails_the_model_and_a_retry_fetches_only_what_is_missing(
    paths: DataPaths,
):
    tampered = Serving({**MODEL_FILES, "encoder_model.onnx": b"not the model"})
    tools = Tools(paths, items=(model_listing(),), fetch=tampered)

    downloaded(tools, "speech-test")

    [(_, progress)] = tools.status()
    assert progress.state == "failed"
    assert progress.problem is not None
    assert progress.problem.startswith("The Whisper test download didn't match")
    assert tools.folder("speech-test") is None

    again = Serving(MODEL_FILES)
    retry = Tools(paths, items=(model_listing(),), fetch=again)
    downloaded(retry, "speech-test")

    assert retry.folder("speech-test") == paths.tools / "speech-test"
    assert again.fetched == ["encoder_model.onnx", "vocab.json"]  # config.json came whole before


def test_a_model_missing_a_file_is_offered_again(paths: DataPaths):
    tools = Tools(paths, items=(model_listing(),), fetch=Serving(MODEL_FILES))
    downloaded(tools, "speech-test")

    (paths.tools / "speech-test" / "vocab.json").unlink()

    [(_, progress)] = tools.status()
    assert progress.state == "missing"
    assert tools.folder("speech-test") is None


def test_a_development_copy_of_a_model_can_stand_in(
    paths: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    own = tmp_path / "whisper"
    own.mkdir()
    monkeypatch.setenv("MAKU_SPEECH_TEST_DIR", str(own))

    tools = Tools(paths, items=(model_listing(),), fetch=offline)

    [(_, progress)] = tools.status()
    assert progress.state == "ready"
    assert tools.folder("speech-test") == own
