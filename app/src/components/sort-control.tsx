import { Segmented } from "@/components/ui/segmented";
import type { TitleSort } from "@/lib/engine";

const SORTS = [
  { value: "released", label: "Release date" },
  { value: "name", label: "Name" },
  { value: "added", label: "Recently added" },
  { value: "missing", label: "Most missing" },
] as const;

/** How a list of series and films is ordered. Release date, oldest first, is the default on every
 * page that lists them (the owner's choice). */
export function SortControl(props: { value: TitleSort; onChange: (sort: TitleSort) => void }) {
  return (
    <Segmented label="Sort by" value={props.value} options={SORTS} onChange={props.onChange} />
  );
}

/** The order in words, under a list's heading: "oldest release first". */
export function sortWords(sort: TitleSort): string {
  switch (sort) {
    case "released":
      return "oldest release first";
    case "name":
      return "by name";
    case "added":
      return "newest added first";
    case "missing":
      return "most missing first";
  }
}
