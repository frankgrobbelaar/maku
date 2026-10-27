import { Captions, Download } from "lucide-react";
import { RadioGroup } from "radix-ui";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { Breadcrumb, LIBRARY } from "@/components/breadcrumb";
import { CheckBox } from "@/components/check-box";
import { EngineProblem } from "@/components/engine-problem";
import { Loading, PanelSkeleton } from "@/components/skeleton";
import { gigabytes } from "@/components/this-pc";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { nights } from "@/lib/convert";
import {
  type Hearable,
  type Quality,
  SPEECH_MODELS,
  type System,
  type Tool,
  useDownloadTool,
  useMakeSubtitles,
  useQueue,
  useSubtitleOptions,
  useSystem,
  useTools,
} from "@/lib/engine";
import { isEnglish, languageName, size } from "@/lib/format";
import { idsIn } from "@/lib/ids";
import { cn } from "@/lib/utils";

type Scope = "ticked" | "season" | "title" | "everything";
type When = "now" | "nights" | "after";

const QUALITIES: { quality: Quality; name: string; says: string }[] = [
  { quality: "best", name: "Best", says: "The larger model. Closest to what's said." },
  { quality: "fast", name: "Fast", says: "A smaller model. Rougher, good for a quick watch." },
];

const WHEN: { value: When; label: string }[] = [
  { value: "now", label: "Start now" },
  { value: "nights", label: "Nights only" },
  { value: "after", label: "After the queue" },
];

/** Why Best can't run here: "Wants a graphics card with 4 GB of its own memory; this one has 2 GB." */
function wanting(system: System | undefined): string {
  if (system?.subtitles.bestWants === "directx") {
    return "Wants a graphics card that runs DirectX 12; this one doesn't.";
  }
  const card = system?.card;
  const has = !card
    ? "this PC has none"
    : card.integrated || card.memory === null
      ? "this PC's graphics share its memory"
      : `this one has ${gigabytes(card.memory)}`;
  return `Wants a graphics card with 4 GB of its own memory; ${has}.`;
}

/** About what a subtitle file takes beside a video, for each second it plays. */
const BYTES_A_SECOND = 20;

/**
 * Make English subtitles: which videos (a season, a title, or everything without English), from
 * which of their sound, at which quality and when, and what that takes; then they join the queue
 * with the conversions. Opened from a title's videos (`?title=7&season=1`), or from Home.
 */
export function MakeSubtitlesPage() {
  const [params] = useSearchParams();
  const titleId = Number(params.get("title")) || null;
  const asked = params.get("season");
  // Opened from a title's ticked videos (`&files=4,5,6`): those, as one choice.
  const ticked = idsIn(params.get("files"));
  const season = asked === null || Number.isNaN(Number(asked)) ? null : Number(asked);
  const navigate = useNavigate();
  const options = useSubtitleOptions();
  const tools = useTools();
  const queue = useQueue();
  const system = useSystem();
  const make = useMakeSubtitles();
  const download = useDownloadTool();
  const [scope, setScope] = useState<Scope | null>(null);
  const [also, setAlso] = useState(false);
  const [language, setLanguage] = useState<string | null>(null);
  const [pickedQuality, setQuality] = useState<Quality | null>(null);
  // Best wants a card with 4 GB of its own: on a PC without one, Fast is right.
  const bestHere = system.data?.subtitles.best !== null;
  const quality: Quality = pickedQuality ?? (bestHere ? "best" : "fast");
  const [when, setWhen] = useState<When | null>(null);
  const [needsModel, setNeedsModel] = useState(false); // asking to download the model first

  const all = options.data?.files ?? [];
  const mine = all.filter((file) => file.titleId === titleId);
  const name = mine[0]?.title ?? null;
  const scopes = scopesFor(all, mine, name, season, ticked);
  const chosen = scopes.find((each) => each.scope === scope) ?? scopes[0];
  const trail = titleId && name ? [LIBRARY, { label: name, to: `/titles/${titleId}` }] : [LIBRARY];
  const top = <Breadcrumb trail={trail} current="Make English subtitles" />;

  if (!options.data || !chosen) {
    return (
      <>
        {top}
        <EngineProblem queries={[options]} />
        <Loading label="Loading the videos" queries={[options]}>
          <PanelSkeleton rows={8} className="mx-auto w-full max-w-160" />
        </Loading>
      </>
    );
  }
  const picked = chosen.files.filter((file) => !file.waiting && (also || !file.english));
  const sounds = byUse(picked.flatMap((file) => file.sound.filter(Boolean)));
  const from = language && sounds.includes(language) ? language : firstChoice(picked, sounds);
  const seconds = picked.reduce((sum, file) => sum + file.seconds, 0);
  const rate = options.data.rates[quality];
  const model = tools.data?.find((tool) => tool.id === SPEECH_MODELS[quality]);
  const timing: When = when ?? (queue.data?.schedule === "nights" ? "nights" : "now");
  const episodes = picked.every((file) => file.episode !== null);
  const what = `${picked.length} ${episodes ? "episode" : "video"}${picked.length === 1 ? "" : "s"}`;

  function queueThem() {
    const body = {
      fileIds: picked.map((file) => file.fileId),
      quality,
      language: from ?? "",
      title: chosen?.title ?? "",
      when: timing,
    };
    make.mutate({ path: "/subtitles", body }, { onSuccess: () => void navigate("/convert/queue") });
  }

  function start() {
    if (model && model.state !== "ready" && model.state !== "downloading") {
      setNeedsModel(true);
      return;
    }
    queueThem();
  }

  return (
    <>
      {top}
      <EngineProblem queries={[options, tools]} />
      <section
        aria-labelledby="make-title"
        className="mx-auto flex w-full max-w-160 animate-fade-up flex-col gap-5 rounded-28 border border-edge bg-glass p-7 shadow-panel"
      >
        <div className="flex items-center gap-3.5">
          <span
            aria-hidden="true"
            className="inline-flex size-12 shrink-0 items-center justify-center rounded-full bg-accent/14 text-accent-fg"
          >
            <Captions size={22} strokeWidth={1.9} />
          </span>
          <span className="flex flex-col">
            <h1 id="make-title" className="font-extrabold text-22 tracking-[-0.01em]">
              Make English subtitles
            </h1>
            <span className="text-13 text-fg-muted">{chosen.title}</span>
          </span>
        </div>
        <p className="text-fg-soft">
          Maku listens to each {episodes ? "episode" : "video"}'s own sound and writes English
          subtitles beside it, on this PC. The video itself never changes.
        </p>

        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 font-extrabold text-13 text-fg-soft">Which videos</legend>
          <RadioGroup.Root
            aria-label="Which videos"
            value={chosen.scope}
            onValueChange={(value) => setScope(value as Scope)}
            className="flex flex-col gap-2"
          >
            {scopes.map((each) => (
              <RadioGroup.Item
                key={each.scope}
                value={each.scope}
                className={cn(
                  "press flex cursor-pointer items-center gap-3 rounded-16 border-2 px-4 py-3 text-left",
                  each.scope === chosen.scope
                    ? "border-accent bg-accent/8"
                    : "border-edge bg-tint/3",
                )}
              >
                <Dot on={each.scope === chosen.scope} />
                <span className="flex-1 font-extrabold">{each.label}</span>
                <span className="text-13 text-fg-muted">{each.note(also)}</span>
              </RadioGroup.Item>
            ))}
          </RadioGroup.Root>
          <label className="press flex min-h-11 cursor-pointer items-center gap-3 px-1">
            <input
              type="checkbox"
              checked={also}
              onChange={(event) => setAlso(event.target.checked)}
              className="peer sr-only"
            />
            <CheckBox state={also} />
            <span className="flex flex-col">
              <span className="font-bold">Also the ones with English subtitles already</span>
              <span className="text-12 text-fg-muted">
                {also
                  ? "On: Maku makes its own for them too"
                  : "Off: what the files have is usually better"}
              </span>
            </span>
          </label>
        </fieldset>

        {sounds.length > 0 && from !== null && (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="flex flex-col">
              <span className="font-extrabold text-13 text-fg-soft">From the sound in</span>
              <span className="text-12 text-fg-muted">
                {isEnglish(from) ? "Maku writes down what's said" : "Maku translates from it"}
              </span>
            </span>
            <Segmented
              label="From the sound in"
              value={from}
              options={sounds
                .slice(0, 4)
                .map((code) => ({ value: code, label: languageName(code) }))}
              onChange={setLanguage}
              className="flex-wrap"
            />
          </div>
        )}

        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 font-extrabold text-13 text-fg-soft">Quality</legend>
          <RadioGroup.Root
            aria-label="Quality"
            value={quality}
            onValueChange={(value) => setQuality(value as Quality)}
            className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-2"
          >
            {QUALITIES.map((each) => {
              const on = each.quality === quality;
              const average = picked.length > 0 ? seconds / picked.length : 24 * 60;
              const no = each.quality === "best" && !bestHere;
              const chip =
                each.quality === "best"
                  ? bestHere && "Recommended"
                  : !bestHere && "Right for this PC";
              return (
                <RadioGroup.Item
                  key={each.quality}
                  value={each.quality}
                  disabled={no}
                  aria-label={each.name}
                  aria-describedby={`quality-${each.quality}`}
                  className={cn(
                    "press flex flex-col gap-1 rounded-16 border-2 px-4 py-3.5 text-left",
                    no
                      ? "cursor-default border-tint/14 border-dashed"
                      : on
                        ? "cursor-pointer border-accent bg-accent/8"
                        : "cursor-pointer border-edge bg-tint/3",
                  )}
                >
                  <span className="flex w-full items-center justify-between gap-2">
                    <span className={cn("font-extrabold", no && "text-fg-muted")}>{each.name}</span>
                    {no ? (
                      <span className="shrink-0 whitespace-nowrap rounded-10 px-2 font-extrabold text-11 text-fg-muted shadow-[inset_0_0_0_1.5px_var(--color-fg-faint)]">
                        {system.data?.card ? "Not on this card" : "Not on this PC"}
                      </span>
                    ) : (
                      chip && (
                        <span className="rounded-full bg-accent px-2 font-extrabold text-11 text-on-accent">
                          {chip}
                        </span>
                      )
                    )}
                  </span>
                  <span id={`quality-${each.quality}`} className="flex flex-col gap-1">
                    <span className="text-13 text-fg-muted">{each.says}</span>
                    {no ? (
                      <span className="text-12 text-fg-soft">{wanting(system.data)}</span>
                    ) : (
                      <span
                        className={cn("font-mono text-12", on ? "text-accent-fg" : "text-fg-muted")}
                      >
                        ≈ {minutes(average * options.data.rates[each.quality])} per{" "}
                        {episodes ? "episode" : "video"}
                        {!bestHere && " on this PC"}
                      </span>
                    )}
                  </span>
                </RadioGroup.Item>
              );
            })}
          </RadioGroup.Root>
        </fieldset>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="font-extrabold text-13 text-fg-soft">When</span>
          <Segmented
            label="When"
            value={timing}
            options={WHEN}
            onChange={setWhen}
            className="flex-wrap"
          />
        </div>

        <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-2.5">
          <Tile
            label="GPU time"
            value={picked.length > 0 ? `≈ ${hoursAndMinutes(seconds * rate)}` : "–"}
            note={
              picked.length > 0
                ? nights(seconds * rate).replace("less than a night", "one night")
                : "nothing to make"
            }
          />
          <Tile
            label="Space"
            value={picked.length > 0 ? size(seconds * BYTES_A_SECOND) : "–"}
            note="beside the videos"
          />
          <Tile
            label="Speech model"
            value={model ? size(model.size) : "–"}
            note={modelNote(model)}
          />
        </div>
        <p className="text-12 text-fg-muted">
          Made from the sound, so names, jokes and songs can come out wrong. The player marks them
          as Maku's, and History can take them away again.
        </p>

        {needsModel && model ? (
          <ModelFirst
            model={model}
            busy={download.isPending || make.isPending}
            problem={
              download.error?.message ??
              make.error?.message ??
              (model.state === "failed" ? model.problem : null)
            }
            onDownload={() =>
              download.mutate(
                { path: `/tools/${model.id}/download` },
                { onSuccess: () => queueThem() },
              )
            }
            onNotNow={() => setNeedsModel(false)}
          />
        ) : (
          <>
            {make.isError && (
              <p role="alert" className="text-13 text-broken-fg">
                Maku couldn't add them: {make.error.message}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2.5">
              <Button onClick={() => void navigate(titleId ? `/titles/${titleId}` : "/")}>
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={picked.length === 0 || make.isPending || !model}
                onClick={start}
              >
                {picked.length === 0 ? "Nothing to make" : `Make subtitles for ${what}`}
              </Button>
            </div>
          </>
        )}
      </section>
    </>
  );
}

/** The ways to choose videos: the season asked about, its title, and the whole library. */
interface ScopeChoice {
  scope: Scope;
  label: string;
  /** What History calls the batch: "Starfall Academy · Season 1". */
  title: string;
  files: Hearable[];
  note: (also: boolean) => string;
}

function scopesFor(
  all: Hearable[],
  mine: Hearable[],
  name: string | null,
  season: number | null,
  ticked: number[],
): ScopeChoice[] {
  const without = (files: Hearable[], also: boolean) => {
    const open = files.filter((file) => !file.waiting);
    return also
      ? `${open.length} videos`
      : `${open.filter((file) => !file.english).length} without English`;
  };
  const found: ScopeChoice[] = [];
  const picked = mine.filter((file) => ticked.includes(file.fileId));
  if (name && picked.length > 0) {
    const label = `The ${picked.length === 1 ? "video" : `${picked.length} videos`} you ticked`;
    found.push({
      scope: "ticked",
      label,
      title: `${name} · ${picked.length === 1 ? "1 video" : `${picked.length} videos`}`,
      files: picked,
      note: (also) => without(picked, also),
    });
  }
  const seasonal = season === null ? [] : mine.filter((file) => file.season === season);
  if (name && seasonal.length > 0) {
    const label = season === 0 ? "Specials" : `Season ${season}`;
    found.push({
      scope: "season",
      label,
      title: `${name} · ${label}`,
      files: seasonal,
      note: (also) => without(seasonal, also),
    });
  }
  if (name && mine.length > 0) {
    found.push({
      scope: "title",
      label: `All of ${name}`,
      title: name,
      files: mine,
      note: (also) => without(mine, also),
    });
  }
  found.push({
    scope: "everything",
    label: "Everything without English",
    title: "Everything without English",
    files: all,
    note: (also) => {
      const open = all.filter((file) => !file.waiting && (also || !file.english));
      const titles = new Set(open.map((file) => file.titleId)).size;
      return `${open.length} video${open.length === 1 ? "" : "s"} in ${titles} title${titles === 1 ? "" : "s"}`;
    },
  });
  return found;
}

/** The speech model isn't on this PC yet: it's fetched once, first. */
function ModelFirst(props: {
  model: Tool;
  busy: boolean;
  problem: string | null;
  onDownload: () => void;
  onNotNow: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-3 rounded-18 border border-accent/40 bg-accent/8 p-4.5"
    >
      <span className="font-extrabold">Maku needs its speech model first</span>
      <span className="text-13 text-fg-soft">
        {size(props.model.size)}, downloaded once from the source the installer's first page lists,
        and checked before it's used. It stays on this PC.
      </span>
      <span className="font-mono text-12 text-fg-muted">
        {props.model.name} · {props.model.licence} licence
      </span>
      {props.problem && <span className="text-13 text-broken-fg">{props.problem}</span>}
      <div className="flex flex-wrap gap-2.5">
        <Button variant="primary" disabled={props.busy} onClick={props.onDownload}>
          <Download size={16} aria-hidden="true" />
          Download it and start
        </Button>
        <Button onClick={props.onNotNow}>Not now</Button>
      </div>
    </div>
  );
}

function Tile(props: { label: string; value: string; note: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-16 bg-tint/4 px-4 py-3.5">
      <span className="text-12 text-fg-muted">{props.label}</span>
      <span className="font-extrabold text-20">{props.value}</span>
      <span className="text-12 text-fg-muted">{props.note}</span>
    </div>
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

function modelNote(model: Tool | undefined): string {
  if (!model) return "";
  if (model.state === "ready") return "on this PC";
  if (model.state === "downloading") {
    return `downloading · ${Math.round((100 * model.done) / Math.max(model.size, 1))}%`;
  }
  if (model.state === "failed") return "its download didn't finish";
  return "once, on the installer's list";
}

/** Each language once, the most used first. */
function byUse(codes: string[]): string[] {
  const counts = new Map<string, number>();
  for (const code of codes) counts.set(code, (counts.get(code) ?? 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1]).map(([code]) => code);
}

/**
 * The sound to start with: the videos' own language, which a file's first sound track is as a
 * rule (the one most of them start with, unlabelled ones left out), else the most used of
 * `sounds`. English sound is written down; any other is translated into English.
 */
function firstChoice(picked: Hearable[], sounds: string[]): string | null {
  const own = byUse(picked.map((file) => file.sound[0] ?? "").filter(Boolean));
  return own[0] ?? sounds[0] ?? null;
}

/** "6 min", at least a minute. */
function minutes(seconds: number): string {
  return `${Math.max(1, Math.round(seconds / 60))} min`;
}

/** "3 h 40 min", "25 min". */
function hoursAndMinutes(seconds: number): string {
  const total = Math.max(1, Math.round(seconds / 60));
  const hours = Math.floor(total / 60);
  return hours ? `${hours} h ${total % 60} min` : `${total} min`;
}
