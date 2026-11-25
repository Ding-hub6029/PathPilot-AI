# Applicant routes — what applicants need beyond their national exam

Research pass 2026-11-25. Data: `data/expansions/applicant_routes.json`
(`data_version: "v1"`). Schema tests: `tests/test_applicant_routes.py`.

## Method

- **Official sources only.** University admissions pages (UCL, Imperial,
  Cambridge, Oxford, MIT, Harvard, NUS), UCAS, UAT-UK, JASSO. No
  aggregator, consultancy or ranking-site content is used as a source. Where
  a search snippet was the only view of an official page, the fact is still
  cited to that official page's URL, and the doc says so below.
- **China is not re-researched.** The `china-gaokao` entry summarises the
  existing Gaokao research (`~/workspace/gaokao_research.md` and
  `backend/ai/gaokao_routes.py`, research pass 2026-11-25). The only new
  China-adjacent check in this pass was confirming the UCL UPC entry
  requirements page exists.
- **Unknown stays unknown.** No equivalence, conversion or threshold is
  invented. If an official page could not be read, the fact is recorded in
  the entry's `unknowns` list with the URL that was tried. Absence from a
  table (e.g. South Korea / Japan not listed in Imperial's accepted
  qualifications) is recorded as "not listed, not an explicit rejection".
- **No U.S. News content anywhere.**
- **Scope.** The question per background is: what does an applicant with
  this qualification need *beyond* their own national exam when applying
  abroad — which admission tests, which language tests, which foundation
  routes, which deadlines. The destination set is the UK (UCL, Imperial,
  Oxford, Cambridge), the US (MIT, Harvard) and Singapore (NUS) where an
  official page covers it. It is not a survey of every university.
- **Cycle.** All thresholds and deadlines are for **2027 entry** unless a
  fact says otherwise. UCAS dates are for the 2027 cycle.

## Key sources (used across backgrounds)

| Source | URL |
|---|---|
| UCL country pages (India, USA, Singapore, Hong Kong, South Korea, Japan, China) | `ucl.ac.uk/study/international/region/...` |
| Imperial accepted qualifications | `https://www.imperial.ac.uk/study/apply/undergraduate/entry-requirements/accepted-qualifications/` |
| Imperial TMUA page | `https://www.imperial.ac.uk/study/apply/undergraduate/process/admissions-tests/tmua/` |
| Imperial English language requirements | `https://www.imperial.ac.uk/study/apply/english-language/` |
| Cambridge international entry requirements (2027 entry, updated March 2026) | `https://www.undergraduate.study.cam.ac.uk/hongkong` (the page that serves the full country list) |
| Cambridge entry requirements / English | `https://www.undergraduate.study.cam.ac.uk/apply/before/entry-requirements` |
| Trinity College Cambridge overseas qualifications | `https://www.trin.cam.ac.uk/undergraduate/applying/overseas-qualifications/` |
| Christ's College Cambridge, applying with AP exams | `https://www.christs.cam.ac.uk/admissions/undergraduate-admissions/international-students-eu-and-non-eu/international-entrance-1/ap` |
| Oxford international qualifications (JS-collapsed, unreadable — see gaps) | `https://www.ox.ac.uk/admissions/undergraduate/courses/admissions-requirements/international-qualifications` |
| UCAS key dates 2027 entry | `https://www.ucas.com/applying/applying-to-university/dates-and-deadlines-for-uni-applications` |
| UAT-UK (TMUA / ESAT / TARA) | `https://esat-tmua.ac.uk/` |
| MIT deadlines & requirements / tests & scores | `https://mitadmissions.org/apply/firstyear/deadlines-requirements/`, `https://mitadmissions.org/apply/firstyear/tests-scores/` |
| Harvard Magazine, testing reinstated | `https://www.harvardmagazine.com/2024/04/standardized-tests-for-admission-reinstated` |
| JASSO EJU 2026 guidelines | `https://www.jasso.go.jp/en/ryugaku/eju/about/eju_guide/2026.html` |
| NUS Singapore-Cambridge GCE A-level requirements | `https://nus.edu.sg/oam/admissions/singapore-cambridge-gce-a-level/admission-requirements` |
| NUS International A-level FAQ | `https://faq.nus.edu.sg/s/article/000004634-What-are-the-admission-requirements-for-applicants-presenting-International-A-Level` |
| UCL UPC entry requirements | `https://www.ucl.ac.uk/study/clie/upc-foundation/entry-requirements` |

## Per-background findings

### China — Gaokao (summary of existing research, not re-done)

- UCL CS BSc: no published Gaokao direct-entry route; the China page lists
  ABB / IB 36 or one year of a Chinese bachelor's at 90%.
- Imperial: Gaokao explicitly not accepted for any degree; remedy is an
  accepted foundation programme or another accepted qualification.
- Direct-entry Gaokao universities that publish a threshold: Birmingham
  (≥80% + school certificate ≥85%), plus LSE via Gaokao+AST (A=210,
  A\*=250). Cambridge: top 0.1% of province (rank, not percentage).
- Extra exams: TMUA compulsory for Imperial Computing (windows 15–16 Oct
  2026 and 8 Jan 2027 in China/HK/Macau); English test still required
  everywhere. No per-band Gaokao→A-level mapping exists.
- Sources: UCL China page, Imperial East Asia page, Birmingham Gaokao
  page, LSE China page, Trinity Cambridge, Imperial TMUA page.

### India — CBSE / ISC (Class XII)

- Direct UK entry at UCL (CISCE/CBSE five subjects at 90, 85, 85, 85, 85
  for the ABB-equivalent; four named state boards on the same marks) and
  Imperial (90% overall across five subjects, 90% in relevant subjects;
  Engineering wants 95% in Maths, Physics and overall, plus a JEE
  common-merit-list rank that "may be waived").
- Cambridge is narrow: CBSE accepted by 21 named colleges for 24 named
  arts/humanities/social-science courses only, at A1×5; anything else needs
  A-levels, IB, 5+ APs at 5 plus A1×5, or a first year of university.
- JEE (Advanced) is supplementary evidence at Cambridge, not a standalone
  route; no official rank threshold was found.
- Language: Imperial IELTS Standard 6.5/6.0, Higher 7.0/6.5 — or Indian
  12th Standard English at 70% (CBSE/CISCE only) in place of a test.
  Cambridge IELTS 7.5/7.0.
- Sources: UCL India page, Imperial accepted-qualifications table and
  Engineering entry page, Cambridge international entry page, Trinity
  Cambridge, Imperial English page, Cambridge entry-requirements page.

### Singapore — Singapore-Cambridge GCE A-level

- H2 grades are direct A-level equivalents: UCL SIPCAL ABB at H2 (NUS High
  GPA 3.9/5.0; polytechnic diploma GPA 3.4/4.0), Imperial minimum three H2
  subjects at grade A, Cambridge typically AAAA at H2 or AAA at H2 plus a
  Merit at H3.
- No foundation needed. Cambridge notes a 2-year deferred place for male
  nationals/PRs doing national service (listed colleges; apply via UCAS for
  a one-year deferral and state the 2-year deferral in My Cambridge
  Application).
- NUS domestic route (2025 sittings onwards): three H2 content subjects +
  General Paper + pass in Project Work + Mother Tongue requirement; UAS on
  a 70-point scale; H2 Knowledge & Inquiry no longer substitutes for GP
  from AY2026.
- Language: Imperial accepts SIPCAL General Paper grade C, Singapore
  A-level English grade C, or O-level English grade B in place of a test.
- Sources: UCL Singapore page, Imperial accepted qualifications and English
  pages, Cambridge international entry page, NUS admissions page.

### USA — SAT / ACT / AP

- The US High School Diploma alone is not enough for UK entry anywhere
  checked. UCL: 3–5 APs, or 2 APs + SAT/ACT with the diploma, or one year
  of US university at CGPA 3.3/4.0 (full AP/SAT/ACT table by A-level band
  is in the JSON). Imperial: five APs at 5,5,5,4,4, or three APs at 5,5,4
  + diploma + SAT 1460 / ACT 31. Cambridge: typically 5 APs at 5 + SAT
  1500 (Maths 750+) for Science/Economics or 1460 (EBRW 730+) otherwise;
  ACT 33 / 32 respectively (+ ACT Science 33 for Science).
- In the US: MIT requires the SAT or ACT (no cutoff); Harvard reinstated
  mandatory SAT/ACT from the Class of 2029, with AP/IB/A-level results
  accepted only where the SAT/ACT is genuinely inaccessible.
- Language: Imperial accepts AP English Language and Composition grade 4,
  or Year 12 English grade B on a US diploma studied in a majority
  English-speaking country, in place of a test.
- Foundation: UCL UPC for applicants without enough APs.
- Sources: UCL USA page, Imperial accepted qualifications and English
  pages, Cambridge international entry page, MIT tests/deadlines pages,
  Harvard Magazine.

### UK — GCE A-level / GCSE

- A-levels are the reference qualification: UCL offers A\*A\*A–ABB on three
  A-levels; Imperial AAA–A\*A\*A. What A-level holders need "beyond" the
  exam depends on destination: UK admissions tests by course (TMUA/ESAT/
  TARA/STEP, plus UCAT/LNAT — dates unverified, see gaps) and SAT/ACT at
  US universities that require them (MIT, Harvard).
- For Singapore: NUS treats International A-levels as a separate route —
  good passes in at least four A2 subjects, from up to two sessions within
  12 months; applicants without final results by the closing date must
  submit SAT/ACT/AP scores and cannot apply for Dentistry, Law or
  Medicine.
- Language: UCL requires GCSE English Language and Mathematics at grade
  4/C or higher for all programmes; Imperial accepts GCSE English Language
  grade 6. UK applicants are normally exempt from English tests at
  Cambridge as majority English speakers.
- Sources: UCL entry-requirements page and Academic Manual 2025-26,
  Imperial accepted qualifications and English pages, NUS International
  A-level FAQ, MIT tests page, Cambridge entry-requirements page.

### IB Diploma (worldwide)

- Accepted for direct entry everywhere checked: UCL 34–40 points by
  A-level band (40 incl. 20 HL for A\*A\*A down to 34 incl. 16 HL for
  ABB), Imperial 38–42 with 6–7 in relevant HL subjects, Cambridge
  (Trinity typical offer) 42 total including bonus points with 7 in
  relevant HL subjects.
- Course-specific admissions tests still apply by course; the IB does not
  exempt an applicant from TMUA/ESAT/TARA/UCAT/LNAT/STEP.
- Language: Imperial accepts IB English A grade 4 (SL or HL) or English B
  grade 6 (SL) / 5 (HL) in place of a test.
- Sources: UCL USA page (IB table), Imperial accepted qualifications and
  English pages, Trinity Cambridge, Cambridge entry-requirements page.

### Hong Kong — HKDSE

- Direct UK entry at UCL (level 5 in English and compulsory Maths + level
  5 in 3 electives; maths-required degrees need 5\* in compulsory Maths
  and ≥5 in the M2 extended module — M1 is not acceptable for these),
  Imperial (5–5\* in relevant subjects; Maths grade needed in both
  compulsory and Extended 1 or 2), Cambridge (core 5s with 5\* in 2+
  relevant core subjects; electives 5\*55 for A\*AA courses, 5\*5\*5 for
  A\*A\*A; M2 required where Maths and Further Maths A-levels are
  required).
- Language: Imperial accepts HKDSE English Level 3 in place of a test;
  Cambridge lists HKDSE as C1-level English evidence.
- Hong Kong candidates sit the TMUA only on 15–16 Oct 2026 or 8 Jan 2027.
- Sources: UCL Hong Kong page, Imperial accepted qualifications, English
  and TMUA pages, Cambridge international entry and entry-requirements
  pages.

### South Korea — CSAT (Suneung)

- No official UK page found accepting the CSAT. UCL publishes no CSAT
  route: ABB-equivalent is a Junior College Diploma or one year of a
  Korean bachelor's at CGPA 4.0/4.5 or 4.0/4.3. Cambridge: the Korean
  diploma alone is not competitive — A-levels, IB, 5 APs at 5 with 수 90%
  in the diploma, or a first year of university. South Korea does not
  appear in Imperial's accepted-qualifications table (absence noted, not
  an explicit rejection).
- Realistic routes: A-levels / IB / APs, first year of university, or a
  foundation year (UCL UPC).
- Sources: UCL South Korea page, Cambridge international entry page,
  Imperial accepted qualifications, UCL UPC page.

### Japan — EJU

- EJU is for international students entering *Japanese* universities
  (JASSO): Japanese as a Foreign Language (reading/listening 0–400,
  writing 0–50), Science (two of physics/chemistry/biology, 0–200),
  Japan and the World (0–200), Mathematics Course 1 or 2 (0–200); in
  Japanese or English except the Japanese test, which is Japanese only.
  2026 sessions: 21 June and 8 November 2026.
- EJU is not a UK admissions test and no official UK page was found
  accepting it. For UK entry, Japanese school leavers need A-levels, IB,
  5 APs at 5 (Cambridge: with GPA 5.0 incl. grade 5 in relevant
  subjects), a first year of university (UCL: one year of a Gakushi at
  UK 2:1 equivalent), or a foundation year (UCL UPC). Japan does not
  appear in Imperial's accepted-qualifications table.
- Sources: JASSO EJU 2026 guidelines and bulletin, UCL Japan page,
  Cambridge international entry page, Imperial accepted qualifications.

### Canada — Provincial High School Diploma (extra, verified)

- Split case: Imperial accepts the provincial diploma directly (85%
  across all Grade 12 subjects, incl. 85% in at least five Grade 12
  subjects with relevant subjects). Cambridge says the diploma alone is
  not competitive — A-levels, IB, 5 APs at 5 with 90% overall, or a first
  year of university.
- Language: Imperial accepts Grade 12 English at 65% in place of a test
  (studied in Canada, excluding Quebec).
- Sources: Imperial accepted qualifications and English pages, Cambridge
  international entry page.

### Australia — ATAR (extra, verified)

- Direct UK entry: Imperial ATAR 97th percentile or better (with the
  school-leaving certificate); Cambridge typically ATAR 98.5–99.5, with
  state subject requirements (e.g. NSW HSC Band 6, Victoria study score
  45+).
- Language: Imperial accepts state/territory HSC English results in place
  of a test (grades vary by territory, e.g. NSW 4, Victoria C in all
  units).
- Sources: Imperial accepted qualifications and English pages, Cambridge
  international entry page.

## Gaps / unknowns (also stored per background in the JSON)

1. **Oxford, almost everywhere.** Oxford's international qualifications
   page (`ox.ac.uk/admissions/undergraduate/courses/admissions-requirements/
   international-qualifications`) is JS-collapsed and its country entries
   could not be read in this pass — same as the Gaokao pass, where Oxford
   Gaokao was left unknown. No Oxford per-country threshold is recorded
   for India, Singapore, USA, UK, IB, Hong Kong, Korea, Japan, Canada or
   Australia. Do not quote Oxford figures from secondary summaries.
2. **Oxford and UCL English levels.** Oxford's own undergraduate English
   page (`ox.ac.uk/englang`) returned 404 in this pass; no Oxford English
   figure is recorded. UCL's five English levels are confirmed to exist
   (UCL UPC page), but the exact IELTS overall/component score per level
   for degree entry was not re-verified on UCL's main English page in
   this pass.
3. **UCAT / LNAT 2027 dates.** Registration dates and deadlines for
   Medicine (UCAT) and Law (LNAT) were not verified from official pages
   in this pass; they are listed as unknown on every background where
   they would matter.
4. **2027 exam dates not yet published or not checked.** 2027 AP and
   SAT/ACT test dates (College Board / ACT), 2027 EJU dates (JASSO 2027
   guidelines), 2027 HKDSE timetable (HKEAA), 2027 CSAT date, 2027 IB
   session dates, and the NUS application window for Singapore-Cambridge
   GCE A-level applicants were not verified in this pass.
5. **JEE (Advanced) rank threshold.** No official rank cut-off was found
   for Cambridge; secondary claims (e.g. top 2,000) are not used. NEET's
   role for Indian applicants to UK medicine was not verified from an
   official source.
6. **Foundation specifics.** Which foundation programmes Imperial accepts
   (for Gaokao, Korean and Japanese applicants) is not published on the
   pages checked. Cambridge Foundation Year eligibility for international
   applicants was not verified.
7. **UCL UPC details.** The UPCSE 70% / 76%-per-core-science-unit mapping
   and the 18 June 2027 UPC deadline come from the Gaokao research pass,
   whose UPC page URLs were not re-captured; re-verify before linking.
8. **Per-course variation.** Course pages set the final offer (e.g. which
   UAT-UK test a course requires, per-course A-level/IB bands). This file
   records university-level rules only; always check the course page.
9. **US test policy is per university.** Only MIT (requires SAT/ACT) and
   Harvard (reinstated from the Class of 2029) were verified. Do not
   generalise to other US universities.
