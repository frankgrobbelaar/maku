# What Maku ships beside its code

English subtitles need one thing that isn't code: a voice detector. It ships inside Maku (the
engine bundle), so nothing is downloaded for it, and it keeps its licence, which goes into
`THIRD-PARTY-NOTICES.txt` (`engine/tools/third_party_notices.py`). Whisper, the speech model the
subtitles need, is too big to ship: it's a download (`engine/src/maku/downloads.json`). The PC
check runs the voice detector once on the graphics card too, to see whether DirectML runs there
(`maku/directml.py`).

| File | What it is | Licence | SHA-256 |
| --- | --- | --- | --- |
| `pyannote-segmentation-3.0.onnx` | pyannote's speaker segmentation model 3.0, as onnx-community converted it: who speaks when, 10 s at a time, which Maku uses to find speech for English subtitles | MIT, as its model card says; the text is pyannote.audio's, CNRS (`pyannote-segmentation-3.0.LICENSE.txt`) | `057ee564753071c0b09b5b611648b50ac188d50846bff5f01e9f7bbf1591ea25` |

How it was made: `onnx/model.onnx` from
[onnx-community/pyannote-segmentation-3.0](https://huggingface.co/onnx-community/pyannote-segmentation-3.0)
at commit `733a93b6473d019a773298e08cefa686894b1854`, as it is.

Why the voice detector: it hears voices over music, where Silero's missed whole scenes
(2026-10-15, see [docs/stack/speech.md](../../../../docs/stack/speech.md)).
