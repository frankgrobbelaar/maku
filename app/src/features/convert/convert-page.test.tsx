import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  type Convertible,
  type ConvertOptions,
  EngineProvider,
  type FranchiseSummary,
  type QueueStatus,
  type System,
  type TitleSummary,
} from "@/lib/engine";
import { convertible } from "@/test/convert";
import { fakeEngine, READY, SETTINGS, SYSTEM, UNCHECKED } from "@/test/engine";
import { ConvertPage } from "./convert-page";

const shell = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => {} }));

const WINTER = "Glass Orchard: The Long Winter";

/** A 4K HDR film in AV1, made HEVC 10-bit: at 4K it stays 4K. */
const FILM: Convertible = convertible(5, {
  titleId: 2,
  title: WINTER,
  label: WINTER,
  season: null,
  episode: null,
  seconds: 7200,
  width: 3840,
  height: 2160,
  hdr: "HDR10",
  size: 20_000_000_000,
  reasons: ["AV1 becomes HEVC 10-bit, HDR kept"],
  outputWidth: 3840,
  outputHeight: 2160,
  gpuSeconds: 4800,
  outputBytes: 18_000_000_000,
});

const OPTIONS: ConvertOptions = {
  standard: "4K",
  files: [
    convertible(1),
    convertible(2),
    convertible(3, { season: 2, episode: 1, label: "Glass Orchard · S02E01" }),
    convertible(4, {
      titleId: 2,
      title: WINTER,
      label: WINTER,
      season: null,
      episode: null,
      broken: true,
      gpuSeconds: 0,
      outputBytes: 0,
    }),
    FILM,
  ],
  free: { "D:": 931_000_000_000 },
  setAside: {},
};

/** The same, at 1080p: the film comes down to it. */
const AT_1080: ConvertOptions = {
  ...OPTIONS,
  standard: "1080p",
  files: OPTIONS.files.map((file) =>
    file.fileId === 5
      ? {
          ...file,
          reasons: ["4K HDR: brought down to 1080p, HDR kept"],
          outputWidth: 1920,
          outputHeight: 1080,
          outputBytes: 9_000_000_000,
        }
      : file,
  ),
};

const COLLECTIONS = [
  {
    id: 1,
    name: "The Glass Orchard Collection",
    titles: [
      { id: 1, name: "Glass Orchard" },
      { id: 2, name: WINTER },
    ] as TitleSummary[],
  },
] as FranchiseSummary[];

const QUEUE: QueueStatus = {
  paused: false,
  schedule: "now",
  waitsForNight: false,
  problem: null,
  running: null,
  queued: [],
  gpuSeconds: 0,
  today: [],
  gpu: null,
  room: null,
  endsAt: null,
  early: false,
};

function renderConvert(address = "/convert") {
  shell.invoke.mockImplementation(async (command: string) =>
    command === "engine_status" ? READY : undefined,
  );
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <EngineProvider>
        <MemoryRouter initialEntries={[address]}>
          <Routes>
            <Route path="/convert" element={<ConvertPage />} />
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

/** The engine with these answers, and the owner's settings kept as they're saved. */
function withSettings(answers: Record<string, unknown>) {
  const kept = { saved: SETTINGS };
  const fetch = fakeEngine({
    "/franchises": COLLECTIONS,
    "/queue": QUEUE,
    "/settings": () => kept.saved,
    "PUT /settings": (init?: RequestInit) => {
      kept.saved = JSON.parse(String(init?.body));
      return kept.saved;
    },
    ...answers,
  });
  return { fetch, kept };
}

describe("ConvertPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    shell.invoke.mockReset();
  });

  it("lists what isn't at the standard by collection, title and season", async () => {
    fakeEngine({ "/convert": OPTIONS, "/franchises": COLLECTIONS, "/queue": QUEUE });
    renderConvert();

    expect(
      await screen.findByRole("checkbox", { name: /The Glass Orchard Collection\s*collection/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /^Glass Orchard\s*3 left/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Season 1\s*2 episodes/ })).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: /The Long Winter\s*1 left, 1 broken skipped/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("Nothing chosen yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose what to convert" })).toBeDisabled();
  });

  it("finds a title to convert by its name, or its collection's whole", async () => {
    fakeEngine({ "/convert": OPTIONS, "/franchises": COLLECTIONS, "/queue": QUEUE });
    renderConvert();

    const search = await screen.findByRole("searchbox", { name: "Search what to convert" });
    expect(search).toHaveAttribute("placeholder", "Search 2 titles");
    fireEvent.change(search, { target: { value: "winter" } });

    // The title found stands on its own: ticking it ticks only its files.
    const winter = await screen.findByRole("checkbox", { name: /The Long Winter\s*1 left/ });
    expect(screen.queryByRole("checkbox", { name: /collection$/ })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("checkbox", { name: /^Glass Orchard\s*3 left/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(winter);
    expect(await screen.findByText("1 file")).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "orchard collection" } });
    expect(
      await screen.findByRole("checkbox", { name: /The Glass Orchard Collection\s*collection/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /^Glass Orchard\s*3 left/ })).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "Starfall" } });
    expect(await screen.findByRole("status")).toHaveTextContent("No title goes by “Starfall”.");
  });

  it("adds up what's chosen, what it gets, and what it takes", async () => {
    fakeEngine({ "/convert": OPTIONS, "/franchises": COLLECTIONS, "/queue": QUEUE });
    renderConvert();

    (await screen.findByRole("checkbox", { name: /Season 1/ })).click();

    expect(await screen.findAllByText("2 episodes")).toHaveLength(2); // the season, and the chip
    expect(screen.getByText("1 h 30 min of video")).toBeInTheDocument();
    expect(screen.getByText("1080p · 16:9")).toBeInTheDocument();
    const how = screen.getByRole("region", { name: "How" });
    expect(how).toHaveTextContent("What they get2H.264 becomes HEVC 10-bit");
    expect(how).toHaveTextContent(
      "Made on the graphics card's encoder, about 6 min a file. Every sound track stays as it is",
    );
    expect(screen.getByText("≈ 12 min")).toBeInTheDocument();
    expect(screen.getByText("4.0 GB → 2.4 GB")).toBeInTheDocument();
    expect(screen.getByText("≈ 1.2 GB per episode")).toBeInTheDocument();
    expect(screen.getByText("free, plenty for this")).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: /^Glass Orchard\s*3 left/ }),
    ).toBePartiallyChecked();
  });

  it("says what everything gets before anything is chosen", async () => {
    fakeEngine({ "/convert": OPTIONS, "/franchises": COLLECTIONS, "/queue": QUEUE });
    renderConvert();

    const how = await screen.findByRole("region", { name: "How" });

    expect(how).toHaveTextContent("What the files get");
    expect(how).toHaveTextContent("3H.264 becomes HEVC 10-bit");
    expect(how).toHaveTextContent("1AV1 becomes HEVC 10-bit, HDR kept");
  });

  it("starts with the videos ticked on a title's page chosen", async () => {
    fakeEngine({ "/convert": OPTIONS, "/franchises": COLLECTIONS, "/queue": QUEUE });
    renderConvert("/convert?files=1,2,4,junk"); // 4 won't play: it can't be converted

    expect(await screen.findAllByText("2 episodes")).toHaveLength(2); // the season, and the chip
    expect(screen.getByRole("checkbox", { name: /Season 1/ })).toBeChecked();
  });

  it("explains the two standards in a line each", async () => {
    withSettings({ "/convert": OPTIONS });
    renderConvert();

    const how = await screen.findByRole("region", { name: "How" });

    expect(await screen.findByText("Up to 4K · HEVC 10-bit · MKV")).toBeInTheDocument();
    expect(how).toHaveTextContent(
      "4K4K stays 4K, with its HDR. Nothing is made bigger than it is.",
    );
    expect(how).toHaveTextContent(
      "1080p4K comes down to 1080p to save room, its HDR kept. Nothing is made bigger.",
    );
  });

  it("chooses the standard right here, and what the files get follows", async () => {
    const { fetch, kept } = withSettings({
      "/convert": () => (kept.saved.standard === "1080p" ? AT_1080 : OPTIONS),
    });
    renderConvert();

    (await screen.findByRole("checkbox", { name: /The Long Winter/ })).click();
    expect(await screen.findByText("20 GB → 18 GB")).toBeInTheDocument();
    expect(screen.getByText("4K HDR · 16:9")).toBeInTheDocument();
    (await screen.findByRole("radio", { name: "1080p" })).click();

    expect(await screen.findByText("20 GB → 9.0 GB")).toBeInTheDocument();
    expect(kept.saved.standard).toBe("1080p");
    expect(sent(fetch, "PUT", "/settings")).toHaveLength(1);
    expect(screen.getByText("Up to 1080p · HEVC 10-bit · MKV")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "How" })).toHaveTextContent(
      "4K HDR: brought down to 1080p, HDR kept",
    );
  });

  it("deletes originals once checked when asked, and reckons room that way", async () => {
    const small = (id: number) => convertible(id, { outputBytes: 400_000_000 }); // from 2 GB
    const { kept } = withSettings({
      "/convert": { ...OPTIONS, files: [small(1), small(2)], free: { "D:": 600_000_000 } },
    });
    renderConvert();

    (await screen.findByRole("checkbox", { name: /^Glass Orchard/ })).click();
    expect(await screen.findByText(/free: not enough, this needs 1\.0 GB/)).toBeInTheDocument();
    expect(screen.getByText("Kept 30 days")).toBeInTheDocument();
    screen.getByRole("radio", { name: "Delete" }).click();

    expect(await screen.findByText("Deleted")).toBeInTheDocument();
    expect(kept.saved.originals).toBe("delete");
    expect(
      screen.getByText("for good, once each result is checked and in place: no putting back"),
    ).toBeInTheDocument();
    expect(await screen.findByText("free, plenty for this")).toBeInTheDocument();
  });

  it("offers the other standard when everything is at this one", async () => {
    const { kept } = withSettings({
      "/convert": () =>
        kept.saved.standard === "1080p" ? AT_1080 : { ...OPTIONS, files: [] as never[] },
    });
    renderConvert();

    expect(
      await screen.findByRole("heading", { name: "Everything is at your standard" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/HEVC 10-bit in MKV, none over 4K/)).toBeInTheDocument();
    (await screen.findByRole("radio", { name: "1080p" })).click();

    expect(await screen.findByRole("checkbox", { name: /Season 1/ })).toBeInTheDocument();
    expect(kept.saved.standard).toBe("1080p");
  });

  it("queues what's chosen to start now, then shows the queue", async () => {
    const fetch = fakeEngine({
      "/convert": OPTIONS,
      "/franchises": COLLECTIONS,
      "/queue": QUEUE,
      "POST /queue": { added: 3 },
    });
    renderConvert();

    (await screen.findByRole("checkbox", { name: /^Glass Orchard\s*3 left/ })).click();
    (await screen.findByRole("button", { name: "Add 3 episodes to the queue" })).click();

    expect(await screen.findByText("The queue")).toBeInTheDocument();
    const [[, init]] = sent(fetch, "POST", "/queue") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ files: [1, 2, 3], when: "now", fit: [] });
  });

  it("can queue for the night instead, in one step", async () => {
    const fetch = fakeEngine({
      "/convert": OPTIONS,
      "/franchises": COLLECTIONS,
      "/queue": QUEUE,
      "POST /queue": { added: 2 },
    });
    renderConvert();

    (await screen.findByRole("checkbox", { name: /Season 1/ })).click();
    (await screen.findByRole("radio", { name: /Nights only/ })).click();
    (await screen.findByRole("button", { name: "Add 2 episodes to the queue" })).click();

    expect(await screen.findByText("The queue")).toBeInTheDocument();
    const [[, init]] = sent(fetch, "POST", "/queue") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toMatchObject({ when: "nights" });
    expect(sent(fetch, "PUT", "/queue/schedule")).toHaveLength(0);
  });

  it("warns of a drive without room, though another has plenty", async () => {
    fakeEngine({
      "/convert": {
        ...OPTIONS,
        files: [convertible(1), convertible(2, { drive: "F:" })],
        free: { "D:": 931_000_000_000, "F:": 200_000_000 },
      },
      "/franchises": COLLECTIONS,
      "/queue": QUEUE,
    });
    renderConvert();

    (await screen.findByRole("checkbox", { name: /^Glass Orchard\s*2 left/ })).click();

    expect(await screen.findByText("Space on F:")).toBeInTheDocument();
    expect(screen.getByText("free: not enough, this needs 1.5 GB")).toBeInTheDocument();
  });

  /** Two episodes of 450 MB each to make on D:, with 600 MB free and 3.4 GB set aside there. */
  const TIGHT: ConvertOptions = {
    ...OPTIONS,
    files: OPTIONS.files.map((file) => ({ ...file, outputBytes: 450_000_000 })),
    free: { "D:": 600_000_000 },
    setAside: { "D:": 3_400_000_000 },
  };

  it("asks what to do when a drive hasn't room for the choice", async () => {
    const fetch = fakeEngine({
      "/convert": TIGHT,
      "/franchises": COLLECTIONS,
      "/queue": QUEUE,
      "POST /queue": { added: 2 },
    });
    renderConvert();

    (await screen.findByRole("checkbox", { name: /Season 1/ })).click();
    (await screen.findByRole("button", { name: "Add 2 episodes to the queue" })).click();

    const dialog = await screen.findByRole("alertdialog", { name: "Not enough space" });
    expect(dialog).toHaveTextContent(
      "Glass Orchard · Season 1 needs about 1.1 GB. D: has 600 MB free.",
    );
    expect(sent(fetch, "POST", "/queue")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add 2 episodes to the queue" }));
    fireEvent.click(await screen.findByRole("button", { name: /Convert the 1 that fit now/ }));

    expect(await screen.findByText("The queue")).toBeInTheDocument();
    const [[, init]] = sent(fetch, "POST", "/queue") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toMatchObject({ files: [1, 2], fit: ["D:"] });
  });

  it("empties the drive's quarantine first, once that's confirmed, then queues", async () => {
    const fetch = fakeEngine({
      "/convert": TIGHT,
      "/franchises": COLLECTIONS,
      "/queue": QUEUE,
      "POST /queue": { added: 2 },
      "POST /quarantine/empty": { files: 4 },
    });
    renderConvert();

    (await screen.findByRole("checkbox", { name: /Season 1/ })).click();
    (await screen.findByRole("button", { name: "Add 2 episodes to the queue" })).click();
    fireEvent.click(await screen.findByRole("button", { name: /Empty quarantine first/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Empty quarantine" }));

    expect(await screen.findByText("The queue")).toBeInTheDocument();
    const [[, emptied]] = sent(fetch, "POST", "/quarantine/empty") as [[unknown, RequestInit]];
    expect(JSON.parse(String(emptied.body))).toEqual({ drive: "D:" });
    const [[, init]] = sent(fetch, "POST", "/queue") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toMatchObject({ files: [1, 2], fit: [] });
  });

  it("shows a frame before and after, at three points of the file", async () => {
    const problem = "ffmpeg couldn't make the frame: Invalid data found when processing input.";
    const fetch = fakeEngine({
      "/convert": OPTIONS,
      "/franchises": COLLECTIONS,
      "/queue": QUEUE,
      "/convert/1/preview/after": () => Response.json({ detail: problem }, { status: 422 }),
    });
    renderConvert();

    const panel = await screen.findByRole("region", { name: "See it first" });
    expect(panel).toHaveTextContent("Glass Orchard · S01E01 · drag the handle");
    expect(panel).toHaveTextContent("Before · original 1080p");
    expect(panel).toHaveTextContent("After · HEVC 10-bit 1080p");
    expect(screen.getByRole("button", { name: "22:30" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText(problem)).toBeInTheDocument();

    screen.getByRole("button", { name: "6:45" }).click();

    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([input]) =>
          String(input).endsWith("/convert/1/preview/after?point=0"),
        ),
      ).toBe(true),
    );
  });

  it("says when everything is at the standard", async () => {
    fakeEngine({
      "/convert": { ...OPTIONS, files: [] },
      "/franchises": COLLECTIONS,
      "/queue": QUEUE,
    });
    renderConvert();

    expect(
      await screen.findByRole("heading", { name: "Everything is at your standard" }),
    ).toBeInTheDocument();
  });

  it("names the encoder this PC converts with", async () => {
    const laptop: System = { ...SYSTEM, encoder: "qsv" };
    fakeEngine({
      "/convert": OPTIONS,
      "/franchises": COLLECTIONS,
      "/queue": QUEUE,
      "/system": laptop,
    });
    renderConvert();

    expect(await screen.findByText(/Made on the Intel Quick Sync encoder/)).toBeInTheDocument();
  });

  it("says its times are this PC's own once it's measured", async () => {
    fakeEngine({
      "/convert": OPTIONS,
      "/franchises": COLLECTIONS,
      "/queue": QUEUE,
      "/system": SYSTEM,
    });
    renderConvert();

    expect(
      await screen.findByText("Measured on this PC · NVIDIA GeForce GTX 1660 SUPER"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/These times are a guess/)).toBeNull();
  });

  it("says its times are a guess till this PC is measured, and tests it on asking", async () => {
    const fetch = fakeEngine({
      "/convert": OPTIONS,
      "/franchises": COLLECTIONS,
      "/queue": QUEUE,
      "/system": UNCHECKED,
      "POST /system/test": {
        ...UNCHECKED,
        testing: { step: "encoder", done: [], fps: null, timing: true },
      },
    });
    renderConvert();

    expect(
      await screen.findByText(
        "These times are a guess, from a GTX 1660 Super, until Maku has measured this PC.",
      ),
    ).toBeInTheDocument();
    screen.getByRole("button", { name: "Test this PC" }).click();

    await waitFor(() => expect(sent(fetch, "POST", "/system/test")).toHaveLength(1));
  });

  it("says when this PC can't convert, and what still works", async () => {
    const r7: System["card"] = {
      name: "AMD Radeon R7 250",
      maker: "amd",
      memory: 2 * 1024 ** 3,
      integrated: false,
      driver: "27.20.20913.2000",
    };
    fakeEngine({
      "/convert": OPTIONS,
      "/franchises": COLLECTIONS,
      "/queue": QUEUE,
      "/system": { ...SYSTEM, card: r7, graphicsCard: r7?.name ?? null, encoder: null },
    });
    renderConvert();

    expect(await screen.findByText("This PC can't convert to your standard")).toBeInTheDocument();
    expect(
      screen.getByText(/Its graphics card, an AMD Radeon R7 250, has no encoder for HEVC 10-bit/),
    ).toHaveTextContent("English subtitles and the player");
    expect(screen.getByRole("button", { name: "Test this PC again" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "How" })).toBeNull();
  });

  it("links the card maker's drivers when its encoder didn't start", async () => {
    fakeEngine({
      "/convert": OPTIONS,
      "/franchises": COLLECTIONS,
      "/queue": QUEUE,
      "/system": {
        ...SYSTEM,
        encoder: null,
        driverLink: "https://www.nvidia.com/Download/index.aspx",
        encoderProblem: "Driver does not support the required nvenc API version.",
      },
    });
    renderConvert();

    expect(await screen.findByText("NVIDIA's encoder didn't start")).toBeInTheDocument();
    expect(
      screen.getByText("hevc_nvenc: Driver does not support the required nvenc API version"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "NVIDIA's drivers" })).toHaveAttribute(
      "href",
      "https://www.nvidia.com/Download/index.aspx",
    );
  });
});
