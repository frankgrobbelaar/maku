import { ArrowRight, Check } from "lucide-react";
import { RadioGroup } from "radix-ui";
import { Fragment, useState } from "react";
import { useNavigate } from "react-router";
import { EmptyState, ShelfIllustration } from "@/components/empty-state";
import { EngineProblem } from "@/components/engine-problem";
import { FileMenuItems, FileNote, useFileActions } from "@/components/file-actions";
import { NoMatches, SearchField, useAddressSearch } from "@/components/search-field";
import { Loading, PanelSkeleton, TilesSkeleton } from "@/components/skeleton";
import { Stayed } from "@/components/stayed";
import { Button } from "@/components/ui/button";
import { RowMenu } from "@/components/ui/menu";
import {
  type CopyFacts,
  type Duplicate,
  type English,
  type ProposedChange,
  type ReviewedChange,
  type TidyCategory,
  type TidyResult,
  useApplyTidy,
  useIgnored,
  useScan,
  useTidy,
  useUndoPlan,
} from "@/lib/engine";
import { codecName, isEnglish, languageName, size, split, within } from "@/lib/format";
import { matches } from "@/lib/search";
import { cn } from "@/lib/utils";

const SHOWN = 5; // changes listed per title before "Show more"

/** Tidy up: Maku proposes where every video goes, the owner keeps what they want and
 * applies it. Nothing changes until then, and History can undo it all. */
export function TidyPage() {
  const navigate = useNavigate();
  const [keep, setKeep] = useState<string[]>([]);
  const proposal = useTidy(keep);
  const ignored = useIgnored().data?.length ?? 0;
  const apply = useApplyTidy();
  const undo = useUndoPlan();
  const scanning = useScan().data?.state === "running";
  const [only, setOnly] = useState<TidyCategory | null>(null);
  const [query, setQuery] = useAddressSearch();
  const [leftOut, setLeftOut] = useState<number[]>([]);
  const [skipped, setSkipped] = useState<string[]>([]); // videos left where they are, this time
  // Copies kept with the other copy's English, or as they are, by the copy kept's path; till the
  // owner chooses, with it, unless Maku tried before and couldn't.
  const [english, setEnglish] = useState<Record<string, boolean>>({});
  const [done, setDone] = useState<TidyResult | null>(null);
  const [undone, setUndone] = useState<TidyResult | null>(null);

  if (!proposal.data) {
    return (
      <>
        <Header />
        <EngineProblem queries={[proposal]} />
        <Loading label="Loading what to tidy" queries={[proposal]}>
          <TilesSkeleton count={5} />
          <PanelSkeleton rows={4} />
          <PanelSkeleton rows={3} />
        </Loading>
      </>
    );
  }
  const found = proposal.data;
  // What's on screen: the kind of change picked, and what the search finds.
  const shown = found.changes.filter(
    (change) =>
      (!only || change.category === only) &&
      matches(query, change.title, change.label, split(change.source)[0], split(change.target)[0]),
  );
  const copies = found.duplicates.filter((duplicate) =>
    matches(
      query,
      duplicate.label,
      ...[duplicate.keep, ...duplicate.drop].map((copy) => split(copy.path)[0]),
    ),
  );
  const shownChosen = shown.filter(
    (change) => !leftOut.includes(change.titleId) && !skipped.includes(change.video),
  ); // what's on screen, and not skipped
  const withEnglish = (duplicate: Duplicate) =>
    duplicate.english !== null &&
    (english[duplicate.keep.path] ?? duplicate.english.tried === null);
  // A copy whose English goes into the one kept stays where it is, with its subtitles, till the
  // queue has added it.
  const giving = found.duplicates.filter(
    (duplicate) =>
      withEnglish(duplicate) &&
      shownChosen.some((change) => change.video === duplicate.english?.other),
  );
  const chosen = shownChosen.filter(
    (change) => !giving.some((duplicate) => duplicate.english?.other === change.video),
  );
  const count = chosen.length + giving.length;
  const busy = apply.isPending || undo.isPending || scanning;

  function applyChosen() {
    setUndone(null);
    const asked = giving.map((duplicate) => duplicate.keep.path);
    apply.mutate(
      { path: "/tidy", body: { changes: chosen.map(reviewed), keep, english: asked } },
      {
        onSuccess: (result) => {
          setDone(result);
          setLeftOut([]);
          setSkipped([]);
          setKeep([]);
          setEnglish({});
        },
      },
    );
  }

  return (
    <>
      <Header
        action={
          found.changes.length > 0 && (
            <Button variant="primary" disabled={busy || count === 0} onClick={applyChosen}>
              {applyText(count)}
            </Button>
          )
        }
      />
      {done && (
        <Done
          result={done}
          busy={busy}
          onUndo={() =>
            done.planId !== null &&
            undo.mutate(
              { path: `/plans/${done.planId}/undo` },
              {
                onSuccess: (result) => {
                  setDone(null);
                  setUndone(result.problems.length > 0 ? result : null);
                },
              },
            )
          }
          onHistory={() => void navigate("/history")}
        />
      )}
      {undone && <Stayed problems={undone.problems} />}
      {(apply.isError || undo.isError) && (
        <p role="alert" className="text-13 text-broken-fg">
          {(apply.error ?? undo.error)?.message}
        </p>
      )}
      <EngineProblem queries={[proposal]} />
      <Tiles
        changes={found.changes}
        waiting={found.waiting}
        ignored={ignored}
        broken={found.broken}
        only={only}
        onOnly={setOnly}
        onMatch={() => void navigate("/match")}
      />
      {found.changes.length === 0 ? (
        <EmptyState title="Everything is filed" illustration={<ShelfIllustration />}>
          Every video Maku knows is filed where it belongs. New ones are proposed here when they
          arrive.
        </EmptyState>
      ) : (
        <>
          <div className="flex animate-fade-up flex-wrap items-center justify-between gap-3">
            <p className="text-13 text-fg-muted">
              Duplicates go to a quarantine folder on the same drive (Maku quarantine). Nothing is
              deleted.
            </p>
            {(found.changes.length > 1 || query) && (
              <SearchField
                value={query}
                onChange={setQuery}
                label="Search the changes"
                placeholder="Search by title or file"
                className="w-64"
              />
            )}
          </div>
          {shown.length === 0 && query && (
            <NoMatches>
              No change{only ? " of this kind" : ""} goes by “{query.trim()}”.
            </NoMatches>
          )}
          {copies.length > 0 && (!only || only === "duplicate") && (
            <section aria-label="Duplicates" className="flex animate-fade-up flex-col gap-4">
              {copies.map((duplicate) => (
                <Copies
                  key={duplicate.label}
                  duplicate={duplicate}
                  withEnglish={withEnglish(duplicate)}
                  onEnglish={(on) =>
                    setEnglish((before) => ({ ...before, [duplicate.keep.path]: on }))
                  }
                  onSwap={() =>
                    setKeep((before) => [
                      ...before.filter((path) => path !== duplicate.keep.path),
                      ...duplicate.drop.slice(0, 1).map((copy) => copy.path),
                    ])
                  }
                />
              ))}
            </section>
          )}
          <section aria-label="Changes" className="flex animate-fade-up flex-col gap-4">
            {byTitle(shown).map(([titleId, changes]) => (
              <TitleChanges
                key={titleId}
                changes={changes}
                included={!leftOut.includes(titleId)}
                onInclude={(on) =>
                  setLeftOut((before) =>
                    on ? before.filter((id) => id !== titleId) : [...before, titleId],
                  )
                }
                skipped={skipped}
                onSkip={(video, on) =>
                  setSkipped((before) =>
                    on ? [...before, video] : before.filter((path) => path !== video),
                  )
                }
              />
            ))}
          </section>
          <footer className="flex animate-fade-up flex-wrap items-center justify-between gap-3 rounded-20 border border-edge bg-glass px-5 py-4 shadow-panel">
            <span className="text-13 text-fg-muted">
              {scanning ? (
                "Maku is scanning. Apply once it's done, so it knows every file."
              ) : (
                <>
                  {count} {count === 1 ? "change" : "changes"} selected.
                  {found.waiting > 0 &&
                    ` ${found.waiting} ${found.waiting === 1 ? "file stays" : "files stay"} where ${found.waiting === 1 ? "it is" : "they are"} until matched.`}
                </>
              )}
            </span>
            <Button variant="primary" disabled={busy || count === 0} onClick={applyChosen}>
              {applyText(count)}
            </Button>
          </footer>
        </>
      )}
      {found.skipped.length > 0 && <Staying skipped={found.skipped} />}
    </>
  );
}

function Header({ action }: { action?: React.ReactNode }) {
  return (
    <header className="page-top flex animate-fade-up flex-wrap items-end justify-between gap-4">
      <div className="flex max-w-xl flex-col gap-1.5">
        <h1 className="type-title">Tidy up</h1>
        <p className="text-14 text-fg-muted">
          Maku proposes, you approve. Nothing changes until you apply, and every change can be
          undone from History.
        </p>
      </div>
      {action}
    </header>
  );
}

function Done(props: {
  result: TidyResult;
  busy: boolean;
  onUndo: () => void;
  onHistory: () => void;
}) {
  const { result } = props;
  const { english } = result;
  const parts = [
    (result.moved > 0 || result.quarantined + english === 0) &&
      `${result.moved} ${result.moved === 1 ? "file" : "files"} filed`,
    result.quarantined > 0 &&
      `${result.quarantined} ${result.quarantined === 1 ? "copy" : "copies"} set aside`,
    english > 0 &&
      `English from ${english} other ${english === 1 ? "copy" : "copies"} joins the queue`,
  ].filter(Boolean);
  return (
    <section
      aria-label="Done"
      className="flex animate-fade-up flex-col gap-3 rounded-20 border border-accent/35 bg-accent/8 px-5 py-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="inline-flex items-center gap-2 font-extrabold text-15">
          <Check size={18} aria-hidden="true" className="text-accent-fg" />
          Done: {parts.join(", ")}.
        </span>
        <div className="flex flex-wrap gap-2.5">
          {result.planId !== null && (
            <Button size="sm" disabled={props.busy} onClick={props.onUndo}>
              Undo
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={props.onHistory}>
            See History
          </Button>
        </div>
      </div>
      {result.problems.length > 0 && (
        <ul className="flex flex-col gap-1 text-13">
          {result.problems.map((problem) => (
            <li key={problem.source} className="text-broken-fg">
              {problem.label}: {problem.problem}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const TILES: { category: TidyCategory; label: string }[] = [
  { category: "mixed", label: "Mixed folders" },
  { category: "rename", label: "Renames" },
  { category: "duplicate", label: "Duplicates" },
];

function Tiles(props: {
  changes: ProposedChange[];
  waiting: number;
  /** Files set aside as not a series or film: listed on the match page, to match after all or
   * delete. */
  ignored: number;
  broken: number;
  only: TidyCategory | null;
  onOnly: (only: TidyCategory | null) => void;
  onMatch: () => void;
}) {
  return (
    <div className="flex animate-fade-up flex-wrap gap-2.5">
      {TILES.map(({ category, label }) => {
        const count = props.changes.filter((change) => change.category === category).length;
        const on = props.only === category;
        return (
          <button
            key={category}
            type="button"
            aria-pressed={on}
            disabled={count === 0}
            onClick={() => props.onOnly(on ? null : category)}
            className={cn(
              "press flex min-w-36 cursor-pointer flex-col items-start gap-0.5 rounded-16 border bg-glass px-4 py-3 text-left shadow-panel disabled:cursor-default disabled:opacity-50",
              on ? "border-accent" : "border-edge",
            )}
          >
            <span className="font-extrabold text-22">{count}</span>{" "}
            <span className="text-12 text-fg-muted">{label}</span>
          </button>
        );
      })}
      <button
        type="button"
        disabled={props.waiting === 0}
        onClick={props.onMatch}
        className="press flex min-w-36 cursor-pointer flex-col items-start gap-0.5 rounded-16 border border-edge bg-glass px-4 py-3 text-left shadow-panel disabled:cursor-default disabled:opacity-50"
      >
        <span className="font-extrabold text-22">{props.waiting}</span>{" "}
        <span className="inline-flex items-center gap-1 text-12 text-fg-muted">
          Need a match {props.waiting > 0 && <ArrowRight size={12} aria-hidden="true" />}
        </span>
      </button>
      {props.ignored > 0 && (
        <button
          type="button"
          onClick={props.onMatch}
          className="press flex min-w-36 cursor-pointer flex-col items-start gap-0.5 rounded-16 border border-edge bg-glass px-4 py-3 text-left shadow-panel"
        >
          <span className="font-extrabold text-22">{props.ignored}</span>{" "}
          <span className="inline-flex items-center gap-1 text-12 text-fg-muted">
            Set aside: not a series or film <ArrowRight size={12} aria-hidden="true" />
          </span>
        </button>
      )}
      <div className="flex min-w-36 flex-col items-start gap-0.5 rounded-16 border border-edge bg-glass px-4 py-3 shadow-panel">
        <span className="font-extrabold text-22">{props.broken}</span>{" "}
        <span className="text-12 text-fg-muted">Broken files</span>
      </div>
    </div>
  );
}

function TitleChanges(props: {
  changes: ProposedChange[];
  included: boolean;
  onInclude: (on: boolean) => void;
  skipped: string[];
  onSkip: (video: string, on: boolean) => void;
}) {
  const [all, setAll] = useState(false);
  const [first] = props.changes;
  if (!first) return null;
  const listed = all ? props.changes : props.changes.slice(0, SHOWN);
  const more = props.changes.length - listed.length;
  return (
    <section
      aria-label={first.title}
      className={cn(
        "flex flex-col gap-3 rounded-22 border border-edge bg-glass p-5 shadow-panel transition-opacity duration-200",
        !props.included && "opacity-55",
      )}
    >
      <label className="flex cursor-pointer items-center gap-3">
        <input
          type="checkbox"
          checked={props.included}
          onChange={(event) => props.onInclude(event.target.checked)}
          className="peer sr-only"
        />
        <span
          aria-hidden="true"
          className={cn(
            "inline-flex size-5.5 shrink-0 items-center justify-center rounded-6 peer-focus-visible:outline-2 peer-focus-visible:outline-accent-fg peer-focus-visible:outline-offset-3",
            props.included ? "bg-accent text-on-accent" : "border-2 border-control",
          )}
        >
          {props.included && <Check size={12} strokeWidth={3.4} />}
        </span>
        <span className="flex min-w-0 flex-col">
          <span className="font-extrabold text-16">{first.title}</span>
          <span className="text-12 text-fg-muted">
            {props.changes.length} {props.changes.length === 1 ? "change" : "changes"}
          </span>
        </span>
      </label>
      <ul className="flex flex-col">
        {listed.map((change) => (
          <ChangeRow
            key={change.source}
            change={change}
            skipped={props.skipped.includes(change.video)}
            onSkip={(on) => props.onSkip(change.video, on)}
          />
        ))}
      </ul>
      {more > 0 && (
        <Button size="sm" variant="ghost" className="self-start" onClick={() => setAll(true)}>
          Show {more} more
        </Button>
      )}
    </section>
  );
}

function ChangeRow(props: {
  change: ProposedChange;
  skipped: boolean;
  onSkip: (on: boolean) => void;
}) {
  const { change } = props;
  const [name] = split(change.source);
  const quarantine = change.kind === "quarantine";
  const files = useFileActions();
  return (
    <li
      className={cn(
        "flex flex-col gap-1 border-rule border-b py-2.5 text-13 transition-opacity duration-200 last:border-b-0",
        props.skipped && !change.taken && "opacity-55",
      )}
    >
      <span className="flex flex-wrap items-center gap-2">
        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <span
            className={cn(
              "inline-flex h-5.5 items-center rounded-full px-2 font-extrabold text-11",
              quarantine ? "bg-broken/20 text-broken-fg" : "bg-tint/8 text-fg-soft",
            )}
          >
            {quarantine ? "Quarantine" : "Move"}
          </span>
          <span className="font-bold">{change.label}</span>
        </span>
        <span className="-my-1.5">
          <RowMenu label={`More for ${name}`}>
            <FileMenuItems path={change.source} actions={files} />
          </RowMenu>
        </span>
      </span>
      <span className="font-mono text-12 text-fg-muted [overflow-wrap:anywhere]">{name}</span>
      <span className="flex items-start gap-1.5 font-mono text-12 text-fg-soft [overflow-wrap:anywhere]">
        <ArrowRight size={13} aria-hidden="true" className="mt-0.5 shrink-0 text-fg-faint" />
        {quarantine ? change.target : within(change.target, change.root)}
      </span>
      {change.taken && change.video === change.source && (
        <Taken change={change} skipped={props.skipped} onSkip={props.onSkip} />
      )}
      <FileNote actions={files} />
    </li>
  );
}

/**
 * A name another file has (board 5.3): Maku never writes over it, so this one gets "(2)" beside
 * it, unless the owner skips it this time and it stays where it is, with its subtitles. Comparing
 * the two shows which is which.
 */
function Taken(props: { change: ProposedChange; skipped: boolean; onSkip: (on: boolean) => void }) {
  const { change } = props;
  const [comparing, setComparing] = useState(false);
  const there = change.compared?.there?.path ?? unnumbered(change.target);
  return (
    <fieldset
      aria-label="Name already taken"
      className="mt-1.5 flex flex-col gap-3 rounded-20 border border-tint/10 bg-raised p-4.5"
    >
      <span className="font-extrabold text-14">
        {props.skipped
          ? "Skipped: it stays where it is this time"
          : "A file with this name is already there"}
      </span>
      <span className="font-mono text-12 text-fg-muted [overflow-wrap:anywhere]">
        {within(there, change.root)}
      </span>
      <div className="flex flex-wrap gap-2">
        {change.compared && (
          <Button
            size="sm"
            variant="primary"
            aria-expanded={comparing}
            onClick={() => setComparing(!comparing)}
          >
            Compare the two
          </Button>
        )}
        <Button size="sm" aria-pressed={!props.skipped} onClick={() => props.onSkip(false)}>
          Keep both
        </Button>
        <Button
          size="sm"
          variant="ghost"
          aria-pressed={props.skipped}
          onClick={() => props.onSkip(true)}
        >
          Skip
        </Button>
      </div>
      {comparing && change.compared && (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
          {change.compared.there ? (
            <CopyCard
              copy={change.compared.there}
              heading="Already there"
              note={THERE_GOES[change.compared.thereGoes]}
            />
          ) : (
            <p className="rounded-16 border border-edge bg-tint/3 p-4 text-12 text-fg-muted">
              Maku doesn't know the file that's there: it isn't in your library.
            </p>
          )}
          <CopyCard
            copy={change.compared.coming}
            heading="This one"
            note={props.skipped ? "Stays where it is" : "Gets (2)"}
          />
        </div>
      )}
      <span className="text-12 text-fg-faint">
        Maku never overwrites a file. Keep both adds (2) to the new one.
      </span>
    </fieldset>
  );
}

/** What the file at a taken name does in the same tidy-up, as the comparison says it. */
const THERE_GOES = {
  stays: "Stays as it is",
  leaves: "Moves in this tidy-up",
  arrives: "Filed there in this tidy-up",
} as const;

/** The name a "(2)" was added to: "Ep 05 (2).mkv" wanted "Ep 05.mkv". */
function unnumbered(path: string): string {
  return path.replace(/ \(\d+\)(\.[^.\\/]+)$/, "$1");
}

function Copies(props: {
  duplicate: Duplicate;
  withEnglish: boolean;
  onEnglish: (on: boolean) => void;
  onSwap: () => void;
}) {
  const { duplicate } = props;
  const [dropped] = duplicate.drop;
  if (!dropped) return null;
  const { english } = duplicate;
  return (
    <section
      aria-label={`Copies of ${duplicate.label}`}
      className="flex flex-col gap-4 rounded-22 border border-edge bg-glass p-5 shadow-panel"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="font-extrabold text-16">
          {duplicate.drop.length === 1 ? "Two copies" : `${duplicate.drop.length + 1} copies`} of{" "}
          {duplicate.label}
        </h2>
        <span className="text-12 text-fg-muted">Maku keeps the better one</span>
      </div>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
        <CopyCard copy={duplicate.keep} heading="Keep" note="Better" kept />
        {duplicate.drop.map((copy) => (
          <CopyCard
            key={copy.path}
            copy={copy}
            heading={duplicate.drop.length === 1 ? "The other copy" : "Another copy"}
            note="Set aside"
            english={english?.other === copy.path ? english : null}
          />
        ))}
      </div>
      {english && (
        <EnglishChoice english={english} on={props.withEnglish} onChange={props.onEnglish} />
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {english ? (
          <span className="text-12 text-fg-faint">
            {english.tried
              ? `Maku tried before: ${english.tried}`
              : "If the two aren't the same cut, the English won't line up: Maku says so and keeps the copies as they are."}
          </span>
        ) : (
          <span className="text-13 text-fg-muted">{duplicate.reason}</span>
        )}
        <Button size="sm" onClick={props.onSwap}>
          Swap which one is kept
        </Button>
      </div>
    </section>
  );
}

/** The other copy has English the one kept hasn't: added to it, or set aside with the copy. */
function EnglishChoice(props: { english: English; on: boolean; onChange: (on: boolean) => void }) {
  const what = [props.english.sound && "sound", props.english.subtitles && "subtitles"]
    .filter(Boolean)
    .join(" and ");
  const choices = [
    {
      value: "english",
      title: "Keep the better picture, with the other's English",
      says: `Maku adds its English ${what} to the copy kept, lining them up with this picture by listening to both. It checks the result before it takes the file's place, then sets the other copy aside as usual.`,
    },
    {
      value: "as-is",
      title: "Keep the better one as it is",
      says: "The other copy goes to quarantine with its English.",
    },
  ];
  const value = props.on ? "english" : "as-is";
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-2 font-extrabold text-13 text-fg-soft">
        The other copy has English this one hasn't
      </legend>
      <RadioGroup.Root
        aria-label="The other copy's English"
        value={value}
        onValueChange={(chosen) => props.onChange(chosen === "english")}
        className="flex flex-col gap-2"
      >
        {choices.map((choice) => (
          <RadioGroup.Item
            key={choice.value}
            value={choice.value}
            aria-label={choice.title}
            className={cn(
              "press flex cursor-pointer items-start gap-3 rounded-16 border-2 px-4 py-3.5 text-left",
              choice.value === value ? "border-accent bg-accent/8" : "border-edge bg-tint/3",
            )}
          >
            <Dot on={choice.value === value} />
            <span className="flex flex-col gap-0.5">
              <span className="font-extrabold">{choice.title}</span>
              <span className="text-13 text-fg-muted">{choice.says}</span>
            </span>
          </RadioGroup.Item>
        ))}
      </RadioGroup.Root>
    </fieldset>
  );
}

function Dot({ on }: { on: boolean }) {
  return on ? (
    <span
      aria-hidden="true"
      className="mt-px inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-accent"
    >
      <span className="size-2 rounded-full bg-on-accent" />
    </span>
  ) : (
    <span
      aria-hidden="true"
      className="mt-px size-5 shrink-0 rounded-full shadow-[inset_0_0_0_2px_var(--color-control)]"
    />
  );
}

function CopyCard(props: {
  copy: CopyFacts;
  heading: string;
  note: string;
  kept?: boolean;
  /** What of this copy's English would go into the one kept: marked. */
  english?: English | null;
}) {
  const { copy } = props;
  const [name] = split(copy.path);
  const files = useFileActions();
  return (
    <div
      className={cn(
        "flex flex-col gap-2.5 rounded-16 border p-4",
        props.kept ? "border-accent/50 bg-accent/6" : "border-edge bg-tint/3",
      )}
    >
      <span className="flex items-center justify-between gap-2">
        <span className="font-extrabold text-13">{props.heading}</span>
        {props.kept ? (
          <span className="rounded-full bg-accent px-2 font-extrabold text-11 text-on-accent">
            {props.note}
          </span>
        ) : (
          <span className="text-11 text-fg-muted">{props.note}</span>
        )}
      </span>
      <span className="flex items-start gap-1">
        <span className="min-w-0 flex-1 pt-1.5 font-mono text-12 [overflow-wrap:anywhere]">
          {name}
        </span>
        <span className="-mr-2">
          <RowMenu label={`More for ${name}`}>
            <FileMenuItems path={copy.path} actions={files} />
          </RowMenu>
        </span>
      </span>
      <FileNote actions={files} />
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-12">
        <dt className="text-fg-muted">Picture</dt>
        <dd className="font-mono">
          {copy.plays && copy.height
            ? `${copy.height}p${copy.codec ? ` · ${codecName(copy.codec)}` : ""}`
            : "won't play"}
        </dd>
        <dt className="text-fg-muted">Sound</dt>
        <dd className="font-mono">
          <Languages codes={copy.audio} marked={props.english?.sound ?? false} />
        </dd>
        <dt className="text-fg-muted">Subtitles</dt>
        <dd className="font-mono">
          <Languages codes={copy.subtitleLanguages} marked={props.english?.subtitles ?? false} />
        </dd>
        <dt className="text-fg-muted">Size</dt>
        <dd className="font-mono">{size(copy.size)}</dd>
      </dl>
    </div>
  );
}

/** "Japanese, English", English marked in amber when it's what goes into the copy kept. */
function Languages({ codes, marked }: { codes: string[]; marked: boolean }) {
  if (codes.length === 0) return <>none</>;
  return (
    <>
      {codes.map((code, at) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: a language may come twice
        <Fragment key={at}>
          {at > 0 && ", "}
          {marked && isEnglish(code) ? (
            <strong className="font-extrabold text-accent-fg">{languageName(code)}</strong>
          ) : (
            languageName(code)
          )}
        </Fragment>
      ))}
    </>
  );
}

function Staying({ skipped }: { skipped: { path: string; reason: string }[] }) {
  return (
    <section
      aria-labelledby="staying-title"
      className="flex animate-fade-up flex-col gap-2.5 rounded-22 border border-rule bg-tint/3 px-5.5 py-5"
    >
      <h2 id="staying-title" className="font-extrabold text-15">
        Staying where they are
      </h2>
      <ul className="flex flex-col">
        {skipped.map((file) => (
          <li
            key={file.path}
            className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-rule border-b py-2 text-12 last:border-b-0"
          >
            <span className="font-mono [overflow-wrap:anywhere]">{split(file.path)[0]}</span>
            <span className="text-fg-muted">{file.reason}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function reviewed({ source, kind, target }: ProposedChange): ReviewedChange {
  return { source, kind, target };
}

/** The changes, a title at a time, in the order Maku proposes them. */
function byTitle(changes: ProposedChange[]): [number, ProposedChange[]][] {
  const groups = new Map<number, ProposedChange[]>();
  for (const change of changes) {
    groups.set(change.titleId, [...(groups.get(change.titleId) ?? []), change]);
  }
  return [...groups];
}

function applyText(count: number): string {
  return count === 0 ? "Nothing selected" : `Apply ${count} ${count === 1 ? "change" : "changes"}`;
}
