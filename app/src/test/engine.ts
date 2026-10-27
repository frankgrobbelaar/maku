import { vi } from "vitest";
import type {
  Card,
  EngineStatus,
  FranchiseSummary,
  Library,
  Scan,
  Settings,
  System,
  TitleKind,
  TitleSummary,
  TmdbStatus,
} from "@/lib/engine";

/** The engine as tests see it: ready, on a made-up address. */
export const READY: EngineStatus = {
  state: "ready",
  url: "http://127.0.0.1:5000",
  token: "secret",
};

export const SETTINGS: Settings = {
  standard: "4k",
  naming: "plex",
  setUp: true,
  reports: true,
  quarantineDays: 30,
  originals: "quarantine",
  artwork: false,
  historyDays: null,
  healthCheck: true,
};

export const NO_LIBRARY: Library = {
  folders: 0,
  files: 0,
  size: 0,
  unread: 0,
  problems: 0,
  sd: 0,
  hd720: 0,
  hd1080: 0,
  larger: 0,
};

export const NO_SCAN: Scan = {
  state: "idle",
  stage: null,
  startedAt: null,
  finishedAt: null,
  found: 0,
  toRead: 0,
  read: 0,
  problems: 0,
  current: null,
  secondsLeft: null,
  unavailable: [],
  problem: null,
  titles: 0,
  waiting: 0,
  note: null,
  mixed: 0,
  added: null,
  gone: null,
};

/** The owner's TMDB key, connected: Maku can find series and films. */
export const TMDB_KEY: TmdbStatus = { connected: true, keyEnd: "a1b2" };

/** No TMDB key yet: Maku reads videos but finds no series or film. */
export const NO_TMDB_KEY: TmdbStatus = { connected: false, keyEnd: null };

const GIB = 1024 ** 3;

/** The owner's graphics card. */
export const GTX: Card = {
  name: "NVIDIA GeForce GTX 1660 SUPER",
  maker: "nvidia",
  memory: 6 * GIB,
  integrated: false,
  driver: "617.42",
};

/** The owner's PC, tested on 15 October and measured since by the queue: everything ready. */
export const SYSTEM: System = {
  graphicsCard: GTX.name,
  card: GTX,
  cards: [GTX],
  processor: "Intel Core i5-9600K",
  cores: 6,
  memory: 24 * GIB,
  checkedAt: "2026-10-15T20:00:00+02:00",
  encoder: "nvenc",
  driverLink: null,
  encoderProblem: null,
  abilities: [
    {
      part: "convert",
      state: "ready",
      how: "HEVC 10-bit on NVIDIA's encoder (NVENC)",
      note: null,
      seconds: [480, 1920], // an hour of 1080p, and of 4K
    },
    {
      part: "subtitles",
      state: "ready",
      how: "Best and Fast on the graphics card",
      note: null,
      seconds: [1440, 540], // an hour of sound
    },
    { part: "player", state: "ready", how: "Windows' own video encoder", note: null, seconds: [] },
  ],
  subtitles: { best: "card", fast: "card", bestWants: null },
  measured: { at: "2026-10-15T20:00:00+02:00", tested: true, conversions: 12, subtitles: 37 },
  testing: null,
};

/** The same PC before Maku has checked it. */
export const UNCHECKED: System = {
  ...SYSTEM,
  checkedAt: null,
  encoder: null,
  abilities: [],
  measured: null,
};

type Answer = unknown | ((init: RequestInit | undefined, url: URL) => unknown);

/**
 * Stands in for the engine's HTTP API: `answers` maps "GET /scan" (or just "/scan" for GET) to the
 * JSON to send back, or to a function of the request (its init and address, query and all).
 * Anything else gets a 404.
 */
export function fakeEngine(answers: Record<string, Answer>) {
  const fetch = vi.fn<typeof globalThis.fetch>(async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input));
    const method = init?.method ?? "GET";
    // An answer of null is a 204, so it's looked for by its key: `??` would pass it over.
    const asked = `${method} ${url.pathname}`;
    const key = asked in answers ? asked : method === "GET" ? url.pathname : null;
    const answer = key !== null && key in answers ? answers[key] : undefined;
    if (answer === undefined) return Response.json({ detail: "Not found" }, { status: 404 });
    const body =
      typeof answer === "function"
        ? (answer as (init: RequestInit | undefined, url: URL) => unknown)(init, url)
        : answer;
    if (body instanceof Response) return body;
    return body === null ? new Response(null, { status: 204 }) : Response.json(body);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

/** A franchise (a collection, on screen) as the engine sends it, made of these titles; its first
 * series (or else its first title) leads it, and `name` is its collection's ("The Starfall
 * Collection") when given. */
export function franchiseOf(titles: TitleSummary[], name?: string): FranchiseSummary {
  const lead = titles.find((title) => title.kind === "series") ?? titles[0];
  if (!lead) throw new Error("A franchise has a title at least.");
  type Counted = "files" | "aired" | "present" | "missing" | "specialsMissing" | "upcoming";
  const sum = (key: Counted) => titles.reduce((total, title) => total + title[key], 0);
  const count = (kind: TitleKind) => titles.filter((title) => title.kind === kind).length;
  const dates = titles.map((title) => title.released).filter((date) => date !== null);
  return {
    id: lead.id,
    name: name ?? lead.name,
    released: dates.sort()[0] ?? null,
    kinds: {
      series: count("series"),
      movie: count("movie"),
    },
    hasPoster: lead.hasPoster,
    airing: titles.some((title) => title.airing),
    files: sum("files"),
    added: lead.added,
    aired: sum("aired"),
    present: sum("present"),
    missing: sum("missing"),
    specialsMissing: sum("specialsMissing"),
    upcoming: sum("upcoming"),
    titles,
  };
}
