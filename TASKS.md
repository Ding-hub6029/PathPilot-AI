# TASKS.md — PathPilot AI Day 1

Status values only: `todo` / `in-progress` / `pass` / `blocked` / `cancelled`.

## Acceptance command

```bash
cd ~/workspace/pathpilot-ai
.venv/bin/python -m pytest tests/ -v
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/api/v1/health
```

## Day 1 — backend + data (this agent)

| ID | Task | Depends on | Artefacts | Status |
|---|---|---|---|---|
| D1-01 | JSON Schemas (StudentProfile, Program, Requirement, Source, SourceFact, Evaluation, RuleResult) | — | `data/schemas/*.json` | pass |
| D1-02 | Verified data v1: 2 real programmes + source manifest + quality report | D1-01 | `data/versions/v1/programs.json`, `source-manifest.json`, `QUALITY_REPORT.md` | pass |
| D1-03 | Synthetic fixture (fixture-p01, IELTS writing 6.0), never in real data | D1-02 | `data/fixtures/fixture-p01.json` | pass |
| D1-04 | FastAPI backend: /health, /programs, /programs/{id}, /profile/validate, /match, /explain, /simulate, /ready | D1-02 | `backend/app/main.py`, `backend/app/schemas.py`, `backend/app/data.py` | pass |
| D1-05 | Pure rules engine (MET/NOT_MET/UNKNOWN/NOT_APPLICABLE) | D1-02 | `backend/domain/eligibility.py` | pass |
| D1-06 | ProviderAdapter env stub + citation-checked template explain | D1-04 | `backend/ai/provider.py`, `backend/ai/explain.py` | pass |
| D1-07 | Pytest suite (25 tests after Day 1 audit fixes) + real run recorded | D1-05, D1-04 | `tests/test_eligibility.py` | pass |
| D1-08 | Live verification: uvicorn start + curl /health, /programs, /match, /simulate | D1-04, D1-07 | `docs/STARTING_POINT.md` (verification note) | pass |
| D1-09 | Tracking docs + README | D1-08 | `TASKS.md`, `DECISIONS.md`, `BLOCKERS.md`, `RELEASE_CHECKLIST.md`, `docs/SOURCES.md`, `docs/STARTING_POINT.md`, `README.md` | pass |

## Day 1 — integration (coordinator, after both agents)

| ID | Task | Depends on | Artefacts | Status |
|---|---|---|---|---|
| D1-10 | Frontend/backend contract adapter (flat wizard profile + program_ids) | D1-04, D2-01 | `backend/app/adapter.py`, `tests/test_api_contract.py` | pass |
| D1-11 | Fix frontend source URLs (NUS fees `/pg/mis/` → `/pg/mcs/`; UCL pages → verified `-2026` URL; English → UCL Level 1 page; fix A-level excerpt) | D1-02 | `frontend/src/lib/programs.ts` | pass |
| D1-12 | Live end-to-end verification: backend + frontend production build, all pages 200, proxy /api/match + /api/simulate | D1-10, D1-11 | this file + `frontend/VERIFICATION.md` (integration note) | pass |

## Day 2 — frontend (this agent, 2026-11-25)

| ID | Task | Depends on | Artefacts | Status |
|---|---|---|---|---|
| D2-F01 | Wizard Day-2 fields: IB total / HL Maths / HL total, GCSE English + Maths, residency (uk/overseas) + overseas-fee note (£46,700 vs £9,790), intake year, test date, graduation status, IT experience years; TOEFL kept separate from IELTS (both sendable) | D2-05 | `frontend/src/app/wizard/page.tsx`, `frontend/src/lib/types.ts` | pass |
| D2-F02 | Data-driven programme list: GET /api/v1/programs with limit/cursor, backend-shape normaliser, local fallback; used by home, wizard, results, report, programme detail | D1-04, D2-06 | `frontend/src/lib/api.ts` (`fetchPrograms`, `fetchProgramById`, `normalizeApiProgram`), `frontend/src/lib/usePrograms.ts` | pass |
| D2-F03 | Evidence drawer on programme detail + results: source label, clickable official URL, excerpt (labelled English-only), verified date, intake applicability; works for API-loaded programmes, unmatched evidence ids shown as unavailable | D2-05 | `frontend/src/components/EvidenceDrawer.tsx`, `frontend/src/app/programs/[id]/page.tsx`, `frontend/src/app/results/page.tsx` | pass |
| D2-F04 | i18n: 28 new keys in all 6 locales (98 → 126 keys); locale check passes; default language stays en per DECISIONS #43, no browser detection | D2-07 | `frontend/messages/*.json` | pass (Day 2 integration, 2026-11-25: +12 keys — degree class + 5 options, masters maths grade, 5 SG residency options — 126 → 138 keys × 6 locales; `npm run build` locale check passes) |
| D2-F05 | Live verification: build pass, all 6 pages 200, proxy /api/programs + /api/match + /api/simulate verified, incl. new-fields profiles | D2-F01–D2-F04 | `frontend/VERIFICATION.md` (Day 2 section) | pass |

Notes (superseded 2026-11-25, Day 2 integration): `~/workspace/day2_courses.json` was merged into `data/versions/v2/` (8 programmes, 72 facts, 29 sources, 25 unknowns) and the 6 new courses ARE wired in — `frontend/src/lib/programs.ts` carries all 8 entries as the offline fallback and the API serves v2. The offline evaluator (`evaluateLocal` in `frontend/src/lib/api.ts`) now mirrors the new Day-2 rules (IB/HL total, GCSE, TOEFL date split, residency fees, all 6 new programmes) per DECISIONS #64.

## Day 2–3 (not this agent's scope)

| ID | Task | Depends on | Status |
|---|---|---|---|
| D2-01 | Frontend (another agent owns `frontend/`) — 6-language framework, UI copy | D1-04 | pass |
| D2-02 | GitHub repository creation + push (user's GitHub access, public repo) | D1-09 | pass (pushed 2026-11-24 ~13:22, 11 batches, 65 files, HEAD ccf8aba; Day 1 audit fixes pushed 2026-11-25 00:22–00:25 in 6 batches + README fix, HEAD 692950a, verified 0 local/repo differences) |
| D2-03 | Local demo recording / deployment only if needed | D1-09 | blocked — user action needed (Day 2, 2026-11-25: app is deploy-ready — `DEPLOY.md`, `backend/Dockerfile`, env-driven `API_BASE_URL`, Vercel deploy button in README — but no public link: Vercel connector reports `not_connected`, no host account exists; needs the user's Vercel OAuth authorisation + a Railway/Render backend host. No account created, no money spent.) |
| D2-04 | /explain must recompute server-side (spec Ch12), not accept a client-supplied Evaluation — forged KNOWN_MINIMUMS_MET demonstrated live in the Day 1 audit | D1-04 | pass (Day 2, 2026-11-25: new shape {profile, program_ids, locale}, nested or flat profile; old {evaluation} shape returns 422 EXPLAIN_REQUIRES_PROFILE; verified live + tests/test_day2.py::test_explain_forged_evaluation_422, test_explain_recomputes_from_profile) |
| D2-05 | Wizard/engine fields missing from Day 1: IB total + HL Maths, IT experience years, intake year, test date, graduation status, residency/domicile, GCSEs, HL total points; adapter must not silently drop TOEFL when IELTS fields are present | D1-05 | pass (Day 2, 2026-11-25: backend schemas + adapter map all fields, IELTS + TOEFL both passed through; wizard has IB total/HL Maths/HL total, GCSE English/Maths, test date, graduation status, IT experience years, intake year, residency incl. SG bands, degree class + masters maths grade; UCL TOEFL Jan 2026 scale split fixed via test date; 6 new v2 evaluators in backend/domain/eligibility.py; offline evaluator mirrors them in frontend/src/lib/api.ts) |
| D2-06 | /programs filtering + pagination, /profile/validate full shape, rate limiting + security headers + OpenAPI, Decimal for money, traceability.csv, evidence translations | D1-04 | pass (Day 2, 2026-11-25: filtering + cursor pagination, validate returns {valid, application_track, normalized_profile, warnings, field_errors}, 60/min + 10/min explain rate limits, security headers, docs/openapi.json generated, Budget.amount Decimal, data/versions/v2/traceability.csv generated; evidence translations NOT done — excerpts labelled English-only per DECISIONS #35; total 79 passed) |
| D2-07 | Real AI provider call (FR06) or explicit P0 deferral; browser-language first-visit default (spec FR11) | D1-06 | pass (Day 2: default language DECIDED — English, first-open, no browser detection, DECISIONS #41/#54; AI provider explicitly deferred, DECISIONS #61 — no key, no spend authorisation, rules/template mode with citation-checked explain) |

## Test result (real run, 2026-11-24)

Command: `.venv/bin/python -m pytest tests/ -v`
Result: **25 passed, 0 failed** (19 original + 6 Day 1 audit-fix tests; pytest 8.3.4, Python 3.12.3, re-run 2026-11-24 after the audit fixes).
Frontend: `npm run build` **pass** (locale check 6×98 keys, all routes).
Live: backend :8000 + frontend :3000, all 6 pages 200, proxy `/api/match` and `/api/simulate` verified (writing 5.5 → NOT_MET; patch to 6.5 → MET, delta recorded). Audit fixes re-verified live 2026-11-24: NUS related-bachelor's + 2y → UNKNOWN (was false MET), UCL contextual A*AB → UNKNOWN (was NOT_MET), NUS IELTS components → NOT_APPLICABLE.

## Test result (real run, 2026-11-25, Day 2 backend)

Command: `.venv/bin/python -m pytest tests/ -q`
Result: **67 passed, 0 failed** (25 Day 1 + 6 contract + 36 new Day 2 in tests/test_day2.py; pytest 8.3.4, Python 3.12.3). No Day 1 test expectations changed — the IB HL-total change (DECISIONS #44) had no Day 1 test asserting IB MET without an HL total.
Live: backend :8000 restarted with Day 2 code, curl /api/v1/health ok (data_version v1, 2 programs), /api/v1/programs?country=GB returns UCL only, /api/v1/openapi.json + /openapi.json + /docs all 200, security headers present on every response, forged /explain returns 422 EXPLAIN_REQUIRES_PROFILE, real /explain recomputes (writing 5.5 → NOT_MET).

## Test result (real run, 2026-11-25, Day 2 final)

Command: `.venv/bin/python -m pytest tests/ -q`
Result: **79 passed, 0 failed** (25 Day 1 + 6 contract + 36 Day 2 + 12 v2 in tests/test_day2_v2.py; pytest 8.3.4, Python 3.12.3, 1 anyio deprecation warning). No Day 1 audit-fix regression.
Frontend: `npm run build` **pass** (locale check 6 × 138 keys, all routes).
Live: backend :8000 restarted with Day 2 v2 code — `GET /api/v1/health` → `{"status":"ok","data_version":"v2","programs":8}`; `GET /api/v1/programs?limit=20` → 8 items; frontend :3000 — all 8 pages 200 (`/`, `/wizard`, `/results`, `/programs/ucl-cs-bsc-2026`, `/programs/nus-mcomp-cs`, `/programs/imperial-comp-beng-2027`, `/programs/ntu-msai-2027`, `/report`); proxy `/api/programs` → 8 items v2; `/api/match` Imperial BEng (A*A*A + IELTS 7.0 → academic/language MET, TMUA UNKNOWN) and NTU MSAI (honours CS + IELTS 7.0 → academic/language MET, GRE UNKNOWN); `/api/simulate` IELTS writing 5.5 → 6.5 delta `ucl-ielts-components NOT_MET → MET`; forged `/explain` → 422; real `/explain` recomputes (writing 5.5 → NOT_MET); security headers present on every response.
Deployment: NOT live — blocked on the user's Vercel OAuth + backend host; see D2-03 and `DEPLOY.md`.

## Fix 2026-11-25 — language, status chips, curriculum branching (user-reported, this agent)

| ID | Task | Artefacts | Status |
|---|---|---|---|
| F-01 | Localise every rule text: frontend renders from structured `observedRaw`/`thresholdRaw` + locale catalogue (`frontend/src/lib/ruleText.ts`, `format.ts`); backend English strings stay as fallbacks; excerpts stay in original language, labelled | `frontend/src/lib/ruleText.ts`, `frontend/src/lib/format.ts`, `frontend/src/components/RuleRow.tsx` | pass |
| F-02 | Labelled status chips (`学术：符合` etc.) + legend + "要求 / 你的情况" on every rule row; fee sentence ("你的预算 GBP 22/年，低于学费 GBP 46,700/年"); detail-page minimums from verified data + "开始资格检查" button; back link "返回首页"; duration/intake/fee period localised | `frontend/src/app/results/page.tsx`, `frontend/src/app/programs/[id]/page.tsx`, `frontend/src/app/report/page.tsx`, `frontend/src/components/StatusChip.tsx` | pass |
| F-03 | Curriculum-first wizard (step 0: China Gaokao / UK A-level+GCSE / IB / USA SAT-ACT-AP / Singapore A-level / Other); only the branch's fields shown; switching curriculum clears other branches' fields; masters academic step unchanged | `frontend/src/app/wizard/page.tsx`, `frontend/src/lib/types.ts` | pass |
| F-04 | Backend curriculum branching: `curriculum` + Gaokao/SAT/ACT/AP fields in schemas, adapter, engine (`effective_curriculum`, `_ug_observed`, `_ap_route_met`, GCSE rule); `observedRaw`/`thresholdRaw`/`reasonKey` in `rule_to_frontend`; `/profile/validate` range checks | `backend/app/schemas.py`, `backend/app/adapter.py`, `backend/domain/eligibility.py`, `backend/app/main.py`, `docs/openapi.json`, `data/schemas/student-profile.json` | pass |
| F-05 | Offline evaluator mirrors the branches + supplementary TOEFL rules (`nus-toefl`, `ntu-msai-toefl`); `ucl-ielts-components` threshold `{each_component}` renders all four components | `frontend/src/lib/api.ts` | pass |
| F-06 | i18n: 138 → 306 keys × 6 locales (44 rule expected texts, 15 short chip names, 21 observed fragments, 16 reason keys, 16 programme duration/intake, 29 wizard keys, legend/next-steps/modal/fee-period keys); es/fr/pt-BR/ar translated by subagent, verified by `check-locales` | `frontend/messages/*.json` | pass |
| F-07 | First-visit modal (smiley, CTA, `results.empty` line, localStorage `pp-welcome-dismissed`, prefers-reduced-motion via global rule); results next-steps panel (summary counts + `/report` + `/wizard`) + per-card "View report" link; home banner wording "built-in verified programme catalogue — the live backend is not connected yet" | `frontend/src/components/WelcomeModal.tsx`, `frontend/src/app/page.tsx`, `frontend/src/app/results/page.tsx` | pass |
| F-08 | Verification: pytest, `npm run build`, live backend + production frontend, zh-CN render test (offline evaluator + ruleText/format with real locale files) | this file | pass (see "Test result (real run, 2026-11-25, fix)" below) |

## Test result (real run, 2026-11-25, fix)

Command: `.venv/bin/python -m pytest tests/ -q` → **92 passed, 0 failed** (79 Day 2 + 13 new in `tests/test_curriculum.py`: Gaokao → UNKNOWN for UCL/Imperial, USA AP below-standard NOT_MET / standard-met UNKNOWN, SG A-level MET, IB unchanged, adapter flat mapping, `/profile/validate` field errors; 1 anyio deprecation warning). No Day 1 audit-fix regression.
Frontend: `npm run build` **pass** (locale check 6 × 306 keys, type check, all 7 routes).
Live: backend :8000 (`{"status":"ok","data_version":"v2","programs":8}`) — `/api/v1/match` Gaokao 680/750 (UCL + Imperial academic UNKNOWN, `gaokao-no-equivalence`, GCSE NOT_APPLICABLE, fee NOT_MET with `observedRaw` 22 / `thresholdRaw` `{gbp_per_year: 46700}`), SG A-level A*A*A (academic MET both), USA AP 5,5,5,4,4 + SAT 1500 (Imperial UNKNOWN `usa-ap-general-only`, UCL UNKNOWN `usa-no-equivalence`); frontend production build on :3000 — all 5 pages 200, detail page SSR shows "Back to home" + minimums note + "IELTS overall 6.5" + "Start eligibility check", wizard SSR shows "Where are you studying?", zh-CN strings present in the built chunks.
Render test (`/tmp/pp-test-src/render-test.ts`, standalone tsc + node, fake `t()` backed by `messages/zh-CN.json` + `en.json`): **all checks passed** — screenshot scenario chips ("学术：符合 / 雅思总分：符合 / 雅思单项：不符合 / TARA：未知 / 学费：不符合"), fee sentence "你的预算 GBP 22/年，低于学费 GBP 46,700/年", components "雅思听力 6.5 / 雅思阅读 6.5 / 雅思写作 5.5 / 雅思口语 6.5", Gaokao "高考 680/750" + Gaokao reason, USA AP observed/reason, backend-shaped fee/Gaokao rules, all 42 detail-page minimums entries and all 16 reason keys in zh-CN and en. The test caught 3 real bugs before the build: `ucl-ielts-components` chip fell through to "规则" (shortKey miss), components observed fell through to the raw-object dump (dispatch missed `-ielts-components`), and `rule.ntu-msai-language-components.expected` was missing from the catalogue and from the backend EXPECTED dict — all fixed, re-verified.
Not verified (needs a real browser): visual click-through of the wizard modal/chips in all 6 locales, Arabic RTL rendering, modal show/dismiss behaviour, scroll retention on language switch, keyboard pass, print/PDF. These are user manual-testing items (BLOCKERS #7/#11).
"Budget GBP 22/year" finding: the 22 was the user's own entered budget, not a sample — `sampleUndergrad` budget is 50000 GBP, `sampleMasters` 70000 SGD. Only the blocker-line format was wrong; no sample changed.
