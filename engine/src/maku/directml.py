"""DirectML, ONNX Runtime's way onto the graphics card for Whisper: which card, one call at a
time, and whether it runs on this PC at all.

In one process, DirectML breaks in two ways (the owner's PC, NVIDIA, 2026-10-15). Two threads
loading or running models at once crash the graphics driver, so every DirectML session in the
engine is made and run under LOCK, a token at a time. And a model loaded and let go of while
Whisper is loaded crashes Whisper's next step, turns or no turns: so the PC check, which loads a
model of its own to see whether DirectML runs, does it in a process of its own (`maku
check-directml`): a process of its own has DirectML to itself, and a graphics driver that fails
on it takes only that process with it.
"""

import logging
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# The PC's high-performance card: on a laptop with two, its own rather than the processor's
# graphics that drive the screen.
PROVIDER = ("DmlExecutionProvider", {"performance_preference": "high_performance"})
LOCK = threading.RLock()
# The model the check runs: pyannote's segmentation model, which ships inside Maku for speech.
_CHECKED_WITH = Path(__file__).parent / "assets" / "pyannote-segmentation-3.0.onnx"
_SAMPLES = 16_000  # a second of silence, at the model's 16 kHz


def runs(model: Path = _CHECKED_WITH) -> bool:
    """Whether DirectML runs a model on this PC's graphics card: a small one, once, on a second
    of silence (about a second all told). False where the card has no DirectX 12, or ONNX Runtime
    won't load. ONNX Runtime loads only now, so the engine starts without it."""
    try:
        import onnxruntime as ort  # loaded when first needed, see above
    except ImportError as error:
        log.info("ONNX Runtime didn't load: %s", error)
        return False
    ort.disable_telemetry_events()  # its Windows builds report use to Microsoft unless told not to
    options = ort.SessionOptions()
    options.enable_mem_pattern = False  # DirectML asks for both of these
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    try:
        with LOCK:
            session = ort.InferenceSession(str(model), options, providers=[PROVIDER])
            if "DmlExecutionProvider" not in session.get_providers():  # the processor's, then
                log.info("DirectML didn't start on this PC's graphics card")
                return False
            name = session.get_inputs()[0].name
            session.run(None, {name: np.zeros((1, 1, _SAMPLES), np.float32)})
    except Exception as error:  # ONNX Runtime raises its own kinds, all of them plain Exceptions
        log.info("DirectML doesn't run here: %s", error)
        return False
    return True
