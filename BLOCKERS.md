# BLOCKERS.md — PathPilot AI Day 1

| # | Blocker | Impact | Status |
|---|---|---|---|
| 1 | Direct curl of the UCL BSc page failed (exit 18) | No SHA-256 hash for that page; facts rest on the browser crawl only. Recorded honestly in `data/versions/v1/QUALITY_REPORT.md` and in the source manifest. Does not block Day 1. | pass (documented) |
| 2 | UCL TARA score threshold unknown | TARA rule always returns UNKNOWN. Cannot be resolved from the verified page. | pass (documented) |
| 3 | NUS application deadline unknown | Recorded as null/UNKNOWN. Do not copy General Track dates. | pass (documented) |
| 4 | No cloud AI key | Explain endpoint runs in rules/template mode (`ai_status=unavailable`). By design for Day 1; not a blocker. | pass (documented) |
| 5 | Frontend/backend contract mismatch found at integration (single vs multi-program; nested vs flat profile; `programs` vs `items`; fact ids vs source ids) | Frontend would have silently fallen back to its offline evaluator. Fixed with `backend/app/adapter.py` + 6 contract tests; live-verified through the frontend proxy 2026-11-24. | pass (fixed) |
| 6 | GitHub push on Day 1 | Repo https://github.com/Ding-hub6029/PathPilot-AI created public and empty via browser on 2026-11-24; Day 1 code is local only — push returns 403 because the Muse GitHub App installation does not yet include PathPilot-AI. | blocked (needs user to select PathPilot-AI in the App installation, then re-push) |
| 7 | Not verified on Day 1 (no live-browser access in this environment) | Full browser click-through, RTL visual rendering, scroll retention on language switch, keyboard walkthrough, print/PDF output. These are user manual-testing items for the next stage. | todo (manual testing) |

No open blockers prevent the Day-1 product from running locally, passing tests, or serving the verified endpoints. The two servers are running now (backend :8000, frontend :3000) for manual testing.
