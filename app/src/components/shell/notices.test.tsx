import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { EngineProvider, useHistory } from "@/lib/engine";
import { fakeEngine, READY } from "@/test/engine";
import { Notices } from "./notices";

type Handler = (event: { payload: unknown }) => void;
const shell = vi.hoisted(() => ({ handlers: new Map<string, Handler>(), invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({
  listen: async (name: string, handler: Handler) => {
    shell.handlers.set(name, handler);
    return () => shell.handlers.delete(name);
  },
}));

function asked(fetch: ReturnType<typeof fakeEngine>, path: string): number {
  return fetch.mock.calls.filter(([input]) => new URL(String(input)).pathname === path).length;
}

describe("Notices", () => {
  it("shows what the engine tells while the window is open, leading where it says", async () => {
    shell.invoke.mockResolvedValue(READY);
    const fetch = fakeEngine({ "/history": [] });
    function Listed() {
      useHistory(); // a screen showing what the engine did
      return <Notices />;
    }
    render(
      <QueryClientProvider client={new QueryClient()}>
        <EngineProvider>
          <MemoryRouter>
            <Routes>
              <Route index element={<Listed />} />
              <Route path="/titles/:id" element={<p>A title</p>} />
            </Routes>
          </MemoryRouter>
        </EngineProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(shell.handlers.has("notice")).toBe(true));
    await waitFor(() => expect(asked(fetch, "/history")).toBe(1));

    act(() =>
      shell.handlers.get("notice")?.({
        payload: {
          title: "The Harbour Line, season 1 is done",
          body: "26 episodes · all checked · 6.1 GB → 11.7 GB",
          link: "/titles/12",
        },
      }),
    );

    const note = await screen.findByRole("status");
    await waitFor(() => expect(asked(fetch, "/history")).toBe(2)); // what changed, asked again
    expect(note).toHaveTextContent("The Harbour Line, season 1 is done");
    expect(note).toHaveTextContent("26 episodes · all checked · 6.1 GB → 11.7 GB");
    screen.getByRole("button", { name: "View" }).click();
    expect(await screen.findByText("A title")).toBeInTheDocument();
  });

  it("stays while it's pointed at or focused, and goes when dismissed", async () => {
    shell.invoke.mockResolvedValue(READY);
    fakeEngine({});
    render(
      <QueryClientProvider client={new QueryClient()}>
        <EngineProvider>
          <MemoryRouter>
            <Notices />
          </MemoryRouter>
        </EngineProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(shell.handlers.has("notice")).toBe(true));
    vi.useFakeTimers();
    try {
      act(() =>
        shell.handlers.get("notice")?.({
          payload: { title: "The queue paused", body: "There isn't room on D:", link: null },
        }),
      );
      const note = screen.getByRole("status");

      fireEvent.mouseEnter(note);
      act(() => vi.advanceTimersByTime(60_000));
      expect(screen.getByRole("status")).toBeInTheDocument(); // read at leisure

      fireEvent.mouseLeave(note);
      act(() => vi.advanceTimersByTime(60_000));
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }

    act(() =>
      shell.handlers.get("notice")?.({
        payload: { title: "Glass Orchard is done", body: "1 episode", link: null },
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
