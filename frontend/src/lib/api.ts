import { PROGRAMS } from './programs';
import { RANKING_ENTRIES, RANKING_INSTITUTIONS, RANKING_PROVIDERS } from './rankings';
import { EXPANSION_PROGRAMS } from './expansion';
import { MatchResponse, MatchResult, Profile, Program, RankingEntry, RankingInstitution, RankingProvider, RuleResult, RULES_VERSION, DATA_VERSION, ExpansionProgram } from './types';
import { cityClimate, climateFit, normaliseClimatePref } from './preferences';
import { convertCurrency, FX_AS_OF } from './fx';

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

// --- Expansion programmes (round 6) ----------------------------------------
// Offline mirror of backend/domain/expansion_eval.py. Only structured
// verified data is evaluated; everything else is UNKNOWN, never MET on
// missing data. Rule ids: exp-fee / exp-language / exp-language-components
// / exp-academic. Language requirements on one programme are ALTERNATIVE
// routes (MET when any evidenced route is met). TOEFL follows the v2 Jan
// 2026 scale split. A-level thresholds are assessed for uk_alevel /
// sg_alevel curricula only; other scores are never converted.

const EXP_GRADE_RANK: Record<string, number> = { 'A*': 5, A: 4, B: 3, C: 2, D: 1, E: 0 };
const EXP_TOEFL_CUTOFF = '2026-01-21';

function expNum(v: unknown): number | null {
  return typeof v === 'number' && !Number.isNaN(v) ? v : null;
}

/** Python `f"{n:g}"` for the expected-label mirror: integers print
 * without a decimal point, other numbers print shortest-round-trip. */
function fmtNumG(n: number): string {
  return String(n);
}

function expRule(ruleId: string, status: RuleResult['status'], observed: string, expected: string, evidenceIds: string[], unknownReason?: string,
  extra?: { observedRaw?: unknown; thresholdRaw?: Record<string, unknown> | null; reasonKey?: string }): RuleResult {
  return {
    ruleId, status, observed, expected, evidenceIds,
    reasonCode: status === 'UNKNOWN' ? 'MISSING_OR_UNVERIFIED' : status === 'MET' ? 'SCORE_MEETS' : status === 'NOT_MET' ? 'SCORE_BELOW' : 'NOT_APPLICABLE',
    unknownReason: status === 'UNKNOWN' ? (unknownReason || 'Not enough information to decide') : undefined,
    observedRaw: extra?.observedRaw ?? null,
    thresholdRaw: extra?.thresholdRaw ?? null,
    reasonKey: extra?.reasonKey ?? (status === 'UNKNOWN' ? 'missing-info' : undefined),
  };
}

type ExpLangKind = 'ielts' | 'toefl' | 'duolingo' | 'pte' | 'hsk' | 'cefr' | 'other';

function expClassifyLanguage(req: { id: string; description: string; threshold?: Record<string, unknown> | null }): ExpLangKind | null {
  const th = req.threshold;
  if (!th || typeof th !== 'object') return null;
  if ('ielts_overall' in th || 'ielts' in th) return 'ielts';
  if ('toefl_ibt' in th || 'toefl_ibt_overall' in th || 'toefl_overall' in th) return 'toefl';
  // Round 9, R13: classify on the structured threshold keys first, so
  // a CEFR requirement is 'cefr' even when its id/description never
  // spells the word out (the Swiss German C1 / French B2 requirements
  // were read as 'other').
  if ('cefr_level' in th) return 'cefr';
  if ('duolingo_overall' in th || 'duolingo' in th) return 'duolingo';
  if ('pte_overall' in th) return 'pte';
  if ('hsk_level' in th) return 'hsk';
  const rid = req.id.toLowerCase();
  const desc = req.description.slice(0, 40).toLowerCase();
  for (const key of ['ielts', 'toefl', 'duolingo', 'pte', 'hsk', 'cefr'] as const) {
    if (rid.includes(key) || desc.includes(key)) return key;
  }
  return 'other';
}

/** Human label for a structured non-IELTS/TOEFL language requirement,
 * e.g. "German C1 (CEFR)" — the mirror of the backend's
 * _other_language_label. */
function expOtherLanguageLabel(req: { threshold?: Record<string, unknown> | null }, kind: ExpLangKind | null): string | null {
  const th = req.threshold;
  if (!th || typeof th !== 'object') return null;
  if (kind === 'cefr') {
    const level = th.cefr_level;
    const lang = th.language;
    if (typeof level === 'string' && level.trim()) {
      return typeof lang === 'string' && lang.trim() ? `${lang} ${level} (CEFR)` : `CEFR ${level}`;
    }
    return null;
  }
  if (kind === 'hsk') {
    const level = expNum(th.hsk_level);
    return level !== null ? `HSK ${level}` : null;
  }
  if (kind === 'duolingo') {
    const score = expNum(th.duolingo_overall) ?? expNum(th.duolingo);
    return score !== null ? `Duolingo ${score}` : null;
  }
  if (kind === 'pte') {
    const score = expNum(th.pte_overall);
    return score !== null ? `PTE ${score}` : null;
  }
  return null;
}

function expIeltsOverallOf(th: Record<string, unknown>, kind: ExpLangKind): number | null {
  if (kind !== 'ielts') return null;
  for (const key of ['ielts_overall', 'ielts', 'overall']) {
    const v = expNum(th[key]);
    if (v !== null) return v;
  }
  return null;
}

function expToeflOverallOf(th: Record<string, unknown>, kind: ExpLangKind): number | null {
  if (kind !== 'toefl') return null;
  // Round 9, R13: the bare "toefl_overall" key (UCLA CS BS / CSE BS,
  // TOEFL 100) was not read, so a real stated threshold was dropped.
  for (const key of ['toefl_ibt_overall', 'toefl_ibt', 'toefl_overall', 'overall']) {
    const v = expNum(th[key]);
    if (v !== null) return v;
  }
  return null;
}

function expIeltsComponentSets(th: Record<string, unknown>, kind: ExpLangKind): Record<string, number>[] {
  if (kind !== 'ielts') return [];
  const sets: Record<string, number>[] = [];
  const each = expNum(th.each_component) ?? expNum(th.ielts_min_each) ?? expNum(th.min_section);
  if (each !== null) {
    sets.push({ listening: each, reading: each, writing: each, speaking: each });
  }
  const three = expNum(th.ielts_min_three_components);
  const remaining = expNum(th.ielts_min_remaining);
  if (three !== null && remaining !== null) {
    sets.push({ __three__: three, __remaining__: remaining });
  }
  const per: Record<string, number> = {};
  for (const key of ['ielts_listening', 'ielts_reading', 'ielts_writing', 'ielts_speaking']) {
    const v = expNum(th[key]);
    if (v !== null && v <= 9) per[key.slice('ielts_'.length)] = v;
  }
  for (const key of ['listening', 'reading', 'writing', 'speaking']) {
    const v = expNum(th[key]);
    if (v !== null && v <= 9 && !(key in per)) per[key] = v;
  }
  if (Object.keys(per).length) sets.push(per);
  return sets;
}

function expHasToeflSections(th: Record<string, unknown>, kind: ExpLangKind): boolean {
  if (kind !== 'toefl') return false;
  if ('toefl_ibt_min_each' in th || 'toefl_ibt_min_other' in th || 'toefl_ibt_writing' in th) return true;
  return ['listening', 'reading', 'writing', 'speaking'].some((k) => {
    const v = expNum(th[k]);
    return v !== null && v > 9;
  });
}

interface ExpLangThresholds {
  ieltsOveralls: number[];
  toeflOveralls: number[];
  componentSets: Record<string, number>[];
  hasToeflSections: boolean;
  hasAnyLanguageReq: boolean;
  /** Real stated requirements in another system (CEFR / HSK /
   * Duolingo / PTE) — shown instead of a fake IELTS/TOEFL label. */
  otherLabels: string[];
}

function expLanguageThresholds(ep: ExpansionProgram): ExpLangThresholds {
  const out: ExpLangThresholds = { ieltsOveralls: [], toeflOveralls: [], componentSets: [], hasToeflSections: false, hasAnyLanguageReq: false, otherLabels: [] };
  for (const req of ep.requirements) {
    if (req.category !== 'language') continue;
    out.hasAnyLanguageReq = true;
    const th = req.threshold;
    if (!th || typeof th !== 'object') continue;
    const kind = expClassifyLanguage(req);
    const label = expOtherLanguageLabel(req, kind);
    if (label !== null && !out.otherLabels.includes(label)) out.otherLabels.push(label);
    if (!kind || kind === 'duolingo' || kind === 'pte' || kind === 'hsk' || kind === 'cefr' || kind === 'other') continue;
    const io = expIeltsOverallOf(th, kind);
    if (io !== null) out.ieltsOveralls.push(io);
    const to = expToeflOverallOf(th, kind);
    if (to !== null) out.toeflOveralls.push(to);
    out.componentSets.push(...expIeltsComponentSets(th, kind));
    if (expHasToeflSections(th, kind)) out.hasToeflSections = true;
  }
  return out;
}

function expToeflRoute(score: number, threshold: number, testDate: string | undefined): 'met' | 'below' | 'unknown' {
  if (threshold <= 6) {
    if (!testDate || testDate < EXP_TOEFL_CUTOFF) return 'unknown';
    return score >= threshold ? 'met' : 'below';
  }
  if (score <= 6) return 'unknown';
  return score >= threshold ? 'met' : 'below';
}

function expParseAlevelTriples(text: string): number[][] {
  const found = text.toUpperCase().match(/A\*|[A-E]/g) || [];
  const triples: number[][] = [];
  for (let i = 0; i + 2 < found.length; i += 3) {
    triples.push([found[i], found[i + 1], found[i + 2]].map((g) => EXP_GRADE_RANK[g]).sort((a, b) => b - a));
  }
  return triples;
}

/** Lexicographic compare of two grade triples (both sorted desc). */
function expCmpTriples(a: number[], b: number[]): number {
  for (let i = 0; i < 3; i++) {
    if (a[i] !== b[i]) return a[i] - b[i];
  }
  return 0;
}

/** Does the applicant's top-3 meet the stated minimum triple? */
function expTripleMeets(top: number[], minimum: number[]): boolean {
  return expCmpTriples(top, minimum) >= 0;
}

interface ExpAlevelReq {
  kind: 'string' | 'grades';
  minimum: number[];
  mathsRank: number | null;
  sourceIds: string[];
}

function expAlevelRequirements(ep: ExpansionProgram): ExpAlevelReq[] {
  const out: ExpAlevelReq[] = [];
  for (const req of ep.requirements) {
    if (req.category !== 'academic') continue;
    const th = req.threshold;
    if (!th || typeof th !== 'object') continue;
    if (typeof th.a_level === 'string' && th.a_level.trim()) {
      const triples = expParseAlevelTriples(th.a_level);
      if (triples.length) {
        const minimum = triples.reduce((a, b) => (expCmpTriples(a, b) <= 0 ? a : b));
        out.push({ kind: 'string', minimum, mathsRank: null, sourceIds: [...req.sourceIds] });
      }
    }
    const grades = th.grades;
    if (Array.isArray(grades) && grades.length >= 3 && grades.every((g) => typeof g === 'string' && g.toUpperCase() in EXP_GRADE_RANK)) {
      const ranks = (grades as string[]).map((g) => EXP_GRADE_RANK[g.toUpperCase()]).sort((a, b) => b - a).slice(0, 3);
      const maths = typeof th.maths_grade === 'string' ? EXP_GRADE_RANK[th.maths_grade.toUpperCase()] ?? null : null;
      out.push({ kind: 'grades', minimum: ranks, mathsRank: maths, sourceIds: [...req.sourceIds] });
    }
  }
  return out;
}

function expAlevelTop3(alevels: string | undefined): number[] | null {
  if (!alevels) return null;
  const grades = (alevels.match(/A\*|[A-E]/gi) || []).map((g) => g.toUpperCase());
  const ranks = grades.map((g) => EXP_GRADE_RANK[g] ?? -1);
  if (ranks.length < 3 || ranks.some((r) => r < 0)) return null;
  return ranks.sort((a, b) => b - a).slice(0, 3);
}

/** Human period text for fee display: the raw "per_year" token must
 * never reach the screen (round 9, R2). */
function expPeriodText(period: string): string {
  if (period === 'per_year') return 'per year';
  if (period === 'per_credit') return 'per credit';
  return period || '';
}

function expFeeRule(profile: Profile, ep: ExpansionProgram): RuleResult {
  const fees = ep.fees;
  const amount = expNum(fees.amount);
  const currency = fees.currency || '';
  const period = fees.period || '';
  const evidence = ep.requirements.filter((r) => r.category === 'fee').flatMap((r) => r.sourceIds);
  let thresholdRaw: Record<string, unknown> | null = amount !== null ? { amount, currency, period } : null;
  const budget = num(profile.budget);
  const budgetCurrency = profile.budgetCurrency || (profile.track === 'undergraduate' ? 'GBP' : 'SGD');
  const budgetPeriod = profile.track === 'undergraduate' ? 'per_year' : 'total';
  const budgetObserved = budget === null
    ? 'Not provided'
    : `Budget ${budgetCurrency} ${budget.toLocaleString('en-US')} ${expPeriodText(budgetPeriod)}`;
  // Round 8 (P5 display fix, mirroring backend _exp_expected): show
  // the real fee when one is stated ("Tuition fee CHF 4,380 per
  // year"); the generic label only when there genuinely is no amount
  // — and then the rule is UNKNOWN below, never NOT_MET. Round 9
  // (R2): when the fee currency differs from the budget currency and
  // the reference table converts it, the expected line also shows the
  // approximate converted figure, always labelled approximate. The
  // converted figure is also carried in thresholdRaw.approx_converted
  // (round 9 integration) so the localised renderer (ruleExpected)
  // can show it without re-parsing the string.
  let expected = amount !== null
    ? ['Tuition fee', currency, amount.toLocaleString('en-US'), expPeriodText(period)].filter(Boolean).join(' ')
    : 'Tuition fee as stated on the official programme page';
  let converted: number | null = null;
  // The approximate figure is shown only when the periods match, so
  // it is never displayed next to a rule that is UNKNOWN on period.
  if (amount !== null && budget !== null && currency && budgetCurrency !== currency && budgetPeriod === period) {
    converted = convertCurrency(amount, currency, budgetCurrency);
    if (converted !== null) {
      expected += ` (approx. ${budgetCurrency} ${Math.round(converted).toLocaleString('en-US')}, rates ${FX_AS_OF})`;
      thresholdRaw = { ...thresholdRaw, approx_converted: { amount: Math.round(converted), currency: budgetCurrency, as_of: FX_AS_OF } };
    }
  }
  if (amount === null) {
    // P0-2 (re-test task 6): the fee is UNKNOWN because the official
    // page states no amount — NOT because the user withheld anything.
    // The old default reasonKey 'missing-info' rendered "未提供这项
    // 检查所需的信息" on cards like Alberta / ANU even with a GBP
    // 50,000 budget supplied. The backend adapter maps the same case
    // to 'fee-not-published'; this mirror must agree.
    return expRule('exp-fee', 'UNKNOWN', 'Not provided', expected, evidence,
      'No tuition fee amount is stated on the official programme page, so the fee cannot be compared with the budget.', { thresholdRaw, reasonKey: 'fee-not-published' });
  }
  if (period === 'per_credit') {
    // P0-2: same mis-mapping class — a per-credit fee cannot be
    // compared without a credit count, which is not user information
    // withheld; it is a property of the fee itself.
    return expRule('exp-fee', 'UNKNOWN', `Tuition is ${currency} ${amount.toLocaleString('en-US')} per credit`, expected, evidence,
      'Tuition is charged per credit; the profile has no credit count, so a per-credit fee cannot be compared with the budget.', { thresholdRaw, reasonKey: 'fee-per-credit' });
  }
  if (budget === null) {
    return expRule('exp-fee', 'UNKNOWN', 'Not provided', expected, evidence, 'No budget supplied.', { thresholdRaw });
  }
  if (budgetPeriod !== period) {
    return expRule('exp-fee', 'UNKNOWN', budgetObserved, expected, evidence,
      `Budget period (${budgetPeriod}) does not match the fee period (${period}), so it cannot be compared with the fee.`,
      { observedRaw: { amount: budget, currency: budgetCurrency, period: budgetPeriod }, thresholdRaw, reasonKey: 'budget-mismatch' });
  }
  if (budgetCurrency !== currency) {
    // Round 9, R2: cross-currency comparison with the dated,
    // approximate FX reference table (frontend/src/lib/fx.ts). A
    // currency with no reference rate is UNKNOWN ("cannot be
    // converted"), never a false mismatch.
    if (converted === null) {
      return expRule('exp-fee', 'UNKNOWN', budgetObserved, expected, evidence,
        `The fee is ${currency} ${amount.toLocaleString('en-US')} ${expPeriodText(period)} and the budget is in ${budgetCurrency}; no reference exchange rate is available for this currency pair, so the fee cannot be converted for comparison.`,
        { observedRaw: { amount: budget, currency: budgetCurrency, period: budgetPeriod }, thresholdRaw, reasonKey: 'fx-cannot-convert' });
    }
    if (budget >= converted) {
      return expRule('exp-fee', 'MET', budgetObserved, expected, evidence,
        undefined, { observedRaw: budget, thresholdRaw });
    }
    return expRule('exp-fee', 'NOT_MET', budgetObserved, expected, evidence,
      undefined, { observedRaw: budget, thresholdRaw });
  }
  if (budget >= amount) {
    return expRule('exp-fee', 'MET', budgetObserved, expected, evidence,
      undefined, { observedRaw: budget, thresholdRaw });
  }
  return expRule('exp-fee', 'NOT_MET', budgetObserved, expected, evidence,
    undefined, { observedRaw: budget, thresholdRaw });
}

/** English `expected` for the components rule, mirroring backend
 * _exp_expected: the real component minimums when stated ("IELTS
 * minimum 7 in each component"); the generic label only when no
 * component minimum exists — and then the rule is UNKNOWN (or
 * NOT_APPLICABLE), never NOT_MET. Multiple alternative sets are
 * joined with " or ". */
function expComponentExpected(sets: Record<string, number>[]): string {
  const generic = 'No IELTS component minimum published';
  if (!sets.length) return generic;
  const renderSet = (s: Record<string, number>): string | null => {
    if ('__three__' in s && '__remaining__' in s) {
      return `IELTS ${fmtNumG(s.__three__)} in at least three components, ${fmtNumG(s.__remaining__)} in the remaining component`;
    }
    const vals = Object.values(s);
    if (!vals.length) return null;
    if (new Set(vals).size === 1) return `IELTS minimum ${fmtNumG(vals[0])} in each component`;
    return `IELTS component minimums: ${Object.entries(s).map(([k, v]) => `${k} ${fmtNumG(v)}`).join(', ')}`;
  };
  const rendered = sets.map(renderSet).filter((x): x is string => x !== null);
  return rendered.length ? rendered.join(' or ') : generic;
}

function expLanguageRules(profile: Profile, ep: ExpansionProgram, thresholds: ExpLangThresholds): RuleResult[] {
  const results: RuleResult[] = [];
  const evidence = ep.requirements.filter((r) => r.category === 'language').flatMap((r) => r.sourceIds);
  const ieltsScore = num(profile.ieltsOverall);
  const toeflScore = num(profile.toefl);
  const testDate = profile.testDate || undefined;
  // Round 8 (P5 display fix, mirroring backend _exp_expected): the
  // real numeric minimum(s) when stated ("IELTS overall 7.5"); the
  // generic label only when the programme states no IELTS/TOEFL
  // overall minimum — and then the rule is UNKNOWN below, never
  // NOT_MET (a NOT_MET here always has a threshold behind it).
  // Round 9 (R13): a requirement in another system (CEFR / HSK /
  // Duolingo / PTE) is named as such ("German C1 (CEFR)"), never
  // relabelled as an IELTS/TOEFL minimum; and the generic label is
  // honest ("No IELTS/TOEFL minimum published") instead of the
  // placeholder-like "... as stated on the official programme page".
  const expectedParts: string[] = [];
  if (thresholds.ieltsOveralls.length) {
    expectedParts.push(`IELTS overall ${fmtNumG(Math.min(...thresholds.ieltsOveralls))}`);
  }
  if (thresholds.toeflOveralls.length) {
    expectedParts.push(`TOEFL iBT ${fmtNumG(Math.min(...thresholds.toeflOveralls))}`);
  }
  expectedParts.push(...thresholds.otherLabels);
  const expected = expectedParts.length
    ? expectedParts.join(' or ')
    : 'No IELTS/TOEFL minimum published';
  let met = false;
  let assessableFailed = false;
  let relevantSupplied = false;
  if (ieltsScore !== null) {
    if (thresholds.ieltsOveralls.length) {
      relevantSupplied = true;
      if (thresholds.ieltsOveralls.some((t) => ieltsScore >= t)) met = true;
      else assessableFailed = true;
    }
  }
  if (toeflScore !== null && !met) {
    if (thresholds.toeflOveralls.length) {
      relevantSupplied = true;
      const verdicts = thresholds.toeflOveralls.map((t) => expToeflRoute(toeflScore, t, testDate));
      if (verdicts.includes('met')) met = true;
      else if (verdicts.includes('below')) assessableFailed = true;
    }
  }
  const observed = `ielts_overall: ${ieltsScore ?? 'None'}, toefl_overall: ${toeflScore ?? 'None'}`;
  // Round 9, R13: "other_requirements" carries the real non-IELTS/TOEFL
  // labels (CEFR / HSK / Duolingo / PTE) so the renderer can name them
  // instead of a generic placeholder (mirrors the backend threshold).
  const thresholdRaw = { ielts_overall: thresholds.ieltsOveralls.length ? thresholds.ieltsOveralls : null, toefl_overall: thresholds.toeflOveralls.length ? thresholds.toeflOveralls : null, other_requirements: thresholds.otherLabels.length ? thresholds.otherLabels : null };
  const observedRaw = { ielts_overall: ieltsScore, toefl_overall: toeflScore };
  if (met) {
    results.push(expRule('exp-language', 'MET', observed, expected, evidence, undefined, { observedRaw, thresholdRaw }));
  } else if (assessableFailed) {
    results.push(expRule('exp-language', 'NOT_MET', observed, expected, evidence, undefined, { observedRaw, thresholdRaw }));
  } else if (!relevantSupplied) {
    let reason: string;
    let reasonKey = 'missing-info';
    if (thresholds.otherLabels.length) {
      // Round 9, R13: name the real requirement (CEFR / HSK /
      // Duolingo / PTE) instead of claiming no IELTS/TOEFL score is
      // stated — e.g. the Swiss German C1 / French B2 requirements.
      reason = `This programme requires ${thresholds.otherLabels.join(', ')}, not an IELTS/TOEFL score; the profile has no evidence for that requirement, so it cannot be assessed from a test score.`;
      reasonKey = 'missing-info';
    } else if (!thresholds.ieltsOveralls.length && !thresholds.toeflOveralls.length && !thresholds.componentSets.length) {
      reason = 'This programme states a language requirement, but no IELTS/TOEFL score is stated on the official page, so it cannot be assessed from a test score.';
      reasonKey = 'no-threshold';
    } else if (toeflScore !== null && thresholds.toeflOveralls.length) {
      reason = 'TOEFL supplied but no valid test date. The Jan 2026 scale split cannot be applied, so TOEFL is UNKNOWN, never converted.';
      reasonKey = 'missing-test-date';
    } else if (ieltsScore === null && toeflScore === null) {
      reason = 'No language test supplied.';
    } else if (ieltsScore !== null) {
      reason = 'IELTS supplied, but this programme states no IELTS minimum (only TOEFL / Duolingo / other routes), so the supplied score is not evidence for any stated route.';
    } else if (toeflScore !== null) {
      reason = 'TOEFL supplied, but this programme states no TOEFL minimum, so the supplied score is not evidence for any stated route.';
    } else {
      reason = 'No IELTS/TOEFL score supplied that matches a stated route (Duolingo / PTE / HSK / CEFR routes cannot be assessed from this profile).';
    }
    results.push(expRule('exp-language', 'UNKNOWN', observed, expected, evidence, reason, { observedRaw, thresholdRaw, reasonKey }));
  } else {
    let reason = 'TOEFL supplied but no valid test date. The Jan 2026 scale split cannot be applied, so TOEFL is UNKNOWN, never converted.';
    let reasonKey = 'missing-test-date';
    if (toeflScore !== null && toeflScore <= 6) {
      reason = 'The supplied TOEFL score is 6 or below, so it cannot be placed on the pre/post-Jan-2026 scale against the stated iBT minimum; TOEFL is UNKNOWN, never converted.';
    }
    results.push(expRule('exp-language', 'UNKNOWN', observed, expected, evidence, reason, { observedRaw, thresholdRaw, reasonKey }));
  }
  // --- Components: IELTS components only. ---
  const sets = thresholds.componentSets;
  const expectedComp = expComponentExpected(sets);
  const comps = [num(profile.ieltsListening), num(profile.ieltsReading), num(profile.ieltsWriting), num(profile.ieltsSpeaking)];
  const compNames = ['listening', 'reading', 'writing', 'speaking'];
  if (!sets.length) {
    if (ieltsScore === null && toeflScore === null) {
      results.push(expRule('exp-language-components', 'UNKNOWN', 'Not provided', expectedComp, evidence, 'No language test supplied.'));
    } else if (thresholds.hasToeflSections) {
      results.push(expRule('exp-language-components', 'UNKNOWN', 'Not provided', expectedComp, evidence,
        'This programme states TOEFL section minimums only; the profile has no TOEFL component scores, so they cannot be assessed.'));
    } else {
      results.push(expRule('exp-language-components', 'NOT_APPLICABLE', 'No component minimum stated', expectedComp, evidence, undefined));
    }
    return results;
  }
  if (ieltsScore === null) {
    results.push(expRule('exp-language-components', 'UNKNOWN', 'Not provided', expectedComp, evidence,
      'TOEFL supplied; IELTS components do not apply. TOEFL is assessed under its own rule.'));
    return results;
  }
  const missing = compNames.filter((_, i) => comps[i] === null);
  const observedComp = `L ${profile.ieltsListening ?? '–'} / R ${profile.ieltsReading ?? '–'} / W ${profile.ieltsWriting ?? '–'} / S ${profile.ieltsSpeaking ?? '–'}`;
  const observedCompRaw = { listening: comps[0], reading: comps[1], writing: comps[2], speaking: comps[3] };
  if (missing.length) {
    results.push(expRule('exp-language-components', 'UNKNOWN', observedComp, expectedComp, evidence,
      `Missing component score(s): ${missing.join(', ')}.`, { observedRaw: observedCompRaw }));
    return results;
  }
  const setMet = (s: Record<string, number>): boolean => {
    if ('__three__' in s) {
      const above = compNames.filter((k) => (comps[compNames.indexOf(k)] as number) >= s.__three__).length;
      return above >= 3 && compNames.every((k) => (comps[compNames.indexOf(k)] as number) >= s.__remaining__);
    }
    return Object.entries(s).every(([k, v]) => (comps[compNames.indexOf(k)] as number) >= v);
  };
  if (sets.some(setMet)) {
    results.push(expRule('exp-language-components', 'MET', observedComp, expectedComp, evidence, undefined,
      { observedRaw: observedCompRaw, thresholdRaw: sets.length === 1 ? sets[0] : null }));
  } else {
    const low: Record<string, number | null> = {};
    compNames.forEach((k, i) => {
      if (sets.some((s) => !('__three__' in s) && k in s && (comps[i] as number) < s[k])) low[k] = comps[i];
    });
    results.push(expRule('exp-language-components', 'NOT_MET', observedComp, expectedComp, evidence,
      `Component(s) below the minimum: ${JSON.stringify(low)}.`, { observedRaw: observedCompRaw, thresholdRaw: sets.length === 1 ? sets[0] : null }));
  }
  return results;
}

/** Real structured academic threshold when one exists but is not an
 * A-level (IB total, GPA, ATAR, degree class) — display only; the
 * rule stays UNKNOWN because the evaluator never converts other
 * qualifications to A-levels. Round 9, R13: show the real number
 * instead of a fake "A-level threshold as stated..." label. */
function expOtherAcademicThreshold(ep: ExpansionProgram): string | null {
  for (const req of ep.requirements) {
    if (req.category !== 'academic') continue;
    const th = req.threshold;
    if (!th || typeof th !== 'object') continue;
    const ib = expNum(th.ib_total);
    if (ib !== null) return `IB total ${fmtNumG(ib)}`;
    const gpa = expNum(th.gpa);
    if (gpa !== null) return `GPA ${fmtNumG(gpa)}`;
    const atar = expNum(th.atar);
    if (atar !== null) return `ATAR ${fmtNumG(atar)}`;
    if (typeof th.degree_class === 'string' && th.degree_class.trim()) {
      return `Degree class: ${th.degree_class}`;
    }
  }
  return null;
}

/** English fallback observed string for the academic rule, from the
 * applicant's own curriculum branch (the localised renderer uses
 * observedRaw; this string is only the fallback). */
function expAcademicObservedText(profile: Profile): string {
  const raw = ugObservedRaw(profile);
  const cur = curriculumOf(profile);
  if (cur === 'cn_gaokao') {
    if (typeof raw.gaokao_score !== 'number') return 'Not provided';
    return `Gaokao ${raw.gaokao_score}/${typeof raw.gaokao_total === 'number' ? raw.gaokao_total : '–'}`;
  }
  if (cur === 'ib') {
    if (raw.total == null && raw.hl_maths == null && raw.hl_total == null) return 'Not provided';
    return `IB total ${raw.total == null ? '–' : raw.total}`;
  }
  if (cur === 'usa') {
    const parts: string[] = [];
    if (typeof raw.sat_total === 'number') parts.push(`SAT ${raw.sat_total}`);
    if (typeof raw.act_composite === 'number') parts.push(`ACT ${raw.act_composite}`);
    if (Array.isArray(raw.ap_grades) && raw.ap_grades.length) parts.push(`AP ${raw.ap_grades.join(', ')}`);
    return parts.length ? parts.join(' · ') : 'Not provided';
  }
  return profile.alevels || 'Not provided';
}

function expAcademicRule(profile: Profile, ep: ExpansionProgram, alevels: ExpAlevelReq[]): RuleResult {
  const evidence = ep.requirements.filter((r) => r.category === 'academic').flatMap((r) => r.sourceIds);
  // Round 8 (P5 display fix, mirroring backend _exp_expected): the
  // real A-level grade string when a threshold is stated ("A-level
  // A*AA"). Round 9 (R13): when no A-level threshold exists, show a
  // real structured threshold of another kind when one is recorded
  // ("IB total 39"), and otherwise an honest "No A-level threshold
  // published" — never the placeholder-like "A-level threshold as
  // stated on the official programme page". The rule is UNKNOWN in
  // both cases, never NOT_MET.
  const gradeLetter = (rank: number): string =>
    ({ 5: 'A*', 4: 'A', 3: 'B', 2: 'C', 1: 'D', 0: 'E' } as Record<number, string>)[rank] ?? '?';
  const otherThreshold = alevels.length ? null : expOtherAcademicThreshold(ep);
  const expected = alevels.length
    ? `A-level ${[...new Set(alevels.map((r) => r.minimum.map(gradeLetter).join('')))].join(' / ')}`
    : otherThreshold ?? 'No A-level threshold published';
  // Round 9, R10: the observed values carry the applicant's own
  // curriculum branch (Gaokao / IB / USA / A-level) so the card shows
  // the supplied score instead of "Not provided".
  const observedText = expAcademicObservedText(profile);
  const observedRaw = ugObservedRaw(profile);
  if (profile.track === 'taught_masters') {
    return expRule('exp-academic', 'UNKNOWN', 'Not provided', expected, evidence,
      'A-level thresholds apply to undergraduate entry; this is a taught-masters programme, so no A-level rule can be assessed here.');
  }
  if (!alevels.length) {
    return expRule('exp-academic', 'UNKNOWN', observedText, expected, evidence,
      'No A-level threshold is stated for this programme (the academic requirement uses GPA / IB / degree-class or free-text criteria), so academic eligibility cannot be decided from grades alone.',
      { reasonKey: 'no-threshold', observedRaw });
  }
  const cur = curriculumOf(profile);
  if (cur !== 'uk_alevel' && cur !== 'sg_alevel') {
    return expRule('exp-academic', 'UNKNOWN', observedText, expected, evidence,
      "An A-level threshold is stated, but this applicant's curriculum is not A-level; A-level thresholds are only assessed for UK / Singapore A-level applicants, and other scores are never converted to A-levels.",
      { reasonKey: 'no-equivalence', observedRaw });
  }
  const top = expAlevelTop3(profile.alevels);
  if (top === null) {
    return expRule('exp-academic', 'UNKNOWN', 'Not provided', expected, evidence,
      'A-level grades not supplied (three grades are needed).', { observedRaw });
  }
  const mathsRank = profile.mathsGrade ? (EXP_GRADE_RANK[profile.mathsGrade.trim().toUpperCase()] ?? null) : null;
  for (const req of alevels) {
    if (!expTripleMeets(top, req.minimum)) continue;
    if (req.kind === 'grades' && req.mathsRank !== null) {
      if (mathsRank === null) {
        return expRule('exp-academic', 'UNKNOWN', profile.alevels || 'Not provided', expected, evidence,
          'A-level grades meet the stated grades, but the required Mathematics grade cannot be checked (no A-level Maths grade supplied).', { observedRaw });
      }
      if (mathsRank < req.mathsRank) continue;
    }
    return expRule('exp-academic', 'MET', profile.alevels || 'Not provided', expected, evidence,
      undefined, { observedRaw, thresholdRaw: { a_level: req.minimum } });
  }
  return expRule('exp-academic', 'NOT_MET', profile.alevels || 'Not provided', expected, evidence,
    undefined, { observedRaw });
}

/** Evaluate one promoted expansion programme offline (mirror of the
 * backend generic evaluator). Only called for matchable programmes. */
export function evaluateExpansionLocal(profile: Profile, ep: ExpansionProgram): RuleResult[] {
  const results: RuleResult[] = [];
  results.push(expFeeRule(profile, ep));
  const thresholds = expLanguageThresholds(ep);
  if (thresholds.hasAnyLanguageReq) {
    results.push(...expLanguageRules(profile, ep, thresholds));
  }
  const alevels = expAlevelRequirements(ep);
  const hasAcademicReq = ep.requirements.some((r) => r.category === 'academic');
  if (hasAcademicReq) {
    results.push(expAcademicRule(profile, ep, alevels));
  }
  // Round 8 placeholder rule — same as the backend generic evaluator
  // (backend/domain/expansion_eval.py, _placeholder_guard): a
  // requirement with no parseable numeric threshold ("... as stated on
  // the official programme page") can never yield NOT_MET; it yields
  // UNKNOWN. A NOT_MET here without a numeric threshold behind it is
  // downgraded, so a placeholder is never counted as an obstacle.
  return results.map((r) => {
    if (r.status !== 'NOT_MET') return r;
    const hasThreshold = r.ruleId === 'exp-fee' ? expNum(ep.fees.amount) !== null
      : r.ruleId === 'exp-language' ? thresholds.ieltsOveralls.length > 0 || thresholds.toeflOveralls.length > 0
      : r.ruleId === 'exp-language-components' ? thresholds.componentSets.length > 0
      : r.ruleId === 'exp-academic' ? alevels.length > 0 : true;
    if (hasThreshold) return r;
    return {
      ...r, status: 'UNKNOWN',
      unknownReason: 'No parseable numeric threshold is stated for this requirement, so it cannot be judged failed.',
      reasonCode: 'MISSING_OR_UNVERIFIED', reasonKey: 'no-threshold',
    };
  });
}

/** Convert one expansion mirror programme to the frontend Program shape. */
export function expansionToProgram(ep: ExpansionProgram): Program {
  const feeItems: Program['feeItems'] = [];
  if (typeof ep.fees.amount === 'number') {
    const period = ep.fees.period === 'per_year' ? 'per year' : ep.fees.period === 'total' ? 'total' : ep.fees.period === 'per_credit' ? 'per credit' : ep.fees.period || '';
    feeItems.push({ label: 'Tuition fee', amount: ep.fees.amount, currency: ep.fees.currency || '', period });
  }
  return {
    id: ep.id,
    institution: ep.institution,
    institutionId: ep.institutionId,
    officialName: ep.officialName,
    nameLocalized: ep.nameLocalized,
    country: ep.country,
    city: ep.city || undefined,
    degreeLevel: ep.degreeLevel,
    field: ep.field,
    subject: ep.field,
    intakeYear: ep.intakeYear || 0,
    intakeLabel: ep.start || (ep.intakeYear ? String(ep.intakeYear) : ''),
    duration: ep.duration || '',
    feeItems,
    status: 'active',
    datasetVersion: DATA_VERSION,
    sources: ep.sources.map((s) => ({ id: s.id, url: s.url, label: s.title || s.id, excerpt: '', verifiedDate: (s.retrievedAt || '').slice(0, 10) })),
    matchable: ep.matchable,
    // Round 9 (R5): verified language of instruction, carried verbatim
    // from the expansion mirror — null/absent for programmes without one.
    languageOfInstruction: ep.languageOfInstruction ?? null,
  };
}

const EXPANSION_INDEX = new Map<string, ExpansionProgram>(
  EXPANSION_PROGRAMS.map((p) => [p.id, p]),
);

let _allPrograms: Program[] | null = null;
/** All programmes: the 8 v2 programmes plus every expansion programme
 * (matchable and display-only), converted to the Program shape. */
export function allPrograms(): Program[] {
  if (!_allPrograms) {
    _allPrograms = [...PROGRAMS, ...EXPANSION_PROGRAMS.map(expansionToProgram)];
  }
  return _allPrograms;
}

const _programIndex = new Map<string, Program>();
/** Old / alternate programme URL slugs that still resolve, instead of
 * erroring. Round 13: /programs/eth-zurich-bsc-computer-science
 * appears NOWHERE in the repo (no in-repo link, case, review or
 * destination uses it — it is a plausible guessed/old slug for the
 * ETH CS BSc), so it is aliased here rather than chased to a source
 * that does not exist. Add a line per slug; the target must be a real
 * programme id. */
export const PROGRAM_ID_ALIASES: Record<string, string> = {
  'eth-zurich-bsc-computer-science': 'eth-cs-bsc-2027',
};

/** A URL slug to its canonical programme id (the slug itself when it
 * is already canonical). */
export function resolveProgramId(id: string): string {
  return PROGRAM_ID_ALIASES[id] ?? id;
}

/** Find one programme by id (v2 or expansion). Alias slugs resolve
 * to their canonical programme, so an old link renders the programme
 * instead of the error page. */
export function findProgram(id: string): Program | undefined {
  if (!_programIndex.size) {
    for (const p of allPrograms()) _programIndex.set(p.id, p);
  }
  return _programIndex.get(resolveProgramId(id));
}

/** Merge a live programme list with the local mirror: live entries win
 * on id, and every programme the local mirror knows (all 881 expansion
 * programmes) is present even when the live list is only the v2 page.
 * The local mirror is generated from the same source as the backend
 * data, so the merged list is complete offline too. */
export function mergePrograms(live: Program[]): Program[] {
  const seen = new Set(live.map((p) => p.id));
  return [...live, ...allPrograms().filter((p) => !seen.has(p.id))];
}

/** Climate signal for one offline result (round 6): the user's stated
 * climate preference against the programme's city. Null = no signal. */
export function offlinePreferenceFit(profile: Profile, p: Program): 'fit' | 'neutral' | 'conflict' | null {
  const pref = normaliseClimatePref(profile.prefClimate);
  if (!pref) return null;
  return climateFit(pref, cityClimate(p.city));
}

export function evaluateLocal(profile: Profile, programIds: string[]): MatchResponse {
  const results: MatchResult[] = programIds.map((id) => {
    const p = findProgram(id);
    if (!p) {
      return { programId: id, eligibilitySummary: 'UNKNOWN', ruleResults: [], trackMismatch: false };
    }
    if (profile.track && profile.track !== p.degreeLevel) {
      // The backend attaches the climate signal to track-mismatch
      // results too, so the offline mirror does the same.
      const mismatch: MatchResult = { programId: id, eligibilitySummary: 'TRACK_MISMATCH', ruleResults: [], trackMismatch: true };
      const fit = offlinePreferenceFit(profile, p);
      if (fit) mismatch.preferenceFit = fit;
      return mismatch;
    }
    // Round 6: expansion programmes evaluate through the generic
    // offline evaluator; display-only ones are not evaluable (the
    // backend 404s them), so they stay UNKNOWN with no rules.
    const ep = EXPANSION_INDEX.get(id);
    if (ep) {
      if (!ep.matchable) {
        return { programId: id, eligibilitySummary: 'UNKNOWN', ruleResults: [], trackMismatch: false };
      }
      const rules = evaluateExpansionLocal(profile, ep);
      const summary = rules.some((r) => r.status === 'NOT_MET') ? 'NOT_MET' : rules.some((r) => r.status === 'UNKNOWN') ? 'PARTIAL_UNKNOWN' : 'MET';
      const result: MatchResult = { programId: id, eligibilitySummary: summary, ruleResults: rules };
      const fit = offlinePreferenceFit(profile, p);
      if (fit) result.preferenceFit = fit;
      return result;
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
      // TARA is required for the 2027/28 admission with no stated threshold, so the
      // offline evaluator can never confirm it — same as the backend.
      rules.push({
        ruleId: 'ucl-tara', status: 'UNKNOWN',
        observed: 'TARA required for 2027/28 admission; no threshold stated',
        expected: 'TARA required (no score threshold stated)', evidenceIds: ['ucl-cs-entry'],
        reasonCode: 'MISSING_SCORE',
        unknownReason: 'TARA is required but no score threshold is stated on the page',
        observedRaw: null,
        reasonKey: 'no-threshold',
      });
      const b = num(profile.budget);
      rules.push({
        ruleId: 'ucl-fee', status: b === null ? 'UNKNOWN' : b >= 48600 ? 'MET' : 'NOT_MET',
        observed: b === null ? 'Not provided' : `Budget ${profile.budgetCurrency || 'GBP'} ${b}/year`,
        expected: 'GBP 48,600/year', evidenceIds: ['ucl-cs-fees'],
        reasonCode: b === null ? 'MISSING_BUDGET' : b >= 48600 ? 'BUDGET_COVERS' : 'BUDGET_BELOW',
        unknownReason: b === null ? 'Budget not provided' : undefined,
        observedRaw: b,
        thresholdRaw: { gbp_per_year: 48600 },
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
        observed: b === null ? 'Not provided' : `Budget ${profile.budgetCurrency || 'GBP'} ${b} total`,
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
    // Round 10, R1: the fee is compared in the budget's own currency.
    // The old version compared raw numbers across currencies, so a GBP
    // 50,000 budget against an SGD 39,700 fee read as MET by accident
    // (50,000 >= 39,700 in any currency) — and a GBP budget against an
    // SGD fee could never be judged properly at all. Cross-currency
    // comparison uses the dated FX reference table (lib/fx), exactly
    // like the backend _fee_for_residency and the expansion mirror; a
    // currency with no reference rate is UNKNOWN, never a mismatch.
    const feeStatus = (amount: number, currency?: string): RuleResult['status'] => {
      const b = num(profile.budget);
      if (b === null) return 'UNKNOWN';
      const budgetCurrency = profile.budgetCurrency || 'GBP';
      if (!currency || currency === budgetCurrency) return b >= amount ? 'MET' : 'NOT_MET';
      const converted = convertCurrency(amount, currency, budgetCurrency);
      if (converted === null) return 'UNKNOWN';
      return b >= converted ? 'MET' : 'NOT_MET';
    };
    // Approximate converted figure for a fee rule's expected line and
    // thresholdRaw, in the expansion mirror's format — the same figure
    // the results pages show. Null when same-currency or unconvertible.
    const feeApprox = (amount: number, currency: string): { amount: number; currency: string } | null => {
      const budgetCurrency = profile.budgetCurrency || 'GBP';
      if (currency === budgetCurrency) return null;
      const converted = convertCurrency(amount, currency, budgetCurrency);
      return converted === null ? null : { amount: Math.round(converted), currency: budgetCurrency };
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
      pushRule('imp-beng-fee', feeStatus(feeAmt, 'GBP'), profile.budget == null ? 'Not provided' : `Budget ${profile.budgetCurrency || 'GBP'} ${profile.budget}`, `GBP ${feeAmt.toLocaleString()}/year`, ['imperial-beng-fees'], undefined,
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
      pushRule('imp-msc-fee', feeStatus(feeAmt, 'GBP'), profile.budget == null ? 'Not provided' : `Budget ${profile.budgetCurrency || 'GBP'} ${profile.budget}`, `GBP ${feeAmt.toLocaleString()}/year`, ['imperial-msc-fees'], undefined,
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
      pushRule('ucl-msc-fee', feeStatus(feeAmt, 'GBP'), profile.budget == null ? 'Not provided' : `Budget ${profile.budgetCurrency || 'GBP'} ${profile.budget}`, `GBP ${feeAmt.toLocaleString()}/year`, ['ucl-msc-fees'], undefined,
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
      // Round 10, R1: generic 'overseas' is an international applicant
      // with no grant claimed — the unsubsidised band (same mapping as
      // the backend). Without it the lookup missed and the fee was
      // UNKNOWN while the live backend called it a budget mismatch.
      const sgResidency = profile.residency === 'overseas' ? 'sg_intl_nogrant' : profile.residency;
      const amt = sgResidency ? band[sgResidency] ?? null : null;
      const feeSt = amt === null ? 'UNKNOWN' : feeStatus(amt, 'SGD');
      const approx = amt === null ? null : feeApprox(amt, 'SGD');
      const nusExpected = amt === null ? 'AY2026/27 rates by residency band'
        : `SGD ${amt.toLocaleString()}/year${approx ? ` (approx. ${approx.currency} ${approx.amount.toLocaleString('en-US')}, rates ${FX_AS_OF})` : ''}`;
      pushRule('nus-bcomp-fee', feeSt, profile.budget == null ? 'Not provided' : `Budget ${profile.budgetCurrency || 'GBP'} ${profile.budget}/year`, nusExpected, ['nus-bcomp-fees'], amt === null ? 'Residency / tuition-grant status not supplied, so the fee cannot be decided' : undefined,
        { observedRaw: num(profile.budget), thresholdRaw: amt === null ? undefined : (approx ? { amount: amt, approx_converted: { ...approx, as_of: FX_AS_OF } } : { amount: amt }), reasonKey: profile.budget == null ? 'missing-info' : amt === null ? 'fee-residency-unknown' : feeSt === 'UNKNOWN' ? 'fx-cannot-convert' : undefined });
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
      // Round 10, R1: same 'overseas' mapping as NUS. Here the band is
      // null because the table does not label CS lab/non-lab, so the fee
      // stays UNKNOWN with the lab-band reason — never a mismatch, and
      // (round 11, F4) never the 'residency not provided' wording:
      // reasonKey is 'fee-band-unlabelled' for the unlabelled band,
      // 'fee-residency-unknown' only when residency itself is missing.
      const sgResidency = profile.residency === 'overseas' ? 'sg_intl_nogrant' : profile.residency;
      const amt = sgResidency ? band[sgResidency] ?? null : null;
      const feeSt = amt === null ? 'UNKNOWN' : feeStatus(amt, 'SGD');
      const approx = amt === null ? null : feeApprox(amt, 'SGD');
      const ntuExpected = amt === null ? 'AY2026/27 rates by residency band'
        : `SGD ${amt.toLocaleString()}/year${approx ? ` (approx. ${approx.currency} ${approx.amount.toLocaleString('en-US')}, rates ${FX_AS_OF})` : ''}`;
      pushRule('ntu-bcomp-fee', feeSt, profile.budget == null ? 'Not provided' : `Budget ${profile.budgetCurrency || 'GBP'} ${profile.budget}/year`, ntuExpected, ['ntu-bcomp-fees'], amt === null ? (sgResidency === 'sg_intl_nogrant' ? 'The non-subsidised band is not labelled for CS (lab-based S$40,600 vs non-lab-based S$36,350), so the fee cannot be decided' : 'Residency / tuition-grant status not supplied, so the fee cannot be decided') : undefined,
        { observedRaw: num(profile.budget), thresholdRaw: amt === null ? undefined : (approx ? { amount: amt, approx_converted: { ...approx, as_of: FX_AS_OF } } : { amount: amt }), reasonKey: profile.budget == null ? 'missing-info' : amt === null ? (sgResidency === 'sg_intl_nogrant' ? 'fee-band-unlabelled' : 'fee-residency-unknown') : feeSt === 'UNKNOWN' ? 'fx-cannot-convert' : undefined });
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
      // Round 10, R1: SGD fee compared in the budget's currency (the
      // backend _fee_for_residency does the same); an unconvertible
      // budget currency is UNKNOWN with reasonKey fx-cannot-convert,
      // never a mismatch.
      const msaiFeeSt = feeStatus(65748.8, 'SGD');
      pushRule('ntu-msai-fee', msaiFeeSt, profile.budget == null ? 'Not provided' : `Budget ${profile.budgetCurrency || 'GBP'} ${profile.budget} total`, 'SGD 65,748.80 total incl. 9% GST', ['ntu-msai-fees'], undefined,
        { observedRaw: num(profile.budget), thresholdRaw: { amount: 65748.8 }, reasonKey: profile.budget == null ? 'missing-info' : msaiFeeSt === 'UNKNOWN' ? 'fx-cannot-convert' : undefined });
    }
    const summary = rules.some((r) => r.status === 'NOT_MET') ? 'NOT_MET' : rules.some((r) => r.status === 'UNKNOWN') ? 'PARTIAL_UNKNOWN' : 'MET';
    const result: MatchResult = { programId: id, eligibilitySummary: summary, ruleResults: rules };
    const fit = offlinePreferenceFit(profile, p);
    if (fit) result.preferenceFit = fit;
    return result;
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

// --- Cold-start resilience (round 7, Fix A) --------------------------------
// The backend runs on a free Render instance that sleeps after 15 min
// idle; the first request takes ~50s+ to wake it, and a proxy or the
// network may give up before it answers. A plain fetch would then
// declare the backend offline even though it is only waking. The
// model chats (pet, PrefChat, RecChat) all call the backend through
// this one helper, so all three get the same behaviour:
// - one attempt gets up to `attemptTimeoutMs` (default 25s);
// - on a network error, an abort, or a 502/503/504 (the waking/proxy
//   signatures), retry after a short pause until `budgetMs`
//   (default 90s) is spent; `onRetry` fires before each retry so the
//   UI can show a "waking the backend" state instead of offline;
// - 4xx (including a 404 for an endpoint that does not exist yet) and
//   429 fail immediately — retrying cannot help, and a missing
//   endpoint must fall back to the guided path at once.
// Only after the budget is exhausted does the caller declare offline.
// Never presents template content as an AI answer — that rule lives in
// the callers (isModelReply / isModelPrefReply).

export interface FetchPatientOptions {
  /** Total retry budget in ms (default 90_000). */
  budgetMs?: number;
  /** Per-attempt timeout in ms (default 25_000). */
  attemptTimeoutMs?: number;
  /** Called before each retry (attempt number, 1-based). */
  onRetry?: (attempt: number) => void;
  /** Round 15, F2: when false, an attempt that ran out its whole
   * per-attempt timeout (the server accepted the request and is
   * chewing on it) is final — it is NOT retried. Retrying a slow
   * chat turn re-issues the whole model call server-side (the
   * abandoned attempt's thread keeps running) and stacks a 40 s
   * abort + a second 40 s attempt into ~90 s of silence before the
   * honest fallback, which is what the 2026-11-27 02:30 re-run
   * showed (first pref-chat reply sent 02:30, answered ~02:32,
   * while the backend caps one turn at ~15 s). A fast failure
   * (connection refused / 502 / 503 / 504 — the backend waking)
   * still retries while budget remains: that failure mode is cheap
   * and retrying it is exactly the cold-start wake. Default true
   * (existing behaviour for match / programs / health probes). */
  retryOnTimeout?: boolean;
  /** P0 (re-test task 6): an outer AbortSignal (e.g. a component
   * unmount). When it fires the in-flight attempt is aborted at once
   * and the retry loop stops instead of retrying for up to 90s after
   * the page that started it is gone — the old behaviour left a
   * sleeping-backend retry loop running behind every navigation, so
   * the browser kept 90s of /api traffic alive after the user had
   * already left the page. An outer abort is final, never retried. */
  signal?: AbortSignal;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function fetchJsonPatient<T>(
  path: string,
  init?: RequestInit,
  options?: FetchPatientOptions,
): Promise<T> {
  const budgetMs = options?.budgetMs ?? 90_000;
  const attemptTimeoutMs = options?.attemptTimeoutMs ?? 25_000;
  const started = Date.now();
  let attempt = 0;
  for (;;) {
    // P0: an outer abort (unmount) ends the loop at once — never
    // start another attempt after the caller has gone away.
    if (options?.signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError');
    }
    attempt += 1;
    const controller = new AbortController();
    // P0: wire the outer signal to this attempt's controller, so an
    // unmount aborts the request in flight instead of letting the
    // per-attempt timer run it out.
    const onOuterAbort = () => controller.abort();
    if (options?.signal) options.signal.addEventListener('abort', onOuterAbort);
    // Round 8: an attempt must never run past the remaining budget —
    // the old code let a 25s attempt start at 79s and fail at ~104s,
    // so "offline" was declared ~15s after the promised ~90s.
    const remaining = budgetMs - (Date.now() - started);
    const attemptTimeout = Math.max(1000, Math.min(attemptTimeoutMs, remaining));
    // Round 15, F2: remember whether THIS attempt was killed by its
    // own timer (slow abort) as opposed to failing fast — only a
    // slow abort is final under retryOnTimeout=false.
    let timerFired = false;
    const timer = setTimeout(() => { timerFired = true; controller.abort(); }, attemptTimeout);
    try {
      const res = await fetch(path, {
        ...init,
        headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
        signal: controller.signal,
      });
      if (!res.ok) {
        const retryable = res.status === 502 || res.status === 503 || res.status === 504;
        if (retryable && Date.now() - started + 2000 < budgetMs) {
          options?.onRetry?.(attempt);
          await sleep(2000);
          continue;
        }
        const body = await res.json().catch(() => ({}));
        const err = new Error(`HTTP ${res.status}`) as Error & { status?: number; body?: unknown };
        err.status = res.status; err.body = body;
        throw err;
      }
      return res.json() as Promise<T>;
    } catch (err) {
      const status = (err as Error & { status?: number }).status;
      // An HTTP error thrown above (non-retryable status, or a
      // retryable one past budget) is final — do not re-enter the
      // retry path for it.
      if (status !== undefined) throw err;
      // P0: an outer abort is final — never retry after unmount.
      if (options?.signal?.aborted) throw err;
      // Round 15, F2: a slow abort (the per-attempt timer fired) is
      // final when retryOnTimeout is false — the server is up but
      // slow, and re-issuing the turn only stacks another full
      // attempt onto the wait. A fast failure still retries below.
      if (timerFired && options?.retryOnTimeout === false) throw err;
      // Network error / abort: retry while budget remains.
      if (Date.now() - started + 2000 < budgetMs) {
        options?.onRetry?.(attempt);
        await sleep(2000);
        continue;
      }
      throw err;
    } finally {
      clearTimeout(timer);
      if (options?.signal) options.signal.removeEventListener('abort', onOuterAbort);
    }
  }
}

/** One chat turn through the patient fetch, bounded to ~20 s total
 * (Round 15, F2). The backend already bounds one turn at ~15 s (one
 * model call, `timeout_s=15.0` in ai/pref_chat.py and ai/chat.py,
 * then the template) plus retrieval, so a chat turn that has not
 * answered in 18 s is not going to be saved by re-issuing it — the
 * old 40 s attempt / 90 s budget stacked a 40 s abort + a second
 * 40 s attempt into ~90 s of silence (browser re-test task 9,
 * 2026-11-27 02:30–02:32: first pref-chat reply took 1–2 min).
 * One attempt gets 18 s (headroom over the backend's 15 s + local
 * retrieval); a fast failure (backend waking: connection refused /
 * 502 / 503 / 504) still retries inside the 20 s total budget, and
 * a slow abort is final at once (retryOnTimeout=false), so the
 * caller falls back honestly — guided template / offline line —
 * within ~20 s. A backend that is merely waking is re-tried by the
 * caller's retry action (retryModelChat / pet footer retry) once it
 * is up, instead of the turn itself paying the ~50 s wake.
 * Not for match / programs / health probes: those keep the 90 s
 * patient budget (a wake there is worth waiting for). */
export async function fetchJsonChat<T>(
  path: string,
  init?: RequestInit,
  options?: Pick<FetchPatientOptions, 'onRetry' | 'signal' | 'attemptTimeoutMs' | 'budgetMs'>,
): Promise<T> {
  return fetchJsonPatient<T>(path, init, {
    budgetMs: 20_000,
    attemptTimeoutMs: 18_000,
    retryOnTimeout: false,
    ...options,
  });
}

/** Model availability, from the backend's LIVE /ai/status probe
 * (Round 14). The probe exercises the gateway and is cached 60 s
 * server-side; this client-side cache (same 60 s) means one status
 * read per minute per browser tab no matter how many model-backed
 * calls the page makes, and concurrent callers share one in-flight
 * read instead of each probing.
 *
 * - 'available': the gateway answered the probe — attempt the model.
 * - 'unavailable': the gateway did not answer — skip the model
 *   attempt and go template-only at once (simulateMulti /
 *   createPlan), instead of spending 15 s proving it again.
 * - 'unknown': the status read itself failed (backend asleep on the
 *   free tier, network error, or the read timed out) — that says
 *   nothing about the model, so the caller attempts it once through
 *   the normal patient fetch, which wakes a sleeping backend. A
 *   status-read failure is never treated as "model down".
 * The read gets a 12 s budget: the probe costs ~3 s when the gateway
 * is unreachable, up to ~10 s when it answers only via the 1-token
 * chat fallback. */
export type ModelAvailability = 'available' | 'unavailable' | 'unknown';

const AI_STATUS_TTL_MS = 60_000;
const AI_STATUS_TIMEOUT_MS = 12_000;
let _aiStatusCache: { at: number; value: ModelAvailability } | null = null;
let _aiStatusInFlight: Promise<ModelAvailability> | null = null;

export async function modelAvailability(): Promise<ModelAvailability> {
  if (_aiStatusCache && Date.now() - _aiStatusCache.at < AI_STATUS_TTL_MS) {
    return _aiStatusCache.value;
  }
  if (_aiStatusInFlight) return _aiStatusInFlight;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), AI_STATUS_TIMEOUT_MS);
  _aiStatusInFlight = fetch('/api/ai/status', { signal: controller.signal })
    .then(async (res) => {
      if (!res.ok) return 'unknown' as ModelAvailability;
      const data = await res.json().catch(() => ({})) as { ai_status?: string };
      return (data.ai_status === 'available' ? 'available' : 'unavailable') as ModelAvailability;
    })
    .catch(() => 'unknown' as ModelAvailability)
    .finally(() => { clearTimeout(timer); });
  try {
    const value = await _aiStatusInFlight;
    _aiStatusCache = { at: Date.now(), value };
    return value;
  } finally {
    _aiStatusInFlight = null;
  }
}

/** Test/manual hook: drop the cached status so the next call probes. */
export function resetModelAvailabilityCache(): void {
  _aiStatusCache = null;
  _aiStatusInFlight = null;
}

/** Options for matchProfile: onRetry fires before each patient retry,
 * so the caller can show a "waking the backend" state instead of an
 * offline claim while the free Render instance wakes. */
export interface MatchOptions {
  onRetry?: (attempt: number) => void;
}

/** Live match first, offline mirror only after the patient budget is
 * spent. The old plain fetch failed fast while the backend was only
 * waking, so the results page declared offline while the backend was
 * up and the chat worked. */
export async function matchProfile(profile: Profile, opts?: MatchOptions): Promise<MatchResponse> {
  const programIds = profile.targetProgramIds.length ? profile.targetProgramIds
    : allPrograms().filter((p) => p.degreeLevel === profile.track && p.matchable !== false).map((p) => p.id);
  try {
    const live = await fetchJsonPatient<MatchResponse>('/api/match', {
      method: 'POST',
      body: JSON.stringify({ profile, program_ids: programIds, data_version: DATA_VERSION }),
    }, { onRetry: opts?.onRetry });
    return { ...live, live: true };
  } catch {
    return evaluateLocal(profile, programIds);
  }
}

export async function fetchPrograms(opts?: { limit?: number; cursor?: string; onRetry?: (attempt: number) => void; signal?: AbortSignal }): Promise<{ programs: Program[]; live: boolean; nextCursor?: string }> {
  try {
    const params = new URLSearchParams();
    if (opts?.limit) params.set('limit', String(opts.limit));
    if (opts?.cursor) params.set('cursor', opts.cursor);
    const qs = params.toString();
    // Round 8: patient fetch — a plain fetch failed fast while the
    // free backend was only waking, so the homepage and results page
    // claimed "live backend not connected" while it was up.
    const data = await fetchJsonPatient<{ items?: unknown[]; programs?: unknown[]; data_version?: string; next_cursor?: string | null }>(`/api/programs${qs ? `?${qs}` : ''}`, undefined, { onRetry: opts?.onRetry, signal: opts?.signal });
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
  return { program: findProgram(id), live: false };
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
  const local = findProgram(id);
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
      nameLocalized: (r.nameLocalized as Record<string, string> | undefined) ?? local?.nameLocalized,
      country: str(r.country) || local?.country || '',
      city: str(r.city) || local?.city,
      degreeLevel: (r.degreeLevel === 'undergraduate' || r.degreeLevel === 'taught_masters' || r.degreeLevel === 'foundation' || r.degreeLevel === 'joint_honours' ? r.degreeLevel : local?.degreeLevel) ?? 'undergraduate',
      field: str(r.field) || local?.field,
      subject: str(r.subject) || local?.subject || '',
      intakeYear: num(r.intakeYear) ?? local?.intakeYear ?? 0,
      intakeLabel: str(r.intakeLabel) || local?.intakeLabel || '',
      duration: str(r.duration) || local?.duration || '',
      feeItems: feeItems.length ? feeItems : local?.feeItems ?? [],
      ucasCode: str(r.ucasCode) || local?.ucasCode,
      status: str(r.status) || 'active',
      datasetVersion: str(r.datasetVersion) || dataVersion || local?.datasetVersion || DATA_VERSION,
      sources,
      matchable: typeof r.matchable === 'boolean' ? r.matchable : local?.matchable,
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
  if (total !== undefined && overseas === undefined) feeItems.push({ label: period === 'total' ? 'Total tuition incl. GST' : 'Tuition fee', amount: total, currency, period: period || 'total' });
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
    institutionId: str(r.institution_id) || local?.institutionId || id.split('-')[0],
    officialName: str(r.official_name) || local?.officialName || id,
    nameLocalized: (r.name_localized as Record<string, string> | undefined) ?? local?.nameLocalized,
    country: str(r.country) || local?.country || '',
    city: str(r.city) || local?.city,
    degreeLevel: (r.degree_level === 'undergraduate' || r.degree_level === 'taught_masters' || r.degree_level === 'foundation' || r.degree_level === 'joint_honours' ? r.degree_level : local?.degreeLevel) ?? 'undergraduate',
    field: str(r.field) || local?.field,
    subject: typeof r.subject === 'string' ? r.subject : str(r.field) || local?.subject || '',
    intakeYear,
    intakeLabel,
    duration: str(r.duration) || local?.duration || '',
    feeItems: feeItems.length ? feeItems : local?.feeItems ?? [],
    ucasCode: str(r.ucas_code) || local?.ucasCode,
    status: 'active',
    datasetVersion: dataVersion || local?.datasetVersion || DATA_VERSION,
    sources: normalizeSources(r.sources, local),
    matchable: typeof r.matchable === 'boolean' ? r.matchable : local?.matchable,
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
  const programIds = profile.targetProgramIds.length ? profile.targetProgramIds
    : allPrograms().filter((p) => p.degreeLevel === profile.track && p.matchable !== false).map((p) => p.id);
  try {
    // Round 8: patient fetch, same as matchProfile — a waking backend
    // must not silently drop the what-if scenario to the offline mirror.
    const live = await fetchJsonPatient<{ baseline: MatchResponse; scenario: MatchResponse; delta: unknown }>('/api/simulate', {
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
  // Round 8: a stalled backend must never block the rankings page — the
  // page renders instantly from the local mirror and this call is only a
  // background refresh, so the whole live attempt gets one 30s budget
  // (a sleeping free-tier backend takes ~50s+ to wake) and then falls
  // back to the mirror with live: false.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);
  try {
    const signal = controller.signal;
    const prov = await fetchJson<{ providers: RankingProvider[] }>('/api/rankings/providers', { signal });
    const providers = Array.isArray(prov.providers) && prov.providers.length ? prov.providers : RANKING_PROVIDERS;
    // The backend caps limit at 20, so page through the cursor until the
    // list ends (300 entries = 15 pages). The loop is bounded so a
    // misbehaving API cannot spin forever.
    const entries: RankingEntry[] = [];
    let cursor: string | undefined;
    for (let page = 0; page < 50; page++) {
      const qs = new URLSearchParams({ limit: '20', ...(cursor ? { cursor } : {}) }).toString();
      const chunk = await fetchJson<{ items: RankingEntry[]; next_cursor?: string | null }>(`/api/rankings?${qs}`, { signal });
      entries.push(...(chunk.items ?? []));
      cursor = chunk.next_cursor ?? undefined;
      if (!cursor) break;
    }
    const list = entries.length ? entries : RANKING_ENTRIES;
    return { providers, institutions: RANKING_INSTITUTIONS, entries: list, live: true };
  } catch {
    return { providers: RANKING_PROVIDERS, institutions: RANKING_INSTITUTIONS, entries: RANKING_ENTRIES, live: false };
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchInstitutionRankings(institutionId: string): Promise<{ institution: RankingInstitution | undefined; entries: RankingEntry[]; live: boolean }> {
  // Round 8: same bounded-attempt rule as fetchRankings — the
  // institution page renders from the local mirror while this refreshes.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20_000);
  try {
    const data = await fetchJson<{ institution: RankingInstitution; rankings: RankingEntry[] }>(`/api/institutions/${encodeURIComponent(institutionId)}/rankings`, { signal: controller.signal });
    return { institution: data.institution, entries: data.rankings, live: true };
  } catch {
    return {
      institution: RANKING_INSTITUTIONS.find((i) => i.id === institutionId),
      entries: RANKING_ENTRIES.filter((e) => e.institution_id === institutionId),
      live: false,
    };
  } finally {
    clearTimeout(timer);
  }
}
