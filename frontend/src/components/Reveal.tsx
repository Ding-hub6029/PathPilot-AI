'use client';
import { useEffect, useRef, useState, type ReactNode } from 'react';

/**
 * Scroll-reveal wrapper (design upgrade, Worker B). Wraps children in a
 * div with the global `reveal` class and adds `reveal-visible` once when
 * it enters the viewport (IntersectionObserver, threshold ~0.15,
 * rootMargin bottom -8%). Dependency-free.
 *
 * Global-class dependency (defined by the other design-upgrade worker
 * in globals.css, never redefined here): .reveal (opacity 0,
 * translateY 14px) and .reveal-visible. Under prefers-reduced-motion
 * the global CSS makes .reveal visible; this component also sets
 * visible immediately in that case, so it stays correct even if the
 * global reduced-motion rule is absent. If IntersectionObserver is
 * unavailable, content renders visible immediately.
 */
export function Reveal({ children, className = '' }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return;
    }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setVisible(true);
      return;
    }
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          io.disconnect();
        }
      },
      { threshold: 0.15, rootMargin: '0px 0px -8% 0px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div ref={ref} className={`reveal${visible ? ' reveal-visible' : ''}${className ? ` ${className}` : ''}`}>
      {children}
    </div>
  );
}
