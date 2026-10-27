import { describe, expect, it } from "vitest";
import type { FranchiseSummary, Job, TitleSummary } from "@/lib/engine";
import { convertible } from "@/test/convert";
import {
  driveOf,
  episodeCode,
  fitting,
  gpuTime,
  jobGroups,
  nights,
  open,
  playTime,
  retryIn,
  sizeName,
  totals,
  tree,
} from "./convert";

function collection(id: number, name: string, titles: [number, string][]): FranchiseSummary {
  return {
    id,
    name,
    titles: titles.map(([titleId, title]) => ({ id: titleId, name: title }) as TitleSummary),
  } as FranchiseSummary;
}

describe("tree", () => {
  it("groups files by collection, title and season, unmatched files last", () => {
    const files = [
      convertible(1),
      convertible(2, { season: 2 }),
      convertible(3, { titleId: 2, title: "Glass Orchard: The Long Winter" }),
      convertible(4, { titleId: 3, title: "Quiet Hours" }),
      convertible(5, { titleId: null, title: null, season: null }),
    ];
    const collections = [
      collection(1, "The Glass Orchard Collection", [
        [1, "Glass Orchard"],
        [2, "Glass Orchard: The Long Winter"],
      ]),
      collection(3, "Quiet Hours", [[3, "Quiet Hours"]]),
    ];

    const groups = tree(files, collections);

    expect(groups.map((group) => [group.name, group.titles.map((t) => t.name)])).toEqual([
      ["The Glass Orchard Collection", ["Glass Orchard", "Glass Orchard: The Long Winter"]],
      ["Quiet Hours", ["Quiet Hours"]],
      ["Not matched yet", ["Not matched yet"]],
    ]);
    expect(groups[0]?.titles[0]?.seasons.map((season) => season.label)).toEqual([
      "Season 1",
      "Season 2",
    ]);
    expect(groups[2]?.titles[0]?.seasons.map((season) => season.label)).toEqual(["The film"]);
  });

  it("lists a collection's series before its films, each in the library's order", () => {
    const files = [
      convertible(1, { titleId: 1, title: "Starfall" }),
      convertible(2, { titleId: 5, title: "Starfall: Last Light", season: null }),
      convertible(3, { titleId: 2, title: "Starfall: Northern Lights" }),
    ];
    const kinds: Record<number, TitleSummary["kind"]> = { 1: "series", 5: "movie", 2: "series" };
    const starfall = collection(1, "The Starfall Collection", [
      [1, "Starfall"],
      [5, "Starfall: Last Light"], // released between the two series
      [2, "Starfall: Northern Lights"],
    ]);
    starfall.titles = starfall.titles.map((title) => ({
      ...title,
      kind: kinds[title.id] ?? "series",
    }));

    const [group] = tree(files, [starfall]);

    expect(group?.titles.map((title) => title.name)).toEqual([
      "Starfall",
      "Starfall: Northern Lights",
      "Starfall: Last Light",
    ]);
  });
});

describe("fitting", () => {
  const files = [
    { output: 400, original: 2000 }, // a big original: its result is smaller
    { output: 400, original: 2000 },
  ];

  it("wants room for every result while originals wait in quarantine", () => {
    expect(fitting(files, 600)).toEqual({ needed: 1000, fit: 1 });
  });

  it("wants room for one result at a time when originals are deleted", () => {
    expect(fitting(files, 600, true)).toEqual({ needed: 500, fit: 2 });
  });

  it("keeps what results add over their originals when those are deleted", () => {
    const small = [
      { output: 400, original: 100 },
      { output: 400, original: 100 },
    ];
    expect(fitting(small, 600, true)).toEqual({ needed: 800, fit: 1 });
  });
});

describe("totals", () => {
  it("adds up a choice", () => {
    const film = convertible(2, {
      width: 3840,
      height: 2160,
      hdr: "HDR10",
      drive: "F:",
      gpuSeconds: 1500,
    });

    const found = totals([convertible(1), film]);

    expect(found).toMatchObject({
      files: 2,
      seconds: 5400,
      gpuSeconds: 1860,
      sizeBefore: 4_000_000_000,
      sizeAfter: 2_400_000_000,
      byDrive: { "D:": 1_200_000_000, "F:": 1_200_000_000 },
      sources: "1080p · 16:9, 4K HDR · 16:9",
    });
  });

  it("leaves out files that won't play or wait in the queue already", () => {
    const files = [
      convertible(1),
      convertible(2, { broken: true }),
      convertible(3, { waiting: true }),
    ];

    expect(open(files).map((file) => file.fileId)).toEqual([1]);
  });
});

describe("words", () => {
  it("says GPU time the way the boards do", () => {
    expect(gpuTime(180)).toBe("3 min");
    expect(gpuTime(720)).toBe("12 min");
    expect(gpuTime(3500)).toBe("58 min");
    expect(gpuTime(3600)).toBe("1 h");
    expect(gpuTime(35 * 3600)).toBe("35 h");
    expect(gpuTime(12 * 24 * 3600)).toBe("12 days");
  });

  it("counts nights of eight hours", () => {
    expect(nights(35 * 3600)).toBe("about 5 nights");
    expect(nights(9 * 3600)).toBe("about 2 nights");
    expect(nights(3600)).toBe("less than a night");
  });

  it("says how long video plays", () => {
    expect(playTime(35 * 1440)).toBe("14 h 0 min");
    expect(playTime(1440)).toBe("24 min");
  });

  it("names a picture's size as the engine does", () => {
    expect(
      [
        [720, 480],
        [1280, 720],
        [1920, 800],
        [2048, 1080],
        [3840, 1600],
        [4096, 2160],
        [7680, 4320],
      ].map(([width = 0, height = 0]) => sizeName(width, height)),
    ).toEqual(["SD", "720p", "1080p", "1080p", "4K", "4K", "8K"]);
  });
});

describe("the queue's groups", () => {
  const job = (id: number, more: Partial<Job> = {}): Job =>
    ({
      id,
      title: "Glass Orchard",
      titleId: 1,
      season: 1,
      episode: id,
      path: `D:\\Videos\\Glass Orchard (2012) - S01E0${id}.mkv`,
      ...more,
    }) as Job;

  it("runs a title's season together, in the queue's order", () => {
    const groups = jobGroups([job(1), job(2), job(3, { season: 2 }), job(4)]);

    expect(groups.map((group) => [group.label, group.jobs.length])).toEqual([
      ["Glass Orchard · Season 1", 2],
      ["Glass Orchard · Season 2", 1],
      ["Glass Orchard · Season 1", 1],
    ]);
  });

  it("codes an episode, or names a film's file", () => {
    expect(episodeCode(job(6))).toBe("S01E06");
    expect(episodeCode(job(7, { season: null, episode: null, path: "D:\\Quiet Hours.mkv" }))).toBe(
      "Quiet Hours.mkv",
    );
  });
});

describe("driveOf", () => {
  it("names a path's drive as Maku writes it, a letter or a share", () => {
    expect(driveOf("d:\\Videos\\Ep 01.mkv")).toBe("D:");
    expect(driveOf("\\\\nas\\videos\\TV\\Ep 01.mkv")).toBe("\\\\nas\\videos");
    expect(driveOf("Ep 01.mkv")).toBe("");
  });
});

describe("retryIn", () => {
  it("says when Maku tries again, in whole minutes", () => {
    const now = Date.parse("2026-10-11T10:00:00+02:00");
    expect(retryIn("2026-10-11T10:05:00+02:00", now)).toBe("in 5 minutes");
    expect(retryIn("2026-10-11T08:01:30+00:00", now)).toBe("in 2 minutes");
    expect(retryIn("2026-10-11T10:00:30+02:00", now)).toBe("in a minute");
    expect(retryIn("2026-10-11T09:59:00+02:00", now)).toBe("in a moment");
  });
});
