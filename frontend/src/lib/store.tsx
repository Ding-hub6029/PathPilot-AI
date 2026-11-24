'use client';
import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import en from '../../messages/en.json';
import zhCN from '../../messages/zh-CN.json';
import es from '../../messages/es.json';
import fr from '../../messages/fr.json';
import ptBR from '../../messages/pt-BR.json';
import ar from '../../messages/ar.json';
import { Profile, emptyProfile } from '../lib/types';

export type Locale = 'en' | 'zh-CN' | 'es' | 'fr' | 'pt-BR' | 'ar';
export const LOCALES: { code: Locale; label: string }[] = [
  { code: 'en', label: 'English' },
  { code: 'zh-CN', label: '简体中文' },
  { code: 'es', label: 'Español' },
  { code: 'fr', label: 'Français' },
  { code: 'pt-BR', label: 'Português (Brasil)' },
  { code: 'ar', label: 'العربية' },
];
const MESSAGES: Record<Locale, Record<string, string>> = {
  en: en as Record<string, string>,
  'zh-CN': zhCN as Record<string, string>,
  es: es as Record<string, string>,
  fr: fr as Record<string, string>,
  'pt-BR': ptBR as Record<string, string>,
  ar: ar as Record<string, string>,
};
export const RTL_LOCALES: Locale[] = ['ar'];

interface AppState {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string) => string;
  profile: Profile;
  setProfile: (p: Profile) => void;
  updateProfile: (patch: Partial<Profile>) => void;
  clearData: () => void;
}

const Ctx = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>('en');
  const [profile, setProfileState] = useState<Profile>(emptyProfile);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const savedLocale = localStorage.getItem('pp-locale') as Locale | null;
      if (savedLocale && MESSAGES[savedLocale]) setLocaleState(savedLocale);
      const savedProfile = localStorage.getItem('pp-profile');
      if (savedProfile) setProfileState({ ...emptyProfile, ...JSON.parse(savedProfile) });
    } catch { /* ignore corrupt local storage */ }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    document.documentElement.lang = locale;
    document.documentElement.dir = RTL_LOCALES.includes(locale) ? 'rtl' : 'ltr';
    localStorage.setItem('pp-locale', locale);
  }, [locale, hydrated]);

  useEffect(() => {
    if (!hydrated) return;
    localStorage.setItem('pp-profile', JSON.stringify(profile));
  }, [profile, hydrated]);

  const setLocale = (l: Locale) => setLocaleState(l);
  const setProfile = (p: Profile) => setProfileState(p);
  const updateProfile = (patch: Partial<Profile>) => setProfileState((prev) => ({ ...prev, ...patch }));
  const clearData = () => {
    setProfileState(emptyProfile);
    try { localStorage.removeItem('pp-profile'); } catch { /* ignore */ }
  };
  const t = (key: string) => MESSAGES[locale][key] ?? MESSAGES.en[key] ?? key;

  const value = useMemo(() => ({ locale, setLocale, t, profile, setProfile, updateProfile, clearData }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [locale, profile]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useApp must be used inside AppProvider');
  return ctx;
}
