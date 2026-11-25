'use client';
import { useApp } from '../lib/store';
import { NEWS_ITEMS, POLICY_ITEMS } from '../lib/news';

/**
 * Latest news & policy, link-out only. Items are curated from verified
 * official pages and feeds (NUS Newsroom RSS, British Council Study UK,
 * UCL News, NTU Alumni, Imperial news feeds, UCAS, GOV.UK, ICA). Titles
 * are the sources' own headlines, shown in English like evidence
 * excerpts; summaries are localised. No article text is copied and no
 * story is invented. Policy cards carry the "check the official page"
 * note.
 */
export function NewsSection() {
  const { t } = useApp();
  return (
    <>
      <section className="section-rule mt-10" aria-labelledby="home-news-title">
        <h2 id="home-news-title" className="line-mask text-2xl font-bold"><span>{t('home.newsTitle')}</span></h2>
        <p className="mt-1 text-sm text-navy/70">{t('home.newsSub')}</p>
        <p className="mt-1 text-xs text-navy/60">{t('evidence.englishOnly')} · {t('home.newsChecked')}</p>
        <ul className="mt-4 grid gap-4 md:grid-cols-2">
          {NEWS_ITEMS.map((n) => (
            <li key={n.id} className="card-lift rounded-2xl border border-navy/10 bg-white p-5 shadow-sm">
              <p className="text-sm font-semibold text-teal">{n.source}{n.date ? ` · ${n.date}` : ''}</p>
              <h3 className="mt-1 font-bold" lang="en" dir="ltr">{n.title}</h3>
              <p className="mt-2 text-sm text-navy/75">{t(n.summaryKey)}</p>
              <p className="mt-3">
                <a href={n.url} target="_blank" rel="noreferrer" className="btn-press inline-block rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy">{t('home.newsRead')}</a>
              </p>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-10" aria-labelledby="home-policy-title">
        <h2 id="home-policy-title" className="text-2xl font-bold">{t('home.policyTitle')}</h2>
        <p className="mt-1 text-sm text-navy/70">{t('home.policyNote')}</p>
        <ul className="mt-4 grid gap-4 md:grid-cols-3">
          {POLICY_ITEMS.map((n) => (
            <li key={n.id} className="card-lift rounded-2xl border border-navy/10 bg-white p-5 shadow-sm">
              <p className="text-sm font-semibold text-teal">{n.source}</p>
              <h3 className="mt-1 font-bold" lang="en" dir="ltr">{n.title}</h3>
              <p className="mt-2 text-sm text-navy/75">{t(n.summaryKey)}</p>
              <p className="mt-3">
                <a href={n.url} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline">{t('home.newsRead')}</a>
              </p>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
