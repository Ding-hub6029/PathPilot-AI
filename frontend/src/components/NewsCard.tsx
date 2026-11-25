'use client';
import { useApp } from '../lib/store';
import { NewsItem } from '../lib/news';

/**
 * One news / policy link-out card, dark variant for the navy
 * FanCarousel. Title is the source's own headline (English, like
 * evidence excerpts); the one-line summary is localised. No article
 * text is copied and no story is invented. No stars — there is no
 * rating data.
 */
export function NewsCard({ n }: { n: NewsItem }) {
  const { t } = useApp();
  return (
    <article className="h-full rounded-2xl border border-white/15 bg-white/5 p-5 text-white">
      <p className="text-sm font-semibold text-amber">{n.source}{n.date ? ` · ${n.date}` : ''}</p>
      <h3 className="mt-1 font-bold" lang="en" dir="ltr">{n.title}</h3>
      <p className="mt-2 text-sm text-white/75">{t(n.summaryKey)}</p>
      <p className="mt-3">
        <a href={n.url} target="_blank" rel="noreferrer" className="btn-press inline-block rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy">{t('home.newsRead')}</a>
      </p>
    </article>
  );
}
