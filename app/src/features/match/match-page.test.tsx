import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PlayerLayer } from "@/features/player/player";
import { PlayerProvider } from "@/features/player/player-context";
import { EngineProvider, type Guess, type WaitingFile } from "@/lib/engine";
import { fakeEngine, NO_TMDB_KEY, READY, TMDB_KEY } from "@/test/engine";
import { MatchPage } from "./match-page";

const shell = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => {} }));
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({ setFullscreen: async () => {} }),
}));

const ORCHARD: Guess = {
  entryId: 6,
  title: "Glass Orchard",
  kind: "series",
  year: 1998,
  episodes: 26,
  minutes: 24,
  cover: null,
  confidence: 41,
  reasons: ["The 6 Glass Orchard files in this folder share the [subs] tag"],
};
const HARBOUR: Guess = {
  ...ORCHARD,
  entryId: 1,
  title: "The Harbour Line",
  confidence: 38,
  reasons: [],
};
/** What the engine says to a search without a TMDB key. */
const NO_KEY = "Maku needs your TMDB key to find series and films: add it in Settings.";

function waiting(id: number, episode: number, alike: number[] = []): WaitingFile {
  return {
    id,
    path: `D:\\Videos\\Downloads\\[subs] ep0${episode} final.mkv`,
    size: 233_000_000,
    minutes: 24.17,
    height: 480,
    codec: "h264",
    audio: ["jpn", "eng"],
    subtitles: ["eng"],
    group: "subs",
    title: null,
    season: null,
    episode,
    kind: "episode",
    guesses: [ORCHARD, HARBOUR],
    alike,
  };
}

const QUEUE = [waiting(3, 3, [4, 5]), waiting(4, 4, [3, 5]), waiting(5, 5, [3, 4])];
const DELETED = { planId: 12, moved: 0, quarantined: 1, problems: [] };

function sent(fetch: ReturnType<typeof fakeEngine>, method: string, path: string) {
  return fetch.mock.calls.filter(
    ([input, init]) => (init?.method ?? "GET") === method && String(input).includes(path),
  );
}

/** The notice a line of it is in: it tells as a status, as Maku's notices do. */
function keyNotice(line: HTMLElement): HTMLElement {
  const notice = line.closest<HTMLElement>("[role=status]");
  if (!notice) throw new Error("The TMDB key's line isn't in a status notice.");
  return notice;
}

/** Opens a row's "More" menu as a keyboard does, and picks one of its items. */
async function fromMenu(menu: string, item: string) {
  fireEvent.keyDown(await screen.findByRole("button", { name: menu }), { key: "Enter" });
  (await screen.findByRole("menuitem", { name: item })).click();
}

function renderMatch(at = "/match") {
  shell.invoke.mockImplementation(async (command: string) =>
    command === "engine_status" ? READY : undefined,
  );
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <EngineProvider>
        <PlayerProvider>
          <MemoryRouter initialEntries={[at]}>
            <Routes>
              <Route path="/match" element={<MatchPage />} />
              <Route path="/titles/:id" element={<ShownTitle />} />
              <Route path="/settings/:section" element={<ShownSettings />} />
              <Route path="*" element={<p>Home</p>} />
            </Routes>
          </MemoryRouter>
          <PlayerLayer />
        </PlayerProvider>
      </EngineProvider>
    </QueryClientProvider>,
  );
}

function ShownTitle() {
  const waiting = (useLocation().state as { waiting?: number } | null)?.waiting;
  return (
    <p>
      Title {useParams().id}
      {waiting !== undefined && `, ${waiting} waiting`}
    </p>
  );
}

function ShownSettings() {
  return <p>Settings › {useParams().section}</p>;
}

describe("MatchPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    shell.invoke.mockReset();
  });

  it("shows the file, what reading it showed, and Maku's best guesses", async () => {
    fakeEngine({ "/review": QUEUE });
    renderMatch();

    expect(
      await screen.findByRole("heading", { name: "[subs] ep03 final.mkv" }),
    ).toBeInTheDocument();
    expect(screen.getByText("File 1 of 3")).toBeInTheDocument();
    expect(screen.getByText("24:10")).toBeInTheDocument();
    expect(screen.getByText("480p · H.264")).toBeInTheDocument();
    expect(screen.getByText("Japanese, English")).toBeInTheDocument();
    expect(screen.getByText("[subs]")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Glass Orchard \(1998\)/ })).toBeChecked();
    expect(screen.getByText("41%")).toBeInTheDocument();
    expect(screen.getByText("Use this for the 2 other [subs] files here")).toBeInTheDocument();
    expect(screen.getByText("Episodes 04 and 05, numbered from their names")).toBeInTheDocument();
    // Maku couldn't tell whether there's a TMDB key (it wasn't answered): no notice about it.
    expect(screen.queryByText(/needs your TMDB key/)).not.toBeInTheDocument();
  });

  it("plays the file to tell what it is, from the start or from a still", async () => {
    const opened = {
      ticket: "T1",
      missing: null,
      drive: "D:",
      duration: 1450,
      sound: [],
      subtitles: [],
      chapters: [],
      chosenSound: null,
      chosenSubtitles: null,
      ready: [],
    };
    const fetch = fakeEngine({ "/review": QUEUE, "POST /player": opened });
    renderMatch();

    (await screen.findByRole("button", { name: "Play from 12:05" })).click();

    const player = await screen.findByRole("region", { name: "Player" });
    expect(player).toHaveTextContent("[subs] ep03 final.mkv");
    expect(player).toHaveTextContent("From the still at 12:05");
    await waitFor(() => {
      const src = player.querySelector("video")?.getAttribute("src") ?? "";
      expect(src).toContain("/stream/T1?at=725.100");
    });
    screen.getByRole("button", { name: "Play it" }).click();
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Player" })).toHaveTextContent(
        "D:\\Videos\\Downloads",
      ),
    );
    expect(sent(fetch, "POST", "/player").length).toBeGreaterThanOrEqual(2);
  });

  it("confirms the choice for the file and the ones like it", async () => {
    const fetch = fakeEngine({ "/review": QUEUE, "POST /review/3": { placed: 3 } });
    renderMatch();

    (await screen.findByRole("button", { name: "Confirm Glass Orchard, episode 3" })).click();

    await waitFor(() => expect(sent(fetch, "POST", "/review/3")).toHaveLength(1));
    const [[, init]] = sent(fetch, "POST", "/review/3") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ entryId: 6, kind: "episode", also: [4, 5] });
  });

  it("picks another guess with its number key, and the kind with the switch", async () => {
    const fetch = fakeEngine({ "/review": QUEUE, "POST /review/3": { placed: 1 } });
    renderMatch();
    await screen.findByRole("radio", { name: /Glass Orchard/ });

    fireEvent.keyDown(window, { key: "2" });
    await waitFor(() =>
      expect(screen.getByRole("radio", { name: /The Harbour Line/ })).toBeChecked(),
    );
    screen.getByRole("radio", { name: "Special or extra" }).click();
    screen.getByRole("checkbox").click();
    (await screen.findByRole("button", { name: "Confirm The Harbour Line" })).click();

    await waitFor(() => expect(sent(fetch, "POST", "/review/3")).toHaveLength(1));
    const [[, init]] = sent(fetch, "POST", "/review/3") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ entryId: 1, kind: "special", also: [] });
  });

  it("asks which episode a file is when its name doesn't say", async () => {
    const dvd: WaitingFile = {
      ...waiting(7, 1),
      path: "D:\\Videos\\Old DVDs\\VTS_01_1.VOB",
      episode: null,
      kind: "dvd",
    };
    const fetch = fakeEngine({ "/review": [dvd], "POST /review/7": { placed: 1 } });
    renderMatch();

    const number = await screen.findByRole("textbox", { name: "Which episode" });
    expect(screen.getByRole("button", { name: "Confirm Glass Orchard" })).toBeInTheDocument();
    fireEvent.change(number, { target: { value: "15x0" } });
    (await screen.findByRole("button", { name: "Confirm Glass Orchard, episode 150" })).click();

    await waitFor(() => expect(sent(fetch, "POST", "/review/7")).toHaveLength(1));
    const [[, init]] = sent(fetch, "POST", "/review/7") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({
      entryId: 6,
      kind: "episode",
      also: [],
      episode: 150,
    });
  });

  it("searches when none of the guesses is right", async () => {
    fakeEngine({
      "/review": QUEUE,
      "/review/3/search": [
        { ...ORCHARD, entryId: 99, title: "Glass Orchard Returns", confidence: 70 },
      ],
    });
    renderMatch();

    fireEvent.change(
      await screen.findByRole("searchbox", { name: "Search for the right series or film" }),
      { target: { value: "Glass Orchard Returns" } },
    );

    expect(await screen.findByRole("radio", { name: /Glass Orchard Returns/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Found" })).toBeInTheDocument();
  });

  it("says why it can't search without a TMDB key", async () => {
    fakeEngine({
      "/review": QUEUE,
      "/review/3/search": () => Response.json({ detail: NO_KEY }, { status: 409 }),
    });
    renderMatch();

    fireEvent.change(
      await screen.findByRole("searchbox", { name: "Search for the right series or film" }),
      { target: { value: "Glass Orchard Returns" } },
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(NO_KEY);
  });

  it("skips to the next file, and sets aside what isn't a series or film", async () => {
    const fetch = fakeEngine({ "/review": QUEUE, "POST /review/4/ignore": null });
    renderMatch();

    (await screen.findByRole("button", { name: "Skip for now" })).click();
    expect(
      await screen.findByRole("heading", { name: "[subs] ep04 final.mkv" }),
    ).toBeInTheDocument();
    screen.getByRole("button", { name: "Not a series or film: set it aside" }).click();

    await waitFor(() => expect(sent(fetch, "POST", "/review/4/ignore")).toHaveLength(1));
  });

  it("keeps going round the files that were skipped", async () => {
    fakeEngine({ "/review": QUEUE });
    renderMatch();

    for (const shown of ["ep03", "ep04", "ep05", "ep03", "ep04"]) {
      expect(
        await screen.findByRole("heading", { name: `[subs] ${shown} final.mkv` }),
      ).toBeInTheDocument();
      screen.getByRole("button", { name: "Skip for now" }).click();
    }
  });

  it("searches once the owner stops typing", async () => {
    const fetch = fakeEngine({
      "/review": QUEUE,
      "/review/3/search": [
        { ...ORCHARD, entryId: 99, title: "Glass Orchard Returns", confidence: 70 },
      ],
    });
    renderMatch();
    const box = await screen.findByRole("searchbox", {
      name: "Search for the right series or film",
    });

    for (const typed of ["Gl", "Gla", "Glas", "Glass", "Glass O"]) {
      fireEvent.change(box, { target: { value: typed } });
    }

    expect(await screen.findByRole("radio", { name: /Glass Orchard Returns/ })).toBeInTheDocument();
    expect(sent(fetch, "GET", "/review/3/search")).toHaveLength(1);
  });

  it("changes a title's match for all its files, then shows where they went", async () => {
    const fetch = fakeEngine({
      "/review": [{ ...waiting(3, 1, [4, 5]), guesses: [HARBOUR, ORCHARD] }],
      "/titles/1": { name: "The Harbour Line" },
      "POST /review/3": { placed: 2, waiting: 1, titleId: 8 },
    });
    renderMatch("/match?title=1");

    expect(await screen.findByText("All 3 files of The Harbour Line")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "The Harbour Line" })).toHaveAttribute(
      "href",
      "/titles/1",
    );
    expect(screen.getByText("Use this for its other 2 files")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Skip for now" })).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("button", { name: "More for this file" }), { key: "Enter" });
    expect(await screen.findByRole("menuitem", { name: "Show in folder" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Delete…" })).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(fetch.mock.calls.some(([input]) => String(input).endsWith("/review?title=1"))).toBe(
      true,
    );
    fireEvent.keyDown(window, { key: "2" });
    (await screen.findByRole("button", { name: "Confirm Glass Orchard, episode 1" })).click();

    expect(await screen.findByText("Title 8, 1 waiting")).toBeInTheDocument();
    const [[, init]] = sent(fetch, "POST", "/review/3") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({
      entryId: ORCHARD.entryId,
      kind: "episode",
      title: 1,
    });
  });

  it("deletes the file on screen once asked, says so, and puts it back", async () => {
    let gone: number[] = []; // once deleted, the files waiting come back without them
    const fetch = fakeEngine({
      "/review": () => QUEUE.filter((file) => !gone.includes(file.id)),
      "POST /files/delete": (init?: RequestInit) => {
        gone = (JSON.parse(String(init?.body)) as { files: number[] }).files;
        return DELETED;
      },
      "POST /plans/12/undo": () => {
        gone = [];
        return { ...DELETED, moved: 1, quarantined: 0 };
      },
    });
    renderMatch();

    await fromMenu("More for this file", "Delete…");
    const asking = await screen.findByRole("group", { name: "Delete this file?" });
    await waitFor(() =>
      expect(asking).toHaveTextContent(
        "1 video (233 MB) goes to the quarantine on D:, with any subtitles named after it. " +
          "They're deleted for good after 30 days; till then History puts them back.",
      ),
    );
    within(asking).getByRole("button", { name: "Delete 1 video" }).click();

    expect(await screen.findByText("Deleted 1 video.")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "[subs] ep04 final.mkv" }),
    ).toBeInTheDocument();
    const [[, init]] = sent(fetch, "POST", "/files/delete") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ files: [3] });
    screen.getByRole("button", { name: "Put back" }).click();

    expect(
      await screen.findByRole("heading", { name: "[subs] ep03 final.mkv" }),
    ).toBeInTheDocument();
    expect(sent(fetch, "POST", "/plans/12/undo")).toHaveLength(1);
  });

  it("deletes a file further on from what's up next, and can be talked out of it", async () => {
    const fetch = fakeEngine({ "/review": QUEUE, "POST /files/delete": DELETED });
    renderMatch();

    await fromMenu("More for [subs] ep04 final.mkv", "Delete…");
    (await screen.findByRole("button", { name: "Cancel" })).click();
    await waitFor(() =>
      expect(screen.queryByRole("group", { name: "Delete this file?" })).not.toBeInTheDocument(),
    );
    await fromMenu("More for [subs] ep05 final.mkv", "Delete…");
    const asking = await screen.findByRole("group", { name: "Delete this file?" });
    within(asking).getByRole("button", { name: "Delete 1 video" }).click();

    await waitFor(() => expect(sent(fetch, "POST", "/files/delete")).toHaveLength(1));
    const [[, init]] = sent(fetch, "POST", "/files/delete") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ files: [5] });
    expect(screen.getByRole("heading", { name: "[subs] ep03 final.mkv" })).toBeInTheDocument();
  });

  it("offers the last file back once it's deleted", async () => {
    let gone = false;
    fakeEngine({
      "/review": () => (gone ? [] : [waiting(3, 3)]),
      "POST /files/delete": () => {
        gone = true;
        return DELETED;
      },
    });
    renderMatch();

    await fromMenu("More for this file", "Delete…");
    (await screen.findByRole("button", { name: "Delete 1 video" })).click();

    expect(
      await screen.findByRole("heading", { name: "Every file is matched" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Deleted 1 video.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Put back" })).toBeInTheDocument();
  });

  it("lists the files set aside as not a series or film, to match after all or delete", async () => {
    let ignored = [
      { id: 9, path: "D:\\Videos\\Specials\\Special 07.mp4", size: 250_000_000 },
      { id: 10, path: "D:\\Videos\\Specials\\Special 08.mp4", size: 27_000_000 },
    ];
    const fetch = fakeEngine({
      "/review": [],
      "/review/ignored": () => ignored,
      "DELETE /review/10/ignore": () => {
        ignored = ignored.filter((file) => file.id !== 10);
        return null;
      },
      "POST /files/delete": () => {
        ignored = ignored.filter((file) => file.id !== 9);
        return DELETED;
      },
    });
    renderMatch();

    expect(
      await screen.findByRole("heading", { name: "Set aside: not a series or film" }),
    ).toBeInTheDocument();
    expect(screen.getByText("D:\\Videos\\Specials · 250 MB")).toBeInTheDocument();
    screen.getByRole("button", { name: "Match it: Special 08.mp4" }).click();
    await waitFor(() => expect(screen.queryByText("Special 08.mp4")).not.toBeInTheDocument());
    expect(sent(fetch, "DELETE", "/review/10/ignore")).toHaveLength(1);

    await fromMenu("More for Special 07.mp4", "Delete…");
    const asking = await screen.findByRole("group", { name: "Delete this file?" });
    within(asking).getByRole("button", { name: "Delete 1 video" }).click();

    expect(await screen.findByText("Deleted 1 video.")).toBeInTheDocument();
    const [[, init]] = sent(fetch, "POST", "/files/delete") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ files: [9] });
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Set aside: not a series or film" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("shows a file in its folder, copies its path, and says when Explorer can't", async () => {
    fakeEngine({ "/review": QUEUE });
    renderMatch();
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    await fromMenu("More for this file", "Show in folder");
    await waitFor(() =>
      expect(shell.invoke).toHaveBeenCalledWith("show_in_folder", { path: QUEUE[0]?.path }),
    );
    await fromMenu("More for [subs] ep04 final.mkv", "Copy path");
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(QUEUE[1]?.path));
    expect(await screen.findByText("Its path is copied.")).toBeInTheDocument();

    shell.invoke.mockImplementation(async (command: string) => {
      if (command === "engine_status") return READY;
      if (command === "show_in_folder") throw "Windows can't find D:\\Videos\\Downloads.";
      return undefined;
    });
    await fromMenu("More for this file", "Show in folder");
    expect(await screen.findByText(/Windows can't find/)).toBeInTheDocument();
  });

  it("says when every file is matched", async () => {
    const fetch = fakeEngine({ "/review": [], "/tmdb": TMDB_KEY });
    renderMatch();

    expect(
      await screen.findByRole("heading", { name: "Every file is matched" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Maku knows which series or film each video is/)).toBeInTheDocument();
    await waitFor(() => expect(sent(fetch, "GET", "/tmdb").length).toBeGreaterThan(0));
    expect(screen.queryByText(/needs your TMDB key/)).not.toBeInTheDocument();
    screen.getByRole("button", { name: "Go to Home" }).click();
    expect(await screen.findByText("Home")).toBeInTheDocument();
  });

  it("says Maku needs the TMDB key while files wait, and leads to it", async () => {
    fakeEngine({ "/review": QUEUE, "/tmdb": NO_TMDB_KEY });
    renderMatch();

    const notice = keyNotice(await screen.findByText(/needs your TMDB key/));
    expect(notice).toHaveTextContent(
      "Maku needs your TMDB key to find your series and films. Your videos are read, and wait for it.",
    );
    expect(screen.getByRole("heading", { name: "[subs] ep03 final.mkv" })).toBeInTheDocument();
    within(notice).getByRole("button", { name: "Add your key" }).click();

    expect(await screen.findByText("Settings › titles")).toBeInTheDocument();
  });

  it("doesn't say every file is matched when nothing could be looked up", async () => {
    fakeEngine({ "/review": [], "/tmdb": NO_TMDB_KEY });
    renderMatch();

    expect(
      await screen.findByRole("heading", { name: "Nothing to match yet" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/once it can look them up on TMDB/)).toBeInTheDocument();
    expect(keyNotice(screen.getByText(/needs your TMDB key/))).toHaveTextContent("Add your key");
    expect(
      screen.queryByRole("heading", { name: "Every file is matched" }),
    ).not.toBeInTheDocument();
    // The notice holds the one way on: the empty state has no button of its own.
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Add your key",
    ]);
  });

  it("says nothing of the key once there is one", async () => {
    const fetch = fakeEngine({ "/review": QUEUE, "/tmdb": TMDB_KEY });
    renderMatch();

    expect(
      await screen.findByRole("heading", { name: "[subs] ep03 final.mkv" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(sent(fetch, "GET", "/tmdb").length).toBeGreaterThan(0));
    expect(screen.queryByText(/needs your TMDB key/)).not.toBeInTheDocument();
  });
});
