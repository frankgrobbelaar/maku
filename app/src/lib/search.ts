/** Text as a search compares it: lower case, without accents ("Rivière" is "riviere"), full-width
 * letters as plain ones, and punctuation as spaces ("Starfall: Ascent" is "starfall ascent"). */
export function folded(text: string): string {
  return text
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

/** The words of what was typed, as a search compares them; none for an empty search. */
export function words(query: string): string[] {
  return folded(query).split(" ").filter(Boolean);
}

/** Whether something is what was typed: every word of it is in one of `texts` (its name, the
 * name of its file, its episode's code…), however it's written. An empty search finds all. */
export function matches(query: string, ...texts: (string | null | undefined)[]): boolean {
  const wanted = words(query);
  if (wanted.length === 0) return true;
  const there = texts
    .filter((text): text is string => Boolean(text))
    .map(folded)
    .join(" ");
  return wanted.every((word) => there.includes(word));
}
