import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PlayerLayer } from "@/features/player/player";
import { PlayerProvider } from "@/features/player/player-context";
import {
  type Continuing,
  EngineProvider,
  type EngineStatus,
  type Hearable,
  type TitleSummary,
} from "@/lib/engine";
import {
  fakeEngine,
  franchiseOf,
  NO_LIBRARY,
  NO_SCAN,
  NO_TMDB_KEY,
  READY,
  SETTINGS,
  TMDB_KEY,
} from "@/test/engine";
import { HomePage } from "./home-page";

const shell = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => {} }));
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({ setFullscreen: async () => {} }),
}));

const FOLDER = {
  id: 1,
  path: "D:\\Videos",
  addedAt: "2026-10-11T09:30:00+00:00",
  available: true,
  files: 3,
  unread: 0,
  problems: 1,
};

const HARBOUR_LINE: TitleSummary = {
  id: 1,
  kind: "series",
  name: "The Harbour Line",
  year: 2004,
  released: "2004-09-22",
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
const GLASS_ORCHARD: TitleSummary = {
  ...HARBOUR_LINE,
  id: 2,
  name: "Glass Orchard",
  year: 2018,
  released: "2018-04-03",
  files: 26,
  aired: 26,
  present: 26,
  missing: 0,
};
const STARFALL: TitleSummary = {
  ...HARBOUR_LINE,
  id: 3,
  kind: "movie",
  name: "Starfall",
  year: 2014,
  released: "2014-11-07",
  files: 1,
  aired: 0,
  present: 0,
  missing: 0,
};
const STARFALL_II: TitleSummary = {
  ...STARFALL,
  id: 5,
  name: "Starfall II",
  year: 2017,
  released: "2017-05-19",
};
const ASCENT: TitleSummary = {
  ...STARFALL,
  id: 6,
  name: "Starfall: Ascent",
  year: 2021,
  released: "2021-12-17",
};
/** A film on its own, in no collection. */
const NORTHWIND: TitleSummary = {
  ...STARFALL,
  id: 4,
  name: "Northwind",
  year: 2009,
  released: "2009-02-13",
};
const STARFALL_COLLECTION = franchiseOf([STARFALL, STARFALL_II], "The Starfall Collection");

/** The engine's answers for a library that's empty and already set up. */
function engineWith(answers: Record<string, unknown> = {}) {
  return fakeEngine({
    "/settings": SETTINGS,
    "/folders": [],
    "/library": NO_LIBRARY,
    "/scan": NO_SCAN,
    "/franchises": [],
    "/recovery": () => Response.json(null),
    ...answers,
  });
}

function sent(fetch: ReturnType<typeof fakeEngine>, method: string, path: string) {
  return fetch.mock.calls.filter(
    ([input, init]) =>
      (init?.method ?? "GET") === method && new URL(String(input)).pathname === path,
  );
}

function renderHome(engine: EngineStatus) {
  shell.invoke.mockImplementation(async (command: string) =>
    command === "engine_status" ? engine : undefined,
  );
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <EngineProvider>
        <PlayerProvider>
          <MemoryRouter>
            <Routes>
              <Route index element={<HomePage />} />
              <Route path="/setup" element={<p>Setup</p>} />
              <Route path="/scan" element={<p>Scan</p>} />
              <Route path="/match" element={<p>Match</p>} />
              <Route path="/titles/:id" element={<p>A title</p>} />
              <Route path="/franchises/:id" element={<p>A collection</p>} />
              <Route path="/history" element={<p>History</p>} />
              <Route path="/subtitles" element={<p>Making subtitles</p>} />
              <Route path="/settings/:section" element={<p>Settings</p>} />
            </Routes>
          </MemoryRouter>
          <PlayerLayer />
        </PlayerProvider>
      </EngineProvider>
    </QueryClientProvider>,
  );
}

describe("HomePage", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    shell.invoke.mockReset();
  });

  it("shows an empty shelf once the engine runs, and only the library", async () => {
    engineWith();
    renderHome(READY);

    expect(await screen.findByRole("heading", { name: "Your shelf is empty" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Add a folder with series or films in it. Any layout, even everything in one folder.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a folder" })).toBeEnabled();
    // What this copy of Maku is up to is in Settings › About.
    expect(screen.queryByRole("heading", { name: "This copy of Maku" })).not.toBeInTheDocument();
  });

  it("adds a folder from the empty shelf and scans it, setup being done", async () => {
    const fetch = engineWith({
      "POST /folders": { ...FOLDER, files: 0, problems: 0 },
      "POST /scan": { ...NO_SCAN, state: "running", stage: "finding" },
    });
    renderHome(READY);
    shell.invoke.mockImplementation(async (command: string) =>
      command === "engine_status" ? READY : command === "pick_folder" ? "D:\\Videos" : undefined,
    );

    (await screen.findByRole("button", { name: "Add a folder" })).click();

    expect(await screen.findByText("Scan")).toBeInTheDocument();
    const [[, added]] = sent(fetch, "POST", "/folders") as [[unknown, RequestInit]];
    expect(JSON.parse(String(added.body))).toEqual({ path: "D:\\Videos" });
    expect(sent(fetch, "POST", "/scan")).toHaveLength(1);
  });

  it("says Maku needs the TMDB key to find anything, and leads to where it goes", async () => {
    engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 3, size: 407_000_000, sd: 3 },
      "/scan": { ...NO_SCAN, state: "done", stage: "done", found: 3, toRead: 3, read: 3 },
      "/tmdb": NO_TMDB_KEY,
    });
    renderHome(READY);

    const said = await screen.findByText("Maku needs your TMDB key to find your series and films.");
    const notice = said.closest("[role=status]") as HTMLElement;
    expect(notice).toHaveTextContent(
      "Maku needs your TMDB key to find your series and films. Your videos are read, and wait for it.",
    );
    // Up top, before the summary of the library.
    const pictures = await screen.findByRole("heading", { name: "Your videos by picture" });
    expect(
      notice.compareDocumentPosition(pictures) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    within(notice).getByRole("button", { name: "Add your key" }).click();
    expect(await screen.findByText("Settings")).toBeInTheDocument();
  });

  it.each<[string, Record<string, unknown>]>([
    ["once Maku has one", { "/tmdb": TMDB_KEY }],
    ["while Maku can't tell whether it has one", {}], // the engine didn't answer
  ])("says nothing of the key %s", async (_, answers) => {
    const fetch = engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 3, size: 407_000_000, sd: 3 },
      ...answers,
    });
    renderHome(READY);

    expect(await screen.findByRole("heading", { name: "Your videos by picture" })).toBeVisible();
    await waitFor(() => expect(sent(fetch, "GET", "/tmdb")).toHaveLength(1));
    expect(screen.queryByText(/TMDB key/)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // nor a problem of it
  });

  it("says what Maku settled after it closed unexpectedly, till it's seen", async () => {
    const at = new Date().toISOString();
    const fetch = engineWith({
      "/recovery": () => Response.json({ at, restarted: 1, finished: 0, putBack: 0, moves: 0 }),
      "POST /recovery/seen": null,
    });
    renderHome(READY);

    const said = await screen.findByText("Maku closed unexpectedly.");
    expect(said.closest("[role=status]")).toHaveTextContent(
      "Maku closed unexpectedly. One file was restarted from the beginning; the original was " +
        "never touched and nothing was lost.",
    );
    screen.getByRole("button", { name: "See what happened" }).click();
    await waitFor(() => expect(sent(fetch, "POST", "/recovery/seen")).toHaveLength(1));
    expect(await screen.findByText("History")).toBeInTheDocument();
  });

  it("words all that a crash left in one sentence", async () => {
    const at = new Date().toISOString();
    engineWith({
      "/recovery": () => Response.json({ at, restarted: 2, finished: 1, putBack: 0, moves: 3 }),
    });
    renderHome(READY);

    const said = await screen.findByText("Maku closed unexpectedly.");
    expect(said.closest("[role=status]")).toHaveTextContent(
      "Maku closed unexpectedly. 2 files were restarted from the beginning, one converted file " +
        "went into its original's place and 3 file moves were settled; nothing was lost.",
    );
  });

  it("opens setup on the very first run", async () => {
    engineWith({ "/settings": { ...SETTINGS, setUp: false } });
    renderHome(READY);

    expect(await screen.findByText("Setup")).toBeInTheDocument();
  });

  it("shows the library by picture size once a scan has read it", async () => {
    engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 3, size: 407_000_000, sd: 3, problems: 1 },
      "/scan": { ...NO_SCAN, state: "done", stage: "done", found: 3, toRead: 3, read: 3 },
    });
    renderHome(READY);

    const pictures = await screen.findByRole("heading", { name: "Your videos by picture" });
    expect(screen.getByText("3 videos · 0.4 GB · 1 folder")).toBeInTheDocument();
    expect(screen.getByText("1 file couldn't be read.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Scan again" })).toBeEnabled();
    expect(screen.getByText("100%")).toBeInTheDocument(); // every one of them SD
    // A summary at the top, before what needs the owner (and the shelf after that).
    const attention = await screen.findByRole("heading", { name: "Needs your attention" });
    expect(
      pictures.compareDocumentPosition(attention) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it.each([
    ["4k", "kept at its size, up to 4K"],
    ["1080p", "brought down to 1080p"],
  ] as const)("says what a %s standard does to what's over 1080p", async (standard, said) => {
    engineWith({
      "/settings": { ...SETTINGS, standard },
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 4, size: 9e10, hd1080: 2, larger: 2 },
      "/scan": { ...NO_SCAN, state: "done", stage: "done", found: 4, toRead: 4, read: 4 },
    });
    renderHome(READY);

    // 1440p, 4K and 8K alike, HDR or not: the tile can't know which each file is.
    const pictures = await screen.findByRole("region", { name: "Your videos by picture" });
    const tiles = () => within(pictures).getAllByRole("listitem");
    await waitFor(() =>
      expect(tiles().map((tile) => tile.textContent)).toEqual([
        "SD0%0kept at its size",
        "720p0%0kept at its size",
        "1080p50%2kept at 1080p",
        `Larger50%2${said}`,
      ]),
    );
  });

  it("goes on with what was being watched, and leaves a title out when asked", async () => {
    const stopped: Continuing = {
      titleId: 2,
      title: "Glass Orchard",
      kind: "series",
      hasPoster: false,
      playedAt: "2026-10-18T10:00:00+00:00",
      upNext: false,
      video: {
        fileId: 12,
        season: 1,
        episode: 2,
        episodeEnd: null,
        name: "The Night Ferry",
        path: "D:\\Videos\\Glass Orchard\\S01E02.mkv",
        duration: 1440,
        resume: 600,
      },
      following: [
        {
          fileId: 13,
          season: 1,
          episode: 3,
          episodeEnd: null,
          name: "Low Tide",
          path: "D:\\Videos\\Glass Orchard\\S01E03.mkv",
          duration: 1440,
          resume: null,
        },
      ],
    };
    const next: Continuing = {
      ...stopped,
      titleId: 3,
      title: "Starfall",
      kind: "movie",
      upNext: true,
      video: { ...stopped.video, fileId: 20, season: null, episode: null, resume: null },
      following: [],
    };
    let going = [stopped, next];
    const fetch = engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 3, size: 407_000_000, sd: 3 },
      "/continue": () => going,
      "DELETE /continue/3": () => {
        going = [stopped];
        return null;
      },
      "POST /player": {
        ticket: "T1",
        missing: null,
        drive: "D:",
        duration: 1440,
        sound: [],
        subtitles: [],
        chapters: [],
        chosenSound: null,
        chosenSubtitles: null,
        ready: [],
      },
    });
    renderHome(READY);

    const shelf = await screen.findByRole("region", { name: "Continue watching" });
    const [first, second] = within(shelf).getAllByRole("listitem") as [HTMLElement, HTMLElement];
    expect(first).toHaveTextContent("Glass Orchard");
    expect(first).toHaveTextContent("S01E02 · The Night Ferry");
    expect(first).toHaveTextContent("14 min left");
    expect(second).toHaveTextContent("The film");
    expect(second).toHaveTextContent("Up next");
    // After the summary of the library at the top.
    const pictures = await screen.findByRole("heading", { name: "Your videos by picture" });
    expect(pictures.compareDocumentPosition(shelf) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    within(first).getByRole("button", { name: "Play Glass Orchard · S01E02" }).click();
    const player = await screen.findByRole("region", { name: "Player" });
    expect(player).toHaveTextContent("Glass Orchard · S01E02");
    const video = player.querySelector("video") as HTMLVideoElement;
    await waitFor(() => expect(video.getAttribute("src")).toContain("at=600.000"));
    fireEvent(video, new Event("playing"));
    expect(await within(player).findByRole("button", { name: "Next episode" })).toBeInTheDocument();
    const [[, opened]] = sent(fetch, "POST", "/player") as [[unknown, RequestInit]];
    expect(JSON.parse(String(opened.body))).toEqual({ file: 12 });

    fireEvent.keyDown(within(second).getByRole("button", { name: "More for Starfall" }), {
      key: "Enter",
    });
    (await screen.findByRole("menuitem", { name: "Remove from Continue watching" })).click();
    await waitFor(() => expect(within(shelf).getAllByRole("listitem")).toHaveLength(1));
    expect(sent(fetch, "DELETE", "/continue/3")).toHaveLength(1);
  });

  it("lists the videos the health check didn't play, and takes the owner's word on each", async () => {
    const unplayed = (fileId: number, episode: number) => ({
      fileId,
      path: `D:\\Videos\\Glass Orchard\\S01E0${episode}.mkv`,
      titleId: 2,
      title: "Glass Orchard",
      season: 1,
      episode,
      episodeEnd: null,
      problem: "It didn't play at 12:05 (Invalid data found when processing input)",
      at: "2026-10-18T01:30:00+02:00",
    });
    const fetch = engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 3, size: 407_000_000, sd: 3 },
      "/scan": { ...NO_SCAN, state: "done", stage: "done", found: 3, toRead: 3, read: 3 },
      "/checkup": { on: true, checked: 3, total: 3, unplayed: [unplayed(4, 4), unplayed(5, 5)] },
      "POST /files/4/check": { problem: null },
      "POST /files/5/broken": null,
    });
    renderHome(READY);

    (await screen.findByRole("button", { name: /2 videos didn't play/ })).click();

    const card = await screen.findByRole("dialog", { name: "Videos that didn't play" });
    const [first, second] = within(card).getAllByRole("listitem") as [HTMLElement, HTMLElement];
    expect(first).toHaveTextContent("Glass Orchard · S01E04");
    expect(first).toHaveTextContent("It didn't play at 12:05");
    within(first).getByRole("button", { name: "Try again" }).click();
    expect(
      await within(card).findByText(
        "Glass Orchard · S01E04 played this time, so it's off the list.",
      ),
    ).toBeInTheDocument();
    fireEvent.keyDown(
      within(second).getByRole("button", { name: "More for Glass Orchard · S01E05" }),
      {
        key: "Enter",
      },
    );
    (await screen.findByRole("menuitem", { name: "Mark as broken" })).click();
    await waitFor(() => expect(sent(fetch, "POST", "/files/5/broken")).toHaveLength(1));
  });

  it("says the library at a glance, and what takes the most room", async () => {
    engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 3, size: 407_000_000, sd: 3 },
      "/library/glance": {
        seconds: 1240 * 3600,
        watched: 86 * 3600,
        converted: { files: 412, before: 380_000_000_000, after: 290_000_000_000 },
        biggest: [
          { titleId: 1, name: "The Harbour Line", files: 239, size: 24_100_000_000 },
          { titleId: 2, name: "Lantern Street", files: 24, size: 9_800_000_000 },
        ],
        size: 61_000_000_000,
      },
    });
    renderHome(READY);

    const glance = await screen.findByRole("region", { name: "At a glance" });
    expect(glance).toHaveTextContent("To watch1,240 hoursof series and films, end to end");
    expect(glance).toHaveTextContent("Watched86 hours7% of it");
    expect(glance).toHaveTextContent("Converting saved90 GB412 files: 380 GB → 290 GB");
    expect(glance).toHaveTextContent(
      "The most room61 GB in allThe Harbour Line24 GBLantern Street9.8 GB",
    );
    expect(within(glance).getByRole("link", { name: "The Harbour Line" })).toHaveAttribute(
      "href",
      "/titles/1",
    );
  });

  it("lists each show's next episode still to come, the soonest first", async () => {
    const day = (from: number) => {
      const when = new Date();
      when.setDate(when.getDate() + from);
      return `${when.getFullYear()}-${String(when.getMonth() + 1).padStart(2, "0")}-${String(
        when.getDate(),
      ).padStart(2, "0")}`;
    };
    const next = (titleId: number, title: string, from: number, later = 0) => ({
      titleId,
      title,
      kind: "series",
      hasPoster: false,
      season: 1,
      number: 5,
      name: "The Café at Dawn",
      aired: day(from),
      later,
    });
    engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 3, size: 407_000_000, sd: 3 },
      "/coming": [
        next(1, "The Harbour Line", 0, 7),
        next(2, "Lantern Street", 1),
        ...[3, 4, 5, 6, 7].map((id) => next(id, `Show ${id}`, 9)),
      ],
    });
    renderHome(READY);

    const coming = await screen.findByRole("region", { name: "Coming up" });
    const rows = within(coming).getAllByRole("listitem");
    expect(rows).toHaveLength(5);
    expect(rows[0]).toHaveTextContent(
      /^Today.*The Harbour LineS01E05 · The Café at Dawn7 more listed$/,
    );
    expect(rows[1]).toHaveTextContent("Tomorrow");
    expect(within(rows[0] as HTMLElement).getByRole("link")).toHaveAttribute("href", "/titles/1");
    within(coming).getByRole("button", { name: "Show all 7" }).click();
    await waitFor(() => expect(within(coming).getAllByRole("listitem")).toHaveLength(7));
  });

  it("says what the videos can be heard and read in, and leads to making English subtitles", async () => {
    const heard = (id: number, more: Partial<Hearable> = {}): Hearable => ({
      fileId: id,
      label: `Glass Orchard · S01E0${id}`,
      titleId: 1,
      title: "Glass Orchard",
      season: 1,
      episode: id,
      seconds: 1440,
      sound: ["fra"],
      subtitles: [],
      english: false,
      made: false,
      waiting: false,
      ...more,
    });
    engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 4, size: 4e9, hd1080: 4 },
      "/scan": { ...NO_SCAN, state: "done", stage: "done", found: 4, toRead: 4, read: 4 },
      "/subtitles": {
        files: [
          heard(1, { sound: ["fra", "eng"], english: true }),
          heard(2, { subtitles: ["en"], english: true, made: true }),
          heard(3),
          heard(4, { titleId: 2, title: "Lantern Street" }),
        ],
        rates: { best: 0.4, fast: 0.15 },
      },
    });
    renderHome(READY);

    const languages = await screen.findByRole("region", { name: "Your videos by language" });
    const tiles = within(languages).getAllByRole("listitem");
    expect(tiles.map((tile) => tile.textContent)).toEqual([
      "English sound25%1in the files",
      "English subtitles25%11 of them made by Maku",
      "No English50%2neither sound nor subtitles",
    ]);
    const card = await screen.findByRole("button", { name: /2 videos have no English/ });
    expect(card).toHaveTextContent(
      "Across 2 titles · Maku can make English subtitles from their sound",
    );
    card.click();
    expect(await screen.findByText("Making subtitles")).toBeInTheDocument();
  });

  it("says across one title when the videos without English are all one's", async () => {
    const video = (id: number): Hearable => ({
      fileId: id,
      label: `Lantern Street · S01E0${id}`,
      titleId: 2,
      title: "Lantern Street",
      season: 1,
      episode: id,
      seconds: 1440,
      sound: ["fra"],
      subtitles: [],
      english: false,
      made: false,
      waiting: false,
    });
    engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 2, size: 2e9, hd1080: 2 },
      "/scan": { ...NO_SCAN, state: "done", stage: "done", found: 2, toRead: 2, read: 2 },
      "/subtitles": { files: [video(1), video(2)], rates: { best: 0.4, fast: 0.15 } },
    });
    renderHome(READY);

    expect(
      await screen.findByText("Across 1 title · Maku can make English subtitles from their sound"),
    ).toBeInTheDocument();
  });

  it("says only when a scan ran, for a scan from before Maku counted what changed", async () => {
    engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 3, size: 407_000_000, sd: 1, hd720: 1 },
      "/scan": { ...NO_SCAN, state: "done", stage: "done", finishedAt: new Date().toISOString() },
    });
    renderHome(READY);

    expect(await screen.findByText(/^Scanned today \d\d:\d\d$/)).toBeInTheDocument();
    // Shares that add up: a third each of three would read 33% three times.
    expect(screen.getAllByText(/^\d+%$/).map((share) => share.textContent)).toEqual([
      "50%",
      "50%",
      "0%",
      "0%",
    ]);
  });

  it("catches up after a scan too quick to be seen running, and says what it found", async () => {
    let scans = 0;
    const finishedAt = new Date().toISOString();
    engineWith({
      "/folders": [FOLDER],
      "/franchises": [franchiseOf([HARBOUR_LINE])],
      "/library": () => ({
        ...NO_LIBRARY,
        folders: 1,
        files: scans > 1 ? 2 : 3,
        size: 407_000_000,
        sd: scans > 1 ? 2 : 3,
      }),
      "/scan": () => {
        scans += 1; // the second look finds another scan done: a video was removed meanwhile
        return {
          ...NO_SCAN,
          state: "done",
          stage: "done",
          startedAt: scans > 1 ? "2026-10-13T13:07:22Z" : "2026-10-13T13:06:16Z",
          finishedAt,
          found: scans > 1 ? 2 : 3,
          added: 0,
          gone: scans > 1 ? 1 : 0,
        };
      },
    });
    renderHome(READY);

    expect(await screen.findByText("1 series · 3 videos · 0.4 GB · 1 folder")).toBeInTheDocument();
    expect(
      await screen.findByText("1 series · 2 videos · 0.4 GB · 1 folder", undefined, {
        timeout: 6000,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/^Scanned today \d\d:\d\d · 1 gone$/)).toBeInTheDocument();
  }, 10_000);

  it("leaves out adding a folder while a scan runs", async () => {
    engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 3, size: 407_000_000, sd: 3 },
      "/scan": { ...NO_SCAN, state: "running", stage: "reading", found: 3, toRead: 3, read: 1 },
    });
    renderHome(READY);

    expect(
      await screen.findByRole("button", { name: "Scanning… see progress" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a folder" })).not.toBeInTheDocument();
  });

  it("catches up with the library when the scan finishes", async () => {
    let asked = 0;
    let finished = false;
    engineWith({
      "/folders": [FOLDER],
      "/library": () => ({
        ...NO_LIBRARY,
        folders: 1,
        files: finished ? 3 : 1,
        size: 407_000_000,
        sd: finished ? 3 : 1,
      }),
      "/scan": () => {
        asked += 1;
        finished = asked > 1;
        return finished
          ? { ...NO_SCAN, state: "done", stage: "done", found: 3, toRead: 3, read: 3 }
          : { ...NO_SCAN, state: "running", stage: "reading", found: 3, toRead: 3, read: 1 };
      },
    });
    renderHome(READY);

    expect(await screen.findByText("1 video · 0.4 GB · 1 folder")).toBeInTheDocument();
    // The scan is asked again a second later, finds it done, and the library is asked again.
    expect(
      await screen.findByText("3 videos · 0.4 GB · 1 folder", undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("notices a scan Maku started on its own", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let started = false;
    engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 3, size: 407_000_000, sd: 3 },
      "/scan": () =>
        started
          ? { ...NO_SCAN, state: "running", stage: "finding", found: 3 }
          : { ...NO_SCAN, state: "done", stage: "done", found: 3, toRead: 3, read: 3 },
    });
    renderHome(READY);
    expect(await screen.findByRole("button", { name: "Scan again" })).toBeInTheDocument();

    started = true; // a new video arrived, and the watcher started a scan
    await act(() => vi.advanceTimersByTimeAsync(10_000));

    expect(
      await screen.findByRole("button", { name: "Scanning… see progress" }),
    ).toBeInTheDocument();
  });

  it("says when the engine couldn't answer, and asks again", async () => {
    let asked = 0;
    engineWith({
      "/folders": () => {
        asked += 1;
        return asked === 1
          ? Response.json({ detail: "The database is locked." }, { status: 503 })
          : [FOLDER];
      },
      "/library": { ...NO_LIBRARY, folders: 1, files: 3, size: 407_000_000, sd: 3 },
    });
    renderHome(READY);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Maku couldn't load this screen. The database is locked. Nothing in your folders was touched.",
    );
    screen.getByRole("button", { name: "Try again" }).click();

    expect(
      await screen.findByRole("heading", { name: "Your videos by picture" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says when the engine isn't running, and offers to try again", async () => {
    engineWith();
    renderHome({ state: "failed", message: "It stopped unexpectedly.", details: "Traceback…" });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Maku's engine isn't running. It stopped unexpectedly.");
    expect(alert).toHaveTextContent("Nothing in your folders was touched.");

    screen.getByRole("button", { name: "Try again" }).click();

    expect(shell.invoke).toHaveBeenCalledWith("restart_engine");
  });

  it("offers the engine's error lines only when there are some", async () => {
    engineWith();
    renderHome({ state: "failed", message: "It stopped unexpectedly.", details: "" });

    await screen.findByRole("alert");

    expect(screen.queryByRole("button", { name: "Copy details" })).not.toBeInTheDocument();
  });

  it("lists the series and films oldest release first, each saying what it is", async () => {
    const fetch = engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 314, size: 9e10 },
      "/scan": { ...NO_SCAN, state: "done", stage: "done" },
      "/franchises": [
        franchiseOf([HARBOUR_LINE]),
        STARFALL_COLLECTION,
        franchiseOf([GLASS_ORCHARD]),
      ],
    });
    renderHome(READY);

    expect(await screen.findByRole("heading", { name: "Series and films" })).toBeInTheDocument();
    expect(screen.getByText("3 on the shelf · by type, oldest release first")).toBeInTheDocument();
    expect(screen.getByText("TV series · 2004 · 291 episodes")).toBeInTheDocument();
    expect(screen.getByText("4 missing")).toBeInTheDocument();
    expect(screen.getByText("287 of 291 · 99%")).toBeInTheDocument();
    expect(screen.getByText("TV series · 2018 · 26 episodes")).toBeInTheDocument();
    expect(screen.getByText("26 of 26 · complete")).toBeInTheDocument();
    expect(screen.getByText("Collection · 2 movies")).toBeInTheDocument();
    // The titles by kind, a collection's films each counted.
    expect(
      screen.getByText("2 series · 2 movies · 314 videos · 90.0 GB · 1 folder"),
    ).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Release date" })).toBeChecked();
    expect(
      fetch.mock.calls.some(([input]) => String(input).endsWith("/franchises?sort=released")),
    ).toBe(true);

    screen.getByRole("radio", { name: "Name" }).click();
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([input]) => String(input).endsWith("/franchises?sort=name")),
      ).toBe(true),
    );

    (await screen.findByRole("link", { name: /The Starfall Collection/ })).click();
    expect(await screen.findByText("A collection")).toBeInTheDocument();
  });

  it("lists collections first, then what stands on its own, by type", async () => {
    engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 314, size: 9e10 },
      "/scan": { ...NO_SCAN, state: "done", stage: "done" },
      "/franchises": [franchiseOf([NORTHWIND]), STARFALL_COLLECTION, franchiseOf([GLASS_ORCHARD])],
    });
    renderHome(READY);

    const [collections, series, movies] = await screen.findAllByRole("heading", { level: 3 });

    expect([collections, series, movies].map((heading) => heading?.textContent)).toEqual([
      "Collections 1",
      "Series 1",
      "Movies 1",
    ]);
  });

  it("finds a collection by its name or any of its films', and says when nothing is", async () => {
    engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 314, size: 9e10 },
      "/scan": { ...NO_SCAN, state: "done", stage: "done" },
      "/franchises": [
        franchiseOf([STARFALL, ASCENT], "The Starfall Collection"),
        franchiseOf([GLASS_ORCHARD]),
      ],
    });
    renderHome(READY);

    const search = await screen.findByRole("searchbox", { name: "Search the shelf" });
    expect(search).toHaveAttribute("placeholder", "Search the shelf");
    fireEvent.change(search, { target: { value: "ascent" } });

    expect(
      await screen.findByText("1 of 2 on the shelf · by type, oldest release first"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /The Starfall Collection/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Glass Orchard/ })).not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: "Lantern " } });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Nothing on the shelf goes by “Lantern”.",
    );

    fireEvent.keyDown(search, { key: "Escape" });
    expect(
      await screen.findByText("2 on the shelf · by type, oldest release first"),
    ).toBeInTheDocument();
    expect(search).toHaveValue("");
  });

  it("leads a title on its own to its page", async () => {
    engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 287, size: 9e10 },
      "/scan": { ...NO_SCAN, state: "done", stage: "done" },
      "/franchises": [franchiseOf([HARBOUR_LINE])],
    });
    renderHome(READY);

    (await screen.findByRole("link", { name: /The Harbour Line/ })).click();

    expect(await screen.findByText("A title")).toBeInTheDocument();
  });

  it("says what needs attention, and leads to it", async () => {
    engineWith({
      "/folders": [FOLDER],
      "/library": { ...NO_LIBRARY, folders: 1, files: 314, problems: 9 },
      "/scan": { ...NO_SCAN, state: "done", stage: "done", waiting: 12, mixed: 1 },
      "/franchises": [franchiseOf([HARBOUR_LINE]), franchiseOf([GLASS_ORCHARD])],
    });
    renderHome(READY);

    expect(await screen.findByText("12 files need a match")).toBeInTheDocument();
    expect(
      screen.getByText("Maku couldn't tell which series or film they are"),
    ).toBeInTheDocument();
    expect(screen.getByText("4 episodes missing")).toBeInTheDocument();
    expect(screen.getByText("Across 1 series · gap reports updated")).toBeInTheDocument();
    expect(screen.getByText("9 files won't play")).toBeInTheDocument();
    expect(screen.getByText("1 folder holds several titles")).toBeInTheDocument();

    screen.getByRole("button", { name: /12 files need a match/ }).click();
    expect(await screen.findByText("Match")).toBeInTheDocument();
  });
});
