import { useState } from "react";
import { NAMING, STANDARDS, StandardChoices } from "@/components/standard-choices";
import { Button } from "@/components/ui/button";
import { type Settings, useSaveSettings, useSettings } from "@/lib/engine";
import { Footer, Panel } from "./parts";

export function StandardStep({
  onBack,
  onContinue,
}: {
  onBack: () => void;
  onContinue: () => void;
}) {
  const stored = useSettings();
  const save = useSaveSettings();
  const [draft, setDraft] = useState<Settings | null>(null);
  const settings = draft ?? stored.data;

  if (!settings) return <Panel title="Choose your standard" labelledBy="standard-title" />;
  // From the latest draft, so two quick changes in a row both count.
  const change = (part: Partial<Settings>) =>
    setDraft((latest) => ({ ...(latest ?? settings), ...part }));

  return (
    <Panel
      title="Choose your standard"
      labelledBy="standard-title"
      intro="Every file in the library is brought to this: HEVC 10-bit in an MKV, no bigger than the size you choose. Nothing is made bigger than it is, and files that already match are only renamed."
    >
      <StandardChoices settings={settings} onChange={change} />

      {save.isError && (
        <p role="alert" className="text-13 text-broken-fg">
          Maku couldn't save your choices: {save.error.message}
        </p>
      )}
      <Footer note="You can change the standard any time. Maku then shows what would be redone before doing it.">
        <Button onClick={onBack}>Back</Button>
        <Button
          variant="primary"
          disabled={save.isPending}
          onClick={() =>
            save.mutate({ path: "/settings", body: settings }, { onSuccess: onContinue })
          }
        >
          Continue
        </Button>
      </Footer>
    </Panel>
  );
}

/** The chosen standard in one line, for the finished step. */
export function describe(settings: Settings): string {
  const standard = STANDARDS.find((each) => each.value === settings.standard);
  const naming = NAMING.find((each) => each.value === settings.naming);
  const format = standard?.spec.split(" · ").slice(1).join(" · ") ?? "";
  const names = settings.naming === "keep" ? "names kept" : `named for ${naming?.label}`;
  return `${standard?.name ?? settings.standard} · ${format} · ${names}`;
}
