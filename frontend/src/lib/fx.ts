// FX reference rates — hand-written static mirror of
// data/expansions/fx_rates.json (Round 9, R2). NOT a generated mirror
// file: keep the rates and the as-of date in sync with that file by
// hand when the table is refreshed (see docs/FX_RATES.md).
//
// Approximate reference rates ONLY, for comparing a programme fee
// with an applicant budget in a different currency. Rates are units
// of the currency per 1 GBP, rounded to three significant figures.
// A converted figure is always approximate — label it as such
// ("about GBP 4,000"), never as exact.

export const FX_AS_OF = '2026-11-26';
export const FX_SOURCE =
  'Mid-market rates, 26 Nov 2026 (exchangerates.org.uk / forexinvestors.com / Finnhub)';

export const FX_RATES_PER_GBP: Record<string, number> = {
  GBP: 1,
  CHF: 1.09,
  EUR: 1.19,
  USD: 1.31,
  AUD: 1.98,
  CAD: 1.86,
  HKD: 10.3,
  CNY: 8.73,
  JPY: 209,
  KRW: 1760,
  SEK: 13.4,
  NZD: 2.39,
  DKK: 8.93,
  TWD: 43.2,
  ARS: 2100,
  MYR: 5.4,
  SAR: 4.92,
  SGD: 1.69,
};

/** Convert `amount` from currency `from` to currency `to` via GBP.
 * Returns null when either currency has no reference rate — the
 * caller must then treat the fee as UNKNOWN (cannot be converted),
 * never as a mismatch. */
export function convertCurrency(
  amount: number,
  from: string,
  to: string,
): number | null {
  if (from === to) return amount;
  const fromRate = FX_RATES_PER_GBP[from];
  const toRate = FX_RATES_PER_GBP[to];
  if (
    typeof fromRate !== 'number' ||
    typeof toRate !== 'number' ||
    fromRate <= 0 ||
    toRate <= 0
  ) {
    return null;
  }
  return (amount / fromRate) * toRate;
}
