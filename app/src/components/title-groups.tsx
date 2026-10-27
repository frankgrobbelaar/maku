import { type ReactNode, useId } from "react";
import { sortWords } from "@/components/sort-control";
import { shelfKind } from "@/components/title-card";
import type { FranchiseSummary, TitleKind, TitleSort } from "@/lib/engine";
import { KIND_ORDER, kindHeading } from "@/lib/kinds";

/** One type's share of a list, in the list's order. */
export interface Group<T> {
  key: string;
  heading: string;
  items: T[];
}

/** Whether a list in this order is grouped by type. "Recently added" and "Most missing" look
 * across every type, so they list everything together. */
export function groupsByType(sort: TitleSort): boolean {
  return sort === "released" || sort === "name";
}

/** The order in words, under a list's heading: "by type, oldest release first"; for a list of
 * one type (a collection's films), where no grouping shows, "oldest release first". */
export function orderWords(sort: TitleSort, oneType = false): string {
  if (!groupsByType(sort) || oneType) return sortWords(sort);
  return sort === "name" ? "by type, then name" : `by type, ${sortWords(sort)}`;
}

/** A whole list as one group, for the orders that look across every type. */
export function together<T>(items: T[]): Group<T>[] {
  return [{ key: "all", heading: "", items }];
}

/** Titles by type: series, then movies, each in the order the titles came. */
export function byKind<T extends { kind: TitleKind }>(titles: T[]): Group<T>[] {
  return KIND_ORDER.map((kind) => ({
    key: kind,
    heading: kindHeading(kind),
    items: titles.filter((title) => title.kind === kind),
  })).filter((group) => group.items.length > 0);
}

/** The shelf by type, as its cards show each: collections of films first, then series and films
 * on their own. */
export function shelfByKind(franchises: FranchiseSummary[]): Group<FranchiseSummary>[] {
  return (["franchise", ...KIND_ORDER] as const)
    .map((kind) => ({
      key: kind,
      heading: kind === "franchise" ? "Collections" : kindHeading(kind),
      items: franchises.filter((franchise) => shelfKind(franchise) === kind),
    }))
    .filter((group) => group.items.length > 0);
}

/** Poster cards in a grid; in groups, each under its type's heading, unless there's only one. */
export function CardGrid<T>(props: {
  groups: Group<T>[];
  keyOf: (item: T) => string | number;
  card: (item: T) => ReactNode;
}) {
  const [only, ...more] = props.groups;
  if (only && more.length === 0) {
    return <Cards items={only.items} keyOf={props.keyOf} card={props.card} />;
  }
  return (
    <div className="flex flex-col gap-7">
      {props.groups.map((group) => (
        <Section key={group.key} group={group} keyOf={props.keyOf} card={props.card} />
      ))}
    </div>
  );
}

function Section<T>(props: {
  group: Group<T>;
  keyOf: (item: T) => string | number;
  card: (item: T) => ReactNode;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h3 id={id} className="flex items-baseline gap-2 font-extrabold text-16">
        {props.group.heading}{" "}
        <span className="font-medium font-mono text-12 text-fg-muted">
          {props.group.items.length}
        </span>
      </h3>
      <Cards items={props.group.items} keyOf={props.keyOf} card={props.card} />
    </section>
  );
}

function Cards<T>(props: {
  items: T[];
  keyOf: (item: T) => string | number;
  card: (item: T) => ReactNode;
}) {
  return (
    <ul className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-x-4.5 gap-y-5">
      {props.items.map((item) => (
        <li key={props.keyOf(item)}>{props.card(item)}</li>
      ))}
    </ul>
  );
}
