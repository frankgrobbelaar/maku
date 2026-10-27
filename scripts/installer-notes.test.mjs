// Run with: node --test "scripts/*.test.mjs"
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { beforeYouInstall } from "./installer-notes.mjs";

const read = (relative) => readFileSync(fileURLToPath(new URL(`../${relative}`, import.meta.url)), "utf8");
const { downloads } = JSON.parse(read("engine/src/maku/downloads.json"));
const licence = read("LICENSE");

describe("the installer's page before installing", () => {
  const page = beforeYouInstall(downloads, licence);

  it("lists every download with what it's for, its licence and where it comes from", () => {
    for (const item of downloads) {
      assert.ok(page.includes(item.name), item.name);
      assert.ok(page.includes(`Licence: ${item.licence}`), item.licence);
      for (const file of item.files?.length ? item.files : [item]) {
        assert.ok(page.includes(`From: ${file.url}`), file.url);
        if (file.sha256) assert.ok(page.includes(`SHA-256: ${file.sha256}`), file.sha256);
      }
      assert.ok(page.replaceAll(/\s+/g, " ").includes(item.purpose), item.purpose);
    }
    assert.match(page, /2\. ffmpeg 9\.0\.2, 77 MB\r\n/);
    assert.match(page, /SHA-256: [0-9a-f]{64}/);
  });

  it("lists each file of a download that comes as several, and says when it's fetched", () => {
    assert.match(page, /3\. Whisper medium fp16 d397824, 1531 MB\r\n/);
    assert.match(page, /only when you first ask for what needs it/i);
    assert.equal(page.match(/From: https:\/\/huggingface\.co\//g)?.length, 10);
  });

  it("carries Maku's licence", () => {
    assert.ok(page.includes("Permission is hereby granted, free of charge"));
    assert.ok(page.includes("THIRD-PARTY-NOTICES.txt"));
  });

  it("is plain ASCII with Windows line endings, as the installer needs", () => {
    assert.ok([...page].every((character) => character <= "~" || character === "\r" || character === "\n"));
    assert.ok(!/[^\r]\n/.test(page));
  });

  it("refuses anything the installer couldn't show", () => {
    assert.throws(
      () => beforeYouInstall([{ ...downloads[1], name: "ffmpeg — fast" }], licence),
      /plain ASCII/,
    );
  });
});

describe("the page's layout", () => {
  it("keeps each paragraph on one line, so the installer's box wraps it cleanly", () => {
    const page = beforeYouInstall(downloads, licence);

    assert.ok(page.includes("Installing, updating and uninstalling never touch your videos.\r\n"));
    assert.match(page, /\r\nPermission is hereby granted, free of charge, to any person obtaining a copy of this software/);
  });
});
