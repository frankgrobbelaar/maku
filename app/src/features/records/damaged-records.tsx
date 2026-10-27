import { useState } from "react";
import { Button } from "@/components/ui/button";
import { type Damage, restartEngine, useRecordsAction } from "@/lib/engine";
import { madeAt } from "@/lib/format";

/**
 * Maku's records are damaged past use (maku.db won't open): the engine answers nothing else, so
 * this stands in for every page till a way back is taken. The newest backup that opens takes the
 * records back to when it was made; with none, Maku starts again with new records, as on its
 * first day. The damaged file stays beside them either way, and the library isn't touched. When
 * it was the disk that couldn't read them (a drive away a moment), trying again comes first.
 */
export function DamagedRecords({ damage }: { damage: Damage }) {
  const action = useRecordsAction();
  const [starting, setStarting] = useState<string | null>(null); // what Maku starts again with
  const when = damage.made ? madeAt(damage.made) : null;
  const way = when
    ? {
        path: "/records/restore",
        label: `Restore the backup from ${when}`,
        offer: `The newest backup that opens is from ${when}. Restoring it takes Maku's records back to then.`,
        after: `Maku is starting again with the backup from ${when}.`,
      }
    : {
        path: "/records/new",
        label: "Start with new records",
        offer:
          "No backup opens either. Maku can start again with new records, as on its first day: you choose your folders again, and nothing in them changes.",
        after: "Maku is starting again with new records.",
      };

  function takeTheWayBack() {
    action.mutate(
      { path: way.path },
      {
        onSuccess: () => {
          setStarting(way.after);
          void restartEngine();
        },
      },
    );
  }

  function tryAgain() {
    setStarting("Maku is starting again, to read its records once more.");
    void restartEngine();
  }

  return (
    <>
      <header className="page-top flex max-w-2xl animate-fade-up flex-col gap-1.5">
        <h1 className="type-title">Maku's records are damaged</h1>
        <p className="text-14 text-fg-muted">
          {damage.badRead
            ? "Maku couldn't read maku.db, where it keeps what it knows about your library, off its disk."
            : "Maku can't read maku.db, where it keeps what it knows about your library."}{" "}
          Your videos are as they were.
        </p>
      </header>
      <section
        aria-label="The way back"
        className="flex max-w-2xl animate-fade-up flex-col items-start gap-4 rounded-24 border border-edge bg-glass p-6 shadow-panel"
      >
        {starting ? (
          <p role="status" className="text-15">
            {starting}
          </p>
        ) : damage.badRead ? (
          <>
            <p className="text-15">
              If its drive was away for a moment, trying again is all it needs. {way.offer}
            </p>
            <div className="flex flex-wrap gap-2.5">
              <Button variant="primary" onClick={tryAgain}>
                Try again
              </Button>
              <Button disabled={action.isPending} onClick={takeTheWayBack}>
                {way.label}
              </Button>
            </div>
          </>
        ) : (
          <>
            <p className="text-15">{way.offer}</p>
            <Button variant="primary" disabled={action.isPending} onClick={takeTheWayBack}>
              {way.label}
            </Button>
          </>
        )}
        {action.error && (
          <p role="alert" className="text-13 text-broken-fg">
            {action.error.message}
          </p>
        )}
        <p className="text-12 text-fg-faint">
          Maku keeps the damaged file beside its records, as it is. SQLite says: {damage.problem}.
        </p>
      </section>
    </>
  );
}
