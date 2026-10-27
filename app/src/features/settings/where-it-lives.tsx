import { Check } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { pickFolder } from "@/lib/dialogs";
import { type DataSizes, restartEngine, useEngine, useMoveData } from "@/lib/engine";
import { openFolder, useExplorer } from "@/lib/explorer";
import { size } from "@/lib/format";
import { Panel } from "./panel";

/**
 * Settings > Your data > Where your data lives: the folder, opening it, and moving it to another
 * drive, which happens as the engine starts again (Maku asks for that right after).
 */
export function WhereItLives(props: { found: DataSizes | null; children: React.ReactNode }) {
  const engine = useEngine();
  const explorer = useExplorer();
  const move = useMoveData();
  const [picking, setPicking] = useState(false);
  const [target, setTarget] = useState<string | null>(null); // chosen, not yet confirmed
  // The move asked for, and the engine asked (its token): the next one moves the data.
  const [asked, setAsked] = useState<{ target: string; token: string } | null>(null);
  const restarted = engine.state === "ready" && engine.token !== asked?.token && !!props.found;
  const moving = asked !== null && !restarted;
  const { found } = props;

  async function choose() {
    setPicking(true);
    try {
      const picked = await pickFolder("Where should Maku's data go?");
      if (picked) {
        move.reset();
        setTarget(makuFolderIn(picked));
      }
    } finally {
      setPicking(false);
    }
  }

  function confirm() {
    if (!target || engine.state !== "ready") return;
    const { token } = engine;
    move.mutate(
      { path: "/data/move", body: { folder: target } },
      {
        onSuccess: () => {
          setAsked({ target, token });
          setTarget(null);
          void restartEngine();
        },
      },
    );
  }

  if (moving) {
    return (
      <Panel title="Where your data lives">
        <p className="text-13 text-fg-soft">
          Maku is starting again to move its data to{" "}
          <span className="font-mono text-12">{asked?.target}</span>.
        </p>
      </Panel>
    );
  }
  if (!found) return null;
  const total =
    found.database + found.artwork + found.cache + found.logs + found.backups + found.tools;
  return (
    <Panel
      title="Where your data lives"
      note={<span className="font-mono text-12 text-fg-soft">{found.folder}</span>}
      action={
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => explorer.run(() => openFolder(found.folder))}>Open folder</Button>
          <Button disabled={picking || move.isPending} onClick={() => void choose()}>
            Move to another drive
          </Button>
        </div>
      }
    >
      {explorer.problem && (
        <p role="alert" className="text-13 text-broken-fg">
          {explorer.problem}
        </p>
      )}
      <Outcome moved={found.moved} />
      {target && (
        <fieldset
          aria-label={`Move Maku's data to ${target}?`}
          className="flex animate-fade-up flex-col gap-3 rounded-16 border border-accent/35 bg-accent/5 p-4"
        >
          <span className="font-extrabold text-14">
            Move Maku's data to <span className="font-mono text-13">{target}</span>?
          </span>
          <span className="text-13 text-fg-soft">
            It's {size(total)}: the database, artwork, backups, logs and tools. Maku starts its
            engine again to move it, and anything under way carries on after. The old folder goes
            once the copy is checked.
          </span>
          {move.isError && (
            <p role="alert" className="text-13 text-broken-fg">
              {move.error.message}
            </p>
          )}
          <div className="flex flex-wrap gap-2.5">
            <Button size="sm" variant="primary" disabled={move.isPending} onClick={confirm}>
              Move it
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setTarget(null)}>
              Cancel
            </Button>
          </div>
        </fieldset>
      )}
      {props.children}
    </Panel>
  );
}

/** How today's move went, if there was one today. */
function Outcome({ moved }: { moved: DataSizes["moved"] }) {
  if (!moved || new Date(moved.at).toDateString() !== new Date().toDateString()) return null;
  return moved.problem ? (
    <p role="alert" className="text-13 text-broken-fg">
      Maku's data stayed here: {moved.problem}
    </p>
  ) : (
    <p className="flex items-center gap-2 text-13 text-fg-soft">
      <Check size={16} aria-hidden="true" className="shrink-0 text-accent-fg" />
      Moved here from <span className="font-mono text-12">{moved.source}</span>.
    </p>
  );
}

/** Maku's data goes into a folder of its own: "F:\" becomes "F:\Maku"; "F:\Maku" stays. */
function makuFolderIn(picked: string): string {
  const folder = picked.replace(/[\\/]+$/, "");
  return /(^|[\\/])maku$/i.test(folder) ? folder : `${folder}\\Maku`;
}
