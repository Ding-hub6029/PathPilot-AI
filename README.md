# PathPilot AI

Evidence-based university selection (UK & Singapore), computer-related
undergraduate + taught masters, two independent tracks.
Built for the **Global AI Builder's Challenge 2026** (event Nov 21–28 2026;
submissions due **Nov 28 15:00 PST = Nov 29 07:00 Beijing**).

Day 1 scope (complete, integrated 2026-11-24): backend + verified data +
schemas + tests + tracking docs + frontend (Next.js, 6 languages, wizard,
results, simulation, evidence drawer) + live end-to-end verification.
Pushed to the public GitHub repo on Day 1.

Day 2 scope (complete 2026-11-25, pushed HEAD 963347a): 8 real programmes
(2 per UK/SG × UG/taught-masters cell) on data version `v2`, server-side
`/explain`, wizard fields (IB/HL total, GCSE, test date, graduation status,
residency incl. Singapore bands, degree class), `/programs` filtering +
pagination, rate limiting, security headers, OpenAPI, Decimal money,
traceability.csv, 138 i18n keys × 6 locales, evidence drawer, 79 tests
passing, live verification green. Deployment is ready but not live — see
`DEPLOY.md` (needs the user's Vercel OAuth + a backend host).

Fix 2026-11-25 (complete, pushed 2026-11-25 ~11:00, HEAD 259cf92; Vercel
redeployed and verified live): full localisation of rule text
(status chips carry rule names, "要求 / 你的情况" on every rule row,
fee sentence "你的预算 GBP 22/年，低于学费 GBP 46,700/年", legend,
detail-page minimums + "开始资格检查" button, first-visit modal,
"返回首页", curriculum-first wizard with Gaokao / UK A-level / IB /
USA SAT-ACT-AP / Singapore A-level / Other branches), 306 i18n keys × 6
locales, 92 tests passing, `npm run build` pass, live verification green.
See TASKS.md (Fix section) and DECISIONS.md #66–#80.

Day 3 rankings (complete 2026-11-25, not yet pushed): `/rankings` page +
ranking cards on programme detail pages + institution detail pages
(`/institutions/[id]`). Three providers (QS 2027, THE 2027, ARWU 2026),
top 100 institutions each = 300 entries across 148 institutions, world
ranks only, verified one by one from each provider's official source on
2026-11-25 (`data/versions/v2/rankings.json`,
`docs/RANKINGS_SOURCES.md`). QS values shown with the exact QS attribution
notice; THE values labelled "reproduction consent not obtained"; ARWU
"reuse permission not verified". No combined/average rank across providers
(BR15); rankings never affect eligibility (BR16). Institution pages carry a compiled IELTS reference transcribed from the
user-supplied THE 2027 table images, labelled as a reference in all 6
locales and never used by the eligibility engine; verified programmes
link to their full detail, other institutions show "programme admission
data not yet verified". Language fix 2026-11-25: 127 of the 148
institutions carry a verified Chinese display name (`name_zh`, from the
user-supplied THE/ARWU table images, THE preferred on conflicts, plus
National Taiwan University and Korea University verified on their official
sites; the 21 QS-only institutions without one fall back to English) and
country names are localised in all 6 locales — in zh-CN the institution
and programme pages show the Chinese names, everywhere else the English
official names. The `/rankings` page itself still renders English names
until the same display helpers are applied there (see DECISIONS.md #97).

Day 3 desktop-pet assistant 小罗盘 (complete 2026-11-25, not yet pushed):
a small round compass mascot floating bottom-end on every page; click opens
a chat panel with at most 3 opening questions (undergraduate/masters,
UK/Singapore, budget — one-tap quick replies), then a short route
suggestion (max 3 lines, conclusion first, ONE evidence link) plus
direct next-step buttons (start eligibility check, view programme).
Rules/template mode only — no model is connected (`ai_status=unavailable`,
panel says so); unknown stays unknown, no admission probabilities, no
personal data collected. Free text answers programme fee / IELTS /
deadline questions and rank lookups from the verified catalogue only.
125 tests passing, 386 i18n keys × 6 locales, `npm run build` pass.
See TASKS.md (pet section) and DECISIONS.md #93–#96.

## Quick start (one command per service; run backend first)

```bash
cd ~/workspace/pathpilot-ai
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
# in a second terminal:
cd frontend && npm install && npm run dev   # http://localhost:3000
```

### Backend (port 8000)

```bash
cd ~/workspace/pathpilot-ai
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

### Frontend (port 3000)

```bash
cd frontend && npm install && npm run dev   # or: npm run build && npm start
```

Next.js 14 + TypeScript + Tailwind. Pages: `/` (home, first-visit modal),
`/wizard` (curriculum first, then track / target / academic / language /
budget), `/results` (labelled chips, legend, next-steps panel),
`/programs/[id]` (minimums list + check button, evidence drawer, ranking
cards), `/rankings` (three providers, top 100 each, filters, compare up to 3 institutions
within one provider's edition, institution detail pages), `/report` (print + JSON export),
plus the 小罗盘 pet on every page (bottom-end floating compass button).
Six locales (en, zh-CN, es, fr, pt-BR, ar; 386 keys each, checked by
`npm run build`), RTL for Arabic, compass-theme motion (navy/teal/amber),
`prefers-reduced-motion` respected. The frontend proxies `/api/*` to the
backend; if the backend is down it falls back to a clearly-labelled
offline evaluator — start the backend first for live results.

### Tests

```bash
.venv/bin/python -m pytest tests/ -v
# real run 2026-11-25: 92 passed, 0 failed (25 Day 1 + 6 contract + 36 Day 2 + 12 v2 + 13 curriculum)
cd frontend && npm run build   # real run 2026-11-25: pass (locale check 6 x 306 keys + all routes)
```

Live end-to-end (2026-11-24): backend :8000 + frontend :3000, all 6 pages
HTTP 200, proxy `/api/match` + `/api/simulate` verified — IELTS writing 5.5
→ component NOT_MET; patch to 6.5 → MET with delta recorded.
Live end-to-end (2026-11-25, Day 2): backend `v2` (8 programmes) + frontend
:3000, all 8 pages 200 (incl. `/programs/imperial-comp-beng-2027` and
`/programs/ntu-msai-2027`), proxy `/api/programs` returns 8 items `v2`,
`/match` Imperial BEng (A*A*A + IELTS 7.0 → academic/language MET,
TMUA UNKNOWN) and NTU MSAI (honours CS + IELTS 7.0 → academic/language MET,
GRE UNKNOWN), `/simulate` delta verified, forged `/explain` → 422.
Live end-to-end (2026-11-25, fix): backend `v2` + frontend :3000
(production build), all 5 pages 200; `/match` Gaokao 680/750 → UCL +
Imperial academic UNKNOWN (`gaokao-no-equivalence`), SG A-level A*A*A →
academic MET both, USA AP 5,5,5,4,4 + SAT 1500 → Imperial UNKNOWN
(`usa-ap-general-only`), UCL UNKNOWN (`usa-no-equivalence`); offline
evaluator + locale renderer checked in zh-CN — chips "学术：符合 /
雅思总分：符合 / 雅思单项：不符合 / TARA：未知 / 学费：不符合",
fee sentence "你的预算 GBP 22/年，低于学费 GBP 46,700/年",
Gaokao observed "高考 680/750", all 42 detail-page minimums and all
16 reason keys render in zh-CN and en.

## Deploy preview

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/Ding-hub6029/PathPilot-AI)

Not live yet: deployment needs the user's Vercel OAuth authorisation and a
backend host (Railway/Render free tier). Full steps in `DEPLOY.md`.

## API (all under `/api/v1`)

| Endpoint | Purpose |
|---|---|
| `GET /health`, `GET /ready` | Liveness / readiness (`ai_status` included) |
| `GET /programs`, `GET /programs/{id}` | The 8 verified real programmes (no fixtures) |
| `POST /assistant/suggest` | 小罗盘 3-question answer: degree + country + budget band -> route suggestion (max 3 lines, one evidence link, `ai_status=unavailable`) |
| `POST /assistant/ask` | 小罗盘 free-text question: fee / IELTS / deadline / rank from verified data only; personal data refused, never echoed |
| `POST /profile/validate` | Cross-track validation (422 `TRACK_MISMATCH` on mismatch) |
| `POST /match` | Rules evaluation for one profile + programme (spec shape) or a flat wizard profile + `program_ids` (frontend shape, multi-program response) |
| `POST /explain` | Citation-checked template explanation; works with no AI key |
| `POST /simulate` | Baseline vs patched profile, same rules/data version (both shapes; frontend shape returns `{baseline, scenario, delta}`) |

The frontend contract is translated by `backend/app/adapter.py` — it changes
no rule logic. Evidence ids in frontend-shaped responses are the frontend's
source ids, so the evidence drawer resolves them.

Errors: `{error:{code,message,field_errors,retryable},request_id}`.

## No AI key needed

With `AI_PROVIDER` / `AI_MODEL` / `AI_API_KEY` all absent, the backend runs
in rules/template mode (`ai_status=unavailable`) and `/explain` still returns
template explanations. See `backend/.env.example` (placeholders only).

## Layout

- `data/schemas/` — JSON Schemas (StudentProfile, Program, Requirement, Source, SourceFact, Evaluation, RuleResult)
- `data/versions/v1/` — `programs.json`, `source-manifest.json`, `QUALITY_REPORT.md`
- `data/fixtures/` — synthetic `fixture-p01.json` (test-only, never in real data)
- `backend/` — FastAPI app, pure rules engine (`backend/domain/eligibility.py`), AI env stub (`backend/ai/`)
- `tests/` — pytest suite
- `docs/` — `SOURCES.md`, `STARTING_POINT.md`
- `TASKS.md`, `DECISIONS.md`, `BLOCKERS.md`, `RELEASE_CHECKLIST.md` — tracking docs
