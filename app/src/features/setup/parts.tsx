import { X } from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

// The pieces every setup step is built from.

export function Panel(props: {
  title: string;
  labelledBy: string;
  intro?: string;
  children?: ReactNode;
}) {
  const panel = useRef<HTMLElement>(null);

  // A new step comes into view as it opens, below the steps already done.
  useEffect(() => {
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    panel.current?.scrollIntoView?.({ block: "nearest", behavior: still ? "auto" : "smooth" });
  }, []);

  return (
    <section
      ref={panel}
      aria-labelledby={props.labelledBy}
      className="flex animate-pop scroll-mt-6 flex-col gap-5 rounded-24 border border-accent/35 bg-raised p-6 shadow-panel"
    >
      <div className="flex flex-col gap-1">
        <h2 id={props.labelledBy} className="font-extrabold text-24 tracking-[-0.02em]">
          {props.title}
        </h2>
        {props.intro && <p className="text-14 text-fg-muted">{props.intro}</p>}
      </div>
      {props.children}
    </section>
  );
}

export function Footer({ note, children }: { note: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="flex-[1_1_320px] text-13 text-fg-muted">{note}</p>
      <div className="flex gap-2.5">{children}</div>
    </div>
  );
}

export function Row(props: {
  icon: ReactNode;
  title: string;
  dashed?: boolean;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section
      className={cn(
        "flex animate-fade-up flex-wrap items-center gap-4 rounded-20 border px-5 py-4.5",
        props.dashed
          ? "border-tint/12 border-dashed text-fg-muted"
          : "border-edge bg-glass text-fg",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "inline-flex size-10 shrink-0 items-center justify-center rounded-full",
          props.dashed ? "bg-tint/5" : "bg-accent/12 text-accent-fg",
        )}
      >
        {props.icon}
      </span>
      <div className="flex min-w-0 flex-[1_1_320px] flex-col gap-1">
        <h2 className={cn("font-extrabold text-15", props.dashed && "text-fg-soft")}>
          {props.title}
        </h2>
        {props.children}
      </div>
      {props.action}
    </section>
  );
}

export function FolderChip({ path, onRemove }: { path: string; onRemove?: () => void }) {
  return (
    <span className="inline-flex h-8 items-center gap-2 rounded-16 bg-tint/6 pr-1.5 pl-3 font-mono text-12">
      {path}
      <span className="font-bold font-sans text-11 text-accent-fg">watching</span>
      {onRemove && (
        <button
          type="button"
          aria-label={`Remove ${path}`}
          onClick={onRemove}
          className="inline-flex size-6 cursor-pointer items-center justify-center rounded-full text-fg-muted hover:bg-tint/8 hover:text-fg"
        >
          <X size={14} aria-hidden="true" />
        </button>
      )}
    </span>
  );
}
