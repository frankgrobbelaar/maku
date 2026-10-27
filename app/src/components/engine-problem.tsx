import { useState } from "react";
import { Button } from "@/components/ui/button";
import { restartEngine, useEngine } from "@/lib/engine";

/** What a screen asked the engine for: the parts of a query result a problem needs. */
interface Asked {
  isError: boolean;
  isFetching: boolean;
  error: Error | null;
  refetch: () => Promise<unknown>;
}

const PANEL =
  "flex animate-fade-up flex-col gap-3 rounded-18 border border-broken/26 bg-broken/7 px-4.5 py-4";

/**
 * Why a screen's data isn't there: the engine isn't running, or it couldn't answer. Names the
 * problem, says what Maku did, and offers the next step. Shows nothing while all is well.
 */
export function EngineProblem({ queries }: { queries: Asked[] }) {
  const engine = useEngine();
  if (engine.state === "failed") {
    return <EngineFailed message={engine.message} details={engine.details} />;
  }
  const failed = queries.filter((query) => query.isError);
  const [first] = failed;
  if (!first) return null;
  return (
    <section role="alert" className={PANEL}>
      <p>
        <strong>Maku couldn't load this screen.</strong> {first.error?.message} Nothing in your
        folders was touched.
      </p>
      <div>
        <Button
          variant="primary"
          size="sm"
          disabled={failed.some((query) => query.isFetching)}
          onClick={() => {
            for (const query of failed) void query.refetch();
          }}
        >
          Try again
        </Button>
      </div>
    </section>
  );
}

/** The engine isn't running: say so, say what Maku did, offer the next step. */
function EngineFailed({ message, details }: { message: string; details: string }) {
  const [retrying, setRetrying] = useState(false);

  return (
    <section role="alert" className={PANEL}>
      <p>
        <strong>Maku's engine isn't running.</strong> {message} Nothing in your folders was touched.
      </p>
      {details && (
        <pre className="max-h-40 overflow-auto rounded-12 bg-inset px-3 py-2.5 font-mono text-11 text-fg-muted leading-[1.7]">
          {details}
        </pre>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          size="sm"
          disabled={retrying}
          onClick={() => {
            setRetrying(true);
            restartEngine().finally(() => setRetrying(false));
          }}
        >
          Try again
        </Button>
        {details && (
          <Button variant="ghost" size="sm" onClick={() => navigator.clipboard.writeText(details)}>
            Copy details
          </Button>
        )}
      </div>
    </section>
  );
}
