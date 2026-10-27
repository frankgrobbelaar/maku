import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EngineProvider, type Hearable, type System, type Tool } from "@/lib/engine";
import { fakeEngine, READY, SYSTEM } from "@/test/engine";
import { MakeSubtitlesPage } from "./make-page";

const shell = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => {} }));

/** An episode of a Korean series, its sound in Korean first, then German in stereo and 5.1. */
function video(id: number, more: Partial<Hearable> = {}): Hearable {
  return {
    fileId: id,
    label: `The Harbour Line · S01E0${id}`,
    titleId: 7,
    title: "The Harbour Line",
    season: 1,
    episode: id,
    seconds: 1440,
    sound: ["kor", "ger", "ger"],
    subtitles: ["ger"],
    english: false,
    made: false,
    waiting: false,
    ...more,
  };
}

const FILES: Hearable[] = [
  video(1),
  video(2),
  video(3, { subtitles: ["ger", "en"], english: true }),
  video(4, { season: 2, episode: 1, label: "The Harbour Line · S02E01" }),
  video(5, { waiting: true }),
  {
    ...video(9),
    titleId: 8,
    title: "Glass Orchard",
    label: "Glass Orchard · S01E01",
    sound: ["kor"],
  },
];

function model(state: Tool["state"]): Tool {
  return {
    id: "speech-best",
    name: "Whisper medium",
    version: "fp16 d397824",
    purpose: "OpenAI's speech model, for English subtitles at Best.",
    licence: "MIT",
    size: 1_530_853_088,
    when: "asked",
    state,
    done: 0,
    problem: null,
  };
}

function engine(state: Tool["state"] = "ready", system: System = SYSTEM) {
  const fast = { ...model("ready"), id: "speech-fast", name: "Whisper small", size: 486_000_000 };
  return fakeEngine({
    "/subtitles": { files: FILES, rates: { best: 0.4, fast: 0.15 } },
    "/system": system,
    "/tools": [model(state), fast],
    "/queue": { schedule: "now", queued: [], running: null },
    "POST /subtitles": { added: 2 },
    "POST /tools/speech-best/download": { ...model("downloading") },
  });
}

function renderMake(address = "/subtitles?title=7&season=1") {
  shell.invoke.mockImplementation(async (command: string) =>
    command === "engine_status" ? READY : undefined,
  );
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <EngineProvider>
        <MemoryRouter initialEntries={[address]}>
          <Routes>
            <Route path="/subtitles" element={<MakeSubtitlesPage />} />
            <Route path="/convert/queue" element={<p>The queue</p>} />
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

describe("MakeSubtitlesPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    shell.invoke.mockReset();
  });

  it("offers the season, its title and everything without English, and what each takes", async () => {
    engine();
    renderMake();

    const which = await screen.findByRole("radiogroup", { name: "Which videos" });
    const choices = within(which).getAllByRole("radio");
    expect(choices.map((choice) => choice.textContent)).toEqual([
      "Season 12 without English", // 1 and 2: 3 has English, 5 waits already
      "All of The Harbour Line3 without English",
      "Everything without English4 videos in 2 titles",
    ]);
    expect(choices[0]).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("The Harbour Line · Season 1")).toBeInTheDocument();
    // Its own language first, the one its videos start with, though German is heard more often;
    // German too.
    expect(screen.getByRole("radio", { name: "Korean" })).toHaveAttribute("data-state", "on");
    expect(screen.getByRole("radio", { name: "German" })).toHaveAttribute("data-state", "off");
    expect(screen.getByRole("radio", { name: "Best" })).toHaveTextContent("≈ 10 min per episode");
    expect(screen.getByRole("radio", { name: "Fast" })).toHaveTextContent("≈ 4 min per episode");
    expect(screen.getByText("≈ 19 min")).toBeInTheDocument(); // two episodes at Best
    expect(screen.getByText("on this PC")).toBeInTheDocument();
  });

  it("starts from the sound heard most when the videos don't say their own", async () => {
    fakeEngine({
      "/subtitles": {
        files: [video(1, { sound: ["", "fre"] }), video(2, { sound: ["", "fre", "ger"] })],
        rates: { best: 0.4, fast: 0.15 },
      },
      "/system": SYSTEM,
      "/tools": [model("ready")],
      "/queue": { schedule: "now", queued: [], running: null },
    });
    renderMake();

    expect(await screen.findByRole("radio", { name: "French" })).toHaveAttribute(
      "data-state",
      "on",
    );
    expect(screen.getByRole("radio", { name: "German" })).toHaveAttribute("data-state", "off");
  });

  it("offers the videos ticked on the title's page first", async () => {
    const fetch = engine();
    renderMake("/subtitles?title=7&files=2,4");

    const which = await screen.findByRole("radiogroup", { name: "Which videos" });
    const [first] = within(which).getAllByRole("radio");
    expect(first).toHaveTextContent("The 2 videos you ticked2 without English");
    expect(first).toHaveAttribute("aria-checked", "true");
    (await screen.findByRole("button", { name: "Make subtitles for 2 episodes" })).click();

    expect(await screen.findByText("The queue")).toBeInTheDocument();
    const [[, made]] = sent(fetch, "POST", "/subtitles") as [[unknown, RequestInit]];
    expect(JSON.parse(String(made.body))).toMatchObject({
      fileIds: [2, 4],
      title: "The Harbour Line · 2 videos",
    });
  });

  it("puts the season in the queue as one batch, then shows the queue", async () => {
    const fetch = engine();
    renderMake();

    (await screen.findByRole("button", { name: "Make subtitles for 2 episodes" })).click();

    expect(await screen.findByText("The queue")).toBeInTheDocument();
    const [[, made]] = sent(fetch, "POST", "/subtitles") as [[unknown, RequestInit]];
    expect(JSON.parse(String(made.body))).toEqual({
      fileIds: [1, 2],
      quality: "best",
      language: "kor",
      title: "The Harbour Line · Season 1",
      when: "now",
    });
  });

  it("can take the ones with English subtitles too, and the whole title", async () => {
    const fetch = engine();
    renderMake();

    (await screen.findByRole("radio", { name: /^All of The Harbour Line/ })).click();
    screen.getByRole("checkbox", { name: /Also the ones with English subtitles already/ }).click();
    (await screen.findByRole("button", { name: "Make subtitles for 4 episodes" })).click();

    await waitFor(() => expect(sent(fetch, "POST", "/subtitles")).toHaveLength(1));
    const [[, made]] = sent(fetch, "POST", "/subtitles") as [[unknown, RequestInit]];
    expect(JSON.parse(String(made.body))).toMatchObject({
      fileIds: [1, 2, 3, 4],
      title: "The Harbour Line",
    });
  });

  it("asks to download the speech model first, then starts", async () => {
    const fetch = engine("missing");
    renderMake();

    (await screen.findByRole("button", { name: "Make subtitles for 2 episodes" })).click();

    const asking = await screen.findByRole("alert");
    expect(asking).toHaveTextContent("Maku needs its speech model first");
    expect(asking).toHaveTextContent("1.5 GB, downloaded once");
    expect(asking).toHaveTextContent("Whisper medium · MIT licence");
    expect(sent(fetch, "POST", "/subtitles")).toHaveLength(0);
    within(asking).getByRole("button", { name: "Download it and start" }).click();

    expect(await screen.findByText("The queue")).toBeInTheDocument();
    expect(sent(fetch, "POST", "/tools/speech-best/download")).toHaveLength(1);
    expect(sent(fetch, "POST", "/subtitles")).toHaveLength(1);
  });

  it("says why the speech model didn't download, and tries again", async () => {
    const fetch = fakeEngine({
      "/subtitles": { files: FILES, rates: { best: 0.4, fast: 0.15 } },
      "/tools": [
        { ...model("failed"), problem: "The download stopped: the connection was reset." },
      ],
      "/queue": { schedule: "now", queued: [], running: null },
      "POST /subtitles": { added: 2 },
      "POST /tools/speech-best/download": { ...model("downloading") },
    });
    renderMake();

    expect(await screen.findByText("its download didn't finish")).toBeInTheDocument();
    (await screen.findByRole("button", { name: "Make subtitles for 2 episodes" })).click();

    const asking = await screen.findByRole("alert");
    expect(asking).toHaveTextContent("The download stopped: the connection was reset.");
    within(asking).getByRole("button", { name: "Download it and start" }).click();
    await waitFor(() => expect(sent(fetch, "POST", "/tools/speech-best/download")).toHaveLength(1));
  });

  it("makes everything without English from Home", async () => {
    engine();
    renderMake("/subtitles");

    const which = await screen.findByRole("radiogroup", { name: "Which videos" });
    expect(within(which).getAllByRole("radio")).toHaveLength(1);
    expect(
      await screen.findByRole("button", { name: "Make subtitles for 4 episodes" }),
    ).toBeEnabled();
  });

  it("offers Fast where the card hasn't the memory for Best", async () => {
    const small: System = {
      ...SYSTEM,
      card: {
        name: "NVIDIA GeForce GTX 1050",
        maker: "nvidia",
        memory: 2 * 1024 ** 3,
        integrated: false,
        driver: "551.86",
      },
      subtitles: { best: null, fast: "card", bestWants: "memory" },
    };
    const fetch = engine("ready", small);
    renderMake();

    const best = await screen.findByRole("radio", { name: "Best" });
    await waitFor(() => expect(best).toBeDisabled());
    expect(best).toHaveTextContent("Not on this card");
    expect(best).toHaveTextContent(
      "Wants a graphics card with 4 GB of its own memory; this one has 2 GB.",
    );
    const fast = screen.getByRole("radio", { name: "Fast" });
    expect(fast).toBeChecked();
    expect(fast).toHaveTextContent("Right for this PC");
    expect(fast).toHaveTextContent("≈ 4 min per episode on this PC");

    screen.getByRole("button", { name: /Make subtitles for 2 episodes/ }).click();

    await waitFor(() => expect(sent(fetch, "POST", "/subtitles")).toHaveLength(1));
    const [[, init]] = sent(fetch, "POST", "/subtitles") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toMatchObject({ quality: "fast" });
  });

  it("names DirectX 12 when that's what Best wants here", async () => {
    engine("ready", {
      ...SYSTEM,
      subtitles: { best: null, fast: "processor", bestWants: "directx" },
    });
    renderMake();

    const best = await screen.findByRole("radio", { name: "Best" });
    await waitFor(() => expect(best).toBeDisabled());
    expect(best).toHaveTextContent("Wants a graphics card that runs DirectX 12; this one doesn't.");
  });
});
