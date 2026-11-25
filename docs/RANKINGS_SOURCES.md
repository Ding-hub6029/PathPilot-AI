# RANKINGS_SOURCES.md — Day 3 rankings module research

Research only. No code was changed for this file. All checks were done on
**2026-11-25, approx. 03:00–03:15 UTC (11:00–11:15 SGT)**, by curl from this
machine and by reading the providers' own terms pages. The top-100 expansion
was verified the same day at approx. 03:20 UTC (see §4). Presence below
means the university appears in the provider's latest edition; exact rank
values are deliberately NOT recorded here — the values live in
`data/versions/v2/rankings.json`, re-verified one by one from the official
feeds, and must never be copied from a third-party reproduction.

Related spec: `PathPilot_AI.docx` Ch9 (FR15/FR16, T20–T22), BR15/BR16.
Institutions in scope: top 100 per provider (QS 2027, THE 2027, ARWU 2026)
— 148 institutions, 300 entries. The four institutions whose programmes
PathPilot covers (UCL, Imperial College London, NUS, NTU) are a subset.

---

## 1. QS World University Rankings (QS Quacquarelli Symonds)

- **Entry URL:** https://www.topuniversities.com/world-university-rankings
- **Latest edition:** QS World University Rankings 2027, published 18 June 2026;
  1,504 institutions from 106 higher-education systems.
- **Methodology:** linked from the ranking page ("methodology" — unchanged from
  the previous year per QS's 2027 release notes).

### Access method
- **No free public API and no official downloadable dataset.** QS sells data
  products; third-party paid feeds exist (e.g. api.sh QS API, ScrapeIt from
  €169/month) — none is free.
- The ranking table on topuniversities.com loads from QS's own internal
  Drupal endpoint (`/rankings/endpoint?nid=…`, undocumented). The identical
  data file is served from QS's own China domain without a challenge:
  `https://www.qs-topuniversities.cn/sites/default/files/qs-rankings-data/en/26f968d285c35eba846f63ffc48a96a2.txt`
  — verified 2026-11-25 via curl: HTTP 200, ~1.2 MB JSON, 1,504 rows. The
  top 100 rows were extracted from this file on 2026-11-25 ~03:20 UTC
  (ranks 1–98; ties compress the last rank). (The hash in the filename is
  edition-specific; Day 3 must re-fetch the live page to get the current
  file. Do not hard-code it as a permanent feed.)

### Reuse / redistribution terms
- Source: https://www.topuniversities.com/terms-conditions (read in full,
  2026-11-25). The terms contain two paragraphs that pull in opposite
  directions, quoted/paraphrased here:
  - Restriction: "Content received through topuniversities.com may be
    displayed, reformatted and printed for your personal, non-commercial use
    only… you agree not to reproduce, retransmit, distribute, disseminate,
    display, sell, publish, broadcast or circulate the content … without
    the express prior written consent of QS Quacquarelli Symonds Ltd. You
    may not reconfigure the data or content in any way. If reproducing any
    part of the data, you must maintain the layout and content as displayed
    on topuniversities.com."
  - Carve-out for the rankings data: "You may reproduce, distribute,
    display or transmit the data from the QS World University Rankings as
    displayed on topuniversities.com, provided that original source
    attribution and all copyright and other proprietary rights notices are
    included alongside any such portion of the content in the same form in
    which said notices appear on topuniversities.com and the phrase 'With
    permission from QS Quacquarelli Symonds'. Hyperlinks in all notices
    must be retained." Typical notice: "Source: QS Quacquarelli Symonds
    (www.qs.com). With permission. Copyright © QS Quacquarelli Symonds
    Ltd." Commercial use: contact [email protected].
- **Rights status: CONDITIONAL — in-repo display of the top-100 ranks
  appears permitted under the carve-out**, provided the values are
  reproduced exactly as displayed (no reconfiguration, no merging into a
  combined cross-provider table, no re-computation), with the exact QS
  attribution notice above, on a non-commercial site. This is not a blanket
  licence: whole-table redistribution, reconfigured displays, and any
  commercial use need QS's prior written consent. The "With permission"
  phrase is part of the required notice wording, not evidence that QS
  individually approved this project.

### Reachability (curl, 2026-11-25)
- `topuniversities.com/world-university-rankings`: **HTTP 403** (Cloudflare
  bot wall) with a browser user-agent.
- `qs-topuniversities.cn` data file above: **HTTP 200** via curl.
- Verification path for Day 3: fetch the `.cn` data file (or read the
  table in a real browser); do not rely on curl against `.com`.

### Presence in QS 2027
- Top 100 verified from QS's own data file: 100 rows, ranks 1–98 (ties).
  UCL `=8`, Imperial `=2`, NUS 10, NTU 12 — unchanged from the
  four-institution build.

---

## 2. Times Higher Education (THE) World University Rankings

- **Entry URL:** https://www.timeshighereducation.com/world-university-rankings/latest/world-ranking
- **Latest edition:** World University Rankings 2027, released 30 September
  2026; 2,297 institutions from 118 countries and territories.
- **Methodology:** linked from the ranking page ("Read the full methodology
  here").

### Access method
- **No free public API.** Ranking data is a paid product (THE DataPoints).
- The table itself loads from a public JSON feed that curl can read:
  `https://www.timeshighereducation.com/json/ranking_tables/world_university_rankings/2027`
  — verified 2026-11-25 via curl: HTTP 200, ~4.1 MB JSON, 3,146 rows. The
  top 100 rows were extracted from this feed on 2026-11-25 ~03:20 UTC
  (ranks 1–97; ties compress the last rank). (UCL is listed under the name
  "UCL".) This is the publisher's own table data, not a documented API:
  use it for verification only, not as a licensed feed.

### Reuse / redistribution terms
- Source: https://www.timeshighereducation.com/website-terms-of-use
  (read in full, 2026-11-25), §9–§10:
  - "THE grants you a personal, non-transferable and non-exclusive licence
    to use our Websites and specific Services for their intended purpose."
  - "Requests to alter or adapt any of the rankings data, or to reproduce
    or distribute the data for any purpose should be sent to
    data@timeshighereducation.com."
  - "You should not reproduce, copy, modify, create derivative works from
    or communicate or make any of the content of our Website or Services
    available to third parties without THE's prior written consent."
  - §10 also bans "data mining, robot, spider, scraping or similar
    automated data gathering, extraction or publication tools".
- THE's press releases carry a softer line — "If you reproduce any part of
  these ranking tables or charts, please credit 'Times Higher Education
  World University Rankings 2027', and link to the full list on our
  website" — but that is press guidance, not a licence in the binding
  website terms.
- **Rights status: PERMISSION NOT OBTAINED.** The website terms require
  prior written consent to reproduce ranking content. No consent has been
  obtained; the values are shown only because the user explicitly directed
  inclusion on 2026-11-25, and are labelled in the UI and docs as
  reproduced without THE consent. The route to closing the gap is a
  permission request to data@timeshighereducation.com (not sent).

### Reachability (curl, 2026-11-25)
- Ranking page: **HTTP 200** (~360 KB).
- JSON feed above: **HTTP 200** (~4.1 MB).
- Verification path for Day 3: curl the JSON feed and confirm each
  institution by name.

### Presence in THE 2027
- Top 100 verified from THE's own JSON feed: 100 rows, ranks 1–97 (ties).
  UCL `=17`, Imperial 8, NUS 15, NTU 28 — unchanged from the
  four-institution build.

---

## 3. ShanghaiRanking — Academic Ranking of World Universities (ARWU)

- **Entry URL:** https://www.shanghairanking.com/rankings/arwu/2026
- **Latest edition:** ARWU 2026, released 15 August 2026. "More than 2,500
  universities are actually ranked by ARWU every year and the best 1,000
  are published."
- **Methodology:** "Read full Methodology" link on the ranking page
  (six indicators: Alumni, Award, HiCi, N&S, PUB, PCP).

### Access method
- **No free public API.** The site offers a "Download Ranking Excel"
  button on the ranking page and on each institution page (the button is
  JavaScript-driven; no direct `.xlsx` URL was found in the page HTML).
- The table data ships in a Nuxt static payload that curl can read:
  `https://www.shanghairanking.com/_nuxt/static/1793351018/rankings/arwu/2026/payload.js`
  — verified 2026-11-25 via curl: HTTP 200, ~970 KB, 1,000 rows. The top
  100 rows were extracted from this payload on 2026-11-25 ~03:20 UTC
  (ranks 1–100; ties at 35, 49 and 89 leave gaps at 36, 50 and 90 — see
  §4). (The `1793351018` build hash is edition-specific; Day 3 must
  re-fetch the live page to get the current payload.)

### Reuse / redistribution terms
- **No terms-of-use page was found.** The site footer links only a
  Privacy Statement (last updated 22 September 2011, covers personal data
  only) and Contact Us. No page states whether rank values may be
  reproduced.
- What is stated: "Since 2009 the Academic Ranking of World Universities
  (ARWU) has been published and copyrighted by ShanghaiRanking
  Consultancy." Footer: "Copyright © 2024 ShanghaiRanking Consultancy.
  All Rights Reserved." Contact for enquiries:
  contact@shanghairanking.com.
- **Rights status: UNCLEAR — reuse permission not verified.** "All Rights
  Reserved" plus a copyright notice, with no reuse permission anywhere.
  The values are shown only because the user explicitly directed inclusion
  on 2026-11-25, and are labelled in the UI and docs as reproduced without
  a verified reuse permission. The Excel download is an access point for
  personal viewing, not a licence to republish. A permission enquiry to
  contact@shanghairanking.com is the route to closing the gap (not sent).

### Reachability (curl, 2026-11-25)
- Ranking page: **HTTP 200** (~240 KB).
- Payload file above: **HTTP 200** (~970 KB).
- Verification path for Day 3: curl the payload file (or the Excel
  download in a browser) and confirm each institution by name.

### Presence in ARWU 2026
- Top 100 verified from ShanghaiRanking's own ARWU 2026 payload: 100 rows,
  ranks 1–100. UCL 17, Imperial 29, NUS 53, NTU 84 — unchanged from the
  four-institution build.

---

## 4. Top-100 expansion + image cross-check (2026-11-25 ~03:20 UTC)

Scope: top 100 institutions per provider — QS 2027 (100 rows, ranks 1–98),
THE 2027 (100 rows, ranks 1–97), ARWU 2026 (100 rows, ranks 1–100). That
is 300 entries across 148 institutions: 59 institutions appear in all
three providers, 34 in two, 55 in one. Countries: 26 (US 44 institutions,
CN 16, GB 16, AU 9, DE 8, NL 6, FR/HK/KR/CH 5 each, plus AR, AT, BE, DK,
IE, IL, IT, JP, MY, NO, NZ, SA, SE, TW). No combined or
averaged rank across providers (BR15); rankings never affect eligibility
(BR16).

### Source of truth
Official feeds only (§1–§3). The user supplied 10 ranking-table images
(THE 2027 top 100 in 4 images, ARWU 2026 top 100 in 6 images — agency
compilations with Xiaohongshu watermarks, "学为贵|珠海 赢未来留学").
Every rank was verified against the official feeds; the images were used
only as a cross-check, and the official feed wins wherever they disagree.

### Image-vs-official discrepancies (official feed wins)
- ARWU, UCL: the image shows total 49.6; the official payload says 49.4.
  The module already carried 49.4 — correct, unchanged.
- ARWU, University of Minnesota, Twin Cities (rank 52): the image shows
  total 22.4, which breaks the score sequence (rank 51 is 33.6, rank 53 is
  33.2); the official payload says 33.4. Official wins.
- ARWU "gaps" at ranks 36, 50 and 90 in the images are not missing
  institutions: they are tie gaps (rows 35,35,37 / 49,49,51 / 89,89,91).
- THE rank 75 appears in two images for two different tied institutions
  (Institut Polytechnique de Paris and UNSW Sydney, both `=75`) — not a
  duplicate or an error.
- King's College London: the official feed spells it with a curly
  apostrophe (U+2019), the image with an ASCII apostrophe — cosmetic only.
- Purdue: the image says "Purdue University", the official ARWU payload
  "Purdue University, West Lafayette" — same institution, official form
  kept as the display name.

### Name normalisation (35 merged variant groups)
Providers spell the same institution differently (parentheticals, "The "
prefix, "University, West Lafayette" vs "University West Lafayette",
local-language vs English forms). Names were canonicalised
(case/accent/punctuation-insensitive, stopwords dropped) and 35 groups
merged, e.g. EPFL = École Polytechnique Fédérale de Lausanne = Swiss
Federal Institute of Technology Lausanne; PSL University = Université PSL
= Paris Sciences et Lettres – PSL Research University Paris; KAIST =
Korea Advanced Institute of Science and Technology; LMU Munich =
Ludwig-Maximilians-Universität München; Heidelberg University =
Universität Heidelberg = Ruprecht-Karls-Universität Heidelberg; UNSW
Sydney = University of New South Wales; Purdue / Ohio State / Minnesota /
Wisconsin / Illinois / Michigan (campus-suffix variants); UCL =
University College London; Paris-Saclay University = Université
Paris-Saclay. The two NTUs were NOT merged: National Taiwan University
(QS only, rank 54) and Nanyang Technological University (all three) are
distinct institutions. University of Technology Sydney and University of
Sydney are likewise distinct. Institution ids are slugs of the canonical
display name, except the four covered institutions, which keep their
existing ids (`ucl`, `imperial`, `nus`, `ntu`).

### IELTS reference (from the THE images only)
The THE images carry a 雅思成绩要求 column. Those 100 values were
transcribed as an institution-level reference on the institution page
only, labelled in all 6 locales as a compiled reference ("参考值，来自用户
提供的榜单整理，非该专业的官方要求；具体项目以官网为准") with the images
as the stated source. Four rows carry the literal value "以院校官网为准"
(Princeton =3, Stanford =3, Harvard 6, Northwestern =29). The
eligibility engine never uses these values — programme matching uses only
official programme pages. Institutions outside the THE top 100 carry no
IELTS reference.

### Chinese display names (name_zh, language fix 2026-11-25)
The rankings data stored official names in English only, so after a
locale switch the rankings and institution pages stayed in English. Fix:
a `name_zh` field on each institution in `data/versions/v2/rankings.json`
(schema: `data/schemas/rankings.json`), mirrored into
`frontend/src/lib/rankings.ts`, exposed through the backend institution
endpoints, and rendered by the display rule in `displayInstitutionName` /
`displayCountryName` / `displayCountryCode` /
`displayProgramInstitutionName` (same file): in zh-CN show `name_zh` when
present, else the English official name; every other locale always shows
the English official name; country names always come from the `country.*`
keys in the locale message files (26 codes × 6 locales), falling back to
the English `country_name` from data. The backend `query` filter also
matches `name_zh` (searching 牛津 finds Oxford). No rank value or score
was touched — the 300 entries are unchanged (test-pinned).

Sources, in priority order: (1) the 10 user-supplied table images — THE
2027 top 100 (English-name column, direct match) and ARWU 2026 top 100
(matched by rank, ties disambiguated explicitly); THE wins on the 19
conflicts where the two compilations differ (e.g. PSL: THE 巴黎文理研究大学
vs ARWU 巴黎文理大学； UC Berkeley: THE 加州大学伯克利分校 vs ARWU
加州大学-伯克利； UBC: THE 不列颠哥伦比亚大学 vs ARWU 英属哥伦比亚大学）.
(2) The institutions' own official sites: National Taiwan University —
国立台湾大学 (ntu.edu.tw) and Korea University — 高丽大学
(oia.korea.ac.kr Chinese admissions guide). Coverage: 127 of 148
institutions. The remaining 21 are QS-only institutions with no verified
Chinese name — they carry no `name_zh` and fall back to English (test
pins the exact missing set): Adelaide, Durham, Freie Universität Berlin,
Institute of Science Tokyo, KTH, King Fahd University of Petroleum &
Minerals, Lund, Osaka, Penn State, Politecnico di Milano, Trinity College
Dublin, Universidad de Buenos Aires, Universiti Malaya, Alberta, Auckland,
Leeds, Nottingham, Sheffield, University of Technology Sydney, Warwick,
Western Australia. Nothing was invented.

Scope note: the display rule is implemented on `/institutions/[id]`
(institution name, country, programme list) and `/programs/[id]`
(institution name, country). `frontend/src/app/rankings/page.tsx` was NOT
edited in this pass (the parent fixed its top-to-bottom sort order there
and owns that file) — its cards, country filter and compare table still
render the English names until the same helpers are applied there (4
render sites: card title, card country, country-filter options, compare
table header; the search should also match `name_zh`). See BLOCKERS #15.

### Official websites
Verified official websites are stored only for the four institutions
whose programmes PathPilot covers (UCL https://www.ucl.ac.uk, Imperial
https://www.imperial.ac.uk, NUS https://www.nus.edu.sg, NTU
https://www.ntu.edu.sg; NUS/NTU returned HTTP 200, UCL/Imperial HTTP 403
bot-protection on curl — the domains are the institutions' canonical
official domains). No official site is guessed for any other institution:
their pages link to the provider profile pages taken from the official
feeds instead. Programme admission data is shown only for the 8 verified
programmes; every other institution shows "programme admission data not
yet verified".

## Bottom-line recommendation for Day 3 (FR15/FR16, T20–T22)

1. **Show rank values in-repo for QS only, under the terms' carve-out**
   — the top-100 QS 2027 ranks, reproduced exactly as displayed, with the
   exact QS attribution notice ("Source: QS Quacquarelli Symonds
   (www.qs.com). With permission. Copyright © QS Quacquarelli Symonds
   Ltd."), hyperlinks retained, non-commercial use. Do not reconfigure the
   data and do not build a merged/averaged cross-provider table (the
   spec's BR15 already forbids this; QS's terms forbid reconfiguring its
   data).
2. **THE and ARWU values are shown only because the user explicitly
   directed inclusion** (2026-11-25), labelled honestly as reproduced
   without consent / without a verified reuse permission. The routes to
   closing the gaps are permission requests: THE via
   data@timeshighereducation.com, ARWU via contact@shanghairanking.com
   (neither sent).
3. **Each provider gets its own entry** (provider, edition label, entry
   URL, methodology link, availability/rights status, retrieved_at) and
   its own rank card per institution — never one combined score.
4. **Store at most top 100 × 3 providers = 300 entries**, each with
   `provider`, `edition_label`, `rank_display` exactly as published
   (`=12` ties, `101–150` bands kept verbatim — never converted to a
   single number), `source_url`, `retrieved_at`, `rights_status`. No
   full lists beyond the top 100 in the repo.
5. **Verification method per provider (Day 3):** QS — fetch the
   `.cn` data file from the live page; THE — curl the JSON feed; ARWU —
   curl the Nuxt payload file. Record `retrieved_at` and the exact source
   URL for every value; anything not re-verified on Day 3 is "not
   verified", not a rank. Images supplied by the user are a cross-check
   only — the official feed always wins.
6. **Subject rankings:** QS subject tables (e.g. Computer Science) and
   ARWU GRAS exist, but no subject-table access or rights were checked
   in this pass — treat subject ranks as out of scope for Day 3 unless
   the same per-provider check is repeated for them. THE subject tables
   are likewise unchecked.

## Open items (not resolved by this research)
- THE permission request (data@timeshighereducation.com) — not sent.
- ARWU permission enquiry (contact@shanghairanking.com) — not sent.
- ARWU "Download Ranking Excel" direct URL — not extracted (JS-driven
  button; no `.xlsx` href in page source).
- Exact rank values for all 300 entries — recorded in
  `data/versions/v2/rankings.json`, verified from the official feeds
  2026-11-25 ~03:20 UTC; intentionally not repeated here.

---

## 5. University crests on the rankings page (2026-11-25)

The `/rankings` page (vertical list, Day 3) shows one crest per institution
row. The manifest is `frontend/src/lib/crests.ts` (institution id →
`{src, source_url, licence}` or `{monogram: true}`); local files live in
`frontend/public/crests/`. No rank value, score or sort order was touched
for this change — the list keeps the existing sort (selected provider's
rank, else best rank) and the same provider-rank values.

### Method
First choice was a freely-usable file on Wikimedia Commons, checked via
the Commons API (`extmetadata LicenseShortName`) on 2026-11-25: only
files whose licence allows redistribution (Public domain, CC BY, CC BY-SA)
were downloaded as small local copies (original SVG where small, else a
256 px raster thumbnail of the SVG via Commons `Special:FilePath`). The
`source_url` in the manifest is the stable Commons file page
(`commons.wikimedia.org/wiki/File:…`) — never a tokenised or expiring
URL. Second choice (official media/brand page) was not needed: every
real crest below came from Commons. Where no freely-usable Commons file
exists — the logo is absent from Commons or is held on Wikipedia under a
non-free (fair-use) rationale, which does not allow redistribution — the
row renders a styled monogram badge (first letters of the official name,
navy #0B1F3A background), never a fake crest or invented logo.

### Real crests (19)
| Institution | Commons file (source_url) | Licence | Local file |
|---|---|---|---|
| Harvard University | https://commons.wikimedia.org/wiki/File:Harvard_University_shield.svg | Public domain | crests/harvard-university.svg |
| Massachusetts Institute of Technology | https://commons.wikimedia.org/wiki/File:Massachusetts_Institute_of_Technology_logo.svg | Public domain | crests/massachusetts-institute-of-technology.svg |
| University of Oxford | https://commons.wikimedia.org/wiki/File:Coat_of_arms_of_the_University_of_Oxford.svg | Public domain | crests/university-of-oxford.png |
| Imperial College London | https://commons.wikimedia.org/wiki/File:Arms_of_Imperial_College_London.svg | CC BY 3.0 | crests/imperial.png |
| Stanford University | https://commons.wikimedia.org/wiki/File:Seal_of_Leland_Stanford_Junior_University.svg | Public domain | crests/stanford-university.png |
| Princeton University | https://commons.wikimedia.org/wiki/File:Princeton_University_Shield.svg | Public domain | crests/princeton-university.svg |
| University of Cambridge | https://commons.wikimedia.org/wiki/File:Coat_of_Arms_of_the_University_of_Cambridge.svg | CC BY-SA 3.0 | crests/university-of-cambridge.png |
| University of California, Berkeley | https://commons.wikimedia.org/wiki/File:Seal_of_University_of_California,_Berkeley.svg | Public domain | crests/university-of-california-berkeley.png |
| Columbia University | https://commons.wikimedia.org/wiki/File:Columbia_University_Shield.svg | Public domain | crests/columbia-university.svg |
| ETH Zurich | https://commons.wikimedia.org/wiki/File:ETH_Zürich_Logo.svg | Public domain | crests/eth-zurich.svg |
| Yale University | https://commons.wikimedia.org/wiki/File:Yale_University_logo.svg | Public domain | crests/yale-university.svg |
| Tsinghua University | https://commons.wikimedia.org/wiki/File:Tsinghua_University_Logo.svg | Public domain | crests/tsinghua-university.png |
| Cornell University | https://commons.wikimedia.org/wiki/File:Cornell_University_seal.svg | Public domain | crests/cornell-university.svg |
| Peking University | https://commons.wikimedia.org/wiki/File:Peking_University_seal.svg | Public domain | crests/peking-university.svg |
| Chinese University of Hong Kong | https://commons.wikimedia.org/wiki/File:Emblem_of_CU.png | Public domain | crests/chinese-university-of-hong-kong.png |
| Université Paris-Saclay | https://commons.wikimedia.org/wiki/File:Logo_Université_Paris-Saclay_2019-12.svg | Public domain | crests/universite-paris-saclay.svg |
| University of California, Los Angeles | https://commons.wikimedia.org/wiki/File:The_University_of_California_UCLA.svg | Public domain | crests/university-of-california-los-angeles.svg |
| University of Pennsylvania | https://commons.wikimedia.org/wiki/File:Shield_of_the_University_of_Pennsylvania.svg | Public domain | crests/university-of-pennsylvania.svg |
| University of California, San Diego | https://commons.wikimedia.org/wiki/File:Seal_of_the_University_of_California,_San_Diego.svg | Public domain | crests/university-of-california-san-diego.png |

Attribution for the two CC-licensed crests: Imperial College London arms
(Arms of Imperial College London.svg) — CC BY 3.0; University of
Cambridge coat of arms (Coat of Arms of the University of Cambridge.svg)
— CC BY-SA 3.0. Both are credited here and in the manifest with their
Commons file page; the files themselves are unchanged. All other crests
above are public domain (no attribution required; source still recorded).
University logos are also trademarks — the files are used only to
identify the institution on this non-commercial student project page.

### Monogram fallback (129 institutions)
Every other institution in the 148-institution set has an explicit
`{ monogram: true }` entry in the manifest — no institution is left
without a crest decision. This includes the top-20 institutions for
which no freely-usable Commons crest was found on 2026-11-25:
California Institute of Technology, University College London (UCL),
University of Chicago, National University of Singapore (NUS), University
of Hong Kong, and Nanyang Technological University (NTU). Their logos
are trademarked and either absent from Commons or held on Wikipedia
under a non-free rationale, so a monogram badge is used instead of
reproducing a non-free logo. The same applies to the remaining 123
institutions (e.g. Johns Hopkins, University of Washington, UNSW Sydney,
all institutions outside the top ~25 by best rank). If a freely-licensed
crest for one of these appears on Commons later, add it to the manifest
with its source URL and licence and add the local file — do not hotlink
an unlicensed logo.
