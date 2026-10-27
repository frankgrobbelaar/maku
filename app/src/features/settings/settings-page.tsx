import { Folder, Info, Lock } from "lucide-react";
import { useId, useState } from "react";
import { Navigate, NavLink, useParams } from "react-router";
import { EngineProblem } from "@/components/engine-problem";
import { SchemePicker } from "@/components/scheme-picker";
import { Loading, PanelSkeleton } from "@/components/skeleton";
import { StandardChoices, Toggle } from "@/components/standard-choices";
import { TmdbCredit } from "@/components/tmdb-credit";
import { TmdbKey } from "@/components/tmdb-key";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { Switch } from "@/components/ui/switch";
import { ORIGINALS } from "@/lib/convert";
import { pickFolder } from "@/lib/dialogs";
import {
  type DataSizes,
  type Settings,
  useAddFolder,
  useCheckup,
  useCheckupAction,
  useDataSizes,
  useFolders,
  useForgetFolder,
  useHealth,
  useSaveSettings,
  useSettings,
} from "@/lib/engine";
import { size } from "@/lib/format";
import { openDownloadsPage } from "@/lib/links";
import { LOOKS, useLook, useScheme, useSetLook, useSetScheme } from "@/lib/look";
import {
  useKeepInTray,
  useSetKeepInTray,
  useSetStartWithWindows,
  useStartWithWindows,
} from "@/lib/startup";
import { updateStatus, useInstallUpdate, useReadyUpdate } from "@/lib/updates";
import { cn } from "@/lib/utils";
import { AboutPanel, PcPanel } from "./about-panel";
import { BackupsPanel } from "./backups-panel";
import { ExportPanel } from "./export-panel";
import { Panel } from "./panel";
import { WhereItLives } from "./where-it-lives";

const SECTIONS = [
  { key: "general", label: "General" },
  { key: "libraries", label: "Libraries" },
  { key: "standard", label: "Standard" },
  { key: "titles", label: "Titles and artwork" },
  { key: "data", label: "Your data" },
  { key: "updates", label: "Updates" },
  { key: "about", label: "About" },
] as const;

type Section = (typeof SECTIONS)[number]["key"];

/** Settings: everything chosen in setup, Maku's data, updates and what Maku is made of. */
export function SettingsPage() {
  const { section } = useParams();
  const folders = useFolders();
  const known = SECTIONS.find((each) => each.key === section);
  if (!known) return <Navigate to="/settings/general" replace />;
  return (
    <>
      <h1 className="page-top type-title animate-fade-up">Settings</h1>
      <div className="@container flex flex-wrap items-start gap-5">
        {/* Beside the sections (not above them), it stays put while they scroll: under the
            page's title (6 px, the title's 35.2 px and the 32 px gap). */}
        <nav
          aria-label="Settings"
          className="flex flex-[0_1_220px] animate-fade-up flex-col gap-1 @min-[800px]:sticky @min-[800px]:top-[4.575rem]"
        >
          {SECTIONS.map(({ key, label }) => (
            <NavLink
              key={key}
              to={`/settings/${key}`}
              className={({ isActive }) =>
                cn(
                  "press flex min-h-11 items-center justify-between rounded-14 px-3.5 font-bold text-14",
                  isActive ? "bg-accent/12 text-accent-fg" : "text-fg-soft",
                )
              }
            >
              {label}
              {key === "libraries" && folders.data && (
                <span className="font-mono text-12 text-fg-muted">{folders.data.length}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-5">
          <Content section={known.key} />
        </div>
      </div>
    </>
  );
}

function Content({ section }: { section: Section }) {
  switch (section) {
    case "general":
      return <General />;
    case "libraries":
      return (
        <>
          <Libraries />
          <HealthCheck />
        </>
      );
    case "standard":
      return <Standard />;
    case "titles":
      return <Titles />;
    case "data":
      return <YourData />;
    case "updates":
      return <Updates />;
    case "about":
      return (
        <>
          <PcPanel />
          <AboutPanel />
        </>
      );
  }
}

function General() {
  const start = useStartWithWindows();
  const change = useSetStartWithWindows();
  const keep = useKeepInTray();
  const changeKeep = useSetKeepInTray();
  const look = useLook();
  const changeLook = useSetLook();
  const scheme = useScheme();
  const changeScheme = useSetScheme();
  const problem =
    change.error ??
    start.error ??
    changeKeep.error ??
    keep.error ??
    changeLook.error ??
    look.error ??
    changeScheme.error ??
    scheme.error;
  return (
    <Panel title="General">
      <div className="flex flex-wrap items-center justify-between gap-3.5 rounded-16 border border-edge bg-glass px-4 py-3.5">
        <span className="flex flex-col gap-0.5">
          <span className="font-extrabold">Light or dark</span>
          <span className="text-13 text-fg-muted">
            With Same as Windows, Maku changes when Windows does.
          </span>
        </span>
        <Segmented
          label="Light or dark"
          value={look.data ?? "windows"}
          options={LOOKS}
          onChange={(chosen) => changeLook.mutate(chosen)}
        />
      </div>
      <div className="flex flex-col gap-3 rounded-16 border border-edge bg-glass px-4 py-3.5">
        <span className="flex flex-col gap-0.5">
          <span className="font-extrabold">Colours</span>
          <span className="text-13 text-fg-muted">
            Four schemes, each in light and dark. Maku changes at once.
          </span>
        </span>
        <SchemePicker
          value={changeScheme.variables ?? scheme.data ?? "velvet"}
          onChange={(chosen) => changeScheme.mutate(chosen)}
        />
      </div>
      <Toggle
        label="Start Maku when Windows starts"
        text="It waits in the tray from when you sign in, so the queue, the nightly backup and the watching carry on, and it tells you when a batch is done."
        checked={start.data ?? false}
        onChange={(on) => change.mutate(on)}
      />
      <Toggle
        label="Keep Maku running when you close the window"
        text="Closing the window leaves Maku in the tray, still at work; quit from there. Off, closing the window quits Maku."
        checked={keep.data ?? false}
        onChange={(on) => changeKeep.mutate(on)}
      />
      {problem && (
        <p role="alert" className="text-13 text-broken-fg">
          {String(problem)}
        </p>
      )}
    </Panel>
  );
}

function Libraries() {
  const folders = useFolders();
  const add = useAddFolder();
  const forget = useForgetFolder();
  const [picking, setPicking] = useState(false);

  async function addFolder() {
    setPicking(true);
    try {
      const path = await pickFolder("Choose a folder with series or films in it");
      if (path) add.mutate({ path: "/folders", body: { path } });
    } finally {
      setPicking(false);
    }
  }

  return (
    <Panel
      title="Your video folders"
      note="A folder can hold many series and films in any layout. Maku only looks: forgetting a folder leaves its files as they are."
      action={
        <Button disabled={picking || add.isPending} onClick={() => void addFolder()}>
          <Folder size={16} aria-hidden="true" />
          Add a folder
        </Button>
      }
    >
      <EngineProblem queries={[folders]} />
      {add.isError && (
        <p role="alert" className="text-13 text-broken-fg">
          {add.error.message}
        </p>
      )}
      <ul className="flex flex-col">
        {folders.data?.map((folder) => (
          <li
            key={folder.id}
            className="flex flex-wrap items-center gap-3 border-rule border-b py-3 last:border-b-0"
          >
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="font-mono text-13 [overflow-wrap:anywhere]">{folder.path}</span>
              <span
                className={cn("text-12", folder.available ? "text-fg-muted" : "text-broken-fg")}
              >
                {folder.available
                  ? `${folder.files} ${folder.files === 1 ? "video" : "videos"}`
                  : "Not connected: its files wait till the drive is back"}
              </span>
            </span>
            <Button
              size="sm"
              variant="ghost"
              disabled={forget.isPending}
              onClick={() => forget.mutate({ path: `/folders/${folder.id}` })}
            >
              Forget
            </Button>
          </li>
        ))}
      </ul>
      {folders.data?.length === 0 && (
        <p className="text-13 text-fg-muted">No folders yet. Add the one your videos are in.</p>
      )}
    </Panel>
  );
}

/** The health check: on or off, how far this month's has got, and every video played again. */
function HealthCheck() {
  const stored = useSettings();
  const save = useSaveSettings();
  const checkup = useCheckup();
  const again = useCheckupAction();
  const settings = stored.data;
  const found = checkup.data;
  if (!settings) return null;
  return (
    <Panel
      title="Health check"
      note="A file can be damaged long after Maku read it. This finds out before you want it."
    >
      <Toggle
        label="Test-play every video overnight"
        text="Between 23:00 and 07:00, while nothing converts, Maku plays a few seconds of each at three points, a few at a time, and again a month on. It changes nothing: what didn't play is listed on Home."
        checked={settings.healthCheck}
        onChange={(healthCheck) =>
          save.mutate({ path: "/settings", body: { ...settings, healthCheck } })
        }
      />
      {found && found.total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-13 text-fg-muted">
            {found.checked.toLocaleString("en-GB")} of {found.total.toLocaleString("en-GB")}{" "}
            {found.total === 1 ? "video" : "videos"} checked this month
            {found.unplayed.length > 0 && ` · ${found.unplayed.length} didn't play`}
          </span>
          <Button
            size="sm"
            variant="ghost"
            disabled={again.isPending || found.checked === 0}
            onClick={() => again.mutate({ path: "/checkup/again" })}
          >
            Check them all again
          </Button>
        </div>
      )}
      {(save.error ?? again.error) && (
        <p role="alert" className="text-13 text-broken-fg">
          {(save.error ?? again.error)?.message}
        </p>
      )}
    </Panel>
  );
}

function Standard() {
  const stored = useSettings();
  const save = useSaveSettings();
  const settings = stored.data;
  if (!settings) {
    return (
      <>
        <EngineProblem queries={[stored]} />
        <Loading label="Loading your standard" queries={[stored]}>
          <PanelSkeleton rows={3} />
        </Loading>
      </>
    );
  }
  return (
    <Panel
      title="Your standard"
      note="Every file is brought to this, and nothing is made bigger than it is. Change it, and what's over the new one can be converted again, Maku's own conversions too: from the converted file, unless you put its original back from History first."
    >
      <StandardChoices
        settings={settings}
        onChange={(part) => save.mutate({ path: "/settings", body: { ...settings, ...part } })}
      />
      {save.isError && (
        <p role="alert" className="text-13 text-broken-fg">
          Maku couldn't save that: {save.error.message}
        </p>
      )}
    </Panel>
  );
}

function Titles() {
  return (
    <Panel
      title="Titles and artwork"
      note="Maku finds each series and film on TMDB with your key: its name, seasons, episode titles and posters."
    >
      <TmdbKey />
      <TmdbCredit>
        This product uses the TMDB API but is not endorsed or certified by TMDB.
      </TmdbCredit>
    </Panel>
  );
}

const PARTS: { key: keyof DataSizes; label: string; note: string; color: string }[] = [
  { key: "database", label: "Database", note: "maku.db, one SQLite file", color: "bg-accent" },
  { key: "artwork", label: "Artwork", note: "can be downloaded again", color: "bg-convert" },
  { key: "backups", label: "Backups", note: "last 7 nights", color: "bg-chart" },
  { key: "cache", label: "Cache", note: "can be asked for again", color: "bg-missing" },
  { key: "tools", label: "Tools", note: "ffmpeg", color: "bg-line-strong" },
  { key: "logs", label: "Logs", note: "kept 30 days", color: "bg-control" },
];

function YourData() {
  const sizes = useDataSizes();
  const stored = useSettings();
  const save = useSaveSettings();
  const found = sizes.data;
  const settings = stored.data;
  return (
    <>
      <EngineProblem queries={[sizes, stored]} />
      <WhereItLives found={found ?? null}>
        {found && <Breakdown sizes={found} />}
        <p className="text-13 text-fg-muted">
          The library, your matches, the undo journal, the queue and History all live in one
          database file. There's no server to install, nothing listens beyond this PC, and none of
          it is uploaded.
        </p>
      </WhereItLives>
      {settings && (
        <Panel title="Kept with your files too">
          <Choice
            label="A gap report in each title's folder"
            text="Maku - Gap analysis.md: what's missing, broken and left to convert"
            checked={settings.reports}
            onChange={(reports) =>
              save.mutate({ path: "/settings", body: { ...settings, reports } })
            }
          />
          <Choice
            label="Poster and background pictures next to each show"
            text="poster.jpg · fanart.jpg, which media servers show"
            checked={settings.artwork}
            onChange={(artwork) =>
              save.mutate({ path: "/settings", body: { ...settings, artwork } })
            }
          />
          <div className="flex items-center gap-3.5">
            <Lock size={16} aria-hidden="true" className="ml-3 shrink-0 text-fg-muted" />
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="font-extrabold text-14">
                A small tag inside every converted file
              </span>
              <span className="text-12 text-fg-muted">
                The standard and Maku's version. It's how a converted file is told apart.
              </span>
            </span>
            <span className="text-12 text-fg-muted">Always on</span>
          </div>
        </Panel>
      )}
      <div className="flex flex-wrap items-stretch gap-5">
        <BackupsPanel className="flex-[1_1_300px]" />
        <ExportPanel />
        {found && settings && <Quarantine sizes={found} settings={settings} />}
        {settings && <HistoryKept settings={settings} />}
      </div>
      <p className="flex items-start gap-2.5 rounded-20 border border-tint/14 border-dashed px-5 py-4 text-13 text-fg-soft">
        <Info size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-fg-muted" />
        Uninstalling asks you to export first, and keeps this folder unless you choose to delete it.
        Your videos are never touched.
      </p>
    </>
  );
}

function Breakdown({ sizes }: { sizes: DataSizes }) {
  const total = PARTS.reduce((sum, part) => sum + (sizes[part.key] as number), 0) || 1;
  return (
    <>
      <div aria-hidden="true" className="flex h-3 gap-0.5 overflow-hidden rounded-6 bg-track">
        {PARTS.map((part) => (
          <span
            key={part.key}
            className={cn("h-full animate-grow-x origin-left", part.color)}
            style={{ width: `${((sizes[part.key] as number) / total) * 100}%` }}
          />
        ))}
      </div>
      <dl className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-3">
        {PARTS.map((part) => (
          <div key={part.key} className="flex flex-col gap-0.5">
            <dt className="inline-flex items-center gap-1.5 text-12 text-fg-muted">
              <span aria-hidden="true" className={cn("size-2 rounded-2", part.color)} />
              {part.label}
            </dt>
            <dd className="font-extrabold text-14">{size(sizes[part.key] as number)}</dd>
            <dd className="font-mono text-11 text-fg-faint">{part.note}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}

function Choice(props: {
  label: string;
  text: string;
  checked: boolean;
  onChange: (on: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="flex items-center gap-3.5">
      <Switch
        id={id}
        checked={props.checked}
        onCheckedChange={props.onChange}
        aria-describedby={`${id}-text`}
      />
      <span className="flex min-w-0 flex-col gap-0.5">
        <label htmlFor={id} className="cursor-pointer font-extrabold text-14">
          {props.label}
        </label>
        <span id={`${id}-text`} className="font-mono text-12 text-fg-muted">
          {props.text}
        </span>
      </span>
    </div>
  );
}

const KEEP = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "never", label: "Never" },
] as const;

function Quarantine({ sizes, settings }: { sizes: DataSizes; settings: Settings }) {
  const save = useSaveSettings();
  const bytes = sizes.quarantine.reduce((sum, each) => sum + each.bytes, 0);
  const files = sizes.quarantine.reduce((sum, each) => sum + each.files, 0);
  const keep = settings.quarantineDays === null ? "never" : String(settings.quarantineDays);
  return (
    <Panel
      title="Quarantine"
      note={
        files === 0
          ? "Nothing set aside now."
          : `${size(bytes)} in ${files} ${files === 1 ? "file" : "files"}: copies set aside and converted files' originals, each on its own drive.`
      }
      className="flex-[1_1_300px]"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="font-bold text-14">Keep them</span>
        <Segmented
          label="Keep what's set aside"
          value={keep as (typeof KEEP)[number]["value"]}
          options={KEEP}
          onChange={(value) =>
            save.mutate({
              path: "/settings",
              body: {
                ...settings,
                quarantineDays: value === "never" ? null : (Number(value) as 7 | 30 | 90),
              },
            })
          }
        />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="font-bold text-14">Converted files' originals</span>
        <Segmented
          label="Converted files' originals"
          value={settings.originals}
          options={ORIGINALS}
          onChange={(originals) =>
            save.mutate({ path: "/settings", body: { ...settings, originals } })
          }
        />
      </div>
      <span
        className={cn(
          "text-12",
          settings.originals === "delete" ? "text-broken-fg" : "text-fg-muted",
        )}
      >
        {settings.originals === "delete"
          ? "Deleted for good once each converted copy is checked and in place: no putting back."
          : "Kept here like any copy, so History can put one back till it's cleared out."}
      </span>
      <ul className="flex flex-col gap-1">
        {sizes.quarantine.map((each) => (
          <li key={each.folder} className="font-mono text-12 text-fg-muted">
            {each.folder} · {size(each.bytes)}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

const HISTORY_KEEP = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "forever", label: "Forever" },
] as const;

/** How long History keeps what Maku did: cleared each day of what's older, or kept till the
 * owner clears it on History. */
function HistoryKept({ settings }: { settings: Settings }) {
  const save = useSaveSettings();
  const keep = settings.historyDays === null ? "forever" : String(settings.historyDays);
  return (
    <Panel
      title="History"
      note="Every tidy-up, conversion and scan, and what can be undone or put back."
      className="flex-[1_1_300px]"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="font-bold text-14">Keep it</span>
        <Segmented
          label="Keep History"
          value={keep as (typeof HISTORY_KEEP)[number]["value"]}
          options={HISTORY_KEEP}
          onChange={(value) =>
            save.mutate({
              path: "/settings",
              body: {
                ...settings,
                historyDays: value === "forever" ? null : (Number(value) as 7 | 30 | 90),
              },
            })
          }
        />
      </div>
      <span className="text-12 text-fg-muted">
        {settings.historyDays === null
          ? "Kept till you clear it on History."
          : "Cleared each day of what's older, but for what still has a copy in quarantine. Your files never change."}
      </span>
    </Panel>
  );
}

/** This copy's version, where the update check stands, and checking now rather than waiting for
 * the daily check. A version found can be installed from here too, though its card was put off. */
function Updates() {
  const health = useHealth();
  const update = useReadyUpdate();
  const install = useInstallUpdate();
  return (
    <Panel
      title="Updates"
      note="Maku looks for a new version when it starts and once a day, and downloads it in the background. When one is ready, it shows what's new and asks before restarting."
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="flex flex-col gap-0.5">
          <span className="text-14">
            This is Maku <span className="font-mono">{health.data?.version ?? "…"}</span>
          </span>
          <span role="status" className="text-13 text-fg-muted">
            {updateStatus(update)}
          </span>
        </span>
        <div className="flex flex-wrap gap-2.5">
          {update.data ? (
            <Button variant="primary" disabled={install.isPending} onClick={() => install.mutate()}>
              Restart and update
            </Button>
          ) : (
            import.meta.env.PROD && (
              <Button disabled={update.isFetching} onClick={() => void update.refetch()}>
                Check for a new version
              </Button>
            )
          )}
          <Button onClick={() => void openDownloadsPage()}>Every version</Button>
        </div>
      </div>
      {install.isError && (
        <p role="alert" className="text-13 text-broken-fg">
          The update didn't start: {String(install.error)}
        </p>
      )}
    </Panel>
  );
}
