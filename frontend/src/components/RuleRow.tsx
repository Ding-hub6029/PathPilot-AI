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
export function RuleRow({ program, rule }: { program: Program; rule: RuleResult }) {
  const { t, tf, locale } = useApp();
  const f = { t, tf, locale };
  const reason = ruleReason(rule, f);
  return (
    <div className="border-t border-navy/5 pt-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold">
          {t('results.required')}{t('common.colon')}{ruleExpected(rule, t)}
        </p>
        <StatusChip status={rule.status} label={chipLabel(rule, f)} />
      </div>
      <p className="mt-1 text-sm text-navy/75">
        {t('results.yourSituation')}{t('common.colon')}{formatObserved(rule, f)}
      </p>
      {reason && (
        <p className="mt-1 text-sm font-semibold text-amber-dark">{reason}</p>
      )}
      <EvidenceDrawer program={program} rule={rule} />
    </div>
  );
}
