'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useApp, type Locale } from '../lib/store';
import type { Profile } from '../lib/types';
import { fetchJson, fetchJsonChat, fetchJsonPatient, modelAvailability, allPrograms, findProgram } from '../lib/api';
import { useElapsed } from '../lib/useElapsed';
import { deriveChatLinks, isModelReply, petKnownSteps, savedPrefsContext, suggestMessage, type ChatHistoryTurn, type ChatReply } from '../lib/chat';
import { hasPreferences, prefSummary } from '../lib/preferences';
import { PROGRAMS, displayProgramTitle } from '../lib/programs';
import { RANKING_ENTRIES, RANKING_INSTITUTIONS } from '../lib/rankings';
import enMessages from '../../messages/en.json';

/**
 * 小罗盘 (Little Compass) — desktop-pet AI assistant (Day 3).
 *
 * Floating compass mascot, bottom-end corner of every page; click opens a
 * chat panel. At most 3 opening questions, each with one-tap quick replies
 * (degree -> country -> budget); after the third answer the pet gives a
 * short route suggestion (max 3 lines, conclusion first, ONE evidence
 * link) and stops asking. Free text is answered by the real model.
 *
 * Model wiring (round 6, Job A): free-text questions AND the guided
 * suggestion both go to POST /api/v1/assistant/chat (with the
 * conversation history for free text, and one constructed message for
 * the suggestion — see lib/chat.ts suggestMessage). A reply counts as
 * an AI answer ONLY when ai_status is "available". Anything else is
 * the template fallback: for free-text questions the template's own
 * verified lines ARE shown, led by the offline line (round 10 —
 * discarding them left the user with no answer at all while the
 * backend had already named the schools); the guided suggestion
 * still uses the labelled offline catalogue (cheapest verified
 * programme + fee), which carries more than the generic template
 * lines. When the backend is entirely unreachable the free-text
 * turn falls back to the built-in directory for the asked country
 * (top ranked institutions), never a bare offline line.
 *
 * Cold-start resilience (round 7, Fix A; round 8): the backend sleeps
 * after 15 min idle and takes ~50s+ to wake; a first call made while
 * it wakes used to fail fast and strand the pet offline for the
 * session. The status check still goes through fetchJsonPatient
 * (lib/api.ts) with up to ~90s of retries before offline is
 * declared, a "waking the backend" line with the elapsed seconds
 * while a retry is in flight, and an explicit retry action in the
 * footer that stays available (disabled only while a check is
 * running) so the user can re-check after waking instead of being
 * stuck offline. Model calls (round 15, F2) go through
 * fetchJsonChat instead: one turn is answered or honestly falls
 * back within ~20 s, so a hanging gateway can no longer stack a
 * 40 s abort + a second 40 s attempt into ~90 s of silence. A call
 * that fails after retries — or on a slow abort — says it timed out
 * (pet.offlineTimeout), not a bare "offline"; a restart clears any
 * stuck busy state so the quick replies come back.
 *
 * Saved profile (round 7, Fix B): the pet reads the wizard profile
 * (useApp profile, persisted as pp-profile). When preferences already
 * exist, the opening turn acknowledges them (pet.greetingKnown) and
 * the guided flow skips what is already known — degree from
 * profile.track, a single saved country, and a GB/SG budget band
 * derived from a saved budget — and goes straight to the suggestion
 * when all three are known. It never claims "no preferences" while
 * the header strip shows saved ones. A greeting like "你好" goes to
 * the model with the saved preferences as context (first free-text
 * turn only; the displayed message stays verbatim), never a canned
 * intro that contradicts the saved state.
 *
 * Locale safety (fix 2026-11-25): message state stores ONLY structured
 * data — prompt keys, chosen values, the user's own verbatim text, and
 * whole backend answer payloads plus the locale they were answered in
 * (replyLocale). No rendered string (no t()/tf() result, no backend
 * line) is ever stored as a bubble. Every visible string is produced
 * at render time from the current locale: prompts/choices through t(),
 * offline suggestions through t()/tf() + displayProgramTitle(), and
 * live backend turns only when replyLocale === locale — otherwise the
 * turn shows the thinking line and is re-fetched in the new locale
 * (see the [locale, messages] effect below), so switching locale
 * mid-conversation leaves no stale-language text anywhere in the panel.
 *
 * Global scope (2026-11-25): the product covers universities worldwide,
 * not just the UK and Singapore. The country question (Q2) is therefore
 * data-driven, not hardcoded: its options are the countries present in
 * the verified data the frontend already ships (programmes' countries
 * first, then the rankings institutions' countries), rendered with the
 * existing `country.*` locale keys — the list follows automatically as
 * new countries are added. Only GB/SG have verified programmes so far;
 * picking any other country answers honestly after Q2 (no verified
 * programme in that track yet, plus what the pet CAN do there: a rank
 * lookup or the eligibility check) and never asks a budget question
 * whose answer would be discarded, never invents a programme or route.
 */

type Degree = 'undergraduate' | 'taught_masters';
/** Any country code from the verified data; only GB/SG have verified
 * programmes (and budget bands) so far. */
type Country = string;
type Band = 'low' | 'mid' | 'high';

/** Countries the pet can ask about, derived from the verified data the
 * frontend already ships — no country is hardcoded here and no new
 * country or programme data is added. Programme countries first (they
 * have verified routes), then every other country in the verified
 * rankings data, sorted by English name. Codes without a `country.*`
 * locale key are left out so a chip never renders a raw key. */
const PET_COUNTRY_CODES: string[] = (() => {
  const programmeCountries = [...new Set(PROGRAMS.map((p) => p.country))];
  const rankingCountries = [...new Set(RANKING_INSTITUTIONS.map((i) => i.country))];
  const withKey = [...new Set([...programmeCountries, ...rankingCountries])]
    .filter((code) => `country.${code}` in enMessages);
  const rest = withKey.filter((code) => !programmeCountries.includes(code));
  rest.sort((a, b) => {
    const nameA = (enMessages as Record<string, string>)[`country.${a}`] ?? a;
    const nameB = (enMessages as Record<string, string>)[`country.${b}`] ?? b;
    return nameA.localeCompare(nameB);
  });
  return [...programmeCountries.filter((code) => withKey.includes(code)), ...rest];
})();

/** True when the verified catalogue holds a matchable programme in
 * this country (v2 + the promoted expansion programmes; display-only
 * programmes do not count — the pet cannot suggest from them). */
function hasVerifiedProgrammes(country: string): boolean {
  return allPrograms().some((p) => p.country === country && p.matchable !== false);
}

/** One conversation turn, stored as structured data only. */
type ChatTurn =
  | { kind: 'prompt'; key: 'pet.greeting' | 'pet.q1' | 'pet.q2' | 'pet.q3' }
  | { kind: 'prefNote' }
  | { kind: 'choice'; step: 0 | 1 | 2; value: string; degree?: Degree; country?: Country }
  | { kind: 'freeText'; text: string }
  | {
      kind: 'suggest';
      degree: Degree; country: Country; band: Band;
      /** Live backend payload + the locale it was answered in. */
      reply: ChatReply | null;
      replyLocale: Locale | null;
      /** True when the live call failed and the offline catalogue is used. */
      offline: boolean;
      offlineProgramId: string | null;
      offlineEvidenceUrl: string | null;
      offlineFee: { currency: string; amount: number; period: string } | null;
      offlineFit: 'within' | 'above' | null;
    }
  | {
      kind: 'ask';
      message: string;
      /** Devil's-advocate turn (round 11): sent with mode=devil, so
          the reply challenges the saved preferences with verified
          facts instead of answering straight. Rendered with the
          devil boundary line + distinct style, never as a verdict. */
      devil: boolean;
      /** Live backend payload + the locale it was answered in.
          Round 10: a template reply (ai_status "unavailable") is
          stored here too, with offline=true — the verified template
          lines ARE the answer when the model is down, and discarding
          them used to leave the user with nothing at all. */
      reply: ChatReply | null;
      replyLocale: Locale | null;
      /** True when the live call failed and the offline catalogue is used. */
      offline: boolean;
      /** Offline rank lookup hit (locale-independent lines). */
      offlineRankId: string | null;
      /** Country the question asked about (ISO code), for the
          built-in directory fallback when the backend is entirely
          unreachable and there is no template reply at all. */
      offlineCountry: string | null;
    }
  | {
      kind: 'noProgrammes';
      degree: Degree; country: string;
    };

/** Budget-band ceilings, mirrored from backend/ai/assistant.py _BANDS.
 * GB bands are per-year GBP; SG UG bands are per-year SGD; SG TM bands
 * are total SGD (masters fees are programme totals). */
const BAND_CEILING: Record<string, Record<Band, number | null>> = {
  'undergraduate-GB': { low: 30000, mid: 50000, high: null },
  'taught_masters-GB': { low: 30000, mid: 50000, high: null },
  'undergraduate-SG': { low: 25000, mid: 45000, high: null },
  'taught_masters-SG': { low: 50000, mid: 80000, high: null },
};

function money(n: number): string {
  return n === Math.floor(n) ? n.toLocaleString('en-US') : n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Offline suggestion from the built-in catalogue (same bands as the
 * backend). Only GB (overseas fee item) and SG taught masters (total
 * fee item) carry a usable offline fee in the v2 list; SG
 * undergraduate has no without-grant fee in the offline list, so it
 * honestly returns null. Other countries (round 6, Job A): the
 * cheapest verified programme in the track/country from the merged
 * catalogue (v2 + promoted expansion programmes) — no band ceiling
 * exists there, so fit is null and no fee-vs-band line is rendered.
 * Returns structured data only — the programme name is rendered at
 * render time via displayProgramTitle(), never stored as a string. */
interface OfflineSuggestion {
  programId: string;
  evidenceUrl: string | null;
  fee: { currency: string; amount: number; period: string } | null;
  fit: 'within' | 'above' | null;
}

function suggestOffline(degree: Degree, country: Country, band: Band): OfflineSuggestion | null {
  if (country === 'GB' || country === 'SG') {
    const candidates = PROGRAMS.filter((p) => p.degreeLevel === degree && p.country === country);
    if (!candidates.length) return null;
    const withFee = candidates.map((p) => {
      const overseas = p.feeItems.find((f) => /overseas/i.test(f.label) && f.period === 'per year');
      const total = p.feeItems.find((f) => f.period === 'total');
      const item = country === 'GB' ? overseas : degree === 'taught_masters' ? total : undefined;
      return { p, item: item ?? null };
    }).filter((x) => x.item !== null);
    if (!withFee.length) return null;
    withFee.sort((a, b) => (a.item as { amount: number }).amount - (b.item as { amount: number }).amount);
    const ceiling = BAND_CEILING[`${degree}-${country}`][band];
    const within = withFee.filter((x) => ceiling === null || (x.item as { amount: number }).amount <= ceiling);
    const picked = within[0] ?? withFee[0];
    const item = picked.item as { amount: number; currency: string; period: string };
    const fit = ceiling === null || item.amount <= ceiling ? 'within' : 'above';
    return {
      programId: picked.p.id,
      evidenceUrl: picked.p.sources[0]?.url ?? null,
      fee: { currency: item.currency, amount: item.amount, period: item.period },
      fit,
    };
  }
  const candidates = allPrograms().filter(
    (p) => p.degreeLevel === degree && p.country === country && p.feeItems.length > 0);
  if (!candidates.length) return null;
  let best: { p: (typeof candidates)[number]; item: (typeof candidates)[number]['feeItems'][number] } | null = null;
  for (const p of candidates) {
    for (const item of p.feeItems) {
      if (!best || item.amount < best.item.amount) best = { p, item };
    }
  }
  if (!best) return null;
  return {
    programId: best.p.id,
    evidenceUrl: best.p.sources[0]?.url ?? null,
    fee: { currency: best.item.currency, amount: best.item.amount, period: best.item.period },
    fit: null,
  };
}

/** Offline rank lookup, rendered only as labelled offline content
 * (the caller leads with pet.offline). Matches the same short aliases
 * the backend knows; anything else stays unknown. The lines it builds
 * are locale-independent (official names, provider codes and rank
 * numbers only), so they are safe to render as-is. */
const OFFLINE_RANK_ALIASES: Record<string, string> = {
  ucl: 'ucl', '伦敦大学学院': 'ucl', imperial: 'imperial', '帝国理工': 'imperial',
  nus: 'nus', '新加坡国立': 'nus', ntu: 'ntu', '南洋理工': 'ntu',
  oxford: 'university-of-oxford', '牛津': 'university-of-oxford',
  cambridge: 'university-of-cambridge', '剑桥': 'university-of-cambridge',
  mit: 'massachusetts-institute-of-technology', '麻省理工': 'massachusetts-institute-of-technology',
  harvard: 'harvard-university', '哈佛': 'harvard-university',
  stanford: 'stanford-university', '斯坦福': 'stanford-university',
  tsinghua: 'tsinghua-university', '清华': 'tsinghua-university',
  peking: 'peking-university', '北大': 'peking-university',
  eth: 'eth-zurich',
};

/** One institution's rank line, locale-independent (official name,
 * provider codes and rank numbers only), so it is safe to render
 * as-is. Shared by the single-institution rank lookup and the
 * country directory below. */
function institutionRankLine(instId: string): { lines: string[]; evidenceUrl: string | null } | null {
  const inst = RANKING_INSTITUTIONS.find((i) => i.id === instId);
  if (!inst) return null;
  const parts = (['qs', 'the', 'arwu'] as const).map((provider) => {
    const e = RANKING_ENTRIES.find((x) => x.institution_id === instId && x.provider === provider);
    return e && e.rank_display ? `${provider.toUpperCase()} ${e.edition_label} #${e.rank_display}` : `${provider.toUpperCase()} —`;
  });
  const profiles = inst.provider_profiles ?? {};
  return {
    lines: [`${inst.official_name}: ${parts.join(' · ')}.`],
    evidenceUrl: profiles.qs ?? profiles.the ?? profiles.arwu ?? null,
  };
}

interface OfflineRank {
  lines: string[];
  evidenceUrl: string | null;
  institutionId: string;
}

function rankOffline(message: string): OfflineRank | null {
  const msg = message.toLowerCase();
  let instId: string | undefined;
  for (const [alias, id] of Object.entries(OFFLINE_RANK_ALIASES)) {
    if (msg.includes(alias)) { instId = id; break; }
  }
  if (!instId) return null;
  const hit = institutionRankLine(instId);
  if (!hit) return null;
  return { lines: hit.lines, evidenceUrl: hit.evidenceUrl, institutionId: instId };
}

/** Built-in directory for a country (round 10): the top 3 ranked
 * institutions in that country from the shipped catalogue, best QS
 * rank first, each with its rank line. Used when the backend is
 * entirely unreachable — no template reply at all — so a question
 * like "瑞士有哪些好学校？" still names real schools instead of
 * answering with a bare offline line. */
function directoryOffline(country: string): { lines: string[]; firstId: string } | null {
  const inCountry = RANKING_INSTITUTIONS.filter((i) => i.country === country);
  if (!inCountry.length) return null;
  const bestQs = (id: string): number => {
    const e = RANKING_ENTRIES.find((x) => x.institution_id === id && x.provider === 'qs');
    const n = e?.rank_display ? parseInt(e.rank_display.replace(/[^0-9]/g, ''), 10) : NaN;
    return Number.isNaN(n) ? 10 ** 9 : n;
  };
  const top = [...inCountry].sort((a, b) => bestQs(a.id) - bestQs(b.id) || a.official_name.localeCompare(b.official_name)).slice(0, 3);
  const lines: string[] = [];
  for (const inst of top) {
    const hit = institutionRankLine(inst.id);
    if (hit) lines.push(...hit.lines);
  }
  if (!lines.length) return null;
  return { lines, firstId: top[0].id };
}

export type PetMood = 'idle' | 'think' | 'celebrate' | 'empathise' | 'bored';

/** Mouth per mood — the face is the state machine's display. */
const MOUTH: Record<PetMood, string> = {
  idle: 'M30 50 Q36 55 42 50',
  think: 'M31 51 L41 51',
  celebrate: 'M29 49 Q36 58 43 49',
  empathise: 'M30 53 Q36 48 42 53',
  bored: 'M31 51 L41 51',
};

/** The pet face, shared with the wizard's chat steps (PrefChat / RecChat)
 * so the same state machine (idle / blink / think / celebrate /
 * empathise / bored) shows there too — the face moves with the chat. */
export function CompassFace({
  size = 56,
  mood = 'idle',
  eyesRef,
  needleRef,
}: {
  size?: number;
  mood?: PetMood;
  /** Pointer-follow targets (button face only): the eyes group is
      translated by JS and the outer needle group is rotated by JS.
      They compose with the inner CSS sway / blink because each lives
      on its own nested group — never two transforms on one element.
      Callback refs (not RefObject) so the types hold on both React 18
      and React 19 ref definitions. */
  eyesRef?: (el: SVGGElement | null) => void;
  needleRef?: (el: SVGGElement | null) => void;
}) {
  return (
    <svg width={size} height={size} viewBox="0 0 72 72" aria-hidden="true" className={mood === 'bored' ? 'pet-bored' : undefined}>
      <circle cx="36" cy="36" r="34" fill="#0E7C7B" />
      <circle cx="36" cy="36" r="27" fill="#F7F5F0" />
      <g stroke="#0B1F3A" strokeWidth="2" strokeLinecap="round">
        <line x1="36" y1="12" x2="36" y2="17" />
        <line x1="36" y1="55" x2="36" y2="60" />
        <line x1="12" y1="36" x2="17" y2="36" />
        <line x1="55" y1="36" x2="60" y2="36" />
      </g>
      <g ref={needleRef} style={{ transformOrigin: '36px 36px' }}>
        <g className="pet-needle-look" style={{ transformOrigin: '36px 36px' }}>
          <g className="anim-needle" style={{ transformOrigin: '36px 36px' }}>
            <polygon points="36,18 41,36 36,34 31,36" fill="#F2A541" />
            <polygon points="36,54 41,36 36,38 31,36" fill="#0B1F3A" />
          </g>
        </g>
      </g>
      <circle cx="36" cy="36" r="3.5" fill="#0B1F3A" />
      <g ref={eyesRef}>
        <circle className="pet-blink" cx="28" cy="45" r="2.2" fill="#0B1F3A" />
        <circle className="pet-blink" cx="44" cy="45" r="2.2" fill="#0B1F3A" />
      </g>
      <path d={MOUTH[mood]} fill="none" stroke="#0B1F3A" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

/** Devil's-advocate profile for /assistant/chat mode=devil (round
 * 11): the saved wizard preferences the backend challenges with
 * verified facts — countries, climate, level, budget, city. The
 * budget period mirrors the pet's own band table (BAND_CEILING):
 * per-year, except taught masters in SG, whose verified fees are
 * programme totals. Null when nothing is known (the backend then
 * derives what it can from the message itself). */
function devilProfileFor(p: Profile): Record<string, unknown> | null {
  const body: Record<string, unknown> = {};
  const countries = [...(p.prefCountries ?? [])];
  if (countries.length) body.countries = countries;
  if (['warm', 'cool', 'four_seasons', 'mild'].includes(p.prefClimate ?? '')) {
    body.climate = p.prefClimate;
  }
  const level = p.track === 'undergraduate' || p.track === 'taught_masters' ? p.track : undefined;
  if (level) body.level = level;
  if (typeof p.budget === 'number') {
    body.budget_amount = p.budget;
    body.budget_currency = p.budgetCurrency || 'GBP';
    body.budget_period = level === 'taught_masters' && countries.length === 1 && countries[0] === 'SG' ? 'total' : 'per_year';
  }
  if ((p.prefCity ?? '').trim()) body.city = p.prefCity!.trim();
  return Object.keys(body).length ? body : null;
}

export function CompassPet() {
  const { t, tf, locale, profile } = useApp();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  /** Devil's advocate (round 11): when on, free-text turns are sent
   * with mode=devil + the saved preferences, and the reply renders
   * with the devil boundary line + distinct style. */
  const [devilMode, setDevilMode] = useState(false);
  /** Round 14: whether there is anything to challenge — the toggle
   * renders exactly when devilProfileFor(profile) is non-null, i.e.
   * saved preferences exist (countries, climate, level, budget or
   * city). It is a pure function of the durable profile (hydrated
   * from pp-profile on every load), never of session flags — see the
   * toggle comment and the /results restore effect below. */
  const canDevil = devilProfileFor(profile) !== null;
  const [answers, setAnswers] = useState<{ degree?: Degree; country?: Country; budget?: Band }>({});
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(false);
  /** The backend is being woken (a retry is in flight after the first
   * attempt failed): show the waking line, not the offline line. */
  const [waking, setWaking] = useState(false);
  /** Seconds spent waking, for the visible progress line. */
  const wakingElapsed = useElapsed(waking);
  /** Round 9, R6: seconds spent waiting on the model, for the visible
   * progress line — a bare "想想……" with no progress is what the
   * re-test flagged. */
  const busyElapsed = useElapsed(busy);
  /** The last offline verdict came after the patient budget was spent
   * (a retry fired) or a chat turn was cut by its own ~18 s timer
   * (an AbortError from fetchJsonChat): the footer and the offline
   * turns say "timed out", not a bare "offline". */
  const [timedOut, setTimedOut] = useState(false);
  /** Whether any retry fired during the current patient call — set by
   * patientOnRetry, read when the call fails. */
  const retryFiredRef = useRef(false);
  const patientOnRetry = () => { retryFiredRef.current = true; setWaking(true); };
  const beginPatientCall = () => { retryFiredRef.current = false; };
  /** Round 15, F2: a failed chat turn timed out when a retry fired
   * OR the error is the per-attempt timer's abort — fetchJsonChat
   * does not retry a slow abort, so no retry fires for it, but the
   * turn still waited out its whole ~18 s budget. */
  const callTimedOut = (err: unknown) =>
    retryFiredRef.current || (err as { name?: string } | null)?.name === 'AbortError';
  /** Chat-turn fetch options (round 15, F2): one turn is bounded
   * to ~20 s by fetchJsonChat (lib/api.ts) — the backend caps a
   * turn at ~15 s (one model call, then the template), so a turn
   * that has not answered in 18 s is not saved by re-issuing it;
   * the old round-10 shape (40 s attempt / 90 s budget, and a
   * 15 s / 12 s short probe when known-offline) stacked a 40 s
   * abort + a second 40 s attempt into ~90 s of silence before
   * offline was declared. A fast failure (backend waking) still
   * retries inside the 20 s budget; a slow abort falls back at
   * once. The /ai/status probe on panel open below still uses
   * the 90 s patient budget — it watches the backend wake, it is
   * not a turn. */
  const chatOpts = { onRetry: patientOnRetry };
  /** Whether the live model answered recently: true after a model
   * reply (ai_status "available"), false after a failure or a
   * template-only reply, null before the first check. The footer
   * reports this honestly — it never claims AI answers it has not
   * seen. */
  const [aiLive, setAiLive] = useState<boolean | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  /** Bumped on every restart so late re-fetch responses are ignored. */
  const convRef = useRef(0);
  /** Indices of backend turns currently being re-fetched for a locale. */
  const inFlightRef = useRef<Set<number>>(new Set());

  /** Pet state machine (research move 3): idle / blink (CSS) / think /
      celebrate / empathise / bored — driven by real app events, never
      random wiggling. The policy, questions and answers are unchanged. */
  const buttonRef = useRef<HTMLButtonElement>(null);
  /** Pointer-follow targets. A plain object inside one ref: the
      installed React types make RefObject.current read-only, so the
      elements live as mutable properties (never reassigning current). */
  const faceElsRef = useRef<{ eyes: SVGGElement | null; needle: SVGGElement | null }>({ eyes: null, needle: null });
  const [celebrate, setCelebrate] = useState(false);
  const [bored, setBored] = useState(false);
  const [inputFocused, setInputFocused] = useState(false);
  const celebrateTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastActiveRef = useRef(Date.now());
  const openRef = useRef(open);
  useEffect(() => { openRef.current = open; }, [open]);

  const doCelebrate = () => {
    setCelebrate(true);
    if (celebrateTimerRef.current) clearTimeout(celebrateTimerRef.current);
    celebrateTimerRef.current = setTimeout(() => setCelebrate(false), 1200);
  };

  /** Eyes + needle follow the pointer (button face only). rAF-throttled
      and applied straight to the DOM — no React re-render per move.
      Skipped entirely under prefers-reduced-motion; beyond 400px the
      face returns to centre. */
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    let raf = 0;
    const onMove = (e: PointerEvent) => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const btn = buttonRef.current;
        if (!btn) return;
        const rect = btn.getBoundingClientRect();
        const dx = e.clientX - (rect.left + rect.width / 2);
        const dy = e.clientY - (rect.top + rect.height / 2);
        const dist = Math.hypot(dx, dy);
        const ex = dist > 400 ? 0 : Math.max(-2.5, Math.min(2.5, dx * 0.008));
        const ey = dist > 400 ? 0 : Math.max(-2, Math.min(2, dy * 0.008));
        const rot = dist > 400 ? 0 : Math.max(-18, Math.min(18, dx * 0.03));
        if (faceElsRef.current.eyes) faceElsRef.current.eyes.style.transform = `translate(${ex}px, ${ey}px)`;
        if (faceElsRef.current.needle) faceElsRef.current.needle.style.transform = `rotate(${rot}deg)`;
      });
    };
    window.addEventListener('pointermove', onMove);
    return () => {
      window.removeEventListener('pointermove', onMove);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  /** Boredom: 60s with no pointer/keyboard activity and the panel
      closed → the pet looks around and half-closes its eyes. Any
      interaction wakes it. */
  useEffect(() => {
    const wake = () => {
      lastActiveRef.current = Date.now();
      setBored(false);
    };
    window.addEventListener('pointerdown', wake);
    window.addEventListener('keydown', wake);
    const timer = setInterval(() => {
      if (!openRef.current && Date.now() - lastActiveRef.current > 60000) setBored(true);
    }, 10000);
    return () => {
      window.removeEventListener('pointerdown', wake);
      window.removeEventListener('keydown', wake);
      clearInterval(timer);
      if (celebrateTimerRef.current) clearTimeout(celebrateTimerRef.current);
    };
  }, []);

  /** Mood precedence: thinking beats everything; a found suggestion
      celebrates; a failed (offline) call gets sympathy; boredom is
      last. `offline` is reset on the next live success so empathise
      never sticks after the backend is reachable again. */
  const mood: PetMood = busy ? 'think' : celebrate ? 'celebrate' : offline ? 'empathise' : bored ? 'bored' : 'idle';
  const typing = inputFocused && input.length > 0;

  const greet = () => {
    convRef.current += 1;
    inFlightRef.current.clear();
    // Round 8: a restart clears any stuck busy/waking state — a
    // restart while a call was in flight used to leave the quick
    // replies hidden (chips render only when !busy) with no way back.
    // The offline flag itself stays: it describes the backend, not
    // this conversation, and the footer retry still re-checks it.
    setBusy(false);
    setWaking(false);
    setTimedOut(false);
    // Round 7, Fix B: the guided flow skips what the wizard already
    // learned, and the opening turn acknowledges the saved preferences
    // instead of claiming there are none. Degree comes from
    // profile.track, the country when exactly one is saved, and the
    // budget band from a saved budget (GB/SG ceilings only). Known
    // answers are shown as choice turns so the transcript shows what
    // was skipped; when all three are known the suggestion starts at
    // once. With no saved preferences this is exactly the old
    // greeting + Q1.
    const knownSteps = petKnownSteps(profile, BAND_CEILING);
    const msgs: ChatTurn[] = [];
    if (hasPreferences(profile)) msgs.push({ kind: 'prefNote' });
    else msgs.push({ kind: 'prompt', key: 'pet.greeting' });
    const answersNext: { degree?: Degree; country?: Country; budget?: Band } = {};
    let stepNext = 0;
    if (knownSteps.degree) {
      answersNext.degree = knownSteps.degree;
      msgs.push({ kind: 'choice', step: 0, value: knownSteps.degree });
      if (knownSteps.country) {
        answersNext.country = knownSteps.country;
        msgs.push({ kind: 'choice', step: 1, value: knownSteps.country });
        if (knownSteps.band) {
          answersNext.budget = knownSteps.band;
          msgs.push({ kind: 'choice', step: 2, value: knownSteps.band, degree: knownSteps.degree, country: knownSteps.country });
          stepNext = 3;
        } else {
          msgs.push({ kind: 'prompt', key: 'pet.q3' });
          stepNext = 2;
        }
      } else {
        msgs.push({ kind: 'prompt', key: 'pet.q2' });
        stepNext = 1;
      }
    } else {
      msgs.push({ kind: 'prompt', key: 'pet.q1' });
    }
    setMessages(msgs);
    setStep(stepNext);
    setAnswers(answersNext);
    if (stepNext === 3 && knownSteps.degree && knownSteps.country && knownSteps.band) {
      void askSuggest(knownSteps.degree, knownSteps.country, knownSteps.band);
    }
  };

  useEffect(() => {
    try {
      if (sessionStorage.getItem('pp-pet-open') === '1') setOpen(true);
    } catch { /* ignore */ }
  }, []);

  /** Round 14 — the toggle vanish (re-test task 8, 2026-11-27): the
   * toggle appeared exactly once, on the first results-page load
   * from a stale `pp-pet-open` session flag, and never came back
   * after a pref-chat reset + two full wizard runs with the identical
   * 8/8 preference summary. Root cause, in code: the toggle JSX had
   * NO profile gate — it rendered whenever the panel was open — and
   * the panel opens on load ONLY from that session flag. Every close
   * path (×, Escape, floating-button toggle, and every pet next-step
   * Link calling toggle(false)) removed the flag, PrefChat restart
   * never touches the pet or the flag, and the wizard finishes with
   * router.push('/results') — a client-side navigation, so the
   * layout (and CompassPet) never remounts and the mount restore
   * never re-runs. Once closed anywhere in the flow, the panel (and
   * the toggle inside it) stayed closed for the rest of the session,
   * however complete the saved preferences were.
   *
   * Fix: the panel re-opens on arrival at /results whenever there
   * are saved preferences to challenge (canDevil), unless the user
   * explicitly dismissed it this session ('pp-pet-dismissed', set
   * only by the explicit close paths in toggle(false) — never by a
   * navigation link, which uses closeForNavigation and keeps the
   * open memory). It calls setOpen directly, never toggle(true), so
   * it never steals input focus on a page load. The toggle itself
   * is gated on canDevil below, so the two agree: the panel opens
   * exactly when the toggle will be in it. */
  useEffect(() => {
    if (pathname !== '/results' || open || !canDevil) return;
    try {
      if (sessionStorage.getItem('pp-pet-dismissed') === '1') return;
    } catch { /* ignore */ }
    setOpen(true);
    try { sessionStorage.setItem('pp-pet-open', '1'); } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, canDevil, open]);

  useEffect(() => {
    if (open && messages.length === 0) greet();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  /** One cheap status read when the panel opens, so the footer states
   * the truth about the model before any chat is claimed as AI. The
   * patient fetch retries while the backend wakes (round 7, Fix A):
   * offline is declared only after the ~90s budget is spent, and the
   * waking line shows while a retry is in flight. */
  useEffect(() => {
    if (!open || aiLive !== null) return;
    setWaking(false);
    beginPatientCall();
    fetchJsonPatient<{ ai_status?: string }>('/api/ai/status', {}, { onRetry: patientOnRetry })
      .then((s) => { setWaking(false); setTimedOut(false); setAiLive(s.ai_status === 'available'); if (s.ai_status !== 'available') setOffline(true); })
      .catch(() => { setWaking(false); setTimedOut(retryFiredRef.current); setAiLive(false); setOffline(true); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  /** Re-check the backend after an offline verdict (footer retry):
   * the instance may have woken since the last check. A live status
   * clears the offline flag so the next message tries the model
   * again; a failed check keeps it offline. */
  const retryStatus = () => {
    setWaking(true);
    beginPatientCall();
    fetchJsonPatient<{ ai_status?: string }>('/api/ai/status', {}, { onRetry: patientOnRetry })
      .then((s) => {
        setWaking(false);
        setTimedOut(false);
        const live = s.ai_status === 'available';
        setAiLive(live);
        setOffline(!live);
      })
      .catch(() => { setWaking(false); setTimedOut(retryFiredRef.current); setAiLive(false); setOffline(true); });
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [messages, busy]);

  /** The constructed suggestion message for one guided answer (see
   * lib/chat.ts suggestMessage). The message itself is always English;
   * the backend answers in the requested locale. GB/SG bands carry
   * their ceiling (per year, except SG taught masters which is a
   * total); other countries have no band table, so no ceiling is
   * stated and the backend picks the cheapest verified programme. */
  const suggestMessageFor = (degree: Degree, country: Country, band: Band): string => {
    const ceilingEntry = BAND_CEILING[`${degree}-${country}`]?.[band];
    const currency = country === 'GB' ? 'GBP' : country === 'SG' ? 'SGD' : null;
    const ceiling = ceilingEntry != null && currency
      ? {
          currency,
          amount: ceilingEntry,
          period: (country === 'SG' && degree === 'taught_masters' ? 'total' : 'per year') as 'per year' | 'total',
        }
      : null;
    const countryNameEn = (enMessages as Record<string, string>)[`country.${country}`] ?? country;
    return suggestMessage(degree, country, countryNameEn, band, ceiling);
  };

  /** Country code a free-text question asks about, from the country
   * names in the current locale plus the English names (round 10:
   * the offline directory needs it when the backend is entirely
   * unreachable). Short names match on word boundaries only, so
   * "uk" never fires inside another word. */
  const countryFromMessage = (text: string): string | null => {
    const lower = text.toLowerCase();
    for (const code of PET_COUNTRY_CODES) {
      const names = [
        t(`country.${code}`),
        (enMessages as Record<string, string>)[`country.${code}`] ?? '',
      ].map((n) => n.toLowerCase()).filter(Boolean);
      const hit = names.some((n) => {
        if (!n) return false;
        if (n.length <= 3) {
          const esc = n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
          return new RegExp(`(?<![a-z])${esc}(?![a-z])`).test(lower);
        }
        return lower.includes(n);
      });
      if (hit) return code;
    }
    return null;
  };

  /** Conversation history for /assistant/chat: the live model turns so
   * far (user question + the model's own lines), oldest first, last 6
   * entries. Offline turns are never included — their lines are not
   * model answers. `before` limits to turns before an index (used by
   * the locale re-fetch, so a turn never quotes itself). */
  const buildHistory = (turns: ChatTurn[], before?: number): ChatHistoryTurn[] => {
    const out: ChatHistoryTurn[] = [];
    turns.forEach((m, i) => {
      if (before !== undefined && i >= before) return;
      if (m.kind !== 'ask' || !m.reply || !isModelReply(m.reply)) return;
      out.push({ role: 'user', content: m.message });
      out.push({ role: 'assistant', content: m.reply.lines.join(' ') });
    });
    return out.slice(-6);
  };

  /**
   * Locale change: re-fetch every live backend-backed turn whose reply
   * was answered in the old locale, in the new locale. While a turn
   * awaits its fresh reply it renders the thinking line (see
   * renderTurn), never the old-locale lines. A failed re-fetch — or a
   * re-fetch that comes back template-only (ai_status not
   * "available") — falls back to the offline catalogue rendered in
   * the new locale. The in-flight set stops duplicate fetches;
   * replyLocale records the locale each reply was actually answered
   * in, so a reply that lands after a further switch is re-fetched
   * again instead of shown stale.
   */
  useEffect(() => {
    messages.forEach((m, i) => {
      if ((m.kind !== 'suggest' && m.kind !== 'ask') || !m.reply || m.replyLocale === locale) return;
      if (inFlightRef.current.has(i)) return;
      inFlightRef.current.add(i);
      const conv = convRef.current;
      // A devil's-advocate turn is re-fetched in devil mode too, with
      // the saved preferences — otherwise the fresh reply would be a
      // straight answer wearing the devil boundary.
      const devilProf = m.kind === 'ask' && m.devil ? devilProfileFor(profile) : null;
      const req = m.kind === 'suggest'
        ? fetchJson<ChatReply>('/api/assistant/chat', {
            method: 'POST',
            body: JSON.stringify({ message: suggestMessageFor(m.degree, m.country, m.band), locale }),
          })
        : fetchJson<ChatReply>('/api/assistant/chat', {
            method: 'POST',
            body: JSON.stringify({
              message: m.message, locale, history: buildHistory(messages, i),
              ...(devilProf ? { mode: 'devil', profile: devilProf } : {}),
            }),
          });
      const toOffline = () => {
        if (convRef.current !== conv) return;
        setOffline(true);
        setAiLive(false);
        setMessages((prev) => prev.map((x, j) => {
          if (j !== i) return x;
          if (x.kind === 'suggest') {
            const off = suggestOffline(x.degree, x.country, x.band);
            return {
              ...x, reply: null, replyLocale: null, offline: true,
              offlineProgramId: off?.programId ?? null,
              offlineEvidenceUrl: off?.evidenceUrl ?? null,
              offlineFee: off?.fee ?? null, offlineFit: off?.fit ?? null,
            };
          }
          if (x.kind === 'ask') {
            const rank = rankOffline(x.message);
            return { ...x, reply: null, replyLocale: null, offline: true, offlineRankId: rank?.institutionId ?? null, offlineCountry: countryFromMessage(x.message) };
          }
          return x;
        }));
      };
      req.then((fresh) => {
        if (convRef.current !== conv) return;
        if (!isModelReply(fresh)) {
          // Round 10: a template reply in the NEW locale is still a
          // verified answer — store it as an offline turn (led by
          // the offline line at render time) instead of dropping it
          // for a bare offline line. Only a reply with no lines at
          // all falls through to the catalogue.
          if (m.kind === 'ask' && fresh.lines?.length) {
            setOffline(true);
            setAiLive(false);
            setMessages((prev) => prev.map((x, j) => (j === i && x.kind === 'ask' ? { ...x, reply: fresh, replyLocale: locale, offline: true } : x)));
            return;
          }
          toOffline(); return;
        }
        setOffline(false);
        setAiLive(true);
        setMessages((prev) => prev.map((x, j) => {
          if (j !== i || (x.kind !== 'suggest' && x.kind !== 'ask')) return x;
          return { ...x, reply: fresh, replyLocale: locale };
        }));
      }).catch(toOffline)
        .finally(() => { inFlightRef.current.delete(i); });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale, messages]);

  const toggle = (next: boolean) => {
    setOpen(next);
    try {
      if (next) {
        // Opening clears an explicit dismiss from earlier in the
        // session, so the /results restore above can work again.
        sessionStorage.setItem('pp-pet-open', '1');
        sessionStorage.removeItem('pp-pet-dismissed');
      } else {
        // Round 14: an EXPLICIT close (×, Escape, floating button)
        // records the dismiss, so the /results restore never fights
        // a close the user chose. Navigation-link closes use
        // closeForNavigation instead and never set this.
        sessionStorage.removeItem('pp-pet-open');
        sessionStorage.setItem('pp-pet-dismissed', '1');
      }
    } catch { /* ignore */ }
    if (next) setTimeout(() => inputRef.current?.focus(), 100);
  };

  /** Close the panel for a navigation the pet itself started (a
   * next-step Link or the "edit preferences" link): the panel gets
   * out of the way, but the open memory (pp-pet-open) is kept and no
   * dismiss is recorded — returning to /results restores the panel
   * (see the effect above) instead of losing the toggle for the
   * rest of the session, which is what the old toggle(false) here
   * did. */
  const closeForNavigation = () => {
    setOpen(false);
  };

  const push = (msg: ChatTurn) => setMessages((prev) => [...prev, msg]);

  /** Label for a stored quick-reply choice, localised at render time. */
  const choiceLabel = (turn: Extract<ChatTurn, { kind: 'choice' }>): string => {
    if (turn.step === 0) return t(turn.value === 'undergraduate' ? 'pet.q1ug' : 'pet.q1tm');
    if (turn.step === 1) return t(`country.${turn.value}`);
    if (turn.country === 'GB') {
      return t(turn.value === 'low' ? 'pet.q3gbLow' : turn.value === 'mid' ? 'pet.q3gbMid' : 'pet.q3gbHigh');
    }
    if (turn.country === 'SG') {
      if (turn.degree === 'undergraduate') {
        return t(turn.value === 'low' ? 'pet.q3sgUgLow' : turn.value === 'mid' ? 'pet.q3sgUgMid' : 'pet.q3sgUgHigh');
      }
      return t(turn.value === 'low' ? 'pet.q3sgTmLow' : turn.value === 'mid' ? 'pet.q3sgTmMid' : 'pet.q3sgTmHigh');
    }
    // Other countries have no currency band table — generic bands.
    return t(turn.value === 'low' ? 'pet.q3Low' : turn.value === 'mid' ? 'pet.q3Mid' : 'pet.q3High');
  };

  /**
   * Every visible string of one turn, produced at render time from the
   * current locale. Backend lines are shown only when they were
   * answered in the current locale; a stale reply renders the thinking
   * line until its re-fetch lands (see the [locale, messages] effect).
   */
  const renderTurn = (turn: ChatTurn): {
    lines: string[];
    evidenceUrl?: string | null;
    nextSteps?: { wizard?: string; program?: string | null; institution?: string | null };
    /** Devil's-advocate reply: rendered with the devil boundary line
        + distinct style, never as a verdict. Only set when a devil
        reply is actually shown in the current locale. */
    devil?: boolean;
    /** Round 18 (W3): the devil reply is an offline template answer
        (turn.offline) — the boundary must then be the offline one
        (devil.offlineBoundary), never the live "AI-generated" line,
        or the same bubble claims both AI generation and offline mode. */
    devilOffline?: boolean;
  } => {
    // Round 8: an offline turn whose call timed out after the patient
    // budget says so plainly, instead of a bare "offline".
    const offlineLine = timedOut ? t('pet.offlineTimeout') : t('pet.offline');
    switch (turn.kind) {
      case 'prompt':
        return { lines: [t(turn.key)] };
      case 'prefNote':
        // The saved wizard preferences, in the user's own words —
        // rendered at render time from the current profile, so a
        // locale switch never leaves a stale-language bubble.
        // Round 18 (W3): on /results the full summary is already
        // visible on the page itself, so the greeting acknowledges
        // the saved preferences without restating the whole list
        // (pet.greetingKnownShort has no {prefs}).
        return { lines: [pathname === '/results' ? t('pet.greetingKnownShort') : tf('pet.greetingKnown', { prefs: prefSummary(profile, t) })] };
      case 'choice':
        return { lines: [choiceLabel(turn)] };
      case 'freeText':
        // The user's own words, verbatim — not a localised string.
        return { lines: [turn.text] };
      case 'noProgrammes': {
        // Honest unknown, rendered at render time from the current
        // locale (needs pet.suggestNone / pet.noProgrammesRank /
        // pet.suggestUnknown2 — see the test file for the exact keys).
        // No programme is invented; the pet offers what it CAN do in
        // this country instead: a rank lookup, or the eligibility check.
        const level = t(turn.degree === 'undergraduate' ? 'pet.q1ug' : 'pet.q1tm');
        const countryName = t(`country.${turn.country}`);
        return {
          lines: [
            tf('pet.suggestNone', { level, country: countryName }),
            t('pet.noProgrammesRank'),
            t('pet.suggestUnknown2'),
          ],
          nextSteps: { wizard: '/wizard' },
        };
      }
      case 'suggest': {
        if (turn.reply && turn.replyLocale === locale) {
          // A live reply counts as an AI answer only when the backend
          // actually used a model (ai_status "available") — a
          // template-only reply is never stored as one (see
          // askSuggest), so reaching here means model lines. Links
          // come from the reply's source ids, never from model text.
          const links = deriveChatLinks(turn.reply.sources);
          return {
            lines: turn.reply.lines,
            evidenceUrl: turn.reply.evidence_url,
            nextSteps: { wizard: '/wizard', program: links.program, institution: links.institution },
          };
        }
        if (turn.reply) return { lines: [t('pet.thinking')] };
        if (turn.offline) {
          if (!turn.offlineProgramId) return { lines: [offlineLine] };
          const program = findProgram(turn.offlineProgramId);
          const lines = [
            offlineLine,
            program ? displayProgramTitle(program, locale) : turn.offlineProgramId,
          ];
          if (turn.offlineFee && (turn.offlineFee.period === 'per year' || turn.offlineFee.period === 'total')) {
            const fee = tf(turn.offlineFee.period === 'total' ? 'pet.feeTotal' : 'pet.feePerYear',
              { currency: turn.offlineFee.currency, amount: money(turn.offlineFee.amount) });
            if (turn.offlineFit) {
              lines.push(tf(turn.offlineFit === 'within' ? 'pet.feeWithin' : 'pet.feeAbove', { fee }));
            } else {
              lines.push(fee);
            }
          }
          return {
            lines,
            evidenceUrl: turn.offlineEvidenceUrl,
            nextSteps: { wizard: '/wizard', program: `/programs/${turn.offlineProgramId}` },
          };
        }
        return { lines: [t('pet.thinking')] };
      }
      case 'ask': {
        if (turn.reply && turn.replyLocale === locale) {
          const links = deriveChatLinks(turn.reply.sources);
          // Round 10: an offline turn whose reply is the verified
          // template answer leads with the offline line, then the
          // template's own lines — the school names the backend
          // retrieved — instead of hiding them and showing a bare
          // "offline" with nothing after it.
          // Round 19 (W1): a devil turn already discloses via the
          // boundary above (devil.offlineBoundary) — drop the body offline line.
          const lines = turn.offline && !turn.devil ? [offlineLine, ...turn.reply.lines] : turn.reply.lines;
          return {
            lines,
            evidenceUrl: turn.reply.evidence_url,
            nextSteps: { wizard: '/wizard', program: links.program, institution: links.institution },
            devil: turn.devil,
            // Round 18 (W3): an offline devil turn wears the offline
            // boundary, never the live "AI-generated" one.
            devilOffline: turn.devil && turn.offline,
          };
        }
        if (turn.reply) return { lines: [t('pet.thinking')] };
        if (turn.offline) {
          // Labelled offline content only: the rank lookup below is
          // from the built-in catalogue, never a model answer.
          const rank = rankOffline(turn.message);
          if (rank) {
            return {
              lines: [offlineLine, ...rank.lines],
              evidenceUrl: rank.evidenceUrl,
              nextSteps: { wizard: '/wizard', institution: `/institutions/${rank.institutionId}` },
            };
          }
          // Round 10: no rank alias matched, but the question asked
          // about a country — list that country's top schools from
          // the built-in directory instead of answering with nothing.
          const dir = turn.offlineCountry ? directoryOffline(turn.offlineCountry) : null;
          if (dir) {
            return {
              lines: [offlineLine, ...dir.lines],
              nextSteps: { wizard: '/wizard', institution: `/institutions/${dir.firstId}` },
            };
          }
          return { lines: [offlineLine] };
        }
        return { lines: [t('pet.thinking')] };
      }
    }
  };

  /** The guided suggestion, from the real model when it is reachable.
   * The three answers become one constructed message; the backend
   * retrieves the cheapest verified programme in that track/country
   * as the model's evidence. A template-only reply (ai_status not
   * "available") is NOT stored as an answer — the turn falls back to
   * the labelled offline catalogue instead. */
  const askSuggest = async (degree: Degree, country: Country, band: Band) => {
    if (!hasVerifiedProgrammes(country)) {
      // Defensive: the Q2 branch already answers this without calling
      // the backend, so this is unreachable in the normal flow.
      push({ kind: 'noProgrammes', degree, country });
      return;
    }
    setBusy(true);
    const requestLocale = locale;
    // Round 8: the conversation this call belongs to — a restart
    // (greet bumps convRef) while the call is in flight must not let
    // the late reply land in the new conversation.
    const conv = convRef.current;
    beginPatientCall();
    // Round 15, F2: one turn is bounded to ~20 s by fetchJsonChat
    // (lib/api.ts) — a slow abort falls back at once instead of
    // re-issuing the whole turn for another 40 s.
    const patientOpts = chatOpts;
    // NOTE: goOffline does not touch timedOut — the caller sets it:
    // a template reply is a fast answer (not a timeout), a thrown
    // call carries the retry verdict.
    const goOffline = () => {
      if (convRef.current !== conv) return;
      setOffline(true);
      setAiLive(false);
      const off = suggestOffline(degree, country, band);
      if (off) doCelebrate();
      push({
        kind: 'suggest', degree, country, band,
        reply: null, replyLocale: null, offline: true,
        offlineProgramId: off?.programId ?? null,
        offlineEvidenceUrl: off?.evidenceUrl ?? null,
        offlineFee: off?.fee ?? null, offlineFit: off?.fit ?? null,
      });
    };
    // Round 18 W2: when the model is KNOWN down, go offline at once
    // instead of burning the 15 s model budget: the offline catalogue
    // is exactly what a template reply produces here, and skipping
    // the call also unblocks the input ~15 s sooner. 'available' /
    // 'unknown' proceed as before. The verdict is usually cached
    // (SimulatePanel warms it every 45 s), so this is ~ms.
    if ((await modelAvailability()) === 'unavailable') {
      setTimedOut(false);
      goOffline();
      return;
    }
    try {
      const r = await fetchJsonChat<ChatReply>('/api/assistant/chat', {
        method: 'POST',
        body: JSON.stringify({ message: suggestMessageFor(degree, country, band), locale: requestLocale }),
      }, patientOpts);
      setWaking(false);
      if (!isModelReply(r)) { setTimedOut(false); goOffline(); return; }
      if (convRef.current !== conv) return;
      setOffline(false);
      setTimedOut(false);
      setAiLive(true);
      if (deriveChatLinks(r.sources).program) doCelebrate();
      push({
        kind: 'suggest', degree, country, band,
        reply: r, replyLocale: requestLocale, offline: false,
        offlineProgramId: null, offlineEvidenceUrl: null, offlineFee: null, offlineFit: null,
      });
    } catch (err) {
      setWaking(false);
      if (convRef.current === conv) {
        setTimedOut(callTimedOut(err));
        goOffline();
      }
    } finally {
      if (convRef.current === conv) {
        setWaking(false);
        setBusy(false);
      }
    }
  };

  const onChip = (value: string) => {
    if (busy) return;
    if (step === 0) {
      const degree = value as Degree;
      setAnswers((a) => ({ ...a, degree }));
      push({ kind: 'choice', step: 0, value });
      push({ kind: 'prompt', key: 'pet.q2' });
      setStep(1);
    } else if (step === 1) {
      const country = value;
      setAnswers((a) => ({ ...a, country }));
      push({ kind: 'choice', step: 1, value });
      if (hasVerifiedProgrammes(country)) {
        push({ kind: 'prompt', key: 'pet.q3' });
        setStep(2);
      } else {
        // No verified programme in this country yet: say so honestly
        // and stop asking — a budget question here would have nothing
        // to decide, and no programme or route is ever invented.
        push({ kind: 'noProgrammes', degree: answers.degree as Degree, country });
        setStep(3);
      }
    } else if (step === 2) {
      const band = value as Band;
      const degree = answers.degree as Degree;
      const country = answers.country as Country;
      setAnswers((a) => ({ ...a, budget: band }));
      push({ kind: 'choice', step: 2, value, degree, country });
      setStep(3);
      void askSuggest(degree, country, band);
    }
  };

  /** Free text goes to the real model, with the conversation history
   * for context. Round 10: a template-only reply IS shown — led by
   * the offline line, with the template's own verified lines after
   * it — because the backend's template answer (e.g. the Swiss
   * schools for "瑞士有哪些好学校？") is a real answer the user
   * needs, and discarding it used to leave nothing at all. Only
   * when the call itself fails (backend unreachable) does the turn
   * fall back to the labelled offline rank lookup, the built-in
   * country directory, or the plain offline line. Round 7,
   * Fix B: on the first free-text turn the saved wizard preferences
   * travel as context with the message (the displayed message stays
   * the user's verbatim words), so a greeting like "你好" gets a real
   * reply that knows what is already saved instead of a canned intro
   * that contradicts it. */
  const onSend = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    push({ kind: 'freeText', text });
    setBusy(true);
    setWaking(false);
    const requestLocale = locale;
    // Round 8: the conversation this call belongs to — a restart
    // while the call is in flight must not let the late reply land
    // in the new conversation.
    const conv = convRef.current;
    beginPatientCall();
    // Round 15, F2: one turn is bounded to ~20 s by fetchJsonChat
    // (lib/api.ts) — a slow abort falls back at once instead of
    // re-issuing the whole turn for another 40 s.
    const patientOpts = chatOpts;
    // NOTE: goOffline does not touch timedOut — the caller sets it:
    // a template reply is a fast answer (not a timeout), a thrown
    // call carries the retry verdict.
    const goOffline = () => {
      if (convRef.current !== conv) return;
      setOffline(true);
      setAiLive(false);
      const rank = rankOffline(text);
      if (rank) doCelebrate();
      push({ kind: 'ask', message: text, reply: null, replyLocale: null, offline: true, devil: devilMode, offlineRankId: rank?.institutionId ?? null, offlineCountry: countryFromMessage(text) });
    };
    const hasAsked = messages.some((m) => m.kind === 'ask');
    const context = !hasAsked ? savedPrefsContext(profile) : null;
    const sentMessage = context ? `${text}\n${context}` : text;
    // Devil's advocate (round 11): the saved preferences travel as a
    // structured profile with mode=devil, so the backend challenges
    // them with engine-computed conflicts; without a profile the
    // backend derives what it can from the message itself.
    const devilProf = devilMode ? devilProfileFor(profile) : null;
    try {
      const r = await fetchJsonChat<ChatReply>('/api/assistant/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: sentMessage, locale: requestLocale, history: buildHistory(messages),
          ...(devilProf ? { mode: 'devil', profile: devilProf } : {}),
        }),
      }, patientOpts);
      setWaking(false);
      if (!isModelReply(r)) {
        // Round 10: the verified template answer, led by the offline
        // line at render time — never discarded. A reply with no
        // lines at all still falls through to the catalogue.
        if (r.lines?.length) {
          if (convRef.current !== conv) return;
          setOffline(true);
          setTimedOut(false);
          setAiLive(false);
          if (deriveChatLinks(r.sources).program || deriveChatLinks(r.sources).institution) doCelebrate();
          push({ kind: 'ask', message: text, reply: r, replyLocale: requestLocale, offline: true, devil: devilMode, offlineRankId: null, offlineCountry: null });
          return;
        }
        setTimedOut(false);
        goOffline();
        return;
      }
      if (convRef.current !== conv) return;
      setOffline(false);
      setTimedOut(false);
      setAiLive(true);
      if (deriveChatLinks(r.sources).program || deriveChatLinks(r.sources).institution) doCelebrate();
      push({ kind: 'ask', message: text, reply: r, replyLocale: requestLocale, offline: false, devil: devilMode, offlineRankId: null, offlineCountry: null });
    } catch (err) {
      setWaking(false);
      if (convRef.current === conv) {
        setTimedOut(callTimedOut(err));
        goOffline();
      }
    } finally {
      if (convRef.current === conv) {
        setWaking(false);
        setBusy(false);
      }
    }
  };

  const chips: { value: string; label: string }[] =
    step === 0
      ? [{ value: 'undergraduate', label: t('pet.q1ug') }, { value: 'taught_masters', label: t('pet.q1tm') }]
      : step === 1
        ? PET_COUNTRY_CODES.map((code) => ({ value: code, label: t(`country.${code}`) }))
        : step === 2
          ? answers.country === 'GB'
            ? [{ value: 'low', label: t('pet.q3gbLow') }, { value: 'mid', label: t('pet.q3gbMid') }, { value: 'high', label: t('pet.q3gbHigh') }]
            : answers.country === 'SG'
              ? answers.degree === 'undergraduate'
                ? [{ value: 'low', label: t('pet.q3sgUgLow') }, { value: 'mid', label: t('pet.q3sgUgMid') }, { value: 'high', label: t('pet.q3sgUgHigh') }]
                : [{ value: 'low', label: t('pet.q3sgTmLow') }, { value: 'mid', label: t('pet.q3sgTmMid') }, { value: 'high', label: t('pet.q3sgTmHigh') }]
              : [{ value: 'low', label: t('pet.q3Low') }, { value: 'mid', label: t('pet.q3Mid') }, { value: 'high', label: t('pet.q3High') }]
          : [];

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => toggle(!open)}
        aria-label={t('pet.openLabel')}
        aria-expanded={open}
        className={`btn-press anim-pet-pop fixed bottom-4 end-4 z-50 rounded-full bg-white p-1.5 shadow-lg ring-2 ring-amber${busy ? ' pet-thinking glow-amber-on' : ''}`}
      >
        <span className={`anim-pet-bob${celebrate ? ' anim-pet-celebrate' : ''}`}>
          <CompassFace size={52} mood={mood} eyesRef={(el) => { faceElsRef.current.eyes = el; }} needleRef={(el) => { faceElsRef.current.needle = el; }} />
        </span>
      </button>
      {open && (
        <div
          role="dialog"
          aria-label={t('pet.name')}
          className="anim-pet-panel fixed bottom-24 end-4 z-50 flex max-h-[70vh] w-[min(92vw,380px)] flex-col overflow-hidden rounded-3xl bg-white shadow-xl ring-1 ring-navy/10"
          onKeyDown={(e) => { if (e.key === 'Escape') toggle(false); }}
        >
          <div className="flex items-center gap-2 bg-teal px-3 py-2 text-white">
            <span className={typing ? 'pet-lean inline-flex' : 'inline-flex'}>
              <CompassFace size={36} mood={mood} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-bold">{t('pet.name')}</p>
              <p className="truncate text-xs text-white/80">{t('pet.subtitle')}</p>
            </div>
            <button type="button" onClick={greet} className="btn-press rounded-full px-2 py-1 text-xs font-semibold hover:bg-white/15" title={t('pet.restart')}>{t('pet.restart')}</button>
            <button type="button" onClick={() => toggle(false)} aria-label={t('pet.close')} className="btn-press rounded-full px-2 py-1 text-base font-bold leading-none hover:bg-white/15">×</button>
          </div>
          {/* Saved preferences, in the user's own words: the pet remembers
              what the wizard learned, but never invents a programme fact
              from them — suggestions still use only verified data.
              Round 18 (W3): hidden on /results, where the results page
              itself already shows the full summary (its own edit link,
              results.prefEdit, is on that page) — otherwise the summary
              appears three times on the page: results page + this strip
              + the pet.greetingKnown opening bubble. */}
          {hasPreferences(profile) && pathname !== '/results' && (
            <div className="flex items-center justify-between gap-2 bg-amber/15 px-3 py-2 text-xs text-navy">
              <p className="min-w-0 truncate">{tf('pet.prefSaved', { prefs: prefSummary(profile, t) })}</p>
              <Link href="/wizard" onClick={closeForNavigation} className="btn-press shrink-0 rounded-full bg-white px-2.5 py-1 font-semibold text-navy ring-1 ring-navy/10">{t('results.prefEdit')}</Link>
            </div>
          )}
          <div className="flex-1 space-y-2 overflow-y-auto bg-paper p-3 text-sm">
            {messages.map((m, i) => {
              const rendered = renderTurn(m);
              const isUser = m.kind === 'choice' || m.kind === 'freeText';
              return (
                <div key={i} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] rounded-2xl px-3 py-2 ${isUser ? 'bg-teal text-white' : rendered.devil ? 'bg-amber/10 text-navy shadow-sm ring-2 ring-amber' : 'bg-white text-navy shadow-sm ring-1 ring-navy/5'}`}>
                    {rendered.devil && (
                      <>
                        <p className="text-[11px] font-bold leading-tight text-navy/70">{t(rendered.devilOffline ? 'devil.offlineBoundary' : 'devil.boundary')}</p>
                        <div className="my-1.5 border-t border-amber" aria-hidden="true" />
                      </>
                    )}
                    {rendered.lines.filter(Boolean).map((line, j) => (
                      <p key={j} className={j > 0 ? 'mt-1' : ''}>{line}</p>
                    ))}
                    {rendered.evidenceUrl && (
                      <a href={rendered.evidenceUrl} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs font-semibold text-teal underline">
                        {t('pet.evidence')} ↗
                      </a>
                    )}
                    {rendered.nextSteps && (
                      <div className="mt-2 flex flex-wrap gap-2">
                        <Link href={rendered.nextSteps.wizard ?? '/wizard'} onClick={closeForNavigation} className="btn-press rounded-full bg-amber px-3 py-1.5 text-xs font-bold text-navy">
                          {t('pet.ctaWizard')}
                        </Link>
                        {rendered.nextSteps.program && (
                          <Link href={rendered.nextSteps.program} onClick={closeForNavigation} className="btn-press rounded-full border border-navy/25 px-3 py-1.5 text-xs font-semibold text-navy">
                            {t('pet.ctaProgram')}
                          </Link>
                        )}
                        {rendered.nextSteps.institution && !rendered.nextSteps.program && (
                          <Link href={rendered.nextSteps.institution} onClick={closeForNavigation} className="btn-press rounded-full border border-navy/25 px-3 py-1.5 text-xs font-semibold text-navy">
                            {t('pet.ctaInstitution')}
                          </Link>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
            {busy && (
              <div className="flex justify-start">
                {/* Alive thinking treatment (design upgrade, Worker C):
                    .think-dots / .glow-amber are global classes owned
                    by the globals.css worker — used here, not defined
                    here. Visuals only; the elapsed-seconds text and
                    all logic are unchanged. */}
                <div className="glow-amber-on rounded-2xl bg-white px-3 py-2 text-navy/60 shadow-sm ring-1 ring-navy/5">
                  <span>{waking ? tf('pet.wakingElapsed', { seconds: wakingElapsed }) : tf('r9chat.thinkingElapsed', { seconds: busyElapsed })}</span>
                  <span className="think-dots ms-2" aria-hidden="true"><span /><span /><span /></span>
                </div>
              </div>
            )}
            {chips.length > 0 && !busy && (
              <div className="flex flex-wrap gap-2 pt-1">
                {chips.map((c) => (
                  <button key={c.value} type="button" onClick={() => onChip(c.value)} className="btn-press anim-chip rounded-full bg-teal px-3 py-1.5 text-xs font-semibold text-white">
                    {c.label}
                  </button>
                ))}
              </div>
            )}
            <div ref={bottomRef} />
          </div>
          <div className="border-t border-navy/10 bg-white p-2">
            {/* Devil's advocate toggle (round 11; round 14 gating):
                a second AI voice that challenges the saved preferences
                with verified facts. The reply renders with the devil
                boundary line above, never as a verdict. Round 14: the
                toggle renders exactly when there is something to
                challenge (canDevil — devilProfileFor(profile) is
                non-null, i.e. saved preferences exist) and is hidden
                only when there genuinely is nothing to challenge.
                Before, it was unconditional inside the panel, so its
                visibility depended entirely on the panel's session
                flag (see the /results restore effect): it appeared
                once from a stale flag and then never came back. */}
            {canDevil && (
              <div className="mb-2 flex items-center justify-start px-1">
                <button
                  type="button"
                  onClick={() => setDevilMode((d) => !d)}
                  aria-pressed={devilMode}
                  className={`btn-press rounded-full px-3 py-1.5 text-xs font-semibold ${devilMode ? 'bg-amber/15 text-navy ring-1 ring-amber' : 'text-navy/70 ring-1 ring-navy/20 hover:bg-paper'}`}
                >
                  {devilMode ? t('devil.toggleActive') : t('devil.toggle')}
                </button>
              </div>
            )}
            <div className="flex gap-2">
              <input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onFocus={() => setInputFocused(true)}
                onBlur={() => setInputFocused(false)}
                onKeyDown={(e) => { if (e.key === 'Enter') void onSend(); }}
                placeholder={t('pet.placeholder')}
                aria-label={t('pet.placeholder')}
                maxLength={500}
                className="min-w-0 flex-1 rounded-full border border-navy/20 px-3 py-2 text-sm outline-none focus:border-teal"
              />
              <button type="button" onClick={() => void onSend()} disabled={busy || !input.trim()} className="btn-press rounded-full bg-teal px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">
                {t('pet.send')}
              </button>
            </div>
            <div className="mt-1.5 flex items-center justify-center gap-2 px-1 text-[11px] leading-tight text-navy/50">
              <span>
                {waking
                  ? tf('pet.wakingElapsed', { seconds: wakingElapsed })
                  : offline || aiLive === false
                    ? timedOut ? t('pet.offlineTimeout') : t('pet.offline')
                    : aiLive === true
                      ? t('pet.aiLive')
                      : t('pet.aiChecking')}
              </span>
              {/* Round 8: the retry stays available after sending a
                  message (it used to disappear while waking) — it is
                  only disabled while a check is already running. */}
              {(offline || aiLive === false) && (
                <button type="button" onClick={retryStatus} disabled={waking || busy} className="btn-press shrink-0 rounded-full bg-amber px-2.5 py-1 text-[11px] font-bold text-navy disabled:opacity-40">
                  {t('pet.retry')}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
