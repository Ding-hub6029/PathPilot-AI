'use client';
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useApp } from '../../lib/store';
import { usePrograms } from '../../lib/usePrograms';
import { useElapsed } from '../../lib/useElapsed';
import { matchProfile, mergePrograms, simulate } from '../../lib/api';
import { MatchResponse, Profile, Program } from '../../lib/types';
import {
  catalogueCountInCountry, cityDisplayName, countryAlternatives, fieldDisplayLabel,
  hasPreferences, missingPrefCountries, prefHints, prefSummary, trackDisplayLabel,
} from '../../lib/preferences';
import { displayProgramName, displayProgramTitle, PROGRAMS } from '../../lib/programs';
import { EXPANSION_PROGRAMS } from '../../lib/expansion';
import { displayProgramInstitutionName } from '../../lib/rankings';
import { StatusChip } from '../../components/StatusChip';
import { RuleRow } from '../../components/RuleRow';
import { CompassFace } from '../../components/CompassPet';
import { ViewTransitionLink } from '../../components/ViewTransitionLink';
import { vtRef } from '../../lib/viewTransition';
import { useBackendStatus } from '../../lib/backendStatus';
import { GaokaoPanel } from '../../components/GaokaoPanel';
import { chipLabel, formatFeeSentence, formatObserved, ruleExpected, ruleName } from '../../lib/ruleText';

type Filter = 'all' | 'met' | 'notmet' | 'unknown';

export default function ResultsPage() {
  const { t, tf, locale, profile } = useApp();
  const f = { t, tf, locale, budgetCurrency: profile.budgetCurrency };
  const { programs: livePrograms } = usePrograms();
  // Round 9 (R9): backend status comes from the one shared probe
  // (lib/backendStatus) — never from this page's own match/fetch, so
  // this header can no longer contradict the rankings/browse footers.
  const backendStatus = useBackendStatus();
  // Round 6: lookups cover the merged list (live v2 + expansion mirror),
  // so expansion results resolve to a programme card.
  const programs = useMemo(() => mergePrograms(livePrograms), [livePrograms]);
  const [data, setData] = useState<MatchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  /** The match call is retrying while the backend wakes: show the
   * waking line with elapsed seconds, never a wrong offline claim —
   * the offline banners below render only after the patient call
   * settles offline (round 8). */
  const [waking, setWaking] = useState(false);
  const wakingElapsed = useElapsed(waking);
  const [filter, setFilter] = useState<Filter>('all');
  const [countryFilter, setCountryFilter] = useState<string | null>(null);
  const [cityFilter, setCityFilter] = useState<string | null>(null);
  const [simPatch, setSimPatch] = useState<Partial<Profile>>({});
  const [simData, setSimData] = useState<MatchResponse | null>(null);
  const [simLoading, setSimLoading] = useState(false);

  useEffect(() => {
    if (!profile.track || profile.targetProgramIds.length === 0) return;
    setLoading(true); setError(''); setWaking(false);
    matchProfile(profile, { onRetry: () => setWaking(true) })
      .then(setData)
      .catch(() => setError(t('results.error')))
      .finally(() => { setLoading(false); setWaking(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile.track, JSON.stringify(profile.targetProgramIds)]);

  // A completed check is remembered so the homepage banner can greet
  // returning users with their results (2026-11-25: the banner shows
  // every session; this flag only switches its copy).
  useEffect(() => {
    if (data && data.results.length > 0) {
      try { localStorage.setItem('pp-check-done', '1'); } catch { /* ignore */ }
    }
  }, [data]);

  const runSim = async () => {
    if (!Object.keys(simPatch).length) return;
    setSimLoading(true);
    try { setSimData(await simulate(profile, simPatch)); } catch { /* keep baseline */ }
    setSimLoading(false);
  };

  // Programmes behind the current results, for the country / city
  // filters. City comes from the programme's verified city field.
  const resultPrograms = useMemo(() => {
    if (!data) return [];
    return data.results.map((r) => programs.find((x) => x.id === r.programId)).filter((p): p is Program => !!p);
  }, [data, programs]);
  const resultCountries = useMemo(() => [...new Set(resultPrograms.map((p) => p.country))].sort(), [resultPrograms]);
  const resultCities = useMemo(() => [...new Set(resultPrograms.map((p) => p.city).filter((c): c is string => !!c))].sort(), [resultPrograms]);

  // Round 8 (Switzerland honesty): a chosen country with no programme
  // in the filtered set is explained with the closest verified
  // alternatives — never a silent zero. Programmes that arrive later
  // (Worker E) flow through automatically, because the notice is
  // computed from the live lists, not hardcoded.
  const missingCountries = useMemo(
    () => (data ? missingPrefCountries(profile, resultPrograms) : []),
    [data, resultPrograms, profile],
  );

  // Sorted by eligibility (MET, then partly unknown, then not met),
  // with climate conflicts last (round 6) — the preference never hides
  // a programme, it only reorders, and the note below says so.
  const shown = useMemo(() => {
    if (!data) return [];
    const rank = (s: string) => s === 'MET' ? 0 : s === 'PARTIAL_UNKNOWN' ? 1 : s === 'NOT_MET' ? 2 : 3;
    return data.results.filter((r) => {
      if (filter === 'all') { /* fall through to the pref filters */ }
      else if (filter === 'met' && !r.ruleResults.every((x) => x.status === 'MET')) return false;
      else if (filter === 'notmet' && !r.ruleResults.some((x) => x.status === 'NOT_MET')) return false;
      else if (filter === 'unknown' && !r.ruleResults.some((x) => x.status === 'UNKNOWN')) return false;
      const p = programs.find((x) => x.id === r.programId);
      if (countryFilter && p?.country !== countryFilter) return false;
      if (cityFilter && p?.city !== cityFilter) return false;
      return true;
    }).sort((a, b) => rank(a.eligibilitySummary) - rank(b.eligibilitySummary)
      || (a.preferenceFit === 'conflict' ? 1 : 0) - (b.preferenceFit === 'conflict' ? 1 : 0));
  }, [data, filter, countryFilter, cityFilter, programs]);

  if (!profile.track || profile.targetProgramIds.length === 0) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-12 text-center">
        <p className="text-lg">{t('results.empty')}</p>
        <Link href="/wizard" className="btn-press mt-6 inline-block rounded-full bg-navy px-6 py-3 font-semibold text-white">{t('results.goWizard')}</Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="line-mask text-2xl font-bold"><span>{t('results.title')}</span></h1>
      {profile.sample && <p className="mt-2 inline-block rounded-lg bg-amber/25 px-3 py-1 text-sm font-semibold">{t('common.synthetic')}</p>}
      {backendStatus === 'live' && <p className="mt-3 rounded-lg bg-teal/10 p-3 text-sm font-semibold text-teal-dark" role="status">{t('r9pages.backendLive')}</p>}
      {backendStatus === 'checking' && <p className="mt-3 rounded-lg bg-white/70 p-3 text-sm font-semibold text-navy/70" role="status">{t('r9pages.backendChecking')}</p>}
      {backendStatus === 'offline' && <p className="mt-3 rounded-lg bg-amber/20 p-3 text-sm font-semibold" role="status">{t('common.offline')}: {t('results.offlineNote')}</p>}
      {/* Round 8: every count says what it counts — the filtered
          result count, the full result count, the 8 deeply-verified
          v2 programmes and the 881 expansion programmes — so the
          numbers here can never contradict another page's. */}
      {data && (
        <p className="mt-2 text-sm text-navy/70">
          {tf('results.countLine', { shown: shown.length, total: data.results.length, v2: PROGRAMS.length, expansion: EXPANSION_PROGRAMS.length })}
        </p>
      )}

      {/* Status legend: a bare chip ("符合") means nothing without its rule. */}
      <div className="mt-4 rounded-2xl border border-navy/10 bg-white p-4 text-sm">
        <p className="font-bold">{t('results.legendTitle')}</p>
        <ul className="mt-2 space-y-2 text-navy/80">
          <li className="flex flex-wrap items-center gap-2"><StatusChip status="MET" /><span>{t('results.legendMet')}</span></li>
          <li className="flex flex-wrap items-center gap-2"><StatusChip status="NOT_MET" /><span>{t('results.legendNotMet')}</span></li>
          <li className="flex flex-wrap items-center gap-2"><StatusChip status="UNKNOWN" /><span>{t('results.legendUnknown')}</span></li>
          <li className="flex flex-wrap items-center gap-2"><StatusChip status="NOT_APPLICABLE" /><span>{t('results.legendNotApplicable')}</span></li>
        </ul>
      </div>

      {/* Next step (flow fix): the check is done — the report is the
          analysis, and the wizard is where a profile is refined. */}
      {data && !loading && (() => {
        const usable = data.results.filter((r) => !r.trackMismatch && r.ruleResults.length > 0);
        const metCount = usable.filter((r) => r.ruleResults.every((x) => x.status === 'MET')).length;
        const blockerCount = usable.filter((r) => r.ruleResults.some((x) => x.status === 'NOT_MET')).length;
        const unknownCount = usable.filter((r) => r.ruleResults.some((x) => x.status === 'UNKNOWN')).length;
        return (
          <section className="glass grid-bg mt-4 rounded-2xl p-5" aria-labelledby="next-title">
            <h2 id="next-title" className="text-lg font-bold">{t('results.nextTitle')}</h2>
            <p className="mt-1 text-sm text-navy/75">{tf('results.nextSummary', { met: metCount, blockers: blockerCount, unknown: unknownCount })}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Link href="/report" className="btn-press rounded-full bg-navy px-5 py-2 font-semibold text-white">{t('results.nextReport')}</Link>
              <Link href="/wizard" className="btn-press rounded-full border border-navy/30 bg-white px-5 py-2 font-semibold">{t('results.nextEdit')}</Link>
            </div>
          </section>
        );
      })()}

      {/* Round 9 (R11): "0 个课程符合所有已知要求" with no explanation
          reads as a verdict on the applicant. For a Gaokao applicant it
          is structural — no university publishes a Gaokao equivalence,
          so the academic rule is UNKNOWN everywhere and nothing can
          ever be fully MET. Say so in plain words, and point at the
          Gaokao route panel (what universities actually publish) instead
          of leaving the zero unexplained. Shown only when the zero is
          really caused by unknown academics for a Gaokao profile. */}
      {data && !loading && (() => {
        const usable = data.results.filter((r) => !r.trackMismatch && r.ruleResults.length > 0);
        const metCount = usable.filter((r) => r.ruleResults.every((x) => x.status === 'MET')).length;
        const hasGaokao = profile.gaokaoScore !== '' && profile.gaokaoScore !== undefined;
        const academicUnknown = usable.some((r) => r.ruleResults.some((x) => x.ruleId.endsWith('-academic') && x.status === 'UNKNOWN'));
        if (metCount !== 0 || !hasGaokao || !academicUnknown) return null;
        return (
          <section className="mt-4 rounded-2xl border border-amber/40 bg-amber/10 p-5" aria-labelledby="zero-met-title">
            <h2 id="zero-met-title" className="text-lg font-bold">{t('r9pages.zeroMetTitle')}</h2>
            <p className="mt-1 text-sm text-navy/80">{t('r9pages.zeroMetBody')}</p>
            <p className="mt-2 text-sm font-semibold">{t('r9pages.zeroMetGaokaoHint')}</p>
            <GaokaoPanel />
          </section>
        );
      })()}

      {/* Your preferences, in your own words. They only filter and hint —
          they never change an eligibility result. Climate is matched
          against the curated city climate table (round 6) only to order
          results and show an honest note — never to exclude a programme;
          salary / pressure / teaching style are never matched against a
          programme because no official data exists for them. */}
      {hasPreferences(profile) && (
        <section className="mt-4 rounded-2xl border border-amber/40 bg-amber/10 p-5" aria-labelledby="prefs-title">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="prefs-title" className="text-lg font-bold">{t('results.prefTitle')}</h2>
            <Link href="/wizard" className="btn-press rounded-full border border-navy/30 bg-white px-4 py-1.5 text-sm font-semibold">{t('results.prefEdit')}</Link>
          </div>
          <p className="mt-1 text-sm text-navy/80">{prefSummary(profile, t)}</p>
          {/* Pet-voiced line (2026-11-25): not just a field list. Only
              countries / cities that actually appear in the verified
              results are named — the country line is true because
              matching programmes carry the preference hint chip below. */}
          {(() => {
            const matchedCountries = (profile.prefCountries ?? []).filter((c) => resultCountries.includes(c));
            const wantCity = (profile.prefCity ?? '').trim().toLowerCase();
            const cityCount = wantCity ? resultPrograms.filter((p) => (p.city ?? '').toLowerCase() === wantCity).length : 0;
            if (matchedCountries.length === 0 && cityCount === 0) return null;
            return (
              <div className="mt-3 flex items-start gap-2">
                <span className="inline-flex shrink-0 rounded-full bg-teal/10 p-0.5"><CompassFace size={32} mood="idle" /></span>
                <div className="text-sm">
                  {matchedCountries.length > 0 && (
                    <p>{tf('results.prefVoiceCountries', { countries: matchedCountries.map((c) => t(`country.${c}`)).join(locale === 'zh-CN' ? '、' : ', ') })}</p>
                  )}
                  {cityCount > 0 && (
                    <p className={matchedCountries.length > 0 ? 'mt-1' : ''}>{tf('results.prefVoiceCity', { city: cityDisplayName(profile.prefCity ?? '', t), count: cityCount })}</p>
                  )}
                </div>
              </div>
            );
          })()}
          {profile.prefSalary !== '' && profile.prefSalary !== undefined && (
            <>
              <p className="mt-2 text-sm font-semibold">{tf('results.prefSalaryLine', { salary: `${profile.prefSalary} ${profile.prefSalaryCurrency ?? ''}`.trim() })}</p>
              <p className="mt-1 text-sm text-navy/70">{t('results.noSalaryData')}</p>
            </>
          )}
        </section>
      )}

      {/* Round 8 (Switzerland honesty): a chosen country with no
          programme in the filtered set is explained with the closest
          verified alternatives — never a silent zero. */}
      {data && missingCountries.length > 0 && missingCountries.map((code) => {
        const alts = countryAlternatives(code, profile, programs);
        const catalogueCount = catalogueCountInCountry(code, programs);
        const level = trackDisplayLabel(profile.track, t);
        const field = fieldDisplayLabel(profile.field, t);
        const altList = [...alts.sameTrack, ...alts.sameField];
        return (
          <section key={`missing-${code}`} className="mt-4 rounded-2xl border border-amber/40 bg-amber/10 p-5" aria-labelledby={`missing-${code}-title`}>
            <h2 id={`missing-${code}-title`} className="text-lg font-bold">{tf('results.noCountryTitle', { country: t(`country.${code}`) })}</h2>
            <p className="mt-1 text-sm text-navy/80">{tf('results.noCountryNote', { country: t(`country.${code}`), level, field })}</p>
            {catalogueCount > 0 ? (
              <>
                <p className="mt-2 text-sm">{tf('results.noCountryCatalogue', { count: catalogueCount, country: t(`country.${code}`), level })}</p>
                <ul className="mt-1 space-y-1">
                  {altList.map((p) => {
                    const levelLabel = trackDisplayLabel(p.degreeLevel, t);
                    return (
                      <li key={p.id}>
                        <Link href={`/programs/${p.id}`} className="text-sm font-semibold text-teal underline">
                          {displayProgramTitle(p, locale)}{levelLabel ? ` · ${levelLabel}` : ''}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </>
            ) : (
              <p className="mt-2 text-sm text-navy/80">{t('results.noCountryNone')}</p>
            )}
          </section>
        );
      })}

      <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="Filters">
        {([['all', t('results.filterAll')], ['met', t('results.filterMet')], ['notmet', t('results.filterNotMet')], ['unknown', t('results.filterUnknown')]] as [Filter, string][]).map(([f, label]) => (
          <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}
            className={`btn-press rounded-full px-4 py-2 text-sm font-semibold ${filter === f ? 'bg-navy text-white' : 'border border-navy/25 bg-white'}`}>{label}</button>
        ))}
      </div>

      {/* Country / city filters: only values present in the verified
          results are offered — never a filter that can match nothing. */}
      {resultCountries.length > 1 && (
        <div className="mt-3">
          <p className="text-sm font-semibold text-navy/60">{t('results.filterByCountry')}</p>
          <div className="mt-1 flex flex-wrap gap-2">
            <button type="button" aria-pressed={countryFilter === null} onClick={() => setCountryFilter(null)}
              className={`btn-press rounded-full px-3 py-1.5 text-sm font-semibold ${countryFilter === null ? 'bg-navy text-white' : 'border border-navy/25 bg-white'}`}>{t('results.filterAllCountries')}</button>
            {resultCountries.map((c) => (
              <button key={c} type="button" aria-pressed={countryFilter === c} onClick={() => setCountryFilter(countryFilter === c ? null : c)}
                className={`btn-press rounded-full px-3 py-1.5 text-sm font-semibold ${countryFilter === c ? 'bg-navy text-white' : 'border border-navy/25 bg-white'}`}>{t(`country.${c}`)}</button>
            ))}
          </div>
        </div>
      )}
      {resultCities.length > 1 && (
        <div className="mt-3">
          <p className="text-sm font-semibold text-navy/60">{t('results.filterByCity')}</p>
          <div className="mt-1 flex flex-wrap gap-2">
            <button type="button" aria-pressed={cityFilter === null} onClick={() => setCityFilter(null)}
              className={`btn-press rounded-full px-3 py-1.5 text-sm font-semibold ${cityFilter === null ? 'bg-navy text-white' : 'border border-navy/25 bg-white'}`}>{t('results.filterAllCities')}</button>
            {resultCities.map((c) => (
              <button key={c} type="button" aria-pressed={cityFilter === c} onClick={() => setCityFilter(cityFilter === c ? null : c)}
                className={`btn-press rounded-full px-3 py-1.5 text-sm font-semibold ${cityFilter === c ? 'bg-navy text-white' : 'border border-navy/25 bg-white'}`}>{cityDisplayName(c, t)}</button>
            ))}
          </div>
        </div>
      )}

      <div aria-live="polite" className="mt-6">
        {loading && <p>{waking ? tf('pet.wakingElapsed', { seconds: wakingElapsed }) : t('results.loading')}</p>}
        {error && <p role="alert" className="rounded-lg bg-red-50 p-3 font-semibold text-red-800">{error}</p>}
        <div className="grid gap-4 md:grid-cols-2">
          {shown.map((r, i) => {
            const p = programs.find((x) => x.id === r.programId);
            if (!p) return null;
            const unknowns = r.ruleResults.filter((x) => x.status === 'UNKNOWN').length;
            const blockers = r.ruleResults.filter((x) => x.status === 'NOT_MET');
            const sim = simData?.results.find((x) => x.programId === r.programId);
            return (
              <article key={r.programId} className="card-lift rounded-2xl border border-navy/10 bg-white p-5 card-surface">
                <p className="text-sm font-semibold text-teal">{displayProgramInstitutionName(p.institution, locale)} · {p.country}</p>
                <h2 className="mt-1 text-lg font-bold" ref={vtRef(`program-title-${p.id}`)}>{displayProgramName(p, locale)}</h2>
                {prefHints(profile, p, t).length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {prefHints(profile, p, t).map((h) => (
                      <span key={h} className="rounded-full bg-amber/25 px-2.5 py-1 text-xs font-semibold text-navy">{tf('results.prefMatch', { value: h })}</span>
                    ))}
                  </div>
                )}
                {r.preferenceFit === 'conflict' && (
                  <p className="mt-2 rounded-lg bg-amber/20 p-2 text-sm font-semibold" role="note">{t('results.prefClimateConflict')}</p>
                )}
                {r.trackMismatch ? (
                  <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{t('results.trackMismatch')}</p>
                ) : (
                  <>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {r.ruleResults.map((rule) => <StatusChip key={rule.ruleId} status={rule.status} label={chipLabel(rule, f)} />)}
                    </div>
                    <p className="mt-3 text-sm text-navy/70">
                      {unknowns > 0 ? `${unknowns} ${t('results.unknownCount')}` : ''}
                    </p>
                    {blockers.length > 0 && (
                      <div className="mt-2">
                        <p className="text-sm font-bold">{t('results.blockers')}:</p>
                        <ul className="list-disc ps-5 text-sm text-navy/80">
                          {blockers.map((b) => {
                            const sentence = formatFeeSentence(b, f);
                            return (
                              <li key={b.ruleId}>
                                {sentence ?? (
                                  <>
                                    <strong>{ruleName(b.ruleId, t)}</strong>{t('common.colon')}{ruleExpected(b, f)} — {t('results.yourSituation')}{t('common.colon')}{formatObserved(b, f)}
                                  </>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    )}
                    <div className="mt-3 space-y-2">
                      {r.ruleResults.map((rule) => <RuleRow key={rule.ruleId} program={p} rule={rule} />)}
                    </div>
                    {sim && (
                      <div className="mt-3 rounded-lg bg-teal/10 p-3 text-sm" aria-live="polite">
                        <p className="font-bold">{t('sim.scenario')}</p>
                        <div className="mt-1 flex flex-wrap gap-2">
                          {sim.ruleResults.map((rule) => <StatusChip key={rule.ruleId} status={rule.status} label={chipLabel(rule, f)} />)}
                        </div>
                      </div>
                    )}
                  </>
                )}
                <div className="mt-4 flex flex-wrap gap-2">
                  <ViewTransitionLink href={`/programs/${p.id}`} className="btn-press inline-block rounded-full bg-navy px-4 py-2 text-sm font-semibold text-white">{t('results.viewDetail')}</ViewTransitionLink>
                  <Link href="/report" className="btn-press inline-block rounded-full border border-navy/30 bg-white px-4 py-2 text-sm font-semibold">{t('results.viewReport')}</Link>
                </div>
              </article>
            );
          })}
        </div>
      </div>

      {/* Simulation panel */}
      <section className="mt-10 rounded-2xl border border-navy/10 bg-white p-6 shadow-sm" aria-labelledby="sim-title">
        <h2 id="sim-title" className="text-xl font-bold">{t('sim.title')}</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block"><span className="text-sm font-semibold">{t('wizard.ieltsOverall')}</span>
            <input type="number" step="0.5" min={0} max={9} value={simPatch.ieltsOverall ?? profile.ieltsOverall ?? ''} onChange={(e) => setSimPatch({ ...simPatch, ieltsOverall: e.target.value === '' ? '' : Number(e.target.value) })} className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" /></label>
          <label className="block"><span className="text-sm font-semibold">{t('wizard.ieltsWriting')}</span>
            <input type="number" step="0.5" min={0} max={9} value={simPatch.ieltsWriting ?? profile.ieltsWriting ?? ''} onChange={(e) => setSimPatch({ ...simPatch, ieltsWriting: e.target.value === '' ? '' : Number(e.target.value) })} className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" /></label>
          <label className="block"><span className="text-sm font-semibold">{t('wizard.ieltsListening')}</span>
            <input type="number" step="0.5" min={0} max={9} value={simPatch.ieltsListening ?? profile.ieltsListening ?? ''} onChange={(e) => setSimPatch({ ...simPatch, ieltsListening: e.target.value === '' ? '' : Number(e.target.value) })} className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" /></label>
          <label className="block"><span className="text-sm font-semibold">{t('wizard.ieltsReading')}</span>
            <input type="number" step="0.5" min={0} max={9} value={simPatch.ieltsReading ?? profile.ieltsReading ?? ''} onChange={(e) => setSimPatch({ ...simPatch, ieltsReading: e.target.value === '' ? '' : Number(e.target.value) })} className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" /></label>
          <label className="block"><span className="text-sm font-semibold">{t('wizard.ieltsSpeaking')}</span>
            <input type="number" step="0.5" min={0} max={9} value={simPatch.ieltsSpeaking ?? profile.ieltsSpeaking ?? ''} onChange={(e) => setSimPatch({ ...simPatch, ieltsSpeaking: e.target.value === '' ? '' : Number(e.target.value) })} className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" /></label>
          <label className="block"><span className="text-sm font-semibold">{t('sim.budget')}{profile.budgetCurrency ? ` (${profile.budgetCurrency})` : ''}</span>
            <input type="number" step="1" min={0} value={simPatch.budget ?? profile.budget ?? ''} onChange={(e) => setSimPatch({ ...simPatch, budget: e.target.value === '' ? '' : Number(e.target.value) })} className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" /></label>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" onClick={runSim} disabled={simLoading} className="btn-press rounded-full bg-teal px-5 py-2 font-semibold text-white disabled:opacity-50">{simLoading ? t('common.loading') : t('sim.apply')}</button>
          <button type="button" onClick={() => { setSimPatch({}); setSimData(null); }} className="btn-press rounded-full border border-navy/30 px-5 py-2 font-semibold">{t('sim.reset')}</button>
        </div>
        <div className="mt-4 grid gap-4 text-sm md:grid-cols-2">
          <div className="rounded-lg bg-paper p-4"><p className="font-bold">{t('sim.baseline')}</p><p className="mt-1 text-navy/70">IELTS {profile.ieltsOverall ?? '–'} · {t('sim.budget')}: {profile.budget ?? '–'} {profile.budgetCurrency}</p></div>
          <div className="rounded-lg bg-teal/10 p-4"><p className="font-bold">{t('sim.scenario')}</p><p className="mt-1 text-navy/70">IELTS {simPatch.ieltsOverall ?? profile.ieltsOverall ?? '–'} · {t('wizard.ieltsWriting')}: {simPatch.ieltsWriting ?? profile.ieltsWriting ?? '–'} · {t('sim.budget')}: {simPatch.budget ?? profile.budget ?? '–'} {profile.budgetCurrency ?? ''}</p></div>
        </div>
      </section>

      <p className="mt-6 rounded-lg bg-white/70 p-3 text-sm text-navy/80" role="note">{t('home.disclaimer')}</p>
    </div>
  );
}
