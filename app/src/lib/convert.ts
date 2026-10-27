/** What the Convert screens work out from the engine's lists: the tree of what can be converted,
 * what a choice adds up to, and how long things take, in words. */

import type { Convertible, FranchiseSummary, Job, RunningJob } from "@/lib/engine";
import { KIND_ORDER } from "@/lib/kinds";

/** A season of a title, or its specials, or a film's file. */
export interface SeasonNode {
  key: string;
  label: string;
  files: Convertible[];
}

export interface TitleNode {
  key: string;
  name: string;
  seasons: SeasonNode[];
  files: Convertible[];
}

/** A collection of several titles (a franchise, as the engine calls it), or one title on its
 * own. */
export interface GroupNode {
  key: string;
  name: string;
  /** Several titles: the collection's; one: that title's seasons, under the group itself. */
  titles: TitleNode[];
  files: Convertible[];
}

const OTHERS = "Not matched yet";

/**
 * The files by collection, title and season, in the library's order: collections as Home sorts
 * them (`franchises`), each one's titles by type (series, then films), then files Maku hasn't
 * matched yet.
 */
export function tree(files: Convertible[], franchises: FranchiseSummary[]): GroupNode[] {
  const franchiseOf = new Map<number, FranchiseSummary>();
  for (const franchise of franchises) {
    for (const title of franchise.titles) franchiseOf.set(title.id, franchise);
  }
  const titles = new Map<string, TitleNode>();
  for (const file of files) {
    const key = file.titleId === null ? "none" : `t${file.titleId}`;
    const node = titles.get(key) ?? {
      key,
      name: file.title ?? OTHERS,
      seasons: [],
      files: [],
    };
    node.files.push(file);
    titles.set(key, node);
  }
  for (const node of titles.values()) node.seasons = seasonsOf(node.files);

  const groups: GroupNode[] = [];
  const placed = new Set<string>();
  for (const franchise of franchises) {
    const members = [...franchise.titles]
      .sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind)) // by type first
      .map((title) => titles.get(`t${title.id}`))
      .filter((node): node is TitleNode => node !== undefined);
    if (members.length === 0) continue;
    for (const member of members) placed.add(member.key);
    groups.push({
      key: `f${franchise.id}`,
      name: members.length > 1 ? franchise.name : (members[0]?.name ?? franchise.name),
      titles: members,
      files: members.flatMap((member) => member.files),
    });
  }
  for (const node of titles.values()) {
    if (placed.has(node.key)) continue;
    groups.push({ key: node.key, name: node.name, titles: [node], files: node.files });
  }
  return groups;
}

function seasonsOf(files: Convertible[]): SeasonNode[] {
  const seasons = new Map<string, SeasonNode>();
  for (const file of files) {
    const key = file.season === null ? "film" : `s${file.season}`;
    const node = seasons.get(key) ?? { key, label: seasonLabel(file.season), files: [] };
    node.files.push(file);
    seasons.set(key, node);
  }
  return [...seasons.values()];
}

function seasonLabel(season: number | null): string {
  if (season === null) return "The film";
  return season === 0 ? "Specials" : `Season ${season}`;
}

/** Files that can join the queue: they play, and aren't in it already. */
export function open(files: Convertible[]): Convertible[] {
  return files.filter((file) => !file.broken && !file.waiting);
}

/** What converting `files` adds up to. */
export interface Totals {
  files: number;
  /** How long they play. */
  seconds: number;
  gpuSeconds: number;
  sizeBefore: number;
  sizeAfter: number;
  /** The results' size on each drive. */
  byDrive: Record<string, number>;
  /** "1080p · 16:9", or "SD · 4:3, 4K HDR · 16:9". */
  sources: string;
}

export function totals(files: Convertible[]): Totals {
  const byDrive: Record<string, number> = {};
  const sources: string[] = [];
  let seconds = 0;
  let gpuSeconds = 0;
  let sizeBefore = 0;
  let sizeAfter = 0;
  for (const file of files) {
    seconds += file.seconds;
    gpuSeconds += file.gpuSeconds;
    sizeBefore += file.size;
    sizeAfter += file.outputBytes;
    byDrive[file.drive] = (byDrive[file.drive] ?? 0) + file.outputBytes;
    const source = `${sizeName(file.width, file.height)}${file.hdr ? " HDR" : ""} · ${file.aspect}`;
    if (!sources.includes(source)) sources.push(source);
  }
  return {
    files: files.length,
    seconds,
    gpuSeconds,
    sizeBefore,
    sizeAfter,
    byDrive,
    sources: sources.length > 2 ? `${sources.slice(0, 2).join(", ")} and more` : sources.join(", "),
  };
}

/** A picture's size as the engine calls it: "SD", "720p", "1080p", "4K" or "8K", by the
 * smallest frame it fits (cinema's wider 4096 and 2048 included). */
export function sizeName(width: number, height: number): string {
  const frames: [number, number, string][] = [
    [1024, 576, "SD"],
    [1280, 720, "720p"],
    [1920, 1080, "1080p"],
    [3840, 2160, "4K"],
  ];
  const fits = frames.find(([w, h]) => width <= w * 1.07 && height <= h * 1.07);
  return fits ? fits[2] : "8K";
}

/** GPU time in words: "12 min", "1 h", "35 h", "12 days". */
/** How far the file converting now has got, in whole percents. */
export function progress(running: Pick<RunningJob, "frames" | "total">): number {
  return running.total > 0 ? Math.min(100, Math.round((running.frames / running.total) * 100)) : 0;
}

export function gpuTime(seconds: number): string {
  const minutes = seconds / 60;
  if (minutes < 59.5) return `${Math.max(1, Math.round(minutes))} min`;
  const hours = minutes / 60;
  if (hours < 47.5) return `${Math.round(hours)} h`;
  const days = Math.round(hours / 24);
  return `${days} days`;
}

/** The short form the queue's rows use: "1 h", "12 min", "10 d". */
export function gpuTimeShort(seconds: number): string {
  return gpuTime(seconds).replace(/ days$/, " d");
}

/** The drive a path is on, as Maku writes it: "D:", or a share, "\\\\nas\\videos" (empty for none). */
export function driveOf(path: string): string {
  const letter = /^[a-z]:/i.exec(path)?.[0];
  if (letter) return letter.toUpperCase();
  return /^\\\\[^\\]+\\[^\\]+/.exec(path)?.[0] ?? "";
}

/** Free space wanted on a drive, over a result's size (the engine wants the same). */
export const ROOM = 1.25;

/**
 * Of files to convert on one drive, in turn: the free space their results all want, and how
 * many fit in `free` now, each result taking its size of what's left (as the engine counts).
 * When originals are deleted as their results take their place (`deleting`), a result wants its
 * room only while it's made and keeps just what it adds over its original: the space wanted is
 * the most wanted at any one time.
 */
export function fitting(
  files: { output: number; original: number }[],
  free: number,
  deleting = false,
): { needed: number; fit: number } {
  let left = free;
  let needed = 0;
  let kept = 0;
  let fit = 0;
  for (const { output, original } of files) {
    const wanted = Math.round(output * ROOM);
    const stays = deleting ? Math.max(0, output - original) : output;
    needed = deleting ? Math.max(needed, kept + wanted) : needed + wanted;
    kept += stays;
    if (left >= wanted) {
      fit += 1;
      left -= stays;
    }
  }
  return { needed, fit };
}

/** What a converted file's original becomes, as Settings and Convert offer it. */
export const ORIGINALS = [
  { value: "quarantine", label: "Keep" },
  { value: "delete", label: "Delete" },
] as const;

/** When Maku tries again, from now: "in 5 minutes", "in a minute", "in a moment". */
export function retryIn(retryAt: string, now: number): string {
  const minutes = Math.ceil((Date.parse(retryAt) - now) / 60_000);
  if (minutes <= 0) return "in a moment";
  return minutes === 1 ? "in a minute" : `in ${minutes} minutes`;
}

/** Nights of 23:00 to 07:00 that GPU time takes: "about 5 nights", or "less than a night". */
export function nights(seconds: number): string {
  if (seconds < 8 * 3600) return "less than a night";
  const count = Math.ceil(seconds / 3600 / 8);
  return `about ${count} nights`;
}

/** "13 h 40 min of video". */
export function playTime(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} h ${minutes % 60} min` : `${minutes} min`;
}

/** The queue's waiting files, a title's season at a time: "Glass Orchard · Season 1". */
export interface JobGroup {
  key: string;
  label: string;
  jobs: Job[];
}

export function jobGroups(jobs: Job[]): JobGroup[] {
  const groups: JobGroup[] = [];
  for (const job of jobs) {
    const season =
      job.season === null ? "" : job.season === 0 ? "Specials" : `Season ${job.season}`;
    const title = job.title ?? OTHERS;
    const key = `${job.titleId ?? "none"}-${job.season ?? "film"}`;
    const last = groups.at(-1);
    if (last?.key === key) last.jobs.push(job);
    else groups.push({ key, label: season ? `${title} · ${season}` : title, jobs: [job] });
  }
  return groups;
}

/** A job's place in its season, "S01E06", or its file's name for a film or unmatched file. */
export function episodeCode(job: Pick<Job, "season" | "episode" | "path">): string {
  if (job.season === null || job.episode === null) {
    const at = Math.max(job.path.lastIndexOf("\\"), job.path.lastIndexOf("/"));
    return job.path.slice(at + 1);
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `S${pad(job.season)}E${pad(job.episode)}`;
}

/** What each method is called on the screens: a conversion's, or subtitles' quality. */
export const METHOD_NAMES = {
  best: "Best",
  fast: "Fast",
  reencode: "Re-encode",
  remux: "Remux",
} as const;

/** What a conversion does to the picture, as the queue tells it. */
export const METHOD_PICTURES = {
  reencode: "Made HEVC 10-bit",
  remux: "Picture copied into MKV",
} as const;
