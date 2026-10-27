import { describe, expect, it } from "vitest";
import { languageName, size } from "./format";

describe("size", () => {
  it("writes sizes the way the boards do", () => {
    expect(size(0)).toBe("0 KB");
    expect(size(200)).toBe("1 KB");
    expect(size(320_400)).toBe("320 KB");
    expect(size(233_000_000)).toBe("233 MB");
    expect(size(1_100_000_000)).toBe("1.1 GB");
    expect(size(8_200_000_000)).toBe("8.2 GB");
    expect(size(16_400_000_000)).toBe("16 GB");
    expect(size(931_000_000_000)).toBe("931 GB");
    expect(size(1_240_000_000_000)).toBe("1.2 TB");
  });
});

describe("languageName", () => {
  it("names a language however a file or Whisper writes it", () => {
    expect(languageName("jpn")).toBe("Japanese");
    expect(languageName("ja")).toBe("Japanese");
    expect(languageName("ger")).toBe("German");
    expect(languageName("english")).toBe("English");
    // Whisper hears languages beyond those Maku names itself.
    expect(languageName("nl")).toBe("Dutch");
    expect(languageName("nld")).toBe("Dutch");
    expect(languageName("sv")).toBe("Swedish");
  });

  it("says when a file doesn't name a track's language", () => {
    expect(languageName("")).toBe("not labelled");
  });
});
