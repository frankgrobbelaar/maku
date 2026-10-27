import { Link } from "react-router";
import { type LibraryGlance, useLibraryGlance } from "@/lib/engine";
import { size } from "@/lib/format";
import { share } from "@/lib/share";

/** The library in a few numbers, beside its pictures: how long it all plays, how much of that was
 * watched, what converting did to its size, and the titles taking the most room. */
export function Glance() {
  const glance = useLibraryGlance();
  const found = glance.data;
  if (!found || found.seconds === 0) return null;
  const watched = share(found.watched, found.seconds);
  return (
    <section
      aria-labelledby="glance-title"
      className="flex animate-fade-up flex-col gap-2.5 [animation-delay:75ms]"
    >
      <h2 id="glance-title" className="font-bold text-13 text-fg-muted">
        At a glance
      </h2>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2.5">
        <Tile
          label="To watch"
          value={hours(found.seconds)}
          note="of series and films, end to end"
        />
        <Tile
          label="Watched"
          value={hours(found.watched)}
          note={found.watched > 0 ? `${watched}% of it` : "none seen to the end yet"}
        />
        <Converting glance={found} />
        <Biggest glance={found} />
      </div>
    </section>
  );
}

function Tile(props: { label: string; value: string; note: string }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-16 border border-edge bg-glass px-4 py-3.5 shadow-panel">
      <span className="font-bold text-13">{props.label}</span>
      <span className="font-extrabold text-24 leading-[1.1]">{props.value}</span>
      <span className="text-12 text-fg-muted">{props.note}</span>
    </div>
  );
}

/** What converting did to the space the converted files take: saved, or used where a result
 * came out bigger than its original. */
function Converting({ glance }: { glance: LibraryGlance }) {
  const { files, before, after } = glance.converted;
  if (files === 0) {
    return <Tile label="Converting" value="None yet" note="what's converted shows here" />;
  }
  const saved = before - after;
  return (
    <Tile
      label={saved >= 0 ? "Converting saved" : "Converting used"}
      value={size(Math.abs(saved))}
      note={`${files.toLocaleString("en-GB")} ${files === 1 ? "file" : "files"}: ${size(before)} → ${size(after)}`}
    />
  );
}

/** The titles taking the most room: the biggest three, by name and size. */
function Biggest({ glance }: { glance: LibraryGlance }) {
  if (glance.biggest.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5 rounded-16 border border-edge bg-glass px-4 py-3.5 shadow-panel">
      <span className="flex items-baseline justify-between gap-2">
        <span className="font-bold text-13">The most room</span>
        <span className="font-mono text-12 text-fg-muted">{size(glance.size)} in all</span>
      </span>
      <ul className="flex flex-col gap-1">
        {glance.biggest.slice(0, 3).map((title) => (
          <li key={title.titleId} className="flex items-baseline gap-2 text-13">
            <Link
              to={`/titles/${title.titleId}`}
              className="min-w-0 flex-1 truncate underline-offset-3 hover:underline"
            >
              {title.name}
            </Link>
            <span className="shrink-0 font-mono text-12 text-fg-muted">{size(title.size)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** "1,240 hours", "18 hours", "45 min". */
function hours(seconds: number): string {
  const whole = Math.round(seconds / 3600);
  if (whole >= 1) return `${whole.toLocaleString("en-GB")} ${whole === 1 ? "hour" : "hours"}`;
  return `${Math.round(seconds / 60)} min`;
}
