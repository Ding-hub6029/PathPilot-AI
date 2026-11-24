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
- [x] Pytest: 13 passed, 0 failed (real run, command in TASKS.md).
- [x] No secrets in code; `.env.example` placeholders only.
- [x] No fabricated data; unknowns listed, not guessed.
- [ ] Frontend built (other agent's scope — not a Day-1 backend release item).
- [ ] GitHub repository created + pushed (Day 2–3).
- [ ] Submission to Devpost before Nov 28 15:00 PST / Nov 29 07:00 Beijing (competition deadline).
