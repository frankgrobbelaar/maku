# ffmpeg (reading and converting video)

[ffmpeg](https://ffmpeg.org) 9.0.2 reads what each video holds (`ffprobe`) and does the conversion
work: decoding, deinterlacing, bringing pictures down to the standard, and encoding HEVC 10-bit
with the graphics card's encoder (NVENC, AMF or Quick Sync: [encoding.md](encoding.md),
[hardware.md](hardware.md)). Maku doesn't
ship it: it downloads one pinned build the first time it starts, from the list
in [engine/src/maku/downloads.json](../../engine/src/maku/downloads.json), the same list the
installer shows (see [releasing.md](../releasing.md)).

## Which build, and why

- **BtbN's LGPL shared build for Windows** (`ffmpeg-n9.0.2-…-win64-lgpl-shared-9.0.zip`,
  77 MB): the release branch, built with NVENC, AMF and Quick Sync, zimg and libdav1d, and
  nothing under the GPL, so Maku's MIT code may drive it. The shared build keeps ffmpeg's
  libraries as separate DLLs. Without the GPL's libx265 there's no HEVC 10-bit encoder on the
  processor, so a PC without one on its graphics card doesn't convert.
- **Pinned to a month's last build.** BtbN keeps the last build of each month for two years, while
  "latest" changes daily. `downloads.json` names one such build with its size and SHA-256, and
  Maku uses the download only when both match.
- **Downloaded from BtbN, not from Maku.** The PC fetches it from where it's published, with
  its licence and source there.

The encoding measurements of 2026-10-27 used this build ([encoding.md](encoding.md)): bwdif,
Lanczos, HDR10's colours and light levels, FLAC from Blu-ray's and DVD's PCM, and NVENC HEVC 10-bit
all ran without trouble on the GTX 1660 Super.

## Where it lives

`%LOCALAPPDATA%\Maku\tools\ffmpeg\` holds the build's `bin` folder (ffmpeg.exe, ffprobe.exe and
their DLLs) and `maku-download.json`, which names the build and every file unpacked from it. When
`downloads.json` moves to a new build, the next start sees the difference and offers the download
again; the new build replaces the old one. A file that goes missing (an antivirus, say) also makes
ffmpeg "missing" again, and so does an ffprobe that can't even say its version: a scan then stops
without marking any file, and Setup offers the download. A file that makes ffprobe crash while
ffprobe itself still works is that file's problem, so one bad file never blocks a scan.
[maku/tools.py](../../engine/src/maku/tools.py) does the downloading, checking and unpacking, and
finds the programs (`Tools.path("ffprobe")`).

In development, set `MAKU_FFMPEG_DIR` to a folder holding `ffprobe.exe` and `ffmpeg.exe` to skip
the download.

## Running it

Maku runs ffmpeg and ffprobe as child processes with `CREATE_NO_WINDOW`, so no console window
flashes, and reads ffprobe's JSON (`-show_format -show_streams -show_chapters`), which
[maku/core/media.py](../../engine/src/maku/core/media.py) turns into a `MediaInfo`.

**Nothing on standard input.** ffmpeg looks for key presses (q to quit) on standard input. Under
Maku's window the engine's standard input is a pipe from the app, which the engine reads to know
when the app closes, and Windows makes ffmpeg's look at that pipe wait behind the engine's read:
ffmpeg would stop for good part way through a file (it did, in the first test under the app).
So every ffmpeg command starts with `-nostdin` (`QUIET_INPUT` in
[maku/core/convert.py](../../engine/src/maku/core/convert.py)), and every program the engine
starts gets an empty standard input unless it's given frames there.

**A test play keeps the file's own times.** Every result is played (decoded to `-f null`) for
five seconds at three points before it replaces its original, and anything ffmpeg says at
`-v error` fails it. By default ffmpeg rounds the frames' times to the frame rate for that
output, and an MKV's millisecond times can round two frames to one: then it complains
("non monotonically increasing dts to muxer") at points of files that play well, originals too.
That threw 42 good results away on 2026-10-14. So the test play keeps the times as the file has
them (`-enc_time_base:v demux`, in `_play` in
[maku/convert.py](../../engine/src/maku/convert.py)).

## Playing inside Maku

The player ([maku/core/player.py](../../engine/src/maku/core/player.py)) has ffmpeg make what
the window's `<video>` plays as it comes: fragmented MP4 (`-movflags
frag_keyframe+empty_moov+default_base_moof`) on ffmpeg's output, from `-ss <at>` with `-copyts`
so subtitles line up wherever it starts, the times then started from nothing (`setpts`,
`asetpts`). The picture is made at most 1080 high with square pixels, 8-bit 4:2:0
(`scale=w='trunc(oh*dar/2)*2':h='trunc(min(1080,ih)/2)*2',setsar=1,format=yuv420p`), drawn
whole first when it may be interlaced (`bwdif=mode=send_frame:deint=interlaced`, at the file's
own rate); one sound track becomes AAC stereo.

**Licensed encoders only, Windows' own first.** Maku makes H.264 with encoders that come with
their licence: Windows' own (`h264_mf`, Media Foundation's, part of Windows), then the graphics
cards' (`h264_nvenc`, `h264_amf`, `h264_qsv`, without B-frames), keeping to the first that works.
OpenH264 isn't used: Cisco's patent licence for it covers only the builds Cisco publishes, not
one built into ffmpeg. On the owner's PC (2026-10-14, a conversion running in the
background), Windows' encoder's first bytes came in about a second and 1080p
HEVC 10-bit went at three times the speed of playing; NVENC went as fast or faster, but once took
3.3 s to start while the card was busy. Every seek starts a new stream, so a steady start
matters most. A stream that gives nothing at all tries the next encoder only when its own fails
on a fifth of a second of black too; otherwise the file is the problem, and the player says so.
A read that fails part way (a drive unplugged) ends ffmpeg as if the file had ended, so the player
looks for the drive and the file whenever a stream ends early.

**Subtitles.** Text subtitles in the file are copied out once (`-map 0:s:N -c:s copy -f ass`,
or made ASS from SubRip and the like), which reads the whole file: about 7 s for a 480 MB
episode and 97 s for a 5 GB film from the hard drive, under 2 s once Windows has the file in
memory. The stream plays meanwhile. The file's fonts come out with the first copy, each by its
stream's index to a name of Maku's (`-dump_attachment:5 …\fonts\0.ttf`): a file's own names
for its attachments could point anywhere. They're drawn with `subtitles=filename=…:fontsdir=…`,
paths written by [maku/core/filters.py](../../engine/src/maku/core/filters.py). Subtitles that
are pictures (PGS, DVD) are laid over the picture from the file itself
(`[0:v:0]…[base];[base][0:s:N]overlay=eof_action=pass`).

## English from another copy

`maku/core/merge.py` builds the one command that adds another copy's English to the copy kept: the
kept copy's every stream as it is (`-map 0:V`, never a cover image, then its sound, subtitles and
fonts), then the other's English sound and subtitles (and its fonts, for styled subtitles),
stream-copied (`-c copy`), the added tracks never the default. The other copy is lined up by the
offset Maku heard (`maku/core/align.py`): one that runs earlier is read as it is with `-itsoffset`,
its tracks waiting till their moment; one that runs later is read from just the right moment with
`-ss`, so its sound is made anew as AAC (96 kbit/s a channel) and its text subtitles written anew,
and subtitles drawn as pictures can't come (Maku then keeps both copies as they are, rather than set
one aside with English that didn't come). Copies less than 0.08 s apart, closer than lining up can
tell, count as lined up already: copied as they are. `-t` ends the result with the kept copy's
picture (half a second's grace), though a subtitle begun before then may stay up a moment longer.
MP4's text subtitles become SRT, as MKV can't hold them as they are.

Measured with ffmpeg 8 on two pairs of clips whose timestamps start at 0: a copy 6.7 s earlier, its
English sound's first packet at 6.755 s and its subtitles 6.74 s later than in the copy; a copy 8 s
later, its subtitles 8.03 s earlier, the cue the cut fell in left out. A copy whose timestamps don't
start at 0 with its subtitles before its picture (cut with `-copyts`) can come out longer than the
kept copy: the check finds it, and both copies stay as they are. Every video in the library it was
tried against starts at 0.

## Moving to a newer build

1. Pick the last build of a month on [BtbN's releases](https://github.com/BtbN/FFmpeg-Builds/releases)
   (`autobuild-YYYY-MM-<last day>-…`) and its `win64-lgpl-shared` zip for the newest release branch.
2. Put its address, size and SHA-256 (the release lists each asset's digest) in `downloads.json`.
3. Run the engine tests, and check a scan and a conversion on real files before releasing.

A new pin means every copy of Maku downloads ffmpeg again (77 MB), so it moves for a new release
or a month's last build, not for each day's. Checked 2026-10-18: October's builds are still
9.0.2, with the 9.0 branch's later fixes, so the pin stays on September's last build.
