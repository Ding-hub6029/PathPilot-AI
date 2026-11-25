'use client';
import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import { takeSuppressNextRouteEnter } from '../lib/viewTransition';

/**
 * Route transition (research move 2) — the compass motif, not a cover.
 *
 * Full variant (home `/` and wizard `/wizard`, where the motion budget
 * is spent): a thin amber route line draws itself across the top of the
 * viewport — left-to-right in LTR, right-to-left in RTL — while the new
 * page rises .5s. Total budget ~.55s, under the 0.8s cap. No preloader,
 * no full-screen cover, no hold: users click constantly in this tool.
 *
 * Quiet variant (evidence pages: rankings, institution/programme
 * detail, results, report, cases — research move 6): a calm .3s fade
 * only. No line, no rise, so facts are never made to wait.
 *
 * The wrapper's inner div is keyed by pathname, so it remounts — and
 * replays — on every route change. A shared-element navigation
 * (ViewTransitionLink) suppresses it via the one-shot flag in
 * lib/viewTransition: the crest / title morph is the transition there.
 *
 * Accessibility (research move 8): keyboard focus moves to <main> on
 * every route change with preventScroll, so scroll restoration on the
 * back button is untouched and screen-reader context follows the page.
 * The line is aria-hidden and pointer-events-none; under
 * prefers-reduced-motion it is display:none (globals.css) and the
 * entrance collapses to an instant swap via the global rule.
 */

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

  useEffect(() => {
    const main = document.querySelector('main');
    if (main) (main as HTMLElement).focus({ preventScroll: true });
  }, [pathname]);

  const quiet = isQuiet(pathname);
  return (
    <>
      {!quiet && !plain && (
        <div aria-hidden="true" className="route-line" key={`line-${pathname}`}>
          <svg viewBox="0 0 1200 18" preserveAspectRatio="none">
            <path
              d="M0 9 C 240 2, 480 16, 720 8 S 1080 12, 1200 9"
              fill="none"
              stroke="#F2A541"
              strokeWidth="2.5"
              strokeLinecap="round"
            />
          </svg>
        </div>
      )}
      <div key={pathname} className={plain ? undefined : quiet ? 'route-enter-quiet' : 'route-enter'}>
        {children}
      </div>
    </>
  );
}
