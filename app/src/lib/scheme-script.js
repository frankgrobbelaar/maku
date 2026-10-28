// What Maku's window runs before the page, once the shell has told it the scheme it keeps
// (`window.__MAKU_SCHEME__ = "dusk";`, app/src-tauri/src/look.rs, which embeds this file as it
// is): puts the scheme on <html> before the first frame, so the page never shows another first.
// A page loaded again in the same session starts in the newest scheme chosen (lib/look.ts keeps
// it there), not the one the window was made with. It runs before the page is read, while there's
// no <html> yet: then it waits for one, and wears the scheme as it comes.
(() => {
  const schemes = ["velvet", "lagoon", "dusk", "graphite"]; // as `Scheme` in lib/look.ts
  let scheme = window.__MAKU_SCHEME__;
  try {
    const newest = window.sessionStorage.getItem("maku-scheme");
    if (schemes.includes(newest)) scheme = newest;
  } catch {
    // The session keeps nothing: the shell's scheme stands.
  }
  if (!schemes.includes(scheme)) return;
  window.__MAKU_SCHEME__ = scheme;
  const wear = () => {
    const root = document.documentElement;
    if (root) root.dataset.scheme = scheme;
    return root !== null;
  };
  if (wear()) return;
  const watch = new MutationObserver(() => {
    if (wear()) watch.disconnect();
  });
  watch.observe(document, { childList: true });
})();
