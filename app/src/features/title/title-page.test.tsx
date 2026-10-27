import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PlayerLayer } from "@/features/player/player";
import { PlayerProvider } from "@/features/player/player-context";
import {
  EngineProvider,
  type EpisodeState,
  type FileDetails,
  type TitleDetail,
} from "@/lib/engine";
import { fakeEngine, READY, SETTINGS } from "@/test/engine";
import { TitlePage } from "./title-page";

const shell = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => {} }));
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({ setFullscreen: async () => {} }),
}));

function episodes(season: number, size: number, state: (n: number) => EpisodeState["state"]) {
  return Array.from({ length: size }, (_, index) => ({
    season,
    number: index + 1,
    name: index === 10 && season === 4 ? "The Night Ferry" : `Episode ${index + 1}`,
    aired: "1991-01-01",
    state: state(index + 1),
    fileId: null,
  }));
}

/** What the About panel says of a title Maku hasn't looked up yet. */
const UNKNOWN: TitleDetail["about"] = {
  overview: null,
  genres: [],
  studio: null,
  status: null,
  started: null,
  ended: null,
  minutes: null,
  tmdbType: null,
  tmdbId: null,
};

const HARBOUR: TitleDetail = {
  about: UNKNOWN,
  id: 1,
  kind: "series",
  name: "The Harbour Line",
  year: 1989,
  released: "1989-04-26",
  airing: false,
  hasPoster: false,
  files: 70,
  added: null,
  aired: 72,
  present: 70,
  missing: 2,
  specialsMissing: 1,
  upcoming: 0,
  franchise: null,
  folder: "D:\\Videos\\TV\\The Harbour Line (1989)",
  seasons: [
    { season: 1, present: 39, aired: 39, total: 39 },
    { season: 4, present: 30, aired: 32, total: 32 },
  ],
  missingEpisodes: [],
  missingSpecials: [],
  upcomingEpisodes: [],
  episodes: [
    ...episodes(1, 39, () => "to convert"),
    ...episodes(4, 32, (n) => (n === 11 || n === 12 ? "missing" : n === 5 ? "broken" : "ready")),
    {
      season: 0,
      number: 1,
      name: "The Lighthouse",
      aired: "1990-10-17",
      state: "ready",
      fileId: 9,
    },
    {
      season: 0,
      number: 2,
      name: "Fog Over the Bay",
      aired: "1993-08-06",
      state: "missing",
      fileId: null,
    },
  ],
  videos: [
    {
      id: 1,
      path: "D:\\Videos\\TV\\The Harbour Line (1989)\\Season 01\\The Harbour Line - S01E01.mkv",
      size: 233_000_000,
      season: 1,
      episode: 1,
      episodeEnd: null,
      problem: null,
      height: 480,
      codec: "h264",
      duration: 1440,
      made: false,
      subtitlesJob: null,
      watched: false,
      resume: null,
      sound: ["jpn"],
      subtitles: ["eng"],
      heard: null,
    },
  ],
};

/** The Harbour Line's first video in full, as its details tell of it. */
const DETAILS: FileDetails = {
  id: 1,
  path: "D:\\Videos\\TV\\The Harbour Line (1989)\\Season 01\\The Harbour Line - S01E01.mkv",
  size: 233_000_000,
  foundAt: "2026-10-12T09:00:00+00:00",
  duration: 1440,
  problem: null,
  titleId: 1,
  title: "The Harbour Line",
  season: 1,
  episode: 1,
  episodeEnd: null,
  episodeName: "The Arrival",
  aired: "1989-04-26",
  overview: "A visitor lands with news from far away.",
  picture: { codec: "h264", width: 640, height: 480, bitDepth: 8, frameRate: 23.976 },
  sound: [{ language: "jpn", codec: "aac", channels: 2, lossless: false, heard: false }],
  subtitles: [
    { language: "eng", codec: "ass", text: true, forced: false, beside: false, made: false },
    { language: "eng", codec: null, text: true, forced: false, beside: true, made: true },
  ],
  chapters: 4,
  converted: false,
  converting: {
    state: "to convert",
    method: "reencode",
    reasons: ["H.264 becomes HEVC 10-bit"],
  },
};

/** A video of The Harbour Line's at S`season`E`episode` (none for a file without one), named
 * `name`. */
function video(id: number, season: number | null, episode: number | null, name: string) {
  return {
    id,
    path: `D:\\Videos\\TV\\The Harbour Line (1989)\\${name}.mkv`,
    size: 412_000_000,
    season,
    episode,
    episodeEnd: null,
    problem: null,
    height: 1080,
    codec: "hevc",
    duration: 1453,
    sound: ["jpn"],
    subtitles: ["ger"],
    heard: null as string | null,
    made: false,
    subtitlesJob: null as "queued" | "running" | null,
    watched: false,
    resume: null as number | null,
  };
}

/** A film of The Starfall Collection's, alone in the library: one file, no seasons. */
const STARFALL: TitleDetail = {
  ...HARBOUR,
  id: 3,
  kind: "movie",
  name: "Starfall",
  year: 2001,
  released: "2001-07-13",
  files: 1,
  aired: 0,
  present: 0,
  missing: 0,
  specialsMissing: 0,
  folder: "D:\\Videos\\Movies\\Starfall (2001)",
  seasons: [],
  episodes: [],
  videos: [
    {
      ...video(5, null, null, "Starfall (2001)"),
      path: "D:\\Videos\\Movies\\Starfall (2001)\\Starfall (2001).mkv",
      size: 2_100_000_000,
      duration: 6900,
    },
  ],
};

/** A film of the collection that the library hasn't got, as TMDB knows it. */
const ASCENT = {
  entryId: -40377,
  kind: "movie",
  name: "Starfall: Ascent",
  year: 2009,
  released: "2009-06-26",
  episodes: null,
  coming: false,
  airing: false,
  cover: null,
  overview: null,
  genres: [],
  studio: null,
  tmdbType: "movie",
  tmdbId: 40377,
};

const OPENED = {
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
};

function renderTitle(
  title: TitleDetail,
  report: unknown = undefined,
  state: unknown = null,
  more: Record<string, unknown> = {},
  player = false,
) {
  const fetch = fakeEngine({
    [`/titles/${title.id}`]: title,
    [`/titles/${title.id}/report`]: report,
    "/settings": SETTINGS,
    ...more,
  });
  shell.invoke.mockImplementation(async (command: string) =>
    command === "engine_status" ? READY : undefined,
  );
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <EngineProvider>
        <PlayerProvider>
          <MemoryRouter initialEntries={[{ pathname: `/titles/${title.id}`, state }]}>
            <Routes>
              <Route path="/titles/:id" element={<TitlePage />} />
              <Route path="/match" element={<MatchSearch />} />
              <Route path="*" element={<Elsewhere />} />
            </Routes>
          </MemoryRouter>
          {player && <PlayerLayer />}
        </PlayerProvider>
      </EngineProvider>
    </QueryClientProvider>,
  );
  return fetch;
}

/** Pictures the window is given are object addresses: jsdom has none, so each is the same one. */
function showsPictures() {
  Object.defineProperty(URL, "createObjectURL", {
    value: () => "blob:the-picture",
    configurable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", { value: () => {}, configurable: true });
}

/** A picture as the engine sends it, saying whether it's from the episode or its show's. */
function picture(source: "episode" | "show") {
  return new Response(new Blob(["jpeg"], { type: "image/jpeg" }), {
    headers: { "Maku-Picture": source },
  });
}

/** Opens a row's "More" menu as a keyboard does, and picks one of its items. */
async function fromMenu(menu: string, item: string) {
  fireEvent.keyDown(await screen.findByRole("button", { name: menu }), { key: "Enter" });
  (await screen.findByRole("menuitem", { name: item })).click();
}

function sent(fetch: ReturnType<typeof fakeEngine>, method: string, path: string) {
  return fetch.mock.calls.filter(
    ([input, init]) =>
      (init?.method ?? "GET") === method && new URL(String(input)).pathname === path,
  );
}

const DELETED = { planId: 12, moved: 0, quarantined: 1, problems: [] };

function MatchSearch() {
  return <p>Match {useLocation().search}</p>;
}

/** Another page, by its address: Convert, or making English subtitles. */
function Elsewhere() {
  const at = useLocation();
  return <p>Went to {at.pathname + at.search}</p>;
}

describe("TitlePage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    shell.invoke.mockReset();
  });

  it("shows the page's shape while it loads", async () => {
    renderTitle(HARBOUR);
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );

    expect(await screen.findByRole("status", { name: "Loading the title" })).toBeInTheDocument();
  });

  it("says what the title is and how much of it is there", async () => {
    renderTitle(HARBOUR);

    expect(
      await screen.findByRole("heading", { name: "The Harbour Line", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByText("TV series")).toBeInTheDocument();
    expect(screen.getByText("Matched on TMDB")).toBeInTheDocument();
    expect(screen.getByText("1989 · 2 seasons · 72 episodes")).toBeInTheDocument();
    expect(screen.getByText("97%")).toBeInTheDocument();
    expect(screen.getByText("70 of 72 episodes")).toBeInTheDocument();
  });

  it("says when files didn't fit its new match, and leads to them", async () => {
    renderTitle(HARBOUR, undefined, { waiting: 2 });

    expect(
      await screen.findByText("2 files didn't fit this match. They wait for you in Need a match."),
    ).toBeInTheDocument();
    screen.getByRole("button", { name: "Match them" }).click();

    expect(await screen.findByText("Match")).toBeInTheDocument();
  });

  it("says why Explorer couldn't open its folder", async () => {
    renderTitle(HARBOUR);
    const gone = `Windows can't open ${HARBOUR.folder}: it isn't a folder that's there.`;
    shell.invoke.mockImplementation(async (command: string) => {
      if (command === "engine_status") return READY;
      if (command === "open_folder") throw gone;
      return undefined;
    });

    (await screen.findByRole("button", { name: "Open folder" })).click();

    expect(await screen.findByRole("alert")).toHaveTextContent(gone);
  });

  it("says which collection a film is part of, and leads back to it", async () => {
    renderTitle({ ...STARFALL, franchise: { id: 7, name: "The Starfall Collection" } });

    expect(
      await screen.findByText("2001 · 1 file · part of The Starfall Collection"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "The Starfall Collection" })).toHaveAttribute(
      "href",
      "/franchises/7",
    );
  });

  it("leads to the films its collection lacks, even alone in the library", async () => {
    renderTitle(STARFALL, undefined, null, {
      "/franchises/3/missing": { titles: [ASCENT], looking: false },
    });

    expect(await screen.findByRole("link", { name: "Missing films 1" })).toHaveAttribute(
      "href",
      "/franchises/3?missing",
    );
  });

  it("leads to its collection's page for the films the collection lacks", async () => {
    renderTitle(
      { ...STARFALL, franchise: { id: 7, name: "The Starfall Collection" } },
      undefined,
      null,
      { "/franchises/7/missing": { titles: [ASCENT], looking: false } },
    );

    expect(await screen.findByRole("link", { name: "Missing films 1" })).toHaveAttribute(
      "href",
      "/franchises/7?missing",
    );
  });

  it("never asks what a collection lacks for a series, which stands alone", async () => {
    const fetch = renderTitle(HARBOUR, undefined, null, {
      "/franchises/1/missing": { titles: [ASCENT], looking: false },
    });

    await screen.findByRole("button", { name: "Change match" });
    await new Promise((settled) => setTimeout(settled, 50)); // whatever it asks, asked
    expect(sent(fetch, "GET", "/titles/1").length).toBeGreaterThan(0);
    expect(sent(fetch, "GET", "/franchises/1/missing")).toHaveLength(0);
    expect(screen.queryByRole("link", { name: /Missing/ })).not.toBeInTheDocument();
  });

  it("offers no missing films once its videos are all gone", async () => {
    const fetch = renderTitle({ ...STARFALL, files: 0, videos: [] }, undefined, null, {
      "/franchises/3/missing": { titles: [ASCENT], looking: false },
    });

    await screen.findByRole("button", { name: "Change match" });
    await waitFor(() => expect(sent(fetch, "GET", "/franchises/3/missing")).toHaveLength(1));
    await new Promise((settled) => setTimeout(settled, 50)); // its answer read, too
    expect(screen.queryByRole("link", { name: /Missing films/ })).not.toBeInTheDocument();
  });

  it("offers no missing films when its collection lacks none", async () => {
    const fetch = renderTitle(STARFALL, undefined, null, {
      "/franchises/3/missing": { titles: [], looking: false },
    });

    await screen.findByRole("button", { name: "Change match" });
    await waitFor(() => expect(sent(fetch, "GET", "/franchises/3/missing")).toHaveLength(1));
    expect(screen.queryByRole("link", { name: /Missing films/ })).not.toBeInTheDocument();
  });

  it("opens its folder, and leads to changing its match", async () => {
    renderTitle(HARBOUR);

    (await screen.findByRole("button", { name: "Open folder" })).click();
    await waitFor(() =>
      expect(shell.invoke).toHaveBeenCalledWith("open_folder", { path: HARBOUR.folder }),
    );
    screen.getByRole("button", { name: "Change match" }).click();

    expect(await screen.findByText("Match ?title=1")).toBeInTheDocument();
  });

  it("shows its gap analysis in its folder, or copies it", async () => {
    const copied = vi.fn<(text: string) => Promise<void>>(async () => {});
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: copied } });
    const report = {
      path: `${HARBOUR.folder}\\Maku - Gap analysis.md`,
      text: "# The Harbour Line",
    };
    renderTitle(HARBOUR, report);

    (await screen.findByRole("button", { name: "Show in folder" })).click();
    await waitFor(() =>
      expect(shell.invoke).toHaveBeenCalledWith("show_in_folder", { path: report.path }),
    );
    screen.getByRole("button", { name: "Copy" }).click();

    await waitFor(() => expect(copied).toHaveBeenCalledWith("# The Harbour Line"));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("lists the seasons, the map, and the missing and broken episodes", async () => {
    renderTitle(HARBOUR);

    expect(await screen.findByText("2 missing")).toBeInTheDocument();
    expect(screen.getByText("complete")).toBeInTheDocument();
    // The map goes season by season.
    const map = screen.getByRole("region", { name: "Episode map" });
    expect(
      within(map)
        .getAllByRole("list")
        .map((season) => season.getAttribute("aria-label")),
    ).toEqual(["Season 1: 39 to convert", "Season 4: 29 ready, 1 broken, 2 missing"]);
    expect(within(map).getByText("Season 4")).toBeInTheDocument();
    expect(
      within(map).getByTitle("S04E12 · episode 51 · Episode 12 · missing"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Episode 51 · missing/)).toBeInTheDocument();
    expect(screen.getByText(/Episode 50 · The Night Ferry · missing/)).toBeInTheDocument();
    expect(screen.getByText(/Episode 44 · won't play/)).toBeInTheDocument();
  });

  it("reads a long run of missing episodes as one range", async () => {
    renderTitle({
      ...HARBOUR,
      name: "Lantern Street",
      year: 1986,
      aired: 153,
      present: 4,
      missing: 149,
      seasons: [{ season: 1, present: 4, aired: 153, total: 153 }],
      episodes: episodes(1, 153, (n) => (n <= 3 || n === 6 ? "to convert" : "missing")),
    });

    expect(await screen.findByText("S01E07–E153")).toBeInTheDocument();
    expect(screen.getByText(/Episodes 7 to 153 · 147 missing/)).toBeInTheDocument();
    expect(screen.getByText(/Episode 4 · missing/)).toBeInTheDocument();
    expect(screen.getByText(/Episode 5 · missing/)).toBeInTheDocument();
    expect(screen.queryByText(/Episode 100 · missing/)).not.toBeInTheDocument();
    expect(screen.getByText("3%")).toBeInTheDocument();
  });

  it("deletes a video once asked, says where it went, and puts it back", async () => {
    let gone = false; // once deleted, the title comes back without the video and its row
    const fetch = renderTitle(HARBOUR, undefined, null, {
      "/titles/1": () => (gone ? { ...HARBOUR, videos: [] } : HARBOUR),
      "POST /files/delete": () => {
        gone = true;
        return DELETED;
      },
      "POST /plans/12/undo": DELETED,
    });

    await fromMenu("More for S01E01", "Delete…");
    const asking = await screen.findByRole("group", { name: "Delete S01E01?" });
    await waitFor(() =>
      expect(asking).toHaveTextContent(
        "1 video (233 MB) goes to the quarantine on D:, with any subtitles named after it. " +
          "They're deleted for good after 30 days; till then History puts them back.",
      ),
    );
    within(asking).getByRole("button", { name: "Delete 1 video" }).click();

    expect(await screen.findByText("Deleted 1 video.")).toBeInTheDocument();
    const [[, init]] = sent(fetch, "POST", "/files/delete") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ files: [1] });
    screen.getByRole("button", { name: "Put back" }).click();
    await waitFor(() => expect(sent(fetch, "POST", "/plans/12/undo")).toHaveLength(1));
  });

  it("ticks videos to mark several watched at once, or a whole season", async () => {
    const two = { ...HARBOUR, videos: [...HARBOUR.videos, video(2, 1, 2, "S01E02")] };
    const fetch = renderTitle(two, undefined, null, { "POST /files/watched": null });

    expect(
      await screen.findByText("Tick videos to mark, convert, subtitle or delete several at once"),
    ).toBeInTheDocument();
    screen.getByRole("checkbox", { name: "Tick S01E01" }).click();
    const bar = await screen.findByRole("group", { name: "Ticked videos" });
    expect(bar).toHaveTextContent("1 ticked");
    expect(
      screen.getByRole("checkbox", { name: "Tick every video of Season 1" }),
    ).toBePartiallyChecked();
    screen.getByRole("checkbox", { name: "Tick every video of Season 1" }).click();
    expect(bar).toHaveTextContent("2 ticked");
    within(bar).getByRole("button", { name: "Mark as watched" }).click();

    await waitFor(() => expect(sent(fetch, "POST", "/files/watched")).toHaveLength(1));
    const [[, init]] = sent(fetch, "POST", "/files/watched") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ files: [1, 2], watched: true });
    expect(screen.queryByRole("group", { name: "Ticked videos" })).not.toBeInTheDocument();
  });

  it("acts only on the ticked videos a search shows", async () => {
    const two = { ...HARBOUR, videos: [...HARBOUR.videos, video(2, 1, 2, "S01E02")] };
    const fetch = renderTitle(two, undefined, null, { "POST /files/watched": null });

    (await screen.findByRole("checkbox", { name: "Tick every video of Season 1" })).click();
    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search the videos of The Harbour Line" }),
      {
        target: { value: "S01E02" },
      },
    );
    const bar = await screen.findByRole("group", { name: "Ticked videos" });
    expect(bar).toHaveTextContent("1 ticked");
    within(bar).getByRole("button", { name: "Mark as watched" }).click();

    await waitFor(() => expect(sent(fetch, "POST", "/files/watched")).toHaveLength(1));
    const [[, init]] = sent(fetch, "POST", "/files/watched") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ files: [2], watched: true });
  });

  it("converts ticked videos, or makes their English subtitles, from those pages", async () => {
    const two = { ...HARBOUR, videos: [...HARBOUR.videos, video(2, 1, 2, "S01E02")] };
    renderTitle(two);

    (await screen.findByRole("checkbox", { name: "Tick S01E01" })).click();
    screen.getByRole("checkbox", { name: "Tick S01E02" }).click();
    within(await screen.findByRole("group", { name: "Ticked videos" }))
      .getByRole("button", { name: "Convert" })
      .click();

    expect(await screen.findByText("Went to /convert?files=1,2")).toBeInTheDocument();
  });

  it("deletes ticked videos together, once asked", async () => {
    const two = { ...HARBOUR, videos: [...HARBOUR.videos, video(2, 1, 2, "S01E02")] };
    const fetch = renderTitle(two, undefined, null, {
      "POST /files/delete": { ...DELETED, quarantined: 2 },
    });

    (await screen.findByRole("checkbox", { name: "Tick every video of Season 1" })).click();
    within(await screen.findByRole("group", { name: "Ticked videos" }))
      .getByRole("button", { name: "Delete…" })
      .click();
    const asking = await screen.findByRole("group", { name: "Delete 2 videos?" });
    within(asking).getByRole("button", { name: "Delete 2 videos" }).click();

    await waitFor(() => expect(sent(fetch, "POST", "/files/delete")).toHaveLength(1));
    const [[, init]] = sent(fetch, "POST", "/files/delete") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ files: [1, 2] });
  });

  it("chooses another of TMDB's posters", async () => {
    const option = (poster: string, language: string | null) => ({
      poster,
      address: `https://image.tmdb.org/t/p/w342${poster}`,
      language,
      width: 1000,
      height: 1500,
    });
    const fetch = renderTitle({ ...HARBOUR, hasPoster: true }, undefined, null, {
      "/titles/1/poster": () => new Response(new Blob(["a poster"]), { status: 200 }),
      "/titles/1/posters": {
        found: "/a.jpg",
        chosen: "/c.jpg",
        options: [option("/c.jpg", "fr"), option("/a.jpg", "en"), option("/b.jpg", null)],
        problem: null,
      },
      "PUT /titles/1/poster": null,
    });

    (await screen.findByRole("button", { name: "Change poster" })).click();

    const card = await screen.findByRole("dialog", { name: "Choose a poster" });
    expect(card).toHaveTextContent("The Harbour Line · from TMDB.");
    expect(
      await within(card).findByRole("button", { name: "In use: TMDB · French" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(within(card).getByRole("button", { name: "Use TMDB · English" })).toBeInTheDocument();
    expect(
      within(card).getByRole("button", { name: "Back to the one Maku found" }),
    ).toBeInTheDocument();
    within(card).getByRole("button", { name: "Use TMDB · no words" }).click();

    await waitFor(() => expect(sent(fetch, "PUT", "/titles/1/poster")).toHaveLength(1));
    const [[, init]] = sent(fetch, "PUT", "/titles/1/poster") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ poster: "/b.jpg" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // The poster on the page loads anew, rather than the one from before.
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([input]) => String(input).endsWith("/titles/1/poster?v=1")),
      ).toBe(true),
    );
  });

  it("says when TMDB has no poster of it", async () => {
    renderTitle(HARBOUR, undefined, null, {
      "/titles/1/posters": { found: null, chosen: null, options: [], problem: null },
    });

    (await screen.findByRole("button", { name: "Change poster" })).click();

    const card = await screen.findByRole("dialog", { name: "Choose a poster" });
    expect(await within(card).findByText("TMDB has no poster of it.")).toBeInTheDocument();
    expect(within(card).queryByRole("list", { name: "Posters" })).not.toBeInTheDocument();
  });

  it("says which videos couldn't be deleted, and why", async () => {
    const open = "It's open in another app, maybe your player. Close it, then try again.";
    const stayed = {
      planId: 13,
      moved: 0,
      quarantined: 0,
      problems: [
        { label: "The Harbour Line · S01E01", source: String.raw`D:\Videos\x.mkv`, problem: open },
      ],
    };
    renderTitle(HARBOUR, undefined, null, { "POST /files/delete": stayed });

    await fromMenu("More for S01E01", "Delete…");
    (await screen.findByRole("button", { name: "Delete 1 video" })).click();

    const said = await screen.findByRole("region", { name: "Deleted" });
    expect(said).toHaveTextContent("Nothing was deleted.");
    expect(said).toHaveTextContent(`The Harbour Line · S01E01: ${open}`);
    expect(screen.queryByRole("button", { name: "Put back" })).not.toBeInTheDocument();
  });

  it("deletes a whole title or season only once asked, and can be talked out of it", async () => {
    const fetch = renderTitle(HARBOUR, undefined, null, { "POST /files/delete": DELETED });

    (await screen.findByRole("button", { name: "Delete" })).click();
    expect(
      await screen.findByRole("group", { name: "Delete The Harbour Line?" }),
    ).toBeInTheDocument();
    screen.getByRole("button", { name: "Cancel" }).click();
    await waitFor(() =>
      expect(
        screen.queryByRole("group", { name: "Delete The Harbour Line?" }),
      ).not.toBeInTheDocument(),
    );

    screen.getByRole("button", { name: "Delete season 1" }).click();
    (await screen.findByRole("button", { name: "Delete 1 video" })).click();

    await waitFor(() => expect(sent(fetch, "POST", "/files/delete")).toHaveLength(1));
    expect(screen.queryByRole("button", { name: "Delete season 4" })).not.toBeInTheDocument();
  });

  it("keeps the specials apart", async () => {
    renderTitle(HARBOUR);

    expect(await screen.findByRole("heading", { name: "Specials" })).toBeInTheDocument();
    expect(screen.getByText("1 not in the library · never counted as missing")).toBeInTheDocument();
    expect(screen.getByText(/Fog Over the Bay/)).toBeInTheDocument();
  });

  it("shows the gap analysis as a reader sees it, not its Markdown", async () => {
    renderTitle(HARBOUR, {
      path: "D:\\Videos\\TV\\The Harbour Line (1989)\\Maku - Gap analysis.md",
      text: [
        "# The Harbour Line (1989) — gap analysis",
        "_Updated 10 Oct 2026, 14:20 · library D:\\Videos_",
        "",
        "## Summary",
        "- Present: **289 of 291** episodes (99%)",
        "",
        "## Missing",
        "| Episode | Absolute | Folder |",
        "| --- | --- | --- |",
        "| S01E51 | 51 | Season 01 |",
        "",
      ].join("\n"),
    });

    const report = await screen.findByRole("region", { name: "Gap Analysis" });
    expect(
      await within(report).findByRole("heading", {
        name: "The Harbour Line (1989) — gap analysis",
      }),
    ).toBeInTheDocument();
    expect(within(report).getByRole("heading", { name: "Missing" })).toBeInTheDocument();
    expect(within(report).getByRole("cell", { name: "S01E51" })).toBeInTheDocument();
    expect(within(report).getByText("289 of 291").tagName).toBe("STRONG");
    expect(report).not.toHaveTextContent("##");
    expect(report).not.toHaveTextContent("Plex");
  });

  it("a film shows its file, without seasons", async () => {
    renderTitle(STARFALL);

    expect(await screen.findByText("Movie")).toBeInTheDocument();
    expect(screen.getByText("2001 · 1 file")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Seasons" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Its file" })).toBeInTheDocument();
  });

  it("lists its videos a season at a time, each by its episode's title", async () => {
    renderTitle({
      ...HARBOUR,
      videos: [
        video(9, 0, 1, "The Lighthouse"),
        video(4, 4, 1, "S04E01"),
        video(2, 1, 2, "S01E02"),
        { ...video(3, 1, 1, "S01E01"), problem: "It stops at 12:41." },
        video(5, null, null, "Opening"),
      ],
    });

    const seasons = await screen.findByRole("radiogroup", { name: "Season" });
    expect(
      within(seasons)
        .getAllByRole("radio")
        .map((each) => each.textContent),
    ).toEqual(["Season 1", "Season 4", "Specials", "Other files"]);
    const first = screen.getByRole("list", { name: "Season 1" });
    const rows = within(first).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("S01E01Episode 1won't play");
    expect(rows[1]).toHaveTextContent("S01E02Episode 2");
    expect(rows[1]).toHaveTextContent("1080p · HEVC · 24 min · 412 MB");
    expect(within(first).getByRole("button", { name: "Episode 2" })).toHaveAttribute(
      "title",
      video(2, 1, 2, "S01E02").path,
    );
    expect(within(first).queryByRole("button", { name: "Play S01E01" })).not.toBeInTheDocument();

    within(seasons).getByRole("radio", { name: "Specials" }).click();
    expect(await screen.findByRole("list", { name: "Specials" })).toHaveTextContent(
      "S00E01The Lighthouse",
    );
    within(seasons).getByRole("radio", { name: "Other files" }).click();
    expect(await screen.findByRole("list", { name: "Other files" })).toHaveTextContent(
      "Opening.mkv",
    );
  });

  it("says what each video, and the title, can be heard and read in, and what has no English", async () => {
    renderTitle({
      ...HARBOUR,
      videos: [
        { ...video(1, 1, 1, "S01E01"), sound: ["jpn"], subtitles: ["ger", "en"] },
        { ...video(2, 1, 2, "S01E02"), sound: ["jpn", "eng"], subtitles: [] },
        { ...video(3, 1, 3, "S01E03"), sound: ["jpn"], subtitles: ["ger"] },
      ],
    });

    const header = await screen.findByRole("region", { name: "The Harbour Line" });
    expect(header).toHaveTextContent(
      "Japanese and English sound · German subtitles, English on 1 of 3",
    );
    expect(within(header).getByText("1 without English")).toBeInTheDocument();
    const rows = within(screen.getByRole("list", { name: "Videos" })).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("JapaneseGerman subsEnglish subs");
    expect(rows[0]).not.toHaveTextContent("No English");
    expect(rows[1]).toHaveTextContent("Japanese, English");
    expect(rows[1]).not.toHaveTextContent("No English");
    expect(rows[2]).toHaveTextContent("JapaneseGerman subsNo English");
  });

  it("says when a file doesn't name its sound's language, and the one Maku heard there", async () => {
    renderTitle({
      ...HARBOUR,
      videos: [
        { ...video(1, 1, 1, "S01E01"), sound: [""], subtitles: [] },
        { ...video(2, 1, 2, "S01E02"), sound: ["ja"], heard: "ja", made: true, subtitles: ["en"] },
        { ...video(3, 1, 3, "S01E03"), sound: ["jpn", ""], subtitles: ["eng", "en"] },
      ],
    });

    const list = await screen.findByRole("list", { name: "Videos" });
    const rows = within(list).getAllByRole("listitem");
    expect(within(rows[0] as HTMLElement).getByText("Language not labelled")).toHaveAttribute(
      "title",
      "The file doesn't say which language its sound is in.",
    );
    expect(rows[0]).not.toHaveTextContent("unnamed");
    expect(within(rows[1] as HTMLElement).getByText("Japanese")).toHaveAttribute(
      "title",
      "The file doesn't say which language its sound is in: Maku heard Japanese when it made English subtitles.",
    );
    expect(rows[2]).toHaveTextContent("Japanese, not labelledEnglish subs");
    // Each language once, however its files write it.
    expect(within(rows[2] as HTMLElement).getAllByText("English subs")).toHaveLength(1);
    expect(screen.getByRole("region", { name: "The Harbour Line" })).toHaveTextContent(
      "Japanese sound · English subtitles on 2 of 3",
    );
  });

  it("marks the English subtitles Maku made, is making and has waiting, and makes more", async () => {
    renderTitle(
      {
        ...HARBOUR,
        videos: [
          { ...video(1, 1, 1, "S01E01"), subtitles: ["ger", "en"], made: true },
          { ...video(2, 1, 2, "S01E02"), subtitlesJob: "running" },
          { ...video(3, 1, 3, "S01E03"), subtitlesJob: "queued" },
          video(4, 1, 4, "S01E04"),
        ],
      },
      undefined,
      null,
      {
        "/queue": {
          running: {
            job: { id: 30, fileId: 2, kind: "subtitles" },
            stage: "listening",
            frames: 604,
            total: 1440,
          },
          queued: [],
        },
      },
    );

    const list = await screen.findByRole("list", { name: "Videos" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("JapaneseGerman subsEnglish subs · made by Maku");
    await waitFor(() => expect(rows[1]).toHaveTextContent("Making English subs · 41%"));
    expect(rows[2]).toHaveTextContent("English subs next in the queue");
    expect(rows[3]).toHaveTextContent("No English");
    expect(screen.getByText("4 files · 3 without English")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Make English subtitles" })).toHaveAttribute(
      "href",
      "/subtitles?title=1&season=1",
    );
  });

  it("finds videos through every season by episode code or title, or file name", async () => {
    renderTitle({
      ...HARBOUR,
      videos: [
        video(1, 1, 1, "S01E01"),
        video(2, 4, 11, "S04E11"),
        video(3, 0, 1, "S00E01"),
        video(4, null, null, "Opening"),
      ],
    });

    const search = await screen.findByRole("searchbox", {
      name: "Search the videos of The Harbour Line",
    });
    expect(search).toHaveAttribute("placeholder", "Search 4 videos");
    fireEvent.change(search, { target: { value: "ferry" } });

    const found = await screen.findByRole("list", { name: "Videos found" });
    expect(within(found).getAllByRole("listitem")).toHaveLength(1);
    expect(found).toHaveTextContent("S04E11The Night Ferry");
    expect(screen.getByText("1 of 4 videos")).toBeVisible();
    expect(screen.queryByRole("radio", { name: "Season 1" })).not.toBeInTheDocument();
    // Its English subtitles are made for the whole title while searching.
    expect(screen.getByRole("link", { name: "Make English subtitles" })).toHaveAttribute(
      "href",
      "/subtitles?title=1",
    );

    fireEvent.change(search, { target: { value: "s00e01" } });
    expect(await screen.findByText("The Lighthouse")).toBeVisible();
    fireEvent.change(search, { target: { value: "opening.mkv" } });
    expect(await within(found).findByText("Opening.mkv")).toBeVisible();
    fireEvent.change(search, { target: { value: "Zeppelin" } });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "No video of The Harbour Line goes by “Zeppelin”.",
    );

    // A season's name in Seasons shows its videos, the search put away.
    within(screen.getByRole("region", { name: "Seasons" }))
      .getByRole("button", { name: "Season 4" })
      .click();
    expect(await screen.findByRole("list", { name: "Season 4" })).toHaveTextContent("S04E11");
    expect(search).toHaveValue("");
  });

  it("finds a video of two episodes by either", async () => {
    renderTitle({
      ...HARBOUR,
      videos: [video(1, 4, 10, "S04E10-E11"), video(2, 4, 12, "S04E12")].map((each) =>
        each.id === 1 ? { ...each, episodeEnd: 11 } : each,
      ),
    });
    const search = await screen.findByRole("searchbox", {
      name: "Search the videos of The Harbour Line",
    });

    for (const asked of ["S04E11", "ferry"]) {
      fireEvent.change(search, { target: { value: asked } });
      const found = await screen.findByRole("list", { name: "Videos found" });
      await waitFor(() => expect(within(found).getAllByRole("listitem")).toHaveLength(1));
      expect(found).toHaveTextContent("S04E10-E11");
    }
  });

  it("goes to its videos when the title bar's search leads here", async () => {
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    try {
      renderTitle({ ...HARBOUR, videos: [video(1, 1, 1, "S01E01")] }, undefined, { videos: true });

      await waitFor(() => expect(scrolled).toHaveBeenCalled());
      expect(scrolled.mock.contexts[0]).toBe(screen.getByRole("region", { name: "Videos" }));
    } finally {
      // @ts-expect-error: jsdom has none of its own
      delete Element.prototype.scrollIntoView;
    }
  });

  it("says what the title is about, and opens its page on TMDB", async () => {
    renderTitle({
      ...HARBOUR,
      about: {
        overview: "Five years after the last crossing, the harbour pilot keeps a quiet life.",
        genres: ["Drama", "Mystery"],
        studio: "Northlight Pictures",
        status: "finished",
        started: "1989-04-26",
        ended: "1996-01-31",
        minutes: 24,
        tmdbType: "tv",
        tmdbId: 40211,
      },
    });

    const about = await screen.findByRole("region", { name: "About" });
    expect(about).toHaveTextContent("Five years after the last crossing");
    expect(within(about).getByRole("list", { name: "Genres" })).toHaveTextContent("DramaMystery");
    expect(about).toHaveTextContent("StudioNorthlight Pictures");
    expect(about).toHaveTextContent("AiredApr 1989 to Jan 1996");
    expect(about).toHaveTextContent("StatusFinished");
    expect(about).toHaveTextContent("Length24 min an episode");

    // Its page on TMDB is the one place to read more.
    expect(
      within(about)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["On TMDB"]);
    within(about).getByRole("button", { name: "On TMDB" }).click();
    await waitFor(() =>
      expect(shell.invoke).toHaveBeenCalledWith("open_tmdb_page", { kind: "tv", id: 40211 }),
    );
  });

  it("says when there's no synopsis yet, and a film's length and release", async () => {
    renderTitle({
      ...STARFALL,
      about: { ...UNKNOWN, started: "2013-03-30", minutes: 105, status: "finished" },
    });

    const about = await screen.findByRole("region", { name: "About" });
    expect(about).toHaveTextContent("No synopsis yet.");
    expect(about).toHaveTextContent("Released30 Mar 2013");
    expect(about).toHaveTextContent("StatusOut");
    expect(about).toHaveTextContent("Length1 h 45 min");
    // Without its number on TMDB, there's no page to open.
    expect(within(about).queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows a season's videos from its name in Seasons", async () => {
    renderTitle({ ...HARBOUR, videos: [video(1, 1, 1, "S01E01"), video(2, 4, 1, "S04E01")] });

    const panel = await screen.findByRole("region", { name: "Seasons" });
    within(panel).getByRole("button", { name: "Season 4" }).click();

    await waitFor(() =>
      expect(screen.getByRole("radio", { name: "Season 4" })).toHaveAttribute("data-state", "on"),
    );
    expect(screen.getByRole("list", { name: "Season 4" })).toHaveTextContent("S04E01");
    // A season without videos has nothing to show.
    expect(within(panel).queryByRole("button", { name: "Season 2" })).not.toBeInTheDocument();
  });

  it("a film plays from the top of its page", async () => {
    renderTitle(STARFALL, undefined, null, { "POST /player": OPENED }, true);

    const file = await screen.findByRole("list", { name: "Its file" });
    expect(file).toHaveTextContent("Starfall (2001).mkv");
    expect(file).toHaveTextContent("1080p · HEVC · 1 h 55 min · 2.1 GB");
    const header = screen.getByRole("region", { name: "Starfall" });
    within(header).getByRole("button", { name: "Play" }).click();

    const player = await screen.findByRole("region", { name: "Player" });
    expect(player).toHaveTextContent("Starfall");
    expect(await within(header).findByRole("button", { name: "Playing" })).toBeInTheDocument();
  });

  it("plays a video from its row, marking it playing, its episode's name with it", async () => {
    const fetch = renderTitle(HARBOUR, undefined, null, { "POST /player": OPENED }, true);

    const button = await screen.findByRole("button", { name: "Play S01E01" });
    button.focus();
    button.click();

    const player = await screen.findByRole("region", { name: "Player" });
    expect(document.activeElement).toBe(button);
    expect(player).toHaveTextContent("The Harbour Line · S01E01");
    expect(player).toHaveTextContent("Episode 1");
    const row = screen.getByTitle(HARBOUR.videos[0]?.path ?? "").closest("li");
    expect(row).toHaveTextContent("Playing");
    expect(screen.queryByRole("button", { name: "Play S01E01" })).not.toBeInTheDocument();
    // The same button, so the keyboard keeps its place.
    expect(screen.getByRole("button", { name: "Playing S01E01" })).toBeInTheDocument();
    await waitFor(() => expect(sent(fetch, "POST", "/player")).toHaveLength(1));
  });

  it("says which videos were watched and what's left of one, and picks it up there", async () => {
    const [first] = HARBOUR.videos as [TitleDetail["videos"][number]];
    const watched = { ...first, watched: true };
    const stopped = { ...video(2, 1, 2, "S01E02"), resume: 553 };
    const fetch = renderTitle(
      { ...HARBOUR, videos: [watched, stopped] },
      undefined,
      null,
      { "POST /player": OPENED },
      true,
    );

    const videos = await screen.findByRole("region", { name: "Videos" });
    expect(videos).toHaveTextContent("2 files · 1 watched");
    const rows = within(videos).getAllByRole("listitem");
    expect(
      within(rows[0] as HTMLElement).getByRole("img", { name: "Watched" }),
    ).toBeInTheDocument();
    expect(rows[1]).toHaveTextContent("1080p · HEVC · 15 min left · 412 MB");
    within(videos).getByRole("button", { name: "Play S01E02" }).click();

    const player = await screen.findByRole("region", { name: "Player" });
    expect(player).toHaveTextContent("The Harbour Line · S01E02");
    await waitFor(() => expect(sent(fetch, "POST", "/player")).toHaveLength(1));
    const src = player.querySelector("video")?.getAttribute("src");
    await waitFor(() =>
      expect(new URL(src ?? "http://x/?at=0").searchParams.get("at")).toBe("553.000"),
    );
  });

  it("marks a video watched, or not, from its menu", async () => {
    const fetch = renderTitle(HARBOUR, undefined, null, { "POST /files/watched": null });

    await fromMenu("More for S01E01", "Mark as watched");

    await waitFor(() => expect(sent(fetch, "POST", "/files/watched")).toHaveLength(1));
    const [[, init]] = sent(fetch, "POST", "/files/watched") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ files: [1], watched: true });
  });

  it("tells of a video in full, keeping what happens in it hidden till asked", async () => {
    renderTitle(HARBOUR, undefined, null, { "/files/1": DETAILS });

    await fromMenu("More for S01E01", "Details");

    const card = await screen.findByRole("dialog", { name: "S01E01 · The Arrival" });
    expect(card).toHaveTextContent("The Harbour Line · aired 26 Apr 1989");
    // A blur stands in for what happens: nothing of it is on the page till asked.
    expect(card).not.toHaveTextContent(DETAILS.overview ?? "");
    within(card).getByRole("button", { name: "Show what happens" }).click();
    expect(await within(card).findByText(DETAILS.overview ?? "")).toBeInTheDocument();
    const file = within(card).getByRole("region", { name: "The file" });
    expect(file).toHaveTextContent("640 × 480 · H.264 8-bit · 23.98 fps");
    expect(file).toHaveTextContent("Japanese · AAC stereo");
    expect(file).toHaveTextContent("English · in it");
    expect(file).toHaveTextContent("English · beside it · made by Maku");
    expect(file).toHaveTextContent("24:00");
    expect(file).toHaveTextContent("233 MB");
    expect(file).toHaveTextContent("H.264 becomes HEVC 10-bit");
    expect(file).toHaveTextContent(DETAILS.path);
  });

  it("shows the video in its folder from its details, copies its path, and plays it", async () => {
    const fetch = renderTitle(
      HARBOUR,
      undefined,
      null,
      { "/files/1": DETAILS, "POST /player": OPENED },
      true,
    );
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    // The video's name opens its details too.
    (await screen.findByTitle(DETAILS.path)).click();
    const card = await screen.findByRole("dialog", { name: "S01E01 · The Arrival" });
    within(card).getByRole("button", { name: "Show in folder" }).click();
    await waitFor(() =>
      expect(shell.invoke).toHaveBeenCalledWith("show_in_folder", { path: DETAILS.path }),
    );
    fireEvent.keyDown(within(card).getByRole("button", { name: "More for S01E01" }), {
      key: "Enter",
    });
    (await screen.findByRole("menuitem", { name: "Copy path" })).click();
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(DETAILS.path));
    expect(await within(card).findByText("Its path is copied.")).toBeInTheDocument();

    // Play sits on the picture.
    within(card).getByRole("button", { name: "Play" }).click();
    const player = await screen.findByRole("region", { name: "Player" });
    expect(player).toHaveTextContent("The Harbour Line · S01E01");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(sent(fetch, "POST", "/player")).toHaveLength(1));
  });

  it("goes along the episode map by the arrow keys, one stop for the keyboard", async () => {
    renderTitle(HARBOUR);

    const map = await screen.findByRole("region", { name: "Episode map" });
    const squares = within(map).getAllByRole("button");
    expect(squares.filter((square) => square.tabIndex === 0)).toHaveLength(1);
    const first = squares[0] as HTMLElement;
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(document.activeElement).toBe(squares[1]);
    fireEvent.keyDown(squares[1] as HTMLElement, { key: "End" });
    expect(document.activeElement).toHaveAccessibleName("S04E32 · episode 71 · Episode 32 · ready");
    expect(squares.filter((square) => square.tabIndex === 0)).toEqual([squares.at(-1)]);
  });

  it("says an episode still to come isn't out yet", async () => {
    renderTitle(
      {
        ...HARBOUR,
        episodes: [
          ...HARBOUR.episodes,
          {
            season: 4,
            number: 33,
            name: "Next Week",
            aired: "2099-01-01",
            state: "upcoming",
            fileId: null,
          },
        ],
      },
      undefined,
      null,
      {
        "/titles/1/episodes/4/33": {
          season: 4,
          number: 33,
          name: "Next Week",
          aired: "2099-01-01",
          overview: null,
          minutes: 24,
          fileId: null,
        },
      },
    );

    (await screen.findByTitle("S04E33 · episode 72 · Next Week · still to air")).click();

    const card = await screen.findByRole("dialog", { name: "S04E33 · Next Week" });
    expect(await within(card).findByText("Not out yet")).toBeInTheDocument();
    expect(card).toHaveTextContent("Airs 1 Jan 2099 · 24 min");
  });

  it("opens with the card itself in focus, and gives the focus back once it closes", async () => {
    renderTitle(HARBOUR, undefined, null, { "/files/1": DETAILS });

    const name = await screen.findByRole("button", { name: "Episode 1" });
    name.focus();
    name.click();
    const card = await screen.findByRole("dialog", { name: "S01E01 · The Arrival" });
    // Not its cross: nothing in it looks picked before anything is.
    await waitFor(() => expect(document.activeElement).toBe(card));
    fireEvent.keyDown(card, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(document.activeElement).toBe(name));
  });

  it("tells of an episode the library lacks, from the map and from the lists", async () => {
    renderTitle(HARBOUR, undefined, null, {
      "/titles/1/episodes/4/11": {
        season: 4,
        number: 11,
        name: "The Night Ferry",
        aired: "1991-01-01",
        overview: "Five strangers board at midnight.",
        minutes: 24,
        fileId: null,
      },
      "/titles/1/episodes/0/2": {
        season: 0,
        number: 2,
        name: "Fog Over the Bay",
        aired: "1993-08-06",
        overview: null,
        minutes: 52,
        fileId: null,
      },
    });

    const map = await screen.findByRole("region", { name: "Episode map" });
    within(map).getByTitle("S04E11 · episode 50 · The Night Ferry · missing").click();
    let card = await screen.findByRole("dialog", { name: "S04E11 · The Night Ferry" });
    expect(await within(card).findByText("Not in your library")).toBeInTheDocument();
    expect(card).toHaveTextContent("Aired 1 Jan 1991 · 24 min");
    expect(within(card).getByRole("button", { name: "Show what happens" })).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Play" })).not.toBeInTheDocument();
    within(card).getByRole("button", { name: "Close" }).click();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    // The same episode from the list of what's missing, then a special from its own.
    screen.getByRole("button", { name: /Episode 50 · The Night Ferry · missing/ }).click();
    card = await screen.findByRole("dialog", { name: "S04E11 · The Night Ferry" });
    within(card).getByRole("button", { name: "Close" }).click();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    screen.getByRole("button", { name: /Fog Over the Bay/ }).click();
    card = await screen.findByRole("dialog", { name: "S00E02 · Fog Over the Bay" });
    expect(await within(card).findByText("Not in your library")).toBeInTheDocument();
    expect(card).toHaveTextContent("Special · S00E02");
    expect(
      within(card).queryByRole("button", { name: "Show what happens" }),
    ).not.toBeInTheDocument();
    // A special goes on among the specials.
    expect(
      within(card).getByRole("button", { name: "Previous: S00E01 · The Lighthouse" }),
    ).toBeVisible();
    expect(within(card).queryByRole("button", { name: /^Next/ })).not.toBeInTheDocument();
  });

  it("goes to the episode before or after it from its card, the keyboard keeping its place", async () => {
    renderTitle(HARBOUR, undefined, null, {
      "/titles/1/episodes/4/11": {
        season: 4,
        number: 11,
        name: "The Night Ferry",
        aired: "1991-01-01",
        overview: "Five strangers board at midnight.",
        minutes: 24,
        fileId: null,
      },
      "/titles/1/episodes/4/12": {
        season: 4,
        number: 12,
        name: "Episode 12",
        aired: "1991-01-08",
        overview: "A stranger asks the way.",
        minutes: 24,
        fileId: null,
      },
    });

    const map = await screen.findByRole("region", { name: "Episode map" });
    within(map).getByTitle("S04E11 · episode 50 · The Night Ferry · missing").click();
    const card = await screen.findByRole("dialog", { name: "S04E11 · The Night Ferry" });
    expect(
      within(card).getByRole("button", { name: "Previous: S04E10 · Episode 10" }),
    ).toBeVisible();
    within(card).getByRole("button", { name: "Show what happens" }).click();
    const next = within(card).getByRole("button", { name: "Next: S04E12 · Episode 12" });
    next.focus();
    next.click();

    expect(await screen.findByRole("dialog", { name: "S04E12 · Episode 12" })).toBe(card);
    expect(document.activeElement).toBe(next);
    expect(next).toHaveAccessibleName("Next: S04E13 · Episode 13");
    // The next episode's story is hidden again till asked.
    expect(await within(card).findByRole("button", { name: "Show what happens" })).toBeVisible();
    expect(card).not.toHaveTextContent("A stranger asks the way.");
    within(card).getByRole("button", { name: "Previous: S04E11 · The Night Ferry" }).click();
    expect(await screen.findByRole("dialog", { name: "S04E11 · The Night Ferry" })).toBe(card);
  });

  it("keeps the keyboard's place in the card: its story's button, its menu, its last step", async () => {
    renderTitle(HARBOUR, undefined, null, {
      "/files/1": DETAILS,
      "/files/9": { ...DETAILS, id: 9, season: 0, episode: 1, episodeName: "The Lighthouse" },
      "/titles/1/episodes/0/2": {
        season: 0,
        number: 2,
        name: "Fog Over the Bay",
        aired: "1993-08-06",
        overview: null,
        minutes: 52,
        fileId: null,
      },
    });
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    const name = await screen.findByRole("button", { name: "Episode 1" });
    name.focus();
    name.click();
    let card = await screen.findByRole("dialog", { name: "S01E01 · The Arrival" });
    // Shown and hidden again, the focus staying on the button as it turns.
    const show = await within(card).findByRole("button", { name: "Show what happens" });
    show.focus();
    show.click();
    await waitFor(() => expect(document.activeElement).toHaveAccessibleName("Hide what happens"));
    // The card's own menu, then Escape: the focus goes back to what opened the card.
    fireEvent.keyDown(within(card).getByRole("button", { name: "More for S01E01" }), {
      key: "Enter",
    });
    (await screen.findByRole("menuitem", { name: "Copy path" })).click();
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    fireEvent.keyDown(card, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(document.activeElement).toBe(name));

    // The specials' first, then on to their last: the focus moves to the step that's left.
    screen.getByRole("button", { name: /The Lighthouse/ }).click();
    card = await screen.findByRole("dialog", { name: "S00E01 · The Lighthouse" });
    const next = within(card).getByRole("button", { name: "Next: S00E02 · Fog Over the Bay" });
    next.focus();
    next.click();
    await screen.findByRole("dialog", { name: "S00E02 · Fog Over the Bay" });
    await waitFor(() =>
      expect(document.activeElement).toHaveAccessibleName("Previous: S00E01 · The Lighthouse"),
    );
  });

  it("goes through the title's videos in the page's order from a video's card", async () => {
    const second = video(2, 1, 2, "The Harbour Line - S01E02");
    renderTitle({ ...HARBOUR, videos: [...HARBOUR.videos, second] }, undefined, null, {
      "/files/1": DETAILS,
      "/files/2": { ...DETAILS, id: 2, episode: 2, episodeName: "The Search", path: second.path },
    });

    await fromMenu("More for S01E01", "Details");
    const card = await screen.findByRole("dialog", { name: "S01E01 · The Arrival" });
    expect(within(card).queryByRole("button", { name: /^Previous/ })).not.toBeInTheDocument();
    within(card).getByRole("button", { name: "Next: S01E02 · Episode 2" }).click();

    expect(await screen.findByRole("dialog", { name: "S01E02 · The Search" })).toBe(card);
    expect(
      within(card).getByRole("button", { name: "Previous: S01E01 · Episode 1" }),
    ).toBeVisible();
  });

  it("shows a picture from the episode across the top of its card, Play on it", async () => {
    showsPictures();
    const stopped = { ...(HARBOUR.videos[0] as TitleDetail["videos"][number]), resume: 610 };
    renderTitle({ ...HARBOUR, videos: [stopped] }, undefined, null, {
      "/files/1": DETAILS,
      "/files/1/picture": () => picture("show"),
    });

    await fromMenu("More for S01E01", "Details");
    const card = await screen.findByRole("dialog", { name: "S01E01 · The Arrival" });

    await waitFor(() =>
      expect(card.querySelector("img")?.getAttribute("src")).toBe("blob:the-picture"),
    );
    // The show's picture gives nothing away: it isn't blurred.
    expect(card.querySelector("img")).not.toHaveClass("blur-2xl");
    expect(
      within(card).queryByRole("button", { name: "Show the picture" }),
    ).not.toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Play from 10:10" })).toBeVisible();
    expect(card).toHaveTextContent("The Harbour Line · aired 26 Apr 1989 · 14 min left");
  });

  it("blurs a picture from an episode not yet watched till asked", async () => {
    showsPictures();
    const seen = { ...(HARBOUR.videos[0] as TitleDetail["videos"][number]), id: 2, watched: true };
    renderTitle(
      { ...HARBOUR, videos: [...HARBOUR.videos, { ...seen, episode: 2 }] },
      undefined,
      null,
      {
        "/files/1": DETAILS,
        "/files/1/picture": () => picture("episode"),
        "/files/2": { ...DETAILS, id: 2, episode: 2, episodeName: "The Search" },
        "/files/2/picture": () => picture("episode"),
        "/titles/1/episodes/4/11": {
          season: 4,
          number: 11,
          name: "The Night Ferry",
          aired: "1991-01-01",
          overview: null,
          minutes: 24,
          fileId: null,
        },
        "/titles/1/episodes/4/11/picture": () => picture("episode"),
      },
    );

    // Not watched: blurred, Play still on it, till "Show the picture".
    await fromMenu("More for S01E01", "Details");
    let card = await screen.findByRole("dialog", { name: "S01E01 · The Arrival" });
    const show = await within(card).findByRole("button", { name: "Show the picture" });
    expect(card.querySelector("img")).toHaveClass("blur-2xl");
    expect(within(card).getByRole("button", { name: "Play" })).toBeVisible();
    show.focus();
    show.click();
    await waitFor(() => expect(card.querySelector("img")).not.toHaveClass("blur-2xl"));
    // The keyboard stays on it, turned to hide it again.
    expect(document.activeElement).toHaveAccessibleName("Hide the picture");
    within(card).getByRole("button", { name: "Hide the picture" }).click();
    await waitFor(() => expect(card.querySelector("img")).toHaveClass("blur-2xl"));
    within(card).getByRole("button", { name: "Show the picture" }).click();
    await waitFor(() => expect(card.querySelector("img")).not.toHaveClass("blur-2xl"));

    // Watched: there's no story left to give away.
    within(card).getByRole("button", { name: "Next: S01E02 · Episode 2" }).click();
    card = await screen.findByRole("dialog", { name: "S01E02 · The Search" });
    await waitFor(() => expect(card.querySelector("img")).toBeInTheDocument());
    expect(card.querySelector("img")).not.toHaveClass("blur-2xl");
    within(card).getByRole("button", { name: "Close" }).click();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    // An episode the library hasn't got has never been watched.
    const map = screen.getByRole("region", { name: "Episode map" });
    within(map).getByTitle("S04E11 · episode 50 · The Night Ferry · missing").click();
    card = await screen.findByRole("dialog", { name: "S04E11 · The Night Ferry" });
    expect(await within(card).findByRole("button", { name: "Show the picture" })).toBeVisible();
    expect(card.querySelector("img")).toHaveClass("blur-2xl");
  });

  it("says why a video won't play in its details, and offers no Play", async () => {
    const broken = HARBOUR.videos[0];
    if (!broken) throw new Error("The Harbour Line has a video.");
    renderTitle(
      { ...HARBOUR, videos: [{ ...broken, problem: "No video stream" }] },
      undefined,
      null,
      {
        "/files/1": { ...DETAILS, problem: "No video stream", picture: null },
      },
    );

    await fromMenu("More for S01E01", "Details");

    const card = await screen.findByRole("dialog", { name: "S01E01 · The Arrival" });
    expect(await within(card).findByText("It won't play: No video stream")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Play" })).not.toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Show in folder" })).toBeInTheDocument();
  });
});
