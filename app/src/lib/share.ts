/**
 * How much of a show is there, in whole percent, as the gap analysis says it
 * (engine/src/maku/core/report.py): never 100 while an episode is missing, never 0 once one is
 * there.
 */
export function share(present: number, total: number): number {
  if (total <= 0) return 0;
  let percent = Math.round((present / total) * 100);
  if (present < total) percent = Math.min(percent, 99);
  if (present > 0) percent = Math.max(percent, 1);
  return percent;
}
