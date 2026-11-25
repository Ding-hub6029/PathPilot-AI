import { FeeItem, Program } from './types';

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
 */

const fmtNum = (n: number, locale: string): string => n.toLocaleString(locale);

export function formatDuration(program: Program, t: (key: string) => string): string {
  const key = `program.duration.${program.id}`;
  const v = t(key);
  return v === key ? program.duration : v;
}

export function formatIntake(program: Program, t: (key: string) => string): string {
  const key = `program.intake.${program.id}`;
  const v = t(key);
  return v === key ? program.intakeLabel : v;
}

export function formatFeeItem(f: FeeItem, t: (key: string) => string, locale: string): string {
  const period = f.period === 'total' ? t('fee.period.total') : t('fee.period.perYear');
  return `${f.currency} ${fmtNum(f.amount, locale)} ${period}`;
}

export function formatFeeItems(program: Program, t: (key: string) => string, locale: string): string {
  return program.feeItems.map((f) => formatFeeItem(f, t, locale)).join(', ');
}

/** "September 2026 · 3 years full-time · GBP 46,700 per year" line,
 * in the current locale. */
export function formatProgramLine(program: Program, t: (key: string) => string, locale: string): string {
  return `${formatIntake(program, t)} · ${formatDuration(program, t)} · ${formatFeeItems(program, t, locale)}`;
}
