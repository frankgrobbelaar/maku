import {
  Clock,
  House,
  Layers,
  LibraryBig,
  ListChecks,
  type LucideIcon,
  SlidersHorizontal,
} from "lucide-react";

export interface Section {
  path: string;
  label: string;
  icon: LucideIcon;
}

/** The six places in Maku, in nav rail order. */
export const sections: Section[] = [
  { path: "/", label: "Home", icon: House },
  { path: "/library", label: "Library", icon: LibraryBig },
  { path: "/tidy", label: "Tidy up", icon: ListChecks },
  { path: "/convert", label: "Convert", icon: Layers },
  { path: "/history", label: "History", icon: Clock },
  { path: "/settings", label: "Settings", icon: SlidersHorizontal },
];

/**
 * The section a page sits in, whose tile stays lit while it's open, as its breadcrumb says: a
 * title, a collection (`/franchises`, as the engine calls one) and what's asked of one of them (its
 * match changed, its subtitles made) are the Library's; the scan, and subtitles for the whole
 * library, Home's, where they're started from; and a file to match is Tidy up's.
 */
export function sectionOf(pathname: string, search: string): string {
  const [, first = ""] = pathname.split("/");
  const forTitle = new URLSearchParams(search).has("title");
  if (first === "match") return forTitle ? "/library" : "/tidy";
  if (first === "subtitles") return forTitle ? "/library" : "/";
  if (["library", "franchises", "titles"].includes(first)) return "/library";
  return ["", "scan"].includes(first) ? "/" : `/${first}`;
}
