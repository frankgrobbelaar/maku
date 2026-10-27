import { Link, useLocation } from "react-router";
import { progress } from "@/lib/convert";
import {
  type QueueStatus,
  type Scan,
  type TidyProposal,
  useQueueGlance,
  useScanGlance,
  useTidyGlance,
} from "@/lib/engine";
import { cn } from "@/lib/utils";
import { sectionOf, sections } from "./sections";

/** What a place has going on, over its tile, as the boards show it: solid amber for what waits
 * for the owner ("Tidy up 56"), tinted for what's under way ("Convert 63%"). */
export interface Badge {
  text: string;
  /** What it means, read out after the tile's name. */
  says: string;
  waits: boolean;
}

/** The badges by place (a section's path). */
export type Badges = Partial<Record<string, Badge>>;

/**
 * The main navigation. A column of tiles beside the page; in a compact window (under 900 px) the
 * tiles flow into a row on top. It never scrolls with the page. The section a page sits in stays
 * lit while it's open (a title's page lights Home), and a tile's badge says what's going on there.
 */
export function NavRail({ badges = {} }: { badges?: Badges }) {
  const location = useLocation();
  const lit = sectionOf(location.pathname, location.search);
  return (
    <nav
      aria-label="Main"
      className="flex shrink-0 flex-col px-2.5 pt-2 pb-3 standard:w-24 standard:pb-5"
    >
      <div className="flex flex-wrap gap-1.5">
        {sections.map(({ path, label, icon: Icon }) => {
          const badge = badges[path];
          return (
            <Link
              key={path}
              to={path}
              aria-current={path === lit ? "page" : undefined}
              className={cn(
                "press relative flex min-h-16 flex-[1_1_72px] flex-col items-center justify-center gap-1 rounded-16 px-1 py-1.5 font-bold text-11",
                path === lit ? "bg-accent/12 text-accent-fg" : "text-fg-muted",
              )}
            >
              <Icon size={22} strokeWidth={1.8} aria-hidden="true" />
              {label}
              {badge && (
                <span
                  className={cn(
                    "absolute top-1.5 inline-flex h-4.5 min-w-4.5 items-center justify-center rounded-full px-1.25 font-extrabold text-10",
                    badge.waits
                      ? "right-2.5 bg-accent text-on-accent"
                      : "right-1.5 bg-accent/18 text-accent-fg",
                  )}
                >
                  <span aria-hidden="true">{badge.text}</span>
                  <span className="sr-only">, {badge.says}</span>
                </span>
              )}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

/** The nav rail with its badges, from what the engine says of the queue, the scan and tidying. */
export function BusyNavRail() {
  const queue = useQueueGlance().data;
  const scan = useScanGlance().data;
  const tidy = useTidyGlance().data;
  return <NavRail badges={badgesOf({ queue, scan, tidy })} />;
}

/**
 * The tiles' badges: Convert says how far the file converting now has got, or how many files wait
 * to convert; Tidy up, how many changes and files to match wait for the owner. Home, History and
 * Settings have nothing that runs long enough to need one (a scan shows on Home itself).
 */
export function badgesOf(seen: { queue?: QueueStatus; scan?: Scan; tidy?: TidyProposal }): Badges {
  const badges: Badges = {};
  const { queue, scan, tidy } = seen;
  const waiting = (tidy?.changes.length ?? 0) + (scan?.waiting ?? 0);
  if (waiting > 0) {
    badges["/tidy"] = {
      text: badgeCount(waiting),
      says: `${waiting} waiting for you`,
      waits: true,
    };
  }
  if (queue?.running) {
    const share = progress(queue.running);
    badges["/convert"] = { text: `${share}%`, says: `converting, ${share}% done`, waits: false };
  } else if (queue && queue.queued.length > 0) {
    const files = queue.queued.length;
    badges["/convert"] = {
      text: badgeCount(files),
      says: `${files} ${files === 1 ? "file waits" : "files wait"} to convert`,
      waits: false,
    };
  }
  return badges;
}

/** A count that fits a badge: past 999, "999+". */
function badgeCount(count: number): string {
  return count > 999 ? "999+" : String(count);
}
