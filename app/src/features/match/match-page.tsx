import { Check, Play, Search } from "lucide-react";
import { RadioGroup } from "radix-ui";
import { type ReactNode, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { Breadcrumb, LIBRARY } from "@/components/breadcrumb";
import { type Asking, ConfirmDelete, Deleted, useDeleting } from "@/components/delete";
import { EmptyState, ShelfIllustration } from "@/components/empty-state";
import { EngineProblem } from "@/components/engine-problem";
import { FileMenuItems, FileNote, useFileActions } from "@/components/file-actions";
import { Loading, PanelSkeleton, Skeleton } from "@/components/skeleton";
import { NoTmdbKey } from "@/components/tmdb-key";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MenuItem, MenuSeparator, RowMenu } from "@/components/ui/menu";
import { Segmented } from "@/components/ui/segmented";
import { type PlayItem, usePlayer } from "@/features/player/player-context";
import {
  type Guess,
  type TidyResult,
  useChooseMatch,
  useCover,
  useIgnored,
  useIgnoreFile,
  useMatchSearch,
  useReview,
  useStill,
  useTitle,
  useTmdb,
  useUnignore,
  type WaitingFile,
} from "@/lib/engine";
import { clockLength, clockTime, codecName, languages, listed, size, split } from "@/lib/format";
import { kindWord } from "@/lib/kinds";
import { useSettled } from "@/lib/settled";
import { cn } from "@/lib/utils";

type Kind = "episode" | "movie" | "special";

const KINDS = [
  { value: "episode", label: "Episode" },
  { value: "movie", label: "Movie" },
  { value: "special", label: "Special or extra" },
] as const;

/** Files Maku couldn't place surely, one at a time: which series or film is this? With
 * `?title=`, a title's files all at once, to change its match. Without a TMDB key, a notice
 * under the header says Maku can't look anything up, and the way to the key. */
export function MatchPage() {
  const [params] = useSearchParams();
  const titleId = params.has("title") ? Number(params.get("title")) : null;
  const review = useReview(titleId);
  const title = useTitle(titleId ?? 0, titleId !== null);
  const [skipped, setSkipped] = useState<number[]>([]);
  const [settled, setSettled] = useState(0);
  // Deleting asks first, beside the file; right after, the page says so and offers it back. It
  // lives with the page, not with the file: the file on screen goes as soon as it's deleted.
  const [asking, setAsking] = useState<Asking | null>(null);
  const [deleted, setDeleted] = useState<TidyResult | null>(null);
  const deleting = useDeleting((result) => {
    setAsking(null);
    setDeleted(result);
  });
  const forTitle = titleId === null ? null : { id: titleId, name: title.data?.name ?? "…" };
  const deletes: Deletes = {
    ask: (next) => {
      deleting.reset();
      setDeleted(null);
      setAsking(next);
    },
    confirm: (where) =>
      asking?.where === where ? (
        <ConfirmDelete
          asking={asking}
          busy={deleting.busy}
          problem={deleting.problem}
          onConfirm={() => deleting.delete(asking.files)}
          onCancel={() => setAsking(null)}
        />
      ) : null,
  };
  const notice = deleted && <Deleted result={deleted} onPutBack={() => setDeleted(null)} />;
  const setAside = forTitle ? null : <SetAside deletes={deletes} />;

  if (!review.data) {
    return (
      <>
        <h1 className="page-top type-title animate-fade-up">Which title is this?</h1>
        <EngineProblem queries={[review]} />
        <Loading label="Loading the files to match" queries={[review]}>
          <div className="flex flex-col gap-4 rounded-22 border border-edge bg-glass p-5 shadow-panel">
            <Skeleton className="h-5 w-72 max-w-full" />
            <div className="grid grid-cols-3 gap-2.5">
              <Skeleton className="aspect-video w-full rounded-12" />
              <Skeleton className="aspect-video w-full rounded-12" />
              <Skeleton className="aspect-video w-full rounded-12" />
            </div>
          </div>
          <PanelSkeleton rows={4} />
        </Loading>
      </>
    );
  }
  // Skipped files go to the back of the queue for this visit, the latest skipped last.
  const queue = [...review.data].sort((a, b) => skipped.indexOf(a.id) - skipped.indexOf(b.id));
  const [file, ...next] = queue;
  if (!file) return <AllMatched notice={notice} setAside={setAside} />;

  return (
    <>
      {forTitle ? (
        <Breadcrumb
          trail={[LIBRARY, { label: forTitle.name, to: `/titles/${forTitle.id}` }]}
          current="Change match"
        />
      ) : (
        <Breadcrumb trail={[{ label: "Tidy up", to: "/tidy" }]} current="Need a match" />
      )}
      <MatchFile
        key={file.id}
        file={file}
        forTitle={forTitle}
        position={settled + 1}
        total={settled + queue.length}
        next={next}
        deletes={forTitle ? null : deletes}
        notice={notice}
        onSkip={() => setSkipped((before) => [...before.filter((id) => id !== file.id), file.id])}
        onSettled={(count) => setSettled((before) => before + count)}
      />
      {setAside}
      <EngineProblem queries={[review]} />
    </>
  );
}

/** A file's "More" menu: its folder, its path, and deleting it where the page offers that. How
 * showing or copying went shows on a line of its own under the row. */
function FileMenu(props: {
  label: string;
  file: { id: number; path: string; size: number };
  deletes: Deletes | null;
  where: string;
}) {
  const { file, deletes } = props;
  const actions = useFileActions();
  return (
    <>
      <RowMenu label={props.label}>
        <FileMenuItems path={file.path} actions={actions} />
        {deletes && (
          <>
            <MenuSeparator />
            <MenuItem
              danger
              onSelect={() => deletes.ask({ what: "this file", where: props.where, files: [file] })}
            >
              Delete…
            </MenuItem>
          </>
        )}
      </RowMenu>
      <FileNote actions={actions} className="basis-full pb-2 text-12 text-fg-muted" />
    </>
  );
}

/** Deleting from the page: asking about a file, and the question where it was asked. */
interface Deletes {
  ask: (asking: Asking) => void;
  /** The question, if it was asked about this file ("file-17"). */
  confirm: (where: string) => ReactNode;
}

function MatchFile(props: {
  file: WaitingFile;
  /** The title whose match changes, all its files at once. */
  forTitle: { id: number; name: string } | null;
  position: number;
  total: number;
  next: WaitingFile[];
  /** Null while changing a title's match: its page deletes its files. */
  deletes: Deletes | null;
  /** What the page says above the file: what was just deleted. */
  notice: ReactNode;
  onSkip: () => void;
  onSettled: (count: number) => void;
}) {
  const { file, forTitle } = props;
  const navigate = useNavigate();
  const choose = useChooseMatch();
  const ignore = useIgnoreFile();
  const [search, setSearch] = useState("");
  const asked = useSettled(search, 350); // TMDB is asked once the owner stops typing
  const found = useMatchSearch(file.id, asked);
  const searching = asked.trim().length >= 2;
  const guesses = searching ? (found.data ?? []) : file.guesses;
  const [picked, setPicked] = useState<number | null>(file.guesses[0]?.entryId ?? null);
  const [kind, setKind] = useState<Kind>(asKind(file.kind));
  // An episode's number starts as its name gives it; a special's starts blank.
  const named = file.episode === null ? "" : String(file.episode);
  const [numbers, setNumbers] = useState({ episode: named, special: "" });
  const number = kind === "movie" ? "" : numbers[kind];
  const [together, setTogether] = useState(true);
  const chosen = guesses.find((guess) => guess.entryId === picked) ?? null;
  const busy = choose.isPending || ignore.isPending;

  // 1, 2 or 3 picks a guess, as the board says, unless the owner is typing.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.target instanceof HTMLInputElement || event.ctrlKey || event.altKey) return;
      const index = ["1", "2", "3"].indexOf(event.key);
      const guess = guesses[index];
      if (guess) setPicked(guess.entryId);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [guesses]);

  function confirm() {
    if (!chosen) return;
    // The number goes only when the owner gave one its name doesn't.
    const given = number !== "" && (kind === "special" || number !== named);
    const episode = given ? Number(number) : undefined;
    // A whole title goes at once, each file keeping its kind; or the file, with its alike.
    const which = forTitle ? { title: forTitle.id } : { also: together ? file.alike : [] };
    choose.mutate(
      {
        path: `/review/${file.id}`,
        body: { entryId: chosen.entryId, kind, episode, ...which },
      },
      {
        onSuccess: (answer) => {
          if (forTitle && answer.titleId !== null)
            void navigate(`/titles/${answer.titleId}`, { state: { waiting: answer.waiting } });
          else props.onSettled(answer.placed);
        },
      },
    );
  }

  return (
    <>
      <header className="page-top flex animate-fade-up flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-2">
          <h1 className="font-extrabold text-32 leading-[1.1] tracking-[-0.02em]">
            Which title is this?
          </h1>
          {forTitle ? (
            <span className="text-14 text-fg-muted">
              All {file.alike.length + 1} files of {forTitle.name}
            </span>
          ) : (
            <div className="flex items-center gap-3 text-14 text-fg-muted">
              <span>
                File {props.position} of {props.total}
              </span>
              <span className="h-1.5 w-35 overflow-hidden rounded-3 bg-track" aria-hidden="true">
                <span
                  className="block h-full rounded-3 bg-accent transition-[width] duration-320 ease-cinema"
                  style={{ width: `${(props.position / props.total) * 100}%` }}
                />
              </span>
            </div>
          )}
        </div>
        {forTitle ? (
          <Button disabled={busy} onClick={() => void navigate(`/titles/${forTitle.id}`)}>
            Cancel
          </Button>
        ) : (
          <div className="flex flex-wrap gap-2.5">
            <Button disabled={busy} onClick={props.onSkip}>
              Skip for now
            </Button>
            <Button
              disabled={busy}
              onClick={() =>
                ignore.mutate(
                  { path: `/review/${file.id}/ignore` },
                  { onSuccess: () => props.onSettled(1) },
                )
              }
            >
              Not a series or film: set it aside
            </Button>
          </div>
        )}
      </header>
      <NoTmdbKey />
      {props.notice}

      <div className="flex flex-wrap items-start gap-5">
        <FilePanel file={file} deletes={props.deletes} />

        <section
          aria-labelledby="guess-title"
          className="flex min-w-0 flex-[1.3_1_420px] animate-fade-up flex-col gap-3.5 rounded-24 border border-accent/35 bg-raised p-5.5 shadow-panel [animation-delay:120ms]"
        >
          <div className="flex items-baseline justify-between gap-3">
            <h2 id="guess-title" className="font-extrabold text-17">
              {searching ? "Found" : "Best guesses"}
            </h2>
            {guesses.length > 1 && (
              <span className="text-12 text-fg-muted">
                Press{" "}
                {guesses
                  .slice(0, 3)
                  .map((_, index) => index + 1)
                  .join(", ")
                  .replace(/, (\d)$/, " or $1")}
              </span>
            )}
          </div>
          {guesses.length > 0 ? (
            <RadioGroup.Root
              aria-label="Pick the series or film"
              value={picked === null ? "" : String(picked)}
              onValueChange={(value) => setPicked(Number(value))}
              className="flex flex-col gap-2.5"
            >
              {guesses.slice(0, searching ? 6 : 3).map((guess, index) => (
                <GuessOption key={guess.entryId} guess={guess} index={index} file={file} />
              ))}
            </RadioGroup.Root>
          ) : (
            <p className="rounded-16 bg-tint/4 px-4 py-3.5 text-13 text-fg-muted">
              {searching
                ? found.isFetching
                  ? "Searching…"
                  : "Nothing by that name. Try another spelling, or its original title."
                : "Maku has no guess for this one. Search for the series or film by name."}
            </p>
          )}
          <label className="flex h-11 items-center gap-2.5 rounded-full border border-field-edge bg-field px-4 text-fg-muted">
            <Search size={16} aria-hidden="true" />
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="None of these? Search for the series or film"
              aria-label="Search for the right series or film"
              className="min-w-0 flex-1 bg-transparent text-13 text-fg outline-none placeholder:text-fg-faint"
            />
          </label>
          {found.isError && (
            <p role="alert" className="text-13 text-broken-fg">
              {found.error.message}
            </p>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="font-bold text-13">It is a</span>
            <Segmented label="Kind of file" value={kind} options={KINDS} onChange={setKind} />
          </div>
          {kind !== "movie" && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <label htmlFor="match-number" className="font-bold text-13">
                {kind === "special" ? "Which special" : "Which episode"}
              </label>
              <Input
                id="match-number"
                inputMode="numeric"
                autoComplete="off"
                value={number}
                onChange={(event) => {
                  const digits = event.target.value.replace(/\D/g, "").slice(0, 4);
                  setNumbers((before) => ({ ...before, [kind]: digits }));
                }}
                placeholder={kind === "special" ? "If you know it" : "Its number"}
                className="h-10 w-36 text-right font-mono text-13 placeholder:font-sans"
              />
            </div>
          )}

          {file.alike.length > 0 && (
            <Together
              file={file}
              others={props.next.filter((other) => file.alike.includes(other.id))}
              wholeTitle={forTitle !== null}
              on={together}
              onChange={setTogether}
            />
          )}

          {(choose.isError || ignore.isError) && (
            <p role="alert" className="text-13 text-broken-fg">
              {(choose.error ?? ignore.error)?.message}
            </p>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-12 text-fg-faint">
              Your choice is remembered, so a rescan never undoes it.
            </span>
            <Button variant="primary" disabled={!chosen || busy} onClick={confirm}>
              {chosen ? confirmText(chosen, kind, number) : "Pick the series or film first"}
            </Button>
          </div>
        </section>
      </div>

      {props.next.length > 0 && (
        <UpNext
          files={props.next.slice(0, 4)}
          following={together ? file.alike : []}
          deletes={props.deletes}
        />
      )}
    </>
  );
}

/** The file itself: its name, folder, three stills and what reading it showed, and its menu. */
function FilePanel({ file, deletes }: { file: WaitingFile; deletes: Deletes | null }) {
  const [name, folder] = split(file.path);
  const where = `file-${file.id}`;
  const { play } = usePlayer();
  // A quick look at it, to tell what it is: named by the file, from its folder.
  const item: PlayItem = {
    fileId: file.id,
    label: name,
    name: folder,
    path: file.path,
    fileName: true,
  };
  return (
    <section
      aria-labelledby="file-title"
      className="flex min-w-0 flex-[1_1_380px] animate-fade-up flex-col gap-4 rounded-24 border border-edge bg-glass p-5.5 shadow-panel [animation-delay:60ms]"
    >
      <div className="flex flex-wrap items-start gap-2">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h2 id="file-title" className="font-medium font-mono text-15 [overflow-wrap:anywhere]">
            {name}
          </h2>
          <span className="font-mono text-12 text-fg-muted [overflow-wrap:anywhere]">{folder}</span>
        </div>
        <FileMenu label="More for this file" file={file} deletes={deletes} where={where} />
      </div>
      {deletes?.confirm(where)}
      {file.minutes !== null && (
        <div className="grid grid-cols-3 gap-2">
          {[0.15, 0.5, 0.8].map((point, index) => (
            <Still
              key={point}
              fileId={file.id}
              index={index}
              at={clockTime((file.minutes ?? 0) * 60 * point)}
              onPlay={() => {
                const from = (file.minutes ?? 0) * 60 * point;
                play([{ ...item, name: `From the still at ${clockTime(from)}` }], 0, from);
              }}
            />
          ))}
        </div>
      )}
      <Button size="sm" className="self-start" onClick={() => play([item])}>
        <Play size={13} fill="currentColor" aria-hidden="true" />
        Play it
      </Button>
      <dl className="grid grid-cols-[auto_1fr] gap-x-5 gap-y-2 text-13">
        <Fact label="Length">
          {file.minutes !== null ? clockTime(file.minutes * 60) : "unknown"}
        </Fact>
        <Fact label="Picture">
          {file.height ? `${file.height}p` : "unknown"}
          {file.codec ? ` · ${codecName(file.codec)}` : ""}
        </Fact>
        <Fact label="Audio">{languages(file.audio)}</Fact>
        <Fact label="Subtitles">{languages(file.subtitles)}</Fact>
        <Fact label="Size">{size(file.size)}</Fact>
        {file.group && <Fact label="Group tag">[{file.group}]</Fact>}
      </dl>
    </section>
  );
}

/** A still from the file, and when it's from: it plays from there. */
function Still(props: { fileId: number; index: number; at: string; onPlay: () => void }) {
  const picture = useStill(props.fileId, props.index);
  return (
    <button
      type="button"
      aria-label={`Play from ${props.at}`}
      onClick={props.onPlay}
      className="press flex cursor-pointer flex-col gap-1 text-left"
    >
      <span className="aspect-[4/3] w-full overflow-hidden rounded-10 bg-surface">
        {picture && <img src={picture} alt="" className="size-full object-cover" />}
      </span>
      <span className="font-mono text-11 text-fg-muted">{props.at}</span>
    </button>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-fg-muted">{label}</dt>
      <dd className="font-mono text-12">{children}</dd>
    </>
  );
}

function GuessOption({ guess, index, file }: { guess: Guess; index: number; file: WaitingFile }) {
  const cover = useCover(guess.cover);
  const facts = [
    guess.kind ? kindWord(guess.kind) : null,
    guess.kind !== "movie" && guess.episodes ? `${guess.episodes} episodes` : null,
    guess.minutes ? `${guess.minutes} min` : null,
  ].filter(Boolean);
  return (
    <RadioGroup.Item
      value={String(guess.entryId)}
      className="press flex cursor-pointer items-center gap-3.5 rounded-18 border-2 border-edge bg-glass px-3.5 py-3 text-left data-[state=checked]:border-accent data-[state=checked]:bg-accent/10"
    >
      <span className="w-5.5 shrink-0 font-mono text-12 text-fg-muted">
        {index < 3 ? index + 1 : ""}
      </span>
      <span
        aria-hidden="true"
        className="relative h-16.5 w-11 shrink-0 overflow-hidden rounded-8 bg-featured"
      >
        {cover && <img src={cover} alt="" className="absolute inset-0 size-full object-cover" />}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="font-extrabold">
          {guess.title}
          {guess.year ? ` (${guess.year})` : ""}
        </span>
        <span className="text-12 text-fg-muted">
          {file.episode !== null && guess.kind !== "movie" ? `Episode ${file.episode} · ` : ""}
          {facts.join(" · ")}
        </span>
        <span className="flex items-center gap-2 text-12">
          <span className="h-1.25 w-30 overflow-hidden rounded-3 bg-track" aria-hidden="true">
            <span
              className="block h-full rounded-3 bg-accent"
              style={{ width: `${guess.confidence}%` }}
            />
          </span>
          <span className="font-mono">{guess.confidence}%</span>
        </span>
        {guess.reasons.length > 0 && (
          <span className="text-12 text-fg-muted">{guess.reasons.join("; ")}</span>
        )}
      </span>
    </RadioGroup.Item>
  );
}

function Together(props: {
  file: WaitingFile;
  others: WaitingFile[];
  /** The others are the rest of a title's files, wherever they are. */
  wholeTitle: boolean;
  on: boolean;
  onChange: (on: boolean) => void;
}) {
  const count = props.file.alike.length;
  const tag = props.file.group ? `[${props.file.group}] ` : "";
  const numbers = props.others
    .map((other) => other.episode)
    .filter((episode): episode is number => episode !== null)
    .map((episode) => String(episode).padStart(2, "0"));
  return (
    <label className="press flex min-h-13 cursor-pointer items-center gap-3 rounded-16 border border-edge bg-glass px-3.5 py-2">
      <input
        type="checkbox"
        checked={props.on}
        onChange={(event) => props.onChange(event.target.checked)}
        className="peer sr-only"
      />
      <span
        aria-hidden="true"
        className={cn(
          "inline-flex size-5.5 shrink-0 items-center justify-center rounded-6 peer-focus-visible:outline-2 peer-focus-visible:outline-accent-fg peer-focus-visible:outline-offset-3",
          props.on ? "bg-accent text-on-accent" : "border-2 border-control",
        )}
      >
        {props.on && <Check size={12} strokeWidth={3.4} />}
      </span>
      <span className="flex flex-col">
        <span className="font-extrabold">
          {props.wholeTitle
            ? `Use this for its other ${count === 1 ? "file" : `${count} files`}`
            : `Use this for the ${count === 1 ? "other" : `${count} other`} ${tag}${count === 1 ? "file" : "files"} here`}
        </span>
        {numbers.length > 0 && (
          <span className="text-12 text-fg-muted">
            {numbers.length === 1 ? "Episode" : "Episodes"} {listed(numbers)}, numbered from their
            names
          </span>
        )}
      </span>
    </label>
  );
}

function UpNext(props: { files: WaitingFile[]; following: number[]; deletes: Deletes | null }) {
  const { files, following, deletes } = props;
  return (
    <section
      aria-labelledby="next-title"
      className="flex animate-fade-up flex-col gap-2.5 rounded-22 border border-rule bg-tint/3 px-5.5 py-5 [animation-delay:180ms]"
    >
      <h2 id="next-title" className="font-extrabold text-15">
        Up next
      </h2>
      <ul className="flex flex-col">
        {files.map((file) => {
          const [name, folder] = split(file.path);
          const where = `file-${file.id}`;
          const asked = deletes?.confirm(where);
          return (
            <li
              key={file.id}
              className="flex min-h-11 flex-wrap items-center gap-3 border-rule border-b last:border-b-0"
            >
              <span className="flex-[1_1_260px] font-mono text-12 [overflow-wrap:anywhere]">
                {name}
              </span>
              <span className="text-12 text-fg-muted">
                {following.includes(file.id)
                  ? "follows this choice"
                  : `${folder} · ${describe(file)}`}
              </span>
              <FileMenu label={`More for ${name}`} file={file} deletes={deletes} where={where} />
              {asked && <div className="basis-full pb-3">{asked}</div>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * The files the owner said aren't a series or film, which Maku leaves where they are: each can
 * wait for a match after all, or be deleted.
 */
function SetAside({ deletes }: { deletes: Deletes }) {
  const ignored = useIgnored();
  const unignore = useUnignore();
  const files = ignored.data ?? [];
  if (files.length === 0) return null;
  return (
    <section
      aria-labelledby="set-aside-title"
      className="flex animate-fade-up flex-col gap-2.5 rounded-22 border border-rule bg-tint/3 px-5.5 py-5 [animation-delay:240ms]"
    >
      <div className="flex flex-col gap-1">
        <h2 id="set-aside-title" className="font-extrabold text-15">
          Set aside: not a series or film
        </h2>
        <span className="text-13 text-fg-muted">
          Maku leaves these where they are, out of your library. Match one after all, or delete it.
        </span>
      </div>
      <ul className="flex flex-col">
        {files.map((file) => {
          const [name, folder] = split(file.path);
          const where = `file-${file.id}`;
          const asked = deletes.confirm(where);
          return (
            <li
              key={file.id}
              className="flex min-h-11 flex-wrap items-center gap-3 border-rule border-b py-1.5 last:border-b-0"
            >
              <span className="flex min-w-0 flex-[1_1_260px] flex-col">
                <span className="font-mono text-12 [overflow-wrap:anywhere]">{name}</span>
                <span className="text-12 text-fg-muted [overflow-wrap:anywhere]">
                  {folder} · {size(file.size)}
                </span>
              </span>
              <Button
                size="sm"
                aria-label={`Match it: ${name}`}
                disabled={unignore.isPending}
                onClick={() => unignore.mutate({ path: `/review/${file.id}/ignore` })}
              >
                Match it
              </Button>
              <FileMenu label={`More for ${name}`} file={file} deletes={deletes} where={where} />
              {asked && <div className="basis-full pb-3">{asked}</div>}
            </li>
          );
        })}
      </ul>
      {unignore.isError && (
        <p role="alert" className="text-13 text-broken-fg">
          {unignore.error.message}
        </p>
      )}
    </section>
  );
}

/** Nothing waits for a match. Without a TMDB key nothing could be looked up yet, so the page
 * doesn't say every file is matched: the notice under the header holds the way to the key. */
function AllMatched({ notice, setAside }: { notice: ReactNode; setAside: ReactNode }) {
  const navigate = useNavigate();
  const noKey = useTmdb().data?.connected === false;
  return (
    <>
      <h1 className="page-top type-title animate-fade-up">Which title is this?</h1>
      <NoTmdbKey />
      {notice}
      {noKey ? (
        <EmptyState title="Nothing to match yet" illustration={<ShelfIllustration />}>
          Maku asks here about any video it can't place surely, once it can look them up on TMDB.
        </EmptyState>
      ) : (
        <EmptyState
          title="Every file is matched"
          illustration={<ShelfIllustration />}
          action={
            <Button variant="primary" onClick={() => void navigate("/")}>
              Go to Home
            </Button>
          }
        >
          Maku knows which series or film each video is. New files are identified as they arrive.
        </EmptyState>
      )}
      {setAside}
    </>
  );
}

function asKind(kind: WaitingFile["kind"]): Kind {
  if (kind === "movie") return "movie";
  if (kind === "special" || kind === "extra") return "special";
  return "episode";
}

function confirmText(guess: Guess, kind: Kind, number: string): string {
  if (kind === "episode" && number !== "") return `Confirm ${guess.title}, episode ${number}`;
  if (kind === "special" && number !== "") return `Confirm ${guess.title}, special ${number}`;
  return `Confirm ${guess.title}`;
}

function describe(file: WaitingFile): string {
  const length = file.minutes !== null ? clockLength(file.minutes) : "length unknown";
  if (file.kind === "dvd") return `DVD file, ${length}`;
  if (file.kind === "extra") return `extra, ${length}`;
  if (file.kind === "movie" || (file.minutes ?? 0) >= 60) return `${length}, probably a film`;
  return length;
}
