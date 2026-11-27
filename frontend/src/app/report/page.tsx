'use client';
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useApp } from '../../lib/store';
import { usePrograms } from '../../lib/usePrograms';
import { useElapsed } from '../../lib/useElapsed';
import { matchProfile, mergePrograms } from '../../lib/api';
import { MatchResponse } from '../../lib/types';
import { RuleRow } from '../../components/RuleRow';
import { formatProgramLine } from '../../lib/format';
import { displayProgramTitle } from '../../lib/programs';
import { fieldDisplayLabel, prefSummary, trackDisplayLabel } from '../../lib/preferences';
import { statusText } from '../../lib/ruleText';

const CURRICULUM_LABEL_KEYS: Record<string, string> = {
  cn_gaokao: 'wizard.curriculumCnGaokao',
  uk_alevel: 'wizard.curriculumUk',
  ib: 'wizard.curriculumIb',
  usa: 'wizard.curriculumUsa',
  sg_alevel: 'wizard.curriculumSg',
  other: 'wizard.curriculumOther',
};

/**
 * Report page (round 8): real content instead of the near-blank page
 * the audit found — a profile summary, a results table (programme /
 * status / blockers / unknowns), and the per-programme rule detail.
 * The date is locale-correct (never US mm/dd/yyyy on a Chinese UI),
 * and print / download give in-page feedback instead of silence.
 */
export default function ReportPage() {
  const { t, tf, locale, profile } = useApp();
  const { programs: livePrograms } = usePrograms();
  // Round 6: lookups cover the merged list (live v2 + expansion mirror).
  const programs = useMemo(() => mergePrograms(livePrograms), [livePrograms]);
  const [data, setData] = useState<MatchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  /** The match call is retrying while the backend wakes: show the
   * waking line with elapsed seconds, never a wrong offline claim. */
  const [waking, setWaking] = useState(false);
  const wakingElapsed = useElapsed(waking);
  /** Print feedback: "preparing" paints before the print dialog
   * opens, "done" after it closes — the action never looks dead. */
  const [printStatus, setPrintStatus] = useState<'idle' | 'preparing' | 'done'>('idle');
  const [downloaded, setDownloaded] = useState(false);

  useEffect(() => {
    if (!profile.track || profile.targetProgramIds.length === 0) return;
    setLoading(true); setError(''); setWaking(false);
    matchProfile(profile, { onRetry: () => setWaking(true) })
      .then(setData)
      .catch(() => setError(t('report.error')))
      .finally(() => { setLoading(false); setWaking(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile.track, JSON.stringify(profile.targetProgramIds)]);

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify({ generatedAt: new Date().toISOString(), profile: { ...profile }, evaluation: data }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'pathpilot-report.json'; a.click();
    URL.revokeObjectURL(url);
    setDownloaded(true);
  };

  const handlePrint = () => {
    setPrintStatus('preparing');
    // Let the "preparing" line paint before the print dialog opens.
    setTimeout(() => {
      window.print();
      setPrintStatus('done');
    }, 60);
  };

  // Profile summary rows: only what was actually entered.
  const scoreParts: string[] = [];
  if (profile.gaokaoScore !== '' && profile.gaokaoScore !== undefined) scoreParts.push(`Gaokao ${profile.gaokaoScore}/${profile.gaokaoTotal ?? '–'}`);
  if (profile.alevels) scoreParts.push(`A-level ${profile.alevels}`);
  if (profile.ibTotal !== '' && profile.ibTotal !== undefined) scoreParts.push(`IB ${profile.ibTotal}`);
  if (profile.satTotal !== '' && profile.satTotal !== undefined) scoreParts.push(`SAT ${profile.satTotal}`);
  if (profile.actComposite !== '' && profile.actComposite !== undefined) scoreParts.push(`ACT ${profile.actComposite}`);
  if (profile.ieltsOverall !== '' && profile.ieltsOverall !== undefined) scoreParts.push(`IELTS ${profile.ieltsOverall}`);
  if (profile.toefl !== '' && profile.toefl !== undefined) scoreParts.push(`TOEFL ${profile.toefl}`);
  if (profile.greTotal !== '' && profile.greTotal !== undefined) scoreParts.push(`GRE ${profile.greTotal}`);
  if (profile.gmat !== '' && profile.gmat !== undefined) scoreParts.push(`GMAT ${profile.gmat}`);
  const summaryRows: { label: string; value: string }[] = [
    { label: t('report.profileDegree'), value: trackDisplayLabel(profile.track, t) },
    { label: t('report.profileCurriculum'), value: profile.curriculum ? t(CURRICULUM_LABEL_KEYS[profile.curriculum] ?? 'wizard.curriculumOther') : '' },
    { label: t('report.profileField'), value: fieldDisplayLabel(profile.field, t) },
    { label: t('report.profileScores'), value: scoreParts.join(' · ') },
    { label: t('report.profileBudget'), value: profile.budget !== '' && profile.budget !== undefined ? `${profile.budget} ${profile.budgetCurrency ?? ''}`.trim() : '' },
    { label: t('report.profileIntake'), value: profile.intakeYear ? String(profile.intakeYear) : '' },
    { label: t('report.profilePrefs'), value: prefSummary(profile, t, locale) },
  ].filter((row) => row.value);

  // Locale-correct date: e.g. 2026年11月26日 on a Chinese UI, never
  // US mm/dd/yyyy.
  const generatedDate = new Date().toLocaleDateString(locale, { year: 'numeric', month: 'long', day: 'numeric' });

  if (!profile.track) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-12 text-center">
        <p className="text-lg">{t('results.empty')}</p>
        <Link href="/wizard" className="btn-press mt-6 inline-block rounded-full bg-navy px-6 py-3 font-semibold text-white">{t('results.goWizard')}</Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="line-mask text-2xl font-bold"><span>{t('report.title')}</span></h1>
      <p className="mt-2 text-sm text-navy/70">{t('report.summary')} · {generatedDate}</p>
      {profile.sample && <p className="mt-2 inline-block rounded-lg bg-amber/25 px-3 py-1 text-sm font-semibold">{t('common.synthetic')}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={downloadJson} className="btn-press rounded-full bg-navy px-5 py-2 font-semibold text-white">{t('report.downloadJson')}</button>
        <button type="button" onClick={handlePrint} disabled={printStatus === 'preparing'} className="btn-press rounded-full border border-navy/30 bg-white px-5 py-2 font-semibold disabled:opacity-50">{t('report.print')}</button>
        <Link href="/results" className="btn-press rounded-full border border-navy/30 bg-white px-5 py-2 font-semibold">{t('report.backToResults')}</Link>
      </div>
      {printStatus === 'preparing' && <p className="mt-3 text-sm text-navy/70" role="status">{t('report.printPreparing')}</p>}
      {printStatus === 'done' && <p className="mt-3 text-sm text-navy/70" role="status">{t('report.printDone')}</p>}
      {downloaded && <p className="mt-3 text-sm text-navy/70" role="status">{t('report.downloaded')}</p>}
      {loading && <p className="mt-6" role="status">{waking ? tf('pet.wakingElapsed', { seconds: wakingElapsed }) : t('report.loading')}</p>}
      {error && <p role="alert" className="mt-6 rounded-lg bg-red-50 p-3 font-semibold text-red-800">{error}</p>}

      {/* Profile summary */}
      <section className="mt-6 rounded-2xl border border-navy/10 bg-white p-5 shadow-sm" aria-labelledby="profile-title">
        <h2 id="profile-title" className="text-lg font-bold">{t('report.profileTitle')}</h2>
        {summaryRows.length > 0 ? (
          <dl className="mt-3 space-y-2 text-sm">
            {summaryRows.map((row) => (
              <div key={row.label} className="flex flex-wrap gap-2">
                <dt className="w-32 shrink-0 font-semibold text-navy/60">{row.label}</dt>
                <dd className="min-w-0 flex-1">{row.value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="mt-2 text-sm text-navy/70">{t('report.profileEmpty')}</p>
        )}
      </section>

      {/* Results table */}
      {data && data.results.length > 0 && (
        <section className="mt-6 rounded-2xl border border-navy/10 bg-white p-5 shadow-sm" aria-labelledby="results-title">
          <h2 id="results-title" className="text-lg font-bold">{t('report.resultsTitle')}</h2>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-navy/10 text-navy/60">
                  <th scope="col" className="py-2 pe-3 font-semibold">{t('report.tableProgram')}</th>
                  <th scope="col" className="py-2 pe-3 font-semibold">{t('report.tableStatus')}</th>
                  <th scope="col" className="py-2 pe-3 font-semibold">{t('report.tableBlockers')}</th>
                  <th scope="col" className="py-2 font-semibold">{t('report.tableUnknown')}</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((r) => {
                  const p = programs.find((x) => x.id === r.programId);
                  if (!p) return null;
                  const blockers = r.ruleResults.filter((x) => x.status === 'NOT_MET').length;
                  const unknowns = r.ruleResults.filter((x) => x.status === 'UNKNOWN').length;
                  return (
                    <tr key={r.programId} className="border-b border-navy/5 align-top">
                      <td className="py-2 pe-3 font-semibold">{displayProgramTitle(p, locale)}</td>
                      <td className="py-2 pe-3">{statusText(r.eligibilitySummary, t)}</td>
                      <td className="py-2 pe-3">{blockers}</td>
                      <td className="py-2">{unknowns}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {data && data.results.length === 0 && !loading && (
        <p className="mt-6 text-navy/70">{t('report.noResults')}</p>
      )}

      <div className="mt-6 space-y-4">
        {(data?.results ?? []).map((r) => {
          const p = programs.find((x) => x.id === r.programId);
          if (!p) return null;
          return (
            <section key={r.programId} className="rounded-2xl border border-navy/10 bg-white p-5 shadow-sm">
              <h2 className="text-lg font-bold">{displayProgramTitle(p, locale)}</h2>
              <p className="text-sm text-navy/70">{formatProgramLine(p, t, locale)}</p>
              <ul className="mt-3 space-y-2">
                {r.ruleResults.map((rule) => (
                  <li key={rule.ruleId} className="border-b border-navy/5 pb-2">
                    <RuleRow program={p} rule={rule} />
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
      <p className="mt-6 rounded-lg bg-white/70 p-3 text-sm text-navy/80" role="note">{t('home.disclaimer')}</p>
    </div>
  );
}
