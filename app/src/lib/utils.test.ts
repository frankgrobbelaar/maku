import { describe, expect, it } from "vitest";
import tokens from "@/styles/tokens.css?raw";
import { cn, fontSizes, radii } from "./utils";

function tokenNames(prefix: string) {
  return [...tokens.matchAll(new RegExp(`--${prefix}-([\\w-]+):`, "g"))]
    .map((match) => match[1])
    .filter((name) => name !== "*");
}

describe("cn", () => {
  it("keeps a Cinema font size next to a Cinema colour", () => {
    expect(cn("text-13", "text-fg-muted")).toBe("text-13 text-fg-muted");
  });

  it("lets the later of two font sizes win", () => {
    expect(cn("text-13", "text-15")).toBe("text-15");
  });

  it("lets the later of two radii win", () => {
    expect(cn("rounded-16", "rounded-22")).toBe("rounded-22");
  });

  it("drops classes that are switched off", () => {
    expect(cn("press", false && "lift", undefined)).toBe("press");
  });

  it("knows every font size and radius in tokens.css", () => {
    expect(fontSizes).toEqual(tokenNames("text"));
    expect(radii).toEqual(tokenNames("radius"));
  });
});
