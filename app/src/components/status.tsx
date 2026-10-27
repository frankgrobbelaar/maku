import type { EpisodeStateName } from "@/lib/engine";
import { cn } from "@/lib/utils";

/** Each state's shape: ready is solid amber, to convert solid blue, broken hatched, missing
 * hollow; an episode still to air is a faint hollow. Shapes read without colour too. */
const SHAPES: Record<EpisodeStateName, string> = {
  ready: "status-ready",
  "to convert": "status-convert",
  broken: "status-broken",
  missing: "status-missing",
  upcoming: "status-missing opacity-40",
};

const WORDS: Record<EpisodeStateName, string> = {
  ready: "Ready",
  "to convert": "To convert",
  broken: "Broken",
  missing: "Missing",
  upcoming: "Still to air",
};

export function StatusShape({ state, className }: { state: EpisodeStateName; className?: string }) {
  return (
    <span aria-hidden="true" className={cn("inline-block rounded-3", SHAPES[state], className)} />
  );
}

export function statusWord(state: EpisodeStateName): string {
  return WORDS[state];
}

/** The key under a map: each state that appears, with its shape. */
export function StatusLegend({ states }: { states: EpisodeStateName[] }) {
  const shown = (Object.keys(WORDS) as EpisodeStateName[]).filter((state) =>
    states.includes(state),
  );
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-12 text-fg-muted">
      {shown.map((state) => (
        <span key={state} className="inline-flex items-center gap-1.5">
          <StatusShape state={state} className="size-2.5" />
          {WORDS[state]}
        </span>
      ))}
    </div>
  );
}
