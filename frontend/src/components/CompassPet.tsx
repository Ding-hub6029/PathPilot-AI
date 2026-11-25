'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useApp, type Locale } from '../lib/store';
import { fetchJson } from '../lib/api';
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
 * link) and stops asking. Free text is answered only from verified data.
 *
 * Rules/template mode only: no model is connected (the backend returns
 * ai_status="unavailable" and the panel says so). Unknown stays unknown,
 * no admission probabilities, no personal data is ever asked for or kept.
 * The panel's open state is remembered in sessionStorage only
 * ('pp-pet-open'); closing it forgets it for the session.
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

/** True when the verified catalogue holds a programme in this country. */
function hasVerifiedProgrammes(country: string): boolean {
  return PROGRAMS.some((p) => p.country === country);
}

interface AssistantReply {
  lines: string[];
  program_id?: string | null;
  program_name?: string | null;
  institution_id?: string | null;
  evidence_url?: string | null;
  fee_fit?: string;
  ai_status?: string;
  next_steps?: { wizard?: string; program?: string | null; institution?: string | null };
}

/** One conversation turn, stored as structured data only. */
type ChatTurn =
  | { kind: 'prompt'; key: 'pet.greeting' | 'pet.q1' | 'pet.q2' | 'pet.q3' }
  | { kind: 'choice'; step: 0 | 1 | 2; value: string; degree?: Degree; country?: Country }
  | { kind: 'freeText'; text: string }
  | {
      kind: 'suggest';
      degree: Degree; country: Country; band: Band;
      /** Live backend payload + the locale it was answered in. */
      reply: AssistantReply | null;
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
      /** Live backend payload + the locale it was answered in. */
      reply: AssistantReply | null;
      replyLocale: Locale | null;
      /** True when the live call failed and the offline catalogue is used. */
      offline: boolean;
      /** Offline rank lookup hit (locale-independent lines). */
      offlineRankId: string | null;
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
 * fee item) carry a usable offline fee; SG undergraduate has no
 * without-grant fee in the offline list, so it honestly returns null.
 * Returns structured data only — the programme name is rendered at
 * render time via displayProgramTitle(), never stored as a string. */
interface OfflineSuggestion {
  programId: string;
  evidenceUrl: string | null;
  fee: { currency: string; amount: number; period: string } | null;
  fit: 'within' | 'above';
}

function suggestOffline(degree: Degree, country: Country, band: Band): OfflineSuggestion | null {
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

/** Offline rank lookup from the built-in 300 entries. Matches the same
 * short aliases the backend knows; anything else stays unknown. The
 * lines it builds are locale-independent (official names, provider
 * codes and rank numbers only), so they are safe to render as-is. */
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

function rankOffline(message: string): AssistantReply | null {
  const msg = message.toLowerCase();
  let instId: string | undefined;
  for (const [alias, id] of Object.entries(OFFLINE_RANK_ALIASES)) {
    if (msg.includes(alias)) { instId = id; break; }
  }
  if (!instId) return null;
  const inst = RANKING_INSTITUTIONS.find((i) => i.id === instId);
  if (!inst) return null;
  const parts = (['qs', 'the', 'arwu'] as const).map((provider) => {
    const e = RANKING_ENTRIES.find((x) => x.institution_id === instId && x.provider === provider);
    return e && e.rank_display ? `${provider.toUpperCase()} ${e.edition_label} #${e.rank_display}` : `${provider.toUpperCase()} —`;
  });
  const profiles = inst.provider_profiles ?? {};
  return {
    lines: [`${inst.official_name}: ${parts.join(' · ')}.`],
    institution_id: instId,
    evidence_url: profiles.qs ?? profiles.the ?? profiles.arwu ?? null,
    ai_status: 'unavailable',
    next_steps: { wizard: '/wizard', institution: `/institutions/${instId}` },
  };
}

type PetMood = 'idle' | 'think' | 'celebrate' | 'empathise' | 'bored';

/** Mouth per mood — the face is the state machine's display. */
const MOUTH: Record<PetMood, string> = {
  idle: 'M30 50 Q36 55 42 50',
  think: 'M31 51 L41 51',
  celebrate: 'M29 49 Q36 58 43 49',
  empathise: 'M30 53 Q36 48 42 53',
  bored: 'M31 51 L41 51',
};

function CompassFace({
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

export function CompassPet() {
  const { t, tf, locale } = useApp();
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<{ degree?: Degree; country?: Country; budget?: Band }>({});
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(false);
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
    setMessages([
      { kind: 'prompt', key: 'pet.greeting' },
      { kind: 'prompt', key: 'pet.q1' },
    ]);
    setStep(0);
    setAnswers({});
  };

  useEffect(() => {
    try {
      if (sessionStorage.getItem('pp-pet-open') === '1') setOpen(true);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (open && messages.length === 0) greet();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [messages, busy]);

  /**
   * Locale change: re-fetch every live backend-backed turn whose reply
   * was answered in the old locale, in the new locale. While a turn
   * awaits its fresh reply it renders the thinking line (see
   * renderTurn), never the old-locale lines. A failed re-fetch falls
   * back to the offline catalogue rendered in the new locale. The
   * in-flight set stops duplicate fetches; replyLocale records the
   * locale each reply was actually answered in, so a reply that lands
   * after a further switch is re-fetched again instead of shown stale.
   */
  useEffect(() => {
    messages.forEach((m, i) => {
      if ((m.kind !== 'suggest' && m.kind !== 'ask') || !m.reply || m.replyLocale === locale) return;
      if (inFlightRef.current.has(i)) return;
      inFlightRef.current.add(i);
      const conv = convRef.current;
      const req = m.kind === 'suggest'
        ? fetchJson<AssistantReply>('/api/assistant/suggest', {
            method: 'POST',
            body: JSON.stringify({ degree_level: m.degree, country: m.country, budget_band: m.band, locale }),
          })
        : fetchJson<AssistantReply>('/api/assistant/ask', {
            method: 'POST',
            body: JSON.stringify({ message: m.message, locale }),
          });
      req.then((fresh) => {
        if (convRef.current !== conv) return;
        setOffline(false);
        setMessages((prev) => prev.map((x, j) => {
          if (j !== i || (x.kind !== 'suggest' && x.kind !== 'ask')) return x;
          return { ...x, reply: fresh, replyLocale: locale };
        }));
      }).catch(() => {
        if (convRef.current !== conv) return;
        setOffline(true);
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
            return { ...x, reply: null, replyLocale: null, offline: true, offlineRankId: rank?.institution_id ?? null };
          }
          return x;
        }));
      }).finally(() => { inFlightRef.current.delete(i); });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale, messages]);

  const toggle = (next: boolean) => {
    setOpen(next);
    try {
      if (next) sessionStorage.setItem('pp-pet-open', '1');
      else sessionStorage.removeItem('pp-pet-open');
    } catch { /* ignore */ }
    if (next) setTimeout(() => inputRef.current?.focus(), 100);
  };

  const push = (msg: ChatTurn) => setMessages((prev) => [...prev, msg]);

  /** Label for a stored quick-reply choice, localised at render time. */
  const choiceLabel = (turn: Extract<ChatTurn, { kind: 'choice' }>): string => {
    if (turn.step === 0) return t(turn.value === 'undergraduate' ? 'pet.q1ug' : 'pet.q1tm');
    if (turn.step === 1) return t(`country.${turn.value}`);
    if (turn.country === 'GB') {
      return t(turn.value === 'low' ? 'pet.q3gbLow' : turn.value === 'mid' ? 'pet.q3gbMid' : 'pet.q3gbHigh');
    }
    if (turn.degree === 'undergraduate') {
      return t(turn.value === 'low' ? 'pet.q3sgUgLow' : turn.value === 'mid' ? 'pet.q3sgUgMid' : 'pet.q3sgUgHigh');
    }
    return t(turn.value === 'low' ? 'pet.q3sgTmLow' : turn.value === 'mid' ? 'pet.q3sgTmMid' : 'pet.q3sgTmHigh');
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
  } => {
    switch (turn.kind) {
      case 'prompt':
        return { lines: [t(turn.key)] };
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
          return { lines: turn.reply.lines, evidenceUrl: turn.reply.evidence_url, nextSteps: turn.reply.next_steps };
        }
        if (turn.reply) return { lines: [t('pet.thinking')] };
        if (turn.offline) {
          if (!turn.offlineProgramId) return { lines: [t('pet.offline')] };
          const program = PROGRAMS.find((p) => p.id === turn.offlineProgramId);
          const lines = [
            t('pet.offline'),
            program ? displayProgramTitle(program, locale) : turn.offlineProgramId,
          ];
          if (turn.offlineFee) {
            const fee = tf(turn.offlineFee.period === 'total' ? 'pet.feeTotal' : 'pet.feePerYear',
              { currency: turn.offlineFee.currency, amount: money(turn.offlineFee.amount) });
            lines.push(tf(turn.offlineFit === 'within' ? 'pet.feeWithin' : 'pet.feeAbove', { fee }));
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
          return { lines: turn.reply.lines, evidenceUrl: turn.reply.evidence_url, nextSteps: turn.reply.next_steps };
        }
        if (turn.reply) return { lines: [t('pet.thinking')] };
        if (turn.offline) {
          const rank = rankOffline(turn.message);
          if (rank) return { lines: rank.lines, evidenceUrl: rank.evidence_url, nextSteps: rank.next_steps };
          return { lines: [t('pet.offline')] };
        }
        return { lines: [t('pet.thinking')] };
      }
    }
  };

  const askSuggest = async (degree: Degree, country: Country, band: Band) => {
    if (!hasVerifiedProgrammes(country)) {
      // Defensive: the Q2 branch already answers this without calling
      // the backend, so this is unreachable in the normal flow.
      push({ kind: 'noProgrammes', degree, country });
      return;
    }
    setBusy(true);
    const requestLocale = locale;
    try {
      const r = await fetchJson<AssistantReply>('/api/assistant/suggest', {
        method: 'POST',
        body: JSON.stringify({ degree_level: degree, country, budget_band: band, locale: requestLocale }),
      });
      setOffline(false);
      if (r.program_id || r.institution_id) doCelebrate();
      push({
        kind: 'suggest', degree, country, band,
        reply: r, replyLocale: requestLocale, offline: false,
        offlineProgramId: null, offlineEvidenceUrl: null, offlineFee: null, offlineFit: null,
      });
    } catch {
      setOffline(true);
      const off = suggestOffline(degree, country, band);
      if (off) doCelebrate();
      push({
        kind: 'suggest', degree, country, band,
        reply: null, replyLocale: null, offline: true,
        offlineProgramId: off?.programId ?? null,
        offlineEvidenceUrl: off?.evidenceUrl ?? null,
        offlineFee: off?.fee ?? null, offlineFit: off?.fit ?? null,
      });
    } finally {
      setBusy(false);
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

  const onSend = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    push({ kind: 'freeText', text });
    setBusy(true);
    const requestLocale = locale;
    try {
      const r = await fetchJson<AssistantReply>('/api/assistant/ask', {
        method: 'POST',
        body: JSON.stringify({ message: text, locale: requestLocale }),
      });
      setOffline(false);
      if (r.program_id || r.institution_id) doCelebrate();
      push({ kind: 'ask', message: text, reply: r, replyLocale: requestLocale, offline: false, offlineRankId: null });
    } catch {
      setOffline(true);
      const rank = rankOffline(text);
      if (rank) doCelebrate();
      push({ kind: 'ask', message: text, reply: null, replyLocale: null, offline: true, offlineRankId: rank?.institution_id ?? null });
    } finally {
      setBusy(false);
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
            : answers.degree === 'undergraduate'
              ? [{ value: 'low', label: t('pet.q3sgUgLow') }, { value: 'mid', label: t('pet.q3sgUgMid') }, { value: 'high', label: t('pet.q3sgUgHigh') }]
              : [{ value: 'low', label: t('pet.q3sgTmLow') }, { value: 'mid', label: t('pet.q3sgTmMid') }, { value: 'high', label: t('pet.q3sgTmHigh') }]
          : [];

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => toggle(!open)}
        aria-label={t('pet.openLabel')}
        aria-expanded={open}
        className={`btn-press anim-pet-pop fixed bottom-4 end-4 z-50 rounded-full bg-white p-1.5 shadow-lg ring-2 ring-amber${busy ? ' pet-thinking' : ''}`}
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
          <div className="flex-1 space-y-2 overflow-y-auto bg-paper p-3 text-sm">
            {messages.map((m, i) => {
              const rendered = renderTurn(m);
              const isUser = m.kind === 'choice' || m.kind === 'freeText';
              return (
                <div key={i} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] rounded-2xl px-3 py-2 ${isUser ? 'bg-teal text-white' : 'bg-white text-navy shadow-sm ring-1 ring-navy/5'}`}>
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
                        <Link href={rendered.nextSteps.wizard ?? '/wizard'} onClick={() => toggle(false)} className="btn-press rounded-full bg-amber px-3 py-1.5 text-xs font-bold text-navy">
                          {t('pet.ctaWizard')}
                        </Link>
                        {rendered.nextSteps.program && (
                          <Link href={rendered.nextSteps.program} onClick={() => toggle(false)} className="btn-press rounded-full border border-navy/25 px-3 py-1.5 text-xs font-semibold text-navy">
                            {t('pet.ctaProgram')}
                          </Link>
                        )}
                        {rendered.nextSteps.institution && !rendered.nextSteps.program && (
                          <Link href={rendered.nextSteps.institution} onClick={() => toggle(false)} className="btn-press rounded-full border border-navy/25 px-3 py-1.5 text-xs font-semibold text-navy">
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
                <div className="rounded-2xl bg-white px-3 py-2 text-navy/60 shadow-sm ring-1 ring-navy/5">{t('pet.thinking')}</div>
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
            <p className="mt-1.5 px-1 text-center text-[11px] leading-tight text-navy/50">
              {offline ? t('pet.offline') : t('pet.rulesMode')}
            </p>
          </div>
        </div>
      )}
    </>
  );
}
