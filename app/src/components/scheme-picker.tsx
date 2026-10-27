import { ToggleGroup } from "radix-ui";
import { SCHEMES, type Scheme } from "@/lib/look";
import { cn } from "@/lib/utils";

interface SchemePickerProps {
  value: Scheme;
  onChange: (scheme: Scheme) => void;
}

/**
 * Maku's four colour schemes, each a card with its swatch: its window in dark and in light, its
 * accent and its ready mark on each. Built on Radix's ToggleGroup, so arrow keys move between
 * them, as the Light or dark choice beside it does.
 */
export function SchemePicker({ value, onChange }: SchemePickerProps) {
  return (
    <ToggleGroup.Root
      type="single"
      aria-label="Colours"
      value={value}
      onValueChange={(next) => {
        if (next) onChange(next as Scheme); // choosing the chosen one again keeps it
      }}
      className="grid grid-cols-2 gap-2.5 standard:grid-cols-4"
    >
      {SCHEMES.map((each) => (
        <ToggleGroup.Item
          key={each.value}
          value={each.value}
          className={cn(
            "press group flex cursor-pointer flex-col gap-2 rounded-16 border border-edge bg-field p-2.5 text-left transition-colors duration-200",
            "data-[state=on]:border-accent data-[state=on]:bg-tint/6",
          )}
        >
          <span className="flex h-14 overflow-hidden rounded-10" aria-hidden="true">
            {[each.dark, each.light].map((half) => (
              <span
                key={half.window}
                className="flex flex-1 items-end gap-1.5 p-2"
                style={{ background: half.window }}
              >
                <span className="h-2 w-6 rounded-full" style={{ background: half.accent }} />
                <span className="size-2 rounded-2" style={{ background: half.ready }} />
              </span>
            ))}
          </span>
          <span className="flex flex-col gap-0.5 px-0.5">
            <span className="font-extrabold group-data-[state=on]:text-accent-fg">
              {each.label}
            </span>
            <span className="text-12 text-fg-muted">{each.text}</span>
          </span>
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}
