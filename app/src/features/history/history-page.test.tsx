import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EngineProvider, type History, type PlanDone, type SubtitlesDone } from "@/lib/engine";
import { fakeEngine, READY } from "@/test/engine";
import { HistoryPage } from "./history-page";

const shell = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => {} }));

function today(hour: number, minute: number): string {
  const moment = new Date();
  moment.setHours(hour, minute, 0, 0);
  return moment.toISOString();
}

const TIDIED: PlanDone = {
  id: 13,
  kind: "tidy",
  title: "Tidied 30 files: Clockwork Garden, Glass Orchard and 2 more",
  appliedAt: today(11, 40),
  undoneAt: null,
  moved: 29,
  quarantined: 1,
  failed: 0,
  undone: 0,
  deleted: false,
  conversion: null,
  takenAway: 0,
};
const CONVERTED: PlanDone = {
  ...TIDIED,
  id: 14,
  kind: "convert",
  title: "Converted Northwind · S01E03",
  appliedAt: today(14, 20),
  moved: 1,
  quarantined: 1,
  conversion: {
    jobId: 5,
    kind: "convert",
    method: "reencode",
    before: { height: 480, codec: "h264", size: 233_000_000 },
    after: { height: 1080, codec: "hevc", size: 412_000_000 },
    seconds: 3480,
    restored: false,
    replaced: false,
  },
};
const RENAMED: PlanDone = {
  ...TIDIED,
  id: 12,
  title: "Renamed 287 Lantern Street files",
  appliedAt: today(10, 58),
  moved: 287,
  quarantined: 0,
};
const UNDONE: PlanDone = {
  ...TIDIED,
  id: 9,
  title: "Renamed 3 Starfall files",
  appliedAt: "2026-10-08T18:30:00+00:00",
  undoneAt: "2026-10-08T19:02:00+00:00",
  moved: 0,
  quarantined: 0,
  undone: 3,
};
const RENAMED_EARLIER: PlanDone = {
  ...RENAMED,
  id: 8,
  title: "Renamed 12 Northwind files",
  appliedAt: "2026-10-08T17:00:00+00:00",
  moved: 12,
};

/** "2026-10-14": the day a moment fell on, on this PC. */
function localDay(moment: Date): string {
  const month = String(moment.getMonth() + 1).padStart(2, "0");
  const day = String(moment.getDate()).padStart(2, "0");
  return `${moment.getFullYear()}-${month}-${day}`;
}

const HISTORY: History = {
  plans: [TIDIED, RENAMED, UNDONE],
  subtitles: [],
  scans: [
    {
      id: 4,
      startedAt: today(10, 51),
      finishedAt: today(10, 53),
      state: "done",
      problem: null,
      note: null,
      added: 2,
      gone: 1,
    },
  ],
  older: null,
};

function renderHistory(at = "/history") {
  shell.invoke.mockImplementation(async (command: string) =>
    command === "engine_status" ? READY : undefined,
  );
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <EngineProvider>
        <MemoryRouter initialEntries={[at]}>
          <HistoryPage />
        </MemoryRouter>
      </EngineProvider>
    </QueryClientProvider>,
  );
}

describe("HistoryPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    shell.invoke.mockReset();
  });

  it("lists what Maku did by day, newest first", async () => {
    fakeEngine({ "/history": HISTORY });
    renderHistory();

    const todayList = await screen.findByRole("region", { name: "Today" });
    expect(todayList).toHaveTextContent(
      "11:40MovedTidied 30 files: Clockwork Garden, Glass Orchard and 2 more29 files moved · 1 copy set aside · plan 13",
    );
    expect(todayList).toHaveTextContent("10:58RenamedRenamed 287 Lantern Street files");
    expect(todayList).toHaveTextContent(
      "10:51ScannedYour library foldersEvery folder looked at · 2 new, 1 gone",
    );
    expect(screen.getByRole("region", { name: "8 October" })).toHaveTextContent(
      "UndoneRenamed 3 Starfall filesYou put 3 files back",
    );
    expect(screen.getAllByRole("button", { name: "Undo" })).toHaveLength(2);
  });

  it("undoes a tidy-up", async () => {
    const fetch = fakeEngine({
      "/history": HISTORY,
      "POST /plans/13/undo": { planId: 13, moved: 29, quarantined: 1, problems: [] },
    });
    renderHistory();

    (await screen.findAllByRole("button", { name: "Undo" }))[0]?.click();

    await waitFor(() =>
      expect(
        fetch.mock.calls.some(
          ([input, init]) => init?.method === "POST" && String(input).endsWith("/plans/13/undo"),
        ),
      ).toBe(true),
    );
  });

  it("says what was deleted, and puts it back", async () => {
    const deleted: PlanDone = {
      ...TIDIED,
      id: 15,
      title: "Deleted 2 Northwind files",
      moved: 0,
      quarantined: 2,
      deleted: true,
    };
    const fetch = fakeEngine({
      "/history": { plans: [deleted], scans: [], subtitles: [], older: null },
      "POST /plans/15/undo": { planId: 15, moved: 0, quarantined: 2, problems: [] },
    });
    renderHistory();

    const todayList = await screen.findByRole("region", { name: "Today" });
    expect(todayList).toHaveTextContent(
      "11:40Deleted2 Northwind files2 videos in quarantine · plan 15",
    );
    screen.getByRole("button", { name: "Put back what was deleted" }).click();

    await waitFor(() =>
      expect(
        fetch.mock.calls.some(
          ([input, init]) => init?.method === "POST" && String(input).endsWith("/plans/15/undo"),
        ),
      ).toBe(true),
    );
  });

  it("lists the English subtitles Maku made, and takes them away", async () => {
    const made: SubtitlesDone = {
      id: 4,
      title: "The Harbour Line · Season 1",
      quality: "best",
      language: "fre",
      madeAt: today(6, 42),
      made: 37,
      quiet: 1,
      failed: 0,
      waiting: 0,
      present: 37,
    };
    const fetch = fakeEngine({
      "/history": { plans: [], scans: [], subtitles: [made], older: null },
      "POST /subtitles/batches/4/take-away": { planId: 20 },
    });
    renderHistory();

    const todayList = await screen.findByRole("region", { name: "Today" });
    expect(todayList).toHaveTextContent(
      "06:42MadeEnglish subtitles for 37 videosThe Harbour Line · Season 1 · from the French sound · Best · 1 with no one speaking",
    );
    screen.getByRole("button", { name: "Take them away" }).click();

    await waitFor(() =>
      expect(
        fetch.mock.calls.some(
          ([input, init]) =>
            init?.method === "POST" && String(input).endsWith("/subtitles/batches/4/take-away"),
        ),
      ).toBe(true),
    );
  });

  it("puts back the subtitles Maku took away, and shows them under Subtitles", async () => {
    const taken: PlanDone = {
      ...TIDIED,
      id: 20,
      title: "Took away the English subtitles Maku made for The Harbour Line · Season 1",
      moved: 0,
      quarantined: 0,
      takenAway: 37,
    };
    const fetch = fakeEngine({
      "/history": { plans: [taken, TIDIED], scans: [], subtitles: [], older: null },
      "POST /plans/20/undo": { planId: 20, moved: 0, quarantined: 0, problems: [] },
    });
    renderHistory();

    const todayList = await screen.findByRole("region", { name: "Today" });
    expect(todayList).toHaveTextContent(
      "Took awayEnglish subtitles Maku made for The Harbour Line · Season 137 files in quarantine · plan 20",
    );
    screen.getByRole("radio", { name: "Subtitles" }).click();
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Today" })).not.toHaveTextContent("Tidied"),
    );
    screen.getByRole("button", { name: "Put back the subtitles" }).click();

    await waitFor(() =>
      expect(
        fetch.mock.calls.some(
          ([input, init]) => init?.method === "POST" && String(input).endsWith("/plans/20/undo"),
        ),
      ).toBe(true),
    );
  });

  it("keeps Undo for a tidy-up not all put back", async () => {
    const partly: PlanDone = { ...TIDIED, moved: 1, quarantined: 0, undone: 29 };
    fakeEngine({ "/history": { plans: [partly], scans: [], subtitles: [], older: null } });
    renderHistory();

    const todayList = await screen.findByRole("region", { name: "Today" });
    expect(todayList).toHaveTextContent("1 file moved · 29 put back · plan 13");
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("lists each conversion with what it made, and puts an original back", async () => {
    const fetch = fakeEngine({
      "/history": { plans: [CONVERTED, TIDIED], scans: [], subtitles: [], older: null },
      "POST /plans/14/undo": { planId: 14, moved: 1, quarantined: 0, problems: [] },
    });
    renderHistory();

    const todayList = await screen.findByRole("region", { name: "Today" });
    expect(todayList).toHaveTextContent(
      "14:20ConvertedNorthwind · S01E03480p H.264 233 MB → 1080p HEVC 412 MB · 58 min · checked",
    );
    screen.getByRole("button", { name: "Put back the original" }).click();
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(
          ([input, init]) => init?.method === "POST" && String(input).endsWith("/plans/14/undo"),
        ),
      ).toBe(true),
    );

    screen.getByRole("radio", { name: "Conversions" }).click();
    await waitFor(() => expect(screen.queryByText(/Tidied 30 files/)).not.toBeInTheDocument());
    expect(screen.getByText("Northwind · S01E03")).toBeInTheDocument();
  });

  it("lists English added from another copy, and puts both copies back", async () => {
    const merged: PlanDone = {
      ...CONVERTED,
      title: "Added English from another copy to The Harbour Line · S02E07",
      quarantined: 2,
      conversion: CONVERTED.conversion && {
        ...CONVERTED.conversion,
        kind: "merge",
        method: "remux",
      },
    };
    const fetch = fakeEngine({
      "/history": { plans: [merged], scans: [], subtitles: [], older: null },
      "POST /plans/14/undo": { planId: 14, moved: 1, quarantined: 0, problems: [], english: 0 },
    });
    renderHistory();

    const todayList = await screen.findByRole("region", { name: "Today" });
    expect(todayList).toHaveTextContent(
      "14:20AddedEnglish to The Harbour Line · S02E07From its other copy, set aside with it · checked",
    );
    screen.getByRole("button", { name: "Put back both copies" }).click();
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(
          ([input, init]) => init?.method === "POST" && String(input).endsWith("/plans/14/undo"),
        ),
      ).toBe(true),
    );
  });

  it("puts a file's later change back first", async () => {
    const earlier: PlanDone = {
      ...CONVERTED,
      conversion: CONVERTED.conversion && { ...CONVERTED.conversion, replaced: true },
    };
    fakeEngine({ "/history": { plans: [earlier], scans: [], subtitles: [], older: null } });
    renderHistory();

    const todayList = await screen.findByRole("region", { name: "Today" });
    expect(todayList).toHaveTextContent("58 min · checked · changed again since");
    expect(screen.queryByRole("button", { name: "Put back the original" })).not.toBeInTheDocument();
  });

  it("says when a converted file's original is gone, and offers nothing to put back", async () => {
    const gone: PlanDone = { ...CONVERTED, quarantined: 0 }; // deleted, or cleared out
    fakeEngine({ "/history": { plans: [gone], scans: [], subtitles: [], older: null } });
    renderHistory();

    const todayList = await screen.findByRole("region", { name: "Today" });
    expect(todayList).toHaveTextContent(
      "Northwind · S01E03480p H.264 233 MB → 1080p HEVC 412 MB · 58 min · checked · original deleted",
    );
    expect(screen.queryByRole("button", { name: "Put back the original" })).not.toBeInTheDocument();
  });

  it("says when a converted file's original came back", async () => {
    const back: PlanDone = {
      ...CONVERTED,
      undoneAt: today(15, 0),
      conversion: CONVERTED.conversion && { ...CONVERTED.conversion, restored: true },
    };
    fakeEngine({ "/history": { plans: [back], scans: [], subtitles: [], older: null } });
    renderHistory();

    const todayList = await screen.findByRole("region", { name: "Today" });
    expect(todayList).toHaveTextContent(
      "15:00Put backNorthwind · S01E03The original is in its place again",
    );
    expect(screen.queryByRole("button", { name: "Put back the original" })).not.toBeInTheDocument();
  });

  it("shows only scans, or only renames and moves", async () => {
    fakeEngine({ "/history": HISTORY });
    renderHistory();

    (await screen.findByRole("radio", { name: "Scans" })).click();

    await waitFor(() => expect(screen.queryByText(/Tidied 30 files/)).not.toBeInTheDocument());
    expect(screen.getByText("Your library folders")).toBeInTheDocument();
  });

  it("finds what names a title or file, and says when nothing does", async () => {
    const fetch = fakeEngine({
      "/history": (_: unknown, url: URL) => {
        const asked = url.searchParams.get("q");
        if (asked === null) return HISTORY;
        const plans = asked === "northwind" ? [RENAMED_EARLIER] : [];
        return { plans, scans: [], subtitles: [], older: null };
      },
    });
    renderHistory();
    await screen.findByRole("region", { name: "Today" });

    const filter = screen.getByRole("searchbox", { name: "Filter History" });
    expect(filter).toHaveAttribute("placeholder", "Filter by title or file");
    fireEvent.change(filter, { target: { value: "northwind" } });

    await waitFor(() =>
      expect(screen.getByRole("region", { name: "8 October" })).toHaveTextContent(
        "Renamed 12 Northwind files",
      ),
    );
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Today" })).not.toBeInTheDocument(),
    );
    expect(fetch.mock.calls.some(([input]) => String(input).endsWith("/history?q=northwind"))).toBe(
      true,
    );

    fireEvent.change(filter, { target: { value: "Kestrel" } });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Nothing in History goes by “Kestrel”.",
    );
    expect(screen.queryByText("Nothing yet")).not.toBeInTheDocument();
  });

  it("says nothing of an empty search while the next one's days come", async () => {
    const fetch = fakeEngine({
      "/history": (_: unknown, url: URL) =>
        url.searchParams.has("q") ? { plans: [], scans: [], subtitles: [], older: null } : HISTORY,
    });
    const answer = fetch.getMockImplementation();
    // History unfiltered takes a moment to come.
    fetch.mockImplementation(async (input, init) => {
      if (new URL(String(input)).search === "") await new Promise((done) => setTimeout(done, 400));
      return answer ? answer(input, init) : Response.error();
    });
    renderHistory("/history?q=Kestrel");
    expect(await screen.findByText("Nothing in History goes by “Kestrel”.")).toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole("searchbox", { name: "Filter History" }), { key: "Escape" });

    await new Promise((done) => setTimeout(done, 350)); // the filter settled, History on its way
    expect(screen.queryByText("Nothing yet")).not.toBeInTheDocument();
    expect(screen.queryByText(/Nothing in History goes by/)).not.toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Today" })).toBeInTheDocument();
  });

  it("says when there's nothing yet", async () => {
    fakeEngine({ "/history": { plans: [], scans: [], subtitles: [], older: null } });
    renderHistory();

    expect(await screen.findByRole("heading", { name: "Nothing yet" })).toBeInTheDocument();
  });

  it("shows older days on asking, an undo on the day it happened", async () => {
    // Undone today, applied on 8 October: today's page has its undo, the older page the rest.
    const lately: PlanDone = { ...UNDONE, id: 20, undoneAt: today(9, 15) };
    const fetch = fakeEngine({
      "/history": (_init: RequestInit | undefined, url: URL) =>
        url.searchParams.get("before") === null
          ? { plans: [lately], scans: [], subtitles: [], older: localDay(new Date()) }
          : { plans: [lately, RENAMED_EARLIER], scans: [], subtitles: [], older: null },
    });
    renderHistory();

    const todayList = await screen.findByRole("region", { name: "Today" });
    expect(todayList).toHaveTextContent("09:15UndoneRenamed 3 Starfall filesYou put 3 files back");
    expect(screen.queryByRole("region", { name: "8 October" })).not.toBeInTheDocument();

    screen.getByRole("button", { name: "Show older" }).click();

    const older = await screen.findByRole("region", { name: "8 October" });
    expect(older).toHaveTextContent("RenamedRenamed 3 Starfall files");
    expect(older).toHaveTextContent("RenamedRenamed 12 Northwind files");
    expect(screen.queryByRole("button", { name: "Show older" })).not.toBeInTheDocument();
    const asked = fetch.mock.calls.map(([input]) => new URL(String(input)).search);
    expect(asked).toContain(`?before=${localDay(new Date())}`);
  });

  it("names the year of a day in another year, keeping the same day of two years apart", async () => {
    const year = new Date().getFullYear();
    const lastYear: PlanDone = {
      ...RENAMED,
      id: 30,
      title: "Renamed 12 Northwind files",
      appliedAt: new Date(year - 1, 9, 8, 18, 0).toISOString(),
    };
    const before: PlanDone = {
      ...lastYear,
      id: 31,
      appliedAt: new Date(year - 2, 9, 8, 18, 0).toISOString(),
    };
    fakeEngine({
      "/history": { plans: [lastYear, before], scans: [], subtitles: [], older: null },
    });
    renderHistory();

    expect(
      await screen.findByRole("region", { name: `8 October ${year - 1}` }),
    ).toBeInTheDocument();
    expect(screen.getByRole("region", { name: `8 October ${year - 2}` })).toBeInTheDocument();
  });

  it("shows a busy day's first 20, and all of them on asking", async () => {
    const night = Array.from(
      { length: 26 },
      (_, n): PlanDone => ({
        ...CONVERTED,
        id: 100 + n,
        title: `Converted Northwind · S01E${String(n + 1).padStart(2, "0")}`,
        appliedAt: today(1, n),
      }),
    );
    fakeEngine({ "/history": { plans: night, scans: [], subtitles: [], older: null } });
    renderHistory();

    const todayList = await screen.findByRole("region", { name: "Today" });
    expect(todayList.querySelectorAll("li")).toHaveLength(20);

    screen.getByRole("button", { name: "Show all 26" }).click();

    await waitFor(() => expect(todayList.querySelectorAll("li")).toHaveLength(26));
    expect(screen.queryByRole("button", { name: "Show all 26" })).not.toBeInTheDocument();
  });

  it("clears History after asking what to keep", async () => {
    let cleared = false;
    const fetch = fakeEngine({
      "/history": () =>
        cleared ? { plans: [TIDIED], scans: [], subtitles: [], older: null } : HISTORY,
      "POST /history/clear": () => {
        cleared = true;
        return { cleared: 3 };
      },
    });
    renderHistory();

    (await screen.findByRole("button", { name: "Clear History" })).click();
    const asking = await screen.findByRole("group", { name: "Clear History?" });
    expect(asking).toHaveTextContent("What's cleared can't be undone or put back from here.");
    screen.getByRole("radio", { name: "Nothing" }).click();
    await waitFor(() =>
      expect(screen.getByRole("radio", { name: "Nothing" })).toHaveAttribute("data-state", "on"),
    );
    screen.getByRole("button", { name: "Clear all of History" }).click();

    expect(await screen.findByRole("status")).toHaveTextContent(
      "3 entries cleared from History. Your files stay as they are.",
    );
    const sent = fetch.mock.calls.find(([input]) => String(input).endsWith("/history/clear"));
    expect(JSON.parse(String(sent?.[1]?.body))).toEqual({ keep: "nothing" });
    await waitFor(() =>
      expect(screen.queryByText("Renamed 287 Lantern Street files")).not.toBeInTheDocument(),
    );
  });

  it("asks again without clearing on Back", async () => {
    const fetch = fakeEngine({ "/history": HISTORY });
    renderHistory();

    (await screen.findByRole("button", { name: "Clear History" })).click();
    (await screen.findByRole("button", { name: "Back" })).click();

    await waitFor(() =>
      expect(screen.queryByRole("group", { name: "Clear History?" })).not.toBeInTheDocument(),
    );
    expect(fetch.mock.calls.some(([input]) => String(input).endsWith("/history/clear"))).toBe(
      false,
    );
  });
});
