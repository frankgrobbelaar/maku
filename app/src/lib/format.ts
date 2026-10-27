/** How Maku writes sizes, times, codecs, languages and lists, on every screen. */

/** A path's file name and its folder. */
export function split(path: string): [string, string] {
  const at = Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"));
  return [path.slice(at + 1), path.slice(0, at)];
}

/** 24:10, or 1:32:05 past an hour. */
export function clockTime(seconds: number): string {
  const whole = Math.round(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = String(whole % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}

/** "1 h 32 min", or "24 min". */
export function clockLength(minutes: number): string {
  const whole = Math.round(minutes);
  return whole >= 60 ? `${Math.floor(whole / 60)} h ${whole % 60} min` : `${whole} min`;
}

/** When a backup was made, as the owner reads it: "today 03:00", "yesterday 03:00", "11 October 03:00". */
export function madeAt(made: string): string {
  const moment = new Date(made);
  if (Number.isNaN(moment.getTime())) return "a backup Maku no longer has";
  return dayAndTime(moment);
}

/** A moment as the owner reads it: "today 03:00", "yesterday 03:00", "11 October 03:00". */
export function dayAndTime(moment: Date): string {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const time = moment.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (moment.toDateString() === today.toDateString()) return `today ${time}`;
  if (moment.toDateString() === yesterday.toDateString()) return `yesterday ${time}`;
  return `${moment.toLocaleDateString("en-GB", { day: "numeric", month: "long" })} ${time}`;
}

/** What a scan changed: "2 new, 1 gone", or "nothing new or gone". */
export function scanChanges(added: number, gone: number): string {
  const parts = [
    added > 0 && `${added.toLocaleString("en-GB")} new`,
    gone > 0 && `${gone.toLocaleString("en-GB")} gone`,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(", ") : "nothing new or gone";
}

/** How long what's set aside is kept, as Settings says: "for 30 days", or "for good". */
export function keptFor(days: number | null | undefined): string {
  return days === null ? "for good" : `for ${days ?? 30} days`;
}

/** "233 MB", "1.1 GB" from a billion bytes, "16 GB" from ten billion, "320 KB" under a million. */
export function size(bytes: number): string {
  if (bytes >= 1e12) return `${(bytes / 1e12).toFixed(1)} TB`;
  if (bytes >= 1e10) return `${Math.round(bytes / 1e9)} GB`;
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  return `${bytes > 0 ? Math.max(1, Math.round(bytes / 1e3)) : 0} KB`;
}

const CODECS: Record<string, string> = {
  h264: "H.264",
  hevc: "HEVC",
  av1: "AV1",
  mpeg2video: "MPEG-2",
  mpeg4: "MPEG-4",
  vp9: "VP9",
};

export function codecName(codec: string): string {
  return CODECS[codec] ?? codec.toUpperCase();
}

const LANGUAGES: Record<string, string> = {
  jpn: "Japanese",
  eng: "English",
  ger: "German",
  deu: "German",
  fre: "French",
  fra: "French",
  spa: "Spanish",
  ita: "Italian",
  por: "Portuguese",
  rus: "Russian",
  chi: "Chinese",
  zho: "Chinese",
  kor: "Korean",
  ara: "Arabic",
  // As subtitle files beside a video name them: "Episode 1.en.srt".
  en: "English",
  ja: "Japanese",
  jp: "Japanese",
  de: "German",
  fr: "French",
  es: "Spanish",
  it: "Italian",
  pt: "Portuguese",
  ru: "Russian",
  zh: "Chinese",
  ko: "Korean",
  ar: "Arabic",
};

/** Every other language's name, from the list the web view carries (Unicode's CLDR): "Dutch"
 * for "nl" or "nld". */
const NAMES = (() => {
  try {
    return new Intl.DisplayNames(["en"], { type: "language", fallback: "none" });
  } catch {
    return null;
  }
})();

export function languages(codes: string[]): string {
  if (codes.length === 0) return "none";
  return codes.map(languageName).join(", ");
}

/** A language as people say it: "Japanese" for "jpn", "English" for "en" or a file's "english",
 * "not labelled" for a track whose file doesn't say. */
export function languageName(code: string): string {
  const known = LANGUAGES[code];
  if (known) return known;
  if (code === "") return "not labelled";
  try {
    const name = NAMES?.of(code);
    if (name) return name;
  } catch {
    // not a code at all: a word a file's name carries, as "english"
  }
  return code.length > 3 ? code.charAt(0).toUpperCase() + code.slice(1) : code.toUpperCase();
}

/** English, however a file names it: "eng", "en", "English", "en-US". */
export function isEnglish(code: string): boolean {
  const lower = code.toLowerCase();
  return ["eng", "en", "english"].includes(lower) || /^en[-_]/.test(lower);
}

export function listed(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}

/** A path inside a library folder, written from that folder: "TV\Northwind (2019)\Season 01". */
export function within(path: string, root: string): string {
  const folder = root.replace(/[\\/]+$/, "");
  const inside = path.slice(0, folder.length).toLowerCase() === folder.toLowerCase();
  return inside ? path.slice(folder.length).replace(/^[\\/]+/, "") : path;
}
