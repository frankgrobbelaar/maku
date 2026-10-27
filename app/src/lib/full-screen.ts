import { getCurrentWindow } from "@tauri-apps/api/window";

/** Makes Maku's window full screen, or puts it back as it was (the player's full screen). Out of
 * Maku's shell (in a test), nothing happens. */
export function fullScreen(on: boolean) {
  Promise.resolve()
    .then(() => getCurrentWindow().setFullscreen(on))
    .catch(() => {});
}
