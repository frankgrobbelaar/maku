// Run with: node --test scripts/
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  compareVersions,
  entries,
  isReleaseCommit,
  newest,
  nextVersion,
  parseVersion,
  promote,
  releaseNotes,
  sectionBody,
  sections,
} from "./versioning.mjs";

const CHANGELOG = `# Changelog

Every change to Maku you'd notice.

## Unreleased

### Added
- Scanning finds every video in your folders.

### Fixed
- The update card no longer hides behind dialogs.

## 0.1.0 - 2026-10-11

### Added
- Maku's window and its engine.
`;

describe("versions", () => {
  it("reads major.minor.patch and nothing else", () => {
    assert.deepEqual(parseVersion("1.20.3"), [1, 20, 3]);
    for (const wrong of ["1.2", "v1.2.3", "1.2.3-beta.1", "01.2.3", "1.2.3 "]) {
      assert.equal(parseVersion(wrong), null, wrong);
    }
  });

  it("compares numerically, not as text", () => {
    assert.ok(compareVersions("0.10.0", "0.9.9") > 0);
    assert.ok(compareVersions("1.0.0", "1.0.1") < 0);
    assert.equal(compareVersions("2.3.4", "2.3.4"), 0);
  });

  it("steps to the next patch, minor or major version", () => {
    assert.equal(nextVersion("0.4.2", "patch"), "0.4.3");
    assert.equal(nextVersion("0.4.2", "minor"), "0.5.0");
    assert.equal(nextVersion("0.4.2", "major"), "1.0.0");
    assert.equal(nextVersion("0.4.2", "0.6.0"), "0.6.0");
  });

  it("refuses a version that wouldn't reach installed copies as an update", () => {
    assert.throws(() => nextVersion("0.4.2", "0.4.2"), /isn't newer than 0\.4\.2/);
    assert.throws(() => nextVersion("0.4.2", "0.3.9"), /installed copies wouldn't update/);
    assert.throws(() => nextVersion("0.4.2", "soon"), /isn't patch, minor, major/);
  });

  it("finds the newest version, ignoring anything else", () => {
    assert.equal(newest(["0.9.0", "0.10.0", "nightly", "0.2.1"]), "0.10.0");
    assert.equal(newest([]), null);
  });
});

describe("changelog", () => {
  it("splits into sections with their versions and dates", () => {
    const found = sections(CHANGELOG);

    assert.deepEqual(
      found.map(({ title, version, date }) => ({ title, version, date })),
      [
        { title: "Unreleased", version: null, date: null },
        { title: "0.1.0 - 2026-10-11", version: "0.1.0", date: "2026-10-11" },
      ],
    );
    assert.deepEqual(entries(found[0].body), [
      "Scanning finds every video in your folders.",
      "The update card no longer hides behind dialogs.",
    ]);
  });

  it("gives a version's notes, or null when the changelog has none", () => {
    assert.equal(sectionBody(CHANGELOG, "0.1.0"), "### Added\n- Maku's window and its engine.");
    assert.equal(sectionBody(CHANGELOG, "0.2.0"), null);
  });

  it("moves what's unreleased under the new version and starts Unreleased afresh", () => {
    const released = promote(CHANGELOG, "0.2.0", "2026-10-20");

    assert.equal(sectionBody(released, "Unreleased"), "");
    assert.equal(sectionBody(released, "0.2.0"), sectionBody(CHANGELOG, "Unreleased"));
    assert.equal(sectionBody(released, "0.1.0"), sectionBody(CHANGELOG, "0.1.0"));
    assert.deepEqual(
      sections(released).map((section) => section.title),
      ["Unreleased", "0.2.0 - 2026-10-20", "0.1.0 - 2026-10-11"],
    );
    assert.match(released, /^# Changelog\n\nEvery change to Maku you'd notice\.\n\n## Unreleased\n\n## 0\.2\.0/);
  });

  it("won't release with nothing listed, or the same version twice", () => {
    const empty = promote(CHANGELOG, "0.2.0", "2026-10-20");

    assert.throws(() => promote(empty, "0.3.0", "2026-10-21"), /Nothing is listed under Unreleased/);
    assert.throws(() => promote(CHANGELOG, "0.1.0", "2026-10-21"), /already has a section for 0\.1\.0/);
  });

  it("reads a changelog saved with Windows line endings", () => {
    assert.equal(sectionBody(CHANGELOG.replaceAll("\n", "\r\n"), "0.1.0"), "### Added\n- Maku's window and its engine.");
  });
});

describe("release notes", () => {
  const repository = "https://github.com/frankgrobbelaar/maku";

  it("lists the changelog, every commit since the last release, and the comparison", () => {
    const notes = releaseNotes({
      version: "0.2.0",
      previous: "0.1.0",
      body: "### Added\n- Scanning.",
      commits: [{ sha: "0123456789abcdef", subject: "Scan library folders" }],
      repository,
    });

    assert.equal(
      notes,
      [
        "### Added",
        "- Scanning.",
        "",
        "### Every change since 0.1.0",
        "",
        `- Scan library folders ([0123456](${repository}/commit/0123456789abcdef))`,
        "",
        `**Full changelog**: ${repository}/compare/v0.1.0...v0.2.0`,
        "",
      ].join("\n"),
    );
  });

  it("links the first release to its whole history", () => {
    const notes = releaseNotes({ version: "0.1.0", previous: null, body: "- First.", commits: [], repository });

    assert.match(notes, /\*\*Full changelog\*\*: https:\/\/github\.com\/frankgrobbelaar\/maku\/commits\/v0\.1\.0/);
  });

  it("knows the commits the release script makes", () => {
    assert.ok(isReleaseCommit("Release 1.2.3"));
    assert.ok(!isReleaseCommit("Release the scan lock early"));
  });
});
