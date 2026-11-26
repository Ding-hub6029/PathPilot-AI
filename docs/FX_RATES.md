# FX reference rates (Round 9, R2)

## What this is

`data/expansions/fx_rates.json` is a small, dated, **approximate**
reference table used ONLY to compare a programme's tuition fee with an
applicant's budget when the two are in different currencies. Before
Round 9 the generic expansion fee rule refused every cross-currency
comparison as UNKNOWN, and the UI rendered that as a false budget
mismatch ("你的预算与该课程的学费不匹配") — e.g. a CHF 4,380 fee
against a GBP 50,000 budget. The rule now converts with this table
instead.

## The table

- **As of:** 2026-11-26 (mid-market rates retrieved that day).
- **Source:** exchangerates.org.uk ("Live Currency Exchange Rates
  Table", 26 Nov 2026, 09:06 GMT), forexinvestors.com ("British Pound
  Exchange Rates", 26 Nov 2026) and Finnhub GBP cross rates
  (1 GBP = 1.0925 CHF as of 2026-11-26 11:16 UTC; 1 GBP = 13.3907 SEK;
  1 GBP = 2102.3498 ARS).
- **Base:** GBP. Each value is "units of the currency per 1 GBP"
  (e.g. CHF 1.09 means 1 GBP = 1.09 CHF).
- **Precision:** rounded to three significant figures on purpose.
  These rates are coarse by design — a converted fee is an
  approximation, never an exact figure, and must always be labelled
  as such (e.g. "about GBP 4,000", "约 £4,000").
- **Coverage:** every currency that appears on a matchable expansion
  programme's fee (AUD, ARS, CAD, CHF, CNY, DKK, EUR, GBP, HKD, JPY,
  KRW, MYR, NZD, SAR, SEK, SGD, TWD, USD). A currency with no rate
  here cannot be converted: the fee rule returns UNKNOWN ("cannot be
  converted for comparison"), NEVER a mismatch.

## How conversion works

To compare a fee in currency F with a budget in currency B, the fee
is converted into B via GBP:

```
fee_in_B = fee_amount / rate[F] * rate[B]
```

The budget is then compared with the converted fee: budget >=
converted fee is MET, otherwise NOT_MET. The rule detail records the
approximate converted figure, the rate used and the as-of date, e.g.
"Budget GBP 50,000 per_year covers the CHF 4,380 per_year fee
(about GBP 4,018 at the reference rate 1 GBP = 1.09 CHF, 26 Nov
2026 — approximate)". Same-currency comparisons are exact and
unchanged; a fee period that differs from the budget period
(per_year vs total) is still UNKNOWN, as is a per-credit fee.

## Frontend mirror

`frontend/src/lib/fx.ts` is a hand-written static copy of the same
table (same rates, same as-of date) used by the offline evaluator in
`frontend/src/lib/api.ts`. It is NOT a generated mirror file — keep
the two in sync by hand when the table is refreshed, and update the
as-of date in both places.

## Refreshing

Refresh the table when it is visibly stale (roughly monthly, or when
a rate has moved enough to change a verdict near a boundary). Update
`as_of`, the rates, and this doc's source lines together; never
refresh one currency in isolation. Do NOT fetch live rates at
request time: the table must stay a fixed, reviewable snapshot so a
verdict can be reproduced from the data version.
