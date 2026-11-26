'use client';
import { useMemo, useState } from 'react';
import { RANKING_ENTRIES, RANKING_INSTITUTIONS, displayCountryCode, displayCountryName, displayInstitutionName } from '../../lib/rankings';
import { crestFor, monogramFor } from '../../lib/crests';
import { useApp } from '../../lib/store';
import { RankingEntry } from '../../lib/types';
import { ViewTransitionLink } from '../../components/ViewTransitionLink';
import { vtRef } from '../../lib/viewTransition';

/**
 * Institution index (Round 8). Previously there was no /institutions
 * index — only /institutions/[id] — so /universities 404'd with nowhere
 * to go and the institution list only existed inside /rankings. This
 * page lists all 148 ranked institutions with crest, country and best
 * world rank, each linking to its detail page. Data is the local mirror
 * (identical to the verified backend data), so the page renders instantly.
 */
const rankValue = (e?: RankingEntry): number => {
  if (!e || e.verification_status !== 'verified') return Number.POSITIVE_INFINITY;
  const m = /^=?(\d+)/.exec(e.rank_display ?? '');
  return m ? parseInt(m[1], 10) : Number.POSITIVE_INFINITY;
};

export default function InstitutionsPage() {
  const { t, tf, locale } = useApp();
  const [country, setCountry] = useState('all');
  const [query, setQuery] = useState('');

  const countries = useMemo(() => {
    const byCode = new Map<string, string>();
    for (const inst of RANKING_INSTITUTIONS) byCode.set(inst.country, inst.country_name);
    return [...byCode.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, []);

  const filtered = useMemo(() => {
    const list = RANKING_INSTITUTIONS.filter((inst) => {
      if (country !== 'all' && inst.country !== country) return false;
      if (query.trim()) {
        const q = query.trim().toLowerCase();
        const hay = `${inst.official_name} ${inst.name_zh ?? ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    // Best world rank across the three providers first, then name.
    list.sort((a, b) => {
      const ra = Math.min(...RANKING_ENTRIES.filter((e) => e.institution_id === a.id).map(rankValue));
      const rb = Math.min(...RANKING_ENTRIES.filter((e) => e.institution_id === b.id).map(rankValue));
      if (ra !== rb) return ra - rb;
      return a.official_name.localeCompare(b.official_name);
    });
    return list;
  }, [country, query]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="line-mask text-2xl font-bold"><span>{t('institutions.title')}</span></h1>
      <p className="mt-2 text-navy/70">{t('institutions.subtitle')}</p>
      <p className="mt-2 text-sm text-navy/60" role="status">
        {tf('institutions.count', { count: filtered.length })}
      </p>

      <div className="mt-4 flex flex-wrap items-end gap-3 rounded-2xl border border-navy/10 bg-white p-4 shadow-sm">
        <label className="text-sm font-semibold">
          {t('rankings.search')}
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('rankings.searchPlaceholder')}
            className="mt-1 block w-64 rounded-lg border border-navy/25 px-2 py-1.5 font-normal"
          />
        </label>
        <label className="text-sm font-semibold">
          {t('rankings.country')}
          <select value={country} onChange={(e) => setCountry(e.target.value)} className="mt-1 block rounded-lg border border-navy/25 px-2 py-1.5 font-normal">
            <option value="all">{t('rankings.allCountries')}</option>
            {countries.map(([code, name]) => (
              <option key={code} value={code}>{displayCountryCode(code, name, t)}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => { setCountry('all'); setQuery(''); }}
          className="btn-press rounded-full border border-navy/25 px-4 py-2 text-sm font-semibold"
        >
          {t('rankings.clearFilters')}
        </button>
      </div>

      {filtered.length === 0 && (
        <p role="status" className="mt-4 rounded-lg bg-white p-3 text-sm font-semibold">{t('rankings.noResults')}</p>
      )}

      <ol className="mt-4 flex flex-col gap-3">
        {filtered.map((inst) => {
          const instEntries = RANKING_ENTRIES.filter((e) => e.institution_id === inst.id);
          const bestEntry = [...instEntries].sort((a, b) => rankValue(a) - rankValue(b))[0];
          const crest = crestFor(inst.id);
          return (
            <li key={inst.id} className="flex items-center gap-3 rounded-2xl border border-navy/10 bg-white p-3 shadow-sm sm:gap-4 sm:p-4">
              <span className="w-12 shrink-0 text-center text-lg font-bold text-navy" dir="ltr">
                {bestEntry ? bestEntry.rank_display : '—'}
              </span>
              {crest && 'src' in crest ? (
                <span ref={vtRef(`crest-${inst.id}`)} className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-navy/10 bg-white" aria-hidden="true">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={crest.src} alt="" className="h-12 w-12 object-contain" />
                </span>
              ) : (
                <span ref={vtRef(`crest-${inst.id}`)} className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-[#0B1F3A] text-base font-bold text-white" aria-hidden="true">
                  {monogramFor(inst.official_name)}
                </span>
              )}
              <div className="min-w-0 flex-1">
                <p className="font-bold">
                  <ViewTransitionLink href={`/institutions/${inst.id}`} className="text-teal-dark underline">
                    {displayInstitutionName(inst, locale)}
                  </ViewTransitionLink>
                </p>
                <p className="text-sm text-navy/60">{displayCountryName(inst, t)}</p>
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {instEntries.map((e) => (
                    <li key={e.provider} className="rounded-full bg-navy/5 px-2.5 py-1 text-xs font-semibold">
                      <span dir="ltr">{e.provider.toUpperCase()} {e.edition_label}: {e.verification_status === 'verified' ? e.rank_display : t('rankings.unavailableShort')}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
