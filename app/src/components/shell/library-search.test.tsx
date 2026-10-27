import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EngineProvider, type Found } from "@/lib/engine";
import { fakeEngine, READY } from "@/test/engine";
import { LibrarySearch } from "./library-search";

const shell = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => {} }));

const LANTERN: Found = {
  titles: [
    {
      id: 3,
      name: "Starfall Academy: The Lantern Festival",
      kind: "movie",
      year: 2022,
      hasPoster: false,
      also: null,
    },
  ],
  episodes: [
    {
      titleId: 1,
      title: "Starfall Academy",
      season: 1,
      number: 2,
      name: "Lanterns Over the Lake",
      fileId: 2,
      coming: false,
    },
    {
      titleId: 1,
      title: "Starfall Academy",
      season: 1,
      number: 9,
      name: "The Last Lantern",
      fileId: null,
      coming: false,
    },
  ],
  files: [
    {
      fileId: 5,
      path: "D:\\Videos\\Downloads\\lantern_extras_01.mkv",
      titleId: null,
      title: null,
      season: null,
      episode: null,
      episodeEnd: null,
      place: "match",
    },
    {
      fileId: 8,
      path: "D:\\Videos\\Extras\\Lantern Trailer.mkv",
      titleId: null,
      title: null,
      season: null,
      episode: null,
      episodeEnd: null,
      place: "extra",
    },
    {
      fileId: 7,
      path: "D:\\Videos\\Starfall Academy\\Season 01\\[Lantern] Starfall Academy - 04.mkv",
      titleId: 1,
      title: "Starfall Academy",
      season: 1,
      episode: 4,
      episodeEnd: null,
      place: "title",
    },
  ],
  totalTitles: 1,
  totalEpisodes: 14,
  totalFiles: 3,
};

const NOTHING: Found = {
  titles: [],
  episodes: [],
  files: [],
  totalTitles: 0,
  totalEpisodes: 0,
  totalFiles: 0,
};

/** Where the search led: the page's address, and whether it was asked to show the videos. */
function Where() {
  const location = useLocation();
  const state = location.state as { videos?: boolean } | null;
  return (
    <p>
      At {location.pathname}
      {location.search}
      {state?.videos ? " · videos" : ""}
    </p>
  );
}

function renderSearch() {
  shell.invoke.mockImplementation(async (command: string) =>
    command === "engine_status" ? READY : undefined,
  );
  const fetch = fakeEngine({
    "/search": (_: unknown, url: URL) =>
      url.searchParams.get("q")?.toLowerCase().includes("lantern") ? LANTERN : NOTHING,
  });
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <EngineProvider>
        <MemoryRouter initialEntries={["/"]}>
          <LibrarySearch />
          <Routes>
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </EngineProvider>
    </QueryClientProvider>,
  );
  return {
    fetch,
    field: screen.getByRole("combobox", { name: "Search titles, episodes or files" }),
  };
}

describe("LibrarySearch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    shell.invoke.mockReset();
  });

  it("lists the titles, episodes and videos a search finds, each kind's closest first", async () => {
    const { field } = renderSearch();

    fireEvent.change(field, { target: { value: "lantern" } });

    const found = await screen.findByRole("listbox", { name: "Found in the library" });
    expect(field).toHaveAttribute("aria-expanded", "true");
    const groups = await within(found).findAllByRole("group");
    expect(groups).toEqual([
      within(found).getByRole("group", { name: "Titles" }),
      within(found).getByRole("group", { name: "Episodes" }),
      within(found).getByRole("group", { name: "Videos" }),
    ]);
    expect(groups[0]).toHaveTextContent("Starfall Academy: The Lantern FestivalMovie · 2022");
    expect(groups[1]).toHaveTextContent("2 of 14");
    expect(groups[1]).toHaveTextContent("S01E02 · Lanterns Over the LakeStarfall Academy");
    expect(groups[1]).toHaveTextContent("S01E09 · The Last LanternStarfall AcademyNot in library");
    expect(groups[2]).toHaveTextContent("lantern_extras_01.mkvD:\\Videos\\DownloadsNeeds a match");
    expect(groups[2]).toHaveTextContent(
      "Lantern Trailer.mkvD:\\Videos\\ExtrasExtra · show in folder",
    );
    // What the list says is beside it, not among what can be chosen.
    expect(screen.getByRole("status")).toHaveTextContent("Type more to narrow it down.");
    expect(within(found).queryByRole("status")).not.toBeInTheDocument();
  });

  it("opens what's chosen with the keyboard: an episode on its title's videos", async () => {
    const { field } = renderSearch();
    fireEvent.change(field, { target: { value: "lantern" } });
    await screen.findByRole("option", { name: /Lanterns Over the Lake/ });

    fireEvent.keyDown(field, { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: /Lanterns Over the Lake/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    fireEvent.keyDown(field, { key: "Enter" });

    expect(await screen.findByText("At /titles/1?q=S01E02 · videos")).toBeInTheDocument();
    expect(field).toHaveValue("");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("leads a title to its page, a video to its title's videos, one waiting to its match", async () => {
    const { field } = renderSearch();
    const pick = async (name: RegExp) => {
      fireEvent.change(field, { target: { value: "lantern" } });
      fireEvent.click(await screen.findByRole("option", { name }));
    };

    await pick(/The Lantern Festival/);
    expect(await screen.findByText("At /titles/3")).toBeInTheDocument();
    await pick(/Starfall Academy - 04/);
    expect(
      await screen.findByText(
        `At /titles/1?q=${encodeURIComponent("[Lantern] Starfall Academy - 04.mkv")} · videos`,
      ),
    ).toBeInTheDocument();
    await pick(/lantern_extras_01/);
    expect(await screen.findByText("At /match")).toBeInTheDocument();
    // An episode the library lacks leads to its title's page.
    await pick(/The Last Lantern/);
    expect(await screen.findByText("At /titles/1")).toBeInTheDocument();
  });

  it("opens nothing with Enter till the list answers what's typed, nor once it's closed", async () => {
    const { field } = renderSearch();
    fireEvent.change(field, { target: { value: "lantern" } });
    await screen.findByRole("option", { name: /Lanterns Over the Lake/ });

    // Typed on, the list is still the last search's: Enter waits for the new one.
    fireEvent.change(field, { target: { value: "lantern fes" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(screen.getByText("At /")).toBeInTheDocument();
    // Closed with Escape, Enter opens nothing.
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /The Lantern Festival/ })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
    fireEvent.keyDown(field, { key: "Escape" });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(screen.getByText("At /")).toBeInTheDocument();
  });

  it("shows an extra in its folder, as Maku files it under no title", async () => {
    const { field } = renderSearch();
    fireEvent.change(field, { target: { value: "lantern" } });

    fireEvent.click(await screen.findByRole("option", { name: /Lantern Trailer/ }));

    await waitFor(() =>
      expect(shell.invoke).toHaveBeenCalledWith("show_in_folder", {
        path: "D:\\Videos\\Extras\\Lantern Trailer.mkv",
      }),
    );
    expect(screen.getByText("At /")).toBeInTheDocument();
  });

  it("says when the engine didn't answer", async () => {
    const { field } = renderSearch();
    fakeEngine({ "/search": () => Response.json({ detail: "It stopped." }, { status: 500 }) });

    fireEvent.change(field, { target: { value: "lantern" } });

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Maku's engine didn't answer. Try again in a moment.",
      ),
    );
  });

  it("says when nothing goes by it, waits for two letters, and Escape closes then clears", async () => {
    const { fetch, field } = renderSearch();

    fireEvent.change(field, { target: { value: "k" } });
    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(fetch.mock.calls.some(([input]) => String(input).includes("/search"))).toBe(false);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

    fireEvent.change(field, { target: { value: "Kestrel" } });
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Nothing in the library goes by “Kestrel”.",
      ),
    );
    fireEvent.keyDown(field, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
    expect(field).toHaveValue("Kestrel");
    fireEvent.keyDown(field, { key: "Escape" });
    expect(field).toHaveValue("");
  });
});
