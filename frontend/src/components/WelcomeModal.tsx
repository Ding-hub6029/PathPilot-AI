'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useApp } from '../lib/store';

/**
 * First-visit reminder (fix 2026-11-25, req. B): when a user first opens
 * the site with no eligibility check yet, a friendly popup points them
 * to the check. Dismissible; once dismissed — or once a check exists —
 * it never reappears (localStorage 'pp-welcome-dismissed'). Motion uses
 * the existing anim-fade-in class, which the global
 * prefers-reduced-motion rule already neutralises.
 */
export function WelcomeModal() {
  const { t } = useApp();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem('pp-welcome-dismissed')) return;
      const saved = localStorage.getItem('pp-profile');
      if (saved) {
        const p = JSON.parse(saved) as { track?: string; targetProgramIds?: unknown[] };
        if (p?.track && Array.isArray(p.targetProgramIds) && p.targetProgramIds.length > 0) return;
      }
    } catch { /* ignore corrupt local storage */ }
    setOpen(true);
  }, []);

  const dismiss = () => {
    try { localStorage.setItem('pp-welcome-dismissed', '1'); } catch { /* ignore */ }
    setOpen(false);
  };

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-navy/50 p-4" role="presentation" onClick={dismiss}>
      <div role="dialog" aria-modal="true" aria-labelledby="welcome-title" className="anim-fade-in w-full max-w-md rounded-3xl bg-white p-6 text-center shadow-xl" onClick={(e) => e.stopPropagation()}>
        <svg width="72" height="72" viewBox="0 0 72 72" aria-hidden="true" className="mx-auto">
          <circle cx="36" cy="36" r="32" fill="#F2A541" />
          <circle cx="25" cy="30" r="4" fill="#0B1F3A" />
          <circle cx="47" cy="30" r="4" fill="#0B1F3A" />
          <path d="M24 42 Q36 54 48 42" fill="none" stroke="#0B1F3A" strokeWidth="4" strokeLinecap="round" />
        </svg>
        <h2 id="welcome-title" className="mt-3 text-xl font-bold">{t('home.welcomeTitle')}</h2>
        <p className="mt-2 text-sm text-navy/70">{t('home.welcomeBody')}</p>
        <Link href="/wizard" onClick={dismiss} className="btn-press mt-5 inline-block rounded-full bg-amber px-6 py-2.5 font-semibold text-navy">{t('home.ctaWizard')}</Link>
        <p className="mt-3 text-sm text-navy/60">{t('results.empty')}</p>
        <button type="button" onClick={dismiss} className="btn-press mt-4 rounded-full border border-navy/25 px-4 py-2 text-sm font-semibold">{t('common.close')}</button>
      </div>
    </div>
  );
}
