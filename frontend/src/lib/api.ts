import { PROGRAMS } from './programs';
import { MatchResponse, MatchResult, Profile, Program, RuleResult, RULES_VERSION, DATA_VERSION } from './types';

// Local (offline) evaluation mirroring the backend contract. Used ONLY when
// the live backend is unreachable; results are labelled offline in the UI.
// Rule statuses: MET / NOT_MET / UNKNOWN — never guess a missing value.
function num(v: number | '' | undefined): number | null {
  return typeof v === 'number' && !Number.isNaN(v) ? v : null;
}

function gradeRank(g: string): number {
  const m = g.trim().toUpperCase().match(/^(A\*|A|B|C|D|E)/);
  if (!m) return -1;
  return { 'A*': 6, A: 5, B: 4, C: 3, D: 2, E: 1 }[m[1]] ?? -1;
}

function alevelMeets(alevels: string | undefined, maths: string | undefined): RuleResult['status'] | 'UNKNOWN' {
  if (!alevels || !maths) return 'UNKNOWN';
  // Requirement: A*A*A incl. A* in Maths/Further Maths.
  // Requirement "A*A*A" = grades A*, A*, A (two starred), plus A* in Maths.
  const grades = (alevels.match(/A\*|[A-E]/gi) || []).map((g) => g.toUpperCase());
  if (grades.length < 3 || grades.some((g) => gradeRank(g) < 0)) return 'UNKNOWN';
  const required = [6, 6, 5]; // A*, A*, A
  const top = grades.map(gradeRank).sort((a, b) => b - a);
  const mathsOk = gradeRank(maths) >= 6;
  return required.every((r, i) => top[i] >= r) && mathsOk ? 'MET' : 'NOT_MET';
}

export function evaluateLocal(profile: Profile, programIds: string[]): MatchResponse {
  const results: MatchResult[] = programIds.map((id) => {
    const p = PROGRAMS.find((x) => x.id === id);
    if (!p) {
      return { programId: id, eligibilitySummary: 'UNKNOWN', ruleResults: [], trackMismatch: false };
    }
    if (profile.track && profile.track !== p.degreeLevel) {
      return { programId: id, eligibilitySummary: 'TRACK_MISMATCH', ruleResults: [], trackMismatch: true };
    }
    const rules: RuleResult[] = [];
    if (p.id === 'ucl-cs-bsc-2026') {
      const a = alevelMeets(profile.alevels, profile.mathsGrade);
      rules.push({
        ruleId: 'ucl-alevel', status: a, observed: profile.alevels ? `${profile.alevels} (Maths ${profile.mathsGrade || '?'})` : 'Not provided',
        expected: "A*A*A with A* in Maths/Further Maths", evidenceIds: ['ucl-cs-entry'],
        reasonCode: a === 'UNKNOWN' ? 'MISSING_GRADES' : a === 'MET' ? 'GRADES_MEET' : 'GRADES_BELOW',
        unknownReason: a === 'UNKNOWN' ? 'A-level grades or Maths grade not provided' : undefined,
      });
      const ov = num(profile.ieltsOverall);
      rules.push({
        ruleId: 'ucl-ielts-overall', status: ov === null ? 'UNKNOWN' : ov >= 6.5 ? 'MET' : 'NOT_MET',
        observed: ov === null ? 'Not provided' : `IELTS overall ${ov}`,
        expected: 'IELTS overall 6.5', evidenceIds: ['ucl-cs-english'],
        reasonCode: ov === null ? 'MISSING_SCORE' : ov >= 6.5 ? 'SCORE_MEETS' : 'SCORE_BELOW',
        unknownReason: ov === null ? 'IELTS overall not provided' : undefined,
      });
      const comps = [num(profile.ieltsListening), num(profile.ieltsReading), num(profile.ieltsWriting), num(profile.ieltsSpeaking)];
      const compStatus: RuleResult['status'] = comps.some((c) => c === null) ? 'UNKNOWN' : comps.every((c) => (c as number) >= 6.0) ? 'MET' : 'NOT_MET';
      rules.push({
        ruleId: 'ucl-ielts-components', status: compStatus,
        observed: comps.every((c) => c === null) ? 'Not provided' : `L ${profile.ieltsListening ?? '–'} / R ${profile.ieltsReading ?? '–'} / W ${profile.ieltsWriting ?? '–'} / S ${profile.ieltsSpeaking ?? '–'}`,
        expected: 'IELTS minimum 6.0 in each component', evidenceIds: ['ucl-cs-english'],
        reasonCode: compStatus === 'UNKNOWN' ? 'MISSING_SCORE' : compStatus === 'MET' ? 'SCORE_MEETS' : 'SCORE_BELOW',
        unknownReason: compStatus === 'UNKNOWN' ? 'One or more IELTS component scores not provided' : undefined,
      });
      const b = num(profile.budget);
      rules.push({
        ruleId: 'ucl-budget', status: b === null ? 'UNKNOWN' : b >= 46700 ? 'MET' : 'NOT_MET',
        observed: b === null ? 'Not provided' : `Budget ${profile.budgetCurrency || 'GBP'} ${b}/year`,
        expected: 'GBP 46,700/year', evidenceIds: ['ucl-cs-fees'],
        reasonCode: b === null ? 'MISSING_BUDGET' : b >= 46700 ? 'BUDGET_COVERS' : 'BUDGET_BELOW',
        unknownReason: b === null ? 'Budget not provided' : undefined,
      });
    }
    if (p.id === 'nus-mcomp-cs') {
      const deg = (profile.degree || '').toLowerCase();
      const degStatus: RuleResult['status'] = !profile.degree ? 'UNKNOWN' : /comput|computer science|cs\b|software|information/.test(deg) ? 'MET' : 'UNKNOWN';
      rules.push({
        ruleId: 'nus-degree', status: degStatus,
        observed: profile.degree || 'Not provided',
        expected: 'Good honours degree in computing or related discipline', evidenceIds: ['nus-mcomp-admissions'],
        reasonCode: degStatus === 'MET' ? 'DEGREE_MATCHES' : 'DEGREE_UNVERIFIED',
        unknownReason: degStatus === 'UNKNOWN' ? 'Degree subject could not be verified from the profile as entered' : undefined,
      });
      const ov = num(profile.ieltsOverall);
      const tf = num(profile.toefl);
      const eng: RuleResult['status'] = ov !== null ? (ov >= 6.0 ? 'MET' : 'NOT_MET') : tf !== null ? (tf >= 90 ? 'MET' : 'NOT_MET') : 'UNKNOWN';
      rules.push({
        ruleId: 'nus-english', status: eng,
        observed: ov !== null ? `IELTS overall ${ov}` : tf !== null ? `TOEFL iBT ${tf}` : 'Not provided',
        expected: 'IELTS min 6.0 overall (no component minimum stated) or TOEFL iBT min 90', evidenceIds: ['nus-mcomp-admissions'],
        reasonCode: eng === 'UNKNOWN' ? 'MISSING_SCORE' : eng === 'MET' ? 'SCORE_MEETS' : 'SCORE_BELOW',
        unknownReason: eng === 'UNKNOWN' ? 'No IELTS or TOEFL score provided' : undefined,
      });
      const gre = num(profile.greTotal), aw = num(profile.greAw), gmat = num(profile.gmat);
      const greOk = gre !== null && aw !== null && gre >= 320 && aw >= 3.5;
      const gmatOk = gmat !== null && gmat >= 650;
      const greStatus: RuleResult['status'] = greOk || gmatOk ? 'MET' : gre === null && aw === null && gmat === null ? 'UNKNOWN' : 'NOT_MET';
      rules.push({
        ruleId: 'nus-gre-gmat', status: greStatus,
        observed: gre !== null ? `GRE ${gre} / AW ${aw ?? '–'}` : gmat !== null ? `GMAT ${gmat}` : 'Not provided',
        expected: 'GRE 320 + 3.5 analytical or GMAT 650+', evidenceIds: ['nus-mcomp-gre'],
        reasonCode: greStatus === 'UNKNOWN' ? 'MISSING_SCORE' : greStatus === 'MET' ? 'SCORE_MEETS' : 'SCORE_BELOW',
        unknownReason: greStatus === 'UNKNOWN' ? 'No GRE or GMAT score provided — requirement status cannot be confirmed from the profile alone' : undefined,
      });
      const b = num(profile.budget);
      rules.push({
        ruleId: 'nus-budget', status: b === null ? 'UNKNOWN' : b >= 69215 ? 'MET' : 'NOT_MET',
        observed: b === null ? 'Not provided' : `Budget SGD ${b} total`,
        expected: 'SGD 69,215 total incl. 9% GST', evidenceIds: ['nus-mcomp-fees'],
        reasonCode: b === null ? 'MISSING_BUDGET' : b >= 69215 ? 'BUDGET_COVERS' : 'BUDGET_BELOW',
        unknownReason: b === null ? 'Budget not provided' : undefined,
      });
    }
    const summary = rules.some((r) => r.status === 'NOT_MET') ? 'NOT_MET' : rules.some((r) => r.status === 'UNKNOWN') ? 'PARTIAL_UNKNOWN' : 'MET';
    return { programId: id, eligibilitySummary: summary, ruleResults: rules };
  });
  return {
    evaluationId: `local-${Date.now()}`,
    results,
    rulesVersion: RULES_VERSION,
    sourceManifestHash: 'local-offline',
    live: false,
  };
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) } });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = new Error(`HTTP ${res.status}`) as Error & { status?: number; body?: unknown };
    err.status = res.status; err.body = body;
    throw err;
  }
  return res.json() as Promise<T>;
}

export async function matchProfile(profile: Profile): Promise<MatchResponse> {
  const programIds = profile.targetProgramIds.length ? profile.targetProgramIds : PROGRAMS.filter((p) => p.degreeLevel === profile.track).map((p) => p.id);
  try {
    const live = await fetchJson<MatchResponse>('/api/match', {
      method: 'POST',
      body: JSON.stringify({ profile, program_ids: programIds, data_version: DATA_VERSION }),
    });
    return { ...live, live: true };
  } catch {
    return evaluateLocal(profile, programIds);
  }
}

export async function fetchPrograms(): Promise<{ programs: Program[]; live: boolean }> {
  try {
    const data = await fetchJson<{ items: Program[]; data_version: string }>('/api/programs');
    const items = Array.isArray(data.items) && data.items.length ? data.items : PROGRAMS;
    return { programs: items, live: true };
  } catch {
    return { programs: PROGRAMS, live: false };
  }
}

export async function simulate(profile: Profile, patch: Partial<Profile>): Promise<MatchResponse> {
  const scenario = { ...profile, ...patch };
  const programIds = profile.targetProgramIds.length ? profile.targetProgramIds : PROGRAMS.filter((p) => p.degreeLevel === profile.track).map((p) => p.id);
  try {
    const live = await fetchJson<{ baseline: MatchResponse; scenario: MatchResponse; delta: unknown }>('/api/simulate', {
      method: 'POST',
      body: JSON.stringify({ baseline_profile: profile, patch, program_ids: programIds, versions: { data_version: DATA_VERSION, rules_version: RULES_VERSION } }),
    });
    return { ...live.scenario, live: true };
  } catch {
    return evaluateLocal(scenario, programIds);
  }
}
