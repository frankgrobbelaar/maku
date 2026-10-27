/** "4,5,6" from a page's address (`?files=4,5,6`) as the ids it lists; anything else there is
 * passed over. */
export function idsIn(listed: string | null): number[] {
  return (listed ?? "")
    .split(",")
    .map(Number)
    .filter((id) => Number.isInteger(id) && id > 0);
}
