import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EngineProvider, type EngineStatus, type Scan, type TitleSummary } from "@/lib/engine";
import { fakeEngine, NO_SCAN, NO_TMDB_KEY, READY, TMDB_KEY } from "@/test/engine";
import { ScanPage } from "./scan-page";

const shell = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => {} }));

const FOLDER = {
  id: 1,
  path: "D:\\Videos",
  addedAt: "2026-10-11T09:30:00+00:00",
  available: true,
  files: 2941,
  unread: 937,
  problems: 3,
};
const RUNNING: Scan = {
  ...NO_SCAN,
  state: "running",
  stage: "reading",
  startedAt: "2026-10-11T09:44:00+00:00",
  found: 2941,
  toRead: 2941,
  read: 2004,
  problems: 3,
  current: "D:\\Videos\\Downloads\\Lantern Street\\Season 07\\Lantern Street - 143 [720p].mkv",
  secondsLeft: 240,
};
const DONE: Scan = {
  ...RUNNING,
  state: "done",
  stage: "done",
  read: 2941,
  current: null,
  finishedAt: "2026-10-11T09:49:00+00:00",
};

function engineWith(scan: Scan, titles: TitleSummary[] = [], more: Record<string, unknown> = {}) {
  return fakeEngine({
    "/scan": scan,
    "/folders": [FOLDER],
    "/titles": titles,
    "POST /scan": { ...scan, state: "running" },
    "POST /scan/pause": { ...scan, state: "paused" },
    "POST /scan/resume": { ...scan, state: "running" },
    ...more,
  });
}

function Where() {
  const location = useLocation();
  return <p>{`${location.pathname}${location.search}`}</p>;
}

function renderScan(engine: EngineStatus = READY) {
  shell.invoke.mockImplementation(async (command: string) =>
    command === "engine_status" ? engine : undefined,
  );
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <EngineProvider>
        <MemoryRouter initialEntries={["/scan"]}>
          <Routes>
            <Route path="/scan" element={<ScanPage />} />
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </EngineProvider>
    </QueryClientProvider>,
  );
}

const HARBOUR_LINE: TitleSummary = {
  id: 1,
  kind: "series",
  name: "The Harbour Line",
  year: 2014,
  released: "2014-04-26",
  airing: false,
  hasPoster: false,
  files: 287,
  added: "2026-10-11T09:44:00+00:00",
  aired: 291,
  present: 287,
  missing: 4,
  specialsMissing: 0,
  upcoming: 0,
};
const STARFALL: TitleSummary = {
  ...HARBOUR_LINE,
  id: 2,
  kind: "movie",
  name: "Starfall",
  year: 2001,
  released: "2001-09-01",
  files: 1,
  aired: 0,
  present: 0,
  missing: 0,
};

describe("ScanPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    shell.invoke.mockReset();
  });

  it("shows how far the scan is and what it's reading", async () => {
    renderScan();
    engineWith(RUNNING);

    expect(await screen.findByRole("heading", { name: "Mapping D:\\Videos" })).toBeInTheDocument();
    expect(
      screen.getByText(/about 4 minutes left · nothing is renamed or moved/),
    ).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Files read" })).toHaveAttribute(
      "aria-valuenow",
      "68",
    );
    expect(screen.getByText("2,004 / 2,941")).toBeInTheDocument();
    expect(screen.getByText(RUNNING.current ?? "")).toBeInTheDocument();
    expect(screen.getByText("Read length and quality")).toHaveTextContent(
      "Read length and quality, in progress",
    );
  });

  it("pauses between files and resumes", async () => {
    const fetch = engineWith(RUNNING);
    renderScan();

    (await screen.findByRole("button", { name: "Pause scan" })).click();

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        new URL("http://127.0.0.1:5000/scan/pause"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("names a folder whose drive is unplugged", async () => {
    engineWith({ ...RUNNING, unavailable: ["F:\\More films"] });
    renderScan();

    // The page's own note, once the shapes shown while it loaded have gone.
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "F:\\More films isn't connected. Maku scans it when the drive is back",
      ),
    );
  });

  it("offers ffmpeg when the scan stopped for want of it", async () => {
    engineWith({
      ...NO_SCAN,
      state: "failed",
      stage: "reading",
      startedAt: RUNNING.startedAt,
      found: 3,
      toRead: 3,
      problem: "Maku needs ffmpeg to read the files it found. Download it, then scan again.",
    });
    renderScan();

    expect(await screen.findByRole("alert")).toHaveTextContent("Maku needs ffmpeg");
    screen.getByRole("button", { name: "Get ffmpeg" }).click();

    expect(await screen.findByText("/setup?step=tools")).toBeInTheDocument();
  });

  it("says when the engine couldn't answer, and asks again", async () => {
    let asked = 0;
    fakeEngine({
      "/scan": () => {
        asked += 1;
        return asked === 1 ? new Response("Internal Server Error", { status: 500 }) : RUNNING;
      },
      "/folders": [FOLDER],
    });
    renderScan();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Maku couldn't load this screen. The engine answered 500 to GET /scan. " +
        "Nothing in your folders was touched.",
    );
    screen.getByRole("button", { name: "Try again" }).click();

    expect(await screen.findByRole("heading", { name: "Mapping D:\\Videos" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says when the engine isn't running", async () => {
    engineWith(RUNNING);
    renderScan({ state: "failed", message: "It stopped unexpectedly.", details: "" });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Maku's engine isn't running. It stopped unexpectedly. Nothing in your folders was touched.",
    );
  });

  it("says when it's done and offers to scan again", async () => {
    const fetch = engineWith({ ...DONE, added: 2, gone: 1 });
    renderScan();

    expect(await screen.findByRole("heading", { name: "Mapped D:\\Videos" })).toBeInTheDocument();
    expect(screen.getByText(/· 2 new, 1 gone · finished/)).toBeInTheDocument();
    screen.getByRole("button", { name: "Scan again" }).click();
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        new URL("http://127.0.0.1:5000/scan"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("looks up each series and film after reading, and shows what it found so far", async () => {
    engineWith(
      {
        ...RUNNING,
        stage: "identifying",
        read: 2941,
        current: "The Harbour Line",
        titles: 31,
        waiting: 9,
        mixed: 1,
      },
      [HARBOUR_LINE, STARFALL],
    );
    renderScan();

    expect(await screen.findByText("Identify each series, film and episode")).toHaveTextContent(
      "Identify each series, film and episode, in progress",
    );
    expect(
      screen.getByText("Names, runtimes and numbering, checked against TMDB"),
    ).toBeInTheDocument();
    expect(screen.getByText("Read length and quality")).toHaveTextContent(", done");
    expect(screen.getByText("titles found so far").previousSibling).toHaveTextContent("31");
    expect(screen.getByText("files need a match").previousSibling).toHaveTextContent("9");
    expect(screen.getByText("folder with several titles").previousSibling).toHaveTextContent("1");
    expect(screen.getByText(/looking up each series and film/)).toBeInTheDocument();
    expect(screen.getByText(/Looking up/)).toBeInTheDocument();

    expect(await screen.findByRole("heading", { name: "Found so far" })).toBeInTheDocument();
    expect(screen.getByText("Artwork appears as each title is recognised")).toBeInTheDocument();
    expect(screen.getByText("TV · 287 files")).toBeInTheDocument();
    expect(screen.getByText("Movie · 1 file")).toBeInTheDocument();
  });

  it("offers to match the files it couldn't place, once it's done", async () => {
    engineWith({ ...DONE, titles: 31, waiting: 2 });
    renderScan();

    expect(await screen.findByText("titles found")).toBeInTheDocument();
    screen.getByRole("button", { name: "Match 2 files" }).click();

    expect(await screen.findByText("/match")).toBeInTheDocument();
  });

  it("says what it couldn't do though it finished", async () => {
    engineWith(
      { ...DONE, note: "Titles wait for the next scan: TMDB couldn't be asked (no internet)." },
      [],
      { "/tmdb": TMDB_KEY },
    );
    renderScan();

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Titles wait for the next scan: TMDB couldn't be asked",
      ),
    );
  });

  it("says plainly that it found nothing without a TMDB key, and leads to the key", async () => {
    engineWith(
      { ...DONE, note: "Maku needs your TMDB key to find series and films: add it in Settings." },
      [],
      { "/tmdb": NO_TMDB_KEY },
    );
    renderScan();

    // One notice, the engine's note in it: the way to the key, not the same words twice.
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Maku needs your TMDB key to find your series and films. Your videos are read, and wait for it.",
      ),
    );
    expect(screen.queryByText(/add it in Settings/)).not.toBeInTheDocument();
    screen.getByRole("button", { name: "Add your key" }).click();

    expect(await screen.findByText("/settings/titles")).toBeInTheDocument();
  });
});
