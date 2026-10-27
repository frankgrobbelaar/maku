import type { ReactNode } from "react";
import tmdbLogo from "@/assets/tmdb-logo.svg";

/**
 * TMDB's credit, as its terms ask: its logo, unchanged and smaller than Maku's own, beside the
 * line saying TMDB doesn't endorse Maku (see app/src/assets/README.md).
 */
export function TmdbCredit({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-center gap-3 text-12 text-fg-faint">
      <img src={tmdbLogo} alt="TMDB" className="h-3 w-auto shrink-0" />
      <span>{children}</span>
    </p>
  );
}
