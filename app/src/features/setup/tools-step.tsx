import { Check } from "lucide-react";
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router";
import { ThisPc } from "@/components/this-pc";
import { Button } from "@/components/ui/button";
import {
  type Tool,
  useDownloadTool,
  useSaveSettings,
  useScanAction,
  useSettings,
  useSystem,
  useTestPc,
  useTools,
} from "@/lib/engine";
import { Footer, Panel } from "./parts";

export function ToolsStep({ onBack }: { onBack: () => void }) {
  const tools = useTools();
  const system = useSystem();
  const stored = useSettings();
  const save = useSaveSettings();
  const scan = useScanAction();
  const navigate = useNavigate();
  // The speech models come the first time subtitles are asked for, not now.
  const needed = tools.data?.filter((tool) => tool.when === "setup");
  const ready = needed?.every((tool) => tool.state === "ready") ?? false;
  useTestOnce(ready);

  function startScan() {
    if (!stored.data) return;
    save.mutate(
      { path: "/settings", body: { ...stored.data, setUp: true } },
      {
        onSuccess: () =>
          scan.mutate({ path: "/scan" }, { onSuccess: () => void navigate("/scan") }),
      },
    );
  }

  return (
    <Panel
      title="Tools and this PC"
      labelledBy="tools-title"
      intro="Maku fetches ffmpeg once, checks it against the list it ships with, then looks at what this PC can do with it."
    >
      <ul className="flex flex-col gap-3">
        {needed?.map((tool) => (
          <li key={tool.id}>
            <ToolRow tool={tool} />
          </li>
        ))}
      </ul>
      {system.data && <ThisPc system={system.data} waiting={!ready} />}
      {(save.isError || scan.isError) && (
        <p role="alert" className="text-13 text-broken-fg">
          The scan didn't start: {(save.error ?? scan.error)?.message}
        </p>
      )}
      <Footer note="The first scan only looks: nothing is renamed or moved.">
        <Button onClick={onBack}>Back</Button>
        <Button
          variant="primary"
          disabled={!ready || save.isPending || scan.isPending}
          onClick={startScan}
        >
          Start the first scan
        </Button>
      </Footer>
    </Panel>
  );
}

/**
 * Tests this PC once ffmpeg is ready, unless its times are measured already: the test times
 * each part, so what Setup shows is this PC's own.
 */
function useTestOnce(ready: boolean) {
  const system = useSystem();
  const test = useTestPc();
  const asked = useRef(false);
  const due = ready && system.data && !system.data.measured && !system.data.testing;
  useEffect(() => {
    if (!due || asked.current) return;
    asked.current = true;
    test.mutate({ path: "/system/test" });
  }, [due, test]);
}

function ToolRow({ tool }: { tool: Tool }) {
  const download = useDownloadTool();
  const busy = tool.state === "downloading" || tool.state === "unpacking";
  const percent = tool.size ? Math.round((tool.done / tool.size) * 100) : 0;

  return (
    <div className="flex flex-col gap-3 rounded-16 border border-edge bg-glass px-4 py-3.5">
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex min-w-0 flex-[1_1_320px] flex-col gap-0.5">
          <span className="font-extrabold text-15">
            {tool.name} <span className="font-normal text-fg-muted">{tool.version}</span>
          </span>
          <span className="text-13 text-fg-muted">{tool.purpose}</span>
          <span className="font-mono text-11 text-fg-faint">
            {megabytes(tool.size)} · {tool.licence}
          </span>
        </div>
        {tool.state === "ready" && (
          <span className="inline-flex items-center gap-2 font-bold text-13 text-accent-fg">
            <Check size={16} strokeWidth={3} aria-hidden="true" />
            Ready
          </span>
        )}
        {(tool.state === "missing" || tool.state === "failed") && (
          <Button
            variant={tool.state === "missing" ? "primary" : "secondary"}
            disabled={download.isPending}
            onClick={() => download.mutate({ path: `/tools/${tool.id}/download` })}
          >
            {tool.state === "missing" ? "Download" : "Try again"}
          </Button>
        )}
        {busy && (
          <span className="font-mono text-12 text-fg-muted">
            {tool.state === "unpacking" ? "Unpacking…" : `${percent}%`}
          </span>
        )}
      </div>
      {busy && (
        <div
          role="progressbar"
          aria-label={`Downloading ${tool.name}`}
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          className="h-1.5 overflow-hidden rounded-3 bg-track"
        >
          <div
            className="h-full rounded-3 bg-accent transition-[width] duration-320 ease-cinema"
            style={{ width: `${percent}%` }}
          />
        </div>
      )}
      {tool.state === "failed" && tool.problem && (
        <p role="alert" className="text-13 text-broken-fg">
          {tool.problem}
        </p>
      )}
    </div>
  );
}

export function CardFound({ name }: { name: string }) {
  return (
    <span className="inline-flex h-7.5 items-center gap-2 rounded-full bg-tint/5 px-3 font-bold text-12 text-fg-soft">
      <span aria-hidden="true" className="size-2 animate-pulse rounded-full bg-accent" />
      {name.replace(/^NVIDIA GeForce /, "")} found
    </span>
  );
}

export function megabytes(bytes: number): string {
  return `${Math.round(bytes / 1e6)} MB`;
}
