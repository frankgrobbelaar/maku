import { describe, expect, it } from "vitest";

// Every source file of the page but the tests, as text.
const sources = import.meta.glob<string>(["../**/*.{ts,tsx}", "!../**/*.test.{ts,tsx}"], {
  query: "?raw",
  import: "default",
  eager: true,
});

// A class that paints with a colour given by value ("bg-[#2449b8]", "bg-[rgb(6_10_28/0.62)]")
// rather than a token: it stays the same whichever scheme is on, light or dark.
const COLOUR_BY_VALUE =
  /\b(?:bg|text|border(?:-[trblxy])?|outline|ring|fill|stroke|from|via|to|decoration|caret|accent|divide|placeholder|shadow)-\[(?:#|(?:rgba?|hsla?|oklch|oklab|lab|lch|hwb|color)\()[^\]]*\]/g;

describe("colours", () => {
  it("finds the page's sources", () => {
    expect(Object.keys(sources)).toContain("../components/shell/notices.tsx");
  });

  it("are every one the scheme's, never given by value", () => {
    const byValue = Object.entries(sources).flatMap(([file, text]) =>
      [...text.matchAll(COLOUR_BY_VALUE)].map(([found]) => `${file}: ${found}`),
    );
    expect(byValue).toEqual([]);
  });
});
