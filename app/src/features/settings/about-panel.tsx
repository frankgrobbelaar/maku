import { Link } from "react-router";
import { ThisPcPanel } from "@/components/this-pc";
import { TmdbCredit } from "@/components/tmdb-credit";
import { useEngine, useHealth, useSystem, useTmdb } from "@/lib/engine";
import { openDownloadsPage } from "@/lib/links";
import { updateStatus, useReadyUpdate } from "@/lib/updates";
import { Panel } from "./panel";

const LINK =
  "cursor-pointer text-accent-fg underline-offset-3 hover:text-accent-fg-hover hover:underline";

/** This PC: what Maku can do here and how long it takes, tested again on asking. */
export function PcPanel() {
  const system = useSystem();
  return system.data ? <ThisPcPanel system={system.data} /> : null;
}

/** About Maku: this copy at a glance (engine, data folder, database, lookups and updates), its
 * licence, and whose work it stands on. */
export function AboutPanel() {
  const engine = useEngine();
  const health = useHealth();
  const tmdb = useTmdb();
  const update = useReadyUpdate();

  const engineText = { starting: "Starting…", ready: "Running", failed: "Not running" }[
    engine.state
  ];

  return (
    <Panel
      title="About Maku"
      note="幕, the curtain: a personal tool for one library of series and films."
    >
      <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2.5 text-13">
        <dt className="text-fg-muted">Version</dt>
        <dd className="font-mono">{health.data?.version ?? "…"}</dd>
        <dt className="text-fg-muted">Engine</dt>
        <dd className="flex items-center gap-2">
          {engine.state === "starting" && (
            <span className="size-2 animate-pulse rounded-full bg-accent" aria-hidden="true" />
          )}
          {engineText}
        </dd>
        <dt className="text-fg-muted">Data folder</dt>
        <dd className="font-mono text-12 text-fg-soft [overflow-wrap:anywhere]">
          {health.data?.dataDir ?? "…"}
        </dd>
        <dt className="text-fg-muted">Database</dt>
        <dd>{health.data ? `Ready · schema version ${health.data.schemaVersion}` : "…"}</dd>
        <dt className="text-fg-muted">Titles and artwork</dt>
        <dd>
          {tmdb.data?.connected && `TMDB connected · key ending ${tmdb.data.keyEnd}`}
          {tmdb.data && !tmdb.data.connected && (
            <>
              No key: Maku can't find your series and films ·{" "}
              <Link to="/settings/titles" className={LINK}>
                Add your TMDB key
              </Link>
            </>
          )}
          {!tmdb.data && "…"}
        </dd>
        <dt className="text-fg-muted">Updates</dt>
        <dd>{updateStatus(update)}</dd>
        <dt className="text-fg-muted">Versions</dt>
        <dd>
          <button type="button" className={LINK} onClick={() => void openDownloadsPage()}>
            Every version and what changed
          </button>
        </dd>
        <dt className="text-fg-muted">Licence</dt>
        <dd>MIT. Anyone may fork it; the repo takes no contributions.</dd>
      </dl>
      <p className="text-13 text-fg-muted">
        Maku is for videos you have the right to keep and watch. It looks after the files on this PC
        and plays them in its own window; it never searches for, downloads or shares video.
      </p>
      <p className="text-13 text-fg-muted">
        Maku stands on others' work: ffmpeg reads and converts the videos, TMDB says what each one
        is, Whisper and pyannote make English subtitles. THIRD-PARTY-NOTICES.txt, next to Maku,
        lists every part with its licence.
      </p>
      <TmdbCredit>
        This product uses the TMDB API but is not endorsed or certified by TMDB.
      </TmdbCredit>
    </Panel>
  );
}
