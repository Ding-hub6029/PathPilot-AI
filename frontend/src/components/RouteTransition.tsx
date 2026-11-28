'use client';
import { useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { takeSuppressNextRouteEnter } from '../lib/viewTransition';
import styles from './RouteTransition.module.css';

/**
 * Route transition (research move 2) — the compass motif, not a cover.
 *
 * Full variant (home `/` and wizard `/wizard`, where the motion budget
 * is spent): a small compass rose sweeps across the top of the viewport
 * — inline-start to inline-end, so right-to-left in RTL — while an
 * amber route line draws itself behind it, then the overlay fades out
 * and unmounts. Total budget 0.8s, under the cap. No preloader, no
 * full-screen cover, no hold: users click constantly in this tool.
 * The new page rises .5s (.route-enter, globals.css) underneath.
 *
 * Quiet variant (evidence pages: rankings, institution/programme
 * detail, results, report, cases — research move 6): a calm .3s fade
 * only. No line, no needle, no rise, so facts are never made to wait.
 *
 * The wrapper's inner div is keyed by pathname, so it remounts — and
 * replays — on every route change. A shared-element navigation
 * (ViewTransitionLink) suppresses it via the one-shot flag in
 * lib/viewTransition: the crest / title morph is the transition there.
 *
 * Safety: the overlay is pointer-events-none and aria-hidden and is
 * unmounted 0.8s after each route change, so it can never block a
 * click, trap focus, or linger. Navigation and the back button are
 * untouched — nothing here scrolls or focuses except the existing
 * focus-to-<main> effect below and the guarded clipped-arrival
 * reset (Round 34 D3), which fires only when the first heading is
 * actually under the sticky header on arrival. Under
 * prefers-reduced-motion the sweep is display:none (module CSS) and
 * the entrance collapses to an instant swap via the global rule.
 */

/**
 * Round 34 D3 — clipped-arrival guard (pure, so it is unit-testable
 * without a DOM): true exactly when the first heading's top edge is
 * under the sticky header, i.e. the heading is painted over by the
 * header and the user sees it clipped. `headerBottom` is the live
 * bottom edge of the sticky header in viewport coordinates, so a
 * wrapped (taller) mobile header is covered with no hard-coded
 * pixel height. Boundary cases: h1Top == headerBottom is fully
 * visible (false); h1Top < 0 is a restored deep scroll — e.g. a
 * back/forward arrival — and must never be reset (false); a
 * scrollY = 0 arrival puts the H1 a full py-8 below the header
 * bottom (false).
 */
export function isClippedArrival(h1Top: number, headerBottom: number): boolean {
  return h1Top >= 0 && h1Top < headerBottom;
}

const QUIET_PREFIXES = ['/rankings', '/institutions', '/programs', '/report', '/results', '/cases'];

function isQuiet(pathname: string): boolean {
  return QUIET_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function RouteTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  /**
   * One-shot flag, consumed once per pathname (React's adjust-state-
   * during-render pattern): the component itself stays mounted across
   * navigations (it lives in the root layout), so the flag cannot be
   * read in a mount-only initializer. The cached value is reused by
   * re-renders for the same pathname.
   */
  const plainRef = useRef<{ path: string; plain: boolean }>({ path: pathname, plain: false });
  if (plainRef.current.path !== pathname) {
    plainRef.current = { path: pathname, plain: takeSuppressNextRouteEnter() };
  }
  const plain = plainRef.current.plain;

  /** The sweep overlay unmounts 0.8s after each route change — the
      same budget as its fade-out animation — so it can never linger
      past the transition. Re-armed on every pathname change. */
  const [sweepDone, setSweepDone] = useState(false);
  useEffect(() => {
    setSweepDone(false);
    // P0 (re-test task 6): log every committed route change with a
    // timestamp, so a browser re-test can measure click-to-commit for
    // a navigation (pair with the [p0-nav] click logs on the link /
    // button that started it). The overlay is pointer-events-none and
    // the commit itself renders from the local mirror — a slow
    // navigation shows up here as a late log line, not a missing one.
    if (typeof console !== 'undefined' && typeof console.debug === 'function') {
      console.debug(`[p0-nav] route committed ${pathname}`);
    }
    const timer = setTimeout(() => setSweepDone(true), 800);
    return () => clearTimeout(timer);
  }, [pathname]);

  useEffect(() => {
    const main = document.querySelector('main');
    if (main) (main as HTMLElement).focus({ preventScroll: true });
  }, [pathname]);

  /**
   * Round 34 D3 — guarded clipped-arrival scroll reset. Mechanism
   * (DECISIONS #327): on a client-side <Link> navigation Next
   * 14.2.35's InnerScrollAndFocusHandler early-exits without
   * resetting scroll when the new page's top is already in the
   * viewport, and pushState does not reset scroll either, so a
   * carried-over scrollY in (32px, headerHeight] leaves the H1 —
   * py-8 below the page top — under the sticky header (z-50).
   * The reset runs in requestAnimationFrame, i.e. after paint and
   * after Next's scroll handler has settled, and ONLY when
   * isClippedArrival says the first heading is actually under the
   * header right now: a restored deep scroll (back/forward) puts
   * the H1 above the viewport, and a scrollY = 0 arrival puts it
   * below the header, so neither is ever disturbed. Both edges
   * are measured live (header.getBoundingClientRect().bottom,
   * h1.getBoundingClientRect().top) — no hard-coded heights, so
   * the wrapped mobile header is covered. Pages without an h1
   * are left alone. This is the app's only scroll-to-top call.
   */
  useEffect(() => {
    if (typeof window === 'undefined') return;
    let raf = 0;
    raf = window.requestAnimationFrame(() => {
      const header = document.querySelector('header');
      const h1 = document.querySelector('main h1');
      if (!header || !h1) return;
      if (isClippedArrival(h1.getBoundingClientRect().top, header.getBoundingClientRect().bottom)) {
        window.scrollTo(0, 0);
      }
    });
    return () => window.cancelAnimationFrame(raf);
  }, [pathname]);

  const quiet = isQuiet(pathname);
  return (
    <>
      {!quiet && !plain && !sweepDone && (
        <div aria-hidden="true" className={styles.sweep} key={`sweep-${pathname}`}>
          <svg className={styles.sweepLine} viewBox="0 0 1200 18" preserveAspectRatio="none">
            <path
              d="M0 9 C 240 2, 480 16, 720 8 S 1080 12, 1200 9"
              fill="none"
              stroke="#F2A541"
              strokeWidth="2.5"
              strokeLinecap="round"
            />
          </svg>
          <span className={styles.needle} aria-hidden="true">
            <svg viewBox="0 0 24 24">
              <polygon points="12,1 20,12 12,23 4,12" fill="#F2A541" />
              <polygon points="12,7 16,12 12,17 8,12" fill="#0E7C7B" />
              <circle cx="12" cy="12" r="1.6" fill="#0B1F3A" />
            </svg>
          </span>
        </div>
      )}
      <div key={pathname} className={plain ? undefined : quiet ? 'route-enter-quiet' : 'route-enter'}>
        {children}
      </div>
    </>
  );
}
