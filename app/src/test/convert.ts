import type { Convertible } from "@/lib/engine";

/** A video the Convert screen lists: by default a 45-minute 1080p H.264 episode of Glass Orchard,
 * to be made HEVC 10-bit at its own size. */
export function convertible(fileId: number, more: Partial<Convertible> = {}): Convertible {
  return {
    fileId,
    label: `Glass Orchard · S01E${String(fileId).padStart(2, "0")}`,
    titleId: 1,
    title: "Glass Orchard",
    season: 1,
    episode: fileId,
    seconds: 2700,
    width: 1920,
    height: 1080,
    aspect: "16:9",
    hdr: null,
    size: 2_000_000_000,
    drive: "D:",
    method: "reencode",
    reasons: ["H.264 becomes HEVC 10-bit"],
    outputWidth: 1920,
    outputHeight: 1080,
    gpuSeconds: 360,
    outputBytes: 1_200_000_000,
    waiting: false,
    broken: false,
    ...more,
  };
}
