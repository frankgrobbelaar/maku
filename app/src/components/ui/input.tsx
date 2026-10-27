import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

// Adapted from shadcn/ui's input (MIT, see LICENSE-shadcn.txt), restyled to Cinema: a pill like
// the buttons beside it, glass inside, amber focus ring.
export function Input({ className, type = "text", ...props }: ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-11 w-full min-w-0 rounded-full border border-field-edge bg-field px-4.5 text-14 text-fg transition-[border-color] duration-200 ease-cinema placeholder:text-fg-faint hover:border-tint/20 disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
