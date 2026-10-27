import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

const FOCUS =
  "peer-focus-visible:outline-2 peer-focus-visible:outline-accent-fg peer-focus-visible:outline-offset-3";

/**
 * How a checkbox looks, drawn beside the real one hidden before it (`peer sr-only`), which keeps
 * the keyboard and screen readers: ticked in amber, a bar when some of a group is picked
 * ("mixed"), an empty ring otherwise.
 */
export function CheckBox({ state }: { state: boolean | "mixed" }) {
  if (state === true) {
    return (
      <span
        aria-hidden="true"
        className={cn(
          "inline-flex size-5 shrink-0 items-center justify-center rounded-6 bg-accent text-on-accent",
          FOCUS,
        )}
      >
        <Check size={11} strokeWidth={3.6} />
      </span>
    );
  }
  if (state === "mixed") {
    return (
      <span
        aria-hidden="true"
        className={cn(
          "inline-flex size-5 shrink-0 items-center justify-center rounded-6 bg-accent/25 shadow-[inset_0_0_0_2px_var(--color-accent)]",
          FOCUS,
        )}
      >
        <span className="h-0.5 w-2.5 bg-accent-fg" />
      </span>
    );
  }
  return (
    <span
      aria-hidden="true"
      className={cn(
        "size-5 shrink-0 rounded-6 shadow-[inset_0_0_0_2px_var(--color-control)]",
        FOCUS,
      )}
    />
  );
}
