import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { invoke } from "@tauri-apps/api/core";

/**
 * Light or dark: as Windows is (the default), or always one. The shell keeps the choice and gives
 * the window its theme, and the page's colours follow it (styles/tokens.css), so nothing here
 * paints. Mirrors `Look` in src-tauri/src/look.rs.
 */
export type Look = "windows" | "light" | "dark";

export const LOOKS: readonly { value: Look; label: string }[] = [
  { value: "windows", label: "Same as Windows" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

const KEY = ["shell", "look"];

/** The look chosen. */
export function useLook() {
  return useQuery({ queryKey: KEY, queryFn: () => invoke<Look>("look") });
}

/** Chooses the look, from now and at every start. */
export function useSetLook() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: (look: Look) => invoke<Look>("set_look", { look }),
    onSuccess: (look) => queries.setQueryData(KEY, look),
  });
}

/**
 * Maku's colours: one of four schemes, each in light and dark. The shell keeps the choice, and
 * its script puts it on the page before the first frame (scheme-script.js): the page wears it as
 * `data-scheme` on <html>, and styles/tokens.css does the rest. Mirrors `Scheme` in
 * src-tauri/src/look.rs.
 */
export type Scheme = "velvet" | "lagoon" | "dusk" | "graphite";

/** Each scheme, with the colours its swatch shows: its window and accent, in dark and light
 * (the same as in styles/tokens.css). */
export const SCHEMES: readonly {
  value: Scheme;
  label: string;
  text: string;
  dark: { window: string; accent: string; ready: string };
  light: { window: string; accent: string; ready: string };
}[] = [
  {
    value: "velvet",
    label: "Velvet",
    text: "Wine and crimson, brass for what's ready",
    dark: { window: "#120b0e", accent: "#c8374f", ready: "#d6a84f" },
    light: { window: "#f6efea", accent: "#b52f48", ready: "#c9973a" },
  },
  {
    value: "lagoon",
    label: "Lagoon",
    text: "Deep teal, a coral sun",
    dark: { window: "#061113", accent: "#2cc6b5", ready: "#2cc6b5" },
    light: { window: "#eef5f4", accent: "#0d7f74", ready: "#13a395" },
  },
  {
    value: "dusk",
    label: "Dusk",
    text: "Indigo and coral pink",
    dark: { window: "#0c0a16", accent: "#ff6f91", ready: "#ff6f91" },
    light: { window: "#f3f1fa", accent: "#c92d62", ready: "#e0477a" },
  },
  {
    value: "graphite",
    label: "Graphite",
    text: "Black and white, nothing else",
    dark: { window: "#0d0e10", accent: "#ececee", ready: "#ececee" },
    light: { window: "#f4f4f3", accent: "#16171a", ready: "#2a2c31" },
  },
];

declare global {
  interface Window {
    /** The scheme to start in, as the shell's script leaves it before anything else runs: the
     * one the shell keeps, or the newest chosen since, should the page have been reloaded. */
    __MAKU_SCHEME__?: string;
  }
}

const SCHEME_KEY = ["shell", "scheme"];
/** Where the session keeps the scheme the page wears, so a reload starts in the newest choice.
 * The shell's script reads it (scheme-script.js). */
const WORN = "maku-scheme";

function isScheme(value: unknown): value is Scheme {
  return SCHEMES.some((each) => each.value === value);
}

/** The scheme to start in: the one the shell's script put on the page, else Velvet. */
export function startingScheme(): Scheme {
  const told = window.__MAKU_SCHEME__;
  return isScheme(told) ? told : "velvet";
}

/** Puts a scheme on the page: its colours change at once, and a reload starts in it. */
export function showScheme(scheme: Scheme) {
  document.documentElement.dataset.scheme = scheme;
  try {
    sessionStorage.setItem(WORN, scheme);
  } catch {
    // The session keeps nothing: a reload starts in the one the shell keeps.
  }
}

/** The scheme the page wears now. */
function wornScheme(): Scheme | undefined {
  const worn = document.documentElement.dataset.scheme;
  return isScheme(worn) ? worn : undefined;
}

/** The scheme chosen, as the shell keeps it. */
export function savedScheme(): Promise<Scheme> {
  return invoke<Scheme>("scheme");
}

/** The scheme chosen. */
export function useScheme() {
  return useQuery({ queryKey: SCHEME_KEY, queryFn: savedScheme });
}

/** Chooses the scheme, from now and at every start: the page wears it at once, and goes back to
 * the one the shell keeps (else the one it wore) should the shell not keep it. */
export function useSetScheme() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: (scheme: Scheme) => invoke<Scheme>("set_scheme", { scheme }),
    onMutate: (scheme) => {
      const worn = wornScheme();
      showScheme(scheme);
      return worn;
    },
    onSuccess: (scheme) => queries.setQueryData(SCHEME_KEY, scheme),
    onError: (_error, _scheme, worn) => {
      const kept = queries.getQueryData<Scheme>(SCHEME_KEY) ?? worn;
      if (kept) showScheme(kept); // the shell didn't keep it: back to the one it has
    },
  });
}
