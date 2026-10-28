import { afterEach, describe, expect, it, vi } from "vitest";
import { SCHEMES, showScheme, startingScheme } from "./look";
import script from "./scheme-script.js?raw";

/** Runs what the shell runs before the page (app/src-tauri/src/look.rs): the scheme it kept when
 * it made the window, then this script. */
function runShellScript(kept: string) {
  window.__MAKU_SCHEME__ = kept;
  new Function(script)();
}

const root = document.documentElement;

describe("the scheme before the first frame", () => {
  afterEach(() => {
    if (!document.documentElement) document.appendChild(root);
    delete window.__MAKU_SCHEME__;
    delete root.dataset.scheme;
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("is the one the shell keeps, on the page before anything else runs", () => {
    runShellScript("lagoon");

    expect(root.dataset.scheme).toBe("lagoon");
    expect(startingScheme()).toBe("lagoon");
  });

  it("waits for the page's root when the script runs before there is one", async () => {
    root.remove(); // as WebView2 runs it: before the page is read
    runShellScript("dusk");
    expect(root.dataset.scheme).toBeUndefined();

    document.appendChild(root);
    await Promise.resolve(); // what watches for it hears at once, before anything is painted

    expect(root.dataset.scheme).toBe("dusk");
  });

  it("is the newest chosen this session when the page is loaded again", () => {
    for (const { value } of SCHEMES) {
      showScheme(value); // chosen after the window was made with Lagoon
      delete root.dataset.scheme;

      runShellScript("lagoon");

      expect(root.dataset.scheme).toBe(value);
      expect(startingScheme()).toBe(value);
    }
  });

  it("is the shell's when the session can't be read", () => {
    showScheme("graphite");
    delete root.dataset.scheme;
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("Storage is switched off.", "SecurityError");
    });

    runShellScript("dusk");

    expect(root.dataset.scheme).toBe("dusk");
  });

  it("is the shell's when the session holds no scheme", () => {
    sessionStorage.setItem("maku-scheme", "neon");

    runShellScript("lagoon");

    expect(root.dataset.scheme).toBe("lagoon");
  });
});

describe("showScheme", () => {
  afterEach(() => {
    delete root.dataset.scheme;
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("wears a scheme at once", () => {
    showScheme("dusk");

    expect(root.dataset.scheme).toBe("dusk");
  });

  it("wears it still when the session can't keep it", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("The quota is spent.", "QuotaExceededError");
    });

    showScheme("lagoon");

    expect(root.dataset.scheme).toBe("lagoon");
  });
});
