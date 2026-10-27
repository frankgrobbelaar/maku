import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import {
  createContext,
  type ReactNode,
  use,
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

/** The engine as Maku's shell reports it. Mirrors `EngineStatus` in src-tauri/src/engine.rs. */
export type EngineStatus =
  | { state: "starting" }
  | { state: "ready"; url: string; token: string }
  | { state: "failed"; message: string; details: string };

export type ReadyEngine = Extract<EngineStatus, { state: "ready" }>;

const EngineContext = createContext<EngineStatus>({ state: "starting" });

/** Follows the engine's status: asks the shell once, then listens for changes. */
export function EngineProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<EngineStatus>({ state: "starting" });

  useEffect(() => {
    let heardEvent = false;
    const stopListening = listen<EngineStatus>("engine-status", (event) => {
      heardEvent = true;
      setStatus(event.payload);
    });
    invoke<EngineStatus>("engine_status").then((current) => {
      if (!heardEvent) setStatus(current); // an event is always newer than this answer
    });
    return () => {
      stopListening.then((unlisten) => unlisten());
    };
  }, []);

  return <EngineContext value={status}>{children}</EngineContext>;
}

export function useEngine(): EngineStatus {
  return use(EngineContext);
}

/** Asks the shell to start the engine again, after it failed. */
export function restartEngine(): Promise<void> {
  return invoke("restart_engine");
}

export class EngineError extends Error {}

/** Calls the engine's HTTP API with this launch's token. */
export async function callEngine<T>(
  engine: ReadyEngine,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${engine.token}`);
  let response: Response;
  try {
    response = await fetch(new URL(path, engine.url), { ...init, headers });
  } catch {
    throw new EngineError("Maku's engine didn't answer.");
  }
  if (!response.ok) {
    throw new EngineError(
      (await problemIn(response)) ??
        `The engine answered ${response.status} to ${init?.method ?? "GET"} ${path}.`,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** The sentence the engine sends with a refusal (FastAPI's `detail`), if it sent one. */
async function problemIn(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // not JSON: fall back to the status
  }
  return null;
}

function engineKey(engine: EngineStatus, path: string) {
  return ["engine", engine.state === "ready" ? engine.url : null, path];
}

/**
 * A query for one engine endpoint. It waits until the engine is ready (and `enabled`). `poll`
 * asks again every that many milliseconds while it returns a number for the latest answer (a job
 * in progress). `keep` shows the last answer while a changed question loads (a list re-sorting),
 * instead of nothing.
 */
export function useEngineQuery<T>(
  path: string,
  poll?: (data: T | undefined) => number | false,
  enabled = true,
  keep = false,
) {
  const engine = useEngine();
  return useQuery({
    queryKey: engineKey(engine, path),
    queryFn: () => {
      if (engine.state !== "ready") throw new EngineError("The engine isn't ready yet.");
      return callEngine<T>(engine, path);
    },
    enabled: engine.state === "ready" && enabled,
    refetchInterval: poll ? (query) => poll(query.state.data) : false,
    placeholderData: keep ? keepPreviousData : undefined,
  });
}

/**
 * A glance at an engine endpoint for the window's shell (the nav rail's badges): like
 * `useEngineQuery`, but it doesn't ask again when the window comes back into focus. What it shows
 * catches up after every scan and change anyway, and the page that's open asks for itself.
 */
function useGlance<T>(path: string, poll?: number) {
  const engine = useEngine();
  return useQuery({
    queryKey: engineKey(engine, path),
    queryFn: () => {
      if (engine.state !== "ready") throw new EngineError("The engine isn't ready yet.");
      return callEngine<T>(engine, path);
    },
    enabled: engine.state === "ready",
    refetchInterval: poll ?? false,
    refetchOnWindowFocus: false,
  });
}

/**
 * Asks the engine again for what these paths' queries show, so screens catch up with a change.
 * A path covers everything under it: "/titles" also refreshes "/titles?sort=name" and "/titles/3".
 */
function useRefresh() {
  const engine = useEngine();
  const queries = useQueryClient();
  return useCallback(
    (paths: string[]) => {
      const url = engine.state === "ready" ? engine.url : null;
      return queries.invalidateQueries({
        predicate: ({ queryKey: [scope, address, asked] }) =>
          scope === "engine" &&
          address === url &&
          typeof asked === "string" &&
          paths.some(
            (path) =>
              asked === path || asked.startsWith(`${path}?`) || asked.startsWith(`${path}/`),
          ),
      });
    },
    [engine, queries],
  );
}

/**
 * A change sent to the engine: `send(path, body?)` posts it, then refreshes the queries for
 * `refreshes` so the screen shows the result.
 */
export function useEngineAction<T>(
  refreshes: string[],
  method: "POST" | "PUT" | "DELETE" = "POST",
) {
  const engine = useEngine();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => {
      if (engine.state !== "ready") throw new EngineError("The engine isn't ready yet.");
      const init: RequestInit = { method };
      if (body !== undefined) {
        init.body = JSON.stringify(body);
        init.headers = { "Content-Type": "application/json" };
      }
      return callEngine<T>(engine, path, init);
    },
    onSettled: () => refresh(refreshes),
  });
}

// The engine's API. These types mirror engine/openapi.json: change both together.

export interface Health {
  status: "ok";
  version: string;
  dataDir: string;
  schemaVersion: number;
}

export const useHealth = () => useEngineQuery<Health>("/health");

/** Maku's records are damaged (maku.db won't open): what's wrong, and the newest backup that opens. */
export interface Damage {
  /** In SQLite's words: "file is not a database". */
  problem: string;
  /** The disk couldn't read them (a drive away a moment): trying again may be all it needs. */
  badRead: boolean;
  /** The backup's name ("maku 2026-10-11 0300.db"), or null when none opens. */
  backup: string | null;
  /** When it was made, local time. */
  made: string | null;
}

/** Whether Maku's records are damaged; null while they're fine. */
export const useRecords = () => useEngineQuery<Damage | null>("/records");
/**
 * The way back from damaged records: `/records/restore` (the newest backup that opens) or
 * `/records/new`. The app starts the engine again right after (`restartEngine`).
 */
export const useRecordsAction = () => useEngineAction<void>([]);

export type ToolState = "missing" | "downloading" | "unpacking" | "ready" | "failed";

/** Something Maku downloads to work with, such as ffmpeg (engine/src/maku/downloads.json). */
export interface Tool {
  id: string;
  name: string;
  version: string;
  purpose: string;
  licence: string;
  size: number;
  /** Fetched on the setup's Tools step, or the first time the owner asks for what needs it (the
   * speech models). */
  when: "setup" | "asked";
  state: ToolState;
  done: number;
  problem: string | null;
}

const busy = (state: ToolState) => state === "downloading" || state === "unpacking";

/** Maku's tools, asked again every second while one is downloading. */
export const useTools = () =>
  useEngineQuery<Tool[]>("/tools", (tools) =>
    tools?.some((tool) => busy(tool.state)) ? 1000 : false,
  );

/** Starts downloading a tool: `download.mutate({ path: "/tools/ffmpeg/download" })`. */
export const useDownloadTool = () => useEngineAction<Tool>(["/tools"]);

/** A folder in the library. */
export interface LibraryFolder {
  id: number;
  path: string;
  addedAt: string;
  /** False while its drive is unplugged. */
  available: boolean;
  files: number;
  unread: number;
  problems: number;
}

/** The library at a glance. */
export interface Library {
  folders: number;
  files: number;
  size: number;
  unread: number;
  problems: number;
  sd: number;
  hd720: number;
  hd1080: number;
  larger: number;
}

export type ScanState = "idle" | "running" | "paused" | "done" | "failed";

/** The latest scan. */
export interface Scan {
  state: ScanState;
  stage: "finding" | "reading" | "identifying" | "checking" | "done" | null;
  startedAt: string | null;
  finishedAt: string | null;
  found: number;
  toRead: number;
  read: number;
  problems: number;
  current: string | null;
  secondsLeft: number | null;
  unavailable: string[];
  problem: string | null;
  /** Series and films identified in the library. */
  titles: number;
  /** Files that need the owner to say which series or film they are. */
  waiting: number;
  /** What the scan couldn't do, though it finished (offline, or no TMDB key to look up with). */
  note: string | null;
  /** Folders holding more than one series or film. */
  mixed: number;
  /** Videos this scan found that weren't there before; null for a scan from before Maku counted. */
  added: number | null;
  /** Videos this scan found gone. */
  gone: number | null;
}

const LIBRARY = ["/folders", "/library", "/scan"];

/** The latest scan for the nav rail's badges: the window's shell asks for it already
 * (`useScan`). */
export const useScanGlance = () => useGlance<Scan>("/scan");

export const useFolders = () => useEngineQuery<LibraryFolder[]>("/folders");
export const useLibrary = () => useEngineQuery<Library>("/library");

/** What the engine changes by itself: a batch converted, the queue paused, files moved in. */
const CHANGED_ON_ITS_OWN = [
  "/queue",
  "/history",
  "/library",
  "/titles",
  "/franchises",
  "/convert",
  "/subtitles",
];

/** Asks again for what the engine may have changed by itself, once it tells of something. */
export function useEngineChanged(): () => void {
  const refresh = useRefresh();
  return useCallback(() => void refresh(CHANGED_ON_ITS_OWN), [refresh]);
}

/**
 * The latest scan, asked again every second while it runs. A scan fills in the library, so when
 * one stops, the library, its folders and what Maku proposes from them are asked again too.
 */
/** The scan each query client last caught up after: several parts of a screen follow scans, and
 * one catching up is enough. */
const caughtUp = new WeakMap<object, string>();

export function useScan() {
  // Every second while a scan runs; every three seconds otherwise, so a scan Maku starts on its
  // own (a video added or removed) shows soon too.
  const scan = useEngineQuery<Scan>("/scan", (now) => (now?.state === "running" ? 1000 : 3000));
  const refresh = useRefresh();
  const queries = useQueryClient();
  // A scan that has ended since this screen last looked, however quickly it ran (most take under
  // a second, between two looks): what it found shows everywhere.
  const key = scan.data ? `${scan.data.startedAt}:${scan.data.state}` : null;
  const seen = useRef<string | null>(null);
  useEffect(() => {
    if (key === null) return;
    const before = seen.current;
    seen.current = key;
    const ended = before !== null && before !== key && !key.endsWith(":running");
    if (ended && caughtUp.get(queries) !== key) {
      caughtUp.set(queries, key);
      void refresh([
        "/library",
        "/folders",
        "/titles",
        "/franchises",
        "/review",
        "/tidy",
        "/convert",
        "/history",
      ]);
    }
  }, [key, refresh, queries]);
  return scan;
}

/** Adds a folder: `add.mutate({ path: "/folders", body: { path } })`. */
export const useAddFolder = () => useEngineAction<LibraryFolder>(LIBRARY);
/** Forgets a folder: `forget.mutate({ path: "/folders/3" })`. Its files stay put. */
export const useForgetFolder = () => useEngineAction<void>(LIBRARY, "DELETE");
/** Starts, pauses or resumes the scan: `/scan`, `/scan/pause` or `/scan/resume`. */
export const useScanAction = () => useEngineAction<Scan>(LIBRARY);

/** Maku's preferences, chosen during setup. */
export interface Settings {
  /** The most a picture comes to: 4K, or 1080p to save room. Nothing is made bigger. */
  standard: "4k" | "1080p";
  naming: "plex" | "jellyfin" | "keep";
  /** The first-run steps are done. */
  setUp: boolean;
  /** A gap analysis next to each title that has a folder of its own. */
  reports: boolean;
  /** Days copies set aside and converted files' originals are kept, or null: for good. */
  quarantineDays: 7 | 30 | 90 | null;
  /** What a converted file's original becomes once its result is checked and in place. */
  originals: "quarantine" | "delete";
  /** Poster and background pictures next to each show, for media servers. */
  artwork: boolean;
  /** Days History keeps what Maku did before it's cleared out each day, or null: for good. */
  historyDays: 7 | 30 | 90 | null;
  /** Every video test-played overnight, a few at a time. */
  healthCheck: boolean;
}

export const useSettings = () => useEngineQuery<Settings>("/settings");
/** Saves the preferences: `save.mutate({ path: "/settings", body: settings })`. The standard
 * decides what's left to convert and how each episode stands, so the screens showing those are
 * asked again too. */
export const useSaveSettings = () =>
  useEngineAction<Settings>(
    ["/settings", "/convert", "/queue", "/data", "/titles", "/franchises", "/library"],
    "PUT",
  );

/** A video the overnight health check couldn't play. */
export interface UnplayedVideo {
  fileId: number;
  path: string;
  titleId: number | null;
  title: string | null;
  season: number | null;
  episode: number | null;
  episodeEnd: number | null;
  /** "It didn't play at 12:05 (…)". */
  problem: string;
  /** When it was checked; null: it's to be played again. */
  at: string | null;
}

/** How the health check stands: how many of the videos it plays were checked this month, and
 * the ones that didn't play. */
export interface Checkup {
  on: boolean;
  checked: number;
  total: number;
  unplayed: UnplayedVideo[];
}

export const useCheckup = () => useEngineQuery<Checkup>("/checkup");
/** The owner's word on a video that didn't play, `{ path: "/files/7/plays" }` (it plays after
 * all) or `"/files/7/broken"`; or every video played again: `"/checkup/again"`. */
export const useCheckupAction = () =>
  useEngineAction<void>(["/checkup", "/titles", "/franchises", "/library", "/convert"]);
/** Plays one video again now, as the night's check does: `{ path: "/files/7/check" }`. */
export const useCheckOne = () => useEngineAction<{ problem: string | null }>(["/checkup"]);

/** A drive's quarantine folder: copies set aside and converted files' originals. */
export interface Quarantined {
  folder: string;
  bytes: number;
  files: number;
}

/** How big each part of Maku's data is (Settings > Your data). */
export interface DataSizes {
  /** The data folder. */
  folder: string;
  database: number;
  artwork: number;
  /** Answers from TMDB, stills and comparison frames. */
  cache: number;
  logs: number;
  backups: number;
  tools: number;
  /** On each drive the library is on. */
  quarantine: Quarantined[];
  /** How the last move to another folder went. */
  moved: { source: string; target: string; at: string; problem: string | null } | null;
}

export const useDataSizes = () => useEngineQuery<DataSizes>("/data");
/**
 * Asks for Maku's data to move to another folder as the engine starts again, which the caller
 * asks the shell for next: `move.mutate({ path: "/data/move", body: { folder } })`.
 */
export const useMoveData = () => useEngineAction<void>([]);
/** Writes the export zip: `exporting.mutate({ path: "/export", body: { folder } })`. */
export const useExport = () => useEngineAction<{ path: string; size: number }>(["/data"]);

/** What Maku settled as it started again after closing unexpectedly (a crash, a power cut). */
export interface Recovery {
  /** When Maku started again. */
  at: string;
  /** Files that were converting: in line again, from their beginning. */
  restarted: number;
  /** Results that were taking their original's place: in it now. */
  finished: number;
  /** Originals put back, their results never in place. */
  putBack: number;
  /** A tidy-up's or a delete's file moves, settled. */
  moves: number;
}

/** What a crash left for Home to tell, while it's news; null otherwise. */
export const useRecovery = () => useEngineQuery<Recovery | null>("/recovery");

/** The owner has seen it: `seen.mutate({ path: "/recovery/seen" })`. */
export const useRecoverySeen = () => useEngineAction<void>(["/recovery"]);

/** A backup of Maku's records, made each night (Settings > Your data). */
export interface Backup {
  /** "maku 2026-10-11 0300.db" */
  name: string;
  /** Local time, to the minute: "2026-10-11T03:00". */
  made: string;
  size: number;
  /** Made just before another backup was restored. */
  beforeRestoring: boolean;
  /** The database an imported export held. */
  fromExport: boolean;
  /** Made when the owner asked ("Back up now"); kept apart from the nightly ones. */
  byHand: boolean;
}

export interface Backups {
  /** Newest first. */
  backups: Backup[];
  /** How the last restore went. */
  restored: { name: string; at: string; problem: string | null } | null;
}

export const useBackups = () => useEngineQuery<Backups>("/backups");
/** Makes a backup now: `backUp.mutate({ path: "/backups" })`. */
export const useBackUp = () => useEngineAction<Backup>(["/backups", "/data"]);
/**
 * Asks for a backup to be restored as the engine starts again, which the caller asks the shell
 * for next: `restore.mutate({ path: "/backups/<name>/restore" })`.
 */
export const useRestoreBackup = () => useEngineAction<void>([]);
/**
 * Asks for an export's records to be put in place as the engine starts again, the way a backup
 * is restored: `importing.mutate({ path: "/backups/import", body: { path } })`.
 */
export const useImportExport = () => useEngineAction<void>([]);

/** Whether Maku has a TMDB key: without one it reads videos but finds no series or film. */
export interface TmdbStatus {
  connected: boolean;
  /** The key's last four characters, to tell which key it is. */
  keyEnd: string | null;
}

export const useTmdb = () => useEngineQuery<TmdbStatus>("/tmdb");
/**
 * Checks a key with TMDB, then keeps it: `connect.mutate({ path: "/tmdb", body: { key } })`. A
 * scan then looks up the videos waiting for it, so the scan is asked about again.
 */
export const useConnectTmdb = () => useEngineAction<TmdbStatus>(["/tmdb", "/scan"], "PUT");
/** Forgets the key: `forget.mutate({ path: "/tmdb" })`. */
export const useForgetTmdb = () => useEngineAction<TmdbStatus>(["/tmdb"], "DELETE");

/** A graphics card, or the processor's graphics. */
export interface Card {
  /** As Windows names it: "NVIDIA GeForce GTX 1660 SUPER". */
  name: string;
  maker: "nvidia" | "amd" | "intel" | "other";
  /** Bytes of its own; null when Windows doesn't say. */
  memory: number | null;
  /** The processor's graphics, sharing the PC's memory. */
  integrated: boolean;
  /** Its driver's version, as its maker writes it: "617.42". */
  driver: string | null;
}

/** A part of Maku, as this PC's check lists them. */
export type PcAbility = "convert" | "subtitles" | "player";
/** A part of the check itself: the encoder, then DirectML for English subtitles. */
export type PcStep = "encoder" | "subtitles";
/** Where English subtitles of a quality are made. */
export type Place = "card" | "processor";

/** One part of Maku on this PC. */
export interface Ability {
  part: PcAbility;
  /** Ready; limited (a lighter way only); or not here. */
  state: "ready" | "limited" | "no";
  /** What does it here: "HEVC 10-bit on NVIDIA's encoder (NVENC)". */
  how: string;
  /** What's limited, or why it can't. */
  note: string | null;
  /** An hour of video's time here, in seconds: converting, 1080p's then 4K's; subtitles, Best's
   * then Fast's. */
  seconds: number[];
}

/** What this PC has, and what Maku can do on it and how fast. */
export interface System {
  /** The card Maku works on, as Windows names it; null when Windows wouldn't say. */
  graphicsCard: string | null;
  /** The card Maku works on: the one of its own with the most memory. */
  card: Card | null;
  cards: Card[];
  /** "Intel Core i5-9600K". */
  processor: string | null;
  cores: number | null;
  /** Bytes installed. */
  memory: number | null;
  /** When this PC was checked; null till it is. */
  checkedAt: string | null;
  /** The encoder that converts here; null without one, or before the check. */
  encoder: "nvenc" | "amf" | "qsv" | null;
  /** The card's maker's drivers, when its own encoder didn't start for want of a newer one. */
  driverLink: string | null;
  /** What that encoder said. */
  encoderProblem: string | null;
  /** Each part of Maku here, once this PC is checked. */
  abilities: Ability[];
  /**
   * Where English subtitles are made at each quality, null where this PC can't, and why Best
   * isn't here: its card hasn't the memory, or doesn't run DirectX 12.
   */
  subtitles: { best: Place | null; fast: Place | null; bestWants: "memory" | "directx" | null };
  /** How the times were measured; null while they're a guess. */
  measured: { at: string; tested: boolean; conversions: number; subtitles: number } | null;
  /** A check under way: its part, the parts done, the encoder's frames a second once timed. */
  testing: { step: PcStep; done: PcStep[]; fps: number | null; timing: boolean } | null;
}

/** Where a test's times show: what's to convert and the queue, and subtitles' estimates. */
const TIMED = ["/convert", "/subtitles", "/queue"];

/**
 * What this PC has and can do, asked every second while it's being tested; once a test is over,
 * the screens with times catch up.
 */
export function useSystem() {
  const query = useEngineQuery<System>("/system", (now) => (now?.testing ? 1000 : false));
  const refresh = useRefresh();
  const testing = Boolean(query.data?.testing);
  const was = useRef(testing);
  useEffect(() => {
    if (was.current && !testing) void refresh(TIMED);
    was.current = testing;
  }, [testing, refresh]);
  return query;
}

/** Tests this PC again, in the background: `test.mutate({ path: "/system/test" })`. */
export const useTestPc = () => useEngineAction<System>(["/system"]);

/** What a title is, in the words Maku shows: a TV series or a movie. A show's specials stay among
 * its episodes, in season 0. */
export type TitleKind = "series" | "movie";

/** The orders a list of titles can take; release date is the default everywhere. */
export type TitleSort = "released" | "name" | "added" | "missing";

/** A series or film in the library, with how much of it is there. */
export interface TitleSummary {
  id: number;
  kind: TitleKind;
  name: string;
  year: number | null;
  /** The first episode, or the film's release (ISO date): lists sort by it. */
  released: string | null;
  airing: boolean;
  hasPoster: boolean;
  /** Videos in the library. */
  files: number;
  added: string | null;
  /** Numbered episodes out so far; 0 for a film. */
  aired: number;
  present: number;
  missing: number;
  /** Specials the library lacks: listed apart, never counted as missing. */
  specialsMissing: number;
  upcoming: number;
}

export interface SeasonCount {
  season: number;
  present: number;
  aired: number;
  total: number;
}

export interface EpisodeRef {
  season: number;
  number: number;
  name: string | null;
  aired: string | null;
}

export interface TitleFile {
  id: number;
  path: string;
  /** In bytes. */
  size: number;
  season: number | null;
  episode: number | null;
  episodeEnd: number | null;
  problem: string | null;
  height: number | null;
  codec: string | null;
  duration: number | null;
  /** The languages it can be heard and read in: its sound tracks', and its subtitles' in it and
   * beside it ("jpn", "en"; "" for one that doesn't say), each once. */
  sound: string[];
  subtitles: string[];
  /** What Whisper heard ("ja") in a sound track that doesn't say its language, when Maku made
   * English subtitles from it: that track's language in `sound`. */
  heard: string | null;
  /** English subtitles Maku made from its sound are beside it. */
  made: boolean;
  /** In the queue for English subtitles, or having them made. */
  subtitlesJob: "queued" | "running" | null;
  /** Seen to its last tenth, or marked watched. */
  watched: boolean;
  /** Where Play picks it up, in seconds; null for from the top. */
  resume: number | null;
}

/** How an episode stands; on screen each has its shape (see the status-* utilities). */
export type EpisodeStateName = "ready" | "to convert" | "broken" | "missing" | "upcoming";

export interface EpisodeState {
  /** 0 for the specials. */
  season: number;
  number: number;
  name: string | null;
  aired: string | null;
  state: EpisodeStateName;
  fileId: number | null;
}

/** One title in full: its seasons, every episode's state, what it's missing, and its videos. */
export interface TitleDetail extends TitleSummary {
  /** The collection it's one of (a franchise, to the engine), when the library has several of
   * its films. */
  franchise: FranchiseRef | null;
  /** Its own folder, when its videos have one. */
  folder: string | null;
  seasons: SeasonCount[];
  missingEpisodes: EpisodeRef[];
  missingSpecials: EpisodeRef[];
  upcomingEpisodes: EpisodeRef[];
  episodes: EpisodeState[];
  videos: TitleFile[];
  about: TitleAbout;
}

/** Where a title stands: its episodes are all out, more are coming, none is out yet, it was
 * stopped, or it's resting before it goes on. */
export type TitleStatus = "finished" | "airing" | "coming" | "cancelled" | "paused";

/** What a title's About panel says, from TMDB, and where to read more. */
export interface TitleAbout {
  overview: string | null;
  genres: string[];
  studio: string | null;
  status: TitleStatus | null;
  /** Its first episode, or the film's release (ISO date). */
  started: string | null;
  /** Its latest episode so far; null for a film, or while unknown. */
  ended: string | null;
  /** An episode's usual length, or the film's. */
  minutes: number | null;
  /** Its page on TMDB. */
  tmdbType: "tv" | "movie" | null;
  tmdbId: number | null;
}

/** A video in full, for its details. */
export interface FileDetails {
  id: number;
  path: string;
  /** In bytes. */
  size: number;
  /** When Maku first found it. */
  foundAt: string;
  /** In seconds. */
  duration: number | null;
  /** Why it can't be read. */
  problem: string | null;
  titleId: number | null;
  title: string | null;
  season: number | null;
  episode: number | null;
  episodeEnd: number | null;
  /** The (first) episode it holds, as TMDB names it. */
  episodeName: string | null;
  aired: string | null;
  /** What happens in it: a spoiler, shown on asking. */
  overview: string | null;
  picture: {
    codec: string;
    width: number;
    height: number;
    bitDepth: number;
    frameRate: number | null;
  } | null;
  sound: {
    language: string | null;
    codec: string;
    channels: number;
    lossless: boolean;
    /** Its language is the one Maku heard, as the track doesn't say. */
    heard: boolean;
  }[];
  subtitles: {
    language: string | null;
    /** Null for a file beside the video. */
    codec: string | null;
    /** Words (ASS, SRT) rather than pictures (PGS, DVD). */
    text: boolean;
    /** Signs and songs only. */
    forced: boolean;
    /** A file beside the video rather than a track in it. */
    beside: boolean;
    /** English subtitles Maku made. */
    made: boolean;
  }[];
  chapters: number;
  /** Maku made it: its tag is inside. */
  converted: boolean;
  /** What converting it to the library's standard does. */
  converting: {
    state: "ready" | "to convert" | "broken";
    method: Method | "rename" | "skip" | null;
    /** In words: "4K HDR: brought down to 1080p, HDR kept". */
    reasons: string[];
  };
}

/** One episode as TMDB lists it, whether the library has it or not. */
export interface EpisodeDetails {
  season: number;
  number: number;
  name: string | null;
  aired: string | null;
  overview: string | null;
  minutes: number | null;
  /** Its video, when the library has it. */
  fileId: number | null;
}

export const useFileDetails = (id: number | null) =>
  useEngineQuery<FileDetails>(`/files/${id ?? 0}`, undefined, id !== null);
/** The picture across the top of a video's details: TMDB's from its episode, a frame from the
 * file, or its show's wide picture (`source` says which); `problem` once there's none. */
export const useFilePicture = (id: number | null) =>
  useEnginePicture(id === null ? null : `/files/${id}/picture`);
/** The same for an episode the library may not have: TMDB's from it, or its show's. */
export const useEpisodePicture = (
  titleId: number,
  episode: { season: number; number: number } | null,
) =>
  useEnginePicture(
    episode ? `/titles/${titleId}/episodes/${episode.season}/${episode.number}/picture` : null,
  );
export const useEpisodeDetails = (
  titleId: number,
  season: number,
  number: number,
  enabled = true,
) =>
  useEngineQuery<EpisodeDetails>(
    `/titles/${titleId}/episodes/${season}/${number}`,
    undefined,
    enabled,
  );

/** A video "Continue watching" plays, or one that plays after it. */
export interface NextVideo {
  fileId: number;
  season: number | null;
  episode: number | null;
  episodeEnd: number | null;
  /** Its episode's, as TMDB names it. */
  name: string | null;
  path: string;
  /** In seconds. */
  duration: number | null;
  /** Where Play picks it up, in seconds; null for from the top. */
  resume: number | null;
}

/** A title to go on with, on Home: the video stopped part way, or the one after the last seen. */
export interface Continuing {
  titleId: number;
  title: string;
  kind: TitleKind;
  hasPoster: boolean;
  playedAt: string;
  /** The one after the last seen, rather than one stopped part way. */
  upNext: boolean;
  video: NextVideo;
  /** What plays after it, in order. */
  following: NextVideo[];
}

/** The library in a few numbers, for Home. */
export interface LibraryGlance {
  /** How long it all plays. */
  seconds: number;
  /** Seconds of it watched. */
  watched: number;
  /** What converting did to the space the converted files take. */
  converted: { files: number; before: number; after: number };
  /** The titles taking the most room, the biggest first. */
  biggest: { titleId: number; name: string; files: number; size: number }[];
  /** In bytes, all of it. */
  size: number;
}

export const useLibraryGlance = () => useEngineQuery<LibraryGlance>("/library/glance");

/** A title's next episode, still to come, and how many more its list has after it. */
export interface ComingEpisode {
  titleId: number;
  title: string;
  kind: TitleKind;
  hasPoster: boolean;
  /** 0 for one of its specials. */
  season: number;
  number: number;
  name: string | null;
  /** The day it airs. */
  aired: string;
  /** Episodes listed after it. */
  later: number;
}

/** Home's "Coming up": the soonest first. */
export const useComing = () => useEngineQuery<ComingEpisode[]>("/coming");

/** Home's "Continue watching": the latest played first. */
export const useContinue = () => useEngineQuery<Continuing[]>("/continue");
/** Marks videos watched or not: `{ path: "/files/watched", body: { files, watched } }`. */
export const useMarkWatched = () => useEngineAction<void>(["/titles", "/continue", "/library"]);
/** Leaves a title out of "Continue watching" till it plays again: `{ path: "/continue/7" }`. */
export const useStopContinuing = () => useEngineAction<void>(["/continue"], "DELETE");

/**
 * Says where a video is to the engine (`PUT /files/{id}/position`), as the player plays it:
 * `stopped` once it stops, so its title's page and Home's "Continue watching" catch up.
 */
export function usePositionNote() {
  const engine = useEngine();
  const refresh = useRefresh();
  return useCallback(
    (fileId: number, position: number, duration: number | null, stopped: boolean) => {
      if (engine.state !== "ready") return;
      void callEngine<void>(engine, `/files/${fileId}/position`, {
        method: "PUT",
        body: JSON.stringify({ position, duration: duration || null }),
        headers: { "Content-Type": "application/json" },
      })
        .then(() => (stopped ? refresh(["/titles", "/continue", "/library"]) : undefined))
        // A position that didn't reach the engine is a small thing: the next one says it again.
        .catch(() => {});
    },
    [engine, refresh],
  );
}

/** A poster the owner can choose for a title: one of TMDB's. */
export interface PosterOption {
  /** What's kept: TMDB's image path. */
  poster: string;
  /** Where the picture is, to show it. */
  address: string;
  /** "en", "fr"; null for one without words. */
  language: string | null;
  width: number | null;
  height: number | null;
}

/** The posters to choose from for a title, the one it has first. */
export interface PosterChoices {
  /** The poster TMDB gave it. */
  found: string | null;
  /** The owner's, when they chose one. */
  chosen: string | null;
  options: PosterOption[];
  /** Why TMDB's couldn't be asked for now. */
  problem: string | null;
}

export const usePosterChoices = (titleId: number, enabled: boolean) =>
  useEngineQuery<PosterChoices>(`/titles/${titleId}/posters`, undefined, enabled);
/** Keeps the owner's choice of poster, or null for the one found:
 * `{ path: "/titles/7/poster", body: { poster } }`. Every screen showing the poster follows. */
export const useChoosePoster = () =>
  useEngineAction<void>(["/titles", "/franchises", "/continue", "/coming", "/search"], "PUT");

/** A title's About panel alone: a franchise's page shows its lead's. */
export const useTitleAbout = (id: number, enabled = true) =>
  useEngineQuery<TitleAbout>(`/titles/${id}/about`, undefined, enabled);

/** The gap analysis Maku wrote next to a title. */
export interface Report {
  path: string;
  text: string;
}

/** The library's titles in `sort` order, asked again every two seconds while `poll`. */
export const useTitles = (sort: TitleSort = "released", poll = false) =>
  useEngineQuery<TitleSummary[]>(`/titles?sort=${sort}`, () => (poll ? 2000 : false), true, true);
export const useTitle = (id: number, enabled = true) =>
  useEngineQuery<TitleDetail>(`/titles/${id}`, undefined, enabled);
export const useReport = (id: number) => useEngineQuery<Report>(`/titles/${id}/report`);

/** A series or film a search found, by its own name or another it goes by (`also`). */
export interface TitleFound {
  id: number;
  name: string;
  kind: TitleKind;
  year: number | null;
  hasPoster: boolean;
  /** The other name it was found by (its original title, say), when not its own. */
  also: string | null;
}

/** An episode a search found by its code or name. */
export interface EpisodeFound {
  titleId: number;
  title: string;
  /** 0 for a special. */
  season: number;
  number: number;
  name: string | null;
  /** Its video, or null when the library hasn't it. */
  fileId: number | null;
  /** Not out yet. */
  coming: boolean;
}

/** A video a search found by its file's name. */
export interface FileFound {
  fileId: number;
  path: string;
  titleId: number | null;
  title: string | null;
  season: number | null;
  episode: number | null;
  episodeEnd: number | null;
  /** In a title, waiting for a match, set aside as not a series or film, an extra (an opening,
   * an ending, a preview), under no title for another reason, or still being read. */
  place: "title" | "match" | "aside" | "extra" | "other" | "reading";
}

/** What a search of the library found, each kind's closest few, and how many in all. */
export interface Found {
  titles: TitleFound[];
  episodes: EpisodeFound[];
  files: FileFound[];
  totalTitles: number;
  totalEpisodes: number;
  totalFiles: number;
}

/** The library searched from the title bar: its series and films, their episodes and its
 * videos. Nothing is asked till there's `query` to ask, and a new search shows the last one's
 * till it comes. */
export const useSearch = (query: string) =>
  useEngineQuery<Found>(
    `/search?q=${encodeURIComponent(query)}`,
    undefined,
    query.trim().length > 0,
    true,
  );

export interface FranchiseRef {
  /** Its lead title's. */
  id: number;
  name: string;
}

/**
 * Titles that go together: the films TMDB keeps in one collection, which the screens call a
 * collection. Its `name` is the collection's ("The Starfall Collection") when the library has
 * several of its films. A title on its own is a franchise of one: a series always stands alone.
 */
export interface FranchiseSummary extends FranchiseRef {
  /** Its first release (ISO date). */
  released: string | null;
  kinds: Record<TitleKind, number>;
  /** Its lead's. */
  hasPoster: boolean;
  airing: boolean;
  files: number;
  added: string | null;
  aired: number;
  present: number;
  missing: number;
  specialsMissing: number;
  upcoming: number;
  /** In the order asked for. */
  titles: TitleSummary[];
}

/** Every franchise with its titles, in `sort` order: Home's shelf. */
export const useFranchises = (sort: TitleSort = "released") =>
  useEngineQuery<FranchiseSummary[]>(`/franchises?sort=${sort}`, undefined, true, true);
/** The franchise a title belongs to (any of its titles finds it), its titles in `sort` order. */
export const useFranchise = (id: number, sort: TitleSort = "released") =>
  useEngineQuery<FranchiseSummary>(`/franchises/${id}?sort=${sort}`, undefined, true, true);

/** A film of a franchise's collection that the library has no part of, as TMDB knows it. */
export interface MissingTitle {
  /** The TMDB entry Maku knows it by (a film's number negated). */
  entryId: number;
  kind: TitleKind;
  name: string;
  year: number | null;
  /** Its first episode, or the film's release (ISO date). */
  released: string | null;
  /** Null while TMDB doesn't say how many. */
  episodes: number | null;
  /** Not out yet. */
  coming: boolean;
  /** Out, with more of it still to come. */
  airing: boolean;
  /** Its poster's path on TMDB's image server (shown through the engine, `useCover`). */
  cover: string | null;
  /** Its synopsis. */
  overview: string | null;
  genres: string[];
  /** The first company TMDB names for it. */
  studio: string | null;
  /** Its page on TMDB. */
  tmdbType: "tv" | "movie";
  tmdbId: number;
}

/** The films of a franchise's collection that the library has none of. */
export interface FranchiseMissing {
  /** Oldest release first. */
  titles: MissingTitle[];
  /** Maku is still looking some of the franchise up, a few entries at a time. */
  looking: boolean;
}

/** What a franchise lacks, asked again every 10 seconds while Maku is still looking it up; not
 * asked while `enabled` is false (a series, which no collection holds). */
export const useFranchiseMissing = (id: number, enabled = true) =>
  useEngineQuery<FranchiseMissing>(
    `/franchises/${id}/missing`,
    (now) => (now?.looking ? 10_000 : false),
    enabled,
  );

/** One of Maku's guesses for a file it couldn't place surely: a show or film on TMDB. */
export interface Guess {
  /** The TMDB entry: a show's number, or a film's negated. */
  entryId: number;
  title: string;
  kind: TitleKind | null;
  year: number | null;
  episodes: number | null;
  minutes: number | null;
  cover: string | null;
  /** 0 to 100. */
  confidence: number;
  reasons: string[];
}

/** A file waiting for the owner to say which series or film it is. */
export interface WaitingFile {
  id: number;
  path: string;
  size: number;
  minutes: number | null;
  height: number | null;
  codec: string | null;
  audio: string[];
  subtitles: string[];
  group: string | null;
  title: string | null;
  season: number | null;
  episode: number | null;
  kind: "episode" | "special" | "movie" | "extra" | "dvd";
  guesses: Guess[];
  /** Other waiting files beside it from the same release. */
  alike: number[];
}

/**
 * The files waiting for a match; with `title`, that title's files as one, to change its match (its
 * first file, with the others alike).
 */
export const useReview = (title: number | null = null) =>
  useEngineQuery<WaitingFile[]>(title === null ? "/review" : `/review?title=${title}`);
/**
 * TMDB's shows and films for `text`, scored against one file; asked only for two letters or
 * more. The last answer stays on screen while the next loads. Without a TMDB key the engine
 * refuses (409), saying where the key goes.
 */
export const useMatchSearch = (fileId: number, text: string) =>
  useEngineQuery<Guess[]>(
    `/review/${fileId}/search?q=${encodeURIComponent(text.trim())}`,
    undefined,
    text.trim().length >= 2,
    true,
  );
/** What the owner's choice did: files placed, files that didn't fit it and wait now, and where
 * the file went. */
export interface Chosen {
  placed: number;
  waiting: number;
  titleId: number | null;
}

/**
 * The owner's choice: `choose.mutate({ path: "/review/7", body: { entryId, kind, also, episode } })`,
 * or with `title` instead of `also`, a whole title's new match (each file keeps its kind).
 */
export const useChooseMatch = () =>
  useEngineAction<Chosen>(["/review", "/titles", "/franchises", "/scan", "/library", "/tidy"]);
/** Not a series or film: `ignore.mutate({ path: "/review/7/ignore" })`. */
export const useIgnoreFile = () => useEngineAction<void>(["/review", "/scan", "/tidy"]);

/** A file the owner said isn't a series or film: left where it is, out of the library. */
export interface IgnoredFile {
  id: number;
  path: string;
  /** In bytes. */
  size: number;
}

/** The files the owner said aren't series or films, in name order. */
export const useIgnored = () => useEngineQuery<IgnoredFile[]>("/review/ignored");
/** A series or film after all: `unignore.mutate({ path: "/review/7/ignore" })`; it waits for a
 * match again. */
export const useUnignore = () => useEngineAction<void>(["/review", "/scan", "/tidy"], "DELETE");

/**
 * A picture the engine serves (a poster, a cover, a still) as an address the page can show (an
 * object URL), or null while there's none. Fetched with this launch's token, since the engine
 * answers nothing without it.
 */
export function useEngineImage(path: string | null): string | null {
  const engine = useEngine();
  const [shown, setShown] = useState<{ path: string; address: string } | null>(null);
  useEffect(() => {
    if (path === null || engine.state !== "ready") return;
    let address: string | null = null;
    let cancelled = false;
    const headers = { Authorization: `Bearer ${engine.token}` };
    fetch(new URL(path, engine.url), { headers })
      .then((response) => (response.ok ? response.blob() : null))
      .then((blob) => {
        if (!blob || cancelled) return;
        address = URL.createObjectURL(blob);
        setShown({ path, address });
      })
      .catch(() => {}); // no picture: the placeholder stays
    return () => {
      cancelled = true;
      if (address) URL.revokeObjectURL(address);
    };
  }, [engine, path]);
  return shown !== null && shown.path === path ? shown.address : null;
}

/**
 * A picture the engine makes on asking (a frame to compare), with why it couldn't when it
 * couldn't: `address` while it's there, `problem` in the engine's words.
 */
/** Where a video's or an episode's picture is from: the episode itself, or its show. */
export type PictureSource = "episode" | "show";

export function useEnginePicture(path: string | null): {
  address: string | null;
  problem: string | null;
  /** Where a video's or an episode's picture is from (`Maku-Picture`): "episode" for TMDB's
   * picture from it or a frame, "show" for its show's; null for any other picture. */
  source: PictureSource | null;
} {
  const engine = useEngine();
  const [shown, setShown] = useState<{
    path: string;
    address: string | null;
    problem: string | null;
    source: PictureSource | null;
  } | null>(null);
  useEffect(() => {
    if (path === null || engine.state !== "ready") return;
    let address: string | null = null;
    let cancelled = false;
    const headers = { Authorization: `Bearer ${engine.token}` };
    fetch(new URL(path, engine.url), { headers })
      .then(async (response) => {
        if (cancelled) return;
        if (!response.ok) {
          const problem = (await problemIn(response)) ?? "Maku couldn't make the picture.";
          if (!cancelled) setShown({ path, address: null, problem, source: null });
          return;
        }
        const told = response.headers.get("Maku-Picture");
        const source = told === "episode" || told === "show" ? told : null;
        const blob = await response.blob();
        if (cancelled) return;
        address = URL.createObjectURL(blob);
        setShown({ path, address, problem: null, source });
      })
      .catch(() => {
        if (!cancelled) {
          setShown({ path, address: null, problem: "Maku's engine didn't answer.", source: null });
        }
      });
    return () => {
      cancelled = true;
      if (address) URL.revokeObjectURL(address);
    };
  }, [engine, path]);
  if (shown === null || shown.path !== path) return { address: null, problem: null, source: null };
  return { address: shown.address, problem: shown.problem, source: shown.source };
}

/** A title's poster, when it has one. */
// How many times each title's poster was chosen this session: its pictures load anew.
const posterTurns = new Map<number, number>();
const posterListeners = new Set<() => void>();

/** The owner chose another poster for a title: every picture of it loads anew. */
export function posterChanged(titleId: number) {
  posterTurns.set(titleId, (posterTurns.get(titleId) ?? 0) + 1);
  for (const listener of posterListeners) listener();
}

function onPosterChange(listener: () => void) {
  posterListeners.add(listener);
  return () => {
    posterListeners.delete(listener);
  };
}

export function usePoster(titleId: number, has: boolean) {
  const turn = useSyncExternalStore(onPosterChange, () => posterTurns.get(titleId) ?? 0);
  return useEngineImage(has ? `/titles/${titleId}/poster${turn ? `?v=${turn}` : ""}` : null);
}
/** A poster from TMDB's image server (a guess's, or a missing film's), through the engine. */
export const useCover = (address: string | null) =>
  useEngineImage(address ? `/artwork?address=${encodeURIComponent(address)}` : null);
/** The same, with `problem` once it can't be had: for a card that shows a stand-in then. */
export const useCoverPicture = (address: string | null) =>
  useEnginePicture(address ? `/artwork?address=${encodeURIComponent(address)}` : null);
/** One of a waiting file's three stills (0, 1 or 2). */
export const useStill = (fileId: number, index: number) =>
  useEngineImage(`/review/${fileId}/stills/${index}`);

/** Why a change is proposed: a rename in place, a move out of a folder holding several titles,
 * or a second copy of an episode set aside. */
export type TidyCategory = "rename" | "mixed" | "duplicate";

/** One change Maku proposes. Nothing moves until the owner applies it. */
export interface ProposedChange {
  kind: "move" | "quarantine";
  source: string;
  target: string;
  /** The library folder it's in. */
  root: string;
  /** "The Harbour Line · S01E01", "The Harbour Line · S01E01 · subtitles". */
  label: string;
  reason: string;
  category: TidyCategory;
  titleId: number;
  title: string;
  /** Its name was another file's, so it gets "(2)": Maku never overwrites a file. */
  taken: boolean;
  /**
   * When it was taken: the file there (null when Maku doesn't know it), this one, and what the
   * one there does in the same tidy-up: stays, leaves (moved or set aside), or arrives there.
   */
  compared: {
    there: CopyFacts | null;
    coming: CopyFacts;
    thereGoes: "stays" | "leaves" | "arrives";
  } | null;
  /** The video the change is of: itself, or the one subtitles go with. */
  video: string;
}

/** What decides between two copies of one episode. */
export interface CopyFacts {
  path: string;
  height: number | null;
  codec: string | null;
  audio: string[];
  /** Subtitle tracks that can be switched off. */
  subtitles: number;
  size: number;
  plays: boolean;
  /** Its subtitles' languages, in it and in the files beside it ("ger", "en"; "" unsaid). */
  subtitleLanguages: string[];
}

/** English the copy set aside has in it that the one kept hasn't, which Maku can add. */
export interface English {
  /** The copy set aside. */
  other: string;
  /** Its English sound comes. */
  sound: boolean;
  /** Its English subtitles come. */
  subtitles: boolean;
  /** Why Maku couldn't, the last time it was asked to. */
  tried: string | null;
}

/** Copies of one episode or movie: the one Maku keeps, and the ones it sets aside. */
export interface Duplicate {
  label: string;
  keep: CopyFacts;
  drop: CopyFacts[];
  reason: string;
  /** Two copies: what the one set aside could give the one kept. */
  english: English | null;
}

export interface TidyProposal {
  changes: ProposedChange[];
  /** Videos that stay where they are, and why. */
  skipped: { path: string; reason: string }[];
  duplicates: Duplicate[];
  /** Videos that need a match first. */
  waiting: number;
  /** Videos that won't play. */
  broken: number;
}

/** A proposed change as the owner saw it: what applying sends, so the engine makes exactly
 * that, or nothing if its proposal changed meanwhile. */
export type ReviewedChange = Pick<ProposedChange, "source" | "kind" | "target">;

/** What applying or undoing a tidy-up did. */
export interface TidyResult {
  /** Null when nothing was asked for. */
  planId: number | null;
  moved: number;
  quarantined: number;
  problems: { label: string; source: string; problem: string }[];
  /** Copies kept whose other copy's English joined the queue. */
  english: number;
}

/** Where every video would go; `keep` holds copies the owner keeps instead. */
export const useTidy = (keep: string[] = []) =>
  useEngineQuery<TidyProposal>(
    `/tidy${keep.length ? `?${keep.map((path) => `keep=${encodeURIComponent(path)}`).join("&")}` : ""}`,
    undefined,
    true,
    true,
  );
/** What tidying up proposes, for the nav rail's badge: asked again after every scan, tidy-up
 * and match, not every time the window comes back into focus (it takes a moment to work out). */
export const useTidyGlance = () => useGlance<TidyProposal>("/tidy");
const TIDIED = [
  "/tidy",
  "/history",
  "/titles",
  "/franchises",
  "/library",
  "/review",
  "/convert",
  "/queue",
  "/data",
];
/** Makes the changes: `apply.mutate({ path: "/tidy", body: { changes, keep, english } })`,
 * `changes` being ReviewedChange[] and `english` the copies kept that get the English of the
 * copy set aside (which then stays where it is till the queue has added it). */
export const useApplyTidy = () => useEngineAction<TidyResult>(TIDIED);
/** Puts back what a tidy-up moved (or what couldn't go back last time):
 * `undo.mutate({ path: "/plans/12/undo" })`. */
export const useUndoPlan = () => useEngineAction<TidyResult>(TIDIED);
/**
 * Deletes videos the way Maku deletes: into the quarantine with their subtitles, put back from
 * History till it's cleared out: `remove.mutate({ path: "/files/delete", body: { files } })`.
 */
export const useDeleteFiles = () => useEngineAction<TidyResult>([...TIDIED, "/queue"]);

/** A video's picture and size, before or after converting. */
export interface Picture {
  height: number | null;
  codec: string | null;
  size: number | null;
}

/** What converting made of a file, as History tells it. */
export interface Conversion {
  jobId: number;
  /** A conversion, or English added from another copy (nothing converted: `method` is a remux),
   * which went to quarantine with the original. */
  kind: "convert" | "merge";
  method: Method;
  before: Picture;
  after: Picture;
  /** How long converting took. */
  seconds: number | null;
  /** The original is back in its place. */
  restored: boolean;
  /** A later conversion, or another copy's English, replaced the file since: that's put back
   * first. */
  replaced: boolean;
}

/** A tidy-up or conversion that was applied, as History lists it. */
export interface PlanDone {
  id: number;
  kind: "tidy" | "convert";
  /** "Renamed 26 The Harbour Line files", "Converted Glass Orchard · S01E03". */
  title: string;
  appliedAt: string;
  undoneAt: string | null;
  moved: number;
  quarantined: number;
  failed: number;
  undone: number;
  /** The owner deleted these videos: they went to quarantine. */
  deleted: boolean;
  conversion: Conversion | null;
  /** English subtitles Maku made, taken away: those set aside and still there to put back. */
  takenAway: number;
}

/** A batch of English subtitles the owner asked for at once, as History lists it. */
export interface SubtitlesDone {
  id: number;
  /** What they're for: "Starfall Academy · Season 1". */
  title: string;
  quality: Quality;
  /** The sound they're made from: "jpn". */
  language: string;
  /** When the latest of them was over. */
  madeAt: string;
  /** Videos that got them. */
  made: number;
  /** Videos where no one speaks: none were made. */
  quiet: number;
  /** Videos they couldn't be made for. */
  failed: number;
  /** Videos still in the queue for them. */
  waiting: number;
  /** Of those made, how many are there now as Maku wrote them. */
  present: number;
}

export interface ScanDone {
  id: number;
  startedAt: string;
  finishedAt: string | null;
  state: "running" | "paused" | "done" | "failed";
  problem: string | null;
  note: string | null;
  /** Videos it found new, and gone; null for a scan from before Maku counted. */
  added: number | null;
  gone: number | null;
}

/** What Maku did on a week's worth of days with anything on them, newest first. */
export interface History {
  /** A tidy-up undone on a later day is on that day's page too. */
  plans: PlanDone[];
  scans: ScanDone[];
  subtitles: SubtitlesDone[];
  /** The day the next page starts before ("2026-10-07"); null: there's no more. */
  older: string | null;
}

/**
 * History, a page of days at a time: `fetchNextPage()` adds the days before. Every page loaded is
 * asked again when History changes. With a `query`, only what names that title or file, on the
 * days it finds anything on.
 */
export function useHistory(query = "") {
  const engine = useEngine();
  const search = query.trim() ? `q=${encodeURIComponent(query.trim())}` : "";
  return useInfiniteQuery({
    queryKey: engineKey(engine, search ? `/history?${search}` : "/history"),
    queryFn: ({ pageParam }) => {
      if (engine.state !== "ready") throw new EngineError("The engine isn't ready yet.");
      const asked = [search, pageParam ? `before=${pageParam}` : ""].filter(Boolean).join("&");
      return callEngine<History>(engine, asked ? `/history?${asked}` : "/history");
    },
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.older ?? null,
    enabled: engine.state === "ready",
    placeholderData: keepPreviousData, // a new search shows the last one's till it comes
  });
}

/** Forgets what Maku did before the last day, week or month, or all of it:
 * `clear.mutate({ path: "/history/clear", body: { keep } })`. Files don't change. */
export const useClearHistory = () => useEngineAction<{ cleared: number }>(["/history"]);

/** How a file is converted: its picture copied into an MKV, or made anew in HEVC 10-bit. */
export type Method = "remux" | "reencode";

/** A video not at the library's standard yet, with what it gets and what that takes. */
export interface Convertible {
  fileId: number;
  /** "Glass Orchard · S01E06". */
  label: string;
  titleId: number | null;
  title: string | null;
  season: number | null;
  episode: number | null;
  /** How long it plays. */
  seconds: number;
  width: number;
  height: number;
  /** "4:3", "16:9". */
  aspect: string;
  /** An HDR picture, which stays HDR. */
  hdr: "HDR10" | "HLG" | null;
  size: number;
  /** "D:". */
  drive: string;
  /** What it gets: a new picture, or its own in an MKV. */
  method: Method;
  /** Why, in words: "4K HDR: brought down to 1080p, HDR kept". */
  reasons: string[];
  /** The result's picture: its own size, or brought down to the standard. */
  outputWidth: number;
  outputHeight: number;
  /** Its GPU time on this PC, about; none for a broken file. */
  gpuSeconds: number;
  /** The result's size, about; none for a broken file. */
  outputBytes: number;
  /** In the queue already, or converting. */
  waiting: boolean;
  /** It won't play, so it can't be converted. */
  broken: boolean;
}

export interface ConvertOptions {
  /** "4K": the most any picture comes to. */
  standard: string;
  files: Convertible[];
  /** Bytes free on each drive the files are on. */
  free: Record<string, number>;
  /** Bytes emptying each drive's quarantine would free. */
  setAside: Record<string, number>;
}

export const useConvertOptions = () => useEngineQuery<ConvertOptions>("/convert");

export type JobState =
  | "queued"
  | "running"
  | "replacing"
  | "done"
  | "failed"
  | "skipped"
  | "restored";

/** A file in the queue: to convert, or to have English subtitles made (`method` their quality). */
export interface Job {
  id: number;
  fileId: number;
  path: string;
  label: string;
  titleId: number | null;
  title: string | null;
  season: number | null;
  episode: number | null;
  /** What it gets: a conversion's method, or subtitles' quality. */
  method: Method | Quality;
  state: JobState;
  /** How long it takes on the graphics card, as estimated. */
  gpuSeconds: number;
  addedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  /** Why it failed, in words. */
  problem: string | null;
  sourceSize: number;
  outputSize: number | null;
  /** The result's picture, for a file still to finish. */
  width: number | null;
  height: number | null;
  /** Waiting, and its drive isn't connected: it goes when the drive is back. */
  driveMissing: boolean;
  /**
   * Made, and waiting beside its original for another app (a player) to let go of it: when Maku
   * tries again to put it in place.
   */
  retryAt: string | null;
  /** What ffmpeg said, when a conversion failed ("Copy full log"). */
  log: string | null;
  /** Waiting for room on its drive while the others go. */
  noRoom: boolean;
  /** A conversion, English subtitles, or English from another copy added to the file. */
  kind: "convert" | "subtitles" | "merge";
  /** Subtitles: the sound they're made from ("jpn"; "" when it doesn't say). */
  language: string | null;
  /** Subtitles waiting for their speech model to download. */
  modelMissing: boolean;
  /** Subtitles at Best that failed where Fast would go: "Make them with Fast". */
  fastInstead: boolean;
}

/** A drive without room for the files waiting to convert on it. */
export interface Room {
  /** "D:". */
  drive: string;
  /** The queue paused for it; else the files that don't fit wait while the others go. */
  paused: boolean;
  /** Files waiting to convert on it. */
  files: number;
  /** The free space their results want, in bytes. */
  needed: number;
  /** Bytes free on it now. */
  free: number;
  /** How many of them fit now, in turn. */
  fit: number;
  /** Bytes its quarantine would free, emptied now. */
  setAside: number;
}

/** The file converting now, or having its subtitles made, and how it's going. */
export interface RunningJob {
  job: Job;
  stage: "looking" | "converting" | "checking" | "replacing" | "reading" | "listening" | "writing";
  /** Frames converted; for subtitles, seconds of the video heard. */
  frames: number;
  total: number;
  secondsLeft: number | null;
  /** Frames a second, over the last ten minutes. */
  fps: number | null;
}

export interface QueueStatus {
  paused: boolean;
  schedule: "now" | "nights";
  /** Nights only, and it's day (or tonight's run is over): files start again at 23:00. */
  waitsForNight: boolean;
  /** Why nothing converts though files wait (no ffmpeg, say). */
  problem: string | null;
  running: RunningJob | null;
  /** In the order they'll go. */
  queued: Job[];
  /** The work left, in seconds of GPU time. */
  gpuSeconds: number;
  /** Finished today, newest first. */
  today: Job[];
  /** The graphics card's load and temperature, while a file converts. */
  gpu: { busy: number; celsius: number } | null;
  /** A drive without room for what waits on it. */
  room: Room | null;
  /**
   * Nights only, at night: when tonight's run takes its last file (07:00, or earlier when the
   * owner said to stop early), local time.
   */
  endsAt: string | null;
  /** The owner said to stop early tonight. */
  early: boolean;
}

/** The queue, asked again every two seconds while a file converts, else every ten. */
export const useQueue = () =>
  useEngineQuery<QueueStatus>("/queue", (now) => (now?.running ? 2000 : 10_000));
/** The queue for the nav rail's badge, asked every 10 seconds. */
export const useQueueGlance = () => useGlance<QueueStatus>("/queue", 10_000);

const QUEUED = ["/queue", "/convert", "/history", "/library", "/titles"];
/**
 * Adds files, each to get what suits it: `add.mutate({ path: "/queue", body: { files, when,
 * fit } })`, `when` being "now", "nights" (both resume a paused queue) or "after" (the queue goes
 * on as it is), and `fit` the drives without room for them all, where those that fit convert and
 * the rest wait for room.
 */
export const useAddToQueue = () => useEngineAction<{ added: number }>(QUEUED);
/**
 * Changes the queue: `/queue/pause`, `/queue/resume`, `/queue/7/skip`, `/queue/7/retry`
 * (subtitles with `{ quality: "fast" }` to make them with Fast instead), `/queue/7/move` (with
 * `{ before }`), `/queue/7/restore`, or `/queue/fit` (with `{ drive }`: there, the files that
 * fit convert and the rest wait for room).
 */
export const useQueueAction = () => useEngineAction<unknown>(QUEUED);
/**
 * Deletes everything set aside on a drive now, to make room there; History can't put it back:
 * `empty.mutate({ path: "/quarantine/empty", body: { drive } })`.
 */
export const useEmptyQuarantine = () => useEngineAction<{ files: number }>([...QUEUED, "/data"]);
/** Takes a waiting file out: `remove.mutate({ path: "/queue/7" })`. */
export const useRemoveFromQueue = () => useEngineAction<void>(QUEUED, "DELETE");
/** Converts whenever files wait, or only at night: `{ path: "/queue/schedule", body: { schedule } }`. */
export const useQueueSchedule = () => useEngineAction<QueueStatus>(QUEUED, "PUT");
/** Tonight's run stops at 03:00, or goes on till 07:00: `{ path: "/queue/tonight", body: { early } }`. */
export const useQueueTonight = () => useEngineAction<QueueStatus>(QUEUED, "PUT");

/** A sound track of a video opened to play. */
export interface SoundTrack {
  /** Among the file's sound tracks. */
  number: number;
  /** "jpn", or null when the file doesn't say. */
  language: string | null;
  title: string | null;
  channels: number;
  /** The file's own pick. */
  default: boolean;
}

/** A subtitle track of a video opened to play: in the file, or a file of its own beside it. */
export interface SubtitleTrack {
  number: number;
  language: string | null;
  title: string | null;
  /** Styled: as the file styles them. */
  kind: "text" | "styled" | "pictures";
  default: boolean;
  forced: boolean;
  beside: boolean;
  /** English subtitles Maku made from the sound: names and jokes can be off. */
  made: boolean;
}

export interface ChapterMark {
  /** Seconds in. */
  start: number;
  title: string | null;
}

/** A video opened to play: its ticket for the stream, and what it offers. */
export interface OpenedVideo {
  /** Null when the file isn't there to play: `missing` says why. */
  ticket: string | null;
  missing: "drive" | "file" | null;
  /** "F:". */
  drive: string;
  duration: number | null;
  sound: SoundTrack[];
  subtitles: SubtitleTrack[];
  chapters: ChapterMark[];
  /** What the file starts with. */
  chosenSound: number | null;
  chosenSubtitles: number | null;
  /** Subtitles ready to draw in now. */
  ready: number[];
}

/** Why the latest stream of a video ended early. */
export interface StreamStopped {
  why: "drive" | "gone" | "damaged" | "failed";
  /** What ffmpeg said last. */
  detail: string | null;
}

/** How an open video's subtitles are getting on, and why its stream stopped if it did. */
export interface PlayerState {
  ready: number[];
  /** Being copied out of the file, which reads all of it. */
  preparing: number[];
  failed: { number: number; problem: string }[];
  stopped: StreamStopped | null;
}

/** Opens a video to play: `POST /player`. */
export function openVideo(engine: ReadyEngine, file: number): Promise<OpenedVideo> {
  return callEngine<OpenedVideo>(engine, "/player", {
    method: "POST",
    body: JSON.stringify({ file }),
    headers: { "Content-Type": "application/json" },
  });
}

/** Has subtitles got ready to draw in (copied out of the file first, for text in it). */
export function prepareSubtitles(
  engine: ReadyEngine,
  ticket: string,
  subtitles: number,
): Promise<PlayerState> {
  return callEngine<PlayerState>(engine, `/player/${ticket}/subtitles/${subtitles}`, {
    method: "POST",
  });
}

/** Closes a video: its stream stops. */
export function closeVideo(engine: ReadyEngine, ticket: string): Promise<void> {
  return callEngine<void>(engine, `/player/${ticket}`, { method: "DELETE" });
}

/** How the open video's subtitles are getting on: asked every second while some get ready, or
 * while the `wanted` ones (asked for as the video opened) aren't ready nor failed yet. */
export const usePlayerState = (ticket: string | null, wanted: number | null) =>
  useEngineQuery<PlayerState>(
    `/player/${ticket}`,
    (now) =>
      now?.preparing.length ||
      (wanted !== null &&
        !now?.ready.includes(wanted) &&
        !now?.failed.some((each) => each.number === wanted))
        ? 1000
        : false,
    ticket !== null,
  );

/** The address the window's <video> plays: the ticket is its key, as it can't send the token. */
export function streamAddress(
  engine: ReadyEngine,
  ticket: string,
  choice: { at: number; sound: number | null; subtitles: number | null },
): string {
  const address = new URL(`/stream/${ticket}`, engine.url);
  address.searchParams.set("at", choice.at.toFixed(3));
  if (choice.sound !== null) address.searchParams.set("sound", String(choice.sound));
  if (choice.subtitles !== null) address.searchParams.set("subtitles", String(choice.subtitles));
  return address.toString();
}

/** Whisper medium ("best") or small ("fast"). */
export type Quality = "best" | "fast";

/** The speech model each quality needs, as Maku's tools name it (engine/src/maku/speech.py). */
export const SPEECH_MODELS: Record<Quality, string> = {
  best: "speech-best",
  fast: "speech-fast",
};

/** A video Maku could make English subtitles for. */
export interface Hearable {
  fileId: number;
  /** "Starfall Academy · S01E05". */
  label: string;
  titleId: number;
  title: string;
  season: number | null;
  episode: number | null;
  /** How long it plays. */
  seconds: number;
  /** Each sound track's language ("jpn"; "" when one doesn't say). */
  sound: string[];
  /** Its subtitles' languages, in it and beside it. */
  subtitles: string[];
  /** It can be heard or read in English already. */
  english: boolean;
  /** English subtitles Maku made are beside it. */
  made: boolean;
  /** In the queue for them, or being made. */
  waiting: boolean;
}

export interface SubtitleOptions {
  files: Hearable[];
  /** Seconds of the graphics card's time each second of a video takes, at each quality. */
  rates: Record<Quality, number>;
}

export const useSubtitleOptions = () => useEngineQuery<SubtitleOptions>("/subtitles");

const SUBTITLED = ["/subtitles", "/queue", "/titles", "/history", "/library"];
/**
 * Puts videos in the queue for English subtitles as one batch: `make.mutate({ path:
 * "/subtitles", body: { fileIds, quality, language, title, when } })`.
 */
export const useMakeSubtitles = () => useEngineAction<{ added: number }>(SUBTITLED);
/**
 * Sets a batch's subtitles aside, to quarantine, as a tidy-up History can undo:
 * `take.mutate({ path: `/subtitles/batches/${id}/take-away` })`.
 */
export const useTakeAway = () => useEngineAction<{ planId: number | null }>(SUBTITLED);
