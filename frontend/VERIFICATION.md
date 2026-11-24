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
  the Day 1 audit re-opened the official `-2026` page the same day and
  confirmed the recorded facts (A*A*A with A* in Maths/Further Maths,
  contextual A*AB, IB 40 / contextual 38, TARA required, £46,700 overseas,
  14 Jan 2026 deadline).
- NUS MComp admissions URL was corrected after a 404:
  `https://www.comp.nus.edu.sg/programmes/pg/misc/admissions/` — live search
  confirms the thresholds on it (GRE 320 + 3.5, GMAT 650+, TOEFL iBT 90,
  IELTS 6.0) and the fees page
  `https://www.comp.nus.edu.sg/programmes/pg/mcs/scholarships/` confirms
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
  actually opened and hashed during research). The `/mis/` URL that used to
  appear above was corrected in place by the Day 1 audit (2026-11-24). UCL source URLs were also
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

## Day 2 frontend (2026-11-25, this agent)

Date: 2026-11-25 00:25–01:00 CST (Nov 24 16:25–17:00 UTC). Node v24.22.1, npm 10.9.4, Next.js 14.2.35.

### What changed

- Wizard: IB total / HL Maths / HL total, GCSE English + Maths (UCL C/4
  hint), residency select (uk/overseas) with the overseas-fee note
  (UCL £46,700/yr overseas vs £9,790/yr UK), intake year, language test
  date, graduation status, IT experience years. TOEFL iBT stays a
  separate field from IELTS — both are sent, neither is discarded.
  New flat field names sent to the backend: `ibTotal`, `ibHlMaths`,
  `ibHlTotal`, `gcseEnglish`, `gcseMaths`, `residency`, `intakeYear`,
  `testDate`, `graduationStatus`, `itExperienceYears` (+ existing `toefl`).
- Programme list is data-driven: `fetchPrograms({limit, cursor})` calls
  GET /api/v1/programs through the /api rewrite, normalises the backend
  snake_case shape to the frontend `Program` shape (fees incl. the UK
  £9,790 item, intake labels, durations), merges local sources (which
  carry the verified excerpts) with API-only sources, and falls back to
  the local `PROGRAMS` list when the backend is unreachable. Used by
  home, wizard, results, report and programme detail via `usePrograms`.
- Evidence drawer (`src/components/EvidenceDrawer.tsx`, shared by the
  programme detail page and the results page): every rule result links
  to its source — label, clickable official URL, excerpt, verified
  date, intake applicability. Excerpts are labelled
  "Excerpt in English (original)" in all 6 locales, never presented as
  translated. Unmatched evidence ids are shown as unavailable rather
  than silently dropped.
- i18n: 28 new keys in all 6 locales — 98 → **126 keys per locale**,
  `npm run check-locales` passes (6 files × 126 keys). Default language
  stays `en` (DECISIONS #43); no browser-language detection was added.
- `~/workspace/day2_courses.json` did NOT exist at the time of this
  work, so the 6 new Day-2 courses were NOT wired into `programs.ts`.
  The loader + fallback are built; a TODO comment in
  `frontend/src/lib/programs.ts` marks where the v2 entries go.

### Build

- `npm run build` — **PASS** (locale check 6×126 keys, types, all
  routes: `/`, `/wizard`, `/results`, `/programs/[id]`, `/report`).
  New labels confirmed present in the built wizard chunk
  (`.next/static/chunks/467-*.js`): "IB total points (out of 45)",
  "GCSE English Language grade", "Residency for fees",
  "Language test date", "Graduation status",
  "IT industry experience (years)", "Intended intake year",
  "Excerpt in English (original)", "Applies to intake".
  (The wizard SSR HTML only contains step 0 — the new fields live on
  steps 1–4, which render client-side — so the chunk check is the right
  evidence, not a curl grep of the HTML.)

### Live verification (backend :8000 + `next start` :3000)

- All 6 pages HTTP 200: `/`, `/wizard`, `/results`,
  `/programs/ucl-cs-bsc-2026`, `/programs/nus-mcomp-cs`, `/report`.
- `GET /api/programs` through the frontend proxy: 2 items
  (`ucl-cs-bsc-2026`, `nus-mcomp-cs`), `data_version: v1`.
  `?limit=1` returns 1 item + `next_cursor: MQ==`; following the
  cursor returns the second programme (`next_cursor: null`).
- `POST /api/match` (new-fields UG profile: IB 40 / HL Maths 7 /
  HL total 20, GCSE A/A*, residency overseas, intake 2026,
  test date 2026-01-15, IELTS 7.0 + TOEFL 100): live, 7 rules —
  `ucl-ielts-overall MET`, `ucl-ielts-components MET`,
  `ucl-toefl MET` (TOEFL kept alongside IELTS, not discarded),
  `ucl-gcse MET`, `ucl-academic MET` (via IB), `ucl-tara UNKNOWN`,
  `ucl-fee MET`. Masters new-fields profile: `nus-toefl MET` alongside
  IELTS, `nus-language-components NOT_APPLICABLE`, all others MET.
- `POST /api/simulate` (IELTS writing 5.5 → 6.5): delta
  `ucl-ielts-components NOT_MET → MET` — verified live.
- Normaliser smoke test (`node --experimental-strip-types`,
  `/tmp/day2smoke/smoke.mts`): backend snake_case → frontend shape
  correct (UCL fees overseas £46,700 + UK £9,790; NUS SGD 69,215
  total; intakes "September 2026" / "August 2027, AY2027/2028
  Semester 1"); local sources keep excerpts, API-only sources are
  appended without an excerpt. Offline evaluator runs with the new
  fields (UG: academic UNKNOWN offline — see gap below).

### Incident during verification (backend, not frontend)

- The first backend start (00:35 CST) served a **stale** `/match`:
  HTTP 500 `INTERNAL_ERROR: 'UndergradProfile' object has no attribute
  'tara_taken'` for both the Day-1 and the new-fields profiles. The
  backend agent had edited `backend/app/{main,schemas}.py` and
  `backend/domain/eligibility.py` at 16:32–16:33 UTC (minutes before
  this session) while the server was starting — the running process
  loaded a half-updated module set. Restarting uvicorn after the
  backend files settled fixed it: in-process `TestClient` and the
  restarted server both return 200 with the Day-2 rules (`ucl-gcse`,
  `ucl-toefl`, `nus-toefl`). No frontend change was needed; the
  frontend's offline fallback would have shown the offline banner in
  the meantime. Lesson: when the backend agent is editing live, restart
  the backend before trusting a 500.

### Known gaps (Day 2 frontend)

- The 6 new Day-2 courses are not wired in (no `day2_courses.json`
  yet; backend catalogue is still v1 / 2 programmes).
- The offline evaluator (`evaluateLocal` in `src/lib/api.ts`) does not
  yet model the new Day-2 rules (IB, GCSE, TOEFL-date): an IB
  applicant sees `ucl-academic UNKNOWN` offline where live returns
  MET, and the offline rule set is 5 rules vs 7 live. Live is the
  primary path and is correct; offline is a degraded fallback with an
  explicit banner. Aligning it is a frontend follow-up, not done here
  to avoid inventing rule logic in the fallback.
- Still not verified (unchanged): browser click-through (wizard steps
  1–4 in a real browser, drawer open/close), RTL visual rendering,
  scroll retention on language switch, keyboard walkthrough, print/PDF.

## Day 2 integration verification (2026-11-25, coordinator)

- `frontend/src/lib/programs.ts`: all 8 v2 programmes present as offline fallback (2 Day 1 + 6 new), each with official sources + excerpts, verifiedDate 2026-11-25. The stale TODO is gone.
- `frontend/src/lib/types.ts`: `residency` accepts `uk | overseas | sg_citizen | sg_pr | sg_intl_asean | sg_intl_other | sg_intl_nogrant`; `degreeClass` + `mastersMathsGrade` added to `Profile` and `emptyProfile`.
- Wizard: masters step has degree-class select + A-level Maths grade; residency select has the 5 Singapore options.
- `frontend/messages/*.json`: 138 keys × 6 locales (126 + 12: degree class + 5 options, masters maths grade, 5 SG residency options); `npm run build` locale check passes.
- Offline evaluator (`frontend/src/lib/api.ts` `evaluateLocal`): models all 6 new programmes + IB/HL total, GCSE, TOEFL date split, residency fees; IGP-only academic rules stay UNKNOWN, matching live. Verified by build + live proxy checks (below).
- Live (backend :8000 v2 + `next start` :3000): all 8 pages 200, incl. `/programs/imperial-comp-beng-2027` and `/programs/ntu-msai-2027`; proxy `/api/programs?limit=20` returns 8 items, `data_version: v2`; `/api/match` Imperial BEng and NTU MSAI verified end-to-end.
- Not visually verified (no live browser in this session): wizard click-through with the new fields, evidence drawer open/close, Arabic RTL rendering. Same open items as Day 1 (user's manual testing).
