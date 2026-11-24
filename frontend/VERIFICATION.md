# Verification — PathPilot AI frontend (Day 1)

Date: 2026-11-24. Environment: Node v24.22.1, npm 10.9.4, Next.js 14.2.35.

## Build

- `npm install` — added 107 packages, OK.
- `npm run build` — **PASS**. Locale check passed (6 files × 98 keys), Next.js
  compiled, types checked. Routes: `/`, `/wizard`, `/results`,
  `/programs/[id]`, `/report`.
- One build failure was found and fixed during development: `StatusChip` was
  exported from a page file (invalid page export). Moved to
  `src/components/StatusChip.tsx`; rebuild passed.

## Dev server

- `npm run dev` serves on http://localhost:3000. Verified with curl:
  `/` 200, `/wizard` 200, `/results` 200, `/programs/ucl-cs-bsc-2026` 200,
  `/report` 200; home page HTML contains "PathPilot AI".

## Backend — BLOCKER (not available)

- `curl http://localhost:8000/api/v1/health` failed at start, mid-build and end
  of the session: **backend was not up at any point during this build**.
- The frontend therefore **has NOT been verified against the live backend**.
  It was built against the API contract in the task and falls back to a local
  evaluator (`src/lib/api.ts` → `evaluateLocal`) when `/api/*` (Next.js
  rewrite → `http://localhost:8000/api/v1/*`) is unreachable. The UI shows an
  explicit offline banner ("Backend unavailable — showing offline data") in
  that case. Nothing in this report claims live-backend verification.
- Still to verify once the backend is up: `GET /programs` shape vs the local
  dataset, `POST /match` statuses, `POST /simulate` delta, 422
  TRACK_MISMATCH handling end-to-end, and `POST /explain`.

## Match-engine smoke tests (local evaluator, Node type-stripping)

Command: `node --experimental-strip-types /tmp/smoketest/smoke.mts`
(imports copied to /tmp with `.ts` extensions; logic identical to shipped code)

| Case | Result |
|---|---|
| UG sample (A*A*A, IELTS 7.0/6.5/6.5/6.0/6.5, £50,000) | All 4 UCL rules MET |
| Same, IELTS Writing 5.5 (simulation delta) | Component rule flips MET → NOT_MET; others unchanged |
| PG sample (Computing honours, IELTS 6.5, GRE 325/4.0, S$70,000) | All 4 NUS rules MET |
| PG sample with no GRE/GMAT | GRE/GMAT rule UNKNOWN (not MET) |
| UG profile checked against NUS programme | TRACK_MISMATCH flagged |
| Empty UG profile | All 4 rules UNKNOWN |

Two real bugs were found and fixed by these tests:
1. A-level parser treated "A*A*A" as one token → UNKNOWN. Fixed with
   token regex `/A\*|[A-E]/gi`.
2. Checker demanded three A*s; "A*A*A" means grades A*, A*, A (two starred).
   Fixed to compare sorted grades against required [A*, A*, A] + A* in Maths.

## Source URLs

- UCL CS BSc URL (`ucl.ac.uk/.../computer-science-bsc`) — fetched 2026-11-24;
  URL resolves on ucl.ac.uk (fetched page returned the degree index, not the
  full CS page body, so UCL excerpts are the brief's wording, not re-typed
  from a live page read).
- NUS MComp admissions URL was corrected after a 404:
  `https://www.comp.nus.edu.sg/programmes/pg/misc/admissions/` — live search
  confirms the thresholds on it (GRE 320 + 3.5, GMAT 650+, TOEFL iBT 90,
  IELTS 6.0) and the fees page
  `https://www.comp.nus.edu.sg/programmes/pg/mis/scholarships/` confirms
  S$69,215 incl. 9% GST, up to 40 units, AY2027/2028 Aug 2027 intake.
  Excerpts in `src/lib/programs.ts` now quote that verified text.

## Not verified (needs a live browser — unavailable to this agent)

- Full wizard click-through in a browser (sample → match → results →
  simulate → language switch to ar/zh-CN, layout + no mixed-language flash).
- RTL visual rendering, scroll retention on language switch, keyboard/focus
  walkthrough, `prefers-reduced-motion` behaviour.
- Print/PDF output of the report page.

## Integration verification (coordinator, 2026-11-24, after this file was written)

- **Correction:** the NUS fees URL in `src/lib/programs.ts` was
  `.../pg/mis/scholarships/` — a typo, not the verified page. Fixed to
  `https://www.comp.nus.edu.sg/programmes/pg/mcs/scholarships/` (the page
  actually opened and hashed during research). The line 65 reference to the
  `/mis/` URL above is superseded by this note. UCL source URLs were also
  fixed to the verified `-2026` page and the UCL English Level 1 page, and
  the A-level excerpt corrected (the draft's "A*AA" alternative is not on
  the official page).
- **Backend is now up and verified live through the frontend proxy:**
  backend :8000 + `next start` :3000. All 6 pages HTTP 200
  (`/`, `/wizard`, `/results`, `/programs/ucl-cs-bsc-2026`,
  `/programs/nus-mcomp-cs`, `/report`). `POST /api/match` (flat wizard
  profile, writing 5.5) returns live `NOT_MET` on the component rule with
  frontend source ids; `POST /api/simulate` (writing 5.5 → 6.5) returns
  delta `NOT_MET → MET`, scenario summary `PARTIAL_UNKNOWN` (TARA still
  UNKNOWN). `npm run build` re-run after the URL fixes: pass.
- **Contract mismatch found and fixed at integration:** the backend
  originally accepted only single-`program_id` + nested profiles while the
  frontend sends flat profiles + `program_ids`. Fixed by
  `backend/app/adapter.py` (no rule logic changed) + 6 new contract tests
  (`tests/test_api_contract.py`). Without this fix the frontend would have
  silently used its offline evaluator.
- Still not verified (unchanged): browser click-through, RTL visual
  rendering, scroll retention, keyboard walkthrough, print/PDF.
