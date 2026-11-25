'use client';
import { useApp } from '../lib/store';
import { SuccessCase } from '../lib/types';

/**
 * One netizen-shared success case. Shows only what the poster shared:
 * offer, undergraduate background, scores, key experience, platform and
 * source link. Missing fields render nothing — never invented, never a
 * placeholder value. Every card carries the "not officially verified"
 * label; there is no contact info and no agency case in the data.
 */
export function CaseCard({ c }: { c: SuccessCase }) {
  const { t } = useApp();
  return (
    <article className="card-lift h-full rounded-2xl border border-navy/10 bg-white p-5 card-surface">
      <p className="text-sm font-semibold text-teal">{c.offerInstitution}</p>
      <h3 className="mt-1 text-lg font-bold" dir="auto">{c.offerProgramme ?? c.offerInstitution}</h3>
      <p className="mt-1 text-sm text-navy/70">
        {c.offerLevel === 'undergraduate' ? t('cases.filterUg') : t('cases.filterTm')}
        {c.intake ? ` · ${c.intake}` : ''}
      </p>
      <dl className="mt-3 space-y-2 text-sm">
        {(c.undergradInstitution || c.undergradMajor || c.gpa) && (
          <div>
            <dt className="font-semibold">{t('cases.background')}</dt>
            <dd className="text-navy/75" dir="auto">
              {[c.undergradInstitution, c.undergradMajor, c.gpa].filter(Boolean).join(' · ')}
            </dd>
          </div>
        )}
        {c.languageScores && (
          <div>
            <dt className="font-semibold">{t('cases.scores')}</dt>
            <dd className="text-navy/75" dir="ltr">{c.languageScores}</dd>
          </div>
        )}
        {c.keyExperience && (
          <div>
            <dt className="font-semibold">{t('cases.experience')}</dt>
            <dd className="text-navy/75" dir="auto">{c.keyExperience}</dd>
          </div>
        )}
      </dl>
      <p className="mt-3">
        <span className="inline-block rounded-full bg-amber/25 px-3 py-1 text-xs font-semibold text-navy">{t('cases.unverifiedLabel')}</span>
      </p>
      <p className="mt-3 text-xs text-navy/60">
        {c.platform}
        {c.postedDate ? ` · ${c.postedDate}` : ''}
        {' · '}
        <a href={c.sourceUrl} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline">{t('cases.viewSource')}</a>
      </p>
    </article>
  );
}
