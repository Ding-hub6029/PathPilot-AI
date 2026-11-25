'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useApp } from '../lib/store';
import { usePrograms } from '../lib/usePrograms';
import { sampleUndergrad, sampleMasters } from '../lib/types';
import { formatProgramLine } from '../lib/format';
import { displayProgramName } from '../lib/programs';
import { displayProgramInstitutionName } from '../lib/rankings';
import { WelcomeModal } from '../components/WelcomeModal';

export default function HomePage() {
  const { t, locale, setProfile } = useApp();
  const { programs, live: programsLive, loading: programsLoading } = usePrograms();
  const router = useRouter();

  const trySample = (which: 'ug' | 'pg') => {
    setProfile(which === 'ug' ? sampleUndergrad : sampleMasters);
    router.push('/results');
  };

  return (
    <div className="page-enter mx-auto max-w-6xl px-4 py-8">
      <WelcomeModal />
      {/* Hero with compass-rose / route-line draw-in */}
      <section className="grid items-center gap-8 rounded-3xl bg-navy p-8 text-white md:grid-cols-2">
        <div>
          <p className="anim-fade-up text-sm font-semibold uppercase tracking-widest text-amber">{t('tagline')}</p>
          <h1 className="anim-fade-up stagger-1 mt-2 text-3xl font-bold leading-tight md:text-4xl">{t('home.heroTitle')}</h1>
          <p className="anim-fade-up stagger-2 mt-3 text-white/85">{t('home.heroSub')}</p>
          <div className="anim-fade-up stagger-3 mt-6 flex flex-wrap gap-3">
            <Link href="/wizard" className="btn-press rounded-full bg-amber px-5 py-2.5 font-semibold text-navy">{t('home.ctaWizard')}</Link>
            <button type="button" onClick={() => trySample('ug')} className="btn-press rounded-full border border-white/50 px-5 py-2.5 font-semibold">{t('home.ctaSample')}</button>
          </div>
          <p className="anim-fade-up stagger-4 mt-5 rounded-lg bg-white/10 p-3 text-sm text-white/90" role="note">{t('home.disclaimer')}</p>
        </div>
        <div aria-hidden="true" className="mx-auto w-full max-w-md">
          <svg viewBox="0 0 400 260" className="w-full">
            <path className="anim-route" d="M30 220 C 110 200, 140 120, 200 110 S 320 60, 370 40" fill="none" stroke="#F2A541" strokeWidth="3" strokeLinecap="round" />
            <circle cx="30" cy="220" r="8" fill="#0E7C7B" stroke="#F7F5F0" strokeWidth="2" />
            <circle cx="200" cy="110" r="8" fill="#0E7C7B" stroke="#F7F5F0" strokeWidth="2" />
            <circle cx="370" cy="40" r="10" fill="#F2A541" stroke="#F7F5F0" strokeWidth="2" />
            <g className="anim-needle">
              <circle cx="330" cy="200" r="34" fill="none" stroke="#F7F5F0" strokeWidth="2" opacity=".7" />
              <path d="M330 172 L338 200 L330 228 L322 200 Z" fill="#F2A541" />
              <path d="M302 200 L330 192 L358 200 L330 208 Z" fill="#0E7C7B" />
            </g>
          </svg>
        </div>
      </section>

      {/* How it works */}
      <section className="mt-10">
        <h2 className="text-2xl font-bold">{t('home.howTitle')}</h2>
        <ol className="mt-4 grid gap-4 md:grid-cols-3">
          {[t('home.step1'), t('home.step2'), t('home.step3')].map((s, i) => (
            <li key={i} className={`card-lift anim-fade-up stagger-${i + 1} rounded-2xl border border-navy/10 bg-white p-5 shadow-sm`}>
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-teal font-bold text-white">{i + 1}</span>
              <p className="mt-3">{s}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* Programmes */}
      <section className="mt-10">
        <h2 className="text-2xl font-bold">{t('home.programsTitle')}</h2>
        {programsLoading && <p className="mt-2 text-sm text-navy/60">{t('programs.loading')}</p>}
        {!programsLoading && !programsLive && <p className="mt-2 rounded-lg bg-amber/20 p-3 text-sm font-semibold" role="status">{t('programs.offlineNote')}</p>}
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {programs.map((p, i) => (
            <article key={p.id} className={`card-lift anim-fade-up stagger-${i + 1} rounded-2xl border border-navy/10 bg-white p-5 shadow-sm`}>
              <p className="text-sm font-semibold text-teal">{displayProgramInstitutionName(p.institution, locale)} · {p.country}</p>
              <h3 className="mt-1 text-lg font-bold">{displayProgramName(p, locale)}</h3>
              <p className="mt-2 text-sm text-navy/75">
                {formatProgramLine(p, t, locale)}
                {p.ucasCode ? ` · UCAS ${p.ucasCode}` : ''}
              </p>
              <div className="mt-4 flex gap-2">
                <Link href={`/programs/${p.id}`} className="btn-press rounded-full bg-navy px-4 py-2 text-sm font-semibold text-white">{t('results.viewDetail')}</Link>
                <button type="button" onClick={() => trySample(p.degreeLevel === 'undergraduate' ? 'ug' : 'pg')} className="btn-press rounded-full border border-navy/30 px-4 py-2 text-sm font-semibold">
                  {t('home.ctaSample')} · <span className="text-xs font-normal">({t('common.synthetic')})</span>
                </button>
              </div>
            </article>
          ))}
        </div>
        <p className="mt-3 text-sm text-navy/60">{t('home.sampleNote')}</p>
      </section>
    </div>
  );
}
