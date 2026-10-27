// Builds Maku's downloads page: every published version, newest first, with its notes and its
// installer. The downloads workflow publishes it on GitHub Pages after each release.
//
//   node scripts/downloads-page.mjs <folder>                     # reads the releases from GitHub
//   node scripts/downloads-page.mjs <folder> --releases <file>   # from a saved list, to preview
//
// See docs/releasing.md.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compareVersions, parseVersion } from "./versioning.mjs";

const REPOSITORY = "frankgrobbelaar/maku";

// Maku's mark, a stage curtain drawn back (幕, maku, is a curtain), as app/src-tauri/icons/maku.svg.
const LOGO = `<svg viewBox="0 0 24 24" width="32" height="32" aria-hidden="true">
  <rect x="1" y="1" width="22" height="22" rx="7" fill="#c8374f"/>
  <rect x="5.8" y="5.4" width="12.4" height="2.2" rx="1.1" fill="#fff4ec"/>
  <path d="M5.8 7.2H11.8C10.2 7.6 8.6 9.6 8 12.6C8 14.8 8.4 16.8 9 18.6H6.8A1 1 0 0 1 5.8 17.6Z" fill="#fff4ec"/>
  <path d="M18.2 7.2H12.2C13.8 7.6 15.4 9.6 16 12.6C16 14.8 15.6 16.8 15 18.6H17.2A1 1 0 0 0 18.2 17.6Z" fill="#fff4ec"/>
</svg>`;

export function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function inline(text) {
  return escapeHtml(text)
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2">$2</a>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

/** The little Markdown the changelog uses: headings, lists (with wrapped lines), links, bold, code. */
export function markdown(text) {
  const html = [];
  let list = null;
  let paragraph = [];
  const close = () => {
    if (paragraph.length) html.push(`<p>${inline(paragraph.join(" "))}</p>`);
    if (list) html.push(`<ul>${list.map((item) => `<li>${inline(item)}</li>`).join("")}</ul>`);
    paragraph = [];
    list = null;
  };
  for (const raw of String(text).replaceAll("\r\n", "\n").split("\n")) {
    const line = raw.trim();
    const heading = /^#{1,6} (.+)$/.exec(line);
    const item = /^[-*] (.+)$/.exec(line);
    if (!line) {
      close();
    } else if (heading) {
      close();
      html.push(`<h3>${inline(heading[1])}</h3>`);
    } else if (item) {
      if (paragraph.length) close();
      list ??= [];
      list.push(item[1]);
    } else if (list && /^\s/.test(raw)) {
      list[list.length - 1] += ` ${line}`;
    } else {
      if (list) close();
      paragraph.push(line);
    }
  }
  close();
  return html.join("\n");
}

/** Splits release notes into what's new and the list of every commit after it. */
function splitNotes(body) {
  const text = String(body ?? "").replaceAll("\r\n", "\n");
  const at = text.search(/^### Every change/m);
  return at === -1 ? [text, ""] : [text.slice(0, at), text.slice(at)];
}

function day(iso) {
  const options = { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" };
  return new Date(iso).toLocaleDateString("en-GB", options);
}

function megabytes(bytes) {
  return `${(bytes / 1e6).toFixed(1)} MB`;
}

/** Published versions, newest first, each with its installer and notices. */
export function versions(releases) {
  return releases
    .filter((release) => !release.draft && !release.prerelease)
    .map((release) => ({ release, version: String(release.tag_name).replace(/^v/, "") }))
    .filter(({ version }) => parseVersion(version))
    .sort((a, b) => compareVersions(b.version, a.version))
    .map(({ release, version }) => ({
      version,
      date: day(release.published_at),
      notes: release.body ?? "",
      page: release.html_url,
      installer: release.assets?.find((asset) => /_x64-setup\.exe$/.test(asset.name)) ?? null,
      notices: release.assets?.find((asset) => asset.name === "THIRD-PARTY-NOTICES.txt") ?? null,
    }));
}

// What a PC needs for each part of Maku, as the "Maku on Any PC" canvas has it (and the README).
const NEEDS = [
  [
    "Everything but converting",
    "Windows 10 or 11, 64-bit, and 8 GB of memory: finding and naming series and films, tidying up, the gap analysis and playing",
    "16 GB of memory",
  ],
  [
    "Converting to the standard",
    "A graphics card or the processor's graphics that encodes HEVC 10-bit: NVIDIA GeForce GTX 10-series or newer, AMD Radeon RX 5000 or newer, or Intel Core 7th generation or newer",
    "NVIDIA GeForce GTX 16-series or newer",
  ],
  [
    "English subtitles",
    "Fast: 2 GB of graphics memory, or the processor, slowly. Best: 4 GB",
    "6 GB: Best in about 8 minutes an episode",
  ],
  [
    "Space",
    "About 350 MB for Maku and ffmpeg, 2 GB more with both speech models",
    "Room beside your library for a converted file and its original",
  ],
];

function needs() {
  const rows = NEEDS.map(
    ([part, works, best]) =>
      `<tr><th scope="row">${escapeHtml(part)}</th><td>${escapeHtml(works)}</td><td>${escapeHtml(best)}</td></tr>`,
  ).join("\n");
  return `<section class="panel" aria-labelledby="needs">
  <h2 id="needs">What your PC needs</h2>
  <p>Maku runs on any 64-bit Windows 10 or 11 PC. What it can convert, and how fast, depends on the graphics card. Maku tests your PC when it's set up, says what it can and can't do there, and measures its own times on it.</p>
  <div class="table"><table>
<thead><tr><th scope="col">For</th><th scope="col">It works with</th><th scope="col">Best with</th></tr></thead>
<tbody>
${rows}
</tbody>
</table></div>
  <p class="note">Maku installs nothing by hand but a graphics driver, and says when one is too old for what it asks of the card.</p>
</section>`;
}

function downloadButton(version) {
  if (!version.installer) return "";
  return `<a class="button primary" href="${escapeHtml(version.installer.browser_download_url)}">Download for Windows</a>`;
}

function fileLine(version) {
  if (!version.installer) return "";
  const { name, size, digest } = version.installer;
  const hash = digest?.startsWith("sha256:")
    ? `<span class="hash">SHA-256 ${escapeHtml(digest.slice(7))}</span>`
    : "";
  return `<p class="file"><span>${escapeHtml(name)} · ${megabytes(size)}</span>${hash}</p>`;
}

function notesBlock(version) {
  const [whatsNew, everyChange] = splitNotes(version.notes);
  const every = everyChange.trim()
    ? `<details><summary>Every change in ${escapeHtml(version.version)}</summary>${markdown(everyChange)}</details>`
    : "";
  return `${markdown(whatsNew)}${every}`;
}

function hero(latest, repository) {
  if (!latest) {
    return `<section class="hero" aria-labelledby="latest">
  <span class="orb" aria-hidden="true"></span>
  <p class="eyebrow">Downloads</p>
  <h1 id="latest">Maku is on its way</h1>
  <p class="lede">No version has been released yet. Each one will appear here, newest first, with
  what changed and a download for Windows.</p>
  <div class="actions"><a class="button primary" href="${repository}">Maku on GitHub</a></div>
</section>`;
  }
  return `<section class="hero" aria-labelledby="latest">
  <span class="orb" aria-hidden="true"></span>
  <p class="eyebrow">Latest version</p>
  <h1 id="latest">Maku ${escapeHtml(latest.version)}</h1>
  <p class="lede">Released ${escapeHtml(latest.date)} · Windows 10 and 11, 64-bit</p>
  <div class="actions">${downloadButton(latest)}
    <a class="button ghost" href="${escapeHtml(latest.page)}">Release on GitHub</a></div>
  ${fileLine(latest)}
</section>`;
}

function previous(older) {
  if (!older.length) return "";
  const rows = older
    .map(
      (version) => `<details class="version">
  <summary><span class="name">Maku ${escapeHtml(version.version)}</span><span class="date">${escapeHtml(version.date)}</span></summary>
  <div class="body">
    <div class="actions">${version.installer ? `<a class="button small" href="${escapeHtml(version.installer.browser_download_url)}">Download ${escapeHtml(version.version)}</a>` : ""}
      <a class="button small ghost" href="${escapeHtml(version.page)}">Release on GitHub</a></div>
    ${fileLine(version)}
    ${notesBlock(version)}
  </div>
</details>`,
    )
    .join("\n");
  return `<section class="panel" aria-labelledby="older"><h2 id="older">Earlier versions</h2>${rows}</section>`;
}

export function renderPage(releases, repository = `https://github.com/${REPOSITORY}`) {
  const all = versions(releases);
  const [latest, ...older] = all;
  const whatsNew = latest
    ? `<section class="panel" aria-labelledby="new"><h2 id="new">What's new in ${escapeHtml(latest.version)}</h2>${notesBlock(latest)}</section>`
    : "";
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Maku downloads</title>
<meta name="description" content="Download Maku for Windows: the latest version and every earlier one, with what changed.">
<link rel="icon" href="data:image/svg+xml,${encodeURIComponent(LOGO.replace(' width="32" height="32"', ""))}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist+Mono:wght@400;500&family=Manrope:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {
    color-scheme: dark;
    /* Velvet, Maku's own scheme, in dark (app/src/styles/tokens.css). */
    --window: #120b0e; --glass: rgb(247 238 240 / 0.045); --edge: rgb(247 238 240 / 0.08);
    --fg: #f7eef0; --fg-soft: #d7ced0; --fg-muted: #a9a1a3; --fg-faint: #847c7f;
    --accent: #c8374f; --on-accent: #ffffff; --accent-fg: #ff97a8; --accent-fg-hover: #ffc0cb;
    --featured: #3b0d1b; --orb: #d6a24e; --sun: #f5d491;
    --sans: Manrope, system-ui, sans-serif; --mono: "Geist Mono", ui-monospace, monospace;
    --ease: cubic-bezier(.2, .8, .2, 1);
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--window); color: var(--fg); font: 15px/1.6 var(--sans); }
  a { color: var(--accent-fg); }
  a:hover { color: var(--accent-fg-hover); }
  main, header, footer { width: min(880px, 100% - 32px); margin-inline: auto; }
  header { display: flex; align-items: center; gap: 12px; padding: 28px 0 20px; }
  header .word { font-weight: 800; font-size: 20px; letter-spacing: -0.01em; }
  header nav { margin-left: auto; }
  header nav a { color: var(--fg-muted); text-decoration: none; font-weight: 600; }
  header nav a:hover { color: var(--fg); }
  main { display: grid; gap: 20px; }
  .hero { position: relative; overflow: hidden; background: var(--featured); border-radius: 24px;
    padding: 36px 32px; }
  .orb { position: absolute; right: -90px; top: -110px; width: 300px; height: 300px;
    border-radius: 50%; background: var(--orb); }
  .orb::after { content: ""; position: absolute; left: 70px; bottom: 60px; width: 64px; height: 64px;
    border-radius: 50%; background: var(--sun); }
  .hero > *:not(.orb) { position: relative; }
  .eyebrow { display: inline-block; margin: 0 0 14px; padding: 4px 12px; border-radius: 999px;
    background: rgb(255 255 255 / 0.1); font-size: 13px; font-weight: 700; }
  h1 { margin: 0; font-size: clamp(34px, 7vw, 52px); line-height: 1.05; font-weight: 800;
    letter-spacing: -0.02em; }
  .lede { margin: 10px 0 0; color: var(--fg-soft); max-width: 34em; }
  .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 22px; }
  .button { display: inline-flex; align-items: center; justify-content: center; min-height: 44px;
    padding: 0 22px; border-radius: 999px; font-weight: 800; text-decoration: none;
    border: 1px solid var(--edge); color: var(--fg); background: var(--glass);
    transition: transform 120ms var(--ease), background 120ms var(--ease); }
  .button:hover { color: var(--fg); background: rgb(255 255 255 / 0.08); }
  .button:active { transform: scale(0.97); }
  .button.primary { background: var(--accent); color: var(--on-accent); border-color: var(--accent); }
  .button.primary:hover { background: #d84a61; color: var(--on-accent); }
  .button.small { min-height: 36px; padding: 0 16px; font-size: 14px; }
  .file { margin: 16px 0 0; display: grid; gap: 2px; font: 12px/1.6 var(--mono); color: var(--fg-muted); }
  .hash { overflow-wrap: anywhere; color: var(--fg-faint); }
  .panel { background: var(--glass); border: 1px solid var(--edge); border-radius: 20px; padding: 24px 28px; }
  h2 { margin: 0 0 6px; font-size: 20px; font-weight: 800; letter-spacing: -0.01em; }
  h3 { margin: 18px 0 4px; font-size: 13px; font-weight: 800; text-transform: uppercase;
    letter-spacing: 0.06em; color: var(--fg-muted); }
  ul { margin: 6px 0 0; padding-left: 20px; }
  li { margin: 4px 0; color: var(--fg-soft); }
  li::marker { color: var(--accent); }
  p { color: var(--fg-soft); }
  code { font: 13px var(--mono); background: rgb(255 255 255 / 0.06); padding: 1px 6px; border-radius: 6px; }
  details { margin-top: 14px; }
  summary { cursor: pointer; font-weight: 700; color: var(--fg); }
  summary:focus-visible, a:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 8px; }
  details li { font-size: 14px; }
  .version { border-top: 1px solid var(--edge); padding-top: 14px; }
  .version summary { display: flex; align-items: baseline; gap: 10px; list-style: none; }
  .version summary::-webkit-details-marker { display: none; }
  .version summary::before { content: ""; width: 7px; height: 7px; border: solid var(--fg-muted);
    border-width: 0 2px 2px 0; transform: rotate(-45deg); transition: transform 200ms var(--ease); }
  .version[open] summary::before { transform: rotate(45deg); }
  .version .date { margin-left: auto; }
  .version .date { color: var(--fg-muted); font: 13px/1.8 var(--mono); }
  .version .body { padding: 4px 0 6px; }
  .table { overflow-x: auto; margin-top: 14px; border: 1px solid var(--edge); border-radius: 16px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  thead tr { background: var(--glass); }
  th, td { padding: 12px 16px; text-align: left; vertical-align: top; }
  th { font-weight: 800; color: var(--fg); }
  td { color: var(--fg-soft); }
  tbody tr { border-top: 1px solid var(--edge); }
  .note { margin: 12px 0 0; font-size: 13px; color: var(--fg-faint); }
  .facts { display: grid; gap: 10px; margin: 8px 0 0; padding: 0; list-style: none; }
  .facts li { color: var(--fg-soft); margin: 0; }
  .facts strong { color: var(--fg); }
  footer { padding: 28px 0 48px; color: var(--fg-faint); font-size: 13px; }
  footer p { color: var(--fg-faint); margin: 4px 0; }
  @media (max-width: 560px) {
    .hero { padding: 28px 22px; }
    .orb { width: 180px; height: 180px; right: -100px; top: -110px; }
    .orb::after { left: 34px; bottom: 34px; width: 40px; height: 40px; }
    .panel { padding: 20px; }
  }
  @media (prefers-reduced-motion: reduce) { .button { transition: none; } }
</style>
</head>
<body>
<header>${LOGO}<span class="word">Maku</span><nav><a href="${repository}">GitHub</a></nav></header>
<main>
${hero(latest, repository)}
${whatsNew}
<section class="panel" aria-labelledby="before">
  <h2 id="before">Before you install</h2>
  <ul class="facts">
    <li><strong>For your own videos.</strong> Maku looks after the series and movies already on your PC and never searches for, downloads or shares video. It isn't for piracy in any form: use it with videos you have the right to keep and watch.</li>
    <li><strong>Windows SmartScreen warns once.</strong> Maku isn't code-signed: choose More info, then Run anyway.</li>
    <li><strong>No admin rights needed.</strong> Maku installs for you alone, keeps its data apart, and never touches your videos.</li>
    <li><strong>It updates itself.</strong> Once installed, Maku offers each new version and shows what changed.</li>
    <li><strong>Nothing is fetched behind your back.</strong> The installer's first page lists everything Maku downloads, such as ffmpeg, and Maku checks each download before using it.</li>
  </ul>
</section>
${needs()}
${previous(older)}
</main>
<footer>
  <p>Maku is free software under the <a href="${repository}/blob/main/LICENSE">MIT licence</a>.
  Each release carries the third-party notices for everything inside it.</p>
  <p>Maku contains no video or artwork and isn't affiliated with TMDB or any show's or film's owners.</p>
</footer>
</body>
</html>
`;
}

async function fetchReleases(repository) {
  const headers = { Accept: "application/vnd.github+json", "User-Agent": "maku-downloads-page" };
  if (process.env.GITHUB_TOKEN) headers.Authorization = `Bearer ${process.env.GITHUB_TOKEN}`;
  const releases = [];
  for (let page = 1; ; page++) {
    const response = await fetch(`https://api.github.com/repos/${repository}/releases?per_page=100&page=${page}`, { headers });
    if (!response.ok) throw new Error(`GitHub answered ${response.status} for ${repository}'s releases.`);
    const batch = await response.json();
    releases.push(...batch);
    if (batch.length < 100) return releases;
  }
}

async function main() {
  const [folder, flag, file] = process.argv.slice(2);
  if (!folder) throw new Error("Usage: node scripts/downloads-page.mjs <folder> [--releases <file>]");
  const repository = process.env.GITHUB_REPOSITORY ?? REPOSITORY;
  const releases = flag === "--releases" ? JSON.parse(readFileSync(file, "utf8")) : await fetchReleases(repository);
  mkdirSync(folder, { recursive: true });
  writeFileSync(join(folder, "index.html"), renderPage(releases, `https://github.com/${repository}`));
  console.log(`Wrote the downloads page with ${versions(releases).length} versions.`);
}

const runDirectly = process.argv[1] && resolve(process.argv[1]).toLowerCase() === fileURLToPath(import.meta.url).toLowerCase();
if (runDirectly) {
  main().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}
