import { RadioGroup } from "radix-ui";
import { useId } from "react";
import { Segmented } from "@/components/ui/segmented";
import { Switch } from "@/components/ui/switch";
import type { Settings } from "@/lib/engine";

/** The two standards: the most a picture comes to. Nothing is made bigger than it is. */
export const STANDARDS = [
  {
    value: "4k",
    name: "4K",
    recommended: true,
    spec: "Up to 4K · HEVC 10-bit · MKV",
    text: "4K stays 4K, with its HDR. Nothing is made bigger than it is.",
    size: "≈ 9 GB an hour of 4K, 3 GB of 1080p",
  },
  {
    value: "1080p",
    name: "1080p",
    recommended: false,
    spec: "Up to 1080p · HEVC 10-bit · MKV",
    text: "4K comes down to 1080p to save room, its HDR kept. Nothing is made bigger.",
    size: "≈ 3 GB an hour",
  },
] as const;

// Clean names are the layout media servers read ("plex" in the settings, as before; "jellyfin"
// names files the same way).
export const NAMING = [
  { value: "plex", label: "Clean names" },
  { value: "keep", label: "Keep my names" },
] as const;

// Made-up titles, as in every picture of Maku that goes public.
const EXAMPLES = [
  {
    from: "starfall_academy_01.mkv",
    folder: "TV\\Starfall Academy (1989)\\Season 01\\",
    name: "Starfall Academy (1989) - S01E01 - The First Bell.mkv",
  },
  {
    from: "Last Light.avi",
    folder: "Movies\\Starfall Academy - Last Light (2018)\\",
    name: "Starfall Academy - Last Light (2018).avi",
  },
];

/**
 * The library standard and how files are named: chosen in setup, and changed later in Settings.
 * `onChange` hears each change as it's made.
 */
export function StandardChoices({
  settings,
  onChange: change,
}: {
  settings: Settings;
  onChange: (part: Partial<Settings>) => void;
}) {
  return (
    <>
      <RadioGroup.Root
        aria-label="Standard"
        value={settings.standard}
        onValueChange={(value) => change({ standard: value as Settings["standard"] })}
        className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-3"
      >
        {STANDARDS.map((standard) => (
          <RadioGroup.Item
            key={standard.value}
            value={standard.value}
            className="press group flex cursor-pointer flex-col gap-2.5 rounded-18 border-2 border-edge bg-glass p-4.5 text-left data-[state=checked]:border-accent data-[state=checked]:bg-accent/10"
          >
            <span className="flex w-full items-center justify-between gap-2">
              <span className="font-extrabold text-17">{standard.name}</span>
              <RadioRing />
            </span>
            {standard.recommended && (
              <span className="inline-flex h-5.5 w-fit items-center rounded-full bg-accent px-2 font-extrabold text-11 text-on-accent">
                Recommended
              </span>
            )}
            <span className="text-13 text-fg-soft">{standard.spec}</span>
            <span className="text-13 text-fg-muted">{standard.text}</span>
            <span className="font-mono text-12 text-fg-muted group-data-[state=checked]:text-accent-fg">
              {standard.size}
            </span>
          </RadioGroup.Item>
        ))}
        <div
          aria-disabled="true"
          className="flex flex-col gap-2.5 rounded-18 border-2 border-edge border-dashed p-4.5 text-fg-muted"
        >
          <span className="font-extrabold text-17 text-fg-soft">Custom</span>
          <span className="text-13">Pick every detail yourself</span>
          <span className="text-13">
            Resolution, codec and quality, which audio languages to keep, subtitle handling.
          </span>
          <span className="font-mono text-12">Not ready yet</span>
        </div>
      </RadioGroup.Root>
      <p className="text-13 text-fg-muted">
        Every sound track is kept as it is, lossless ones too; only DVD's and Blu-ray's PCM become
        FLAC, still lossless. Subtitles, fonts and chapters stay.
      </p>

      <div className="flex flex-col gap-2.5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="font-extrabold text-15">File names</span>
          <Segmented
            label="File names"
            value={settings.naming === "keep" ? "keep" : "plex"}
            options={NAMING}
            onChange={(naming) => change({ naming })}
          />
        </div>
        <NamePreview keep={settings.naming === "keep"} />
      </div>
    </>
  );
}

function NamePreview({ keep }: { keep: boolean }) {
  return (
    <div className="flex flex-col gap-3 overflow-x-auto rounded-16 bg-inset px-4 py-3.5 font-mono text-12">
      {EXAMPLES.map((example) => (
        <div key={example.from} className="flex flex-col gap-1 whitespace-nowrap">
          <span className="text-fg-faint">{example.from}</span>
          <span className="text-fg">
            → {example.folder}
            {keep ? example.from : example.name}
          </span>
        </div>
      ))}
      {keep && (
        <span className="font-sans text-12 text-fg-muted">
          Files keep their names, and still go into a folder per show, season and movie.
        </span>
      )}
    </div>
  );
}

export function Toggle(props: {
  label: string;
  text: string;
  checked: boolean;
  onChange: (on: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="flex items-center gap-3.5 rounded-16 border border-edge bg-glass px-4 py-3.5">
      <Switch
        id={id}
        checked={props.checked}
        onCheckedChange={props.onChange}
        aria-describedby={`${id}-text`}
      />
      <span className="flex flex-col gap-0.5">
        <label htmlFor={id} className="cursor-pointer font-extrabold">
          {props.label}
        </label>
        <span id={`${id}-text`} className="text-13 text-fg-muted">
          {props.text}
        </span>
      </span>
    </div>
  );
}

function RadioRing() {
  return (
    <span
      aria-hidden="true"
      className="inline-flex size-5.5 items-center justify-center rounded-full border-2 border-control group-data-[state=checked]:border-accent"
    >
      <span className="size-2.5 rounded-full bg-accent opacity-0 group-data-[state=checked]:opacity-100" />
    </span>
  );
}
