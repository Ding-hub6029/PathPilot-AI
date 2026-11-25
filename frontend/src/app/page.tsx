'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useApp } from '../lib/store';
import { usePrograms } from '../lib/usePrograms';
import { sampleUndergrad, sampleMasters } from '../lib/types';
import { formatProgramLine } from '../lib/format';
import { displayProgramName } from '../lib/programs';
import { displayProgramInstitutionName } from '../lib/rankings';
import { WelcomeModal } from '../components/WelcomeModal';
import { TimelinePanel } from '../components/TimelinePanel';
import { BeforeAfter } from '../components/BeforeAfter';

export default function HomePage() {
  const { t, locale, setProfile } = useApp();
  const { programs, live: programsLive, loading: programsLoading } = usePrograms();
  const router = useRouter();

  // Opening moment (ref 3 — curtain pull-away): on the first visit of a
  // session a navy veil covers the hero, then slides away to reveal the
  // panorama. Skipped on repeat visits and under prefers-reduced-motion;
  // a safety timeout dismisses it even if the animation never fires.
  const [veil, setVeil] = useState(false);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      if (sessionStorage.getItem('pp-hero-veil')) return;
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        sessionStorage.setItem('pp-hero-veil', '1');
        return;
      }
      setVeil(true);
      timer = setTimeout(() => {
        try { sessionStorage.setItem('pp-hero-veil', '1'); } catch { /* ignore */ }
        setVeil(false);
      }, 2500);
    } catch { /* ignore */ }
    return () => { if (timer) clearTimeout(timer); };
  }, []);
  const dismissVeil = () => {
    try { sessionStorage.setItem('pp-hero-veil', '1'); } catch { /* ignore */ }
    setVeil(false);
  };

  const trySample = (which: 'ug' | 'pg') => {
    setProfile(which === 'ug' ? sampleUndergrad : sampleMasters);
    router.push('/results');
  };

  return (
    <div className="page-enter mx-auto max-w-6xl px-4 py-8">
      <WelcomeModal />
      {/* Hero with compass-rose / route-line draw-in */}
      <section className="relative grid items-center gap-8 overflow-hidden rounded-3xl bg-navy p-8 text-white md:grid-cols-2">
        {veil && (
          <div aria-hidden="true" className="anim-veil absolute inset-0 z-10 flex items-center justify-center bg-navy" onAnimationEnd={dismissVeil}>
            <p className="microcopy text-amber">{t('brand')} — {t('tagline')}</p>
          </div>
        )}
        <div>
          <p className="microcopy anim-fade-up text-amber">{t('tagline')}</p>
          <h1 className="hero-display anim-fade-up stagger-1 mt-3"><span className="grad-amber-text">{t('home.heroTitle')}</span></h1>
          <p className="anim-fade-up stagger-2 mt-4 max-w-md text-white/85">{t('home.heroSub')}</p>
          <div className="anim-fade-up stagger-3 mt-6 flex flex-wrap gap-3">
            <Link href="/wizard" className="btn-press rounded-full bg-amber px-5 py-2.5 font-semibold text-navy">{t('home.ctaWizard')}</Link>
            <button type="button" onClick={() => trySample('ug')} className="btn-press rounded-full border border-white/50 px-5 py-2.5 font-semibold">{t('home.ctaSample')}</button>
          </div>
          <p className="anim-fade-up stagger-4 mt-5 rounded-lg bg-white/10 p-3 text-sm text-white/90" role="note">{t('home.disclaimer')}</p>
          <p className="anim-fade-up stagger-4 mt-4 flex items-center justify-between gap-2">
            <span className="microcopy text-white/50" dir="ltr">NAVY · TEAL · AMBER</span>
            <span className="microcopy text-white/50">{t('home.heroKicker')}</span>
          </p>
        </div>
        <div aria-hidden="true" className="mx-auto w-full max-w-md">
          <svg viewBox="0 0 400 260" className="w-full">
            <defs>
              <radialGradient id="sphereGrad" cx="35%" cy="30%" r="75%">
                <stop offset="0%" stopColor="#F7F5F0" />
                <stop offset="55%" stopColor="#0E7C7B" />
                <stop offset="100%" stopColor="#0B1F3A" />
              </radialGradient>
            </defs>
            <path className="anim-route" d="M30 220 C 110 200, 140 120, 200 110 S 320 60, 370 40" fill="none" stroke="#F2A541" strokeWidth="3" strokeLinecap="round" />
            <circle cx="30" cy="220" r="8" fill="#0E7C7B" stroke="#F7F5F0" strokeWidth="2" />
            <circle cx="200" cy="110" r="8" fill="#0E7C7B" stroke="#F7F5F0" strokeWidth="2" />
            <circle cx="370" cy="40" r="10" fill="#F2A541" stroke="#F7F5F0" strokeWidth="2" />
            {/* 3D compass sphere: orbit ring, concentric rings, gradient sphere, swaying needle */}
            <g>
              <circle className="anim-orbit" cx="330" cy="200" r="52" fill="none" stroke="#F7F5F0" strokeWidth="1.5" strokeDasharray="4 7" opacity=".55" />
              <circle cx="330" cy="200" r="42" fill="none" stroke="#F7F5F0" strokeWidth="1.5" opacity=".7" />
              <circle cx="330" cy="200" r="34" fill="url(#sphereGrad)" opacity=".95" />
              <g className="anim-needle">
                <path d="M330 172 L338 200 L330 228 L322 200 Z" fill="#F2A541" />
                <path d="M302 200 L330 192 L358 200 L330 208 Z" fill="#F7F5F0" opacity=".9" />
              </g>
              <circle cx="330" cy="200" r="3" fill="#F7F5F0" />
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

      {/* Timeline + before/after (design upgrade 2026-11-25) */}
      <TimelinePanel />
      <BeforeAfter />

      {/* Programmes — fan-out stack (ref 1) with a verification ring per card */}
      <section className="mt-10">
        <h2 className="text-2xl font-bold">{t('home.programsTitle')}</h2>
        {programsLoading && <p className="mt-2 text-sm text-navy/60">{t('programs.loading')}</p>}
        {!programsLoading && !programsLive && <p className="mt-2 rounded-lg bg-amber/20 p-3 text-sm font-semibold" role="status">{t('programs.offlineNote')}</p>}
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {programs.map((p, i) => {
            // Verification ring: real official-source count, capped at 5 for
            // the ring scale; the number in the middle is the true count.
            const srcCount = p.sources.length;
            const frac = Math.min(srcCount, 5) / 5;
            const dash = 97.4 * (1 - frac);
            return (
            <article key={p.id} className={`card-lift anim-fan stagger-${(i % 4) + 1} rounded-2xl border border-navy/10 bg-white p-5 shadow-sm`} style={{ '--fan-rot': `${((i % 4) - 1.5) * 1.2}deg` } as React.CSSProperties}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-teal">{displayProgramInstitutionName(p.institution, locale)} · {p.country}</p>
                  <h3 className="mt-1 text-lg font-bold">{displayProgramName(p, locale)}</h3>
                </div>
                <span className="flex shrink-0 flex-col items-center" aria-label={`${srcCount} ${t('program.sources')}`}>
                  <svg width="40" height="40" viewBox="0 0 36 36" aria-hidden="true">
                    <circle cx="18" cy="18" r="15.5" fill="none" stroke="#0B1F3A" strokeOpacity=".12" strokeWidth="4" />
                    <circle className="anim-ring" cx="18" cy="18" r="15.5" fill="none" stroke="#F2A541" strokeWidth="4" strokeLinecap="round" transform="rotate(-90 18 18)" style={{ '--ring-dash': dash } as React.CSSProperties} />
                    <text x="18" y="22" textAnchor="middle" fontSize="11" fontWeight="800" fill="#0B1F3A">{srcCount}</text>
                  </svg>
                  <span className="microcopy mt-0.5 text-navy/50">{t('program.sources')}</span>
                </span>
              </div>
              <p className="mt-2 text-sm text-navy/75">
                {formatProgramLine(p, t, locale)}
                {p.ucasCode ? ` · UCAS ${p.ucasCode}` : ''}
              </p>
              <div className="mt-4 flex gap-2">
                <Link href={`/programs/${p.id}`} className="btn-press rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy">{t('results.viewDetail')}</Link>
                <button type="button" onClick={() => trySample(p.degreeLevel === 'undergraduate' ? 'ug' : 'pg')} className="btn-press rounded-full border border-navy/30 px-4 py-2 text-sm font-semibold">
                  {t('home.ctaSample')} · <span className="text-xs font-normal">({t('common.synthetic')})</span>
                </button>
              </div>
            </article>
            );
          })}
        </div>
        <p className="mt-3 text-sm text-navy/60">{t('home.sampleNote')}</p>
      </section>
    </div>
  );
}
