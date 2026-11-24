'use client';
import { useState } from 'react';
import { useApp } from '../lib/store';
import { Program, RuleResult } from '../lib/types';

/**
 * Evidence drawer (Day 2, FR03): every rule result links to its evidence
 * source. Shows the source label, the official URL (clickable), the
 * excerpt, the verified date, and the intake the evidence applies to.
 *
 * Evidence excerpts are English-only in the data — they are labelled
 * honestly (evidence.englishOnly) rather than presented as translated.
 * Works for any programme, including ones loaded from the API: sources
 * are matched by id, and an evidence id with no matching source is shown
 * as unavailable instead of silently dropping the rule's evidence.
 */
export function EvidenceDrawer({ program, rule }: { program: Program; rule: RuleResult }) {
  const { t } = useApp();
  const [openSource, setOpenSource] = useState<string | null>(null);
  const srcs = program.sources.filter((s) => rule.evidenceIds.includes(s.id));
  const missing = rule.evidenceIds.filter((id) => !program.sources.some((s) => s.id === id));
  if (rule.evidenceIds.length === 0 && srcs.length === 0) return null;

  return (
    <div>
      <div className="mt-2 flex flex-wrap gap-2">
        {srcs.map((s) => (
          <button key={s.id} type="button" onClick={() => setOpenSource(openSource === s.id ? null : s.id)} aria-expanded={openSource === s.id}
            className="btn-press rounded-full border border-teal px-3 py-1 text-xs font-semibold text-teal-dark">
            {s.label} · {t('program.sourceVerified')} {s.verifiedDate}
          </button>
        ))}
        {missing.length > 0 && (
          <span className="rounded-full border border-navy/25 px-3 py-1 text-xs font-semibold text-navy/60">
            {t('evidence.unavailable')} ({missing.join(', ')})
          </span>
        )}
      </div>
      {srcs.map((s) => openSource === s.id && (
        <div key={s.id} className="anim-fade-in mt-3 rounded-lg bg-paper p-3 text-sm">
          {s.excerpt ? (
            <>
              <p className="italic" lang="en" dir="ltr">“{s.excerpt}”</p>
              <p className="mt-1 text-xs font-semibold text-navy/60">{t('evidence.englishOnly')}</p>
            </>
          ) : (
            <p className="text-navy/70">{t('evidence.unavailable')}</p>
          )}
          <a href={s.url} target="_blank" rel="noreferrer" className="mt-2 inline-block break-all font-semibold text-teal-dark underline">{s.url}</a>
          <p className="mt-1 text-xs text-navy/60">
            {t('program.sourceVerified')}: {s.verifiedDate}
            {' · '}{t('evidence.intakeApplies')}: {s.appliesTo || program.intakeLabel}
          </p>
        </div>
      ))}
    </div>
  );
}
