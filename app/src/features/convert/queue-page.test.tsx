import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EngineProvider, type Job, type QueueStatus, type Room } from "@/lib/engine";
import { fakeEngine, READY, SYSTEM } from "@/test/engine";
import { QueuePage } from "./queue-page";

const shell = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => {} }));

function job(id: number, more: Partial<Job> = {}): Job {
  const code = `S01E${String(id).padStart(2, "0")}`;
  return {
    id,
    fileId: id,
    path: `D:\\Videos\\TV\\Glass Orchard (2012)\\Season 01\\Glass Orchard (2012) - ${code}.mkv`,
    label: `Glass Orchard · ${code}`,
    titleId: 1,
    title: "Glass Orchard",
    season: 1,
    episode: id,
    method: "reencode",
    state: "queued",
    gpuSeconds: 480,
    addedAt: "2026-10-11T10:00:00+02:00",
    startedAt: null,
    finishedAt: null,
    problem: null,
    sourceSize: 233_000_000,
    outputSize: null,
    width: 1920,
    height: 1080,
    driveMissing: false,
    retryAt: null,
    log: null,
    noRoom: false,
    kind: "convert",
    language: null,
    modelMissing: false,
    fastInstead: false,
    ...more,
  };
}

const RUNNING: QueueStatus = {
  paused: false,
  schedule: "now",
  waitsForNight: false,
  problem: null,
  running: {
    job: job(5, { state: "running" }),
    stage: "converting",
    frames: 41_200,
    total: 65_400,
    secondsLeft: 140,
    fps: 171.6,
  },
  queued: [job(6), job(7), job(8, { season: 2, episode: 1, label: "Glass Orchard · S02E01" })],
  gpuSeconds: 3 * 480 + 140,
  today: [
    job(3, { state: "done", outputSize: 412_000_000, finishedAt: "2026-10-11T13:16:00+02:00" }),
    job(9, {
      state: "failed",
      label: "Quiet Hours · S01E04",
      problem: "The source file is damaged at 04:12. The original is untouched.",
      finishedAt: "2026-10-11T12:00:00+02:00",
      log: "ffmpeg version 8.0\n[h264 @ 0000] error while decoding MB 23 11\nStopped at frame 6,045 of 34,512.",
    }),
  ],
  gpu: { busy: 97, celsius: 71 },
  room: null,
  endsAt: null,
  early: false,
};

function renderQueue() {
  shell.invoke.mockImplementation(async (command: string) =>
    command === "engine_status" ? READY : undefined,
  );
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <EngineProvider>
        <MemoryRouter initialEntries={["/convert/queue"]}>
          <Routes>
            <Route path="/convert/queue" element={<QueuePage />} />
            <Route path="/convert" element={<p>The choosing screen</p>} />
            <Route path="/history" element={<p>History</p>} />
          </Routes>
        </MemoryRouter>
      </EngineProvider>
    </QueryClientProvider>,
  );
}

function sent(fetch: ReturnType<typeof fakeEngine>, method: string, path: string) {
  return fetch.mock.calls.filter(
    ([input, init]) =>
      (init?.method ?? "GET") === method && new URL(String(input)).pathname === path,
  );
}

describe("QueuePage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    shell.invoke.mockReset();
  });

  it("shows the file converting now, how far it is, and the card", async () => {
    fakeEngine({ "/queue": RUNNING });
    renderQueue();

    const now = await screen.findByRole("region", { name: "Now converting" });
    expect(now).toHaveTextContent("Glass Orchard · S01E05");
    expect(now).toHaveTextContent("63% · 2 min left");
    expect(now).toHaveTextContent("Made HEVC 10-bit · 1920 × 1080");
    expect(screen.getByRole("img", { name: "Graphics card 97 percent busy" })).toBeInTheDocument();
    expect(now).toHaveTextContent("71 °C");
    expect(now).toHaveTextContent("171.6 fps");
    expect(screen.getByText("Encode").closest("li")).toHaveAttribute("aria-current", "step");
    expect(
      screen.getByText("Running · 3 in the queue · about 26 min of GPU time"),
    ).toBeInTheDocument();
  });

  it("shows English subtitles being made: from which sound, how far, and what's heard", async () => {
    const hearing = job(5, {
      state: "running",
      kind: "subtitles",
      method: "best",
      language: "jpn",
      label: "Starfall Academy · S01E05",
    });
    fakeEngine({
      "/queue": {
        ...RUNNING,
        running: {
          job: hearing,
          stage: "listening",
          frames: 608,
          total: 1453,
          secondsLeft: 190,
          fps: null,
        },
        queued: [
          job(6, { kind: "subtitles", method: "best", language: "jpn", gpuSeconds: 580 }),
          job(7, { kind: "subtitles", method: "fast", modelMissing: true, gpuSeconds: 220 }),
          job(8),
        ],
      },
    });
    renderQueue();

    const now = await screen.findByRole("region", { name: "Now making English subtitles" });
    expect(now).toHaveTextContent("Starfall Academy · S01E05");
    expect(now).toHaveTextContent("from the Japanese sound · Best");
    expect(within(now).getByRole("listitem", { current: "step" })).toHaveTextContent(
      "Listen and translate",
    );
    expect(now).toHaveTextContent("42% · 3 min left");
    expect(now).toHaveTextContent("10:08 of 24:13 heard");
    const next = screen.getByRole("region", { name: "Up next" });
    expect(next).toHaveTextContent("English subs · Best");
    expect(next).toHaveTextContent("Waiting for its speech model");
    expect(next).toHaveTextContent("Re-encode"); // the conversion after them
  });

  it("offers the speech model subtitles wait for, saying why its download didn't finish", async () => {
    const whisper = {
      id: "speech-best",
      name: "Whisper medium",
      version: "fp16 d397824",
      purpose: "OpenAI's speech model, for English subtitles at Best.",
      licence: "MIT",
      size: 1_530_853_088,
      when: "asked",
      state: "failed",
      done: 0,
      problem: "The download stopped: the connection was reset.",
    };
    const fetch = fakeEngine({
      "/queue": {
        ...RUNNING,
        running: null,
        queued: [job(6, { kind: "subtitles", method: "best", modelMissing: true })],
      },
      "/tools": [whisper],
      "POST /tools/speech-best/download": { ...whisper, state: "downloading", problem: null },
    });
    renderQueue();

    const card = await screen.findByRole("status", { name: "Speech model" });
    expect(card).toHaveTextContent("English subtitles wait for their speech model.");
    expect(card).toHaveTextContent("Whisper medium · 1.5 GB · MIT licence");
    expect(card).toHaveTextContent("The download stopped: the connection was reset.");
    expect(screen.getByRole("region", { name: "Waiting" })).toHaveTextContent(
      "English subtitles start once their speech model is on this PC.",
    );
    fireEvent.click(within(card).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(sent(fetch, "POST", "/tools/speech-best/download")).toHaveLength(1));
  });

  it("shows English from another copy being added, and next in line", async () => {
    fakeEngine({
      "/queue": {
        ...RUNNING,
        running: {
          job: job(5, { state: "running", kind: "merge", method: "remux" }),
          stage: "converting",
          frames: 550_000_000,
          total: 1_100_000_000,
          secondsLeft: 6,
          fps: 90_000_000,
        },
        queued: [job(6, { kind: "merge", method: "remux", gpuSeconds: 31 }), job(7)],
      },
    });
    renderQueue();

    const now = await screen.findByRole("region", { name: "Now adding English from another copy" });
    expect(now).toHaveTextContent("Glass Orchard · S01E05");
    expect(within(now).getByRole("listitem", { current: "step" })).toHaveTextContent(
      "Add the English",
    );
    expect(now).toHaveTextContent("50% · 1 min left");
    expect(now).not.toHaveTextContent("fps");
    const next = screen.getByRole("region", { name: "Up next" });
    expect(next).toHaveTextContent("English from another copy");
  });

  it("says why English couldn't be added, and offers to try again but not to mark it broken", async () => {
    fakeEngine({
      "/queue": {
        ...RUNNING,
        running: null,
        queued: [],
        today: [
          job(9, {
            state: "failed",
            kind: "merge",
            method: "remux",
            problem: "The two copies aren't the same cut, so the English wouldn't line up.",
            finishedAt: "2026-10-11T12:00:00+02:00",
          }),
        ],
      },
    });
    renderQueue();

    const failed = await screen.findByRole("alert");
    expect(failed).toHaveTextContent("No English added to Glass Orchard · S01E09.");
    expect(within(failed).getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(within(failed).queryByRole("button", { name: "Mark as broken" })).toBeNull();
  });

  it("says why subtitles couldn't be made, and offers to try again but not to mark it broken", async () => {
    const fetch = fakeEngine({
      "/queue": {
        ...RUNNING,
        running: null,
        queued: [],
        today: [
          job(9, {
            state: "failed",
            kind: "subtitles",
            label: "Starfall Academy · S01E09",
            problem: "ffmpeg couldn't read its sound (invalid data).",
            log: "[aac @ 0] Error decoding: invalid data",
            finishedAt: "2026-10-11T12:00:00+02:00",
          }),
        ],
      },
      "POST /queue/9/retry": null,
    });
    renderQueue();

    const failed = await screen.findByRole("alert");
    expect(failed).toHaveTextContent(
      "No English subtitles for Starfall Academy · S01E09. ffmpeg couldn't read its sound (invalid data). The video is as it was.",
    );
    expect(failed).toHaveTextContent("Error decoding: invalid data");
    expect(
      within(failed).queryByRole("button", { name: "Mark as broken" }),
    ).not.toBeInTheDocument();
    within(failed).getByRole("button", { name: "Try again" }).click();
    await waitFor(() => expect(sent(fetch, "POST", "/queue/9/retry")).toHaveLength(1));
  });

  it("offers Fast when the card ran out of memory for Best", async () => {
    const fetch = fakeEngine({
      "/queue": {
        ...RUNNING,
        running: null,
        queued: [],
        today: [
          job(9, {
            state: "failed",
            kind: "subtitles",
            label: "Starfall Academy · S01E09",
            problem: "The graphics card ran out of memory for Best.",
            fastInstead: true,
            finishedAt: "2026-10-11T12:00:00+02:00",
          }),
        ],
      },
      "/system": SYSTEM,
      "POST /queue/9/retry": null,
    });
    renderQueue();

    const failed = await screen.findByRole("alert");
    await waitFor(() =>
      expect(failed).toHaveTextContent(
        "No English subtitles for Starfall Academy · S01E09. The graphics card ran out of memory for Best. Fast needs less, and takes about 9 minutes an hour of video here. The video is as it was.",
      ),
    );
    within(failed).getByRole("button", { name: "Make them with Fast" }).click();

    await waitFor(() => expect(sent(fetch, "POST", "/queue/9/retry")).toHaveLength(1));
    const [[, init]] = sent(fetch, "POST", "/queue/9/retry") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ quality: "fast" });
    expect(within(failed).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("pauses everything, by the button or the space bar", async () => {
    const fetch = fakeEngine({ "/queue": RUNNING, "POST /queue/pause": RUNNING });
    renderQueue();

    (await screen.findByRole("button", { name: /Pause all/ })).click();
    await waitFor(() => expect(sent(fetch, "POST", "/queue/pause")).toHaveLength(1));

    fireEvent.keyDown(document.body, { code: "Space" });
    await waitFor(() => expect(sent(fetch, "POST", "/queue/pause")).toHaveLength(2));
  });

  it("skips the file converting now", async () => {
    const fetch = fakeEngine({ "/queue": RUNNING, "POST /queue/5/skip": null });
    renderQueue();

    (await screen.findByRole("button", { name: "Skip this file" })).click();

    await waitFor(() => expect(sent(fetch, "POST", "/queue/5/skip")).toHaveLength(1));
  });

  it("lists what's next a season at a time, and moves a file up", async () => {
    const fetch = fakeEngine({ "/queue": RUNNING, "POST /queue/7/move": null });
    renderQueue();

    const next = await screen.findByRole("region", { name: "Up next" });
    expect(next).toHaveTextContent("Glass Orchard · Season 1 · 2 left");
    expect(next).toHaveTextContent("S01E06Glass Orchard (2012) - S01E06.mkvRe-encode≈ 8 min");
    expect(next).toHaveTextContent("Glass Orchard · Season 2 · 1 left≈ 8 min");

    fireEvent.keyDown(screen.getByRole("button", { name: "More for Glass Orchard · S01E07" }), {
      key: "Enter",
    });
    (await screen.findByRole("menuitem", { name: "Convert next" })).click();

    await waitFor(() => expect(sent(fetch, "POST", "/queue/7/move")).toHaveLength(1));
    const [[, init]] = sent(fetch, "POST", "/queue/7/move") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ before: 6 });
  });

  it("shows a file waiting in its folder, or copies its path", async () => {
    fakeEngine({ "/queue": RUNNING });
    renderQueue();
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const path = job(7).path;

    const more = await screen.findByRole("button", { name: "More for Glass Orchard · S01E07" });
    fireEvent.keyDown(more, { key: "Enter" });
    (await screen.findByRole("menuitem", { name: "Show in folder" })).click();
    await waitFor(() => expect(shell.invoke).toHaveBeenCalledWith("show_in_folder", { path }));
    fireEvent.keyDown(more, { key: "Enter" });
    (await screen.findByRole("menuitem", { name: "Copy path" })).click();
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(path));
    expect(await screen.findByText("Its path is copied.")).toBeInTheDocument();
  });

  it("takes a whole season out of the queue at once", async () => {
    const fetch = fakeEngine({ "/queue": RUNNING, "POST /queue/remove": { changed: 2 } });
    renderQueue();

    (await screen.findByRole("checkbox", { name: "Glass Orchard · Season 1 · 2 left" })).click();
    const ticked = screen.getByRole("group", { name: "Ticked files" });
    expect(ticked).toHaveTextContent("2 ticked");
    within(ticked).getByRole("button", { name: "Take out of the queue" }).click();

    await waitFor(() => expect(sent(fetch, "POST", "/queue/remove")).toHaveLength(1));
    const [[, init]] = sent(fetch, "POST", "/queue/remove") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ ids: [6, 7] });
    expect(await screen.findByText("Tick files to move or take out several at once")).toBeVisible();
  });

  it("moves ticked files from different seasons together, next or to the end", async () => {
    const fetch = fakeEngine({ "/queue": RUNNING, "POST /queue/move": { changed: 2 } });
    renderQueue();

    (await screen.findByRole("checkbox", { name: /S01E07/ })).click();
    const season = screen.getByRole("checkbox", { name: "Glass Orchard · Season 1 · 2 left" });
    expect(season).toBePartiallyChecked();
    screen.getByRole("button", { name: "Show the files of Glass Orchard · Season 2" }).click();
    (await screen.findByRole("checkbox", { name: /S02E01/ })).click();
    screen.getByRole("button", { name: "Convert next" }).click();

    await waitFor(() => expect(sent(fetch, "POST", "/queue/move")).toHaveLength(1));
    const [[, next]] = sent(fetch, "POST", "/queue/move") as [[unknown, RequestInit]];
    expect(JSON.parse(String(next.body))).toEqual({ ids: [7, 8], before: 6 });

    (await screen.findByRole("checkbox", { name: /S01E06/ })).click();
    screen.getByRole("button", { name: "Move to the end" }).click();
    await waitFor(() => expect(sent(fetch, "POST", "/queue/move")).toHaveLength(2));
    const [, [, last]] = sent(fetch, "POST", "/queue/move") as [unknown, [unknown, RequestInit]];
    expect(JSON.parse(String(last.body))).toEqual({ ids: [6], before: null });
  });

  it("ticks every file waiting at once, and unticks them", async () => {
    fakeEngine({ "/queue": RUNNING });
    renderQueue();

    const every = await screen.findByRole("checkbox", { name: "Tick every file waiting" });
    every.click();
    expect(await screen.findByText("3 ticked")).toBeVisible();
    expect(every).toBeChecked();
    every.click();

    expect(await screen.findByText("Tick files to move or take out several at once")).toBeVisible();
  });

  it("finds files waiting by title, episode or file name, and ticks only those found", async () => {
    const fetch = fakeEngine({
      "/queue": {
        ...RUNNING,
        queued: [
          job(6),
          job(7),
          job(8, {
            season: 2,
            episode: 1,
            label: "Glass Orchard · S02E01",
            path: "D:VideosTVGlass Orchard (2012)Season 02Glass Orchard (2012) - S02E01.mkv",
          }),
          job(10, {
            titleId: 2,
            title: "Northern Lights",
            label: "Northern Lights · S01E03",
            path: "D:VideosNorthern LightsNorthern Lights - 03.mkv",
            episode: 3,
          }),
        ],
      },
      "POST /queue/move": { changed: 2 },
    });
    renderQueue();

    const search = await screen.findByRole("searchbox", { name: "Search the queue" });
    expect(search).toHaveAttribute("placeholder", "Search 4 files waiting");
    fireEvent.change(search, { target: { value: "orchard s01" } });

    const next = screen.getByRole("region", { name: "Up next" });
    await waitFor(() => expect(next).not.toHaveTextContent("Season 2"));
    expect(next).toHaveTextContent("Glass Orchard · Season 1 · 2 left");
    expect(next).not.toHaveTextContent("Northern Lights");
    screen.getByRole("checkbox", { name: "Tick every file shown" }).click();
    expect(await screen.findByText("2 ticked")).toBeVisible();
    screen.getByRole("button", { name: "Move to the end" }).click();
    await waitFor(() => expect(sent(fetch, "POST", "/queue/move")).toHaveLength(1));
    const [[, init]] = sent(fetch, "POST", "/queue/move") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ ids: [6, 7], before: null });

    fireEvent.change(search, { target: { value: "Northern Lights - 03" } });
    expect(await within(next).findByText("Northern Lights · Season 1 · 1 left")).toBeVisible();
    fireEvent.change(search, { target: { value: "Vash" } });
    expect(await within(next).findByRole("status")).toHaveTextContent(
      "No file waiting goes by “Vash”.",
    );
  });

  it("shows the page's shape while the queue loads", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );
    renderQueue();

    expect(await screen.findByRole("status", { name: "Loading the queue" })).toBeInTheDocument();
  });

  it("cancels everything only once asked, and can be talked out of it", async () => {
    const fetch = fakeEngine({ "/queue": RUNNING, "POST /queue/cancel": RUNNING });
    renderQueue();

    (await screen.findByRole("button", { name: "Cancel all" })).click();
    const asking = await screen.findByRole("group", { name: "Cancel all?" });
    expect(asking).toHaveTextContent(
      "Cancel all 4 files?The file converting now stops, and every file waiting leaves the queue.",
    );
    within(asking).getByRole("button", { name: "Keep them" }).click();
    await waitFor(() =>
      expect(screen.queryByRole("group", { name: "Cancel all?" })).not.toBeInTheDocument(),
    );
    expect(sent(fetch, "POST", "/queue/cancel")).toHaveLength(0);

    screen.getByRole("button", { name: "Cancel all" }).click();
    (await screen.findByRole("button", { name: "Cancel all 4 files" })).click();

    await waitFor(() => expect(sent(fetch, "POST", "/queue/cancel")).toHaveLength(1));
    await waitFor(() =>
      expect(screen.queryByRole("group", { name: "Cancel all?" })).not.toBeInTheDocument(),
    );
  });

  it("counts today's results, and tries a failed file again", async () => {
    const fetch = fakeEngine({ "/queue": RUNNING, "POST /queue/9/retry": null });
    renderQueue();

    const today = await screen.findByRole("region", { name: "Today" });
    expect(today).toHaveTextContent("1converted1failed412 MBwritten");
    expect(today).toHaveTextContent(
      "Quiet Hours · S01E04 failed. The source file is damaged at 04:12. The original is untouched.",
    );
    screen.getByRole("button", { name: "Try again" }).click();

    await waitFor(() => expect(sent(fetch, "POST", "/queue/9/retry")).toHaveLength(1));
  });

  it("shows what ffmpeg said of a failed file, copies all of it, and marks it broken", async () => {
    const copied = vi.fn(async (_text: string) => {});
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: copied },
      configurable: true,
    });
    const fetch = fakeEngine({ "/queue": RUNNING, "POST /queue/9/broken": null });
    renderQueue();

    const failed = await screen.findByRole("alert");
    expect(failed).toHaveTextContent(
      "[h264 @ 0000] error while decoding MB 23 11Stopped at frame 6,045 of 34,512.",
    );
    expect(failed).not.toHaveTextContent("ffmpeg version 8.0"); // only its last lines show
    screen.getByRole("button", { name: "Copy full log" }).click();
    await waitFor(() => expect(copied).toHaveBeenCalledWith(RUNNING.today[1]?.log));
    screen.getByRole("button", { name: "Mark as broken" }).click();
    await waitFor(() => expect(sent(fetch, "POST", "/queue/9/broken")).toHaveLength(1));
  });

  it("converts at night only, when asked", async () => {
    const fetch = fakeEngine({
      "/queue": { ...RUNNING, running: null, schedule: "nights", waitsForNight: true },
      "PUT /queue/schedule": RUNNING,
    });
    renderQueue();

    expect(
      await screen.findByText("Files convert tonight, from 23:00 to 07:00."),
    ).toBeInTheDocument();
    expect(screen.getByText("Picks up again tonight at 23:00")).toBeInTheDocument();
    screen.getByRole("switch", { name: "Nights only, 23:00–07:00" }).click();

    await waitFor(() => expect(sent(fetch, "PUT", "/queue/schedule")).toHaveLength(1));
    const [[, init]] = sent(fetch, "PUT", "/queue/schedule") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ schedule: "now" });
  });

  it("resumes a paused queue", async () => {
    const fetch = fakeEngine({
      "/queue": { ...RUNNING, running: null, paused: true },
      "POST /queue/resume": RUNNING,
    });
    renderQueue();

    expect(await screen.findByText(/The queue is paused/)).toBeInTheDocument();
    screen.getAllByRole("button", { name: /Resume/ })[0]?.click();

    await waitFor(() => expect(sent(fetch, "POST", "/queue/resume")).toHaveLength(1));
  });

  it("says when nothing waits, and leads to choosing", async () => {
    fakeEngine({ "/queue": { ...RUNNING, running: null, queued: [], today: [], gpuSeconds: 0 } });
    renderQueue();

    expect(await screen.findByRole("heading", { name: "Nothing waiting" })).toBeInTheDocument();
    screen.getByRole("link", { name: "Choose what to convert" }).click();
    expect(await screen.findByText("The choosing screen")).toBeInTheDocument();
  });

  it("keeps the PC awake overnight till 07:00, or stops at 03:00 when asked", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-13T01:00:00"));
    try {
      const nights = { ...RUNNING, schedule: "nights" as const, endsAt: "2026-10-13T07:00:00" };
      const fetch = fakeEngine({
        "/queue": nights,
        "PUT /queue/tonight": { ...nights, endsAt: "2026-10-13T03:00:00", early: true },
      });
      renderQueue();

      expect(
        await screen.findByText(
          "Keeping the PC awake until 07:00 while it converts. Normal sleep comes back after.",
        ),
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Stop at 03:00" }));

      await waitFor(() => expect(sent(fetch, "PUT", "/queue/tonight")).toHaveLength(1));
      const [[, init]] = sent(fetch, "PUT", "/queue/tonight") as [[unknown, RequestInit]];
      expect(JSON.parse(String(init.body))).toEqual({ early: true });
    } finally {
      vi.useRealTimers();
    }
  });

  it("past 03:00, offers to stop after the file converting", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-13T04:10:00"));
    try {
      fakeEngine({
        "/queue": { ...RUNNING, schedule: "nights", endsAt: "2026-10-13T07:00:00" },
      });
      renderQueue();

      expect(
        await screen.findByRole("button", { name: "Stop after this file" }),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("offers to go on till 07:00 once stopping early", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-13T03:20:00"));
    try {
      fakeEngine({
        "/queue": {
          ...RUNNING,
          schedule: "nights",
          endsAt: "2026-10-13T03:00:00",
          early: true,
        },
      });
      renderQueue();

      expect(
        await screen.findByText(
          "Keeping the PC awake while this file finishes. Normal sleep comes back after.",
        ),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Go on till 07:00" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("says nothing of the night while converting by day, or on the always schedule", async () => {
    fakeEngine({ "/queue": RUNNING });
    renderQueue();

    expect(await screen.findByText(/22,000 of 34,920 frames|Now converting/)).toBeInTheDocument();
    expect(screen.queryByText(/Keeping the PC awake until/)).not.toBeInTheDocument();
  });

  it("says which files wait for their drive", async () => {
    fakeEngine({
      "/queue": {
        ...RUNNING,
        running: null,
        paused: true,
        queued: [job(6, { driveMissing: true }), job(7)],
      },
    });
    renderQueue();

    expect(await screen.findByRole("region", { name: "Up next" })).toHaveTextContent(
      "S01E06Glass Orchard (2012) - S01E06.mkvIts drive isn't connected",
    );
  });

  it("offers to empty the quarantine or convert what fits when a drive is full", async () => {
    const room: Room = {
      drive: "D:",
      paused: true,
      files: 2,
      needed: 1_125_000_000,
      free: 600_000_000,
      fit: 1,
      setAside: 3_400_000_000,
    };
    const fetch = fakeEngine({
      "/queue": { ...RUNNING, running: null, paused: true, queued: [job(6), job(7)], room },
      "POST /queue/fit": RUNNING,
      "POST /quarantine/empty": { files: 41 },
      "POST /queue/resume": RUNNING,
    });
    renderQueue();

    const dialog = await screen.findByRole("alertdialog", { name: "Not enough space" });
    expect(dialog).toHaveTextContent(
      "Glass Orchard · Season 1 needs about 1.1 GB. D: has 600 MB free.",
    );
    expect(screen.queryByText(/The queue is paused/)).not.toBeInTheDocument(); // it says why

    fireEvent.click(screen.getByRole("button", { name: /Convert the 1 that fit now/ }));
    await waitFor(() => expect(sent(fetch, "POST", "/queue/fit")).toHaveLength(1));
    const [[, fit]] = sent(fetch, "POST", "/queue/fit") as [[unknown, RequestInit]];
    expect(JSON.parse(String(fit.body))).toEqual({ drive: "D:" });

    fireEvent.click(screen.getByRole("button", { name: /Empty quarantine first/ }));
    const asked = await screen.findByRole("group", { name: "Empty the quarantine on D:?" });
    expect(asked).toHaveTextContent(
      "What's set aside there (3.4 GB) is deleted for good, and History can't put it back.",
    );
    expect(sent(fetch, "POST", "/quarantine/empty")).toHaveLength(0); // not till it's confirmed
    fireEvent.click(screen.getByRole("button", { name: "Empty quarantine" }));

    await waitFor(() => expect(sent(fetch, "POST", "/queue/resume")).toHaveLength(1));
    const [[, emptied]] = sent(fetch, "POST", "/quarantine/empty") as [[unknown, RequestInit]];
    expect(JSON.parse(String(emptied.body))).toEqual({ drive: "D:" });
  });

  it("says when the files left wait for room while the others go", async () => {
    const room: Room = {
      drive: "D:",
      paused: false,
      files: 1,
      needed: 2_812_500_000,
      free: 1_000_000,
      fit: 0,
      setAside: 0,
    };
    fakeEngine({
      "/queue": { ...RUNNING, running: null, queued: [job(6, { noRoom: true })], room },
    });
    renderQueue();

    expect(await screen.findByText("Waiting for room on D: · 1 in the queue")).toBeInTheDocument();
    expect(screen.getByRole("alertdialog", { name: "Not enough space" })).toHaveTextContent(
      "D: has 1 MB free, and 1 file there needs about 2.8 GB: it waits for room while the others go.",
    );
    expect(screen.queryByRole("button", { name: /Empty quarantine/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /fit now|Wait for room/ })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Up next" })).toHaveTextContent("Waiting for room");
    expect(screen.queryByText(/in a moment/)).not.toBeInTheDocument();
  });

  it("says so when every file waiting is on a drive that isn't connected", async () => {
    fakeEngine({
      "/queue": {
        ...RUNNING,
        running: null,
        queued: [job(6, { driveMissing: true }), job(7, { driveMissing: true })],
      },
    });
    renderQueue();

    expect(
      await screen.findByText(
        "Every file waiting is on D:, which isn't connected. Plug it in to carry on.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Waiting for D: · 2 in the queue")).toBeInTheDocument();
    expect(screen.queryByText(/in a moment/)).not.toBeInTheDocument();
  });

  it("tells of a file open in another app, and tries it now or skips it", async () => {
    const waiting = job(4, {
      problem:
        "Glass Orchard · S01E04 is open in another app, maybe your player. Maku will try again in 5 minutes.",
      retryAt: new Date(Date.now() + 5 * 60_000 - 1000).toISOString(),
      gpuSeconds: 0,
    });
    const fetch = fakeEngine({
      "/queue": { ...RUNNING, running: null, queued: [waiting], gpuSeconds: 0, today: [] },
      "POST /queue/4/retry": null,
      "POST /queue/4/skip": null,
    });
    renderQueue();

    const said = await screen.findByText("Glass Orchard · S01E04 is open in another app,");
    expect(said.closest("[role=status]")).toHaveTextContent(
      "Glass Orchard · S01E04 is open in another app, maybe your player. Maku will try again in 5 minutes.",
    );
    expect(screen.getByText("Waiting for another app · 1 in the queue")).toBeInTheDocument();
    expect(screen.queryByText(/starts in a moment/)).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Up next" })).toHaveTextContent(
      "S01E04Glass Orchard (2012) - S01E04.mkvOpen in another app",
    );

    screen.getByRole("button", { name: "Try now" }).click();
    await waitFor(() => expect(sent(fetch, "POST", "/queue/4/retry")).toHaveLength(1));
    const skip = screen.getByRole("button", { name: "Skip this file" });
    await waitFor(() => expect(skip).toBeEnabled());
    skip.click();
    await waitFor(() => expect(sent(fetch, "POST", "/queue/4/skip")).toHaveLength(1));
  });

  it("says a result waiting for its app waits, nights only or not", async () => {
    const waiting = job(4, {
      retryAt: new Date(Date.now() + 5 * 60_000 - 1000).toISOString(),
      gpuSeconds: 0,
    });
    fakeEngine({
      "/queue": {
        ...RUNNING,
        running: null,
        schedule: "nights",
        waitsForNight: true,
        queued: [waiting],
        gpuSeconds: 0,
      },
    });
    renderQueue();

    expect(await screen.findByText("Waiting for another app · 1 in the queue")).toBeInTheDocument();
  });

  it("says a made file waits for its drive, and offers no try that can't work", async () => {
    const waiting = job(4, {
      retryAt: new Date(Date.now() - 60_000).toISOString(), // due, but its drive is away
      gpuSeconds: 0,
      driveMissing: true,
    });
    fakeEngine({ "/queue": { ...RUNNING, running: null, queued: [waiting], gpuSeconds: 0 } });
    renderQueue();

    const said = await screen.findByText("Glass Orchard · S01E04 is made, and waits for D:.");
    expect(said.closest("[role=status]")).toHaveTextContent(
      "Glass Orchard · S01E04 is made, and waits for D:. It goes in once the drive is connected.",
    );
    expect(screen.queryByRole("button", { name: "Try now" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip this file" })).toBeInTheDocument();
  });

  it("says why skipping, taking out or trying again didn't work", async () => {
    const refused = (detail: string) => () => Response.json({ detail }, { status: 404 });
    fakeEngine({
      "/queue": RUNNING,
      "POST /queue/5/skip": refused("That file isn't waiting or converting."),
      "DELETE /queue/7": refused("That file isn't waiting in the queue."),
      "POST /queue/9/retry": refused("That file didn't fail and wasn't skipped."),
    });
    renderQueue();

    (await screen.findByRole("button", { name: "Skip this file" })).click();
    expect(await screen.findByText("That file isn't waiting or converting.")).toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole("button", { name: "More for Glass Orchard · S01E07" }), {
      key: "Enter",
    });
    (await screen.findByRole("menuitem", { name: "Take out of the queue" })).click();
    expect(await screen.findByText("That file isn't waiting in the queue.")).toBeInTheDocument();

    screen.getByRole("button", { name: "Try again" }).click();
    expect(
      await screen.findByText("That file didn't fail and wasn't skipped."),
    ).toBeInTheDocument();
  });

  it("says why nothing converts without ffmpeg", async () => {
    const problem = "Maku needs ffmpeg to convert. It's downloaded on the setup's Tools step.";
    fakeEngine({ "/queue": { ...RUNNING, running: null, problem } });
    renderQueue();

    expect(await screen.findByText(problem)).toBeInTheDocument();
  });
});
