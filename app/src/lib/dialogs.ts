import { invoke } from "@tauri-apps/api/core";

/** Asks for a folder with Windows' folder picker. Null when it's cancelled. */
export function pickFolder(title: string) {
  return invoke<string | null>("pick_folder", { title });
}

/** Asks for a Maku export (its zip) with Windows' file picker. Null when it's cancelled. */
export function pickExport(title: string) {
  return invoke<string | null>("pick_export", { title });
}
