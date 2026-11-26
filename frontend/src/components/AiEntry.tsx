'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useApp } from '../lib/store';
import { fetchJsonPatient } from '../lib/api';
import { deriveChatLinks, isModelReply, type ChatReply } from '../lib/chat';
import type { Profile } from '../lib/types';

/**
 * AiEntry — the AI visibility layer (W5): one shared AI entry point
 * for the major pages (rankings, institution detail, cases, programme
 * browse, programme detail), reusing the existing grounded chat
 * (POST /api/assistant/chat) instead of a new model capability.
 *
 * Interaction choice: an inline mini-panel that calls the endpoint
 * directly — NOT opening the pet with a prefilled question. The pet
 * (CompassPet) exposes no opener/prefill API: its state lives inside
 * the component, and reaching it from a page would mean a new global
 * event or store field plus touching the layout and the store, both
 * outside this layer's ownership. The inline panel is self-contained,
 * reuses the pet's own rules (fetchJsonPatient with the same ~90 s
 * patient budget, isModelReply for the AI/offline distinction, and
 * deriveChatLinks for next-step links, never from model text), and
 * aborts its request on unmount/close (the P0 abort pattern).
 *
 * Honesty rules (the hard boundary, in every locale):
 * - the entry is visibly labelled AI (AI badge on the button and in
 *   the panel header);
 * - a reply counts as an AI answer ONLY when ai_status is
 *   "available" (isModelReply). Anything else is the verified
 *   template answer, shown led by the offline line (aivis.offline) —
 *   never presented as a model answer;
 * - every panel carries the boundary line (aivis.boundary): verified
 *   facts carry source links, model narration is the AI's reading
 *   and may be wrong, suggestions are suggestions, unknown stays
 *   unknown. No admission probabilities anywhere;
 * - when the backend is entirely unreachable the panel says so and
 *   offers a retry — it never invents an answer.
 *
 * The question is built by the calling page from its own context
 * (provider, institution, programme id, filters) plus the saved
 * wizard profile when present; the message itself is always English
 * and the backend answers in the current locale. A locale change
 * while the panel is open re-asks in the new locale, like the pet.
 */

export type RecommendLevel = 'undergraduate' | 'taught_masters';

export interface RecommendBudget {
  currency: string;
  amount: number;
  /** 'per year' for undergraduate bands, 'total' for taught-masters totals. */
  period: 'per year' | 'total';
}

/** Budget ceiling from the saved wizard profile, or null when no
 * budget is saved. The period mirrors the pet's own band table
 * (BAND_CEILING in CompassPet): per-year, except taught masters in
 * SG, whose verified fees are programme totals. */
export function budgetFromProfile(
  profile: Profile,
  level: RecommendLevel,
  countryCode: string,
): RecommendBudget | null {
  if (typeof profile.budget !== 'number' || Number.isNaN(profile.budget)) {
    return null;
  }
  return {
    currency: profile.budgetCurrency || 'GBP',
    amount: profile.budget,
    period: level === 'taught_masters' && countryCode === 'SG' ? 'total' : 'per year',
  };
}

/** One constructed recommendation question for /assistant/chat — the
 * same shape as the guided flow's suggestMessage (lib/chat.ts) but
 * without a budget band, which only GB/SG have: degree + country
 * (name + the explicit country-code marker the backend keys on) +
 * ceiling when known. Built only from the caller's values — no
 * programme is named, so the backend suggests from the verified
 * evidence it retrieves. */
export function recommendQuestion(
  level: RecommendLevel,
  countryCode: string,
  countryName: string,
  budget: RecommendBudget | null,
): string {
  const levelText = level === 'undergraduate' ? 'undergraduate' : 'taught masters';
  let q = `Recommend a ${levelText} programme in ${countryName} (country code ${countryCode}).`;
  if (budget) {
    q += ` Budget: under ${budget.currency} ${budget.amount.toLocaleString('en-US')} ${budget.period}.`;
  }
  return q;
}

/** Fallback question when no country is known: a climate wish the
 * backend CAN answer from its curated table (top cities + verified
 * programme counts), or a bare recommendation that stays honestly
 * unknown. Never invents a country. */
export function fallbackQuestion(profile: Profile, level: RecommendLevel): string {
  const levelText = level === 'undergraduate' ? 'undergraduate' : 'taught masters';
  const climate = (profile.prefClimate || '').trim();
  if (['warm', 'cool', 'four_seasons', 'mild'].includes(climate)) {
    const word = climate === 'four_seasons' ? 'four seasons' : climate;
    return `I like a ${word} climate. Recommend a ${levelText} programme in a ${word}-climate city.`;
  }
  return `Recommend a ${levelText} programme.`;
}

export interface AiEntryProps {
  /** Button label, already localised by the caller (aivis.*). */
  label: string;
  /** The contextual question sent to /assistant/chat (English; the
   * backend answers in the current locale). */
  question: string;
  /** Extra honesty note rendered in the panel (e.g. the cases page:
   * the AI matches verified programmes, not individual cases). */
  note?: string;
  /** This entry sits on this programme's page: never link to an
   * arbitrary sibling programme from the reply's sources, and never
   * link to the page itself. */
  programId?: string;
  /** This entry sits on this institution's page: same rule — no
   * sibling-programme link, no self link. */
  institutionId?: string;
}

export function AiEntry({ label, question, note, programId, institutionId }: AiEntryProps) {
  const { t, locale } = useApp();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [waking, setWaking] = useState(false);
  const [reply, setReply] = useState<ChatReply | null>(null);
  const [replyLocale, setReplyLocale] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const requestRef = useRef(0);
  const lastQuestionRef = useRef('');

  const ask = useCallback(async (q: string, loc: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const req = ++requestRef.current;
    setBusy(true);
    setWaking(false);
    setFailed(false);
    try {
      const r = await fetchJsonPatient<ChatReply>('/api/assistant/chat', {
        method: 'POST',
        body: JSON.stringify({ message: q, locale: loc }),
      }, {
        budgetMs: 90000,
        attemptTimeoutMs: 40000,
        onRetry: () => { if (requestRef.current === req) setWaking(true); },
        signal: controller.signal,
      });
      if (requestRef.current !== req || controller.signal.aborted) return;
      setReply(r);
      setReplyLocale(loc);
      lastQuestionRef.current = q;
    } catch {
      if (controller.signal.aborted) return;
      if (requestRef.current === req) setFailed(true);
    } finally {
      if (requestRef.current === req) {
        setBusy(false);
        setWaking(false);
      }
    }
  }, []);

  // P0 abort pattern: an unmount ends the patient retry loop at once —
  // no 90 s of backend traffic behind a page the user already left.
  useEffect(() => () => {
    requestRef.current += 1;
    abortRef.current?.abort();
  }, []);

  const toggle = (next: boolean) => {
    setOpen(next);
    if (next) {
      setReply(null);
      setReplyLocale(null);
      setFailed(false);
      void ask(question, locale);
    } else {
      abortRef.current?.abort();
    }
  };

  // Locale change while open: re-ask in the new locale, like the pet —
  // a stale-locale reply is never shown as the current answer.
  useEffect(() => {
    if (!open || !reply || replyLocale === locale) return;
    void ask(question, locale);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale, open, reply, replyLocale]);

  // The page's context changed under an open panel (e.g. the browse
  // filters moved): re-ask with the new question.
  useEffect(() => {
    if (!open || !lastQuestionRef.current || lastQuestionRef.current === question) return;
    void ask(question, locale);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [question, open]);

  const model = isModelReply(reply);
  // Thinking only while a request is actually in flight. A locale
  // re-fetch starts at once on a locale change, so a stale-locale
  // reply is never shown as the current answer; if that re-fetch
  // fails, the error + retry shows instead of the stale reply.
  const showThinking = busy;
  // Next-step links come from the reply's source ids, never from model
  // text (deriveChatLinks, as in the pet). On a programme page the
  // programme link would be an arbitrary sibling, so it is dropped;
  // on an institution page both onward links are dropped (the
  // institution link is this page itself). One onward link at most —
  // the programme link wins over the institution link, as in the pet.
  const derived = deriveChatLinks(reply?.sources);
  let programLink = derived.program ?? null;
  let institutionLink = derived.institution ?? null;
  if (programId) {
    programLink = null;
  } else if (institutionId) {
    programLink = null;
    institutionLink = null;
  }
  if (programLink) institutionLink = null;

  return (
    <div>
      <button
        type="button"
        onClick={() => toggle(!open)}
        aria-expanded={open}
        className="btn-press rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy"
      >
        <span className="me-1.5 rounded bg-navy px-1.5 py-0.5 text-xs font-bold text-white">AI</span>
        {label}
      </button>
      {open && (
        <div className="mt-3 rounded-2xl border border-navy/10 bg-white p-4 shadow-sm" role="status">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-bold">
              <span className="me-1.5 rounded bg-navy px-1.5 py-0.5 text-xs font-bold text-white">AI</span>
              {reply && !showThinking
                ? (model ? t('aivis.liveBadge') : t('aivis.templateBadge'))
                : t('aivis.liveBadge')}
            </p>
            <button
              type="button"
              onClick={() => toggle(false)}
              className="btn-press rounded-full border border-navy/25 px-3 py-1 text-xs font-semibold"
            >
              {t('aivis.close')}
            </button>
          </div>

          {showThinking && (
            <p className="mt-3 text-sm text-navy/70">
              {waking ? t('pet.waking') : t('pet.thinking')}
            </p>
          )}

          {!showThinking && failed && (
            <div className="mt-3">
              <p className="text-sm font-semibold text-navy/80">{t('aivis.error')}</p>
              <button
                type="button"
                onClick={() => void ask(question, locale)}
                className="btn-press mt-2 rounded-full border border-navy/25 px-4 py-1.5 text-sm font-semibold"
              >
                {t('aivis.retry')}
              </button>
            </div>
          )}

          {!showThinking && !failed && reply && (
            <div className="mt-3">
              {!model && (
                <p className="text-sm font-semibold text-amber-dark">{t('aivis.offline')}</p>
              )}
              <div className="mt-2 space-y-1.5">
                {reply.lines.map((line, i) => (
                  <p key={i} className="text-sm text-navy/85">{line}</p>
                ))}
              </div>
              {note && (
                <p className="mt-3 text-xs text-navy/60">{note}</p>
              )}
              {(reply.evidence_url || programLink || institutionLink) && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {reply.evidence_url && (
                    <a
                      href={reply.evidence_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-block text-xs font-semibold text-teal-dark underline"
                    >
                      {t('pet.evidence')} ↗
                    </a>
                  )}
                  <Link
                    href="/wizard"
                    className="btn-press rounded-full bg-amber px-3 py-1.5 text-xs font-bold text-navy"
                  >
                    {t('pet.ctaWizard')}
                  </Link>
                  {programLink && (
                    <Link
                      href={programLink}
                      className="btn-press rounded-full border border-navy/25 px-3 py-1.5 text-xs font-semibold text-navy"
                    >
                      {t('pet.ctaProgram')}
                    </Link>
                  )}
                  {institutionLink && (
                    <Link
                      href={institutionLink}
                      className="btn-press rounded-full border border-navy/25 px-3 py-1.5 text-xs font-semibold text-navy"
                    >
                      {t('pet.ctaInstitution')}
                    </Link>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Hard boundary, always visible under the answer: verified
              facts carry source links; model narration is the AI's
              reading and may be wrong; suggestions are suggestions,
              not facts; unknown stays unknown. */}
          <p className="mt-3 border-t border-navy/10 pt-2 text-xs text-navy/60">
            {t('aivis.boundary')}
          </p>
        </div>
      )}
    </div>
  );
}
