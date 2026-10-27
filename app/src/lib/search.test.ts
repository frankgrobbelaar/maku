import { describe, expect, it } from "vitest";
import { folded, matches } from "./search";

describe("matches", () => {
  it("finds what was typed however it's written", () => {
    expect(matches("starfall", "Starfall Academy")).toBe(true);
    expect(matches("STAR acad", "Starfall Academy")).toBe(true);
    expect(matches("riviere", "La Rivière Noire")).toBe(true);
    expect(matches("starfall ascent", "Starfall: Ascent")).toBe(true);
    expect(matches("ｍｏｏｎ", "Moonlit Harbour")).toBe(true);
  });

  it("wants every word, in any of the texts", () => {
    expect(matches("s02 lantern", "Season 2", "S02E04", "The Lantern Festival")).toBe(true);
    expect(matches("s03 lantern", "S02E04", "The Lantern Festival")).toBe(false);
    expect(matches("harbour", null, undefined, "Moonlit Harbour (2019).mkv")).toBe(true);
  });

  it("finds everything when nothing is typed", () => {
    expect(matches("", "Starfall Academy")).toBe(true);
    expect(matches("  - ", "Starfall Academy")).toBe(true);
  });
});

describe("folded", () => {
  it("keeps letters and numbers of any script", () => {
    expect(folded("星の海 - Episode 01")).toBe("星の海 episode 01");
  });
});
