import { AlertTriangle, Check, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { type TidyResult, useDeleteFiles, useSettings, useUndoPlan } from "@/lib/engine";
import { size } from "@/lib/format";

/** A video the owner can delete: a title's (TitleFile) or one waiting for a match (WaitingFile). */
export interface Deletable {
  id: number;
  path: string;
  /** In bytes. */
  size: number;
}

/** What the owner is asked about deleting: the videos, and how the question names them. */
export interface Asking {
  /** "The Harbour Line", "season 4", "S01E03", "this file": "Delete S01E03?" */
  what: string;
  /** Where the question shows: "title", "season-4", "video-17", "file-17". */
  where: string;
  files: Deletable[];
}

/** A small bin beside what it deletes. It only asks: nothing goes till the owner confirms. */
export function DeleteIcon({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="press inline-flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-full text-fg-faint hover:text-danger"
    >
      <Trash2 size={14} aria-hidden="true" />
    </button>
  );
}

/**
 * Deletes what the owner confirms, once they confirm it. It lives with the page, not with the
 * question: the videos (and the row the question sits in) go as soon as they're deleted.
 */
export function useDeleting(onDone: (result: TidyResult) => void) {
  const remove = useDeleteFiles();
  return {
    busy: remove.isPending,
    problem: remove.error?.message ?? null,
    reset: remove.reset,
    delete: (files: Deletable[]) =>
      remove.mutate(
        { path: "/files/delete", body: { files: files.map((file) => file.id) } },
        { onSuccess: onDone },
      ),
  };
}

/**
 * Asks before deleting, saying how much goes, where to, and for how long it can come back.
 * Maku deletes the way it sets copies aside: into the quarantine on the videos' own drive.
 */
export function ConfirmDelete(props: {
  asking: Asking;
  busy: boolean;
  problem: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const settings = useSettings();
  const { what, files } = props.asking;
  const videos = files.length === 1 ? "1 video" : `${files.length} videos`;
  const bytes = files.reduce((sum, file) => sum + file.size, 0);
  const drives = [...new Set(files.map((file) => /^[a-z]:/i.exec(file.path)?.[0].toUpperCase()))]
    .filter(Boolean)
    .join(" and ");
  const days = settings.data?.quarantineDays;
  const kept =
    days === null
      ? "They stay there, and History can put them back."
      : `They're deleted for good after ${days ?? 30} days; till then History puts them back.`;
  return (
    <fieldset
      aria-label={`Delete ${what}?`}
      className="flex animate-fade-up flex-col gap-3 rounded-16 border border-danger/40 bg-danger/8 p-4"
    >
      <span className="font-extrabold text-14">Delete {what}?</span>
      <span className="text-13 text-fg-soft">
        {videos} ({size(bytes)}) {files.length === 1 ? "goes" : "go"} to the quarantine on{" "}
        {drives || "its drive"}, with any subtitles named after {files.length === 1 ? "it" : "them"}
        . {kept}
      </span>
      {props.problem && (
        <p role="alert" className="text-13 text-broken-fg">
          {props.problem}
        </p>
      )}
      <div className="flex flex-wrap gap-2.5">
        <Button size="sm" variant="danger" disabled={props.busy} onClick={props.onConfirm}>
          Delete {videos}
        </Button>
        <Button size="sm" variant="ghost" onClick={props.onCancel}>
          Cancel
        </Button>
      </div>
    </fieldset>
  );
}

/** Right after deleting: what went, the way to put it back, and what stayed and why. */
export function Deleted(props: { result: TidyResult; onPutBack: () => void }) {
  const undo = useUndoPlan();
  const { quarantined: count, problems } = props.result;
  return (
    <section
      aria-label="Deleted"
      className="flex animate-fade-up flex-wrap items-center gap-3 rounded-20 border border-edge bg-glass px-5 py-3.5 text-13 shadow-panel"
    >
      {count > 0 ? (
        <Check size={16} aria-hidden="true" className="shrink-0 text-accent-fg" />
      ) : (
        <AlertTriangle size={16} aria-hidden="true" className="shrink-0 text-broken-fg" />
      )}
      <span className="min-w-0 flex-1">
        {count > 0
          ? `Deleted ${count === 1 ? "1 video" : `${count} videos`}.`
          : "Nothing was deleted."}
      </span>
      {undo.isError && (
        <span role="alert" className="text-broken-fg">
          {undo.error.message}
        </span>
      )}
      {problems.length > 0 && (
        <ul className="flex basis-full flex-col gap-1 text-broken-fg">
          {problems.map((problem) => (
            <li key={problem.source}>
              {problem.label}: {problem.problem}
            </li>
          ))}
        </ul>
      )}
      {props.result.planId !== null && count > 0 && (
        <Button
          size="sm"
          disabled={undo.isPending}
          onClick={() =>
            undo.mutate(
              { path: `/plans/${props.result.planId}/undo` },
              { onSuccess: props.onPutBack },
            )
          }
        >
          Put back
        </Button>
      )}
    </section>
  );
}
