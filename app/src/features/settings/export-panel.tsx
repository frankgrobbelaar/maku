import { Check } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { pickExport, pickFolder } from "@/lib/dialogs";
import { restartEngine, useEngine, useExport, useImportExport } from "@/lib/engine";
import { showInFolder, useExplorer } from "@/lib/explorer";
import { size, split } from "@/lib/format";
import { Panel } from "./panel";

const IN_IT = [
  "The database, as SQLite",
  "Every file change, as CSV",
  "The library's videos, as CSV",
  "Your settings",
];

/**
 * Settings > Your data > Export and import: one zip with everything, and an export brought
 * back, which happens as the engine starts again (Maku asks for that right after), the way a
 * backup is restored.
 */
export function ExportPanel() {
  const engine = useEngine();
  const exporting = useExport();
  const importing = useImportExport();
  const explorer = useExplorer();
  const [picking, setPicking] = useState(false);
  const [chosen, setChosen] = useState<string | null>(null); // an export, not yet confirmed
  // The import asked for, and the engine asked (its token): the next one imports it.
  const [asked, setAsked] = useState<{ path: string; token: string } | null>(null);
  const waiting = asked !== null && !(engine.state === "ready" && engine.token !== asked.token);

  async function exportEverything() {
    setPicking(true);
    try {
      const folder = await pickFolder("Where should the export go?");
      if (folder) exporting.mutate({ path: "/export", body: { folder } });
    } finally {
      setPicking(false);
    }
  }

  async function chooseExport() {
    setPicking(true);
    try {
      const path = await pickExport("Which Maku export should Maku import?");
      if (path) {
        importing.reset();
        setChosen(path);
      }
    } finally {
      setPicking(false);
    }
  }

  function importChosen() {
    if (!chosen || engine.state !== "ready") return;
    const { token } = engine;
    importing.mutate(
      { path: "/backups/import", body: { path: chosen } },
      {
        onSuccess: () => {
          setAsked({ path: chosen, token });
          setChosen(null);
          void restartEngine();
        },
      },
    );
  }

  const done = exporting.data;
  return (
    <Panel
      title="Export and import"
      note="One zip with everything, in files you can open without Maku."
      className="flex-[1_1_300px] border-accent/35 bg-accent/5"
    >
      <ul className="flex flex-col gap-1.5 text-13">
        {IN_IT.map((item) => (
          <li key={item} className="flex items-center gap-2.5">
            <span aria-hidden="true" className="size-1.5 rounded-full bg-accent" />
            {item}
          </li>
        ))}
      </ul>
      {done && (
        <div className="flex flex-wrap items-center gap-2.5 rounded-14 bg-tint/4 px-3.5 py-2.5 text-13">
          <Check size={16} aria-hidden="true" className="text-accent-fg" />
          <span className="min-w-0 flex-1 font-mono text-12 [overflow-wrap:anywhere]">
            {done.path} · {size(done.size)}
          </span>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => explorer.run(() => showInFolder(done.path))}
          >
            Show in folder
          </Button>
        </div>
      )}
      {waiting && (
        <p className="text-13 text-fg-soft">
          Maku is starting again to import {split(asked?.path ?? "")[0]}.
        </p>
      )}
      {chosen && (
        <fieldset
          aria-label={`Import ${split(chosen)[0]}?`}
          className="flex animate-fade-up flex-col gap-3 rounded-16 border border-edge bg-glass p-4"
        >
          <span className="font-extrabold text-14">Import {split(chosen)[0]}?</span>
          <span className="text-13 text-fg-soft">
            Maku's records become the export's: matches, tidy-ups, History, the queue and your
            settings. Your videos stay as they are. What Maku knows now is backed up first, so you
            can come back to it from Backups.
          </span>
          {importing.isError && (
            <p role="alert" className="text-13 text-broken-fg">
              {importing.error.message}
            </p>
          )}
          <div className="flex flex-wrap gap-2.5">
            <Button
              size="sm"
              variant="danger"
              disabled={importing.isPending}
              onClick={importChosen}
            >
              Import it
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setChosen(null)}>
              Cancel
            </Button>
          </div>
        </fieldset>
      )}
      {(exporting.isError || explorer.problem) && (
        <p role="alert" className="text-13 text-broken-fg">
          {exporting.error?.message ?? explorer.problem}
        </p>
      )}
      <div className="mt-auto flex flex-wrap gap-2.5">
        <Button
          variant="primary"
          disabled={picking || exporting.isPending || waiting}
          onClick={() => void exportEverything()}
        >
          {exporting.isPending ? "Exporting…" : "Export everything"}
        </Button>
        <Button disabled={picking || waiting} onClick={() => void chooseExport()}>
          Import an export
        </Button>
      </div>
    </Panel>
  );
}
