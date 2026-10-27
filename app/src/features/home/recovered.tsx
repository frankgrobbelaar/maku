import { RotateCw } from "lucide-react";
import { useNavigate } from "react-router";
import { type Recovery, useRecovery, useRecoverySeen } from "@/lib/engine";

/**
 * After Maku closed unexpectedly (a crash, a power cut): what it settled as it started again,
 * until the owner has looked, for a day. History has each file.
 */
export function Recovered() {
  const recovery = useRecovery();
  const seen = useRecoverySeen();
  const navigate = useNavigate();
  const found = recovery.data;
  if (!found) return null;
  return (
    <div
      role="status"
      className="flex animate-fade-up gap-3 rounded-18 border border-tint/10 bg-raised px-4.5 py-4 shadow-toast"
    >
      <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-accent/14 text-accent-fg">
        <RotateCw size={18} aria-hidden="true" />
      </span>
      <span className="flex flex-col items-start gap-1.5 text-14">
        <span>
          <strong className="font-extrabold">Maku closed unexpectedly.</strong>{" "}
          {recoveryWords(found)}
        </span>
        <button
          type="button"
          className="press cursor-pointer font-extrabold text-13 text-accent-fg"
          onClick={() => {
            seen.mutate({ path: "/recovery/seen" });
            void navigate("/history");
          }}
        >
          See what happened
        </button>
      </span>
    </div>
  );
}

/**
 * What a start settled, in one sentence: "One file was restarted from the beginning; the
 * original was never touched and nothing was lost."
 */
function recoveryWords(found: Recovery): string {
  const parts = [
    found.restarted &&
      `${many(found.restarted, "file was", "files were")} restarted from the beginning`,
    found.finished &&
      `${many(found.finished, "converted file went", "converted files went")} into ${
        found.finished === 1 ? "its original's place" : "their originals' places"
      }`,
    found.putBack && `${many(found.putBack, "original was", "originals were")} put back`,
    found.moves && `${many(found.moves, "file move was", "file moves were")} settled`,
  ].filter((part): part is string => Boolean(part));
  const only = found.restarted > 0 && parts.length === 1;
  const kept = found.restarted === 1 ? "the original was" : "the originals were";
  const tail = only ? `${kept} never touched and nothing was lost` : "nothing was lost";
  return `${capitalised(listed(parts))}; ${tail}.`;
}

/** "one file was", "3 files were". */
function many(count: number, one: string, more: string): string {
  return count === 1 ? `one ${one}` : `${count} ${more}`;
}

/** "a", "a and b", "a, b and c". */
function listed(parts: string[]): string {
  if (parts.length < 2) return parts[0] ?? "";
  return `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`;
}

function capitalised(words: string): string {
  return words.charAt(0).toUpperCase() + words.slice(1);
}
