"""Whether DirectML runs on this PC's graphics card: the PC check's look, for English subtitles."""

from pathlib import Path

from maku import directml


def test_a_model_that_wont_load_says_directml_isnt_here(tmp_path: Path):
    broken = tmp_path / "not a model.onnx"
    broken.write_bytes(b"not a model")

    assert directml.runs(broken) is False


def test_the_model_it_checks_with_ships_inside_maku():
    assert directml.runs.__defaults__ is not None
    [model] = directml.runs.__defaults__
    assert isinstance(model, Path)
    assert model.is_file()
