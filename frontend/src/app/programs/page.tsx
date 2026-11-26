'use client';
import { useEffect, useMemo, useState } from 'react';
import { allPrograms, fetchPrograms, mergePrograms } from '../../lib/api';
import { useBackendStatus } from '../../lib/backendStatus';
import { RANKING_INSTITUTIONS, displayCountryCode, displayProgramInstitutionName } from '../../lib/rankings';
import { displayProgramName } from '../../lib/programs';
import { formatDuration, formatFeeItems, formatIntake } from '../../lib/format';
import { useApp } from '../../lib/store';
import { Program } from '../../lib/types';
import { ViewTransitionLink } from '../../components/ViewTransitionLink';

/**
 * Programme browse page (Round 8). The old /programs route was a 404 —
 * there was no way to browse programmes, so Swiss programmes (20 across
 * ETH Zurich, University of Zurich and EPFL) were unfindable outside the
 * wizard. This page lists the full catalogue: the 8 fully verified v2
 * programmes plus the 881 expansion programmes collected from official
 * pages, with search + country/level filters.
 *
 * Data renders instantly from the local merged list (allPrograms: v2 +
 * expansion mirror); the live backend only refreshes it in the
 * background via mergePrograms, so a sleeping backend never empties
 * the page. Expansion programmes link to their /programs/[id] detail
 * page, which resolves them from the same merged list.
 */
const PAGE_SIZE = 100;

const LEVEL_KEYS: Record<string, string> = {
  undergraduate: 'cases.filterUg',
  taught_masters: 'cases.filterTm',
  foundation: 'institution.filterFoundation',
  joint_honours: 'institution.filterJointHonours',
};

const INSTITUTION_IDS = new Set(RANKING_INSTITUTIONS.map((i) => i.id));

export default function ProgramsPage() {
  const { t, tf, locale } = useApp();
  // Round 9 (R9): the offline note reads the one shared backend
  // status — the old `live` flag started false and showed
  // "实时后端尚未连接" on first paint even while the backend was up.
  const backendStatus = useBackendStatus();
  const [programs, setPrograms] = useState<Program[]>(() => allPrograms());
  const [country, setCountry] = useState('all');
  const [level, setLevel] = useState('all');
  const [query, setQuery] = useState('');
  const [shown, setShown] = useState(PAGE_SIZE);

  useEffect(() => {
    let cancelled = false;
    fetchPrograms({ limit: 20 })
      .then((res) => {
        if (cancelled) return;
        // The live list is only the v2 page; mergePrograms keeps every
        // local expansion programme and lets live entries win on id.
        if (res.live) setPrograms(mergePrograms(res.programs));
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  // Country filter options come from the data itself, never a hard-coded
  // list (23 countries in the catalogue).
  const countries = useMemo(() => {
    const byCode = new Map<string, string>();
    for (const p of programs) {
      if (!byCode.has(p.country)) byCode.set(p.country, p.country);
    }
    return [...byCode.keys()].sort();
  }, [programs]);

  const filtered = useMemo(() => {
    const list = programs.filter((p) => {
      if (country !== 'all' && p.country !== country) return false;
      if (level !== 'all' && p.degreeLevel !== level) return false;
      if (query.trim()) {
        const q = query.trim().toLowerCase();
        const hay = [
          p.officialName,
          p.nameLocalized?.['zh-CN'] ?? '',
          p.nameLocalized?.['en'] ?? '',
          p.institution,
          p.city ?? '',
          p.subject,
        ].join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    list.sort((a, b) =>
      a.institution.localeCompare(b.institution) || a.officialName.localeCompare(b.officialName));
    return list;
  }, [programs, country, level, query]);

  const visible = filtered.slice(0, shown);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="line-mask text-2xl font-bold"><span>{t('programs.title')}</span></h1>
      <p className="mt-2 text-navy/70">{t('programs.subtitle')}</p>
      <p className="mt-2 text-sm text-navy/60" role="status">
        {tf('programs.resultsCount', { count: filtered.length })}
        {backendStatus === 'checking' && <span className="ms-2 font-semibold">{t('r9pages.backendChecking')}</span>}
        {backendStatus === 'offline' && <span className="ms-2 font-semibold">{t('programs.offlineNote')}</span>}
      </p>

      <div className="mt-4 flex flex-wrap items-end gap-3 rounded-2xl border border-navy/10 bg-white p-4 shadow-sm">
        <label className="text-sm font-semibold">
          {t('programs.search')}
          <input
            type="search"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setShown(PAGE_SIZE); }}
            placeholder={t('programs.searchPlaceholder')}
            className="mt-1 block w-64 rounded-lg border border-navy/25 px-2 py-1.5 font-normal"
          />
        </label>
        <label className="text-sm font-semibold">
          {t('programs.country')}
          <select value={country} onChange={(e) => { setCountry(e.target.value); setShown(PAGE_SIZE); }} className="mt-1 block rounded-lg border border-navy/25 px-2 py-1.5 font-normal">
            <option value="all">{t('programs.allCountries')}</option>
            {countries.map((code) => (
              <option key={code} value={code}>{displayCountryCode(code, code, t)}</option>
            ))}
          </select>
        </label>
        <label className="text-sm font-semibold">
          {t('programs.level')}
          <select value={level} onChange={(e) => { setLevel(e.target.value); setShown(PAGE_SIZE); }} className="mt-1 block rounded-lg border border-navy/25 px-2 py-1.5 font-normal">
            <option value="all">{t('programs.allLevels')}</option>
            {Object.entries(LEVEL_KEYS).map(([value, key]) => (
              <option key={value} value={value}>{t(key)}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => { setCountry('all'); setLevel('all'); setQuery(''); setShown(PAGE_SIZE); }}
          className="btn-press rounded-full border border-navy/25 px-4 py-2 text-sm font-semibold"
        >
          {t('rankings.clearFilters')}
        </button>
      </div>

      {filtered.length === 0 && (
        <p role="status" className="mt-4 rounded-lg bg-white p-3 text-sm font-semibold">{t('programs.noResults')}</p>
      )}

      <ol className="mt-4 flex flex-col gap-3">
        {visible.map((p) => {
          const fees = formatFeeItems(p, t, locale);
          const instName = displayProgramInstitutionName(p.institution, locale);
          return (
            <li key={p.id} className="rounded-2xl border border-navy/10 bg-white p-4 shadow-sm">
              <p className="font-bold">
                <ViewTransitionLink href={`/programs/${p.id}`} className="text-teal-dark underline">
                  {displayProgramName(p, locale)}
                </ViewTransitionLink>
              </p>
              <p className="mt-1 text-sm text-navy/60">
                {INSTITUTION_IDS.has(p.institutionId) ? (
                  <ViewTransitionLink href={`/institutions/${p.institutionId}`} className="font-semibold text-teal-dark underline">
                    {instName}
                  </ViewTransitionLink>
                ) : (
                  <span className="font-semibold">{instName}</span>
                )}
                {' · '}{displayCountryCode(p.country, p.country, t)}
                {p.city ? ` · ${p.city}` : ''}
              </p>
              <p className="mt-1 text-sm text-navy/75">
                {t(LEVEL_KEYS[p.degreeLevel] ?? 'cases.filterTm')}
                {' · '}{formatIntake(p, t)}
                {' · '}{formatDuration(p, t)}
                {' · '}{fees || t('institution.feeNotPublished')}
              </p>
            </li>
          );
        })}
      </ol>

      {shown < filtered.length && (
        <p className="mt-4 text-center">
          <button
            type="button"
            onClick={() => setShown((n) => n + PAGE_SIZE)}
            className="btn-press rounded-full border border-navy/25 bg-white px-5 py-2.5 text-sm font-semibold"
          >
            {t('programs.showMore')}
          </button>
        </p>
      )}
    </div>
  );
}
