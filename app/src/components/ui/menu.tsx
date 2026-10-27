import { EllipsisVertical } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** A row's "More" menu: its ⋮ button, and what it can do, listed beside it. Radix's dropdown
 * menu, so the arrow keys move through it and Escape closes it. It opens above a card. */
export function RowMenu({ label, children }: { label: string; children: ReactNode }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        aria-label={label}
        className="press inline-flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-full text-fg-muted hover:bg-tint/8 hover:text-fg"
      >
        <EllipsisVertical size={16} aria-hidden="true" />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={4}
          className="z-60 flex min-w-44 flex-col rounded-16 border border-edge bg-dialog p-1.5 text-13 shadow-float"
        >
          {children}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

/** One thing a menu does; `danger` for one that sets something aside. */
export function MenuItem(props: { onSelect: () => void; danger?: boolean; children: ReactNode }) {
  return (
    <DropdownMenu.Item
      onSelect={props.onSelect}
      className={cn(
        "cursor-pointer rounded-10 px-3 py-2 font-bold outline-none data-highlighted:bg-tint/6",
        props.danger ? "text-danger" : "text-fg-soft data-highlighted:text-fg",
      )}
    >
      {props.children}
    </DropdownMenu.Item>
  );
}

/** A line between a menu's groups of things. */
export function MenuSeparator() {
  return <DropdownMenu.Separator className="mx-2 my-1 h-px bg-rule" />;
}
