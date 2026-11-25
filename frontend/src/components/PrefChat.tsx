'use client';
import { useEffect, useRef, useState } from 'react';
import { useApp, type Locale } from '../lib/store';
import { Profile, emptyProfile } from '../lib/types';
import {
  PREF_COUNTRY_CODES,
  bestCityForClimate, climateLabel, environmentLabel, afterGradLabel, pressureLabel, teachingLabel,
  normaliseClimatePref, prefSummary,
} from '../lib/preferences';
import { allPrograms, fetchJson } from '../lib/api';
import { isModelReply, looksLikeQuestion, type ChatHistoryTurn, type ChatReply, type ParseReply } from '../lib/chat';
import { CompassFace, type PetMood } from './CompassPet';
import enMessages from '../../messages/en.json';

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
 * from the verified data already shipped in the frontend (the merged
 * catalogue: which institutions are in London / Singapore, how many
 * verified programmes a city has, and the curated city climate table
 * for the climate question). Anything not in the data is never stated.
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
  const names = [...new Set(allPrograms().filter((p) => p.country === country).map((p) => p.institution))];
  return names.join(locale === 'zh-CN' ? '、' : ', ');
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

/** One field of a parse confirmation, stored structured (locale key +
 * raw value, plus an existing locale key when the value is an enum) so
 * the bubble renders in the current locale at render time. */
interface ParseSummaryEntry { key: string; value: string; valueKey?: string; }

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

export function PrefChat({ onDone }: { onDone: () => void }) {
  const { t, tf, locale, profile, updateProfile } = useApp();
  const [qIndex, setQIndex] = useState(0);
  const [mood, setMood] = useState<PetMood>('celebrate');
  const [input, setInput] = useState('');
  /** A model call (chat or parse) is in flight. */
  const [thinking, setThinking] = useState(false);
  /** True once a model call has failed or come back template-only:
   * the chat says so plainly and keeps working on the guided
   * questions + local understanding. Reset on the next model success. */
  const [aiOffline, setAiOffline] = useState(false);
  /** Model answers to free-text questions, kept per question so they
   * survive advancing. Ephemeral help: a refresh rebuilds the chat
   * from the Profile, so they do not survive a reload. */
  const [modelTurns, setModelTurns] = useState<{
    q: PrefQId; question: string;
    reply: ChatReply | null; replyLocale: Locale | null; offline: boolean;
  }[]>([]);
  /** A parse that understood academic/language facts and waits for the
   * user to confirm — nothing here is applied until they say yes. */
  const [pendingParse, setPendingParse] = useState<null | {
    q: PrefQId; text: string;
    patch: Partial<Profile>; summary: ParseSummaryEntry[];
  }>(null);
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
  }, [qIndex, profile, modelTurns, thinking]);

  /** Locale change: re-fetch model answers in the new locale (the
   * question alone is enough context). A failed or template-only
   * re-fetch marks the turn offline instead of showing stale text. */
  useEffect(() => {
    modelTurns.forEach((turn, i) => {
      if (!turn.reply || turn.replyLocale === locale) return;
      fetchJson<ChatReply>('/api/assistant/chat', {
        method: 'POST',
        body: JSON.stringify({ message: turn.question, locale }),
      }).then((fresh) => {
        if (!isModelReply(fresh)) {
          setAiOffline(true);
          setModelTurns((prev) => prev.map((x, j) => (j === i ? { ...x, reply: null, replyLocale: null, offline: true } : x)));
          return;
        }
        setModelTurns((prev) => prev.map((x, j) => (j === i ? { ...x, reply: fresh, replyLocale: locale, offline: false } : x)));
      }).catch(() => {
        setAiOffline(true);
        setModelTurns((prev) => prev.map((x, j) => (j === i ? { ...x, reply: null, replyLocale: null, offline: true } : x)));
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);

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
   * catalogue (the merged v2 + expansion list) and the curated city
   * climate table are used: institution names per country,
   * verified-programme counts per city, and the best city for a wanted
   * climate. Returns the locale key + vars, or null for a plain
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
        // Round 6: answer with the best city for the wanted climate,
        // from the curated climate table + verified programme counts.
        const pref = normaliseClimatePref(p.prefClimate);
        if (pref === 'warm') return { key: 'wizard.chatOpWarm', mood: 'celebrate' };
        if (pref) {
          const best = bestCityForClimate(pref, allPrograms());
          if (best) {
            const key = pref === 'cool' ? 'wizard.chatOpCool' : pref === 'four_seasons' ? 'wizard.chatOpFourSeasons' : 'wizard.chatOpMild';
            return { key, vars: { count: best.count }, mood: 'celebrate' };
          }
        }
        return { key: 'wizard.chatOpThanks', mood: 'celebrate' };
      }
      case 'city': {
        const want = (p.prefCity ?? '').trim().toLowerCase();
        if (!want) return null;
        const count = allPrograms().filter((x) => (x.city ?? '').toLowerCase() === want).length;
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

  /** A pending parse belongs to its question: leaving the question
   * (chip tap, skip, back, restart) drops it instead of applying a
   * stale confirmation later. */
  useEffect(() => {
    setPendingParse((prev) => (prev && prev.q !== currentQ ? null : prev));
  }, [currentQ]);

  const answerSingle = (q: PrefQId, patch: Partial<Profile>) => {
    updateProfile(patch);
    // The opinion needs the just-saved value, which is not in `profile`
    // yet at call time — compute it from the merged profile.
    const op = opinion(q, { ...profile, ...patch });
    flashMood(op?.mood ?? 'celebrate');
    setInput('');
    setQIndex((i) => Math.min(i + 1, QUESTIONS.length));
  };

  /** A free-text question goes to the real model (grounded, with the
   * earlier model turns as history). A template-only reply is never
   * shown as an answer — the turn is stored as offline instead. */
  const askModel = async (q: PrefQId, text: string) => {
    setThinking(true);
    const requestLocale = locale;
    const history: ChatHistoryTurn[] = [];
    for (const turn of modelTurns) {
      if (!turn.reply || !isModelReply(turn.reply)) continue;
      history.push({ role: 'user', content: turn.question });
      history.push({ role: 'assistant', content: turn.reply.lines.join(' ') });
    }
    try {
      const r = await fetchJson<ChatReply>('/api/assistant/chat', {
        method: 'POST',
        body: JSON.stringify({ message: text, locale: requestLocale, history: history.slice(-6) }),
      });
      if (!isModelReply(r)) {
        setAiOffline(true);
        setModelTurns((prev) => [...prev, { q, question: text, reply: null, replyLocale: null, offline: true }]);
        return;
      }
      setAiOffline(false);
      setModelTurns((prev) => [...prev, { q, question: text, reply: r, replyLocale: requestLocale, offline: false }]);
    } catch {
      setAiOffline(true);
      setModelTurns((prev) => [...prev, { q, question: text, reply: null, replyLocale: null, offline: true }]);
    } finally {
      setThinking(false);
    }
  };

  /** A free-text answer to the current question, without the local
   * mapping: keep the existing verbatim behaviour (countries note /
   * city / free-text field value) — the opinion bubble still answers. */
  const applyLocalAnswer = (q: PrefQId, text: string) => {
    const mapped = mapLocalAnswer(q, text, t, profile);
    if (mapped) { answerSingle(q, mapped); return; }
    if (q === 'countries') {
      updateProfile({ prefCountriesNote: text });
      flashMood('celebrate');
      setInput('');
      setQIndex((i) => Math.min(i + 1, QUESTIONS.length));
    } else if (q === 'city') {
      answerSingle(q, { prefCity: text });
    } else {
      answerSingle(q, { [singleField[q]]: text } as Partial<Profile>);
    }
  };

  /** One free-text submit (Enter or the Send button). A question goes
   * to the model and stays on this question; an answer first goes to
   * /profile/parse — when it understands academic/language facts it
   * asks for confirmation and applies NOTHING until the user says
   * yes — and otherwise falls back to the local mapping. When the
   * backend is unreachable the parse is skipped (offline note shows)
   * and the local mapping still understands the answer. */
  const submitFreeText = async () => {
    const text = input.trim();
    if (!text || thinking || !currentQ) return;
    const q = currentQ;
    if (looksLikeQuestion(text)) {
      setInput('');
      await askModel(q, text);
      return;
    }
    setThinking(true);
    let parsed: ParseReply | null = null;
    try {
      parsed = await fetchJson<ParseReply>('/api/profile/parse', {
        method: 'POST',
        body: JSON.stringify({ text, locale }),
      });
    } catch {
      setAiOffline(true);
    }
    setThinking(false);
    if (parsed) {
      const mapped = mapParseToProfile(parsed.parsed_profile, profile);
      if (mapped) {
        setPendingParse({ q, text, patch: mapped.patch, summary: mapped.summary });
        setInput('');
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
    const local = mapLocalAnswer(q, text, t, { ...profile, ...patch });
    if (local) { answerSingle(q, local); return; }
    flashMood('celebrate');
    setQIndex((i) => Math.min(i + 1, QUESTIONS.length));
  };

  const dismissParse = () => setPendingParse(null);

  const skip = () => {
    setInput('');
    setQIndex((i) => Math.min(i + 1, QUESTIONS.length));
  };

  const restart = () => {
    updateProfile(PREF_RESET);
    setInput('');
    setPendingParse(null);
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

  /** A pending parse's understood fields, rendered in the current
   * locale at render time from the stored structured entries. */
  const parseSummaryText = (entries: ParseSummaryEntry[]): string =>
    entries.map((s) => tf(s.key, { value: s.valueKey ? t(s.valueKey) : s.value })).join(' · ');

  /** The model Q&A bubbles for one question: the user's question
   * verbatim, then the model's lines + evidence link (only when
   * answered in the current locale), the thinking line while a
   * re-fetch is pending, or the honest offline line. */
  const renderModelTurns = (q: PrefQId) => modelTurns.filter((turn) => turn.q === q).map((turn, i) => (
    <div key={`${q}-ai-${i}`} className="space-y-3">
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
            <p>{t('wizard.chatAiOffline')}</p>
          )}
        </div>
      </div>
    </div>
  ));

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
            {thinking && (
              <div className="flex justify-start">
                <div className="rounded-2xl bg-white px-4 py-3 text-navy/60 shadow-sm ring-1 ring-navy/5">{t('pet.thinking')}</div>
              </div>
            )}
            {aiOffline && (
              <p className="text-xs text-navy/60">{t('wizard.chatAiOffline')}</p>
            )}

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
                  placeholder={currentQ === 'countries' ? t('wizard.prefCountriesOther') : currentQ === 'city' ? t('wizard.prefCityPlaceholder') : t('wizard.prefFreeText')}
                  aria-label={t('wizard.chatTypePlaceholder')}
                  disabled={thinking || !!pendingParse}
                  className="min-w-0 flex-1 rounded-full border border-navy/25 bg-white px-3 py-2 text-sm disabled:opacity-50" />
                <button type="button"
                  onClick={() => void submitFreeText()}
                  disabled={thinking || !!pendingParse || !input.trim()}
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
