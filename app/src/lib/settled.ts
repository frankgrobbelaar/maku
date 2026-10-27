import { useEffect, useState } from "react";

/** `value` once it has stayed the same for `delay` milliseconds: what's typed, once the owner
 * stops typing. */
export function useSettled(value: string, delay: number): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}
