'use client';
import { useApp } from '../lib/store';
import { SuccessCase } from '../lib/types';

/**
 * One netizen-shared success case — one card per applicant (Round 8
 * dedupe). Shows only what the poster shared: offer(s), undergraduate
 * background, scores, key experience, platform and source link. Missing
 * fields render nothing — never invented, never a placeholder value.
 * Every card carries the "not officially verified" label; there is no
 * contact info and no agency case in the data. No stars anywhere — there
 * is no rating data.
 *
 * Single-offer cards keep the original layout (institution eyebrow,
 * programme heading). Multi-offer cards list every offer the applicant
 * shared, each with its own programme / intake / note, so one person is
 * never counted as several applicants.
 *
 * `dark` renders the same content on the navy FanCarousel block
 * (dark-grey card, 1px translucent border, light text).
 */
export function CaseCard({ c, dark = false }: { c: SuccessCase; dark?: boolean }) {
  const { t, tf } = useApp();
  const levelLabel = (level: string) =>
    level === 'undergraduate' ? t('cases.filterUg') : t('cases.filterTm');
  const multi = c.offers.length > 1;
  // Applicant-level experience, or the single offer's own note.
  const experience = c.keyExperience ?? (!multi ? (c.offers[0]?.note ?? null) : null);
  return (
    <article className={`h-full rounded-2xl border p-5 ${dark ? 'border-white/15 bg-white/5 text-white' : 'card-lift border-navy/10 bg-white card-surface'}`}>
      {multi ? (
        <>
          <p className={`text-sm font-semibold ${dark ? 'text-amber' : 'text-teal'}`}>{tf('cases.offersCount', { count: c.offers.length })}</p>
          <ul className="mt-2 space-y-3">
            {c.offers.map((o, i) => (
              <li key={i} className={`rounded-xl border px-3 py-2 ${dark ? 'border-white/10 bg-white/5' : 'border-navy/10 bg-navy/[0.03]'}`}>
                <p className="text-sm font-semibold" dir="auto">{o.institution}</p>
                <p className={`text-sm ${dark ? 'text-white/85' : 'text-navy/85'}`} dir="auto">
                  {o.programme ?? o.institution}
                  {` · ${levelLabel(o.level)}`}
                  {o.intake ? ` · ${o.intake}` : ''}
                </p>
                {o.note && (
                  <p className={`mt-1 text-sm ${dark ? 'text-white/75' : 'text-navy/75'}`} dir="auto">{o.note}</p>
                )}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <>
          <p className={`text-sm font-semibold ${dark ? 'text-amber' : 'text-teal'}`}>{c.offers[0]?.institution}</p>
          <h3 className="mt-1 text-lg font-bold" dir="auto">{c.offers[0]?.programme ?? c.offers[0]?.institution}</h3>
          <p className={`mt-1 text-sm ${dark ? 'text-white/70' : 'text-navy/70'}`}>
            {levelLabel(c.offers[0]?.level ?? 'taught_masters')}
            {c.offers[0]?.intake ? ` · ${c.offers[0].intake}` : ''}
          </p>
        </>
      )}
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
        {experience && (
          <div>
            <dt className="font-semibold">{t('cases.experience')}</dt>
            <dd className={dark ? 'text-white/75' : 'text-navy/75'} dir="auto">{experience}</dd>
          </div>
        )}
      </dl>
      <p className="mt-3">
        <span className={`inline-block max-w-full whitespace-normal break-words rounded-full px-3 py-1 text-[11px] font-semibold leading-snug ${dark ? 'bg-amber/20 text-amber' : 'bg-amber/25 text-navy'}`}>{t('cases.unverifiedLabel')}</span>
      </p>
      <p className={`mt-3 flex flex-wrap items-baseline gap-x-1 text-xs ${dark ? 'text-white/60' : 'text-navy/60'}`}>
        <span>{[c.platform, c.postedDate, c.sourceRef].filter(Boolean).join(' · ')}</span>
        <span aria-hidden="true">·</span>
        {c.sourceUrl && (
          <a href={c.sourceUrl} target="_blank" rel="noreferrer" className={`whitespace-nowrap font-semibold underline ${dark ? 'text-teal-200' : 'text-teal-dark'}`}>{t('cases.viewSource')}</a>
        )}
      </p>
    </article>
  );
}
