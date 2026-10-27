# Encoding (the standard, ffmpeg's command, the encoders)

Every video goes to the library standard: HEVC 10-bit in an MKV, no bigger than the standard's
size. The owner chooses the standard on Convert and in Settings, and it's a top, not a target:

| Standard | What it means |
| --- | --- |
| **4K** (the first choice) | 4K stays 4K, with its HDR. Nothing is made bigger than it is. |
| **1080p** | 4K comes down to 1080p to save room, its HDR kept. Nothing is made bigger. |

[maku/core/standard.py](../../engine/src/maku/core/standard.py) decides what each file needs
(`decide`), [maku/core/convert.py](../../engine/src/maku/core/convert.py) builds the ffmpeg
command (`recipe`, `one_command`) and checks the result (`check`), and
[maku/convert.py](../../engine/src/maku/convert.py) runs it, checks it and puts it in place.
The setting is `standard` (`"4k"` or `"1080p"`, `maku/api/settings.py`).

## What each file gets

| The file | What it gets | Its reasons, as Convert and the details card say them |
| --- | --- | --- |
| HEVC 10-bit, progressive, in MKV, no bigger than the standard | renamed only | "Already HEVC 10-bit in MKV: only renamed" |
| The same in MP4 (or an AVI, a TS) | remux: the picture copied | "MP4 becomes MKV" |
| Blu-ray's or DVD's PCM sound | remux, the sound made FLAC | "Blu-ray's PCM sound becomes FLAC, still lossless" |
| Another codec, or HEVC 8-bit | re-encode at its own size | "H.264 becomes HEVC 10-bit", "AV1 becomes HEVC 10-bit, HDR kept" |
| Bigger than the standard | re-encode, brought down | "4K HDR: brought down to 1080p, HDR kept", "8K: brought down to 4K" |
| Interlaced | re-encode, deinterlaced first | "Interlaced: deinterlaced first" |

**Never bigger.** A picture at or under the standard keeps its own size, pixels and shape: a DVD
stays 720x480 with its pixel shape (an anamorphic DVD keeps its 16:9 flag), 720p stays 720p. Only
a picture bigger than the standard's 16:9 frame (1920x1080 or 3840x2160) is resized, to the largest
size with its shape on screen that fits the frame, with square pixels (a 3840x1600 film becomes
1920x800 at 1080p). Up to 7% over a frame still counts as its size, for cinema's own widths
(4096x2160, 2048x1080, 1998x1080) and the odd 1920x1088. Sizes are called by the smallest frame
they fit: SD (up to 1024x576), 720p, 1080p, 4K, 8K (`size_name`).

**Sound is kept as it is, every track**: TrueHD and Atmos, DTS-HD MA, FLAC, PCM, AC-3 and AAC,
copied. Only what MKV can't hold changes: Blu-ray's and DVD's PCM (`pcm_bluray`, `pcm_dvd`),
which ffmpeg's MKV muxer refuses ("No wav codec tag found for codec pcm_bluray"), become FLAC,
still lossless (24-bit stays 24-bit). Subtitles, fonts and chapters are copied too (MP4's text
subtitles become SRT, as MKV can't hold them as they are), with Maku's tag (`MAKU`: "reencode to
1080p · Maku 0.1.0").

## The command

One ffmpeg command makes each file (`-nostdin`, see [ffmpeg.md](ffmpeg.md)), every stream mapped
from the original (`-map 0:V:0` for the picture, never a cover image, then `0:a?`, `0:s?`, `0:t?`,
its chapters and tags), its progress read from `-progress pipe:1`. A remux copies the picture
(`-c:v copy`). A re-encode filters it, in this order:

1. `bwdif=mode=send_frame` when it's interlaced: a frame for each frame, so the frame rate stays.
   A picture ffprobe can't place is looked at with `idet` first (600 frames from its middle).
   Film that was telecined to 29.97 is deinterlaced the same way, not put back to 23.976.
2. `scale=W:H:flags=lanczos,setsar=1` only when it's brought down. `scale` resizes without touching
   the colours, so an HDR picture's PQ or HLG values stay as they were.
3. `format=p010le`: 10-bit 4:2:0, what the encoders take.
4. `setparams=color_primaries=…:color_trc=…:colorspace=…:range=tv` for an HDR picture.

**HDR stays HDR.** A picture is HDR when its transfer is PQ (`smpte2084`: HDR10, and Dolby
Vision's HDR10 base) or HLG (`arib-std-b67`). ffmpeg 9 takes the colours it writes from the
frames, not from `-color_primaries` or `-color_trc` on the command line (measured 2026-10-27:
those two options came out "unknown", while `setparams` came through), so Maku sets them on the
frames, from the original's own (BT.2020 where it leaves them unsaid). The mastering display and
light levels (HDR10's MaxCLL and MaxFALL) ride on the frames as side data: NVENC writes them into
the new picture and the MKV carries them (measured on an HDR10 clip that had them). The check
fails a result whose transfer didn't come through ("Its HDR didn't come through").

**Dolby Vision.** A remux or a rename keeps Dolby Vision whole. A new picture can't carry its own
layer: the picture under it is kept (HDR10 for profiles 7 and 8.1, HLG for 8.4), the reasons say so
("Dolby Vision's own layer can't be carried over: its HDR10 picture is kept"), and the result is
cleaned of anything that would claim Dolby Vision without it (`-bsf:v dovi_rpu=strip=1`). A picture
that is only right with Dolby Vision (profile 5, whose base layer is in Dolby's own colours,
compatibility id 0) is never made anew: brought down or re-encoded, its colours would be wrong, so
it stays as it is ("4K Dolby Vision: kept as it is, as a new picture would spoil its colours").
ffprobe tells Dolby Vision by its configuration record (`side_data_list`) or, in an MP4, its
`dvhe`/`dvh1` tag (`maku/core/media.py`). No Dolby Vision file was at hand to test with: the
commands are tested as values, and the `dovi_rpu` filter on an ordinary picture.

## The encoders

NVIDIA's NVENC, set for live action:

```
-c:v hevc_nvenc -preset p6 -tune hq -rc vbr -cq 21 -b:v 0 -spatial-aq 1 -profile:v main10
-maxrate <the original picture's bits a second> -bufsize <twice that>
```

- **A ceiling of its own.** In VBR with `-b:v 0`, NVENC quietly holds the bit rate to its preset's
  own average (about 10 Mb/s at 1080p, 20 at 4K) unless it's given `-maxrate`: at constant
  quality 20 a detailed clip came out 18.6 MB with no ceiling and 25.9 MB with one. So each file
  gets a ceiling: its original picture's rate (the stream's, or MKVToolNix's `BPS` statistics;
  else the whole file's), so a new picture never comes out bigger than its original's. It's never
  over what players expect of the size: 15 Mb/s for SD, 25 for 720p, 40 for 1080p, 100 for 4K,
  within the HEVC levels players take for those sizes (NVENC picks the level from the ceiling:
  4.1 for 1080p at 40, measured).
- **Constant quality 21** (the owner asked for 20 to 21). On a detailed, lightly grainy made-up
  1080p clip (16 Mb/s H.264): 19 gave 28.7 MB and VMAF 96.0, **20** 25.9 MB and 95.3, **21**
  23.4 MB and 94.6, 22 21.0 MB and 93.7, 23 18.8 MB and 92.8. 21 keeps the picture as good as
  the eye needs at a tenth less than 20.
- **Preset p6, spatial AQ.** p5 was 37% quicker (244 frames a second against 178) for the same
  size and score, p7 8% slower for nothing; temporal AQ, B-frames as references, lookahead and
  two passes changed neither size nor score here and cost up to 6% speed. Spatial AQ moves bits
  into flat and dark areas, where live action shows blocks first: VMAF scores it a little lower
  (it measures the bits moved away), the eye a little better.
- Turing (GTX 16) encodes HEVC 10-bit; it has no AV1 encoder, and decodes no AV1 on the card.

AMD's and Intel's, for other PCs (`maku/core/convert.py`'s `ENCODERS`), set to look as good:
AMF in constant QP 20 and 22 (`-usage transcoding -quality quality`), Quick Sync at global quality
21 (`-preset slower`), both `main10`. They keep to their quality without a ceiling. Neither has
been measured on a real card: the check finds which one starts ([hardware.md](hardware.md)).

The LGPL ffmpeg has no HEVC 10-bit encoder on the processor (libx265 is GPL), so a PC without one
on its card doesn't convert; everything else in Maku works there.

**Decoding stays on the processor.** Decoding on the card (`-hwaccel d3d11va`) was no quicker
for 1080p and 4K H.264 (NVENC is the slow part), and only 12% quicker bringing 4K HEVC down to
1080p, for a second way a file can fail. ffmpeg's own decoders read everything, AV1 included
(libdav1d, which the GTX 16 cards can't decode).

## Measured speeds and sizes

On the owner's PC (GTX 1660 Super, i5-9600K, 2026-10-27), with the command above on made-up
grainy clips (decoding included, steady frames a second once started):

| Original | Made | Frames a second | Megapixels a second |
| --- | --- | --- | --- |
| 1080p H.264 | 1080p | 180 | 373 |
| 720p H.264 | 720p | 387 | 357 |
| DVD (720x480, 29.97, interlaced) | the same, deinterlaced | 984 | 340 |
| 4K H.264 | 4K | 46 | 381 |
| 4K HEVC 10-bit HDR10 | 1080p | 56 | 461 |
| 1080p AV1 10-bit HDR10 | 1080p | 181 | 375 |

The work follows the pixels read, so this PC's speed is kept as one number, megapixels of the
original's picture a second (`Speeds.megapixels`, 373 till the PC is timed): an hour of 1080p
takes about 8 minutes, an hour of 4K about 32. The PC check times it on a made-up 1080p picture
(178 frames a second here, 370 megapixels) and every re-encode measures it again
([hardware.md](hardware.md)).

Sizes can't be measured without real video, and real video's size goes with its grain. Until
Maku has made a file, a new picture is reckoned at what live action usually comes to at constant
quality 21 (`PICTURE_RATES` in [maku/core/estimate.py](../../engine/src/maku/core/estimate.py)):
SD 1.5 Mb/s, 720p 3.5, 1080p 7, 4K 20 (about 0.7, 1.6, 3.2 and 9 GB an hour), never more than the
original's picture. The sound, subtitles and fonts are counted at what the file says of them (or
4 Mb/s a lossless track, 640 kb/s another), as they're copied.

## See it first

The comparison's after is made by the same filters (`preview_command`), to an 8-bit PNG, at 15%,
50% or 80% of the file: deinterlaced, brought down, or only made 10-bit. A remux shows the picture
as it is on both sides. An HDR picture's PNG shows its values as they are, without tone mapping,
on both sides alike.

## Tests

No test needs a graphics card: CI runs on Windows machines without one. The decisions and commands
are tested as values (`tests/core/test_standard.py`, `tests/core/test_convert.py`), the run with
`tests/fake_ffmpeg.py` standing in for ffmpeg, and the real commands ran on the made-up clips on
the owner's PC: every result checked out (picture, HDR flags, FLAC from both PCMs, SRT from MP4's
text subtitles, a test play at three points).
