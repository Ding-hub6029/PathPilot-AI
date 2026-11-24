'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useApp } from '../../../lib/store';
import { usePrograms } from '../../../lib/usePrograms';
import { matchProfile } from '../../../lib/api';
import { MatchResponse } from '../../../lib/types';
import { StatusChip } from '../../../components/StatusChip';
import { EvidenceDrawer } from '../../../components/EvidenceDrawer';

export default function ProgramDetail({ params }: { params: { id: string } }) {
  const { t, profile } = useApp();
  const { programs } = usePrograms();
  const [data, setData] = useState<MatchResponse | null>(null);
  const program = programs.find((p) => p.id === params.id);

  useEffect(() => {
    if (!program || !profile.track) return;
    matchProfile({ ...profile, targetProgramIds: [program.id] }).then(setData).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  if (!program) {
    return <div className="mx-auto max-w-3xl px-4 py-12"><p>{t('common.error')}</p><Link href="/results" className="text-teal-dark underline">{t('program.back')}</Link></div>;
  }
  const result = data?.results.find((r) => r.programId === program.id);

  return (
    <div className="page-enter mx-auto max-w-4xl px-4 py-8">
      <Link href="/results" className="btn-press inline-block rounded-full border border-navy/25 bg-white px-4 py-2 text-sm font-semibold">← {t('program.back')}</Link>
      <h1 className="mt-4 text-2xl font-bold">{program.institution} — {program.officialName}</h1>
      <p className="mt-1 text-navy/70">{program.country} · {program.intakeLabel} · {program.duration}</p>
      <div className="mt-4 grid gap-3 rounded-2xl border border-navy/10 bg-white p-5 shadow-sm sm:grid-cols-3">
        <div><p className="text-sm font-semibold text-navy/60">{t('program.fee')}</p><p className="font-bold">{program.feeItems.map((f) => `${f.currency} ${f.amount.toLocaleString()} ${f.period}`).join(', ')}</p></div>
        <div><p className="text-sm font-semibold text-navy/60">{t('program.duration')}</p><p className="font-bold">{program.duration}</p></div>
        <div><p className="text-sm font-semibold text-navy/60">{t('program.intake')}</p><p className="font-bold">{program.intakeLabel}</p></div>
      </div>

      <section className="mt-8" aria-labelledby="req-title">
        <h2 id="req-title" className="text-xl font-bold">{t('program.requirements')}</h2>
        {result?.trackMismatch && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 font-semibold text-red-800">{t('results.trackMismatch')}</p>}
        {result && !result.trackMismatch && (
          <ul className="mt-4 space-y-3">
            {result.ruleResults.map((rule) => {
              return (
                <li key={rule.ruleId} className="card-lift rounded-2xl border border-navy/10 bg-white p-4 shadow-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-bold">{rule.expected}</p>
                    <StatusChip status={rule.status} />
                  </div>
                  <p className="mt-1 text-sm text-navy/75">{rule.observed}</p>
                  {rule.status === 'UNKNOWN' && <p className="mt-1 text-sm font-semibold text-amber-dark">{rule.unknownReason ?? t('program.unknownNote')}</p>}
                  <EvidenceDrawer program={program} rule={rule} />
                </li>
              );
            })}
          </ul>
        )}
        {!result && <p className="mt-4 text-navy/70">{t('results.empty')}</p>}
      </section>

      <section className="mt-8" aria-labelledby="src-title">
        <h2 id="src-title" className="text-xl font-bold">{t('program.sources')}</h2>
        <ul className="mt-3 space-y-2">
          {program.sources.map((s) => (
            <li key={s.id} className="rounded-lg border border-navy/10 bg-white p-3 text-sm">
              <a href={s.url} target="_blank" rel="noreferrer" className="font-semibold text-teal-dark underline">{s.label}</a>
              <span className="ms-2 text-navy/60">· {t('program.sourceVerified')} {s.verifiedDate} · {t('evidence.intakeApplies')}: {s.appliesTo || program.intakeLabel}</span>
              {s.excerpt && <p className="mt-1 italic text-navy/75" lang="en" dir="ltr">“{s.excerpt}” <span className="not-italic text-xs font-semibold text-navy/60">— {t('evidence.englishOnly')}</span></p>}
            </li>
          ))}
        </ul>
      </section>
      <p className="mt-6 rounded-lg bg-white/70 p-3 text-sm text-navy/80" role="note">{t('home.disclaimer')}</p>
    </div>
  );
}
