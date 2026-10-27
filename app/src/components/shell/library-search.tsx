import { FileVideo, Play, Search, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { StatusShape } from "@/components/status";
import {
  type EpisodeFound,
  type FileFound,
  type Found,
  type TitleFound,
  usePoster,
  useSearch,
} from "@/lib/engine";
import { showInFolder } from "@/lib/explorer";
import { split } from "@/lib/format";
import { kindWord } from "@/lib/kinds";
import { useSettled } from "@/lib/settled";
import { cn } from "@/lib/utils";

/** A search shorter than this waits for more: a letter or two finds half the library. */
const ENOUGH = 2;

type Group = "Titles" | "Episodes" | "Videos";

/** Something a search found, and what opening it does: a page of Maku's, or the file's folder
 * for a video Maku files under no title. */
interface Hit {
  key: string;
  group: Group;
  to?: string;
  folder?: string;
  title?: TitleFound;
  episode?: EpisodeFound;
  file?: FileFound;
}

/**
 * The title bar's search, as the boards draw it: the library's series and films by any name
 * they go by, their episodes by code or name, and its videos by their files' names, listed under
 * the field as you type, the closest first. The arrow keys move through what's found and Enter
 * opens it, once what's listed answers what's typed; Escape closes the list, then clears the
 * search. An episode or video opens on its title's page with its videos searched for it.
 */
export function LibrarySearch() {
  const navigate = useNavigate();
  const location = useLocation();
  const id = useId();
  const field = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  // Why a video's folder couldn't be shown, as the shell words it.
  const [problem, setProblem] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const typed = query.trim();
  const asked = useSettled(typed, 150);
  const search = useSearch(asked.length >= ENOUGH ? asked : "");
  const found = asked.length >= ENOUGH ? search.data : undefined;
  const hits = found ? hitsOf(found) : [];
  const showing = open && typed.length >= ENOUGH;
  // What's listed answers what's typed now: the typing has settled, and the engine answered it.
  const settled = typed === asked;
  const current = settled && found !== undefined && !search.isPlaceholderData;

  // A page opened from it starts a new search.
  // biome-ignore lint/correctness/useExhaustiveDependencies: only when the page changes
  useEffect(() => {
    setOpen(false);
    setQuery("");
  }, [location.pathname]);
  // Each new answer starts from its first.
  // biome-ignore lint/correctness/useExhaustiveDependencies: only when what's asked changes
  useEffect(() => setActive(0), [asked]);

  function go(hit: Hit | undefined) {
    if (!hit) return;
    const folder = hit.folder;
    if (folder) {
      setProblem(null);
      showInFolder(folder).catch((error: unknown) => setProblem(String(error))); // the list stays
      return;
    }
    setOpen(false);
    setQuery("");
    field.current?.blur();
    if (hit.to) void navigate(hit.to, { state: hit.to.includes("?q=") ? { videos: true } : null });
  }

  function onKey(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!showing) {
        setOpen(true);
        return;
      }
      if (!current || hits.length === 0) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((before) => (Math.min(before, hits.length - 1) + step + hits.length) % hits.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (showing && current && !event.nativeEvent.isComposing) go(hits[active] ?? hits[0]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      if (showing) setOpen(false);
      else setQuery("");
    }
  }

  const list = `${id}-found`;
  const activeId = showing && current && hits[active] ? `${id}-${hits[active].key}` : undefined;
  // The option the arrow keys reach stays in sight in a long list.
  useEffect(() => {
    if (activeId) document.getElementById(activeId)?.scrollIntoView?.({ block: "nearest" });
  }, [activeId]);
  return (
    <search
      className="relative flex min-w-0 flex-[0_1_460px]"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <label className="flex h-9.5 min-w-0 flex-1 cursor-text items-center gap-2.5 rounded-full border border-edge bg-tint/6 pr-1.5 pl-3.5 text-fg-muted transition-[border-color] duration-200 ease-cinema focus-within:outline-2 focus-within:outline-accent-fg focus-within:outline-offset-3 hover:border-tint/20">
        <Search size={16} strokeWidth={1.9} aria-hidden="true" className="shrink-0" />
        <input
          ref={field}
          type="text"
          role="combobox"
          aria-label="Search titles, episodes or files"
          aria-expanded={showing && hits.length > 0}
          aria-controls={hits.length > 0 ? list : undefined}
          aria-autocomplete="list"
          aria-activedescendant={activeId}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
            setProblem(null);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKey}
          placeholder="Search titles, episodes or files"
          autoComplete="off"
          spellCheck={false}
          className="h-full min-w-0 flex-1 bg-transparent text-13 text-fg outline-none select-text placeholder:text-fg-muted"
        />
        {query ? (
          <button
            type="button"
            aria-label="Clear the search"
            onClick={() => {
              setQuery("");
              field.current?.focus();
            }}
            className="press inline-flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-full hover:bg-tint/8 hover:text-fg"
          >
            <X size={14} aria-hidden="true" />
          </button>
        ) : (
          <span aria-hidden="true" className="size-7 shrink-0" />
        )}
      </label>
      {showing && (
        <div className="absolute top-[calc(100%+8px)] right-0 left-0 z-50 flex max-h-[min(32rem,70vh)] flex-col overflow-y-auto rounded-16 border border-edge bg-dialog p-1.5 text-13 shadow-float">
          {found && hits.length > 0 && (
            <Results
              id={list}
              found={found}
              hits={hits}
              active={current ? active : -1}
              idOf={(hit) => `${id}-${hit.key}`}
              onHover={setActive}
              onPick={go}
            />
          )}
          <Note>
            {problem ??
              note({
                asked,
                found,
                hits,
                current,
                // Not looking, and nothing to show: the engine isn't there to ask.
                down: search.isError || (settled && !search.isFetching),
              })}
          </Note>
        </div>
      )}
    </search>
  );
}

/** What the list says under what it found, or in its place. */
function note(state: {
  asked: string;
  found: Found | undefined;
  hits: Hit[];
  current: boolean;
  down: boolean;
}): string | null {
  const { found, hits } = state;
  if (!found)
    return state.down ? "Maku's engine didn't answer. Try again in a moment." : "Searching…";
  if (!state.current) return hits.length === 0 ? "Searching…" : null;
  if (hits.length === 0) return `Nothing in the library goes by “${state.asked}”.`;
  const more =
    found.totalTitles > found.titles.length ||
    found.totalEpisodes > found.episodes.length ||
    found.totalFiles > found.files.length;
  return more ? "Type more to narrow it down." : null;
}

function Results(props: {
  id: string;
  found: Found;
  hits: Hit[];
  /** The option the keys are on; -1 while the list is still the last search's. */
  active: number;
  idOf: (hit: Hit) => string;
  onHover: (index: number) => void;
  onPick: (hit: Hit) => void;
}) {
  const { found, hits } = props;
  const totals: Record<Group, number> = {
    Titles: found.totalTitles,
    Episodes: found.totalEpisodes,
    Videos: found.totalFiles,
  };
  const groups = (["Titles", "Episodes", "Videos"] as const).filter((group) =>
    hits.some((hit) => hit.group === group),
  );
  return (
    <div id={props.id} role="listbox" aria-label="Found in the library" className="flex flex-col">
      {groups.map((group) => {
        const mine = hits.filter((hit) => hit.group === group);
        const heading = `${props.id}-${group}`;
        return (
          // biome-ignore lint/a11y/useSemanticElements: a listbox groups its options with role=group, not a fieldset
          <div key={group} role="group" aria-labelledby={heading} className="flex flex-col">
            <div
              role="presentation"
              className="flex items-baseline justify-between px-3 pt-2 pb-1 font-extrabold text-11 text-fg-muted uppercase tracking-[0.06em]"
            >
              <span id={heading}>{group}</span>
              {totals[group] > mine.length && (
                <span className="font-mono font-medium normal-case tracking-normal">
                  {mine.length} of {totals[group]}
                </span>
              )}
            </div>
            {mine.map((hit) => {
              const index = hits.indexOf(hit);
              return (
                // biome-ignore lint/a11y/useKeyWithClickEvents: the field's arrow keys and Enter choose an option (aria-activedescendant)
                <div
                  key={hit.key}
                  id={props.idOf(hit)}
                  role="option"
                  aria-selected={index === props.active}
                  tabIndex={-1}
                  onMouseMove={() => props.onHover(index)}
                  onMouseDown={(event) => event.preventDefault()} // the field keeps the focus
                  onClick={() => props.onPick(hit)}
                  className={cn(
                    "flex min-h-11 cursor-pointer items-center gap-3 rounded-10 px-3 py-1.5",
                    index === props.active ? "bg-tint/6 text-fg" : "text-fg-soft",
                  )}
                >
                  <HitRow hit={hit} />
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

function HitRow({ hit }: { hit: Hit }) {
  if (hit.title) {
    const title = hit.title;
    return (
      <>
        <Thumb title={title} />
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-bold">{title.name}</span>
          <span className="truncate text-12 text-fg-muted">
            {[kindWord(title.kind), title.year, title.also && `also ${title.also}`]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </span>
      </>
    );
  }
  if (hit.episode) {
    const episode = hit.episode;
    const lacking = episode.fileId === null;
    return (
      <>
        {lacking ? (
          <StatusShape
            state={episode.coming ? "upcoming" : "missing"}
            className="mx-0.75 size-2.5 shrink-0"
          />
        ) : (
          <Play size={16} strokeWidth={1.9} aria-hidden="true" className="shrink-0" />
        )}
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate font-bold">
            <span className="font-mono text-12">{code(episode.season, episode.number)}</span>
            {episode.name && ` · ${episode.name}`}
          </span>
          <span className="truncate text-12 text-fg-muted">{episode.title}</span>
        </span>
        {lacking && (
          <span className="shrink-0 text-12 text-fg-muted">
            {episode.coming ? "Not out yet" : "Not in library"}
          </span>
        )}
      </>
    );
  }
  const file = hit.file as FileFound;
  const [name, folder] = split(file.path);
  return (
    <>
      <FileVideo size={16} strokeWidth={1.9} aria-hidden="true" className="shrink-0" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate font-mono text-12">{name}</span>
        <span className="truncate text-12 text-fg-muted">{file.title ?? folder}</span>
      </span>
      {file.place !== "title" && (
        <span className="shrink-0 text-12 text-fg-muted">{PLACES[file.place]}</span>
      )}
    </>
  );
}

/** Where a video found is, when it isn't in a title. */
const PLACES = {
  match: "Needs a match",
  aside: "Set aside",
  extra: "Extra · show in folder",
  other: "In no title · show in folder",
  reading: "Being read",
} as const;

/** A title's poster, small, or the boards' blue with its orange orb. */
function Thumb({ title }: { title: TitleFound }) {
  const address = usePoster(title.id, title.hasPoster);
  return (
    <span
      aria-hidden="true"
      className="relative aspect-[2/3] w-7 shrink-0 overflow-hidden rounded-6 bg-featured"
    >
      {address ? (
        <img src={address} alt="" className="absolute inset-0 size-full object-cover" />
      ) : (
        <span className="-right-[40%] -top-[15%] absolute aspect-square w-[95%] rounded-full bg-featured-orb" />
      )}
    </span>
  );
}

/** What the list says, for screen readers too; nothing when there's nothing to say. */
function Note({ children }: { children: string | null }) {
  return (
    <p role="status" className={cn("px-3 text-12 text-fg-muted", children && "py-2")}>
      {children}
    </p>
  );
}

/** Everything found, in the order it's listed: series and films, then episodes, then videos. */
function hitsOf(found: Found): Hit[] {
  return [
    ...found.titles.map(
      (title): Hit => ({
        key: `title-${title.id}`,
        group: "Titles",
        to: `/titles/${title.id}`,
        title,
      }),
    ),
    ...found.episodes.map(
      (episode): Hit => ({
        key: `episode-${episode.titleId}-${episode.season}-${episode.number}`,
        group: "Episodes",
        to:
          episode.fileId === null
            ? `/titles/${episode.titleId}`
            : `/titles/${episode.titleId}?q=${code(episode.season, episode.number)}`,
        episode,
      }),
    ),
    ...found.files.map(
      (file): Hit => ({ key: `file-${file.fileId}`, group: "Videos", file, ...opening(file) }),
    ),
  ];
}

/** Where opening a video found leads: its title's videos searched for its file's name, "Which
 * title is this?" for one waiting there or set aside, the scan for one Maku is still reading, or
 * the file's folder for one Maku files under no title. */
function opening(file: FileFound): Pick<Hit, "to" | "folder"> {
  switch (file.place) {
    case "title":
      return { to: `/titles/${file.titleId}?q=${encodeURIComponent(split(file.path)[0])}` };
    case "match":
    case "aside":
      return { to: "/match" };
    case "reading":
      return { to: "/scan" };
    default:
      return { folder: file.path };
  }
}

function code(season: number, number: number): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `S${pad(season)}E${pad(number)}`;
}
