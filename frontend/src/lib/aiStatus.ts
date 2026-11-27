/** Pet footer AI-verdict rules (Round 21 W1) — pure, zero-dependency,
 * so the task-15 harness can exercise the real decision logic in Node.
 *
 * Background: the footer claimed "AI 回答" on the very first homepage
 * open (re-test task 15, 2026-11-27 13:22) while the model was offline
 * the whole run. The open-probe accepted any backend `available`,
 * but /api/v1/ai/status caches its verdict 60 s server-side, shared
 * by every user/tab, and served the cached verdict with
 * "probed": True — a verdict primed minutes earlier by someone else,
 * from a 1-token probe weaker than a real turn, was indistinguishable
 * from a live probe in this open. The checking line also resolved so
 * fast from that warm cache that it was never perceived.
 *
 * Rules pinned here:
 * - Only a FRESH live probe (ai_status "available" AND probed true,
 *   i.e. a probe that ran in this open via ?fresh=1) may claim AI.
 * - "unavailable" is always accepted as down (the safe direction).
 * - An available-but-unprobed claim is UNCONFIRMED (null) — never
 *   live, never silently down; the caller re-probes fresh instead.
 * - The checking state is visible for at least AI_CHECKING_MIN_MS
 *   after an open, however fast the probe resolves. */

/** Minimum time the footer shows the checking line after a panel
 * open / devil enable, in ms — long enough to be perceived even when
 * the probe resolves from a warm path in a fraction of a second. */
export const AI_CHECKING_MIN_MS = 1200;

/** The /api/v1/ai/status payload fields the footer decision reads. */
export interface AiStatusPayload {
  ai_status?: string;
  probed?: boolean;
  cache_age_s?: number | null;
}

/** Interpret one /ai/status payload as a footer verdict.
 * true = a fresh live probe just confirmed the model (claim AI);
 * false = the model is down (show offline); null = unconfirmed —
 * an "available" that did not come from a fresh probe in this open
 * (cached / config-only claim). Null must never produce "AI 回答". */
export function freshAiVerdict(payload: AiStatusPayload): boolean | null {
  if (payload.ai_status === 'unavailable') return false;
  if (payload.ai_status === 'available' && payload.probed === true) return true;
  return null;
}

/** Footer line key for the non-waking branch — the exact semantics
 * of the CompassPet footer ternary (offline beats live, a false
 * verdict is offline, true is the AI line, null is checking). The
 * waking branch is handled by the caller, as before. */
export function footerAiLineKey(args: {
  offline: boolean;
  timedOut: boolean;
  aiLive: boolean | null;
}): string {
  if (args.offline || args.aiLive === false) {
    return args.timedOut ? 'pet.offlineTimeout' : 'pet.offline';
  }
  if (args.aiLive === true) return 'pet.aiLive';
  return 'pet.aiChecking';
}

/** Probe verdicts are the WEAKEST evidence about the model — a
 * 1-token chat, weaker than a real turn — so a probe verdict may only
 * be applied while it is still the freshest evidence. Round 22 W1
 * (re-test task 16, 2026-11-27 14:21-14:27): the open probe is slow
 * (its 1-token confirmation hangs up to ~7 s on a flapping gateway)
 * while a turn verdict can land first — the known-down fast path
 * declares offline within ~1-2 s of open — so the probe resolved
 * "available" DURING the user's lookup and flipped the footer
 * offline -> "AI 回答" mid-turn; the turn's template reply then set
 * it back to offline. The old probe guard (a sequence ref) only
 * protected against newer PROBES, never against TURN verdicts.
 *
 * A probe verdict applies only when BOTH hold:
 * - no turn is currently in flight (a turn in flight is about to
 *   produce fresher, real-turn evidence), AND
 * - no turn verdict has landed since this probe started (a turn
 *   verdict after the probe started is fresher evidence than the
 *   probe, whichever direction it points).
 * Dropping a stale probe verdict is always safe: the turn's own
 * verdict lands when it ends, and the footer retry re-probes. */
export function probeVerdictApplies(args: {
  turnInFlight: boolean;
  turnVerdictGenAtProbeStart: number;
  turnVerdictGenNow: number;
}): boolean {
  if (args.turnInFlight) return false;
  return args.turnVerdictGenAtProbeStart === args.turnVerdictGenNow;
}

/** Milliseconds to wait before applying a verdict that arrived
 * `elapsedMs` after the open, so the checking state is visible for
 * at least AI_CHECKING_MIN_MS in total. */
export function checkingDelayMs(elapsedMs: number): number {
  return Math.max(0, AI_CHECKING_MIN_MS - elapsedMs);
}
