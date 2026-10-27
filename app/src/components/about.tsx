import { ExternalLink } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Button } from "@/components/ui/button";
import type { TitleKind, TitleStatus } from "@/lib/engine";
import { clockLength } from "@/lib/format";
import { openTmdbPage } from "@/lib/links";
import { cn } from "@/lib/utils";

/** A synopsis, its paragraphs kept: a long one shows its start, and all of it on asking. */
export function Synopsis({ text, lines = 4 }: { text: string; lines?: 4 | 6 }) {
  const [all, setAll] = useState(false);
  const long = text.length > 320;
  return (
    <div className="flex flex-col items-start gap-1.5">
      <div
        className={cn(
          "space-y-2.5 text-14 text-fg-soft leading-relaxed",
          long && !all && (lines === 4 ? "line-clamp-4" : "line-clamp-6"),
        )}
      >
        {text.split(/\n{2,}/).map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
      </div>
      {long && (
        <button
          type="button"
          aria-expanded={all}
          onClick={() => setAll(!all)}
          className="cursor-pointer font-bold text-13 text-accent-fg hover:text-accent-fg-hover"
        >
          {all ? "Less" : "More"}
        </button>
      )}
    </div>
  );
}

/** A title's genres, as chips. */
export function Genres({ genres }: { genres: string[] }) {
  if (genres.length === 0) return null;
  return (
    <ul aria-label="Genres" className="flex flex-wrap gap-1.5">
      {genres.map((genre) => (
        <li
          key={genre}
          className="rounded-full bg-tint/6 px-2.5 py-0.5 font-bold text-12 text-fg-soft"
        >
          {genre}
        </li>
      ))}
    </ul>
  );
}

/** Facts in two columns: what each is, and what it says. */
export function Facts({ facts }: { facts: [string, ReactNode][] }) {
  const shown = facts.filter(([, value]) => value !== null && value !== undefined && value !== "");
  if (shown.length === 0) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-5 gap-y-1.5 text-13">
      {shown.map(([label, value]) => (
        <div key={label} className="col-span-2 grid grid-cols-subgrid">
          <dt className="text-fg-muted">{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Where to read more of it: its page on TMDB, in the browser. */
export function ElsewhereLinks(props: { tmdbType: "tv" | "movie" | null; tmdbId: number | null }) {
  const { tmdbType, tmdbId } = props;
  if (!tmdbType || !tmdbId) return null;
  return (
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="secondary" onClick={() => void openTmdbPage(tmdbType, tmdbId)}>
        On TMDB
        <ExternalLink size={14} aria-hidden="true" />
      </Button>
    </div>
  );
}

const STATUS: Record<TitleStatus, string> = {
  finished: "Finished",
  airing: "Still airing",
  coming: "Not out yet",
  cancelled: "Cancelled",
  paused: "On a break",
};

/** Where a title stands, in words: a film that's out is just out. */
export function statusWords(status: TitleStatus | null, kind: TitleKind): string | null {
  if (status === null) return null;
  if (kind === "movie" && status === "finished") return "Out";
  return STATUS[status];
}

/** When it aired: "Apr 1989 to Jan 1996", "since Apr 2026", "1 Sep 2001" for a film. */
export function airedWords(
  started: string | null,
  ended: string | null,
  kind: TitleKind,
  airing: boolean,
): string | null {
  if (!started) return null;
  if (kind === "movie") return day(started);
  if (airing) return `Since ${month(started)}`;
  if (!ended || month(ended) === month(started)) return month(started);
  return `${month(started)} to ${month(ended)}`;
}

/** How long it lasts: "24 min an episode", or a film's "1 h 55 min". */
export function lengthWords(minutes: number | null, kind: TitleKind): string | null {
  if (!minutes) return null;
  return kind === "movie" ? clockLength(minutes) : `${clockLength(minutes)} an episode`;
}

function month(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString("en-GB", {
    month: "short",
    year: "numeric",
  });
}

function day(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
