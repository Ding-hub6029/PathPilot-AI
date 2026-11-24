# STARTING_POINT.md — PathPilot AI Day 1

## What Day 1 is

Day 1 of 3 for the Global AI Builder's Challenge 2026 (event Nov 21–28 2026;
submissions due **Nov 28 15:00 PST = Nov 29 07:00 Beijing**).
Product: evidence-based university selection, UK & Singapore, computer-related
undergraduate + taught masters, two independent tracks.
Day 1 scope: **backend + data + schemas + tests + tracking docs + frontend (integrated 2026-11-24) + GitHub push (completed 2026-11-24, HEAD ccf8aba)**. (Original scope was backend-only with no frontend and no push; the frontend was integrated and the code pushed the same day after the user selected PathPilot-AI in the GitHub App installation.)

## Eligibility checklist (NOT verified — user to confirm)

- [ ] Student is 13+ (competition minimum age).
- [ ] Team size up to 6.
- [ ] AI disclosure required for the submission (product AI max 24 + dev AI 6).
- [ ] User to confirm own student status and consent for the entry.

## Run it

Backend (port 8000):

```bash
cd ~/workspace/pathpilot-ai
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Frontend (port 3000):

```bash
cd frontend && npm install && npm run dev   # http://localhost:3000
```

Tests:

```bash
.venv/bin/python -m pytest tests/ -v
```

## Live verification (actually run 2026-11-24, not claimed)

Server started with uvicorn on 127.0.0.1:8000; then curl:

- `GET /api/v1/health` →
  `{"status":"ok","data_version":"v1","programs":2}`
- `GET /api/v1/ready` →
  `{"status":"ready","data_version":"v1","programs":["nus-mcomp-cs","ucl-cs-bsc-2026"],"ai_status":"unavailable"}`
- `GET /api/v1/programs` → 2 real programmes (`ucl-cs-bsc-2026`, `nus-mcomp-cs`), 0 fixtures.
- `POST /api/v1/match` (UCL sample: A\*A\*A with A\* maths, IELTS overall 7.0, all
  components 6.5, budget GBP 50,000/year) → `overall_status: "UNKNOWN"`
  (all scored rules MET; TARA is UNKNOWN because no threshold is stated).
  `ai_status: "unavailable"`, template explanation returned.
- `POST /api/v1/simulate` (baseline writing 5.5 → patch writing 6.5) →
  baseline `overall_status: "NOT_MET"` (component rule NOT_MET),
  patched `overall_status: "UNKNOWN"` (components MET).
- `POST /api/v1/match` with a taught-masters profile against UCL →
  HTTP 422 `{"error":{"code":"TRACK_MISMATCH", ...}}`.

Pytest (real run): `.venv/bin/python -m pytest tests/ -v` →
**13 passed, 0 failed** (Python 3.12.3, pytest 8.3.4).

## Data in v1

- `ucl-cs-bsc-2026` — UCL Computer Science BSc (fees GBP 46,700/yr overseas).
- `nus-mcomp-cs` — NUS Master of Computing, Computer Science specialisation
  (SGD 69,215 total incl. 9% GST).
- Unknowns recorded, not guessed: UCL TARA threshold, NUS deadline, NUS IELTS
  components, living costs, UCL non-A-level/IB equivalence.
- Direct curl of the UCL BSc page failed (exit 18); see `data/versions/v1/QUALITY_REPORT.md`.
