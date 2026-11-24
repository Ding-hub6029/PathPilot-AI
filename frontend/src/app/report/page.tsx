'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useApp } from '../../lib/store';
import { usePrograms } from '../../lib/usePrograms';
import { matchProfile } from '../../lib/api';
import { MatchResponse } from '../../lib/types';
import { StatusChip } from '../../components/StatusChip';

export default function ReportPage() {
  const { t, profile } = useApp();
  const { programs } = usePrograms();
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
      <div className="page-enter mx-auto max-w-3xl px-4 py-12 text-center">
        <p className="text-lg">{t('results.empty')}</p>
        <Link href="/wizard" className="btn-press mt-6 inline-block rounded-full bg-navy px-6 py-3 font-semibold text-white">{t('results.goWizard')}</Link>
      </div>
    );
  }

  return (
    <div className="page-enter mx-auto max-w-4xl px-4 py-8">
      <h1 className="text-2xl font-bold">{t('report.title')}</h1>
      <p className="mt-2 text-sm text-navy/70">{t('report.summary')} · {new Date().toLocaleDateString()}</p>
      {profile.sample && <p className="mt-2 inline-block rounded-lg bg-amber/25 px-3 py-1 text-sm font-semibold">{t('common.synthetic')}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={downloadJson} className="btn-press rounded-full bg-navy px-5 py-2 font-semibold text-white">{t('report.downloadJson')}</button>
        <button type="button" onClick={() => window.print()} className="btn-press rounded-full border border-navy/30 bg-white px-5 py-2 font-semibold">{t('report.print')}</button>
      </div>
      <div className="mt-6 space-y-4">
        {(data?.results ?? []).map((r) => {
          const p = programs.find((x) => x.id === r.programId);
          if (!p) return null;
          return (
            <section key={r.programId} className="rounded-2xl border border-navy/10 bg-white p-5 shadow-sm">
              <h2 className="text-lg font-bold">{p.institution} — {p.officialName}</h2>
              <p className="text-sm text-navy/70">{p.intakeLabel} · {p.feeItems.map((f) => `${f.currency} ${f.amount.toLocaleString()} ${f.period}`).join(', ')}</p>
              <ul className="mt-3 space-y-2">
                {r.ruleResults.map((rule) => (
                  <li key={rule.ruleId} className="flex flex-wrap items-center justify-between gap-2 border-b border-navy/5 pb-2 text-sm">
                    <span>{rule.expected} — <span className="text-navy/70">{rule.observed}</span></span>
                    <StatusChip status={rule.status} />
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
