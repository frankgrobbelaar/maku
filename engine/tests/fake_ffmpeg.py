"""Stands in for ffmpeg in tests: python fake_ffmpeg.py <ffmpeg's arguments>.

It answers the commands maku/core/convert.py builds, without converting anything:

- idet: reports a progressive picture, or an interlaced one for a file named "interlaced";
- one whole conversion: writes the file, telling its progress the way -progress does;
- a test play: says nothing, as ffmpeg does when a file plays;
- the player's stream (maku/core/player.py): writes MAKU_FAKE_CHUNKS lines naming its
  arguments to its output ("endless": one every 20 ms till it's stopped); an encoder showing it
  works on a made-up picture (maku/pc_check.py): says nothing, taking as long as MAKU_FAKE_FPS
  frames a second makes its frames (no time at all without), and tells its progress as it goes
  when it's asked to (-progress);
  subtitles copied out: writes the ASS file, and each font to its path;
- a sound track read for English subtitles (maku/speech.py): writes MAKU_FAKE_SOUND seconds of
  silence (one) as floats, at the rate asked for;
- English from another copy (maku/core/merge.py): writes the copy kept, with words for the
  English added.

MAKU_FAKE_FAIL names a step that fails instead: "encode", "play" or "frame", "convert" (one
command, 1,200 frames in), "stream" (before its first bytes), "midstream" (after them),
"subtitles", "sound" or "merge".
MAKU_FAKE_PICTURES is how many pictures a stretch of the health check's test play decodes (120).
MAKU_FAKE_NO_ENCODERS names the encoders this PC hasn't, separated by commas, and MAKU_FAKE_WHY
what each says as it doesn't start.
MAKU_FAKE_SLOW is the seconds a conversion takes over each step of its progress (none), so a test
can stop it mid-way, and the seconds a copy of subtitles takes. MAKU_FAKE_ROUNDS makes a test
play do what real ffmpeg does at some points of a file that plays well: rounding the frames'
times to the frame rate, it gives two the same one and complains of it, unless the times are
kept as the file has them (-enc_time_base demux).
"""

import os
import sys
import time
from itertools import count, pairwise
from pathlib import Path


def main() -> None:
    args = sys.argv[1:]
    fail = os.environ.get("MAKU_FAKE_FAIL", "")
    missing = os.environ.get("MAKU_FAKE_NO_ENCODERS", "").split(",")
    if "lavfi" in args:  # an encoder showing it works, on a made-up picture
        wanted = args[args.index("-c:v") + 1] if "-c:v" in args else ""
        if wanted in missing:
            why = os.environ.get("MAKU_FAKE_WHY", "No capable devices found")
            print(f"[{wanted} @ 000001d2c5f0] {why}", file=sys.stderr)
            print("Error while opening encoder: no device", file=sys.stderr)
            sys.exit(1)
        fps = float(os.environ.get("MAKU_FAKE_FPS", "0"))
        frames = int(args[args.index("-frames:v") + 1]) if "-frames:v" in args else 0
        if "-progress" in args:  # being timed: its progress, as ffmpeg tells it
            made, step = 0, max(1, frames // 10)
            while made < frames:
                made = min(frames, made + step)
                time.sleep(step / fps if fps else 0)
                print(f"frame={made}", flush=True)
                print("progress=continue", flush=True)
            print("progress=end", flush=True)
        elif fps and frames:
            time.sleep(frames / fps)
        return
    if args[-1] == "pipe:1":  # the player's stream
        stream(args, fail, missing)
        return
    if args[-3:] == ["-f", "f32le", "-"]:  # a sound track read for subtitles
        if fail == "sound":
            print("[aac @ 0] Error decoding: invalid data found", file=sys.stderr)
            sys.exit(1)
        seconds = float(os.environ.get("MAKU_FAKE_SOUND", "1"))
        rate = int(args[args.index("-ar") + 1])
        sys.stdout.buffer.write(bytes(round(seconds * rate) * 4))
        return
    if args[-3:-1] == ["-f", "ass"]:  # subtitles copied out
        if fail == "subtitles":
            print("Subtitle encoding is only possible from text to text", file=sys.stderr)
            sys.exit(1)
        for flag, path in pairwise(args):
            if flag.startswith("-dump_attachment:"):
                Path(path).write_bytes(f"font {flag}".encode())
        time.sleep(float(os.environ.get("MAKU_FAKE_SLOW", "0")))
        Path(args[-1]).write_text(f"[Script Info]\n; {' '.join(args)}\n", encoding="utf-8")
        return
    if "idet" in args:
        source = Path(args[args.index("-i") + 1])
        tff = 420 if "interlaced" in source.name else 3
        print(
            f"[Parsed_idet_0 @ 0] Multi frame detection: TFF: {tff} BFF: 0 Progressive: 150",
            file=sys.stderr,
        )
        return
    if "-progress" in args and "null" in args:  # the health check counts the pictures that came
        if fail == "play":
            print("Invalid data found when processing input", file=sys.stderr)
            sys.exit(1)
        print("[h264 @ 0] co located POCs unavailable", file=sys.stderr)  # said, and fine
        print(f"frame={os.environ.get('MAKU_FAKE_PICTURES', '120')}")
        print("progress=end")
        return
    if "-progress" in args:  # one whole conversion
        if fail == "encode":
            print("hevc_nvenc: No capable devices found", file=sys.stderr)
            sys.exit(1)
        if fail == "convert":
            print("frame=1200\nfps=24.0\nprogress=continue", flush=True)
            print("Error while decoding stream #0:0: Invalid data found", file=sys.stderr)
            sys.exit(1)
        source = Path(args[args.index("-i") + 1])
        slow = float(os.environ.get("MAKU_FAKE_SLOW", "0"))
        for frame in (10, 20, 30):
            print(f"frame={frame}\nfps=24.0\nprogress=continue", flush=True)
            time.sleep(slow)
        Path(args[-1]).write_bytes(b"converted " + source.read_bytes())
        print("frame=30\nprogress=end", flush=True)
        return
    if "-frames:v" in args and args[-1].endswith(".png"):  # a frame to compare
        if fail == "frame":
            print("Invalid data found when processing input", file=sys.stderr)
            sys.exit(1)
        Path(args[-1]).write_bytes(b"png of " + " ".join(args).encode())
        return
    if args[-3:-1] == ["-f", "matroska"] and args.count("-i") == 2:  # English from another copy
        if fail == "merge":
            print("[matroska @ 0] Error writing trailer: No space left on device", file=sys.stderr)
            sys.exit(1)
        kept = Path(args[args.index("-i") + 1])
        Path(args[-1]).write_bytes(b"kept " + kept.read_bytes() + b" with the other's English")
        return
    if "null" in args:  # a test play
        if fail == "play":
            print("Invalid data found when processing input", file=sys.stderr)
            sys.exit(1)
        if os.environ.get("MAKU_FAKE_ROUNDS") and "demux" not in args:
            print(
                "[null @ 0000] Application provided invalid, non monotonically increasing dts to "
                "muxer in stream 0: 6 >= 6",
                file=sys.stderr,
            )
        return
    print(f"fake_ffmpeg doesn't know {args}", file=sys.stderr)
    sys.exit(2)


def stream(args: list[str], fail: str, missing: list[str]) -> None:
    if args[args.index("-c:v") + 1] in missing:
        print("Error while opening encoder: no device", file=sys.stderr)
        sys.exit(1)
    if fail == "stream":
        print("[matroska @ 0] Invalid data found when processing input", file=sys.stderr)
        sys.exit(1)
    chunks = os.environ.get("MAKU_FAKE_CHUNKS", "3")
    numbers = count() if chunks == "endless" else range(int(chunks))
    for n in numbers:
        sys.stdout.buffer.write(f"fmp4 {n}: {' '.join(args)}\n".encode())
        sys.stdout.buffer.flush()
        if chunks == "endless":
            time.sleep(0.02)
    if fail == "midstream":
        print("[hevc @ 0] Error while decoding stream #0:0: Invalid data found", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
