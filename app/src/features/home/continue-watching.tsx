import { Play } from "lucide-react";
import { Link } from "react-router";
import { Poster } from "@/components/poster";
import { MenuItem, RowMenu } from "@/components/ui/menu";
import { type PlayItem, usePlayer } from "@/features/player/player-context";
import { type Continuing, type NextVideo, useContinue, useStopContinuing } from "@/lib/engine";
import { split } from "@/lib/format";

const SHOWN = 6; // titles to go on with, at most

/** The titles to go on with, the latest played first: the video stopped part way, picked up
 * where it stopped, or the one after the last seen. Play plays the rest of the title after it. */
export function ContinueWatching() {
  const going = useContinue();
  const stop = useStopContinuing();
  const items = (going.data ?? []).slice(0, SHOWN);
  if (items.length === 0) return null;
  return (
    <section
      aria-labelledby="continue-title"
      className="flex animate-fade-up flex-col gap-3 [animation-delay:30ms]"
    >
      <h2 id="continue-title" className="type-heading">
        Continue watching
      </h2>
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(19rem,1fr))] gap-3">
        {items.map((item) => (
          <Card
            key={item.titleId}
            item={item}
            onStop={() => stop.mutate({ path: `/continue/${item.titleId}` })}
          />
        ))}
      </ul>
      {stop.isError && (
        <p role="alert" className="text-13 text-broken-fg">
          {stop.error.message}
        </p>
      )}
    </section>
  );
}

function Card({ item, onStop }: { item: Continuing; onStop: () => void }) {
  const { play } = usePlayer();
  const { video } = item;
  const label = labelOf(item, video);
  const done = video.resume !== null && video.duration ? video.resume / video.duration : 0;
  return (
    <li className="flex min-w-0 items-center gap-3.5 rounded-20 border border-edge bg-glass p-3 shadow-panel">
      <Link
        to={`/titles/${item.titleId}`}
        tabIndex={-1}
        aria-hidden="true"
        className="w-14 shrink-0"
      >
        <Poster
          title={{ id: item.titleId, name: item.title, hasPoster: item.hasPoster }}
          size="small"
          className="rounded-10"
        />
      </Link>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <Link
          to={`/titles/${item.titleId}`}
          className="truncate font-extrabold text-14 underline-offset-3 hover:underline"
        >
          {item.title}
        </Link>
        <span className="truncate text-13 text-fg-soft">{episodeWords(item, video)}</span>
        <span className="text-12 text-fg-muted">{stateWords(item, video)}</span>
        {done > 0 && (
          <span aria-hidden="true" className="mt-1.5 h-1 overflow-hidden rounded-full bg-tint/10">
            <span className="block h-full bg-accent" style={{ width: `${done * 100}%` }} />
          </span>
        )}
      </span>
      <button
        type="button"
        aria-label={`Play ${label}`}
        onClick={() => play([video, ...item.following].map((each) => playItem(item, each)))}
        className="press inline-flex size-10 shrink-0 cursor-pointer items-center justify-center rounded-full bg-accent text-on-accent"
      >
        <Play size={15} fill="currentColor" aria-hidden="true" />
      </button>
      <RowMenu label={`More for ${label}`}>
        <MenuItem onSelect={onStop}>Remove from Continue watching</MenuItem>
      </RowMenu>
    </li>
  );
}

/** "S01E05 · Lanterns Over the Lake", or the file's name for a video without an episode. */
function episodeWords(item: Continuing, video: NextVideo): string {
  const code = codeOf(video);
  if (!code) return item.kind === "movie" ? "The film" : split(video.path)[0];
  return video.name ? `${code} · ${video.name}` : code;
}

/** "12 min left", or "Up next" for the one after the last seen. */
function stateWords(item: Continuing, video: NextVideo): string {
  if (video.resume !== null && video.duration) {
    const left = Math.max(1, Math.round((video.duration - video.resume) / 60));
    return `${left} min left`;
  }
  return item.upNext ? "Up next" : "From the start";
}

function labelOf(item: Continuing, video: NextVideo): string {
  const code = codeOf(video);
  return code ? `${item.title} · ${code}` : item.title;
}

function playItem(item: Continuing, video: NextVideo): PlayItem {
  const code = codeOf(video);
  return {
    fileId: video.fileId,
    label: labelOf(item, video),
    name: code ? video.name : item.kind === "movie" ? null : split(video.path)[0],
    path: video.path,
    resume: video.resume,
  };
}

function codeOf(video: NextVideo): string | null {
  if (video.season === null || video.episode === null) return null;
  const pad = (value: number) => String(value).padStart(2, "0");
  const last = video.episodeEnd ? `-E${pad(video.episodeEnd)}` : "";
  return `S${pad(video.season)}E${pad(video.episode)}${last}`;
}
