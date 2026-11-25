/**
 * Shared-element (view) transitions, research move 4.
 *
 * Two pieces:
 * 1. `vtRef(name)` — assigns a `view-transition-name` to an element
 *    without going through React's style prop (React 18 warns on the
 *    unlisted property; a direct DOM assignment works in every browser
 *    that supports the API and is a no-op elsewhere).
 * 2. A one-shot flag so a shared-element navigation can tell
 *    RouteTransition to skip its own entrance: the view-transition
 *    snapshot of the new page is taken while the route entrance is at
 *    opacity 0, which would hide the morph. ViewTransitionLink sets
 *    the flag just before pushing; RouteTransition consumes it on the
 *    next render and clears it, so ordinary navigations still animate.
 *    (In dev StrictMode the flag may be consumed by a discarded render
 *    and the entrance may play once — production renders once.)
 */

let suppressNext = false;

export function suppressNextRouteEnter(): void {
  suppressNext = true;
}

export function takeSuppressNextRouteEnter(): boolean {
  const value = suppressNext;
  suppressNext = false;
  return value;
}

export function vtRef(name: string) {
  return (el: HTMLElement | null) => {
    if (el) {
      (el.style as CSSStyleDeclaration & { viewTransitionName?: string }).viewTransitionName = name;
    }
  };
}
