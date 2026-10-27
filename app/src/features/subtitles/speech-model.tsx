import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { type Quality, SPEECH_MODELS, type Tool, useDownloadTool, useTools } from "@/lib/engine";
import { size } from "@/lib/format";

/**
 * English subtitles in the queue wait for a speech model that isn't on this PC: what it is, how
 * its download goes, and the way to fetch it, or fetch it again when the download failed. They
 * start once it's here.
 */
export function SpeechModelWait({ quality }: { quality: Quality }) {
  const tools = useTools();
  const download = useDownloadTool();
  const model = tools.data?.find((tool) => tool.id === SPEECH_MODELS[quality]);
  if (!model || model.state === "ready") return null;
  const busy = model.state === "downloading" || model.state === "unpacking";
  return (
    <div
      role="status"
      aria-label="Speech model"
      className="flex animate-fade-up flex-col gap-3 rounded-18 border border-tint/10 bg-raised px-4.5 py-4 shadow-panel"
    >
      <span className="flex gap-3 text-14">
        <Download size={20} aria-hidden="true" className="shrink-0 text-accent-fg" />
        <span>
          <strong className="font-extrabold">English subtitles wait for their speech model.</strong>{" "}
          {words(model)}
        </span>
      </span>
      <span className="font-mono text-12 text-fg-muted">
        {model.name} · {size(model.size)} · {model.licence} licence
      </span>
      {model.state === "failed" && model.problem && (
        <span className="text-13 text-broken-fg">{model.problem}</span>
      )}
      {download.isError && (
        <span role="alert" className="text-13 text-broken-fg">
          {download.error.message}
        </span>
      )}
      {!busy && (
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="primary"
            disabled={download.isPending}
            onClick={() => download.mutate({ path: `/tools/${model.id}/download` })}
          >
            {model.state === "failed" ? "Try again" : "Download it"}
          </Button>
        </div>
      )}
    </div>
  );
}

function words(model: Tool): string {
  if (model.state === "downloading" || model.state === "unpacking") {
    const share = Math.round((100 * model.done) / Math.max(model.size, 1));
    return `Downloading · ${share}%. They start once it's on this PC.`;
  }
  if (model.state === "failed") return "Its download didn't finish.";
  return "It's downloaded once, from the source the installer's first page lists, and checked before it's used.";
}
