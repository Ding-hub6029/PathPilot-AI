# DECISIONS.md — PathPilot AI Day 1

| # | Decision | Rationale |
|---|---|---|
| 1 | Day 1 backend only; no frontend, no GitHub push | Task scope: another agent owns `frontend/`; no push requested for Day 1. |
| 2 | Two independent tracks (undergraduate / taught_masters), cross-track profiles rejected with 422 `TRACK_MISMATCH` | Competition product design; prevents meaningless cross-track matches. |
| 3 | Only 2 real programmes in v1, each fact traced to a source id + excerpt | No fabricated data; Day-1 scope is a working rules engine, not coverage. |
| 4 | Rules/template explain mode with no AI key; `ai_status=unavailable` | No cloud AI key available and none required by the competition; the explain endpoint must work without one. |
| 5 | ProviderAdapter reads only env vars (`AI_PROVIDER`, `AI_MODEL`, `AI_API_KEY`); no key in code | Secrets rule; `.env.example` holds placeholders only. |
| 6 | UNKNOWN, never NOT_MET, for: UCL TOEFL, UCL TARA, UCL non-A-level/IB qualifications, NUS missing GRE/GMAT, NUS IELTS components, mismatched/missing budget | The verified sources state no threshold or no rejection rule; converting or rejecting would invent evidence. |
| 7 | NUS application deadline recorded as UNKNOWN (null) | Not stated on the admissions page; General Track dates deliberately not copied. |
| 8 | UCL BSc page recorded as `fetch_status: failed` (direct curl exit 18), facts from browser crawl | Honest provenance; no hash claimed for that page. |
| 9 | Fixture `fixture-p01` is synthetic, lives only in `data/fixtures/`, and the backend refuses fixtures in real data at startup | Test isolation without contaminating real data. |
| 10 | Overall status: any NOT_MET → NOT_MET; else any UNKNOWN → UNKNOWN; else KNOWN_MINIMUMS_MET | Deterministic summary rule shared by engine and tests. |
| 11 | CORS limited to `http://localhost:3000` | Frontend dev origin only. |
| 12 | Backend runs on port 8000, frontend on port 3000 | Convention agreed for the two-agent split. |
| 13 | Python 3.12 venv in the project (`.venv/`), pinned requirements in `backend/requirements.txt` | Reproducible local run; no paid resources. |
| 14 | Backend accepts BOTH API shapes: spec/test contract (single `program_id`, nested StudentProfile) and frontend contract (flat wizard profile + `program_ids`, multi-program response) | The two Day-1 agents built against different shapes; the adapter translates without touching rule logic. Both shapes are pinned by tests. |
| 15 | Adapter maps engine evidence ids (manifest fact ids) to frontend source ids | The frontend evidence drawer looks sources up by its own ids; unmapped ids would show an empty drawer. |
| 16 | Wizard budget assumed per-year for undergraduate, total for taught masters | Matches the wizard (currency defaults GBP for UG, SGD for masters); recorded as an assumption, not a verified fact. |
| 17 | Frontend source URLs fixed to the verified pages (NUS fees `/pg/mcs/scholarships/`, UCL `-2026` page, UCL English Level 1 page) and the A-level excerpt corrected to the page wording | The frontend draft used `/pg/mis/scholarships/` (typo, not the verified page) and a no-year UCL URL (403 via curl); the A-level excerpt invented an "A*AA" alternative the page does not state. |
