# PathPilot AI

Evidence-based university selection (UK & Singapore), computer-related
undergraduate + taught masters, two independent tracks.
Built for the **Global AI Builder's Challenge 2026** (event Nov 21–28 2026;
submissions due **Nov 28 15:00 PST = Nov 29 07:00 Beijing**).

Day 1 scope (complete, integrated 2026-11-24): backend + verified data +
schemas + tests + tracking docs + frontend (Next.js, 6 languages, wizard,
results, simulation, evidence drawer) + live end-to-end verification.
Pushed to the public GitHub repo on Day 1.

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

Next.js 14 + TypeScript + Tailwind. Pages: `/` (home), `/wizard`
(track first, then target / academic / language / budget), `/results`,
`/programs/[id]` (evidence drawer), `/report` (print + JSON export).
Six locales (en, zh-CN, es, fr, pt-BR, ar; 98 keys each, checked by
`npm run build`), RTL for Arabic, compass-theme motion (navy/teal/amber),
`prefers-reduced-motion` respected. The frontend proxies `/api/*` to the
backend; if the backend is down it falls back to a clearly-labelled
offline evaluator — start the backend first for live results.

### Tests

```bash
.venv/bin/python -m pytest tests/ -v
# real run 2026-11-24: 19 passed, 0 failed (13 engine/API + 6 frontend-contract)
cd frontend && npm run build   # real run 2026-11-24: pass (locale check + all routes)
```

Live end-to-end (2026-11-24): backend :8000 + frontend :3000, all 6 pages
HTTP 200, proxy `/api/match` + `/api/simulate` verified — IELTS writing 5.5
→ component NOT_MET; patch to 6.5 → MET with delta recorded.

## API (all under `/api/v1`)

| Endpoint | Purpose |
|---|---|
| `GET /health`, `GET /ready` | Liveness / readiness (`ai_status` included) |
| `GET /programs`, `GET /programs/{id}` | The 2 verified real programmes (no fixtures) |
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
