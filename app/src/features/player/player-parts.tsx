import { Captions, Check, HardDrive, Play, TriangleAlert } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import type { ComponentProps, ReactNode } from "react";
import { Button } from "@/components/ui/button";
import type { ChapterMark, OpenedVideo, PlayerState } from "@/lib/engine";
import { cn } from "@/lib/utils";
import { playTime, soundWords, subtitleWords } from "./tracks";

/** A round button over the picture: an icon, named for screen readers. */
export function RoundButton({
  label,
  size = "sm",
  className,
  children,
  ...props
}: ComponentProps<"button"> & { label: string; size?: "sm" | "md" | "lg" }) {
  return (
    <button
      type="button"
      aria-label={label}
      className={cn(
        "press inline-flex shrink-0 cursor-pointer items-center justify-center rounded-full text-white disabled:pointer-events-none disabled:opacity-50",
        size === "sm" ? "size-8.5" : size === "md" ? "size-11" : "size-12",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

/** Where it plays: the amber part played, the knob where it is, the chapters marked. Dragging
 * or the arrow keys move it; the video plays from there once it's let go. */
export function SeekBar(props: {
  at: number;
  duration: number;
  chapters: ChapterMark[];
  large: boolean;
  onSeek: (to: number, now: boolean) => void;
}) {
  const { at, duration, large } = props;
  const share = duration > 0 ? Math.min(100, (at / duration) * 100) : 0;
  return (
    <span className={cn("relative flex flex-1 items-center", large ? "h-4" : "h-3")}>
      <span
        aria-hidden="true"
        className={cn(
          "absolute inset-x-0 overflow-hidden rounded-full bg-tint/22",
          large ? "h-1.5" : "h-1",
        )}
      >
        <span className="absolute inset-y-0 left-0 bg-accent" style={{ width: `${share}%` }} />
        {large &&
          props.chapters
            .filter((chapter) => chapter.start > 0 && chapter.start < duration)
            .map((chapter) => (
              <span
                key={chapter.start}
                className="absolute inset-y-0 w-0.5 bg-black"
                style={{ left: `${(chapter.start / duration) * 100}%` }}
              />
            ))}
      </span>
      <input
        type="range"
        min={0}
        max={Math.max(duration, 1)}
        step={1}
        value={Math.min(Math.floor(at), Math.max(duration, 1))}
        aria-label="Where it plays"
        aria-valuetext={`${playTime(at)} of ${playTime(duration)}`}
        onChange={(event) => props.onSeek(Number(event.currentTarget.value), false)}
        onPointerUp={(event) => props.onSeek(Number(event.currentTarget.value), true)}
        className={cn(
          "relative w-full cursor-pointer appearance-none bg-transparent",
          "[&::-webkit-slider-runnable-track]:h-full [&::-webkit-slider-thumb]:appearance-none",
          "[&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent",
          large ? "h-4 [&::-webkit-slider-thumb]:size-4" : "h-3 [&::-webkit-slider-thumb]:size-3",
        )}
      />
    </span>
  );
}

/** Sound and subtitles: one of each, as the file has them; subtitles getting ready say so. */
export function TracksMenu(props: {
  video: OpenedVideo;
  state: PlayerState | undefined;
  sound: number | null;
  subtitles: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSound: (sound: number) => void;
  onSubtitles: (subtitles: number | null) => void;
  size: "sm" | "md";
}) {
  const { video } = props;
  return (
    <DropdownMenu.Root open={props.open} onOpenChange={props.onOpenChange}>
      <DropdownMenu.Trigger asChild>
        <RoundButton
          label="Sound and subtitles"
          size={props.size}
          className={cn(props.open && "bg-tint/14")}
        >
          <Captions size={props.size === "sm" ? 17 : 20} strokeWidth={1.8} aria-hidden="true" />
        </RoundButton>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side="top"
          align="end"
          sideOffset={10}
          className="scheme-dark z-60 flex w-75 max-w-[calc(100vw-32px)] flex-col gap-1 rounded-18 border border-tint/10 bg-dialog p-2.5 text-fg shadow-dialog"
        >
          {video.sound.length > 0 && (
            <>
              <Heading>Sound</Heading>
              <DropdownMenu.RadioGroup
                value={String(props.sound)}
                onValueChange={(value) => props.onSound(Number(value))}
              >
                {video.sound.map((track) => (
                  <Choice
                    key={track.number}
                    value={String(track.number)}
                    words={soundWords(track)}
                  />
                ))}
              </DropdownMenu.RadioGroup>
              <DropdownMenu.Separator className="mx-2.5 my-1.5 h-px bg-tint/6" />
            </>
          )}
          <Heading>Subtitles</Heading>
          <DropdownMenu.RadioGroup
            value={props.subtitles === null ? "off" : String(props.subtitles)}
            onValueChange={(value) => props.onSubtitles(value === "off" ? null : Number(value))}
          >
            {video.subtitles.map((track) => (
              <Choice
                key={track.number}
                value={String(track.number)}
                words={subtitleWords(track, props.state)}
              />
            ))}
            <Choice value="off" words={["Off", null]} />
          </DropdownMenu.RadioGroup>
          {video.subtitles.some((track) => track.made) && (
            <span className="px-2.5 pt-1.5 pb-1 text-12 text-fg-faint">
              Maku made the English ones from the sound: names and jokes can be off.
            </span>
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function Heading({ children }: { children: ReactNode }) {
  return (
    <DropdownMenu.Label className="px-2.5 pt-1.5 pb-0.5 font-extrabold text-11 text-fg-muted uppercase tracking-[0.06em]">
      {children}
    </DropdownMenu.Label>
  );
}

function Choice({ value, words }: { value: string; words: [string, string | null] }) {
  const [name, detail] = words;
  return (
    <DropdownMenu.RadioItem
      value={value}
      className="group flex min-h-10 cursor-pointer items-center gap-2.5 rounded-12 px-2.5 font-bold text-13 text-fg-soft outline-none data-highlighted:bg-tint/6 data-[state=checked]:bg-accent/12 data-[state=checked]:text-accent-fg"
    >
      <span className="flex w-3.5 shrink-0 justify-center">
        <DropdownMenu.ItemIndicator>
          <Check size={14} strokeWidth={3} aria-hidden="true" />
        </DropdownMenu.ItemIndicator>
      </span>
      <span className="flex-1">{name}</span>
      {detail && (
        <span className="font-medium text-12 text-fg-muted group-data-[state=checked]:text-accent-fg">
          {detail}
        </span>
      )}
    </DropdownMenu.RadioItem>
  );
}

/** Before the first picture: the file being read. */
export function GettingReady({ drive }: { drive: string }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2.5 bg-inset">
      <span role="status" className="font-extrabold text-14">
        Getting it ready
      </span>
      <span aria-hidden="true" className="relative h-1 w-40 overflow-hidden rounded-2 bg-tint/14">
        <span className="absolute inset-0 animate-shimmer bg-linear-to-r from-transparent via-accent to-transparent" />
      </span>
      {drive && <span className="text-12 text-fg-muted">Reading the file from {drive}</span>}
    </div>
  );
}

/** Why it won't play, and what to do: a damaged file, a drive unplugged, a file gone. */
export function Stopped(props: {
  icon: "alert" | "drive";
  title: string;
  children: ReactNode;
  action?: { label: string; play?: boolean; onClick: () => void };
  onClose: () => void;
}) {
  const Icon = props.icon === "drive" ? HardDrive : TriangleAlert;
  return (
    <div className="absolute inset-0 flex flex-col justify-center gap-2.5 bg-inset px-5.5">
      <span role={props.icon === "drive" ? "status" : "alert"} className="flex items-start gap-2.5">
        <Icon
          size={18}
          strokeWidth={2}
          aria-hidden="true"
          className={cn(
            "mt-0.5 shrink-0",
            props.icon === "drive" ? "text-fg-muted" : "text-broken-fg",
          )}
        />
        <span className="flex flex-col gap-0.5">
          <strong className="font-extrabold text-14">{props.title}</strong>
          <span className="text-13 text-fg-soft">{props.children}</span>
        </span>
      </span>
      <span className="flex flex-wrap gap-2 pl-7">
        {props.action && (
          <Button size="sm" onClick={props.action.onClick}>
            {props.action.play && <Play size={12} fill="currentColor" aria-hidden="true" />}
            {props.action.label}
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={props.onClose}>
          Close
        </Button>
      </span>
    </div>
  );
}
