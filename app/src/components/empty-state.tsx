import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  /** What this place is for, in one or two plain sentences. */
  children: ReactNode;
  illustration?: ReactNode;
  /** The one thing to do next. */
  action?: ReactNode;
  note?: ReactNode;
}

/** A place with nothing in it yet: what it's for and the one next step. */
export function EmptyState({ title, children, illustration, action, note }: EmptyStateProps) {
  return (
    <section className="flex animate-fade-up flex-col items-center gap-3 rounded-20 border border-tint/14 border-dashed bg-tint/3 px-5 py-6.5 text-center">
      {illustration}
      <h2 className="font-extrabold text-17">{title}</h2>
      <p className="max-w-md text-13 text-fg-muted">{children}</p>
      {action}
      {note && <p className="text-12 text-fg-faint">{note}</p>}
    </section>
  );
}

/** Three spines floating over a shelf, in the scheme's accent: the "nothing here yet" picture. */
export function ShelfIllustration() {
  return (
    <div aria-hidden="true" className="relative h-21 w-30">
      <span className="absolute bottom-2.5 left-3.5 h-15 w-6 animate-float rounded-6 bg-accent" />
      <span className="absolute bottom-2.5 left-11 h-12.5 w-6 animate-float rounded-6 bg-accent/60 [animation-delay:300ms]" />
      <span className="absolute bottom-2.5 left-18.5 h-16.5 w-6 rotate-10 animate-float rounded-6 bg-accent/35 [animation-delay:600ms]" />
      <span className="absolute inset-x-0 bottom-1 h-1.5 rounded-3 bg-line" />
    </div>
  );
}
