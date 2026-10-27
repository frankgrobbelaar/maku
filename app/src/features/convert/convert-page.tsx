import { Check } from "lucide-react";
import { RadioGroup } from "radix-ui";
import { Fragment, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { CheckBox } from "@/components/check-box";
import { EmptyState, ShelfIllustration } from "@/components/empty-state";
import { EngineProblem } from "@/components/engine-problem";
import { NoMatches, SearchField, useAddressSearch } from "@/components/search-field";
import { Loading, PanelSkeleton } from "@/components/skeleton";
import { STANDARDS } from "@/components/standard-choices";
import { GuessNote, NoEncoder } from "@/components/this-pc";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import {
  fitting,
  type GroupNode,
  gpuTime,
  nights,
  ORIGINALS,
  open,
  playTime,
  type SeasonNode,
  type TitleNode,
  totals,
  tree,
} from "@/lib/convert";
import {
  type Convertible,
  type Settings,
  type System,
  useAddToQueue,
  useConvertOptions,
  useEmptyQuarantine,
  useFranchises,
  useQueue,
  useSaveSettings,
  useSettings,
  useSystem,
} from "@/lib/engine";
import { size } from "@/lib/format";
import { idsIn } from "@/lib/ids";
import { matches } from "@/lib/search";
import { cn } from "@/lib/utils";
import { ConvertTabs, Step } from "./convert-tabs";
import { NoRoom } from "./no-room";
import { SeeItFirst } from "./see-it-first";

type When = "now" | "nights" | "after";

/** The encoder this PC converts with, as How names it. */
const ENCODERS: Record<NonNullable<System["encoder"]>, string> = {
  nvenc: "NVIDIA NVENC encoder",
  amf: "AMD AMF encoder",
  qsv: "Intel Quick Sync encoder",
};

const REASONS_SHOWN = 6; // the most common reasons How lists, of what the files get

/** Convert: pick what to convert, see what it takes, then queue it. */
export function ConvertPage() {
  const navigate = useNavigate();
  const options = useConvertOptions();
  const franchises = useFranchises();
  const queue = useQueue();
  const system = useSystem();
  const add = useAddToQueue();
  const empty = useEmptyQuarantine();
  const stored = useSettings();
  const save = useSaveSettings();
  const settings = stored.data;
  // The standard and what becomes of originals are the library's settings, chosen here as in
  // Settings: the estimates follow at once.
  const change = (part: Partial<Settings>) =>
    settings && save.mutate({ path: "/settings", body: { ...settings, ...part } });
  // Opened from a title's ticked videos (`?files=4,5,6`), those start chosen.
  const [params] = useSearchParams();
  const [selected, setSelected] = useState<Set<number>>(() => new Set(idsIn(params.get("files"))));
  const [when, setWhen] = useState<When | null>(null);
  const [asking, setAsking] = useState(false); // about a drive without room for the choice

  const header = (
    <header className="page-top flex animate-fade-up flex-wrap items-end justify-between gap-4">
      <div className="flex max-w-xl flex-col gap-1.5">
        <h1 className="type-title">Convert</h1>
        <p className="text-14 text-fg-muted">
          Pick what to convert, see what it takes, then queue it.
        </p>
      </div>
      <ConvertTabs queued={queue.data ? queue.data.queued.length : null} />
    </header>
  );
  if (!options.data || !franchises.data) {
    return (
      <>
        {header}
        <EngineProblem queries={[options, franchises]} />
        <Loading label="Loading what can be converted" queries={[options, franchises]}>
          <div className="flex flex-wrap items-stretch gap-5">
            <PanelSkeleton rows={7} className="flex-[1_1_380px]" />
            <PanelSkeleton rows={4} className="flex-[999_1_520px]" />
          </div>
          <div className="flex flex-wrap items-stretch gap-5">
            <PanelSkeleton rows={2} className="flex-[1_1_380px]" />
            <PanelSkeleton rows={2} className="flex-[1_1_380px]" />
          </div>
        </Loading>
      </>
    );
  }
  if (system.data?.checkedAt && system.data.encoder === null) {
    return (
      <>
        {header}
        <NoEncoder system={system.data} />
      </>
    );
  }
  const files = options.data.files;
  if (files.length === 0) {
    return (
      <>
        {header}
        <EmptyState
          title="Everything is at your standard"
          illustration={<ShelfIllustration />}
          action={
            settings && (
              <StandardPick settings={settings} onChange={(standard) => change({ standard })} />
            )
          }
          note="Choose the other, and what's over it can be converted to it, Maku's own conversions too."
        >
          Every video in your library is at your standard already: HEVC 10-bit in MKV, none over{" "}
          {options.data.standard}. New ones show up here when a scan finds them.
        </EmptyState>
        {save.isError && <Unsaved message={save.error.message} />}
      </>
    );
  }
  const groups = tree(files, franchises.data);
  const chosen = open(files).filter((file) => selected.has(file.fileId));
  const timing = (when ?? (queue.data?.schedule === "nights" ? "nights" : "now")) as When;

  function toggle(node: Convertible[]) {
    setAsking(false); // a new choice is asked about afresh
    const ids = open(node).map((file) => file.fileId);
    setSelected((before) => {
      const next = new Set(before);
      const all = ids.every((id) => next.has(id));
      for (const id of ids) {
        if (all) next.delete(id);
        else next.add(id);
      }
      return next;
    });
  }

  function queueChosen(fit: string[] = []) {
    const body = { files: chosen.map((file) => file.fileId), when: timing, fit };
    add.mutate({ path: "/queue", body }, { onSuccess: () => void navigate("/convert/queue") });
  }

  const deleting = settings?.originals === "delete";
  const short = shortage(chosen, options.data.free, options.data.setAside, deleting);
  const room = asking && short && (
    <NoRoom
      drive={short.drive}
      waiting={short.files}
      needed={short.needed}
      free={short.free}
      fit={short.fit}
      setAside={short.setAside}
      busy={add.isPending || empty.isPending}
      problem={empty.error ?? add.error}
      onEmpty={() =>
        empty.mutate(
          { path: "/quarantine/empty", body: { drive: short.drive } },
          { onSuccess: () => queueChosen() },
        )
      }
      onFit={() => queueChosen([short.drive])}
      onBack={() => setAsking(false)}
    />
  );

  return (
    <>
      {header}
      <EngineProblem queries={[options, franchises]} />
      <div className="flex flex-wrap items-stretch gap-5">
        <What groups={groups} selected={selected} chosen={chosen} onToggle={toggle} />
        <How
          standard={options.data.standard}
          settings={settings}
          onStandard={(standard) => change({ standard })}
          basis={chosen.length > 0 ? chosen : open(files)}
          chosen={chosen.length > 0}
          system={system.data}
        />
      </div>
      <SeeItFirst n={3} file={chosen[0] ?? open(files)[0] ?? null} />
      <div className="flex flex-wrap items-stretch gap-5">
        <Estimate
          chosen={chosen}
          system={system.data}
          free={options.data.free}
          settings={settings}
          onOriginals={(originals) => change({ originals })}
        />
        <WhenPanel
          when={timing}
          onWhen={setWhen}
          count={chosen.length}
          episodes={chosen.every((file) => file.episode !== null)}
          busy={add.isPending}
          onQueue={() => (short ? setAsking(true) : queueChosen())}
          problem={room ? null : (add.error?.message ?? null)}
          room={room || null}
        />
      </div>
      {save.isError && <Unsaved message={save.error.message} />}
    </>
  );
}

function Unsaved({ message }: { message: string }) {
  return (
    <p role="alert" className="text-13 text-broken-fg">
      Maku couldn't save that: {message}
    </p>
  );
}

/**
 * The library's standard, which every file is brought to: the same choice as Settings', here
 * where converting starts. Changed, what's at the old one can be converted again.
 */
function StandardPick(props: {
  settings: Settings;
  onChange: (standard: Settings["standard"]) => void;
}) {
  return (
    <Segmented
      label="Your standard"
      value={props.settings.standard}
      options={STANDARDS.map((each) => ({ value: each.value, label: each.name }))}
      onChange={props.onChange}
    />
  );
}

function What(props: {
  groups: GroupNode[];
  selected: Set<number>;
  chosen: Convertible[];
  onToggle: (files: Convertible[]) => void;
}) {
  const [query, setQuery] = useAddressSearch();
  const sum = totals(props.chosen);
  const titles = props.groups.reduce((total, group) => total + group.titles.length, 0);
  const found = searched(props.groups, query);
  const rows = found.flatMap((group) =>
    group.titles.length > 1
      ? [
          <TreeRow
            key={group.key}
            level={0}
            name={group.name}
            meta="collection"
            files={group.files}
            {...props}
          />,
          ...group.titles.flatMap((title) => titleRows(title, 1, props)),
        ]
      : group.titles.flatMap((title) => titleRows(title, 0, props)),
  );
  return (
    <Step n={1} id="what-title" title="What" className="flex-[1_1_380px]">
      {(titles > 1 || query) && (
        <SearchField
          value={query}
          onChange={setQuery}
          label="Search what to convert"
          placeholder={`Search ${titles} titles`}
        />
      )}
      {found.length === 0 ? (
        <NoMatches>No title goes by “{query.trim()}”.</NoMatches>
      ) : (
        <div className="flex max-h-[28rem] flex-col overflow-y-auto text-14">{rows}</div>
      )}
      <div className="mt-auto flex flex-wrap gap-2">
        {props.chosen.length === 0 ? (
          <Chip>Nothing chosen yet</Chip>
        ) : (
          <>
            <Chip>
              {count(
                props.chosen.length,
                props.chosen.every((file) => file.episode !== null) ? "episode" : "file",
              )}
            </Chip>
            <Chip>{playTime(sum.seconds)} of video</Chip>
            <Chip>{sum.sources}</Chip>
          </>
        )}
      </div>
    </Step>
  );
}

/** What a search finds: a collection by its name, whole, or else the titles in it found by
 * theirs, each on its own. */
function searched(groups: GroupNode[], query: string): GroupNode[] {
  return groups.flatMap((group) => {
    if (matches(query, group.name)) return [group];
    return group.titles
      .filter((title) => matches(query, title.name))
      .map((title) => ({ key: title.key, name: title.name, titles: [title], files: title.files }));
  });
}

function titleRows(
  title: TitleNode,
  level: number,
  props: { selected: Set<number>; onToggle: (files: Convertible[]) => void },
) {
  return [
    <TreeRow
      key={title.key}
      level={level}
      name={title.name}
      meta={left(title.files)}
      files={title.files}
      {...props}
    />,
    ...(title.seasons.length > 1
      ? compact(title.seasons).map((season) => (
          <TreeRow
            key={`${title.key}-${season.key}`}
            level={level + 1}
            name={season.label}
            meta={count(open(season.files).length, "episode")}
            files={season.files}
            {...props}
          />
        ))
      : []),
  ];
}

/** A title's seasons, the first two on their own and the rest together: "Seasons 3 to 9". */
function compact(seasons: SeasonNode[]): SeasonNode[] {
  const numbered = seasons.filter((season) => season.key.startsWith("s") && season.key !== "s0");
  if (numbered.length <= 3) return seasons;
  const [first, second, ...rest] = numbered;
  const others = seasons.filter((season) => !numbered.includes(season));
  const label = `Seasons ${rest[0]?.label.replace("Season ", "")} to ${rest.at(-1)?.label.replace("Season ", "")}`;
  const together = { key: "rest", label, files: rest.flatMap((season) => season.files) };
  return [first, second, together, ...others].filter(
    (season): season is SeasonNode => season !== undefined,
  );
}

/** "283 left", "62 left, 2 broken skipped", "all in the queue". */
function left(files: Convertible[]): string {
  const ready = open(files).length;
  const broken = files.filter((file) => file.broken).length;
  if (ready === 0 && broken === 0) return "all in the queue";
  return [`${ready} left`, broken > 0 && `${broken} broken skipped`].filter(Boolean).join(", ");
}

function TreeRow(props: {
  level: number;
  name: string;
  meta: string;
  files: Convertible[];
  selected: Set<number>;
  onToggle: (files: Convertible[]) => void;
}) {
  const ids = open(props.files).map((file) => file.fileId);
  const picked = ids.filter((id) => props.selected.has(id)).length;
  const state = ids.length > 0 && picked === ids.length ? true : picked > 0 ? "mixed" : false;
  const indent = ["pl-2", "pl-9", "pl-16"][props.level] ?? "pl-16";
  return (
    <label
      className={cn(
        "press flex min-h-11 cursor-pointer items-center gap-3 rounded-12 pr-2 has-disabled:cursor-default has-disabled:opacity-50",
        indent,
        props.level === 0 ? "font-extrabold" : "font-bold",
        state === true ? "bg-accent/8 text-fg" : state === "mixed" ? "text-fg" : "text-fg-soft",
      )}
    >
      <input
        type="checkbox"
        checked={state === true}
        ref={(box) => {
          if (box) box.indeterminate = state === "mixed";
        }}
        disabled={ids.length === 0}
        onChange={() => props.onToggle(props.files)}
        className="peer sr-only"
      />
      <CheckBox state={state} />
      <span className="min-w-0 truncate">{props.name}</span>
      <span
        className={cn(
          "ml-auto shrink-0 font-semibold text-12",
          state === true && props.level > 0 ? "text-accent-fg" : "text-fg-muted",
        )}
      >
        {props.meta}
      </span>
    </label>
  );
}

function How(props: {
  standard: string;
  settings: Settings | undefined;
  onStandard: (standard: Settings["standard"]) => void;
  /** What's chosen, or else everything, for what the files get. */
  basis: Convertible[];
  /** `basis` is the choice. */
  chosen: boolean;
  system: System | undefined;
}) {
  const spec = STANDARDS.find((each) => each.value === props.settings?.standard)?.spec;
  const reasons = reasonsOf(props.basis);
  const encoder = props.system?.encoder;
  const timed = props.basis.filter((file) => !file.broken);
  const each =
    timed.length > 0 ? timed.reduce((sum, file) => sum + file.gpuSeconds, 0) / timed.length : null;
  return (
    <Step
      n={2}
      id="how-title"
      title="How"
      note={props.settings ? undefined : `To your standard: ${props.standard}`}
      className="flex-[999_1_520px]"
    >
      {props.settings && (
        <div className="flex flex-col gap-2.5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="flex flex-col">
              <span className="font-bold text-14">Your standard</span>
              {spec && <span className="font-mono text-12 text-fg-muted">{spec}</span>}
            </span>
            <StandardPick settings={props.settings} onChange={props.onStandard} />
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-12">
            {STANDARDS.map((standard) => {
              const on = standard.value === props.settings?.standard;
              return (
                <Fragment key={standard.value}>
                  <dt className={cn("font-extrabold", on ? "text-accent-fg" : "text-fg-muted")}>
                    {standard.name}
                  </dt>
                  <dd className={on ? "text-fg-soft" : "text-fg-faint"}>{standard.text}</dd>
                </Fragment>
              );
            })}
          </dl>
          <span className="text-12 text-fg-faint">
            Change it, and what's over the new one can be converted again, Maku's own conversions
            too.
          </span>
        </div>
      )}
      {reasons.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="font-bold text-14">
            {props.chosen ? "What they get" : "What the files get"}
          </span>
          <ul className="flex flex-col gap-1.5 text-13">
            {reasons.map(([reason, n]) => (
              <li key={reason} className="flex items-baseline gap-3">
                <span className="w-9 shrink-0 text-right font-mono text-12 text-accent-fg">
                  {n}
                </span>
                <span className="text-fg-soft">{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <span className="mt-auto text-12 text-fg-faint">
        {encoder ? `Made on the ${ENCODERS[encoder]}` : "Made on the graphics card's encoder"}
        {each !== null ? `, about ${gpuTime(each)} a file` : ""}. Every sound track stays as it is,
        and so do subtitles, fonts and chapters.
      </span>
    </Step>
  );
}

/** Why the files get what they get, the most common first: each reason with how many files. */
function reasonsOf(files: Convertible[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const file of files) {
    for (const reason of file.reasons) counts.set(reason, (counts.get(reason) ?? 0) + 1);
  }
  return [...counts].sort((a, b) => b[1] - a[1]).slice(0, REASONS_SHOWN);
}

/**
 * The drive without room for what's chosen, as converting it in turn would find it, with what
 * waits there and what its quarantine would free; null when there's room on every drive.
 */
function shortage(
  chosen: Convertible[],
  free: Record<string, number>,
  setAside: Record<string, number>,
  deleting: boolean,
) {
  for (const [drive, files] of byDrive(chosen)) {
    const room = free[drive];
    if (room === undefined) continue; // not connected: it waits for the drive instead
    const { needed, fit } = fitting(
      files.map((file) => ({ output: file.outputBytes, original: file.size })),
      room,
      deleting,
    );
    if (fit === files.length) continue;
    const aside = Object.entries(setAside).find(([d]) => d.toUpperCase() === drive.toUpperCase());
    return { drive, files, needed, free: room, fit, setAside: aside?.[1] ?? 0 };
  }
  return null;
}

function Estimate(props: {
  chosen: Convertible[];
  system: System | undefined;
  free: Record<string, number>;
  settings: Settings | undefined;
  onOriginals: (originals: Settings["originals"]) => void;
}) {
  const days = props.settings?.quarantineDays;
  const deleting = props.settings?.originals === "delete";
  const sum = totals(props.chosen);
  const [drive, needed] = spaceToShow(needs(props.chosen, deleting), props.free);
  const each = props.chosen.every((file) => file.episode !== null) ? "episode" : "file";
  const free = props.free[drive] ?? null;
  const enough = free === null || free >= needed;
  const system = props.system;
  const card = system?.graphicsCard;
  return (
    <Step
      n={4}
      id="estimate-title"
      title="Estimate"
      note={system?.measured ? `Measured on this PC${card ? ` · ${card}` : ""}` : undefined}
      className="flex-[999_1_520px]"
    >
      <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2.5">
        <Tile
          label="GPU time"
          value={sum.files > 0 ? `≈ ${gpuTime(sum.gpuSeconds)}` : "–"}
          note={sum.files > 0 ? nights(sum.gpuSeconds) : "nothing chosen yet"}
        />
        <Tile
          label="Size"
          value={sum.files > 0 ? `${size(sum.sizeBefore)} → ${size(sum.sizeAfter)}` : "–"}
          note={sum.files > 0 ? `≈ ${size(sum.sizeAfter / sum.files)} per ${each}` : "nothing yet"}
        />
        <Tile
          label={`Space on ${drive}`}
          value={
            <>
              {free === null ? "?" : size(free)}
              {free !== null && enough && (
                <Check size={18} strokeWidth={3} aria-hidden="true" className="text-accent-fg" />
              )}
            </>
          }
          note={
            free === null
              ? "the drive isn't connected"
              : enough
                ? "free, plenty for this"
                : `free: not enough, this needs ${size(needed)}`
          }
          warn={!enough}
        />
        <div className="flex flex-col gap-1.5 rounded-16 bg-tint/4 px-4 py-3.5">
          <span className="text-12 text-fg-muted">Originals</span>
          <span className="font-extrabold text-24 leading-[1.1]">
            {deleting ? "Deleted" : days === null ? "Kept for good" : `Kept ${days ?? 30} days`}
          </span>
          <span className={cn("text-12", deleting ? "text-broken-fg" : "text-fg-muted")}>
            {deleting
              ? "for good, once each result is checked and in place: no putting back"
              : "in quarantine, after each check"}
          </span>
          {props.settings && (
            <Segmented
              label="Originals, once each result is checked"
              value={props.settings.originals}
              options={ORIGINALS}
              onChange={props.onOriginals}
              className="mt-1 self-start"
            />
          )}
        </div>
      </div>
      {system && !system.measured && <GuessNote system={system} />}
    </Step>
  );
}

/**
 * The free space what's chosen wants on each drive it's on, as converting it in turn would find
 * it (with the margin converting keeps): less when originals are deleted as results go in.
 */
function needs(chosen: Convertible[], deleting: boolean): Record<string, number> {
  return Object.fromEntries(
    [...byDrive(chosen)].map(([drive, files]) => [
      drive,
      fitting(
        files.map((file) => ({ output: file.outputBytes, original: file.size })),
        Number.POSITIVE_INFINITY,
        deleting,
      ).needed,
    ]),
  );
}

/** What's chosen, by the drive each file is on. */
function byDrive(chosen: Convertible[]): Map<string, Convertible[]> {
  const found = new Map<string, Convertible[]>();
  for (const file of chosen) found.set(file.drive, [...(found.get(file.drive) ?? []), file]);
  return found;
}

/**
 * The drive the space tile speaks for, and the space it wants: one without room for what's
 * chosen, else one that isn't connected, else the one wanting the most.
 */
function spaceToShow(
  wanted: Record<string, number>,
  free: Record<string, number>,
): [string, number] {
  const drives = Object.entries(wanted).sort((a, b) => b[1] - a[1]);
  return (
    drives.find(([drive, needed]) => (free[drive] ?? Infinity) < needed) ??
    drives.find(([drive]) => free[drive] === undefined) ??
    drives[0] ?? [Object.keys(free)[0] ?? "", 0]
  );
}

function Tile(props: { label: string; value: React.ReactNode; note: string; warn?: boolean }) {
  return (
    <div className="flex flex-col gap-1 rounded-16 bg-tint/4 px-4 py-3.5">
      <span className="text-12 text-fg-muted">{props.label}</span>
      <span className="flex items-center gap-2 font-extrabold text-24 leading-[1.1]">
        {props.value}
      </span>
      <span className={cn("text-12", props.warn ? "text-broken-fg" : "text-fg-muted")}>
        {props.note}
      </span>
    </div>
  );
}

function WhenPanel(props: {
  when: When;
  onWhen: (when: When) => void;
  count: number;
  episodes: boolean;
  busy: boolean;
  onQueue: () => void;
  problem: string | null;
  /** Not enough space for the choice: the ways on from there, instead of adding. */
  room: React.ReactNode;
}) {
  const choices: { when: When; label: string; note?: string }[] = [
    { when: "now", label: "Start now" },
    { when: "nights", label: "Nights only", note: "23:00–07:00" },
    { when: "after", label: "After the current queue" },
  ];
  const what = props.episodes ? "episode" : "file";
  return (
    <Step n={5} id="when-title" title="When" className="flex-[1_1_380px]">
      <RadioGroup.Root
        aria-label="When to convert"
        value={props.when}
        onValueChange={(value) => props.onWhen(value as When)}
        className="flex flex-col gap-1.5"
      >
        {choices.map((choice) => {
          const on = props.when === choice.when;
          return (
            <RadioGroup.Item
              key={choice.when}
              value={choice.when}
              className={cn(
                "press flex min-h-11 cursor-pointer items-center gap-3 rounded-14 px-3 text-left",
                on ? "bg-accent/10 font-extrabold text-fg" : "font-bold text-fg-soft",
              )}
            >
              <Dot on={on} />
              {choice.label}
              {choice.note && (
                <span className="ml-auto font-medium font-mono text-12 text-accent-fg">
                  {choice.note}
                </span>
              )}
            </RadioGroup.Item>
          );
        })}
      </RadioGroup.Root>
      {props.problem && (
        <p role="alert" className="text-13 text-broken-fg">
          {props.problem}
        </p>
      )}
      {props.room ?? (
        <Button
          variant="primary"
          className="mt-auto min-h-12 w-full"
          disabled={props.count === 0 || props.busy}
          onClick={props.onQueue}
        >
          {props.count === 0
            ? "Choose what to convert"
            : `Add ${count(props.count, what)} to the queue`}
        </Button>
      )}
    </Step>
  );
}

function Dot({ on }: { on: boolean }) {
  return on ? (
    <span
      aria-hidden="true"
      className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-accent"
    >
      <span className="size-2 rounded-full bg-on-accent" />
    </span>
  ) : (
    <span
      aria-hidden="true"
      className="size-5 shrink-0 rounded-full shadow-[inset_0_0_0_2px_var(--color-control)]"
    />
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex h-7 items-center rounded-full bg-tint/6 px-3 font-bold text-12">
      {children}
    </span>
  );
}

function count(n: number, one: string): string {
  return `${n} ${n === 1 ? one : `${one}s`}`;
}
