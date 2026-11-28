/**
 * Shared helpers for the three model-wired chats (round 6, Job A):
 * the desktop pet (CompassPet), the preference chat (PrefChat) and the
 * recommend chat (RecChat).
 *
 * All three talk to the same two endpoints through the Next.js proxy
 * (frontend/next.config.js rewrites /api/:path* to the backend's
 * /api/v1/:path*):
 * - POST /assistant/chat — grounded free-text chat. ai_status is
 *   "available" ONLY when a validated model output was actually used;
 *   anything else is the template fallback and must NEVER be shown as
 *   an AI answer (see the honest-offline rule in each component).
 * - POST /profile/parse — free text -> StudentProfile-shaped dict.
 *   NEVER applies a profile; the caller applies only after the user
 *   confirms.
 * - POST /assistant/pref-chat (round 7) — the model-led preference
 *   conversation: one user message + the already-known preferences +
 *   history in, model lines + server-validated `extracted` prefs +
 *   the single most useful still-missing preference (`next_question`)
 *   out. `extracted` holds ONLY what the server understood from THIS
 *   message; nothing is applied until the user confirms it.
 *
 * No programme data, fee, requirement or opinion is invented here:
 * next-step links are derived from the reply's source ids (never from
 * model text), and the suggestion message is built only from the
 * user's own guided answers (degree, country, budget band).
 */

import type { Profile } from './types';
import { joinList } from './format';
import { choiceLabelFor, choiceRefsForLabel } from './preferences';

/** One /assistant/chat reply. */
export interface ChatReply {
  lines: string[];
  evidence_url?: string | null;
  ai_status?: string;
  model?: string | null;
  sources?: { id: string; url: string | null; title: string }[];
  /** Round 24 (W1): the programme ids behind an ambiguous reply
   * ("I found 2 matching programmes…") — the caller carries them
   * forward as the scope of the level follow-up. Absent unless the
   * reply is ambiguous. */
  candidates?: string[];
}

/** One /profile/parse reply (StudentProfile-shaped, parse only). */
export interface ParseReply {
  parsed_profile: Record<string, unknown>;
  unparsed: string[];
  confidence: Record<string, string>;
  confirmation_required: boolean;
  parser?: string;
  ai_status?: string;
  note?: string;
}

/** One history turn for /assistant/chat (max 6 are kept server-side). */
export interface ChatHistoryTurn {
  role: 'user' | 'assistant';
  content: string;
}

/** True only when the backend actually used a validated model output
 * for this reply. Anything else (template fallback, or no status at
 * all) is offline content, never an AI answer. */
export function isModelReply(reply: ChatReply | null | undefined): boolean {
  return !!reply && reply.ai_status === 'available';
}

/**
 * Next-step links derived from a chat reply's source ids — never from
 * model text. Programme pages come from `src:<program-id>:` ids,
 * institution pages from `rank:` / `profile:` / `site:` ids (see
 * backend/ai/grounding.py for the id formats).
 */
export function deriveChatLinks(
  sources: ChatReply['sources'],
): { program?: string | null; institution?: string | null } {
  let program: string | null = null;
  let institution: string | null = null;
  for (const s of sources ?? []) {
    if (!program) {
      const m = /^src:([^:]+):/.exec(s.id);
      if (m) program = `/programs/${m[1]}`;
    }
    if (!institution) {
      const m = /^(?:rank|profile):[^:]+:(.+)$/.exec(s.id)
        ?? /^site:(.+)$/.exec(s.id);
      if (m) institution = `/institutions/${m[1]}`;
    }
    if (program && institution) break;
  }
  return { program, institution };
}

const QUESTION_MARKERS = [
  '?', '？', '吗', '么', '哪', '什么', '怎么', '为什么', '为何',
  '是否', '能不能', '可以吗', '有吗', '推荐', '建议', '怎样', '如何',
  '多久', '多少',
];
const QUESTION_WORDS_EN =
  /\b(what|which|how|why|when|where|is there|are there|any|recommend|suggest|do you|can you|could you|should i|would you)\b/i;

/**
 * True when free text is a question (or a request for a recommendation),
 * not an answer to the question being asked. A question goes to the
 * model; an answer goes to /profile/parse + the local mapping.
 */
export function looksLikeQuestion(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  if (QUESTION_MARKERS.some((m) => t.includes(m))) return true;
  return QUESTION_WORDS_EN.test(t);
}

export type DegreeLevel = 'undergraduate' | 'taught_masters';
export type BudgetBand = 'low' | 'mid' | 'high';

export interface BudgetCeiling {
  currency: string;
  amount: number;
  /** 'per year' for undergraduate bands, 'total' for taught-masters totals. */
  period: 'per year' | 'total';
}

/**
 * The guided 3-question flow's suggestion as one constructed message
 * for /assistant/chat: degree + country (English name for the model to
 * read, plus the explicit country-code marker the backend's retrieval
 * keys on) + budget band + ceiling when the band has one. Built only
 * from the user's own guided answers — no programme is named, so the
 * model suggests from the verified evidence the backend retrieves.
 */
export function suggestMessage(
  degree: DegreeLevel,
  countryCode: string,
  countryNameEn: string,
  band: BudgetBand,
  ceiling: BudgetCeiling | null,
): string {
  const level = degree === 'undergraduate' ? 'undergraduate' : 'taught masters';
  const base = `Recommend a ${level} programme in ${countryNameEn} ` +
    `(country code ${countryCode}). Budget band: ${band}.`;
  if (!ceiling) return base;
  return `${base} Budget: under ${ceiling.currency} ` +
    `${ceiling.amount.toLocaleString('en-US')} ${ceiling.period}.`;
}

// --- Scoped programme question (round 23) ---------------------------------
// A one-tap chip that scopes a question to ONE programme must send the
// internal id to the backend but NEVER show it to the user (re-test
// task 17: tapping the ETH chip rendered the user bubble as
// "Programme id eth-cs-bsc-2027. 这个专业学费多少？").
//
// - `scopedProgrammeMessage` is the exact string POSTed to
//   /assistant/chat: the backend keys its programme-id intent on the
//   "Programme id <id>." marker (backend/app/router_chat.py
//   program_ids), so the marker stays in the SENT message.
// - `scopedProgrammeDisplay` is the bubble text: the programme's
//   display name plus the user's question, no id. The separator is
//   locale-shaped (full-width colon in Chinese locales, ": "
//   elsewhere) so the label reads naturally in both.
// - `stripProgrammeMarker` is the render-side guard: a leading
//   marker is stripped from anything shown in a user bubble, so even
//   a stale or mis-wired turn can never leak an internal id. The
//   pattern is anchored to the start and requires the trailing ". ",
//   so a user's own words mentioning a programme id mid-sentence are
//   left alone.
export function scopedProgrammeMessage(programId: string, question: string): string {
  return `Programme id ${programId}. ${question}`;
}

export function scopedProgrammeDisplay(programTitle: string, question: string, locale = 'en'): string {
  return `${programTitle}${locale.startsWith('zh') ? '：' : ': '}${question}`;
}

export function stripProgrammeMarker(text: string): string {
  return text.replace(/^Programme id [A-Za-z0-9_-]+\.\s*/, '');
}

// --- Programme disambiguation (round 24, W1) -------------------------------
// The pet's free-text fee flow used to dead-end on the backend's
// ambiguous reply ("I found 2 matching programmes… Tell me
// undergraduate or masters."): the reply carried no programme ids,
// the "Undergraduate" chip was the onboarding Q1 chip (tapping it
// jumped to country selection), and typing "undergraduate" sent a
// bare level word the backend honestly answered with unknown —
// while the same fee answers directly in wizard step 8. The backend
// is stateless per request, so the follow-up carries the pending
// context in the request itself: the original question + the level
// word as the message, scoped to the matched ids as program_ids.
// These helpers own the frontend half of that contract; CompassPet
// renders from them. Nothing here invents data: the candidates come
// from the reply, the level words mirror the backend's own
// _UG_WORDS/_TM_WORDS (ai/assistant.py).

/** Level words, mirroring backend ai/assistant.py _UG_WORDS /
 * _TM_WORDS — undergraduate checked first, exactly as the backend
 * filters. "研究生" is a masters word (a postgraduate student). */
const DISAMBIG_UG_WORDS = ['本科', '学士', 'undergrad', 'bsc', 'beng', 'bcomp', 'bachelor'];
const DISAMBIG_TM_WORDS = ['硕士', '研究生', 'master', 'msc', 'mcomp', 'msai', 'postgrad', 'taught'];

/** Degree level a free-text reply names, or null when it names none.
 * Substring match on the lowercased text, the same rule the backend
 * uses — so the frontend and the backend agree on what counts as a
 * level answer ("Undergraduate", "masters", "本科", "硕士",
 * "研究生"). A word that names no level ("grad", "hmm") is null:
 * the caller re-asks instead of sending a bare word the backend
 * would answer with unknown. */
export function detectLevelWord(text: string): DegreeLevel | null {
  const lower = (text ?? '').toLowerCase();
  if (DISAMBIG_UG_WORDS.some((w) => lower.includes(w))) return 'undergraduate';
  if (DISAMBIG_TM_WORDS.some((w) => lower.includes(w))) return 'taught_masters';
  return null;
}

/** One chat turn, as far as the disambiguation derivation needs it. */
export interface DisambiguationTurnLike {
  kind: string;
  message?: string;
  reply?: ChatReply | null;
  replyLocale?: string | null;
}

/** A live level disambiguation: the ambiguous reply's candidates +
 * the original question it asked about. */
export interface PendingDisambiguation {
  /** The matched programme ids, in the backend's order. */
  candidates: string[];
  /** The original question, verbatim (the ask turn's message). */
  question: string;
  /** The ambiguous reply itself (re-used for the local re-ask). */
  reply: ChatReply;
  /** The locale the ambiguous reply was answered in. */
  replyLocale: string | null;
}

/**
 * The pending disambiguation, derived from the turns alone — no
 * extra state to go stale. It is the LAST ask/freeText turn, and it
 * is pending only when that turn is an ask whose reply still lists
 * 2+ candidates: any later turn ends it — a follow-up (whose reply
 * either answers the fee or asks again with fresh candidates), a
 * new question, or a re-ask turn (which carries the same candidates
 * and keeps it live). Choice/prompt turns in between do not decide
 * anything; they cannot follow an ambiguous ask through the UI —
 * except a level-chip answer, which IS the follow-up: since round
 * 26 (W4) onChip stores it as a structured `choice` turn (step 0),
 * so a trailing choice ends the pending state instead of
 * resurrecting the level chips until the follow-up ask lands.
 */
export function pendingDisambiguation(
  turns: readonly DisambiguationTurnLike[],
): PendingDisambiguation | null {
  for (let i = turns.length - 1; i >= 0; i--) {
    const t = turns[i];
    if (t.kind !== 'ask' && t.kind !== 'freeText' && t.kind !== 'choice') continue;
    if (t.kind === 'ask' && t.reply
      && (t.reply.candidates?.length ?? 0) >= 2 && t.message) {
      return {
        candidates: [...(t.reply.candidates as string[])],
        question: t.message,
        reply: t.reply,
        replyLocale: t.replyLocale ?? null,
      };
    }
    return null;
  }
  return null;
}

/**
 * The distinct degree levels among the candidates, undergraduate
 * first (the Q1 chip order — never the backend's candidate order,
 * which lists MSc first for ETH). Unknown ids contribute nothing;
 * [] when no candidate resolves — the caller then falls back to
 * both level chips, since the backend still resolves the follow-up
 * from the message alone.
 */
export function disambiguationLevels(
  candidates: string[],
  programs: { id: string; degreeLevel?: string }[],
): DegreeLevel[] {
  const found = new Set<DegreeLevel>();
  for (const id of candidates) {
    const p = programs.find((x) => x.id === id);
    if (p?.degreeLevel === 'undergraduate' || p?.degreeLevel === 'taught_masters') {
      found.add(p.degreeLevel);
    }
  }
  return (['undergraduate', 'taught_masters'] as DegreeLevel[])
    .filter((l) => found.has(l));
}

/**
 * The exact message POSTed for a level follow-up: the ORIGINAL
 * question + the level word, so the backend's matcher (which already
 * answers "…Computer Science? undergraduate" with the BSc fee)
 * resolves it from the scoped programme. The word is the question's
 * own locale (本科/硕士 for zh-CN, undergraduate/masters otherwise)
 * — the backend recognises both word sets in any locale.
 */
export function disambiguationFollowupMessage(
  question: string,
  level: DegreeLevel,
  locale = 'en',
): string {
  const word = locale === 'zh-CN'
    ? (level === 'undergraduate' ? '本科' : '硕士')
    : (level === 'undergraduate' ? 'undergraduate' : 'masters');
  return `${question} ${word}`;
}

// --- Pref-chat contract (round 7) ------------------------------------------
// POST /api/assistant/pref-chat. The frontend calls it through the
// Next.js proxy; the backend serves it at /api/v1/assistant/pref-chat.
// `extracted` holds ONLY fields the server understood from THIS
// message (server-validated). `next_question` is the single most useful
// still-missing preference, or null when all 8 are known (done=true) —
// never a known one. When ai_status is "unavailable", extracted={} and
// next_question is the first missing preference computed
// deterministically; the caller must then fall back to the guided
// queue and never show the reply's lines as an AI answer.

export type PrefNextQuestion =
  | 'countries' | 'climate' | 'environment' | 'city'
  | 'afterGrad' | 'salary' | 'pressure' | 'teaching'
  | null;

/** The 8 preference questions, in the order the guided queue asks
 * them — also the deterministic order for "first missing". */
export const PREF_QUESTIONS: Exclude<PrefNextQuestion, null>[] = [
  'countries', 'climate', 'environment', 'city',
  'afterGrad', 'salary', 'pressure', 'teaching',
];

export interface PrefKnown {
  countries: string[];
  climate: 'warm' | 'cool' | 'four_seasons' | 'mild' | null;
  environment: 'big_city' | 'small_city' | 'campus' | 'quiet_town' | null;
  city: string | null;
  afterGrad: 'stay' | 'return_home' | 'hometown' | 'undecided' | null;
  salary: number | null;
  salaryCurrency: 'GBP' | 'SGD' | 'USD' | 'CHF' | null;
  pressure: 'low' | 'medium' | 'high' | null;
  teaching: 'lecture' | 'seminar' | 'hands_on' | null;
  note: string | null;
}

export interface PrefChatRequest {
  message: string;
  locale: string;
  known: PrefKnown;
  history: ChatHistoryTurn[];
}

export interface PrefExtracted {
  countries?: string[];
  climate?: PrefKnown['climate'];
  environment?: PrefKnown['environment'];
  city?: string;
  afterGrad?: PrefKnown['afterGrad'];
  salary?: { amount: number; currency: 'GBP' | 'SGD' | 'USD' | 'CHF' };
  pressure?: PrefKnown['pressure'];
  teaching?: PrefKnown['teaching'];
  note?: string;
}

export interface PrefChatReply {
  lines: string[];
  evidence_url?: string | null;
  ai_status?: string;
  model?: string | null;
  sources?: { id: string; url: string | null; title: string }[];
  extracted?: PrefExtracted;
  next_question?: PrefNextQuestion;
  done?: boolean;
  /** Round 14, P0: the WHY follow-up for the turn that just recorded
   * new countries (``{countries, note?}``) — present in the FIRST
   * reply of that turn, never gated on confirming the extraction.
   * Absent/null when no new country was recorded. */
  why_followup?: { countries: string[]; note?: string | null } | null;
  /** Round 28 D2: the structured climate evidence behind the
   * offline fallback's cities line — present ONLY on a fallback
   * (``ai_status === 'unavailable'``) result, and only when the
   * cities line was actually placed into ``lines[0]``. The frontend
   * re-renders the cities line + no-match sentence in the current
   * locale from these items (see ``prefFallbackLines.ts``); model
   * replies never carry them. Persisted whole with the reply:
   * `serializePrefChatState` / `parsePrefChatState` pass `reply`
   * through as one object, so no whitelist change was needed. */
  evidence_cities?: { city: string; climate: 'warm' | 'cool' | 'four_seasons' | 'mild'; count: number }[] | null;
  /** Round 28 D2: the wanted climate class for the fallback turn
   * (or null when none was stated/known). Pairs with
   * `evidence_cities`. */
  climate_wanted?: 'warm' | 'cool' | 'four_seasons' | 'mild' | null;
}

/** True only when the backend actually used a validated model output
 * for this pref-chat reply. Anything else is offline content. */
export function isModelPrefReply(reply: PrefChatReply | null | undefined): boolean {
  return !!reply && reply.ai_status === 'available';
}

const CLIMATES = ['warm', 'cool', 'four_seasons', 'mild'] as const;
const ENVIRONMENTS = ['big_city', 'small_city', 'campus', 'quiet_town'] as const;
const AFTER_GRADS = ['stay', 'return_home', 'hometown', 'undecided'] as const;
const PRESSURES = ['low', 'medium', 'high'] as const;
const TEACHINGS = ['lecture', 'seminar', 'hands_on'] as const;
const SALARY_CURRENCIES = ['GBP', 'SGD', 'USD', 'CHF'] as const;

/** The wizard Profile's preferences, reshaped into the pref-chat
 * `known` object. Only exact enum values are passed — free text in a
 * preference field is NOT passed as that enum (it would misread the
 * user's words); the countries note travels as `note` instead. */
export function knownFromProfile(p: Profile): PrefKnown {
  const pick = <T extends string>(v: string | undefined, allowed: readonly T[]): T | null =>
    (v && (allowed as readonly string[]).includes(v) ? (v as T) : null);
  return {
    countries: [...(p.prefCountries ?? [])],
    climate: pick(p.prefClimate, CLIMATES),
    environment: pick(p.prefEnvironment, ENVIRONMENTS),
    city: (p.prefCity ?? '').trim() || null,
    afterGrad: pick(p.prefAfterGrad, AFTER_GRADS),
    salary: typeof p.prefSalary === 'number' && !Number.isNaN(p.prefSalary) ? p.prefSalary : null,
    salaryCurrency: pick(p.prefSalaryCurrency, SALARY_CURRENCIES),
    pressure: pick(p.prefPressure, PRESSURES),
    teaching: pick(p.prefTeaching, TEACHINGS),
    note: (p.prefCountriesNote ?? '').trim() || null,
  };
}

/** How many of the 8 preferences are already known. */
export function countKnownPrefs(known: PrefKnown): number {
  let n = 0;
  if (known.countries.length > 0 || known.note) n += 1;
  if (known.climate) n += 1;
  if (known.environment) n += 1;
  if (known.city) n += 1;
  if (known.afterGrad) n += 1;
  if (known.salary !== null) n += 1;
  if (known.pressure) n += 1;
  if (known.teaching) n += 1;
  return n;
}

/** The first still-missing preference in deterministic order, or null
 * when all 8 are known. */
export function firstMissingPref(known: PrefKnown): PrefNextQuestion {
  if (known.countries.length === 0 && !known.note) return 'countries';
  if (!known.climate) return 'climate';
  if (!known.environment) return 'environment';
  if (!known.city) return 'city';
  if (!known.afterGrad) return 'afterGrad';
  if (known.salary === null) return 'salary';
  if (!known.pressure) return 'pressure';
  if (!known.teaching) return 'teaching';
  return null;
}

/** Round 27 W2: the guided queue's next position — the first
 * still-unanswered question at or after `from`, or
 * PREF_QUESTIONS.length when nothing is left (the queue is done).
 * The queue walks in QUESTIONS order but must never re-ask a
 * question the profile already answers: answers can arrive out of
 * order (a model turn preserved across the drop to guided mode, a
 * pending extraction confirmed while the queue sits elsewhere), so
 * advancing by a bare +1 re-asks known answers — re-test 21: after
 * the pressure answer the guided queue replayed from salary and
 * asked pressure (and teaching) again. `from` past the end, and a
 * fully-known set, both return PREF_QUESTIONS.length. */
export function nextMissingPrefIndex(known: PrefKnown, from: number): number {
  for (let i = Math.max(0, from); i < PREF_QUESTIONS.length; i++) {
    if (!isPrefKnown(PREF_QUESTIONS[i], known)) return i;
  }
  return PREF_QUESTIONS.length;
}

/** True when one preference question is answered in the known set. */
export function isPrefKnown(q: Exclude<PrefNextQuestion, null>, known: PrefKnown): boolean {
  switch (q) {
    case 'countries': return known.countries.length > 0 || !!known.note;
    case 'climate': return !!known.climate;
    case 'environment': return !!known.environment;
    case 'city': return !!known.city;
    case 'afterGrad': return !!known.afterGrad;
    case 'salary': return known.salary !== null;
    case 'pressure': return !!known.pressure;
    case 'teaching': return !!known.teaching;
  }
}

/** The next question to offer chips for: the server's answer when it
 * is still unanswered, else the first missing preference — and never
 * a skipped one. Null when nothing is left to ask. (Round 7: answers
 * in any order collect prefs without re-asking known ones.) */
export function effectiveNextPref(
  serverNext: PrefNextQuestion | undefined,
  known: PrefKnown,
  skipped: string[],
): PrefNextQuestion {
  const candidates = serverNext
    ? [serverNext, ...PREF_QUESTIONS.filter((q) => q !== serverNext)]
    : [...PREF_QUESTIONS];
  return candidates.find((q) => !isPrefKnown(q, known) && !skipped.includes(q)) ?? null;
}

/**
 * Map a server-validated `extracted` object onto the flat wizard
 * Profile — applied ONLY after the user confirms. Countries merge
 * with the ones already saved (never replace them); the note appends
 * to an existing note instead of overwriting the user's own words.
 * Returns null when there is nothing to apply.
 */
export function profilePatchFromExtracted(
  extracted: PrefExtracted,
  profile: Profile,
): Partial<Profile> | null {
  const patch: Partial<Profile> = {};
  if (extracted.countries?.length) {
    patch.prefCountries = [...new Set([...(profile.prefCountries ?? []), ...extracted.countries])];
  }
  if (extracted.climate) patch.prefClimate = extracted.climate;
  if (extracted.environment) patch.prefEnvironment = extracted.environment;
  if (extracted.city) patch.prefCity = extracted.city;
  if (extracted.afterGrad) patch.prefAfterGrad = extracted.afterGrad;
  if (extracted.salary) {
    patch.prefSalary = extracted.salary.amount;
    patch.prefSalaryCurrency = extracted.salary.currency;
  }
  if (extracted.pressure) patch.prefPressure = extracted.pressure;
  if (extracted.teaching) patch.prefTeaching = extracted.teaching;
  if (extracted.note?.trim()) {
    // Round 14, P2a: the note is ONE value, stored joined with '·'
    // so the preference summary keeps it as one atom (see
    // normaliseCountryNote) instead of splitting it on '；'/'、'.
    patch.prefCountriesNote = appendCountryNote(profile.prefCountriesNote, extracted.note);
  }
  return Object.keys(patch).length ? patch : null;
}

/** Whether the why-follow-up fires for newly recorded countries
 * (Round 13). The follow-up asks what the reason MEANS to the user —
 * so a reason that arrived in the SAME turn as the countries ("瑞士，
 * 环境优美") does NOT suppress it: the chat confirmed the phrase but
 * never explored it, and the re-test showed the chat going straight
 * to climate. Only a reason recorded in an EARLIER turn suppresses
 * it (the user already elaborated once — asking again would nag).
 * One rule, used by every path that records countries (model-led
 * confirm, template-fallback confirm, guided free text, guided
 * chips, parse confirm, and the gateway-down failure preserve). */
export function shouldAskCountryWhy(
  newCountries: string[],
  priorNote: string | undefined,
): boolean {
  return newCountries.length > 0 && !(priorNote ?? '').trim();
}

/** The WHY follow-up for one pref-chat reply, derived from its
 * `extracted` against the known set BEFORE the turn (Round 14, P0).
 * The backend now sends the same shape as `why_followup`; this is
 * the local fallback for replies that predate it (or template
 * replies built without it). Null when no new country was recorded
 * or a reason from an earlier turn is already on file. */
export function whyFollowupFromExtracted(
  extracted: PrefExtracted | undefined,
  knownBefore: PrefKnown,
): { countries: string[]; note?: string } | null {
  if (!extracted?.countries?.length) return null;
  const fresh = extracted.countries.filter((c) => !knownBefore.countries.includes(c));
  if (!shouldAskCountryWhy(fresh, knownBefore.note ?? undefined)) return null;
  const note = extracted.note?.trim();
  return note ? { countries: fresh, note } : { countries: fresh };
}

/** Round 15: which turn the WHY follow-up bubble anchors to. The
 * WHY belongs to the FIRST reply of the turn that recorded the new
 * countries, so it renders immediately after that turn's reply
 * bubble — before the confirm bubble, never after it. The id of that
 * turn (or null when the follow-up was armed without one: an old
 * blob, or the guided preserve path, whose turn was removed): the
 * caller then renders the bubble right after all turns, still
 * before the confirm bubble. A turnId for a turn that is no longer
 * in the list is also null — the bubble must never attach to the
 * wrong turn. */
export function whyAnchoredTurnId(
  awaitingReason: { turnId?: number } | null,
  turnIds: number[],
): number | null {
  if (!awaitingReason || awaitingReason.turnId === undefined) return null;
  return turnIds.includes(awaitingReason.turnId) ? awaitingReason.turnId : null;
}

// --- WHY as a first-class part of its turn (round 16) -----------------------
// Re-test task 10 (2026-11-27 03:14-03:19 CST) found the WHY still
// broken in three ways, all in the turn rendering:
// (1) ORDER: the first reply's lines end with the next-question line
//     (climate), and the WHY bubble renders after the whole reply —
//     so the climate question is asked BEFORE the WHY. The backend
//     now withholds the question line when why_followup is present
//     (see ai/pref_chat.py); the deferred question renders after the
//     WHY is answered or skipped, never before.
// (2) DETACHED ANSWER: the WHY answer was appended to the
//     confirmedNotes list and rendered as a bottom bubble while the
//     WHY question itself vanished from history (awaitingReason was
//     cleared, and nothing in the turn remembered the question). The
//     WHY question + answer now live ON the turn (PrefTurnWhy,
//     persisted with it) and render inside the turn's block, in
//     order, in both the model and the guided branch (renderPrefTurns
//     is shared) and across leave-and-return.
// (3) The input died while a confirm was pending (see mergeExtracted
//     below and the PrefChat input guards).

/** One WHY follow-up as part of a pref-chat turn: the question the
 * turn asked about the user's reason for its countries, the user's
 * verbatim answer once given, and whether they skipped it. */
export interface PrefTurnWhy {
  countries: string[];
  note?: string;
  /** The user's verbatim answer, once given; null while unanswered. */
  answer: string | null;
  /** True when the user skipped the WHY (the reason stays unknown). */
  skipped: boolean;
}

/** The fields of a pref-chat turn the bubble order depends on. */
export interface PrefTurnLike {
  id: number;
  question: string;
  reply: PrefChatReply | null;
  why?: PrefTurnWhy | null;
}

/** One bubble of a rendered pref-chat turn, in order. The component
 * renders each kind; this function owns the ORDER, so it is
 * unit-testable without a DOM (see tests/test_r16_w1.py). */
export type PrefTurnBubble =
  | { kind: 'user'; text: string }
  | { kind: 'reply'; lines: string[] }
  | { kind: 'why'; countries: string[]; note?: string }
  | { kind: 'whyAnswer'; answer: string }
  | { kind: 'deferredQuestion'; question: Exclude<PrefNextQuestion, null> }
  /** Round 28 D1: the next preference question, moved out of the
   * reply bubble (see prefTurnBubbles) so it renders through the
   * current locale's question key instead of frozen in the reply's
   * locale. Same rendering as 'deferredQuestion'. */
  | { kind: 'question'; question: Exclude<PrefNextQuestion, null> };

/** The bubbles of one pref-chat turn, in rendered order:
 * the user's verbatim message, the reply's lines, the WHY question,
 * the WHY answer (once given), and — only after the WHY is answered
 * or skipped — the deferred next question. The climate question can
 * never appear before the WHY answer: while the WHY is live the
 * deferred bubble is withheld, and the reply's lines carry no
 * next-question line for a WHY turn (the backend withholds it; see
 * the strip below, retained as defence in depth now the locale
 * re-fetch that used to recompute it is deleted — Round 27 W1).
 * Round 28 D1: a turn with NO why record carries its next question
 * as the last line of `lines` (the server appends it); that line is
 * frozen in the reply's locale, so after a language switch the
 * robot's question stayed Chinese in the English UI (re-test 22
 * item d). The trailing line moves out of the reply bubble into a
 * `question` bubble, which the component renders through the
 * current locale's question key — render-time localisation of a
 * structured field, the same class as the Round 27 W4 choice-label
 * fix; no re-fetch, no storage change. The invariant relied on is
 * the one in the strip comment below (last line is the question
 * when next_question is non-null); it is pinned by
 * tests/test_r28_d1.py and by the backend's own tests
 * (test_r16_w1.py: no-WHY turns still ask the next question last).
 * Residual: if a model substance line ever equalled the
 * deterministic question line verbatim, the backend's dedupe
 * (ai/pref_chat.py _render_pref_lines) would leave it mid-lines
 * and the positional drop would take a substance line instead —
 * the same pre-existing exposure as the WHY strip. */
export function prefTurnBubbles(
  turn: PrefTurnLike,
  awaitingReason: { countries: string[]; note?: string; turnId?: number } | null,
): PrefTurnBubble[] {
  const out: PrefTurnBubble[] = [{ kind: 'user', text: turn.question }];
  const lines = turn.reply?.lines ?? [];
  // Round 27 W1: the locale re-fetch that used to recompute
  // why_followup as null after the WHY was answered AND confirmed
  // is deleted — a stored reply is never re-fetched — so this strip
  // is defence in depth only: if a stored reply ever ends with the
  // question line while a WHY is attached, drop that trailing line
  // here, so the question shows once, as the deferred bubble below,
  // never twice and never inside the reply ahead of the WHY. The
  // question line is always the last line of `lines` when
  // next_question is non-null (the server appends it); a WHY turn's
  // own reply never ends with it (the backend withheld it), so no
  // substance line is ever dropped.
  const stripQuestion = !!turn.why && !turn.reply?.why_followup
    && !!turn.reply?.next_question && lines.length > 0;
  // Round 28 D1: the same trailing line, on a turn with no WHY —
  // it leaves the reply bubble and renders as a `question` bubble
  // below. Guarded on !why_followup: when the reply carries a WHY
  // follow-up but the turn has no why record (a pre-round-16 blob),
  // the backend withheld the line, so there is no trailing line to
  // move and no question bubble to emit.
  const moveQuestion = !turn.why && !turn.reply?.why_followup
    && !!turn.reply?.next_question && lines.length > 0;
  out.push({ kind: 'reply', lines: (stripQuestion || moveQuestion) ? lines.slice(0, -1) : lines });
  // The WHY question: live when it anchors to this turn, else the
  // turn's own record (resolved or still open).
  const liveHere = awaitingReason?.turnId === turn.id ? awaitingReason : null;
  if (liveHere) {
    out.push({ kind: 'why', countries: liveHere.countries, ...(liveHere.note ? { note: liveHere.note } : {}) });
    return out;
  }
  if (turn.why) {
    out.push({ kind: 'why', countries: turn.why.countries, ...(turn.why.note ? { note: turn.why.note } : {}) });
    if (turn.why.answer !== null) {
      out.push({ kind: 'whyAnswer', answer: turn.why.answer });
    }
    if ((turn.why.answer !== null || turn.why.skipped) && turn.reply?.next_question) {
      out.push({ kind: 'deferredQuestion', question: turn.reply.next_question });
    }
    return out;
  }
  // Round 28 D1: a non-WHY turn's next question, as its own bubble
  // after the reply — the question the trailing line carried, now
  // rendered through the current locale. Emitted whenever the reply
  // names a next question (even with empty lines — the turn cannot
  // crash on a missing trailing line); a done turn (next_question
  // null) gets none.
  if (!turn.reply?.why_followup && turn.reply?.next_question) {
    out.push({ kind: 'question', question: turn.reply.next_question });
  }
  return out;
}

/** Attach a WHY answer to its turn: the acknowledgement renders
 * inside the turn, right after the WHY question — never as a
 * detached bottom bubble. Returns the turns with that turn's
 * why.answer set (skipped false); every other turn is returned
 * untouched. When the turn has no why record yet, one is created
 * from `why` (the live awaitingReason); when turnId is undefined
 * or matches no turn, the turns are returned unchanged — the caller
 * then falls back to the confirmedNotes bubble (old blobs, the
 * guided queue's turn-less WHY). */
export function answerTurnWhy<T extends PrefTurnLike>(
  turns: readonly T[],
  turnId: number | undefined,
  answer: string,
  why?: { countries: string[]; note?: string } | null,
): T[] {
  if (turnId === undefined) return [...turns];
  return turns.map((x) => {
    if (x.id !== turnId) return x;
    const record: PrefTurnWhy | null = x.why ?? (why && why.countries.length
      ? { countries: why.countries, ...(why.note ? { note: why.note } : {}), answer: null, skipped: false }
      : null);
    if (!record) return x;
    return { ...x, why: { ...record, answer, skipped: false } };
  });
}

/** Mark a turn's WHY as skipped (the reason stays unknown): the WHY
 * question stays in the turn's history, the deferred question
 * renders after it, and the question is never re-asked. Same
 * fallbacks as answerTurnWhy. */
export function skipTurnWhy<T extends PrefTurnLike>(
  turns: readonly T[],
  turnId: number | undefined,
  why?: { countries: string[]; note?: string } | null,
): T[] {
  if (turnId === undefined) return [...turns];
  return turns.map((x) => {
    if (x.id !== turnId) return x;
    const record: PrefTurnWhy | null = x.why ?? (why && why.countries.length
      ? { countries: why.countries, ...(why.note ? { note: why.note } : {}), answer: null, skipped: false }
      : null);
    if (!record) return x;
    return { ...x, why: { ...record, skipped: true } };
  });
}

/** Localised city name for a stored (canonical English) city value:
 * `city.<slug>` when the locale file has one, the stored value
 * itself otherwise (a Chinese city name, or an untranslated city,
 * renders as stored — never a raw locale key). Same slug rule as
 * `cityDisplayName` in preferences.ts, kept here so the confirmation
 * summary in this file can localise a city without that import. */
export function localisedCityName(city: string, t: (k: string) => string): string {
  if (!city) return city;
  const slug = city.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  if (!slug) return city;
  const key = `city.${slug}`;
  const v = t(key);
  return v === key ? city : v;
}

/** The countries note, stored so it survives the preference summary
 * as ONE atom (Round 14, P2a). `prefSummary` splits parts into atoms
 * on '；' ';' '、' '，' — so a note joined or typed with '；'/'、'
 * ("空气清新、湖光山色、安静宜居") used to render as three separate
 * summary items. Joining the note's segments with an unspaced '·'
 * instead keeps it one atom: `prefSummary` never splits a note on
 * '·' into atoms (its note-only step strips only a '·'-segment that
 * duplicates another atom, which is exactly the Round 13 dedupe —
 * "环境优美·校园氛围" next to the campus label still loses the
 * "校园氛围" segment and keeps "环境优美"). Only enumeration
 * separators are normalised: '，' and ',' are sentence punctuation
 * and stay verbatim (test_p0_retest6 pins "瑞士，因为那边环境优美"
 * word-for-word), so a comma-joined clause is still split by the
 * summary builder — the full fix for that shape is exempting the
 * note from atom-splitting in `prefSummary` itself. Words are
 * preserved; only enumeration separators are normalised. */
export function normaliseCountryNote(note: string): string {
  return note
    .split(/[；;、·]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .join('·');
}

/** Append a reason to the stored countries note, joined so the whole
 * note stays one summary atom (see normaliseCountryNote). An exact
 * duplicate is not appended twice. */
export function appendCountryNote(existing: string | undefined, addition: string): string {
  const base = normaliseCountryNote((existing ?? '').trim());
  const add = normaliseCountryNote(addition.trim());
  if (!add) return base;
  if (!base) return add;
  if (base === add || base.includes(add)) return base;
  return `${base}·${add}`;
}

/** Short label for one preference question (locale key suffix). */
export function prefQuestionNameKey(q: Exclude<PrefNextQuestion, null>): string {
  return `wizard.chatPrefName${q[0].toUpperCase()}${q.slice(1)}`;
}

/**
 * The understood values of one extraction, as a readable summary for
 * the confirmation bubble — enum values in the current locale, the
 * user's own words (city, note) verbatim and quoted. Nothing is
 * invented: a field the server did not extract is simply absent.
 *
 * Round 8: a note that says the same thing as an already-listed value
 * is dropped instead of repeated — the model often extracts both the
 * enum and the user's own words for it ("大学城·校园氛围" as
 * environment=campus AND note="大学城·校园氛围"), which used to
 * render as the tautology "大学城·校园氛围 · “大学城·校园氛围”".
 */
export function extractedSummary(
  extracted: PrefExtracted,
  t: (k: string) => string,
  locale?: string,
): string {
  const parts: string[] = [];
  if (extracted.countries?.length) {
    parts.push(joinList(extracted.countries.map((c) => t(`country.${c}`)), locale ?? 'en'));
  }
  if (extracted.climate) {
    parts.push(t(`wizard.prefClimate${extracted.climate === 'four_seasons' ? 'FourSeasons' : extracted.climate[0].toUpperCase() + extracted.climate.slice(1)}`));
  }
  if (extracted.environment) {
    const key: Record<string, string> = {
      big_city: 'wizard.prefEnvironmentBigCity', small_city: 'wizard.prefEnvironmentSmallCity',
      campus: 'wizard.prefEnvironmentCampus', quiet_town: 'wizard.prefEnvironmentQuietTown',
    };
    parts.push(t(key[extracted.environment]));
  }
  if (extracted.city) parts.push(localisedCityName(extracted.city, t));
  if (extracted.afterGrad) {
    const key: Record<string, string> = {
      stay: 'wizard.prefAfterGradStay', return_home: 'wizard.prefAfterGradReturnHome',
      hometown: 'wizard.prefAfterGradHometown', undecided: 'wizard.prefAfterGradUndecided',
    };
    parts.push(t(key[extracted.afterGrad]));
  }
  if (extracted.salary) parts.push(`${extracted.salary.amount} ${extracted.salary.currency}`);
  if (extracted.pressure) {
    parts.push(t(`wizard.prefPressure${extracted.pressure[0].toUpperCase()}${extracted.pressure.slice(1)}`));
  }
  if (extracted.teaching) {
    const key: Record<string, string> = {
      lecture: 'wizard.prefTeachingLecture', seminar: 'wizard.prefTeachingSeminar',
      hands_on: 'wizard.prefTeachingHandsOn',
    };
    parts.push(t(key[extracted.teaching]));
  }
  // The reason, in the user's own words — never paraphrased away —
  // unless it says exactly the same as a value already listed above
  // (only an exact match is dropped: a note that ADDS words, e.g.
  // "瑞士，因为那边环境优美" next to "瑞士", is kept whole).
  if (extracted.note?.trim()) {
    const note = extracted.note.trim();
    const norm = (s: string) => s.toLowerCase().replace(/[·、，,；;。.\s]/g, '');
    if (!parts.some((p) => norm(p) === norm(note))) {
      parts.push(`“${note}”`);
    }
  }
  return parts.join(' · ');
}

/**
 * Round 28 D1: a stored confirmed note, in the CURRENT locale.
 * confirmExtract stores `extractedSummary(...)` — a ' · '-joined
 * string built in the confirm-time locale — and saveReason stores
 * the user's verbatim WHY text; the confirmedNotes render used to
 * print the stored string verbatim under a re-localised "Got it,
 * noted!" prefix, so after a zh→en switch the bubbles still read
 * "苏黎世", "适中", "瑞士 · 凉爽 · …" (re-test 22 item d). This
 * helper inverts exactly what extractedSummary produces, at render
 * time only (storage, the backend contract and the persist
 * whitelist are untouched, so old snapshots benefit too):
 *
 * - split on ' · ' (space-dot-space): the environment label itself
 *   contains '·' WITHOUT spaces ("大学城·校园氛围"), so it stays
 *   one segment and re-localises;
 * - a segment re-localises ONLY when it resolves unambiguously to
 *   a single choice ref (choiceRefsForLabel length 1): ambiguous
 *   labels ("新加坡" / "香港", country-vs-city) stay verbatim;
 * - segments with no reverse-map match stay verbatim — that covers
 *   the salary ("80000 CHF") and the WHY reason in the user's own
 *   words ("“环境优美”"), which must NEVER be re-localised, and a
 *   multi-label segment ("瑞士和英国", "瑞士、英国") which stays
 *   verbatim (documented residual: the countries join is one
 *   segment, not two choices);
 * - a choice label can itself span the separator: the environment
 *   campus label is "University town · campus vibe" in en/es/fr/
 *   pt-BR/ar (spaced '·'), so a note built in one of those locales
 *   splits it into two segments — the two-segment join is tried
 *   first, then the single segment, so the label re-localises in
 *   both directions. Only the campus labels contain ' · ', so a
 *   two-segment join can only ever match a campus label.
 *
 * Pure; never invents a label — every re-localisation goes through
 * the existing reverse map and choiceLabelFor.
 */
export function localisedConfirmedNote(note: string, t: (k: string) => string): string {
  const segments = note.split(' · ');
  const out: string[] = [];
  let i = 0;
  while (i < segments.length) {
    if (i + 1 < segments.length) {
      const joined = `${segments[i]} · ${segments[i + 1]}`;
      const joinedRefs = choiceRefsForLabel(joined);
      if (joinedRefs.length === 1) {
        out.push(choiceLabelFor(joinedRefs[0], t));
        i += 2;
        continue;
      }
    }
    const refs = choiceRefsForLabel(segments[i]);
    out.push(refs.length === 1 ? choiceLabelFor(refs[0], t) : segments[i]);
    i += 1;
  }
  return out.join(' · ');
}

/** Fold a pending (not yet confirmed) extraction into the known set,
 * so the "Understood n of 8" progress counts what the model already
 * understood — it must not wait for the user's confirm tap. The
 * extraction is never applied here; confirmation still owns that. */
export function mergeKnownWithExtracted(known: PrefKnown, extracted: PrefExtracted): PrefKnown {
  const next: PrefKnown = { ...known, countries: [...known.countries] };
  if (extracted.countries?.length) {
    next.countries = [...new Set([...next.countries, ...extracted.countries])];
  }
  if (extracted.climate) next.climate = extracted.climate;
  if (extracted.environment) next.environment = extracted.environment;
  if (extracted.city) next.city = extracted.city;
  if (extracted.afterGrad) next.afterGrad = extracted.afterGrad;
  if (extracted.salary) {
    next.salary = extracted.salary.amount;
    next.salaryCurrency = extracted.salary.currency;
  }
  if (extracted.pressure) next.pressure = extracted.pressure;
  if (extracted.teaching) next.teaching = extracted.teaching;
  if (extracted.note?.trim()) next.note = extracted.note.trim();
  return next;
}

/**
 * Merge two pref-chat extractions, oldest first (Round 16): when a
 * new reply arrives while an earlier extraction is still waiting for
 * confirmation — which is now reachable, because the input stays live
 * while a confirm is pending — the new understanding is folded into
 * the pending one instead of overwriting it. Nothing the model
 * understood is dropped, and the confirm bubble covers everything
 * understood so far. Countries union; enums / city / salary take the
 * newer value; the note appends as one atom (see appendCountryNote).
 * Nothing is applied here — confirmation still owns that.
 */
export function mergeExtracted(oldE: PrefExtracted, newE: PrefExtracted): PrefExtracted {
  const out: PrefExtracted = { ...oldE };
  if (newE.countries?.length) {
    out.countries = [...new Set([...(oldE.countries ?? []), ...newE.countries])];
  }
  if (newE.climate !== undefined) out.climate = newE.climate;
  if (newE.environment !== undefined) out.environment = newE.environment;
  if (newE.city !== undefined) out.city = newE.city;
  if (newE.afterGrad !== undefined) out.afterGrad = newE.afterGrad;
  if (newE.salary !== undefined) out.salary = newE.salary;
  if (newE.pressure !== undefined) out.pressure = newE.pressure;
  if (newE.teaching !== undefined) out.teaching = newE.teaching;
  if (newE.note?.trim()) {
    out.note = appendCountryNote(oldE.note, newE.note.trim());
  }
  return out;
}

/**
 * Round 17, P0 — answering the WHY about a country is implicit
 * confirmation of that country. Split a pending (unconfirmed)
 * extraction into the countries the WHY answer confirms and the
 * rest, which stays pending for the confirm bubble. The user just
 * elaborated on WHY they want that country — they cannot
 * meaningfully answer "what does Switzerland's scenery mean to you"
 * while rejecting Switzerland — so those countries land in the
 * Profile with the WHY answer instead of waiting for a confirm tap
 * that a later model drop can kill (re-test task 11: the confirm was
 * never tapped, the model dropped, enterGuidedMode discarded the
 * pending extraction, and Switzerland was silently lost while the
 * WHY free text masqueraded as the country answer). Only the WHY's
 * countries are confirmed here — anything else the pending
 * extraction holds (a later climate answer, the reason note) stays
 * in `remaining` for the confirm bubble. Pure: nothing is applied,
 * the caller applies `confirmedCountries` and keeps `remaining`.
 * `remaining` is null when nothing is left to confirm.
 */
export function splitWhyConfirmedCountries(
  extracted: PrefExtracted | undefined,
  whyCountries: string[],
): { confirmedCountries: string[]; remaining: PrefExtracted | null } {
  const confirmedCountries = (extracted?.countries ?? []).filter((c) => whyCountries.includes(c));
  const restCountries = (extracted?.countries ?? []).filter((c) => !whyCountries.includes(c));
  const remaining: PrefExtracted = { ...(extracted ?? {}) };
  if (restCountries.length) remaining.countries = restCountries;
  else delete remaining.countries;
  return { confirmedCountries, remaining: Object.keys(remaining).length ? remaining : null };
}

// --- Desktop-pet known-steps (round 7, Fix B) -------------------------------
// The pet's guided flow (degree -> country -> budget) must skip what
// the wizard already learned, and must never claim "no preferences"
// while the saved profile holds them. Pure helpers so the logic is
// unit-testable; CompassPet renders from their result.

export interface PetKnownSteps {
  /** Degree from profile.track, when set. */
  degree: DegreeLevel | null;
  /** Country when exactly one preferred country is saved. Several
   * saved countries still need a choice, so they are not auto-picked. */
  country: string | null;
  /** Budget band derived from a saved budget, GB/SG only (their
   * ceilings are the only band tables that exist). Null otherwise. */
  band: BudgetBand | null;
}

/**
 * What the pet's guided flow already knows from the saved wizard
 * profile. `ceilings` is the GB/SG band table (BAND_CEILING in
 * CompassPet): low when the budget is at or under the low ceiling,
 * mid at or under the mid ceiling, high above it (or when the mid
 * ceiling is null — the "high" band has no ceiling).
 */
export function petKnownSteps(
  profile: Profile,
  ceilings: Record<string, Record<BudgetBand, number | null>>,
): PetKnownSteps {
  const degree: DegreeLevel | null =
    profile.track === 'undergraduate' || profile.track === 'taught_masters' ? profile.track : null;
  const countries = profile.prefCountries ?? [];
  const country = countries.length === 1 ? countries[0] : null;
  let band: BudgetBand | null = null;
  if (degree && country && typeof profile.budget === 'number') {
    const table = ceilings[`${degree}-${country}`];
    if (table) {
      if (table.low !== null && profile.budget <= table.low) band = 'low';
      else if (table.mid !== null && profile.budget <= table.mid) band = 'mid';
      else band = 'high';
    }
  }
  return { degree, country, band };
}

/** One-line English context of the saved preferences, appended (only)
 * to the message the pet sends to the model on the first free-text
 * turn — so a greeting like "你好" gets a reply that knows what the
 * wizard already learned, instead of a canned intro that contradicts
 * the saved state. The stored/displayed message stays verbatim. */
export function savedPrefsContext(profile: Profile): string | null {
  const known = knownFromProfile(profile);
  const parts: string[] = [];
  if (known.countries.length) parts.push(`countries: ${known.countries.join(', ')}`);
  if (known.climate) parts.push(`climate: ${known.climate}`);
  if (known.environment) parts.push(`environment: ${known.environment}`);
  if (known.city) parts.push(`city: ${known.city}`);
  if (known.afterGrad) parts.push(`after graduation: ${known.afterGrad}`);
  if (known.salary !== null) parts.push(`expected salary: ${known.salary} ${known.salaryCurrency ?? ''}`.trim());
  if (known.pressure) parts.push(`pressure tolerance: ${known.pressure}`);
  if (known.teaching) parts.push(`teaching style: ${known.teaching}`);
  if (known.note) parts.push(`note in the user's own words: ${known.note}`);
  if (!parts.length) return null;
  return `The user's saved preferences from the eligibility check: ${parts.join('; ')}.`;
}

// --- Append-only model drop (round 15, F1) --------------------------------
// A mid-conversation model drop must APPEND a guided continuation,
// never rewrite or discard earlier turns. The pre-round-15 code in
// PrefChat.preserveFailedAnswer did
// `setTurns(prev => prev.filter(x => x.id !== turnId))` — deleting
// the just-sent turn — and then switched `mode` to 'guided', whose
// branch does not render `turns` at all, so every earlier model turn
// vanished from the screen and the chat read as "rewritten as guided
// template" (browser re-test task 9, 2026-11-27 ~02:27 and ~02:33).
// The fix (PrefChat patch, see tests/test_r15_w3.py): mark the failed
// turn offline IN PLACE and render the kept turns above the guided
// continuation. This helper is the turn-array half of that fix —
// pure, so the invariant is unit-testable here:
// - length never changes, order never changes, every other turn is
//   returned untouched (same reference);
// - the dropped turn keeps its question verbatim, keeps a template
//   reply when one arrived, loses nothing else, and is marked
//   offline + not pending, so it renders with the honest offline
//   line instead of disappearing;
// - the caller's answer preservation (local mapping / failedText
//   prefill) is untouched — the turn and the preserved answer are
//   two halves of the same drop, neither may delete the other.

export interface DropTurnLike<Reply> {
  id: number;
  question: string;
  reply: Reply | null;
  replyLocale: string | null;
  offline: boolean;
  pending: boolean;
}

/** Mark one turn offline after a model drop, in place. `reply` /
 * `replyLocale` carry a template reply when one arrived (round 10:
 * a template reply with an extraction is kept, labelled offline);
 * both default to null (the call itself failed — no reply at all).
 * Every other turn is returned as-is; nothing is removed, reordered
 * or rewritten. */
export function markTurnOffline<Reply, T extends DropTurnLike<Reply>>(
  turns: readonly T[],
  turnId: number,
  reply?: Reply | null,
  replyLocale?: string | null,
): T[] {
  return turns.map((x) => (x.id === turnId
    ? {
        ...x,
        reply: reply !== undefined ? reply : null,
        replyLocale: replyLocale !== undefined ? replyLocale : null,
        offline: true,
        pending: false,
      }
    : x));
}

// --- Pref-chat progress persistence (round 14, P1) --------------------------
// Leaving the wizard mid-way used to reset the pref-chat to 0/8: only
// the completed summary was saved (the Profile itself is already
// persisted as pp-profile). The chat's own turn/progress state is
// persisted alongside it (localStorage 'pp-prefchat', written by
// PrefChat) and restored on mount, so leaving and returning resumes
// where it left off — same turns, same count, same next question.
// The blob is validated against a fingerprint of the saved Profile's
// preference fields: a blob whose fingerprint does not match the
// stored profile (cleared data, a restart elsewhere, a stale
// completed chat after the profile was reset) is discarded, never
// resurrected. A turn that was still pending when the user left is
// restored as offline (its reply never landed), never as pending
// forever. Pure helpers, unit-tested via a node harness.

export interface PersistedPrefTurn {
  id: number;
  question: string;
  reply: PrefChatReply | null;
  replyLocale: string | null;
  offline: boolean;
  /** Round 16: the WHY follow-up that belongs to this turn (see
   * PrefTurnWhy) — persisted with the turn so leave-and-return keeps
   * the WHY question + answer attached to it, never as a detached
   * bottom bubble. Absent on pre-round-16 blobs. */
  why?: PrefTurnWhy | null;
}

export interface PersistedModelTurn {
  id: number;
  q: string;
  question: string;
  reply: ChatReply | null;
  replyLocale: string | null;
  offline: boolean;
}

export interface PrefChatPersistedState {
  version: 1;
  mode: 'model' | 'guided';
  turns: PersistedPrefTurn[];
  modelTurns: PersistedModelTurn[];
  qIndex: number;
  skipped: string[];
  serverNext: PrefNextQuestion | undefined;
  awaitingReason: { countries: string[]; note?: string; turnId?: number } | null;
  verbatim: Record<string, string>;
  failedText: string | null;
  /** Round 15: an extraction waiting for confirmation — it is NOT in
   * the Profile yet (confirmation owns that), so without it a
   * leave-and-return silently dropped the turn's understanding and
   * the progress count fell (2/8 -> 1/8: the climate answer was
   * understood but never confirmed). Restored as-is, so the confirm
   * bubble and the count survive the return. */
  pendingExtract: { extracted: PrefExtracted; rawText: string } | null;
  /** Round 15: every "noted" bubble — the WHY answer ("干净的空气、
   * 湖光山色、安静的生活") and the confirm summary ("瑞士·'环境优美'").
   * Round 14 kept only the latest one in a transient `confirmedNote`
   * slot (answering WHY and then confirming overwrote the WHY answer
   * even before leaving, and leaving lost the slot entirely). A list
   * keeps each bubble, in order, across leave-and-return. */
  confirmedNotes: string[];
  fingerprint: string;
}

/** Fingerprint of the preference fields the chat owns — the blob is
 * only restored when it matches the stored Profile. */
export function prefChatFingerprint(p: Profile): string {
  return JSON.stringify([
    p.prefCountries ?? [], p.prefCountriesNote ?? '',
    p.prefClimate ?? '', p.prefEnvironment ?? '', p.prefCity ?? '',
    p.prefAfterGrad ?? '', p.prefSalary ?? '', p.prefSalaryCurrency ?? '',
    p.prefPressure ?? '', p.prefTeaching ?? '',
  ]);
}

export type PrefChatStateToPersist = Omit<PrefChatPersistedState, 'version' | 'fingerprint'> & {
  turns: (PersistedPrefTurn & { pending?: boolean })[];
  modelTurns: (PersistedModelTurn & { pending?: boolean })[];
};

/** Serialise one snapshot. Pending turns are stored as offline (the
 * reply never landed); `pending` itself is never persisted. */
export function serializePrefChatState(
  state: PrefChatStateToPersist,
  fingerprint: string,
): string {
  const turns = state.turns.map((x: PersistedPrefTurn & { pending?: boolean }) => ({
    id: x.id, question: x.question, reply: x.reply,
    replyLocale: x.replyLocale ?? null, offline: x.offline || !!x.pending,
    ...(x.why ? { why: x.why } : {}),
  }));
  const modelTurns = state.modelTurns.map((x: PersistedModelTurn & { pending?: boolean }) => ({
    id: x.id, q: x.q, question: x.question, reply: x.reply,
    replyLocale: x.replyLocale ?? null, offline: x.offline || !!x.pending,
  }));
  return JSON.stringify({
    version: 1, mode: state.mode, turns, modelTurns,
    qIndex: state.qIndex, skipped: state.skipped,
    serverNext: state.serverNext ?? null,
    awaitingReason: state.awaitingReason, verbatim: state.verbatim,
    failedText: state.failedText,
    pendingExtract: state.pendingExtract ?? null,
    confirmedNotes: state.confirmedNotes ?? [],
    fingerprint,
  });
}

const _isStr = (v: unknown): v is string => typeof v === 'string';
const _isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** Parse + validate a stored blob against the current profile
 * fingerprint. Null on any mismatch or malformed content — a stale
 * or foreign blob is discarded, never applied. */
export function parsePrefChatState(
  raw: string | null | undefined,
  fingerprint: string,
): PrefChatPersistedState | null {
  if (!raw) return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!data || typeof data !== 'object') return null;
  const d = data as Record<string, unknown>;
  if (d.version !== 1 || d.fingerprint !== fingerprint) return null;
  if (d.mode !== 'model' && d.mode !== 'guided') return null;
  if (!Array.isArray(d.turns) || !Array.isArray(d.modelTurns)) return null;
  const turns: PersistedPrefTurn[] = [];
  for (const x of d.turns as unknown[]) {
    if (!x || typeof x !== 'object') return null;
    const t = x as Record<string, unknown>;
    if (!_isNum(t.id) || !_isStr(t.question) || !t.question.trim()) return null;
    // Round 16: the WHY that belongs to this turn. A malformed why
    // is dropped, never applied — the turn itself still parses.
    let why: PrefTurnWhy | null = null;
    if (t.why && typeof t.why === 'object') {
      const w = t.why as Record<string, unknown>;
      if (Array.isArray(w.countries) && w.countries.length
        && w.countries.every((c) => _isStr(c) && c)
        && (w.answer === null || _isStr(w.answer))
        && typeof w.skipped === 'boolean') {
        why = {
          countries: w.countries as string[],
          ...(_isStr(w.note) && w.note ? { note: w.note } : {}),
          answer: w.answer as string | null,
          skipped: w.skipped as boolean,
        };
      }
    }
    turns.push({
      id: t.id, question: t.question,
      reply: (t.reply && typeof t.reply === 'object' ? t.reply : null) as PrefChatReply | null,
      replyLocale: _isStr(t.replyLocale) ? t.replyLocale : null,
      offline: t.offline === true,
      ...(why ? { why } : {}),
    });
  }
  const modelTurns: PersistedModelTurn[] = [];
  for (const x of d.modelTurns as unknown[]) {
    if (!x || typeof x !== 'object') return null;
    const t = x as Record<string, unknown>;
    if (!_isNum(t.id) || !_isStr(t.q) || !_isStr(t.question) || !t.question.trim()) return null;
    modelTurns.push({
      id: t.id, q: t.q, question: t.question,
      reply: (t.reply && typeof t.reply === 'object' ? t.reply : null) as ChatReply | null,
      replyLocale: _isStr(t.replyLocale) ? t.replyLocale : null,
      offline: t.offline === true,
    });
  }
  const qIndex = _isNum(d.qIndex) ? Math.max(0, Math.min(PREF_QUESTIONS.length, Math.floor(d.qIndex))) : 0;
  const skipped = Array.isArray(d.skipped)
    ? (d.skipped as unknown[]).filter((q): q is string => _isStr(q) && (PREF_QUESTIONS as string[]).includes(q))
    : [];
  const serverNext = _isStr(d.serverNext) && (PREF_QUESTIONS as string[]).includes(d.serverNext)
    ? d.serverNext as PrefNextQuestion : undefined;
  let awaitingReason: PrefChatPersistedState['awaitingReason'] = null;
  if (d.awaitingReason && typeof d.awaitingReason === 'object') {
    const a = d.awaitingReason as Record<string, unknown>;
    if (Array.isArray(a.countries) && a.countries.length
      && a.countries.every((c) => _isStr(c) && c)) {
      awaitingReason = {
        countries: a.countries as string[],
        ...(_isStr(a.note) && a.note ? { note: a.note } : {}),
        // Round 15: the turn that armed the WHY (see
        // whyAnchoredTurnId) — old blobs have none, which simply
        // means "render after the turns, before the confirm bubble".
        ...(_isNum(a.turnId) ? { turnId: Math.floor(a.turnId) } : {}),
      };
    }
  }
  const verbatim: Record<string, string> = {};
  if (d.verbatim && typeof d.verbatim === 'object') {
    for (const [k, v] of Object.entries(d.verbatim as Record<string, unknown>)) {
      if (_isStr(v)) verbatim[k] = v;
    }
  }
  // Round 15: an extraction waiting for confirmation, restored as-is
  // (its `extracted` is validated when it is applied, exactly as a
  // fresh reply's is). A malformed entry is dropped, never applied.
  let pendingExtract: PrefChatPersistedState['pendingExtract'] = null;
  if (d.pendingExtract && typeof d.pendingExtract === 'object') {
    const p = d.pendingExtract as Record<string, unknown>;
    if (p.extracted && typeof p.extracted === 'object' && _isStr(p.rawText)) {
      pendingExtract = {
        extracted: p.extracted as PrefExtracted, rawText: p.rawText,
      };
    }
  }
  // Round 15: the "noted" bubbles, in order. Old (round 14) blobs
  // have none — they parse as an empty list, never as a failure.
  const confirmedNotes: string[] = Array.isArray(d.confirmedNotes)
    ? (d.confirmedNotes as unknown[]).filter((v): v is string => _isStr(v) && !!v.trim())
    : [];
  return {
    version: 1, mode: d.mode, turns, modelTurns, qIndex, skipped,
    serverNext, awaitingReason, verbatim,
    failedText: _isStr(d.failedText) ? d.failedText : null,
    pendingExtract, confirmedNotes,
    fingerprint,
  };
}
