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
| Blu-ray's or DVD's PCM sound, or other PCM MKV can't hold | remux, the sound made FLAC | "Blu-ray's PCM sound becomes FLAC, still lossless" |
| Other sound MKV can't hold (QuickTime's ADPCM, say) | remux, the sound made FLAC | "ADPCM sound becomes FLAC, as MKV can't hold it" |
| Subtitles MKV can't hold (teletext, closed captions, TTML) | left out | "Teletext subtitles are left out: MKV can't hold them" |
| Another codec, or HEVC 8-bit | re-encode at its own size | "H.264 becomes HEVC 10-bit", "AV1 becomes HEVC 10-bit, HDR kept" |
| Bigger than the standard | re-encode, brought down | "4K HDR: brought down to 1080p, HDR kept", "1440p: brought down to 1080p", "8K: brought down to 4K" |
| Interlaced | re-encode, deinterlaced first | "Interlaced: deinterlaced first" |

**Never bigger.** A picture at or under the standard keeps its own size, pixels and shape: a DVD
stays 720x480 with its pixel shape (an anamorphic DVD keeps its 16:9 flag), 720p stays 720p. Only
a picture bigger than the standard's frame is resized, to the largest size with its shape on screen
that fits its 16:9 frame (1920x1080 or 3840x2160), with square pixels (a 3840x1600 film becomes
1920x800 at 1080p). Sizes are called by the smallest frame they fit (`size_name`): SD (a DVD, or
1024x576), 720p, 1080p, 1440p, 4K, and 8K for anything bigger. A frame takes pictures up to 7%
wider than its 16:9 width, for cinema's own widths (4096x2160, 2048x1080, 1998x1080), and as tall
as a 16:10 picture of that width: 1920x1200 is a 1080p picture, and stays as it is at 1080p, as
does the odd 1920x1088. A new picture of an odd size (an AV1 encode of a scope film, 1920x803)
loses its last line or column: the encoders make 4:2:0 pictures in pairs of lines, and NVENC padded
1920x803 to 1920x804 (measured), which the check failed. A copied picture keeps its odd size.

**Sound is kept as it is, every track**: TrueHD and Atmos, DTS-HD MA, FLAC, PCM, AC-3 and AAC,
copied. Only what MKV can't hold changes, which only a file in another container can have: an
MKV's own tracks are ones MKV holds, and stay (`sound_way` and `subtitle_way` in
[maku/core/standard.py](../../engine/src/maku/core/standard.py), each codec tried with Maku's
ffmpeg on 2026-10-28). Blu-ray's and DVD's PCM (`pcm_bluray`, `pcm_dvd`), which ffmpeg's MKV muxer
refuses ("No wav codec tag found for codec pcm_bluray"), and any other PCM it refuses (8-bit,
unsigned, planar), become FLAC, the same samples up to 24 bits (measured: 24-bit stays 24-bit).
FLAC would keep only 24 bits of 32- and 64-bit PCM, so that stays PCM as MKV holds it
(`pcm_s32le`, `pcm_s64le`), and float PCM stays float in the byte order MKV holds (`pcm_f32le`,
`pcm_f64le`): the same samples, measured. Any other sound MKV can't hold (QuickTime's ADPCM,
Nellymoser) becomes FLAC as it plays. Subtitles, fonts and chapters are copied too: MP4's text
subtitles become SRT, as MKV can't hold them as they are, and subtitles it can't hold any way are
left out, the reasons saying so (teletext and closed captions; TTML, which ffmpeg can't read). The
result carries Maku's tag (`MAKU`: "reencode to 1080p · Maku 0.1.0").

## The command

One ffmpeg command makes each file (`-nostdin`, see [ffmpeg.md](ffmpeg.md)), the streams mapped
from the original (`-map 0:V:0` for the picture, never a cover image, then `0:a?`, each subtitle
track MKV can hold by its number, `0:s:0`…, and `0:t?`, its chapters and tags), its progress read
from `-progress pipe:1`. ffmpeg copies each stream's tags into the result, MKVToolNix's statistics
too (`BPS`, `NUMBER_OF_BYTES`…), which would describe the original: a picture made 3 Mb/s still
said its Blu-ray's 25. So every stream's are cleared (`-metadata:s BPS=`, and the others, in
either spelling). A remux copies the picture (`-c:v copy`). A re-encode filters it, in this order:

1. `bwdif=mode=send_frame` when it's interlaced: a frame for each frame, so the frame rate stays.
   A picture ffprobe can't place is looked at with `idet` first (600 frames from its middle).
   Film that was telecined to 29.97 is deinterlaced the same way, not put back to 23.976.
2. `scale=W:H:flags=lanczos,setsar=1` only when it's brought down. `scale` resizes without touching
   the colours, so an HDR picture's PQ or HLG values stay as they were. Or `crop=W:H:0:0` when
   it only loses an odd last line or column.
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
  gets a ceiling: its original picture's rate, so a new picture never comes out bigger than its
  original's. That's the stream's, or the statistics MKVToolNix and MakeMKV count as they write a
  file (`BPS`), but not in a file ffmpeg wrote (its `ENCODER` tag says "Lavf…"), whose statistics
  were copied from another, nor one that would make the stream bigger than its whole file
  (`maku/core/media.py`). Else it's the whole file's less its sound, or the whole file's where the
  sound can't be told apart. A minute of grainy 1080p made 3.7 Mb/s by ffmpeg, its tag still
  saying its original's 25, came out 80 MB from 27.5 MB with that 25 as its ceiling, and 27.8 MB
  with the file's own 3 (measured 2026-10-28; the 0.3 MB over is NVENC's buffer, nothing over an
  episode). It's never over what players expect of the size: 15 Mb/s for SD, 25 for 720p, 40 for
  1080p, 60 for 1440p, 100 for 4K, within the HEVC levels players take for those sizes (NVENC
  made 1080p at 40 level 4.1, and 1440p at 40 to 80 and 4K at 100 level 5.0, measured).
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
SD 1.5 Mb/s, 720p 3.5, 1080p 7, 1440p 11, 4K 20 (about 0.7, 1.6, 3.2, 5 and 9 GB an hour), never
more than the original's picture (read as the ceiling reads it). The sound, subtitles and fonts are
counted at what the file says of them (or 4 Mb/s a lossless track, 640 kb/s another), as they're
copied.

## See it first

The comparison's after is made by the same filters (`preview_command`), to an 8-bit PNG, at 15%,
50% or 80% of the file: deinterlaced, brought down, cut to an even size, or only made 10-bit. A
remux shows the picture as it is on both sides. An HDR picture's PNG shows its values as they are,
without tone mapping, on both sides alike.

## The check

A result takes its original's place only when it checks out (`check`, then a test play at three
points in `maku/convert.py`): as long as its original, HEVC 10-bit at the size decided, its HDR
come through, every sound track, the subtitle tracks MKV can hold, the fonts, and Maku's tag. A
file found at the standard by its turn in the queue (the standard changed since it joined) is
passed over, saying so: it's skipped, not failed, as nothing went wrong.

## Tests

No test needs a graphics card: CI runs on Windows machines without one. The decisions and commands
are tested as values (`tests/core/test_standard.py`, `tests/core/test_convert.py`), the run with
`tests/fake_ffmpeg.py` standing in for ffmpeg, and the real commands ran on the made-up clips on
the owner's PC: every result checked out (picture, HDR flags, FLAC from both PCMs, SRT from MP4's
text subtitles, a test play at three points). On 2026-10-28 they ran again on made-up clips at odd
sizes (1920x803 in FFV1 and AV1, 721x405: 1920x802 and 720x404 came out, and checked out), with
8-bit, float, 32- and 64-bit PCM and QuickTime's ADPCM in a MOV and a NUT, with TTML beside MP4's
text, at 1440p and 1920x1200, and from a file whose statistics were another's: each checked out
and played, with no statistics left in it.
