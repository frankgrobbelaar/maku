import { useState } from "react";
import { EmptyState } from "@/components/empty-state";
import { EngineProblem } from "@/components/engine-problem";
import { NoMatches, SearchField, useAddressSearch } from "@/components/search-field";
import { Loading, PanelSkeleton } from "@/components/skeleton";
import { Stayed } from "@/components/stayed";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import {
  type Conversion,
  type History,
  type Picture,
  type PlanDone,
  type ScanDone,
  type SubtitlesDone,
  type TidyResult,
  useClearHistory,
  useHistory,
  useSettings,
  useTakeAway,
  useUndoPlan,
} from "@/lib/engine";
import { clockLength, codecName, languageName, scanChanges, size } from "@/lib/format";
import { useSettled } from "@/lib/settled";

type Shown = "all" | "conversions" | "subtitles" | "moves" | "scans";

const FILTERS = [
  { value: "all", label: "All" },
  { value: "conversions", label: "Conversions" },
  { value: "subtitles", label: "Subtitles" },
  { value: "moves", label: "Renames and moves" },
  { value: "scans", label: "Scans" },
] as const;

/** One thing Maku did, at a moment. */
type Event =
  | { kind: "plan"; at: string; plan: PlanDone }
  | { kind: "undo"; at: string; plan: PlanDone }
  | { kind: "scan"; at: string; scan: ScanDone }
  | { kind: "subtitles"; at: string; made: SubtitlesDone };

/** What a day shows before "Show all": a night's conversions or a day of scans can be many. */
const A_DAY = 20;

type Keep = "day" | "week" | "month" | "nothing";

const KEEP = [
  { value: "day", label: "Last 24 hours" },
  { value: "week", label: "Last 7 days" },
  { value: "month", label: "Last 30 days" },
  { value: "nothing", label: "Nothing" },
] as const;

/** Everything Maku changed, newest first, a week's worth of days at a time; a tidy-up can be
 * undone from here, and History cleared, all of it or what's older than a day, week or month.
 * The filter finds what names a title or file, a week of the days it finds anything on at a
 * time. */
export function HistoryPage() {
  const [query, setQuery] = useAddressSearch();
  const asked = useSettled(query.trim(), 250);
  const history = useHistory(asked);
  const undo = useUndoPlan();
  const takeAway = useTakeAway();
  const settings = useSettings().data;
  const kept = settings?.quarantineDays;
  const [shown, setShown] = useState<Shown>("all");
  const [result, setResult] = useState<TidyResult | null>(null);
  const [clearing, setClearing] = useState(false);
  const [cleared, setCleared] = useState<number | null>(null);
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const answered = history.data !== undefined && !history.isPlaceholderData;

  const pages = history.data?.pages;
  const events = pages ? eventsOf(together(pages), shown) : [];
  const anything =
    pages?.some((page) => page.plans.length + page.scans.length + page.subtitles.length > 0) ??
    false;
  return (
    <>
      <header className="page-top flex animate-fade-up flex-wrap items-end justify-between gap-4">
        <div className="flex max-w-xl flex-col gap-1.5">
          <h1 className="type-title">History</h1>
          <p className="text-14 text-fg-muted">
            {settings?.historyDays
              ? `Everything Maku changed in the last ${settings.historyDays} days, newest first. Renames and moves can be undone while they're here`
              : "Everything Maku changed, newest first. Renames and moves can be undone at any time"}
            , and a converted file's original put back{" "}
            {kept === null ? "while it's in quarantine" : `for ${kept ?? 30} days`}.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <SearchField
            value={query}
            onChange={setQuery}
            label="Filter History"
            placeholder="Filter by title or file"
            className="w-60"
          />
          <Segmented label="Show" value={shown} options={FILTERS} onChange={setShown} />
          {anything && !clearing && (
            <Button variant="ghost" onClick={() => setClearing(true)}>
              Clear History
            </Button>
          )}
        </div>
      </header>
      {clearing && (
        <ClearHistory
          onClose={() => setClearing(false)}
          onCleared={(gone) => {
            setCleared(gone);
            setClearing(false);
          }}
        />
      )}
      {cleared !== null && !clearing && (
        <p role="status" className="text-13 text-fg-muted">
          {cleared === 0
            ? "There was nothing to clear: what's left is newer, or can still be put back."
            : `${count(cleared, "entry", "entries")} cleared from History. Your files stay as they are.`}
        </p>
      )}
      <EngineProblem queries={[history]} />
      {!history.data && (
        <Loading label="Loading history" queries={[history]}>
          <PanelSkeleton rows={4} />
          <PanelSkeleton rows={3} />
        </Loading>
      )}
      {(undo.error ?? takeAway.error) && (
        <p role="alert" className="text-13 text-broken-fg">
          {(undo.error ?? takeAway.error)?.message}
        </p>
      )}
      {result && result.problems.length > 0 && <Stayed problems={result.problems} />}
      {/* The last search's days stand in while the next one's come: they say nothing of it. */}
      {answered && events.length === 0 && !history.hasNextPage && asked && (
        <NoMatches>
          Nothing in History goes by “{asked}”{shown === "all" ? "" : " among what's shown"}.
        </NoMatches>
      )}
      {answered && events.length === 0 && !history.hasNextPage && !asked && (
        <EmptyState title="Nothing yet">
          Maku lists here everything it changes in your folders, newest first.
        </EmptyState>
      )}
      {answered && events.length === 0 && history.hasNextPage && (
        <p className="text-13 text-fg-muted">Nothing of that kind on the days shown.</p>
      )}
      {days(events).map(([day, onDay]) => {
        const all = opened.has(day) || onDay.length <= A_DAY;
        return (
          <section
            key={day}
            aria-label={day}
            className="flex animate-fade-up flex-col gap-1 rounded-22 border border-edge bg-glass px-5 py-4 shadow-panel"
          >
            <h2 className="pb-1 font-extrabold text-15">{day}</h2>
            <ul className="flex flex-col">
              {(all ? onDay : onDay.slice(0, A_DAY)).map((event) => (
                <EventRow
                  key={`${event.kind}-${idOf(event)}`}
                  event={event}
                  busy={undo.isPending || takeAway.isPending}
                  onUndo={(plan) =>
                    undo.mutate({ path: `/plans/${plan.id}/undo` }, { onSuccess: setResult })
                  }
                  onTakeAway={(made) =>
                    takeAway.mutate({ path: `/subtitles/batches/${made.id}/take-away` })
                  }
                />
              ))}
            </ul>
            {!all && (
              <Button
                size="sm"
                variant="ghost"
                className="self-start"
                onClick={() => setOpened((before) => new Set(before).add(day))}
              >
                Show all {onDay.length}
              </Button>
            )}
          </section>
        );
      })}
      {history.hasNextPage && (
        <Button
          className="self-center"
          disabled={history.isFetchingNextPage}
          onClick={() => void history.fetchNextPage()}
        >
          {history.isFetchingNextPage ? "Loading older days…" : "Show older"}
        </Button>
      )}
    </>
  );
}

/** Asks before clearing History: what stays (the last day, week or month, or nothing), and
 * that what goes can't be undone from here. Files never change, and what still has a copy in
 * quarantine stays, so it can be put back. */
function ClearHistory(props: { onClose: () => void; onCleared: (gone: number) => void }) {
  const clear = useClearHistory();
  const [keep, setKeep] = useState<Keep>("week");
  return (
    <fieldset
      aria-label="Clear History?"
      className="flex animate-fade-up flex-col gap-3 rounded-16 border border-danger/40 bg-danger/8 p-4"
    >
      <span className="font-extrabold text-14">Clear History?</span>
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-bold text-13">Keep</span>
        <Segmented label="Keep" value={keep} options={KEEP} onChange={setKeep} />
      </div>
      <span className="text-13 text-fg-soft">
        What's cleared can't be undone or put back from here. Your files stay as they are, and
        anything with a copy still in quarantine stays listed, so you can still put it back.
      </span>
      {clear.isError && (
        <p role="alert" className="text-13 text-broken-fg">
          {clear.error.message}
        </p>
      )}
      <div className="flex flex-wrap gap-2.5">
        <Button
          size="sm"
          variant="danger"
          disabled={clear.isPending}
          onClick={() =>
            clear.mutate(
              { path: "/history/clear", body: { keep } },
              { onSuccess: (done) => props.onCleared(done.cleared) },
            )
          }
        >
          {keep === "nothing" ? "Clear all of History" : "Clear the rest"}
        </Button>
        <Button size="sm" variant="ghost" onClick={props.onClose}>
          Back
        </Button>
      </div>
    </fieldset>
  );
}

function EventRow(props: {
  event: Event;
  busy: boolean;
  onUndo: (plan: PlanDone) => void;
  onTakeAway: (made: SubtitlesDone) => void;
}) {
  const { event } = props;
  const [verb, title, detail] = words(event);
  const plan = event.kind === "plan" ? event.plan : null;
  // A conversion goes back only while its original is still in quarantine, and only once what
  // replaced the file since is put back.
  const undoable =
    plan !== null &&
    plan.undoneAt === null &&
    (plan.kind === "convert"
      ? plan.quarantined > 0 && !plan.conversion?.replaced
      : plan.moved + plan.quarantined + plan.takenAway > 0);
  const action =
    plan?.conversion?.kind === "merge"
      ? "Put back both copies"
      : plan?.kind === "convert"
        ? "Put back the original"
        : plan?.deleted
          ? "Put back what was deleted"
          : plan && plan.takenAway > 0
            ? "Put back the subtitles"
            : "Undo";
  if (event.kind === "subtitles") {
    return (
      <li className="grid grid-cols-[3.5rem_6.5rem_1fr_auto] items-center gap-x-3 gap-y-1 border-rule border-b py-3 text-13 last:border-b-0">
        <span className="font-mono text-12 text-fg-muted">{clock(event.at)}</span>
        <span className="font-extrabold">{verb}</span>
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="font-bold">{title}</span>
          {detail && <span className="text-12 text-fg-muted">{detail}</span>}
        </span>
        {event.made.present > 0 ? (
          <Button size="sm" disabled={props.busy} onClick={() => props.onTakeAway(event.made)}>
            Take them away
          </Button>
        ) : (
          <span />
        )}
      </li>
    );
  }
  return (
    <li className="grid grid-cols-[3.5rem_6.5rem_1fr_auto] items-center gap-x-3 gap-y-1 border-rule border-b py-3 text-13 last:border-b-0">
      <span className="font-mono text-12 text-fg-muted">{clock(event.at)}</span>
      <span className="font-extrabold">{verb}</span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="font-bold">{title}</span>
        {detail && <span className="text-12 text-fg-muted">{detail}</span>}
      </span>
      {undoable ? (
        <Button
          size="sm"
          aria-label={action}
          disabled={props.busy}
          onClick={() => props.onUndo(plan)}
        >
          {plan.kind === "convert" || plan.deleted || plan.takenAway > 0 ? "Put back" : "Undo"}
        </Button>
      ) : (
        <span />
      )}
    </li>
  );
}

/** [verb, title, detail] for one event, as the history board words them. */
function words(event: Event): [string, string, string | null] {
  if (event.kind === "scan") {
    const { scan } = event;
    const detail =
      scan.state === "failed"
        ? (scan.problem ?? "It stopped")
        : scan.state === "running"
          ? "Running now"
          : scan.state === "paused"
            ? "Paused"
            : (scan.note ?? "Every folder looked at");
    const changed =
      scan.state === "done" && scan.added !== null && scan.gone !== null
        ? ` · ${scanChanges(scan.added, scan.gone)}`
        : "";
    return ["Scanned", "Your library folders", `${detail}${changed}`];
  }
  if (event.kind === "subtitles") return subtitleWords(event.made);
  const { plan } = event;
  const made = plan.conversion;
  if (made?.kind === "merge") {
    const label = plan.title.replace(/^Added English from another copy to /, "");
    if (event.kind === "undo") {
      return ["Put back", label, "It and its other copy are as they were again"];
    }
    const since = made.replaced ? " · changed again since" : "";
    return [
      "Added",
      `English to ${label}`,
      `From its other copy, set aside with it · checked${since}`,
    ];
  }
  if (plan.kind === "convert") {
    const label = plan.title.replace(/^Converted /, "");
    if (event.kind === "undo") return ["Put back", label, "The original is in its place again"];
    const gone = plan.undoneAt === null && plan.quarantined === 0 && plan.moved > 0;
    const words = [
      made && conversionWords(made),
      gone && "original deleted",
      made?.replaced && "changed again since",
    ].filter(Boolean);
    return ["Converted", label, words.length > 0 ? words.join(" · ") : null];
  }
  if (plan.deleted) {
    const label = plan.title.replace(/^Deleted /, "");
    if (event.kind === "undo")
      return ["Put back", label, `You put ${count(plan.undone, "file")} back`];
    const parts = [
      plan.quarantined > 0 && `${count(plan.quarantined, "video")} in quarantine`,
      plan.failed > 0 && `${plan.failed} couldn't be moved`,
      plan.undoneAt !== null && "Put back since",
      `plan ${plan.id}`,
    ].filter(Boolean);
    return ["Deleted", label, parts.join(" · ")];
  }
  if (plan.takenAway > 0 || (plan.undoneAt !== null && plan.title.startsWith("Took away"))) {
    const label = plan.title.replace(/^Took away the /, "");
    if (event.kind === "undo") {
      return ["Put back", label, `You put ${count(plan.undone, "file")} back`];
    }
    const parts = [
      plan.takenAway > 0 && `${count(plan.takenAway, "file")} in quarantine`,
      plan.undoneAt !== null && "Put back since",
      `plan ${plan.id}`,
    ].filter(Boolean);
    return ["Took away", label, parts.join(" · ")];
  }
  if (event.kind === "undo") {
    return ["Undone", plan.title, `You put ${count(plan.undone, "file")} back`];
  }
  const parts = [
    plan.moved > 0 && `${count(plan.moved, "file")} moved`,
    plan.quarantined > 0 && `${count(plan.quarantined, "copy", "copies")} set aside`,
    plan.failed > 0 && `${plan.failed} couldn't be moved`,
    plan.undoneAt !== null && "Put back since",
    plan.undoneAt === null && plan.undone > 0 && `${plan.undone} put back`, // the rest couldn't be
    `plan ${plan.id}`,
  ].filter(Boolean);
  return [plan.title.startsWith("Renamed") ? "Renamed" : "Moved", plan.title, parts.join(" · ")];
}

/** "English subtitles for 37 episodes", "Glass Orchard · Season 1 · from the French sound ·
 * Best", with what couldn't be made, what waits, and whether they're still there. */
function subtitleWords(made: SubtitlesDone): [string, string, string] {
  const parts = [
    made.title,
    made.language ? `from the ${languageName(made.language)} sound` : "from their sound",
    made.quality === "best" ? "Best" : "Fast",
    made.quiet > 0 && `${made.quiet} with no one speaking`,
    made.failed > 0 && `${made.failed} couldn't be made`,
    made.waiting > 0 && `${made.waiting} still to make`,
    made.made > 0 && made.present === 0 && "taken away since",
    made.present > 0 && made.present < made.made && `${made.present} still there`,
  ].filter(Boolean);
  return ["Made", `English subtitles for ${count(made.made, "video")}`, parts.join(" · ")];
}

/** "480p H.264 233 MB → 1080p HEVC 412 MB · 58 min · checked": every result is checked before
 * it takes its original's place. */
function conversionWords(made: Conversion): string {
  const picture = ({ height, codec, size: bytes }: Picture) =>
    [height && `${height}p`, codec && codecName(codec), bytes && size(bytes)]
      .filter(Boolean)
      .join(" ");
  return [
    `${picture(made.before)} → ${picture(made.after)}`,
    made.seconds !== null &&
      (made.seconds < 60 ? `${Math.round(made.seconds)} s` : clockLength(made.seconds / 60)),
    "checked",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The pages loaded, as one: a tidy-up undone on a later day is on both days' pages. Only
 * what happened on the days loaded shows (from `from` on), so the tidy-up itself waits for its
 * own page. */
function together(pages: History[]): {
  plans: PlanDone[];
  scans: ScanDone[];
  subtitles: SubtitlesDone[];
  from: string | null;
} {
  const plans = new Map<number, PlanDone>();
  const scans = new Map<number, ScanDone>();
  const subtitles = new Map<number, SubtitlesDone>();
  for (const page of pages) {
    for (const plan of page.plans) if (!plans.has(plan.id)) plans.set(plan.id, plan);
    for (const scan of page.scans) if (!scans.has(scan.id)) scans.set(scan.id, scan);
    for (const made of page.subtitles) if (!subtitles.has(made.id)) subtitles.set(made.id, made);
  }
  return {
    plans: [...plans.values()],
    scans: [...scans.values()],
    subtitles: [...subtitles.values()],
    from: pages.at(-1)?.older ?? null,
  };
}

function eventsOf(history: ReturnType<typeof together>, shown: Shown): Event[] {
  const events: Event[] = [];
  // Taking Maku's subtitles away is a tidy-up, shown with the subtitles.
  const showsPlan: Record<Shown, (plan: PlanDone) => boolean> = {
    all: () => true,
    conversions: (plan) => plan.kind === "convert",
    subtitles: (plan) => plan.takenAway > 0 || plan.title.startsWith("Took away"),
    moves: (plan) =>
      plan.kind === "tidy" && !(plan.takenAway > 0 || plan.title.startsWith("Took away")),
    scans: () => false,
  };
  for (const plan of history.plans) {
    if (!showsPlan[shown](plan)) continue;
    events.push({ kind: "plan", at: plan.appliedAt, plan });
    if (plan.undoneAt) events.push({ kind: "undo", at: plan.undoneAt, plan });
  }
  if (shown === "all" || shown === "scans") {
    for (const scan of history.scans) events.push({ kind: "scan", at: scan.startedAt, scan });
  }
  if (shown === "all" || shown === "subtitles") {
    for (const made of history.subtitles) events.push({ kind: "subtitles", at: made.madeAt, made });
  }
  return events
    .filter((event) => history.from === null || localDay(event.at) >= history.from)
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
}

/** "2026-10-14": the day on this PC a moment fell on, as the engine counts History's days. */
function localDay(at: string): string {
  const moment = new Date(at);
  const month = String(moment.getMonth() + 1).padStart(2, "0");
  const day = String(moment.getDate()).padStart(2, "0");
  return `${moment.getFullYear()}-${month}-${day}`;
}

/** The events by day, as the owner reads them: "Today", "Yesterday", "8 October", and
 * "8 October 2025" a year back. */
function days(events: Event[]): [string, Event[]][] {
  const groups = new Map<string, Event[]>();
  for (const event of events) {
    const day = dayName(new Date(event.at));
    groups.set(day, [...(groups.get(day) ?? []), event]);
  }
  return [...groups];
}

function dayName(moment: Date): string {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (moment.toDateString() === today.toDateString()) return "Today";
  if (moment.toDateString() === yesterday.toDateString()) return "Yesterday";
  // A year ago, the same day has the year with it, so the two never run together.
  return moment.toLocaleDateString(
    "en-GB",
    moment.getFullYear() === today.getFullYear()
      ? { day: "numeric", month: "long" }
      : { day: "numeric", month: "long", year: "numeric" },
  );
}

function idOf(event: Event): number {
  if (event.kind === "scan") return event.scan.id;
  if (event.kind === "subtitles") return event.made.id;
  return event.plan.id;
}

function clock(at: string): string {
  return new Date(at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function count(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
