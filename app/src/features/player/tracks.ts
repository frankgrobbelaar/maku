import type { OpenedVideo, PlayerState, SoundTrack, SubtitleTrack } from "@/lib/engine";
import { languages } from "@/lib/format";

/** "03:12", or "1:02:05" past an hour: the player's clock. */
export function playTime(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = String(Math.floor((whole % 3600) / 60)).padStart(2, "0");
  const rest = String(whole % 60).padStart(2, "0");
  return hours ? `${hours}:${minutes}:${rest}` : `${minutes}:${rest}`;
}

/** A sound track as the menu names it: ["Japanese", "stereo"], ["English", "5.1, played as
 * stereo"]. Every sound plays as stereo. */
export function soundWords(track: SoundTrack): [string, string | null] {
  const name = track.language
    ? languages([track.language])
    : (track.title ?? `Sound ${track.number + 1}`);
  const layout =
    track.channels === 1
      ? "mono"
      : track.channels === 2
        ? "stereo"
        : track.channels === 6
          ? "5.1, played as stereo"
          : track.channels === 8
            ? "7.1, played as stereo"
            : track.channels > 2
              ? `${track.channels} channels, played as stereo`
              : null;
  const named = track.language && track.title ? track.title : null;
  return [name, [named, layout].filter(Boolean).join(" · ") || null];
}

/** Subtitles as the menu names them: ["English", "as the file styles them"], or how getting
 * them ready goes. */
export function subtitleWords(
  track: SubtitleTrack,
  state: PlayerState | undefined,
): [string, string | null] {
  const name = track.language
    ? languages([track.language])
    : (track.title ?? `Subtitles ${track.number + 1}`);
  if (state?.preparing.includes(track.number)) return [name, "getting ready…"];
  if (state?.failed.some((each) => each.number === track.number)) return [name, "won't show"];
  const detail =
    (track.made ? "made by Maku" : null) ||
    (track.language && track.title) ||
    (track.kind === "styled" ? "as the file styles them" : null) ||
    (track.beside ? "beside the video" : null);
  return [name, detail];
}

/** What the owner picked last time, kept on this PC: the next video starts the same way. */
export interface Liked {
  /** A sound track's language. */
  sound?: string | null;
  /** A subtitle track's language, or "off". */
  subtitles?: string | null;
  volume?: number;
  muted?: boolean;
}

const LIKED = "maku.player";

export function liked(): Liked {
  try {
    const kept: unknown = JSON.parse(localStorage.getItem(LIKED) ?? "{}");
    return kept && typeof kept === "object" ? (kept as Liked) : {};
  } catch {
    return {}; // nothing kept, or storage this window can't use
  }
}

export function like(change: Liked) {
  try {
    localStorage.setItem(LIKED, JSON.stringify({ ...liked(), ...change }));
  } catch {
    // not kept: the next video starts as the file says
  }
}

/** The sound to start with: in the language picked last time, or else the file's own pick. */
export function pickSound(video: OpenedVideo, kept: Liked): number | null {
  const same = video.sound.find((track) => kept.sound && track.language === kept.sound);
  return same?.number ?? video.chosenSound;
}

/** The subtitles to start with: none when the owner turned them off last time, in the language
 * picked last time (all of them rather than signs only), or else the file's own pick. */
export function pickSubtitles(video: OpenedVideo, kept: Liked): number | null {
  if (kept.subtitles === "off") return null;
  const same = video.subtitles.filter(
    (track) => kept.subtitles && track.language === kept.subtitles,
  );
  const full = same.find((track) => !track.forced) ?? same[0];
  return full?.number ?? video.chosenSubtitles;
}
