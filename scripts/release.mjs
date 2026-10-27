// Prepares a release on main: picks the next version, moves CHANGELOG.md's Unreleased notes under
// it, sets the version everywhere it lives, commits "Release <version>" and tags it. The Release
// workflow runs it when the owner releases from GitHub; run on a PC, nothing leaves the PC until
// the commit and the tag are pushed, which publishes them.
//
//   node scripts/release.mjs patch      # fixes only: 0.4.2 -> 0.4.3
//   node scripts/release.mjs minor      # new features: 0.4.2 -> 0.5.0
//   node scripts/release.mjs major      # a change you have to act on: 0.4.2 -> 1.0.0
//   node scripts/release.mjs 0.6.0      # an exact version, which must be newer
//
// See docs/releasing.md.
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { compareVersions, newest, nextVersion, promote } from "./versioning.mjs";

const path = (relative) => fileURLToPath(new URL(`../${relative}`, import.meta.url));
const root = { cwd: path("."), encoding: "utf8" };
const git = (...args) => execFileSync("git", args, root).trim();

function fail(message) {
  console.error(message);
  process.exit(1);
}

function replaceIn(file, pattern, replacement) {
  const before = readFileSync(path(file), "utf8");
  const after = before.replace(pattern, replacement);
  if (after === before) throw new Error(`No version found in ${file}`);
  writeFileSync(path(file), after);
}

const how = process.argv[2];
if (!how) fail("Usage: node scripts/release.mjs patch|minor|major|1.2.3");
if (git("branch", "--show-current") !== "main") fail("Release from main.");
if (git("status", "--porcelain")) fail("Commit or put away your changes first: the release commit holds only the release.");

const current = JSON.parse(readFileSync(path("app/package.json"), "utf8")).version;
let version;
try {
  // The version in package.json can go out as it is, once: Maku's first release is 0.1.0.
  const untagged = !git("tag", "--list", `v${current}`);
  version = how === current && untagged ? current : nextVersion(current, how);
} catch (error) {
  fail(error.message);
}
const released = newest(git("tag", "--list", "v*").split("\n").map((tag) => tag.slice(1)));
if (released && compareVersions(version, released) <= 0) {
  fail(`${version} isn't newer than v${released}, which is already tagged.`);
}

const today = new Date().toISOString().slice(0, 10);
try {
  writeFileSync(path("CHANGELOG.md"), promote(readFileSync(path("CHANGELOG.md"), "utf8"), version, today));
} catch (error) {
  fail(error.message);
}
if (version !== current) {
  replaceIn("app/package.json", /"version": "[^"]+"/, `"version": "${version}"`);
  replaceIn("engine/pyproject.toml", /^version = "[^"]+"/m, `version = "${version}"`);
}

const engine = { cwd: path("engine"), stdio: "inherit" };
execFileSync("uv", ["lock"], engine);
execFileSync("uv", ["run", "maku", "openapi", "openapi.json"], engine);

const files = ["CHANGELOG.md", "app/package.json", "engine/pyproject.toml", "engine/uv.lock", "engine/openapi.json"];
git("add", "--", ...files);
git("commit", "--quiet", "-m", `Release ${version}`);
git("tag", "--annotate", `v${version}`, "-m", `Maku ${version}`);

console.log(`\nMaku ${version} is committed and tagged.`);
if (!process.env.GITHUB_ACTIONS) {
  console.log("Publish it, which every installed copy then offers as an update, with:");
  console.log(`  git push --atomic origin main v${version}`);
}
