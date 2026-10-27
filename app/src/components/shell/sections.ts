import { Clock, House, Layers, ListChecks, type LucideIcon, SlidersHorizontal } from "lucide-react";

export interface Section {
  path: string;
  label: string;
  icon: LucideIcon;
}

/** The five places in Maku, in nav rail order. */
export const sections: Section[] = [
  { path: "/", label: "Home", icon: House },
  { path: "/tidy", label: "Tidy up", icon: ListChecks },
  { path: "/convert", label: "Convert", icon: Layers },
  { path: "/history", label: "History", icon: Clock },
  { path: "/settings", label: "Settings", icon: SlidersHorizontal },
];

/**
 * The section a page sits in, whose tile stays lit while it's open: the scan, a collection
 * (`/franchises`, as the engine calls one) and a title are Home's, and a file to match is Tidy
 * up's, as its breadcrumb says, or Home's when it's a title's match being changed.
 */
export function sectionOf(pathname: string, search: string): string {
  const [, first = ""] = pathname.split("/");
  if (first === "match") return new URLSearchParams(search).has("title") ? "/" : "/tidy";
  return ["", "scan", "franchises", "titles"].includes(first) ? "/" : `/${first}`;
}
