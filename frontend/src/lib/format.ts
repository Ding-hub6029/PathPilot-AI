import { FeeItem, Profile, Program } from './types';

/**
 * Localized rendering of programme metadata (fix 2026-11-25, req. C).
 *
 * Duration, intake label and fee period are programme facts, but they
 * were rendered as raw English strings ("3 years full-time",
 * "September 2026", "per year") on every page. They now come from the
 * locale files, keyed by programme id, with the raw English value as
 * the fallback for programmes the catalogue does not know yet.
 * Institution names and official programme names are proper nouns and
 * stay as they are.
 *
 * Round 8: the per-id keys cover the 8 v2 programmes only — the 881
 * expansion programmes fell back to raw English ("September 2027" +
 * a Chinese "入学" suffix = mixed language). The fallback is now
 * parsed and rendered in the current locale: month + year through
 * Intl.DateTimeFormat, seasons through the intake.season.* keys, a
 * bare year as-is. Anything unparseable still falls back to the raw
 * label rather than an invented one.
 */

const fmtNum = (n: number, locale: string): string => n.toLocaleString(locale);

/** Round 24: the enumeration separator for a locale — the single
 * place frontend name lists are joined. Before this, each call site
 * hard-coded its own rule (`locale === 'zh-CN' ? '、' : ', '`), and
 * several joined with a bare '、' in every locale, so an English chat
 * bubble listed countries/programmes with a Chinese enumeration
 * comma; ar fell through to the Latin ", " everywhere. Standard
 * enumeration separators: ", " in en/es/fr/pt-BR, "、" in zh-CN,
 * "، " (Arabic comma + space) in ar. Unknown locales fall back to
 * ", ". Storage joins ('·' atoms, ';' legacy notes) are NOT this:
 * they are machine formats parsed back, not rendered lists. */
export const LIST_SEPARATORS: Record<string, string> = {
  en: ', ',
  'zh-CN': '、',
  es: ', ',
  fr: ', ',
  'pt-BR': ', ',
  ar: '، ',
};

export function listSeparator(locale: string): string {
  return LIST_SEPARATORS[locale] ?? ', ';
}

export function joinList(items: readonly string[], locale: string): string {
  return items.join(listSeparator(locale));
}

/** Round 26 (W4): a parenthesised note after a name — "Zurich
 * (Four seasons)" / "苏黎世（四季分明）". Parenthesis style follows
 * the locale, the same rule localiseDurationParen uses below:
 * full-width （） with no space in zh-CN, half-width () with a
 * space everywhere else (en/es/fr/pt-BR/ar). The PrefChat climate
 * no-match line hard-coded the full-width form in every locale, so
 * an English bubble read "Zurich （Four seasons）". */
export function parenNote(name: string, note: string, locale: string): string {
  const cjk = locale === 'zh-CN';
  return `${name}${cjk ? '（' : ' ('}${note}${cjk ? '）' : ')'}`;
}

const MONTHS_EN = [
  'january', 'february', 'march', 'april', 'may', 'june',
  'july', 'august', 'september', 'october', 'november', 'december',
];
const SEASONS_EN = ['spring', 'summer', 'autumn', 'fall', 'winter'] as const;
const SEASON_KEY: Record<string, 'spring' | 'summer' | 'autumn' | 'winter'> = {
  spring: 'spring', summer: 'summer', autumn: 'autumn', fall: 'autumn', winter: 'winter',
};

/** Localise a raw English intake label ("September 2027", "Autumn
 * 2027", "10 October 2027", "2027"). Returns null when the label
 * cannot be parsed, so the caller falls back to the raw value. */
export function localiseIntakeLabel(
  label: string,
  t: (key: string) => string,
  locale: string,
): string | null {
  const s = label.trim();
  if (!s) return null;
  if (/^\d{4}$/.test(s)) return s;
  const monthRe = new RegExp(`^(?:(\\d{1,2})\\s+)?(${MONTHS_EN.join('|')})\\s+(\\d{4})$`, 'i');
  const m = monthRe.exec(s);
  if (m) {
    const monthIndex = MONTHS_EN.indexOf(m[2].toLowerCase());
    const day = m[1] ? Number(m[1]) : undefined;
    const year = Number(m[3]);
    try {
      const fmt = new Intl.DateTimeFormat(locale, day
        ? { day: 'numeric', month: 'long', year: 'numeric' }
        : { month: 'long', year: 'numeric' });
      return fmt.format(new Date(year, monthIndex, day ?? 1));
    } catch {
      return null;
    }
  }
  const seasonRe = new RegExp(`^(${SEASONS_EN.join('|')})(?:\\s+session)?\\s+(\\d{4})$`, 'i');
  const sm = seasonRe.exec(s);
  if (sm) {
    const key = `intake.season.${SEASON_KEY[sm[1].toLowerCase()]}`;
    const v = t(key);
    if (v === key) return null;
    return v.replace('{year}', sm[2]);
  }
  return null;
}

/** Localise the parenthetical of a duration ("180 credits",
 * "180 ECTS", "4 semesters, 120 ECTS"). Each comma-separated part
 * must be a plain "<number> <unit>" the locale files know; anything
 * else returns null so the caller falls back to the raw value
 * instead of rendering an invented one. ECTS is a standard acronym
 * and stays "ECTS" in every locale (like IELTS elsewhere); only the
 * surrounding words are localised. Parenthesis style follows the
 * locale: full-width （） with ， in zh-CN, half-width () with ", "
 * elsewhere. */
const DURATION_PAREN_PART = /^(\d+)\s+(semesters?|credits?|ects)$/i;

function localiseDurationParen(
  inner: string,
  t: (key: string) => string,
  locale: string,
): string | null {
  const cjk = locale === 'zh-CN';
  const parts: string[] = [];
  for (const raw of inner.split(',')) {
    const m = DURATION_PAREN_PART.exec(raw.trim());
    if (!m) return null;
    const n = Number(m[1]);
    const unit = m[2].toLowerCase();
    const key = unit === 'ects'
      ? 'format.ects'
      : unit.startsWith('semester')
        ? (n === 1 ? 'format.semester' : 'format.semesters')
        : (n === 1 ? 'format.credit' : 'format.credits');
    const v = t(key);
    if (v === key) return null;
    parts.push(v.replace('{n}', String(n)));
  }
  if (!parts.length) return null;
  return `${cjk ? '（' : '('}${parts.join(cjk ? '，' : ', ')}${cjk ? '）' : ')'}`;
}

/** Round 21: the parameter is Pick<Program, 'id' | 'duration'>, not
 * Program — the function only reads those two fields, and the
 * institution page's expansion cards (ExpansionProgram) must reuse
 * this same path instead of rendering their raw duration. No caller
 * changes: every Program still satisfies the narrower type. */
export function formatDuration(program: Pick<Program, 'id' | 'duration'>, t: (key: string) => string, locale = 'en'): string {
  const key = `program.duration.${program.id}`;
  const v = t(key);
  if (v !== key) return v;
  // Generic fallback for expansion programmes: "3 years", "12 months",
  // "1 year full-time" — parsed, never rendered as raw English.
  // Round 19: the parenthetical is parsed too — "3 years
  // (180 credits)" / "3 years (180 ECTS)" / "2 years (4 semesters,
  // 120 ECTS)" — because the UZH card fell through here: its
  // duration has a parenthetical the old regex could not match, and
  // it carried no per-programme key. A parenthetical the parser does
  // not know ("1.5 years (three terms)", "2-3 years") still falls
  // back to the raw value rather than an invented rendering.
  const s = (program.duration || '').trim();
  const m = /^(\d+(?:\.\d+)?)\s+(years?|months?)(?:\s+full-time)?(?:\s*\(([^)]+)\))?$/i.exec(s);
  if (m) {
    const n = Number(m[1]);
    const head = s.replace(/\s*\([^)]*\)\s*$/, '');
    const fullTime = /\bfull-time$/i.test(head);
    const unit = m[2].toLowerCase().startsWith('month') ? 'month' : 'year';
    const k = fullTime
      ? (n === 1 ? 'format.yearFullTime' : 'format.yearsFullTime')
      : (unit === 'month' ? (n === 1 ? 'format.month' : 'format.months') : (n === 1 ? 'format.year' : 'format.years'));
    const out = t(k);
    if (out === k) return program.duration;
    const base = out.replace('{n}', String(n));
    if (!m[3]) return base;
    const paren = localiseDurationParen(m[3], t, locale);
    if (paren === null) return program.duration;
    return `${base}${locale === 'zh-CN' ? '' : ' '}${paren}`;
  }
  return program.duration;
}

export function formatIntake(program: Program, t: (key: string) => string, locale = 'en'): string {
  const key = `program.intake.${program.id}`;
  const v = t(key);
  if (v !== key) return v;
  return localiseIntakeLabel(program.intakeLabel, t, locale) ?? program.intakeLabel;
}

export function formatFeeItem(f: FeeItem, t: (key: string) => string, locale: string): string {
  const period = f.period === 'total' ? t('fee.period.total') : t('fee.period.perYear');
  return `${f.currency} ${fmtNum(f.amount, locale)} ${period}`;
}

/** Fee with its home / overseas label ("Overseas: GBP 47,800 per
 * year"), so a card never shows two same-currency fees without saying
 * which is which. Labels come from the fee item's own text: an
 * "Overseas" item is the international fee, a "UK" item the home fee,
 * anything else plain tuition. */
export function feeItemLabel(f: FeeItem, t: (key: string) => string): string {
  if (/overseas/i.test(f.label)) return t('fee.label.overseas');
  if (/^\s*UK\b/i.test(f.label) || /\bhome\b/i.test(f.label)) return t('fee.label.home');
  return t('fee.label.tuition');
}

export function formatFeeItemWithLabel(f: FeeItem, t: (key: string) => string, locale: string): string {
  return `${feeItemLabel(f, t)}${t('common.colon')} ${formatFeeItem(f, t, locale)}`;
}

export function formatFeeItems(program: Program, t: (key: string) => string, locale: string): string {
  return program.feeItems.map((f) => formatFeeItem(f, t, locale)).join(', ');
}

/** The fee item that applies to this applicant: the home item for a UK
 * resident, the overseas item otherwise; then the item in the budget
 * currency; then the first item. A UK programme with both fees used to
 * resolve by currency alone, which could pick the home fee for an
 * overseas applicant (both are GBP). */
export function pickFeeItem(program: Program, profile: Profile): FeeItem | undefined {
  const items = program.feeItems;
  if (!items.length) return undefined;
  const isHome = (f: FeeItem) => /^\s*UK\b/i.test(f.label) || /\bhome\b/i.test(f.label);
  const isOverseas = (f: FeeItem) => /overseas/i.test(f.label);
  if (profile.residency === 'uk') {
    return items.find(isHome) ?? items.find((f) => f.currency === (profile.budgetCurrency ?? '')) ?? items[0];
  }
  return items.find(isOverseas)
    ?? items.find((f) => f.currency === (profile.budgetCurrency ?? '')) ?? items[0];
}

/** "September 2026 · 3 years full-time · GBP 46,700 per year" line,
 * in the current locale. */
export function formatProgramLine(program: Program, t: (key: string) => string, locale: string): string {
  return `${formatIntake(program, t, locale)} · ${formatDuration(program, t, locale)} · ${formatFeeItems(program, t, locale)}`;
}
