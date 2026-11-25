'use client';
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useApp } from '../../lib/store';
import { usePrograms } from '../../lib/usePrograms';
import { matchProfile, mergePrograms } from '../../lib/api';
import { MatchResponse } from '../../lib/types';
import { RuleRow } from '../../components/RuleRow';
import { formatProgramLine } from '../../lib/format';
import { displayProgramTitle } from '../../lib/programs';

export default function ReportPage() {
  const { t, tf, locale, profile } = useApp();
  const f = { t, tf, locale };
  const { programs: livePrograms } = usePrograms();
  // Round 6: lookups cover the merged list (live v2 + expansion mirror).
  const programs = useMemo(() => mergePrograms(livePrograms), [livePrograms]);
  const [data, setData] = useState<MatchResponse | null>(null);

  useEffect(() => {
    if (!profile.track || profile.targetProgramIds.length === 0) return;
    matchProfile(profile).then(setData).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile.track, JSON.stringify(profile.targetProgramIds)]);

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify({ generatedAt: new Date().toISOString(), profile: { ...profile }, evaluation: data }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'pathpilot-report.json'; a.click();
    URL.revokeObjectURL(url);
  };

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
      <p className="mt-2 text-sm text-navy/70">{t('report.summary')} · {new Date().toLocaleDateString()}</p>
      {profile.sample && <p className="mt-2 inline-block rounded-lg bg-amber/25 px-3 py-1 text-sm font-semibold">{t('common.synthetic')}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={downloadJson} className="btn-press rounded-full bg-navy px-5 py-2 font-semibold text-white">{t('report.downloadJson')}</button>
        <button type="button" onClick={() => window.print()} className="btn-press rounded-full border border-navy/30 bg-white px-5 py-2 font-semibold">{t('report.print')}</button>
        <Link href="/results" className="btn-press rounded-full border border-navy/30 bg-white px-5 py-2 font-semibold">{t('report.backToResults')}</Link>
      </div>
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
