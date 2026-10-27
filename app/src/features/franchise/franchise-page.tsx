import { useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { ElsewhereLinks, Facts, Genres, Synopsis, statusWords } from "@/components/about";
import { Breadcrumb, LIBRARY } from "@/components/breadcrumb";
import { EngineProblem } from "@/components/engine-problem";
import { Poster } from "@/components/poster";
import { NoMatches, SearchField, useAddressSearch } from "@/components/search-field";
import { CardsSkeleton, HeaderSkeleton, ListHeadSkeleton, Loading } from "@/components/skeleton";
import { SortControl } from "@/components/sort-control";
import { StatusShape } from "@/components/status";
import { TitleCard } from "@/components/title-card";
import { byKind, CardGrid, groupsByType, orderWords, together } from "@/components/title-groups";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogPicture,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  type FranchiseSummary,
  type MissingTitle,
  type TitleKind,
  type TitleSort,
  type TitleSummary,
  useCover,
  useCoverPicture,
  useFranchise,
  useFranchiseMissing,
  useTitleAbout,
} from "@/lib/engine";
import { kindCount, kindWord } from "@/lib/kinds";
import { matches } from "@/lib/search";
import { share } from "@/lib/share";
import { cn } from "@/lib/utils";

/** A title on a collection's page: one the library has, or one it has none of. */
type Shelved =
  | { kind: TitleKind; name: string; released: string | null; title: TitleSummary }
  | { kind: TitleKind; name: string; released: string | null; missing: MissingTitle };

/** A collection (a franchise, to the engine): the films TMDB keeps together, oldest release first
 * unless the owner picks another order, each leading to its own page. "Missing films" puts in
 * among them the collection's films that the library has none of. A film alone in the library
 * has this page too, for what its collection lacks. The address keeps whether they're in
 * (`?missing`, as a film's own "Missing films" leads here) and the search, so going back to the
 * page finds it as it was left. */
export function FranchisePage() {
  const { id } = useParams();
  const [address, setAddress] = useSearchParams();
  const [sort, setSort] = useState<TitleSort>("released");
  const [query, setQuery] = useAddressSearch();
  const whole = address.has("missing");
  const setWhole = (on: boolean) =>
    setAddress(
      (before) => {
        const after = new URLSearchParams(before);
        if (on) after.set("missing", "");
        else after.delete("missing");
        return after;
      },
      { replace: true },
    );
  const franchise = useFranchise(Number(id), sort);
  const missing = useFranchiseMissing(Number(id));
  // A film the library lacks, opened to say what TMDB knows of it.
  const [opened, setOpened] = useState<MissingTitle | null>(null);

  if (!franchise.data) {
    return (
      <>
        <Breadcrumb trail={[LIBRARY]} current="…" />
        <EngineProblem queries={[franchise]} />
        <Loading label="Loading the collection" queries={[franchise]}>
          <HeaderSkeleton />
          <div className="flex flex-col gap-4">
            <ListHeadSkeleton />
            <CardsSkeleton count={8} />
          </div>
        </Loading>
      </>
    );
  }
  const found = franchise.data;
  const rest = missing.data;
  // Offered while there's something it lacks, or Maku is still looking; on only while offered.
  const offered = rest && (rest.titles.length > 0 || rest.looking) ? rest : null;
  const on = whole && offered !== null;
  const lacking = on ? offered.titles : [];
  const all = shelved(found.titles, lacking, sort);
  const items = all.filter((item) => matches(query, item.name));
  const kinds = new Set(all.map((item) => item.kind));
  // A collection holds films; were anything else among them (an older record), they're titles.
  const films = kinds.size === 1 && kinds.has("movie");
  const one = films ? "film" : "title";
  const many = `${one}s`;
  const count = [
    query
      ? `${items.length} of ${all.length} ${many}`
      : on
        ? `${found.titles.length} of ${all.length} ${many}`
        : found.titles.length === 1
          ? `1 ${one}`
          : `${found.titles.length} ${many}`,
    on && offered.looking && "still looking up the rest",
  ];
  return (
    <>
      <Breadcrumb trail={[LIBRARY]} current={found.name} />
      <Header franchise={found} />
      <MissingDetails
        title={opened}
        collection={found.name}
        alone={found.titles.length === 1}
        onClose={() => setOpened(null)}
      />
      <EngineProblem queries={[franchise]} />
      <section
        aria-labelledby="franchise-titles"
        className="flex animate-fade-up flex-col gap-4 [animation-delay:90ms]"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-0.5">
            <h2 id="franchise-titles" className="type-heading">
              {films ? "Films" : "Titles"}
            </h2>
            <span className="text-13 text-fg-muted">
              {[...count, orderWords(sort, kinds.size === 1)].filter(Boolean).join(" · ")}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {(all.length > 1 || query) && (
              <SearchField
                value={query}
                onChange={setQuery}
                label={`Search ${found.name}`}
                placeholder={`Search ${all.length} ${many}`}
                className="w-56"
              />
            )}
            <SortControl value={sort} onChange={setSort} />
            {offered && (
              <>
                <span aria-hidden="true" className="h-6 w-px bg-edge" />
                <MissingToggle
                  on={on}
                  count={offered.titles.length}
                  looking={offered.looking}
                  onChange={setWhole}
                />
              </>
            )}
          </div>
        </div>
        {items.length === 0 ? (
          <NoMatches>
            No {one} in {found.name} goes by “{query.trim()}”.
          </NoMatches>
        ) : (
          <CardGrid
            groups={groupsByType(sort) ? byKind(items) : together(items)}
            keyOf={(item) => ("title" in item ? item.title.id : `missing ${item.missing.entryId}`)}
            card={(item) =>
              "title" in item ? (
                <TitleCard title={item.title} />
              ) : (
                <MissingCard title={item.missing} onOpen={() => setOpened(item.missing)} />
              )
            }
          />
        )}
      </section>
    </>
  );
}

/** The library's titles, and with them the ones it lacks: in their places by release or name,
 * or after the library's own when the order looks at what's in the library (newest added, most
 * missing). */
function shelved(titles: TitleSummary[], lacking: MissingTitle[], sort: TitleSort): Shelved[] {
  const held: Shelved[] = titles.map((title) => ({ ...facts(title), title }));
  if (lacking.length === 0) return held;
  const missing: Shelved[] = lacking.map((title) => ({ ...facts(title), missing: title }));
  if (!groupsByType(sort)) return [...held, ...missing];
  return [...held, ...missing].sort(sort === "name" ? byName : byRelease);
}

function facts(title: TitleSummary | MissingTitle) {
  return { kind: title.kind, name: title.name, released: title.released };
}

function byName(a: Shelved, b: Shelved): number {
  return a.name.localeCompare(b.name, "en", { sensitivity: "base" });
}

/** Oldest release first, undated last, then by name. */
function byRelease(a: Shelved, b: Shelved): number {
  if (a.released === b.released) return byName(a, b);
  if (a.released === null) return 1;
  if (b.released === null) return -1;
  return a.released < b.released ? -1 : 1;
}

/** What TMDB knows of a film the library has none of, in a card over the collection's page: its
 * poster across the top, blurred, with the poster itself in its dotted place beside its name;
 * what it is, its synopsis, and its page there. */
function MissingDetails(props: {
  title: MissingTitle | null;
  /** The page's name: the collection's, or the film's when it's alone in the library. */
  collection: string;
  /** The library has one film of the collection, whose page this is. */
  alone: boolean;
  onClose: () => void;
}) {
  const { title } = props;
  const picture = useCoverPicture(title?.cover ?? null);
  const cover = picture.address;
  return (
    <Dialog open={title !== null} onOpenChange={(open) => !open && props.onClose()}>
      {title && (
        <DialogContent className="w-[min(36rem,calc(100vw-2rem))]">
          <DialogPicture
            src={cover}
            none={!title.cover || picture.problem !== null}
            blur
            tag={kindWord(title.kind)}
          >
            <div className="flex min-w-0 items-end gap-4">
              <div
                className={cn(
                  "relative aspect-[2/3] w-20 shrink-0 overflow-hidden rounded-12 border-2 border-dotted bg-surface",
                  title.coming ? "border-missing/40" : "border-missing",
                )}
              >
                {cover && (
                  <img src={cover} alt="" className="absolute inset-0 size-full object-cover" />
                )}
              </div>
              <div className="flex min-w-0 flex-col gap-0.5 pb-0.5">
                <span className="truncate font-bold text-12 text-fg-soft">{props.collection}</span>
                <DialogTitle className="line-clamp-2 text-24 tracking-[-0.02em]">
                  {title.name}
                </DialogTitle>
              </div>
            </div>
          </DialogPicture>
          <DialogBody>
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="inline-flex h-6 items-center gap-1.5 rounded-full bg-tint/6 px-2.5 font-extrabold text-11">
                <StatusShape state={title.coming ? "upcoming" : "missing"} className="size-2" />
                {title.coming ? "Coming" : "Not in your library"}
              </span>
              <DialogDescription>{missingFacts(title)}</DialogDescription>
            </div>
            <Facts
              facts={[
                ["Studio", title.studio],
                ["Status", statusWords(standing(title), title.kind)],
              ]}
            />
            <Genres genres={title.genres} />
            {title.overview ? (
              <Synopsis text={title.overview} lines={6} />
            ) : (
              <p className="text-13 text-fg-muted">TMDB has no synopsis of it yet.</p>
            )}
            <p className="text-13 text-fg-muted">
              {props.alone
                ? `TMDB keeps it in one collection with ${props.collection}.`
                : `TMDB counts it in ${props.collection}.`}{" "}
              It's here so you know the collection has it.
            </p>
            <ElsewhereLinks tmdbType={title.tmdbType} tmdbId={title.tmdbId} />
          </DialogBody>
        </DialogContent>
      )}
    </Dialog>
  );
}

/** Where a film the library lacks stands, when its tag doesn't say it already ("Coming"). */
function standing(title: MissingTitle) {
  return title.airing && !title.coming ? ("airing" as const) : null;
}

/** Puts the films the library has none of among the collection's, or takes them away. */
function MissingToggle(props: {
  on: boolean;
  count: number;
  looking: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <div className="inline-flex rounded-22 bg-well p-1">
      <button
        type="button"
        aria-pressed={props.on}
        onClick={() => props.onChange(!props.on)}
        className={cn(
          "press inline-flex min-h-9 cursor-pointer items-center gap-2 rounded-18 px-4 font-bold text-fg-soft",
          props.on && "bg-accent font-extrabold text-on-accent",
        )}
      >
        Missing films{" "}
        <span className={cn("font-mono text-12", props.on ? "text-on-accent" : "text-fg-muted")}>
          {props.count === 0 && props.looking ? "…" : props.count}
        </span>
      </button>
    </div>
  );
}

/** A film the library has none of: a place kept for it, its outline dotted, TMDB's poster dimmed
 * in it, with a hollow "Not in library" (a fainter "Coming" for one not out yet). Maku has no
 * page for it: it opens to say what TMDB knows of it. */
function MissingCard({ title, onOpen }: { title: MissingTitle; onOpen: () => void }) {
  const cover = useCover(title.cover);
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`${title.name}: ${title.coming ? "coming" : "not in library"}`}
      className="lift flex w-full cursor-pointer flex-col gap-2.5 rounded-16 text-left focus-visible:outline-2"
    >
      <div
        className={cn(
          "relative aspect-[2/3] overflow-hidden rounded-14 border-2 border-dotted",
          title.coming ? "border-missing/40" : "border-missing",
        )}
      >
        {cover && (
          <img
            src={cover}
            alt=""
            aria-hidden="true"
            className="absolute inset-0 size-full object-cover opacity-40"
          />
        )}
        <span className="absolute top-2 left-2 inline-flex h-6 items-center gap-1.5 rounded-full bg-tag px-2.25 font-bold text-11">
          <StatusShape state={title.coming ? "upcoming" : "missing"} className="size-2" />
          {title.coming ? "Coming" : "Not in library"}
        </span>
      </div>
      <span className="flex flex-col gap-px px-0.5">
        <span
          title={title.name}
          className="line-clamp-2 font-extrabold text-14 text-fg-muted leading-snug"
        >
          {title.name}
        </span>
        <span className="truncate text-12 text-fg-faint">{missingFacts(title)}</span>
      </span>
    </button>
  );
}

/** "Movie · 2017"; for a series, "TV series · 2024 · 20 episodes" or "TV series · 2026 · airing". */
function missingFacts(title: MissingTitle): string {
  const parts = [kindWord(title.kind)];
  if (title.year) parts.push(String(title.year));
  if (title.airing) parts.push("airing");
  else if (title.kind !== "movie" && title.episodes !== null && title.episodes > 1) {
    parts.push(`${title.episodes} episodes`);
  }
  return parts.join(" · ");
}

const KINDS: TitleKind[] = ["series", "movie"];

/** The years a collection spans, by its films' releases: "2014 to 2021", or one year. */
function years(franchise: FranchiseSummary): string | null {
  const dated = franchise.titles.flatMap((title) => (title.year ? [title.year] : []));
  if (dated.length === 0) return null;
  const first = Math.min(...dated);
  const last = Math.max(...dated);
  return first === last ? String(first) : `${first} to ${last}`;
}

/** A collection's poster, name, the years it spans and what it holds, its lead's synopsis, and
 * how much of it is there. */
function Header({ franchise }: { franchise: FranchiseSummary }) {
  const lead = franchise.titles.find((title) => title.id === franchise.id) ?? franchise.titles[0];
  const about = useTitleAbout(lead?.id ?? 0, lead !== undefined).data;
  const kinds = KINDS.filter((kind) => franchise.kinds[kind] > 0).map((kind) =>
    kindCount(kind, franchise.kinds[kind]),
  );
  const facts = [years(franchise), ...kinds].filter(Boolean);

  return (
    <section
      aria-label={franchise.name}
      className="flex animate-fade-up flex-wrap items-center gap-6 rounded-24 border border-edge bg-glass p-6 shadow-panel"
    >
      {lead && (
        <Poster title={{ ...lead, hasPoster: franchise.hasPoster }} className="w-30 shrink-0" />
      )}
      <div className="flex min-w-0 flex-[1_1_320px] flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex h-6.5 items-center rounded-full bg-accent px-2.5 font-extrabold text-12 text-on-accent">
            {/* A film alone in the library, come for what its collection lacks, says what it is. */}
            {franchise.titles.length === 1 && lead ? kindWord(lead.kind) : "Collection"}
          </span>
          {franchise.airing && <span className="text-12 text-accent-fg">Still airing</span>}
        </div>
        <h1 className="type-title">{franchise.name}</h1>
        <span className="text-14 text-fg-muted">{facts.join(" · ")}</span>
        {about?.overview && (
          <div className="max-w-[72ch] pt-1">
            <Synopsis text={about.overview} />
          </div>
        )}
      </div>
      {franchise.aired > 0 && (
        <div className="flex flex-col items-center gap-1">
          <span className="font-extrabold text-36 tracking-[-0.02em]">
            {share(franchise.present, franchise.aired)}%
          </span>
          <span className="text-12 text-fg-muted">
            {franchise.present} of {franchise.aired} episodes
          </span>
        </div>
      )}
    </section>
  );
}
