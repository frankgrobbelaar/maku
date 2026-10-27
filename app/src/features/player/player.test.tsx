import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EngineProvider, type OpenedVideo, type PlayerState } from "@/lib/engine";
import { fakeEngine, READY } from "@/test/engine";
import { PlayerLayer } from "./player";
import { PlayerProvider, type PlayItem, usePlayer } from "./player-context";

const shell = vi.hoisted(() => ({ invoke: vi.fn(), setFullscreen: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => {} }));
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({ setFullscreen: shell.setFullscreen }),
}));

const EPISODES: PlayItem[] = [
  {
    fileId: 5,
    label: "The Harbour Line · S01E05",
    name: "The Night Ferry",
    path: "F:\\Videos\\TV\\The Harbour Line (1989)\\Season 01\\The Harbour Line (1989) - S01E05.mkv",
  },
  {
    fileId: 6,
    label: "The Harbour Line · S01E06",
    name: "A Light in the Fog",
    path: "F:\\Videos\\TV\\The Harbour Line (1989)\\Season 01\\The Harbour Line (1989) - S01E06.mkv",
  },
];

const OPENED: OpenedVideo = {
  ticket: "T1",
  missing: null,
  drive: "F:",
  duration: 1453,
  sound: [
    { number: 0, language: "jpn", title: null, channels: 2, default: true },
    { number: 1, language: "eng", title: null, channels: 6, default: false },
  ],
  subtitles: [
    {
      number: 0,
      language: "eng",
      title: null,
      kind: "styled",
      default: true,
      forced: false,
      beside: false,
      made: false,
    },
    {
      number: 1,
      language: "eng",
      title: "Signs",
      kind: "pictures",
      default: false,
      forced: true,
      beside: false,
      made: false,
    },
  ],
  chapters: [
    { start: 0, title: "Opening" },
    { start: 90, title: "Part A" },
  ],
  chosenSound: 0,
  chosenSubtitles: 0,
  ready: [0, 1],
};

const READY_STATE: PlayerState = { ready: [0, 1], preparing: [], failed: [], stopped: null };

let paused = true;

function renderPlayer(
  answers: Record<string, unknown>,
  items = EPISODES,
  from: number | undefined = undefined,
) {
  const fetch = fakeEngine({
    "POST /player": OPENED,
    "/player/T1": READY_STATE,
    "DELETE /player/T1": null,
    ...answers,
  });
  shell.invoke.mockImplementation(async (command: string) =>
    command === "engine_status" ? READY : undefined,
  );
  function Start() {
    const { play } = usePlayer();
    return (
      <button type="button" onClick={() => play(items, 0, from)}>
        Start
      </button>
    );
  }
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <EngineProvider>
        <PlayerProvider>
          <Start />
          <PlayerLayer />
        </PlayerProvider>
      </EngineProvider>
    </QueryClientProvider>,
  );
  return fetch;
}

async function started() {
  (await screen.findByRole("button", { name: "Start" })).click();
  return screen.findByRole("region", { name: "Player" });
}

/** The <video>, once the stream's address is set: its first picture is up. */
async function playing(): Promise<HTMLVideoElement> {
  const player = await screen.findByRole("region", { name: "Player" });
  const video = player.querySelector("video");
  if (!video) throw new Error("no video");
  await waitFor(() => expect(video.getAttribute("src")).toBeTruthy());
  paused = false;
  fireEvent(video, new Event("playing"));
  return video;
}

/** The stream has played to `seconds` in. */
function playedTo(video: HTMLVideoElement, seconds: number) {
  Object.defineProperty(video, "currentTime", { value: seconds, configurable: true });
  fireEvent(video, new Event("timeupdate"));
}

function asked_(video: HTMLVideoElement) {
  return asked(video.getAttribute("src"));
}

function asked(src: string | null) {
  const address = new URL(src ?? "");
  return {
    path: address.pathname,
    at: address.searchParams.get("at"),
    sound: address.searchParams.get("sound"),
    subtitles: address.searchParams.get("subtitles"),
  };
}

function sent(fetch: ReturnType<typeof fakeEngine>, method: string, path: string) {
  return fetch.mock.calls.filter(
    ([input, init]) =>
      (init?.method ?? "GET") === method && new URL(String(input)).pathname === path,
  );
}

describe("PlayerLayer", () => {
  beforeEach(() => {
    paused = true;
    shell.setFullscreen.mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, "paused", "get").mockImplementation(() => paused);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(async () => {
      paused = false;
    });
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {
      paused = true;
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    shell.invoke.mockReset();
    shell.setFullscreen.mockReset();
    localStorage.clear();
  });

  it("plays a video small over the page, named, from the stream the engine makes", async () => {
    const fetch = renderPlayer({});
    const player = await started();

    expect(within(player).getByRole("status")).toHaveTextContent("Getting it ready");
    expect(player).toHaveTextContent("Reading the file from F:");
    const video = await playing();
    expect(asked(video.getAttribute("src"))).toEqual({
      path: "/stream/T1",
      at: "0.000",
      sound: "0",
      subtitles: "0",
    });
    expect(player).toHaveTextContent("The Harbour Line · S01E05");
    expect(player).toHaveTextContent("The Night Ferry");
    expect(player).toHaveTextContent("Drag to move");
    expect(player).toHaveTextContent("00:00 / 24:13");
    await waitFor(() =>
      expect(within(player).queryByText("Getting it ready")).not.toBeInTheDocument(),
    );
    const [[, init]] = sent(fetch, "POST", "/player") as [[unknown, RequestInit]];
    expect(JSON.parse(String(init.body))).toEqual({ file: 5 });
  });

  it("starts the stream again from wherever it's sought to", async () => {
    renderPlayer({});
    await started();
    const video = await playing();

    const where = screen.getByRole("slider", { name: "Where it plays" });
    fireEvent.change(where, { target: { value: "600" } });
    fireEvent.pointerUp(where);

    await waitFor(() => expect(asked(video.getAttribute("src")).at).toBe("600.000"));
    fireEvent(video, new Event("playing"));
    screen.getByRole("button", { name: "Full screen" }).click();
    (await screen.findByRole("button", { name: "On 10 seconds" })).click();
    await waitFor(() => expect(asked(video.getAttribute("src")).at).toBe("610.000"), {
      timeout: 2000,
    });
  });

  it("adds the subtitles once they're copied out, from where it plays then", async () => {
    let calls = 0;
    renderPlayer({
      "POST /player": { ...OPENED, ready: [1] },
      "/player/T1": () => {
        calls += 1;
        return calls === 1
          ? { ...READY_STATE, ready: [1], preparing: [0] }
          : { ...READY_STATE, ready: [0, 1] };
      },
    });
    const player = await started();
    const video = await playing();
    expect(asked(video.getAttribute("src")).subtitles).toBeNull();
    await waitFor(() => expect(player).toHaveTextContent("Subtitles in a moment"));

    Object.defineProperty(video, "currentTime", { value: 12, configurable: true });
    fireEvent(video, new Event("timeupdate"));

    await waitFor(() => expect(asked(video.getAttribute("src")).subtitles).toBe("0"), {
      timeout: 3000,
    });
    expect(asked(video.getAttribute("src")).at).toBe("12.000");
  });

  it("changes the sound and subtitles from the menu, and starts the next video the same way", async () => {
    renderPlayer({});
    await started();
    const video = await playing();

    fireEvent.keyDown(screen.getByRole("button", { name: "Sound and subtitles" }), {
      key: "Enter",
    });
    const english = await screen.findByRole("menuitemradio", { name: /^English5\.1/ });
    expect(screen.getByRole("menuitemradio", { name: /^Japanese/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(
      screen.getByRole("menuitemradio", { name: /^Englishas the file styles them/ }),
    ).toHaveAttribute("aria-checked", "true");
    english.click();
    await waitFor(() => expect(asked(video.getAttribute("src")).sound).toBe("1"));

    fireEvent.keyDown(screen.getByRole("button", { name: "Sound and subtitles" }), {
      key: "Enter",
    });
    (await screen.findByRole("menuitemradio", { name: "Off" })).click();
    await waitFor(() => expect(asked(video.getAttribute("src")).subtitles).toBeNull());

    // The next episode starts in English, without subtitles, as the owner left it.
    fireEvent(video, new Event("playing"));
    screen.getByRole("button", { name: "Next episode" }).click();
    await waitFor(() => {
      const next = screen.getByRole("region", { name: "Player" }).querySelector("video");
      expect(asked(next?.getAttribute("src") ?? "http://x/").sound).toBe("1");
    });
    const next = screen.getByRole("region", { name: "Player" });
    expect(next).toHaveTextContent("A Light in the Fog");
    expect(asked(next.querySelector("video")?.getAttribute("src") ?? "").subtitles).toBeNull();
  });

  it("marks the English subtitles Maku made, and says they can be off", async () => {
    const made: OpenedVideo = {
      ...OPENED,
      subtitles: [
        ...OPENED.subtitles,
        {
          number: 2,
          language: "en",
          title: null,
          kind: "text",
          default: false,
          forced: false,
          beside: true,
          made: true,
        },
      ],
    };
    renderPlayer({ "POST /player": made });
    await started();
    await playing();

    fireEvent.keyDown(screen.getByRole("button", { name: "Sound and subtitles" }), {
      key: "Enter",
    });

    expect(
      await screen.findByRole("menuitemradio", { name: /^Englishmade by Maku$/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Maku made the English ones from the sound: names and jokes can be off."),
    ).toBeInTheDocument();
  });

  it("takes a mouse's pick from its menu, the press starting no drag", async () => {
    renderPlayer({});
    await started();
    const video = await playing();
    // As a browser does: once an element captures the pointer, the press's up and click go to it.
    let captured: Element | null = null;
    const had = Object.getOwnPropertyDescriptor(Element.prototype, "setPointerCapture");
    Object.defineProperty(Element.prototype, "setPointerCapture", {
      configurable: true,
      writable: true,
      value(this: Element) {
        captured = this;
      },
    });
    try {
      fireEvent.keyDown(screen.getByRole("button", { name: "Sound and subtitles" }), {
        key: "Enter",
      });
      const english = await screen.findByRole("menuitemradio", { name: /^English5\.1/ });
      fireEvent.pointerDown(english, { button: 0, pointerId: 1, pointerType: "mouse" });
      const target = captured ?? english;
      fireEvent.pointerUp(target, { button: 0, pointerId: 1, pointerType: "mouse" });
      fireEvent.click(target);

      await waitFor(() => expect(asked_(video).sound).toBe("1"));
      expect(captured).toBeNull();
    } finally {
      if (had) Object.defineProperty(Element.prototype, "setPointerCapture", had);
      else Reflect.deleteProperty(Element.prototype, "setPointerCapture");
    }
  });

  it("goes full screen and back, Esc leaving it too", async () => {
    renderPlayer({});
    await started();
    await playing();

    screen.getByRole("button", { name: "Full screen" }).click();

    await waitFor(() => expect(shell.setFullscreen).toHaveBeenLastCalledWith(true));
    const player = screen.getByRole("region", { name: "Player" });
    expect(player).toHaveTextContent("The Night Ferry");
    expect(
      within(player).getAllByRole("button", { name: "Back to the small player" }),
    ).toHaveLength(2);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(shell.setFullscreen).toHaveBeenLastCalledWith(false));
    expect(screen.getByText("Drag to move")).toBeInTheDocument();
  });

  it("says when the video's drive isn't connected, and plays once it's back", async () => {
    let plugged = false;
    renderPlayer({
      "POST /player": () =>
        plugged
          ? OPENED
          : { ...OPENED, ticket: null, missing: "drive", sound: [], subtitles: [], ready: [] },
    });
    const player = await started();

    expect(await within(player).findByText("F: isn't connected")).toBeInTheDocument();
    expect(player).toHaveTextContent("Plug the drive in and press Play again.");
    plugged = true;
    within(player).getByRole("button", { name: "Play again" }).click();

    await playing();
  });

  it("says why a file won't play from where it stopped, and shows it in its folder", async () => {
    renderPlayer({
      "/player/T1": { ...READY_STATE, stopped: { why: "damaged", detail: "Invalid data" } },
    });
    const player = await started();
    const video = await playing();
    Object.defineProperty(video, "currentTime", { value: 252, configurable: true });
    fireEvent(video, new Event("timeupdate"));

    fireEvent(video, new Event("ended"));

    expect(
      await within(player).findByText(
        "Its picture is damaged at 04:12, so Maku stopped there. The file is as it was.",
      ),
    ).toBeInTheDocument();
    within(player).getByRole("button", { name: "Open its folder" }).click();
    await waitFor(() =>
      expect(shell.invoke).toHaveBeenCalledWith("show_in_folder", { path: EPISODES[0]?.path }),
    );
  });

  it("picks a video up where it stopped, and starts over when asked", async () => {
    const [first, second] = EPISODES as [PlayItem, PlayItem];
    renderPlayer({}, [{ ...first, resume: 600 }, second]);
    const player = await started();
    const video = await playing();

    expect(asked(video.getAttribute("src")).at).toBe("600.000");
    expect(await within(player).findByText("Picked up at 10:00")).toBeInTheDocument();
    within(player).getByRole("button", { name: "Start over" }).click();

    await waitFor(() => expect(asked(video.getAttribute("src")).at).toBe("0.000"));
    expect(within(player).queryByText("Picked up at 10:00")).not.toBeInTheDocument();
  });

  it("says where the video is as it plays, and as it stops", async () => {
    const fetch = renderPlayer({ "PUT /files/5/position": null });
    await started();
    const video = await playing();
    const told = () =>
      sent(fetch, "PUT", "/files/5/position").map(([, init]) =>
        JSON.parse(String((init as RequestInit).body)),
      );

    for (let second = 1; second <= 9; second += 1) playedTo(video, second);
    expect(told()).toEqual([]); // a look, so far
    for (let second = 10; second <= 12; second += 1) playedTo(video, second);
    await waitFor(() => expect(told()).toEqual([{ position: 10, duration: 1453 }]));

    screen.getByRole("button", { name: "Close the player" }).click();
    await waitFor(() => expect(told()).toHaveLength(2));
    expect(told()[1]).toEqual({ position: 12, duration: 1453 });
  });

  it("keeps nothing of a look of a few seconds", async () => {
    const fetch = renderPlayer({ "PUT /files/5/position": null });
    await started();
    const video = await playing();
    for (let second = 1; second <= 4; second += 1) playedTo(video, second);

    screen.getByRole("button", { name: "Close the player" }).click();

    await waitFor(() => expect(sent(fetch, "DELETE", "/player/T1")).toHaveLength(1));
    expect(sent(fetch, "PUT", "/files/5/position")).toHaveLength(0);
  });

  it("says a video was seen to its end", async () => {
    const fetch = renderPlayer({ "PUT /files/5/position": null });
    await started();
    const video = await playing();
    for (let second = 1; second <= 12; second += 1) playedTo(video, 1440 + second);

    fireEvent(video, new Event("ended"));

    await waitFor(() =>
      expect(
        sent(fetch, "PUT", "/files/5/position").map(([, init]) =>
          JSON.parse(String((init as RequestInit).body)),
        ),
      ).toContainEqual({ position: 1453, duration: 1453 }),
    );
  });

  it("closes, letting go of the video", async () => {
    const fetch = renderPlayer({});
    await started();
    await playing();

    screen.getByRole("button", { name: "Close the player" }).click();

    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Player" })).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(sent(fetch, "DELETE", "/player/T1")).toHaveLength(1));
  });

  it("pauses on a click on the picture, its controls stepping aside while it plays", async () => {
    renderPlayer({});
    const player = await started();
    const video = await playing();
    const controls = within(player).getByRole("button", { name: "Pause" }).closest("div");

    expect(controls).toHaveClass("opacity-0"); // the subtitles at the picture's foot show
    fireEvent.pointerEnter(player);
    expect(controls).not.toHaveClass("opacity-0");

    // The player holds the pointer from the press: the release is its own, wherever it ends.
    fireEvent.pointerDown(video, { button: 0, clientX: 40, clientY: 40, pointerId: 1 });
    fireEvent.pointerUp(player, { clientX: 40, clientY: 40, pointerId: 1 });

    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
    expect(await within(player).findByRole("button", { name: "Play" })).toBeInTheDocument();
    fireEvent.pointerLeave(player);
    expect(controls).not.toHaveClass("opacity-0"); // paused, they stay
  });

  it("plays the next episode full screen when it was", async () => {
    renderPlayer({
      "POST /player": (init?: RequestInit) => ({
        ...OPENED,
        ticket: `T${JSON.parse(String(init?.body)).file}`,
      }),
      "/player/T5": READY_STATE,
      "/player/T6": READY_STATE,
      "DELETE /player/T5": null,
    });
    await started();
    await playing();
    screen.getByRole("button", { name: "Full screen" }).click();
    await waitFor(() => expect(shell.setFullscreen).toHaveBeenLastCalledWith(true));

    (await screen.findByRole("button", { name: "Next episode" })).click();

    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Player" })).toHaveTextContent(
        "A Light in the Fog",
      ),
    );
    const next = screen.getByRole("region", { name: "Player" });
    expect(within(next).getAllByRole("button", { name: "Back to the small player" })).toHaveLength(
      2,
    );
    expect(shell.setFullscreen).not.toHaveBeenCalledWith(false);
  });

  it("leaves the subtitles out when the ones chosen can't be got ready", async () => {
    const three: OpenedVideo = {
      ...OPENED,
      subtitles: [
        ...OPENED.subtitles,
        {
          number: 2,
          language: "ger",
          title: null,
          kind: "text",
          default: false,
          forced: false,
          beside: false,
          made: false,
        },
      ],
    };
    let asked = false;
    renderPlayer({
      "POST /player": three,
      "POST /player/T1/subtitles/2": () => {
        asked = true;
        return { ...READY_STATE, preparing: [2] };
      },
      "/player/T1": () =>
        asked
          ? { ...READY_STATE, failed: [{ number: 2, problem: "ffmpeg couldn't copy them out." }] }
          : READY_STATE,
    });
    await started();
    const video = await playing();
    expect(asked_(video).subtitles).toBe("0");

    fireEvent.keyDown(screen.getByRole("button", { name: "Sound and subtitles" }), {
      key: "Enter",
    });
    (await screen.findByRole("menuitemradio", { name: /^German/ })).click();

    await waitFor(() => expect(asked_(video).subtitles).toBeNull(), { timeout: 3000 });
  });

  it("goes full screen and back without moving the small player from where it was put", async () => {
    renderPlayer({});
    const player = await started();
    await playing();
    act(() => {
      fireEvent.pointerDown(player, { button: 0, clientX: 100, clientY: 100, pointerId: 1 });
      fireEvent.pointerMove(player, { clientX: 300, clientY: 250, pointerId: 1 });
      fireEvent.pointerUp(player, { clientX: 300, clientY: 250, pointerId: 1 });
    });

    screen.getByRole("button", { name: "Full screen" }).click();
    act(() => {
      window.dispatchEvent(new Event("resize")); // the window going full screen
    });
    (await screen.findAllByRole("button", { name: "Back to the small player" }))[0]?.click();

    const small = await screen.findByRole("region", { name: "Player" });
    await waitFor(() => expect(small).toHaveTextContent("Drag to move"));
    expect(small.style.left).toBe("200px");
    expect(small.style.top).toBe("150px");
  });

  it("leaves a click on its controls' strip to the controls", async () => {
    renderPlayer({});
    const player = await started();
    await playing();
    fireEvent.pointerEnter(player);
    const time = within(player).getByText("00:00 / 24:13");

    fireEvent.pointerDown(time, { button: 0, clientX: 40, clientY: 40, pointerId: 1 });
    fireEvent.pointerUp(player, { clientX: 40, clientY: 40, pointerId: 1 });

    expect(HTMLMediaElement.prototype.pause).not.toHaveBeenCalled();
  });

  it("moves where it's dragged, inside the window", async () => {
    renderPlayer({});
    const player = await started();
    await playing();

    act(() => {
      fireEvent.pointerDown(player, { button: 0, clientX: 100, clientY: 100, pointerId: 1 });
      fireEvent.pointerMove(player, { clientX: 300, clientY: 250, pointerId: 1 });
      fireEvent.pointerUp(player, { clientX: 300, clientY: 250, pointerId: 1 });
    });

    expect(player.style.left).toBe("200px");
    expect(player.style.top).toBe("150px");

    act(() => {
      fireEvent.pointerDown(player, { button: 0, clientX: 100, clientY: 100, pointerId: 1 });
      fireEvent.pointerMove(player, { clientX: -500, clientY: 5000, pointerId: 1 });
    });
    expect(player.style.left).toBe("8px");
    expect(player.style.top).toBe(`${window.innerHeight - 8}px`);

    act(() => {
      fireEvent.pointerMove(player, { clientX: 300, clientY: -500, pointerId: 1 });
      fireEvent.pointerUp(player, { clientX: 300, clientY: -500, pointerId: 1 });
    });
    expect(player.style.top).toBe("60px"); // below the title bar, its buttons in reach
  });
});
