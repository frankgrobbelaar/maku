import { Check, FolderTree, Pause, Play, Timer } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { EngineProblem } from "@/components/engine-problem";
import { Poster } from "@/components/poster";
import { Loading, PanelSkeleton } from "@/components/skeleton";
import { NoTmdbKey } from "@/components/tmdb-key";
import { Button } from "@/components/ui/button";
import { type Scan, useFolders, useScan, useScanAction, useTitles, useTmdb } from "@/lib/engine";
import { scanChanges } from "@/lib/format";
import { files, kindWord } from "@/lib/kinds";
import { cn } from "@/lib/utils";

/** The scan: finding every video, reading it, identifying it, then checking. Nothing is moved. */
export function ScanPage() {
  const scan = useScan();
  const folders = useFolders();
  const action = useScanAction();
  const navigate = useNavigate();
  // Without a TMDB key the scan finds no series or film, and its note says so: the notice says
  // the same, with the way to the key.
  const noKey = useTmdb().data?.connected === false;

  if (!scan.data || !folders.data) {
    return (
      <>
        <h1 className="page-top type-title animate-fade-up">Scan</h1>
        <EngineProblem queries={[scan, folders]} />
        <Loading label="Loading the scan" queries={[scan, folders]}>
          <PanelSkeleton rows={4} />
        </Loading>
      </>
    );
  }
  const now = scan.data;
  const where = mapping(folders.data.map((folder) => folder.path));
  const send = (path: string) => action.mutate({ path });

  return (
    <>
      <header className="page-top flex animate-fade-up flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <span className="type-eyebrow">{eyebrow(now)}</span>
          <h1 className="type-title">
            {now.state === "done" ? "Mapped" : "Mapping"} {where}
          </h1>
          <p className="text-14 text-fg-muted">{subtitle(now)}</p>
        </div>
        <div className="flex flex-wrap gap-2.5">
          {now.state === "running" && (
            <Button disabled={action.isPending} onClick={() => send("/scan/pause")}>
              <Pause size={16} aria-hidden="true" />
              Pause scan
            </Button>
          )}
          {now.state === "paused" && (
            <Button
              variant="primary"
              disabled={action.isPending}
              onClick={() => send("/scan/resume")}
            >
              <Play size={16} aria-hidden="true" />
              Resume scan
            </Button>
          )}
          {(now.state === "done" || now.state === "failed" || now.state === "idle") && (
            <Button disabled={action.isPending} onClick={() => send("/scan")}>
              Scan again
            </Button>
          )}
          {now.state === "done" && now.waiting > 0 ? (
            <Button variant="primary" onClick={() => void navigate("/match")}>
              Match {files(now.waiting)}
            </Button>
          ) : (
            <Button
              variant={now.state === "paused" ? "secondary" : "primary"}
              onClick={() => void navigate("/")}
            >
              {now.state === "running" ? "Keep using Maku" : "Go to Home"}
            </Button>
          )}
        </div>
      </header>

      <EngineProblem queries={[scan, folders]} />
      {action.isError && (
        <p role="alert" className="text-13 text-broken-fg">
          {action.error.message}
        </p>
      )}
      {now.state === "failed" && now.problem && (
        <Failed problem={now.problem} onTools={() => void navigate("/setup?step=tools")} />
      )}
      {now.unavailable.map((path) => (
        <p
          key={path}
          role="status"
          className="animate-fade-up rounded-18 border border-edge bg-glass px-4.5 py-3.5 text-14 shadow-panel"
        >
          <strong>{path} isn't connected.</strong> Maku scans it when the drive is back, and its
          files stay as they were.
        </p>
      ))}
      {now.state === "done" && noKey && <NoTmdbKey />}
      {now.state === "done" && now.note && !noKey && (
        <p
          role="status"
          className="animate-fade-up rounded-18 border border-edge bg-glass px-4.5 py-3.5 text-14 shadow-panel"
        >
          {now.note}
        </p>
      )}

      <Progress scan={now} />
      <FoundSoFar running={now.state === "running"} />

      <div className="grid animate-fade-up grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-4 [animation-delay:200ms]">
        <Note icon={<FolderTree size={18} />} title="Any folder layout works">
          One folder per series or film, seasons in sub-folders, or everything mixed in Downloads.
          Each file is identified on its own, then grouped by title.
        </Note>
        <Note icon={<Timer size={18} />} title="Stop any time">
          A paused or interrupted scan carries on where it stopped. Later scans only read new and
          changed files, so they take seconds.
        </Note>
      </div>
    </>
  );
}

const STAGES = ["finding", "reading", "identifying", "checking", "done"] as const;

function Progress({ scan }: { scan: Scan }) {
  const percent =
    scan.stage === "finding" || scan.toRead === 0
      ? scan.stage === "finding" || scan.stage === null
        ? 0
        : 100
      : Math.round((scan.read / scan.toRead) * 100);
  const at = STAGES.indexOf(scan.stage ?? "finding");
  const step = (index: number) => (index < at ? "done" : index === at ? "now" : "later");
  const finding = scan.stage === "finding";
  const settled = scan.state === "done";

  return (
    <section
      aria-label="Scan progress"
      className="flex animate-fade-up flex-col gap-6 rounded-24 border border-edge bg-glass p-7 shadow-panel [animation-delay:120ms]"
    >
      <div className="flex flex-wrap items-center gap-8">
        <Ring percent={percent} read={scan.read} toRead={scan.toRead} />
        <ol className="flex flex-[1_1_280px] flex-col gap-4">
          <StepLine
            state={step(0)}
            title="Find every file"
            text={
              scan.found
                ? `${count(scan.found)} ${scan.found === 1 ? "video" : "videos"}`
                : "Looking through your folders"
            }
          />
          <StepLine
            state={step(1)}
            title="Read length and quality"
            text="Resolution, codecs, audio and subtitle languages"
          />
          <StepLine
            state={step(2)}
            title="Identify each series, film and episode"
            text="Names, runtimes and numbering, checked against TMDB"
          />
          <StepLine
            state={step(3)}
            title="Check health and gaps"
            text="Missing episodes, broken files, mixed folders"
          />
          <StepLine
            state={settled ? "done" : "later"}
            title="Write the reports"
            text="A gap analysis file next to each title"
          />
        </ol>
        <div className="grid flex-[1_1_260px] grid-cols-2 gap-2.5">
          <Tile value={scan.titles} label={settled ? "titles found" : "titles found so far"} />
          <Tile
            value={scan.waiting}
            label={scan.waiting === 1 ? "file needs a match" : "files need a match"}
          />
          <Tile
            value={scan.mixed}
            label={scan.mixed === 1 ? "folder with several titles" : "folders with several titles"}
          />
          <Tile value={scan.problems} label={settled ? "broken files" : "broken files so far"} />
        </div>
      </div>
      <div className="flex flex-col gap-2.5">
        <div className="h-1.5 overflow-hidden rounded-3 bg-track">
          <div
            className="h-full rounded-3 bg-accent transition-[width] duration-320 ease-cinema"
            style={{ width: `${percent}%` }}
          />
        </div>
        {scan.current && (
          <p className="flex min-w-0 items-center gap-2 text-12 text-fg-muted">
            <span
              aria-hidden="true"
              className="size-1.5 shrink-0 animate-pulse rounded-full bg-accent"
            />
            {finding ? "Looking at" : scan.stage === "identifying" ? "Looking up" : "Reading"}
            <span className="truncate font-mono text-fg-soft">{scan.current}</span>
          </p>
        )}
      </div>
    </section>
  );
}

/** The series and films identified so far, oldest release first, artwork and all. */
function FoundSoFar({ running }: { running: boolean }) {
  const titles = useTitles("released", running);
  if (!titles.data?.length) return null;

  return (
    <section
      aria-labelledby="found-title"
      className="flex animate-fade-up flex-col gap-3.5 [animation-delay:160ms]"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="found-title" className="font-extrabold text-20 tracking-[-0.01em]">
          {running ? "Found so far" : "Found"}
        </h2>
        <span className="text-13 text-fg-muted">
          {running ? "Artwork appears as each title is recognised" : "Oldest release first"}
        </span>
      </div>
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(132px,1fr))] gap-x-4 gap-y-4.5">
        {titles.data.map((title) => (
          <li key={title.id} className="animate-pop">
            <Link to={`/titles/${title.id}`} className="lift flex flex-col gap-2 rounded-14">
              <Poster title={title} />
              <span className="flex flex-col gap-px px-0.5">
                <span className="truncate font-bold text-13">{title.name}</span>
                <span className="text-12 text-fg-muted">
                  {kindWord(title.kind, true)} · {files(title.files)}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Ring({ percent, read, toRead }: { percent: number; read: number; toRead: number }) {
  const circumference = 2 * Math.PI * 70;
  return (
    <div className="relative size-40 shrink-0">
      <svg viewBox="0 0 160 160" className="-rotate-90 size-40" aria-hidden="true">
        <circle cx="80" cy="80" r="70" fill="none" strokeWidth="10" className="stroke-track" />
        <circle
          cx="80"
          cy="80"
          r="70"
          fill="none"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - percent / 100)}
          className="stroke-accent transition-[stroke-dashoffset] duration-600 ease-cinema"
        />
      </svg>
      <div
        role="progressbar"
        aria-label="Files read"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        className="absolute inset-0 flex flex-col items-center justify-center"
      >
        <span className="font-extrabold text-36 tracking-[-0.02em]">{percent}%</span>
        {toRead > 0 && (
          <span className="font-mono text-11 text-fg-muted">
            {count(read)} / {count(toRead)}
          </span>
        )}
      </div>
    </div>
  );
}

function StepLine(props: { state: "done" | "now" | "later"; title: string; text: string }) {
  return (
    <li className="flex items-start gap-3">
      <span
        aria-hidden="true"
        className={cn(
          "mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full",
          props.state === "done" && "bg-accent text-on-accent",
          props.state === "now" && "border-2 border-accent",
          props.state === "later" && "border-2 border-line-strong",
        )}
      >
        {props.state === "done" && <Check size={13} strokeWidth={3.4} />}
        {props.state === "now" && <span className="size-2 animate-pulse rounded-full bg-accent" />}
      </span>
      <span className="flex flex-col">
        <span
          className={cn(
            "font-extrabold text-14",
            props.state === "now" && "text-accent-fg",
            props.state === "later" && "text-fg-muted",
          )}
        >
          {props.title}
          <span className="sr-only">
            {props.state === "done"
              ? ", done"
              : props.state === "now"
                ? ", in progress"
                : ", to come"}
          </span>
        </span>
        <span className="text-12 text-fg-muted">{props.text}</span>
      </span>
    </li>
  );
}

function Tile({ value, label }: { value: number; label: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-16 bg-tint/4 px-4 py-3.5">
      <span className="font-extrabold text-26 tracking-[-0.02em]">{count(Math.max(value, 0))}</span>
      <span className="text-12 text-fg-muted">{label}</span>
    </div>
  );
}

function Failed({ problem, onTools }: { problem: string; onTools: () => void }) {
  const needsTools = problem.includes("ffmpeg");
  return (
    <section
      role="alert"
      className="flex animate-fade-up flex-col gap-3 rounded-18 border border-broken/26 bg-broken/7 px-4.5 py-4"
    >
      <p>{problem}</p>
      {needsTools && (
        <div>
          <Button variant="primary" size="sm" onClick={onTools}>
            Get ffmpeg
          </Button>
        </div>
      )}
    </section>
  );
}

function Note({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="flex items-start gap-3.5 rounded-20 border border-edge bg-glass px-5 py-4.5 shadow-panel">
      <span
        aria-hidden="true"
        className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-accent/12 text-accent-fg"
      >
        {icon}
      </span>
      <div className="flex flex-col gap-1">
        <h2 className="font-extrabold text-14">{title}</h2>
        <p className="text-13 text-fg-muted">{children}</p>
      </div>
    </section>
  );
}

function eyebrow(scan: Scan): string {
  if (scan.state === "done") return "Scan finished";
  if (scan.state === "paused") return "Scan paused";
  if (scan.state === "failed") return "Scan stopped";
  return "Scanning";
}

function subtitle(scan: Scan): string {
  const started = scan.startedAt ? `Started ${clock(scan.startedAt)}` : "Not scanned yet";
  switch (scan.state) {
    case "running":
      if (scan.stage === "identifying") {
        return `${started} · looking up each series and film · nothing is renamed or moved`;
      }
      return `${started} · ${timeLeft(scan.secondsLeft)} · nothing is renamed or moved`;
    case "paused":
      return `Paused · ${count(scan.read)} of ${count(scan.toRead)} read · nothing is renamed or moved`;
    case "done":
      return [
        `${count(scan.found)} ${scan.found === 1 ? "video" : "videos"}`,
        scan.added !== null && scan.gone !== null && scanChanges(scan.added, scan.gone),
        `finished ${scan.finishedAt ? clock(scan.finishedAt) : ""}`,
        "nothing was renamed or moved",
      ]
        .filter(Boolean)
        .join(" · ");
    case "failed":
      return `${started} · nothing was renamed or moved`;
    case "idle":
      return "Nothing is renamed or moved: a scan only looks.";
  }
}

function mapping(paths: string[]): string {
  if (paths.length === 0) return "your folders";
  if (paths.length === 1) return paths[0] ?? "";
  return `${paths.length} folders`;
}

function timeLeft(seconds: number | null): string {
  if (seconds === null) return "working out the time left";
  if (seconds < 60) return "less than a minute left";
  const minutes = Math.round(seconds / 60);
  return minutes === 1 ? "about a minute left" : `about ${minutes} minutes left`;
}

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function count(value: number): string {
  return value.toLocaleString("en-GB");
}
