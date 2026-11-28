import { useEffect, useState } from 'react';
import { fetchJsonPatient } from './api';
import { checkingDelayMs, freshAiVerdict, probeVerdictApplies, type AiStatusPayload } from './aiStatus';

/**
 * Single source of truth for the AI verdict (Round 29, E5 — re-test
 * task 23, 2026-11-28).
 *
 * The contradiction: during one run the wizard said "AI 暂时无法连接"
 * (its own per-turn `aiOffline` flag, from a failed pref-chat turn)
 * while the /results banner said "Live backend connected" (backend
 * health only — `useBackendStatus`, which says nothing about the
 * model) and the pet footer said "AI answers" (CompassPet's own
 * `aiLive` state, from its own fresh probe + its own turn verdicts).
 * Three surfaces, three independent verdicts, three different
 * answers about the same model at the same moment.
 *
 * Every surface now reads this one module instead of deriving a
 * verdict of its own:
 * - the pet footer (CompassPet), the wizard's guided-mode banner
 *   (PrefChat) and the results banner (results/page) all render
 *   `useAiVerdict()` — one cached verdict, one label
 *   (`aiVerdictLineKey`), so they can never disagree;
 * - there is one probe (`probeAiVerdict`, a FRESH ?fresh=1 read
 *   applied only through `freshAiVerdict`, lib/aiStatus.ts) —
 *   concurrent callers share the single in-flight read instead of
 *   each probing, and a re-probe is explicit (panel open, devil
 *   enable, footer retry, clear-data), never automatic on mount
 *   once a verdict has settled;
 * - a real chat turn's verdict (`noteAiTurnVerdict`) is the
 *   strongest evidence and overwrites the cached verdict at once,
 *   from whichever surface the turn ran on — a model reply in the
 *   wizard makes the pet footer live, a template reply in the pet
 *   makes the wizard banner offline;
 * - a probe verdict is still the weakest evidence
 *   (`probeVerdictApplies`, Round 22): it applies only when no
 *   turn is in flight and no turn verdict landed since the probe
 *   started, so a slow probe can never overwrite a fresher turn
 *   verdict in either direction;
 * - while the verdict is unknown the state is `checking` and every
 *   surface says checking — never "AI answers" in one place and
 *   "offline" in another. `resetAiVerdict` (clear-data) returns
 *   the verdict to checking and invalidates any in-flight probe,
 *   whose verdict is pre-clear evidence.
 *
 * Deliberately NOT in here: the backend-health verdict
 * (`useBackendStatus`) — reachable backend is not available AI,
 * and the results banner must not render one as the other — and
 * the turn-latency skip verdict (`modelAvailability`, lib/api.ts),
 * which is a performance gate, never a displayed claim.
 */

export type AiVerdict = 'checking' | 'live' | 'offline';

export interface AiVerdictState {
  verdict: AiVerdict;
  /** The last offline verdict came after the patient budget was
   * spent (a retry fired during the probe) or a chat turn was cut
   * by its own timer — the footer says "timed out", not bare
   * "offline". Only meaningful while verdict is 'offline'. */
  timedOut: boolean;
}

/** Locale key for the shared verdict line — the same key on every
 * surface, so the three banners can never disagree about the
 * wording either. Mirrors `footerAiLineKey` (lib/aiStatus.ts) over
 * the shared state instead of CompassPet's local flags. */
export function aiVerdictLineKey(state: AiVerdictState): string {
  if (state.verdict === 'live') return 'pet.aiLive';
  if (state.verdict === 'offline') return state.timedOut ? 'pet.offlineTimeout' : 'pet.offline';
  return 'pet.aiChecking';
}

/** Bounded fresh re-probes for an available-but-unprobed claim
 * (Round 21 W1: never claim AI on it); after these, offline — the
 * safe direction. */
const UNCONFIRMED_RETRIES = 2;
const UNCONFIRMED_RETRY_DELAY_MS = 2000;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

let cached: AiVerdictState = { verdict: 'checking', timedOut: false };
const listeners = new Set<(s: AiVerdictState) => void>();
/** Bumped by resetAiVerdict: an in-flight probe from before the
 * reset is pre-clear evidence and must never land. */
let probeSeq = 0;
let inFlight: Promise<AiVerdictState> | null = null;
/** Round 22 W1 guard, moved here from CompassPet: a probe verdict
 * applies only while no turn is in flight and no turn verdict has
 * landed since the probe started. */
let turnInFlight = false;
let turnGen = 0;

function emit(next: AiVerdictState): void {
  cached = next;
  listeners.forEach((fn) => fn(next));
}

export function getAiVerdict(): AiVerdictState {
  return cached;
}

export function subscribeAiVerdict(fn: (s: AiVerdictState) => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

export interface ProbeAiOptions {
  /** Hold the checking state visible for at least
   * AI_CHECKING_MIN_MS (the pet footer: a warm-cache probe used
   * to resolve in a fraction of a second, so the checking line
   * was never perceived). */
  minChecking?: boolean;
  /** Fires before each patient retry — the caller shows its
   * waking line while a retry is in flight. */
  onRetry?: () => void;
  /** Patient budget override — production default is
   * fetchJsonPatient's 90 s; tests pass a small budget so a
   * failing probe settles fast instead of retrying for 90 s. */
  budgetMs?: number;
}

/** The one shared probe. Concurrent callers share the single
 * in-flight read; a call while no probe is in flight starts a
 * fresh one. Resolves with the settled shared state — which may
 * be the unchanged state when the probe verdict was dropped by
 * the turn guard (the turn's own verdict lands when it ends). */
export function probeAiVerdict(opts?: ProbeAiOptions): Promise<AiVerdictState> {
  if (inFlight) return inFlight;
  const seq = ++probeSeq;
  const genAtStart = turnGen;
  const minChecking = opts?.minChecking ?? false;
  const startedAt = Date.now();
  let retryFired = false;
  const onRetry = () => { retryFired = true; opts?.onRetry?.(); };
  const applies = () =>
    probeVerdictApplies({ turnInFlight, turnVerdictGenAtProbeStart: genAtStart, turnVerdictGenNow: turnGen });

  const run = (async (): Promise<AiVerdictState> => {
    let attempt = 0;
    for (;;) {
      if (probeSeq !== seq) return cached;
      let payload: AiStatusPayload;
      try {
        payload = await fetchJsonPatient<AiStatusPayload>('/api/ai/status?fresh=1', {},
          { onRetry, ...(opts?.budgetMs !== undefined ? { budgetMs: opts.budgetMs } : {}) });
      } catch {
        // The status read itself failed (backend asleep /
        // unreachable): that says the model cannot be reached, so
        // offline — the safe direction. The patient fetch already
        // retried while the backend woke; a retry that fired means
        // the budget was spent, i.e. a timeout, not a fast refusal.
        if (minChecking) await sleep(checkingDelayMs(Date.now() - startedAt));
        if (probeSeq !== seq) return cached;
        if (!applies()) return cached;
        const next: AiVerdictState = { verdict: 'offline', timedOut: retryFired };
        emit(next);
        return next;
      }
      if (probeSeq !== seq) return cached;
      const verdict = freshAiVerdict(payload);
      if (verdict === null) {
        // Available but unprobed: never claim AI on it. Bounded
        // fresh re-probes (the backend normally never returns this
        // for ?fresh=1); after that, offline, with the footer retry
        // available to re-check.
        if (attempt < UNCONFIRMED_RETRIES) {
          attempt += 1;
          await sleep(UNCONFIRMED_RETRY_DELAY_MS);
          continue;
        }
        if (minChecking) await sleep(checkingDelayMs(Date.now() - startedAt));
        if (probeSeq !== seq) return cached;
        if (!applies()) return cached;
        const next: AiVerdictState = { verdict: 'offline', timedOut: false };
        emit(next);
        return next;
      }
      if (minChecking) await sleep(checkingDelayMs(Date.now() - startedAt));
      if (probeSeq !== seq) return cached;
      if (!applies()) return cached;
      const next: AiVerdictState = { verdict: verdict ? 'live' : 'offline', timedOut: false };
      emit(next);
      return next;
    }
  })();
  inFlight = run;
  run.finally(() => { if (inFlight === run) inFlight = null; });
  return run;
}

/** A real chat turn started — a probe resolving while it runs must
 * not overwrite the verdict the turn is about to produce. */
export function beginAiTurn(): void {
  turnInFlight = true;
}

/** A turn ended without noting a verdict (its reply was ignored —
 * e.g. superseded by a restart): it is no longer in flight, so a
 * later probe verdict may apply. */
export function endAiTurn(): void {
  turnInFlight = false;
}

/** A real chat turn's verdict — the strongest evidence about the
 * model, from whichever surface the turn ran on. A model reply
 * (ai_status "available") claims AI; a template-only reply or a
 * failed turn declares offline. `timedOut` is true when the turn
 * was cut by its own timer (a slow abort), so the footer says
 * "timed out" instead of a bare "offline". */
export function noteAiTurnVerdict(live: boolean, opts?: { timedOut?: boolean }): void {
  turnInFlight = false;
  turnGen += 1;
  emit({ verdict: live ? 'live' : 'offline', timedOut: opts?.timedOut ?? false });
}

/** Clear-data: a fresh session for the verdict. The verdict
 * returns to unknown (every surface says checking until a fresh
 * verdict lands) and any in-flight probe is invalidated — its
 * verdict is pre-clear evidence. The next explicit probe (panel
 * open, retry) or the hook's auto-probe re-verifies. */
export function resetAiVerdict(): void {
  probeSeq += 1;
  inFlight = null;
  emit({ verdict: 'checking', timedOut: false });
}

/** Read the shared verdict in a component. Starts the shared
 * probe when the verdict is unknown — so a surface that mounts
 * while the verdict is checking (results page after a clear, the
 * wizard after a clear) re-verifies instead of sitting on
 * "checking" forever — and re-renders every surface the moment
 * the verdict settles. Never probes once a verdict has settled:
 * re-verification is explicit (panel open, devil enable, footer
 * retry, clear-data). */
export function useAiVerdict(): AiVerdictState {
  const [state, setLocal] = useState<AiVerdictState>(cached);
  useEffect(() => {
    listeners.add(setLocal);
    return () => { listeners.delete(setLocal); };
  }, []);
  useEffect(() => {
    if (state.verdict === 'checking') void probeAiVerdict();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.verdict]);
  return state;
}
