import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/shell/app-shell";
import { EngineProvider } from "@/lib/engine";
import { fakeEngine, READY } from "@/test/engine";

const shell = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => {} }));
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({
    minimize: vi.fn(),
    toggleMaximize: vi.fn(),
    close: vi.fn(),
    isMaximized: async () => false,
    onResized: async () => () => {},
  }),
}));

function renderShell() {
  shell.invoke.mockImplementation(async (command: string) =>
    command === "engine_status" ? READY : undefined,
  );
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <EngineProvider>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<p>The home page</p>} />
            </Route>
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

const DAMAGED = {
  problem: "file is not a database",
  badRead: false,
  backup: "maku 2026-09-20 0300.db",
  made: "2026-09-20T03:00:00",
};

describe("DamagedRecords", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    shell.invoke.mockReset();
  });

  it("stands in for every page, and restores the newest backup that opens", async () => {
    const fetch = fakeEngine({ "/records": DAMAGED, "POST /records/restore": null });
    renderShell();

    expect(
      await screen.findByRole("heading", { name: "Maku's records are damaged" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("The home page")).not.toBeInTheDocument();
    expect(screen.getByText(/SQLite says: file is not a database\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument(); // no use

    fireEvent.click(
      screen.getByRole("button", { name: "Restore the backup from 20 September 03:00" }),
    );

    await waitFor(() => expect(shell.invoke).toHaveBeenCalledWith("restart_engine"));
    expect(sent(fetch, "POST", "/records/restore")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Maku is starting again with the backup from 20 September 03:00.",
    );
  });

  it("offers to try again first when the disk couldn't read them", async () => {
    const fetch = fakeEngine({
      "/records": { ...DAMAGED, problem: "disk I/O error", badRead: true },
    });
    renderShell();

    expect(
      await screen.findByRole("button", { name: "Restore the backup from 20 September 03:00" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() => expect(shell.invoke).toHaveBeenCalledWith("restart_engine"));
    expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
  });

  it("offers new records when no backup opens", async () => {
    const fetch = fakeEngine({
      "/records": { ...DAMAGED, backup: null, made: null },
      "POST /records/new": null,
    });
    renderShell();

    fireEvent.click(await screen.findByRole("button", { name: "Start with new records" }));

    await waitFor(() => expect(shell.invoke).toHaveBeenCalledWith("restart_engine"));
    expect(sent(fetch, "POST", "/records/new")).toHaveLength(1);
  });

  it("says why the way back didn't work, and stays", async () => {
    fakeEngine({
      "/records": DAMAGED,
      "POST /records/restore": Response.json(
        { detail: "Maku couldn't restore that backup: disk I/O error" },
        { status: 422 },
      ),
    });
    renderShell();

    fireEvent.click(await screen.findByRole("button", { name: /Restore the backup/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Maku couldn't restore that backup: disk I/O error",
    );
    expect(shell.invoke).not.toHaveBeenCalledWith("restart_engine");
  });

  it("leaves the pages be while the records are fine", async () => {
    fakeEngine({ "/records": () => Response.json(null) });
    renderShell();

    expect(await screen.findByText("The home page")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /damaged/ })).not.toBeInTheDocument();
  });
});
