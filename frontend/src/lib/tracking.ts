import type { Profile } from './types';
import { joinList } from './format';

/**
 * Restyle 2 (Gen UI behaviour half) — pure helpers for the proactive
 * pet greeting, the plan-change sentence, and the follow-up tracking
 * checklist. Pure by design, so the node harness in
 * tests/test_restyle2_b_behaviour.py can exercise the real logic
 * without a browser or a backend.
 *
 * Hard boundary (never broken here): nothing in this module invents
 * a fact. A summary lists only what the stored profile holds; a
 * checklist item exists only when the verified programme data backs
 * it (a deadline item only when the official page published one, a
 * documents item only when the programme lists verified
 * requirements, a visa item only for GB/SG where the site already
 * carries official visa guidance). No admission probabilities, no
 * guarantees, no interview step — no verified interview data exists
 * anywhere in the catalogue, so none is ever derived. Unknown stays
 * unknown: a programme with no published deadline gets no deadline
 * item and no countdown, never a guessed date.
 */

// --- Plan-change sentence -----------------------------------------------

export type PlanChangeKind = 'country' | 'budget' | 'intake';

/** One proposed plan change, as structured data only — the pet
 * renders it at render time from the current locale, and nothing is
 * applied until the user confirms (see CompassPet's planChange turn).
 * `from` is the stored value being replaced, for the confirm bubble;
 * it is never rendered as a claim about the new value. */
export interface PlanChange {
  kind: PlanChangeKind;
  /** ISO country code (kind 'country'). */
  country?: string;
  /** Stored preferred countries being replaced. */
  fromCountries?: string[];
  /** New budget amount (kind 'budget'). */
  budget?: number;
  budgetCurrency?: string;
  /** Stored budget being replaced. */
  fromBudget?: number;
  /** New intake year (kind 'intake'). */
  intakeYear?: number;
  /** Stored intake year being replaced. */
  fromIntakeYear?: number | '';
}

/** Change cues in the 6 locales, for detection only — never rendered.
 * Detection is deliberately heuristic: a sentence that names a new
 * value AND carries a change cue is proposed, never applied; the
 * confirm bubble is the safety net (Skip discards it). A bare
 * question with no cue ("What is the deadline for UK schools?")
 * never fires. */
const CHANGE_CUES = [
  'change', 'switch', 'move', 'instead', 'now ', 'update',
  '改为', '改成', '换成', '换到', '改去', '改', '换', '现在',
  'cambiar', 'cambia', 'cambié', 'cambio', 'actualizar',
  'changer', 'changez', 'modifie', 'maintenant',
  'mudar', 'mude', 'trocar', 'agora',
  'غيّر', 'تغيير', 'بدل', 'الآن',
  'wechseln', 'ändern', 'jetzt',
];

function hasChangeCue(lower: string): boolean {
  return CHANGE_CUES.some((cue) => lower.includes(cue));
}

/** Country names a message may carry, per code: the caller passes the
 * current-locale name plus the English name for every code the
 * verified data knows (see CompassPet.countryNameList). */
export interface CountryNameEntry {
  code: string;
  names: string[];
}

/** First country code named in the message, or null. Short names
 * match on word boundaries only, so "uk" never fires inside another
 * word; longer names match as substrings. */
export function countryFromText(
  text: string,
  countries: CountryNameEntry[],
): string | null {
  const lower = text.toLowerCase();
  for (const entry of countries) {
    for (const raw of entry.names) {
      const name = (raw ?? '').toLowerCase().trim();
      if (!name) continue;
      if (name.length <= 3) {
        const esc = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        if (new RegExp(`(?<![a-z])${esc}(?![a-z])`).test(lower)) return entry.code;
      } else if (lower.includes(name)) {
        return entry.code;
      }
    }
  }
  return null;
}

const CURRENCY_TOKENS: Record<string, string> = {
  gbp: 'GBP', '£': 'GBP', pound: 'GBP', pounds: 'GBP', '镑': 'GBP',
  sgd: 'SGD', 's$': 'SGD', '新元': 'SGD',
  usd: 'USD', dollar: 'USD', dollars: 'USD', '美元': 'USD',
  cny: 'CNY', '¥': 'CNY', rmb: 'CNY', '元': 'CNY',
  eur: 'EUR', '€': 'EUR',
};

/** A budget amount stated in the message, or null. Takes the LAST
 * number in the message (the new value comes last: "change my budget
 * to 60000"), with a k / 万 multiplier and an explicit currency token
 * when one is next to it; 万 implies CNY, otherwise the profile's
 * currency. Only plausible budget amounts count (1,000–1,000,000),
 * so a year or a score never reads as a budget — and a bare
 * 2026–2030 is skipped outright, so an intake year never reads as
 * a budget either. */
export function budgetFromText(
  text: string,
  fallbackCurrency: string,
): { amount: number; currency: string } | null {
  const cleaned = text.replace(/,/g, '');
  const re = /(\d+(?:\.\d+)?)\s*(万|k|K)?\s*(gbp|£|pounds?|sgd|s\$|usd|dollars?|¥|cny|rmb|元|镑|新元|eur|€)?/gi;
  let last: { amount: number; currency: string } | null = null;
  let m: RegExpExecArray | null;
  while ((m = re.exec(cleaned)) !== null) {
    const raw = parseFloat(m[1]);
    if (!Number.isFinite(raw)) continue;
    // A bare intake year (2026–2030) is never a budget — without
    // this, "move my intake to 2027" reads as a budget change and
    // the intake branch below never fires.
    if (Number.isInteger(raw) && raw >= 2026 && raw <= 2030) continue;
    const mult = m[2] === '万' ? 10000 : m[2] ? 1000 : 1;
    const amount = raw * mult;
    if (amount < 1000 || amount > 1000000) continue;
    const token = (m[3] ?? '').toLowerCase();
    // 万 states the amount in yuan, so it implies CNY unless an
    // explicit currency token says otherwise.
    const currency = token ? (CURRENCY_TOKENS[token] ?? fallbackCurrency) : (m[2] === '万' ? 'CNY' : fallbackCurrency);
    last = { amount, currency };
  }
  return last;
}

/** An intake year stated in the message (2026–2030), or null. */
export function intakeYearFromText(text: string): number | null {
  const m = text.match(/\b(202[6-9]|2030)\b/);
  return m ? parseInt(m[1], 10) : null;
}

/**
 * Detect a plan-change sentence: one user sentence that changes the
 * country, the budget, or the intake timing. Returns the proposed
 * change, or null when nothing changed. Only fires when the stored
 * profile already holds a value that differs — setting a value for
 * the first time is the guided flow's job, not a change — and only
 * when the sentence carries a change cue, so questions and
 * information requests never propose a change. Country wins over
 * budget, budget over intake: one sentence, one proposal.
 */
export function detectPlanChange(
  message: string,
  profile: Profile,
  countries: CountryNameEntry[],
): PlanChange | null {
  if (!message || !message.trim()) return null;
  const lower = message.toLowerCase();
  if (!hasChangeCue(lower)) return null;

  const country = countryFromText(message, countries);
  const savedCountries = profile.prefCountries ?? [];
  if (country && savedCountries.length > 0 && !savedCountries.includes(country)) {
    return { kind: 'country', country, fromCountries: [...savedCountries] };
  }

  if (typeof profile.budget === 'number') {
    const found = budgetFromText(message, profile.budgetCurrency || 'GBP');
    if (found && (found.amount !== profile.budget || found.currency !== (profile.budgetCurrency || 'GBP'))) {
      return { kind: 'budget', budget: found.amount, budgetCurrency: found.currency, fromBudget: profile.budget };
    }
  }

  if (typeof profile.intakeYear === 'number' || profile.intakeYear === '') {
    const year = intakeYearFromText(message);
    if (year !== null && year !== profile.intakeYear) {
      return { kind: 'intake', intakeYear: year, fromIntakeYear: profile.intakeYear ?? '' };
    }
  }
  return null;
}

/** The profile patch a confirmed plan change applies. Country changes
 * replace the saved preferred countries; budget / intake replace
 * their stored value. Applied only through the store's updateProfile
 * (a user edit, so the synthetic-sample marker clears with it). */
export function planChangePatch(change: PlanChange): Partial<Profile> {
  if (change.kind === 'country' && change.country) return { prefCountries: [change.country] };
  if (change.kind === 'budget' && typeof change.budget === 'number') {
    return { budget: change.budget, budgetCurrency: change.budgetCurrency || 'GBP' };
  }
  if (change.kind === 'intake' && typeof change.intakeYear === 'number') {
    return { intakeYear: change.intakeYear };
  }
  return {};
}

// --- Proactive summary ----------------------------------------------------

const FIELD_LABEL_KEYS: Record<string, string> = {
  business: 'wizard.fieldBusiness',
  computing: 'wizard.fieldComputing',
  engineering: 'wizard.fieldEngineering',
  science: 'wizard.fieldScience',
  medicine: 'wizard.fieldMedicine',
  humanities: 'wizard.fieldHumanities',
  arts: 'wizard.fieldArts',
};

export interface ProgressEntry {
  labelKey: string;
  text: string;
}

export interface ProfileProgress {
  /** What the stored profile already holds, in selection order. */
  filled: ProgressEntry[];
  /** Label keys of what is still missing, in the same order. */
  missing: string[];
}

function scoreText(profile: Profile): string {
  const parts: string[] = [];
  if (typeof profile.gaokaoScore === 'number') {
    parts.push(`Gaokao ${profile.gaokaoScore}${typeof profile.gaokaoTotal === 'number' ? `/${profile.gaokaoTotal}` : ''}`);
  }
  if (typeof profile.ieltsOverall === 'number') parts.push(`IELTS ${profile.ieltsOverall}`);
  if (typeof profile.toefl === 'number') parts.push(`TOEFL ${profile.toefl}`);
  if (typeof profile.satTotal === 'number') parts.push(`SAT ${profile.satTotal}`);
  if (typeof profile.actComposite === 'number') parts.push(`ACT ${profile.actComposite}`);
  if (profile.alevels) parts.push(`A-level ${profile.alevels}`);
  if (typeof profile.ibTotal === 'number') parts.push(`IB ${profile.ibTotal}`);
  if (typeof profile.greTotal === 'number') parts.push(`GRE ${profile.greTotal}`);
  if (typeof profile.gmat === 'number') parts.push(`GMAT ${profile.gmat}`);
  return parts.join(' · ');
}

/**
 * Selection progress from the real stored profile — what is already
 * filled and what is still missing — for the pet's proactive
 * greeting. Values are the user's own stored values (or localised
 * labels for enums); nothing is invented, and a missing field is
 * listed as missing, never filled with a guess.
 */
export function profileProgress(
  profile: Profile,
  t: (k: string) => string,
  locale: string,
): ProfileProgress {
  const filled: ProgressEntry[] = [];
  const missing: string[] = [];
  if (profile.track === 'undergraduate' || profile.track === 'taught_masters') {
    filled.push({ labelKey: 'report.profileDegree', text: t(profile.track === 'undergraduate' ? 'pet.q1ug' : 'pet.q1tm') });
  } else {
    missing.push('report.profileDegree');
  }
  if (profile.field) {
    const key = FIELD_LABEL_KEYS[profile.field];
    filled.push({ labelKey: 'report.profileField', text: key ? t(key) : profile.field });
  } else {
    missing.push('report.profileField');
  }
  if ((profile.prefCountries ?? []).length > 0) {
    filled.push({
      labelKey: 'results.prefTitle',
      text: joinList((profile.prefCountries ?? []).map((c) => t(`country.${c}`)), locale),
    });
  } else {
    missing.push('results.prefTitle');
  }
  if (typeof profile.budget === 'number') {
    filled.push({ labelKey: 'report.profileBudget', text: `${profile.budget} ${profile.budgetCurrency || ''}`.trim() });
  } else {
    missing.push('report.profileBudget');
  }
  if (typeof profile.intakeYear === 'number') {
    filled.push({ labelKey: 'report.profileIntake', text: String(profile.intakeYear) });
  } else {
    missing.push('report.profileIntake');
  }
  const scores = scoreText(profile);
  if (scores) filled.push({ labelKey: 'report.profileScores', text: scores });
  else missing.push('report.profileScores');
  return { filled, missing };
}

// --- Follow-up checklist --------------------------------------------------

/** The verified programme facts a checklist item may derive from.
 * Only expansion programmes carry them (the merged Program shape
 * drops deadlines and requirements); v2 programmes simply yield no
 * deadline / documents items. */
export interface ChecklistProgramme {
  id: string;
  country: string;
  applicationDeadline: string | null;
  requirements: { category: string; description: string }[];
  sources: { url: string }[];
}

export type ChecklistKind = 'deadline' | 'documents' | 'visa';

export interface ChecklistItem {
  id: string;
  kind: ChecklistKind;
  /** Programme the step belongs to (deadline / documents). */
  programId?: string;
  /** Country the step belongs to (visa). */
  country?: string;
  done: boolean;
}

/** Countries with official visa guidance on this site (the homepage
 * policy lines): only these ever get a visa step. */
export const VISA_COUNTRIES = ['GB', 'SG'];

/**
 * Derive the follow-up checklist from the stored profile and the
 * verified programme data only: one deadline step per target
 * programme with a published deadline, one documents step per target
 * programme with verified requirements, one visa step per distinct
 * GB/SG target country. No interview step exists — no verified
 * interview data is published for any programme — so none is
 * invented. An empty profile derives an empty list.
 */
export function deriveChecklist(
  profile: Profile,
  programmes: ChecklistProgramme[],
): ChecklistItem[] {
  const items: ChecklistItem[] = [];
  const byId = new Map(programmes.map((p) => [p.id, p]));
  for (const id of profile.targetProgramIds ?? []) {
    const p = byId.get(id);
    if (!p) continue;
    if (p.applicationDeadline) {
      items.push({ id: `deadline:${p.id}`, kind: 'deadline', programId: p.id, done: false });
    }
    if (p.requirements.length > 0) {
      items.push({ id: `documents:${p.id}`, kind: 'documents', programId: p.id, done: false });
    }
  }
  const countries = [...new Set(
    (profile.targetProgramIds ?? [])
      .map((id) => byId.get(id)?.country)
      .filter((c): c is string => !!c && VISA_COUNTRIES.includes(c)),
  )];
  for (const country of countries) {
    items.push({ id: `visa:${country}`, kind: 'visa', country, done: false });
  }
  return items;
}

/**
 * Merge a freshly derived checklist over the stored one: done flags
 * survive by id, steps that no longer derive drop out, new steps
 * arrive undone, order follows the derivation. Pure — the store
 * persists the result.
 */
export function mergeChecklist(
  prev: ChecklistItem[],
  derived: ChecklistItem[],
): ChecklistItem[] {
  const doneById = new Map(prev.filter((i) => i.done).map((i) => [i.id, true]));
  return derived.map((item) => ({ ...item, done: doneById.get(item.id) === true }));
}

/** One deadline countdown, from the official deadline string as
 * published (e.g. "1 Dec 2026", "15 October 2026 (UCAS, 6pm UK
 * time)", "1 November 2026 (Early Action); 4 January 2027 (Regular
 * Action)"). Multi-date strings yield the earliest date still in
 * the future; when all dates are past, the latest past date, so the
 * timeline never shows a stale early-action date as the countdown.
 * Unparseable strings return null — no countdown is ever guessed. */
export interface ParsedDeadline {
  /** UTC midnight of the deadline date. */
  dateMs: number;
  /** Whole days from `nowMs` to the deadline (negative when past). */
  daysLeft: number;
}

const MONTHS: Record<string, number> = {
  jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5,
  jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11,
};

export function parseDeadline(raw: string | null | undefined, nowMs: number = Date.now()): ParsedDeadline | null {
  if (!raw) return null;
  // Full month names AND the abbreviations the official pages use
  // ("1 Dec 2026", "15 Feb 2027").
  const re = /(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{4})/gi;
  const dates: number[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(raw)) !== null) {
    const month = MONTHS[m[2].toLowerCase().slice(0, 3)];
    if (month === undefined) continue;
    dates.push(Date.UTC(parseInt(m[3], 10), month, parseInt(m[1], 10)));
  }
  if (!dates.length) return null;
  const todayStart = Date.UTC(
    new Date(nowMs).getUTCFullYear(), new Date(nowMs).getUTCMonth(), new Date(nowMs).getUTCDate(),
  );
  const dayMs = 86400000;
  const future = dates.filter((d) => d >= todayStart).sort((a, b) => a - b);
  const dateMs = future.length ? future[0] : [...dates].sort((a, b) => b - a)[0];
  return { dateMs, daysLeft: Math.round((dateMs - todayStart) / dayMs) };
}
