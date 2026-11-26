'use client';
import { useState } from 'react';
import { useApp } from '../../lib/store';
import { SUCCESS_CASES } from '../../lib/cases';
import { CaseCard } from '../../components/CaseCard';
import { AiEntry, budgetFromProfile, fallbackQuestion, recommendQuestion, type RecommendLevel } from '../../components/AiEntry';
import { displayCountryCode } from '../../lib/rankings';

/**
 * All netizen-shared success cases (one card per applicant), filterable
 * by level. Same rules as the homepage cards: only what the poster
 * shared, missing fields render nothing, every card labelled not
 * officially verified, source link out. The count in the subtitle comes
 * from the data length (tf with SUCCESS_CASES.length), never hardcoded.
 */
export default function CasesPage() {
  const { t, tf, profile } = useApp();
  const [filter, setFilter] = useState<'all' | 'undergraduate' | 'taught_masters'>('all');
  const shown = filter === 'all' ? SUCCESS_CASES : SUCCESS_CASES.filter((c) => c.offers.some((o) => o.level === filter));
  // AI visibility layer (W5): "find cases like me" — the backend
  // holds no case data and the cases here are netizen-shared and
  // unverified, so the entry honestly asks for verified programmes
  // with the same level + country + budget instead (see aivis.casesNote).
  // Level comes from the filter when set, else the saved profile.
  const level: RecommendLevel = filter !== 'all'
    ? filter
    : (profile.track === 'taught_masters' ? 'taught_masters' : 'undergraduate');
  const casesCountry = profile.prefCountries?.[0] ?? null;
  const casesQuestion = casesCountry
    ? recommendQuestion(level, casesCountry, displayCountryCode(casesCountry, casesCountry, t), budgetFromProfile(profile, level, casesCountry))
    : fallbackQuestion(profile, level);
  const chip = (key: 'all' | 'undergraduate' | 'taught_masters', label: string) => (
    <button
      type="button"
      onClick={() => setFilter(key)}
      aria-pressed={filter === key}
      className={`btn-press rounded-full px-4 py-2 text-sm font-semibold ${filter === key ? 'bg-amber text-navy' : 'border border-navy/30 bg-white'}`}
    >
      {label}
    </button>
  );
  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="line-mask text-2xl font-bold"><span>{t('cases.title')}</span></h1>
      <p className="mt-1 text-sm text-navy/70">{tf('cases.sub', { count: SUCCESS_CASES.length })}</p>
      <p className="mt-2">
        <span className="inline-block rounded-full bg-amber/25 px-3 py-1 text-xs font-semibold text-navy">{t('cases.unverifiedLabel')}</span>
      </p>
      <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label={t('cases.title')}>
        {chip('all', t('cases.filterAll'))}
        {chip('undergraduate', t('cases.filterUg'))}
        {chip('taught_masters', t('cases.filterTm'))}
      </div>
      <div className="mt-4">
        <AiEntry label={t('aivis.cases')} question={casesQuestion} note={t('aivis.casesNote')} />
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        {shown.map((c) => (
          <CaseCard key={c.id} c={c} />
        ))}
      </div>
    </div>
  );
}
