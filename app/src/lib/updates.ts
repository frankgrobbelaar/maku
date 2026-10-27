import { type UseQueryResult, useMutation, useQuery } from "@tanstack/react-query";
import { invoke } from "@tauri-apps/api/core";
import { dayAndTime } from "@/lib/format";

/** An update the shell has downloaded and checked. Mirrors src-tauri/src/updater.rs. */
export interface ReadyUpdate {
  version: string;
  /** The version's notes from CHANGELOG.md (Markdown), when the release has them. */
  notes: string | null;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Checks for an update as Maku starts and once a day, or when asked (`refetch()`, Settings'
 * "Check for a new version"), and downloads it in the background.
 * Resolves to the update once it is ready to install, or null when Maku is up to date.
 * Installed builds only: a development build has nothing to update.
 */
export function useReadyUpdate() {
  return useQuery({
    queryKey: ["update"],
    queryFn: () => invoke<ReadyUpdate | null>("prepare_update"),
    enabled: import.meta.env.PROD,
    refetchInterval: DAY_MS,
    refetchOnWindowFocus: false,
    staleTime: DAY_MS,
    retry: false,
  });
}

/** Closes Maku, installs the update and opens Maku again. */
export function useInstallUpdate() {
  return useMutation({ mutationFn: () => invoke<void>("install_update") });
}

/**
 * Where the update check stands, as Settings says it: "Up to date · last checked today 07:12",
 * "Maku 0.3.0 is ready to install", "Checking…", or why Maku can't check.
 */
export function updateStatus(update: UseQueryResult<ReadyUpdate | null>): string {
  if (!import.meta.env.PROD) return "Checked in installed copies of Maku";
  if (update.isFetching) return "Checking…";
  if (update.isPaused) return "You're offline: Maku checks once you're back";
  if (update.isError) return `Can't check right now: ${String(update.error)}`;
  if (update.data) return `Maku ${update.data.version} is ready to install`;
  if (update.isSuccess) {
    return `Up to date · last checked ${dayAndTime(new Date(update.dataUpdatedAt))}`;
  }
  return "Checking…";
}

/**
 * What a version's notes list, as plain sentences: each "- " entry, with its wrapped lines
 * joined and its Markdown (links, bold, code) reduced to text.
 */
export function whatsNew(notes: string | null): string[] {
  const entries: string[] = [];
  let current: string | null = null;
  for (const raw of (notes ?? "").replaceAll("\r\n", "\n").split("\n")) {
    const line = raw.trim();
    if (line.startsWith("- ")) {
      if (current) entries.push(current);
      current = line.slice(2);
    } else if (current && line && /^\s/.test(raw)) {
      current += ` ${line}`;
    } else if (current) {
      entries.push(current);
      current = null;
    }
  }
  if (current) entries.push(current);
  return entries.map((entry) =>
    entry
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/`([^`]+)`/g, "$1"),
  );
}
