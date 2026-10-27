import { Check } from "lucide-react";
import { RadioGroup } from "radix-ui";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  type Backup,
  type Backups,
  restartEngine,
  useBackUp,
  useBackups,
  useEngine,
  useRestoreBackup,
} from "@/lib/engine";
import { madeAt, size } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Panel } from "./panel";

/**
 * Settings > Your data > Backups: the last backup of Maku's records, one made now, and one put
 * back. Restoring happens as the engine starts again, which Maku asks for right after.
 */
export function BackupsPanel({ className }: { className?: string }) {
  const engine = useEngine();
  const found = useBackups();
  const backUp = useBackUp();
  const restore = useRestoreBackup();
  const [choosing, setChoosing] = useState(false);
  const [chosen, setChosen] = useState<string | null>(null);
  // The backup asked for, and the engine asked (its token): the next one restores it as it starts.
  const [asked, setAsked] = useState<{ name: string; token: string } | null>(null);
  const restarted =
    engine.state === "ready" && engine.token !== asked?.token && found.data !== undefined;
  const restoring = asked !== null && !restarted;
  const list = found.data?.backups ?? [];
  const problem = backUp.error ?? restore.error ?? found.error;

  function restoreChosen() {
    if (!chosen || engine.state !== "ready") return;
    const { token } = engine;
    restore.mutate(
      { path: `/backups/${encodeURIComponent(chosen)}/restore` },
      {
        onSuccess: () => {
          setAsked({ name: chosen, token });
          setChoosing(false);
          void restartEngine();
        },
      },
    );
  }

  return (
    <Panel title="Backups" note="Every night at 03:00, keeping the last 7." className={className}>
      {restoring ? (
        <p className="text-13 text-fg-soft">
          Maku is starting again to restore the backup from {madeAt(madeOf(asked?.name ?? ""))}.
        </p>
      ) : (
        <>
          <Last backup={list[0]} loading={!found.data} />
          {found.data && <Outcome restored={found.data.restored} />}
          {choosing && list.length > 0 && (
            <Choose backups={list} chosen={chosen} onChoose={setChosen} />
          )}
        </>
      )}
      {problem && (
        <p role="alert" className="text-13 text-broken-fg">
          {problem.message}
        </p>
      )}
      {!restoring && (
        <div className="mt-auto flex flex-wrap gap-2">
          {choosing ? (
            <>
              <Button
                variant="danger"
                disabled={!chosen || restore.isPending}
                onClick={restoreChosen}
              >
                Restore it
              </Button>
              <Button variant="ghost" onClick={() => setChoosing(false)}>
                Cancel
              </Button>
            </>
          ) : (
            <>
              <Button
                disabled={!found.data || backUp.isPending}
                onClick={() => backUp.mutate({ path: "/backups" })}
              >
                {backUp.isPending ? "Backing up…" : "Back up now"}
              </Button>
              <Button disabled={list.length === 0} onClick={() => setChoosing(true)}>
                Restore a backup
              </Button>
            </>
          )}
        </div>
      )}
    </Panel>
  );
}

/** The newest backup: when it was made, its size, and that it was checked. */
function Last({ backup, loading }: { backup: Backup | undefined; loading: boolean }) {
  if (loading) return null;
  return (
    <div className="flex items-center gap-2.5 rounded-16 bg-tint/4 px-3.5 py-3">
      {backup ? (
        <Check size={18} strokeWidth={3} aria-hidden="true" className="shrink-0 text-accent-fg" />
      ) : (
        <span
          aria-hidden="true"
          className="size-4.5 shrink-0 rounded-full shadow-[inset_0_0_0_2px_var(--color-missing)]"
        />
      )}
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="font-extrabold text-14">
          {backup ? `Last backup ${madeAt(backup.made)}` : "No backup yet"}
        </span>
        <span className="text-12 text-fg-muted">
          {backup ? `${size(backup.size)} · checked` : "The first is made tonight at 03:00."}
        </span>
      </span>
    </div>
  );
}

/** How today's restore went, if there was one today. */
function Outcome({ restored }: { restored: Backups["restored"] }) {
  if (!restored || new Date(restored.at).toDateString() !== new Date().toDateString()) {
    return null;
  }
  const what = / from an export( \(\d+\))?\.db$/.test(restored.name)
    ? "the export"
    : `the backup from ${madeAt(madeOf(restored.name))}`;
  return restored.problem ? (
    <p role="alert" className="text-13 text-broken-fg">
      {capitalised(what)} wasn't restored: {restored.problem}
    </p>
  ) : (
    <p className="flex items-center gap-2 text-13 text-fg-soft">
      <Check size={16} aria-hidden="true" className="shrink-0 text-accent-fg" />
      {what === "the export" ? "Imported the export." : `Restored ${what}.`}
    </p>
  );
}

/** The backups to go back to, newest first, and what going back means. */
function Choose(props: {
  backups: Backup[];
  chosen: string | null;
  onChoose: (name: string) => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <RadioGroup.Root
        aria-label="The backup to restore"
        value={props.chosen ?? ""}
        onValueChange={props.onChoose}
        className="flex flex-col gap-1"
      >
        {props.backups.map((backup) => {
          const on = props.chosen === backup.name;
          const made = capitalised(madeAt(backup.made));
          const kind = kindOf(backup);
          return (
            <RadioGroup.Item
              key={backup.name}
              value={backup.name}
              aria-label={`${made}${kind ? ` · ${kind}` : ""}, ${size(backup.size)}`}
              className={cn(
                "press flex min-h-11 cursor-pointer items-center gap-3 rounded-14 px-3 text-left text-14",
                on ? "bg-accent/10 font-extrabold text-fg" : "font-bold text-fg-soft",
              )}
            >
              <Dot on={on} />
              <span className="min-w-0 flex-1">
                {made}
                {kind && <span className="font-medium text-12 text-fg-muted"> · {kind}</span>}
              </span>
              <span className="font-medium font-mono text-12 text-fg-muted">
                {size(backup.size)}
              </span>
            </RadioGroup.Item>
          );
        })}
      </RadioGroup.Root>
      <p className="text-12 text-fg-muted">
        Maku's records go back to then: matches, tidy-ups, History and the queue. Your videos stay
        as they are. What Maku knows now is backed up first, so you can come back to it.
      </p>
    </div>
  );
}

function Dot({ on }: { on: boolean }) {
  return on ? (
    <span
      aria-hidden="true"
      className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-accent"
    >
      <span className="size-2 rounded-full bg-on-accent" />
    </span>
  ) : (
    <span
      aria-hidden="true"
      className="size-5 shrink-0 rounded-full shadow-[inset_0_0_0_2px_var(--color-control)]"
    />
  );
}

/** "today 03:00", "yesterday 03:00", "9 October 03:00", from a local time ("2026-10-11T03:00"). */
/** What kind of backup it is, when it isn't a nightly one. */
function kindOf(backup: Backup): string | null {
  if (backup.beforeRestoring) return "before a restore";
  if (backup.fromExport) return "from an export";
  return backup.byHand ? "by hand" : null;
}

/** When a backup was made, from its name: "maku 2026-10-11 0300.db" is "2026-10-11T03:00". */
function madeOf(name: string): string {
  const found = /^maku (\d{4}-\d{2}-\d{2}) (\d{2})(\d{2})/.exec(name);
  return found ? `${found[1]}T${found[2]}:${found[3]}` : "";
}

function capitalised(words: string): string {
  return words.charAt(0).toUpperCase() + words.slice(1);
}
