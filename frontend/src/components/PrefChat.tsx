'use client';
import { useEffect, useRef, useState } from 'react';
import { useApp } from '../lib/store';
import { Profile, emptyProfile } from '../lib/types';
import {
  PREF_COUNTRY_CODES,
  climateLabel, environmentLabel, afterGradLabel, pressureLabel, teachingLabel,
  prefSummary,
} from '../lib/preferences';
import { PROGRAMS } from '../lib/programs';
import { CompassFace, type PetMood } from './CompassPet';

/**
 * Preference step as a full-page AI chat with 小罗盘 (2026-11-25, user:
 * "怎么是填表？就不能是一个像AI聊天机器人一样的炫酷的页面来问吗？"
 * + "像真正的人一样的在我面前问我的，带表情，还有自己的观点").
 *
 * One question at a time, quick-reply chips + free text, skippable.
 * The same 8 questions and the same 10 Profile fields as the old form;
 * preferences never enter the matching engine. Every answer is saved
 * into the Profile the moment it is given (updateProfile -> localStorage
 * via the store), so going back or refreshing loses nothing: on mount
 * the chat resumes at the first unanswered question, rebuilt from the
 * stored Profile.
 *
 * The pet has a face AND opinions: its mood follows the chat (celebrate
 * on greeting / a liked answer, think while the user types, empathise
 * when the user is unsure or wants to take it easy), and after some
 * answers it volunteers a view — but every fact inside an opinion comes
 * from the verified data already shipped in the frontend (PROGRAMS):
 * which institutions are in London / Singapore, how many verified
 * programmes a city has. Anything not in the data is never stated.
 * No stars, no invented figures, no salary data.
 */

type PrefQId =
  | 'countries' | 'climate' | 'environment' | 'city'
  | 'afterGrad' | 'salary' | 'pressure' | 'teaching';

const QUESTIONS: PrefQId[] = [
  'countries', 'climate', 'environment', 'city',
  'afterGrad', 'salary', 'pressure', 'teaching',
];

const ASK_KEY: Record<PrefQId, string> = {
  countries: 'wizard.chatQCountries',
  climate: 'wizard.chatQClimate',
  environment: 'wizard.chatQEnvironment',
  city: 'wizard.chatQCity',
  afterGrad: 'wizard.chatQAfterGrad',
  salary: 'wizard.chatQSalary',
  pressure: 'wizard.chatQPressure',
  teaching: 'wizard.chatQTeaching',
};

/** The 10 Profile fields this chat owns — used by the restart button. */
const PREF_RESET: Partial<Profile> = {
  prefClimate: '', prefCountries: [], prefCountriesNote: '',
  prefEnvironment: '', prefCity: '', prefAfterGrad: '',
  prefSalary: '', prefSalaryCurrency: 'GBP',
  prefPressure: '', prefTeaching: '',
};

export function isPrefAnswered(q: PrefQId, p: Profile): boolean {
  switch (q) {
    case 'countries': return (p.prefCountries?.length ?? 0) > 0 || !!p.prefCountriesNote;
    case 'climate': return !!p.prefClimate;
    case 'environment': return !!p.prefEnvironment;
    case 'city': return !!p.prefCity;
    case 'afterGrad': return !!p.prefAfterGrad;
    case 'salary': return p.prefSalary !== '' && p.prefSalary !== undefined;
    case 'pressure': return !!p.prefPressure;
    case 'teaching': return !!p.prefTeaching;
  }
}

function firstUnanswered(p: Profile): number {
  const i = QUESTIONS.findIndex((q) => !isPrefAnswered(q, p));
  return i === -1 ? QUESTIONS.length : i;
}

/** Verified institutions in a country, from the shipped catalogue. */
function schoolsIn(country: string, locale: string): string {
  const names = [...new Set(PROGRAMS.filter((p) => p.country === country).map((p) => p.institution))];
  return names.join(locale === 'zh-CN' ? '、' : ', ');
}

export function PrefChat({ onDone }: { onDone: () => void }) {
  const { t, tf, locale, profile, updateProfile } = useApp();
  const [qIndex, setQIndex] = useState(0);
  const [mood, setMood] = useState<PetMood>('celebrate');
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const moodTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Resume: the store hydrates the Profile from localStorage after
  // mount, but the raw stored profile is readable right away — resume
  // at the first unanswered question so a refresh never loses answers.
  useEffect(() => {
    try {
      const raw = localStorage.getItem('pp-profile');
      if (raw) setQIndex(firstUnanswered({ ...emptyProfile, ...JSON.parse(raw) }));
    } catch { /* ignore corrupt storage */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [qIndex, profile]);

  useEffect(() => () => { if (moodTimerRef.current) clearTimeout(moodTimerRef.current); }, []);

  const flashMood = (m: PetMood) => {
    setMood(m);
    if (moodTimerRef.current) clearTimeout(moodTimerRef.current);
    moodTimerRef.current = setTimeout(() => setMood('idle'), 1600);
  };

  /** The user's answer to one question, in their own words (labels for
   * chips, verbatim for free text) — rendered at render time so a
   * locale switch never leaves a stale-language bubble. */
  const answerText = (q: PrefQId): string => {
    switch (q) {
      case 'countries': {
        const parts = [
          ...(profile.prefCountries ?? []).map((c) => t(`country.${c}`)),
          profile.prefCountriesNote ?? '',
        ].filter(Boolean);
        return parts.join('、');
      }
      case 'climate': return climateLabel(profile.prefClimate, t);
      case 'environment': return environmentLabel(profile.prefEnvironment, t);
      case 'city': return profile.prefCity ?? '';
      case 'afterGrad': return afterGradLabel(profile.prefAfterGrad, t);
      case 'salary': return `${profile.prefSalary} ${profile.prefSalaryCurrency ?? ''}`.trim();
      case 'pressure': return pressureLabel(profile.prefPressure, t);
      case 'teaching': return teachingLabel(profile.prefTeaching, t);
    }
  };

  /**
   * The pet's own view after an answer. Only facts from the verified
   * catalogue (PROGRAMS) are used: institution names per country and
   * verified-programme counts per city. Returns the locale key + vars,
   * or null for a plain acknowledgement. The mood follows the opinion:
   * empathise when the user is unsure or wants it easy, celebrate
   * otherwise.
   */
  const opinion = (q: PrefQId, p: Profile): { key: string; vars?: Record<string, string | number>; mood: PetMood } | null => {
    switch (q) {
      case 'countries': {
        const codes = p.prefCountries ?? [];
        if (codes.includes('GB')) return { key: 'wizard.chatOpGB', vars: { schools: schoolsIn('GB', locale) }, mood: 'celebrate' };
        if (codes.includes('SG')) return { key: 'wizard.chatOpSG', vars: { schools: schoolsIn('SG', locale) }, mood: 'celebrate' };
        return { key: 'wizard.chatOpThanks', mood: 'celebrate' };
      }
      case 'climate':
        if (p.prefClimate === 'warm') return { key: 'wizard.chatOpWarm', mood: 'celebrate' };
        return { key: 'wizard.chatOpThanks', mood: 'celebrate' };
      case 'city': {
        const want = (p.prefCity ?? '').trim().toLowerCase();
        if (!want) return null;
        const count = PROGRAMS.filter((x) => (x.city ?? '').toLowerCase() === want).length;
        if (count > 0) return { key: 'wizard.chatOpCity', vars: { city: p.prefCity ?? '', count }, mood: 'celebrate' };
        return { key: 'wizard.chatOpThanks', mood: 'celebrate' };
      }
      case 'afterGrad':
        if (p.prefAfterGrad === 'undecided') return { key: 'wizard.chatOpAfterGradUndecided', mood: 'empathise' };
        return { key: 'wizard.chatOpThanks', mood: 'celebrate' };
      case 'salary':
        return { key: 'wizard.chatOpSalary', mood: 'idle' };
      case 'pressure':
        if (p.prefPressure === 'low') return { key: 'wizard.chatOpPressureLow', mood: 'empathise' };
        return { key: 'wizard.chatOpThanks', mood: 'celebrate' };
      default:
        return { key: 'wizard.chatOpThanks', mood: 'celebrate' };
    }
  };

  const currentQ = qIndex < QUESTIONS.length ? QUESTIONS[qIndex] : null;

  const answerSingle = (q: PrefQId, patch: Partial<Profile>) => {
    updateProfile(patch);
    // The opinion needs the just-saved value, which is not in `profile`
    // yet at call time — compute it from the merged profile.
    const op = opinion(q, { ...profile, ...patch });
    flashMood(op?.mood ?? 'celebrate');
    setInput('');
    setQIndex((i) => Math.min(i + 1, QUESTIONS.length));
  };

  const skip = () => {
    setInput('');
    setQIndex((i) => Math.min(i + 1, QUESTIONS.length));
  };

  const restart = () => {
    updateProfile(PREF_RESET);
    setInput('');
    setQIndex(0);
    flashMood('celebrate');
  };

  const done = qIndex >= QUESTIONS.length;
  const shownMood: PetMood = input.trim() ? 'think' : mood;

  const singleChips: Record<string, [string, string][]> = {
    climate: [['warm', t('wizard.prefClimateWarm')], ['cool', t('wizard.prefClimateCool')], ['four_seasons', t('wizard.prefClimateFourSeasons')], ['mild', t('wizard.prefClimateMild')]],
    environment: [['big_city', t('wizard.prefEnvironmentBigCity')], ['small_city', t('wizard.prefEnvironmentSmallCity')], ['campus', t('wizard.prefEnvironmentCampus')], ['quiet_town', t('wizard.prefEnvironmentQuietTown')]],
    afterGrad: [['stay', t('wizard.prefAfterGradStay')], ['return_home', t('wizard.prefAfterGradReturnHome')], ['hometown', t('wizard.prefAfterGradHometown')], ['undecided', t('wizard.prefAfterGradUndecided')]],
    pressure: [['low', t('wizard.prefPressureLow')], ['medium', t('wizard.prefPressureMedium')], ['high', t('wizard.prefPressureHigh')]],
    teaching: [['lecture', t('wizard.prefTeachingLecture')], ['seminar', t('wizard.prefTeachingSeminar')], ['hands_on', t('wizard.prefTeachingHandsOn')]],
  };
  const singleField: Record<string, keyof Profile> = {
    climate: 'prefClimate', environment: 'prefEnvironment',
    afterGrad: 'prefAfterGrad', pressure: 'prefPressure', teaching: 'prefTeaching',
  };
  const CITY_CHIPS = ['London', 'Singapore', 'Boston', 'Toronto'];

  const summary = prefSummary(profile, t);
  const hasSalary = profile.prefSalary !== '' && profile.prefSalary !== undefined;

  return (
    <div>
      <div className="flex items-start gap-3">
        <span className="anim-pet-bob inline-flex shrink-0 rounded-full bg-teal/10 p-1">
          <CompassFace size={56} mood={shownMood} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-bold">{t('wizard.chatTitle')}</h2>
          <p className="mt-1 text-sm text-navy/70">
            {done
              ? tf('wizard.chatProgressDone', { total: QUESTIONS.length })
              : tf('wizard.chatProgress', { n: qIndex + 1, total: QUESTIONS.length })}
            {' · '}
            <button type="button" onClick={onDone} className="font-semibold text-teal-dark underline underline-offset-2">{t('wizard.chatSkipAll')}</button>
          </p>
        </div>
      </div>

      <div className="mt-4 space-y-3 rounded-2xl bg-paper p-4" aria-live="polite">
        {/* Opening line from the pet. */}
        <div className="flex justify-start">
          <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5 anim-fade-up">
            <p>{t('wizard.chatIntro')}</p>
          </div>
        </div>

        {/* History: one pet question + the user's answer + the pet's
            view, per answered question. Everything renders from the
            stored Profile, so a refresh rebuilds the same chat. */}
        {QUESTIONS.slice(0, Math.min(qIndex, QUESTIONS.length)).map((q) => {
          const op = opinion(q, profile);
          return (
            <div key={q} className="space-y-3">
              <div className="flex justify-start">
                <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5">
                  <p>{t(ASK_KEY[q])}</p>
                </div>
              </div>
              {isPrefAnswered(q, profile) && (
                <div className="flex justify-end">
                  <div className="max-w-[90%] rounded-2xl bg-teal px-4 py-3 text-white">
                    <p>{answerText(q)}</p>
                  </div>
                </div>
              )}
              {isPrefAnswered(q, profile) && op && (
                <div className="flex justify-start">
                  <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5">
                    <p>{op.vars ? tf(op.key, op.vars) : t(op.key)}</p>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {/* Current question. */}
        {currentQ && (
          <div className="space-y-3">
            <div className="flex justify-start">
              <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5 anim-fade-up">
                <p>{t(ASK_KEY[currentQ])}</p>
              </div>
            </div>

            {/* Countries: multi-select chips + free-text note + confirm. */}
            {currentQ === 'countries' && (
              <div className="flex flex-wrap gap-2">
                {PREF_COUNTRY_CODES.map((code) => {
                  const on = (profile.prefCountries ?? []).includes(code);
                  return (
                    <button key={code} type="button" aria-pressed={on}
                      onClick={() => {
                        const cur = profile.prefCountries ?? [];
                        updateProfile({ prefCountries: on ? cur.filter((c) => c !== code) : [...cur, code] });
                      }}
                      className={`btn-press anim-chip rounded-full border-2 px-3 py-1.5 text-sm font-semibold ${on ? 'border-teal bg-teal/5 text-teal-dark' : 'border-navy/15 bg-white'}`}>
                      {t(`country.${code}`)}
                    </button>
                  );
                })}
              </div>
            )}

            {/* Single-choice questions: tap a chip to answer at once. */}
            {currentQ in singleChips && (
              <div className="flex flex-wrap gap-2">
                {singleChips[currentQ].map(([v, label]) => (
                  <button key={v} type="button"
                    onClick={() => answerSingle(currentQ, { [singleField[currentQ]]: v } as Partial<Profile>)}
                    className="btn-press anim-chip rounded-full border-2 border-navy/15 bg-white px-3 py-1.5 text-sm font-semibold">
                    {label}
                  </button>
                ))}
              </div>
            )}

            {/* City: chips + free text. */}
            {currentQ === 'city' && (
              <div className="flex flex-wrap gap-2">
                {CITY_CHIPS.map((city) => (
                  <button key={city} type="button"
                    onClick={() => answerSingle(currentQ, { prefCity: city })}
                    className="btn-press anim-chip rounded-full border-2 border-navy/15 bg-white px-3 py-1.5 text-sm font-semibold">
                    {city}
                  </button>
                ))}
              </div>
            )}

            {/* Salary: amount + currency chips + confirm. */}
            {currentQ === 'salary' && (
              <div className="flex flex-wrap items-center gap-2">
                <input type="number" step="1" min={0} inputMode="decimal"
                  value={profile.prefSalary ?? ''} placeholder={t('wizard.prefSalaryPlaceholder')}
                  aria-label={t('wizard.prefSalaryQ')}
                  onChange={(e) => { const v = e.target.value; updateProfile({ prefSalary: v === '' ? '' : Number(v) }); }}
                  className="w-36 rounded-full border border-navy/25 bg-white px-3 py-2 text-sm" />
                {(['GBP', 'SGD', 'USD'] as const).map((c) => (
                  <button key={c} type="button" aria-pressed={(profile.prefSalaryCurrency ?? 'GBP') === c}
                    onClick={() => updateProfile({ prefSalaryCurrency: c })}
                    className={`btn-press rounded-full border-2 px-3 py-1.5 text-sm font-semibold ${(profile.prefSalaryCurrency ?? 'GBP') === c ? 'border-teal bg-teal/5 text-teal-dark' : 'border-navy/15 bg-white'}`}>
                    {c}
                  </button>
                ))}
              </div>
            )}

            {/* Free-text line (all questions except the confirm ones
                keep a type-your-own box; countries uses it for the
                "other countries" note and salary has its own input). */}
            {currentQ !== 'salary' && (
              <div className="flex gap-2">
                <input value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key !== 'Enter' || !input.trim()) return;
                    const text = input.trim();
                    if (currentQ === 'countries') { updateProfile({ prefCountriesNote: text }); flashMood('celebrate'); setInput(''); setQIndex((i) => Math.min(i + 1, QUESTIONS.length)); }
                    else if (currentQ === 'city') { answerSingle(currentQ, { prefCity: text }); }
                    else { answerSingle(currentQ, { [singleField[currentQ]]: text } as Partial<Profile>); }
                  }}
                  placeholder={currentQ === 'countries' ? t('wizard.prefCountriesOther') : currentQ === 'city' ? t('wizard.prefCityPlaceholder') : t('wizard.prefFreeText')}
                  aria-label={t('wizard.chatTypePlaceholder')}
                  className="min-w-0 flex-1 rounded-full border border-navy/25 bg-white px-3 py-2 text-sm" />
                <button type="button"
                  onClick={() => {
                    if (currentQ === 'countries') {
                      if (input.trim()) updateProfile({ prefCountriesNote: input.trim() });
                      flashMood('celebrate'); setInput(''); setQIndex((i) => Math.min(i + 1, QUESTIONS.length));
                    } else if (currentQ === 'city') {
                      if (input.trim()) answerSingle(currentQ, { prefCity: input.trim() });
                    } else if (input.trim()) {
                      answerSingle(currentQ, { [singleField[currentQ]]: input.trim() } as Partial<Profile>);
                    }
                  }}
                  disabled={currentQ !== 'countries' && !input.trim()}
                  className="btn-press shrink-0 rounded-full bg-teal px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">
                  {t('wizard.chatSend')}
                </button>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3">
              {currentQ === 'countries' && (
                <button type="button"
                  onClick={() => { flashMood(opinion('countries', profile)?.mood ?? 'celebrate'); setQIndex((i) => Math.min(i + 1, QUESTIONS.length)); }}
                  className="btn-press rounded-full bg-navy px-4 py-2 text-sm font-semibold text-white">
                  {t('wizard.chatNext')}
                </button>
              )}
              {currentQ === 'salary' && (
                <button type="button"
                  onClick={() => { if (hasSalary) flashMood('idle'); setQIndex((i) => Math.min(i + 1, QUESTIONS.length)); }}
                  className="btn-press rounded-full bg-navy px-4 py-2 text-sm font-semibold text-white">
                  {t('wizard.chatNext')}
                </button>
              )}
              {qIndex > 0 && (
                <button type="button" onClick={() => setQIndex((i) => Math.max(0, i - 1))} className="btn-press text-sm font-semibold text-navy/70 underline underline-offset-2">
                  {t('wizard.chatBack')}
                </button>
              )}
              <button type="button" onClick={skip} className="btn-press text-sm font-semibold text-teal-dark underline underline-offset-2">
                {t('wizard.chatSkip')}
              </button>
            </div>
          </div>
        )}

        {/* Summary bubble once all 8 are asked. */}
        {done && (
          <div className="space-y-3">
            <div className="flex justify-start">
              <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5 anim-fade-up">
                <p>{summary ? tf('wizard.chatSummary', { summary }) : t('wizard.chatSummaryEmpty')}</p>
                {hasSalary && <p className="mt-1 text-sm text-navy/70">{t('wizard.chatSalaryNote')}</p>}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={onDone} className="btn-press rounded-full bg-amber px-5 py-2 font-semibold text-navy">
                {t('wizard.finish')}
              </button>
              <button type="button" onClick={restart} className="btn-press rounded-full border border-navy/30 bg-white px-4 py-2 text-sm font-semibold">
                {t('wizard.chatRestart')}
              </button>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
