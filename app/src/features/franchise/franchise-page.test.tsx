import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ShelfCard } from "@/components/title-card";
import {
  EngineProvider,
  type FranchiseMissing,
  type FranchiseSummary,
  type MissingTitle,
  type TitleSummary,
} from "@/lib/engine";
import { fakeEngine, franchiseOf, READY } from "@/test/engine";
import { FranchisePage } from "./franchise-page";

const shell = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => {} }));

const STARFALL: TitleSummary = {
  id: 7,
  kind: "movie",
  name: "Starfall",
  year: 2014,
  released: "2014-11-07",
  airing: false,
  hasPoster: false,
  files: 1,
  added: "2026-10-11T09:44:00+00:00",
  aired: 0,
  present: 0,
  missing: 0,
  specialsMissing: 0,
  upcoming: 0,
};
const STARFALL_II: TitleSummary = {
  ...STARFALL,
  id: 8,
  name: "Starfall II",
  year: 2017,
  released: "2017-05-19",
};
const ASCENT: TitleSummary = {
  ...STARFALL,
  id: 9,
  name: "Starfall: Ascent",
  year: 2021,
  released: "2021-12-17",
};
const COLLECTION = franchiseOf([STARFALL, STARFALL_II, ASCENT], "The Starfall Collection");

/** A series on its own: a collection never holds one. */
const HARBOUR_LINE: TitleSummary = {
  ...STARFALL,
  id: 3,
  kind: "series",
  name: "The Harbour Line",
  year: 2019,
  released: "2019-09-12",
  files: 24,
  aired: 24,
  present: 24,
};

// What TMDB keeps in the collection that the library has none of.
const ORIGINS: MissingTitle = {
  entryId: -3010,
  kind: "movie",
  name: "Starfall: Origins",
  year: 2010,
  released: "2010-06-11",
  episodes: null,
  coming: false,
  airing: false,
  cover: "/starfall-origins.jpg",
  overview: null,
  genres: [],
  studio: null,
  tmdbType: "movie",
  tmdbId: 3010,
};
const LAST_LIGHT: MissingTitle = {
  ...ORIGINS,
  entryId: -3024,
  name: "Starfall: Last Light",
  year: 2024,
  released: "2024-03-01",
  cover: "/starfall-last-light.jpg",
  tmdbId: 3024,
};
const HOMECOMING: MissingTitle = {
  ...ORIGINS,
  entryId: -3030,
  name: "Starfall: Homecoming",
  year: null,
  released: null,
  coming: true,
  cover: null,
  tmdbId: 3030,
};

function renderWithEngine(children: React.ReactNode, at: string) {
  shell.invoke.mockImplementation(async (command: string) =>
    command === "engine_status" ? READY : undefined,
  );
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <EngineProvider>
        <MemoryRouter initialEntries={[at]}>
          <Routes>
            <Route path="/franchises/:id" element={children} />
            <Route path="/titles/:id" element={<p>A title</p>} />
            <Route path="*" element={<p>Home</p>} />
          </Routes>
        </MemoryRouter>
      </EngineProvider>
    </QueryClientProvider>,
  );
  return queries;
}

/** The cards on the page, in the order they show. */
function cards() {
  return within(screen.getByRole("region", { name: "Films" }))
    .getAllByRole("listitem")
    .map((card) => card.textContent);
}

afterEach(() => {
  vi.unstubAllGlobals();
  shell.invoke.mockReset();
});

describe("ShelfCard", () => {
  it.each<[string, FranchiseSummary, string]>([
    ["a series on its own", franchiseOf([HARBOUR_LINE]), "TV series · 2019 · 24 episodes"],
    ["a film on its own", franchiseOf([STARFALL]), "Movie · 2014"],
    ["the films of a collection", COLLECTION, "Collection · 3 movies"],
    [
      "an older record's series with its film",
      franchiseOf([HARBOUR_LINE, STARFALL]),
      "TV series · 24 episodes · 1 movie",
    ],
  ])("says what %s is", (_, franchise, facts) => {
    fakeEngine({});
    renderWithEngine(<ShelfCard franchise={franchise} />, "/franchises/1");

    expect(screen.getByText(facts)).toBeInTheDocument();
  });
});

describe("FranchisePage", () => {
  it("shows the collection and its films, oldest release first", async () => {
    const fetch = fakeEngine({ "/franchises/7": COLLECTION });
    renderWithEngine(<FranchisePage />, "/franchises/7");

    expect(
      await screen.findByRole("heading", { name: "The Starfall Collection", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByText("Collection")).toBeInTheDocument();
    expect(screen.getByText("2014 to 2021 · 3 movies")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Films", level: 2 })).toBeInTheDocument();
    // One kind only: no headings by type, and none in the words.
    expect(screen.getByText("3 films · oldest release first")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3 })).not.toBeInTheDocument();
    expect(screen.queryByText(/episodes/)).not.toBeInTheDocument(); // films have none
    const links = screen.getAllByRole("link", { name: /Starfall/ });
    expect(links.map((card) => card.textContent)).toEqual([
      expect.stringContaining("Movie · 2014"),
      expect.stringContaining("Movie · 2017"),
      expect.stringContaining("Movie · 2021"),
    ]);
    expect(fetch.mock.calls.some(([input]) => String(input).endsWith("?sort=released"))).toBe(true);
  });

  it("calls them titles, by type, where an older record mixes a series in", async () => {
    fakeEngine({ "/franchises/3": franchiseOf([HARBOUR_LINE, STARFALL], "The Harbour Line") });
    renderWithEngine(<FranchisePage />, "/franchises/3");

    expect(await screen.findByRole("heading", { name: "Titles", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("2 titles · by type, oldest release first")).toBeInTheDocument();
    expect(
      screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent),
    ).toEqual(["Series 1", "Movies 1"]);
  });

  it("lists every film together when what's new comes first, and never sorts films by missing", async () => {
    fakeEngine({ "/franchises/7": COLLECTION });
    renderWithEngine(<FranchisePage />, "/franchises/7");

    (await screen.findByRole("radio", { name: "Recently added" })).click();

    expect(await screen.findByText("3 films · newest added first")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3 })).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Most missing" })).not.toBeInTheDocument();
  });

  it("sorts by name too, and leads to each film", async () => {
    const fetch = fakeEngine({ "/franchises/7": COLLECTION });
    renderWithEngine(<FranchisePage />, "/franchises/7");

    (await screen.findByRole("radio", { name: "Name" })).click();
    await waitFor(() =>
      expect(fetch.mock.calls.some(([input]) => String(input).endsWith("?sort=name"))).toBe(true),
    );
    expect(await screen.findByText("3 films · by name")).toBeInTheDocument();
    screen.getByRole("link", { name: /Ascent/ }).click();

    expect(await screen.findByText("A title")).toBeInTheDocument();
  });

  it("puts in the films the library has none of, in their places, when asked", async () => {
    fakeEngine({
      "/franchises/7": COLLECTION,
      "/franchises/7/missing": { titles: [ORIGINS, LAST_LIGHT, HOMECOMING], looking: false },
    });
    renderWithEngine(<FranchisePage />, "/franchises/7");

    const toggle = await screen.findByRole("button", { name: "Missing films 3" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByText("Not in library")).not.toBeInTheDocument();
    toggle.click();

    expect(await screen.findByText("3 of 6 films · oldest release first")).toBeVisible();
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(cards()).toEqual([
      expect.stringMatching(/Not in library.*Starfall: Origins.*Movie · 2010$/),
      expect.stringContaining("Movie · 2014"), // Starfall, the library's
      expect.stringContaining("Movie · 2017"), // Starfall II, the library's
      expect.stringContaining("Movie · 2021"), // Starfall: Ascent, the library's
      expect.stringMatching(/Not in library.*Starfall: Last Light.*Movie · 2024$/),
      expect.stringMatching(/Coming.*Starfall: Homecoming/), // undated, last
    ]);
    // Maku has no page for a film it doesn't have.
    expect(
      screen.queryByRole("link", { name: /Origins|Last Light|Homecoming/ }),
    ).not.toBeInTheDocument();

    toggle.click();
    expect(await screen.findByText("3 films · oldest release first")).toBeVisible();
    expect(screen.queryByText("Not in library")).not.toBeInTheDocument();
  });

  it("finds films by name, the ones it lacks too, and keeps the search with them", async () => {
    fakeEngine({
      "/franchises/7": COLLECTION,
      "/franchises/7/missing": { titles: [ORIGINS, LAST_LIGHT], looking: false },
    });
    renderWithEngine(<FranchisePage />, "/franchises/7?missing");

    const search = await screen.findByRole("searchbox", { name: "Search The Starfall Collection" });
    expect(search).toHaveAttribute("placeholder", "Search 5 films");
    fireEvent.change(search, { target: { value: "as" } });

    expect(await screen.findByText("2 of 5 films · oldest release first")).toBeVisible();
    expect(cards()).toEqual([
      expect.stringContaining("Starfall: Ascent"),
      expect.stringMatching(/Not in library.*Starfall: Last Light/),
    ]);
    // Taking the films it lacks away keeps the search.
    screen.getByRole("button", { name: "Missing films 2" }).click();
    expect(await screen.findByText("1 of 3 films · oldest release first")).toBeVisible();
    expect(search).toHaveValue("as");

    fireEvent.change(search, { target: { value: "Harbour" } });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "No film in The Starfall Collection goes by “Harbour”.",
    );
  });

  it("says what the collection is about and the years it spans", async () => {
    fakeEngine({
      "/franchises/7": COLLECTION,
      "/titles/7/about": {
        overview: "A pilot crash-lands on a world with two suns.",
        genres: [],
        studio: null,
        status: "finished",
        started: "2014-11-07",
        ended: null,
        minutes: 128,
        tmdbType: "movie",
        tmdbId: 3014,
      },
    });
    renderWithEngine(<FranchisePage />, "/franchises/7");

    const header = await screen.findByRole("region", { name: "The Starfall Collection" });
    expect(header).toHaveTextContent("2014 to 2021 · 3 movies");
    expect(await within(header).findByText(/A pilot crash-lands/)).toBeVisible();
  });

  it("opens a film the library lacks to say what TMDB knows of it", async () => {
    const fetch = fakeEngine({
      "/franchises/7": COLLECTION,
      "/franchises/7/missing": {
        titles: [
          {
            ...LAST_LIGHT,
            overview: "The last ship leaves the dying star.",
            genres: ["Science Fiction", "Adventure"],
            studio: "Northlight Pictures",
          },
        ],
        looking: false,
      },
    });
    renderWithEngine(<FranchisePage />, "/franchises/7?missing");

    const card = await screen.findByRole("button", {
      name: "Starfall: Last Light: not in library",
    });
    // A long name wraps rather than trails off, and says itself in full on hover.
    expect(within(card).getByText("Starfall: Last Light")).toHaveClass("line-clamp-2");
    // TMDB's poster, through the engine.
    const poster = `/artwork?address=${encodeURIComponent("/starfall-last-light.jpg")}`;
    await waitFor(() =>
      expect(fetch.mock.calls.some(([input]) => String(input).includes(poster))).toBe(true),
    );
    card.click();

    const details = await screen.findByRole("dialog", { name: "Starfall: Last Light" });
    expect(details).toHaveTextContent("Movie · 2024");
    expect(details).toHaveTextContent("Not in your library");
    expect(details).toHaveTextContent("StudioNorthlight Pictures");
    expect(within(details).getByRole("list", { name: "Genres" })).toHaveTextContent(
      "Science FictionAdventure",
    );
    expect(details).toHaveTextContent("The last ship leaves the dying star.");
    expect(details).toHaveTextContent(
      "TMDB counts it in The Starfall Collection. It's here so you know the collection has it.",
    );
    // Its page on TMDB is the one place to read more.
    expect(within(details).getAllByRole("button", { name: /^On / })).toHaveLength(1);
    within(details).getByRole("button", { name: "On TMDB" }).click();
    await waitFor(() =>
      expect(shell.invoke).toHaveBeenCalledWith("open_tmdb_page", { kind: "movie", id: 3024 }),
    );

    within(details).getByRole("button", { name: "Close" }).click();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("says when TMDB has no synopsis of a film it lacks", async () => {
    fakeEngine({
      "/franchises/7": COLLECTION,
      "/franchises/7/missing": { titles: [HOMECOMING], looking: false },
    });
    renderWithEngine(<FranchisePage />, "/franchises/7?missing");

    (await screen.findByRole("button", { name: "Starfall: Homecoming: coming" })).click();

    const details = await screen.findByRole("dialog", { name: "Starfall: Homecoming" });
    expect(details).toHaveTextContent("Coming");
    expect(details).toHaveTextContent("TMDB has no synopsis of it yet.");
  });

  it("opens with the films it lacks put in, when a film's page leads here", async () => {
    fakeEngine({
      "/franchises/7": COLLECTION,
      "/franchises/7/missing": { titles: [LAST_LIGHT], looking: false },
    });
    renderWithEngine(<FranchisePage />, "/franchises/7?missing");

    expect(await screen.findByText("3 of 4 films · oldest release first")).toBeVisible();
    expect(screen.getByRole("button", { name: "Missing films 1" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Not in library")).toBeVisible();
  });

  it("is a film alone in the library's own page for what its collection lacks", async () => {
    fakeEngine({
      "/franchises/7": franchiseOf([STARFALL]),
      "/franchises/7/missing": { titles: [LAST_LIGHT], looking: false },
    });
    renderWithEngine(<FranchisePage />, "/franchises/7");

    expect(await screen.findByText("1 film · oldest release first")).toBeVisible();
    expect(screen.getByText("Movie")).toBeVisible(); // what it is, not "Collection"
    expect(screen.queryByText("Collection")).not.toBeInTheDocument();
    screen.getByRole("button", { name: "Missing films 1" }).click();
    expect(await screen.findByText("1 of 2 films · oldest release first")).toBeVisible();

    (await screen.findByRole("button", { name: "Starfall: Last Light: not in library" })).click();
    expect(await screen.findByRole("dialog", { name: "Starfall: Last Light" })).toHaveTextContent(
      "TMDB keeps it in one collection with Starfall. It's here so you know the collection has it.",
    );
  });

  it("lists the films it lacks after its own when what's in the library comes first", async () => {
    fakeEngine({
      "/franchises/7": COLLECTION,
      "/franchises/7/missing": { titles: [ORIGINS], looking: false },
    });
    renderWithEngine(<FranchisePage />, "/franchises/7");

    (await screen.findByRole("radio", { name: "Recently added" })).click();
    (await screen.findByRole("button", { name: "Missing films 1" })).click();

    expect(await screen.findByText("3 of 4 films · newest added first")).toBeVisible();
    // Out before the rest, but after the library's own in this order.
    expect(screen.getAllByRole("listitem").at(-1)).toHaveTextContent("Starfall: Origins");
  });

  it("says it's still looking the rest of the collection up", async () => {
    fakeEngine({
      "/franchises/7": COLLECTION,
      "/franchises/7/missing": { titles: [], looking: true },
    });
    renderWithEngine(<FranchisePage />, "/franchises/7");

    (await screen.findByRole("button", { name: "Missing films …" })).click();

    expect(
      await screen.findByText("3 of 3 films · still looking up the rest · oldest release first"),
    ).toBeVisible();
  });

  it("offers no missing films once the library has the whole collection", async () => {
    let rest: FranchiseMissing = { titles: [LAST_LIGHT], looking: false };
    fakeEngine({ "/franchises/7": COLLECTION, "/franchises/7/missing": () => rest });
    const queries = renderWithEngine(<FranchisePage />, "/franchises/7");
    (await screen.findByRole("button", { name: "Missing films 1" })).click();
    expect(await screen.findByText("3 of 4 films · oldest release first")).toBeVisible();

    // A scan finds the last one, and every screen asks again.
    rest = { titles: [], looking: false };
    await act(async () => {
      await queries.invalidateQueries();
    });

    expect(await screen.findByText("3 films · oldest release first")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Missing films/ })).not.toBeInTheDocument();
  });

  it("shows the page's shape while it loads", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );
    renderWithEngine(<FranchisePage />, "/franchises/7");

    expect(
      await screen.findByRole("status", { name: "Loading the collection" }),
    ).toBeInTheDocument();
  });

  it("says when the engine couldn't find it", async () => {
    fakeEngine({});
    renderWithEngine(<FranchisePage />, "/franchises/99");

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument(); // no shapes once it failed
    screen.getByRole("link", { name: "Library" }).click();
    expect(await screen.findByText("Home")).toBeInTheDocument();
  });
});
