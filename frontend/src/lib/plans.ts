import { fetchJson, fetchJsonPatient, modelAvailability, type FetchPatientOptions } from './api';
import type { Profile } from './types';

/** Improvement-plan API (Day 3, spec Ch6 FR13/FR14; W3 expansion fix).
 *
 * The backend lives behind the same /api rewrite as /match, so these
 * paths are /api/improvement-plan... (rewritten to /api/v1/...).
 * createPlan / reassessPlan use the patient fetch: the free Render
 * instance sleeps after 15 min idle and takes ~50s+ to wake. Task
 * status updates use the plain fetch: retrying a POST that already
 * applied would surface a spurious 422 (the transition guard), so a
 * task update that fails fast reports its error instead of retrying.
 *
 * Reliability boundary (user constraint): nothing here invents a
 * verdict. Gap current_state strings and reassessment changes come
 * from the engine; tasks are AI suggestions (or deterministic
 * templates when no model is configured) and may be wrong.
 */

export interface PlanResource {
  label: string;
  url: string | null;
  search_criteria: string | null;
}

export type TaskStatus = 'todo' | 'in_progress' | 'done' | 'to_verify';

export interface PlanTask {
  task_id: string;
  gap_id: string;
  category: string;
  target_program_ids: string[];
  title: string;
  rationale: string;
  current_state: string;
  expected_outcome: string;
  steps: string[];
  resources: PlanResource[];
  weekly_hours: number;
  cost_range: { min: number | null; max: number | null; currency: string | null };
  duration_weeks: number;
  prerequisites: string[];
  acceptance_checklist: string[];
  alternatives: string[];
  uncertainty: string;
  status: TaskStatus;
  deadline: string | null;
}

export interface PlanGap {
  gap_id: string;
  program_id: string;
  category: string;
  evidence_class: 'hard_requirement' | 'competitiveness' | 'to_confirm';
  rule_ids: string[];
  evidence_ids: string[];
  current_state: string;
  what_is_missing: string;
}

export interface Plan {
  plan_id: string;
  track: string;
  program_ids: string[];
  deadline: string | null;
  gap_assessment: { track: string; gaps: PlanGap[] };
  tasks: PlanTask[];
  weekly_schedule: {
    weeks: { week: number; task_ids: string[]; weekly_hours: number }[];
    total_weeks: number;
  };
  assumptions: string[];
  limitations: string[];
  ai_status: 'available' | 'unavailable';
  versions: number[];
}

export interface ReassessChange {
  program_id: string;
  rule_id: string;
  old_status: string;
  new_status: string;
}

export interface ReassessResult {
  plan_id: string;
  new_version: number;
  changes: ReassessChange[];
  remaining_gaps: PlanGap[];
  unknowns: string[];
  note: string;
}

/** Backend error code from a fetch failure, e.g. PROGRAM_NOT_EVALUABLE
 * (display-only programme) or PROGRAM_NOT_FOUND. Null when unknown. */
export function planErrorCode(err: unknown): string | null {
  const body = (err as { body?: { error?: { code?: string } } } | null)?.body;
  return typeof body?.error?.code === 'string' ? body.error.code : null;
}

export function planErrorStatus(err: unknown): number | null {
  const status = (err as { status?: number } | null)?.status;
  return typeof status === 'number' ? status : null;
}

/** True when a fetch failure is the backend's AI-budget rate limit
 * (HTTP 429, error code RATE_LIMITED). Callers show the distinct
 * "too frequent, wait a minute" message for this instead of the
 * generic error — a 429 is a wait-and-retry, not a broken run. */
export function isRateLimitedError(err: unknown): boolean {
  return planErrorStatus(err) === 429 || planErrorCode(err) === 'RATE_LIMITED';
}

export async function createPlan(
  profile: Profile,
  programId: string,
  locale: string,
  options?: FetchPatientOptions,
): Promise<Plan> {
  const budget =
    typeof profile.budget === 'number'
      ? { amount: profile.budget, currency: profile.budgetCurrency || 'GBP' }
      : undefined;
  // Round 14 fail-fast: the plan endpoint has no template-only flag —
  // the plan itself (plan_id, stored tasks) can only be created
  // server-side — so this POST always goes out. But when the model is
  // known-unavailable, the status read above has already run the live
  // probe, and a failed probe trips the backend circuit breaker: the
  // backend's model attempt then raises at once instead of spending
  // its 15 s budget, and the template tasks return in engine time.
  // When the status read itself fails ('unknown'), the call proceeds
  // exactly as before — an unread status says nothing about the model.
  await modelAvailability();
  return fetchJsonPatient<Plan>(
    '/api/improvement-plan',
    {
      method: 'POST',
      body: JSON.stringify({
        profile,
        program_ids: [programId],
        weekly_hours: 6,
        budget,
        locale,
      }),
    },
    // Round 13: 40s per attempt (same as the round-10 chat fix) so a
    // single slow-but-healthy backend attempt is not aborted mid-flight
    // at the 25s default; the overall budget stays 90s.
    { attemptTimeoutMs: 40_000, budgetMs: 90_000, ...options },
  );
}

export async function getPlan(planId: string): Promise<Plan> {
  return fetchJson<Plan>(`/api/improvement-plan/${encodeURIComponent(planId)}`);
}

export async function updateTaskStatus(
  planId: string,
  taskId: string,
  status: TaskStatus,
  userConfirmedEvidence?: string,
): Promise<PlanTask> {
  return fetchJson<PlanTask>(
    `/api/improvement-plan/${encodeURIComponent(planId)}/tasks/${encodeURIComponent(taskId)}`,
    {
      method: 'POST',
      body: JSON.stringify({
        status,
        ...(userConfirmedEvidence ? { user_confirmed_evidence: userConfirmedEvidence } : {}),
      }),
    },
  );
}

/** Build a reassessment patch from the wizard's current flat profile:
 * only the fields the user actually filled in. The backend deep-merges
 * it into the stored profile and recomputes every rule with the engine;
 * a client-supplied verdict is never trusted. An empty patch is a
 * no-change reassessment (the backend says so). */
export function buildProfilePatch(profile: Profile): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  const num = (v: number | '' | undefined): number | undefined =>
    typeof v === 'number' && !Number.isNaN(v) ? v : undefined;
  const language: Record<string, unknown> = {};
  if (num(profile.ieltsOverall) !== undefined || num(profile.toefl) !== undefined) {
    language.exam = num(profile.ieltsOverall) !== undefined ? 'ielts' : 'toefl';
    for (const [flat, nested] of [
      ['ieltsOverall', 'overall'],
      ['ieltsListening', 'listening'],
      ['ieltsReading', 'reading'],
      ['ieltsWriting', 'writing'],
      ['ieltsSpeaking', 'speaking'],
    ] as const) {
      const v = num(profile[flat]);
      if (v !== undefined) language[nested] = v;
    }
    if (num(profile.toefl) !== undefined) language.toefl_overall = num(profile.toefl);
    patch.language = language;
  }
  if (num(profile.budget) !== undefined) {
    patch.budget = {
      amount: num(profile.budget),
      currency: profile.budgetCurrency || 'GBP',
      period: profile.track === 'taught_masters' ? 'total' : 'per_year',
    };
  }
  const undergrad: Record<string, unknown> = {};
  if (num(profile.gaokaoScore) !== undefined) undergrad.gaokao_score = num(profile.gaokaoScore);
  if (num(profile.gaokaoTotal) !== undefined) undergrad.gaokao_total = num(profile.gaokaoTotal);
  if (num(profile.gaokaoMaths) !== undefined) undergrad.gaokao_maths = num(profile.gaokaoMaths);
  if (Object.keys(undergrad).length) patch.undergrad_profile = undergrad;
  return patch;
}

export async function reassessPlan(
  planId: string,
  profile: Profile,
  options?: FetchPatientOptions,
): Promise<ReassessResult> {
  return fetchJsonPatient<ReassessResult>(
    '/api/improvement-plan/reassess',
    {
      method: 'POST',
      body: JSON.stringify({
        plan_id: planId,
        profile_patch: buildProfilePatch(profile),
      }),
    },
    // Round 13: same 40s attempt / 90s budget as createPlan.
    { attemptTimeoutMs: 40_000, budgetMs: 90_000, ...options },
  );
}
