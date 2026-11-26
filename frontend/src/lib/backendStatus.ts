import { useEffect, useState } from 'react';
import { fetchJsonPatient } from './api';

/**
 * One shared backend-status source (Round 9, R9).
 *
 * The bug: every page decided "live backend connected?" on its own, from
 * a different probe with a different timeout — the rankings page seeded
 * `live: false` and showed "实时后端尚未连接" from first paint until its
 * 30s background refresh settled, the browse page showed its offline note
 * before its fetch even started, while the results page showed "后端已连接"
 * because its patient 90s match call had already succeeded. Same backend,
 * contradictory banners.
 *
 * Every page now reads this one hook instead of deriving status from its
 * own fetch:
 * - 'checking' — the probe has not settled yet. Pages show a "checking…"
 *   line, never an offline claim: a sleeping free-tier backend takes
 *   ~50s+ to wake, and "not answered yet" is not "offline".
 * - 'live' — /api/health answered.
 * - 'offline' — the patient probe (90s budget, same as matchProfile)
 *   exhausted its retries without an answer.
 *
 * The probe runs once per page load (module-level singleton promise) no
 * matter how many pages mount the hook, and its result is shared with
 * every subscriber, so all pages agree for the same backend state.
 */
export type BackendStatus = 'checking' | 'live' | 'offline';

let cached: BackendStatus = 'checking';
let inFlight: Promise<BackendStatus> | null = null;
const listeners = new Set<(s: BackendStatus) => void>();

function setStatus(s: BackendStatus): void {
  cached = s;
  listeners.forEach((fn) => fn(s));
}

function probe(): Promise<BackendStatus> {
  if (cached !== 'checking') return Promise.resolve(cached);
  if (!inFlight) {
    // /api/health rewrites to the backend's /api/v1/health (exempt from
    // rate limiting). Patient budget matches matchProfile so the status
    // never contradicts a live match call that is still waking.
    inFlight = fetchJsonPatient<{ status?: string }>('/api/health', undefined, { budgetMs: 90_000, attemptTimeoutMs: 25_000 })
      .then(() => {
        setStatus('live');
        return 'live' as BackendStatus;
      })
      .catch(() => {
        setStatus('offline');
        return 'offline' as BackendStatus;
      })
      .finally(() => {
        inFlight = null;
      });
  }
  return inFlight;
}

export function useBackendStatus(): BackendStatus {
  const [status, setLocal] = useState<BackendStatus>(cached);
  useEffect(() => {
    listeners.add(setLocal);
    if (cached === 'checking') void probe();
    return () => {
      listeners.delete(setLocal);
    };
  }, []);
  return status;
}
