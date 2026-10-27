import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReadyUpdate } from "@/lib/updates";
import { UpdateCard } from "./update-card";

const shell = vi.hoisted(() => ({ invoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: shell.invoke }));

function renderCard(update: ReadyUpdate | null) {
  shell.invoke.mockImplementation(async (command: string) =>
    command === "prepare_update" ? update : undefined,
  );
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queries}>
      <UpdateCard />
    </QueryClientProvider>,
  );
}

describe("UpdateCard", () => {
  beforeEach(() => {
    vi.stubEnv("PROD", true); // only installed copies check for updates
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    shell.invoke.mockReset();
  });

  it("says nothing while Maku is up to date", async () => {
    renderCard(null);

    await vi.waitFor(() => expect(shell.invoke).toHaveBeenCalledWith("prepare_update"));
    expect(screen.queryByRole("heading", { name: /is ready/ })).not.toBeInTheDocument();
  });

  it("lists what's new in the update, a few entries at most", async () => {
    const notes = [
      "### Added",
      "- Scanning: add your video folders and Maku reads every",
      "  video in them.",
      "- A downloads page with every version.",
      "- Maku shows what changed before it updates.",
      "",
      "### Fixed",
      "- The engine restarts after a crash.",
      "- Long file names wrap in the queue.",
      "- Export keeps Japanese titles intact.",
    ].join("\n");

    renderCard({ version: "0.2.0", notes });

    expect(await screen.findByRole("heading", { name: "Maku 0.2.0 is ready" })).toBeInTheDocument();
    const items = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(items).toEqual([
      "Scanning: add your video folders and Maku reads every video in them.",
      "A downloads page with every version.",
      "Maku shows what changed before it updates.",
      "The engine restarts after a crash.",
    ]);
    expect(screen.getByText("And 2 more changes.")).toBeInTheDocument();
  });

  it("still offers the update when the release has no notes", async () => {
    renderCard({ version: "0.2.1", notes: null });

    expect(await screen.findByRole("heading", { name: "Maku 0.2.1 is ready" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "What's new" })).not.toBeInTheDocument();
  });

  it("opens the downloads page for every version", async () => {
    renderCard({ version: "0.2.0", notes: "- Scanning." });

    (await screen.findByRole("button", { name: "Every version" })).click();

    expect(shell.invoke).toHaveBeenCalledWith("open_downloads_page");
  });
});
