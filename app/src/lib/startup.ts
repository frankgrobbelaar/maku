import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { invoke } from "@tauri-apps/api/core";

const KEY = ["shell", "start-with-windows"];
const KEEP = ["shell", "keep-in-tray"];

/**
 * Whether Maku starts with Windows and waits in the tray. Windows keeps the answer (the shell
 * asks it, src-tauri/src/tray.rs), so it's true even when it was set before this launch.
 */
export function useStartWithWindows() {
  return useQuery({ queryKey: KEY, queryFn: () => invoke<boolean>("start_with_windows") });
}

/** Turns starting with Windows on or off. */
export function useSetStartWithWindows() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: (on: boolean) => invoke<boolean>("set_start_with_windows", { on }),
    onSuccess: (on) => queries.setQueryData(KEY, on),
  });
}

/** Whether closing the window keeps Maku running in the tray (the shell keeps the choice). */
export function useKeepInTray() {
  return useQuery({ queryKey: KEEP, queryFn: () => invoke<boolean>("keep_in_tray") });
}

/** Closing the window keeps Maku running in the tray, or quits it. */
export function useSetKeepInTray() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: (on: boolean) => invoke<boolean>("set_keep_in_tray", { on }),
    onSuccess: (on) => queries.setQueryData(KEEP, on),
  });
}
