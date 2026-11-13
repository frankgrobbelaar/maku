import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  type ComingEpisode,
  EngineProvider,
  type EngineStatus,
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
} from "@/test/engine";
import { dayWords } from "./coming-up";
import { LibraryPage } from "./library-page";

const shell = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => {} }));

const FOLDER = {
  id: 1,
  path: "D:\\Videos",
  addedAt: "2026-10-11T09:30:00+00:00",
  available: true,
  files: 314,
  unread: 0,
  problems: 0,
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
const SHELF = [
  STARFALL_COLLECTION,
  franchiseOf([HARBOUR_LINE]),
  franchiseOf([GLASS_ORCHARD]),
  franchiseOf([NORTHWIND]),
];

/** The day `from` days after today (before it, for less than 0), as the engine writes it. */
function day(from: number): string {
  const when = new Date();
  when.setDate(when.getDate() + from);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`;
}

/** An episode of a show out `from` days after today, none of it in the library unless said. */
function out(
  titleId: number,
  title: string,
  from: number,
  more: Partial<ComingEpisode> = {},
): ComingEpisode {
  return {
    titleId,
    title,
    kind: "series",
    hasPoster: false,
    season: 1,
    number: 5,
    last: 5,
    name: "The Café at Dawn",
    aired: day(from),
    episodes: 1,
    held: 0,
    ...more,
  };
}

/** Two shows' last weeks and what's to come: missing, held, a season half held, out today, a
 * special and an episode still to air. */
const COMING: ComingEpisode[] = [
  out(1, "The Harbour Line", -9, { number: 4, last: 4, name: "Fog Signals" }),
  out(2, "Glass Orchard", -9, { number: 2, last: 2, name: "Grafting", held: 1 }),
  out(2, "Glass Orchard", -1, { season: 2, number: 1, last: 8, name: null, episodes: 8, held: 5 }),
  out(1, "The Harbour Line", 0, { number: 6, last: 6, name: "Breakwater" }),
  out(2, "Glass Orchard", 1, { season: 0, number: 1, last: 1, name: "A Short Story" }),
  out(1, "The Harbour Line", 9, { number: 7, last: 7, name: "Undertow" }),
];

/** The engine's answers for a library with a folder in it, scanned. */
function engineWith(answers: Record<string, unknown> = {}) {
  return fakeEngine({
    "/settings": SETTINGS,
    "/folders": [FOLDER],
    "/library": { ...NO_LIBRARY, folders: 1, files: 314, size: 9e10 },
    "/scan": { ...NO_SCAN, state: "done", stage: "done" },
    "/franchises": SHELF,
    "/coming": [],
    ...answers,
  });
}

function asked(fetch: ReturnType<typeof fakeEngine>, ending: string): boolean {
  return fetch.mock.calls.some(([input]) => String(input).endsWith(ending));
}

/** Where a link led, and with what in the address. */
function Where({ name }: { name: string }) {
  const { search } = useLocation();
  return <p>{`${name}${search}`}</p>;
}

function renderLibrary(at = "/library", engine: EngineStatus = READY) {
  shell.invoke.mockImplementation(async (command: string) =>
    command === "engine_status" ? engine : undefined,
  );
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <EngineProvider>
        <MemoryRouter initialEntries={[at]}>
          <Routes>
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/titles/:id" element={<Where name="A title" />} />
            <Route path="/franchises/:id" element={<p>A collection</p>} />
            <Route path="/match" element={<p>Match</p>} />
            <Route path="/scan" element={<p>Scan</p>} />
            <Route path="/settings/:section" element={<p>Settings</p>} />
          </Routes>
        </MemoryRouter>
      </EngineProvider>
    </QueryClientProvider>,
  );
}

describe("LibraryPage", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    shell.invoke.mockReset();
  });

  it("lists the series and films oldest release first, each saying what it is", async () => {
    const fetch = engineWith({
      "/franchises": [
        franchiseOf([HARBOUR_LINE]),
        STARFALL_COLLECTION,
        franchiseOf([GLASS_ORCHARD]),
      ],
    });
    renderLibrary();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Library");
    expect(
      await screen.findByText("3 on the shelf · by type, oldest release first"),
    ).toBeInTheDocument();
    expect(screen.getByText("TV series · 2004 · 291 episodes")).toBeInTheDocument();
    expect(screen.getByText("4 missing")).toBeInTheDocument();
    expect(screen.getByText("287 of 291 · 99%")).toBeInTheDocument();
    expect(screen.getByText("TV series · 2018 · 26 episodes")).toBeInTheDocument();
    expect(screen.getByText("26 of 26 · complete")).toBeInTheDocument();
    expect(screen.getByText("Collection · 2 movies")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Release date" })).toBeChecked();
    expect(asked(fetch, "/franchises?sort=released")).toBe(true);

    screen.getByRole("radio", { name: "Name" }).click();
    await waitFor(() => expect(asked(fetch, "/franchises?sort=name")).toBe(true));
    expect(await screen.findByText("3 on the shelf · by type, then name")).toBeInTheDocument();

    (await screen.findByRole("link", { name: /The Starfall Collection/ })).click();
    expect(await screen.findByText("A collection")).toBeInTheDocument();
  });

  it("opens in the order its address asks for, as Home's most missing first does", async () => {
    const fetch = engineWith();
    renderLibrary("/library?sort=missing");

    expect(await screen.findByText("4 on the shelf · most missing first")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Most missing" })).toBeChecked();
    expect(asked(fetch, "/franchises?sort=missing")).toBe(true);
    // An order that looks across every type lists everything together.
    expect(screen.queryAllByRole("heading", { level: 3 })).toEqual([]);
  });

  it("lists collections first, then what stands on its own, by type", async () => {
    engineWith({
      "/franchises": [franchiseOf([NORTHWIND]), STARFALL_COLLECTION, franchiseOf([GLASS_ORCHARD])],
    });
    renderLibrary();

    const [collections, series, movies] = await screen.findAllByRole("heading", { level: 3 });

    expect([collections, series, movies].map((heading) => heading?.textContent)).toEqual([
      "Collections 1",
      "Series 1",
      "Movies 1",
    ]);
  });

  it("finds a collection by its name or any of its films', and says when nothing is", async () => {
    engineWith({
      "/franchises": [
        franchiseOf([STARFALL, ASCENT], "The Starfall Collection"),
        franchiseOf([GLASS_ORCHARD]),
      ],
    });
    renderLibrary();

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
    engineWith({ "/franchises": [franchiseOf([HARBOUR_LINE])] });
    renderLibrary();

    (await screen.findByRole("link", { name: /The Harbour Line/ })).click();

    expect(await screen.findByText("A title")).toBeInTheDocument();
  });

  it("lays the series' episodes along the days they air, under the series", async () => {
    engineWith({ "/coming": COMING });
    renderLibrary();

    const coming = await screen.findByRole("region", { name: "Coming up" });
    const said = [
      "The Harbour LineS01E04 · Fog SignalsMissing",
      "Glass OrchardS01E02 · GraftingIn your library",
      "Glass OrchardS02E01–E08 · 8 episodes5 of 8 in your library",
      "The Harbour LineS01E06 · BreakwaterOut today",
      "Glass OrchardSpecial 1 · A Short StoryStill to air",
      "The Harbour LineS01E07 · UndertowStill to air",
    ];
    const shows = within(coming).getAllByRole("listitem");
    expect(shows).toHaveLength(said.length);
    shows.forEach((show, at) => {
      expect(show).toHaveTextContent(said[at] ?? "");
    });
    // A day says itself once, over its shows, the last four weeks before today.
    expect(within(coming).getAllByText(dayWords(day(-9)))).toHaveLength(1);
    expect(coming).toHaveTextContent(
      new RegExp(`${dayWords(day(-9))}.*Yesterday.*Today.*Tomorrow.*${dayWords(day(9))}`),
    );
    // Under the series' heading, before their cards, and above the films.
    const series = screen.getByRole("heading", { level: 3, name: /^Series/ });
    const movies = screen.getByRole("heading", { level: 3, name: /^Movies/ });
    const card = screen.getByText("TV series · 2004 · 291 episodes");
    expect(series.compareDocumentPosition(coming) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(coming.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(coming.compareDocumentPosition(movies) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(coming).getByRole("button", { name: "Earlier" })).toBeInTheDocument();
    expect(within(coming).getByRole("button", { name: "Later" })).toBeInTheDocument();
  });

  it("opens an episode the library has on its title's page, searched for it", async () => {
    engineWith({ "/coming": COMING });
    renderLibrary();

    const coming = await screen.findByRole("region", { name: "Coming up" });
    const [missing, held] = within(coming).getAllByRole("link");
    expect(missing).toHaveAttribute("href", "/titles/1");
    expect(held).toHaveAttribute("href", "/titles/2?q=S01E02");

    held?.click();
    expect(await screen.findByText("A title?q=S01E02")).toBeInTheDocument();
  });

  it("says the new day's Today once midnight comes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(2026, 10, 13, 23, 59, 30));
    engineWith({
      "/coming": [
        out(1, "The Harbour Line", 0, { number: 6, last: 6, name: "Breakwater" }),
        out(1, "The Harbour Line", 1, { number: 7, last: 7, name: "Undertow" }),
      ],
    });
    renderLibrary();

    const coming = await screen.findByRole("region", { name: "Coming up" });
    expect(coming).toHaveTextContent(/Today.*Breakwater.*Out today.*Tomorrow.*Undertow/);
    await act(() => vi.advanceTimersByTimeAsync(60_000));

    expect(screen.getByRole("region", { name: "Coming up" })).toHaveTextContent(
      /Yesterday.*Breakwater.*Missing.*Today.*Undertow.*Out today/,
    );
  });

  it("puts Coming up at the top when the shelf isn't by type", async () => {
    engineWith({ "/coming": COMING });
    renderLibrary("/library?sort=added");

    const coming = await screen.findByRole("region", { name: "Coming up" });
    const card = await screen.findByText("TV series · 2004 · 291 episodes");

    expect(coming.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryAllByRole("heading", { level: 3 })).toEqual([]);
  });

  it("narrows Coming up with the shelf's search", async () => {
    engineWith({ "/coming": COMING });
    renderLibrary();

    await screen.findByRole("region", { name: "Coming up" });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search the shelf" }), {
      target: { value: "harbour" },
    });

    await waitFor(() =>
      expect(
        within(screen.getByRole("region", { name: "Coming up" })).getAllByRole("listitem"),
      ).toHaveLength(3),
    );
    fireEvent.change(screen.getByRole("searchbox", { name: "Search the shelf" }), {
      target: { value: "northwind" },
    });
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Coming up" })).not.toBeInTheDocument(),
    );
  });

  it("says when the shelf is empty, and adds a folder from there", async () => {
    engineWith({ "/folders": [], "/library": NO_LIBRARY, "/franchises": [] });
    renderLibrary();

    expect(await screen.findByRole("heading", { name: "Your shelf is empty" })).toBeVisible();
    expect(screen.getByText("No folders yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a folder" })).toBeEnabled();
  });

  it("says nothing is on the shelf yet, and leads to the files to match", async () => {
    engineWith({
      "/franchises": [],
      "/scan": { ...NO_SCAN, state: "done", stage: "done", waiting: 2 },
    });
    renderLibrary();

    expect(await screen.findByRole("heading", { name: "No series or films yet" })).toBeVisible();
    expect(screen.getByText("Nothing on the shelf yet.")).toBeInTheDocument();
    screen.getByRole("button", { name: "Match 2 files" }).click();

    expect(await screen.findByText("Match")).toBeInTheDocument();
  });

  it("says Maku needs the TMDB key while nothing is on the shelf", async () => {
    engineWith({ "/franchises": [], "/tmdb": NO_TMDB_KEY });
    renderLibrary();

    expect(
      await screen.findByText("Maku needs your TMDB key to find your series and films."),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No series or films yet" })).toBeVisible();
  });

  it("says when the engine couldn't answer, and asks again", async () => {
    let asks = 0;
    engineWith({
      "/franchises": () => {
        asks += 1;
        return asks === 1
          ? Response.json({ detail: "The database is locked." }, { status: 503 })
          : SHELF;
      },
    });
    renderLibrary();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Maku couldn't load this screen. The database is locked. Nothing in your folders was touched.",
    );
    screen.getByRole("button", { name: "Try again" }).click();

    expect(
      await screen.findByText("4 on the shelf · by type, oldest release first"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
