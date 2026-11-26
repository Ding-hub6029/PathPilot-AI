import { RuleResult } from './types';

/**
 * Localized rendering of rule results (fix 2026-11-25).
 *
 * The backend returns English `expected` / `observed` strings plus
 * structured `observedRaw` / `thresholdRaw` values and a `reasonKey`
 * for UNKNOWN rules. Everything on screen is rendered from the
 * structured values through the locale files — the English strings are
 * only a fallback for rule ids with no catalogue entry. Official-source
 * excerpts are NOT translated here; they stay in their original language
 * and are labelled as such by the EvidenceDrawer.
 */

export interface Fmt {
  t: (key: string) => string;
  tf: (key: string, vars?: Record<string, string | number>) => string;
  locale: string;
  /** The applicant's own budget currency (profile.budgetCurrency).
   * A budget is NEVER rendered under the fee's currency: GBP 50,000
   * was shown as "SGD 50,000" for NUS/NTU because the fee sentence
   * and the observed line both labelled the budget with the fee
   * currency (round 8). */
  budgetCurrency?: string;
}

const fmtNum = (n: number | string, locale: string): string =>
  Number(n).toLocaleString(locale);

const dash = '–';

/** Rule ids per programme, in display order — the recorded minimum
 * requirements shown on a programme detail page before any check exists.
 * Conditional TOEFL rules are listed only where the main language rule
 * is IELTS-only (the TOEFL route is a real alternative minimum there);
 * where the language rule already states the TOEFL alternative, the
 * supplementary TOEFL rule is left out. */
export const PROGRAM_RULES: Record<string, string[]> = {
  'ucl-cs-bsc-2026': ['ucl-academic', 'ucl-ielts-overall', 'ucl-ielts-components', 'ucl-toefl', 'ucl-gcse', 'ucl-tara', 'ucl-fee'],
  'nus-mcomp-cs': ['nus-academic', 'nus-language', 'nus-language-components', 'nus-gre-gmat', 'nus-fee'],
  'imperial-comp-beng-2027': ['imp-beng-academic', 'imp-beng-language', 'imp-beng-language-components', 'imp-beng-toefl', 'imp-beng-tmua', 'imp-beng-fee'],
  'imperial-msc-computing-2027': ['imp-msc-academic', 'imp-msc-language', 'imp-msc-language-components', 'imp-msc-toefl', 'imp-msc-test', 'imp-msc-fee'],
  'ucl-cs-msc-2027': ['ucl-msc-academic', 'ucl-msc-language', 'ucl-msc-fee'],
  'nus-bcomp-cs-2027': ['nus-bcomp-academic', 'nus-bcomp-language', 'nus-bcomp-language-components', 'nus-bcomp-toefl', 'nus-bcomp-fee'],
  'ntu-bcomp-cs-2027': ['ntu-bcomp-academic', 'ntu-bcomp-language', 'ntu-bcomp-language-components', 'ntu-bcomp-toefl', 'ntu-bcomp-fee'],
  'ntu-msai-2027': ['ntu-msai-academic', 'ntu-msai-language', 'ntu-msai-language-components', 'ntu-msai-gre', 'ntu-msai-fee'],
};

/** Fee metadata per fee rule: currency + period, for the localized
 * budget sentence and observed line. */
const FEE_META: Record<string, { currency: string; period: 'per_year' | 'total' }> = {
  'ucl-fee': { currency: 'GBP', period: 'per_year' },
  'nus-fee': { currency: 'SGD', period: 'total' },
  'imp-beng-fee': { currency: 'GBP', period: 'per_year' },
  'imp-msc-fee': { currency: 'GBP', period: 'per_year' },
  'ucl-msc-fee': { currency: 'GBP', period: 'per_year' },
  'nus-bcomp-fee': { currency: 'SGD', period: 'per_year' },
  'ntu-bcomp-fee': { currency: 'SGD', period: 'per_year' },
  'ntu-msai-fee': { currency: 'SGD', period: 'total' },
};

function periodText(period: 'per_year' | 'total', t: (k: string) => string): string {
  return period === 'total' ? t('fee.period.total') : t('fee.period.perYear');
}

/** Short period form for the fee sentence: "/year" / "/年" so the
 * sentence reads "Your budget GBP 22/year is below the fee
 * GBP 48,600/year" — the long form ("per year" / "每年") cannot follow
 * a slash. */
function periodShortText(period: 'per_year' | 'total', t: (k: string) => string): string {
  return period === 'total' ? t('fee.period.totalShort') : t('fee.period.perYearShort');
}

/** Short family name for a rule id — what a status chip shows, e.g.
 * "学术" / "雅思总分" / "学费". One short name per rule family, not per
 * programme, so the chip stays readable. */
function shortKey(ruleId: string): string {
  if (ruleId.endsWith('-academic')) return 'academic';
  if (ruleId === 'ucl-ielts-overall') return 'ieltsOverall';
  if (ruleId === 'ucl-ielts-components') return 'ieltsComponents';
  if (ruleId === 'nus-language' || ruleId === 'ntu-msai-language') return 'language';
  if (ruleId === 'ucl-msc-language') return 'englishLevel';
  if (ruleId.endsWith('-language')) return 'ieltsOverall';
  if (ruleId.endsWith('-language-components')) return 'ieltsComponents';
  if (ruleId.endsWith('-toefl')) return 'toefl';
  if (ruleId === 'ucl-gcse') return 'gcse';
  if (ruleId === 'ucl-tara') return 'tara';
  if (ruleId === 'imp-beng-tmua') return 'tmua';
  if (ruleId === 'imp-msc-test') return 'admissionsTest';
  if (ruleId.endsWith('-fee')) return 'fee';
  if (ruleId === 'nus-gre-gmat') return 'greGmat';
  if (ruleId === 'ntu-msai-gre') return 'gre';
  if (ruleId === 'fixture-writing') return 'writing';
  return 'rule';
}

export function ruleName(ruleId: string, t: (key: string) => string): string {
  const key = `rule.short.${shortKey(ruleId)}`;
  const v = t(key);
  return v === key ? ruleId : v;
}

function hasThresholdValue(v: unknown): boolean {
  if (v === null || v === undefined) return false;
  if (typeof v === 'number') return true;
  if (typeof v === 'string') return v.length > 0;
  if (Array.isArray(v)) return v.some(hasThresholdValue);
  if (typeof v === 'object') return Object.values(v as Record<string, unknown>).some(hasThresholdValue);
  return false;
}

/** "要求" line for a rule, in the current locale.
 * Round 9 integration: expansion rules render from their structured
 * thresholdRaw instead of the backend's English `expected` string, so
 * the fee line is localised (with the approximate converted figure
 * when the fee was compared across currencies) and a genuinely
 * threshold-less rule shows the localised "未公布具体要求" instead
 * of a bare English placeholder. Per-rule locale keys (v2 rules)
 * still win; anything else falls back to `rule.expected`. */
export function ruleExpected(rule: RuleResult, f: Fmt): string {
  const { t, tf, locale } = f;
  const key = `rule.${rule.ruleId}.expected`;
  const v = t(key);
  if (v !== key) return v;
  if (rule.ruleId === 'exp-fee') {
    const thr = isRecord(rule.thresholdRaw) ? rule.thresholdRaw : null;
    if (thr && typeof thr.amount === 'number') {
      const period = thr.period === 'total' ? t('fee.period.total') : t('fee.period.perYear');
      let line = tf('r9money.feeExpected', {
        currency: String(thr.currency ?? ''),
        amount: fmtNum(thr.amount, locale),
        period,
      });
      const approx = isRecord(thr.approx_converted) ? thr.approx_converted : null;
      if (approx && typeof approx.amount === 'number' && typeof approx.currency === 'string') {
        line += ` (${tf('r9money.feeConverted', {
          currency: approx.currency,
          amount: fmtNum(approx.amount, locale),
        })}${typeof approx.as_of === 'string' && approx.as_of ? ` · ${approx.as_of}` : ''})`;
      }
      return line;
    }
    if (rule.status === 'UNKNOWN') return t('r9money.noThreshold');
    return rule.expected;
  }
  if (rule.ruleId.startsWith('exp-') && rule.status === 'UNKNOWN'
    && !hasThresholdValue(rule.thresholdRaw)) {
    return t('r9money.noThreshold');
  }
  return rule.expected;
}

export function statusText(status: string, t: (key: string) => string): string {
  if (status === 'MET') return t('results.met');
  if (status === 'NOT_MET') return t('results.notMet');
  if (status === 'NOT_APPLICABLE') return t('results.notApplicable');
  return t('results.unknown');
}

/** "学术：符合" — the labelled chip text. */
export function chipLabel(rule: RuleResult, f: Fmt): string {
  return `${ruleName(rule.ruleId, f.t)}${f.t('common.colon')}${statusText(rule.status, f.t)}`;
}

/** Localized UNKNOWN reason, or null. Falls back to the backend's
 * English detail only when no reason key exists (old cached data). */
export function ruleReason(rule: RuleResult, f: Fmt): string | null {
  if (rule.status !== 'UNKNOWN') return null;
  if (rule.reasonKey) {
    const v = f.t(`reason.${rule.reasonKey}`);
    if (v !== `reason.${rule.reasonKey}`) return v;
  }
  return rule.unknownReason ?? null;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function residencyLabel(value: unknown, t: (key: string) => string): string {
  const map: Record<string, string> = {
    uk: 'wizard.residencyUk',
    overseas: 'wizard.residencyOverseas',
    sg_citizen: 'wizard.residencySgCitizen',
    sg_pr: 'wizard.residencySgPr',
    sg_intl_asean: 'wizard.residencySgIntlAsean',
    sg_intl_other: 'wizard.residencySgIntlOther',
    sg_intl_nogrant: 'wizard.residencySgIntlNogrant',
  };
  const key = typeof value === 'string' ? map[value] : undefined;
  return key ? t(key) : String(value ?? dash);
}

function formatFeeObserved(rule: RuleResult, f: Fmt): string {
  const { t, tf, locale } = f;
  const meta = FEE_META[rule.ruleId];
  const raw = rule.observedRaw;
  if (raw === null || raw === undefined) return t('rule.observed.notProvided');
  if (typeof raw === 'number') {
    // The budget is the applicant's, in the applicant's currency —
    // never the fee's currency. Expansion fee rules have no FEE_META
    // entry; their threshold carries the fee currency + period.
    const budgetCurrency = f.budgetCurrency ?? meta?.currency ?? '';
    const period = meta
      ? periodText(meta.period, t)
      : (rule.thresholdRaw && typeof rule.thresholdRaw.period === 'string'
        ? (rule.thresholdRaw.period === 'total' ? t('fee.period.total') : t('fee.period.perYear'))
        : '');
    return tf('rule.observed.budget', {
      currency: budgetCurrency,
      amount: fmtNum(raw, locale),
      period,
    });
  }
  if (isRecord(raw)) {
    if (typeof raw.amount === 'number') {
      const period = raw.period === 'total' ? t('fee.period.total') : t('fee.period.perYear');
      return tf('rule.observed.budget', {
        currency: String(raw.currency ?? meta?.currency ?? ''),
        amount: fmtNum(raw.amount, locale),
        period,
      });
    }
    if ('residency' in raw) {
      return tf('rule.observed.feeResidency', { residency: residencyLabel(raw.residency, t) });
    }
  }
  return rule.observed;
}

function formatAcademicObserved(rule: RuleResult, f: Fmt): string {
  const { t, tf, locale } = f;
  const raw = rule.observedRaw;
  if (!isRecord(raw)) {
    if (typeof raw === 'string' && raw) return raw;
    return t('rule.observed.notProvided');
  }
  const cur = raw.curriculum;
  if (cur === 'cn_gaokao') {
    if (raw.gaokao_score === null || raw.gaokao_score === undefined) {
      return t('rule.observed.notProvided');
    }
    return tf('rule.observed.gaokao', {
      score: fmtNum(raw.gaokao_score as number, locale),
      total: raw.gaokao_total == null ? dash : fmtNum(raw.gaokao_total as number, locale),
    });
  }
  if (cur === 'usa') {
    const parts: string[] = [];
    if (Array.isArray(raw.ap_grades) && raw.ap_grades.length) {
      parts.push(tf('rule.observed.usaAp', { grades: (raw.ap_grades as unknown[]).join(', ') }));
    }
    if (raw.sat_total != null) parts.push(tf('rule.observed.usaSat', { score: fmtNum(raw.sat_total as number, locale) }));
    if (raw.act_composite != null) parts.push(tf('rule.observed.usaAct', { score: fmtNum(raw.act_composite as number, locale) }));
    return parts.length ? parts.join(' · ') : t('rule.observed.notProvided');
  }
  if (cur === 'ib') {
    if (raw.total == null && raw.hl_maths == null && raw.hl_total == null) {
      return t('rule.observed.notProvided');
    }
    return tf('rule.observed.ib', {
      total: raw.total == null ? dash : fmtNum(raw.total as number, locale),
      hlMaths: raw.hl_maths == null ? dash : String(raw.hl_maths),
      hlTotal: raw.hl_total == null ? dash : fmtNum(raw.hl_total as number, locale),
    });
  }
  if (cur === 'uk_alevel' || cur === 'sg_alevel') {
    const grades = Array.isArray(raw.grades) ? (raw.grades as unknown[]) : [];
    if (!grades.length && raw.maths == null) return t('rule.observed.notProvided');
    return tf('rule.observed.alevels', {
      grades: grades.length ? grades.join('') : dash,
      maths: raw.maths == null ? dash : String(raw.maths),
    });
  }
  // Masters academic rules carry a degree field, not a curriculum.
  if ('field' in raw || 'degree_class' in raw || 'experience_years' in raw) {
    return formatDegreeObserved(raw, f);
  }
  // Expansion academic rules carry the A-level grades directly
  // ({grades, maths}) with no curriculum key — render them instead of
  // "Not provided" (the grades were supplied and the rule used them).
  if (Array.isArray(raw.grades) && raw.grades.length) {
    return tf('rule.observed.alevels', {
      grades: (raw.grades as unknown[]).join(''),
      maths: raw.maths == null ? dash : String(raw.maths),
    });
  }
  return t('rule.observed.notProvided');
}

function formatDegreeObserved(raw: Record<string, unknown>, f: Fmt): string {
  const { t, tf } = f;
  const parts: string[] = [];
  if (typeof raw.field === 'string' && raw.field) {
    const key = `rule.field.${raw.field}`;
    const v = t(key);
    parts.push(v === key ? raw.field : v);
  }
  if (raw.honours === true) parts.push(t('rule.observed.honours'));
  if (typeof raw.experience_years === 'number') {
    parts.push(tf('rule.observed.experience', { years: raw.experience_years }));
  }
  if (typeof raw.degree_class === 'string' && raw.degree_class) {
    const map: Record<string, string> = {
      first: 'wizard.degreeClassFirst',
      upper_second: 'wizard.degreeClassUpperSecond',
      lower_second: 'wizard.degreeClassLowerSecond',
      third: 'wizard.degreeClassThird',
      other: 'wizard.degreeClassOther',
    };
    const key = map[raw.degree_class];
    if (key) parts.push(t(key));
  }
  if (raw.maths_alevel != null) {
    parts.push(tf('rule.observed.mathsAlevel', { grade: String(raw.maths_alevel) }));
  }
  return parts.length ? parts.join(' · ') : t('rule.observed.notProvided');
}

function formatLanguageObserved(rule: RuleResult, f: Fmt): string {
  const { t, tf, locale } = f;
  const raw = rule.observedRaw;
  const id = rule.ruleId;
  if (raw === null || raw === undefined) return t('rule.observed.notProvided');
  // Expansion language rules carry the raw scores as a record
  // ({ielts_overall, toefl_overall}) — the old code fell through to
  // the backend's English `observed` string and rendered it verbatim
  // ("ielts_overall: 7, toefl_overall: None"). Render each supplied
  // score with its localised label; a missing score is simply absent,
  // never "None", never a snake_case key.
  if (isRecord(raw) && ('ielts_overall' in raw || 'toefl_overall' in raw)) {
    const parts: string[] = [];
    if (typeof raw.ielts_overall === 'number') {
      parts.push(tf('rule.observed.ieltsOverall', { score: fmtNum(raw.ielts_overall, locale) }));
    }
    if (typeof raw.toefl_overall === 'number') {
      parts.push(tf('rule.observed.toefl', { score: fmtNum(raw.toefl_overall, locale) }));
    }
    return parts.length ? parts.join(' · ') : t('rule.observed.notProvided');
  }
  // IELTS components: render only the components the rule actually
  // requires (from thresholdRaw), e.g. Reading/Writing for NUS BComp.
  // A threshold of {each_component: x} means all four components.
  // UCL names the rule '-ielts-components', the others
  // '-language-components'.
  if ((id.endsWith('-language-components') || id.endsWith('-ielts-components')) && isRecord(raw)) {
    const keys = rule.thresholdRaw ? Object.keys(rule.thresholdRaw) : [];
    const wanted = keys.length && !keys.includes('each_component')
      ? keys
      : ['listening', 'reading', 'writing', 'speaking'];
    const labelKey: Record<string, string> = {
      listening: 'wizard.ieltsListening',
      reading: 'wizard.ieltsReading',
      writing: 'wizard.ieltsWriting',
      speaking: 'wizard.ieltsSpeaking',
    };
    return wanted
      .map((k) => `${t(labelKey[k] ?? k)} ${raw[k] == null ? dash : fmtNum(raw[k] as number, locale)}`)
      .join(' / ');
  }
  // TOEFL supplied where IELTS was expected: say so explicitly.
  if (isRecord(raw) && raw.exam === 'toefl' && raw.overall != null) {
    return tf('rule.observed.toeflInstead', { score: fmtNum(raw.overall as number, locale) });
  }
  if (typeof raw === 'number') {
    // IELTS-only overall rules name the exam; the IELTS-or-TOEFL rules
    // (NUS MComp, NTU MSAI) cannot tell which exam a bare number came
    // from, so they stay neutral.
    if (id === 'nus-language' || id === 'ntu-msai-language') {
      return tf('rule.observed.languageScore', { score: fmtNum(raw, locale) });
    }
    return tf('rule.observed.ieltsOverall', { score: fmtNum(raw, locale) });
  }
  return rule.observed;
}

function formatToeflObserved(rule: RuleResult, f: Fmt): string {
  const { t, tf, locale } = f;
  const raw = rule.observedRaw;
  if (raw === null || raw === undefined) return t('rule.observed.notProvided');
  if (typeof raw === 'number') return tf('rule.observed.toefl', { score: fmtNum(raw, locale) });
  if (isRecord(raw) && raw.overall != null) {
    if (raw.test_date) {
      return tf('rule.observed.toeflDate', {
        score: fmtNum(raw.overall as number, locale),
        date: String(raw.test_date),
      });
    }
    return tf('rule.observed.toefl', { score: fmtNum(raw.overall as number, locale) });
  }
  return rule.observed;
}

function formatGreObserved(rule: RuleResult, f: Fmt): string {
  const { t, tf, locale } = f;
  const raw = rule.observedRaw;
  if (!isRecord(raw)) return t('rule.observed.notProvided');
  if (raw.gre_total != null) {
    return tf('rule.observed.gre', {
      total: fmtNum(raw.gre_total as number, locale),
      aw: raw.gre_analytical == null ? dash : fmtNum(raw.gre_analytical as number, locale),
    });
  }
  if (raw.gmat_total != null) {
    return tf('rule.observed.gmat', { total: fmtNum(raw.gmat_total as number, locale) });
  }
  return t('rule.observed.notProvided');
}

/** "你的情况" line for a rule, in the current locale. */
export function formatObserved(rule: RuleResult, f: Fmt): string {
  const { t } = f;
  if (rule.status === 'NOT_APPLICABLE') return t('rule.observed.notApplicable');
  const id = rule.ruleId;
  if (id.endsWith('-fee')) return formatFeeObserved(rule, f);
  if (id.endsWith('-academic')) return formatAcademicObserved(rule, f);
  if (id.endsWith('-toefl')) return formatToeflObserved(rule, f);
  if (id === 'nus-gre-gmat' || id === 'ntu-msai-gre') return formatGreObserved(rule, f);
  if (id === 'ucl-gcse') {
    const raw = rule.observedRaw;
    if (!isRecord(raw) || (raw.english == null && raw.maths == null)) {
      return t('rule.observed.notProvided');
    }
    return f.tf('rule.observed.gcse', {
      english: raw.english == null ? dash : String(raw.english),
      maths: raw.maths == null ? dash : String(raw.maths),
    });
  }
  if (id.endsWith('-language') || id.endsWith('-language-components') || id.endsWith('-ielts-components')) {
    return formatLanguageObserved(rule, f);
  }
  const raw = rule.observedRaw;
  if (raw === null || raw === undefined) return t('rule.observed.notProvided');
  if (typeof raw === 'number') return fmtNum(raw, f.locale);
  if (typeof raw === 'string') return raw;
  if (isRecord(raw)) {
    // Never render a raw snake_case key ("ielts_overall: 7") or a
    // null value ("toefl_overall: None"). Known keys get a clean
    // label; any other identifier-like key renders its value only.
    const labelFor = (k: string): string | null => {
      if (k === 'ielts_overall') return 'IELTS';
      if (k === 'toefl_overall') return 'TOEFL';
      if (k === 'listening') return t('wizard.ieltsListening');
      if (k === 'reading') return t('wizard.ieltsReading');
      if (k === 'writing') return t('wizard.ieltsWriting');
      if (k === 'speaking') return t('wizard.ieltsSpeaking');
      if (k === 'grades') return null;
      if (k === 'maths') return t('wizard.mathsLabel');
      return null;
    };
    const entries = Object.entries(raw)
      .filter(([, v]) => v !== null && v !== undefined)
      .map(([k, v]) => {
        const value = Array.isArray(v) ? v.join(', ') : String(v);
        const label = labelFor(k);
        if (label) return `${label} ${value}`;
        if (k.includes('_')) return value;
        return `${k}: ${value}`;
      });
    if (entries.length) return entries.join(', ');
  }
  return rule.observed;
}

/** Blocker sentence for a fee rule: "你的预算 GBP 22/年，低于学费
 * GBP 48,600/年". Returns null when the sentence cannot be built
 * (missing budget or fee), so the caller can fall back to the generic
 * blocker line. Round 8: the budget is labelled with the applicant's
 * own currency, never the fee's — and when the two currencies differ
 * the sentence says so plainly instead of claiming "below" across
 * currencies (a fee whose amount is unknown never reaches here: the
 * threshold is missing, so null is returned and no mismatch is
 * claimed). */
export function formatFeeSentence(rule: RuleResult, f: Fmt): string | null {
  const meta = FEE_META[rule.ruleId];
  if (!meta || rule.status !== 'NOT_MET') return null;
  const raw = rule.observedRaw;
  const thr = rule.thresholdRaw;
  const fee = thr ? (thr.gbp_per_year ?? thr.sgd_total ?? thr.amount) : undefined;
  if (typeof raw !== 'number' || typeof fee !== 'number') return null;
  const budgetCurrency = f.budgetCurrency ?? meta.currency;
  const feeCurrency = meta.currency;
  const period = periodShortText(meta.period, f.t);
  if (budgetCurrency !== feeCurrency) {
    return f.tf('rule.fee.currencyDiffers', {
      budgetCurrency,
      budget: fmtNum(raw, f.locale),
      feeCurrency,
      fee: fmtNum(fee, f.locale),
      period,
    });
  }
  return f.tf('rule.fee.below', {
    budgetCurrency,
    budget: fmtNum(raw, f.locale),
    feeCurrency,
    fee: fmtNum(fee, f.locale),
    period,
  });
}
