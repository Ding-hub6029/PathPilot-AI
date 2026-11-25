'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useApp } from '../lib/store';
import { fetchJson } from '../lib/api';
import { PROGRAMS } from '../lib/programs';
import { RANKING_ENTRIES, RANKING_INSTITUTIONS } from '../lib/rankings';

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
 */

type Degree = 'undergraduate' | 'taught_masters';
type Country = 'GB' | 'SG';
type Band = 'low' | 'mid' | 'high';

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

interface ChatMsg {
  role: 'pet' | 'user';
  lines: string[];
  reply?: AssistantReply;
}

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
 * without-grant fee in the offline list, so it honestly returns null. */
interface OfflineSuggestion {
  programId: string;
  programName: string;
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
    programName: `${picked.p.institution} — ${picked.p.officialName}`,
    evidenceUrl: picked.p.sources[0]?.url ?? null,
    fee: { currency: item.currency, amount: item.amount, period: item.period },
    fit,
  };
}

/** Offline rank lookup from the built-in 300 entries. Matches the same
 * short aliases the backend knows; anything else stays unknown. */
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

function CompassFace({ size = 56 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 72 72" aria-hidden="true">
      <circle cx="36" cy="36" r="34" fill="#0E7C7B" />
      <circle cx="36" cy="36" r="27" fill="#F7F5F0" />
      <g stroke="#0B1F3A" strokeWidth="2" strokeLinecap="round">
        <line x1="36" y1="12" x2="36" y2="17" />
        <line x1="36" y1="55" x2="36" y2="60" />
        <line x1="12" y1="36" x2="17" y2="36" />
        <line x1="55" y1="36" x2="60" y2="36" />
      </g>
      <g className="anim-needle" style={{ transformOrigin: '36px 36px' }}>
        <polygon points="36,18 41,36 36,34 31,36" fill="#F2A541" />
        <polygon points="36,54 41,36 36,38 31,36" fill="#0B1F3A" />
      </g>
      <circle cx="36" cy="36" r="3.5" fill="#0B1F3A" />
      <circle cx="28" cy="45" r="2.2" fill="#0B1F3A" />
      <circle cx="44" cy="45" r="2.2" fill="#0B1F3A" />
      <path d="M30 50 Q36 55 42 50" fill="none" stroke="#0B1F3A" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

export function CompassPet() {
  const { t, tf, locale } = useApp();
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<{ degree?: Degree; country?: Country; budget?: Band }>({});
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const greet = () => {
    setMessages([
      { role: 'pet', lines: [t('pet.greeting')] },
      { role: 'pet', lines: [t('pet.q1')] },
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
  }, [open ]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [messages, busy]);

  const toggle = (next: boolean) => {
    setOpen(next);
    try {
      if (next) sessionStorage.setItem('pp-pet-open', '1');
      else sessionStorage.removeItem('pp-pet-open');
    } catch { /* ignore */ }
    if (next) setTimeout(() => inputRef.current?.focus(), 100);
  };

  const push = (msg: ChatMsg) => setMessages((prev) => [...prev, msg]);

  const askSuggest = async (degree: Degree, country: Country, band: Band) => {
    setBusy(true);
    try {
      const r = await fetchJson<AssistantReply>('/api/assistant/suggest', {
        method: 'POST',
        body: JSON.stringify({ degree_level: degree, country, budget_band: band, locale }),
      });
      push({ role: 'pet', lines: r.lines, reply: r });
    } catch {
      setOffline(true);
      const r = suggestOffline(degree, country, band);
      if (r) {
        const fee = r.fee
          ? tf(r.fee.period === 'total' ? 'pet.feeTotal' : 'pet.feePerYear',
               { currency: r.fee.currency, amount: money(r.fee.amount) })
          : null;
        const lines = [t('pet.offline'), r.programName];
        if (fee) lines.push(tf(r.fit === 'within' ? 'pet.feeWithin' : 'pet.feeAbove', { fee }));
        push({
          role: 'pet',
          lines,
          reply: {
            lines, program_id: r.programId, program_name: r.programName,
            evidence_url: r.evidenceUrl, fee_fit: r.fit, ai_status: 'unavailable',
            next_steps: { wizard: '/wizard', program: `/programs/${r.programId}` },
          },
        });
      } else {
        push({ role: 'pet', lines: [t('pet.offline')] });
      }
    } finally {
      setBusy(false);
    }
  };

  const onChip = (value: string) => {
    if (busy) return;
    if (step === 0) {
      const degree = value as Degree;
      setAnswers((a) => ({ ...a, degree }));
      push({ role: 'user', lines: [value === 'undergraduate' ? t('pet.q1ug') : t('pet.q1tm')] });
      push({ role: 'pet', lines: [t('pet.q2')] });
      setStep(1);
    } else if (step === 1) {
      const country = value as Country;
      setAnswers((a) => ({ ...a, country }));
      push({ role: 'user', lines: [value === 'GB' ? t('pet.q2gb') : t('pet.q2sg')] });
      push({ role: 'pet', lines: [t('pet.q3')] });
      setStep(2);
    } else if (step === 2) {
      const band = value as Band;
      const degree = answers.degree as Degree;
      const country = answers.country as Country;
      const label =
        country === 'GB'
          ? band === 'low' ? t('pet.q3gbLow') : band === 'mid' ? t('pet.q3gbMid') : t('pet.q3gbHigh')
          : degree === 'undergraduate'
            ? band === 'low' ? t('pet.q3sgUgLow') : band === 'mid' ? t('pet.q3sgUgMid') : t('pet.q3sgUgHigh')
            : band === 'low' ? t('pet.q3sgTmLow') : band === 'mid' ? t('pet.q3sgTmMid') : t('pet.q3sgTmHigh');
      setAnswers((a) => ({ ...a, budget: band }));
      push({ role: 'user', lines: [label] });
      setStep(3);
      void askSuggest(degree, country, band);
    }
  };

  const onSend = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    push({ role: 'user', lines: [text] });
    setBusy(true);
    try {
      const r = await fetchJson<AssistantReply>('/api/assistant/ask', {
        method: 'POST',
        body: JSON.stringify({ message: text, locale }),
      });
      push({ role: 'pet', lines: r.lines, reply: r });
    } catch {
      setOffline(true);
      const isRank = /排名|rank|qs|泰晤士|软科|arwu|第几/i.test(text);
      const r = isRank ? rankOffline(text) : null;
      if (r) push({ role: 'pet', lines: r.lines, reply: r });
      else push({ role: 'pet', lines: [t('pet.offline')] });
    } finally {
      setBusy(false);
    }
  };

  const chips: { value: string; label: string }[] =
    step === 0
      ? [{ value: 'undergraduate', label: t('pet.q1ug') }, { value: 'taught_masters', label: t('pet.q1tm') }]
      : step === 1
        ? [{ value: 'GB', label: t('pet.q2gb') }, { value: 'SG', label: t('pet.q2sg') }]
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
        type="button"
        onClick={() => toggle(!open)}
        aria-label={t('pet.openLabel')}
        aria-expanded={open}
        className="btn-press anim-pet-pop fixed bottom-4 end-4 z-50 rounded-full bg-white p-1.5 shadow-lg ring-2 ring-amber"
      >
        <CompassFace size={52} />
      </button>
      {open && (
        <div
          role="dialog"
          aria-label={t('pet.name')}
          className="anim-pet-panel fixed bottom-24 end-4 z-50 flex max-h-[70vh] w-[min(92vw,380px)] flex-col overflow-hidden rounded-3xl bg-white shadow-xl ring-1 ring-navy/10"
          onKeyDown={(e) => { if (e.key === 'Escape') toggle(false); }}
        >
          <div className="flex items-center gap-2 bg-teal px-3 py-2 text-white">
            <CompassFace size={36} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-bold">{t('pet.name')}</p>
              <p className="truncate text-xs text-white/80">{t('pet.subtitle')}</p>
            </div>
            <button type="button" onClick={greet} className="btn-press rounded-full px-2 py-1 text-xs font-semibold hover:bg-white/15" title={t('pet.restart')}>{t('pet.restart')}</button>
            <button type="button" onClick={() => toggle(false)} aria-label={t('pet.close')} className="btn-press rounded-full px-2 py-1 text-base font-bold leading-none hover:bg-white/15">×</button>
          </div>
          <div className="flex-1 space-y-2 overflow-y-auto bg-paper p-3 text-sm">
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-2xl px-3 py-2 ${m.role === 'user' ? 'bg-teal text-white' : 'bg-white text-navy shadow-sm ring-1 ring-navy/5'}`}>
                  {m.lines.filter(Boolean).map((line, j) => (
                    <p key={j} className={j > 0 ? 'mt-1' : ''}>{line}</p>
                  ))}
                  {m.reply?.evidence_url && (
                    <a href={m.reply.evidence_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs font-semibold text-teal underline">
                      {t('pet.evidence')} ↗
                    </a>
                  )}
                  {m.reply?.next_steps && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Link href={m.reply.next_steps.wizard ?? '/wizard'} onClick={() => toggle(false)} className="btn-press rounded-full bg-amber px-3 py-1.5 text-xs font-bold text-navy">
                        {t('pet.ctaWizard')}
                      </Link>
                      {m.reply.next_steps.program && (
                        <Link href={m.reply.next_steps.program} onClick={() => toggle(false)} className="btn-press rounded-full border border-navy/25 px-3 py-1.5 text-xs font-semibold text-navy">
                          {t('pet.ctaProgram')}
                        </Link>
                      )}
                      {m.reply.next_steps.institution && !m.reply.next_steps.program && (
                        <Link href={m.reply.next_steps.institution} onClick={() => toggle(false)} className="btn-press rounded-full border border-navy/25 px-3 py-1.5 text-xs font-semibold text-navy">
                          {t('pet.ctaInstitution')}
                        </Link>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
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
