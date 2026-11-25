'use client';
import { useApp } from '../lib/store';
import { SchoolReview } from '../lib/types';

/**
 * One netizen-shared school review, dark variant for the navy
 * FanCarousel. Shows only what the poster shared: institution,
 * programme, level, their own words, platform and source link.
 * Missing fields render nothing — never invented. Every card carries
 * the "not officially verified" label. No stars anywhere — no rating
 * data exists (see docs/SCHOOL_REVIEWS.md).
 *
 * The quote is shown in the collector's Chinese translation in the
 * zh-CN locale (reference only); every other locale shows the verbatim
 * English original.
 */
export function ReviewCard({ r }: { r: SchoolReview }) {
  const { t, locale } = useApp();
  const showZh = locale === 'zh-CN' && !!r.quoteZh;
  const text = showZh ? (r.quoteZh as string) : r.quote;
  return (
    <article className="h-full rounded-2xl border border-white/15 bg-white/5 p-5 text-white">
      <p className="text-sm font-semibold text-amber">{r.institution}</p>
      {r.programme && <h3 className="mt-1 text-lg font-bold" dir="auto">{r.programme}</h3>}
      {r.level && (
        <p className="mt-1 text-sm text-white/70">
          {r.level === 'undergraduate' ? t('cases.filterUg') : r.level === 'taught_masters' ? t('cases.filterTm') : r.level}
        </p>
      )}
      <p className="mt-2 text-sm leading-relaxed text-white/85" lang={showZh ? 'zh-CN' : (r.quoteLang ?? 'en')} dir="auto">“{text}”</p>
      <p className="mt-3">
        <span className="inline-block rounded-full bg-amber/20 px-3 py-1 text-xs font-semibold text-amber">{t('cases.unverifiedLabel')}</span>
      </p>
      <p className="mt-3 text-xs text-white/60">
        {[r.authorDisplay, r.source, r.postedDate].filter(Boolean).join(' · ')}
        {r.sourceUrl && (
          <>
            {' · '}
            <a href={r.sourceUrl} target="_blank" rel="noreferrer" className="font-semibold text-teal-200 underline">{t('cases.viewSource')}</a>
          </>
        )}
      </p>
    </article>
  );
}
