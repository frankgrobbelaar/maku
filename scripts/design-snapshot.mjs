// Turns the Maku Design canvas's boards (.dc.html) into plain HTML pages in docs/design/, so every
// board opens in a browser without the canvas.
//
//   node scripts/design-snapshot.mjs --design <folder>
//
// The canvas as Claude's Artifact tool saves it: a folder holding project/canvas.json. Its Main
// board becomes index.html, every other board a page of its own. See docs/design.md.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const CANVASES = {
  design: "https://claude.ai/artifact/1pVuwSLdjXnp4gPJygp8B8",
};
const out = join(dirname(fileURLToPath(import.meta.url)), "..", "docs", "design");
const today = new Date().toISOString().slice(0, 10);

const folders = foldersIn(process.argv.slice(2));
if (!folders) {
  console.error("Usage: node scripts/design-snapshot.mjs --design <folder>");
  process.exit(1);
}
let written = 0;

if (folders.design) {
  const design = readCanvas(folders.design);
  mkdirSync(out, { recursive: true });
  for (const file of design.order) {
    const name = file.replace(".dc.html", "");
    const page = toPage(design, file, {
      canvas: CANVASES.design,
      link: (target) => (target === "Main" ? "index.html" : `${target.toLowerCase()}.html`),
    });
    writeFileSync(join(out, name === "Main" ? "index.html" : `${name.toLowerCase()}.html`), page);
    written += 1;
  }
}

console.log(`Wrote ${written} pages to ${out}`);

/** The canvases' folders by name (`--light <folder>`), or nothing when the arguments don't read. */
function foldersIn(args) {
  const found = {};
  for (let index = 0; index < args.length; index += 2) {
    const name = args[index].replace(/^--/, "");
    if (!(name in CANVASES) || !args[index + 1]) return null;
    found[name] = args[index + 1];
  }
  return Object.keys(found).length > 0 ? found : null;
}

function readCanvas(folder) {
  const index = JSON.parse(readFileSync(join(folder, "project", "canvas.json"), "utf8"));
  const source = (file) => readFileSync(join(folder, "project", file), "utf8");
  return { ...index, source };
}

function toPage(canvas, file, { canvas: url, link }) {
  const source = canvas.source(file);
  const title = canvas.boards[file]?.title ?? file;
  const helmet = source.match(/<helmet>([\s\S]*?)<\/helmet>/)?.[1] ?? "";
  // A board's own handlers (a drag, a ref) are the canvas's to run, not the page's.
  const board = source
    .match(/<x-dc>([\s\S]*?)<\/x-dc>/)[1]
    .replace(/<helmet>[\s\S]*?<\/helmet>/, "")
    .replace(/\s(?:ref|on[A-Z]\w*)="\{\{[^}]+\}\}"/g, "");
  const body = expand(board, renderValues(source)).replace(
    /href="([\w.-]+)\.dc\.html"/g,
    (_, target) => `href="${link(target)}"`,
  );
  return `<!doctype html>
<!-- Maku design snapshot of "${title}" (${url}), taken ${today}.
     Change the canvas, then re-run scripts/design-snapshot.mjs; don't edit this file. -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title} · Maku design</title>
${helmet.trim()}
</head>
<body>
${body.trim()}
</body>
</html>
`;
}

// A board's script builds the data its template repeats over. It only computes
// values, so it runs in an empty sandbox with nothing but the base class it needs.
function renderValues(source) {
  const script = source.match(/<script type="text\/x-dc"[^>]*>([\s\S]*?)<\/script>/)?.[1];
  if (!script) return {};
  const sandbox = vm.createContext({
    DCLogic: class {
      props = {};
    },
  });
  return vm.runInContext(`${script}\n;new Component().renderVals()`, sandbox, { timeout: 1000 });
}

// Expands <sc-for>, <sc-if> and {{holes}} the way the canvas renders them.
function expand(html, scope) {
  let result = "";
  let rest = html;
  for (;;) {
    const open = rest.match(/<sc-(for|if)\b([^>]*)>/);
    if (!open) return result + fillHoles(rest, scope);
    const [tag, kind, attributes] = open;
    const close = findClose(rest, kind, open.index + tag.length);
    const inner = rest.slice(open.index + tag.length, close);
    const binding = (name) =>
      attributes.match(new RegExp(`${name}="\\{\\{([^}]+)\\}\\}"`))?.[1].trim();

    result += fillHoles(rest.slice(0, open.index), scope);
    if (kind === "for") {
      const as = attributes.match(/as="([^"]+)"/)[1];
      for (const item of lookup(scope, binding("list")) ?? []) {
        result += expand(inner, { ...scope, [as]: item });
      }
    } else if (lookup(scope, binding("value"))) {
      result += expand(inner, scope);
    }
    rest = rest.slice(close + `</sc-${kind}>`.length);
  }
}

function findClose(html, kind, from) {
  const tags = new RegExp(`<sc-${kind}\\b|</sc-${kind}>`, "g");
  tags.lastIndex = from;
  let depth = 1;
  for (let tag = tags.exec(html); tag; tag = tags.exec(html)) {
    depth += tag[0].startsWith("</") ? -1 : 1;
    if (depth === 0) return tag.index;
  }
  throw new Error(`<sc-${kind}> is never closed`);
}

function fillHoles(html, scope) {
  return html.replace(/\{\{([^}]+)\}\}/g, (_, path) => escapeHtml(lookup(scope, path.trim()) ?? ""));
}

function lookup(scope, path) {
  return path.split(".").reduce((value, key) => value?.[key], scope);
}

function escapeHtml(value) {
  const entities = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
  return String(value).replace(/[&<>"]/g, (character) => entities[character]);
}
