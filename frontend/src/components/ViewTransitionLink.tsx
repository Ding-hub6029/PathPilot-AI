'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { MouseEvent, ReactNode } from 'react';
import { suppressNextRouteEnter } from '../lib/viewTransition';

/**
 * A Link that, for a plain left-click, navigates inside
 * document.startViewTransition() so elements carrying a matching
 * `view-transition-name` (crest, programme title — see vtRef in
 * lib/viewTransition) morph across the route change (research move 4).
 * The callback waits two animation frames so React has committed the
 * new page before the browser captures its snapshot.
 *
 * Modifier/middle clicks, reduced motion, and browsers without the API
 * fall back to a plain Link navigation — the transition is never
 * required for the navigation to work. The route entrance is also
 * suppressed for these navigations (one-shot flag), because the
 * morph IS the transition there.
 *
 * Known limit: the App Router's router.push returns no promise, so the
 * double-rAF wait is best-effort; on a slow render the snapshot may
 * still catch the old page and the morph silently does not happen —
 * navigation still works. Verify visually in a real browser.
 */
export function ViewTransitionLink({
  href,
  className,
  children,
}: {
  href: string;
  className?: string;
  children: ReactNode;
}) {
  const router = useRouter();

  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    // P0 (re-test task 6): click timing for the browser re-test —
    // pair with the [p0-nav] route-committed log in RouteTransition.
    if (typeof console !== 'undefined' && typeof console.debug === 'function') {
      console.debug(`[p0-nav] vt-link click ${href}`);
    }
    const doc = document as Document & {
      startViewTransition?: (cb: () => Promise<void> | void) => void;
    };
    if (
      typeof doc.startViewTransition !== 'function' ||
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ) {
      return; // plain Link navigation
    }
    e.preventDefault();
    suppressNextRouteEnter();
    // P0: a throw inside startViewTransition must never swallow the
    // navigation — fall back to a plain router.push.
    try {
      doc.startViewTransition(async () => {
        router.push(href);
        await new Promise<void>((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
        });
      });
    } catch {
      router.push(href);
    }
  };

  return (
    <Link href={href} className={className} onClick={onClick}>
      {children}
    </Link>
  );
}
