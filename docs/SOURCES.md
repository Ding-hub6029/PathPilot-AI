# SOURCES.md — PathPilot AI

## Competition (Devpost) — verified reachable 2026-11-23 18:39 UTC

| ID | URL |
|---|---|
| S1 | https://global-ai-builders-challenge.devpost.com/rules |
| S2 | https://global-ai-builders-challenge.devpost.com/ |
| S3 | https://global-ai-builders-challenge.devpost.com/details/dates |
| S4 | https://global-ai-builders-challenge.devpost.com/resources |

Notes on the live rubric (from the Devpost rules page):

- The live rubric is **25 checkboxes with per-checkbox points**; sections are averaged, then added to a total of 100.
- Product AI max **24**, development AI max **6** (human check required for A4).
- Public deployment and an outside tester are **optional, not required**.

## Programme data — retrieved 2026-11-23 18:39–18:40 UTC

| ID | URL | SHA-256 / status |
|---|---|---|
| ucl-bsc | https://www.ucl.ac.uk/prospective-students/undergraduate/degrees/computer-science-bsc-2026 | Direct curl failed (exit 18); no hash claimed. Facts from browser crawl. |
| ucl-english | https://www.ucl.ac.uk/prospective-students/study-abroad-at-ucl/how-apply/english-language-requirements/ | `eb7a740ae5b0e6c89f6ff8ada343c723daa9fcdebee626873fc7c7af531ce524` (5,725 bytes) |
| nus-admissions | https://www.comp.nus.edu.sg/programmes/pg/misc/admissions/ | `e3d6eb80713349628e21931b071546b4b6c8c096d827ca2f5bec543b697c3b22` |
| nus-scholarships | https://www.comp.nus.edu.sg/programmes/pg/mcs/scholarships/ | `38b9787584b90b81faefa3b6fc3c05e9a74ce0b579f4d1e438b2aac2cb052253` |

Full per-fact traceability (source id, excerpt, retrieved_at) is in
`data/versions/v1/source-manifest.json`; see also
`data/versions/v1/QUALITY_REPORT.md`.

## Rankings — top 100 per provider, verified one by one from each provider's official source, 2026-11-25 ~03:20 UTC

Top 100 institutions per provider (QS 2027, THE 2027, ARWU 2026) = 300 entries across 148 institutions, world ranks only. Full method, access and rights analysis in `docs/RANKINGS_SOURCES.md`; values in `data/versions/v2/rankings.json` (12 original entries `retrieved_at` 2026-11-25T03:12:00Z, 288 new entries `retrieved_at` 2026-11-25T03:20:00Z). The user-supplied ranking-table images were a cross-check only; the official feed wins wherever they disagree (two discrepancies recorded in `docs/RANKINGS_SOURCES.md` §4: ARWU UCL score 49.6 image vs 49.4 official; ARWU Minnesota Twin Cities rank 52 total 22.4 image vs 33.4 official).

| Provider | Edition | Entry URL | Methodology URL | Access used to verify |
|---|---|---|---|---|
| QS | 2027 (pub. 2026-06-18) | https://www.topuniversities.com/world-university-rankings | https://www.topuniversities.com/qs-world-university-rankings/methodology (verified live via browser reader 2026-11-25 03:12 UTC) | QS's own `.cn` data file (curl 200, ~1.2 MB JSON); `.com` page is Cloudflare-blocked for curl (403) |
| THE | 2027 (rel. 2026-09-30) | https://www.timeshighereducation.com/world-university-rankings/latest/world-ranking | https://www.timeshighereducation.com/world-university-rankings/methodology (curl 200) | Provider's own JSON feed (curl 200, ~4.1 MB) |
| ARWU | 2026 (rel. 2026-08-15) | https://www.shanghairanking.com/rankings/arwu/2026 | https://www.shanghairanking.com/methodology/arwu/2026 (curl 200) | Nuxt payload file (curl 200, ~970 KB) |

Verified values for the four institutions whose programmes PathPilot covers (rank_display verbatim, `=` = tie; score = provider-published overall score). The full top-100 set (300 entries, 148 institutions) is in `data/versions/v2/rankings.json`, not repeated here.

| Institution | QS 2027 | THE 2027 | ARWU 2026 |
|---|---|---|---|
| UCL | =8 (96.3) | =17 (90.3) | 17 (49.4) |
| Imperial College London | =2 (99.2) | 8 (95.2) | 29 (41.2) |
| NUS | 10 (96.2) | 15 (91.1) | 53 (33.3) |
| NTU | 12 (93.6) | 28 (84.0) | 84 (28.7) |

Rights: QS values shown under the terms' carve-out with the exact attribution notice; THE values labelled "reproduction consent not obtained" (consent route: data@timeshighereducation.com); ARWU values labelled "reuse permission not verified" (enquiry route: contact@shanghairanking.com). No combined/average rank across providers (BR15); rankings never affect eligibility (BR16). No full lists beyond the top 100 are stored in the repo.
