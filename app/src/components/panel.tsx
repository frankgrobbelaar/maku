import type { ReactNode, RefObject } from "react";

/** A glass panel with its heading, and a note beside the heading. */
export function Panel(props: {
  id: string;
  title: string;
  note?: string;
  icon?: ReactNode;
  /** To scroll to it: it stops clear of the page's top, which stays put. */
  at?: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  return (
    <section
      ref={props.at}
      aria-labelledby={props.id}
      className="flex scroll-mt-14 animate-fade-up flex-col gap-3.5 rounded-22 border border-edge bg-glass p-5 shadow-panel"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id={props.id} className="inline-flex items-center gap-2 font-extrabold text-16">
          {props.icon && (
            <span aria-hidden="true" className="text-accent-fg">
              {props.icon}
            </span>
          )}
          {props.title}
        </h2>
        {props.note && <span className="text-12 text-fg-muted">{props.note}</span>}
      </div>
      {props.children}
    </section>
  );
}
