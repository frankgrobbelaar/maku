import {
  Maximize2,
  Pause,
  PictureInPicture2,
  Play,
  RotateCcw,
  RotateCw,
  SkipForward,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { type PointerEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  closeVideo,
  type OpenedVideo,
  openVideo,
  prepareSubtitles,
  type StreamStopped,
  streamAddress,
  useEngine,
  usePlayerState,
  usePositionNote,
} from "@/lib/engine";
import { showInFolder } from "@/lib/explorer";
import { cn } from "@/lib/utils";
import { type Place, type PlayItem, usePlayer } from "./player-context";
import { GettingReady, RoundButton, SeekBar, Stopped, TracksMenu } from "./player-parts";
import { like, liked, pickSound, pickSubtitles, playTime } from "./tracks";

/** What the stream plays: from where, with which sound, and which subtitles drawn in. */
interface Source {
  at: number;
  sound: number | null;
  subtitles: number | null;
}

/** Why it doesn't play. */
type Problem =
  | { kind: "drive"; drive: string }
  | { kind: "gone" }
  | { kind: "stopped"; at: number; damaged: boolean; detail: string | null }
  | { kind: "engine"; message: string };

const MARGIN = 8; // the small player keeps this far inside the window
const BELOW_TITLE_BAR = 60; // and below the title bar, its buttons always in reach
const QUIET = 3000; // milliseconds before full screen's controls step aside
const NOTE_EVERY = 10_000; // milliseconds between telling the engine where the video is
const COUNTS = 10; // seconds played before Maku keeps where the video is: less is a look
const OFFER = 8000; // milliseconds "Start over" stays, once a video picks up where it stopped

/** The player over the page: small and movable anywhere in the window, or the whole of it. */
export function PlayerLayer() {
  const { playing, play, close } = usePlayer();
  const item = playing?.items[playing.index];
  if (!playing || !item) return null;
  const next = playing.items[playing.index + 1];
  return (
    <Playback
      key={playing.turn}
      item={item}
      from={playing.from}
      resumed={playing.resumed}
      onClose={close}
      onNext={next ? () => play(playing.items, playing.index + 1) : null}
    />
  );
}

function Playback(props: {
  item: PlayItem;
  from: number;
  /** It picks up where it stopped last time. */
  resumed: boolean;
  onClose: () => void;
  onNext: (() => void) | null;
}) {
  const { item, onClose } = props;
  const engine = useEngine();
  const note = usePositionNote();
  const ready = engine.state === "ready" ? engine : null;
  const { place, setPlace, full, setFull } = usePlayer();
  // Each opening of the video, from a point: Play again opens it afresh where it stopped.
  const [opening, setOpening] = useState({ at: props.from });
  const [video, setVideo] = useState<OpenedVideo | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [subtitles, setSubtitles] = useState<number | null>(null); // chosen, ready or not
  const [clock, setClock] = useState(0); // seconds into this stream
  const [started, setStarted] = useState(false); // this stream's first picture is up
  const [shown, setShown] = useState(false); // any stream's has been
  const [frozen, setFrozen] = useState(false); // the last picture holds while it starts again
  const [held, setHeld] = useState(false); // the owner paused it
  const [ended, setEnded] = useState(false);
  const [seekingTo, setSeekingTo] = useState<number | null>(null);
  const [menu, setMenu] = useState(false);
  const [idle, setIdle] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [over, setOver] = useState(false); // the pointer, or the keyboard, is on the player
  const [offer, setOffer] = useState(props.resumed); // "Start over", for a moment
  const [volume, setVolume] = useState(() => liked().volume ?? 1);
  const [muted, setMuted] = useState(() => liked().muted ?? false);
  const element = useRef<HTMLVideoElement>(null);
  const frame = useRef<HTMLCanvasElement>(null);
  const box = useRef<HTMLElement>(null);
  const position = useRef(props.from); // where it plays now, in the video's own seconds
  const commit = useRef<number | undefined>(undefined);
  const resting = useRef<number | undefined>(undefined);
  // A press on the player: where it began, and whether it has become a drag.
  const grab = useRef<{
    x: number;
    y: number;
    dx: number;
    dy: number;
    moved: boolean;
    onPicture: boolean;
  } | null>(null);
  const ticket = video?.ticket ?? null;
  const state = usePlayerState(ticket, subtitles);
  const duration = video?.duration ?? 0;

  // Where it is, told to the engine every few seconds while it plays and as it stops, so Play
  // picks it up there next time. A look of a few seconds isn't kept.
  const played = useRef({ seconds: 0, clock: 0, noted: 0 });
  const tell = useRef((_stopped: boolean) => {});
  tell.current = (stopped: boolean) => {
    if (played.current.seconds < COUNTS) return;
    played.current.noted = Date.now();
    note(item.fileId, position.current, duration || null, stopped);
  };
  useEffect(() => () => tell.current(true), []);
  // Picked up where it stopped, it offers to start over, for a moment once it's playing.
  useEffect(() => {
    if (!offer || !started) return;
    const timer = window.setTimeout(() => setOffer(false), OFFER);
    return () => window.clearTimeout(timer);
  }, [offer, started]);

  // Open the video: a ticket, what it offers, and the sound and subtitles to start with.
  useEffect(() => {
    if (!ready) return;
    let current = true;
    let made: string | null = null;
    setVideo(null);
    setProblem(null);
    setSource(null);
    setShown(false);
    openVideo(ready, item.fileId)
      .then((opened) => {
        made = opened.ticket;
        if (!current) return;
        setVideo(opened);
        if (opened.ticket === null) {
          setProblem(
            opened.missing === "drive" ? { kind: "drive", drive: opened.drive } : { kind: "gone" },
          );
          return;
        }
        const kept = liked();
        const chosen = pickSubtitles(opened, kept);
        const at = opened.duration
          ? Math.min(opening.at, Math.max(0, opened.duration - 1))
          : opening.at;
        position.current = at;
        setSubtitles(chosen);
        setSource({
          at,
          sound: pickSound(opened, kept),
          subtitles: chosen !== null && opened.ready.includes(chosen) ? chosen : null,
        });
        if (chosen !== null && !opened.ready.includes(chosen)) {
          void prepareSubtitles(ready, opened.ticket, chosen).catch(() => {});
        }
      })
      .catch((error: unknown) => {
        if (current) setProblem({ kind: "engine", message: String(error) });
      });
    return () => {
      current = false;
      if (made) void closeVideo(ready, made).catch(() => {});
    };
  }, [ready, item.fileId, opening]);

  /** Holds the last picture on screen while the stream starts again from somewhere else. */
  const freeze = useCallback(() => {
    const playing = element.current;
    const canvas = frame.current;
    if (!playing || !canvas || !playing.videoWidth) return;
    canvas.width = playing.videoWidth;
    canvas.height = playing.videoHeight;
    canvas.getContext("2d")?.drawImage(playing, 0, 0);
    setFrozen(true);
  }, []);

  /** Starts the stream again: from where it is (or `change.at`), with what changed. */
  const restart = useCallback(
    (change: Partial<Source>) => {
      window.clearTimeout(commit.current);
      freeze();
      // Where from, taken now: a moment's playing later must not move it.
      const at = change.at ?? position.current;
      position.current = at;
      setStarted(false);
      setEnded(false);
      setClock(0);
      setSeekingTo(null);
      setSource((now) => now && { ...now, ...change, at });
    },
    [freeze],
  );

  // Subtitles chosen join the picture once they're ready; turned off, or failing to get ready,
  // the ones drawn leave it.
  const readyNow = state.data?.ready ?? video?.ready ?? [];
  const drawable = subtitles !== null && readyNow.includes(subtitles) ? subtitles : null;
  const failing = state.data?.failed.some((each) => each.number === subtitles) ?? false;
  useEffect(() => {
    if (!source || drawable === source.subtitles) return;
    if (drawable !== null || subtitles === null || failing) restart({ subtitles: drawable });
  }, [source, drawable, subtitles, failing, restart]);

  useEffect(() => {
    const playing = element.current;
    if (!playing) return;
    playing.volume = volume;
    playing.muted = muted;
  });

  // Full screen is the window's: Esc leaves it, and so does closing the player.
  const goFull = useCallback(
    (on: boolean) => {
      setFull(on);
      setIdle(false);
    },
    [setFull],
  );
  // Full screen, the controls step aside a few seconds after it starts (the next video's too),
  // unless the pointer moves or a key is pressed.
  useEffect(() => {
    if (!full) return;
    resting.current = window.setTimeout(() => setIdle(true), QUIET);
    return () => window.clearTimeout(resting.current);
  }, [full]);
  useEffect(
    () => () => {
      window.clearTimeout(commit.current);
      window.clearTimeout(resting.current);
    },
    [],
  );
  useEffect(() => {
    if (!full) return;
    const leave = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !menu) goFull(false);
    };
    window.addEventListener("keydown", leave);
    return () => window.removeEventListener("keydown", leave);
  }, [full, menu, goFull]);
  // Moved, the small player stays inside the window as it changes size (not while the player
  // has the whole window: the size then is the window's).
  useEffect(() => {
    if (!place || full) return;
    const keep = () => {
      const size = box.current?.getBoundingClientRect();
      if (size) setPlace(inside(place, size.width, size.height));
    };
    window.addEventListener("resize", keep);
    return () => window.removeEventListener("resize", keep);
  }, [place, setPlace, full]);

  const url = ready && ticket && source && !problem ? streamAddress(ready, ticket, source) : null;
  const at = seekingTo ?? (source ? source.at + clock : props.from);

  async function explain(stoppedAt: number) {
    const found = ticket ? (await state.refetch()).data?.stopped : null;
    setProblem(problemOf(found ?? null, stoppedAt, video?.drive ?? ""));
  }

  function toggle() {
    const playing = element.current;
    if (!playing || !source || problem) return;
    if (ended) {
      setHeld(false);
      restart({ at: 0 });
      return;
    }
    if (playing.paused) {
      setHeld(false);
      void playing.play().catch(() => {});
    } else {
      setHeld(true);
      playing.pause();
      tell.current(true);
    }
  }

  function seek(to: number, now: boolean) {
    const target = Math.min(Math.max(to, 0), Math.max(duration - 1, 0));
    setSeekingTo(target);
    window.clearTimeout(commit.current);
    if (now) restart({ at: target });
    else commit.current = window.setTimeout(() => restart({ at: target }), 350);
  }

  function chooseSound(sound: number) {
    like({ sound: video?.sound.find((track) => track.number === sound)?.language ?? null });
    restart({ sound });
  }

  function chooseSubtitles(chosen: number | null) {
    const track = video?.subtitles.find((each) => each.number === chosen);
    like({ subtitles: chosen === null ? "off" : (track?.language ?? null) });
    setSubtitles(chosen);
    if (ready && ticket && chosen !== null && !readyNow.includes(chosen)) {
      void prepareSubtitles(ready, ticket, chosen)
        .then(() => state.refetch())
        .catch(() => {});
    }
  }

  function playAgain() {
    setOpening({ at: position.current });
  }

  function wake() {
    setIdle(false);
    window.clearTimeout(resting.current);
    resting.current = window.setTimeout(() => setIdle(true), QUIET);
  }

  function onPointerDown(event: PointerEvent<HTMLElement>) {
    // Only a press on the player itself: one in its sound and subtitles menu, which sits outside
    // it on the page, reaches here too, and capturing that pointer would take the menu's click.
    if (!event.currentTarget.contains(event.target as Node)) return;
    if (event.button !== 0 || (event.target as Element).closest("button, input, a")) return;
    const size = event.currentTarget.getBoundingClientRect();
    grab.current = {
      x: event.clientX,
      y: event.clientY,
      dx: event.clientX - size.left,
      dy: event.clientY - size.top,
      moved: false,
      // On the picture, not its controls: a click there plays or pauses.
      onPicture:
        (event.target as Element).closest("[data-picture]") !== null &&
        (event.target as Element).closest("[data-controls]") === null,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function onPointerMove(event: PointerEvent<HTMLElement>) {
    if (full) wake();
    const hold = grab.current;
    if (!hold || full) return;
    if (!hold.moved && Math.hypot(event.clientX - hold.x, event.clientY - hold.y) < 4) return;
    hold.moved = true;
    setDragging(true);
    const size = event.currentTarget.getBoundingClientRect();
    setPlace(
      inside(
        { left: event.clientX - hold.dx, top: event.clientY - hold.dy },
        size.width,
        size.height,
      ),
    );
  }

  function onPointerUp() {
    const hold = grab.current;
    grab.current = null;
    setDragging(false);
    // A click on the picture, not a drag: play or pause.
    if (hold && !hold.moved && hold.onPicture) toggle();
  }

  const playingNow = !held && !ended;
  const asleep = playingNow && started && !menu && !problem && (full ? idle : !over && !dragging);
  const preparing = subtitles !== null && (state.data?.preparing.includes(subtitles) ?? false);

  return (
    <section
      ref={box}
      aria-label="Player"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => {
        grab.current = null;
        setDragging(false);
      }}
      onPointerEnter={() => setOver(true)}
      onPointerLeave={() => setOver(false)}
      onKeyDown={() => {
        if (full) wake();
      }}
      onFocus={() => {
        setOver(true);
        if (full) wake();
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOver(false);
      }}
      className={cn(
        "fixed z-50",
        full
          ? "inset-0"
          : "w-100 max-w-[calc(100vw-48px)] animate-pop touch-none select-none rounded-20 border border-edge shadow-float",
        !full && (dragging ? "cursor-grabbing" : "cursor-grab"),
        full && asleep && "cursor-none",
      )}
      style={full ? undefined : place ? { left: place.left, top: place.top } : SMALL_CORNER}
    >
      <div
        className={cn(
          "scheme-dark relative flex flex-col overflow-hidden bg-dialog text-fg",
          full ? "size-full bg-black" : "rounded-20",
        )}
      >
        <div
          data-picture
          className={cn("relative overflow-hidden bg-black", full ? "flex-1" : "aspect-video")}
        >
          {/* biome-ignore lint/a11y/useMediaCaption: the engine draws the subtitles into the picture */}
          <video
            ref={element}
            src={url ?? undefined}
            autoPlay={!held}
            playsInline
            className="absolute inset-0 size-full object-contain"
            onLoadedData={() => {
              setStarted(true);
              setShown(true);
              setFrozen(false);
            }}
            onPlaying={() => {
              setStarted(true);
              setShown(true);
              setFrozen(false);
            }}
            onTimeUpdate={(event) => {
              const now = event.currentTarget.currentTime;
              setClock(now);
              if (source) position.current = source.at + now;
              // Seconds actually played: a new stream starts its clock again, a seek jumps it.
              const step = now - played.current.clock;
              played.current.clock = now;
              if (step > 0 && step < 2) played.current.seconds += step;
              if (Date.now() - played.current.noted >= NOTE_EVERY) tell.current(false);
            }}
            onEnded={() => {
              if (duration > 0 && position.current < duration - 3) void explain(position.current);
              else {
                setEnded(true);
                position.current = duration;
                tell.current(true);
              }
            }}
            onError={() => {
              if (url) void explain(position.current);
            }}
          />
          <canvas
            ref={frame}
            className={cn("absolute inset-0 size-full object-contain", !frozen && "hidden")}
          />
          {!problem && !shown && <GettingReady drive={video?.drive ?? ""} />}
          {!problem && shown && !started && <Note>Getting it ready</Note>}
          {!problem && started && preparing && <Note>Subtitles in a moment</Note>}
          {!problem && started && !preparing && offer && (
            <PickedUp
              at={props.from}
              full={full}
              onStartOver={() => {
                setOffer(false);
                restart({ at: 0 });
              }}
            />
          )}
          {problem && (
            <Trouble
              problem={problem}
              onPlayAgain={playAgain}
              onFolder={() => void showInFolder(item.path).catch(() => {})}
              onClose={onClose}
            />
          )}
          {!full && (
            <span
              className={cn(
                "absolute top-2.5 right-2.5 flex gap-1.5 transition-opacity duration-200",
                asleep && "pointer-events-none opacity-0",
              )}
            >
              {shown && !problem && (
                <RoundButton label="Full screen" className="bg-tag" onClick={() => goFull(true)}>
                  <Maximize2 size={15} strokeWidth={2} aria-hidden="true" />
                </RoundButton>
              )}
              <RoundButton label="Close the player" className="bg-tag" onClick={onClose}>
                <X size={15} strokeWidth={2} aria-hidden="true" />
              </RoundButton>
            </span>
          )}
          {!full && shown && video && source && !problem && (
            <div
              data-controls
              className={cn(
                "absolute inset-x-0 bottom-0 flex flex-col gap-1.5 bg-window/72 px-2.5 py-2 transition-opacity duration-200",
                asleep && "pointer-events-none opacity-0",
              )}
            >
              <SeekBar
                at={at}
                duration={duration}
                chapters={video.chapters}
                large={false}
                onSeek={seek}
              />
              <span className="flex items-center gap-1">
                <PlayPause playing={playingNow} ended={ended} onClick={toggle} />
                <span className="font-mono text-12 text-fg-soft">
                  {playTime(at)} / {playTime(duration)}
                </span>
                <span className="flex-1" />
                <TracksMenu
                  video={video}
                  state={state.data}
                  sound={source.sound}
                  subtitles={subtitles}
                  open={menu}
                  onOpenChange={setMenu}
                  onSound={chooseSound}
                  onSubtitles={chooseSubtitles}
                  size="sm"
                />
                {props.onNext && (
                  <RoundButton label="Next episode" onClick={props.onNext}>
                    <SkipForward size={16} fill="currentColor" aria-hidden="true" />
                  </RoundButton>
                )}
              </span>
            </div>
          )}
        </div>
        {!full && (
          <div className="flex items-center gap-2.5 px-3.5 pt-2.5 pb-3">
            <span className="flex min-w-0 flex-1 flex-col">
              <strong
                className={cn(
                  "truncate font-extrabold text-13",
                  item.fileName && "font-medium font-mono text-12",
                )}
              >
                {item.label}
              </strong>
              {item.name && <span className="truncate text-12 text-fg-muted">{item.name}</span>}
            </span>
            <span className="shrink-0 text-11 text-fg-faint">Drag to move</span>
          </div>
        )}
        {full && (
          <FullControls
            hidden={asleep}
            label={item.label}
            name={item.name}
            onSmall={() => goFull(false)}
            onClose={onClose}
          >
            {video && source && !problem && (
              <>
                <span className="flex items-center gap-3 font-mono text-12 text-fg-soft">
                  <span>{playTime(at)}</span>
                  <SeekBar
                    at={at}
                    duration={duration}
                    chapters={video.chapters}
                    large
                    onSeek={seek}
                  />
                  <span>{playTime(duration)}</span>
                </span>
                <span className="flex flex-wrap items-center gap-1.5">
                  <RoundButton
                    label={ended ? "Play again" : playingNow ? "Pause" : "Play"}
                    size="lg"
                    className="bg-accent text-on-accent"
                    onClick={toggle}
                  >
                    {playingNow ? (
                      <Pause size={18} fill="currentColor" aria-hidden="true" />
                    ) : (
                      <Play size={18} fill="currentColor" aria-hidden="true" />
                    )}
                  </RoundButton>
                  <RoundButton
                    label="Back 10 seconds"
                    size="md"
                    onClick={() => seek((seekingTo ?? position.current) - 10, false)}
                  >
                    <RotateCcw size={20} strokeWidth={1.8} aria-hidden="true" />
                  </RoundButton>
                  <RoundButton
                    label="On 10 seconds"
                    size="md"
                    onClick={() => seek((seekingTo ?? position.current) + 10, false)}
                  >
                    <RotateCw size={20} strokeWidth={1.8} aria-hidden="true" />
                  </RoundButton>
                  <Loudness
                    volume={volume}
                    muted={muted}
                    onVolume={(value) => {
                      setVolume(value);
                      setMuted(false);
                      like({ volume: value, muted: false });
                    }}
                    onMute={() => {
                      setMuted(!muted);
                      like({ muted: !muted });
                    }}
                  />
                  <span className="flex-1" />
                  <TracksMenu
                    video={video}
                    state={state.data}
                    sound={source.sound}
                    subtitles={subtitles}
                    open={menu}
                    onOpenChange={setMenu}
                    onSound={chooseSound}
                    onSubtitles={chooseSubtitles}
                    size="md"
                  />
                  {props.onNext && (
                    <RoundButton label="Next episode" size="md" onClick={props.onNext}>
                      <SkipForward size={18} fill="currentColor" aria-hidden="true" />
                    </RoundButton>
                  )}
                  <RoundButton
                    label="Back to the small player"
                    size="md"
                    onClick={() => goFull(false)}
                  >
                    <PictureInPicture2 size={20} strokeWidth={1.8} aria-hidden="true" />
                  </RoundButton>
                </span>
              </>
            )}
          </FullControls>
        )}
      </div>
    </section>
  );
}

const SMALL_CORNER = { right: 24, bottom: 24 };

function PlayPause(props: { playing: boolean; ended: boolean; onClick: () => void }) {
  return (
    <RoundButton
      label={props.ended ? "Play again" : props.playing ? "Pause" : "Play"}
      onClick={props.onClick}
    >
      {props.playing ? (
        <Pause size={16} fill="currentColor" aria-hidden="true" />
      ) : (
        <Play size={16} fill="currentColor" aria-hidden="true" />
      )}
    </RoundButton>
  );
}

/** Full screen's bars: its name and the way back on top, the controls at the foot. They step
 * aside while it plays and the pointer rests. */
function FullControls(props: {
  hidden: boolean;
  label: string;
  name: string | null;
  onSmall: () => void;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const fade = cn(
    "absolute inset-x-0 bg-window/72 transition-opacity duration-200",
    props.hidden && "pointer-events-none opacity-0",
  );
  return (
    <>
      <div
        className={cn(fade, "top-0 flex flex-wrap items-center justify-between gap-3 px-6 py-4.5")}
      >
        <span className="flex min-w-0 flex-col">
          <strong className="truncate font-extrabold text-16">{props.label}</strong>
          {props.name && <span className="truncate text-13 text-fg-muted">{props.name}</span>}
        </span>
        <span className="flex gap-2">
          <button
            type="button"
            onClick={props.onSmall}
            className="press inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-full border border-tint/14 bg-tint/8 px-4 font-bold text-13 text-white"
          >
            <PictureInPicture2 size={16} strokeWidth={1.8} aria-hidden="true" />
            Back to the small player
          </button>
          <RoundButton
            label="Close the player"
            className="size-10 border border-tint/14 bg-tint/8"
            onClick={props.onClose}
          >
            <X size={16} strokeWidth={2} aria-hidden="true" />
          </RoundButton>
        </span>
      </div>
      <div className={cn(fade, "bottom-0 flex flex-col gap-2.5 px-6 pt-4 pb-4.5")}>
        {props.children}
      </div>
    </>
  );
}

function Loudness(props: {
  volume: number;
  muted: boolean;
  onVolume: (volume: number) => void;
  onMute: () => void;
}) {
  const silent = props.muted || props.volume === 0;
  return (
    <span className="ml-1.5 inline-flex items-center gap-1">
      <RoundButton label={silent ? "Sound on" : "Mute"} size="md" onClick={props.onMute}>
        {silent ? (
          <VolumeX size={20} strokeWidth={1.8} aria-hidden="true" />
        ) : (
          <Volume2 size={20} strokeWidth={1.8} aria-hidden="true" />
        )}
      </RoundButton>
      <input
        type="range"
        min={0}
        max={100}
        value={silent ? 0 : Math.round(props.volume * 100)}
        aria-label="Volume"
        onChange={(event) => props.onVolume(Number(event.currentTarget.value) / 100)}
        className="w-24 cursor-pointer accent-accent"
      />
    </span>
  );
}

/** A short word over the picture's corner: it's starting again, or subtitles are on the way. */
function Note({ children }: { children: React.ReactNode }) {
  return (
    <span
      role="status"
      className="absolute top-2.5 left-2.5 animate-pulse rounded-full bg-tag px-2.5 py-1 font-bold text-12 text-white"
    >
      {children}
    </span>
  );
}

/** Over the picture's corner, a moment after a video picks up where it stopped: from where, and
 * the way back to its start. */
function PickedUp(props: { at: number; full: boolean; onStartOver: () => void }) {
  return (
    <span
      className={cn(
        "absolute flex animate-fade-in items-center gap-2 rounded-full bg-tag py-1 pr-1 pl-3 font-bold text-12 text-white",
        props.full ? "top-22 left-6" : "top-2.5 left-2.5",
      )}
    >
      <span role="status">Picked up at {playTime(props.at)}</span>
      <button
        type="button"
        onClick={props.onStartOver}
        className="press cursor-pointer rounded-full bg-tint/14 px-2.5 py-0.5 text-white"
      >
        Start over
      </button>
    </span>
  );
}

function Trouble(props: {
  problem: Problem;
  onPlayAgain: () => void;
  onFolder: () => void;
  onClose: () => void;
}) {
  const { problem } = props;
  switch (problem.kind) {
    case "drive":
      return (
        <Stopped
          icon="drive"
          title={`${problem.drive || "Its drive"} isn't connected`}
          action={{ label: "Play again", play: true, onClick: props.onPlayAgain }}
          onClose={props.onClose}
        >
          Plug the drive in and press Play again.
        </Stopped>
      );
    case "gone":
      return (
        <Stopped icon="alert" title="This file isn't there any more" onClose={props.onClose}>
          Maku can't find it where it was. A scan finds where it went.
        </Stopped>
      );
    case "engine":
      return (
        <Stopped icon="alert" title="This file won't play here" onClose={props.onClose}>
          {problem.message.replace(/^Error: /, "")}
        </Stopped>
      );
    case "stopped":
      return (
        <Stopped
          icon="alert"
          title="This file won't play here"
          action={{ label: "Open its folder", onClick: props.onFolder }}
          onClose={props.onClose}
        >
          {problem.damaged
            ? `Its picture is damaged at ${playTime(problem.at)}, so Maku stopped there.`
            : `Maku couldn't play it from ${playTime(problem.at)}${problem.detail ? ` (${problem.detail})` : ""}.`}{" "}
          The file is as it was.
        </Stopped>
      );
  }
}

function problemOf(stopped: StreamStopped | null, at: number, drive: string): Problem {
  if (stopped?.why === "drive") return { kind: "drive", drive };
  if (stopped?.why === "gone") return { kind: "gone" };
  return {
    kind: "stopped",
    at,
    damaged: stopped?.why === "damaged",
    detail: stopped?.detail ?? null,
  };
}

/** A place for the small player that keeps it inside the window. */
function inside(place: NonNullable<Place>, width: number, height: number): NonNullable<Place> {
  return {
    left: Math.min(
      Math.max(place.left, MARGIN),
      Math.max(MARGIN, window.innerWidth - width - MARGIN),
    ),
    top: Math.min(
      Math.max(place.top, BELOW_TITLE_BAR),
      Math.max(BELOW_TITLE_BAR, window.innerHeight - height - MARGIN),
    ),
  };
}
