'use client';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { fetchRankings, RankingsResult } from '../../lib/api';
import { displayCountryCode, displayCountryName, displayInstitutionName } from '../../lib/rankings';
import { crestFor, monogramFor } from '../../lib/crests';
import { useApp } from '../../lib/store';
import { RankingEntry } from '../../lib/types';

/**
 * Standalone rankings page (Day 3, FR15/FR16).
 * Three providers, top 100 institutions each, world ranks only. Providers are
 * never averaged into one score (BR15); world and subject ranks are
 * never mixed — this build ships world ranks only, so a subject filter
 * yields an empty state with an explanation instead of an invented rank.
 * Compare is per provider+edition: rows are providers, columns are the
 * selected institutions (max 3), so a world rank is never compared with
 * a national rank and a subject rank is never presented as a course rank.
 * Institution names link to their institution detail page.
 */
export default function RankingsPage() {
  const { t, locale } = useApp();
  const [data, setData] = useState<RankingsResult | null>(null);
  const [provider, setProvider] = useState('all');
  const [rankType, setRankType] = useState('world');
  const [country, setCountry] = useState('all');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => {
    fetchRankings().then(setData).catch(() => undefined);
  }, []);

  const institutions = data?.institutions ?? [];
  const entries = data?.entries ?? [];
  const providers = data?.providers ?? [];

  // Country filter options come from the data itself (25 countries in the
  // top-100 set), never a hard-coded list.
  const countries = useMemo(() => {
    const byCode = new Map<string, string>();
    for (const inst of institutions) byCode.set(inst.country, inst.country_name);
    return [...byCode.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [institutions]);

  const filteredInstitutions = useMemo(() => {
    return institutions.filter((inst) => {
      if (country !== 'all' && inst.country !== country) return false;
      // Search matches the English official name and the Chinese display
      // name, so searching 牛津 finds Oxford.
      if (query.trim()) {
        const q = query.trim().toLowerCase();
        const hay = `${inst.official_name} ${inst.name_zh ?? ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [institutions, country, query]);

  const visibleEntries = useMemo(() => {
    // Subject ranks were not verified for this build: a subject filter
    // returns nothing rather than inventing a subject rank (T21).
    if (rankType !== 'world') return [] as RankingEntry[];
    return entries.filter((e) => {
      if (provider !== 'all' && e.provider !== provider) return false;
      if (!filteredInstitutions.some((i) => i.id === e.institution_id)) return false;
      return true;
    });
  }, [entries, provider, rankType, filteredInstitutions]);

  // Institutions arrive in id order (alphabetical), not rank order — sort
  // the cards top-to-bottom by rank: the selected provider's rank when one
  // provider is chosen, otherwise the institution's best rank across the
  // visible providers. Unranked institutions go last.
  const rankValue = (e?: RankingEntry): number => {
    if (!e || e.verification_status !== 'verified') return Number.POSITIVE_INFINITY;
    const m = /^=?(\d+)/.exec(e.rank_display ?? '');
    return m ? parseInt(m[1], 10) : Number.POSITIVE_INFINITY;
  };
  const sortedInstitutions = useMemo(() => {
    const list = [...filteredInstitutions];
    list.sort((a, b) => {
      const ra = Math.min(...visibleEntries.filter((e) => e.institution_id === a.id).map(rankValue));
      const rb = Math.min(...visibleEntries.filter((e) => e.institution_id === b.id).map(rankValue));
      if (ra !== rb) return ra - rb;
      return a.official_name.localeCompare(b.official_name);
    });
    return list;
  }, [filteredInstitutions, visibleEntries]);

  const toggleSelect = (id: string) => {
    setSelected((cur) => {
      if (cur.includes(id)) return cur.filter((x) => x !== id);
      if (cur.length >= 3) return cur;
      return [...cur, id];
    });
  };

  const compareInstitutions = selected
    .map((id) => institutions.find((i) => i.id === id))
    .filter((i): i is NonNullable<typeof i> => Boolean(i));

  const entryFor = (providerId: string, institutionId: string) =>
    entries.find((e) => e.provider === providerId && e.institution_id === institutionId);

  return (
    <div className="page-enter mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-2xl font-bold">{t('rankings.title')}</h1>
      <p className="mt-2 text-navy/70">{t('rankings.subtitle')}</p>
      <p className="mt-1 text-sm font-semibold text-navy/70">{t('rankings.noCompare')}</p>

      <section className="mt-6" aria-labelledby="prov-title">
        <h2 id="prov-title" className="text-xl font-bold">{t('rankings.providers')}</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {providers.map((p) => (
            <article key={p.id} className="rounded-2xl border border-navy/10 bg-white p-4 shadow-sm">
              <p className="font-bold">{p.name}</p>
              <p className="mt-1 text-sm text-navy/70">{t('rankings.edition')}: {p.edition_label}</p>
              <p className="mt-3 text-sm">
                <a href={p.entry_url} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline">{t('rankings.officialTable')}</a>
                {p.methodology_url && (
                  <>
                    {' · '}
                    <a href={p.methodology_url} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline">{t('rankings.methodology')}</a>
                  </>
                )}
              </p>
              <p className="mt-2 text-xs text-navy/60">{p.rights_note}</p>
              {p.id === 'qs' && p.attribution && (
                <p className="mt-2 text-xs text-navy/60" lang="en" dir="ltr">{p.attribution}</p>
              )}
            </article>
          ))}
        </div>
      </section>

      <section className="mt-8" aria-labelledby="filter-title">
        <h2 id="filter-title" className="text-xl font-bold">{t('rankings.compare')}</h2>
        <p className="mt-1 text-sm text-navy/70">{t('rankings.compareHint')}</p>
        <div className="mt-3 flex flex-wrap items-end gap-3 rounded-2xl border border-navy/10 bg-white p-4 shadow-sm">
          <label className="text-sm font-semibold">
            {t('rankings.provider')}
            <select value={provider} onChange={(e) => setProvider(e.target.value)} className="mt-1 block rounded-lg border border-navy/25 px-2 py-1.5 font-normal">
              <option value="all">{t('rankings.allProviders')}</option>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>{p.short_name} · {p.edition_label}</option>
              ))}
            </select>
          </label>
          <label className="text-sm font-semibold">
            {t('rankings.rank')}
            <select value={rankType} onChange={(e) => setRankType(e.target.value)} className="mt-1 block rounded-lg border border-navy/25 px-2 py-1.5 font-normal">
              <option value="world">{t('rankings.world')}</option>
              <option value="subject">{t('rankings.subject')}</option>
            </select>
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
          <button
            type="button"
            onClick={() => { setProvider('all'); setRankType('world'); setCountry('all'); setQuery(''); }}
            className="btn-press rounded-full border border-navy/25 px-4 py-2 text-sm font-semibold"
          >
            {t('rankings.clearFilters')}
          </button>
        </div>

        {rankType !== 'world' && (
          <p role="status" className="mt-4 rounded-lg bg-amber/20 p-3 text-sm font-semibold">{t('rankings.subjectEmpty')}</p>
        )}
        {rankType === 'world' && visibleEntries.length === 0 && (
          <p role="status" className="mt-4 rounded-lg bg-white p-3 text-sm font-semibold">{t('rankings.noResults')}</p>
        )}

        <ol className="mt-4 flex flex-col gap-3">
          {sortedInstitutions.map((inst, idx) => {
            const instEntries = visibleEntries.filter((e) => e.institution_id === inst.id);
            if (rankType === 'world' && instEntries.length === 0) return null;
            // Rank shown in the row is the same rank the list is sorted by:
            // the selected provider's rank when one provider is chosen,
            // otherwise the institution's best rank across the visible
            // providers (rankValue is the sort key used above).
            const bestEntry = [...instEntries].sort((a, b) => rankValue(a) - rankValue(b))[0];
            const crest = crestFor(inst.id);
            return (
              <li key={inst.id} className="anim-fade-up flex items-center gap-3 rounded-2xl border border-navy/10 bg-white p-3 shadow-sm sm:gap-4 sm:p-4" style={{ animationDelay: `${(idx % 6) * 60}ms` }}>
                <span className="w-12 shrink-0 text-center text-lg font-bold text-navy" dir="ltr">
                  {bestEntry ? bestEntry.rank_display : '—'}
                </span>
                {crest && 'src' in crest ? (
                  <span className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-navy/10 bg-white" aria-hidden="true">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={crest.src} alt="" className="h-12 w-12 object-contain" />
                  </span>
                ) : (
                  <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-[#0B1F3A] text-base font-bold text-white" aria-hidden="true">
                    {monogramFor(inst.official_name)}
                  </span>
                )}
                <div className="min-w-0 flex-1">
                  <p className="font-bold">
                    <Link href={`/institutions/${inst.id}`} className="text-teal-dark underline">
                      {displayInstitutionName(inst, locale)}
                    </Link>
                  </p>
                  <p className="text-sm text-navy/60">{displayCountryName(inst, t)}</p>
                  <ul className="mt-2 flex flex-wrap gap-1.5">
                    {providers
                      .filter((p) => provider === 'all' || p.id === provider)
                      .map((p) => {
                        const e = instEntries.find((x) => x.provider === p.id);
                        if (!e) return null;
                        return (
                          <li key={p.id} className="rounded-full bg-navy/5 px-2.5 py-1 text-xs font-semibold">
                            <span dir="ltr">{p.short_name} · {p.edition_label}: {e.verification_status === 'verified' ? e.rank_display : t('rankings.unavailableShort')}</span>
                            {e.verification_status === 'verified' && e.rank_kind === 'tie' && (
                              <span className="ms-1 font-normal text-navy/60">{t('rankings.tieNote')}</span>
                            )}
                            {e.verification_status === 'verified' && e.score !== null && (
                              <span className="ms-1 font-normal text-navy/60">{t('rankings.score')}: {e.score}</span>
                            )}
                          </li>
                        );
                      })}
                  </ul>
                  {rankType === 'world' && (
                    <p className="mt-1.5 text-xs text-navy/60">{t('rankings.subjectNote')}</p>
                  )}
                </div>
                <div className="shrink-0 text-end">
                  <label className="flex items-center gap-1 text-sm font-semibold">
                    <input
                      type="checkbox"
                      checked={selected.includes(inst.id)}
                      onChange={() => toggleSelect(inst.id)}
                      disabled={!selected.includes(inst.id) && selected.length >= 3}
                    />
                    {t('rankings.compare')}
                  </label>
                  {selected.length >= 3 && !selected.includes(inst.id) && (
                    <p className="mt-1 text-xs text-navy/60">{t('rankings.maxThree')}</p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </section>

      {compareInstitutions.length >= 2 && (
        <section className="mt-8" aria-labelledby="cmp-title">
          <h2 id="cmp-title" className="text-xl font-bold">{t('rankings.compare')}</h2>
          <p className="mt-1 text-sm text-navy/70">{t('rankings.noCompare')}</p>
          <div className="mt-3 overflow-x-auto rounded-2xl border border-navy/10 bg-white shadow-sm">
            <table className="w-full min-w-[480px] text-sm">
              <thead>
                <tr className="border-b border-navy/10 text-start">
                  <th scope="col" className="p-3 text-start">{t('rankings.provider')}</th>
                  {compareInstitutions.map((inst) => (
                    <th key={inst.id} scope="col" className="p-3 text-start">
                      <Link href={`/institutions/${inst.id}`} className="text-teal-dark underline">
                        {displayInstitutionName(inst, locale)}
                      </Link>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {providers.map((p) => (
                  <tr key={p.id} className="border-t border-navy/5">
                    <th scope="row" className="p-3 text-start font-semibold">{p.short_name} · {p.edition_label}</th>
                    {compareInstitutions.map((inst) => {
                      const e = entryFor(p.id, inst.id);
                      return (
                        <td key={inst.id} className="p-3">
                          {!e || e.verification_status !== 'verified' ? (
                            <span className="font-semibold text-amber-dark">{t('rankings.unavailableShort')}</span>
                          ) : (
                            <span className="font-bold" dir="ltr">{e.rank_display}</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-navy/60">
            {t('rankings.tieNote')} {t('rankings.subjectNote')}
          </p>
        </section>
      )}

      {data && !data.live && (
        <p className="mt-6 text-sm text-navy/60">{t('rankings.offlineNote')}</p>
      )}
      <p className="mt-2 text-xs text-navy/60" lang="en" dir="ltr">
        Source: QS Quacquarelli Symonds (www.qs.com). With permission. Copyright © QS Quacquarelli Symonds Ltd.
      </p>
    </div>
  );
}
