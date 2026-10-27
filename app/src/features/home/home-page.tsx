import { FolderPlus } from "lucide-react";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router";
import { EmptyState, ShelfIllustration } from "@/components/empty-state";
import { EngineProblem } from "@/components/engine-problem";
import { useAddressSearch } from "@/components/search-field";
import { Loading, TilesSkeleton } from "@/components/skeleton";
import { NoTmdbKey } from "@/components/tmdb-key";
import { Button } from "@/components/ui/button";
import { pickFolder } from "@/lib/dialogs";
import {
  type FranchiseSummary,
  type Hearable,
  type Library,
  type Scan,
  type Settings,
  type TitleSort,
  useAddFolder,
  useCheckup,
  useEngine,
  useFolders,
  useFranchises,
  useLibrary,
  useScan,
  useScanAction,
  useSettings,
  useSubtitleOptions,
} from "@/lib/engine";
import { dayAndTime, isEnglish, scanChanges } from "@/lib/format";
import { KIND_ORDER, kindCount } from "@/lib/kinds";
import { Attention } from "./attention";
import { ComingUp } from "./coming-up";
import { ContinueWatching } from "./continue-watching";
import { Glance } from "./glance";
import { Recovered } from "./recovered";
import { Shelf } from "./shelf";
import { UnplayedDialog } from "./unplayed";

export function HomePage() {
  const engine = useEngine();
  const settings = useSettings();
  const folders = useFolders();
  const library = useLibrary();
  const scan = useScan();
  const franchises = useFranchises();
  const heard = useSubtitleOptions();
  const navigate = useNavigate();
  const [sort, setSort] = useState<TitleSort>("released");
  const [query, setQuery] = useAddressSearch();
  const [allComing, setAllComing] = useState(false);
  const checkup = useCheckup();
  const [unplayed, setUnplayed] = useState(false);

  const empty = folders.data?.length === 0;
  if (empty && settings.data && !settings.data.setUp) return <Navigate to="/setup" replace />;
  const working = engine.state !== "failed";
  const missing = (franchises.data ?? []).filter((franchise) => franchise.missing > 0);
  const videos = heard.data?.files ?? [];
  const withoutEnglish = videos.filter((video) => !video.english && !video.waiting);

  return (
    <>
      <header className="page-top flex animate-fade-up flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h1 className="type-title">Library</h1>
          <p className="text-14 text-fg-muted">
            {empty
              ? "No folders yet."
              : library.data
                ? summary(library.data, franchises.data)
                : "…"}
          </p>
        </div>
        {working && scan.data && !empty && <ScanButtons scan={scan.data} />}
      </header>

      <Recovered />
      <NoTmdbKey />
      <EngineProblem queries={[settings, folders, library, scan]} />
      {engine.state !== "failed" && empty && (
        <EmptyState
          title="Your shelf is empty"
          illustration={<ShelfIllustration />}
          action={
            <Button variant="primary" onClick={() => void navigate("/setup?step=folders")}>
              Add a folder
            </Button>
          }
        >
          Add a folder with series or films in it. Any layout, even everything in one folder.
        </EmptyState>
      )}
      {working && !empty && !library.data && (
        <Loading label="Loading your library" queries={[settings, folders, library, scan]}>
          <TilesSkeleton count={4} />
        </Loading>
      )}
      {working && library.data && !empty && (
        <Pictures library={library.data} standard={settings.data?.standard ?? "4k"} />
      )}
      {working && !empty && videos.length > 0 && <Languages videos={videos} />}
      {working && library.data && !empty && <Glance />}
      {working && library.data && !empty && <ContinueWatching />}
      {working && library.data && !empty && <ComingUp all={allComing} onAll={setAllComing} />}
      {working && scan.data && library.data && !empty && (
        <Attention
          waiting={scan.data.waiting}
          missing={missing.reduce((total, franchise) => total + franchise.missing, 0)}
          missingIn={missing.length}
          broken={library.data.problems}
          mixed={scan.data.mixed}
          unplayed={checkup.data?.unplayed.length ?? 0}
          onUnplayed={() => setUnplayed(true)}
          noEnglish={withoutEnglish.length}
          noEnglishIn={new Set(withoutEnglish.map((video) => video.titleId)).size}
          onSubtitles={() => void navigate("/subtitles")}
          onMatch={() => void navigate("/match")}
          onMissing={() => {
            setSort("missing");
            setQuery("");
            document.getElementById("shelf")?.scrollIntoView({ behavior: "smooth" });
          }}
        />
      )}
      {working && !empty && <Shelf sort={sort} onSort={setSort} query={query} onQuery={setQuery} />}
      <UnplayedDialog open={unplayed} onClose={() => setUnplayed(false)} />
    </>
  );
}

/** Scanning again and adding a folder, by the page's title, with when the latest scan ran and
 * what it found new or gone. */
function ScanButtons({ scan }: { scan: Scan }) {
  const navigate = useNavigate();
  const action = useScanAction();
  const add = useAddFolder();
  const [picking, setPicking] = useState(false);
  const scanning = scan.state === "running" || scan.state === "paused";

  const rescan = () =>
    action.mutate({ path: "/scan" }, { onSuccess: () => void navigate("/scan") });

  async function addFolder() {
    setPicking(true);
    try {
      const path = await pickFolder("Choose a folder with series or films in it");
      if (path) add.mutate({ path: "/folders", body: { path } }, { onSuccess: rescan });
    } finally {
      setPicking(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex flex-wrap justify-end gap-2">
        {scanning ? (
          <Button size="sm" variant="primary" onClick={() => void navigate("/scan")}>
            {scan.state === "running" ? "Scanning… see progress" : "Scan paused: see it"}
          </Button>
        ) : (
          <Button size="sm" disabled={action.isPending} onClick={rescan}>
            Scan again
          </Button>
        )}
        {/* Adding a folder starts a scan, and one can't start while another runs. */}
        {scan.state !== "running" && (
          <Button
            size="sm"
            variant="ghost"
            disabled={picking || add.isPending}
            onClick={() => void addFolder()}
          >
            <FolderPlus size={15} aria-hidden="true" />
            Add a folder
          </Button>
        )}
      </div>
      {scan.state === "done" && scan.finishedAt && (
        <span className="text-12 text-fg-muted">
          Scanned {dayAndTime(new Date(scan.finishedAt))}
          {scan.added !== null && scan.gone !== null && ` · ${scanChanges(scan.added, scan.gone)}`}
        </span>
      )}
      {(add.isError || action.isError) && (
        <p role="alert" className="text-13 text-broken-fg">
          {(add.error ?? action.error)?.message}
        </p>
      )}
    </div>
  );
}

/** What's in the library, by picture size: the summary at the top of Home. Each size says what
 * converting to the standard does to it: nothing is made bigger, and 4K stays 4K unless the
 * standard is 1080p. */
function Pictures({ library, standard }: { library: Library; standard: Settings["standard"] }) {
  const sizes = [
    { label: "SD", count: library.sd, note: "kept at its size" },
    { label: "720p", count: library.hd720, note: "kept at its size" },
    { label: "1080p", count: library.hd1080, note: "kept at 1080p" },
    {
      label: "4K",
      count: library.larger,
      note: standard === "4k" ? "kept at 4K, HDR too" : "brought down to 1080p",
    },
  ];
  const parts = shares(sizes.map((size) => size.count));
  return (
    <section
      aria-labelledby="pictures-title"
      className="flex animate-fade-up flex-col gap-2.5 [animation-delay:60ms]"
    >
      <h2 id="pictures-title" className="font-bold text-13 text-fg-muted">
        Your videos by picture
      </h2>
      <ul className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2.5">
        {sizes.map((size, at) => {
          const share = parts[at] ?? 0;
          return (
            <li
              key={size.label}
              className="flex flex-col gap-1.5 rounded-16 border border-edge bg-glass px-4 py-3.5 shadow-panel"
            >
              <span className="flex items-baseline justify-between gap-2">
                <span className="font-bold text-13">{size.label}</span>
                <span className="font-mono text-12 text-fg-muted">{share}%</span>
              </span>
              <span className="font-extrabold text-24 leading-[1.1]">
                {size.count.toLocaleString("en-GB")}
              </span>
              <span className="h-1.5 overflow-hidden rounded-3 bg-track" aria-hidden="true">
                <span
                  className="block h-full animate-grow-x rounded-3 bg-accent"
                  style={{ width: `${share}%` }}
                />
              </span>
              <span className="text-12 text-fg-muted">{size.note}</span>
            </li>
          );
        })}
      </ul>
      {(library.problems > 0 || library.unread > 0) && (
        <p className="text-13 text-fg-muted">
          {library.problems > 0 &&
            `${library.problems.toLocaleString("en-GB")} ${library.problems === 1 ? "file" : "files"} couldn't be read. `}
          {library.unread > 0 &&
            `${library.unread.toLocaleString("en-GB")} still to read: the next scan reads them.`}
        </p>
      )}
    </section>
  );
}

/** What the library's videos can be heard and read in: English sound (in the files),
 * English subtitles (some of them Maku's), and neither. A video can have both, so the shares
 * aren't parts of one whole. */
function Languages({ videos }: { videos: Hearable[] }) {
  const sound = videos.filter((video) => video.sound.some(isEnglish)).length;
  const subtitled = videos.filter((video) => video.subtitles.some(isEnglish));
  const made = subtitled.filter((video) => video.made).length;
  const none = videos.filter((video) => !video.english).length;
  const tiles = [
    { label: "English sound", count: sound, note: "in the files" },
    {
      label: "English subtitles",
      count: subtitled.length,
      note:
        made > 0
          ? `${made.toLocaleString("en-GB")} of them made by Maku`
          : "in the files or beside them",
    },
    { label: "No English", count: none, note: "neither sound nor subtitles" },
  ];
  return (
    <section
      aria-labelledby="languages-title"
      className="flex animate-fade-up flex-col gap-2.5 [animation-delay:60ms]"
    >
      <h2 id="languages-title" className="font-bold text-13 text-fg-muted">
        Your videos by language
      </h2>
      <ul className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2.5">
        {tiles.map((tile) => {
          const share = Math.round((100 * tile.count) / videos.length);
          return (
            <li
              key={tile.label}
              className="flex flex-col gap-1.5 rounded-16 border border-edge bg-glass px-4 py-3.5 shadow-panel"
            >
              <span className="flex items-baseline justify-between gap-2">
                <span className="font-bold text-13">{tile.label}</span>
                <span className="font-mono text-12 text-fg-muted">{share}%</span>
              </span>
              <span className="font-extrabold text-24 leading-[1.1]">
                {tile.count.toLocaleString("en-GB")}
              </span>
              <span className="h-1.5 overflow-hidden rounded-3 bg-track" aria-hidden="true">
                <span
                  className="block h-full animate-grow-x rounded-3 bg-accent"
                  style={{ width: `${share}%` }}
                />
              </span>
              <span className="text-12 text-fg-muted">{tile.note}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Each count's share of them all in whole percents that add up to 100 (the largest
 * remainders rounded up), or every share 0 when there's nothing. */
function shares(counts: number[]): number[] {
  const all = counts.reduce((sum, count) => sum + count, 0);
  if (all === 0) return counts.map(() => 0);
  const exact = counts.map((count) => (count / all) * 100);
  const whole = exact.map(Math.floor);
  const short = 100 - whole.reduce((sum, part) => sum + part, 0);
  const order = exact
    .map((share, at) => ({ at, rest: share - Math.floor(share) }))
    .sort((a, b) => b.rest - a.rest);
  for (const { at } of order.slice(0, short)) whole[at] = (whole[at] ?? 0) + 1;
  return whole;
}

/** The library in one line: its titles by kind, then its videos, size and folders ("9 series ·
 * 5 movies · 287 videos · 1.2 TB · 2 folders"); nothing before the videos while there are none. */
function summary(library: Library, franchises: FranchiseSummary[] | undefined): string {
  const titles = (franchises ?? []).flatMap((franchise) => franchise.titles);
  const kinds = KIND_ORDER.map((kind) => ({
    kind,
    count: titles.filter((title) => title.kind === kind).length,
  }))
    .filter(({ count }) => count > 0)
    .map(({ kind, count }) => kindCount(kind, count));
  const videos = `${library.files.toLocaleString("en-GB")} ${library.files === 1 ? "video" : "videos"}`;
  const size =
    library.size >= 1e12
      ? `${(library.size / 1e12).toFixed(1)} TB`
      : `${(library.size / 1e9).toFixed(1)} GB`;
  const folders = `${library.folders} ${library.folders === 1 ? "folder" : "folders"}`;
  return [...kinds, videos, size, folders].join(" · ");
}
