# Speech: English subtitles from a video's own sound

Maku makes English subtitles for a video that has none by listening to its sound, on this PC:
Whisper, OpenAI's speech model, hears it and translates it into English, or writes English down
as it's said when the sound is English. The sound it starts from is the video's own language:
Make English subtitles offers first the language most of the chosen videos' first sound tracks
are in, and the owner can pick another track's. It's for videos the owner has the right to keep
and watch; Maku never downloads subtitles or sound (see CLAUDE.md, "No piracy"). The video itself
never changes: the subtitles go beside it as `Episode 1.en.srt`, the name media server apps read,
or `Episode 1.maku.en.srt` when another file has the first.

## The pieces

| Part | What | Where |
| --- | --- | --- |
| Reading the sound | ffmpeg makes the chosen sound track 16 kHz mono floats | `maku/speech.py` `sound_of` |
| Who speaks when | pyannote's segmentation model 3.0, on the processor | `maku/speech.py` `Detector`, `maku/assets/pyannote-segmentation-3.0.onnx` |
| Hearing | Whisper medium (Best) or small (Fast), on the graphics card; Fast on the processor where the card hasn't 2 GB | `maku/speech.py` `Listener` |
| Rules and subtitles | log-mel, Whisper's timestamp rules, temperatures, lines and timing, SRT | `maku/core/speech.py` |
| A job | the queue's job of kind `subtitles`: read, listen, write, check, record | `maku/subtitles.py`, `maku/queue.py` |

## The models

- **Whisper** (MIT, OpenAI), as [onnx-community](https://huggingface.co/onnx-community)'s ONNX
  exports in half precision: `whisper-medium-ONNX` (1.53 GB) for Best, `whisper-small` (486 MB)
  for Fast, each an encoder and a merged decoder with its JSON (config, generation config,
  vocabulary). They're downloads, listed in `engine/src/maku/downloads.json` file by file, pinned
  to a commit so a file never changes, each checked by size and SHA-256; Maku fetches one the
  first time the owner makes subtitles at its quality (`when: "asked"`), never during Setup.
- **pyannote segmentation 3.0** (MIT): 6 MB, so it ships inside Maku. It says, about every 17 ms,
  how likely it is that someone speaks, 10 seconds at a time; windows overlap by half and are
  averaged.

Checked 2026-10-18: the pinned commits are still the newest of both exports, and segmentation 3.0
is still pyannote's newest. Whisper large-v3-turbo, OpenAI's newest, is quicker than medium but
was trained to write down what's said, not to translate it, and Best translates every other
language into English, so medium stays.

Licences: Whisper's code and weights are MIT; pyannote's model card says MIT, and its notice uses
pyannote.audio's licence text (CNRS). Both are listed in THIRD-PARTY-NOTICES.txt (the detector)
and on the installer's first page (the downloads).

## How a video is heard

1. **Where someone speaks.** The detector's likelihood starts a stretch at 0.5 and ends it below
   0.35; pauses under 0.3 s close, blips under 0.2 s go, and each stretch gets 0.2 s either side.
2. **Windows.** Stretches are gathered into windows of the sound as it is, at most 30 s each
   (Whisper hears 30 s at a time), the pauses between them included. Times come straight from a
   window's start, so a line can't land minutes away from where it's said.
3. **Whisper hears each window**: the log-mel spectrogram, the encoder, then the decoder a token
   at a time, keeping Whisper's rules (timestamps in pairs, never back, the first within a
   second, none past the window's sound; a timestamp when they're likelier together than any
   word). An answer that loops (text compressing more than 2.4 to 1) or that Whisper is unsure
   of is tried again warmer (0.2 to 1.0); translating takes less certainty (an average
   log-probability of -1.5) than writing down (-1.0). Where no one speaks, it says so.
4. **Lines.** Repeats and lines Whisper invents from nothing ("Thanks for watching") go. A
   subtitle holds two lines of 42 characters at most, as even as they'll go; a longer line is
   shared among as few subtitles as hold it, cut at a sentence or clause where one is near. Each
   stays a second at least and seven at most, 0.4 s past its words where the next leaves room.
5. **Written and checked**: under a name of its own (`.maku-partial`) till it reads back whole,
   in order and within the video's length, then in place. `made_subtitles` records it as Maku's
   before it takes its name (a crash in between leaves nothing Maku wrote unknown), and it stays
   Maku's while it's there as written, its size and the time it was written unchanged; one the
   owner changed is theirs. The record keeps the sound track it's from and the language Whisper
   heard there, which a title's page shows for a track whose file doesn't name its language
   (`heard_in` in `maku/core/languages.py`); one Maku hasn't heard says "Language not labelled".

## On the graphics card

ONNX Runtime with DirectML, with the encoder and decoder in the same place: when the card won't
take the decoder, the encoder runs on the processor with it. A Whisper that hits a
problem it doesn't know is loaded anew for the next video. The decoder's caches stay on the card
between tokens, bound in place with I/O binding (`run_with_iobinding`), and only the next token's
scores come back: handed through Python and NumPy, a 6 GB card ran out of memory ("Not enough
memory resources") on the first episode. The cross-attention's caches are made once per window and
kept. Without a card that can, the processor runs it, slowly: there ONNX Runtime 1.24's highest
graph optimisation breaks the half-precision layer norms as the model loads, so the processor's
sessions load one level below (`ORT_ENABLE_EXTENDED`), as quick.

Other PCs ([hardware.md](hardware.md)): Best wants a card with 4 GB of its own, Fast 2 GB, and
Fast runs on the processor where the card hasn't that (the queue loads Whisper there on purpose).
A card that runs out of memory ("8007000E Not enough memory resources") fails the video saying
so, and Whisper is loaded anew; at Best, the queue's card offers "Make them with Fast". Whisper
medium heard a minute of an episode in 84 seconds on the owner's i5-9600K; small does about a
third of the work, so Fast on a processor is guessed at a second of work for each second of sound
till the PC measures its own.

Every window Whisper encodes and every token it writes takes DirectML's lock
(`maku/directml.py`): two threads on DirectML at once crash the graphics driver. And another model
loaded and let go of in the engine while Whisper is loaded crashes Whisper's next step, so the PC
check, which loads a small model of its own to see whether DirectML runs on the card, does it in
a process of its own (`maku check-directml`).

One job at a time on the card: subtitles wait in the queue with the conversions, in the owner's
order. Whisper stays loaded while subtitles follow subtitles, and is let go before a conversion
and once nothing waits, giving the card's memory back.

## Measured (GTX 1660 Super, 2026-10-15)

Measured in Kura, Maku's sibling, whose speech is the same: an episode of 21 minutes, its sound in
a language other than English with music under most of it, checked against the release's own
English subtitles:

| | Best (medium) | Fast (small) |
| --- | --- | --- |
| Time, through the queue | 474 s (2.6x real time) | 179 s (6.9x) |
| Lines heard where the release has one | 96% | 97% |
| Made lines over a release line | 90% | 93% |
| Names | right more often | rougher |

The estimates (`maku/core/estimate.py` `HEARING`) are 0.4 and 0.15 seconds of the card's time
per second of video. A decoder step costs about 90 to 150 ms with medium and 25 ms with small;
batching windows gained at most 2x at batch 8, not worth its memory.

Why pyannote, not Silero's detector: on that episode Silero heard nothing (0.00) under the
action scenes' music, where the release has 18 lines; Whisper over the whole sound heard them but
invented lines in the music and drifted in time. pyannote heard 258 of the 262 lines.

## Trying it

`maku subtitles VIDEO OUT --quality best --track 0 --language fra` makes one video's subtitles as
the queue does, with Maku's own ffmpeg and model (`MAKU_FFMPEG_DIR` and `MAKU_SPEECH_BEST_DIR`
can point at copies in development). `--language` is the sound's language as files tag it; left
out, Whisper tells.
