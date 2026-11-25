# School Reviews — collection notes (2026-11-25)

Source data: `data/expansions/school_reviews.json` (18 reviews).

## What this is

A collection of **verbatim student quotes about the experience of studying at
a university** (网友分享，未经官方核实), for the PathPilot school-detail
"学生评价" section. Each review is a first-person quote copied word-for-word
from a public review page, with a link to that page. These are **not**
officially verified, and they must never be presented as such. They do not
feed the matching engine, and no admission probability is derived from them.

## Labelling rule

- Every review carries `label: "网友分享，未经官方核实"` in the data, and the
  frontend must display that label next to every review.
- Every review carries a `source_url` — no review without one. The source is
  linked so the reader can check the original post.
- Author handles are shown exactly as on the source page (forum handles, or
  匿名 where the source is anonymous). Nothing is de-anonymised.
- No real full name beyond the display name the source itself publishes, no
  phone number, email, WeChat ID or any contact info is recorded. Posts that
  are clearly agency advertisements (contact info, "加微信", consultant cards,
  paid-promotion wording) were skipped.
- **No star rating is recorded.** The source pages show numeric ratings, but
  PathPilot does not collect ratings, so no rating field exists in the schema
  and none may be invented.
- `quote` is the English original, copied verbatim from the source page.
  Quotes are excerpts: a review may be cut at a sentence or clause boundary
  where the source text continues (e.g. sr-001, sr-008); no words were added
  or rephrased inside a quote. `quote_zh` is the collector's own Chinese
  translation of that quote, for reference only.
- `programme` and `level` are recorded only when the source states them
  (review title, course label, or the review text itself, e.g. "MSc in
  Management", "4 years as an undergrad"). Otherwise they are `null` — never
  inferred from the university or guessed from context.
- `posted_date` is the "Reviewed on" date shown on the source page.

## How reviews were found

Searches (browser.search + browser.open, 2026-11-25) across public review
pages; each page was opened and the quote was copied from the fetched page
text:

- **Shiksha** (`shiksha.com/studyabroad/.../reviews`) — verified student
  reviews with full text, course, and review date. 15 reviews: Imperial ×3,
  Oxford ×2, NUS ×2, Melbourne ×2, Toronto ×2, Cambridge ×2, Columbia ×1,
  UCL ×1.
- **StudentCrowd** (`studentcrowd.com/university-of-edinburgh/...`) — course
  review pages with full review text, author handle and date. 3 reviews, all
  University of Edinburgh undergraduate (Product Design, Interior Design,
  Graphic Design).

Search terms used (English): shiksha Imperial / Oxford / Cambridge / UCL /
NUS / Melbourne / Toronto / Columbia reviews students; StudentCrowd
University of Edinburgh student reviews.

## Coverage (18 reviews)

| Source | Reviews |
| --- | --- |
| Shiksha | 15 |
| StudentCrowd | 3 |

| Country | Reviews | Institutions |
| --- | --- | --- |
| United Kingdom | 11 | Imperial, Edinburgh, Oxford, Cambridge, UCL |
| Singapore | 2 | NUS |
| Australia | 2 | University of Melbourne |
| Canada | 2 | University of Toronto |
| United States | 1 | Columbia University |

| Level | Reviews |
| --- | --- |
| Undergraduate | 6 |
| Taught masters | 7 |
| Unknown (not stated on source) | 5 |

9 institutions, 5 countries. Every `institution_id` matches an id in
`data/versions/v2/rankings.json` — no unmatched ids in this pass.
`posted_date` ranges 2022-10-04 to 2026-11-11; most are 2025–2026.

## What was excluded and why

- **Agency-hosted review/case libraries** — consultant names, 扫码 / 预约咨询 /
  phone funnels and paid-promotion wording. Agency content is advertising, not
  first-person student posts.
- **PhD reviews** — out of scope; PathPilot covers undergraduate + taught
  masters only. (One Toronto review by a research/PhD student was seen and
  not collected.)
- **Truncated snippets** — StudentCrowd reviews shown only as a one-line
  teaser with "read more" and no retrievable full text were not collected;
  only reviews whose full text was visible on the fetched page were used.
- **Reddit / The Student Room threads** — searched as candidate sources, but
  no per-university experience quote with a stable, openable thread URL was
  verified in this pass; they remain candidates for the next pass.
- **Xiaohongshu / Tieba / Zhihu** — no per-post public URL with verifiable
  verbatim experience text surfaced; agency pages dominated results.

## Gaps (honest, for the next collection pass)

- **Only 9 of the QS top 100 institutions covered.** No reviews collected
  for continental Europe (ETH Zurich, TU Munich, etc.), Hong Kong, Japan,
  South Korea, or mainland China — Shiksha has few or no review pages for
  those, and StudentCrowd covers UK universities only.
- **US is thin** — only Columbia (1 review). MIT, Stanford, Harvard, UC
  Berkeley, UCLA, CMU, NYU and other US schools have no Shiksha review page
  with retrievable full text in this pass; US coverage needs Reddit / Unigo /
  Niche as sources.
- **NTU: no reviews found** (same gap as SUCCESS_CASES.md).
- **Hong Kong: none** — HKU / HKUST / CUHK / CityU / PolyU have no usable
  public review page found in this pass.
- **All Shiksha reviewers skew Indian international students** — the quotes
  reflect that perspective (visa, cost, Indian food, PR). UK-home-student
  voices are under-represented; StudentCrowd is the counterweight but only
  Edinburgh was mined.
- **5 reviews have unknown level** (sr-001, sr-002, sr-010, sr-012, sr-014):
  the source page does not state the degree level, so it is null rather than
  guessed.
- **No negative-balance guarantee** — only one clearly negative review
  (sr-006, Edinburgh Graphic Design) was collected; the set skews positive,
  which reflects what the source pages surface first, not a selection rule.
- **Shiksha pagination** — review-list pages change as new reviews arrive, so
  a `source_url` points at the listing page, not a per-review anchor; the
  `posted_date` + author handle identify the review on that page.
