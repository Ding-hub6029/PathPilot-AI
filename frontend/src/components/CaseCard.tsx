'use client';
import { useApp } from '../lib/store';
import { SuccessCase } from '../lib/types';

/**
 * One netizen-shared success case. Shows only what the poster shared:
 * offer, undergraduate background, scores, key experience, platform and
 * source link. Missing fields render nothing — never invented, never a
 * placeholder value. Every card carries the "not officially verified"
 * label; there is no contact info and no agency case in the data.
 * No stars anywhere — there is no rating data.
 *
 * `dark` renders the same content on the navy FanCarousel block
 * (dark-grey card, 1px translucent border, light text).
 */
export function CaseCard({ c, dark = false }: { c: SuccessCase; dark?: boolean }) {
  const { t } = useApp();
  return (
    <article className={`h-full rounded-2xl border p-5 ${dark ? 'border-white/15 bg-white/5 text-white' : 'card-lift border-navy/10 bg-white card-surface'}`}>
      <p className={`text-sm font-semibold ${dark ? 'text-amber' : 'text-teal'}`}>{c.offerInstitution}</p>
      <h3 className="mt-1 text-lg font-bold" dir="auto">{c.offerProgramme ?? c.offerInstitution}</h3>
      <p className={`mt-1 text-sm ${dark ? 'text-white/70' : 'text-navy/70'}`}>
        {c.offerLevel === 'undergraduate' ? t('cases.filterUg') : t('cases.filterTm')}
        {c.intake ? ` · ${c.intake}` : ''}
      </p>
      <dl className="mt-3 space-y-2 text-sm">
        {(c.undergradInstitution || c.undergradMajor || c.gpa) && (
          <div>
            <dt className="font-semibold">{t('cases.background')}</dt>
            <dd className={dark ? 'text-white/75' : 'text-navy/75'} dir="auto">
              {[c.undergradInstitution, c.undergradMajor, c.gpa].filter(Boolean).join(' · ')}
            </dd>
          </div>
        )}
        {c.languageScores && (
          <div>
            <dt className="font-semibold">{t('cases.scores')}</dt>
            <dd className={dark ? 'text-white/75' : 'text-navy/75'} dir="ltr">{c.languageScores}</dd>
          </div>
        )}
        {c.keyExperience && (
          <div>
            <dt className="font-semibold">{t('cases.experience')}</dt>
            <dd className={dark ? 'text-white/75' : 'text-navy/75'} dir="auto">{c.keyExperience}</dd>
          </div>
        )}
      </dl>
      <p className="mt-3">
        <span className={`inline-block rounded-full px-3 py-1 text-xs font-semibold ${dark ? 'bg-amber/20 text-amber' : 'bg-amber/25 text-navy'}`}>{t('cases.unverifiedLabel')}</span>
      </p>
      <p className={`mt-3 text-xs ${dark ? 'text-white/60' : 'text-navy/60'}`}>
        {c.platform}
        {c.postedDate ? ` · ${c.postedDate}` : ''}
        {' · '}
        <a href={c.sourceUrl} target="_blank" rel="noreferrer" className={`font-semibold underline ${dark ? 'text-teal-200' : 'text-teal-dark'}`}>{t('cases.viewSource')}</a>
      </p>
    </article>
  );
}
