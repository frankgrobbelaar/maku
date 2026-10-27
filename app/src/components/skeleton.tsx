import type { ReactNode } from "react";
import { useEngine } from "@/lib/engine";
import { cn } from "@/lib/utils";

/**
 * A shape standing in for what's loading, the size and place of what comes: a page shows its
 * layout at once and fills in. Drawn in the progress tracks' grey, breathing as converting does,
 * and still when Windows' animation effects are off.
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <span aria-hidden="true" className={cn("block animate-pulse rounded-6 bg-track", className)} />
  );
}

/** A page's skeletons while its `queries` load, said to screen readers as the page loading.
 * Gone once the engine is down or a query failed: EngineProblem says what happened instead. */
export function Loading(props: {
  label: string;
  queries: { isError: boolean }[];
  children: ReactNode;
}) {
  const engine = useEngine();
  if (engine.state === "failed" || props.queries.some((query) => query.isError)) return null;
  const { label, children } = props;
  return (
    <div role="status" aria-label={label} className="flex flex-col gap-8">
      {children}
    </div>
  );
}

/** A title's or collection's header: its poster, what it is, its name and facts, and how much of
 * it is there. */
export function HeaderSkeleton() {
  return (
    <div className="flex flex-wrap items-center gap-6 rounded-24 border border-edge bg-glass p-6 shadow-panel">
      <Skeleton className="aspect-[2/3] w-30 shrink-0 rounded-14" />
      <div className="flex min-w-0 flex-[1_1_320px] flex-col gap-3">
        <Skeleton className="h-6.5 w-24 rounded-full" />
        <Skeleton className="h-8 w-72 max-w-full" />
        <Skeleton className="h-3.5 w-56 max-w-full" />
        <div className="flex gap-2.5 pt-1.5">
          <Skeleton className="h-9 w-28 rounded-full" />
          <Skeleton className="h-9 w-32 rounded-full" />
        </div>
      </div>
      <div className="flex flex-col items-center gap-2">
        <Skeleton className="h-9 w-20" />
        <Skeleton className="h-3 w-24" />
      </div>
    </div>
  );
}

/** A list's heading, a line under it, and its sort beside them. */
export function ListHeadSkeleton({ sort = true }: { sort?: boolean }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-3 w-40" />
      </div>
      {sort && <Skeleton className="h-11 w-96 max-w-full rounded-22" />}
    </div>
  );
}

/** Poster cards, as the shelf and a collection's films lay them out. */
export function CardsSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-x-4.5 gap-y-5">
      {places(count).map((place) => (
        <div key={place} className="flex flex-col gap-2.5">
          <Skeleton className="aspect-[2/3] w-full rounded-14" />
          <Skeleton className="h-3.5 w-4/5" />
          <Skeleton className="h-3 w-3/5" />
        </div>
      ))}
    </div>
  );
}

/** A glass panel with a heading and rows, as seasons, the queue and History's days sit in. */
export function PanelSkeleton({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col gap-3.5 rounded-22 border border-edge bg-glass p-5 shadow-panel",
        className,
      )}
    >
      <Skeleton className="h-4 w-36" />
      <div className="flex flex-col">
        {places(rows).map((place) => (
          <div
            key={place}
            className="flex min-h-11 items-center gap-3 border-rule border-b last:border-b-0"
          >
            <Skeleton className="h-3 w-16 shrink-0" />
            <Skeleton className="h-3 flex-1" />
            <Skeleton className="h-3 w-12 shrink-0" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Tiles with a word, a number and a line, as Home's pictures and Tidy up's kinds of change. */
export function TilesSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2.5">
      {places(count).map((place) => (
        <div
          key={place}
          className="flex flex-col gap-2.5 rounded-16 border border-edge bg-glass px-4 py-3.5 shadow-panel"
        >
          <Skeleton className="h-3.5 w-12" />
          <Skeleton className="h-6 w-16" />
          <Skeleton className="h-3 w-28" />
        </div>
      ))}
    </div>
  );
}

/** Names for so many shapes, to tell them apart in a list. */
function places(count: number): string[] {
  return Array.from({ length: count }, (_, at) => `place ${at + 1}`);
}
