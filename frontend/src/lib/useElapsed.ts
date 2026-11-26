import { useEffect, useState } from 'react';

/**
 * Whole seconds elapsed while `active` is true (waking-backend
 * progress, round 8). Resets to 0 when inactive. A 1s interval is
 * enough: the point is visible progress ("waking… 12s"), not a
 * stopwatch.
 */
export function useElapsed(active: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) {
      setSeconds(0);
      return;
    }
    const started = Date.now();
    setSeconds(0);
    const id = setInterval(() => {
      setSeconds(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [active]);
  return seconds;
}
