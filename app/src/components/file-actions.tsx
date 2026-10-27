import { useEffect, useState } from "react";
import { MenuItem } from "@/components/ui/menu";
import { showInFolder, useExplorer } from "@/lib/explorer";

/** What can be done with a video file wherever it shows: showing it in its folder, and copying
 * its path, with a word on how that went (the shell's own, when Explorer can't show it). */
export function useFileActions() {
  const explorer = useExplorer();
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);
  return {
    show: (path: string) => {
      setCopied(false);
      explorer.run(() => showInFolder(path));
    },
    copy: (path: string) => {
      explorer.clear();
      navigator.clipboard.writeText(path).then(
        () => setCopied(true),
        () => setCopied(false), // the window wasn't let at the clipboard: nothing to say
      );
    },
    note: explorer.problem ?? (copied ? "Its path is copied." : null),
  };
}

type FileActions = ReturnType<typeof useFileActions>;

/** A file's two menu items: in a row's "More" menu, beside what else the row does. */
export function FileMenuItems({ path, actions }: { path: string; actions: FileActions }) {
  return (
    <>
      <MenuItem onSelect={() => actions.show(path)}>Show in folder</MenuItem>
      <MenuItem onSelect={() => actions.copy(path)}>Copy path</MenuItem>
    </>
  );
}

/** How showing or copying went, under the row it was asked of. */
export function FileNote({ actions, className }: { actions: FileActions; className?: string }) {
  if (!actions.note) return null;
  return (
    <p role="status" className={className ?? "text-12 text-fg-muted"}>
      {actions.note}
    </p>
  );
}
