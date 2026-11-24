# QUALITY_REPORT.md — PathPilot AI Day 1 data quality

Generated: 2026-11-24 (data retrieved 2026-11-23 18:39–18:40 UTC / 2026-11-24 02:39 CST).

## Retrieval method and honesty note

- Facts were retrieved via browser crawl on 2026-11-23 18:39–18:40 UTC.
- **Direct curl of the UCL BSc page failed (exit 18).** No SHA-256 hash is claimed for
  `https://www.ucl.ac.uk/prospective-students/undergraduate/degrees/computer-science-bsc-2026`.
  Its facts are recorded from the browser crawl only, and this is stated in
  `programs.json` and `source-manifest.json` (`fetch_status: "failed"` for source `ucl-bsc`).
- The UCL English-language page was fetched via curl: 5,725 bytes,
  SHA-256 `eb7a740ae5b0e6c89f6ff8ada343c723daa9fcdebee626873fc7c7af531ce524`.
- NUS admissions page SHA-256: `e3d6eb80713349628e21931b071546b4b6c8c096d827ca2f5bec543b697c3b22`.
- NUS scholarships page SHA-256: `38b9787584b90b81faefa3b6fc3c05e9a74ce0b579f4d1e438b2aac2cb052253`.

## Course 1 — ucl-cs-bsc-2026 (University College London, Computer Science BSc)

| Field | Value | Source |
|---|---|---|
| Institution / country / city | University College London / GB / London Bloomsbury | ucl-bsc |
| Degree level | undergraduate | ucl-bsc |
| Intake year / start | 2026 / September 2026 | ucl-bsc |
| Duration / mode | 3 academic years / full-time | ucl-bsc |
| UCAS code | G400 | ucl-bsc |
| Application deadline | 14 Jan 2026 | ucl-bsc |
| Fees 2026/27 overseas | GBP 46,700 per year | ucl-bsc |
| Fees 2026/27 UK | GBP 9,790 per year | ucl-bsc |
| A-level | A\*A\*A, A\* in Mathematics or Further Mathematics; contextual offer A\*AB | ucl-bsc |
| IB | 40 points total, 20 points in three HL subjects including grade 7 in Mathematics; contextual offer IB 38 | ucl-bsc |
| Language | English Level 1: IELTS Academic overall 6.5, minimum 6.0 in each component | ucl-english |
| Additional test | TARA required for 2026 cycle; no score threshold stated | ucl-bsc |

## Course 2 — nus-mcomp-cs (National University of Singapore, School of Computing)

| Field | Value | Source |
|---|---|---|
| Institution / school / country | National University of Singapore / School of Computing / SG | nus-admissions |
| Degree level | taught_masters | nus-admissions |
| Official name | Master of Computing (Computer Science specialisation) | nus-admissions |
| Intake | August 2027, AY2027/2028 Semester 1 | nus-admissions |
| Fees | SGD 69,215 total tuition incl. 9% GST, up to 40 units | nus-admissions |
| Application fee | SGD 109 | nus-admissions |
| Academic | Good honours in computing; OR good honours in a related discipline + 2 years IT industry experience; OR good bachelor's in computing + 2 years IT experience; OR good bachelor's/honours in a business-related discipline + 2 years IT experience; admission competitive | nus-admissions |
| Language | IELTS minimum 6.0 overall (no component minimum stated); TOEFL iBT minimum 90 | nus-admissions |
| GRE/GMAT | GRE minimum 320 (verbal & quantitative) and 3.5 analytical, OR GMAT 650+; valid 5 years; TOEFL/IELTS valid 2 years. The admissions page lists GRE/GMAT as evidence to submit but states no rejection rule for a missing or low score, so missing/low GRE/GMAT is UNKNOWN, never NOT_MET | nus-admissions |

## Explicit unknowns (never guessed)

1. UCL TARA score threshold — required, no threshold stated.
2. NUS application deadline — not stated on the admissions page. General Track dates were deliberately NOT copied.
3. NUS IELTS component minimums — only overall 6.0 stated.
4. Living costs for both courses — not in the verified sources; excluded from all fee rules.
5. UCL non-A-level/IB equivalence — no equivalence evidence; other qualifications evaluate to UNKNOWN.
6. UCL TOEFL mapping — a TOEFL Level 1 mapping exists on the UCL Study Abroad English page (92 old iBT scale; 4.5 new scale for tests from 21 Jan 2026), but the degree page points to the Undergraduate English requirements page and the scale change makes it date-dependent; not yet modelled, so TOEFL for UCL evaluates to UNKNOWN, never converted. (Corrected 2026-11-24 audit: the earlier claim that no TOEFL threshold exists in the verified sources was wrong — the cited page does list one.)

## What is NOT in the data

- No fabricated data. Only the two courses above, each fact traced to a source id + excerpt in `source-manifest.json`.
- No fixture data in `programs.json`: `data/fixtures/fixture-p01.json` is synthetic, labelled as such, and the backend refuses fixtures in real data at startup.
- No living-cost, ranking, or employment-outcome claims — none were verified.
