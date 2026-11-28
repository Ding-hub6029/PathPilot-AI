'use client';
import { useEffect, useRef, useState } from 'react';
import { useApp, type Locale } from '../lib/store';
import { Profile, emptyProfile } from '../lib/types';
import {
  PREF_COUNTRY_CODES,
  bestCityForClimate, bestCityForClimateIn, canonicalCityName, choiceLabelFor, choiceRefsForLabel, citiesInCountries, cityDisplayName, climateLabel, countryCitiesWithClimate,
  environmentLabel, afterGradLabel, hasExtraWordsBeyondCountries, pressureLabel, teachingLabel,
  normaliseClimatePref, prefSummary,
} from '../lib/preferences';
import { allPrograms, fetchJsonChat } from '../lib/api';
import { joinList, parenNote } from '../lib/format';
import {
  isModelReply, looksLikeQuestion,
  appendCountryNote, countKnownPrefs, effectiveNextPref, extractedSummary, firstMissingPref, isModelPrefReply,
  isPrefKnown, knownFromProfile, markTurnOffline, mergeExtracted, mergeKnownWithExtracted, nextMissingPrefIndex, normaliseCountryNote,
  parsePrefChatState, prefChatFingerprint, prefQuestionNameKey, prefTurnBubbles, profilePatchFromExtracted,
  localisedConfirmedNote,
  answerTurnWhy, skipTurnWhy, splitWhyConfirmedCountries,
  serializePrefChatState, shouldAskCountryWhy, whyAnchoredTurnId, whyFollowupFromExtracted,
  PREF_QUESTIONS,
  type ChatHistoryTurn, type ChatReply, type ParseReply,
  type PrefChatPersistedState, type PrefChatReply, type PrefExtracted, type PrefKnown, type PrefNextQuestion,
  type PrefTurnBubble, type PrefTurnWhy,
} from '../lib/chat';
import { CompassFace, type PetMood } from './CompassPet';
import { localisedReplyLines } from '../lib/prefFallbackLines';
import { useElapsed } from '../lib/useElapsed';
import enMessages from '../../messages/en.json';

/**
 * Preference step as a full-page AI chat with 小罗盘 (2026-11-25, user:
 * "怎么是填表？就不能是一个像AI聊天机器人一样的炫酷的页面来问吗？"
 * + "像真正的人一样的在我面前问我的，带表情，还有自己的观点").
 *
 * Round 7 (2026-11-26): the chat is MODEL-LED, not a fixed 8-question
 * queue. Each user turn goes to POST /api/assistant/pref-chat with the
 * message, the locale, the already-known preferences and the last 6
 * turns of history. The model answers in its own words (≤3 lines) and
 * the server returns what it understood from THIS message
 * (`extracted`, server-validated) plus the single most useful
 * still-missing preference (`next_question`) — never a known one. A
 * mid-flow question ("瑞士有哪些好学校？") goes to the same endpoint
 * and gets a grounded model answer, then the conversation continues
 * with the next question; nothing already known is re-asked.
 *
 * Nothing is applied until the user confirms it: when `extracted` is
 * non-empty a confirmation bubble shows what was understood INCLUDING
 * the user's own words (the `note` reason, e.g. "因为那边环境优美")
 * and the values. Yes applies it to the Profile (countries ->
 * prefCountries, note -> prefCountriesNote, climate -> prefClimate,
 * environment -> prefEnvironment, city -> prefCity, afterGrad ->
 * prefAfterGrad, salary -> prefSalary + prefSalaryCurrency, pressure
 * -> prefPressure, teaching -> prefTeaching); No dismisses it.
 * Progress is "已了解 X / 8 项" with the still-missing items listed —
 * never "第 n / 8 题". The user's bubble always shows their verbatim
 * sentence; the stored record keeps their own words.
 *
 * When the pref-chat call fails or comes back with ai_status
 * "unavailable" (backend waking, gateway down, or the endpoint not
 * deployed yet), the chat degrades to the guided queue below — the
 * original 8 questions + local understanding + data-driven city chips
 * — with a plainly visible honest line, and a retry action that goes
 * back to the model-led chat. Never a faked AI answer. The local
 * keyword mapper (mapLocalAnswer) stays ONLY as the offline fallback's
 * understander, and even there the user's verbatim sentence is kept
 * for the history bubble and a country sentence that carries a reason
 * is stored whole as prefCountriesNote — never reduced to a bare
 * keyword.
 *
 * The pet has a face AND opinions: its mood follows the chat
 * (celebrate on greeting / a liked answer, think while the user types,
 * empathise when the user is unsure or wants to take it easy), and
 * after some answers it volunteers a view — but every fact inside an
 * opinion comes from the verified data already shipped in the frontend
 * (the merged catalogue: which institutions are in a chosen country,
 * how many verified programmes a city has, and the curated city
 * climate table). Climate opinions are scoped to the chosen countries:
 * the best city of the wanted class WITHIN them, or — when the chosen
 * country has no city of that class — the actual climate classes of
 * that country's real cities (e.g. Switzerland: Zurich/Lausanne are
 * four-season), never a pivot to Edinburgh or any other country.
 * Anything not in the data is never stated. No stars, no invented
 * figures, no salary data.
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

/** localStorage key for the chat's own turn/progress state (round 14,
 * P1) — the Profile itself lives under 'pp-profile' in the store. */
const PREF_CHAT_KEY = 'pp-prefchat';

/** Read the persisted chat snapshot, validated against the stored
 * Profile's preference fingerprint (a blob for another profile is
 * discarded, never resurrected). Null when nothing valid was saved. */
function loadPersistedPrefChat(): PrefChatPersistedState | null {
  try {
    const rawProfile = localStorage.getItem('pp-profile');
    const fingerprint = prefChatFingerprint(
      rawProfile ? { ...emptyProfile, ...JSON.parse(rawProfile) } : emptyProfile);
    return parsePrefChatState(localStorage.getItem(PREF_CHAT_KEY), fingerprint);
  } catch {
    return null;
  }
}

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
  // Round 27 W2: the first still-missing preference — the same rule
  // the queue advance uses, so entry and advance can never disagree
  // about what counts as answered. (Equivalent to the old
  // isPrefAnswered scan for every value the app can store:
  // prefSalary is number | '', and the enum fields only ever hold
  // their chip values; a whitespace-only note or an invalid enum
  // string now counts as unanswered instead of answered.)
  return nextMissingPrefIndex(knownFromProfile(p), 0);
}

/** Verified institutions in a country, from the shipped catalogue. */
function schoolsIn(country: string, locale: string): string {
  const names = [...new Set(allPrograms().filter((p) => p.country === country).map((p) => p.institution))];
  return joinList(names, locale);
}

/** Word match: ASCII words match on word boundaries ("low" must not
 * fire inside "follow"); CJK words match as substrings. */
function includesWord(haystack: string, word: string): boolean {
  if (/^[a-z][a-z ]*$/.test(word)) return new RegExp(`\\b${word.replace(/ /g, '\\s+')}\\b`).test(haystack);
  return haystack.includes(word);
}

/**
 * Understand a free-text answer to the current preference question
 * locally, from the question's own chip values: the localised chip
 * labels themselves plus a small English/Chinese synonym list. Only
 * an exact known value is ever returned — anything else is null and
 * the caller keeps the verbatim behaviour. Never invents a value.
 * OFFLINE FALLBACK ONLY (round 7): the model-led path never uses it.
 */
function mapLocalAnswer(
  q: PrefQId, text: string, t: (k: string) => string, profile: Profile,
): Partial<Profile> | null {
  const lower = text.toLowerCase();
  const matchOptions = (options: [string, string, string[]][]): string | null => {
    for (const [value, label, synonyms] of options) {
      if ((label && includesWord(lower, label.toLowerCase()))
        || synonyms.some((s) => includesWord(lower, s))) return value;
    }
    return null;
  };
  switch (q) {
    case 'climate': {
      // Negation guard: "不喜欢冷" must not map to cool.
      if (/(不喜欢|不要|不想|讨厌|don't like|don't want)/.test(lower)) return null;
      const v = matchOptions([
        ['four_seasons', t('wizard.prefClimateFourSeasons'), ['four seasons', '四季']],
        ['cool', t('wizard.prefClimateCool'), ['cool', 'cold', 'chilly', '寒冷', '很冷', '冷', '凉爽', '凉快']],
        ['warm', t('wizard.prefClimateWarm'), ['warm', 'hot', '暖', '热', '炎热']],
        ['mild', t('wizard.prefClimateMild'), ['mild', '温和', '宜人']],
      ]);
      return v ? { prefClimate: v } : null;
    }
    case 'countries': {
      const codes: string[] = [];
      for (const code of PREF_COUNTRY_CODES) {
        const names = [
          t(`country.${code}`),
          (enMessages as Record<string, string>)[`country.${code}`] ?? '',
          code,
        ].map((n) => n.toLowerCase()).filter(Boolean);
        if (names.some((n) => lower.includes(n))) codes.push(code);
      }
      if (!codes.length) return null;
      return { prefCountries: [...new Set([...(profile.prefCountries ?? []), ...codes])] };
    }
    case 'environment': {
      const v = matchOptions([
        ['big_city', t('wizard.prefEnvironmentBigCity'), ['big city', '大城市', '繁华', '热闹', 'buzzing']],
        ['small_city', t('wizard.prefEnvironmentSmallCity'), ['small city', '小城市']],
        ['campus', t('wizard.prefEnvironmentCampus'), ['campus', '校园', '大学城']],
        ['quiet_town', t('wizard.prefEnvironmentQuietTown'), ['quiet', '安静', '小镇', '乡村', 'peaceful']],
      ]);
      return v ? { prefEnvironment: v } : null;
    }
    case 'afterGrad': {
      const v = matchOptions([
        ['stay', t('wizard.prefAfterGradStay'), ['stay', '留下', '留下来', '定居', '留在']],
        ['return_home', t('wizard.prefAfterGradReturnHome'), ['return home', '回国', '回国发展', 'go back']],
        ['hometown', t('wizard.prefAfterGradHometown'), ['hometown', '家乡']],
        ['undecided', t('wizard.prefAfterGradUndecided'), ['undecided', 'not sure', '不知道', '还没想好', '没决定']],
      ]);
      return v ? { prefAfterGrad: v } : null;
    }
    case 'pressure': {
      const v = matchOptions([
        ['low', t('wizard.prefPressureLow'), ['take it easy', '轻松', '低压', '佛系', 'relaxed']],
        ['medium', t('wizard.prefPressureMedium'), ['moderate', '适中', '中等']],
        ['high', t('wizard.prefPressureHigh'), ['intensity', '高压', '高强度', 'intense']],
      ]);
      return v ? { prefPressure: v } : null;
    }
    case 'teaching': {
      const v = matchOptions([
        ['lecture', t('wizard.prefTeachingLecture'), ['lecture', '讲座', '大课']],
        ['seminar', t('wizard.prefTeachingSeminar'), ['seminar', '研讨', '讨论']],
        ['hands_on', t('wizard.prefTeachingHandsOn'), ['hands-on', 'practice', '实践', '动手']],
      ]);
      return v ? { prefTeaching: v } : null;
    }
    default:
      return null;
  }
}

/**
 * P0-4 (re-test task 6): map one just-submitted answer locally, so a
 * failed model turn can be preserved across the fallback switch
 * instead of dropped. Same understanding as the guided queue
 * (mapLocalAnswer + the countries-note rule), plus the two cases the
 * local mapper has no branch for: salary ("60000 GBP" / "60000" —
 * the re-test's lost answer) and city free text. Returns null when
 * nothing maps, and for questions — the caller then prefills the text
 * into the guided input so one tap re-sends it instead of retyping.
 * Exported for tests (tests/test_p0_retest6.py, via a node harness).
 */
export function mapFailedPrefAnswer(
  text: string,
  q: PrefQId | null,
  t: (k: string) => string,
  profile: Profile,
): { patch: Partial<Profile>; verbatim: string } | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  // A question is never mapped as an answer ("瑞士有哪些好学校？"
  // names a country but asks about it — mapping it would record a
  // preference the user never stated). The caller prefills it instead.
  if (looksLikeQuestion(trimmed)) return null;
  if (q === 'salary') {
    const m = trimmed.match(/(\d+(?:\.\d+)?)\s*(GBP|SGD|USD|CHF)?/i);
    if (!m) return null;
    const amount = Number(m[1]);
    if (!Number.isFinite(amount) || amount <= 0) return null;
    const currency = (m[2]?.toUpperCase() as 'GBP' | 'SGD' | 'USD' | 'CHF' | undefined)
      ?? (profile.prefSalaryCurrency as 'GBP' | 'SGD' | 'USD' | 'CHF' | undefined)
      ?? 'GBP';
    return { patch: { prefSalary: amount, prefSalaryCurrency: currency }, verbatim: trimmed };
  }
  if (q === 'city') {
    return { patch: { prefCity: trimmed }, verbatim: trimmed };
  }
  if (q === 'countries') {
    const mapped = mapLocalAnswer('countries', trimmed, t, profile);
    const patch: Partial<Profile> = { ...(mapped ?? {}) };
    if (hasExtraWordsBeyondCountries(trimmed, t, enMessages as Record<string, string>)) {
      // Round 14, P2a: the note is one atom in the summary — store
      // it joined with '·', never with a separator prefSummary
      // splits into separate atoms.
      patch.prefCountriesNote = normaliseCountryNote(trimmed);
    }
    if (!Object.keys(patch).length) {
      // No country code matched: keep the whole sentence as the note
      // (an unlisted country, or a reason for one) — the words are
      // preserved instead of dropped.
      patch.prefCountriesNote = normaliseCountryNote(trimmed);
    }
    return { patch, verbatim: trimmed };
  }
  if (q) {
    const mapped = mapLocalAnswer(q, trimmed, t, profile);
    if (mapped) return { patch: mapped, verbatim: trimmed };
    return null;
  }
  // No question context: only a country mention is safe to map.
  const mapped = mapLocalAnswer('countries', trimmed, t, profile);
  if (mapped) return { patch: mapped, verbatim: trimmed };
  // Round 26 W1: a timeout with no question context (the model
  // considered the chat done, or the question was skipped) must not
  // drop an exact enum answer — "大学城" is unambiguously the campus
  // environment and "很冷" is unambiguously cool, whatever the
  // question was. The same exact-match discipline as the guided
  // queue (mapLocalAnswer): only a chip label / listed synonym ever
  // maps. Free text never becomes a city here — with no question
  // context that would be a guess — and a question is never mapped
  // (checked above).
  for (const eq of ['climate', 'environment', 'afterGrad', 'pressure', 'teaching'] as const) {
    const enumMapped = mapLocalAnswer(eq, trimmed, t, profile);
    if (enumMapped) return { patch: enumMapped, verbatim: trimmed };
  }
  return null;
}

/**
 * Round 27 W4: is a stored history string a bare UI choice label for
 * the answer this question already holds? preserveFailedAnswer stores
 * the just-tapped label verbatim ("适中", "苏黎世"), so the guided
 * history would freeze it in the tap-time locale. A bare label —
 * exactly the localised label of the STORED value, in any locale —
 * re-localises through answerText() instead; the user's own sentence
 * (a reason, extra words, a question) never matches and stays
 * verbatim. Salary is never a label. Exported for tests
 * (tests/test_r27_w4.py, via a node harness).
 */
export function isBareChoiceLabel(
  q: PrefQId, text: string, profile: Profile,
): boolean {
  const refs = choiceRefsForLabel(text);
  if (!refs.length) return false;
  switch (q) {
    case 'countries':
      return refs.some((r) => r.group === 'countries' && (profile.prefCountries ?? []).includes(r.value));
    case 'climate':
      return refs.some((r) => r.group === 'climate' && r.value === profile.prefClimate);
    case 'environment':
      return refs.some((r) => r.group === 'environment' && r.value === profile.prefEnvironment);
    case 'city': {
      const canonical = canonicalCityName(profile.prefCity ?? '');
      return refs.some((r) => r.group === 'city' && (r.value === canonical || r.value === profile.prefCity));
    }
    case 'afterGrad':
      return refs.some((r) => r.group === 'afterGrad' && r.value === profile.prefAfterGrad);
    case 'pressure':
      return refs.some((r) => r.group === 'pressure' && r.value === profile.prefPressure);
    case 'teaching':
      return refs.some((r) => r.group === 'teaching' && r.value === profile.prefTeaching);
    case 'salary':
      return false;
  }
}

/**
 * Round 27 W4: the user bubble of one model-led turn, in the CURRENT
 * locale. A chip tap sends its localised label as the message, and
 * the turn stores that frozen string — after a language switch the
 * bubble stayed in the tap-time locale ("苏黎世", "适中"). When the
 * message is exactly one known choice label (any locale) it renders
 * through that choice's current-locale label instead; anything else
 * — free text, a question, a salary, an ambiguous label ("新加坡"
 * is both a country and a city) — stays verbatim, the user's own
 * words. The turn's stored `question` is unchanged: it is the record
 * of what was sent (Round 27 W1 — a language switch never re-sends
 * it to the backend).
 * Exported for tests (tests/test_r27_w4.py, via a node harness).
 */
export function prefTurnUserText(question: string, t: (k: string) => string): string {
  const refs = choiceRefsForLabel(question);
  if (refs.length !== 1) return question;
  return choiceLabelFor(refs[0], t);
}

/** One field of a parse confirmation, stored structured (locale key +
 * raw value, plus an existing locale key when the value is an enum) so
 * the bubble renders in the current locale at render time. */interface ParseSummaryEntry { key: string; value: string; valueKey?: string; }

/**
 * Map a /profile/parse result onto the flat wizard Profile. Only
 * academic / language facts are mapped (curriculum, scores, degree,
 * GRE/GMAT, intake year). The parse schema's budget is deliberately
 * NOT mapped: it is a tuition budget, and PrefChat has no
 * tuition-budget question (the salary question asks for an expected
 * salary, not a budget) — applying it would misread the user's words.
 * Out-of-range values never reach here: the backend reports them in
 * `unparsed` instead of `parsed_profile`. Returns null when nothing
 * mappable was parsed.
 */
function mapParseToProfile(
  parsed: Record<string, unknown>,
  profile: Profile,
): { patch: Partial<Profile>; summary: ParseSummaryEntry[] } | null {
  const patch: Partial<Profile> = {};
  const summary: ParseSummaryEntry[] = [];
  const under = (parsed.undergrad_profile ?? {}) as Record<string, unknown>;
  const mast = (parsed.masters_profile ?? {}) as Record<string, unknown>;
  const lang = (parsed.language ?? {}) as Record<string, unknown>;
  const num = (v: unknown): number | undefined =>
    (typeof v === 'number' && !Number.isNaN(v) ? v : undefined);

  const curriculum = under.curriculum;
  if (typeof curriculum === 'string') {
    const key: Record<string, string> = {
      cn_gaokao: 'wizard.curriculumCnGaokao', uk_alevel: 'wizard.curriculumUk',
      sg_alevel: 'wizard.curriculumSg', ib: 'wizard.curriculumIb',
      usa: 'wizard.curriculumUsa', other: 'wizard.curriculumOther',
    };
    patch.curriculum = curriculum as Profile['curriculum'];
    summary.push({ key: 'wizard.parseCurriculum', value: curriculum, valueKey: key[curriculum] });
  }
  const gaokao = num(under.gaokao_score);
  if (gaokao !== undefined) { patch.gaokaoScore = gaokao; summary.push({ key: 'wizard.parseGaokao', value: String(gaokao) }); }
  const gaokaoTotal = num(under.gaokao_total);
  if (gaokaoTotal !== undefined) { patch.gaokaoTotal = gaokaoTotal; summary.push({ key: 'wizard.parseGaokaoTotal', value: String(gaokaoTotal) }); }
  const sat = num(under.sat_total);
  if (sat !== undefined) { patch.satTotal = sat; summary.push({ key: 'wizard.parseSat', value: String(sat) }); }
  const act = num(under.act_composite);
  if (act !== undefined) { patch.actComposite = act; summary.push({ key: 'wizard.parseAct', value: String(act) }); }
  const ib = num(under.ib_total);
  if (ib !== undefined) { patch.ibTotal = ib; summary.push({ key: 'wizard.parseIb', value: String(ib) }); }
  if (Array.isArray(under.a_level_grades) && under.a_level_grades.length) {
    const grades = under.a_level_grades.filter((g): g is string => typeof g === 'string').join('');
    if (grades) { patch.alevels = grades; summary.push({ key: 'wizard.parseAlevel', value: grades }); }
  }
  const degreeField = mast.degree_field;
  if (typeof degreeField === 'string' && !profile.degree) {
    patch.degree = degreeField;
    summary.push({ key: 'wizard.parseDegree', value: degreeField });
  }
  const degreeClass = mast.degree_class;
  if (typeof degreeClass === 'string') {
    const key: Record<string, string> = {
      first: 'wizard.degreeClassFirst', upper_second: 'wizard.degreeClassUpperSecond',
      lower_second: 'wizard.degreeClassLowerSecond', third: 'wizard.degreeClassThird',
      other: 'wizard.degreeClassOther',
    };
    patch.degreeClass = degreeClass as Profile['degreeClass'];
    summary.push({ key: 'wizard.parseDegreeClass', value: degreeClass, valueKey: key[degreeClass] });
  }
  const itYears = num(mast.it_experience_years);
  if (itYears !== undefined) { patch.itExperienceYears = itYears; summary.push({ key: 'wizard.parseItYears', value: String(itYears) }); }
  const gre = num(mast.gre_total);
  if (gre !== undefined) { patch.greTotal = gre; summary.push({ key: 'wizard.parseGre', value: String(gre) }); }
  const gmat = num(mast.gmat_total);
  if (gmat !== undefined) { patch.gmat = gmat; summary.push({ key: 'wizard.parseGmat', value: String(gmat) }); }
  if (typeof lang.overall === 'number') { patch.ieltsOverall = lang.overall; summary.push({ key: 'wizard.parseIelts', value: String(lang.overall) }); }
  const toefl = num(lang.toefl_overall);
  if (toefl !== undefined) { patch.toefl = toefl; summary.push({ key: 'wizard.parseToefl', value: String(toefl) }); }
  // IELTS components only — the frontend has no TOEFL component fields.
  if (lang.exam === 'ielts' || (lang.overall !== undefined && lang.toefl_overall === undefined)) {
    const comps: [string, string, 'ieltsListening' | 'ieltsReading' | 'ieltsWriting' | 'ieltsSpeaking'][] = [
      ['listening', 'wizard.parseIeltsListening', 'ieltsListening'],
      ['reading', 'wizard.parseIeltsReading', 'ieltsReading'],
      ['writing', 'wizard.parseIeltsWriting', 'ieltsWriting'],
      ['speaking', 'wizard.parseIeltsSpeaking', 'ieltsSpeaking'],
    ];
    for (const [field, key, profileField] of comps) {
      const v = num(lang[field]);
      if (v !== undefined) { patch[profileField] = v; summary.push({ key, value: String(v) }); }
    }
  }
  const intake = num(parsed.target_intake);
  if (intake !== undefined) { patch.intakeYear = intake; summary.push({ key: 'wizard.parseIntake', value: String(intake) }); }
  if (!Object.keys(patch).length) return null;
  return { patch, summary };
}

/** One model-led turn: the user's verbatim message + the pref-chat
 * reply the model gave for it (plus the locale it was answered in).
 * Round 27 W1: a stored reply is an immutable record — it is shown
 * exactly as answered, in the locale it was answered in, and a
 * language switch never re-fetches or rewrites it; an offline turn
 * says so plainly. Round 8: the turn
 * is pushed OPTIMISTICALLY (pending) the moment the user taps a chip
 * or sends — the user's own message must show at once, not after the
 * ~30s model wait. `id` lets the reply update that exact turn. */
interface PrefTurn {
  id: number;
  question: string;
  reply: PrefChatReply | null;
  replyLocale: Locale | null;
  offline: boolean;
  pending: boolean;
  /** Round 16: the WHY follow-up that belongs to this turn — its
   * question, the user's verbatim answer once given, and whether
   * they skipped it. First-class turn state (see PrefTurnWhy in
   * lib/chat): the WHY question + answer render inside this turn's
   * block and persist with it, never as a detached bottom bubble. */
  why?: PrefTurnWhy | null;
}

export function PrefChat({ onDone }: { onDone: () => void }) {
  const { t, tf, locale, profile, updateProfile } = useApp();
  // Round 14, P1: the persisted snapshot (if any) is read once, on
  // mount, and seeds the state below — leaving the wizard mid-way
  // and returning resumes the chat instead of resetting it to 0/8.
  // A snapshot for a different profile is already discarded by
  // loadPersistedPrefChat (fingerprint mismatch).
  const [persistedSnapshot] = useState<PrefChatPersistedState | null>(
    () => loadPersistedPrefChat());
  const persistedRef = useRef(persistedSnapshot);
  // --- Guided-queue state (offline fallback; the pre-round-7 flow) ---
  const [qIndex, setQIndex] = useState(persistedSnapshot?.qIndex ?? 0);
  const [mood, setMood] = useState<PetMood>('celebrate');
  const [input, setInput] = useState('');
  /** A model call (chat, parse or pref-chat) is in flight. */
  const [thinking, setThinking] = useState(false);
  /** Round 9, R6: seconds spent waiting on the model, for the visible
   * progress line — a bare "想想……" with no progress is what the
   * re-test flagged. */
  const thinkingElapsed = useElapsed(thinking);
  /** The backend is being woken (a retry is in flight after the first
   * attempt failed): show the waking line, not the offline line. */
  const [waking, setWaking] = useState(false);
  /** True once a model call has failed or come back template-only:
   * the chat says so plainly and keeps working on the guided
   * questions + local understanding. Reset on the next model success. */
  const [aiOffline, setAiOffline] = useState(persistedSnapshot?.mode === 'guided');
  /** Model answers to free-text questions (guided mode), kept per
   * question so they survive advancing. Round 14, P1: restored from
   * the persisted snapshot, so they survive leaving the wizard too. */
  const [modelTurns, setModelTurns] = useState<{
    id: number; q: PrefQId; question: string;
    reply: ChatReply | null; replyLocale: Locale | null; offline: boolean; pending: boolean;
  }[]>(() => (persistedSnapshot?.modelTurns ?? []).map((x) => ({
    ...x, q: x.q as PrefQId, replyLocale: x.replyLocale as Locale | null, pending: false,
  })));
  /** A parse that understood academic/language facts and waits for the
   * user to confirm — nothing here is applied until they say yes. */
  const [pendingParse, setPendingParse] = useState<null | {
    q: PrefQId; text: string;
    patch: Partial<Profile>; summary: ParseSummaryEntry[];
  }>(null);
  /** The user's verbatim free-text sentence per guided question
   * (round 7, Fix 2): the guided history renders the sentence the
   * user actually typed, never a bare keyword the local mapper
   * reduced it to. Chip answers have no verbatim text — they render
   * from the Profile via answerText(), which stays locale-safe. */
  const [verbatim, setVerbatim] = useState<Partial<Record<PrefQId, string>>>(
    () => (persistedSnapshot?.verbatim ?? {}) as Partial<Record<PrefQId, string>>);
  // --- Model-led state (round 7) ---
  /** 'model' = the pref-chat conversation; 'guided' = the offline
   * fallback queue. The chat starts model-led; a failed or
   * template-only pref-chat call switches it to guided. */
  const [mode, setMode] = useState<'model' | 'guided'>(persistedSnapshot?.mode ?? 'model');
  const [turns, setTurns] = useState<PrefTurn[]>(() => (persistedSnapshot?.turns ?? []).map((x) => ({
    ...x, replyLocale: x.replyLocale as Locale | null, pending: false,
  })));
  /** The server's last `next_question` (undefined = no model answer
   * yet); null means the server says all 8 are known. */
  const [serverNext, setServerNext] = useState<PrefNextQuestion | undefined>(persistedSnapshot?.serverNext);
  /** Questions the user skipped in the model-led chat (local only —
   * never sent to the server, never applied). */
  const [skipped, setSkipped] = useState<PrefQId[]>(() => (persistedSnapshot?.skipped ?? []) as PrefQId[]);
  /** A pref-chat extraction waiting for confirmation — nothing here
   * is applied until the user says yes. Round 15: restored from the
   * persisted snapshot, so leaving with an unconfirmed extraction
   * keeps both the confirm bubble and the progress count (the count
   * merges this pending extraction — see knownForProgress). */
  const [pendingExtract, setPendingExtract] = useState<null | {
    extracted: PrefExtracted; rawText: string;
  }>(persistedSnapshot?.pendingExtract ?? null);
  /** Every "noted" bubble, in order — the WHY answer and each confirm
   * summary. Round 15: a list, restored from the persisted snapshot.
   * Round 14 kept only the latest one in a transient slot (answering
   * WHY and then confirming overwrote the WHY answer even before
   * leaving, and leaving lost the slot entirely). */
  const [confirmedNotes, setConfirmedNotes] = useState<string[]>(
    () => [...(persistedSnapshot?.confirmedNotes ?? [])]);
  /** The user text whose pref-chat call failed (kept so the retry
   * action can re-send it instead of dropping the user's words). */
  const [failedText, setFailedText] = useState<string | null>(persistedSnapshot?.failedText ?? null);
  /** P0-3 (re-test task 6): a country was recorded without a reason
   * behind it — a chip tap ("瑞士") carries no reason, so without a
   * follow-up the reason is never volunteered and never recorded.
   * While set, the chat asks why (one follow-up, skippable) in both
   * paths; the answer is stored verbatim as prefCountriesNote.
   * Round 13: `note` carries a reason that arrived WITH the
   * countries in the same turn ("环境优美") — the bubble then asks
   * what that reason means to the user instead of asking why from
   * scratch. */
  const [awaitingReason, setAwaitingReason] = useState<{ countries: string[]; note?: string; turnId?: number } | null>(persistedSnapshot?.awaitingReason ?? null);
  /** Salary input for the model-led chat (local only — the amount is
   * sent as a message and applied only after confirmation). */
  const [modelSalary, setModelSalary] = useState('');
  const [modelSalaryCur, setModelSalaryCur] = useState<'GBP' | 'SGD' | 'USD' | 'CHF'>('GBP');
  const bottomRef = useRef<HTMLDivElement>(null);
  const moodTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  /** Monotonic turn ids, so an optimistic turn can be updated in
   * place when its reply lands (round 8). Seeded past any restored
   * turn id, so a resumed chat never reuses an id. */
  const turnIdRef = useRef(Math.max(0,
    ...(persistedSnapshot?.turns ?? []).map((x) => x.id),
    ...(persistedSnapshot?.modelTurns ?? []).map((x) => x.id)));
  const nextTurnId = () => { turnIdRef.current += 1; return turnIdRef.current; };

  // Resume: the store hydrates the Profile from localStorage after
  // mount, but the raw stored profile is readable right away — resume
  // the guided queue at the first unanswered question so a refresh
  // never loses answers. Skipped when a persisted snapshot was
  // restored: its qIndex already is where the user left off (a
  // skipped question must not pull the queue back).
  useEffect(() => {
    if (persistedRef.current) return;
    try {
      const raw = localStorage.getItem('pp-profile');
      if (raw) setQIndex(firstUnanswered({ ...emptyProfile, ...JSON.parse(raw) }));
    } catch { /* ignore corrupt storage */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Round 14, P1: persist the chat's own turn/progress state on
   * every change, so leaving the wizard mid-way and returning
   * resumes it. The fingerprint is the stored Profile's, so a blob
   * for a reset profile is never written over a live one. Guard:
   * before the store hydrates, `profile` is still the empty profile
   * — writing then would overwrite a restored blob with an
   * empty-profile fingerprint, so that write is skipped until the
   * hydrated profile arrives. */
  const restoredFingerprintRef = useRef(persistedSnapshot?.fingerprint ?? null);
  useEffect(() => {
    try {
      const fp = prefChatFingerprint(profile);
      const emptyFp = prefChatFingerprint(emptyProfile);
      if (fp === emptyFp && restoredFingerprintRef.current && restoredFingerprintRef.current !== emptyFp) return;
      localStorage.setItem(PREF_CHAT_KEY, serializePrefChatState(
        { mode, turns, modelTurns, qIndex, skipped, serverNext, awaitingReason, verbatim, failedText, pendingExtract, confirmedNotes }, fp));
    } catch { /* ignore storage errors */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, turns, modelTurns, qIndex, skipped, serverNext, awaitingReason, verbatim, failedText, pendingExtract, confirmedNotes, profile]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [qIndex, profile, modelTurns, thinking, turns, pendingExtract, mode, confirmedNotes]);

  useEffect(() => () => { if (moodTimerRef.current) clearTimeout(moodTimerRef.current); }, []);

  const flashMood = (m: PetMood) => {
    setMood(m);
    if (moodTimerRef.current) clearTimeout(moodTimerRef.current);
    moodTimerRef.current = setTimeout(() => setMood('idle'), 1600);
  };

  // --- Derived model-led state ---------------------------------------------
  const known: PrefKnown = knownFromProfile(profile);
  /** Round 8: progress counts what the model already understood — a
   * pending extraction counts at once, not only after the user taps
   * confirm. The next question still comes from the confirmed set, so
   * nothing is treated as answered before confirmation. */
  const knownForProgress: PrefKnown = pendingExtract
    ? mergeKnownWithExtracted(known, pendingExtract.extracted)
    : known;
  const answeredCount = countKnownPrefs(knownForProgress);
  const missingQs = PREF_QUESTIONS.filter((q) => !isPrefKnown(q, knownForProgress));
  /** The next question to offer chips for: the server's answer when
   * it is still unanswered, else the first missing preference — and
   * never a skipped one. Null when nothing is left to ask. */
  const rawNext: PrefNextQuestion = serverNext !== undefined ? serverNext : firstMissingPref(known);
  const nextQ: PrefNextQuestion = effectiveNextPref(rawNext, known, skipped);
  const modelDone = nextQ === null;
  const remainingLabel = joinList(missingQs.map((q) => t(prefQuestionNameKey(q))), locale);

  /** Switch to the guided queue with the honest offline line. The
   * guided queue resumes at the first unanswered question. `base`
   * is the profile to resume from — the caller passes the merged
   * profile when it just applied a preserved answer (P0-4), so the
   * queue resumes PAST the just-answered question instead of
   * re-asking it from the stale closure profile. */
  const enterGuidedMode = (base?: Profile) => {
    setMode('guided');
    setAiOffline(true);
    // Round 17, P0: the pending extraction is KEPT across the drop —
    // discarding it here is exactly how a stated country was silently
    // lost (re-test task 11: Switzerland sat unconfirmed in the
    // pending extraction when the model dropped, and this line threw
    // it away). The confirm bubble is re-offered in the guided branch
    // below, so the user can still confirm or dismiss it there; a
    // drop never silently drops what the model understood.
    setWaking(false);
    setAwaitingReason(null);
    setQIndex(firstUnanswered(base ?? profile));
  };

  /** P0-4 (re-test task 6): a failed turn must not lose the user's
   * answer (2 of 6 turns failed over and the just-submitted answer —
   * e.g. salary 60000 — had to be re-entered). The text is mapped
   * locally against the question it answered and applied at once, so
   * the guided queue resumes past it; when nothing maps, the text is
   * prefilled into the guided input so one tap re-sends it instead of
   * retyping. A question is never mapped as an answer. */
  const preserveFailedAnswer = (trimmed: string, q: PrefQId | null, turnId: number) => {
    // Round 15: append-only on a model drop — the just-sent turn is
    // marked offline in place, never deleted, so the user's bubble
    // and the earlier history stay visible when guided mode takes over.
    setTurns((prev) => markTurnOffline(prev, turnId));
    // mapFailedPrefAnswer returns null for questions and for anything
    // it cannot map — those are prefilled, never dropped.
    const preserved = mapFailedPrefAnswer(trimmed, q, t, profile);
    if (preserved) {
      if (q) setVerbatim((prev) => ({ ...prev, [q]: preserved.verbatim }));
      setFailedText(null);
      updateProfile(preserved.patch);
      enterGuidedMode({ ...profile, ...preserved.patch });
      // Round 13: the gateway-down failure used to drop the
      // why-follow-up entirely — enterGuidedMode clears it and the
      // guided queue resumes PAST the already-answered countries
      // question, so the chat went straight to climate with no
      // reason ever asked. Re-arm it here when the preserved answer
      // added countries and no reason was on file before this turn
      // (same rule as the model path).
      const knownCountries = profile.prefCountries ?? [];
      const newCountries = (preserved.patch.prefCountries ?? []).filter((c) => !knownCountries.includes(c));
      if (shouldAskCountryWhy(newCountries, profile.prefCountriesNote)) {
        // Round 16: anchor the WHY to the preserved turn (its id)
        // and record it on the turn — the guided branch renders
        // renderPrefTurns above the offline banner, so the WHY
        // question + answer stay with the turn instead of vanishing
        // when the mode switches.
        const note = preserved.patch.prefCountriesNote?.trim() || undefined;
        setAwaitingReason({ countries: newCountries, ...(note ? { note } : {}), turnId });
        setTurns((prev) => prev.map((x) => (x.id === turnId && !x.why
          ? { ...x, why: { countries: newCountries, ...(note ? { note } : {}), answer: null, skipped: false } }
          : x)));
      }
      return;
    }
    setFailedText(trimmed);
    setInput(trimmed);
    enterGuidedMode();
  };

  /** Round 14, P0: arm the WHY follow-up from a pref-chat reply the
   * moment it lands — the backend's `why_followup` when present,
   * else the same rule derived from this turn's extraction against
   * the known set BEFORE the turn. The question then renders in the
   * FIRST reply of the turn, in both the model-up path and the
   * template (gateway-down) path — never behind the confirm chip.
   * Round 15: `turnId` anchors the bubble to THIS turn (see
   * renderPrefTurns): without it the bubble rendered after the
   * confirm bubble, so the first visible reply ended with the
   * climate question and the WHY only appeared underneath the
   * confirm prompt. confirmExtract keeps its own re-arm as a
   * backstop, and only fires when the reason is still unanswered. */
  const armWhyFromReply = (r: PrefChatReply, knownBefore: PrefKnown, turnId?: number) => {
    const w = r.why_followup;
    let why: { countries: string[]; note?: string } | null = null;
    if (w && w.countries?.length) {
      why = { countries: w.countries, ...(w.note ? { note: w.note } : {}) };
    } else {
      why = whyFollowupFromExtracted(r.extracted, knownBefore);
    }
    if (!why) return;
    setAwaitingReason({ ...why, ...(turnId !== undefined ? { turnId } : {}) });
    // Round 16: the WHY belongs to THIS turn — record it on the
    // turn as well, so the question stays in the turn's history
    // (and survives leave-and-return) even after awaitingReason is
    // cleared by the answer. An already-recorded WHY is never
    // overwritten (its answer / skipped state is history now).
    if (turnId !== undefined) {
      // A fresh const: the `let` above loses its non-null narrowing
      // inside the setTurns closure.
      const armedWhy: { countries: string[]; note?: string } = why;
      setTurns((prev) => prev.map((x) => (x.id === turnId && !x.why
        ? { ...x, why: { ...armedWhy, answer: null, skipped: false } }
        : x)));
    }
  };

  /** Set the pending extraction, folding a new understanding into an
   * existing unconfirmed one instead of overwriting it (Round 16):
   * the input stays live while a confirm is pending, so a new reply
   * can land before the old extraction is confirmed — overwriting it
   * would silently drop what the model understood from the earlier
   * turn. The merged whole is still confirmed by one tap. */
  const setPendingExtractMerged = (extracted: PrefExtracted, rawText: string) => {
    setPendingExtract((prev) => (prev
      ? { extracted: mergeExtracted(prev.extracted, extracted), rawText: prev.rawText }
      : { extracted, rawText }));
  };

  /** One model-led turn: message + known prefs + history to the
   * pref-chat endpoint. A template-only reply with NO extraction, or
   * any failure, falls back to the guided queue — never a faked AI
   * answer. Round 10: a template reply that still carries a
   * deterministic extraction is kept as an offline turn with its
   * confirmation bubble, so the user's words are recorded instead
   * of dropped. Round 8: the turn is pushed optimistically first,
   * so the user's message shows at once; on failure it is removed
   * again (the guided queue does not render model turns — the retry
   * there re-sends the words). */
  const sendToPrefChat = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || thinking) return;
    // P0-4: the question this turn answers — needed to preserve the
    // answer locally if the call falls back to guided mode.
    const questionAtSend: PrefQId | null = nextQ as PrefQId | null;
    setThinking(true);
    setWaking(false);
    const requestLocale = locale;
    // Round 16: the request's `known` folds in an unconfirmed
    // extraction, so answering the next question while a confirm is
    // pending does not make the server re-ask what it already
    // understood. Nothing is APPLIED here — the profile still waits
    // for the user's confirm tap.
    const requestKnown = pendingExtract
      ? mergeKnownWithExtracted(knownFromProfile(profile), pendingExtract.extracted)
      : knownFromProfile(profile);
    const turnId = nextTurnId();
    setTurns((prev) => [...prev, { id: turnId, question: trimmed, reply: null, replyLocale: null, offline: false, pending: true }]);
    const history: ChatHistoryTurn[] = [];
    for (const turn of turns) {
      if (!turn.reply || !isModelPrefReply(turn.reply)) continue;
      history.push({ role: 'user', content: turn.question });
      history.push({ role: 'assistant', content: turn.reply.lines.join(' ') });
    }
    try {
      const r = await fetchJsonChat<PrefChatReply>('/api/assistant/pref-chat', {
        method: 'POST',
        body: JSON.stringify({ message: trimmed, locale: requestLocale, known: requestKnown, history: history.slice(-6) }),
      }, {
        // Round 15: chat turns are bounded to ~20 s total — the old
        // 40 s attempt / 90 s budget aborted healthy turns and
        // retried the whole model call, stacking to 1-2 min of
        // silence on the first turn of an outage.
        onRetry: () => setWaking(true),
      });
      setWaking(false);
      if (!isModelPrefReply(r)) {
        // Round 10: a template reply that still carries a
        // deterministic extraction (country + reason matched without
        // a model) is NOT dropped — the turn stays, labelled offline,
        // and the confirmation bubble offers it, so the user's words
        // are recorded instead of lost when the guided queue takes
        // over without replaying the sentence.
        if (r.extracted && Object.keys(r.extracted).length > 0) {
          setAiOffline(true);
          setFailedText(null);
          setTurns((prev) => prev.map((x) => (x.id === turnId ? { ...x, reply: r, replyLocale: requestLocale, offline: true, pending: false } : x)));
          if (r.next_question !== undefined) setServerNext(r.next_question);
          // Round 16: fold into a still-pending extraction instead
          // of overwriting it — see setPendingExtractMerged.
          setPendingExtractMerged(r.extracted, trimmed);
          // Round 14, P0: the WHY follow-up belongs to THIS reply —
          // arm it now, not when the user confirms the extraction.
          // Round 15: anchored to this turn's id, so the bubble
          // renders with this reply, before the confirm bubble.
          armWhyFromReply(r, requestKnown, turnId);
          flashMood('celebrate');
          return;
        }
        // P0-4: preserve the just-submitted answer across the
        // fallback switch instead of dropping it.
        preserveFailedAnswer(trimmed, questionAtSend, turnId);
        return;
      }
      setAiOffline(false);
      setFailedText(null);
      setTurns((prev) => prev.map((x) => (x.id === turnId ? { ...x, reply: r, replyLocale: requestLocale, offline: false, pending: false } : x)));
      if (r.next_question !== undefined) setServerNext(r.next_question);
      if (r.extracted && Object.keys(r.extracted).length > 0) {
        // Round 16: fold into a still-pending extraction instead of
        // overwriting it — see setPendingExtractMerged.
        setPendingExtractMerged(r.extracted, trimmed);
        // Round 14, P0: the WHY follow-up belongs to THIS reply —
        // arm it now, not when the user confirms the extraction.
        // Round 15: anchored to this turn's id, so the bubble
        // renders with this reply, before the confirm bubble.
        armWhyFromReply(r, requestKnown, turnId);
      }
      flashMood('celebrate');
    } catch {
      setWaking(false);
      // P0-4: preserve the just-submitted answer across the fallback
      // switch instead of dropping it.
      preserveFailedAnswer(trimmed, questionAtSend, turnId);
    } finally {
      setThinking(false);
    }
  };

  /** Retry the model-led chat from the guided fallback: the failed
   * message (if any) is re-sent so the user's words are not dropped.
   * Round 17, P0: the pending extraction is KEPT — the re-send's
   * extraction folds into it (setPendingExtractMerged) instead of
   * the retry silently discarding what the model already understood. */
  const retryModelChat = () => {
    setMode('model');
    setAiOffline(false);
    setWaking(false);
    const text = failedText;
    setFailedText(null);
    if (text) void sendToPrefChat(text);
  };

  /** Confirm a pending extraction: apply it to the Profile, then
   * show the "noted" bubble with what was understood, in the user's
   * own words. */
  const confirmExtract = () => {
    if (!pendingExtract) return;
    const summary = extractedSummary(pendingExtract.extracted, t, locale);
    const patch = profilePatchFromExtracted(pendingExtract.extracted, profile);
    // P0-3: a newly recorded country asks why — a chip tap carries
    // no reason, so without this the reason is never volunteered and
    // never recorded (re-test task 6: the chat never asked why
    // Switzerland, and "环境优美" appears nowhere). Round 13: a
    // reason that arrived in THIS extraction ("环境优美" next to
    // "瑞士") no longer suppresses the ask — the chat confirmed the
    // phrase but never asked what it means, and went straight to
    // climate. Only a reason from an EARLIER turn suppresses it
    // (shouldAskCountryWhy). The same rule serves the model-up path
    // and the gateway-down template-fallback path: both confirm here.
    const knownCountries = profile.prefCountries ?? [];
    const newCountries = (pendingExtract.extracted.countries ?? []).filter((c) => !knownCountries.includes(c));
    setPendingExtract(null);
    if (patch) updateProfile(patch);
    // Round 15: append — never overwrite. The old single slot erased
    // the WHY answer the moment the user confirmed the extraction
    // (and leaving lost the slot entirely); each noted bubble is its
    // own entry in the persisted list now.
    setConfirmedNotes((prev) => [...prev, summary]);
    flashMood('celebrate');
    if (shouldAskCountryWhy(newCountries, profile.prefCountriesNote)) {
      // Round 15: anchor the backstop WHY to the turn this extraction
      // came from (the latest turn), so it renders with that reply.
      const anchorId = turns.length ? turns[turns.length - 1].id : undefined;
      // Round 16: never re-arm a WHY the user already answered or
      // skipped on that turn (skip-then-confirm used to resurrect
      // it), and record the WHY on the turn when arming it here.
      const anchorTurn = anchorId !== undefined ? turns.find((x) => x.id === anchorId) : undefined;
      const whyResolved = !!anchorTurn?.why && (anchorTurn.why.answer !== null || anchorTurn.why.skipped);
      if (!whyResolved) {
        const note = pendingExtract.extracted.note?.trim() || undefined;
        setAwaitingReason({ countries: newCountries, ...(note ? { note } : {}), ...(anchorId !== undefined ? { turnId: anchorId } : {}) });
        if (anchorId !== undefined) {
          setTurns((prev) => prev.map((x) => (x.id === anchorId && !x.why
            ? { ...x, why: { countries: newCountries, ...(note ? { note } : {}), answer: null, skipped: false } }
            : x)));
        }
      }
    }
  };

  const dismissExtract = () => {
    setPendingExtract(null);
    flashMood('empathise');
  };

  /** P0-3: store the why-answer verbatim as the countries note. The
   * text IS the reason by construction — it was given in answer to
   * "why {countries}?" — so it is stored directly, never sent through
   * the model/parse path (which would misread it as an answer to the
   * next question). */
  const saveReason = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    // Round 17, P0: answering the WHY about a country IS implicit
    // confirmation of that country — the user just elaborated on why
    // they want it, so the pending extraction's countries for this
    // WHY land in the Profile NOW, in the same update as the note
    // (one updateProfile call: the note is computed once, so the two
    // values can never clobber each other). A drop after this can no
    // longer lose the country (re-test task 11: the confirm was never
    // tapped, the model dropped, and the pending extraction was
    // discarded with Switzerland still in it). Only the WHY's
    // countries land — anything else the pending extraction holds (a
    // later climate answer, the reason note) stays pending for the
    // confirm bubble, which keeps offering it.
    const whyCountries = awaitingReason?.countries ?? [];
    const { confirmedCountries, remaining } = splitWhyConfirmedCountries(
      pendingExtract?.extracted, whyCountries);
    // Round 14, P2a: the note is one summary atom — append joined
    // with '·', never with a separator prefSummary splits on.
    const patch: Partial<Profile> = {
      prefCountriesNote: appendCountryNote(profile.prefCountriesNote, trimmed),
    };
    if (confirmedCountries.length) {
      patch.prefCountries = [...new Set([...(profile.prefCountries ?? []), ...confirmedCountries])];
    }
    updateProfile(patch);
    if (confirmedCountries.length) {
      setPendingExtract((prev) => (prev
        ? (remaining ? { extracted: remaining, rawText: prev.rawText } : null)
        : prev));
    }
    // Round 16: a WHY anchored to a turn is answered ON that turn —
    // the acknowledgement renders inside the turn's block, right
    // after the WHY question, never as a detached bottom bubble. A
    // WHY with no turn to attach to (guided queue, old blob) keeps
    // the confirmedNotes bubble as its fallback (Round 15 behaviour).
    const anchorId = awaitingReason?.turnId;
    if (anchorId !== undefined && turns.some((x) => x.id === anchorId)) {
      setTurns((prev) => answerTurnWhy(prev, anchorId, trimmed, awaitingReason));
    } else {
      setConfirmedNotes((prev) => [...prev, trimmed]);
    }
    setAwaitingReason(null);
    setInput('');
    flashMood('celebrate');
  };

  /** Skip the why-follow-up (the reason stays unknown — unknown stays
   * unknown, never invented). Round 15: skipping the reason must not
   * erase the noted bubbles already shown — they are history now.
   * Round 16: a skipped WHY stays in its turn's history (the
   * question was asked) and the deferred question renders after it;
   * a turn-less WHY just clears. */
  const skipReason = () => {
    const anchorId = awaitingReason?.turnId;
    if (anchorId !== undefined) {
      setTurns((prev) => skipTurnWhy(prev, anchorId, awaitingReason));
    }
    setAwaitingReason(null);
  };

  /** Skip the current next question in the model-led chat (local
   * only — the server is never told, nothing is applied). */
  const skipNext = () => {
    if (!nextQ) return;
    setSkipped((prev) => [...prev, nextQ as PrefQId]);
  };

  /** The user's answer to one question, in their own words (labels for
   * chips, verbatim for free text) — rendered at render time so a
   * locale switch never leaves a stale-language bubble. */
  const answerText = (q: PrefQId): string => {
    switch (q) {
      case 'countries': {
        // Round 8: the free-text note is dropped when it says exactly
        // the same as a chosen country — "瑞士" next to "瑞士" is a
        // tautology; a note that adds words ("瑞士，因为那边环境优美")
        // is kept.
        const norm = (s: string) => s.replace(/[·、，,；;。.]/g, '').replace(/\s+/g, '').toLowerCase();
        const countryLabels = (profile.prefCountries ?? []).map((c) => t(`country.${c}`));
        const note = profile.prefCountriesNote ?? '';
        const parts = [...countryLabels, ...(note && !countryLabels.some((l) => norm(l) === norm(note)) ? [note] : [])].filter(Boolean);
        return joinList(parts, locale);
      }
      case 'climate': return climateLabel(profile.prefClimate, t);
      case 'environment': return environmentLabel(profile.prefEnvironment, t);
      // Round 9, R8c: the stored city is the canonical English name
      // ("Zurich") — the bubble shows the localised name ("苏黎世"),
      // never the raw stored value. Round 27 W4: a stored localised
      // name renders the same way via cityDisplayName's reverse map.
      case 'city': return cityDisplayName(profile.prefCity ?? '', t);
      case 'afterGrad': return afterGradLabel(profile.prefAfterGrad, t);
      case 'salary': return `${profile.prefSalary} ${profile.prefSalaryCurrency ?? ''}`.trim();
      case 'pressure': return pressureLabel(profile.prefPressure, t);
      case 'teaching': return teachingLabel(profile.prefTeaching, t);
    }
  };

  /** Round 27 W4: the guided history's answer bubble for one
   * question. A bare chip label frozen by preserveFailedAnswer
   * re-localises through answerText(); the user's own sentence stays
   * verbatim (see isBareChoiceLabel). */
  const guidedAnswerText = (q: PrefQId): string => {
    const v = verbatim[q];
    if (v && isBareChoiceLabel(q, v, profile)) return answerText(q);
    return v ?? answerText(q);
  };

  /**
   * The pet's own view after an answer. Only facts from the verified
   * catalogue (the merged v2 + expansion list) and the curated city
   * climate table are used: institution names per country,
   * verified-programme counts per city, and the best city for a wanted
   * climate WITHIN the chosen countries. When the chosen country has
   * no city of the wanted class, the pet says so honestly with the
   * actual classes of that country's real cities — it never pivots to
   * Edinburgh or any other country. With no country chosen yet, the
   * global best city is the only case where an unchosen city may be
   * named. Returns the locale key + vars, or null for a plain
   * acknowledgement. The mood follows the opinion: empathise when the
   * user is unsure or wants it easy, celebrate otherwise.
   */
  const opinion = (q: PrefQId, p: Profile): { key: string; vars?: Record<string, string | number>; mood: PetMood } | null => {
    switch (q) {
      case 'countries': {
        const codes = p.prefCountries ?? [];
        if (codes.includes('GB')) return { key: 'wizard.chatOpGB', vars: { schools: schoolsIn('GB', locale) }, mood: 'celebrate' };
        // Round 6: Singapore is warm all year round — if the user
        // already said they want cool weather (or four seasons), the
        // pet warns about the clash instead of celebrating Singapore.
        if (codes.includes('SG')) {
          const pref = normaliseClimatePref(p.prefClimate);
          if (pref === 'cool' || pref === 'four_seasons') return { key: 'wizard.chatOpSGCool', vars: { schools: schoolsIn('SG', locale) }, mood: 'empathise' };
          return { key: 'wizard.chatOpSG', vars: { schools: schoolsIn('SG', locale) }, mood: 'celebrate' };
        }
        return { key: 'wizard.chatOpThanks', mood: 'celebrate' };
      }
      case 'climate': {
        // Round 7: scoped to the chosen countries. No country chosen
        // yet is the ONLY case where the global best city may be named.
        // Round 8: the count is scoped to the user's track too — an
        // undergraduate must not be told Zurich has 11 programmes
        // when all 11 are taught-master's. The count says which level
        // it counts, and the city name is localised.
        const pref = normaliseClimatePref(p.prefClimate);
        if (!pref) return { key: 'wizard.chatOpThanks', mood: 'celebrate' };
        const climateName = climateLabel(pref, t);
        const codes = p.prefCountries ?? [];
        const track = p.track;
        const levelKey = track === 'undergraduate' ? 'wizard.trackUndergrad' : track === 'taught_masters' ? 'wizard.trackMasters' : null;
        if (codes.length) {
          const best = bestCityForClimateIn(pref, codes, allPrograms(), track);
          if (best) {
            const vars = { city: cityDisplayName(best.city, t), climate: climateName, count: best.count, ...(levelKey ? { level: t(levelKey) } : {}) };
            return { key: levelKey ? 'wizard.chatOpClimateCityLevel' : 'wizard.chatOpClimateCity', vars, mood: 'celebrate' };
          }
          const cities = countryCitiesWithClimate(codes, allPrograms());
          const desc = joinList(cities.map(({ city, climate }) => (climate ? parenNote(cityDisplayName(city, t), climateLabel(climate, t), locale) : cityDisplayName(city, t))), locale);
          if (desc) {
            return { key: 'wizard.chatOpClimateNoMatch', vars: { want: climateName, cities: desc }, mood: 'empathise' };
          }
          return { key: 'wizard.chatOpThanks', mood: 'celebrate' };
        }
        const best = bestCityForClimate(pref, allPrograms(), track);
        if (best) {
          const vars = { city: cityDisplayName(best.city, t), climate: climateName, count: best.count, ...(levelKey ? { level: t(levelKey) } : {}) };
          return { key: levelKey ? 'wizard.chatOpClimateCityLevel' : 'wizard.chatOpClimateCity', vars, mood: 'celebrate' };
        }
        return { key: 'wizard.chatOpThanks', mood: 'celebrate' };
      }
      case 'city': {
        // Round 8: the count is scoped to the user's track, says
        // which level it counts, and the city name is localised.
        const want = (p.prefCity ?? '').trim().toLowerCase();
        if (!want) return null;
        const track = p.track;
        const scoped = allPrograms().filter((x) => (x.city ?? '').toLowerCase() === want && (!track || x.degreeLevel === track));
        if (scoped.length > 0) {
          const levelKey = track === 'undergraduate' ? 'wizard.trackUndergrad' : track === 'taught_masters' ? 'wizard.trackMasters' : null;
          const vars = { city: cityDisplayName(p.prefCity ?? '', t), count: scoped.length, ...(levelKey ? { level: t(levelKey) } : {}) };
          return { key: levelKey ? 'wizard.chatOpCityLevel' : 'wizard.chatOpCity', vars, mood: 'celebrate' };
        }
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

  /** A pending parse belongs to its question: leaving the question
   * (chip tap, skip, back, restart) drops it instead of applying a
   * stale confirmation later. */
  useEffect(() => {
    setPendingParse((prev) => (prev && prev.q !== currentQ ? null : prev));
  }, [currentQ]);

  /** Round 27 W2: advance the guided queue to the next question the
   * profile does NOT answer yet — never by a bare +1. Answers can
   * arrive out of order (a model turn preserved across the drop to
   * guided mode, a pending extraction confirmed while the queue sits
   * elsewhere), so +1 re-asks known answers: re-test 21 answered
   * pressure in the chat, dropped to guided at salary, and had to
   * answer salary, pressure and teaching again. `p` is the profile
   * WITH the just-applied patch — the `profile` closure is stale at
   * call time. Landing past the last question (index 8) is the done
   * state: the summary renders, the queue never restarts. */
  const advanceGuided = (from: number, p: Profile) => {
    setQIndex(nextMissingPrefIndex(knownFromProfile(p), from));
  };

  const answerSingle = (q: PrefQId, patch: Partial<Profile>) => {
    updateProfile(patch);
    // The opinion needs the just-saved value, which is not in `profile`
    // yet at call time — compute it from the merged profile.
    const op = opinion(q, { ...profile, ...patch });
    flashMood(op?.mood ?? 'celebrate');
    setInput('');
    advanceGuided(QUESTIONS.indexOf(q) + 1, { ...profile, ...patch });
  };

  /** A free-text question goes to the real model (grounded, with the
   * earlier model turns as history). A template-only reply is shown
   * led by the offline line (round 10 — the verified template lines
   * are a real answer; discarding them used to leave nothing), never
   * as an AI answer. Round 8: the turn is pushed optimistically
   * first, so the user's question shows at once instead of after
   * the model wait. */
  const askModel = async (q: PrefQId, text: string) => {
    setThinking(true);
    setWaking(false);
    const requestLocale = locale;
    const turnId = nextTurnId();
    setModelTurns((prev) => [...prev, { id: turnId, q, question: text, reply: null, replyLocale: null, offline: false, pending: true }]);
    const history: ChatHistoryTurn[] = [];
    for (const turn of modelTurns) {
      if (!turn.reply || !isModelReply(turn.reply)) continue;
      history.push({ role: 'user', content: turn.question });
      history.push({ role: 'assistant', content: turn.reply.lines.join(' ') });
    }
    try {
      const r = await fetchJsonChat<ChatReply>('/api/assistant/chat', {
        method: 'POST',
        body: JSON.stringify({ message: text, locale: requestLocale, history: history.slice(-6) }),
      }, {
        // Round 15: bounded chat turn — see sendToPrefChat.
        onRetry: () => setWaking(true),
      });
      setWaking(false);
      if (!isModelReply(r)) {
        setAiOffline(true);
        // Round 10: keep the verified template lines (labelled
        // offline at render time) when the reply has any.
        setModelTurns((prev) => prev.map((x) => (x.id === turnId ? { ...x, reply: r.lines?.length ? r : null, replyLocale: r.lines?.length ? requestLocale : null, offline: true, pending: false } : x)));
        return;
      }
      setAiOffline(false);
      setModelTurns((prev) => prev.map((x) => (x.id === turnId ? { ...x, reply: r, replyLocale: requestLocale, offline: false, pending: false } : x)));
    } catch {
      setWaking(false);
      setAiOffline(true);
      setModelTurns((prev) => prev.map((x) => (x.id === turnId ? { ...x, reply: null, replyLocale: null, offline: true, pending: false } : x)));
    } finally {
      setThinking(false);
    }
  };

  /** A free-text answer to the current question, without the local
   * mapping: keep the existing verbatim behaviour (countries note /
   * city / free-text field value) — the opinion bubble still answers.
   * Fix 2: the verbatim sentence is kept for the history bubble, and
   * for countries a sentence that says more than the country names
   * (e.g. a reason) is stored whole as prefCountriesNote — the mapped
   * country code alone never drops the user's own words. */
  const applyLocalAnswer = (q: PrefQId, text: string) => {
    setVerbatim((prev) => ({ ...prev, [q]: text }));
    const mapped = mapLocalAnswer(q, text, t, profile);
    if (q === 'countries') {
      const patch: Partial<Profile> = { ...(mapped ?? {}) };
      if (hasExtraWordsBeyondCountries(text, t, enMessages as Record<string, string>)) {
        // Round 14, P2a: the note is one summary atom — store it
        // joined with '·', never with a separator prefSummary
        // splits into separate atoms.
        patch.prefCountriesNote = normaliseCountryNote(text);
      }
      if (Object.keys(patch).length) {
        // P0-3: countries recorded with no reason behind them — ask
        // why instead of advancing (the reason is never volunteered
        // otherwise). Stay on the countries question; the why bubble
        // renders in the current-question block. Round 13: same rule
        // as the model path — a reason in THIS answer does not
        // suppress the ask (it is carried as the note, so the bubble
        // asks what it means); only a reason from an earlier turn does.
        const knownCountries = profile.prefCountries ?? [];
        const newCountries = (patch.prefCountries ?? []).filter((c) => !knownCountries.includes(c));
        if (shouldAskCountryWhy(newCountries, profile.prefCountriesNote)) {
          setVerbatim((prev) => ({ ...prev, [q]: text }));
          updateProfile(patch);
          setAwaitingReason({ countries: newCountries, note: patch.prefCountriesNote?.trim() || undefined });
          setInput('');
          flashMood('celebrate');
          return;
        }
        answerSingle(q, patch); return;
      }
      updateProfile({ prefCountriesNote: normaliseCountryNote(text) });
      flashMood('celebrate');
      setInput('');
      // Round 27 W2: the note alone answers countries — advance past
      // every question the profile now answers, not by a bare +1.
      advanceGuided(QUESTIONS.indexOf(q) + 1, { ...profile, prefCountriesNote: normaliseCountryNote(text) });
      return;
    }
    if (mapped) { answerSingle(q, mapped); return; }
    if (q === 'city') {
      answerSingle(q, { prefCity: text });
    } else {
      answerSingle(q, { [singleField[q]]: text } as Partial<Profile>);
    }
  };

  /** One free-text submit (Enter or the Send button) in the GUIDED
   * queue. A question goes to the model and stays on this question; an
   * answer first goes to /profile/parse — when it understands
   * academic/language facts it asks for confirmation and applies
   * NOTHING until the user says yes — and otherwise falls back to the
   * local mapping. When the backend is unreachable the parse is
   * skipped (offline note shows) and the local mapping still
   * understands the answer. */
  const submitFreeText = async () => {
    const text = input.trim();
    if (!text || thinking || !currentQ) return;
    const q = currentQ;
    // P0-3: while the why-follow-up is open, a reason goes straight
    // to the note and the queue advances past the answered countries
    // question; a question still goes to the model and the why stays
    // open for after the answer.
    if (awaitingReason) {
      if (!looksLikeQuestion(text)) {
        setInput('');
        // Round 14, P0: a parse confirmation may still be open (the
        // WHY was armed in its first reply) — apply its academic
        // facts before moving on, or they are lost when the queue
        // advances past this question.
        if (pendingParse) {
          updateProfile(pendingParse.patch);
          setPendingParse(null);
        }
        saveReason(text);
        // Advance past the countries question only when the queue is
        // still on it: after a gateway-down preserve the queue
        // already sits on the next question, and advancing here would
        // skip that question entirely.
        if (currentQ === 'countries') advanceGuided(qIndex + 1, profile);
        return;
      }
    }
    if (looksLikeQuestion(text)) {
      setInput('');
      await askModel(q, text);
      return;
    }
    // Round 16: the input stays live while a parse waits for confirm
    // — a new answer supersedes the unconfirmed parse, exactly as
    // skipping past it would (a question above leaves it alone).
    if (pendingParse) setPendingParse(null);
    setThinking(true);
    setWaking(false);
    let parsed: ParseReply | null = null;
    try {
      parsed = await fetchJsonChat<ParseReply>('/api/profile/parse', {
        method: 'POST',
        body: JSON.stringify({ text, locale }),
      }, {
        // Round 15: bounded chat turn — see sendToPrefChat.
        onRetry: () => setWaking(true),
      });
    } catch {
      setWaking(false);
      setAiOffline(true);
    }
    setThinking(false);
    setWaking(false);
    if (parsed) {
      const mapped = mapParseToProfile(parsed.parsed_profile, profile);
      if (mapped) {
        setVerbatim((prev) => ({ ...prev, [q]: text }));
        setPendingParse({ q, text, patch: mapped.patch, summary: mapped.summary });
        setInput('');
        // Round 14, P0: the WHY follow-up belongs to THIS reply too
        // — arm it now for a countries answer, not when the user
        // confirms the parse. The parse patch itself carries no
        // countries; the local mapping of the same sentence does.
        if (q === 'countries') {
          const local = mapLocalAnswer('countries', text, t, profile);
          const fresh = (local?.prefCountries ?? []).filter((c) => !(profile.prefCountries ?? []).includes(c));
          if (shouldAskCountryWhy(fresh, profile.prefCountriesNote)) {
            setAwaitingReason({
              countries: fresh,
              ...(hasExtraWordsBeyondCountries(text, t, enMessages as Record<string, string>)
                ? { note: normaliseCountryNote(text) } : {}),
            });
          }
        }
        return;
      }
    }
    setInput('');
    applyLocalAnswer(q, text);
  };

  /** Confirm a pending parse: apply the parsed fields, then also apply
   * the local mapping of the same text to this question when there is
   * one (e.g. "很冷，雅思7分" sets both the score and the climate). */
  const confirmParse = () => {
    if (!pendingParse) return;
    const { q, text, patch } = pendingParse;
    setPendingParse(null);
    updateProfile(patch);
    // Round 13: a parse-confirmed countries answer asks why too —
    // same rule as the other paths (new countries, no reason on file
    // before this turn). The why bubble renders with the next
    // question and its answer is stored verbatim as the note. The
    // parse patch itself carries no countries, so the local mapping
    // of the same sentence supplies them; the WHY may already be
    // armed from the first reply (submitFreeText) — re-arming it is
    // the same value, and an already-answered reason suppresses it
    // (the note is on file by then).
    const merged = { ...profile, ...patch };
    const local = mapLocalAnswer(q, text, t, merged);
    const knownCountries = profile.prefCountries ?? [];
    const candidateCountries = [
      ...(patch.prefCountries ?? []),
      ...((local as Partial<Profile> | null)?.prefCountries ?? []),
    ];
    const newCountries = [...new Set(candidateCountries)].filter((c) => !knownCountries.includes(c));
    const whyOpen = awaitingReason !== null;
    const willAskWhy = shouldAskCountryWhy(newCountries, profile.prefCountriesNote);
    if (willAskWhy) {
      setAwaitingReason({
        countries: newCountries,
        ...(hasExtraWordsBeyondCountries(text, t, enMessages as Record<string, string>)
          ? { note: normaliseCountryNote(text) } : {}),
      });
    }
    if (local) {
      if (willAskWhy || whyOpen) {
        // Stay on this question while the why-follow-up is open
        // (same as applyLocalAnswer): the answer is applied, the why
        // bubble owns the next step, and answering it advances.
        updateProfile(local);
        flashMood(opinion(q, { ...merged, ...local })?.mood ?? 'celebrate');
        setInput('');
        return;
      }
      answerSingle(q, local); return;
    }
    if (willAskWhy || whyOpen) { flashMood('celebrate'); return; }
    flashMood('celebrate');
    // Round 27 W2: the parse patch holds academic facts, not prefs —
    // but the queue still advances past anything already known.
    advanceGuided(QUESTIONS.indexOf(q) + 1, { ...profile, ...patch });
  };

  const dismissParse = () => {
    // The dismissed sentence was never an answer — clear it so a
    // later chip tap on this question does not render it as the bubble.
    if (pendingParse) {
      setVerbatim((prev) => {
        const next = { ...prev };
        delete next[pendingParse.q];
        return next;
      });
    }
    setPendingParse(null);
  };

  const skip = () => {
    // P0-3: skipping while the why-follow-up is open skips the reason
    // (it stays unknown) and moves on — but only past the countries
    // question when the queue is still on it: after a gateway-down
    // preserve the queue already sits on the next question, and
    // advancing here would skip that question entirely.
    if (awaitingReason) {
      const wasCountries = currentQ === 'countries';
      setAwaitingReason(null);
      setInput('');
      // Round 27 W2: skipping the reason moves past countries to the
      // next still-unanswered question, never back over a known one.
      if (wasCountries) advanceGuided(qIndex + 1, profile);
      return;
    }
    setInput('');
    // Round 27 W2: a skipped question stays unanswered, but the queue
    // still lands on the next UNANSWERED one — a later known answer
    // (e.g. pressure, preserved from the chat) is never re-asked.
    advanceGuided(qIndex + 1, profile);
  };

  const restart = () => {
    updateProfile(PREF_RESET);
    setInput('');
    setPendingParse(null);
    setVerbatim({});
    setModelTurns([]);
    setTurns([]);
    setServerNext(undefined);
    setSkipped([]);
    setPendingExtract(null);
    setConfirmedNotes([]);
    setFailedText(null);
    setAwaitingReason(null);
    setAiOffline(false);
    setMode('model');
    setQIndex(0);
    // Round 14, P1: a restart clears the persisted snapshot too, so
    // a fresh chat is never resurrected from the old one.
    try { localStorage.removeItem(PREF_CHAT_KEY); } catch { /* ignore */ }
    flashMood('celebrate');
  };

  const done = mode === 'guided' ? qIndex >= QUESTIONS.length : modelDone;
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
  /** City chips are data-driven (round 7, Fix 1): the verified
   * programme cities of the user's chosen countries, most programmes
   * first — Switzerland gives Zurich + Lausanne ONLY. Empty when the
   * chosen country has no verified programme city: free text only,
   * never unrelated cities. */
  const cityChips = citiesInCountries(profile.prefCountries ?? [], allPrograms());

  /** Round 9, R8b: the city input placeholder no longer says
   * "例如：伦敦" on every locale — it names the top verified city of
   * the user's chosen countries ("例如：苏黎世"), or a neutral prompt
   * when no country is chosen yet. */
  const cityPlaceholder = cityChips.length
    ? tf('r9chat.cityPlaceholder', { city: cityDisplayName(cityChips[0].city, t) })
    : t('r9chat.cityPlaceholderAny');

  const summary = prefSummary(profile, t, locale);
  const hasSalary = profile.prefSalary !== '' && profile.prefSalary !== undefined;

  /** A pending parse's understood fields, rendered in the current
   * locale at render time from the stored structured entries. */
  const parseSummaryText = (entries: ParseSummaryEntry[]): string =>
    entries.map((s) => tf(s.key, { value: s.valueKey ? t(s.valueKey) : s.value })).join(' · ');

  /** The model Q&A bubbles for one question: the user's question
   * verbatim, then the model's lines + evidence link (shown exactly
   * as answered, whatever locale that was — Round 27 W1, a language
   * switch never re-fetches a stored reply), the thinking line while
   * the answer is still on its way, or the honest offline line. */
  const renderModelTurns = (q: PrefQId) => modelTurns.filter((turn) => turn.q === q).map((turn, i) => (
    <div key={`${q}-ai-${i}`} className="space-y-3">
      <div className="flex justify-end">
        <div className="max-w-[90%] rounded-2xl bg-teal px-4 py-3 text-white">
          <p>{turn.question}</p>
        </div>
      </div>
      <div className="flex justify-start">
        <div className={`${turn.pending ? 'think-shimmer ' : ''}max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5`}>
          {turn.pending ? (
            <p className="flex items-center gap-2">
              <span>{waking ? tf('pet.wakingElapsed', { seconds: thinkingElapsed }) : tf('r9chat.thinkingElapsed', { seconds: thinkingElapsed })}</span>
              <span className="think-dots" aria-hidden="true"><span /><span /><span /></span>
            </p>
          ) : turn.reply ? (
            <>
              {/* Round 10: an offline turn shows its stored template
                  lines led by the offline line, never as an AI answer. */}
              {turn.offline && (<p>{t('wizard.chatAiOffline')}</p>)}
              {turn.reply.lines.map((line, j) => (<p key={j} className={j > 0 || turn.offline ? 'mt-1' : ''}>{line}</p>))}
              {turn.reply.evidence_url && (
                <a href={turn.reply.evidence_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs font-semibold text-teal underline">
                  {t('pet.evidence')} ↗
                </a>
              )}
            </>
          ) : (
            <p>{t('wizard.chatAiOffline')}</p>
          )}
        </div>
      </div>
    </div>
  ));

  /** The WHY follow-up bubble (model-led chat): the question for the
   * turn that recorded new countries — "你提到瑞士的'环境优美'，对
   * 你来说具体意味着什么？" — or the from-scratch "why" when the
   * turn carried no reason. Round 15: one shared renderer for the
   * anchored bubble (inside renderPrefTurns, right after its turn's
   * reply) and the unanchored fallback (right after all turns,
   * still before the confirm bubble). */
  const renderWhyBubble = (countries: string[], note?: string) => (
    <div className="flex justify-start">
      <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-amber anim-fade-up">
        <p>{note
          ? tf('p0.chatWhyReason', { countries: joinList(countries.map((c) => t(`country.${c}`)), locale), note })
          : tf('p0.chatWhyCountry', { countries: joinList(countries.map((c) => t(`country.${c}`)), locale) })}</p>
      </div>
    </div>
  );

  /** The live WHY bubble for the currently open follow-up when it
   * anchors to no turn (an old blob, or the guided queue's
   * turn-less WHY): renders right after the turns, still before the
   * confirm bubble. */
  const renderLiveWhyBubble = () => {
    if (!awaitingReason) return null;
    return renderWhyBubble(awaitingReason.countries, awaitingReason.note);
  };

  /** One model-led turn: the user's verbatim message, then the model's
   * lines + evidence link (shown exactly as answered, whatever locale
   * that was — Round 27 W1, a language switch never re-fetches a
   * stored reply), the thinking line while the answer is still on
   * its way, or the honest offline line. Round 16: the
   * bubble ORDER comes from prefTurnBubbles (lib/chat) — user,
   * reply, WHY question, WHY answer, deferred next question — so the
   * order is unit-testable without a DOM. The WHY question stays in
   * the turn's history after it is answered, the acknowledgement
   * renders attached to the turn (never as a detached bottom bubble),
   * and the deferred question (e.g. climate) renders only after the
   * WHY is answered or skipped, never ahead of it. Round 28 D1: a
   * turn with no WHY renders its next question as a separate
   * `question` bubble (same rendering as deferredQuestion) — the
   * trailing question line left the reply bubble in prefTurnBubbles
   * so it re-localises through ASK_KEY instead of staying frozen
   * in the reply's locale. */
  const renderPrefTurns = () => turns.map((turn) => (
    <div key={`pref-${turn.id}`} className="space-y-3">
      {prefTurnBubbles(turn, awaitingReason).map((bubble) => {
        if (bubble.kind === 'user') {
          return (
            <div key={`pref-${turn.id}-user`} className="flex justify-end">
              <div className="max-w-[90%] rounded-2xl bg-teal px-4 py-3 text-white">
                <p>{prefTurnUserText(bubble.text, t)}</p>
              </div>
            </div>
          );
        }
        if (bubble.kind === 'reply') {
          // Round 28 integration: an offline fallback turn's stored
          // deterministic prefix lines (cities + generic suggest) are
          // re-rendered in the current locale from the structured
          // evidence block (D2) — bubble.lines already had the
          // trailing question line moved out by prefTurnBubbles (D1),
          // so the slice inside localisedReplyLines drops exactly
          // the replaced prefix, never the question line.
          const lines = localisedReplyLines(bubble.lines, turn.reply, turn.offline, tf, locale);
          return (
            <div key={`pref-${turn.id}-reply`} className="flex justify-start">
              <div className={`${turn.pending ? 'think-shimmer ' : ''}max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5`}>
                {turn.pending ? (
                  <p className="flex items-center gap-2">
                    <span>{waking ? tf('pet.wakingElapsed', { seconds: thinkingElapsed }) : tf('r9chat.thinkingElapsed', { seconds: thinkingElapsed })}</span>
                    <span className="think-dots" aria-hidden="true"><span /><span /><span /></span>
                  </p>
                ) : turn.reply ? (
                  <>
                    {/* Round 10: an offline turn shows its stored template
                        lines led by the offline line, never as an AI answer. */}
                    {turn.offline && (<p>{t('wizard.chatAiOffline')}</p>)}
                    {lines.map((line, k) => (<p key={k} className={k > 0 || turn.offline ? 'mt-1' : ''}>{line}</p>))}
                    {turn.reply.evidence_url && (
                      <a href={turn.reply.evidence_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs font-semibold text-teal underline">
                        {t('pet.evidence')} ↗
                      </a>
                    )}
                  </>
                ) : (
                  <p>{t('wizard.chatAiOffline')}</p>
                )}
              </div>
            </div>
          );
        }
        if (bubble.kind === 'why') {
          return (
            <div key={`pref-${turn.id}-why`}>
              {renderWhyBubble(bubble.countries, bubble.note)}
            </div>
          );
        }
        if (bubble.kind === 'whyAnswer') {
          // Round 17, P0: the WHY answer is the USER's own words — it
          // renders as a normal cyan right-aligned user bubble,
          // exactly like every other answer (re-test task 11: it was
          // merged into the pet's white assistant bubble, "收到，记下
          // 啦～" first line and the user's words second line in small
          // grey, while the climate answer rendered normally). The
          // acknowledgement is a separate assistant line after it,
          // never a container that swallows the user's words.
          return (
            <div key={`pref-${turn.id}-why-answer`} className="space-y-3">
              <div className="flex justify-end">
                <div className="max-w-[90%] rounded-2xl bg-teal px-4 py-3 text-white">
                  <p>{bubble.answer}</p>
                </div>
              </div>
              <div className="flex justify-start">
                <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5 anim-fade-up">
                  <p>{t('wizard.chatOpThanks')}</p>
                </div>
              </div>
            </div>
          );
        }
        // deferredQuestion: the next preference question, asked only
        // after the WHY is answered or skipped.
        // Round 28 D1: the `question` bubble — a non-WHY turn's next
        // question, moved out of the reply bubble by prefTurnBubbles
        // so it renders through the current locale's ASK_KEY. Same
        // rendering as deferredQuestion, its own key (a turn carries
        // one or the other, never both).
        if (bubble.kind === 'question') {
          return (
            <div key={`pref-${turn.id}-question`} className="flex justify-start">
              <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5 anim-fade-up">
                <p>{t(ASK_KEY[bubble.question])}</p>
              </div>
            </div>
          );
        }
        return (
          <div key={`pref-${turn.id}-deferred`} className="flex justify-start">
            <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5 anim-fade-up">
              <p>{t(ASK_KEY[bubble.question])}</p>
            </div>
          </div>
        );
      })}
    </div>
  ));

  /** Chips for the model-led next question. A tap sends the chip's
   * label as the user's message — the model, not the chip, decides
   * what was understood (and the confirmation bubble follows). */
  const renderModelChips = () => {
    // P0-3: while the why-follow-up is open the chips wait — one
    // question at a time, and the reason is the open question.
    if (!nextQ || thinking || pendingExtract || awaitingReason) return null;
    if (nextQ === 'countries') {
      return (
        <div className="flex flex-wrap gap-2">
          {PREF_COUNTRY_CODES.map((code) => (
            <button key={code} type="button"
              onClick={() => void sendToPrefChat(t(`country.${code}`))}
              className="btn-press anim-chip rounded-full border-2 border-navy/15 bg-white px-3 py-1.5 text-sm font-semibold">
              {t(`country.${code}`)}
            </button>
          ))}
        </div>
      );
    }
    if (nextQ in singleChips) {
      return (
        <div className="flex flex-wrap gap-2">
          {singleChips[nextQ].map(([, label]) => (
            <button key={label} type="button"
              onClick={() => void sendToPrefChat(label)}
              className="btn-press anim-chip rounded-full border-2 border-navy/15 bg-white px-3 py-1.5 text-sm font-semibold">
              {label}
            </button>
          ))}
        </div>
      );
    }
    if (nextQ === 'city') {
      if (!cityChips.length) {
        return <p className="text-sm text-navy/70">{t('wizard.chatNoCityChips')}</p>;
      }
      return (
        <div className="flex flex-wrap gap-2">
          {cityChips.map(({ city }) => (
            <button key={city} type="button"
              // Round 9, R8c: the chip sends its LOCALISED label
              // ("苏黎世"), not the canonical English name ("Zurich") —
              // the user's bubble must show what they tapped.
              onClick={() => void sendToPrefChat(cityDisplayName(city, t))}
              className="btn-press anim-chip rounded-full border-2 border-navy/15 bg-white px-3 py-1.5 text-sm font-semibold">
              {cityDisplayName(city, t)}
            </button>
          ))}
        </div>
      );
    }
    if (nextQ === 'salary') {
      return (
        <div className="flex flex-wrap items-center gap-2">
          <input type="number" step="1" min={0} inputMode="decimal"
            value={modelSalary} placeholder={t('wizard.prefSalaryPlaceholder')}
            aria-label={t('wizard.prefSalaryQ')}
            onChange={(e) => setModelSalary(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { const v = Number(modelSalary); if (modelSalary.trim() && !Number.isNaN(v)) void sendToPrefChat(`${v} ${modelSalaryCur}`); } }}
            className="w-36 rounded-full border border-navy/25 bg-white px-3 py-2 text-sm" />
          {(['GBP', 'SGD', 'USD', 'CHF'] as const).map((c) => (
            <button key={c} type="button" aria-pressed={modelSalaryCur === c}
              onClick={() => setModelSalaryCur(c)}
              className={`btn-press rounded-full border-2 px-3 py-1.5 text-sm font-semibold ${modelSalaryCur === c ? 'border-teal bg-teal/5 text-teal-dark' : 'border-navy/15 bg-white'}`}>
              {c}
            </button>
          ))}
          <button type="button"
            onClick={() => { const v = Number(modelSalary); if (modelSalary.trim() && !Number.isNaN(v)) void sendToPrefChat(`${v} ${modelSalaryCur}`); }}
            disabled={!modelSalary.trim()}
            className="btn-press rounded-full bg-navy px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">
            {t('wizard.chatSend')}
          </button>
        </div>
      );
    }
    return null;
  };

  /** One free-text submit in the model-led chat (Enter or Send).
   * Round 14, P0: the why-follow-up is armed in the FIRST reply now,
   * so it is open while the extraction is still pending confirmation
   * — the input stays live for the reason (a question still goes to
   * the model and the why stays open for after the answer).
   * Round 16: the input/send/skip stay live while a confirm is
   * pending, even after the WHY is answered — a send then goes
   * through as a new turn (sendToPrefChat folds the pending
   * extraction into the request's known, and a new extraction folds
   * into the pending confirm instead of overwriting it), so the user
   * is never stuck at the confirm gate with a dead input. */
  const submitModelText = () => {
    const text = input.trim();
    if (!text || thinking) return;
    // P0-3: while the why-follow-up is open, a reason goes straight
    // to the note; a question still goes to the model and the why
    // stays open for after the answer.
    if (awaitingReason) {
      if (looksLikeQuestion(text)) {
        setInput('');
        void sendToPrefChat(text);
        return;
      }
      saveReason(text);
      return;
    }
    setInput('');
    void sendToPrefChat(text);
  };

  return (
    <div>
      <div className="flex items-start gap-3">
        <span className="anim-pet-bob inline-flex shrink-0 rounded-full bg-teal/10 p-1">
          <CompassFace size={56} mood={shownMood} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-bold">{t('wizard.chatTitle')}</h2>
          <p className="mt-1 text-sm text-navy/70">
            {tf('wizard.chatPrefProgress', { n: answeredCount, total: QUESTIONS.length })}
            {missingQs.length > 0 && (
              <>
                {' · '}
                {tf('wizard.chatPrefRemaining', { items: remainingLabel })}
              </>
            )}
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

        {mode === 'model' ? (
          <div className="space-y-3">
            {/* The model-led conversation: verbatim user turns + the
                model's own lines. */}
            {renderPrefTurns()}

            {/* Round 15: the WHY follow-up with no turn to anchor to
                (restored from an old blob, or armed without a turn)
                still renders HERE — right after the turns, before
                the confirm bubble — never after it. When it IS
                anchored, renderPrefTurns already placed it inside
                its turn, so this renders nothing. */}
            {awaitingReason && whyAnchoredTurnId(awaitingReason, turns.map((x) => x.id)) === null && renderLiveWhyBubble()}

            {/* Before the first turn, the pet asks the first missing
                preference in its own words so the user sees a question
                + chips at once — no model call is spent on the hello.
                After that the model's lines carry the conversation. */}
            {turns.length === 0 && nextQ && (
              <div className="flex justify-start">
                <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5 anim-fade-up">
                  <p>{t(ASK_KEY[nextQ])}</p>
                </div>
              </div>
            )}

            {/* Confirmation: what the model understood from THIS
                message, in the user's own words — nothing is applied
                until the user says yes. */}
            {pendingExtract && (
              <div className="space-y-3">
                <div className="flex justify-start">
                  <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-amber anim-fade-up">
                    <p>{tf('wizard.chatParseConfirm', { summary: extractedSummary(pendingExtract.extracted, t, locale) })}</p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={confirmExtract} className="btn-press rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy">
                    {t('wizard.chatParseYes')}
                  </button>
                  <button type="button" onClick={dismissExtract} className="btn-press rounded-full border border-navy/30 bg-white px-4 py-2 text-sm font-semibold">
                    {t('wizard.chatParseNo')}
                  </button>
                </div>
              </div>
            )}

            {/* What was confirmed, in the user's own words — one bubble
                per noted item, in order (the WHY answer, then each
                confirm summary). Round 15: a list, persisted across
                leave-and-return; the old single slot overwrote the
                WHY answer on confirm and lost it on leave. Round 28
                D1: the stored note is rendered through
                localisedConfirmedNote, so a note confirmed in Chinese
                re-localises its choice values in the English UI
                (the "Got it, noted!" prefix already re-localised);
                the WHY reason in the user's own words stays verbatim. */}
            {confirmedNotes.length > 0 && !pendingExtract && confirmedNotes.map((note, i) => (
              <div key={`noted-${i}`} className="flex justify-start">
                <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-navy/5 anim-fade-up">
                  <p>{t('wizard.chatOpThanks')}</p>
                  <p className="mt-1 text-sm text-navy/70">{localisedConfirmedNote(note, t)}</p>
                </div>
              </div>
            ))}

            {/* Round 10: the pending turn above already renders this
                exact "checking…" line — the standalone bubble here
                used to render it a SECOND time, so every reply showed
                two identical "正在查已核实资料… 0 秒" bubbles. Show
                it only when no pending turn exists. */}
            {thinking && !turns.some((x) => x.pending) && (
              <div className="flex justify-start">
                {/* Waiting bubble only (renders while thinking): alive
                    treatment via the global .think-dots / .think-shimmer
                    classes — defined by the globals.css worker, used
                    here, visuals only. */}
                <div className="think-shimmer rounded-2xl bg-white px-4 py-3 text-navy/60 shadow-sm ring-1 ring-navy/5">
                  <span>{waking ? tf('pet.wakingElapsed', { seconds: thinkingElapsed }) : tf('r9chat.thinkingElapsed', { seconds: thinkingElapsed })}</span>
                  <span className="think-dots ms-2" aria-hidden="true"><span /><span /><span /></span>
                </div>
              </div>
            )}

            {!modelDone && (
              <div className="space-y-3">
                {/* Round 15: the WHY bubble used to render here, AFTER
                    the confirm bubble — the first visible reply ended
                    with the climate question and the WHY only appeared
                    underneath the confirm prompt. It now renders
                    anchored to its turn (renderPrefTurns) or, when
                    unanchored, right after the turns and before the
                    confirm bubble — so this block holds only the
                    chips, the input and Skip. */}
                {renderModelChips()}
                <div className="flex gap-2">
                  <input value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') submitModelText(); }}
                    placeholder={nextQ === 'city' ? cityPlaceholder : t('wizard.prefFreeText')}
                    aria-label={t('wizard.chatTypePlaceholder')}
                    // Round 16: the input stays live while a confirm
                    // is pending — the old `pendingExtract` clause
                    // killed it the moment the WHY was answered (or
                    // on resume with a pending extraction), so the
                    // user could not answer the next question before
                    // tapping confirm. Only a call in flight
                    // disables it now.
                    disabled={thinking}
                    className="min-w-0 flex-1 rounded-full border border-navy/25 bg-white px-3 py-2 text-sm disabled:opacity-50" />
                  <button type="button"
                    onClick={submitModelText}
                    disabled={thinking || !input.trim()}
                    className="btn-press shrink-0 rounded-full bg-teal px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">
                    {t('wizard.chatSend')}
                  </button>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  {/* P0-3: while the why-follow-up is open, Skip skips
                      the reason (it stays unknown), not the next
                      preference question. */}
                  <button type="button" onClick={awaitingReason ? skipReason : skipNext} disabled={thinking} className="btn-press text-sm font-semibold text-teal-dark underline underline-offset-2 disabled:opacity-40">
                    {t('wizard.chatSkip')}
                  </button>
                </div>
              </div>
            )}

            {/* Summary bubble once all 8 are known (or all remaining
                ones skipped). */}
            {modelDone && (
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
          </div>
        ) : (
          <>
            {/* Round 15: earlier model turns stay visible above the
                guided continuation — a model drop appends, never
                rewrites. renderPrefTurns also carries the anchored
                WHY bubble, so the guided WHY block below skips it
                when anchored (see its guard). */}
            {renderPrefTurns()}
            {/* Guided queue (offline fallback): the pre-round-7 flow,
                with data-driven city chips and country-scoped climate
                opinions. The honest line + retry action sit on top. */}
            <div className="flex justify-start">
              <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-amber">
                <p>{t('wizard.chatPrefOffline')}</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={retryModelChat} className="btn-press rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy">
                {t('wizard.chatPrefRetry')}
              </button>
            </div>

            {/* Round 17, P0: a pending extraction survives the drop
                (enterGuidedMode no longer discards it), so its
                confirm bubble is re-offered HERE in the guided branch
                — the same bubble as the model branch, same buttons.
                Without it the confirm vanished with the model and the
                stated preference was silently lost (re-test task 11).
                Confirming applies it; dismissing is the user's own
                choice, never a silent loss. */}
            {pendingExtract && (
              <div className="space-y-3">
                <div className="flex justify-start">
                  <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-amber anim-fade-up">
                    <p>{tf('wizard.chatParseConfirm', { summary: extractedSummary(pendingExtract.extracted, t, locale) })}</p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={confirmExtract} className="btn-press rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy">
                    {t('wizard.chatParseYes')}
                  </button>
                  <button type="button" onClick={dismissExtract} className="btn-press rounded-full border border-navy/30 bg-white px-4 py-2 text-sm font-semibold">
                    {t('wizard.chatParseNo')}
                  </button>
                </div>
              </div>
            )}

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
                        <p>{guidedAnswerText(q)}</p>
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
                  {renderModelTurns(q)}
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

                {/* P0-3: the why-follow-up (guided path) — asked once
                    a country is recorded without a reason. Round 13:
                    when the reason arrived with the countries, the
                    bubble asks what it means (p0.chatWhyReason).
                    Round 15: skipped when the WHY is already anchored
                    to a model turn above (renderPrefTurns renders it
                    there), so it never appears twice. */}
                {awaitingReason && whyAnchoredTurnId(awaitingReason, turns.map((x) => x.id)) === null && (
                  <div className="flex justify-start">
                    <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-amber anim-fade-up">
                      <p>{awaitingReason.note
                        ? tf('p0.chatWhyReason', { countries: joinList(awaitingReason.countries.map((c) => t(`country.${c}`)), locale), note: awaitingReason.note })
                        : tf('p0.chatWhyCountry', { countries: joinList(awaitingReason.countries.map((c) => t(`country.${c}`)), locale) })}</p>
                    </div>
                  </div>
                )}

                {/* Parse confirmation: what the pet understood from the
                    free text — nothing is applied until the user says yes. */}
                {pendingParse && pendingParse.q === currentQ && (
                  <div className="space-y-3">
                    <div className="flex justify-start">
                      <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-amber anim-fade-up">
                        <p>{tf('wizard.chatParseConfirm', { summary: parseSummaryText(pendingParse.summary) })}</p>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button type="button" onClick={confirmParse} className="btn-press rounded-full bg-amber px-4 py-2 text-sm font-semibold text-navy">
                        {t('wizard.chatParseYes')}
                      </button>
                      <button type="button" onClick={dismissParse} className="btn-press rounded-full border border-navy/30 bg-white px-4 py-2 text-sm font-semibold">
                        {t('wizard.chatParseNo')}
                      </button>
                    </div>
                  </div>
                )}

                {/* Model answers to this question's free-text questions. */}
                {renderModelTurns(currentQ)}
                {/* Round 10: same double-bubble fix as the model-led
                    chat above — the pending turn already renders this
                    line. The standalone bubble stays only for the
                    /profile/parse wait, which has no pending turn. */}
                {thinking && !modelTurns.some((x) => x.pending) && (
                  <div className="flex justify-start">
                    {/* Waiting bubble only (the /profile/parse wait):
                        same alive treatment as above. */}
                    <div className="think-shimmer rounded-2xl bg-white px-4 py-3 text-navy/60 shadow-sm ring-1 ring-navy/5">
                      <span>{waking ? tf('pet.wakingElapsed', { seconds: thinkingElapsed }) : tf('r9chat.thinkingElapsed', { seconds: thinkingElapsed })}</span>
                      <span className="think-dots ms-2" aria-hidden="true"><span /><span /><span /></span>
                    </div>
                  </div>
                )}

                {/* Countries: multi-select chips + free-text note + confirm.
                    Hidden while the why-follow-up is open — one
                    question at a time. */}
                {currentQ === 'countries' && !awaitingReason && (
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

                {/* City: data-driven chips + free text. No verified
                    programme city for the chosen countries means free
                    text only — never unrelated cities. */}
                {currentQ === 'city' && (
                  cityChips.length ? (
                    <div className="flex flex-wrap gap-2">
                      {cityChips.map(({ city }) => (
                        <button key={city} type="button"
                          onClick={() => answerSingle(currentQ, { prefCity: city })}
                          className="btn-press anim-chip rounded-full border-2 border-navy/15 bg-white px-3 py-1.5 text-sm font-semibold">
                          {cityDisplayName(city, t)}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-navy/70">{t('wizard.chatNoCityChips')}</p>
                  )
                )}

                {/* Salary: amount + currency chips + confirm. */}
                {currentQ === 'salary' && (
                  <div className="flex flex-wrap items-center gap-2">
                    <input type="number" step="1" min={0} inputMode="decimal"
                      value={profile.prefSalary ?? ''} placeholder={t('wizard.prefSalaryPlaceholder')}
                      aria-label={t('wizard.prefSalaryQ')}
                      onChange={(e) => { const v = e.target.value; updateProfile({ prefSalary: v === '' ? '' : Number(v) }); }}
                      className="w-36 rounded-full border border-navy/25 bg-white px-3 py-2 text-sm" />
                    {(['GBP', 'SGD', 'USD', 'CHF'] as const).map((c) => (
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
                    "other countries" note and salary has its own input).
                    Free text is UNDERSTOOD, not just stored: a question
                    goes to the model, an answer goes to /profile/parse
                    (confirmation first) + the local mapping — see
                    submitFreeText. */}
                {currentQ !== 'salary' && (
                  <div className="flex gap-2">
                    <input value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') void submitFreeText(); }}
                      placeholder={currentQ === 'countries' ? t('wizard.prefCountriesOther') : currentQ === 'city' ? cityPlaceholder : t('wizard.prefFreeText')}
                      aria-label={t('wizard.chatTypePlaceholder')}
                      // Round 16: the input stays live while a parse
                      // waits for confirm (same rule as the model-led
                      // confirm) — only a call in flight disables it.
                      disabled={thinking}
                      className="min-w-0 flex-1 rounded-full border border-navy/25 bg-white px-3 py-2 text-sm disabled:opacity-50" />
                    <button type="button"
                      onClick={() => void submitFreeText()}
                      disabled={thinking || !input.trim()}
                      className="btn-press shrink-0 rounded-full bg-teal px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">
                      {t('wizard.chatSend')}
                    </button>
                  </div>
                )}

                <div className="flex flex-wrap items-center gap-3">
                  {currentQ === 'countries' && (
                    <button type="button"
                      onClick={() => {
                        // P0-3: countries chosen without a reason —
                        // ask why first; a second tap skips the reason.
                        const hasNote = !!(profile.prefCountriesNote ?? '').trim();
                        if (!hasNote && (profile.prefCountries?.length ?? 0) > 0 && !awaitingReason) {
                          setAwaitingReason({ countries: profile.prefCountries ?? [] });
                          flashMood('celebrate');
                          return;
                        }
                        setAwaitingReason(null);
                        flashMood(opinion('countries', profile)?.mood ?? 'celebrate'); advanceGuided(qIndex + 1, profile);
                      }}
                      className="btn-press rounded-full bg-navy px-4 py-2 text-sm font-semibold text-white">
                      {t('wizard.chatNext')}
                    </button>
                  )}
                  {currentQ === 'salary' && (
                    <button type="button"
                      onClick={() => { if (hasSalary) flashMood('idle'); advanceGuided(qIndex + 1, profile); }}
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
          </>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
