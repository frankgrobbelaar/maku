import type { ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { AddFirstFolder } from "@/components/add-folder";
import { EmptyState, ShelfIllustration } from "@/components/empty-state";
import { EngineProblem } from "@/components/engine-problem";
import { NoMatches, SearchField, useAddressSearch } from "@/components/search-field";
import { CardsSkeleton, Loading } from "@/components/skeleton";
import { SortControl } from "@/components/sort-control";
import { ShelfCard } from "@/components/title-card";
import {
  CardGrid,
  type Group,
  groupsByType,
  orderWords,
  shelfByKind,
  together,
} from "@/components/title-groups";
import { NoTmdbKey } from "@/components/tmdb-key";
import { Button } from "@/components/ui/button";
import {
  type Scan,
  type TitleSort,
  useComing,
  useEngine,
  useFolders,
  useFranchises,
  useScan,
} from "@/lib/engine";
import { files } from "@/lib/kinds";
import { matches } from "@/lib/search";
import { ComingUp } from "./coming-up";

const SORTS: readonly TitleSort[] = ["released", "name", "added", "missing"];

/**
 * The Library: every series and film as poster cards, by type (collections, then series and films
 * on their own) and oldest release first unless the owner picks another order, and what's coming
 * up of the series under their heading. A collection of several films is one card with a page of
 * its own. The search finds a collection by its name or any of its films', and narrows Coming up
 * too; it and the order keep to the page's address, so going back finds the page as it was left.
 */
export function LibraryPage() {
  const engine = useEngine();
  const folders = useFolders();
  const scan = useScan();
  const [sort, setSort] = useAddressSort();
  const [query, setQuery] = useAddressSearch();
  const franchises = useFranchises(sort);
  const coming = useComing();

  const working = engine.state !== "failed";
  const empty = folders.data?.length === 0;
  const all = franchises.data ?? [];
  const found = all.filter((franchise) =>
    matches(query, franchise.name, ...franchise.titles.map((title) => title.name)),
  );
  const shows = (coming.data ?? []).filter((show) => matches(query, show.title));
  const shelved = working && !empty && all.length > 0;

  return (
    <>
      <header className="page-top flex animate-fade-up flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h1 className="type-title">Library</h1>
          <p className="text-14 text-fg-muted">
            {empty
              ? "No folders yet."
              : franchises.data
                ? shelfWords(all.length, found.length, query, sort)
                : "…"}
          </p>
        </div>
        {shelved && (
          <div className="flex flex-wrap items-center gap-3">
            {(all.length > 1 || query) && (
              <SearchField
                value={query}
                onChange={setQuery}
                label="Search the shelf"
                placeholder="Search the shelf"
                className="w-64"
              />
            )}
            <SortControl value={sort} onChange={setSort} />
          </div>
        )}
      </header>

      <NoTmdbKey />
      <EngineProblem queries={[folders, franchises]} />
      {working && empty && (
        <EmptyState
          title="Your shelf is empty"
          illustration={<ShelfIllustration />}
          action={<AddFirstFolder />}
        >
          Add a folder with series or films in it. Any layout, even everything in one folder.
        </EmptyState>
      )}
      {working && !empty && !franchises.data && (
        <Loading label="Loading the shelf" queries={[folders, franchises]}>
          <CardsSkeleton count={12} />
        </Loading>
      )}
      {working && folders.data && !empty && franchises.data?.length === 0 && (
        <NothingYet scan={scan.data} />
      )}
      {shelved && (
        <section
          aria-labelledby="shelf-heading"
          className="flex animate-fade-up flex-col gap-4 [animation-delay:60ms]"
        >
          <h2 id="shelf-heading" className="sr-only">
            Series and films
          </h2>
          {found.length === 0 ? (
            <NoMatches>Nothing on the shelf goes by “{query.trim()}”.</NoMatches>
          ) : (
            <CardGrid
              groups={leading(
                groupsByType(sort) ? shelfByKind(found) : together(found),
                shows.length > 0 ? <ComingUp shows={shows} /> : null,
              )}
              keyOf={(franchise) => franchise.id}
              card={(franchise) => <ShelfCard franchise={franchise} />}
            />
          )}
        </section>
      )}
    </>
  );
}

/** Folders, and nothing on the shelf yet: what Maku is at, and the next step when there's one. */
function NothingYet({ scan }: { scan: Scan | undefined }) {
  const navigate = useNavigate();
  const scanning = scan?.state === "running" || scan?.state === "paused";
  const waiting = scan?.waiting ?? 0;
  return (
    <EmptyState
      title="No series or films yet"
      illustration={<ShelfIllustration />}
      action={
        scanning ? (
          <Button variant="primary" onClick={() => void navigate("/scan")}>
            See the scan
          </Button>
        ) : waiting > 0 ? (
          <Button variant="primary" onClick={() => void navigate("/match")}>
            Match {files(waiting)}
          </Button>
        ) : undefined
      }
    >
      {scanning
        ? "Maku is reading your folders. Series and films show here as it finds them."
        : waiting > 0
          ? "Maku couldn't tell which series or film your videos are. Say which, and they show here."
          : "Series and films show here once Maku knows which your videos are."}
    </EmptyState>
  );
}

/** "9 on the shelf · by type, oldest release first"; while searching, "2 of 9 on the shelf · …". */
function shelfWords(count: number, found: number, query: string, sort: TitleSort): string {
  if (count === 0) return "Nothing on the shelf yet.";
  return `${query ? `${found} of ${count}` : count} on the shelf · ${orderWords(sort)}`;
}

/** The groups with Coming up first in the series' (or the first group, were there none), or in
 * the one group of a list that isn't by type. */
function leading<T>(groups: Group<T>[], lead: ReactNode): Group<T>[] {
  if (!lead) return groups;
  const at = Math.max(
    0,
    groups.findIndex((group) => group.key === "series"),
  );
  return groups.map((group, index) => (index === at ? { ...group, lead } : group));
}

/** The shelf's order, kept in the page's address (`?sort=`) as its search is: going back finds it,
 * and Home's "Most missing first" opens the Library in that order. Release date, the default,
 * leaves the address as it is. */
function useAddressSort(): [TitleSort, (sort: TitleSort) => void] {
  const [address, setAddress] = useSearchParams();
  const asked = address.get("sort");
  const sort = SORTS.find((each) => each === asked) ?? "released";
  const setSort = (next: TitleSort) =>
    setAddress(
      (before) => {
        const after = new URLSearchParams(before);
        if (next === "released") after.delete("sort");
        else after.set("sort", next);
        return after;
      },
      { replace: true },
    );
  return [sort, setSort];
}
