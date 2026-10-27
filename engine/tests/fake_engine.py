"""Stands in for the engine's own process in tests: python fake_engine.py check-directml.

It says whether DirectML runs, after a line of ONNX Runtime's own words, as `maku
check-directml` does. MAKU_FAKE_DIRECTML says what happens: "runs" (the default); "no", it
doesn't run here; or "crash", the process ends the way a graphics driver failing ends one,
saying nothing.
"""

import json
import os
import sys


def main() -> None:
    what = os.environ.get("MAKU_FAKE_DIRECTML", "runs")
    if what == "crash":
        os._exit(3)  # as an abort does: no answer at all
    if sys.argv[1] != "check-directml":
        sys.exit(2)
    print("*************** EP Error ***************")  # ONNX Runtime talks on standard output
    print(json.dumps({"runs": what == "runs"}))


if __name__ == "__main__":
    main()
