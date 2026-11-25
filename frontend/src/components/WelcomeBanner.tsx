'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useApp } from '../lib/store';

/**
 * First-visit reminder as a top banner (rework 2026-11-25, user testing:
 * "你这弹窗不应该放在页面最上面吗？怎么放到中间去了？我刚打开这个
 * 网站我还以为黑屏了"). The old centred modal + full-screen dark
 * overlay (bg-navy/50 over the whole viewport) made the site look like
 * a black screen on first open. Now a dismissible in-flow banner at the
 * very top of the homepage, below the sticky nav and above the hero —
 * no overlay, no fixed positioning, nothing ever darkens the screen.
 *
 * Stacking: the banner is in normal flow as a sibling above the hero
 * section, so the hero veil (absolute inset-0 z-10, scoped inside the
 * hero section) cannot cover it; and it is in-flow, so it never covers
 * the sticky nav (z-50) either.
 *
 * Shows EVERY new session (sessionStorage 'pp-welcome-shown'), whether
 * or not an eligibility check was completed (localStorage 'pp-check-done',
 * set by the results page). The old rule hid it forever after one
 * completed check, so a returning user never saw it again — the user
 * asked "弹窗怎么又没了？" and expects it on open. Closing it hides it
 * only for the rest of the session.
 *
 * No flash: the banner renders nothing until the client has mounted and
 * read sessionStorage (state starts 'unknown'), so a repeat visit in
 * the same session never paints the banner and then hides it.
 */
export function WelcomeBanner() {
  const { t } = useApp();
  // 'unknown' = not mounted yet (render nothing); 'open' / 'closed' =
  // decided from sessionStorage after mount.
  const [state, setState] = useState<'unknown' | 'open' | 'closed'>('unknown');
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    try {
      if (sessionStorage.getItem('pp-welcome-shown')) { setState('closed'); return; }
      setChecked(!!localStorage.getItem('pp-check-done'));
      sessionStorage.setItem('pp-welcome-shown', '1');
    } catch { /* ignore storage errors */ }
    setState('open');
  }, []);

  if (state !== 'open') return null;
  return (
    <div data-testid="welcome-banner" role="region" aria-labelledby="welcome-title" className="anim-fade-in mb-6 flex flex-wrap items-center gap-4 rounded-2xl bg-navy p-4 text-white shadow-lg sm:flex-nowrap sm:p-5">
      <svg width="48" height="48" viewBox="0 0 72 72" aria-hidden="true" className="shrink-0">
        <circle cx="36" cy="36" r="32" fill="#F2A541" />
        <circle cx="25" cy="30" r="4" fill="#0B1F3A" />
        <circle cx="47" cy="30" r="4" fill="#0B1F3A" />
        <path d="M24 42 Q36 54 48 42" fill="none" stroke="#0B1F3A" strokeWidth="4" strokeLinecap="round" />
      </svg>
      <div className="min-w-0 flex-1">
        <h2 id="welcome-title" className="text-lg font-bold">{checked ? t('home.welcomeBackTitle') : t('home.welcomeTitle')}</h2>
        <p className="mt-0.5 text-sm text-white/85">{checked ? t('home.welcomeBackBody') : t('home.welcomeBody')}</p>
        {!checked && <p className="mt-1 text-sm font-semibold text-amber">{t('results.empty')}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {checked ? (
          <Link href="/results" className="btn-press rounded-full bg-amber px-5 py-2.5 font-semibold text-navy">{t('home.welcomeBackCta')}</Link>
        ) : (
          <Link href="/wizard" className="btn-press rounded-full bg-amber px-5 py-2.5 font-semibold text-navy">{t('home.ctaWizard')}</Link>
        )}
        <button type="button" onClick={() => setState('closed')} aria-label={t('common.close')} className="btn-press rounded-full border border-white/40 px-4 py-2.5 text-sm font-semibold">{t('common.close')}</button>
      </div>
    </div>
  );
}
