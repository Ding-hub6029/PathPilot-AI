'use client';
import { useState } from 'react';
import { useApp } from '../lib/store';

/**
 * Before / after split (design upgrade 2026-11-25, ref 3 — before/after
 * split-screen): "before choosing" is a confused list, "after choosing" is
 * the clear shortlist PathPilot produces. A range slider moves the split;
 * the range input is natively keyboard-accessible. The after layer is
 * clipped with a logical inset so the split mirrors correctly in RTL
 * (see .ba-after in globals.css). Copy is generic product narrative —
 * no programme facts are stated here.
 */
export function BeforeAfter() {
  const { t } = useApp();
  const [split, setSplit] = useState(50);

  const before = [t('home.before1'), t('home.before2'), t('home.before3')];
  const after = [t('home.after1'), t('home.after2'), t('home.after3')];

  return (
    <section className="mt-10" aria-labelledby="ba-title">
      <p className="microcopy text-teal-dark">{t('home.beforeAfterTitle')}</p>
      <h2 id="ba-title" className="mt-1 text-2xl font-bold tracking-tight">{t('home.beforeAfterTitle')}</h2>

      <div
        className="relative mt-5 overflow-hidden rounded-3xl border border-navy/10 shadow-lg"
        style={{ ['--split' as string]: `${split}%` }}
      >
        {/* Before layer (base) */}
        <div className="grid gap-6 bg-white p-6 sm:grid-cols-2 sm:p-8">
          <div>
            <p className="microcopy text-navy/50">{t('home.beforeTitle')}</p>
            <ul className="mt-3 space-y-3">
              {before.map((s, i) => (
                <li key={i} className="flex items-start gap-2 text-navy/75">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-navy/10 text-xs font-bold text-navy/60" aria-hidden="true">×</span>
                  <span>{s}</span>
                </li>
              ))}
            </ul>
          </div>
          <div aria-hidden="true">
            <p className="microcopy text-navy/50">{t('home.afterTitle')}</p>
            <ul className="mt-3 space-y-3">
              {after.map((s, i) => (
                <li key={i} className="flex items-start gap-2 text-navy/30">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-navy/10 text-xs font-bold" aria-hidden="true">✓</span>
                  <span>{s}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* After layer (clipped to the split) */}
        <div className="ba-after absolute inset-0 bg-navy text-white" aria-hidden="true">
          <div className="grid h-full gap-6 p-6 sm:grid-cols-2 sm:p-8">
            <div>
              <p className="microcopy text-white/50">{t('home.beforeTitle')}</p>
              <ul className="mt-3 space-y-3">
                {before.map((s, i) => (
                  <li key={i} className="flex items-start gap-2 text-white/40">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-bold" aria-hidden="true">×</span>
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="microcopy text-amber">{t('home.afterTitle')}</p>
              <ul className="mt-3 space-y-3">
                {after.map((s, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber text-xs font-bold text-navy" aria-hidden="true">✓</span>
                    <span className="font-semibold">{s}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        {/* Divider handle */}
        <div
          className="pointer-events-none absolute inset-y-0 w-0.5 bg-amber"
          style={{ insetInlineStart: `${split}%` }}
          aria-hidden="true"
        >
          <span className="absolute top-1/2 flex h-10 w-10 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-amber text-lg font-bold text-navy shadow-lg [dir=rtl]:translate-x-1/2">
            ⇄
          </span>
        </div>
      </div>

      <label className="mt-3 flex items-center gap-3 text-sm font-semibold">
        <span>{t('home.beforeAfterHint')}</span>
        <input
          type="range"
          min={5}
          max={95}
          value={split}
          onChange={(e) => setSplit(Number(e.target.value))}
          className="ba-range w-full max-w-xs"
          aria-label={t('home.beforeAfterHint')}
        />
        <span className="text-navy/60" dir="ltr">{split}%</span>
      </label>
    </section>
  );
}
