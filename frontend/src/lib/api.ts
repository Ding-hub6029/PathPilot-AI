import { PROGRAMS } from './programs';
import { RANKING_ENTRIES, RANKING_INSTITUTIONS, RANKING_PROVIDERS } from './rankings';
import { MatchResponse, MatchResult, Profile, Program, RankingEntry, RankingInstitution, RankingProvider, RuleResult, RULES_VERSION, DATA_VERSION } from './types';

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
  if (required.every((r, i) => top[i] >= r) && mathsOk) return 'MET';
  // Contextual offer A*AB with A* in Maths is a real alternative route;
  // without evidence of contextual eligibility it is UNKNOWN, not a failure.
  const contextual = [6, 5, 4]; // A*, A, B
  if (contextual.every((r, i) => top[i] >= r) && mathsOk) return 'UNKNOWN';
  return 'NOT_MET';
}

/** The applicant's curriculum branch (fix 2026-11-25); the wizard sets
 * it, legacy profiles default to UK A-level. */
function curriculumOf(profile: Profile): string {
  return profile.curriculum ?? 'uk_alevel';
}

/** Branch-relevant observed values, same shape as the backend's
 * _ug_observed — the localized renderer depends on this shape. */
function ugObservedRaw(profile: Profile): Record<string, unknown> {
  const cur = curriculumOf(profile);
  const obs: Record<string, unknown> = { curriculum: cur };
  if (cur === 'uk_alevel' || cur === 'sg_alevel') {
    obs.grades = profile.alevels ? (profile.alevels.match(/A\*|[A-E]/gi) || []).map((g) => g.toUpperCase()) : null;
    obs.maths = profile.mathsGrade || null;
  } else if (cur === 'ib') {
    obs.total = num(profile.ibTotal);
    obs.hl_maths = num(profile.ibHlMaths);
    obs.hl_total = num(profile.ibHlTotal);
  } else if (cur === 'cn_gaokao') {
    obs.gaokao_score = num(profile.gaokaoScore);
    obs.gaokao_total = num(profile.gaokaoTotal);
    obs.gaokao_maths = num(profile.gaokaoMaths);
  } else if (cur === 'usa') {
    obs.sat_total = num(profile.satTotal);
    obs.act_composite = num(profile.actComposite);
    obs.ap_grades = profile.apGrades ? profile.apGrades.split(',').map((s) => Number(s.trim())).filter((n) => n >= 1 && n <= 5) : null;
  }
  return obs;
}

function gcsePass(grade: string | undefined): boolean | null {
  if (!grade) return null;
  const g = grade.trim().toUpperCase();
  if (!g) return null;
  if (/^\d+$/.test(g)) return Number(g) >= 4;
  const rank: Record<string, number> = { 'A*': 7, A: 6, B: 5, C: 4, D: 3, E: 2, F: 1, G: 0, U: -1 };
  return g in rank ? rank[g] >= 4 : null;
}

/** UCL IB academic rule, mirroring the backend (total 40 + HL Maths 7 +
 * HL total 20 = MET; total 40 + HL 7 but HL total < 20 = NOT_MET;
 * total 38-39 + HL 7 + HL total 18+ = contextual UNKNOWN). */
function ibUclStatus(profile: Profile): RuleResult['status'] {
  const total = num(profile.ibTotal);
  const hlMaths = num(profile.ibHlMaths);
  const hlTotal = num(profile.ibHlTotal);
  if (total === null || hlMaths === null) return 'UNKNOWN';
  if (hlTotal === null) return 'UNKNOWN';
  if (total >= 40 && hlMaths === 7 && hlTotal >= 20) return 'MET';
  if (total >= 40 && hlMaths === 7) return 'NOT_MET';
  if (total >= 38 && hlMaths === 7 && hlTotal >= 18) return 'UNKNOWN';
  return 'NOT_MET';
}

/** Imperial's published US AP standard, mirroring the backend:
 * five APs 5,5,5,4,4, or three APs 5,5,4 + SAT 1460 / ACT 31.
 * true = standard met (course-level UNKNOWN), false = below (NOT_MET),
 * null = no AP grades supplied. */
function apRouteMet(profile: Profile): boolean | null {
  const grades = (profile.apGrades ? profile.apGrades.split(',').map((s) => Number(s.trim())) : [])
    .filter((n) => n >= 1 && n <= 5).sort((a, b) => b - a);
  if (!grades.length) return null;
  const covers = (need: number[]): boolean => {
    const pool = [...grades];
    for (const n of need) {
      const i = pool.indexOf(n);
      if (i < 0) return false;
      pool.splice(i, 1);
    }
    return true;
  };
  if (covers([5, 5, 5, 4, 4])) return true;
  const sat = num(profile.satTotal);
  const act = num(profile.actComposite);
  if (covers([5, 5, 4]) && ((sat !== null && sat >= 1460) || (act !== null && act >= 31))) return true;
  return false;
}

function degreeField(degree: string): string {
  const d = degree.toLowerCase();
  if (/comput|software|information/.test(d)) return 'computing';
  if (/business|management|economics|finance|accounting|marketing/.test(d)) return 'business';
  if (/engineer|math|statistic|physics|chemistry|biology|science/.test(d)) return 'related';
  return 'other';
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
      // Academic: evaluated against the applicant's own curriculum branch
      // (fix 2026-11-25) — Gaokao / USA have no published UCL equivalence.
      const cur = curriculumOf(profile);
      let acad: RuleResult['status'];
      let acadReason: string | undefined;
      if (cur === 'ib') {
        acad = ibUclStatus(profile);
        const total = num(profile.ibTotal);
        const hlMaths = num(profile.ibHlMaths);
        const hlTotal = num(profile.ibHlTotal);
        if (acad === 'UNKNOWN' && total !== null && total >= 38 && total < 40 && hlMaths === 7 && hlTotal !== null && hlTotal >= 18) acadReason = 'contextual-offer';
      } else if (cur === 'cn_gaokao') {
        acad = 'UNKNOWN'; acadReason = 'gaokao-no-equivalence';
      } else if (cur === 'usa') {
        acad = 'UNKNOWN'; acadReason = 'usa-no-equivalence';
      } else if (cur === 'other') {
        acad = 'UNKNOWN'; acadReason = 'no-equivalence';
      } else {
        acad = alevelMeets(profile.alevels, profile.mathsGrade);
        if (acad === 'UNKNOWN' && profile.alevels && profile.mathsGrade) acadReason = 'contextual-offer';
      }
      rules.push({
        ruleId: 'ucl-academic', status: acad, observed: profile.alevels ? `${profile.alevels} (Maths ${profile.mathsGrade || '?'})` : 'Not provided',
        expected: "A*A*A with A* in Maths/Further Maths", evidenceIds: ['ucl-cs-entry'],
        reasonCode: acad === 'UNKNOWN' ? (profile.alevels && profile.mathsGrade ? 'GRADES_CONTEXTUAL' : 'MISSING_GRADES') : acad === 'MET' ? 'GRADES_MEET' : 'GRADES_BELOW',
        unknownReason: acad === 'UNKNOWN' ? (acadReason === 'contextual-offer' ? 'Grades meet the UCL contextual offer (A*AB) but contextual eligibility is not confirmed' : 'A-level grades or Maths grade not provided') : undefined,
        observedRaw: ugObservedRaw(profile),
        reasonKey: acad === 'UNKNOWN' ? (acadReason ?? 'missing-info') : undefined,
      });
      const ov = num(profile.ieltsOverall);
      const toeflOv = num(profile.toefl);
      rules.push({
        ruleId: 'ucl-ielts-overall', status: ov === null ? 'UNKNOWN' : ov >= 6.5 ? 'MET' : 'NOT_MET',
        observed: ov === null ? (toeflOv !== null ? `TOEFL iBT ${toeflOv}` : 'Not provided') : `IELTS overall ${ov}`,
        expected: 'IELTS overall 6.5', evidenceIds: ['ucl-cs-english'],
        reasonCode: ov === null ? 'MISSING_SCORE' : ov >= 6.5 ? 'SCORE_MEETS' : 'SCORE_BELOW',
        unknownReason: ov === null ? (toeflOv !== null ? 'TOEFL supplied, IELTS not supplied. TOEFL is assessed under rule ucl-toefl.' : 'IELTS overall not provided') : undefined,
        observedRaw: ov !== null ? ov : toeflOv !== null ? { exam: 'toefl', overall: toeflOv } : null,
        thresholdRaw: { overall: 6.5 },
        reasonKey: ov === null && toeflOv !== null ? 'toefl-instead' : ov === null ? 'missing-info' : undefined,
      });
      const comps = [num(profile.ieltsListening), num(profile.ieltsReading), num(profile.ieltsWriting), num(profile.ieltsSpeaking)];
      const compStatus: RuleResult['status'] = comps.some((c) => c === null) ? 'UNKNOWN' : comps.every((c) => (c as number) >= 6.0) ? 'MET' : 'NOT_MET';
      rules.push({
        ruleId: 'ucl-ielts-components', status: compStatus,
        observed: comps.every((c) => c === null) ? 'Not provided' : `L ${profile.ieltsListening ?? '–'} / R ${profile.ieltsReading ?? '–'} / W ${profile.ieltsWriting ?? '–'} / S ${profile.ieltsSpeaking ?? '–'}`,
        expected: 'IELTS minimum 6.0 in each component', evidenceIds: ['ucl-cs-english'],
        reasonCode: compStatus === 'UNKNOWN' ? 'MISSING_SCORE' : compStatus === 'MET' ? 'SCORE_MEETS' : 'SCORE_BELOW',
        unknownReason: compStatus === 'UNKNOWN' ? 'One or more IELTS component scores not provided' : undefined,
        observedRaw: { listening: comps[0], reading: comps[1], writing: comps[2], speaking: comps[3] },
        thresholdRaw: { each_component: 6.0 },
        reasonKey: compStatus === 'UNKNOWN' ? 'missing-info' : undefined,
      });
      // TOEFL (separate rule, Jan 2026 scale split by test date).
      if (toeflOv !== null) {
        const date = profile.testDate || undefined;
        const toeflStatus: RuleResult['status'] = !date ? 'UNKNOWN' : toeflOv >= (date >= '2026-01-21' ? 4.5 : 92) ? 'MET' : 'NOT_MET';
        rules.push({
          ruleId: 'ucl-toefl', status: toeflStatus,
          observed: `TOEFL iBT ${toeflOv}`,
          expected: 'TOEFL iBT Level 1: 92 (tests before 21 Jan 2026) or 4.5 on the new scale (tests from 21 Jan 2026)', evidenceIds: ['ucl-cs-english'],
          reasonCode: toeflStatus === 'UNKNOWN' ? 'MISSING_SCORE' : toeflStatus === 'MET' ? 'SCORE_MEETS' : 'SCORE_BELOW',
          unknownReason: toeflStatus === 'UNKNOWN' ? 'TOEFL supplied but no valid test date' : undefined,
          observedRaw: { exam: 'toefl', overall: toeflOv, test_date: date ?? null },
          reasonKey: toeflStatus === 'UNKNOWN' ? 'missing-test-date' : undefined,
        });
      }
      // GCSE: UK A-level branch only (or when GCSE grades were supplied);
      // other branches without GCSEs are NOT_APPLICABLE, never UNKNOWN.
      const engPass = gcsePass(profile.gcseEnglish);
      const mathsPass = gcsePass(profile.gcseMaths);
      const gcseApplicable = cur === 'uk_alevel' || engPass !== null || mathsPass !== null;
      const gcseStatus: RuleResult['status'] = !gcseApplicable ? 'NOT_APPLICABLE'
        : engPass === null || mathsPass === null ? 'UNKNOWN'
        : engPass && mathsPass ? 'MET' : 'NOT_MET';
      rules.push({
        ruleId: 'ucl-gcse', status: gcseStatus,
        observed: !gcseApplicable ? 'GCSE does not apply to this curriculum branch' : `English ${profile.gcseEnglish ?? '–'} / Maths ${profile.gcseMaths ?? '–'}`,
        expected: 'GCSE English and Maths at grade C/4 or above', evidenceIds: ['ucl-cs-entry'],
        reasonCode: gcseStatus === 'UNKNOWN' ? 'MISSING_SCORE' : gcseStatus === 'MET' ? 'SCORE_MEETS' : 'SCORE_BELOW',
        unknownReason: gcseStatus === 'UNKNOWN' ? 'GCSE grade(s) not supplied or unrecognised' : undefined,
        observedRaw: gcseApplicable ? { english: profile.gcseEnglish ?? null, maths: profile.gcseMaths ?? null } : { curriculum: cur },
        thresholdRaw: { each: 'C/4' },
        reasonKey: gcseStatus === 'NOT_APPLICABLE' ? 'gcse-not-applicable' : gcseStatus === 'UNKNOWN' ? 'missing-info' : undefined,
      });
      // TARA is required for the 2026 cycle with no stated threshold, so the
      // offline evaluator can never confirm it — same as the backend.
      rules.push({
        ruleId: 'ucl-tara', status: 'UNKNOWN',
        observed: 'TARA required for 2026 cycle; no threshold stated',
        expected: 'TARA required (no score threshold stated)', evidenceIds: ['ucl-cs-entry'],
        reasonCode: 'MISSING_SCORE',
        unknownReason: 'TARA is required but no score threshold is stated on the page',
        observedRaw: null,
        reasonKey: 'no-threshold',
      });
      const b = num(profile.budget);
      rules.push({
        ruleId: 'ucl-fee', status: b === null ? 'UNKNOWN' : b >= 46700 ? 'MET' : 'NOT_MET',
        observed: b === null ? 'Not provided' : `Budget ${profile.budgetCurrency || 'GBP'} ${b}/year`,
        expected: 'GBP 46,700/year', evidenceIds: ['ucl-cs-fees'],
        reasonCode: b === null ? 'MISSING_BUDGET' : b >= 46700 ? 'BUDGET_COVERS' : 'BUDGET_BELOW',
        unknownReason: b === null ? 'Budget not provided' : undefined,
        observedRaw: b,
        thresholdRaw: { gbp_per_year: 46700 },
        reasonKey: b === null ? 'missing-info' : undefined,
      });
    }
    if (p.id === 'nus-mcomp-cs') {
      const deg = (profile.degree || '').toLowerCase();
      const degStatus: RuleResult['status'] = !profile.degree ? 'UNKNOWN' : /comput|computer science|cs\b|software|information/.test(deg) ? 'MET' : 'UNKNOWN';
      rules.push({
        ruleId: 'nus-academic', status: degStatus,
        observed: profile.degree || 'Not provided',
        expected: 'Good honours degree in computing or related discipline', evidenceIds: ['nus-mcomp-admissions'],
        reasonCode: degStatus === 'MET' ? 'DEGREE_MATCHES' : 'DEGREE_UNVERIFIED',
        unknownReason: degStatus === 'UNKNOWN' ? 'Degree subject could not be verified from the profile as entered' : undefined,
        observedRaw: { field: degreeField(profile.degree || ''), honours: /honou?rs/.test(deg) ? true : null, experience_years: num(profile.itExperienceYears) },
        reasonKey: degStatus === 'UNKNOWN' ? 'degree-unverified' : undefined,
      });
      const ov = num(profile.ieltsOverall);
      const tf = num(profile.toefl);
      const eng: RuleResult['status'] = ov !== null ? (ov >= 6.0 ? 'MET' : 'NOT_MET') : tf !== null ? (tf >= 90 ? 'MET' : 'NOT_MET') : 'UNKNOWN';
      rules.push({
        ruleId: 'nus-language', status: eng,
        observed: ov !== null ? `IELTS overall ${ov}` : tf !== null ? `TOEFL iBT ${tf}` : 'Not provided',
        expected: 'IELTS min 6.0 overall (no component minimum stated) or TOEFL iBT min 90', evidenceIds: ['nus-mcomp-admissions'],
        reasonCode: eng === 'UNKNOWN' ? 'MISSING_SCORE' : eng === 'MET' ? 'SCORE_MEETS' : 'SCORE_BELOW',
        unknownReason: eng === 'UNKNOWN' ? 'No IELTS or TOEFL score provided' : undefined,
        observedRaw: ov ?? tf,
        thresholdRaw: { overall: 6.0 },
        reasonKey: eng === 'UNKNOWN' ? 'missing-info' : undefined,
      });
      // NUS states no IELTS component minimum, so there is no component
      // requirement to check — NOT_APPLICABLE, not UNKNOWN.
      const compStatus: RuleResult['status'] = ov !== null || tf !== null ? 'NOT_APPLICABLE' : 'UNKNOWN';
      rules.push({
        ruleId: 'nus-language-components', status: compStatus,
        observed: compStatus === 'NOT_APPLICABLE' ? 'No component minimum stated by NUS' : 'Not provided',
        expected: 'No component minimum stated (overall only)', evidenceIds: ['nus-mcomp-admissions'],
        reasonCode: compStatus === 'UNKNOWN' ? 'MISSING_SCORE' : 'NOT_APPLICABLE',
        unknownReason: compStatus === 'UNKNOWN' ? 'No IELTS or TOEFL score provided' : undefined,
        observedRaw: null,
        reasonKey: compStatus === 'UNKNOWN' ? 'missing-info' : undefined,
      });
      // Supplementary TOEFL rule (backend parity): when IELTS is the
      // primary exam but a TOEFL score was also supplied, evaluate it as
      // its own rule instead of dropping it.
      if (ov !== null && tf !== null) {
        rules.push({
          ruleId: 'nus-toefl', status: tf >= 90 ? 'MET' : 'NOT_MET',
          observed: `TOEFL iBT ${tf}`,
          expected: 'TOEFL iBT minimum 90 (supplementary; IELTS also supplied)', evidenceIds: ['nus-mcomp-admissions'],
          reasonCode: tf >= 90 ? 'SCORE_MEETS' : 'SCORE_BELOW',
          observedRaw: { exam: 'toefl', overall: tf },
          thresholdRaw: { overall: 90 },
        });
      }
      const gre = num(profile.greTotal), aw = num(profile.greAw), gmat = num(profile.gmat);
      const greOk = gre !== null && aw !== null && gre >= 320 && aw >= 3.5;
      const gmatOk = gmat !== null && gmat >= 650;
      // Backend rule: a missing or below-minimum GRE/GMAT is UNKNOWN, never
      // NOT_MET — the admissions page states no rejection rule for it.
      const greStatus: RuleResult['status'] = greOk || gmatOk ? 'MET' : 'UNKNOWN';
      const greSupplied = gre !== null || aw !== null || gmat !== null;
      rules.push({
        ruleId: 'nus-gre-gmat', status: greStatus,
        observed: gre !== null ? `GRE ${gre} / AW ${aw ?? '–'}` : gmat !== null ? `GMAT ${gmat}` : 'Not provided',
        expected: 'GRE 320 + 3.5 analytical or GMAT 650+', evidenceIds: ['nus-mcomp-gre'],
        reasonCode: greStatus === 'MET' ? 'SCORE_MEETS' : 'MISSING_SCORE',
        unknownReason: greStatus === 'UNKNOWN' ? (greSupplied ? 'GRE/GMAT supplied but below the stated minimums; the admissions page states no rejection rule for a low score' : 'No GRE or GMAT score provided — requirement status cannot be confirmed from the profile alone') : undefined,
        observedRaw: { gre_total: gre, gre_analytical: aw, gmat_total: gmat },
        reasonKey: greStatus === 'UNKNOWN' ? 'no-rejection-rule' : undefined,
      });
      const b = num(profile.budget);
      rules.push({
        ruleId: 'nus-fee', status: b === null ? 'UNKNOWN' : b >= 69215 ? 'MET' : 'NOT_MET',
        observed: b === null ? 'Not provided' : `Budget SGD ${b} total`,
        expected: 'SGD 69,215 total incl. 9% GST', evidenceIds: ['nus-mcomp-fees'],
        reasonCode: b === null ? 'MISSING_BUDGET' : b >= 69215 ? 'BUDGET_COVERS' : 'BUDGET_BELOW',
        unknownReason: b === null ? 'Budget not provided' : undefined,
        observedRaw: b,
        thresholdRaw: { sgd_total: 69215 },
        reasonKey: b === null ? 'missing-info' : undefined,
      });
    }

    // --- Day 2 (v2) programmes: offline mirror of the backend rules. ---
    // Thresholds are the verified v2 facts; IGP-only programmes (NUS/NTU
    // undergraduate) stay UNKNOWN academically, exactly like live.
    const toeflDate = profile.testDate || undefined;
    const toeflScore = num(profile.toefl);
    const ieltsOv = num(profile.ieltsOverall);
    const toeflStatus = (oldMin: number, newMin: number): RuleResult['status'] | null => {
      if (toeflScore === null) return null;
      if (!toeflDate) return 'UNKNOWN';
      return toeflScore >= (toeflDate >= '2026-01-21' ? newMin : oldMin) ? 'MET' : 'NOT_MET';
    };
    const feeStatus = (amount: number): RuleResult['status'] => {
      const b = num(profile.budget);
      if (b === null) return 'UNKNOWN';
      return b >= amount ? 'MET' : 'NOT_MET';
    };
    const pushRule = (ruleId: string, status: RuleResult['status'], observed: string, expected: string, evidenceIds: string[], unknownReason?: string,
      extra?: { observedRaw?: unknown; thresholdRaw?: Record<string, unknown>; reasonKey?: string }) => {
      rules.push({ ruleId, status, observed, expected, evidenceIds,
        reasonCode: status === 'UNKNOWN' ? 'MISSING_OR_UNVERIFIED' : status === 'MET' ? 'SCORE_MEETS' : 'SCORE_BELOW',
        unknownReason: status === 'UNKNOWN' ? (unknownReason || 'Not enough information to decide') : undefined,
        observedRaw: extra?.observedRaw ?? null,
        thresholdRaw: extra?.thresholdRaw ?? null,
        reasonKey: extra?.reasonKey ?? (status === 'UNKNOWN' ? 'missing-info' : undefined) });
    };
    if (p.id === 'imperial-comp-beng-2027') {
      // Academic: curriculum branch (fix 2026-11-25) — IB, Gaokao and USA
      // AP routes mirror the backend; UK/Singapore A level as before.
      const cur = curriculumOf(profile);
      let acad: RuleResult['status'];
      let acadReason: string | undefined;
      if (cur === 'ib') {
        const total = num(profile.ibTotal);
        const hlMaths = num(profile.ibHlMaths);
        acad = total === null || hlMaths === null ? 'UNKNOWN' : total < 41 || hlMaths < 7 ? 'NOT_MET' : 'UNKNOWN';
      } else if (cur === 'cn_gaokao') {
        acad = 'UNKNOWN'; acadReason = 'gaokao-no-equivalence';
      } else if (cur === 'usa') {
        const ap = apRouteMet(profile);
        acad = ap === false ? 'NOT_MET' : 'UNKNOWN';
        if (ap === true) acadReason = 'usa-ap-general-only';
      } else if (cur === 'other') {
        acad = 'UNKNOWN'; acadReason = 'no-equivalence';
      } else {
        acad = alevelMeets(profile.alevels, profile.mathsGrade);
        if (acad === 'UNKNOWN' && profile.alevels && profile.mathsGrade) acadReason = 'contextual-offer';
      }
      pushRule('imp-beng-academic', acad, profile.alevels || 'Not provided', 'A*A*A or A*AAA with A* in Maths', ['imperial-beng-entry'], undefined,
        { observedRaw: ugObservedRaw(profile), reasonKey: acad === 'UNKNOWN' ? (acadReason ?? 'missing-info') : undefined });
      const langOv: RuleResult['status'] = ieltsOv === null ? 'UNKNOWN' : ieltsOv >= 6.5 ? 'MET' : 'NOT_MET';
      pushRule('imp-beng-language', langOv, ieltsOv === null ? 'Not provided' : `IELTS overall ${ieltsOv}`, 'IELTS 6.5 overall, min 6.0 in all elements', ['imperial-beng-english'], undefined,
        { observedRaw: ieltsOv, thresholdRaw: { overall: 6.5 } });
      const bengComps = [num(profile.ieltsListening), num(profile.ieltsReading), num(profile.ieltsWriting), num(profile.ieltsSpeaking)];
      const bengCompSt: RuleResult['status'] = bengComps.some((c) => c === null) ? 'UNKNOWN' : bengComps.every((c) => (c as number) >= 6.0) ? 'MET' : 'NOT_MET';
      pushRule('imp-beng-language-components', bengCompSt, `L ${profile.ieltsListening ?? '–'} / R ${profile.ieltsReading ?? '–'} / W ${profile.ieltsWriting ?? '–'} / S ${profile.ieltsSpeaking ?? '–'}`, 'IELTS minimum 6.0 in all elements', ['imperial-beng-english'], undefined,
        { observedRaw: { listening: bengComps[0], reading: bengComps[1], writing: bengComps[2], speaking: bengComps[3] }, thresholdRaw: { listening: 6.0, reading: 6.0, writing: 6.0, speaking: 6.0 } });
      const tf = toeflStatus(92, 4.5);
      if (tf !== null) pushRule('imp-beng-toefl', tf, `TOEFL iBT ${toeflScore}`, 'TOEFL iBT 92 (before 21 Jan 2026) or 4.5 (new scale)', ['imperial-beng-english'], undefined,
        { observedRaw: { exam: 'toefl', overall: toeflScore, test_date: toeflDate ?? null }, reasonKey: tf === 'UNKNOWN' ? 'missing-test-date' : undefined });
      pushRule('imp-beng-tmua', 'UNKNOWN', 'TMUA required; no threshold stated', 'TMUA required (no score threshold stated)', ['imperial-beng-entry'], 'TMUA is required but no score threshold is stated',
        { observedRaw: null, reasonKey: 'no-threshold' });
      const feeAmt = profile.residency === 'uk' ? 10050 : 47800;
      pushRule('imp-beng-fee', feeStatus(feeAmt), profile.budget == null ? 'Not provided' : `Budget ${profile.budgetCurrency || 'GBP'} ${profile.budget}`, `GBP ${feeAmt.toLocaleString()}/year`, ['imperial-beng-fees'], undefined,
        { observedRaw: num(profile.budget), thresholdRaw: { amount: feeAmt }, reasonKey: profile.budget == null ? 'missing-info' : undefined });
    }
    if (p.id === 'imperial-msc-computing-2027') {
      const deg = (profile.degree || '').toLowerCase();
      const isComputing = /comput|software|information/.test(deg);
      const dc = profile.degreeClass;
      const acad: RuleResult['status'] = isComputing ? 'NOT_MET' : !dc ? 'UNKNOWN' : dc !== 'first' ? 'NOT_MET' : /business|management|economics|finance/.test(deg) ? (profile.mastersMathsGrade && ['A*', 'A'].includes(profile.mastersMathsGrade.toUpperCase()) ? 'MET' : profile.mastersMathsGrade ? 'NOT_MET' : 'UNKNOWN') : 'MET';
      pushRule('imp-msc-academic', acad, profile.degree || 'Not provided', 'First-Class degree in a subject without substantial Computing content', ['imperial-msc-entry'], undefined,
        { observedRaw: { field: degreeField(profile.degree || ''), degree_class: dc ?? null, maths_alevel: profile.mastersMathsGrade || null } });
      const mscLangOv: RuleResult['status'] = ieltsOv === null ? 'UNKNOWN' : ieltsOv >= 7.0 ? 'MET' : 'NOT_MET';
      pushRule('imp-msc-language', mscLangOv, ieltsOv === null ? 'Not provided' : `IELTS overall ${ieltsOv}`, 'IELTS 7.0 overall, min 6.5 in all elements', ['imperial-msc-english'], undefined,
        { observedRaw: ieltsOv, thresholdRaw: { overall: 7.0 } });
      const mscComps = [num(profile.ieltsListening), num(profile.ieltsReading), num(profile.ieltsWriting), num(profile.ieltsSpeaking)];
      const mscCompSt: RuleResult['status'] = mscComps.some((c) => c === null) ? 'UNKNOWN' : mscComps.every((c) => (c as number) >= 6.5) ? 'MET' : 'NOT_MET';
      pushRule('imp-msc-language-components', mscCompSt, `L ${profile.ieltsListening ?? '–'} / R ${profile.ieltsReading ?? '–'} / W ${profile.ieltsWriting ?? '–'} / S ${profile.ieltsSpeaking ?? '–'}`, 'IELTS minimum 6.5 in all elements', ['imperial-msc-english'], undefined,
        { observedRaw: { listening: mscComps[0], reading: mscComps[1], writing: mscComps[2], speaking: mscComps[3] }, thresholdRaw: { listening: 6.5, reading: 6.5, writing: 6.5, speaking: 6.5 } });
      const tf = toeflStatus(100, 5.0);
      if (tf !== null) pushRule('imp-msc-toefl', tf, `TOEFL iBT ${toeflScore}`, 'TOEFL iBT 100 (before 21 Jan 2026) or 5.0 (new scale)', ['imperial-msc-english'], undefined,
        { observedRaw: { exam: 'toefl', overall: toeflScore, test_date: toeflDate ?? null }, reasonKey: tf === 'UNKNOWN' ? 'missing-test-date' : undefined });
      pushRule('imp-msc-test', 'NOT_APPLICABLE', 'Normally no admissions tests or interviews', 'Normally no admissions tests or interviews', ['imperial-msc-entry'], undefined,
        { observedRaw: null });
      const feeAmt = profile.residency === 'uk' ? 25850 : 48300;
      pushRule('imp-msc-fee', feeStatus(feeAmt), profile.budget == null ? 'Not provided' : `Budget ${profile.budgetCurrency || 'GBP'} ${profile.budget}`, `GBP ${feeAmt.toLocaleString()}/year`, ['imperial-msc-fees'], undefined,
        { observedRaw: num(profile.budget), thresholdRaw: { amount: feeAmt }, reasonKey: profile.budget == null ? 'missing-info' : undefined });
    }
    if (p.id === 'ucl-cs-msc-2027') {
      const deg = (profile.degree || '').toLowerCase();
      const isComputing = /comput|software|information/.test(deg);
      const dc = profile.degreeClass;
      const acad: RuleResult['status'] = isComputing ? 'NOT_MET' : !dc ? 'UNKNOWN' : (dc === 'lower_second' || dc === 'third' || dc === 'other') ? 'NOT_MET' : profile.mastersMathsGrade ? 'MET' : 'UNKNOWN';
      pushRule('ucl-msc-academic', acad, profile.degree || 'Not provided', "Upper second-class degree in a subject other than CS/IT, maths to A-level standard", ['ucl-msc-entry'], undefined,
        { observedRaw: { field: degreeField(profile.degree || ''), degree_class: dc ?? null, maths_alevel: profile.mastersMathsGrade || null } });
      pushRule('ucl-msc-language', 'UNKNOWN', 'No English level stated on the course page', 'No English language level stated on the course page', ['ucl-msc-english'], 'The course page does not state which UCL English level applies',
        { observedRaw: null, reasonKey: 'no-english-level' });
      const feeAmt = profile.residency === 'uk' ? 21500 : 44400;
      pushRule('ucl-msc-fee', feeStatus(feeAmt), profile.budget == null ? 'Not provided' : `Budget ${profile.budgetCurrency || 'GBP'} ${profile.budget}`, `GBP ${feeAmt.toLocaleString()}/year`, ['ucl-msc-fees'], undefined,
        { observedRaw: num(profile.budget), thresholdRaw: { amount: feeAmt }, reasonKey: profile.budget == null ? 'missing-info' : undefined });
    }
    if (p.id === 'nus-bcomp-cs-2027') {
      pushRule('nus-bcomp-academic', 'UNKNOWN', 'IGP AAA/A (admitted students) — not a threshold', 'No fixed minimum published; Indicative Grade Profile AAA/A', ['nus-bcomp-entry'], 'NUS publishes no fixed minimum; only the Indicative Grade Profile of admitted students',
        { observedRaw: ugObservedRaw(profile), reasonKey: 'igp-not-threshold' });
      const comps = [num(profile.ieltsReading), num(profile.ieltsWriting)];
      const langSt: RuleResult['status'] = ieltsOv === null ? 'UNKNOWN' : ieltsOv >= 6.5 ? 'MET' : 'NOT_MET';
      pushRule('nus-bcomp-language', langSt, ieltsOv === null ? 'Not provided' : `IELTS overall ${ieltsOv}`, 'IELTS 6.5 overall, 6.5 in Reading and Writing', ['nus-bcomp-english'], undefined,
        { observedRaw: ieltsOv, thresholdRaw: { overall: 6.5 } });
      const compSt: RuleResult['status'] = ieltsOv === null ? 'UNKNOWN' : comps.some((c) => c === null) ? 'UNKNOWN' : comps.every((c) => (c as number) >= 6.5) ? 'MET' : 'NOT_MET';
      pushRule('nus-bcomp-language-components', compSt, `R ${profile.ieltsReading ?? '–'} / W ${profile.ieltsWriting ?? '–'}`, 'IELTS 6.5 in Reading and Writing (Listening/Speaking minima not stated)', ['nus-bcomp-english'], undefined,
        { observedRaw: { listening: num(profile.ieltsListening), reading: comps[0], writing: comps[1], speaking: num(profile.ieltsSpeaking) }, thresholdRaw: { reading: 6.5, writing: 6.5 } });
      if (toeflScore !== null) pushRule('nus-bcomp-toefl', toeflScore <= 6 ? 'UNKNOWN' : toeflScore >= 92 ? 'MET' : 'NOT_MET', `TOEFL iBT ${toeflScore}`, 'TOEFL iBT 92-93', ['nus-bcomp-english'], undefined,
        { observedRaw: { exam: 'toefl', overall: toeflScore, test_date: toeflDate ?? null }, reasonKey: toeflScore <= 6 ? 'toefl-scale-unknown' : undefined });
      const band: Record<string, number | null> = { sg_citizen: 8300, sg_pr: 11600, sg_intl_asean: 18050, sg_intl_other: 21400, sg_intl_nogrant: 39700 };
      const amt = profile.residency ? band[profile.residency] ?? null : null;
      pushRule('nus-bcomp-fee', amt === null ? 'UNKNOWN' : feeStatus(amt), profile.budget == null ? 'Not provided' : `Budget SGD ${profile.budget}/year`, amt === null ? 'AY2026/27 rates by residency band' : `SGD ${amt.toLocaleString()}/year`, ['nus-bcomp-fees'], amt === null ? 'Residency / tuition-grant status not supplied, so the fee cannot be decided' : undefined,
        { observedRaw: num(profile.budget), thresholdRaw: amt === null ? undefined : { amount: amt }, reasonKey: profile.budget == null ? 'missing-info' : amt === null ? 'fee-residency-unknown' : undefined });
    }
    if (p.id === 'ntu-bcomp-cs-2027') {
      pushRule('ntu-bcomp-academic', 'UNKNOWN', 'IGP AAB/C (10th) to AAA/A (90th) — not a threshold', 'No fixed minimum published; Indicative Grade Profile AAB/C to AAA/A', ['ntu-bcomp-entry'], 'NTU publishes no fixed minimum; only the Indicative Grade Profile of admitted students',
        { observedRaw: ugObservedRaw(profile), reasonKey: 'igp-not-threshold' });
      const comps = [num(profile.ieltsWriting), num(profile.ieltsSpeaking)];
      const langSt: RuleResult['status'] = ieltsOv === null ? 'UNKNOWN' : ieltsOv >= 6.5 ? 'MET' : 'NOT_MET';
      pushRule('ntu-bcomp-language', langSt, ieltsOv === null ? 'Not provided' : `IELTS overall ${ieltsOv}`, 'IELTS 6.5 overall, 6.5 Writing, 6.5 Speaking', ['ntu-bcomp-english'], undefined,
        { observedRaw: ieltsOv, thresholdRaw: { overall: 6.5 } });
      const compSt: RuleResult['status'] = ieltsOv === null ? 'UNKNOWN' : comps.some((c) => c === null) ? 'UNKNOWN' : comps.every((c) => (c as number) >= 6.5) ? 'MET' : 'NOT_MET';
      pushRule('ntu-bcomp-language-components', compSt, `W ${profile.ieltsWriting ?? '–'} / S ${profile.ieltsSpeaking ?? '–'}`, 'IELTS 6.5 in Writing and Speaking', ['ntu-bcomp-english'], undefined,
        { observedRaw: { listening: num(profile.ieltsListening), reading: num(profile.ieltsReading), writing: comps[0], speaking: comps[1] }, thresholdRaw: { writing: 6.5, speaking: 6.5 } });
      const tf = toeflStatus(90, 4.5);
      if (tf !== null) pushRule('ntu-bcomp-toefl', tf, `TOEFL iBT ${toeflScore}`, 'TOEFL total 90 (before 21 Jan 2026) or 4.5 (new scale)', ['ntu-bcomp-english'], undefined,
        { observedRaw: { exam: 'toefl', overall: toeflScore, test_date: toeflDate ?? null }, reasonKey: tf === 'UNKNOWN' ? 'missing-test-date' : undefined });
      const band: Record<string, number | null> = { sg_citizen: 8300, sg_pr: 11600, sg_intl_asean: 18050, sg_intl_other: 21400, sg_intl_nogrant: null };
      const amt = profile.residency ? band[profile.residency] ?? null : null;
      pushRule('ntu-bcomp-fee', amt === null ? 'UNKNOWN' : feeStatus(amt), profile.budget == null ? 'Not provided' : `Budget SGD ${profile.budget}/year`, amt === null ? 'AY2026/27 rates by residency band' : `SGD ${amt.toLocaleString()}/year`, ['ntu-bcomp-fees'], amt === null ? 'Residency / tuition-grant status not supplied, or the non-subsidised band is not labelled for CS' : undefined,
        { observedRaw: num(profile.budget), thresholdRaw: amt === null ? undefined : { amount: amt }, reasonKey: profile.budget == null ? 'missing-info' : amt === null ? 'fee-residency-unknown' : undefined });
    }
    if (p.id === 'ntu-msai-2027') {
      const deg = (profile.degree || '').toLowerCase();
      const field = /comput|software|information/.test(deg) ? 'computing' : /engineer|math|statistic|physics|science/.test(deg) ? 'related' : 'other';
      const exp = num(profile.itExperienceYears);
      const honours = /honou?rs/.test(deg);
      const acad: RuleResult['status'] = (field === 'computing' || field === 'related') && honours ? 'MET' : (field === 'computing' || field === 'related') && exp !== null && exp >= 2 ? 'MET' : 'UNKNOWN';
      pushRule('ntu-msai-academic', acad, profile.degree || 'Not provided', 'Good honours in CS/CE/related, or good bachelor’s + 2 years industry experience', ['ntu-msai-entry'], undefined,
        { observedRaw: { field, honours: honours || null, experience_years: exp } });
      const langSt: RuleResult['status'] = ieltsOv !== null ? (ieltsOv >= 6.5 ? 'MET' : 'NOT_MET') : toeflScore !== null ? (toeflStatus(100, 5.0) ?? 'UNKNOWN') : 'UNKNOWN';
      pushRule('ntu-msai-language', langSt, ieltsOv !== null ? `IELTS overall ${ieltsOv}` : toeflScore !== null ? `TOEFL iBT ${toeflScore}` : 'Not provided', 'IELTS >= 6.5 or TOEFL iBT >= 100 / >= 5.0', ['ntu-msai-english'], undefined,
        { observedRaw: ieltsOv ?? toeflScore, thresholdRaw: { overall: 6.5 } });
      // NTU MSAI states no component minimums: NOT_APPLICABLE once a
      // language test exists, UNKNOWN before that. A TOEFL supplied
      // alongside IELTS gets its own supplementary rule.
      const compSt: RuleResult['status'] = ieltsOv !== null || toeflScore !== null ? 'NOT_APPLICABLE' : 'UNKNOWN';
      pushRule('ntu-msai-language-components', compSt, compSt === 'NOT_APPLICABLE' ? 'No component minimums stated' : 'Not provided', 'No IELTS/TOEFL component minimums stated', ['ntu-msai-english'], undefined,
        { observedRaw: null });
      if (ieltsOv !== null && toeflScore !== null) {
        const sup = toeflStatus(100, 5.0);
        if (sup !== null) pushRule('ntu-msai-toefl', sup, `TOEFL iBT ${toeflScore}`, 'TOEFL iBT >= 100 (before 21 Jan 2026) or >= 5.0 on the new scale', ['ntu-msai-english'], undefined,
          { observedRaw: { exam: 'toefl', overall: toeflScore, test_date: toeflDate ?? null }, reasonKey: sup === 'UNKNOWN' ? 'missing-test-date' : undefined });
      }
      pushRule('ntu-msai-gre', 'UNKNOWN', 'GRE optional; no rejection rule stated', 'GRE optional; no rejection rule for a missing or low score', ['ntu-msai-entry'], 'GRE scores are listed as Optional; no rejection rule for a missing or low score',
        { observedRaw: { gre_total: num(profile.greTotal), gre_analytical: num(profile.greAw) }, reasonKey: 'no-rejection-rule' });
      pushRule('ntu-msai-fee', feeStatus(65748.8), profile.budget == null ? 'Not provided' : `Budget SGD ${profile.budget} total`, 'SGD 65,748.80 total incl. 9% GST', ['ntu-msai-fees'], undefined,
        { observedRaw: num(profile.budget), thresholdRaw: { amount: 65748.8 }, reasonKey: profile.budget == null ? 'missing-info' : undefined });
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

export async function fetchPrograms(opts?: { limit?: number; cursor?: string }): Promise<{ programs: Program[]; live: boolean; nextCursor?: string }> {
  try {
    const params = new URLSearchParams();
    if (opts?.limit) params.set('limit', String(opts.limit));
    if (opts?.cursor) params.set('cursor', opts.cursor);
    const qs = params.toString();
    const data = await fetchJson<{ items?: unknown[]; programs?: unknown[]; data_version?: string; next_cursor?: string | null }>(`/api/programs${qs ? `?${qs}` : ''}`);
    const raw = Array.isArray(data.items) ? data.items : Array.isArray(data.programs) ? data.programs : [];
    const items = raw.map((r) => normalizeApiProgram(r, data.data_version)).filter((p): p is Program => p !== null);
    // Empty catalogue from the API is not usable — fall back to the local
    // list rather than showing nothing, but still report live.
    const programs = items.length ? items : PROGRAMS;
    return { programs, live: true, nextCursor: data.next_cursor ?? undefined };
  } catch {
    return { programs: PROGRAMS, live: false };
  }
}

export async function fetchProgramById(id: string): Promise<{ program: Program | undefined; live: boolean }> {
  try {
    const raw = await fetchJson<unknown>(`/api/programs/${encodeURIComponent(id)}`);
    const program = normalizeApiProgram(raw);
    if (program) return { program, live: true };
  } catch { /* fall through to the local list */ }
  return { program: PROGRAMS.find((p) => p.id === id), live: false };
}

/**
 * Normalise one programme from the API into the frontend Program shape.
 * Accepts BOTH shapes: the frontend shape (feeItems + sources with
 * excerpts, as in src/lib/programs.ts) and the backend shape (snake_case:
 * official_name, degree_level, fees {overseas_per_year_gbp,
 * uk_per_year_gbp, total_sgd_incl_gst}, sources {id, title, url,
 * retrieved_at} with no excerpts). Returns null for anything unusable.
 *
 * Evidence sources: the API's sources carry no excerpts, so when the
 * programme also exists in the local list (which holds the verified
 * excerpts) the local sources win; API-only sources are kept with an
 * empty excerpt so the drawer still shows label, URL and verified date.
 */
export function normalizeApiProgram(raw: unknown, dataVersion?: string): Program | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const id = typeof r.id === 'string' ? r.id : '';
  if (!id) return null;
  const local = PROGRAMS.find((p) => p.id === id);
  const str = (v: unknown): string => (typeof v === 'string' ? v : '');
  const num = (v: unknown): number | undefined => (typeof v === 'number' && !Number.isNaN(v) ? v : undefined);

  // Already frontend-shaped: keep it, filling gaps from the local entry.
  if (Array.isArray(r.feeItems)) {
    const feeItems = (r.feeItems as Record<string, unknown>[])
      .map((f) => ({ label: str(f.label), amount: num(f.amount) ?? 0, currency: str(f.currency) || 'GBP', period: str(f.period) || 'per year' }))
      .filter((f) => f.amount > 0 || local !== undefined);
    const sources = normalizeSources(r.sources, local);
    return {
      id,
      institution: str(r.institution) || local?.institution || '',
      institutionId: str(r.institutionId) || local?.institutionId || id.split('-')[0],
      officialName: str(r.officialName) || local?.officialName || id,
      country: str(r.country) || local?.country || '',
      degreeLevel: (r.degreeLevel === 'undergraduate' || r.degreeLevel === 'taught_masters' ? r.degreeLevel : local?.degreeLevel) ?? 'undergraduate',
      subject: str(r.subject) || local?.subject || '',
      intakeYear: num(r.intakeYear) ?? local?.intakeYear ?? 0,
      intakeLabel: str(r.intakeLabel) || local?.intakeLabel || '',
      duration: str(r.duration) || local?.duration || '',
      feeItems: feeItems.length ? feeItems : local?.feeItems ?? [],
      ucasCode: str(r.ucasCode) || local?.ucasCode,
      status: str(r.status) || 'active',
      datasetVersion: str(r.datasetVersion) || dataVersion || local?.datasetVersion || DATA_VERSION,
      sources,
    };
  }

  // Backend (snake_case) shape.
  const fees = (r.fees ?? {}) as Record<string, unknown>;
  const feeItems: Program['feeItems'] = [];
  const currency = str(fees.currency) || 'GBP';
  const overseas = num(fees.overseas_per_year_gbp);
  const uk = num(fees.uk_per_year_gbp);
  const total = num(fees.total_sgd_incl_gst) ?? num(fees.total) ?? num(fees.amount);
  const period = str(fees.period);
  if (overseas !== undefined) feeItems.push({ label: 'Overseas tuition fee', amount: overseas, currency, period: 'per year' });
  if (uk !== undefined) feeItems.push({ label: 'UK tuition fee', amount: uk, currency, period: 'per year' });
  if (total !== undefined && overseas === undefined) feeItems.push({ label: 'Total tuition incl. GST', amount: total, currency, period: period || 'total' });
  if (period === 'per_year' && overseas === undefined && total !== undefined) {
    // A per-year fee reported only as a single total: keep the amount with
    // its stated period rather than inventing an overseas/UK split.
    feeItems[0] = { label: 'Tuition fee', amount: total, currency, period: 'per year' };
  }
  const intakeYear = num(r.intake_year) ?? local?.intakeYear ?? 0;
  const intakeLabel = str(r.start) || str(r.intake) || local?.intakeLabel || (intakeYear ? String(intakeYear) : '');
  return {
    id,
    institution: str(r.institution) || local?.institution || '',
    institutionId: local?.institutionId || id.split('-')[0],
    officialName: str(r.official_name) || local?.officialName || id,
    country: str(r.country) || local?.country || '',
    degreeLevel: (r.degree_level === 'undergraduate' || r.degree_level === 'taught_masters' ? r.degree_level : local?.degreeLevel) ?? 'undergraduate',
    subject: typeof r.subject === 'string' ? r.subject : local?.subject || '',
    intakeYear,
    intakeLabel,
    duration: str(r.duration) || local?.duration || '',
    feeItems: feeItems.length ? feeItems : local?.feeItems ?? [],
    ucasCode: str(r.ucas_code) || local?.ucasCode,
    status: 'active',
    datasetVersion: dataVersion || local?.datasetVersion || DATA_VERSION,
    sources: normalizeSources(r.sources, local),
  };
}

function normalizeSources(rawSources: unknown, local: Program | undefined): Program['sources'] {
  const apiSources: Program['sources'] = Array.isArray(rawSources)
    ? (rawSources as Record<string, unknown>[]).map((s) => ({
        id: typeof s.id === 'string' ? s.id : '',
        url: typeof s.url === 'string' ? s.url : '',
        label: typeof s.title === 'string' ? s.title : typeof s.label === 'string' ? s.label : '',
        excerpt: typeof s.excerpt === 'string' ? s.excerpt : '',
        verifiedDate: typeof s.retrieved_at === 'string' ? s.retrieved_at.slice(0, 10) : typeof s.verifiedDate === 'string' ? s.verifiedDate : '',
      })).filter((s) => s.id && s.url)
    : [];
  if (!local) return apiSources;
  // Local sources carry the verified excerpts; keep them, and append any
  // API-only source the local list does not have yet.
  const merged = [...local.sources];
  for (const s of apiSources) {
    if (!merged.some((m) => m.id === s.id)) merged.push(s);
  }
  return merged;
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

// --- Rankings (Day 3, spec Ch9 FR15/FR16) -----------------------------------
// Live backend first, offline fallback (RANKING_ENTRIES, identical values)
// when the backend is unreachable. No combined or averaged rank is ever
// computed here (BR15); world and subject ranks are never mixed — this
// build ships world ranks only, so a subject filter returns no entries.
export interface RankingsResult {
  providers: RankingProvider[];
  institutions: RankingInstitution[];
  entries: RankingEntry[];
  live: boolean;
}

export async function fetchRankings(): Promise<RankingsResult> {
  try {
    const prov = await fetchJson<{ providers: RankingProvider[] }>('/api/rankings/providers');
    const providers = Array.isArray(prov.providers) && prov.providers.length ? prov.providers : RANKING_PROVIDERS;
    // The backend caps limit at 20, so page through the cursor until the
    // list ends (300 entries = 15 pages). The loop is bounded so a
    // misbehaving API cannot spin forever.
    const entries: RankingEntry[] = [];
    let cursor: string | undefined;
    for (let page = 0; page < 50; page++) {
      const qs = new URLSearchParams({ limit: '20', ...(cursor ? { cursor } : {}) }).toString();
      const chunk = await fetchJson<{ items: RankingEntry[]; next_cursor?: string | null }>(`/api/rankings?${qs}`);
      entries.push(...(chunk.items ?? []));
      cursor = chunk.next_cursor ?? undefined;
      if (!cursor) break;
    }
    const list = entries.length ? entries : RANKING_ENTRIES;
    return { providers, institutions: RANKING_INSTITUTIONS, entries: list, live: true };
  } catch {
    return { providers: RANKING_PROVIDERS, institutions: RANKING_INSTITUTIONS, entries: RANKING_ENTRIES, live: false };
  }
}

export async function fetchInstitutionRankings(institutionId: string): Promise<{ institution: RankingInstitution | undefined; entries: RankingEntry[]; live: boolean }> {
  try {
    const data = await fetchJson<{ institution: RankingInstitution; rankings: RankingEntry[] }>(`/api/institutions/${encodeURIComponent(institutionId)}/rankings`);
    return { institution: data.institution, entries: data.rankings, live: true };
  } catch {
    return {
      institution: RANKING_INSTITUTIONS.find((i) => i.id === institutionId),
      entries: RANKING_ENTRIES.filter((e) => e.institution_id === institutionId),
      live: false,
    };
  }
}
