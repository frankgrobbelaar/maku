import { Switch as Primitive } from "radix-ui";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

/**
 * An on/off switch, built on Radix's Switch so it works with the keyboard and screen readers.
 * Cinema: a 44 by 24 pill, amber when on.
 */
export function Switch({ className, ...props }: ComponentProps<typeof Primitive.Root>) {
  return (
    <Primitive.Root
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-12 bg-control transition-colors duration-200 ease-cinema data-[state=checked]:bg-accent disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      <Primitive.Thumb className="absolute top-1 left-1 size-4 rounded-full bg-white transition-transform duration-200 ease-cinema data-[state=checked]:translate-x-5 data-[state=checked]:bg-on-accent" />
    </Primitive.Root>
  );
}
