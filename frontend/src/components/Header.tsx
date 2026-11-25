'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useApp, LOCALES } from '../lib/store';

export default function Header() {
  const { t, locale, setLocale, clearData } = useApp();
  const [menuOpen, setMenuOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);

  const nav = (
    <>
      <Link href="/" className="rounded px-2 py-1 hover:bg-white/10">{t('nav.home')}</Link>
      <Link href="/wizard" className="rounded px-2 py-1 hover:bg-white/10">{t('nav.wizard')}</Link>
      <Link href="/results" className="rounded px-2 py-1 hover:bg-white/10">{t('nav.results')}</Link>
      <Link href="/rankings" className="rounded px-2 py-1 hover:bg-white/10">{t('nav.rankings')}</Link>
      <Link href="/report" className="rounded px-2 py-1 hover:bg-white/10">{t('nav.report')}</Link>
    </>
  );

  return (
    <header className="sticky top-0 z-50 bg-navy text-white shadow-md">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-3">
        <Link href="/" className="flex items-center gap-2 font-bold text-lg tracking-tight" aria-label="PathPilot AI">
          <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true" className="anim-needle">
            <circle cx="16" cy="16" r="14" fill="none" stroke="#F2A541" strokeWidth="2" />
            <path d="M16 6 L19 16 L16 26 L13 16 Z" fill="#F2A541" />
            <path d="M6 16 L16 13 L26 16 L16 19 Z" fill="#0E7C7B" />
            <circle cx="16" cy="16" r="2.5" fill="#F7F5F0" />
          </svg>
          {t('brand')}
        </Link>
        <nav className="hidden items-center gap-1 md:flex" aria-label="Main">{nav}</nav>
        <div className="flex items-center gap-2">
          <div className="relative">
            <button type="button" className="btn-press rounded-full border border-white/40 px-3 py-1 text-sm" aria-haspopup="listbox" aria-expanded={langOpen} onClick={() => setLangOpen((v) => !v)}>
              🌐 {LOCALES.find((l) => l.code === locale)?.label}
            </button>
            {langOpen && (
              <ul role="listbox" aria-label={t('common.language')} className="absolute end-0 mt-2 w-52 rounded-lg bg-white py-1 text-navy shadow-xl">
                {LOCALES.map((l) => (
                  <li key={l.code}>
                    <button type="button" role="option" aria-selected={locale === l.code} className="block w-full px-4 py-2 text-start hover:bg-paper" onClick={() => { setLocale(l.code); setLangOpen(false); }}>
                      {l.label}{locale === l.code ? ' ✓' : ''}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button type="button" onClick={clearData} className="btn-press hidden rounded-full border border-white/40 px-3 py-1 text-sm sm:block">{t('nav.clearData')}</button>
          <button type="button" className="btn-press rounded px-2 py-1 md:hidden" aria-expanded={menuOpen} aria-label="Menu" onClick={() => setMenuOpen((v) => !v)}>☰</button>
        </div>
      </div>
      {menuOpen && (
        <nav className="flex flex-col gap-1 px-4 pb-3 md:hidden" aria-label="Mobile">
          {nav}
          <button type="button" onClick={() => { clearData(); setMenuOpen(false); }} className="rounded px-2 py-1 text-start hover:bg-white/10">{t('nav.clearData')}</button>
        </nav>
      )}
    </header>
  );
}
