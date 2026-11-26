// Multi-change what-if simulation (Day 3): typed client for the extended
// POST /api/simulate flat contract — scenarios + leverage + explanation.
// The candidate patches here mirror the backend's leverage_candidates
// (ai/simulate_explain.py): only changes the engine actually evaluates.
// No Gaokao candidate exists on either side: no university publishes a
// Gaokao equivalence, so the academic rule stays UNKNOWN whatever the score.
import { fetchJsonPatient, modelAvailability, type FetchPatientOptions } from './api';
import { DATA_VERSION, MatchResponse, Profile, RULES_VERSION } from './types';

export interface SimulateChange {
  field: string;
  from: number;
  to: number;
}

export interface LeverageCandidate {
  id: string;
  patch: Partial<Profile>;
  change: SimulateChange;
  flips: number;
  flipped_program_ids: string[];
  /** Strict NOT_MET -> MET count; often 0 (UNKNOWN rules block MET). */
  flips_to_met: number;
  rule_flips: number;
  flipped_rules: { program_id: string; rule_id: string; baseline_status: string; scenario_status: string }[];
}

export interface SimulateScenario {
  name: string | null;
  patch: Partial<Profile>;
  scenario: MatchResponse;
  delta: { program_id: string; rule_id: string; baseline_status: string; scenario_status: string }[];
  programme_flips: { program_id: string; baseline_summary: string; scenario_summary: string }[];
  flipped_program_ids: string[];
  flipped_to_met_ids: string[];
  rule_flip_count: number;
}

export interface SimulateExplanation {
  text: string;
  structured: Record<string, unknown>;
  ai_status: string;
  source: 'model' | 'template';
  top_change: string | null;
}

export interface MultiSimulateResponse {
  baseline: MatchResponse;
  scenarios: SimulateScenario[];
  scenario: MatchResponse;
  delta: SimulateScenario['delta'];
  leverage: { top: LeverageCandidate | null; all: LeverageCandidate[] };
  explanation: SimulateExplanation;
}

export interface SimulateCandidate {
  id: string;
  patch: Partial<Profile>;
  change: SimulateChange;
}

const CANDIDATE_SPECS: { id: string; field: 'ieltsOverall' | 'ieltsWriting' | 'budget'; delta: number }[] = [
  { id: 'ielts-overall-plus-0.5', field: 'ieltsOverall', delta: 0.5 },
  { id: 'ielts-writing-plus-0.5', field: 'ieltsWriting', delta: 0.5 },
  { id: 'budget-plus-10000', field: 'budget', delta: 10000 },
  { id: 'budget-plus-5000', field: 'budget', delta: 5000 },
];

/** Candidate single-field changes for a profile, in display order.
 * A candidate is offered only when its baseline value is a number. */
export function leverageCandidates(profile: Profile): SimulateCandidate[] {
  const out: SimulateCandidate[] = [];
  for (const spec of CANDIDATE_SPECS) {
    const base = profile[spec.field];
    if (typeof base !== 'number') continue;
    const next = spec.field === 'budget' ? base + spec.delta : Math.round((base + spec.delta) * 2) / 2;
    if (spec.field !== 'budget' && next > 9) continue;
    out.push({ id: spec.id, patch: { [spec.field]: next } as Partial<Profile>, change: { field: spec.field, from: base, to: next } });
  }
  return out;
}

/** Default selection for the multi-simulate toggles (Round 13).
 * The two budget options are mutually exclusive — both raise the same
 * budget field, so checking both would apply two different patches to
 * one field. The default keeps the larger step (+£10,000) and drops
 * +£5,000; the IELTS options are independent of each other and of the
 * budget, so they stay checked. */
export function defaultSimulateSelection(candidates: SimulateCandidate[]): string[] {
  const ids = candidates.map((c) => c.id);
  if (ids.includes('budget-plus-10000')) return ids.filter((id) => id !== 'budget-plus-5000');
  return ids;
}

const BUDGET_OPTION_IDS = ['budget-plus-10000', 'budget-plus-5000'];

/** Toggle one candidate, enforcing budget mutual exclusion: checking
 * one budget option unchecks the other; unchecking never affects the
 * other option. Non-budget toggles are independent. */
export function toggleSimulateSelection(prev: string[], id: string): string[] {
  if (prev.includes(id)) return prev.filter((x) => x !== id);
  if (!BUDGET_OPTION_IDS.includes(id)) return [...prev, id];
  const other = id === 'budget-plus-10000' ? 'budget-plus-5000' : 'budget-plus-10000';
  return [...prev.filter((x) => x !== other), id];
}

/** Run several scenarios at once. The backend evaluates every scenario
 * plus the leverage candidates against the same verified rules; the
 * response carries the per-scenario deltas, the leverage ranking and
 * the (template or model) explanation. `explain: true` asks the backend
 * to attempt one citation-checked model call; without it the response
 * carries the deterministic template explanation only.
 *
 * Round 14 fail-fast: when the model is KNOWN-unavailable (the live
 * /ai/status probe said so — cached 60 s, shared with createPlan),
 * the explained call is never fired: explain:false goes out at once
 * and the template renders in engine time instead of spending the
 * backend's 15 s model budget proving the gateway is still down. When
 * the status read itself fails ('unknown' — backend asleep, network
 * error), the model is attempted once as before: an unread status
 * says nothing about the model, and the patient fetch wakes a
 * sleeping backend. The existing fallback (a failed explain:true call
 * retries once with explain:false in SimulatePanel) is untouched. */
export async function simulateMulti(
  profile: Profile,
  programIds: string[],
  scenarios: { name: string; patch: Partial<Profile> }[],
  opts?: { explain?: boolean; locale?: string; patientOptions?: FetchPatientOptions },
): Promise<MultiSimulateResponse> {
  const wantExplain = opts?.explain ?? true;
  const explain = wantExplain && (await modelAvailability()) !== 'unavailable';
  return fetchJsonPatient<MultiSimulateResponse>('/api/simulate', {
    method: 'POST',
    body: JSON.stringify({
      baseline_profile: profile,
      scenarios,
      program_ids: programIds,
      locale: opts?.locale,
      explain,
      versions: { data_version: DATA_VERSION, rules_version: RULES_VERSION },
    }),
  },
  // Round 13: 40s per attempt (same as the round-10 chat fix) so a
  // single slow-but-healthy backend attempt is not aborted mid-flight
  // at the 25s default; the overall budget stays 90s.
  { attemptTimeoutMs: 40_000, budgetMs: 90_000, ...opts?.patientOptions });
}

/** Locale key for a candidate id (frontend/messages/*.json, sim.*). */
export function candidateLabelKey(id: string): string {
  switch (id) {
    case 'ielts-overall-plus-0.5': return 'sim.candidateOverall';
    case 'ielts-writing-plus-0.5': return 'sim.candidateWriting';
    case 'budget-plus-10000': return 'sim.candidateBudget10k';
    case 'budget-plus-5000': return 'sim.candidateBudget5k';
    default: return 'sim.candidateUnknown';
  }
}
