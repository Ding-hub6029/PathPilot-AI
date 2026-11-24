import { useEffect, useState } from 'react';
import { fetchPrograms } from './api';
import { PROGRAMS } from './programs';
import { Program } from './types';

/**
 * Data-driven programme list (Day 2): loads GET /api/v1/programs (via the
 * /api/* Next.js rewrite) with limit/cursor support and falls back to the
 * local PROGRAMS list when the backend is unreachable. While loading, the
 * local list is shown so the page never renders empty.
 */
export function usePrograms(opts?: { limit?: number }): { programs: Program[]; live: boolean; loading: boolean; nextCursor?: string } {
  const [programs, setPrograms] = useState<Program[]>(PROGRAMS);
  const [live, setLive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [nextCursor, setNextCursor] = useState<string | undefined>(undefined);
  const limit = opts?.limit;

  useEffect(() => {
    let cancelled = false;
    fetchPrograms(limit ? { limit } : {})
      .then((res) => {
        if (cancelled) return;
        setPrograms(res.programs);
        setLive(res.live);
        setNextCursor(res.nextCursor);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limit]);

  return { programs, live, loading, nextCursor };
}
