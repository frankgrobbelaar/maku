import { AlertTriangle, Check, Lock, Pause, Play } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { CheckBox } from "@/components/check-box";
import { EmptyState, ShelfIllustration } from "@/components/empty-state";
import { EngineProblem } from "@/components/engine-problem";
import { FileMenuItems, FileNote, useFileActions } from "@/components/file-actions";
import { NoMatches, SearchField, useAddressSearch } from "@/components/search-field";
import { Loading, PanelSkeleton } from "@/components/skeleton";
import { fastSubtitles } from "@/components/this-pc";
import { Button } from "@/components/ui/button";
import { MenuItem, MenuSeparator, RowMenu } from "@/components/ui/menu";
import { Switch } from "@/components/ui/switch";
import { SpeechModelWait } from "@/features/subtitles/speech-model";
import {
  driveOf,
  episodeCode,
  gpuTime,
  gpuTimeShort,
  type JobGroup,
  jobGroups,
  METHOD_NAMES,
  METHOD_PICTURES,
  progress,
  retryIn,
} from "@/lib/convert";
import {
  type Job,
  type Quality,
  type QueueStatus,
  type Room,
  type RunningJob,
  useEmptyQuarantine,
  useQueue,
  useQueueAction,
  useQueueSchedule,
  useQueueTonight,
  useRemoveFromQueue,
  useSettings,
  useStill,
  useSystem,
} from "@/lib/engine";
import { clockTime, keptFor, languageName, split } from "@/lib/format";
import { matches } from "@/lib/search";
import { cn } from "@/lib/utils";
import { ConvertTabs } from "./convert-tabs";
import { NoRoom } from "./no-room";

const LISTED = 5; // waiting files a group shows before "Show more"

/** The queue: the file converting now, what's next, when it runs, and today's results. */
export function QueuePage() {
  const queue = useQueue();
  const action = useQueueAction();
  const settings = useSettings();
  const status = queue.data;
  const [cancelling, setCancelling] = useState(false);

  // Space pauses or resumes, as the board's key hint says, unless a control has the focus.
  const toggle = useRef<() => void>(() => {});
  toggle.current = () => {
    if (!status || action.isPending) return;
    action.mutate({ path: status.paused ? "/queue/resume" : "/queue/pause" });
  };
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.code !== "Space" || event.target !== document.body) return;
      event.preventDefault();
      toggle.current();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const header = (
    <header className="page-top flex animate-fade-up flex-wrap items-end justify-between gap-4">
      <div className="flex min-w-0 flex-col gap-1.5">
        <h1 className="type-title">Queue</h1>
        {status && <StatusLine status={status} />}
      </div>
      <div className="flex flex-wrap items-center gap-2.5">
        <ConvertTabs queued={status ? status.queued.length : null} />
        {status && (status.running || status.queued.length > 0) && (
          <Button disabled={action.isPending} onClick={() => toggle.current()}>
            {status.paused ? (
              <Play size={14} fill="currentColor" aria-hidden="true" />
            ) : (
              <Pause size={14} fill="currentColor" aria-hidden="true" />
            )}
            {status.paused ? "Resume" : "Pause all"}
            <kbd className="rounded-6 border border-tint/14 px-1.5 font-mono text-11 text-fg-muted leading-[18px]">
              Space
            </kbd>
          </Button>
        )}
        {status && (status.running || status.queued.length > 0) && (
          <Button variant="ghost" onClick={() => setCancelling(true)}>
            Cancel all
          </Button>
        )}
      </div>
    </header>
  );
  if (!status) {
    return (
      <>
        {header}
        <EngineProblem queries={[queue]} />
        <Loading label="Loading the queue" queries={[queue]}>
          <div className="flex flex-wrap items-start gap-5">
            <PanelSkeleton rows={6} className="flex-[999_1_560px]" />
            <div className="flex min-w-0 flex-[1_1_340px] flex-col gap-5">
              <PanelSkeleton rows={2} />
              <PanelSkeleton rows={2} />
            </div>
          </div>
        </Loading>
      </>
    );
  }
  const idle = !status.running && status.queued.length === 0;
  const held = status.queued.filter((job) => job.retryAt !== null);
  const unready = [...new Set(status.queued.filter((job) => job.modelMissing).map(qualityOf))];
  return (
    <>
      {header}
      {cancelling && !idle && (
        <CancelAll
          files={status.queued.length + (status.running ? 1 : 0)}
          converting={status.running !== null}
          onClose={() => setCancelling(false)}
        />
      )}
      <EngineProblem queries={[queue]} />
      <Problem error={action.error} />
      {status.problem && (
        <p
          role="alert"
          className="rounded-20 border border-broken/40 bg-broken/8 px-5 py-4 text-13"
        >
          {status.problem}
        </p>
      )}
      {status.room && <RoomCard room={status.room} queued={status.queued} />}
      {status.queued.map(
        (job) =>
          job.retryAt !== null && <OpenElsewhere key={job.id} job={job} retryAt={job.retryAt} />,
      )}
      {unready.map((quality) => (
        <SpeechModelWait key={quality} quality={quality} />
      ))}
      {status.running && status.endsAt && <Tonight endsAt={status.endsAt} early={status.early} />}
      {status.running?.job.kind === "subtitles" ? (
        <NowHearing running={status.running} gpu={status.gpu} paused={status.paused} />
      ) : status.running?.job.kind === "merge" ? (
        <NowAdding running={status.running} paused={status.paused} />
      ) : status.running ? (
        <NowConverting running={status.running} gpu={status.gpu} paused={status.paused} />
      ) : (
        held.length < status.queued.length && !status.room && <Waiting status={status} />
      )}
      {idle && (
        <EmptyState
          title="Nothing waiting"
          illustration={<ShelfIllustration />}
          action={
            <Button asChild variant="primary">
              <Link to="/convert">Choose what to convert</Link>
            </Button>
          }
        >
          Files you add to the queue convert here, one at a time, each checked before it takes its
          original's place.
        </EmptyState>
      )}
      <div className="flex flex-wrap items-start gap-5">
        {status.queued.length > 0 && <UpNext jobs={status.queued} />}
        <div className="flex min-w-0 flex-[1_1_340px] flex-col gap-5">
          <Schedule status={status} />
          <Today jobs={status.today} />
          <p className="text-12 text-fg-faint">
            Every finished file is checked for length, streams and a test play before it replaces
            the original.{" "}
            {settings.data?.originals === "delete"
              ? "Originals are deleted once their converted copy is in place."
              : `Originals are kept in quarantine ${keptFor(settings.data?.quarantineDays)}.`}
          </p>
        </div>
      </div>
    </>
  );
}

function StatusLine({ status }: { status: QueueStatus }) {
  const waiting = status.queued.length;
  const left = status.gpuSeconds > 0 ? `about ${gpuTime(status.gpuSeconds)} of GPU time` : null;
  const queued = `${waiting} in the queue`;
  const missing = drivesMissing(status.queued);
  const held = status.queued.every((job) => job.retryAt !== null);
  const forRoom = status.room && !status.room.paused && waitingForRoom(status.queued);
  const [dot, words] = status.paused
    ? ["bg-fg-faint", ["Paused", queued]]
    : status.running
      ? ["animate-pulse bg-accent", ["Running", queued, left]]
      : status.waitsForNight && waiting > 0 && !held
        ? ["bg-convert", ["Waiting for the night", queued, "starts at 23:00"]]
        : missing
          ? ["bg-fg-faint", [`Waiting for ${either(missing) || "a drive"}`, queued]]
          : forRoom
            ? ["bg-fg-faint", [`Waiting for room on ${status.room?.drive}`, queued]]
            : waiting > 0 && held
              ? ["bg-fg-faint", ["Waiting for another app", queued]]
              : waiting > 0
                ? ["animate-pulse bg-accent", ["Starting", queued]]
                : ["bg-fg-faint", ["Nothing waiting"]];
  return (
    <span className="inline-flex items-center gap-2 text-14 text-fg-muted">
      <span aria-hidden="true" className={cn("size-2 rounded-full", dot)} />
      {words.filter(Boolean).join(" · ")}
    </span>
  );
}

const STEPS = ["Read", "Encode", "Check"] as const;

/** Where a file is: reading it, making it, checking the result. */
function stepOf(running: RunningJob): number {
  if (running.stage === "looking") return 0;
  return running.stage === "converting" ? 1 : 2;
}

function NowConverting(props: { running: RunningJob; gpu: QueueStatus["gpu"]; paused: boolean }) {
  const { running } = props;
  const { job } = running;
  const action = useQueueAction();
  const still = useStill(job.fileId, 1);
  const at = stepOf(running);
  const share = progress(running);
  const speed = useSpeeds(running.fps);
  return (
    <section
      aria-label="Now converting"
      className="relative flex animate-fade-up flex-wrap items-center gap-6 overflow-hidden rounded-26 bg-featured p-6.5 text-white scheme-dark"
    >
      <span
        aria-hidden="true"
        className="-right-30 -bottom-40 absolute size-90 rounded-full bg-featured-orb/90"
      />
      <div
        aria-hidden="true"
        className="relative h-37.5 flex-[0_0_200px] overflow-hidden rounded-14 bg-inset shadow-[0_20px_40px_-20px_rgb(0_0_0/0.6)]"
      >
        {still && <img src={still} alt="" className="size-full object-cover" />}
      </div>
      <div className="relative flex min-w-0 flex-[1_1_340px] flex-col gap-3">
        <span className="font-extrabold text-12 text-converting">Now converting</span>
        <h2 className="font-extrabold text-[28px] leading-[1.1] tracking-[-0.02em]">{job.label}</h2>
        <ol aria-label="Steps" className="flex flex-wrap items-center gap-1.5 font-bold text-12">
          {STEPS.map((step, index) => (
            <li
              key={step}
              aria-current={index === at ? "step" : undefined}
              className={cn(
                "inline-flex items-center gap-1.5",
                index === at ? "text-converting" : index > at && "text-white/75",
              )}
            >
              {index > 0 && (
                <span
                  aria-hidden="true"
                  className={cn("mr-0.5 h-0.5 w-3.5", index <= at ? "bg-accent" : "bg-white/30")}
                />
              )}
              <StepMark done={index < at} now={index === at} />
              {step}
            </li>
          ))}
        </ol>
        <div className="relative h-2 overflow-hidden rounded-4 bg-white/16">
          <div
            className="relative h-full overflow-hidden rounded-4 bg-accent transition-[width] duration-600 ease-cinema"
            style={{ width: `${share}%` }}
          >
            <span
              aria-hidden="true"
              className="absolute inset-0 animate-shimmer bg-linear-to-r from-white/0 via-white/60 to-white/0"
            />
          </div>
        </div>
        <div className="flex flex-wrap justify-between gap-x-4 gap-y-1.5 text-13 text-white/85">
          <span>
            {share}%
            {running.secondsLeft !== null && running.secondsLeft > 0
              ? ` · ${gpuTime(running.secondsLeft)} left`
              : running.stage === "checking"
                ? " · checking the result"
                : running.stage === "replacing"
                  ? " · putting it in place"
                  : ""}
          </span>
          <span>
            {job.method === "remux" ? METHOD_PICTURES.remux : METHOD_PICTURES.reencode}
            {job.width && job.height ? ` · ${job.width} × ${job.height}` : ""}
          </span>
        </div>
        <div className="flex flex-wrap gap-2.5">
          <FeaturedButton
            disabled={action.isPending || props.paused}
            onClick={() => action.mutate({ path: "/queue/pause" })}
          >
            <Pause size={14} fill="currentColor" aria-hidden="true" />
            Pause
          </FeaturedButton>
          <FeaturedButton
            disabled={action.isPending}
            onClick={() => action.mutate({ path: `/queue/${job.id}/skip` })}
          >
            Skip this file
          </FeaturedButton>
        </div>
        <Problem error={action.error} />
      </div>
      <div className="relative grid min-w-60 flex-[0_1_300px] grid-cols-2 gap-2.5">
        {props.gpu && (
          <>
            <Stat className="items-center">
              <Ring busy={props.gpu.busy} />
              <span className="text-12 text-white/80">GPU busy</span>
            </Stat>
            <Stat className="justify-center">
              <span className="font-extrabold text-22 leading-none">{props.gpu.celsius} °C</span>
              <span className="h-1.5 overflow-hidden rounded-3 bg-white/16">
                <span
                  className="block h-full rounded-3 bg-converting"
                  style={{ width: `${Math.min(100, props.gpu.celsius)}%` }}
                />
              </span>
              <span className="text-12 text-white/80">GPU temperature</span>
            </Stat>
          </>
        )}
        <Stat className="col-span-2">
          <span className="flex justify-between text-12 text-white/80">
            <span>Speed, last 10 min</span>
            <span className="font-mono text-converting">
              {running.fps ? `${running.fps.toFixed(1)} fps` : "…"}
            </span>
          </span>
          <Sparkline values={speed} />
        </Stat>
      </div>
    </section>
  );
}

const HEARING = ["Read the sound", "Listen", "Write", "Check"] as const;

/** Where subtitles being made are: reading the sound, hearing it, writing them, checking them. */
function hearingStep(running: RunningJob): number {
  if (running.stage === "listening") return 1;
  if (running.stage === "writing") return 2;
  if (running.stage === "checking") return 3;
  return 0;
}

const ADDING = ["Line them up", "Add the English", "Check", "Put it in place"] as const;

/** Where English from another copy is: lining the copies up, copying the one kept with the
 * English, checking it, putting it in place. */
function addingStep(running: RunningJob): number {
  return { looking: 0, converting: 1, checking: 2, replacing: 3 }[running.stage as string] ?? 0;
}

/** English from another copy being added now: the copy kept, the steps, how far. Nothing runs
 * on the graphics card. */
function NowAdding(props: { running: RunningJob; paused: boolean }) {
  const { running } = props;
  const { job } = running;
  const action = useQueueAction();
  const still = useStill(job.fileId, 1);
  const at = addingStep(running);
  const share = progress(running);
  return (
    <section
      aria-label="Now adding English from another copy"
      className="relative flex animate-fade-up flex-wrap items-center gap-6 overflow-hidden rounded-26 bg-featured p-6.5 text-white scheme-dark"
    >
      <span
        aria-hidden="true"
        className="-right-30 -bottom-40 absolute size-90 rounded-full bg-featured-orb/90"
      />
      <div
        aria-hidden="true"
        className="relative h-37.5 flex-[0_0_200px] overflow-hidden rounded-14 bg-inset shadow-[0_20px_40px_-20px_rgb(0_0_0/0.6)]"
      >
        {still && <img src={still} alt="" className="size-full object-cover" />}
      </div>
      <div className="relative flex min-w-0 flex-[1_1_340px] flex-col gap-3">
        <span className="font-extrabold text-12 text-converting">English from another copy</span>
        <h2 className="font-extrabold text-[28px] leading-[1.1] tracking-[-0.02em]">{job.label}</h2>
        <span className="text-13 text-white/85">
          Lined up with this picture by the sound both copies have
        </span>
        <ol aria-label="Steps" className="flex flex-wrap items-center gap-1.5 font-bold text-12">
          {ADDING.map((step, index) => (
            <li
              key={step}
              aria-current={index === at ? "step" : undefined}
              className={cn(
                "inline-flex items-center gap-1.5",
                index === at ? "text-converting" : index > at && "text-white/75",
              )}
            >
              {index > 0 && (
                <span
                  aria-hidden="true"
                  className={cn("mr-0.5 h-0.5 w-3.5", index <= at ? "bg-accent" : "bg-white/30")}
                />
              )}
              <StepMark done={index < at} now={index === at} />
              {step}
            </li>
          ))}
        </ol>
        <div className="relative h-2 overflow-hidden rounded-4 bg-white/16">
          <div
            className="relative h-full overflow-hidden rounded-4 bg-accent transition-[width] duration-600 ease-cinema"
            style={{ width: `${share}%` }}
          >
            <span
              aria-hidden="true"
              className="absolute inset-0 animate-shimmer bg-linear-to-r from-white/0 via-white/60 to-white/0"
            />
          </div>
        </div>
        <span className="text-13 text-white/85">
          {share}%
          {running.secondsLeft !== null && running.secondsLeft > 0
            ? ` · ${gpuTime(running.secondsLeft)} left`
            : running.stage === "checking"
              ? " · checking it plays"
              : ""}
        </span>
        <div className="flex flex-wrap gap-2.5">
          <FeaturedButton
            disabled={action.isPending || props.paused}
            onClick={() => action.mutate({ path: "/queue/pause" })}
          >
            <Pause size={14} fill="currentColor" aria-hidden="true" />
            Pause
          </FeaturedButton>
          <FeaturedButton
            disabled={action.isPending}
            onClick={() => action.mutate({ path: `/queue/${job.id}/skip` })}
          >
            Skip this file
          </FeaturedButton>
        </div>
        <Problem error={action.error} />
      </div>
    </section>
  );
}

/** English subtitles being made now: the video, from which sound and at what quality, how far
 * Maku has heard it, and the card's load. */
function NowHearing(props: { running: RunningJob; gpu: QueueStatus["gpu"]; paused: boolean }) {
  const { running } = props;
  const { job } = running;
  const action = useQueueAction();
  const still = useStill(job.fileId, 1);
  const at = hearingStep(running);
  const share = progress(running);
  const english = job.language === "eng" || job.language === "en";
  const steps = HEARING.map((step) =>
    step === "Listen" ? (english ? "Listen and write down" : "Listen and translate") : step,
  );
  return (
    <section
      aria-label="Now making English subtitles"
      className="relative flex animate-fade-up flex-wrap items-center gap-6 overflow-hidden rounded-26 bg-featured p-6.5 text-white scheme-dark"
    >
      <span
        aria-hidden="true"
        className="-right-30 -bottom-40 absolute size-90 rounded-full bg-featured-orb/90"
      />
      <div
        aria-hidden="true"
        className="relative h-37.5 flex-[0_0_200px] overflow-hidden rounded-14 bg-inset shadow-[0_20px_40px_-20px_rgb(0_0_0/0.6)]"
      >
        {still && <img src={still} alt="" className="size-full object-cover" />}
      </div>
      <div className="relative flex min-w-0 flex-[1_1_340px] flex-col gap-3">
        <span className="font-extrabold text-12 text-converting">English subtitles</span>
        <h2 className="font-extrabold text-[28px] leading-[1.1] tracking-[-0.02em]">{job.label}</h2>
        <span className="text-13 text-white/85">
          {[
            job.language ? `from the ${languageName(job.language)} sound` : "from its sound",
            METHOD_NAMES[job.method],
          ].join(" · ")}
        </span>
        <ol aria-label="Steps" className="flex flex-wrap items-center gap-1.5 font-bold text-12">
          {steps.map((step, index) => (
            <li
              key={step}
              aria-current={index === at ? "step" : undefined}
              className={cn(
                "inline-flex items-center gap-1.5",
                index === at ? "text-converting" : index > at && "text-white/75",
              )}
            >
              {index > 0 && (
                <span
                  aria-hidden="true"
                  className={cn("mr-0.5 h-0.5 w-3.5", index <= at ? "bg-accent" : "bg-white/30")}
                />
              )}
              <StepMark done={index < at} now={index === at} />
              {step}
            </li>
          ))}
        </ol>
        <div className="relative h-2 overflow-hidden rounded-4 bg-white/16">
          <div
            className="relative h-full overflow-hidden rounded-4 bg-accent transition-[width] duration-600 ease-cinema"
            style={{ width: `${share}%` }}
          >
            <span
              aria-hidden="true"
              className="absolute inset-0 animate-shimmer bg-linear-to-r from-white/0 via-white/60 to-white/0"
            />
          </div>
        </div>
        <div className="flex flex-wrap justify-between gap-x-4 gap-y-1.5 text-13 text-white/85">
          <span>
            {share}%
            {running.secondsLeft !== null && running.secondsLeft > 0
              ? ` · ${gpuTime(running.secondsLeft)} left`
              : running.stage === "checking"
                ? " · checking them"
                : running.stage === "writing"
                  ? " · writing them beside the video"
                  : ""}
          </span>
          {running.total > 0 && (
            <span className="font-mono">
              {clockTime(running.frames)} of {clockTime(running.total)} heard
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-2.5">
          <FeaturedButton
            disabled={action.isPending || props.paused}
            onClick={() => action.mutate({ path: "/queue/pause" })}
          >
            <Pause size={14} fill="currentColor" aria-hidden="true" />
            Pause
          </FeaturedButton>
          <FeaturedButton
            disabled={action.isPending}
            onClick={() => action.mutate({ path: `/queue/${job.id}/skip` })}
          >
            Skip this file
          </FeaturedButton>
        </div>
        <Problem error={action.error} />
      </div>
      {props.gpu && (
        <div className="relative grid min-w-60 flex-[0_1_300px] grid-cols-2 gap-2.5">
          <Stat className="items-center">
            <Ring busy={props.gpu.busy} />
            <span className="text-12 text-white/80">GPU busy</span>
          </Stat>
          <Stat className="justify-center">
            <span className="font-extrabold text-22 leading-none">{props.gpu.celsius} °C</span>
            <span className="h-1.5 overflow-hidden rounded-3 bg-white/16">
              <span
                className="block h-full rounded-3 bg-converting"
                style={{ width: `${Math.min(100, props.gpu.celsius)}%` }}
              />
            </span>
            <span className="text-12 text-white/80">GPU temperature</span>
          </Stat>
        </div>
      )}
    </section>
  );
}

/** The speeds heard while this page is open, for the sparkline. */
function useSpeeds(fps: number | null): number[] {
  const [speeds, setSpeeds] = useState<number[]>([]);
  useEffect(() => {
    if (fps !== null) setSpeeds((before) => [...before.slice(-29), fps]);
  }, [fps]);
  return speeds;
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <span className="h-9" />;
  const top = Math.max(...values) * 1.15;
  const points = values
    .map((value, index) => `${(index / (values.length - 1)) * 240},${36 - (value / top) * 30}`)
    .join(" ");
  return (
    <svg
      width="100%"
      height="36"
      viewBox="0 0 240 36"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <polyline
        points={points}
        fill="none"
        stroke="var(--color-accent)"
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

function Ring({ busy }: { busy: number }) {
  return (
    <span className="relative size-16">
      <svg
        width="64"
        height="64"
        viewBox="0 0 100 100"
        role="img"
        aria-label={`Graphics card ${busy} percent busy`}
      >
        <circle
          cx="50"
          cy="50"
          r="40"
          fill="none"
          stroke="rgb(255 255 255 / 0.16)"
          strokeWidth="10"
        />
        <circle
          cx="50"
          cy="50"
          r="40"
          fill="none"
          stroke="var(--color-accent)"
          strokeWidth="10"
          strokeLinecap="round"
          pathLength="100"
          strokeDasharray="100"
          strokeDashoffset={100 - busy}
          transform="rotate(-90 50 50)"
          className="transition-[stroke-dashoffset] duration-600 ease-cinema"
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-extrabold text-14">
        {busy}%
      </span>
    </span>
  );
}

/** A figure on the featured panel, in a box of the scheme's deepest dark. */
function Stat({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1.5 rounded-18 border border-white/12 bg-inset/62 p-3.5",
        className,
      )}
    >
      {children}
    </div>
  );
}

function StepMark({ done, now }: { done: boolean; now: boolean }) {
  if (done) {
    return (
      <span className="inline-flex size-4.5 items-center justify-center rounded-full bg-accent text-on-accent">
        <Check size={10} strokeWidth={3.6} aria-hidden="true" />
      </span>
    );
  }
  if (now) {
    return (
      <span className="inline-flex size-4.5 items-center justify-center rounded-full shadow-[inset_0_0_0_2px_var(--color-accent)]">
        <span className="size-2 animate-pulse rounded-full bg-accent" />
      </span>
    );
  }
  return <span className="size-4.5 rounded-full shadow-[inset_0_0_0_2px_rgb(255_255_255/0.35)]" />;
}

function FeaturedButton(props: React.ComponentProps<"button">) {
  return (
    <button
      type="button"
      {...props}
      className="press inline-flex min-h-10.5 cursor-pointer items-center gap-2 rounded-full bg-white/14 px-4.5 font-bold text-white disabled:pointer-events-none disabled:opacity-50"
    />
  );
}

/**
 * Files wait, but none converts: paused, waiting for the night or for a drive, or about to
 * start.
 */
function Waiting({ status }: { status: QueueStatus }) {
  const action = useQueueAction();
  const missing = drivesMissing(status.queued);
  const waiting = status.queued.filter((job) => job.retryAt === null);
  const words = status.paused
    ? "The queue is paused. A file that was converting starts again from its beginning."
    : status.waitsForNight
      ? "Files convert tonight, from 23:00 to 07:00."
      : missing
        ? unpluggedWords(missing)
        : waiting.length > 0 && waiting.every((job) => job.modelMissing)
          ? "English subtitles start once their speech model is on this PC."
          : "The next file starts in a moment.";
  return (
    <section
      aria-label="Waiting"
      className="flex animate-fade-up flex-wrap items-center justify-between gap-3 rounded-24 border border-edge bg-glass px-5.5 py-4.5 shadow-panel"
    >
      <span className="text-14">{words}</span>
      {status.paused && (
        <Button
          variant="primary"
          disabled={action.isPending}
          onClick={() => action.mutate({ path: "/queue/resume" })}
        >
          <Play size={14} fill="currentColor" aria-hidden="true" />
          Resume
        </Button>
      )}
      <Problem error={action.error} className="basis-full" />
    </section>
  );
}

/**
 * While the nights-only queue converts at night (board 5.3): Maku keeps the PC awake till
 * tonight's run takes its last file, and the owner can have it stop at 03:00 instead, so normal
 * sleep comes back sooner. A file started before then finishes.
 */
function Tonight({ endsAt, early }: { endsAt: string; early: boolean }) {
  const tonight = useQueueTonight();
  const now = new Date();
  const end = new Date(endsAt);
  const until = end.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const hour = now.getHours();
  const label = early
    ? "Go on till 07:00"
    : hour >= 3 && hour < 7
      ? "Stop after this file"
      : "Stop at 03:00";
  return (
    <div
      role="status"
      className="flex animate-fade-up flex-wrap items-center gap-3 rounded-18 border border-tint/10 bg-tint/5 px-4 py-3.5"
    >
      <span aria-hidden="true" className="size-2.5 shrink-0 animate-pulse rounded-full bg-accent" />
      <span className="min-w-0 flex-1 text-14">
        {now >= end
          ? "Keeping the PC awake while this file finishes. Normal sleep comes back after."
          : `Keeping the PC awake until ${until} while it converts. Normal sleep comes back after.`}
      </span>
      <Button
        size="sm"
        disabled={tonight.isPending}
        onClick={() => tonight.mutate({ path: "/queue/tonight", body: { early: !early } })}
      >
        {label}
      </Button>
      <Problem error={tonight.error} className="basis-full" />
    </div>
  );
}

/**
 * When every file still to convert is on a drive that isn't connected: those drives ("D:"), else
 * null. One made already waits for another app instead.
 */
function drivesMissing(jobs: Job[]): string[] | null {
  const unmade = jobs.filter((job) => job.retryAt === null);
  if (unmade.length === 0 || unmade.some((job) => !job.driveMissing)) return null;
  return [...new Set(unmade.map((job) => driveOf(job.path)))].filter(Boolean);
}

/** Whether every file still to convert waits: for room on its drive, or for the drive. */
function waitingForRoom(jobs: Job[]): boolean {
  const unmade = jobs.filter((job) => job.retryAt === null);
  return unmade.some((job) => job.noRoom) && unmade.every((job) => job.noRoom || job.driveMissing);
}

/**
 * Not enough space: the queue paused for a drive without room for what waits on it, or the
 * files there that don't fit wait for room while the others go.
 */
function RoomCard({ room, queued }: { room: Room; queued: Job[] }) {
  const action = useQueueAction();
  const empty = useEmptyQuarantine();
  const drive = room.drive.toUpperCase();
  const waiting = queued.filter(
    (job) => job.retryAt === null && !job.driveMissing && driveOf(job.path).toUpperCase() === drive,
  );
  return (
    <NoRoom
      drive={room.drive}
      waiting={waiting}
      needed={room.needed}
      free={room.free}
      fit={room.fit}
      setAside={room.setAside}
      waitingForRoom={!room.paused}
      busy={action.isPending || empty.isPending}
      problem={empty.error ?? action.error}
      onEmpty={() =>
        empty.mutate(
          { path: "/quarantine/empty", body: { drive: room.drive } },
          { onSuccess: () => room.paused && action.mutate({ path: "/queue/resume" }) },
        )
      }
      onFit={() => action.mutate({ path: "/queue/fit", body: { drive: room.drive } })}
    />
  );
}

/**
 * A converted file waiting beside its original, which another app (a player, say) has open; or,
 * made, waiting for its drive to be connected again.
 */
/** The quality English subtitles are made at: their job's method. */
function qualityOf(job: Job): Quality {
  return job.method === "fast" ? "fast" : "best";
}

function OpenElsewhere({ job, retryAt }: { job: Job; retryAt: string }) {
  const action = useQueueAction();
  const drive = driveOf(job.path) || "its drive";
  return (
    <div
      role="status"
      className="flex animate-fade-up flex-col gap-3 rounded-18 border border-tint/10 bg-raised px-4.5 py-4 shadow-panel"
    >
      <span className="flex gap-3 text-14">
        <Lock size={20} aria-hidden="true" className="shrink-0 text-convert-fg" />
        {job.driveMissing ? (
          <span>
            <strong className="font-extrabold">
              {job.label} is made, and waits for {drive}.
            </strong>{" "}
            It goes in once the drive is connected.
          </span>
        ) : (
          <span>
            <strong className="font-extrabold">{job.label} is open in another app,</strong> maybe
            your player. Maku will try again {retryIn(retryAt, Date.now())}.
          </span>
        )}
      </span>
      <div className="flex flex-wrap gap-2">
        {!job.driveMissing && (
          <Button
            size="sm"
            disabled={action.isPending}
            onClick={() => action.mutate({ path: `/queue/${job.id}/retry` })}
          >
            Try now
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          disabled={action.isPending}
          onClick={() => action.mutate({ path: `/queue/${job.id}/skip` })}
        >
          Skip this file
        </Button>
      </div>
      <Problem error={action.error} />
    </div>
  );
}

/** "D:", "D: or F:", "D:, E: or F:"; empty when there are none. */
function either(drives: string[]): string {
  if (drives.length < 2) return drives[0] ?? "";
  return `${drives.slice(0, -1).join(", ")} or ${drives.at(-1)}`;
}

function unpluggedWords(drives: string[]): string {
  if (drives.length === 0) {
    return "Every file waiting is on a drive that isn't connected. Plug it in to carry on.";
  }
  return drives.length === 1
    ? `Every file waiting is on ${either(drives)}, which isn't connected. Plug it in to carry on.`
    : `Every file waiting is on ${either(drives)}, which aren't connected. Plug one in to carry on.`;
}

/** Asks before cancelling everything: the file converting now stops, and every file waiting
 * leaves the queue. The files themselves stay as they are. */
function CancelAll(props: { files: number; converting: boolean; onClose: () => void }) {
  const action = useQueueAction();
  const files = props.files === 1 ? "1 file" : `${props.files} files`;
  return (
    <fieldset
      aria-label="Cancel all?"
      className="flex animate-fade-up flex-col gap-3 rounded-16 border border-danger/40 bg-danger/8 p-4"
    >
      <span className="font-extrabold text-14">Cancel all {files}?</span>
      <span className="text-13 text-fg-soft">
        {props.converting
          ? "The file converting now stops, and every file waiting leaves the queue."
          : "Every file waiting leaves the queue."}{" "}
        Your files stay as they are, and you can add them again from Convert.
      </span>
      <Problem error={action.error} />
      <div className="flex flex-wrap gap-2.5">
        <Button
          size="sm"
          variant="danger"
          disabled={action.isPending}
          onClick={() => action.mutate({ path: "/queue/cancel" }, { onSuccess: props.onClose })}
        >
          Cancel all {files}
        </Button>
        <Button size="sm" variant="ghost" onClick={props.onClose}>
          Keep them
        </Button>
      </div>
    </fieldset>
  );
}

/** What waits, by title and season, each group with a tick for all its files. Ticked files can be
 * moved or taken out all at once; each file's own menu does the same for it alone. */
function UpNext({ jobs }: { jobs: Job[] }) {
  const [query, setQuery] = useAddressSearch();
  const shown = jobs.filter((job) =>
    matches(query, job.label, job.title, episodeCode(job), split(job.path)[0]),
  );
  const groups = jobGroups(shown);
  const batch = useQueueAction();
  const [picked, setPicked] = useState<ReadonlySet<number>>(new Set());
  // The ticked files shown, in the order they wait in: one that started converting meanwhile
  // drops out, and one the search hides waits ticked till it shows again.
  const chosen = shown.filter((job) => picked.has(job.id)).map((job) => job.id);
  const next = jobs.find((job) => !chosen.includes(job.id));
  const all = chosen.length === 0 ? false : chosen.length === shown.length ? true : "mixed";
  const pick = (ids: number[], on: boolean) =>
    setPicked((before) => {
      const after = new Set(before);
      for (const id of ids) {
        if (on) after.add(id);
        else after.delete(id);
      }
      return after;
    });
  const act = (path: string, body: object) =>
    batch.mutate({ path, body }, { onSuccess: () => setPicked(new Set()) });
  if (jobs.length === 0) return null;
  return (
    <section
      aria-labelledby="next-title"
      className="flex min-w-0 flex-[999_1_560px] animate-fade-up flex-col gap-1 rounded-24 border border-edge bg-glass p-5.5 shadow-panel"
    >
      <div className="mb-2 flex min-h-9 flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3 px-1.5">
          <label className="flex cursor-pointer">
            <input
              type="checkbox"
              aria-label={query ? "Tick every file shown" : "Tick every file waiting"}
              checked={all === true}
              ref={(box) => {
                if (box) box.indeterminate = all === "mixed";
              }}
              disabled={shown.length === 0}
              onChange={() =>
                pick(
                  shown.map((job) => job.id),
                  all !== true,
                )
              }
              className="peer sr-only"
            />
            <CheckBox state={all} />
          </label>
          <h2 id="next-title" className="font-extrabold text-18">
            Up next
          </h2>
        </div>
        {chosen.length > 0 ? (
          <fieldset aria-label="Ticked files" className="flex flex-wrap items-center gap-2">
            <span className="mr-1 font-bold text-13">{chosen.length} ticked</span>
            {next && (
              <Button
                size="sm"
                disabled={batch.isPending}
                onClick={() => act("/queue/move", { ids: chosen, before: next.id })}
              >
                Convert next
              </Button>
            )}
            <Button
              size="sm"
              disabled={batch.isPending}
              onClick={() => act("/queue/move", { ids: chosen, before: null })}
            >
              Move to the end
            </Button>
            <Button
              size="sm"
              disabled={batch.isPending}
              onClick={() => act("/queue/remove", { ids: chosen })}
            >
              Take out of the queue
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setPicked(new Set())}>
              Untick all
            </Button>
          </fieldset>
        ) : (
          <span className="text-12 text-fg-muted">
            Tick files to move or take out several at once
          </span>
        )}
      </div>
      {(jobs.length > 1 || query) && (
        <SearchField
          value={query}
          onChange={setQuery}
          label="Search the queue"
          placeholder={`Search ${jobs.length} files waiting`}
          className="mb-2"
        />
      )}
      <Problem error={batch.error} />
      {groups.length === 0 && <NoMatches>No file waiting goes by “{query.trim()}”.</NoMatches>}
      {groups.map((group, at) => (
        <Group
          key={group.key}
          group={group}
          first={at === 0}
          picked={picked}
          onPick={pick}
          top={jobs[0]?.id ?? null}
        />
      ))}
    </section>
  );
}

/** One title's (or season's) files waiting: a tick for all of them, then the files themselves, a
 * few at first. The first group shows its files; the others on asking. */
function Group(props: {
  group: JobGroup;
  first: boolean;
  picked: ReadonlySet<number>;
  onPick: (ids: number[], on: boolean) => void;
  top: number | null;
}) {
  const { group } = props;
  // The first group shows its files till the owner says otherwise, whichever group is first.
  const [shown, setShown] = useState<boolean | null>(null);
  const open = shown ?? props.first;
  const [all, setAll] = useState(false);
  const ids = group.jobs.map((job) => job.id);
  const ticked = ids.filter((id) => props.picked.has(id)).length;
  const state = ticked === 0 ? false : ticked === ids.length ? true : "mixed";
  const listed = all ? group.jobs : group.jobs.slice(0, LISTED);
  return (
    <div className={cn("flex flex-col", !props.first && "mt-1 border-rule border-t pt-1")}>
      <div className="flex min-h-10 items-center gap-2.5 px-1.5">
        <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 font-extrabold text-12 text-fg-muted">
          <input
            type="checkbox"
            checked={state === true}
            ref={(box) => {
              if (box) box.indeterminate = state === "mixed";
            }}
            onChange={() => props.onPick(ids, state !== true)}
            className="peer sr-only"
          />
          <CheckBox state={state} />
          <span className="min-w-0 truncate">
            {group.label} · {group.jobs.length} left
          </span>
        </label>
        <span className="font-mono text-12 text-fg-muted">≈ {gpuTimeShort(sum(group.jobs))}</span>
        <Button
          size="sm"
          variant="ghost"
          aria-expanded={open}
          aria-label={`${open ? "Hide" : "Show"} the files of ${group.label}`}
          onClick={() => setShown(!open)}
        >
          {open ? "Hide" : "Show"}
        </Button>
      </div>
      {open && (
        <>
          <ul className="flex flex-col">
            {listed.map((job) => (
              <JobRow
                key={job.id}
                job={job}
                first={props.top}
                top={job.id === props.top}
                picked={props.picked.has(job.id)}
                onPick={(on) => props.onPick([job.id], on)}
              />
            ))}
          </ul>
          {group.jobs.length > listed.length && (
            <Button size="sm" variant="ghost" className="self-start" onClick={() => setAll(true)}>
              Show {group.jobs.length - listed.length} more
            </Button>
          )}
        </>
      )}
    </div>
  );
}

function JobRow(props: {
  job: Job;
  first: number | null;
  top: boolean;
  picked: boolean;
  onPick: (on: boolean) => void;
}) {
  const { job, first, top } = props;
  const action = useQueueAction();
  const remove = useRemoveFromQueue();
  const files = useFileActions();
  const [name] = split(job.path);
  return (
    <li className="flex flex-col border-rule border-b px-1.5 text-13 last:border-b-0">
      <div className="flex min-h-13 items-center gap-3">
        <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
          <input
            type="checkbox"
            checked={props.picked}
            onChange={(event) => props.onPick(event.target.checked)}
            className="peer sr-only"
          />
          <CheckBox state={props.picked} />
          <span className="w-17 shrink-0 font-mono">{episodeCode(job)}</span>
          <span className="min-w-0 flex-1 truncate text-fg-soft">{name}</span>
        </label>
        {job.driveMissing ? (
          <span className="rounded-full bg-tint/8 px-2 py-0.5 font-bold text-11 text-fg-muted">
            Its drive isn't connected
          </span>
        ) : job.noRoom ? (
          <span className="rounded-full bg-tint/8 px-2 py-0.5 font-bold text-11 text-fg-muted">
            Waiting for room
          </span>
        ) : job.retryAt !== null ? (
          <span className="rounded-full bg-tint/8 px-2 py-0.5 font-bold text-11 text-fg-muted">
            Open in another app
          </span>
        ) : job.modelMissing ? (
          <span className="rounded-full bg-tint/8 px-2 py-0.5 font-bold text-11 text-fg-muted">
            Waiting for its speech model
          </span>
        ) : (
          <span className="rounded-full bg-accent/14 px-2 py-0.5 font-extrabold text-11 text-accent-fg">
            {job.kind === "subtitles"
              ? `English subs · ${METHOD_NAMES[job.method]}`
              : job.kind === "merge"
                ? "English from another copy"
                : METHOD_NAMES[job.method]}
          </span>
        )}
        <span className="w-14 shrink-0 text-right font-mono text-12 text-fg-muted">
          {job.retryAt === null && `≈ ${gpuTimeShort(job.gpuSeconds)}`}
        </span>
        <RowMenu label={`More for ${job.label}`}>
          {!top && first !== null && (
            <MenuItem
              onSelect={() =>
                action.mutate({ path: `/queue/${job.id}/move`, body: { before: first } })
              }
            >
              {job.kind === "convert" ? "Convert next" : "Make next"}
            </MenuItem>
          )}
          <MenuItem
            onSelect={() =>
              action.mutate({ path: `/queue/${job.id}/move`, body: { before: null } })
            }
          >
            Move to the end
          </MenuItem>
          <MenuItem onSelect={() => remove.mutate({ path: `/queue/${job.id}` })}>
            Take out of the queue
          </MenuItem>
          <MenuSeparator />
          <FileMenuItems path={job.path} actions={files} />
        </RowMenu>
      </div>
      <Problem error={action.error ?? remove.error} className="pb-3" />
      <FileNote actions={files} className="pb-3 text-12 text-fg-muted" />
    </li>
  );
}

function Schedule({ status }: { status: QueueStatus }) {
  const schedule = useQueueSchedule();
  const id = useId();
  const nights = status.schedule === "nights";
  return (
    <section
      aria-labelledby="schedule-title"
      className="flex animate-fade-up flex-col gap-3.5 rounded-24 border border-edge bg-glass p-5 shadow-panel"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="schedule-title" className="font-extrabold text-16">
          Schedule
        </h2>
        <span className="font-bold text-12 text-accent-fg">
          {nights ? "Nights only" : "Running now, by hand"}
        </span>
      </div>
      <div className="flex items-start gap-3">
        <Switch
          id={id}
          checked={nights}
          disabled={schedule.isPending}
          aria-describedby={`${id}-text`}
          onCheckedChange={(on) =>
            schedule.mutate({ path: "/queue/schedule", body: { schedule: on ? "nights" : "now" } })
          }
        />
        <span className="flex flex-col gap-0.5">
          <label htmlFor={id} className="cursor-pointer font-extrabold text-14">
            Nights only, 23:00–07:00
          </label>
          <span id={`${id}-text`} className="text-12 text-fg-muted">
            {nights && status.waitsForNight
              ? "Picks up again tonight at 23:00"
              : "A file started before 07:00 finishes"}
          </span>
        </span>
      </div>
      <Problem error={schedule.error} />
      <p className="text-12 text-fg-muted">
        Maku keeps the PC awake while a file converts; Windows' sleep settings come back when it's
        done.
      </p>
    </section>
  );
}

function Today({ jobs }: { jobs: Job[] }) {
  const navigate = useNavigate();
  const done = jobs.filter((job) => job.state === "done");
  const failed = jobs.filter((job) => job.state === "failed");
  const written = done.reduce((total, job) => total + (job.outputSize ?? 0), 0);
  return (
    <section
      aria-labelledby="today-title"
      className="flex animate-fade-up flex-col gap-3.5 rounded-24 border border-edge bg-glass p-5 shadow-panel"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="today-title" className="font-extrabold text-16">
          Today
        </h2>
        <button
          type="button"
          onClick={() => void navigate("/history")}
          className="press cursor-pointer font-bold text-12 text-accent-fg"
        >
          History
        </button>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Figure
          value={String(done.length)}
          label={done.some((job) => job.kind !== "convert") ? "done" : "converted"}
        />
        <Figure value={String(failed.length)} label="failed" />
        <Figure
          value={
            written >= 1e9 ? `${(written / 1e9).toFixed(1)} GB` : `${Math.round(written / 1e6)} MB`
          }
          label="written"
        />
      </div>
      {failed.length > 0 && (
        // A long run of failed files keeps to a height and scrolls in its place, so the panel
        // doesn't run the page on (the owner, 2026-10-14: 42 cards were "a long scroll down").
        <div className="-mr-2 flex max-h-100 flex-col gap-3.5 overflow-y-auto pr-2">
          {failed.map((job) => (
            <Failed key={job.id} job={job} />
          ))}
        </div>
      )}
    </section>
  );
}

const LOG_SHOWN = 2; // of what ffmpeg said, the last lines a failed file shows

/** A file that failed: why, what ffmpeg said last, and what can be done about it. */
function Failed({ job }: { job: Job }) {
  const action = useQueueAction();
  const system = useSystem();
  const fast = fastSubtitles(system.data);
  const [copied, setCopied] = useState(false);
  const said = (job.log ?? "").split("\n").filter(Boolean).slice(-LOG_SHOWN);
  const asked = (path: string) => action.variables?.path === `/queue/${job.id}/${path}`;
  return (
    <div
      role="alert"
      className="flex flex-col gap-3 rounded-18 border border-broken/26 bg-broken/7 p-4"
    >
      <span className="flex items-start gap-2.5 text-13">
        <AlertTriangle size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-broken-fg" />
        <span>
          <strong className="font-extrabold">
            {job.kind === "subtitles"
              ? `No English subtitles for ${job.label}.`
              : job.kind === "merge"
                ? `No English added to ${job.label}.`
                : `${job.label} failed.`}
          </strong>{" "}
          <span className="text-fg-soft">
            {job.problem}
            {job.fastInstead && fastOffer(fast, system.data?.subtitles.bestWants === "directx")}
            {job.kind === "subtitles" && " The video is as it was."}
          </span>
        </span>
      </span>
      {said.length > 0 && (
        <div className="overflow-x-auto rounded-12 bg-inset px-3 py-2.5 font-mono text-11 text-fg-muted leading-[1.7]">
          {said.map((line, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: the same line may come twice
            <div key={index} className="whitespace-pre">
              {line}
            </div>
          ))}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {job.kind === "convert" && (
          <Button
            size="sm"
            variant="primary"
            disabled={action.isPending}
            onClick={() => action.mutate({ path: `/queue/${job.id}/broken` })}
          >
            Mark as broken
          </Button>
        )}
        {job.fastInstead && (
          <Button
            size="sm"
            variant="primary"
            disabled={action.isPending}
            onClick={() =>
              action.mutate({ path: `/queue/${job.id}/retry`, body: { quality: "fast" } })
            }
          >
            Make them with Fast
          </Button>
        )}
        <Button
          size="sm"
          variant={job.kind === "convert" || job.fastInstead ? undefined : "primary"}
          disabled={action.isPending}
          onClick={() => action.mutate({ path: `/queue/${job.id}/retry` })}
        >
          Try again
        </Button>
        {job.log && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              void navigator.clipboard.writeText(job.log ?? "").then(() => setCopied(true))
            }
          >
            {copied ? "Copied" : "Copy full log"}
          </Button>
        )}
      </div>
      <Problem error={asked("retry") || asked("broken") ? action.error : null} />
    </div>
  );
}

/** What Fast offers after Best failed: less memory, or the processor where DirectX 12 isn't. */
function fastOffer(seconds: number | null, processor: boolean): string {
  const time = seconds ? `about ${inWords(seconds)} an hour of video` : "";
  return processor
    ? ` Fast runs on the processor here${time ? `, ${time}` : ""}.`
    : ` Fast needs less${time ? `, and takes ${time} here` : ""}.`;
}

/** "4 minutes", "an hour", "2 hours": a time said in words. */
function inWords(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.round(minutes / 60);
  return hours === 1 ? "an hour" : `${hours} hours`;
}

/** Why something asked of the queue didn't happen, when it didn't. */
function Problem({ error, className }: { error: Error | null; className?: string }) {
  if (!error) return null;
  return (
    <p role="alert" className={cn("text-13 text-broken-fg", className)}>
      {error.message}
    </p>
  );
}

function Figure({ value, label }: { value: string; label: string }) {
  return (
    <span className="flex flex-col">
      <span className="font-extrabold text-22">{value}</span>
      <span className="text-12 text-fg-muted">{label}</span>
    </span>
  );
}

function sum(jobs: Job[]): number {
  return jobs.reduce((total, job) => total + job.gpuSeconds, 0);
}
