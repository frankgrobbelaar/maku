import { Folder } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { pickFolder } from "@/lib/dialogs";
import { useAddFolder, useFolders, useForgetFolder } from "@/lib/engine";
import { FolderChip, Footer, Panel } from "./parts";

export function FoldersStep({
  onBack,
  onContinue,
}: {
  onBack: () => void;
  onContinue: () => void;
}) {
  const folders = useFolders();
  const add = useAddFolder();
  const forget = useForgetFolder();
  const [picking, setPicking] = useState(false);
  const none = !folders.data?.length;

  async function addFolder() {
    setPicking(true);
    try {
      const path = await pickFolder("Choose a folder with series or films in it");
      if (path) add.mutate({ path: "/folders", body: { path } });
    } finally {
      setPicking(false);
    }
  }

  return (
    <Panel title="Your video folders" labelledBy="folders-title">
      <p className="text-14 text-fg-muted">
        A folder can hold many series and films in any layout, even mixed together. Maku works out
        what is what. Nothing in them changes: Maku only looks.
      </p>
      {folders.data && folders.data.length > 0 && (
        <ul aria-label="Folders in your library" className="flex flex-wrap gap-2">
          {folders.data.map((folder) => (
            <li key={folder.id}>
              <FolderChip
                path={folder.path}
                onRemove={() => forget.mutate({ path: `/folders/${folder.id}` })}
              />
            </li>
          ))}
        </ul>
      )}
      <div>
        <Button
          variant={none ? "primary" : "secondary"}
          disabled={picking || add.isPending}
          onClick={() => void addFolder()}
        >
          <Folder size={16} aria-hidden="true" />
          Add a folder
        </Button>
      </div>
      {add.isError && (
        <p role="alert" className="text-13 text-broken-fg">
          {add.error.message}
        </p>
      )}
      <Footer note="Add as many as you like. Later scans only read what's new.">
        <Button onClick={onBack}>Back</Button>
        <Button variant={none ? "secondary" : "primary"} disabled={none} onClick={onContinue}>
          Continue
        </Button>
      </Footer>
    </Panel>
  );
}
