// Maku's versions and changelog: the rules scripts/release.mjs and the release workflow share.
//
// Versions are semantic (https://semver.org): major.minor.patch, nothing more. Every release must be
// newer than the last one, or installed copies wouldn't see it as an update. CHANGELOG.md keeps
// what changed under "## Unreleased" until a release moves it under "## 1.2.3 - 2026-10-11".
// See docs/releasing.md.

const VERSION = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const HEADING = /^## (.+?)\s*$/;
const RELEASED = /^(\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})$/;

/** [major, minor, patch], or null when the text isn't a version like 1.2.3. */
export function parseVersion(text) {
  const match = VERSION.exec(text);
  return match ? match.slice(1, 4).map(Number) : null;
}

/** Negative when a is older than b, positive when newer, 0 when equal. */
export function compareVersions(a, b) {
  const [x, y] = [parseVersion(a), parseVersion(b)];
  if (!x) throw new Error(`"${a}" isn't a version like 1.2.3.`);
  if (!y) throw new Error(`"${b}" isn't a version like 1.2.3.`);
  for (let part = 0; part < 3; part++) {
    if (x[part] !== y[part]) return x[part] - y[part];
  }
  return 0;
}

/** The version after `current`: "patch", "minor", "major", or an exact newer version. */
export function nextVersion(current, how) {
  const parts = parseVersion(current);
  if (!parts) throw new Error(`The current version "${current}" isn't a version like 1.2.3.`);
  const [major, minor, patch] = parts;
  const steps = {
    major: `${major + 1}.0.0`,
    minor: `${major}.${minor + 1}.0`,
    patch: `${major}.${minor}.${patch + 1}`,
  };
  const next = steps[how] ?? how;
  if (!parseVersion(next)) {
    throw new Error(`"${how}" isn't patch, minor, major or a version like 1.2.3.`);
  }
  if (compareVersions(next, current) <= 0) {
    throw new Error(`${next} isn't newer than ${current}, so installed copies wouldn't update to it.`);
  }
  return next;
}

/** The newest of the given versions, or null. Anything that isn't a version is ignored. */
export function newest(versions) {
  const valid = versions.filter((version) => parseVersion(version));
  return valid.sort(compareVersions).at(-1) ?? null;
}

/** The changelog's "## …" sections in order: { title, version, date, body }. */
export function sections(changelog) {
  const found = [];
  for (const line of changelog.replaceAll("\r\n", "\n").split("\n")) {
    const heading = HEADING.exec(line);
    if (heading) {
      const released = RELEASED.exec(heading[1]);
      found.push({
        title: heading[1],
        version: released ? released[1] : null,
        date: released ? released[2] : null,
        lines: [],
      });
    } else if (found.length) {
      found.at(-1).lines.push(line);
    }
  }
  return found.map(({ lines, ...section }) => ({ ...section, body: lines.join("\n").trim() }));
}

/** What a section lists: its "- " lines, without the dash. */
export function entries(body) {
  return body
    .split("\n")
    .filter((line) => line.startsWith("- "))
    .map((line) => line.slice(2).trim());
}

/** The body of the section for `version` ("Unreleased" works too), or null if there isn't one. */
export function sectionBody(changelog, version) {
  const wanted = version.toLowerCase();
  const section = sections(changelog).find(
    (each) => each.version === version || each.title.toLowerCase() === wanted,
  );
  return section ? section.body : null;
}

/** Moves what's under "## Unreleased" into a new "## <version> - <date>" section below it. */
export function promote(changelog, version, date) {
  const unreleased = sectionBody(changelog, "Unreleased");
  if (unreleased === null) throw new Error('CHANGELOG.md has no "## Unreleased" section.');
  if (!entries(unreleased).length) {
    throw new Error("Nothing is listed under Unreleased in CHANGELOG.md: add what changed first.");
  }
  if (sectionBody(changelog, version) !== null) {
    throw new Error(`CHANGELOG.md already has a section for ${version}.`);
  }
  const text = changelog.replaceAll("\r\n", "\n");
  const start = text.search(/^## Unreleased\s*$/m);
  const bodyStart = text.indexOf("\n", start) + 1;
  const next = text.indexOf("\n## ", bodyStart);
  const end = next === -1 ? text.length : next + 1;
  const released = `## Unreleased\n\n## ${version} - ${date}\n\n${unreleased}\n\n`;
  return `${text.slice(0, start)}${released}${text.slice(end)}`.replace(/\n{3,}/g, "\n\n");
}

/**
 * The GitHub release notes: what the changelog says, then every commit since the previous
 * release, then a link to compare the two.
 */
export function releaseNotes({ version, previous, body, commits, repository }) {
  const lines = [body.trim(), ""];
  if (commits.length) {
    lines.push(previous ? `### Every change since ${previous}` : "### Every change", "");
    for (const { sha, subject } of commits) {
      lines.push(`- ${subject} ([${sha.slice(0, 7)}](${repository}/commit/${sha}))`);
    }
    lines.push("");
  }
  const compare = previous
    ? `${repository}/compare/v${previous}...v${version}`
    : `${repository}/commits/v${version}`;
  lines.push(`**Full changelog**: ${compare}`, "");
  return lines.join("\n");
}

/** True for the commits scripts/release.mjs makes, which the notes leave out. */
export function isReleaseCommit(subject) {
  return /^Release \d+\.\d+\.\d+$/.test(subject);
}
