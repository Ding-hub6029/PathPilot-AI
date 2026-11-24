'use client';
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useApp } from '../../lib/store';
import { PROGRAMS } from '../../lib/programs';
import { matchProfile, simulate } from '../../lib/api';
import { MatchResponse, Profile } from '../../lib/types';
import { StatusChip } from '../../components/StatusChip';

type Filter = 'all' | 'met' | 'notmet' | 'unknown';

export default function ResultsPage() {
  const { t, profile } = useApp();
  const [data, setData] = useState<MatchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [simPatch, setSimPatch] = useState<Partial<Profile>>({});
  const [simData, setSimData] = useState<MatchResponse | null>(null);
  const [simLoading, setSimLoading] = useState(false);

  useEffect(() => {
    if (!profile.track || profile.targetProgramIds.length === 0) return;
    setLoading(true); setError('');
    matchProfile(profile)
      .then(setData)
      .catch(() => setError(t('results.error')))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile.track, JSON.stringify(profile.targetProgramIds)]);

  const runSim = async () => {
    if (!Object.keys(simPatch).length) return;
    setSimLoading(true);
    try { setSimData(await simulate(profile, simPatch)); } catch { /* keep baseline */ }
    setSimLoading(false);
  };

  const shown = useMemo(() => {
    if (!data) return [];
    return data.results.filter((r) => {
      if (filter === 'all') return true;
      if (filter === 'met') return r.ruleResults.every((x) => x.status === 'MET');
      if (filter === 'notmet') return r.ruleResults.some((x) => x.status === 'NOT_MET');
      return r.ruleResults.some((x) => x.status === 'UNKNOWN');
    });
  }, [data, filter]);

  if (!profile.track || profile.targetProgramIds.length === 0) {
    return (
      <div className="page-enter mx-auto max-w-3xl px-4 py-12 text-center">
        <p className="text-lg">{t('results.empty')}</p>
        <Link href="/wizard" className="btn-press mt-6 inline-block rounded-full bg-navy px-6 py-3 font-semibold text-white">{t('results.goWizard')}</Link>
      </div>
    );
  }

  return (
    <div className="page-enter mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-2xl font-bold">{t('results.title')}</h1>
      {profile.sample && <p className="mt-2 inline-block rounded-lg bg-amber/25 px-3 py-1 text-sm font-semibold">{t('common.synthetic')}</p>}
      {data && !data.live && <p className="mt-3 rounded-lg bg-amber/20 p-3 text-sm font-semibold" role="status">{t('common.offline')}: {t('results.offlineNote')}</p>}
      {data && data.live && <p className="mt-3 rounded-lg bg-teal/10 p-3 text-sm font-semibold text-teal-dark" role="status">{t('common.online')}</p>}

      <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="Filters">
        {([['all', t('results.filterAll')], ['met', t('results.filterMet')], ['notmet', t('results.filterNotMet')], ['unknown', t('results.filterUnknown')]] as [Filter, string][]).map(([f, label]) => (
          <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}
            className={`btn-press rounded-full px-4 py-2 text-sm font-semibold ${filter === f ? 'bg-navy text-white' : 'border border-navy/25 bg-white'}`}>{label}</button>
        ))}
      </div>

      <div aria-live="polite" className="mt-6">
        {loading && <p>{t('results.loading')}</p>}
        {error && <p role="alert" className="rounded-lg bg-red-50 p-3 font-semibold text-red-800">{error}</p>}
        <div className="grid gap-4 md:grid-cols-2">
          {shown.map((r, i) => {
            const p = PROGRAMS.find((x) => x.id === r.programId);
            if (!p) return null;
            const unknowns = r.ruleResults.filter((x) => x.status === 'UNKNOWN').length;
            const blockers = r.ruleResults.filter((x) => x.status === 'NOT_MET');
            const sim = simData?.results.find((x) => x.programId === r.programId);
            return (
              <article key={r.programId} className={`card-lift anim-fade-up stagger-${(i % 4) + 1} rounded-2xl border border-navy/10 bg-white p-5 shadow-sm`}>
                <p className="text-sm font-semibold text-teal">{p.institution} · {p.country}</p>
                <h2 className="mt-1 text-lg font-bold">{p.officialName}</h2>
                {r.trackMismatch ? (
                  <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{t('results.trackMismatch')}</p>
                ) : (
                  <>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {r.ruleResults.map((rule) => <StatusChip key={rule.ruleId} status={rule.status} />)}
                    </div>
                    <p className="mt-3 text-sm text-navy/70">
                      {unknowns > 0 ? `${unknowns} ${t('results.unknownCount')}` : ''}
                    </p>
                    {blockers.length > 0 && (
                      <div className="mt-2">
                        <p className="text-sm font-bold">{t('results.blockers')}:</p>
                        <ul className="list-disc ps-5 text-sm text-navy/80">
                          {blockers.map((b) => <li key={b.ruleId}>{b.expected} — {b.observed}</li>)}
                        </ul>
                      </div>
                    )}
                    {sim && (
                      <div className="mt-3 rounded-lg bg-teal/10 p-3 text-sm" aria-live="polite">
                        <p className="font-bold">{t('sim.scenario')}</p>
                        <div className="mt-1 flex flex-wrap gap-2">
                          {sim.ruleResults.map((rule) => <StatusChip key={rule.ruleId} status={rule.status} />)}
                        </div>
                      </div>
                    )}
                  </>
                )}
                <div className="mt-4">
                  <Link href={`/programs/${p.id}`} className="btn-press inline-block rounded-full bg-navy px-4 py-2 text-sm font-semibold text-white">{t('results.viewDetail')}</Link>
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
          <label className="block"><span className="text-sm font-semibold">{t('sim.budget')}</span>
            <input type="number" step="1" min={0} value={simPatch.budget ?? profile.budget ?? ''} onChange={(e) => setSimPatch({ ...simPatch, budget: e.target.value === '' ? '' : Number(e.target.value) })} className="mt-1 w-full rounded-lg border border-navy/25 px-3 py-2" /></label>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" onClick={runSim} disabled={simLoading} className="btn-press rounded-full bg-teal px-5 py-2 font-semibold text-white disabled:opacity-50">{simLoading ? t('common.loading') : t('sim.apply')}</button>
          <button type="button" onClick={() => { setSimPatch({}); setSimData(null); }} className="btn-press rounded-full border border-navy/30 px-5 py-2 font-semibold">{t('sim.reset')}</button>
        </div>
        <div className="mt-4 grid gap-4 text-sm md:grid-cols-2">
          <div className="rounded-lg bg-paper p-4"><p className="font-bold">{t('sim.baseline')}</p><p className="mt-1 text-navy/70">IELTS {profile.ieltsOverall ?? '–'} · {t('sim.budget')}: {profile.budget ?? '–'} {profile.budgetCurrency}</p></div>
          <div className="rounded-lg bg-teal/10 p-4"><p className="font-bold">{t('sim.scenario')}</p><p className="mt-1 text-navy/70">IELTS {simPatch.ieltsOverall ?? profile.ieltsOverall ?? '–'} · {t('wizard.ieltsWriting')}: {simPatch.ieltsWriting ?? profile.ieltsWriting ?? '–'} · {t('sim.budget')}: {simPatch.budget ?? profile.budget ?? '–'}</p></div>
        </div>
      </section>

      <p className="mt-6 rounded-lg bg-white/70 p-3 text-sm text-navy/80" role="note">{t('home.disclaimer')}</p>
    </div>
  );
}
