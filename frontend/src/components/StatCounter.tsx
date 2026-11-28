'use client';
import { useEffect, useRef, useState } from 'react';

/**
 * Animated counter (restyle 2026-11-28): counts up from 0 to `value`
 * once when it scrolls into view (IntersectionObserver, ease-out
 * cubic, ~1.2 s). The number is data-driven — callers pass a live
 * count, never a hard-coded figure. Under prefers-reduced-motion (or
 * without IntersectionObserver) the final value renders at once.
 * Tabular figures via the global .stat-num class, so the count-up
 * does not jitter horizontally.
 */
export function StatCounter({ value, duration = 1200 }: { value: number; duration?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [shown, setShown] = useState(0);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setShown(value);
      return;
    }
    if (typeof IntersectionObserver === 'undefined') {
      setShown(value);
      return;
    }
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        io.disconnect();
        const t0 = performance.now();
        const tick = (t: number) => {
          const p = Math.min(1, (t - t0) / duration);
          setShown(Math.round(value * (1 - Math.pow(1 - p, 3))));
          if (p < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      },
      { threshold: 0.4 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [value, duration]);

  return (
    <span ref={ref} className="stat-num">
      {shown.toLocaleString()}
    </span>
  );
}
