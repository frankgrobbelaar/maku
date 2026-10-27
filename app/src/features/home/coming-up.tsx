import { Link } from "react-router";
import { Poster } from "@/components/poster";
import { type ComingEpisode, useComing } from "@/lib/engine";

const SHOWN = 5; // titles listed before "Show all"

/** Each of the library's shows with an episode still to come that the library hasn't got: its
 * next one, the soonest first, on the day it airs. */
export function ComingUp({ all, onAll }: { all: boolean; onAll: (all: boolean) => void }) {
  const coming = useComing();
  const found = coming.data ?? [];
  if (found.length === 0) return null;
  const shown = all ? found : found.slice(0, SHOWN);
  return (
    <section
      aria-labelledby="coming-title"
      className="flex animate-fade-up flex-col gap-3 rounded-22 border border-edge bg-glass p-5 shadow-panel [animation-delay:45ms]"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="coming-title" className="font-extrabold text-15">
          Coming up
        </h2>
        <span className="text-12 text-fg-muted">From the episode lists, asked for hourly</span>
      </div>
      <ul className="flex flex-col">
        {shown.map((episode) => (
          <li key={episode.titleId} className="border-rule border-b last:border-b-0">
            <Link
              to={`/titles/${episode.titleId}`}
              className="-mx-2 flex min-h-14 items-center gap-3 rounded-12 px-2 py-1.5 hover:bg-tint/4"
            >
              <span className="w-24 shrink-0 font-bold text-13 text-accent-fg">
                {dayWords(episode.aired)}
              </span>
              <Poster
                title={{ id: episode.titleId, name: episode.title, hasPoster: episode.hasPoster }}
                size="tiny"
                className="w-8 shrink-0 rounded-6"
              />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-bold text-13">{episode.title}</span>
                <span className="truncate text-12 text-fg-muted">{episodeWords(episode)}</span>
              </span>
              {episode.later > 0 && (
                <span className="shrink-0 text-12 text-fg-faint">{episode.later} more listed</span>
              )}
            </Link>
          </li>
        ))}
      </ul>
      {found.length > SHOWN && (
        <button
          type="button"
          onClick={() => onAll(!all)}
          className="self-start font-bold text-13 text-accent-fg hover:text-accent-fg-hover"
        >
          {all ? "Show fewer" : `Show all ${found.length}`}
        </button>
      )}
    </section>
  );
}

/** "S02E05 · The Café at Dawn", or "Special 1" for one of its specials. */
function episodeWords(episode: ComingEpisode): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  const code =
    episode.season === 0
      ? `Special ${episode.number}`
      : `S${pad(episode.season)}E${pad(episode.number)}`;
  return episode.name ? `${code} · ${episode.name}` : code;
}

/** "Today", "Tomorrow", "Thu 23 Oct" within the week, else "23 Oct" (with its year when it
 * isn't this one). */
export function dayWords(iso: string, now = new Date()): string {
  const day = new Date(`${iso}T12:00:00`);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 12);
  const days = Math.round((day.getTime() - today.getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Tomorrow";
  if (days < 7) {
    return day.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  }
  return day.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: day.getFullYear() === now.getFullYear() ? undefined : "numeric",
  });
}
