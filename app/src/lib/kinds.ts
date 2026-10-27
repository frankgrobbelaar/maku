import type { TitleKind } from "@/lib/engine";

/** The words for each kind of title, as every screen says them: TV series and movies. */
const WORDS: Record<TitleKind, { full: string; short: string; one: string; many: string }> = {
  series: { full: "TV series", short: "TV", one: "series", many: "series" },
  movie: { full: "Movie", short: "Movie", one: "movie", many: "movies" },
};

/** The order lists group titles in: series, then movies. */
export const KIND_ORDER: readonly TitleKind[] = ["series", "movie"];

/** A group's heading: "Series" or "Movies". */
export function kindHeading(kind: TitleKind): string {
  const many = WORDS[kind].many;
  return many.charAt(0).toUpperCase() + many.slice(1);
}

/** "TV series" or "Movie"; `short` gives "TV" for a series, where room is tight. */
export function kindWord(kind: TitleKind, short = false): string {
  return short ? WORDS[kind].short : WORDS[kind].full;
}

/** "3 movies", "1 series". */
export function kindCount(kind: TitleKind, count: number): string {
  return `${count.toLocaleString("en-GB")} ${count === 1 ? WORDS[kind].one : WORDS[kind].many}`;
}

/** "1 file", "287 files". */
export function files(count: number): string {
  return `${count.toLocaleString("en-GB")} ${count === 1 ? "file" : "files"}`;
}
