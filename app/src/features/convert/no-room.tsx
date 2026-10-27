import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { size } from "@/lib/format";
import { cn } from "@/lib/utils";

/** A file waiting to convert, as far as saying what waits goes. */
export interface Waiting {
  title: string | null;
  titleId: number | null;
  season: number | null;
}

/**
 * Not enough space (board 5.3): a drive without room for what waits to convert on it, and the
 * ways on. Emptying its quarantine first deletes what's set aside there for good, so Maku asks
 * once more before it does; converting what fits leaves the rest to wait for room, and they go
 * by themselves once there is.
 */
export function NoRoom(props: {
  drive: string;
  /** The files on the drive still to convert. */
  waiting: Waiting[];
  needed: number;
  free: number;
  fit: number;
  setAside: number;
  /** They wait for room already, while the others go: making room is all that's left to do. */
  waitingForRoom?: boolean;
  busy: boolean;
  problem: Error | null;
  onEmpty: () => void;
  onFit: () => void;
  /** Away without choosing (the Convert screen, back to its choices). */
  onBack?: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const id = useId();
  const { drive, setAside } = props;

  if (confirming) {
    return (
      <fieldset
        aria-label={`Empty the quarantine on ${drive}?`}
        className="flex animate-fade-up flex-col gap-3 rounded-16 border border-danger/40 bg-danger/8 p-4"
      >
        <span className="font-extrabold text-14">Empty the quarantine on {drive}?</span>
        <span className="text-13 text-fg-soft">
          What's set aside there ({size(setAside)}) is deleted for good, and History can't put it
          back.
        </span>
        <Problem error={props.problem} />
        <div className="flex flex-wrap gap-2.5">
          <Button size="sm" variant="danger" disabled={props.busy} onClick={props.onEmpty}>
            Empty quarantine
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
            Back
          </Button>
        </div>
      </fieldset>
    );
  }
  const none = props.fit === 0;
  return (
    <div
      role="alertdialog"
      aria-label="Not enough space"
      aria-describedby={id}
      className="flex animate-fade-up flex-col gap-3 rounded-20 border border-tint/10 bg-raised p-4.5 shadow-panel"
    >
      <span id={id} className="font-extrabold">
        {props.waitingForRoom ? waitingWords(props) : neededWords(props)}
      </span>
      {setAside > 0 && (
        <Choice primary disabled={props.busy} onClick={() => setConfirming(true)}>
          Empty quarantine first
          <span className="font-mono text-12">+{size(setAside)}</span>
        </Choice>
      )}
      {!props.waitingForRoom && (
        <Choice disabled={props.busy} onClick={props.onFit}>
          {none ? "Wait for room" : `Convert the ${props.fit} that fit now`}
          <span className="font-medium text-12 text-fg-muted">
            {none ? "it goes on by itself" : "rest later"}
          </span>
        </Choice>
      )}
      {props.onBack && (
        <Button size="sm" variant="ghost" className="self-start" onClick={props.onBack}>
          Back
        </Button>
      )}
      <Problem error={props.problem} />
    </div>
  );
}

/** "Glass Orchard · Season 2 needs about 16 GB. D: has 9 GB free." */
function neededWords(props: { drive: string; waiting: Waiting[]; needed: number; free: number }) {
  const one = oneSeason(props.waiting);
  const files = props.waiting.length;
  const what =
    one ?? (files === 1 ? `The file on ${props.drive}` : `The ${files} files on ${props.drive}`);
  const needs = one !== null || files === 1 ? "needs" : "need";
  return `${what} ${needs} about ${size(props.needed)}. ${props.drive} has ${size(props.free)} free.`;
}

/** "D: has 1 MB free, and 2 files there need about 5.6 GB: they wait for room while…" */
function waitingWords(props: { drive: string; waiting: Waiting[]; needed: number; free: number }) {
  const one = props.waiting.length === 1;
  const files = one ? "1 file there needs" : `${props.waiting.length} files there need`;
  return `${props.drive} has ${size(props.free)} free, and ${files} about ${size(props.needed)}: ${
    one ? "it waits" : "they wait"
  } for room while the others go.`;
}

/** The title and season every file belongs to ("Glass Orchard · Season 1", or a film's title). */
function oneSeason(waiting: Waiting[]): string | null {
  const [first] = waiting;
  if (!first?.title) return null;
  const same = waiting.every((w) => w.titleId === first.titleId && w.season === first.season);
  if (!same) return null;
  if (first.season === null) return first.title;
  return `${first.title} · ${first.season === 0 ? "Specials" : `Season ${first.season}`}`;
}

function Choice(props: {
  primary?: boolean;
  disabled: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={props.disabled}
      onClick={props.onClick}
      className={cn(
        "press flex min-h-11 w-full cursor-pointer items-center justify-between gap-2.5 rounded-14 px-3.5 text-left disabled:pointer-events-none disabled:opacity-50",
        props.primary
          ? "bg-accent/12 font-extrabold text-accent-fg"
          : "bg-tint/5 font-bold text-fg",
      )}
    >
      {props.children}
    </button>
  );
}

function Problem({ error }: { error: Error | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="text-13 text-broken-fg">
      {error.message}
    </p>
  );
}
