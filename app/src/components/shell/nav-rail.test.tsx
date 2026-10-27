import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import type { Job, ProposedChange, QueueStatus, RunningJob, TidyProposal } from "@/lib/engine";
import { NO_SCAN } from "@/test/engine";
import { badgesOf, NavRail } from "./nav-rail";

const QUEUE: QueueStatus = {
  paused: false,
  schedule: "now",
  waitsForNight: false,
  problem: null,
  running: null,
  queued: [],
  gpuSeconds: 0,
  today: [],
  gpu: null,
  room: null,
  endsAt: null,
  early: false,
};
const NOTHING_TO_TIDY: TidyProposal = {
  changes: [],
  skipped: [],
  duplicates: [],
  waiting: 0,
  broken: 0,
};
const files = (count: number) => Array.from({ length: count }, (_, at) => ({ id: at }) as Job);
const changes = (count: number) => Array.from({ length: count }, () => ({}) as ProposedChange);

/** The tiles lit while `page` is open. */
function litOn(page: string): string[] {
  render(
    <MemoryRouter initialEntries={[page]}>
      <NavRail />
    </MemoryRouter>,
  );
  return screen
    .getAllByRole("link")
    .filter((tile) => tile.getAttribute("aria-current") === "page")
    .map((tile) => tile.textContent ?? "");
}

describe("NavRail", () => {
  it.each([
    ["/", "Home"],
    ["/scan", "Home"],
    ["/franchises/1", "Home"],
    ["/titles/7", "Home"],
    ["/match?title=7", "Home"],
    ["/match", "Tidy up"],
    ["/tidy", "Tidy up"],
    ["/convert", "Convert"],
    ["/convert/queue", "Convert"],
    ["/history", "History"],
    ["/settings/about", "Settings"],
  ])("keeps the place of %s lit: %s", (page, tile) => {
    expect(litOn(page)).toEqual([tile]);
  });
});

describe("badgesOf", () => {
  it("says how far the file converting now has got", () => {
    const running = { frames: 22_000, total: 34_920 } as RunningJob;

    expect(badgesOf({ queue: { ...QUEUE, running, queued: files(3) } })["/convert"]).toEqual({
      text: "63%",
      says: "converting, 63% done",
      waits: false,
    });
  });

  it("says how many files wait to convert while none converts", () => {
    expect(badgesOf({ queue: { ...QUEUE, paused: true, queued: files(3) } })["/convert"]).toEqual({
      text: "3",
      says: "3 files wait to convert",
      waits: false,
    });
  });

  it("adds up the changes and the files to match that wait for the owner in Tidy up", () => {
    const tidy = { ...NOTHING_TO_TIDY, changes: changes(54) };

    expect(badgesOf({ tidy, scan: { ...NO_SCAN, waiting: 2 } })["/tidy"]).toEqual({
      text: "56",
      says: "56 waiting for you",
      waits: true,
    });
  });

  it("keeps a big count short", () => {
    expect(badgesOf({ scan: { ...NO_SCAN, waiting: 1234 } })["/tidy"]?.text).toBe("999+");
  });

  it("puts no badge where nothing goes on", () => {
    expect(badgesOf({ queue: QUEUE, scan: NO_SCAN, tidy: NOTHING_TO_TIDY })).toEqual({});
    expect(badgesOf({})).toEqual({});
  });
});

describe("NavRail badges", () => {
  it("shows each badge over its tile, solid for what waits for you, and says it", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <NavRail
          badges={{
            "/tidy": { text: "56", says: "56 waiting for you", waits: true },
            "/convert": { text: "63%", says: "converting, 63% done", waits: false },
          }}
        />
      </MemoryRouter>,
    );

    const tidy = screen.getByRole("link", { name: "Tidy up, 56 waiting for you" });
    expect(within(tidy).getByText("56").parentElement).toHaveClass("bg-accent");
    const convert = screen.getByRole("link", { name: "Convert, converting, 63% done" });
    expect(within(convert).getByText("63%").parentElement).toHaveClass("bg-accent/18");
    expect(screen.getByRole("link", { name: "History" })).toBeInTheDocument(); // no badge
  });
});
