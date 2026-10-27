// Writes the page the installer shows before it installs anything: what Maku downloads to the
// PC (from engine/src/maku/downloads.json, the list the engine follows too) and Maku's licence.
//
//   node scripts/installer-notes.mjs <file>     # pnpm build:installer-notes does this
//
// NSIS shows it as its licence page, in a box that wraps long lines itself, so each paragraph is
// one line. It's plain ASCII with Windows line endings. See docs/releasing.md.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const path = (relative) => fileURLToPath(new URL(`../${relative}`, import.meta.url));

/** The page's text, from the download list and the licence. */
export function beforeYouInstall(downloads, licence) {
  const lines = [
    "BEFORE YOU INSTALL MAKU",
    "",
    "Maku installs for you alone, in your user folder, without admin rights. Its data stays apart in %LOCALAPPDATA%\\Maku. Installing, updating and uninstalling never touch your videos.",
    "",
    "WHAT MAKU DOWNLOADS TO THIS PC",
    "",
    "Maku needs nothing installed by hand except a graphics card driver. Everything else it downloads is listed here, fetched over HTTPS, and checked before it's used.",
    "",
  ];
  downloads.forEach((item, index) => {
    const size = item.size ? `, ${Math.round(item.size / 1e6)} MB` : "";
    const version = item.version === "current" ? "" : ` ${item.version}`;
    lines.push(`${index + 1}. ${item.name}${version}${size}`);
    lines.push(item.purpose);
    lines.push(`Licence: ${item.licence}`);
    if (item.when === "asked") lines.push("Only when you first ask for what needs it.");
    for (const file of item.files?.length ? item.files : [item]) {
      lines.push(`From: ${file.url}`);
      if (file.sha256) lines.push(`SHA-256: ${file.sha256}`);
    }
    lines.push("");
  });
  lines.push(
    "Maku never uploads your files. It only goes online to look up titles, episode lists and artwork (on TMDB, with your own free key), to fetch what's listed above, and to check for updates.",
    "",
    "MAKU'S LICENCE",
    "",
    ...paragraphs(licence),
    "The open-source software inside Maku, each part with its licence, is listed in THIRD-PARTY-NOTICES.txt next to Maku.",
    "",
  );
  const text = lines.join("\r\n");
  const unprintable = [...text].find((character) => character > "~" && character !== "\r");
  if (unprintable) throw new Error(`The installer page can only hold plain ASCII, not "${unprintable}".`);
  return text;
}

/** Each paragraph of a hard-wrapped text as one line, with a blank line after it. */
function paragraphs(text) {
  return text
    .replaceAll("\r\n", "\n")
    .trim()
    .split(/\n\s*\n/)
    .flatMap((paragraph) => [paragraph.split("\n").map((line) => line.trim()).join(" "), ""]);
}

if (process.argv[1]?.toLowerCase().endsWith("installer-notes.mjs")) {
  const target = process.argv[2];
  if (!target) {
    console.error("Usage: node scripts/installer-notes.mjs <file>");
    process.exit(1);
  }
  const { downloads } = JSON.parse(readFileSync(path("engine/src/maku/downloads.json"), "utf8"));
  const page = beforeYouInstall(downloads, readFileSync(path("LICENSE"), "utf8"));
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, page, "utf8");
  console.log(`Wrote the installer's "before you install" page: ${downloads.length} downloads.`);
}
