# RELEASE_CHECKLIST.md — PathPilot AI Day 1

- [x] `data/schemas/*.json` — 7 JSON Schemas present and valid JSON.
- [x] `data/versions/v1/programs.json` — exactly 2 real programmes, 0 fixtures, 0 synthetic flags.
- [x] `data/versions/v1/source-manifest.json` — every fact has source id + excerpt + `retrieved_at` 2026-11-23T18:39:00Z; unknowns listed explicitly.
- [x] `data/versions/v1/QUALITY_REPORT.md` — records the failed UCL BSc curl (exit 18) honestly.
- [x] `data/fixtures/fixture-p01.json` — synthetic, labelled, not in `programs.json`.
- [x] Backend starts with uvicorn (verified live, port 8000).
- [x] `GET /health` returns `{"status":"ok","data_version":"v1","programs":2}`.
- [x] `GET /programs` returns the 2 real programmes, no fixtures.
- [x] `POST /match` returns a real evaluation (sample profile verified live).
- [x] `POST /simulate` baseline vs patched verified live.
- [x] Track mismatch returns 422 `TRACK_MISMATCH` (verified live).
- [x] `POST /explain` works with no AI key (`ai_status=unavailable`, template explanation).
- [x] Pytest: 25 passed, 0 failed (real run 2026-11-24, after the Day 1 audit fixes; command in TASKS.md).
- [x] No secrets in code; `.env.example` placeholders only.
- [x] No fabricated data; unknowns listed, not guessed.
- [x] Frontend built (`npm run build` pass 2026-11-24, locale check 6×98 keys, all routes; all 6 pages HTTP 200 live).
- [x] GitHub repository created + pushed (public repo, HEAD ccf8aba, 14 commits, 2026-11-24; the audit fixes of 2026-11-24 still need a push).
- [ ] Submission to Devpost before Nov 28 15:00 PST / Nov 29 07:00 Beijing (competition deadline).

## Day 2 (2026-11-25)

- [x] `data/versions/v2/programs.json` — 8 real programmes (2 per UK/SG × UG/taught-masters cell), 0 fixtures.
- [x] `data/versions/v2/source-manifest.json` — 72 facts, 29 sources, 25 unknowns; 0 bad cross-references.
- [x] `data/versions/v2/QUALITY_REPORT.md` — coverage table + honest limitations (IGP-only academic, UCL MSc English UNKNOWN, AY2026/27 SG fees, NTU MSAI deadline UNKNOWN, Imperial MSc fee/Round 1 UNKNOWN, TMUA/STEP UNKNOWN).
- [x] `data/versions/v2/traceability.csv` — 24 rows, generated from the manifest.
- [x] Backend serves data version `v2` (`GET /api/v1/health` → `{"status":"ok","data_version":"v2","programs":8}`).
- [x] `GET /programs` filtering + cursor pagination over 8 programmes.
- [x] `POST /explain` recomputes server-side; forged shape → 422 `EXPLAIN_REQUIRES_PROFILE`.
- [x] Wizard fields: IB total/HL Maths/HL total, GCSE English/Maths, test date, graduation status, IT experience years, intake year, residency incl. SG bands, degree class + masters maths grade.
- [x] Rate limiting (60/min, 10/min explain) + security headers on every response; `GET /api/v1/openapi.json` + `/docs` 200.
- [x] Money with Decimal (`Budget.amount`); language scores still float (deferred, DECISIONS #49).
- [x] Frontend built (`npm run build` pass 2026-11-25, locale check 6×138 keys, all routes; all 8 pages HTTP 200 live).
- [x] Pytest: 79 passed, 0 failed (real run 2026-11-25; command in TASKS.md).
- [x] Evidence excerpts labelled English-only where not translated (DECISIONS #35); no invented translations.
- [x] Deploy-ready: `DEPLOY.md`, `backend/Dockerfile`, env-driven `API_BASE_URL`, Vercel deploy button in README.
- [ ] Preview deployment live (blocked — needs the user's Vercel OAuth + backend host; BLOCKERS #10).
- [ ] Day 2 code pushed to GitHub (parent's step — NOT done by this agent).
- [ ] Submission to Devpost before Nov 28 15:00 PST / Nov 29 07:00 Beijing (competition deadline).
