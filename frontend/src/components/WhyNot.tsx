'use client';
import { useApp } from '../lib/store';
import { MatchResult, Program, RuleResult } from '../lib/types';
import { chipLabel, formatObserved, ruleExpected, ruleName } from '../lib/ruleText';
import { displayProgramName } from '../lib/programs';
import { displayProgramInstitutionName } from '../lib/rankings';
import { StatusChip } from './StatusChip';
import { RuleRow } from './RuleRow';
import { GaokaoPanel } from './GaokaoPanel';

/**
 * Why-not explanations + rule-by-rule comparison (Day 3, W2).
 *
 * The template is computed locally from the /match ruleResults already
 * on the page (engine-computed expected/observed + thresholdRaw /
 * observedRaw) — so it renders even when the backend is asleep or
 * offline, and it can never invent a number: every gap is read off
 * the rule's own threshold vs observed values. The backend /whynot
 * response (when available) only adds two things: engine verification
 * of the cheapest fix (the change was re-run through the rules) and
 * an optional citation-checked model note. The model note is labelled
 * as the AI's reading and may be wrong; the boundary line above the
 * numbers says so in every locale.
 *
 * No admission probabilities anywhere. A Gaokao academic UNKNOWN is
 * never "fixed" by a score change: no university publishes a Gaokao
 * equivalence, so the panel says so and links the official Gaokao
 * routes instead.
 */

// --- Server shape (POST /api/v1/whynot, snake_case) -------------------------
export interface WhynotServerGap {
  kind: string;
  label: string;
  required?: number | null;
  observed?: number | null;
  gap?: number | null;
  fee_currency?: string | null;
  fee_amount?: number | null;
  converted_fee?: number | null;
  converted_currency?: string | null;
  as_of?: string | null;
  text?: string | null;
}

export interface WhynotServerFix {
  id: string;
  kind: string;
  field: string;
  component?: string | null;
  from?: number | null;
  to?: number | Record<string, number> | null;
  currency?: string | null;
  resolves_rule_ids?: string[];
  verified?: boolean;
}

export interface WhynotServer {
  program_id: string;
  failing_rules: { rule_id: string; family: string; gaps: WhynotServerGap[] }[];
  unknown_rules: string[];
  academic_unknown: boolean;
  gaokao_route: boolean;
  cheapest_fix: WhynotServerFix | null;
  no_single_fix: boolean;
}

export interface WhynotServerResult {
  whynot: WhynotServer | null;
  model_note: string | null;
  ai_status: string;
}

// --- Local template computation (mirror of backend/ai/explain.py) ----------
export type GapKind = 'component' | 'overall' | 'toefl' | 'fee' | 'detail';

export interface WhynotGap {
  kind: GapKind;
  label: string;
  required?: number;
  observed?: number | null;
  gap?: number | null;
  feeCurrency?: string;
  feeAmount?: number;
  convertedFee?: number;
  convertedCurrency?: string;
  asOf?: string;
  text?: string;
}

export interface WhynotFix {
  id: string;
  kind: string;
  field: string;
  component?: string | null;
  from?: number | null;
  to?: number | Record<string, number> | null;
  currency?: string;
  resolvesRuleIds: string[];
  verified: boolean;
}

export interface WhynotLocal {
  failingRuleIds: string[];
  gapsByRule: Record<string, WhynotGap[]>;
  cheapestFix: WhynotFix | null;
  noSingleFix: boolean;
  academicUnknown: boolean;
  gaokaoRoute: boolean;
}

const COMPONENTS = ['listening', 'reading', 'writing', 'speaking'] as const;

const FAMILY_ORDER = ['academic', 'language', 'language-components', 'toefl',
  'gcse', 'test', 'gre', 'fee', 'other'];

/** Rule family for comparison alignment (mirror of backend
 * ai.explain.rule_family): programmes name the same requirement
 * differently, so the comparison aligns by family, never by raw id. */
export function ruleFamily(ruleId: string): string {
  if (ruleId.endsWith('-academic')) return 'academic';
  if (ruleId.endsWith('-fee')) return 'fee';
  if (ruleId.endsWith('-toefl')) return 'toefl';
  if (ruleId.endsWith('-language-components') || ruleId.endsWith('-ielts-components')) return 'language-components';
  if (ruleId.endsWith('-language') || ruleId.endsWith('-ielts-overall')) return 'language';
  if (ruleId === 'ucl-gcse') return 'gcse';
  if (ruleId.endsWith('-tmua') || ruleId === 'ucl-tara' || ruleId.endsWith('-test')) return 'test';
  if (ruleId.endsWith('-gre') || ruleId.endsWith('-gre-gmat')) return 'gre';
  return 'other';
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function num(v: unknown): number | null {
  return typeof v === 'number' && !Number.isNaN(v) ? v : null;
}

function roundHalfUp(v: number): number {
  return Math.ceil(v * 2 - 1e-9) / 2;
}

function componentRequired(thr: Record<string, unknown> | null | undefined, comp: string): number | null {
  if (!thr) return null;
  return num(thr[comp]) ?? num(thr.each_component);
}

function gapsForRule(rule: RuleResult, budgetCurrency?: string): WhynotGap[] {
  const family = ruleFamily(rule.ruleId);
  const thr = isRecord(rule.thresholdRaw) ? rule.thresholdRaw : null;
  const obs = rule.observedRaw;
  const gaps: WhynotGap[] = [];
  if (family === 'language-components') {
    const observed = isRecord(obs) ? obs : {};
    const three = thr ? num(thr.__three__) : null;
    const remaining = thr ? num(thr.__remaining__) : null;
    if (three !== null && remaining !== null) {
      let atThree = 0;
      for (const comp of COMPONENTS) {
        const score = num(observed[comp]);
        if (score === null) continue;
        if (score >= three) atThree += 1;
        if (score < remaining) {
          gaps.push({ kind: 'component', label: comp, required: remaining, observed: score, gap: Math.round((remaining - score) * 100) / 100 });
        }
      }
      if (atThree < 3) {
        gaps.push({ kind: 'overall', label: 'three_components', required: three, observed: atThree, gap: 3 - atThree });
      }
      return gaps;
    }
    for (const comp of COMPONENTS) {
      const required = componentRequired(thr, comp);
      const score = num(observed[comp]);
      if (required === null || score === null || score >= required) continue;
      gaps.push({ kind: 'component', label: comp, required, observed: score, gap: Math.round((required - score) * 100) / 100 });
    }
    return gaps;
  }
  if (family === 'language') {
    if (typeof obs === 'number') {
      const required = thr ? num(thr.overall) : null;
      if (required !== null && obs < required) {
        gaps.push({ kind: 'overall', label: 'overall', required, observed: obs, gap: Math.round((required - obs) * 100) / 100 });
      }
      return gaps;
    }
    if (isRecord(obs)) {
      for (const [exam, key] of [['ielts', 'ielts_overall'], ['toefl', 'toefl_overall']] as const) {
        const raw = thr ? thr[key] : undefined;
        const required = Array.isArray(raw)
          ? Math.min(...raw.map((v) => num(v)).filter((v): v is number => v !== null))
          : num(raw);
        const score = num(obs[key]);
        if (required !== null && !Number.isNaN(required) && score !== null && score < required) {
          gaps.push({ kind: 'overall', label: exam, required, observed: score, gap: Math.round((required - score) * 100) / 100 });
        }
      }
      return gaps;
    }
    return gaps;
  }
  if (family === 'toefl') {
    const required = thr ? num(thr.overall) : null;
    const score = isRecord(obs) ? num(obs.overall) : num(obs);
    if (required !== null && score !== null && score < required) {
      gaps.push({ kind: 'toefl', label: 'toefl', required, observed: score, gap: Math.round((required - score) * 100) / 100 });
    }
    return gaps;
  }
  if (family === 'fee') {
    let feeAmount: number | null = null;
    let feeCurrency: string | null = null;
    if (thr) {
      for (const [key, ccy] of [['gbp_per_year', 'GBP'], ['sgd_total', 'SGD']] as const) {
        if (num(thr[key]) !== null) { feeAmount = num(thr[key]); feeCurrency = ccy; break; }
      }
      if (feeAmount === null) {
        feeAmount = num(thr.amount);
        feeCurrency = typeof thr.currency === 'string' ? thr.currency : null;
      }
    }
    const budget = isRecord(obs) ? num(obs.amount) : num(obs);
    if (feeAmount !== null && budget !== null) {
      const approx = thr && isRecord(thr.approx_converted) ? thr.approx_converted : null;
      const gap: WhynotGap = { kind: 'fee', label: 'fee', required: feeAmount, observed: budget, feeCurrency: feeCurrency ?? undefined, feeAmount };
      if (approx) {
        const convAmount = num(approx.amount);
        const convCcy = typeof approx.currency === 'string' ? approx.currency : undefined;
        if (convAmount !== null && convCcy) {
          gap.convertedFee = convAmount;
          gap.convertedCurrency = convCcy;
          gap.gap = Math.round((convAmount - budget) * 100) / 100;
          gap.asOf = typeof approx.as_of === 'string' ? approx.as_of : undefined;
        }
      } else if (budgetCurrency && feeCurrency && budgetCurrency === feeCurrency) {
        gap.gap = Math.round((feeAmount - budget) * 100) / 100;
      }
      gaps.push(gap);
    }
    return gaps;
  }
  return gaps;
}

const KIND_ORDER: Record<string, number> = {
  ielts_component: 0, ielts_overall: 1, toefl: 2, budget: 3, ielts_components: 4,
};

function fixStep(fix: WhynotFix): number {
  if (fix.kind === 'budget' || fix.kind === 'ielts_component' || fix.kind === 'ielts_overall' || fix.kind === 'toefl') {
    if (typeof fix.from === 'number' && typeof fix.to === 'number') return fix.to - fix.from;
    return Infinity;
  }
  if (fix.kind === 'ielts_components' && isRecord(fix.to)) {
    return Object.values(fix.to).reduce((s, v) => s + (typeof v === 'number' ? v : 0), 0);
  }
  return Infinity;
}

function candidatesForRule(rule: RuleResult, gaps: WhynotGap[]): WhynotFix[] {
  const family = ruleFamily(rule.ruleId);
  const out: WhynotFix[] = [];
  if (family === 'language-components') {
    const compGaps = gaps.filter((g) => g.kind === 'component');
    const threeGap = gaps.find((g) => g.kind === 'overall' && g.label === 'three_components');
    for (const g of compGaps) {
      const target = roundHalfUp(g.required ?? 0);
      out.push({
        id: `ielts-${g.label}-to-${target}`, kind: 'ielts_component',
        field: `ielts${g.label.charAt(0).toUpperCase()}${g.label.slice(1)}`,
        component: g.label, from: g.observed ?? null, to: target,
        resolvesRuleIds: compGaps.length === 1 && !threeGap ? [rule.ruleId] : [],
        verified: false,
      });
    }
    if (compGaps.length > 1 || threeGap) {
      const changes: Record<string, number> = {};
      for (const g of compGaps) changes[g.label] = roundHalfUp(g.required ?? 0);
      if (threeGap && threeGap.required !== undefined) {
        const target3 = roundHalfUp(threeGap.required);
        for (const comp of COMPONENTS) changes[comp] = Math.max(changes[comp] ?? 0, target3);
      }
      out.push({
        id: 'ielts-components-retake', kind: 'ielts_components', field: 'ieltsComponents',
        component: null, from: null, to: changes,
        resolvesRuleIds: [rule.ruleId], verified: false,
      });
    }
    return out;
  }
  if (family === 'language' || family === 'toefl') {
    for (const g of gaps) {
      if (g.kind !== 'overall' && g.kind !== 'toefl') continue;
      const target = g.kind === 'toefl' ? (g.required ?? 0) : roundHalfUp(g.required ?? 0);
      const isToefl = g.kind === 'toefl' || g.label === 'toefl';
      out.push({
        id: `${isToefl ? 'toefl' : 'ielts-overall'}-to-${target}`,
        kind: isToefl ? 'toefl' : 'ielts_overall',
        field: isToefl ? 'toefl' : 'ieltsOverall',
        component: null, from: g.observed ?? null, to: target,
        resolvesRuleIds: [rule.ruleId], verified: false,
      });
    }
    return out;
  }
  if (family === 'fee') {
    for (const g of gaps) {
      if (g.kind !== 'fee' || g.gap === null || g.gap === undefined || g.gap <= 0) continue;
      const currency = g.convertedCurrency ?? g.feeCurrency;
      const target = g.convertedFee !== undefined
        ? Math.floor(g.convertedFee) + 1
        : g.feeAmount ?? 0;
      out.push({
        id: 'budget-to-fee', kind: 'budget', field: 'budget',
        component: null, from: g.observed ?? null, to: target,
        currency, resolvesRuleIds: [rule.ruleId], verified: false,
      });
    }
    return out;
  }
  return out;
}

/** Local why-not for one result (structural template, unverified). */
export function computeWhynotLocal(result: MatchResult, budgetCurrency?: string): WhynotLocal {
  const failingRuleIds: string[] = [];
  const gapsByRule: Record<string, WhynotGap[]> = {};
  let candidates: WhynotFix[] = [];
  let academicUnknown = false;
  let gaokaoRoute = false;
  for (const r of result.ruleResults) {
    if (r.status === 'UNKNOWN') {
      if (ruleFamily(r.ruleId) === 'academic') {
        academicUnknown = true;
        const obs = isRecord(r.observedRaw) ? r.observedRaw : null;
        if (obs && obs.curriculum === 'cn_gaokao') gaokaoRoute = true;
      }
    }
    if (r.status !== 'NOT_MET') continue;
    failingRuleIds.push(r.ruleId);
    let gaps = gapsForRule(r, budgetCurrency);
    if (!gaps.length) {
      // No numeric gap can be read off the rule (e.g. an academic
      // NOT_MET on A-level grades): the required / your-situation
      // lines rendered above already carry the engine's verdict, so
      // no extra gap line is invented.
      gaps = [{ kind: 'detail', label: ruleFamily(r.ruleId), text: '' }];
    }
    gapsByRule[r.ruleId] = gaps;
    candidates = candidates.concat(candidatesForRule(r, gaps));
  }
  candidates.sort((a, b) =>
    (b.resolvesRuleIds.length - a.resolvesRuleIds.length)
    || ((KIND_ORDER[a.kind] ?? 99) - (KIND_ORDER[b.kind] ?? 99))
    || (fixStep(a) - fixStep(b)));
  const cheapestFix = candidates.find((c) => c.resolvesRuleIds.length > 0) ?? null;
  return {
    failingRuleIds, gapsByRule, cheapestFix,
    noSingleFix: failingRuleIds.length > 0 && cheapestFix === null,
    academicUnknown, gaokaoRoute,
  };
}

// --- Rendering ----------------------------------------------------------------

function fmtNum(n: number | null | undefined, locale: string): string {
  if (n === null || n === undefined) return '–';
  return Number(n).toLocaleString(locale);
}

function componentLabel(comp: string, t: (k: string) => string): string {
  const key: Record<string, string> = {
    listening: 'wizard.ieltsListening', reading: 'wizard.ieltsReading',
    writing: 'wizard.ieltsWriting', speaking: 'wizard.ieltsSpeaking',
  };
  return t(key[comp] ?? comp);
}

function fixLabel(fix: WhynotFix, t: (k: string) => string, tf: (k: string, v?: Record<string, string | number>) => string, locale: string): string {
  if (fix.kind === 'ielts_component' && fix.component) {
    return tf('whynot.fixComponent', {
      component: componentLabel(fix.component, t),
      from: fmtNum(fix.from, locale), to: fmtNum(typeof fix.to === 'number' ? fix.to : null, locale),
    });
  }
  if (fix.kind === 'ielts_overall') {
    return tf('whynot.fixOverall', { from: fmtNum(fix.from, locale), to: fmtNum(typeof fix.to === 'number' ? fix.to : null, locale) });
  }
  if (fix.kind === 'toefl') {
    return tf('whynot.fixToefl', { from: fmtNum(fix.from, locale), to: fmtNum(typeof fix.to === 'number' ? fix.to : null, locale) });
  }
  if (fix.kind === 'budget') {
    return tf('whynot.fixBudget', { to: fmtNum(typeof fix.to === 'number' ? fix.to : null, locale), currency: fix.currency ?? '' });
  }
  if (fix.kind === 'ielts_components' && isRecord(fix.to)) {
    const list = Object.entries(fix.to)
      .map(([c, v]) => `${componentLabel(c, t)} ${fmtNum(typeof v === 'number' ? v : null, locale)}`)
      .join(locale === 'zh-CN' ? '、' : ', ');
    return tf('whynot.fixComponents', { list });
  }
  return fix.id;
}

function GapLine({ rule, gap }: { rule: RuleResult; gap: WhynotGap }) {
  const { t, tf, locale } = useApp();
  if (gap.kind === 'detail') {
    // No numeric gap: the required / your-situation lines above
    // already show the engine's verdict — render nothing extra.
    return null;
  }
  if (gap.kind === 'component') {
    return (
      <p className="mt-1 text-sm text-navy/80">
        {tf('whynot.gapComponent', {
          component: componentLabel(gap.label, t),
          required: fmtNum(gap.required, locale),
          observed: fmtNum(gap.observed, locale),
          gap: fmtNum(gap.gap, locale),
        })}
      </p>
    );
  }
  if (gap.kind === 'overall') {
    if (gap.label === 'three_components') {
      return (
        <p className="mt-1 text-sm text-navy/80">
          {tf('whynot.gapThreeComponents', {
            required: fmtNum(gap.required, locale),
            observed: fmtNum(gap.observed, locale),
          })}
        </p>
      );
    }
    return (
      <p className="mt-1 text-sm text-navy/80">
        {tf('whynot.gapOverall', {
          exam: gap.label === 'toefl' ? 'TOEFL' : 'IELTS',
          required: fmtNum(gap.required, locale),
          observed: fmtNum(gap.observed, locale),
          gap: fmtNum(gap.gap, locale),
        })}
      </p>
    );
  }
  if (gap.kind === 'toefl') {
    return (
      <p className="mt-1 text-sm text-navy/80">
        {tf('whynot.gapOverall', {
          exam: 'TOEFL',
          required: fmtNum(gap.required, locale),
          observed: fmtNum(gap.observed, locale),
          gap: fmtNum(gap.gap, locale),
        })}
      </p>
    );
  }
  if (gap.kind === 'fee') {
    if (gap.convertedFee !== undefined && gap.convertedCurrency && gap.gap !== null && gap.gap !== undefined) {
      return (
        <p className="mt-1 text-sm text-navy/80">
          {tf('whynot.gapFeeConverted', {
            feeCurrency: gap.feeCurrency ?? '',
            fee: fmtNum(gap.feeAmount, locale),
            convertedCurrency: gap.convertedCurrency,
            converted: fmtNum(gap.convertedFee, locale),
            budget: fmtNum(gap.observed, locale),
            shortfall: fmtNum(gap.gap, locale),
            currency: gap.convertedCurrency,
          })}
        </p>
      );
    }
    if (gap.gap !== null && gap.gap !== undefined) {
      return (
        <p className="mt-1 text-sm text-navy/80">
          {tf('whynot.gapFee', {
            feeCurrency: gap.feeCurrency ?? '',
            fee: fmtNum(gap.feeAmount, locale),
            budget: fmtNum(gap.observed, locale),
            shortfall: fmtNum(gap.gap, locale),
            currency: gap.feeCurrency ?? '',
          })}
        </p>
      );
    }
    return (
      <p className="mt-1 text-sm text-navy/80">
        {tf('whynot.gapFeeNoShortfall', {
          feeCurrency: gap.feeCurrency ?? '',
          fee: fmtNum(gap.feeAmount, locale),
          budget: fmtNum(gap.observed, locale),
        })}
      </p>
    );
  }
  return null;
}

export function WhyNot({ result, program, server, modelNote, aiStatus }: {
  result: MatchResult;
  program: Program;
  server?: WhynotServer | null;
  modelNote?: string | null;
  aiStatus?: string;
}) {
  const { t, tf, locale, profile } = useApp();
  const f = { t, tf, locale, budgetCurrency: profile.budgetCurrency };
  const local = computeWhynotLocal(result, profile.budgetCurrency);
  const blockers = result.ruleResults.filter((r) => r.status === 'NOT_MET');
  // Render for programmes with a failing rule, or where the academic
  // rule alone is UNKNOWN (the "why isn't this met?" question the
  // audit profile asks on every card). Otherwise nothing to explain.
  if (blockers.length === 0 && !local.academicUnknown) return null;
  // The verified cheapest fix (engine re-checked) wins over the local
  // structural one; the local template always renders the gaps. A
  // server fix that resolves no rule is no fix at all — when server
  // data is present it is trusted over the local structural ranking.
  const serverFix = server?.cheapest_fix ?? null;
  const fix: WhynotFix | null = server
    ? (serverFix && (serverFix.resolves_rule_ids ?? []).length > 0
      ? {
          id: serverFix.id, kind: serverFix.kind, field: serverFix.field,
          component: serverFix.component ?? null,
          from: serverFix.from ?? null, to: serverFix.to ?? null,
          currency: serverFix.currency ?? undefined,
          resolvesRuleIds: serverFix.resolves_rule_ids ?? [],
          verified: serverFix.verified ?? false,
        }
      : null)
    : local.cheapestFix;
  const noSingleFix = server ? server.no_single_fix : local.noSingleFix;
  return (
    <section className="mt-3 rounded-xl border border-navy/10 bg-amber/10 p-4" aria-labelledby={`whynot-${result.programId}`}>
      <h3 id={`whynot-${result.programId}`} className="text-sm font-bold">{t('whynot.title')}</h3>
      {/* Reliability boundary (all locales): engine numbers are
          verified facts; model words are the AI's reading and may be
          wrong; suggestions are suggestions, not facts. */}
      <p className="mt-1 text-xs text-navy/70" role="note">{t('whynot.boundary')}</p>
      {blockers.length === 0 && (
        <p className="mt-2 text-sm text-navy/80">{t('whynot.onlyUnknown')}</p>
      )}
      {blockers.map((b) => (
        <div key={b.ruleId} className="mt-2 border-t border-navy/10 pt-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">{ruleName(b.ruleId, t)}</span>
            <StatusChip status={b.status} label={chipLabel(b, f)} />
          </div>
          <p className="mt-1 text-sm text-navy/75">
            {t('results.required')}{t('common.colon')}{ruleExpected(b, f)}
          </p>
          <p className="mt-1 text-sm text-navy/75">
            {t('results.yourSituation')}{t('common.colon')}{formatObserved(b, f)}
          </p>
          {(local.gapsByRule[b.ruleId] ?? []).map((gap, i) => (
            <GapLine key={`${b.ruleId}-gap-${i}`} rule={b} gap={gap} />
          ))}
        </div>
      ))}
      {fix && (
        <p className="mt-2 text-sm font-semibold">
          {tf('whynot.cheapestFix', {
            fix: fixLabel(fix, t, tf, locale),
            count: fix.resolvesRuleIds.length,
            rules: fix.resolvesRuleIds.map((id) => ruleName(id, t)).join(locale === 'zh-CN' ? '、' : ', '),
          })}
          {fix.verified ? ` ${t('whynot.verified')}` : ''}
        </p>
      )}
      {!fix && noSingleFix && (
        <p className="mt-2 text-sm font-semibold">{t('whynot.noSingleFix')}</p>
      )}
      {local.academicUnknown && (
        <div className="mt-2">
          <p className="text-sm text-navy/80">{t('whynot.academicUnknown')}</p>
          {local.gaokaoRoute && (
            <>
              <p className="mt-1 text-sm font-semibold">{t('whynot.gaokaoNote')}</p>
              <details className="mt-2">
                <summary className="cursor-pointer text-sm font-semibold text-teal-dark underline">{t('whynot.gaokaoRoutes')}</summary>
                <GaokaoPanel />
              </details>
            </>
          )}
        </div>
      )}
      {aiStatus === 'available' && modelNote && (
        <div className="mt-2 rounded-lg bg-white/70 p-3">
          <p className="text-sm font-bold">{t('whynot.modelNoteLabel')}</p>
          <p className="mt-1 whitespace-pre-line text-sm text-navy/80">{modelNote}</p>
        </div>
      )}
    </section>
  );
}

// --- Comparison view ----------------------------------------------------------

/** Rule-by-rule comparison of 2–3 programmes, aligned by rule family
 * (see ruleFamily). Each cell reuses RuleRow (status chip, required /
 * your situation, evidence drawer) so the comparison shows the same
 * verified numbers as the cards, side by side. */
export function CompareView({ results, programs }: { results: MatchResult[]; programs: Program[] }) {
  const { t, tf, locale, profile } = useApp();
  if (results.length < 2) return null;
  const families: string[] = [];
  for (const r of results) {
    for (const rule of r.ruleResults) {
      const fam = ruleFamily(rule.ruleId);
      if (!families.includes(fam)) families.push(fam);
    }
  }
  families.sort((a, b) => FAMILY_ORDER.indexOf(a) - FAMILY_ORDER.indexOf(b));
  const cols = results.map((r) => {
    const program = programs.find((p) => p.id === r.programId);
    const byFamily = new Map<string, RuleResult[]>();
    for (const rule of r.ruleResults) {
      const fam = ruleFamily(rule.ruleId);
      const list = byFamily.get(fam) ?? [];
      list.push(rule);
      byFamily.set(fam, list);
    }
    return { result: r, program, byFamily, local: computeWhynotLocal(r, profile.budgetCurrency) };
  });
  return (
    <section className="mt-4 rounded-2xl border border-navy/10 bg-white p-5" aria-labelledby="compare-title">
      <h2 id="compare-title" className="text-lg font-bold">{t('whynot.compareTitle')}</h2>
      <p className="mt-1 text-xs text-navy/70" role="note">{t('whynot.boundary')}</p>
      <div className="mt-3 grid gap-4" style={{ gridTemplateColumns: `repeat(${cols.length}, minmax(0, 1fr))` }}>
        {cols.map(({ result, program, byFamily, local }) => (
          <div key={result.programId} className="min-w-0 rounded-xl border border-navy/10 p-3">
            {program && (
              <>
                <p className="text-xs font-semibold text-teal">{displayProgramInstitutionName(program.institution, locale)} · {program.country}</p>
                <p className="mt-0.5 text-sm font-bold">{displayProgramName(program, locale)}</p>
              </>
            )}
            {families.map((fam) => {
              const rules = byFamily.get(fam) ?? [];
              return (
                <div key={fam} className="mt-3 border-t border-navy/5 pt-2">
                  <p className="text-xs font-bold uppercase tracking-wide text-navy/50">{t(`whynot.family.${fam}`)}</p>
                  {rules.length === 0 && (
                    <p className="mt-1 text-sm text-navy/50">{t('whynot.compareNoRule')}</p>
                  )}
                  {program && rules.map((rule) => (
                    <RuleRow key={rule.ruleId} program={program} rule={rule} />
                  ))}
                </div>
              );
            })}
            {local.cheapestFix && (
              <p className="mt-3 text-sm font-semibold">
                {tf('whynot.cheapestFix', {
                  fix: fixLabel(local.cheapestFix, t, tf, locale),
                  count: local.cheapestFix.resolvesRuleIds.length,
                  rules: local.cheapestFix.resolvesRuleIds.map((id) => ruleName(id, t)).join(locale === 'zh-CN' ? '、' : ', '),
                })}
              </p>
            )}
            {!local.cheapestFix && local.noSingleFix && (
              <p className="mt-3 text-sm font-semibold">{t('whynot.noSingleFix')}</p>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
