import { NavLink } from "react-router";
import { cn } from "@/lib/utils";

/** The Convert section's two screens: choosing what to convert, and the queue converting it. */
export function ConvertTabs({ queued }: { queued: number | null }) {
  return (
    <nav aria-label="Convert sections" className="inline-flex gap-1 rounded-24 bg-well p-1">
      <Tab to="/convert">Choose</Tab>
      <Tab to="/convert/queue">
        Queue
        {queued !== null && queued > 0 && (
          <span className="font-mono text-11 opacity-75">{queued}</span>
        )}
      </Tab>
    </nav>
  );
}

function Tab({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        cn(
          "press inline-flex min-h-10 items-center gap-2 rounded-20 px-4.5 font-bold",
          isActive ? "bg-accent font-extrabold text-on-accent" : "text-fg-soft",
        )
      }
    >
      {children}
    </NavLink>
  );
}

/** One numbered step of a screen: "1 What", with a note on the right. */
export function Step(props: {
  n: number;
  id: string;
  title: string;
  note?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      aria-labelledby={props.id}
      className={cn(
        "flex min-w-0 animate-fade-up flex-col gap-3 rounded-24 border border-edge bg-glass p-5.5 shadow-panel",
        props.className,
      )}
    >
      <div className="flex flex-wrap items-center gap-2.5">
        <span
          aria-hidden="true"
          className="inline-flex size-6.5 items-center justify-center rounded-full bg-accent font-extrabold text-13 text-on-accent"
        >
          {props.n}
        </span>
        <h2 id={props.id} className="font-extrabold text-18">
          {props.title}
        </h2>
        {props.note && <span className="ml-auto text-12 text-fg-muted">{props.note}</span>}
      </div>
      {props.children}
    </section>
  );
}
