import { AudioLines, ChevronLeft, ChevronRight, Eye, Play } from "lucide-react";
import { type MouseEvent, type ReactNode, useLayoutEffect, useRef, useState } from "react";
import { Synopsis } from "@/components/about";
import { FileNote, useFileActions } from "@/components/file-actions";
import { Skeleton } from "@/components/skeleton";
import { StatusShape } from "@/components/status";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogPicture,
  DialogTitle,
} from "@/components/ui/dialog";
import { MenuItem, RowMenu } from "@/components/ui/menu";
import { usePlayingFile } from "@/features/player/player-context";
import {
  type EpisodeState,
  type FileDetails,
  type TitleDetail,
  useEpisodeDetails,
  useEpisodePicture,
  useFileDetails,
  useFilePicture,
  useMarkWatched,
} from "@/lib/engine";
import { clockTime, codecName, languageName, size, split } from "@/lib/format";
import { kindWord } from "@/lib/kinds";
import { cn } from "@/lib/utils";

/** What the card tells of: one of the title's videos, or one of its episodes, which the library
 * may not have. */
export type Opened = { video: number } | { episode: { season: number; number: number } };

/** The video or episode before or after the one open, to go to without closing. */
export interface Step {
  opened: Opened;
  /** "S01E04", or none for a video without an episode. */
  code: string | null;
  name: string;
}

/** One video or episode in full, in a card over the title's page with a picture from it across
 * its top: Play on the picture, what happens in it (hidden till asked, as it gives the story away),
 * what the file holds and where it is, what converting it does, and the ones before and after it
 * at its foot. */
export function VideoDetails(props: {
  title: TitleDetail;
  opened: Opened | null;
  before: Step | null;
  after: Step | null;
  onOpen: (opened: Opened) => void;
  onClose: () => void;
  onPlay: (fileId: number) => void;
}) {
  const { title, opened } = props;
  const asked = opened && "episode" in opened ? opened.episode : null;
  const listed = asked
    ? title.episodes.find((each) => each.season === asked.season && each.number === asked.number)
    : undefined;
  const fileId = opened && "video" in opened ? opened.video : (listed?.fileId ?? null);
  return (
    <Dialog open={opened !== null} onOpenChange={(open) => !open && props.onClose()}>
      {opened && (
        <DialogContent>
          {/* Each video or episode afresh: its picture, its story hidden again, scrolled to the top. */}
          {fileId !== null ? (
            <VideoCard
              key={`video ${fileId}`}
              title={title}
              fileId={fileId}
              onPlay={() => props.onPlay(fileId)}
            />
          ) : (
            asked && (
              <EpisodeCard
                key={`episode ${asked.season} ${asked.number}`}
                title={title}
                episode={asked}
                listed={listed}
              />
            )
          )}
          <Steps before={props.before} after={props.after} onOpen={props.onOpen} />
        </DialogContent>
      )}
    </Dialog>
  );
}

/** A video in the library: Play on its picture, then its episode, the file and what it holds. */
function VideoCard(props: { title: TitleDetail; fileId: number; onPlay: () => void }) {
  const { title, fileId } = props;
  const file = useFileDetails(fileId);
  const picture = useFilePicture(fileId);
  const playing = usePlayingFile() === fileId;
  const actions = useFileActions();
  const mark = useMarkWatched();
  const found = file.data;
  // What the page knows already shows at once; the file's own details fill in.
  const video = title.videos.find((each) => each.id === fileId);
  const season = found?.season ?? video?.season ?? null;
  const number = found?.episode ?? video?.episode ?? null;
  const listed = episodeOf(title, season, number);
  const shown =
    season !== null && number !== null
      ? code(season, number, found?.episodeEnd ?? video?.episodeEnd ?? null)
      : null;
  const path = found?.path ?? video?.path ?? null;
  const name = found?.episodeName ?? listed?.name ?? (path ? split(path)[0] : "…");
  const aired = found?.aired ?? listed?.aired ?? null;
  const duration = found?.duration ?? video?.duration ?? null;
  const resume = video?.resume ?? null;
  const problem = found ? found.problem : (video?.problem ?? null);
  const left =
    resume !== null && duration
      ? `${Math.max(1, Math.round((duration - resume) / 60))} min left`
      : null;
  return (
    <>
      <DialogPicture
        src={picture.address}
        none={picture.problem !== null}
        // A picture from the episode can give its story away: blurred till asked, till it's watched.
        spoiler={picture.source === "episode" && !video?.watched}
        tag={tagOf(title, season, shown)}
        progress={resume !== null && duration ? Math.min(1, resume / duration) : null}
      >
        {!problem &&
          (playing ? (
            <span className="inline-flex min-h-11 items-center gap-2 rounded-full bg-tag px-5 font-extrabold text-14 text-accent-fg">
              <AudioLines size={16} strokeWidth={2.2} aria-hidden="true" />
              Playing
            </span>
          ) : (
            <Button variant="primary" onClick={props.onPlay}>
              <Play size={15} fill="currentColor" aria-hidden="true" />
              {resume !== null ? `Play from ${clockTime(resume)}` : "Play"}
            </Button>
          ))}
      </DialogPicture>
      <DialogBody>
        <div className="flex items-start gap-3">
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <DialogTitle
              aria-label={shown ? `${shown} · ${name}` : undefined}
              className="text-24 tracking-[-0.02em] [overflow-wrap:anywhere]"
            >
              {name}
            </DialogTitle>
            <DialogDescription>
              {[title.name, aired ? `aired ${day(aired)}` : null].filter(Boolean).join(" · ")}
              {left ? (
                <>
                  {" · "}
                  <strong className="font-bold text-accent-fg">{left}</strong>
                </>
              ) : (
                video?.watched && " · watched"
              )}
            </DialogDescription>
          </div>
          {path && (
            <div className="flex shrink-0 items-center gap-1">
              <Button size="sm" onClick={() => actions.show(path)}>
                Show in folder
              </Button>
              <RowMenu label={`More for ${shown ?? name}`}>
                <MenuItem onSelect={() => actions.copy(path)}>Copy path</MenuItem>
                {video && (
                  <MenuItem
                    onSelect={() =>
                      mark.mutate({
                        path: "/files/watched",
                        body: { files: [video.id], watched: !video.watched },
                      })
                    }
                  >
                    {video.watched ? "Mark as not watched" : "Mark as watched"}
                  </MenuItem>
                )}
              </RowMenu>
            </div>
          )}
        </div>
        <FileNote actions={actions} />
        {mark.isError && (
          <p role="alert" className="text-13 text-broken-fg">
            {mark.error.message}
          </p>
        )}
        {problem && (
          <p className="rounded-14 border border-broken/40 bg-broken/8 px-3.5 py-2.5 text-13">
            It won't play: {problem}
          </p>
        )}
        {found ? (
          <>
            {found.overview && <WhatHappens text={found.overview} />}
            <TheFile file={found} />
          </>
        ) : file.isError ? (
          <p role="alert" className="text-13 text-broken-fg">
            {file.error.message}
          </p>
        ) : (
          <FileSkeleton />
        )}
      </DialogBody>
    </>
  );
}

/** An episode the library hasn't got, or one still to come: its title on its picture, when it
 * aired, and what happens in it. */
function EpisodeCard(props: {
  title: TitleDetail;
  episode: { season: number; number: number };
  listed: EpisodeState | undefined;
}) {
  const { title, episode, listed } = props;
  const details = useEpisodeDetails(title.id, episode.season, episode.number);
  const picture = useEpisodePicture(title.id, episode);
  const coming = listed?.state === "upcoming";
  const name = details.data?.name ?? listed?.name ?? `Episode ${episode.number}`;
  const aired = details.data?.aired ?? listed?.aired ?? null;
  const minutes = details.data?.minutes ?? null;
  const numbered = code(episode.season, episode.number);
  const when = [
    aired ? `${coming ? "Airs" : "Aired"} ${day(aired)}` : null,
    minutes ? `${minutes} min` : null,
  ].filter(Boolean);
  return (
    <>
      <DialogPicture
        src={picture.address}
        none={picture.problem !== null}
        // Not in the library, so not watched: a picture from it stays blurred till asked.
        spoiler={picture.source === "episode"}
        tag={tagOf(title, episode.season, numbered)}
      >
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="truncate font-bold text-12 text-fg-soft">{title.name}</span>
          <DialogTitle
            aria-label={`${numbered} · ${name}`}
            className="line-clamp-2 text-26 tracking-[-0.02em] [overflow-wrap:anywhere]"
          >
            {name}
          </DialogTitle>
        </div>
      </DialogPicture>
      <DialogBody>
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="inline-flex h-6 items-center gap-1.5 rounded-full bg-tint/6 px-2.5 font-extrabold text-11">
            <StatusShape state={coming ? "upcoming" : "missing"} className="size-2" />
            {coming ? "Not out yet" : "Not in your library"}
          </span>
          <DialogDescription>
            {when.length > 0 ? when.join(" · ") : "No air date known"}
          </DialogDescription>
        </div>
        {details.data?.overview && <WhatHappens text={details.data.overview} />}
        {details.isError && (
          <p role="alert" className="text-13 text-broken-fg">
            {details.error.message}
          </p>
        )}
      </DialogBody>
    </>
  );
}

/** The video or episode before it and after it, at the card's foot. */
function Steps(props: { before: Step | null; after: Step | null; onOpen: (to: Opened) => void }) {
  const { before, after } = props;
  const foot = useRef<HTMLDivElement>(null);
  // Gone to the first or the last from the keyboard: the button it was on goes, and the focus
  // moves to the one left rather than out of reach.
  const kept = useRef(false);
  useLayoutEffect(() => {
    if (!kept.current) return;
    kept.current = false;
    if (!foot.current?.contains(document.activeElement))
      foot.current?.querySelector("button")?.focus();
  });
  if (!before && !after) return null;
  const open = (to: Opened, event: MouseEvent<HTMLButtonElement>) => {
    kept.current = document.activeElement === event.currentTarget;
    props.onOpen(to);
  };
  return (
    <DialogFooter at={foot}>
      {before ? <StepButton step={before} back onOpen={open} /> : <span />}
      {after ? <StepButton step={after} onOpen={open} /> : <span />}
    </DialogFooter>
  );
}

function StepButton(props: {
  step: Step;
  back?: boolean;
  onOpen: (to: Opened, event: MouseEvent<HTMLButtonElement>) => void;
}) {
  const { step, back } = props;
  const words = [step.code, step.name].filter(Boolean).join(" · ");
  return (
    <button
      type="button"
      aria-label={`${back ? "Previous" : "Next"}: ${words}`}
      title={words}
      onClick={(event) => props.onOpen(step.opened, event)}
      className={cn(
        "press flex min-h-11 min-w-0 max-w-[48%] cursor-pointer items-center gap-2 rounded-full hover:bg-tint/6",
        back ? "pr-3.5 pl-1.5 text-left" : "flex-row-reverse pr-1.5 pl-3.5 text-right",
      )}
    >
      {back ? (
        <ChevronLeft size={17} strokeWidth={2.2} aria-hidden="true" className="shrink-0" />
      ) : (
        <ChevronRight size={17} strokeWidth={2.2} aria-hidden="true" className="shrink-0" />
      )}
      <span className="flex min-w-0 flex-col leading-snug">
        {step.code && <span className="font-mono text-11 text-fg-muted">{step.code}</span>}
        <span className="truncate font-bold text-13">{step.name}</span>
      </span>
    </button>
  );
}

/** What happens in an episode: hidden till asked, as it gives the story away. Till then a blur
 * stands in for it, its words' shapes and no more, so nothing of it is on the page to read or
 * find. */
function WhatHappens({ text }: { text: string }) {
  const [shown, setShown] = useState(false);
  // The button turns from "Show" to "Hide" and back: the keyboard's focus goes with it.
  const turned = useRef(false);
  const turn = (to: boolean, button: HTMLButtonElement) => {
    turned.current = button === document.activeElement;
    setShown(to);
  };
  const focusTurned = (button: HTMLButtonElement | null) => {
    if (!button || !turned.current) return;
    turned.current = false;
    button.focus();
  };
  if (shown) {
    return (
      <section aria-label="What happens" className="flex flex-col items-start gap-1">
        <Synopsis text={text} lines={6} />
        <Button
          ref={focusTurned}
          size="sm"
          variant="ghost"
          className="-ml-3.5"
          onClick={(event) => turn(false, event.currentTarget)}
        >
          Hide what happens
        </Button>
      </section>
    );
  }
  return (
    <section aria-label="What happens" className="relative overflow-hidden rounded-16 bg-tint/4">
      <p
        aria-hidden="true"
        className="line-clamp-3 select-none px-4 py-3.5 text-14 text-fg-soft leading-relaxed opacity-55 blur-[5px] [overflow-wrap:anywhere]"
      >
        {text.replace(/\S/g, "x")}
      </p>
      <div className="absolute inset-0 flex items-center justify-center">
        <Button
          ref={focusTurned}
          size="sm"
          className="bg-dialog/80"
          onClick={(event) => turn(true, event.currentTarget)}
        >
          <Eye size={15} aria-hidden="true" />
          Show what happens
        </Button>
      </div>
    </section>
  );
}

/** The file: what it holds, where it is, and what converting it does. */
function TheFile({ file }: { file: FileDetails }) {
  const facts: [string, ReactNode][] = [
    ["Picture", picture(file)],
    ["Sound", lines(file.sound.map((track) => sound(track)))],
    ["Subtitles", lines(file.subtitles.map((track) => subtitles(track)))],
    [
      "Size",
      [
        size(file.size),
        file.duration ? clockTime(file.duration) : null,
        file.chapters > 0
          ? `${file.chapters} ${file.chapters === 1 ? "chapter" : "chapters"}`
          : null,
      ]
        .filter(Boolean)
        .join(" · "),
    ],
    ["Found", day(file.foundAt)],
    ["Converting", converting(file)],
  ];
  const shown = facts.filter(([, value]) => value !== null && value !== "");
  return (
    <section aria-label="The file" className="flex flex-col gap-3">
      <dl className="grid grid-cols-2 gap-x-5 gap-y-2.5 text-13">
        {shown.map(([label, value]) => (
          <div key={label} className="flex min-w-0 flex-col">
            <dt className="text-12 text-fg-muted">{label}</dt>
            <dd className="[overflow-wrap:anywhere]">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="font-mono text-12 text-fg-muted [overflow-wrap:anywhere]">{file.path}</p>
    </section>
  );
}

/** The file's facts, the size and place of what comes, while they load. */
function FileSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-x-5 gap-y-3" aria-hidden="true">
      {[0, 1, 2, 3, 4, 5].map((each) => (
        <div key={each} className="flex flex-col gap-1.5">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3.5 w-40 max-w-full" />
        </div>
      ))}
    </div>
  );
}

/** The tag on the picture: "S01E05", "Special · S00E02", or what a title without episodes is. */
function tagOf(title: TitleDetail, season: number | null, numbered: string | null): ReactNode {
  if (numbered === null) return kindWord(title.kind);
  return (
    <span className="font-medium font-mono">
      {season === 0 ? `Special · ${numbered}` : numbered}
    </span>
  );
}

function episodeOf(
  title: TitleDetail,
  season: number | null,
  number: number | null,
): EpisodeState | undefined {
  if (season === null || number === null) return undefined;
  return title.episodes.find((each) => each.season === season && each.number === number);
}

function picture(file: FileDetails): string | null {
  const { picture } = file;
  if (!picture) return null;
  return [
    `${picture.width} × ${picture.height}`,
    `${codecName(picture.codec)} ${picture.bitDepth}-bit`,
    picture.frameRate ? `${Math.round(picture.frameRate * 100) / 100} fps` : null,
    file.converted ? "made by Maku" : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function sound(track: FileDetails["sound"][number]): string {
  const layout =
    track.channels === 1
      ? "mono"
      : track.channels === 2
        ? "stereo"
        : track.channels === 6
          ? "5.1"
          : track.channels === 8
            ? "7.1"
            : `${track.channels} channels`;
  return [
    track.language
      ? `${languageName(track.language)}${track.heard ? ", as Maku heard it" : ""}`
      : "Language not labelled",
    `${track.codec.toUpperCase()} ${layout}`,
    track.lossless ? "lossless" : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function subtitles(track: FileDetails["subtitles"][number]): string {
  return [
    track.language ? languageName(track.language) : "Language not labelled",
    track.beside ? "beside it" : track.text ? "in it" : "in it, as pictures",
    track.forced ? "signs and songs" : null,
    track.made ? "made by Maku" : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function converting(file: FileDetails): string | null {
  const { state, reasons } = file.converting;
  if (state === "broken") return null;
  if (state === "ready") return "At your standard: nothing to do";
  return reasons[0] ?? "To convert";
}

/** Several lines in one fact, or nothing for none. */
function lines(items: string[]): ReactNode {
  if (items.length === 0) return null;
  return (
    <span className="flex flex-col">
      {items.map((item, index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: two tracks can read the same
        <span key={index}>{item}</span>
      ))}
    </span>
  );
}

/** "S01E05", or "S01E05-E06" for a file of two. */
function code(season: number, number: number, last: number | null = null): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `S${pad(season)}E${pad(number)}${last ? `-E${pad(last)}` : ""}`;
}

function day(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
