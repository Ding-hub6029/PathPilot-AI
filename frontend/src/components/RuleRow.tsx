'use client';
import { useApp } from '../lib/store';
import { chipLabel, formatObserved, ruleExpected, ruleReason } from '../lib/ruleText';
import { RuleResult } from '../lib/types';
import { StatusChip } from './StatusChip';
import { EvidenceDrawer } from './EvidenceDrawer';
import { Program } from '../lib/types';

/**
 * One rule row, shared by the results cards and the programme detail
 * page (fix 2026-11-25): labelled status chip, "要求 / 你的情况" in
 * the current locale, localized UNKNOWN reason, and the evidence
 * drawer. Source excerpts stay in their original language.
 */

const LANG_KEYS: Record<string, string> = {
  German: 'r9pages.langGerman',
  French: 'r9pages.langFrench',
  English: 'r9pages.langEnglish',
};

/**
 * Round 9 (R5): the verified language of instruction, shown next to the
 * language requirement — ETH/EPFL bachelor's are not taught in English,
 * and that decides whether a Gaokao applicant can even follow the
 * course. The language name is localised; the official note stays in
 * its original language (same rule as source excerpts) with a link to
 * the official page it came from. Renders nothing when the programme
 * carries no verified language of instruction.
 */
export function LanguageOfInstructionLine({ languageOfInstruction }: { languageOfInstruction?: { language: string; note?: string | null; sourceUrl: string } | null }) {
  const { t, tf } = useApp();
  const loi = languageOfInstruction;
  if (!loi || !loi.language) return null;
  const name = t(LANG_KEYS[loi.language] ?? 'r9pages.langEnglish');
  return (
    <p className="mt-2 rounded-lg bg-amber/15 p-2 text-sm font-semibold text-navy" role="note">
      {tf('r9pages.taughtIn', { language: name })}
      {loi.note ? (
        <span className="mt-1 block font-normal text-navy/75" lang="en" dir="ltr">{loi.note}</span>
      ) : null}
      {loi.sourceUrl ? (
        <a href={loi.sourceUrl} target="_blank" rel="noreferrer" className="mt-1 inline-block font-semibold text-teal-dark underline">
          {t('r9pages.languageSource')}
        </a>
      ) : null}
    </p>
  );
}

export function RuleRow({ program, rule }: { program: Program; rule: RuleResult }) {
  const { t, tf, locale, profile } = useApp();
  // Round 8: the fee sentence / observed line must label the budget
  // with the applicant's own currency, never the fee's.
  const f = { t, tf, locale, budgetCurrency: profile.budgetCurrency };
  const reason = ruleReason(rule, f);
  return (
    <div className="border-t border-navy/5 pt-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold">
          {t('results.required')}{t('common.colon')}{ruleExpected(rule, f)}
        </p>
        <StatusChip status={rule.status} label={chipLabel(rule, f)} />
      </div>
      <p className="mt-1 text-sm text-navy/75">
        {t('results.yourSituation')}{t('common.colon')}{formatObserved(rule, f)}
      </p>
      {reason && (
        <p className="mt-1 text-sm font-semibold text-amber-dark">{reason}</p>
      )}
      {/* Round 9 (R5): the teaching language belongs with the language
          requirement — one line per card, only on the language rule, so
          the results cards and the programme detail page (both render
          RuleRow) show it exactly once. */}
      {rule.ruleId === 'exp-language' && <LanguageOfInstructionLine languageOfInstruction={program.languageOfInstruction} />}
      <EvidenceDrawer program={program} rule={rule} />
    </div>
  );
}
