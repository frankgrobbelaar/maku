import { ArrowDownToLine } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { openDownloadsPage } from "@/lib/links";
import { useInstallUpdate, useReadyUpdate, whatsNew } from "@/lib/updates";

const SHOWN = 4; // entries listed before "and N more"

/** Shown once an update has downloaded in the background, with what changed in it. */
export function UpdateCard() {
  const update = useReadyUpdate();
  const install = useInstallUpdate();
  const [later, setLater] = useState(false);

  if (!update.data || later) return null;

  const changes = whatsNew(update.data.notes);
  const more = changes.length - SHOWN;

  return (
    <section
      aria-labelledby="update-title"
      className="fixed right-6 bottom-6 z-10 flex w-[min(26rem,calc(100vw-3rem))] animate-pop flex-col gap-4.5 rounded-28 border border-tint/10 bg-dialog p-7 shadow-dialog"
    >
      <div className="flex items-center gap-3.5">
        <span className="inline-flex size-12 shrink-0 items-center justify-center rounded-full bg-accent text-on-accent">
          <ArrowDownToLine size={22} strokeWidth={2.4} aria-hidden="true" />
        </span>
        <div className="flex flex-col">
          <h2 id="update-title" className="font-extrabold text-22 tracking-[-0.01em]">
            Maku {update.data.version} is ready
          </h2>
          <span className="text-13 text-fg-muted">Downloaded in the background</span>
        </div>
      </div>
      {changes.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="font-bold text-12 text-fg-muted uppercase tracking-[0.06em]">
            What's new
          </h3>
          <ul className="flex flex-col gap-1.5 text-13 text-fg-soft">
            {changes.slice(0, SHOWN).map((change) => (
              <li key={change} className="flex gap-2.5">
                {/* The board's amber dot: a list marker would vanish under line-clamp. */}
                <span
                  aria-hidden="true"
                  className="mt-2 size-1.5 shrink-0 rounded-full bg-accent"
                />
                <span className="line-clamp-2">{change}</span>
              </li>
            ))}
          </ul>
          {more > 0 && (
            <p className="text-13 text-fg-muted">
              And {more} more {more === 1 ? "change" : "changes"}.
            </p>
          )}
        </div>
      )}
      <p className="text-13 text-fg-soft">
        Maku closes, updates and opens again. Your settings and library stay as they are.
      </p>
      <div className="flex flex-wrap gap-2.5">
        <Button variant="primary" disabled={install.isPending} onClick={() => install.mutate()}>
          Restart and update
        </Button>
        <Button variant="ghost" onClick={() => setLater(true)}>
          Later
        </Button>
        <Button variant="ghost" onClick={() => void openDownloadsPage()}>
          Every version
        </Button>
      </div>
      {install.isError && (
        <p role="alert" className="text-13 text-broken-fg">
          The update didn't start: {String(install.error)}
        </p>
      )}
    </section>
  );
}
