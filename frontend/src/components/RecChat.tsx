'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useApp, type Locale } from '../lib/store';
import { MatchResult, Program, type FeeItem, type Profile } from '../lib/types';
import { fetchJson, fetchJsonChat } from '../lib/api';
import { isModelReply, scopedProgrammeDisplay, scopedProgrammeMessage, stripProgrammeMarker, type ChatHistoryTurn, type ChatReply } from '../lib/chat';
import {
  catalogueCountInCountry, cityDisplayName, climateLabel, countryAlternatives,
  fieldDisplayLabel, missingPrefCountries, sortRecsByPreference, trackDisplayLabel,
} from '../lib/preferences';
import { useElapsed } from '../lib/useElapsed';
import { StatusChip } from './StatusChip';
import { CompassFace, type PetMood } from './CompassPet';
import { formatDuration, formatFeeItem, formatFeeItemWithLabel, formatIntake, pickFeeItem } from '../lib/format';
import { convertCurrency, FX_AS_OF } from '../lib/fx';
import { ruleName } from '../lib/ruleText';
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
 * fee measured against the user's own budget (same currency only),
 * with the approximate figure in the budget currency next to a
 * foreign-currency fee — the same format as the results pages.
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

/** Fee line with the approximate figure in the applicant's own currency
 * (Round 10, P1): the same format as the results pages — "学费：CHF
 * 4,380 每年（按参考汇率约合 GBP 4,018 · 2026-11-26）". Same-currency
 * fees and unconvertible currencies show no suffix, never a guess.
 * `withLabel` (default true) keeps the "学费：" label for the card's
 * fee row; the pet comment (comment()) passes false, because its
 * sentence templates (wizard.recChatFee / FeeAbove / FeeWithin)
 * already say "学费" — the labelled form there rendered the doubled
 * "学费 学费：CHF 4,380 每年…" (round 11, F5). */
function feeItemWithApprox(f: FeeItem, profile: Profile, t: (key: string) => string, tf: (key: string, vars: Record<string, string | number>) => string, locale: string, withLabel = true): string {
  const base = withLabel ? formatFeeItemWithLabel(f, t, locale) : formatFeeItem(f, t, locale);
  const budgetCurrency = profile.budgetCurrency ?? '';
  if (!budgetCurrency || f.currency === budgetCurrency) return base;
  const converted = convertCurrency(f.amount, f.currency, budgetCurrency);
  if (converted === null) return base;
  return `${base} (${tf('r9money.feeConverted', { currency: budgetCurrency, amount: Math.round(converted).toLocaleString(locale) })} · ${FX_AS_OF})`;
}

export function RecChat({
  recs, recLoading, recWaking, programs, onViewResults, onEditPrefs,
}: {
  recs: MatchResult[] | null;
  recLoading: boolean;
  /** The recommend match is still waking the backend (set by the
   * wizard page's onRetry): show the waking line, not a bare
   * loading spinner. */
  recWaking?: boolean;
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
    id: number; question: string; sent: string; reply: ChatReply | null; replyLocale: Locale | null; offline: boolean; pending: boolean;
  }[]>([]);
  /** `question` is the user-visible bubble text; `sent` is the exact
   * message POSTed to the backend. They differ when a one-tap chip
   * scopes the question to one programme (round 23): `sent` carries
   * the "Programme id <id>." marker the backend keys on, while
   * `question` is the clean display label (programme display name +
   * the question) — the internal id never reaches the bubble. A
   * retry or locale re-fetch re-sends `sent`, never the display
   * text, so the scoping survives both. */
  /** Monotonic turn ids, so an optimistic turn (and a retry of it) can
   * be updated in place when its reply lands (round 8). */
  const turnIdRef = useRef(0);
  const nextTurnId = () => { turnIdRef.current += 1; return turnIdRef.current; };
  const [aiBusy, setAiBusy] = useState(false);
  const [aiOffline, setAiOffline] = useState(false);
  /** The backend is being woken (a retry is in flight after the first
   * attempt failed): show the waking line, not the offline line. */
  const [waking, setWaking] = useState(false);
  /** The last free-text message, kept so the retry action can re-send
   * it instead of dropping the user's words. */
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);
  /** Round 9, R6: seconds spent waiting on the model / the match, for
   * the visible progress line — a bare "想想……" with no progress is
   * what the re-test flagged. */
  const aiElapsed = useElapsed(aiBusy);
  const recElapsed = useElapsed(recLoading);

  /** Locale change: re-fetch model answers in the new locale. A
   * failed or template-only re-fetch marks the turn offline instead
   * of showing stale text. */
  useEffect(() => {
    aiTurns.forEach((turn, i) => {
      if (!turn.reply || turn.replyLocale === locale) return;
      fetchJson<ChatReply>('/api/assistant/chat', {
        method: 'POST',
        // Round 21 (W3): scope the re-ask to the cards in view, so a
        // deictic "this programme" question is answered from those
        // programmes' verified facts instead of "查不到".
        // Round 22 (W2): send the wizard track too, so an
        // undergraduate profile can never match an MSc programme.
        // Round 23: re-send the turn's `sent` message (with the
        // "Programme id" marker when a chip scoped it), never the
        // display label — the re-fetch must stay scoped to the same
        // programme the user tapped.
        body: JSON.stringify({ message: turn.sent ?? turn.question, locale, program_ids: shown.map((r) => r.programId), track: profile.track ? profile.track : undefined }),
      }).then((fresh) => {
        if (!isModelReply(fresh)) {
          // Round 10: keep a template re-fetch as an offline turn instead
          // of dropping the answer.
          setAiOffline(true);
          const hasLines = Array.isArray(fresh.lines) && fresh.lines.length > 0;
          setAiTurns((prev) => prev.map((x, j) => (j === i ? { ...x, reply: hasLines ? fresh : null, replyLocale: hasLines ? locale : null, offline: true } : x)));
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

  /** Round 9, R1: the list is ordered preference-first (preferred
   * countries first, then eligibility) — the wizard page sorts the
   * same way, and this re-sort keeps RecChat correct even when recs
   * arrive in backend order. Eligibility-first used to put UCL /
   * Imperial / Peking / Tsinghua / MIT in both batches while the five
   * verified Swiss UG programmes sat buried mid-list. */
  const orderedRecs = sortRecsByPreference(recs ?? [], programs, profile);
  const filtered = orderedRecs.filter((r) => {
    const p = programs.find((x) => x.id === r.programId);
    if (!p) return false;
    if (filter?.country && p.country !== filter.country) return false;
    if (filter?.city && (p.city ?? '').toLowerCase() !== filter.city.toLowerCase()) return false;
    return true;
  });
  const batches = Math.max(1, Math.ceil(filtered.length / BATCH_SIZE));
  const shown = filtered.slice(batch * BATCH_SIZE, batch * BATCH_SIZE + BATCH_SIZE);

  /** Round 8 (Switzerland honesty): a chosen country with no
   * programme in the recommendation set is explained, never silently
   * zero — with the closest verified alternatives from the full
   * catalogue (same track first, then same field). Programmes that
   * arrive later (Worker E) flow through automatically, because the
   * notice is computed from the live lists, not hardcoded. */
  const recPrograms = (recs ?? []).map((r) => programs.find((x) => x.id === r.programId)).filter((p): p is Program => !!p);
  const missingCountries = missingPrefCountries(profile, recPrograms);

  /** One line of pet comment per programme — built only from verified
   * data, and different for every card: status, city + localised
   * duration, the residency-aware labelled fee against the user's own
   * budget (same currency only — an unknown fee is never called
   * within/above budget), the intake against the planned year, and
   * the rule names when something is not met. No quality claims
   * ("很强"), no invented figures, no probabilities. */
  const comment = (r: MatchResult, p: Program): string => {
    const statusKey = r.eligibilitySummary === 'MET' ? 'wizard.recChatMet'
      : r.eligibilitySummary === 'PARTIAL_UNKNOWN' ? 'wizard.recChatPartial' : 'wizard.recChatNotMet';
    const parts = [t(statusKey)];
    const cityName = p.city ? cityDisplayName(p.city, t) : '';
    const duration = formatDuration(p, t, locale);
    if (cityName || duration) parts.push([cityName, duration].filter(Boolean).join(' · '));
    const feeItem = pickFeeItem(p, profile);
    if (feeItem) {
      // Round 11, F5: label-free here — the recChatFee* templates
      // already say "学费", so the labelled form doubled it.
      const feeText = feeItemWithApprox(feeItem, profile, t, tf, locale, false);
      const budget = typeof profile.budget === 'number' ? profile.budget : null;
      if (budget !== null && feeItem.amount !== null && feeItem.currency === (profile.budgetCurrency ?? '')) {
        parts.push(tf(feeItem.amount > budget ? 'wizard.recChatFeeAbove' : 'wizard.recChatFeeWithin', { fee: feeText }));
      } else {
        parts.push(tf('wizard.recChatFee', { fee: feeText }));
      }
    }
    const intakeLabel = formatIntake(p, t, locale);
    if (profile.intakeYear && p.intakeYear && p.intakeYear !== profile.intakeYear) {
      parts.push(tf('wizard.recChatIntakePlanned', { intake: intakeLabel, year: profile.intakeYear }));
    } else {
      parts.push(tf('wizard.recChatIntake', { intake: intakeLabel }));
    }
    const blockers = (r.ruleResults ?? []).filter((rule) => rule.status === 'NOT_MET').map((rule) => ruleName(rule.ruleId, t));
    if (blockers.length) parts.push(blockers.join('、'));
    // Round 6: when the climate preference conflicts with this city's
    // climate, say so honestly — the programme stays in the list, just
    // ranked lower by the wizard sort.
    if (r.preferenceFit === 'conflict' && p.city) {
      parts.push(tf('wizard.recChatClimateConflict', { city: cityDisplayName(p.city, t), climate: climateLabel(profile.prefClimate, t) }));
    }
    return parts.join(' ');
  };

  /** A real question for the model, with the earlier model turns as
   * history. The full sentence is sent — never just the country/city
   * keyword — so the reply can acknowledge the user's reason. A
   * template-only reply is never shown as an answer: the turn is
   * stored as offline instead. Round 8: the turn is pushed
   * optimistically first, so the user's question shows at once; a
   * retry re-sends by updating the same turn (`existingId`), not by
   * appending a duplicate. Round 23: `text` is the DISPLAY text
   * (what the bubble shows); `sentOverride` is the exact message
   * POSTed to the backend when it differs — a chip tap passes the
   * "Programme id <id>." marker here, so the backend stays scoped
   * while the bubble stays clean. A retry (`existingId`) re-sends
   * the stored `sent`, so the scoping survives a retry too. */
  const askModel = async (text: string, existingId?: number, sentOverride?: string) => {
    setAiBusy(true);
    setWaking(false);
    setMood('think');
    const requestLocale = locale;
    const turnId = existingId ?? nextTurnId();
    const existing = existingId !== undefined ? aiTurns.find((x) => x.id === existingId) : undefined;
    const sent = sentOverride ?? existing?.sent ?? text;
    if (existingId === undefined) {
      setAiTurns((prev) => [...prev, { id: turnId, question: text, sent, reply: null, replyLocale: null, offline: false, pending: true }]);
    } else {
      setAiTurns((prev) => prev.map((x) => (x.id === turnId ? { ...x, pending: true, offline: false } : x)));
    }
    const history: ChatHistoryTurn[] = [];
    for (const turn of aiTurns) {
      if (!turn.reply || !isModelReply(turn.reply)) continue;
      history.push({ role: 'user', content: turn.sent ?? turn.question });
      history.push({ role: 'assistant', content: turn.reply.lines.join(' ') });
    }
    try {
      const r = await fetchJsonChat<ChatReply>('/api/assistant/chat', {
        method: 'POST',
        // Round 21 (W3): scope the question to the cards in view —
        // the user is asking about one of these. Without it a
        // deictic "this programme" / "这个专业" question matched
        // nothing and got the blanket "查不到", while the same
        // question on the programme detail page (which carries the
        // "Programme id" marker) got the verified fee answer.
        // Round 22 (W2): send the wizard track too, so an
        // undergraduate profile can never match an MSc programme.
        // Round 23: send `sent` — the exact message, with the
        // "Programme id" marker when a chip scoped the question —
        // never the display label.
        body: JSON.stringify({ message: sent, locale: requestLocale, history: history.slice(-6), program_ids: shown.map((r) => r.programId), track: profile.track ? profile.track : undefined }),
      }, { onRetry: () => setWaking(true) });
      setWaking(false);
      if (!isModelReply(r)) {
        // Round 10: a template reply is a verified answer, not nothing —
        // store it as an offline turn (rendered with the offline line)
        // instead of discarding it, the same bug the pet had.
        setAiOffline(true);
        const hasLines = Array.isArray(r.lines) && r.lines.length > 0;
        setAiTurns((prev) => prev.map((x) => (x.id === turnId ? { ...x, reply: hasLines ? r : null, replyLocale: hasLines ? requestLocale : null, offline: true, pending: false } : x)));
        setMood('empathise');
        return;
      }
      setAiOffline(false);
      setAiTurns((prev) => prev.map((x) => (x.id === turnId ? { ...x, reply: r, replyLocale: requestLocale, offline: false, pending: false } : x)));
      setMood('celebrate');
    } catch {
      setWaking(false);
      setAiOffline(true);
      setAiTurns((prev) => prev.map((x) => (x.id === turnId ? { ...x, reply: null, replyLocale: null, offline: true, pending: false } : x)));
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
        setReply({ key: 'wizard.recChatFilteredCity', vars: { city: cityDisplayName(city, t) } });
        setMood('celebrate');
        await askModel(text);
        return;
      }
    }
    // A real question: ask the model, grounded in the verified data.
    await askModel(text);
  };

  /** Retry the AI chat after an offline turn: re-sends the last
   * offline turn's own question, updating that turn in place (no
   * duplicate bubble); falls back to the last free-text message when
   * there is no offline turn to retry. */
  const retryAi = () => {
    if (aiBusy) return;
    const lastOffline = [...aiTurns].reverse().find((x) => x.offline);
    setAiOffline(false);
    if (lastOffline) {
      void askModel(lastOffline.question, lastOffline.id);
      return;
    }
    if (!lastQuestion) return;
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
            {/* Waiting bubble: alive treatment via the global .think-dots /
                .think-shimmer classes (globals.css worker) — visuals only. */}
            <div className="think-shimmer rounded-2xl bg-white px-4 py-3 text-navy/60 shadow-sm ring-1 ring-navy/5">
              <span>{recWaking ? tf('pet.wakingElapsed', { seconds: recElapsed }) : tf('r9chat.matchingElapsed', { seconds: recElapsed })}</span>
              <span className="think-dots ms-2" aria-hidden="true"><span /><span /><span /></span>
            </div>
          </div>
        )}

        {/* Round 8 (Switzerland honesty): a chosen country with no
            programme in the recommendations is explained with the
            closest verified alternatives — never a silent zero, and
            the non-Swiss cards below are not presented as if they
            matched the Switzerland preference. */}
        {!recLoading && recs !== null && missingCountries.length > 0 && missingCountries.map((code) => {
          const alts = countryAlternatives(code, profile, programs);
          const catalogueCount = catalogueCountInCountry(code, programs);
          const level = trackDisplayLabel(profile.track, t);
          const field = fieldDisplayLabel(profile.field, t);
          const altList = [...alts.sameTrack, ...alts.sameField];
          return (
            <div key={`missing-${code}`} className="flex justify-start">
              <div className="max-w-[90%] rounded-2xl bg-amber/15 px-4 py-3 shadow-sm ring-1 ring-amber/40 anim-fade-up">
                <p className="font-bold">{tf('results.noCountryTitle', { country: t(`country.${code}`) })}</p>
                {/* Round 18: the note needs {total} in all 6 locales —
                    the old call never passed it, so the raw "{total}"
                    reached the user. Total = the evaluated list for
                    this field/track, the same number the sentence
                    counts ("已为你评估的 {total} 个课程中"). */}
                <p className="mt-1 text-sm text-navy/75">{tf('results.noCountryNote', { country: t(`country.${code}`), level, field, total: (recs ?? []).length })}</p>
                {catalogueCount > 0 ? (
                  <>
                    <p className="mt-2 text-sm">{tf('results.noCountryCatalogue', { count: catalogueCount, country: t(`country.${code}`), level })}</p>
                    <ul className="mt-1 space-y-1">
                      {altList.map((p) => {
                        const levelLabel = trackDisplayLabel(p.degreeLevel, t);
                        return (
                          <li key={p.id}>
                            <Link href={`/programs/${p.id}`} className="text-sm font-semibold text-teal underline">
                              {displayProgramTitle(p, locale)}{levelLabel ? ` · ${levelLabel}` : ''}
                            </Link>
                          </li>
                        );
                      })}
                    </ul>
                  </>
                ) : (
                  /* Round 18: noCountryNone needs {country} in all 6
                     locales — the old t() call never interpolated, so
                     the raw "{country}" reached the user whenever the
                     verified catalogue held no programme in that
                     country at all. */
                  <p className="mt-2 text-sm text-navy/75">{tf('results.noCountryNone', { country: t(`country.${code}`) })}</p>
                )}
              </div>
            </div>
          );
        })}

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
                  ✕ {filter.country ? t(`country.${filter.country}`) : filter.city ? cityDisplayName(filter.city, t) : ''} · {t('wizard.recChatClearFilter')}
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
                        {formatIntake(p, t, locale)} · {p.feeItems.map((f) => feeItemWithApprox(f, profile, t, tf, locale)).join(', ')}
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
            <p className="text-center text-sm text-navy/60">
              {/* Round 9, R8a: the vars must match the strings' own
                  placeholders ({count} / {total}) — the old call passed
                  {shown, total}, so "本方向共 {count} 个已评估推荐"
                  rendered with the raw {count} in it. */}
              {tf(filter ? 'wizard.recChatCountFiltered' : 'wizard.recChatCount', { count: filtered.length, total: (recs ?? []).length })}
            </p>
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
                {/* Round 23: render-side guard — a leading "Programme
                    id" marker is stripped, so an internal id can
                    never reach the user bubble even if a turn was
                    stored mis-wired. */}
                <p>{stripProgrammeMarker(turn.question)}</p>
              </div>
            </div>
            <div className="flex justify-start">
              <div className={`${turn.pending ? 'think-shimmer ' : ''}max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5`}>
                {turn.pending ? (
                  <p className="flex items-center gap-2">
                    <span>{waking ? tf('pet.wakingElapsed', { seconds: aiElapsed }) : tf('r9chat.thinkingElapsed', { seconds: aiElapsed })}</span>
                    <span className="think-dots" aria-hidden="true"><span /><span /><span /></span>
                  </p>
                ) : turn.reply && turn.replyLocale === locale ? (
                  <>
                    {turn.offline && <p className="mb-1 text-xs font-semibold text-navy/60">{t('wizard.recChatOffline')}</p>}
                    {turn.reply.lines.map((line, j) => (<p key={j} className={j > 0 ? 'mt-1' : ''}>{line}</p>))}
                    {turn.reply.evidence_url && (
                      <a href={turn.reply.evidence_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs font-semibold text-teal underline">
                        {t('pet.evidence')} ↗
                      </a>
                    )}
                    {/* Round 22 (W2): a genuinely ambiguous "which
                        one" reply becomes one tap, not a free-text
                        English-name quiz — chips name the visible
                        programmes, and tapping one re-asks the same
                        question scoped to that programme. Round 23:
                        the scope travels ONLY in the sent message
                        ("Programme id <id>." marker) — the bubble
                        shows the clean display label (programme
                        display name + the question), never the raw
                        internal id (re-test task 17). Only on the
                        latest turn: the chips name the batch in view
                        now. */}
                    {i === aiTurns.length - 1 && (turn.reply.lines.join(' ').includes('哪一门') || turn.reply.lines.join(' ').includes('Which one do you mean')) && (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {shown.map((r) => {
                          const p = programs.find((x) => x.id === r.programId);
                          if (!p) return null;
                          return (
                            <button key={r.programId} type="button" disabled={aiBusy}
                              onClick={() => void askModel(
                                scopedProgrammeDisplay(displayProgramTitle(p, locale), turn.question, locale),
                                undefined,
                                scopedProgrammeMessage(p.id, turn.question),
                              )}
                              className="btn-press rounded-full border border-teal/50 bg-teal/10 px-3 py-1.5 text-left text-xs font-semibold text-navy disabled:opacity-40">
                              {displayProgramTitle(p, locale)}
                            </button>
                          );
                        })}
                      </div>
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
        {aiBusy && !aiTurns.some((x) => x.pending) && (
          <div className="flex justify-start">
            {/* Waiting bubble only: same alive treatment as the pending turn. */}
            <div className="think-shimmer rounded-2xl bg-white px-4 py-3 text-navy/60 shadow-sm ring-1 ring-navy/5">
              <span>{waking ? tf('pet.wakingElapsed', { seconds: aiElapsed }) : tf('r9chat.thinkingElapsed', { seconds: aiElapsed })}</span>
              <span className="think-dots ms-2" aria-hidden="true"><span /><span /><span /></span>
            </div>
          </div>
        )}
        {aiOffline && (
          <div className="space-y-2">
            <p className="text-xs text-navy/60">{t('wizard.recChatOffline')}</p>
            {/* Round 23: a chip-scoped turn never sets lastQuestion
                (it is free text only), so the retry button must also
                show when an offline turn exists — retryAi re-sends
                that turn's stored `sent` message, marker included. */}
            {(lastQuestion || aiTurns.some((x) => x.offline)) && (
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
              {/* Round 13: this used to be a <button onClick={onViewResults}>
                  whose router.push('/results') never landed in the
                  re-test (click stayed on /wizard, only scrolled to
                  top) — the top nav "结果" Link worked, so this is a
                  real Link to /results now, with the id sync kept as
                  its onClick. The try/catch means a failure in the
                  sync can never swallow the navigation itself. */}
              <Link href="/results" onClick={() => { try { onViewResults(); } catch { /* the Link still navigates */ } }} className="btn-press rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy">
                {t('wizard.finish')}
              </Link>
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
