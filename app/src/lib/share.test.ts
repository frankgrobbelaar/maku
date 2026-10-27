import { describe, expect, it } from "vitest";
import { share } from "./share";

describe("share", () => {
  it("rounds to a whole percent, as the gap analysis does", () => {
    expect(share(287, 291)).toBe(99);
    expect(share(3, 153)).toBe(2);
    expect(share(26, 26)).toBe(100);
  });

  it("never says 100% while an episode is missing, or 0% once one is there", () => {
    expect(share(290, 291)).toBe(99);
    expect(share(1, 300)).toBe(1);
    expect(share(0, 12)).toBe(0);
    expect(share(0, 0)).toBe(0);
  });
});
