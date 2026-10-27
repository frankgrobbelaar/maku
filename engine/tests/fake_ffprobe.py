"""Stands in for ffprobe in tests: python fake_ffprobe.py [--broken] <ffprobe's arguments> <file>.

Answers with a report for a 720x540 HEVC 10-bit episode. For files whose name holds "broken"
it fails like ffprobe, for "fault" it crashes the way Windows ends a program, and for "stuck" it
never answers. With --broken it fails at everything, `-version` too, without a word: like an
ffprobe missing one of its DLLs.
"""

import json
import os
import sys
import time
from pathlib import Path

REPORT = {
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "hevc",
            "width": 720,
            "height": 540,
            "sample_aspect_ratio": "1:1",
            "display_aspect_ratio": "4:3",
            "r_frame_rate": "24000/1001",
            "avg_frame_rate": "24000/1001",
            "pix_fmt": "yuv420p10le",
            "field_order": "progressive",
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 2,
            "tags": {"language": "jpn"},
        },
    ],
    "format": {"format_name": "matroska,webm", "duration": "1244.202000", "size": "130000000"},
    "chapters": [],
}


ACCESS_VIOLATION = -1073741819  # 0xC0000005, the code Windows gives a program that crashed


def main() -> None:
    if "--broken" in sys.argv:
        sys.exit(1)
    if "-version" in sys.argv:
        print("ffprobe version n9.0.2 (a stand-in)")
        return
    file = Path(sys.argv[-1])
    if "stuck" in file.name:
        time.sleep(60)
    if "fault" in file.name:
        print("Something went wrong inside ffprobe", file=sys.stderr, flush=True)
        os._exit(ACCESS_VIOLATION)
    if "broken" in file.name:
        print(f"{file}: Invalid data found when processing input", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(REPORT))


if __name__ == "__main__":
    main()
