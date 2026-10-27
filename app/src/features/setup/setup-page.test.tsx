import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  EngineProvider,
  type EngineStatus,
  type LibraryFolder,
  type Settings,
  type System,
  type Tool,
} from "@/lib/engine";
import { fakeEngine, NO_SCAN, READY, SETTINGS, SYSTEM, UNCHECKED } from "@/test/engine";
import { SetupPage } from "./setup-page";

const shell = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => {} }));

const DATA_DIR = "C:\\Users\\you\\AppData\\Local\\Maku";
const TMDB_KEY = "a-read-access-token-ending-in-ab12";
const VIDEOS: LibraryFolder = {
  id: 1,
  path: "D:\\Videos",
  addedAt: "2026-10-11T09:30:00+00:00",
  available: true,
  files: 0,
  unread: 0,
  problems: 0,
};
const FFMPEG: Tool = {
  id: "ffmpeg",
  name: "ffmpeg",
  version: "9.0.2",
  purpose: "Reads what each video holds, and converts it.",
  licence: "LGPL-2.1-or-later",
  size: 76_972_461,
  when: "setup",
  state: "missing",
  done: 0,
  problem: null,
};
/** A speech model, fetched the first time subtitles are asked for: not on the Tools step. */
const WHISPER: Tool = {
  id: "speech-best",
  name: "Whisper medium",
  version: "fp16 d397824",
  purpose: "OpenAI's speech model, for English subtitles at Best.",
  licence: "MIT",
  size: 1_530_853_088,
  when: "asked",
  state: "missing",
  done: 0,
  problem: null,
};

/** A first run: no folders yet, recommended settings, ffmpeg still to fetch. */
function firstRun(overrides: Record<string, unknown> = {}) {
  const library = {
    folders: [] as LibraryFolder[],
    settings: { ...SETTINGS, setUp: false },
    tmdb: { connected: false, keyEnd: null as string | null },
  };
  return fakeEngine({
    "/health": { status: "ok", version: "0.1.0", dataDir: DATA_DIR, schemaVersion: 3 },
    "/folders": () => library.folders,
    "POST /folders": (init?: RequestInit) => {
      const { path } = JSON.parse(String(init?.body)) as { path: string };
      library.folders = [{ ...VIDEOS, path }];
      return library.folders[0];
    },
    "/settings": () => library.settings,
    "PUT /settings": (init?: RequestInit) => {
      library.settings = JSON.parse(String(init?.body)) as Settings;
      return library.settings;
    },
    "/tools": [FFMPEG],
    "POST /tools/ffmpeg/download": { ...FFMPEG, state: "downloading" },
    "/system": UNCHECKED,
    "/tmdb": () => library.tmdb,
    "PUT /tmdb": (init?: RequestInit) => {
      const { key } = JSON.parse(String(init?.body)) as { key: string };
      if (key !== TMDB_KEY) {
        return Response.json({ detail: "TMDB didn't accept this key." }, { status: 400 });
      }
      library.tmdb = { connected: true, keyEnd: key.slice(-4) };
      return library.tmdb;
    },
    "/scan": NO_SCAN,
    "POST /scan": { ...NO_SCAN, state: "running", stage: "finding" },
    ...overrides,
  });
}

function renderSetup(step?: string, engine: EngineStatus = READY) {
  shell.invoke.mockImplementation(async (command: string) => {
    if (command === "engine_status") return engine;
    if (command === "pick_folder") return "D:\\Videos";
    return undefined;
  });
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <EngineProvider>
        <MemoryRouter initialEntries={[step ? `/setup?step=${step}` : "/setup"]}>
          <Routes>
            <Route path="/setup" element={<SetupPage />} />
            <Route path="/scan" element={<p>The scan</p>} />
          </Routes>
        </MemoryRouter>
      </EngineProvider>
    </QueryClientProvider>,
  );
}

function sent(fetch: ReturnType<typeof firstRun>, method: string, path: string) {
  return fetch.mock.calls.filter(
    ([input, init]) => (init?.method ?? "GET") === method && String(input).endsWith(path),
  );
}

describe("SetupPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    shell.invoke.mockReset();
  });

  it("walks through the data folder, the video folders, the TMDB key and the standard", async () => {
    const fetch = firstRun();
    renderSetup();

    expect(screen.getByRole("heading", { name: "Welcome to Maku" })).toBeInTheDocument();
    expect(screen.getByText(/^Five quick steps\./)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Setup steps" })).toHaveTextContent(
      "1Your data2Your folders3Your TMDB key4Your standard5Tools and this PC",
    );
    // Still to come, the key says what it's for.
    expect(
      screen.getByText("Maku finds your series and films on TMDB, with your own free key."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/look up titles, episode lists and artwork on TMDB,/),
    ).toBeInTheDocument();
    expect(await screen.findByText(DATA_DIR)).toBeInTheDocument();
    expect(screen.getByText(/Your videos never go here\./)).toBeInTheDocument();
    screen.getByRole("button", { name: "Continue" }).click();

    expect(await screen.findByRole("heading", { name: "Your video folders" })).toBeInTheDocument();
    expect(
      screen.getByText(
        /A folder can hold many series and films in any layout, even mixed together/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    screen.getByRole("button", { name: "Add a folder" }).click();
    expect(await screen.findByRole("button", { name: "Remove D:\\Videos" })).toBeInTheDocument();
    expect(shell.invoke).toHaveBeenCalledWith("pick_folder", {
      title: "Choose a folder with series or films in it",
    });
    screen.getByRole("button", { name: "Continue" }).click();

    // Without a key Maku finds nothing, so it has a step of its own; it can wait.
    expect(
      await screen.findByRole("heading", { name: "Find your series and films" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Maku finds your series and films on TMDB, with your own free key. Without one, it reads your videos but can't tell what they are.",
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("No key yet? Skip for now, and add it later in Settings."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    screen.getByRole("button", { name: "Skip for now" }).click();

    expect(
      await screen.findByRole("heading", { name: "Choose your standard" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Skipped for now: Maku can't find your series and films till you add it"),
    ).toBeInTheDocument();
    expect(sent(fetch, "PUT", "/tmdb")).toHaveLength(0);
    const smaller = screen.getByRole("radio", { name: /^1080p/ });
    smaller.click();
    await waitFor(() => expect(smaller).toBeChecked());
    const keep = screen.getByRole("radio", { name: "Keep my names" });
    keep.click();
    await waitFor(() => expect(keep).toBeChecked());
    expect(screen.getByText(/Files keep their names/)).toBeInTheDocument();
    screen.getByRole("button", { name: "Continue" }).click();

    // The tools step is on screen once its own button is.
    expect(await screen.findByRole("button", { name: "Start the first scan" })).toBeInTheDocument();
    const [[, put]] = sent(fetch, "PUT", "/settings") as [[unknown, RequestInit]];
    expect(JSON.parse(String(put.body))).toMatchObject({
      standard: "1080p",
      naming: "keep",
      setUp: false,
    });
  });

  it("says why a folder can't be added", async () => {
    firstRun({
      "POST /folders": () =>
        Response.json({ detail: "D:\\Videos is already in your library." }, { status: 400 }),
    });
    renderSetup("folders");

    (await screen.findByRole("button", { name: "Add a folder" })).click();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "D:\\Videos is already in your library.",
    );
  });

  it("says when the engine isn't running, and offers to try again", async () => {
    firstRun();
    renderSetup(undefined, { state: "failed", message: "It stopped unexpectedly.", details: "" });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Maku's engine isn't running. It stopped unexpectedly. Nothing in your folders was touched.",
    );
    screen.getByRole("button", { name: "Try again" }).click();

    expect(shell.invoke).toHaveBeenCalledWith("restart_engine");
  });

  it("says when the engine couldn't answer, and asks again", async () => {
    let asked = 0;
    firstRun({
      "/tools": () => {
        asked += 1;
        return asked === 1 ? new Response("Internal Server Error", { status: 500 }) : [FFMPEG];
      },
    });
    renderSetup("tools");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Maku couldn't load this screen. The engine answered 500 to GET /tools.",
    );
    screen.getByRole("button", { name: "Try again" }).click();

    expect(await screen.findByRole("button", { name: "Download" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("checks a TMDB key with TMDB, then shows it connected and goes on", async () => {
    const fetch = firstRun();
    renderSetup("tmdb");

    const field = await screen.findByLabelText("TMDB API Read Access Token");
    fireEvent.change(field, { target: { value: "not the key" } });
    screen.getByRole("button", { name: "Connect" }).click();
    expect(await screen.findByRole("alert")).toHaveTextContent("TMDB didn't accept this key.");

    fireEvent.change(field, { target: { value: TMDB_KEY } });
    screen.getByRole("button", { name: "Connect" }).click();

    expect(await screen.findByText("Key ending ab12 · kept on this PC only")).toBeInTheDocument();
    expect(sent(fetch, "PUT", "/tmdb")).toHaveLength(2);
    expect(screen.getByText("You can change or remove it later in Settings.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Skip for now" })).not.toBeInTheDocument();
    const next = screen.getByRole("button", { name: "Continue" });
    expect(next).toBeEnabled();
    next.click();

    expect(
      await screen.findByRole("heading", { name: "Choose your standard" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Connected · key ending ab12")).toBeInTheDocument();
  });

  it("asks for the TMDB key on its own step, not with the tools", async () => {
    firstRun({ "/tools": [{ ...FFMPEG, state: "ready", done: FFMPEG.size }] });
    renderSetup("tools");

    expect(await screen.findByRole("button", { name: "Start the first scan" })).toBeInTheDocument();
    expect(await screen.findByText("ffmpeg")).toBeInTheDocument();
    expect(screen.queryByLabelText("TMDB API Read Access Token")).not.toBeInTheDocument();
    // Skipped, the key's row says what that means, and leads back to it.
    expect(
      await screen.findByText(
        "Skipped for now: Maku can't find your series and films till you add it",
      ),
    ).toBeInTheDocument();
    const change = screen.getAllByRole("button", { name: "Change" });
    expect(change).toHaveLength(3); // the folders, the key and the standard
    change[1]?.click();

    expect(await screen.findByLabelText("TMDB API Read Access Token")).toBeInTheDocument();
  });

  it("downloads ffmpeg, then starts the first scan", async () => {
    const fetch = firstRun();
    renderSetup("tools");

    expect(await screen.findByText(/NVIDIA GeForce GTX 1660 SUPER/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start the first scan" })).toBeDisabled();
    (await screen.findByRole("button", { name: "Download" })).click();
    await waitFor(() => expect(sent(fetch, "POST", "/tools/ffmpeg/download")).toHaveLength(1));
  });

  it("starts the first scan once the tools are ready, and remembers setup is done", async () => {
    const fetch = firstRun({
      "/tools": [{ ...FFMPEG, state: "ready", done: FFMPEG.size }, WHISPER],
    });
    renderSetup("tools");

    expect(await screen.findByText("ffmpeg")).toBeInTheDocument();
    expect(screen.queryByText("Whisper medium")).not.toBeInTheDocument(); // fetched when asked for

    const start = await screen.findByRole("button", { name: "Start the first scan" });
    await waitFor(() => expect(start).toBeEnabled());
    start.click();

    expect(await screen.findByText("The scan")).toBeInTheDocument();
    const [[, put]] = sent(fetch, "PUT", "/settings") as [[unknown, RequestInit]];
    expect(JSON.parse(String(put.body))).toMatchObject({ setUp: true });
    expect(sent(fetch, "POST", "/scan")).toHaveLength(1);
  });

  it("tests this PC once ffmpeg is ready, then says what it can do and how long it takes", async () => {
    let pc = UNCHECKED;
    const testing: System["testing"] = {
      step: "subtitles",
      done: ["encoder"],
      fps: 61.4,
      timing: true,
    };
    const fetch = firstRun({
      "/tools": [{ ...FFMPEG, state: "ready", done: FFMPEG.size }],
      "/system": () => pc,
      "POST /system/test": () => {
        pc = { ...UNCHECKED, testing };
        return pc;
      },
    });
    renderSetup("tools");

    const progress = await screen.findByRole("status", { name: "Testing this PC" });
    expect(progress).toHaveTextContent("The encoder · 61 frames a second of 1080p");
    expect(progress).toHaveTextContent("The graphics card, for English subtitles");
    expect(sent(fetch, "POST", "/system/test")).toHaveLength(1);

    const now = { at: "2026-10-15T20:00:00+02:00", tested: true, conversions: 0, subtitles: 0 };
    pc = { ...SYSTEM, measured: now };
    expect(
      await screen.findByText("Convert to your standard", {}, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(screen.getByText("HEVC 10-bit on NVIDIA's encoder (NVENC)")).toBeInTheDocument();
    expect(screen.getByText("1080p ≈ 8 min · 4K ≈ 32 min")).toBeInTheDocument();
    expect(screen.getByText("≈ 24 min · 9 min")).toBeInTheDocument();
    expect(screen.getByText("Intel Core i5-9600K · 6 cores · 24 GB")).toBeInTheDocument();
    expect(screen.getByText(/Times measured on this PC just now/)).toBeInTheDocument();
    expect(sent(fetch, "POST", "/system/test")).toHaveLength(1); // once

    screen.getByRole("button", { name: "Test this PC again" }).click();
    await waitFor(() => expect(sent(fetch, "POST", "/system/test")).toHaveLength(2));
  });

  it("says before ffmpeg is there that the PC is tested once it is", async () => {
    firstRun();
    renderSetup("tools");

    expect(
      await screen.findByText(/Maku tests what this PC can do once ffmpeg is ready/),
    ).toBeInTheDocument();
    expect(screen.getByText("NVIDIA GeForce GTX 1660 SUPER · 6 GB")).toBeInTheDocument();
  });
});
