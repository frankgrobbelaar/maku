import { Search, X } from "lucide-react";
import { type ReactNode, useRef } from "react";
import { useSearchParams } from "react-router";
import { cn } from "@/lib/utils";

/** A page's search, kept in its address (`?q=`), so going back to the page finds it as it was
 * left. Typing replaces the address rather than adding to the way back. */
export function useAddressSearch(): [string, (query: string) => void] {
  const [address, setAddress] = useSearchParams();
  const setQuery = (query: string) =>
    setAddress(
      (before) => {
        const after = new URLSearchParams(before);
        if (query) after.set("q", query);
        else after.delete("q");
        return after;
      },
      { replace: true },
    );
  return [address.get("q") ?? "", setQuery];
}

/** A search over a list on the page: the list narrows as you type. Escape, or the cross, clears
 * it. Drawn as the field on "Which title is this?": a pill, glass inside. */
export function SearchField(props: {
  value: string;
  onChange: (value: string) => void;
  /** What it searches, for screen readers: "Search the shelf". */
  label: string;
  placeholder: string;
  className?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <label
      className={cn(
        "flex h-11 min-w-0 cursor-text items-center gap-2.5 rounded-full border border-field-edge bg-field pr-1.5 pl-4 text-fg-muted transition-[border-color] duration-200 ease-cinema focus-within:outline-2 focus-within:outline-accent-fg focus-within:outline-offset-3 hover:border-tint/20",
        props.className,
      )}
    >
      <Search size={16} aria-hidden="true" className="shrink-0" />
      <input
        ref={input}
        type="search"
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== "Escape" || !props.value) return;
          event.preventDefault();
          event.stopPropagation(); // clears the search, and closes nothing else
          props.onChange("");
        }}
        placeholder={props.placeholder}
        aria-label={props.label}
        autoComplete="off"
        spellCheck={false}
        className="h-full min-w-0 flex-1 bg-transparent text-13 text-fg outline-none placeholder:text-fg-faint [&::-webkit-search-cancel-button]:appearance-none"
      />
      {props.value ? (
        <button
          type="button"
          aria-label="Clear the search"
          onClick={() => {
            props.onChange("");
            input.current?.focus();
          }}
          className="press inline-flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-full hover:bg-tint/8 hover:text-fg"
        >
          <X size={14} aria-hidden="true" />
        </button>
      ) : (
        <span aria-hidden="true" className="size-8 shrink-0" />
      )}
    </label>
  );
}

/** What a list says when nothing in it is what was searched for; the field's cross brings back
 * all of it. */
export function NoMatches({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="rounded-16 bg-tint/4 px-4 py-3.5 text-13 text-fg-muted">
      {children}
    </p>
  );
}
