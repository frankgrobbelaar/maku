import { ToggleGroup } from "radix-ui";
import { cn } from "@/lib/utils";

interface SegmentedProps<T extends string> {
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
  className?: string;
}

/**
 * One choice from a few, shown side by side (Clean names, Keep my names). Built on Radix's
 * ToggleGroup, so arrow keys move between the choices.
 */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  className,
}: SegmentedProps<T>) {
  return (
    <ToggleGroup.Root
      type="single"
      aria-label={label}
      value={value}
      onValueChange={(next) => {
        if (next) onChange(next as T); // clicking the chosen one again keeps it chosen
      }}
      className={cn("inline-flex gap-1 rounded-22 bg-well p-1", className)}
    >
      {options.map((option) => (
        <ToggleGroup.Item
          key={option.value}
          value={option.value}
          className="press min-h-9 cursor-pointer rounded-18 px-4 font-bold text-fg-soft data-[state=on]:bg-accent data-[state=on]:font-extrabold data-[state=on]:text-on-accent"
        >
          {option.label}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}
