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

/** One /assistant/chat reply. */
export interface ChatReply {
  lines: string[];
  evidence_url?: string | null;
  ai_status?: string;
  model?: string | null;
  sources?: { id: string; url: string | null; title: string }[];
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
  salaryCurrency: 'GBP' | 'SGD' | 'USD' | null;
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
  salary?: { amount: number; currency: 'GBP' | 'SGD' | 'USD' };
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
const SALARY_CURRENCIES = ['GBP', 'SGD', 'USD'] as const;

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
    const note = extracted.note.trim();
    const existing = (profile.prefCountriesNote ?? '').trim();
    patch.prefCountriesNote = existing && existing !== note && !existing.includes(note)
      ? `${existing}；${note}`
      : note;
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
): string {
  const parts: string[] = [];
  if (extracted.countries?.length) {
    parts.push(extracted.countries.map((c) => t(`country.${c}`)).join('、'));
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
  if (extracted.city) parts.push(extracted.city);
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
