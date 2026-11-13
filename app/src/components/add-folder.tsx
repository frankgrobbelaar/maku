import { useState } from "react";
import { useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { pickFolder } from "@/lib/dialogs";
import { useAddFolder, useScanAction } from "@/lib/engine";

/** Scanning again, and adding a folder, which a scan of it follows: by Home's title, and on an
 * empty shelf once setup is done (a PC with no videos yet skips its folders). */
export function useAddAndScan() {
  const navigate = useNavigate();
  const action = useScanAction();
  const add = useAddFolder();
  const [picking, setPicking] = useState(false);

  const rescan = () =>
    action.mutate({ path: "/scan" }, { onSuccess: () => void navigate("/scan") });

  async function addFolder() {
    setPicking(true);
    try {
      const path = await pickFolder("Choose a folder with series or films in it");
      if (path) add.mutate({ path: "/folders", body: { path } }, { onSuccess: rescan });
    } finally {
      setPicking(false);
    }
  }

  return { action, add, picking, rescan, addFolder };
}

/** An empty shelf's "Add a folder", on Home and the Library: the folder, then its scan. */
export function AddFirstFolder() {
  const { action, add, picking, addFolder } = useAddAndScan();
  return (
    <div className="flex flex-col items-center gap-2">
      <Button
        variant="primary"
        disabled={picking || add.isPending || action.isPending}
        onClick={() => void addFolder()}
      >
        Add a folder
      </Button>
      {(add.isError || action.isError) && (
        <p role="alert" className="text-13 text-broken-fg">
          {(add.error ?? action.error)?.message}
        </p>
      )}
    </div>
  );
}
