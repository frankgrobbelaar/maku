import { Check, Cpu, Gpu } from "lucide-react";
import { Button } from "@/components/ui/button";
import { gpuTime } from "@/lib/convert";
import {
  type Ability,
  type Card,
  type PcAbility,
  type PcStep,
  type System,
  useTestPc,
} from "@/lib/engine";
import { cn } from "@/lib/utils";

/**
 * What this PC can do for Maku, and how long it takes here, as Setup's last step and About in
 * Settings show it; and the small things Convert says when it can't.
 */

const GIB = 1024 ** 3;

/** Each part of Maku, as the check lists them. */
const PARTS: Record<PcAbility, string> = {
  convert: "Convert to your standard",
  subtitles: "English subtitles",
  player: "Play inside Maku",
};

const CHIPS: Partial<Record<Ability["state"], string>> = {
  limited: "Fast only",
};

const STEPS: { step: PcStep; name: string }[] = [
  { step: "encoder", name: "The encoder" },
  { step: "subtitles", name: "The graphics card, for English subtitles" },
];

/** Each maker's encoder as ffmpeg names it, for what it said. */
const FFMPEG_NAMES: Record<Card["maker"], string | null> = {
  nvidia: "hevc_nvenc",
  amd: "hevc_amf",
  intel: "hevc_qsv",
  other: null,
};

const MAKERS: Record<Card["maker"], string> = {
  nvidia: "NVIDIA",
  amd: "AMD",
  intel: "Intel",
  other: "Its maker",
};

/** The card Maku found, as one line: "NVIDIA GeForce GTX 1660 SUPER · 6 GB". */
export function cardLine(card: Card | null, driver = false): string {
  if (!card) return "No graphics card found";
  const memory =
    card.integrated || card.memory === null ? "shares the PC's memory" : gigabytes(card.memory);
  const version = driver && card.driver ? ` · driver ${card.driver}` : "";
  return `${card.name} · ${memory}${version}`;
}

/** "6 GB", from bytes: the memory of a card or a PC. */
export function gigabytes(bytes: number): string {
  const amount = bytes / GIB;
  return `${amount >= 1 ? Math.round(amount) : amount.toFixed(1)} GB`;
}

/** One part of Maku on this PC, once it's checked. */
export function abilityOf(system: System | undefined, part: PcAbility): Ability | undefined {
  return system?.abilities.find((each) => each.part === part);
}

/** How long Fast takes for an hour of sound's subtitles here, in seconds, once this PC is
 * checked. */
export function fastSubtitles(system: System | undefined): number | null {
  return abilityOf(system, "subtitles")?.seconds.at(-1) ?? null;
}

/**
 * Setup's look at this PC: what it has, what Maku can do on it and how long each takes, the
 * check as it runs, and "Test this PC again".
 */
export function ThisPc({ system, waiting }: { system: System; waiting: boolean }) {
  const test = useTestPc();
  const facts = [
    system.processor,
    system.cores && `${system.cores} cores`,
    system.memory && gigabytes(system.memory),
  ].filter(Boolean);
  return (
    <section aria-labelledby="pc-title" className="flex flex-col gap-3.5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <span className="flex flex-col gap-1">
          <h3 id="pc-title" className="font-extrabold text-17">
            What this PC can do
          </h3>
          <span className="flex flex-wrap gap-2">
            <Fact icon={<Gpu size={14} aria-hidden="true" />}>{cardLine(system.card)}</Fact>
            {facts.length > 0 && (
              <Fact icon={<Cpu size={14} aria-hidden="true" />}>{facts.join(" · ")}</Fact>
            )}
          </span>
        </span>
        {system.checkedAt && !system.testing && (
          <Button
            size="sm"
            disabled={test.isPending}
            onClick={() => test.mutate({ path: "/system/test" })}
          >
            Test this PC again
          </Button>
        )}
      </div>
      {system.testing ? (
        <TestingPc testing={system.testing} />
      ) : system.checkedAt ? (
        <>
          <Abilities abilities={system.abilities} />
          <p className="text-12 text-fg-faint">{measuredNote(system, "setup")}</p>
        </>
      ) : (
        <p className="rounded-16 border border-tint/12 border-dashed px-4 py-3.5 text-13 text-fg-muted">
          {waiting
            ? "Maku tests what this PC can do once ffmpeg is ready: about a minute."
            : "Testing this PC…"}
        </p>
      )}
      {test.isError && (
        <p role="alert" className="text-13 text-broken-fg">
          Maku couldn't test this PC: {test.error.message}
        </p>
      )}
    </section>
  );
}

/** Settings › About's panel: this PC as Maku found it, what it can do and how long it takes. */
export function ThisPcPanel({ system }: { system: System }) {
  const test = useTestPc();
  const processor = [system.processor, system.cores && `${system.cores} cores`].filter(Boolean);
  const id = "this-pc-title";
  return (
    <section
      aria-labelledby={id}
      className="flex animate-fade-up flex-col gap-3.5 rounded-24 border border-edge bg-glass p-5.5 shadow-panel"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 id={id} className="font-extrabold text-18">
            This PC
          </h2>
          <span className="text-13 text-fg-muted">
            What Maku can do here, and how long it takes
          </span>
        </div>
        {!system.testing && (
          <Button
            size="sm"
            disabled={test.isPending}
            onClick={() => test.mutate({ path: "/system/test" })}
          >
            {system.checkedAt ? "Test again" : "Test this PC"}
          </Button>
        )}
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-13">
        <dt className="text-fg-muted">Graphics card</dt>
        <dd className="font-mono text-12 [overflow-wrap:anywhere]">
          {cardLine(system.card, true)}
        </dd>
        <dt className="text-fg-muted">Processor</dt>
        <dd className="font-mono text-12">{processor.join(" · ") || "–"}</dd>
        <dt className="text-fg-muted">Memory</dt>
        <dd className="font-mono text-12">{system.memory ? gigabytes(system.memory) : "–"}</dd>
      </dl>
      {system.testing ? (
        <TestingPc testing={system.testing} />
      ) : system.checkedAt ? (
        <Abilities abilities={system.abilities} compact />
      ) : (
        <p className="text-13 text-fg-muted">
          Maku hasn't tested this PC yet. Testing takes about a minute, and nothing in your library
          is touched.
        </p>
      )}
      {!system.testing && system.checkedAt && (
        <p className="text-12 text-fg-faint">{measuredNote(system, "about")}</p>
      )}
      {test.isError && (
        <p role="alert" className="text-13 text-broken-fg">
          Maku couldn't test this PC: {test.error.message}
        </p>
      )}
    </section>
  );
}

function Fact({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <span className="inline-flex min-h-7 items-center gap-2 rounded-14 bg-tint/5 px-3 font-bold text-12 text-fg-soft">
      {icon}
      {children}
    </span>
  );
}

/** Each part of Maku here: its shape, its name, what does it, and an hour's time. */
function Abilities({ abilities, compact }: { abilities: Ability[]; compact?: boolean }) {
  return (
    <ul className="flex flex-col overflow-hidden rounded-18 border border-edge">
      {abilities.map((ability) => (
        <li
          key={ability.part}
          className={cn(
            "grid grid-cols-[18px_minmax(0,1.1fr)_minmax(0,1.6fr)_minmax(0,1fr)] gap-3.5 border-rule border-b px-4 py-3.5 last:border-b-0",
            ability.note ? "items-start" : "items-center",
            compact && "py-3 text-13",
          )}
        >
          <AbilityShape state={ability.state} className={ability.note ? "mt-1" : undefined} />
          <span className="flex flex-col items-start gap-1">
            <span className="font-extrabold">{PARTS[ability.part]}</span>
            {CHIPS[ability.state] && (
              <span className="shrink-0 whitespace-nowrap rounded-10 bg-accent/14 px-2 font-extrabold text-11 text-accent-fg">
                {CHIPS[ability.state]}
              </span>
            )}
          </span>
          <span className="text-13 text-fg-muted">
            {compact ? ability.how.replace(/^HEVC 10-bit on /, "") : ability.how}
            {ability.note && `. ${ability.note}`}
          </span>
          <AbilityTime ability={ability} />
        </li>
      ))}
    </ul>
  );
}

function AbilityShape({ state, className }: { state: Ability["state"]; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "size-3 rounded-3",
        state === "ready" && "status-ready",
        state === "limited" && "shadow-[inset_0_0_0_2px_var(--color-accent)]",
        state === "no" && "status-missing",
        className,
      )}
    />
  );
}

function AbilityTime({ ability }: { ability: Ability }) {
  if (ability.part === "player") {
    return <span className="text-right font-bold text-13 text-accent-fg">Ready</span>;
  }
  const [first, second] = ability.seconds;
  if (first === undefined) return <span />;
  const time =
    ability.part === "convert" && second !== undefined
      ? `1080p ≈ ${gpuTime(first)} · 4K ≈ ${gpuTime(second)}`
      : second === undefined
        ? `≈ ${gpuTime(first)} an hour`
        : `≈ ${gpuTime(first)} · ${gpuTime(second)}`;
  return <span className="text-right font-mono text-12 text-fg-soft">{time}</span>;
}

/** What the times are: measured just now, since a day, or a guess till this PC is measured. */
function measuredNote(system: System, where: "setup" | "about"): string {
  const measured = system.measured;
  const again = "Test again after changing the graphics card or its driver.";
  if (!measured) {
    return "These times are a guess, from a GTX 1660 Super, until Maku has measured this PC.";
  }
  if (where === "setup" && measured.tested && measured.conversions + measured.subtitles === 0) {
    return "Times measured on this PC just now, for an hour of video. Maku keeps measuring as it works, so they stay true.";
  }
  const day = new Date(measured.at).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
  });
  const jobs = [
    measured.conversions > 0 && count(measured.conversions, "conversion"),
    measured.subtitles > 0 && `${count(measured.subtitles, "video")}' subtitles`,
  ].filter(Boolean);
  const since = jobs.length > 0 ? jobs.join(" and ") : null;
  if (measured.tested) {
    return since
      ? `Measured on ${day}, and since then by ${since}. ${again}`
      : `Measured on ${day}. ${again}`;
  }
  return `Measured by ${since ?? "Maku's work"} since ${day}. ${again}`;
}

function count(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/** A check of this PC under way: each part, the one it's on, and what's done. */
export function TestingPc({ testing }: { testing: NonNullable<System["testing"]> }) {
  return (
    <div
      role="status"
      aria-label="Testing this PC"
      className="flex flex-col gap-3 rounded-20 border border-edge bg-glass p-4.5"
    >
      <span className="font-extrabold">
        {testing.timing ? "Testing this PC · about a minute" : "Checking this PC"}
      </span>
      <ol className="flex flex-col gap-2 text-13">
        {STEPS.map(({ step, name }) => {
          const done = testing.done.includes(step);
          const now = testing.step === step && !done;
          return (
            <li
              key={step}
              aria-current={now ? "step" : undefined}
              className={cn(
                "flex items-center gap-2.5",
                now && "font-bold text-accent-fg",
                !done && !now && "text-fg-muted",
              )}
            >
              {done ? (
                <span
                  aria-hidden="true"
                  className="inline-flex size-4.5 items-center justify-center rounded-full bg-accent text-on-accent"
                >
                  <Check size={11} strokeWidth={3.5} />
                </span>
              ) : (
                <span
                  aria-hidden="true"
                  className={cn(
                    "size-4.5 rounded-full",
                    now
                      ? "animate-pulse shadow-[inset_0_0_0_2px_var(--color-accent)]"
                      : "shadow-[inset_0_0_0_2px_var(--color-control)]",
                  )}
                />
              )}
              {name}
              {step === "encoder" && done && testing.fps
                ? ` · ${Math.round(testing.fps)} frames a second of 1080p`
                : ""}
            </li>
          );
        })}
      </ol>
      <span className="text-12 text-fg-muted">
        Converting waits till it's done. Nothing in your library is touched.
      </span>
    </div>
  );
}

/**
 * Convert, on a PC that can't: its card's own encoder didn't start (a driver too old, its
 * maker's link to a newer one), or it has none for HEVC 10-bit. Everything else still works.
 */
export function NoEncoder({ system }: { system: System }) {
  const test = useTestPc();
  const card = system.card;
  const again = (label: string) => (
    <Button
      size="sm"
      disabled={test.isPending}
      onClick={() => test.mutate({ path: "/system/test" })}
    >
      {label}
    </Button>
  );
  if (system.driverLink && card) {
    const maker = MAKERS[card.maker];
    const said = FFMPEG_NAMES[card.maker];
    return (
      <div
        role="alert"
        className="flex animate-fade-up flex-col gap-3 rounded-20 border border-edge bg-glass p-4.5"
      >
        <span className="font-extrabold">{maker}'s encoder didn't start</span>
        <span className="text-13 text-fg-soft">
          The card is there, so its driver may be too old for the encoder Maku's ffmpeg asks for.
          Update the driver from {maker}'s site, then test this PC again.
        </span>
        {system.encoderProblem && (
          <span className="font-mono text-12 text-fg-muted [overflow-wrap:anywhere]">
            {said ? `${said}: ` : ""}
            {system.encoderProblem.replace(/\.$/, "")}
          </span>
        )}
        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="primary">
            <a href={system.driverLink} target="_blank" rel="noreferrer">
              {maker}'s drivers
            </a>
          </Button>
          {again("Test again")}
        </div>
        <TestProblem error={test.error} />
      </div>
    );
  }
  return (
    <div
      role="status"
      className="flex animate-fade-up flex-col gap-3 rounded-20 border border-edge bg-glass p-4.5"
    >
      <span className="flex items-center gap-2.5">
        <AbilityShape state="no" />
        <span className="font-extrabold">This PC can't convert to your standard</span>
      </span>
      <span className="text-13 text-fg-soft">
        {card
          ? `Its graphics card, ${article(card.name)} ${card.name}, has no encoder for HEVC 10-bit.`
          : "Maku found no graphics card with an encoder for HEVC 10-bit."}{" "}
        Everything else in Maku works here: finding and naming every episode and film, tidying up,
        the gap analysis, English subtitles and the player.
      </span>
      <span className="text-12 text-fg-muted">
        Converting wants an NVIDIA GeForce GTX 10-series card or newer, an AMD Radeon RX 5000 or
        newer, or an Intel Core from the 7th generation on.
      </span>
      <div className="flex flex-wrap gap-2">{again("Test this PC again")}</div>
      <TestProblem error={test.error} />
    </div>
  );
}

/** "an" before a card whose name says its first letter as a vowel: an AMD, an NVIDIA, an Intel. */
function article(name: string): string {
  return /^(amd|nvidia|intel|[aeio])/i.test(name) ? "an" : "a";
}

/** Convert's times before this PC is measured: a guess, with the test a click away. */
export function GuessNote({ system }: { system: System }) {
  const test = useTestPc();
  if (system.testing) return <TestingPc testing={system.testing} />;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-16 bg-tint/4 px-4 py-3">
        <span className="flex-[1_1_260px] text-13 text-fg-soft">
          These times are a guess, from a GTX 1660 Super, until Maku has measured this PC.
        </span>
        <Button
          size="sm"
          disabled={test.isPending}
          onClick={() => test.mutate({ path: "/system/test" })}
        >
          Test this PC
        </Button>
      </div>
      <TestProblem error={test.error} />
    </div>
  );
}

function TestProblem({ error }: { error: Error | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="text-13 text-broken-fg">
      Maku couldn't test this PC: {error.message}
    </p>
  );
}
