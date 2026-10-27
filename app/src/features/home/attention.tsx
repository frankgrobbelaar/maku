import {
  ArrowRight,
  Captions,
  CircleHelp,
  FileWarning,
  FolderTree,
  ListX,
  ShieldAlert,
} from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface AttentionProps {
  /** Files Maku couldn't place surely. */
  waiting: number;
  /** Episodes aired that the library doesn't hold, and across how many series. */
  missing: number;
  missingIn: number;
  /** Files that couldn't be read. */
  broken: number;
  /** Folders holding more than one series or film. */
  mixed: number;
  /** Videos the overnight health check couldn't play. */
  unplayed: number;
  /** Videos that can't be heard or read in English, and across how many titles. */
  noEnglish: number;
  noEnglishIn: number;
  onSubtitles: () => void;
  onMatch: () => void;
  onMissing: () => void;
  onUnplayed: () => void;
}

/** What needs the owner, as the home board shows it; nothing changes until they review it. */
export function Attention(props: AttentionProps) {
  const cards: ReactNode[] = [];
  if (props.waiting > 0) {
    cards.push(
      <Card
        key="match"
        icon={<CircleHelp size={18} />}
        title={`${count(props.waiting)} ${props.waiting === 1 ? "file needs" : "files need"} a match`}
        text="Maku couldn't tell which series or film they are"
        action="Match files"
        onClick={props.onMatch}
      />,
    );
  }
  if (props.missing > 0) {
    cards.push(
      <Card
        key="missing"
        icon={<ListX size={18} />}
        title={`${count(props.missing)} ${props.missing === 1 ? "episode" : "episodes"} missing`}
        text={`Across ${count(props.missingIn)} series · gap reports updated`}
        action="Most missing first"
        onClick={props.onMissing}
      />,
    );
  }
  if (props.noEnglish > 0) {
    cards.push(
      <Card
        key="english"
        icon={<Captions size={18} />}
        title={`${count(props.noEnglish)} ${props.noEnglish === 1 ? "video has" : "videos have"} no English`}
        text={`Across ${count(props.noEnglishIn)} ${props.noEnglishIn === 1 ? "title" : "titles"} · Maku can make English subtitles from their sound`}
        action="Make English subtitles"
        onClick={props.onSubtitles}
      />,
    );
  }
  if (props.unplayed > 0) {
    cards.push(
      <Card
        key="unplayed"
        icon={<ShieldAlert size={18} />}
        title={`${count(props.unplayed)} ${props.unplayed === 1 ? "video" : "videos"} didn't play`}
        text="In the overnight health check · nothing changes till you say"
        action="See which"
        onClick={props.onUnplayed}
      />,
    );
  }
  if (props.broken > 0) {
    cards.push(
      <Card
        key="broken"
        icon={<FileWarning size={18} />}
        title={`${count(props.broken)} ${props.broken === 1 ? "file won't" : "files won't"} play`}
        text="Damaged or not videos · each title shows which"
      />,
    );
  }
  if (props.mixed > 0) {
    cards.push(
      <Card
        key="mixed"
        icon={<FolderTree size={18} />}
        title={`${count(props.mixed)} ${props.mixed === 1 ? "folder holds" : "folders hold"} several titles`}
        text="Sorting them into folders comes with Tidy up"
      />,
    );
  }
  if (cards.length === 0) return null;

  return (
    <section
      aria-labelledby="attention-title"
      className="flex animate-fade-up flex-col gap-3.5 [animation-delay:60ms]"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="attention-title" className="type-heading">
          Needs your attention
        </h2>
        <span className="text-13 text-fg-muted">Nothing changes until you review it</span>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3">{cards}</div>
    </section>
  );
}

function Card(props: {
  icon: ReactNode;
  title: string;
  text: string;
  action?: string;
  onClick?: () => void;
}) {
  const body = (
    <>
      <span
        aria-hidden="true"
        className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-accent/12 text-accent-fg"
      >
        {props.icon}
      </span>
      <span className="flex flex-col gap-0.5">
        <span className="font-extrabold text-15">{props.title}</span>
        <span className="text-12 text-fg-muted">{props.text}</span>
      </span>
      {props.action && (
        <span className="mt-auto inline-flex items-center gap-1.5 font-bold text-13 text-accent-fg">
          {props.action}
          <ArrowRight size={14} aria-hidden="true" />
        </span>
      )}
    </>
  );
  const look =
    "flex h-full flex-col gap-3 rounded-20 border border-edge bg-glass px-4.5 py-4 text-left shadow-panel";
  if (!props.onClick) return <div className={look}>{body}</div>;
  return (
    <button type="button" onClick={props.onClick} className={cn(look, "lift cursor-pointer")}>
      {body}
    </button>
  );
}

function count(value: number): string {
  return value.toLocaleString("en-GB");
}
