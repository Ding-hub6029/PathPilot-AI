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
| D1-07 | Pytest suite (13 tests) + real run recorded | D1-05, D1-04 | `tests/test_eligibility.py` | pass |
| D1-08 | Live verification: uvicorn start + curl /health, /programs, /match, /simulate | D1-04, D1-07 | `docs/STARTING_POINT.md` (verification note) | pass |
| D1-09 | Tracking docs + README | D1-08 | `TASKS.md`, `DECISIONS.md`, `BLOCKERS.md`, `RELEASE_CHECKLIST.md`, `docs/SOURCES.md`, `docs/STARTING_POINT.md`, `README.md` | pass |

## Day 1 — integration (coordinator, after both agents)

| ID | Task | Depends on | Artefacts | Status |
|---|---|---|---|---|
| D1-10 | Frontend/backend contract adapter (flat wizard profile + program_ids) | D1-04, D2-01 | `backend/app/adapter.py`, `tests/test_api_contract.py` | pass |
| D1-11 | Fix frontend source URLs (NUS fees `/pg/mis/` → `/pg/mcs/`; UCL pages → verified `-2026` URL; English → UCL Level 1 page; fix A-level excerpt) | D1-02 | `frontend/src/lib/programs.ts` | pass |
| D1-12 | Live end-to-end verification: backend + frontend production build, all pages 200, proxy /api/match + /api/simulate | D1-10, D1-11 | this file + `frontend/VERIFICATION.md` (integration note) | pass |

## Day 2–3 (not this agent's scope)

| ID | Task | Depends on | Status |
|---|---|---|---|
| D2-01 | Frontend (another agent owns `frontend/`) — 6-language framework, UI copy | D1-04 | pass |
| D2-02 | GitHub repository creation + push (user's GitHub access, public repo) | D1-09 | blocked (repo created public 2026-11-24 but still empty; push returns 403 — Muse GitHub App installation does not yet include PathPilot-AI; needs user to select the repo in the App installation) |
| D2-03 | Local demo recording / deployment only if needed | D1-09 | todo |

## Test result (real run, 2026-11-24)

Command: `.venv/bin/python -m pytest tests/ -v`
Result: **19 passed, 0 failed** (13 original + 6 frontend-contract tests; pytest 8.3.4, Python 3.12.3).
Frontend: `npm run build` **pass** (locale check 6×98 keys, all 5 routes).
Live: backend :8000 + frontend :3000, all 6 pages 200, proxy `/api/match` and `/api/simulate` verified (writing 5.5 → NOT_MET; patch to 6.5 → MET, delta recorded).
