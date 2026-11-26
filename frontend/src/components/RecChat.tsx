'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useApp, type Locale } from '../lib/store';
import { MatchResult, Program } from '../lib/types';
import { fetchJson, fetchJsonPatient } from '../lib/api';
import { isModelReply, type ChatHistoryTurn, type ChatReply } from '../lib/chat';
import { climateLabel } from '../lib/preferences';
import { StatusChip } from './StatusChip';
import { CompassFace, type PetMood } from './CompassPet';
import { formatFeeItem, formatIntake } from '../lib/format';
import { displayProgramTitle } from '../lib/programs';
import enMessages from '../../messages/en.json';

/**
 * Recommend step as a chat with 小罗盘 (2026-11-25, user: "这一步和
 * 推荐也是啊" — the chat experience is not only the pet widget; the
 * preference step AND the recommend step are chats too).
 *
 * The pet opens with its own view, then the recommended programmes sit
 * inside the conversation as cards, each with one line of comment built
 * only from verified data: the eligibility status, the intake, and the
 * fee measured against the user's own budget (same currency only).
 * No quality claims ("很强"), no invented figures, no probabilities.
 *
 * Quick replies: view results / show another batch / edit preferences.
 * Free text is really understood when it names a country or city that
 * appears in the verified recommendations — the list is re-filtered
 * for real. Anything else gets an honest "I didn't understand" plus
 * the buttons again; the pet never pretends to understand.
 *
 * Filtering here is a view only: the full evaluated list is still what
 * "查看我的结果" carries to the results page.
 */

const BATCH_SIZE = 3;

export function RecChat({
  recs, recLoading, programs, onViewResults, onEditPrefs,
}: {
  recs: MatchResult[] | null;
  recLoading: boolean;
  programs: Program[];
  onViewResults: () => void;
  onEditPrefs: () => void;
}) {
  const { t, tf, locale, profile } = useApp();
  const [batch, setBatch] = useState(0);
  const [filter, setFilter] = useState<{ country?: string; city?: string } | null>(null);
  const [input, setInput] = useState('');
  const [reply, setReply] = useState<{ key: string; vars?: Record<string, string | number> } | null>(null);
  const [mood, setMood] = useState<PetMood>('celebrate');
  /** Model answers to free-text questions (the country/city fast path
   * below stays local — it really re-filters). A template-only reply
   * is never shown as an answer: the turn is stored as offline. */
  const [aiTurns, setAiTurns] = useState<{
    question: string; reply: ChatReply | null; replyLocale: Locale | null; offline: boolean;
  }[]>([]);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiOffline, setAiOffline] = useState(false);
  /** The backend is being woken (a retry is in flight after the first
   * attempt failed): show the waking line, not the offline line. */
  const [waking, setWaking] = useState(false);
  /** The last free-text message, kept so the retry action can re-send
   * it instead of dropping the user's words. */
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);

  /** Locale change: re-fetch model answers in the new locale. A
   * failed or template-only re-fetch marks the turn offline instead
   * of showing stale text. */
  useEffect(() => {
    aiTurns.forEach((turn, i) => {
      if (!turn.reply || turn.replyLocale === locale) return;
      fetchJson<ChatReply>('/api/assistant/chat', {
        method: 'POST',
        body: JSON.stringify({ message: turn.question, locale }),
      }).then((fresh) => {
        if (!isModelReply(fresh)) {
          setAiOffline(true);
          setAiTurns((prev) => prev.map((x, j) => (j === i ? { ...x, reply: null, replyLocale: null, offline: true } : x)));
          return;
        }
        setAiTurns((prev) => prev.map((x, j) => (j === i ? { ...x, reply: fresh, replyLocale: locale, offline: false } : x)));
      }).catch(() => {
        setAiOffline(true);
        setAiTurns((prev) => prev.map((x, j) => (j === i ? { ...x, reply: null, replyLocale: null, offline: true } : x)));
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);

  const filtered = (recs ?? []).filter((r) => {
    const p = programs.find((x) => x.id === r.programId);
    if (!p) return false;
    if (filter?.country && p.country !== filter.country) return false;
    if (filter?.city && (p.city ?? '').toLowerCase() !== filter.city.toLowerCase()) return false;
    return true;
  });
  const batches = Math.max(1, Math.ceil(filtered.length / BATCH_SIZE));
  const shown = filtered.slice(batch * BATCH_SIZE, batch * BATCH_SIZE + BATCH_SIZE);

  /** One line of pet comment per programme — status + fee vs the user's
   * own budget, all from verified data. Currency is compared only when
   * it matches the budget currency; otherwise the fee is just stated. */
  const comment = (r: MatchResult, p: Program): string => {
    const statusKey = r.eligibilitySummary === 'MET' ? 'wizard.recChatMet'
      : r.eligibilitySummary === 'PARTIAL_UNKNOWN' ? 'wizard.recChatPartial' : 'wizard.recChatNotMet';
    const parts = [t(statusKey)];
    const budget = typeof profile.budget === 'number' ? profile.budget : null;
    const fee = budget !== null
      ? p.feeItems.find((f) => f.currency === (profile.budgetCurrency ?? '')) ?? p.feeItems[0]
      : p.feeItems[0];
    if (fee) {
      const feeText = formatFeeItem(fee, t, locale);
      if (budget !== null && fee.currency === (profile.budgetCurrency ?? '')) {
        parts.push(tf(fee.amount > budget ? 'wizard.recChatFeeAbove' : 'wizard.recChatFeeWithin', { fee: feeText }));
      } else {
        parts.push(tf('wizard.recChatFee', { fee: feeText }));
      }
    }
    parts.push(tf('wizard.recChatIntake', { intake: formatIntake(p, t) }));
    // Round 6: when the climate preference conflicts with this city's
    // climate, say so honestly — the programme stays in the list, just
    // ranked lower by the wizard sort.
    if (r.preferenceFit === 'conflict' && p.city) {
      parts.push(tf('wizard.recChatClimateConflict', { city: p.city, climate: climateLabel(profile.prefClimate, t) }));
    }
    return parts.join(' ');
  };

  /** A real question for the model, with the earlier model turns as
   * history. The full sentence is sent — never just the country/city
   * keyword — so the reply can acknowledge the user's reason. A
   * template-only reply is never shown as an answer: the turn is
   * stored as offline instead. */
  const askModel = async (text: string) => {
    setAiBusy(true);
    setWaking(false);
    setMood('think');
    const requestLocale = locale;
    const history: ChatHistoryTurn[] = [];
    for (const turn of aiTurns) {
      if (!turn.reply || !isModelReply(turn.reply)) continue;
      history.push({ role: 'user', content: turn.question });
      history.push({ role: 'assistant', content: turn.reply.lines.join(' ') });
    }
    try {
      const r = await fetchJsonPatient<ChatReply>('/api/assistant/chat', {
        method: 'POST',
        body: JSON.stringify({ message: text, locale: requestLocale, history: history.slice(-6) }),
      }, { onRetry: () => setWaking(true) });
      setWaking(false);
      if (!isModelReply(r)) {
        setAiOffline(true);
        setAiTurns((prev) => [...prev, { question: text, reply: null, replyLocale: null, offline: true }]);
        setMood('empathise');
        return;
      }
      setAiOffline(false);
      setAiTurns((prev) => [...prev, { question: text, reply: r, replyLocale: requestLocale, offline: false }]);
      setMood('celebrate');
    } catch {
      setWaking(false);
      setAiOffline(true);
      setAiTurns((prev) => [...prev, { question: text, reply: null, replyLocale: null, offline: true }]);
      setMood('empathise');
    } finally {
      setAiBusy(false);
    }
  };

  /** Free text: naming a country or a city really re-filters (fast
   * path, unchanged) — AND the full sentence still goes to the model
   * for a conversational reply that acknowledges the reason (round 7,
   * Fix 2: never just show the template "已按X筛选" and drop the
   * reason). Anything else is a question for the real model, with the
   * earlier model turns as history. If the model is offline, the
   * template reply stays and the offline line shows. */
  const onSend = async () => {
    const text = input.trim();
    if (!text || aiBusy) return;
    setInput('');
    setLastQuestion(text);
    const lower = text.toLowerCase();
    // Country? Match the localised name, the English name, or the code
    // of any country present in the verified recommendations.
    const countries = [...new Set((recs ?? []).map((r) => programs.find((x) => x.id === r.programId)?.country).filter((c): c is string => !!c))];
    for (const code of countries) {
      const names = [
        t(`country.${code}`),
        (enMessages as Record<string, string>)[`country.${code}`] ?? '',
        code,
      ].map((n) => n.toLowerCase()).filter(Boolean);
      if (names.some((n) => lower.includes(n))) {
        setFilter({ country: code });
        setBatch(0);
        setReply({ key: 'wizard.recChatFilteredCountry', vars: { country: t(`country.${code}`) } });
        setMood('celebrate');
        await askModel(text);
        return;
      }
    }
    // City? Match any city present in the verified recommendations.
    const cities = [...new Set((recs ?? []).map((r) => programs.find((x) => x.id === r.programId)?.city).filter((c): c is string => !!c))];
    for (const city of cities) {
      if (lower.includes(city.toLowerCase())) {
        setFilter({ city });
        setBatch(0);
        setReply({ key: 'wizard.recChatFilteredCity', vars: { city } });
        setMood('celebrate');
        await askModel(text);
        return;
      }
    }
    // A real question: ask the model, grounded in the verified data.
    await askModel(text);
  };

  /** Retry the AI chat after an offline turn: re-sends the last
   * free-text message so the user's words are not dropped. */
  const retryAi = () => {
    if (!lastQuestion || aiBusy) return;
    setAiOffline(false);
    void askModel(lastQuestion);
  };

  const shownMood: PetMood = input.trim() ? 'think' : mood;

  return (
    <div>
      <div className="flex items-start gap-3">
        <span className="anim-pet-bob inline-flex shrink-0 rounded-full bg-teal/10 p-1">
          <CompassFace size={56} mood={shownMood} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-bold">{t('wizard.recChatTitle')}</h2>
          <p className="mt-1 text-sm text-navy/70">{t('wizard.recChatNote')}</p>
        </div>
      </div>

      <div className="mt-4 space-y-3 rounded-2xl bg-paper p-4" aria-live="polite">
        <div className="flex justify-start">
          <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5 anim-fade-up">
            <p>{t('wizard.recChatIntro')}</p>
          </div>
        </div>

        {recLoading && (
          <div className="flex justify-start">
            <div className="rounded-2xl bg-white px-4 py-3 text-navy/60 shadow-sm ring-1 ring-navy/5">{t('wizard.recommendLoading')}</div>
          </div>
        )}

        {!recLoading && recs !== null && recs.length === 0 && (
          <div className="flex justify-start">
            <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5">
              <p className="font-bold">{t('wizard.recommendEmpty')}</p>
              <p className="mt-1 text-sm text-navy/70">{t('wizard.recommendEmptyNote')}</p>
              <Link href="/rankings" className="btn-press mt-3 inline-block rounded-full bg-navy px-4 py-2 text-sm font-semibold text-white">{t('nav.rankings')}</Link>
            </div>
          </div>
        )}

        {!recLoading && shown.length > 0 && (
          <div className="space-y-3">
            {filter && (
              <div className="flex justify-start">
                <button type="button" onClick={() => { setFilter(null); setBatch(0); setReply(null); }}
                  className="btn-press rounded-full bg-amber/25 px-3 py-1.5 text-sm font-semibold text-navy">
                  ✕ {filter.country ? t(`country.${filter.country}`) : filter.city} · {t('wizard.recChatClearFilter')}
                </button>
              </div>
            )}
            {shown.map((r) => {
              const p = programs.find((x) => x.id === r.programId);
              if (!p) return null;
              const summaryLabel = r.eligibilitySummary === 'MET' ? t('wizard.recMet') : r.eligibilitySummary === 'PARTIAL_UNKNOWN' ? t('wizard.recPartial') : t('wizard.recNotMet');
              return (
                <div key={r.programId} className="anim-fade-up rounded-2xl bg-white p-4 shadow-sm ring-1 ring-navy/5">
                  <div className="flex items-start gap-3">
                    <span className="inline-flex shrink-0 rounded-full bg-teal/10 p-1">
                      <CompassFace size={36} mood="idle" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-navy/75">{comment(r, p)}</p>
                      <p className="mt-2 flex flex-wrap items-center gap-2">
                        <span className="font-bold">{displayProgramTitle(p, locale)}</span>
                        <StatusChip status={r.eligibilitySummary} label={summaryLabel} />
                      </p>
                      <p className="mt-1 text-sm text-navy/70">
                        {formatIntake(p, t)} · {p.feeItems.map((f) => formatFeeItem(f, t, locale)).join(', ')}
                      </p>
                      <Link href={`/programs/${p.id}`} className="btn-press mt-2 inline-block rounded-full border border-navy/30 px-3 py-1.5 text-sm font-semibold">
                        {t('results.viewDetail')}
                      </Link>
                    </div>
                  </div>
                </div>
              );
            })}
            {batches > 1 && (
              <p className="text-center text-sm text-navy/60">
                {tf('wizard.recChatBatch', { n: batch + 1, total: batches })}
              </p>
            )}
          </div>
        )}

        {reply && (
          <div className="flex justify-start">
            <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5 anim-fade-up">
              <p>{reply.vars ? tf(reply.key, reply.vars) : t(reply.key)}</p>
            </div>
          </div>
        )}

        {/* Model answers to free-text questions (the country/city
            re-filter above stays local). A turn answered in another
            locale shows the thinking line until its re-fetch lands;
            an offline turn says so plainly instead of pretending. */}
        {aiTurns.map((turn, i) => (
          <div key={`ai-${i}`} className="space-y-3">
            <div className="flex justify-end">
              <div className="max-w-[90%] rounded-2xl bg-teal px-4 py-3 text-white">
                <p>{turn.question}</p>
              </div>
            </div>
            <div className="flex justify-start">
              <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5">
                {turn.reply && turn.replyLocale === locale ? (
                  <>
                    {turn.reply.lines.map((line, j) => (<p key={j} className={j > 0 ? 'mt-1' : ''}>{line}</p>))}
                    {turn.reply.evidence_url && (
                      <a href={turn.reply.evidence_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs font-semibold text-teal underline">
                        {t('pet.evidence')} ↗
                      </a>
                    )}
                  </>
                ) : turn.reply ? (
                  <p>{t('pet.thinking')}</p>
                ) : (
                  <p>{t('wizard.recChatOffline')}</p>
                )}
              </div>
            </div>
          </div>
        ))}
        {aiBusy && (
          <div className="flex justify-start">
            <div className="rounded-2xl bg-white px-4 py-3 text-navy/60 shadow-sm ring-1 ring-navy/5">{waking ? t('pet.waking') : t('pet.thinking')}</div>
          </div>
        )}
        {aiOffline && (
          <div className="space-y-2">
            <p className="text-xs text-navy/60">{t('wizard.recChatOffline')}</p>
            {lastQuestion && (
              <button type="button" onClick={retryAi} disabled={aiBusy}
                className="btn-press rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy disabled:opacity-40">
                {t('wizard.chatPrefRetry')}
              </button>
            )}
          </div>
        )}

        {!recLoading && recs !== null && recs.length > 0 && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={onViewResults} className="btn-press rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy">
                {t('wizard.finish')}
              </button>
              {filtered.length > BATCH_SIZE && (
                <button type="button" onClick={() => { setBatch((b) => (b + 1) % batches); setMood('celebrate'); }}
                  className="btn-press rounded-full border border-navy/30 bg-white px-4 py-2 text-sm font-semibold">
                  {t('wizard.recChatMore')}
                </button>
              )}
              <button type="button" onClick={onEditPrefs} className="btn-press rounded-full border border-navy/30 bg-white px-4 py-2 text-sm font-semibold">
                {t('wizard.recChatEditPrefs')}
              </button>
            </div>
            <div className="flex gap-2">
              <input value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') void onSend(); }}
                placeholder={t('wizard.recChatTypePlaceholder')}
                aria-label={t('wizard.recChatTypePlaceholder')}
                maxLength={200}
                disabled={aiBusy}
                className="min-w-0 flex-1 rounded-full border border-navy/25 bg-white px-3 py-2 text-sm disabled:opacity-50" />
              <button type="button" onClick={() => void onSend()} disabled={!input.trim() || aiBusy}
                className="btn-press shrink-0 rounded-full bg-teal px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">
                {t('wizard.chatSend')}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
