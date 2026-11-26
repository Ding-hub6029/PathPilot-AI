import { useEffect, useState } from 'react';
import { fetchPrograms } from './api';
import { PROGRAMS } from './programs';
import { Program } from './types';

/**
 * Data-driven programme list (Day 2): loads GET /api/v1/programs (via the
 * /api/* Next.js rewrite) with limit/cursor support and falls back to the
 * local PROGRAMS list when the backend is unreachable. While loading, the
 * local list is shown so the page never renders empty.
 *
 * P0 (re-test task 6):
 * - `enabled` (default true): the wizard defers its live refresh until
 *   the preferences step, so no 90s patient fetch runs during the
 *   steps where the Next button was observed hanging. The local mirror
 *   is complete (all 881 expansion programmes), so the wizard's
 *   candidates do not depend on the live call at all.
 * - The fetch is ABORTED on unmount: the old effect only set a
 *   `cancelled` flag, so a patient fetch kept retrying for up to 90s
 *   against a sleeping backend after the user had already navigated
 *   away — long-lived /api traffic surviving every navigation. The
 *   AbortSignal is threaded through fetchPrograms/fetchJsonPatient.
 * - A settle timing is logged (console.debug, [p0-programs]) so a
 *   browser re-test can see when the live list landed and whether it
 *   was still in flight at a click.
 */
export function usePrograms(opts?: { limit?: number; enabled?: boolean }): { programs: Program[]; live: boolean; loading: boolean; nextCursor?: string } {
  const [programs, setPrograms] = useState<Program[]>(PROGRAMS);
  const [live, setLive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [nextCursor, setNextCursor] = useState<string | undefined>(undefined);
  const limit = opts?.limit;
  const enabled = opts?.enabled ?? true;

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    let settledLive = false;
    const controller = new AbortController();
    const started = Date.now();
    fetchPrograms({ ...(limit ? { limit } : {}), signal: controller.signal })
      .then((res) => {
        settledLive = res.live;
        if (cancelled) return;
        setPrograms(res.programs);
        setLive(res.live);
        setNextCursor(res.nextCursor);
      })
      .catch(() => {
        // fetchPrograms falls back to the local list on failure; the
        // only way this rejects is the unmount abort, which is silent
        // — it is not an offline verdict.
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
        if (typeof console !== 'undefined' && typeof console.debug === 'function') {
          console.debug(`[p0-programs] fetch settled in ${Date.now() - started}ms live=${settledLive} aborted=${controller.signal.aborted}`);
        }
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limit, enabled]);

  return { programs, live, loading, nextCursor };
}
