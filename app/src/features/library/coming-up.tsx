import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { Poster } from "@/components/poster";
import { StatusShape } from "@/components/status";
import { Button } from "@/components/ui/button";
import type { ComingEpisode, EpisodeStateName } from "@/lib/engine";
import { cn } from "@/lib/utils";

/** How much of what's before today shows as the strip opens: the day before it whole, and the
 * edge of the one before that, so it's plain the strip goes back. */
const PEEK = 320;

/** Where a day falls: before today, today, or after it. */
type When = "aired" | "today" | "ahead";

interface Day {
  iso: string;
  when: When;
  shows: ComingEpisode[];
}

/**
 * The library's shows by the day their episodes air, along a strip that scrolls sideways: the
 * last four weeks to the left of today, and all that's listed ahead to its right, each saying
 * whether the library has it. It opens at today, the day before in sight; Earlier and Later page
 * along it, and Today comes back.
 */
export function ComingUp({ shows }: { shows: ComingEpisode[] }) {
  const strip = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const now = useToday();
  const days = byDay(shows, now);
  const placed = `${isoDay(now)}: ${days.map((day) => day.iso).join(" ")}`;

  // At today on opening, and again whenever the days shown change (the search narrows them) or
  // a new day comes.
  useLayoutEffect(() => {
    if (placed) toToday(strip.current, "auto");
  }, [placed]);

  if (days.length === 0) return null;
  return (
    <section aria-labelledby={titleId} className="mb-2 flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
          <h4 id={titleId} className="font-bold text-13 text-fg-muted">
            Coming up
          </h4>
          <span className="text-12 text-fg-faint">
            The last four weeks and all that's listed ahead, from the episode lists
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            aria-label="Earlier"
            className="w-9 px-0"
            onClick={() => page(strip.current, -1)}
          >
            <ChevronLeft size={16} aria-hidden="true" />
          </Button>
          <Button size="sm" onClick={() => toToday(strip.current, motion())}>
            Today
          </Button>
          <Button
            size="sm"
            aria-label="Later"
            className="w-9 px-0"
            onClick={() => page(strip.current, 1)}
          >
            <ChevronRight size={16} aria-hidden="true" />
          </Button>
        </div>
      </div>
      <div
        ref={strip}
        className="relative flex gap-6 overflow-x-auto px-0.5 pt-1.5 pb-3.5 [mask-image:linear-gradient(to_right,transparent,black_2.25rem,black_calc(100%_-_2.25rem),transparent)]"
      >
        {days.map((day) => (
          <div key={day.iso} data-when={day.when} className="flex shrink-0 flex-col gap-2">
            <span
              className={cn(
                "inline-flex h-5.5 items-center self-start rounded-full font-bold text-12",
                day.when === "today" && "bg-accent/12 px-2.25 font-extrabold text-accent-fg",
                day.when === "aired" && "text-fg-faint",
                day.when === "ahead" && "text-fg-muted",
              )}
            >
              {dayWords(day.iso, now)}
            </span>
            <ul className="flex gap-2.5">
              {day.shows.map((show) => (
                <li key={`${show.titleId}-${show.season}`}>
                  <Episode show={show} when={day.when} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

/** One show's episodes on a day: what they are, and whether the library has them. A single
 * episode the library has opens on its title's page searched for it. */
function Episode({ show, when }: { show: ComingEpisode; when: When }) {
  const status = statusOf(show, when);
  const one = show.episodes === 1 && show.held === 1;
  return (
    <Link
      to={
        one
          ? `/titles/${show.titleId}?q=${code(show.season, show.number)}`
          : `/titles/${show.titleId}`
      }
      state={one ? { videos: true } : null}
      className="lift flex w-62 items-center gap-3 rounded-16 border border-edge bg-glass py-2.5 pr-3 pl-2.5 shadow-panel"
    >
      <Poster
        title={{ id: show.titleId, name: show.title, hasPoster: show.hasPoster }}
        size="tiny"
        className="w-10 shrink-0 rounded-8"
      />
      <span className="flex min-w-0 flex-1 flex-col gap-px">
        <span className="truncate font-extrabold text-13">{show.title}</span>
        <span className="truncate text-12 text-fg-soft">{episodeWords(show)}</span>
        <span className={cn("mt-0.5 inline-flex items-center gap-1.5 text-12", status.tone)}>
          <StatusShape state={status.state} className="size-2" />
          {status.words}
        </span>
      </span>
    </Link>
  );
}

/** The shows in days, in the order they come (the soonest last), each day saying where it falls. */
function byDay(shows: ComingEpisode[], now: Date): Day[] {
  const today = isoDay(now);
  const days: Day[] = [];
  for (const show of shows) {
    const last = days.at(-1);
    if (last?.iso === show.aired) {
      last.shows.push(show);
      continue;
    }
    const when = show.aired < today ? "aired" : show.aired === today ? "today" : "ahead";
    days.push({ iso: show.aired, when, shows: [show] });
  }
  return days;
}

/** What a show's episodes on a day are to the library: all in it, some, missing (aired, and none
 * in it), out today, or still to air. Shape first, as everywhere; missing reads strongest. */
function statusOf(
  show: ComingEpisode,
  when: When,
): { state: EpisodeStateName; words: string; tone: string } {
  if (show.held === show.episodes) {
    return { state: "ready", words: "In your library", tone: "text-fg-muted" };
  }
  if (show.held > 0) {
    return {
      state: "missing",
      words: `${show.held} of ${show.episodes} in your library`,
      tone: "font-bold text-fg",
    };
  }
  if (when === "aired") return { state: "missing", words: "Missing", tone: "font-bold text-fg" };
  if (when === "today") {
    return { state: "upcoming", words: "Out today", tone: "font-bold text-accent-fg" };
  }
  return { state: "upcoming", words: "Still to air", tone: "text-fg-faint" };
}

/** "S02E05 · The Café at Dawn", "Special 1", or for a season put out at once, "S02E01–E08 · 8
 * episodes". */
export function episodeWords(show: ComingEpisode): string {
  if (show.episodes > 1) {
    const which =
      show.season === 0
        ? `Specials ${show.number}–${show.last}`
        : `${code(show.season, show.number)}–E${pad(show.last)}`;
    return `${which} · ${show.episodes} episodes`;
  }
  const which = show.season === 0 ? `Special ${show.number}` : code(show.season, show.number);
  return show.name ? `${which} · ${show.name}` : which;
}

/** "Today", "Yesterday" and "Tomorrow", else the day: "Fri 16 Oct", with its year when it isn't
 * this one ("Fri 5 Mar 2027"). */
export function dayWords(iso: string, now = new Date()): string {
  const day = new Date(`${iso}T12:00:00`);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 12);
  const days = Math.round((day.getTime() - today.getTime()) / 86_400_000);
  if (days === 0) return "Today";
  if (days === -1) return "Yesterday";
  if (days === 1) return "Tomorrow";
  const words = day.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
  return day.getFullYear() === now.getFullYear() ? words : `${words} ${day.getFullYear()}`;
}

/** Now, as the window's clock has it, again each midnight: a Library left open overnight says
 * the new day's "Today". */
function useToday(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
    const timer = setTimeout(() => setNow(new Date()), midnight.getTime() - now.getTime() + 1000);
    return () => clearTimeout(timer);
  }, [now]);
  return now;
}

/** Scrolls the strip to today (or the first day after it), with the day before in sight. */
function toToday(strip: HTMLDivElement | null, behavior: ScrollBehavior) {
  if (!strip) return;
  const mark = strip.querySelector<HTMLElement>('[data-when="today"], [data-when="ahead"]');
  const left = mark ? Math.max(0, mark.offsetLeft - PEEK) : strip.scrollWidth;
  strip.scrollTo?.({ left, behavior });
}

/** Pages along the strip, back (-1) or on (1), by most of its width. */
function page(strip: HTMLDivElement | null, way: -1 | 1) {
  if (!strip) return;
  strip.scrollBy?.({ left: way * Math.round(strip.clientWidth * 0.8), behavior: motion() });
}

/** Smooth, unless Windows' animation effects are off. */
function motion(): ScrollBehavior {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

function isoDay(when: Date): string {
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`;
}

function code(season: number, number: number): string {
  return `S${pad(season)}E${pad(number)}`;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}
