import {
  createContext,
  type ReactNode,
  use,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { fullScreen } from "@/lib/full-screen";

/** A video to play, as the page that offers it names it. */
export interface PlayItem {
  fileId: number;
  /** "The Harbour Line · S01E05", or the file's name. */
  label: string;
  /** "The Night Ferry", "From the still at 12:05", or the file's folder. */
  name: string | null;
  /** Where the file is, to show it in its folder when it won't play. */
  path: string;
  /** The label is a file's name, written as paths are. */
  fileName?: boolean;
  /** Where it stopped last time, in seconds: Play picks it up there. */
  resume?: number | null;
}

/** What's playing: one of the page's videos (the next of them a click away), from a point. */
export interface Playing {
  items: PlayItem[];
  index: number;
  /** Seconds in to start from. */
  from: number;
  /** It starts where it stopped last time, rather than where it was asked to. */
  resumed: boolean;
  /** Changes on every Play, so asking for the same video again starts it again. */
  turn: number;
}

/** Where the small player was moved to; null till it's moved (the window's bottom right). */
export type Place = { left: number; top: number } | null;

interface PlayerContextValue {
  playing: Playing | null;
  /** Plays `items[index]` from `from` seconds in (where it stopped last time, unless said),
   * the rest of `items` next. */
  play: (items: PlayItem[], index?: number, from?: number) => void;
  close: () => void;
  place: Place;
  setPlace: (place: Place) => void;
  /** The player has the whole window (which is full screen): the next video keeps it. */
  full: boolean;
  setFull: (full: boolean) => void;
}

/** Outside the window's shell (a page drawn on its own, in a test): nothing plays. */
const NOTHING: PlayerContextValue = {
  playing: null,
  play: () => {},
  close: () => {},
  place: null,
  setPlace: () => {},
  full: false,
  setFull: () => {},
};

const PlayerContext = createContext<PlayerContextValue>(NOTHING);

/** The player inside Maku's window: one video at a time, over whichever page is open. */
export function PlayerProvider({ children }: { children: ReactNode }) {
  const [playing, setPlaying] = useState<Playing | null>(null);
  const [place, setPlace] = useState<Place>(null);
  const [full, setFullState] = useState(false);
  const fullNow = useRef(false);
  const setFull = useCallback((on: boolean) => {
    fullNow.current = on;
    setFullState(on);
    fullScreen(on);
  }, []);
  const play = useCallback((items: PlayItem[], index = 0, from?: number) => {
    const resume = items[index]?.resume ?? 0;
    setPlaying((before) => ({
      items,
      index,
      from: from ?? resume,
      resumed: from === undefined && resume > 0,
      turn: (before?.turn ?? 0) + 1,
    }));
  }, []);
  // Closed, or gone with the window's shell, the player gives the window back as it was.
  const close = useCallback(() => {
    if (fullNow.current) setFull(false);
    setPlaying(null);
  }, [setFull]);
  useEffect(
    () => () => {
      if (fullNow.current) fullScreen(false);
    },
    [],
  );
  const value = useMemo(
    () => ({ playing, play, close, place, setPlace, full, setFull }),
    [playing, play, close, place, full, setFull],
  );
  return <PlayerContext value={value}>{children}</PlayerContext>;
}

export function usePlayer(): PlayerContextValue {
  return use(PlayerContext);
}

/** The file playing now, for a page to mark it; null when nothing plays. */
export function usePlayingFile(): number | null {
  const { playing } = usePlayer();
  return playing ? (playing.items[playing.index]?.fileId ?? null) : null;
}
