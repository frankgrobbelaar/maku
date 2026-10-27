import type { ReactNode } from "react";
import {
  airedWords,
  ElsewhereLinks,
  Facts,
  Genres,
  lengthWords,
  Synopsis,
  statusWords,
} from "@/components/about";
import { Panel } from "@/components/panel";
import type { TitleDetail } from "@/lib/engine";

/** What a title is about: its synopsis, genres, studio, when it aired and how long it lasts, as
 * TMDB says, and its page there. Still airing goes without saying here: the title's header says
 * so. */
export function AboutPanel({ title }: { title: TitleDetail }) {
  const { about } = title;
  const facts: [string, ReactNode][] = [
    ["Studio", about.studio],
    [
      title.kind === "movie" ? "Released" : "Aired",
      airedWords(about.started, about.ended, title.kind, title.airing),
    ],
    ["Status", about.status === "airing" ? null : statusWords(about.status, title.kind)],
    ["Length", lengthWords(about.minutes, title.kind)],
  ];
  return (
    <Panel id="about-title" title="About">
      <div className="flex max-w-[72ch] flex-col gap-4">
        {about.overview ? (
          <Synopsis text={about.overview} />
        ) : (
          <p className="text-13 text-fg-muted">
            No synopsis yet. Maku looks each title up on TMDB now and then, and fills this in.
          </p>
        )}
        <Genres genres={about.genres} />
        <Facts facts={facts} />
        <ElsewhereLinks tmdbType={about.tmdbType} tmdbId={about.tmdbId} />
      </div>
    </Panel>
  );
}
