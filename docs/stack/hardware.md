# Any PC (the check of what a PC can do)

Maku was measured on the owner's GTX 1660 Super, and runs on other PCs too: it checks what each PC
can do, uses what works there, says what doesn't, and measures its own times on it. Nothing is
promised that the PC can't do, and no time shown is another PC's.

| Part | Where |
| --- | --- |
| What a PC has and can do, decided (pure) | `maku/core/hardware.py` |
| Looking at Windows, and what's kept about the PC | `maku/hardware.py` |
| Checking and timing it, in the background | `maku/pc_check.py` (`PcCheck`, the engine's `app.state.pc`) |
| Whether DirectML runs, in a process of its own | `maku/directml.py`, `maku check-directml` |
| The API | `GET /system`, `POST /system/test` (`maku/api/system.py`) |
| The screens | `app/src/components/this-pc.tsx`: Setup's last step, Settings › About, Convert |

## What Maku looks at

Windows lists the display adapters (`Win32_VideoController`, through one PowerShell call that
also counts the processor's cores). Only cards on the PC's bus count (`PCI\…`): not Windows'
basic or remote display. Each card's maker comes from its PCI vendor id (`VEN_10DE` NVIDIA,
`VEN_1002` AMD, `VEN_8086` Intel), its own memory from the registry
(`HardwareInformation.qwMemorySize` under the display class key: the listing's `AdapterRAM`
stops just short of 4 GB, so a card at that cap counts as having 4 GB), and NVIDIA's driver
version as NVIDIA writes it ("617.42" from Windows' "32.0.16.1742"). Intel's and AMD's with less
than 2 GB of their own are the processor's graphics. Maku works on the card of its own with the
most memory, else the processor's graphics. The processor's name comes from the registry ("Intel
Core i5-9600K"), the memory from `GetPhysicallyInstalledSystemMemory`. When PowerShell doesn't
answer, what was known stays: the cards as they were, and their times.

## The check

1. **The encoder.** Each HEVC 10-bit encoder Maku's ffmpeg has is tried on a made-up picture
   (`testsrc2`, 24 frames, `p010le`), the best card's own maker's first: NVIDIA's NVENC, AMD's
   AMF, Intel's Quick Sync. The first that starts is the one Maku converts with
   (`maku/core/convert.py`'s `ENCODERS`, see [encoding.md](encoding.md)). The LGPL build has no
   software HEVC 10-bit encoder (libx265 is GPL, kvazaar is 8-bit only, Media Foundation's is
   8-bit), so a PC without one doesn't convert; everything else in Maku works there. What the
   card's own encoder said when it didn't start is kept: words about its driver ("Driver does not
   support the required nvenc API version", "DLL amfrt64.dll failed to open") link the maker's
   driver page; others mean the card has no encoder for it. The player's H.264 encoders are
   tried too (`maku/core/player.py`'s order, Windows' own first): a Windows N edition without
   Microsoft's Media Feature Pack plays through the card's.
2. **DirectML**, which English subtitles at Best want for Whisper: ONNX Runtime runs a small
   model once on the graphics card (pyannote's voice detector, which ships inside Maku, on a
   second of silence), in a process of its own (`maku check-directml`, which answers in one line
   of JSON): a graphics driver that fails on it takes only that process with it, never the
   engine. DirectML takes the PC's high-performance card (`performance_preference`), so a laptop
   with two uses its own card, not the processor's graphics that drive the screen. Where DirectML
   doesn't start (no DirectX 12), ONNX Runtime would quietly run on the processor, and the check
   says no.

Testing the PC (Setup's last step, by itself once ffmpeg is there; "Test this PC again" there
and in Settings › About; "Test this PC" on Convert) also times the encoder making 1080p from a
made-up picture, from ffmpeg's own progress (so starting it doesn't count) over up to 480 frames
or half a minute, a slow card's speed being what it managed by then. It's kept as megapixels a
second (frames a second times the 2.07 megapixels of 1080p), the unit converting's estimates use.
An encoder that couldn't be timed keeps the time it had: no guess is kept as measured. While a job
has the card, a test only checks: its times would be the job's too.

A check shows as under way from the moment it's asked for (Windows is asked what the PC has
first), nothing in the queue starts meanwhile, and a test asked for while one runs follows it. As
the engine starts it checks the PC (without timing) when it hasn't been checked, its last check
found a part that didn't run (a card busy, or a driver mid-update, that once), or its cards or
their drivers changed. New cards (a different name or memory) are timed anew, and the old card's
times forgotten; a new driver keeps the card's times.

## What's kept

Two settings rows: `pc` (what Windows said, and what the check found) and `pc_speeds` (the
times: re-encoding's megapixels of the original a second, and subtitles' seconds of work for each
second of sound, by quality and place). A test replaces the conversion speed. Every file
re-encoded measures it again (its original's frames times its pixels, over the time from when it
began to when its result was made, so checking and putting it in place don't count; a remux only
copies, and measures nothing), and every video's subtitles their rate (a video where no one speaks
is left out): each blended into the time kept, 70 % old and 30 % new. Until anything is measured,
the times are the owner's card's, and the screens say so.

## What follows from it

- **Times for an hour of video.** Setup and Settings › About show converting's time for an hour of
  1080p and an hour of 4K, and English subtitles' for an hour of sound (Best's, then Fast's).
- **No encoder.** Convert says this PC can't convert and what still works, or that the card's
  driver may be too old, with its maker's drivers. Conversions in the queue wait, saying why,
  while subtitles and English from another copy go on (and are told when they're done).
- **English subtitles.** Best (Whisper medium) wants a card with 4 GB of its own and DirectML;
  Fast (Whisper small) 2 GB, and runs on the processor where the card hasn't that (or where
  DirectML doesn't run; when Windows doesn't say what the card has, both run on it). Best on a PC
  without the memory or DirectX 12, or a card that runs out of memory ("8007000E Not enough
  memory resources"), fails saying which, with "Make them with Fast" on the queue's card. Each
  quality's time comes from where it runs here.
- **Estimates** everywhere (Convert, the queue, Make English subtitles, the gap analysis) use
  this PC's times.

## Measured

The owner's PC (GTX 1660 Super, i5-9600K, 2026-10-27): the whole test, timing included, takes
about 5 seconds. NVENC starts, Windows' own H.264 encoder plays, and DirectML runs (loading the
voice detector and hearing a second of silence took about a second). The encoder made 178 frames a
second of the made-up 1080p picture, 370 megapixels a second, as a real 1080p H.264 file goes
(180): an hour of 1080p about 8 minutes, an hour of 4K about 32. On 2026-10-15 AMF said "DLL
amfrt64.dll failed to open." and Quick Sync "Error creating a MFX session: -9." (no AMD or Intel
graphics). Whisper medium heard a minute of an episode in 84 seconds on the processor.

On the processor, ONNX Runtime 1.24's highest graph optimisation level breaks Whisper's
half-precision layer norms ("Attempting to get index by a name which does not exist:
InsertedPrecisionFreeCast…" as it loads), so `maku/speech.py` loads it there one level below
(`ORT_ENABLE_EXTENDED`), which loads and runs as quick.

## Tests

No test needs a graphics card. `tests/fake_ffmpeg.py` answers the check's commands: encoders
the PC hasn't fail (`MAKU_FAKE_NO_ENCODERS`, `MAKU_FAKE_WHY` for what they say), and made-up
pictures take as long as `MAKU_FAKE_FPS` makes them, telling their progress when timed.
`tests/fake_engine.py` stands in for `maku check-directml` (`MAKU_FAKE_DIRECTML`: it runs, it
doesn't, or the process dies); Windows' answer is a stand-in in `PcCheck(looking=…)` (None when it
doesn't answer), and `tests/test_hardware.py` asks the real one once.
