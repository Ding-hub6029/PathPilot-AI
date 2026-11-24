# Locale Coverage — PathPilot AI frontend (Day 1)

All UI copy lives in `messages/{locale}.json` (98 keys each), except a few
hardcoded bits: the Header 🌐/☰ icons, the program-detail "←" back link, and
the wizard placeholders "A*A*A"/"A*". `npm run build` runs `scripts/check-locales.mjs`, which
fails if any locale is missing a key, has an extra key, or has an empty value.

| Locale | File | Keys | Status |
|---|---|---|---|
| en | `messages/en.json` | 98 | Complete |
| zh-CN | `messages/zh-CN.json` | 98 | Complete |
| es | `messages/es.json` | 98 | Complete |
| fr | `messages/fr.json` | 98 | Complete |
| pt-BR | `messages/pt-BR.json` | 98 | Complete |
| ar | `messages/ar.json` | 98 | Complete (RTL: `dir=rtl`, `lang=ar`; logical properties used for header menu alignment) |

## Coverage per page / state

| Page / state | en | zh-CN | es | fr | pt-BR | ar |
|---|---|---|---|---|---|---|
| Home (hero, how-it-works, programme cards, disclaimer) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Wizard (track, target, academic, language, budget, errors) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Results (cards, filters, blockers, unknown counts, simulation) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Programme detail (rules, evidence drawer, sources) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Report (summary, download/print) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Loading / empty / error / offline states | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Header + language switcher (own-name labels) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Track-mismatch friendly error | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

## What stays untranslated (by design)

- Trademark: "PathPilot AI"
- University names: "University College London", "National University of Singapore"
- URLs, exam abbreviations (IELTS, TOEFL, GRE, GMAT, UCAS), programme codes (G400)
- User-entered input (grades, degree text) and numbers/currency amounts

## Known gaps (honest)

- RTL layout was verified by code inspection (logical `ms-`/`ps-`/`end-` classes,
  `dir`/`lang` set on `<html>`), **not** in a live browser — no live-browser
  access in this build environment. Visual RTL check still needed.
- Arabic translations were written by the builder, not reviewed by a native
  speaker; same for es/fr/pt-BR. Treat as Day-1 drafts.
- Switching language keeps profile, filters, simulation, step and scroll
  (single-page React state + localStorage persistence), but scroll-position
  restore after a language switch has not been live-tested.
- `next/font` is not used; system fonts render CJK/Arabic via the OS.
