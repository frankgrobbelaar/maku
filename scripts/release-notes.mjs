// Writes a release's notes for the release workflow, and stops it when the release couldn't
// reach installed copies as an update.
//
//   node scripts/release-notes.mjs <version> <folder>
//
// Writes <folder>/notes.md (the GitHub release: the changelog, every commit since the last
// release, the comparison) and <folder>/update-notes.md (the changelog alone, which latest.json
// carries to the update card). With DRY_RUN=1 it previews: a version without its own changelog
// section shows what's under Unreleased. See docs/releasing.md.
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { compareVersions, isReleaseCommit, parseVersion, releaseNotes, sectionBody } from "./versioning.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));
const git = (...args) => execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();

function fail(message) {
  console.error(`::error::${message}`);
  process.exit(1);
}

const [version, folder] = process.argv.slice(2);
const dryRun = process.env.DRY_RUN === "1";
if (!version || !folder) fail("Usage: node scripts/release-notes.mjs <version> <folder>");
if (!parseVersion(version)) fail(`"${version}" isn't a version like 1.2.3.`);

const changelog = readFileSync(join(root, "CHANGELOG.md"), "utf8");
let body = sectionBody(changelog, version);
if (body === null && dryRun) body = sectionBody(changelog, "Unreleased") ?? "";
if (body === null) {
  fail(`CHANGELOG.md has no "## ${version} - <date>" section. Release with scripts/release.mjs, which writes it.`);
}
if (!body.trim() && !dryRun) fail(`CHANGELOG.md lists nothing for ${version}.`);

const tags = git("tag", "--list", "v*")
  .split("\n")
  .map((tag) => tag.slice(1))
  .filter((tag) => parseVersion(tag) && tag !== version);
const newer = tags.filter((tag) => compareVersions(tag, version) > 0);
if (newer.length && !dryRun) {
  fail(`v${newer.sort(compareVersions).at(-1)} is already out, so ${version} wouldn't reach installed copies as an update.`);
}
const previous = tags.filter((tag) => compareVersions(tag, version) < 0).sort(compareVersions).at(-1) ?? null;

const range = previous ? [`v${previous}..HEAD`] : ["HEAD"];
const commits = git("log", "--format=%H%x09%s", ...range)
  .split("\n")
  .filter(Boolean)
  .map((line) => {
    const [sha, subject] = line.split("\t");
    return { sha, subject };
  })
  .filter(({ subject }) => !isReleaseCommit(subject));

const server = process.env.GITHUB_SERVER_URL ?? "https://github.com";
const repository = `${server}/${process.env.GITHUB_REPOSITORY ?? "frankgrobbelaar/maku"}`;
mkdirSync(folder, { recursive: true });
writeFileSync(join(folder, "notes.md"), releaseNotes({ version, previous, body, commits, repository }));
writeFileSync(join(folder, "update-notes.md"), `${body.trim()}\n`);
console.log(`Notes for ${version}${previous ? ` (since ${previous})` : ""}: ${commits.length} commits.`);
