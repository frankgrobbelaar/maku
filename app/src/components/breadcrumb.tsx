import { Fragment } from "react";
import { Link } from "react-router";

/** Where a page sits: "Library › The Starfall Collection › Starfall II", every step but the last
 * a link. */
export function Breadcrumb({
  trail,
  current,
}: {
  trail: { label: string; to: string }[];
  current: string;
}) {
  return (
    <nav
      aria-label="Breadcrumb"
      className="page-top flex animate-fade-up items-center gap-2 text-13"
    >
      {trail.map((step) => (
        <Fragment key={step.to}>
          <Link
            to={step.to}
            className="text-fg-muted underline-offset-3 hover:text-fg hover:underline"
          >
            {step.label}
          </Link>
          <span aria-hidden="true" className="text-fg-faint">
            ›
          </span>
        </Fragment>
      ))}
      <span aria-current="page" className="truncate font-bold">
        {current}
      </span>
    </nav>
  );
}

export const LIBRARY = { label: "Library", to: "/" };
