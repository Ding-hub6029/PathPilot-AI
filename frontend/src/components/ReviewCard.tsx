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
 *
 * Round 8: the "not officially verified" pill is ~45 chars in English,
 * i.e. right at the 300px content width of a 340px carousel card, so it
 * used to run past the card edge and read as truncated. It now wraps
 * cleanly inside the pill (never clipped) at a slightly smaller size,
 * and the footer is a wrapping flex row whose "view original post" link
 * is nowrap — wrapping happens between segments, never inside the link.
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
        <span className="inline-block max-w-full whitespace-normal break-words rounded-full bg-amber/20 px-3 py-1 text-[11px] font-semibold leading-snug text-amber">{t('cases.unverifiedLabel')}</span>
      </p>
      <p className="mt-3 flex flex-wrap items-baseline gap-x-1 text-xs text-white/60">
        <span>{[r.authorDisplay, r.source, r.postedDate].filter(Boolean).join(' · ')}</span>
        {r.sourceUrl && (
          <>
            <span aria-hidden="true">·</span>
            <a href={r.sourceUrl} target="_blank" rel="noreferrer" className="whitespace-nowrap font-semibold text-teal-200 underline">{t('cases.viewSource')}</a>
          </>
        )}
      </p>
    </article>
  );
}
