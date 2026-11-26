# Success Cases — collection notes (2026-11-25; regrouped 2026-11-26, Round 8)

Source data: `data/expansions/success_cases.json` (41 applicant cards, 53 offers).

## What this is

A collection of **netizen-shared offer stories** (网友分享，未经官方核实) for the
PathPilot homepage / school-detail "成功案例" section. These are first-person
posts found on public social sources. They are **not** officially verified
admission outcomes, and they must never be presented as such. They do not feed
the matching engine, and no admission probability is derived from them.

## Labelling rule

- Every case carries `label: "网友分享，未经官方核实"` in the data, and the
  frontend must display that label next to every case.
- Every case carries a `source_url` — no case without one. The source is linked
  so the reader can check the original post.
- Author handles are shown exactly as in the source (forum handles, or 匿名
  where the source is anonymous). A poster's own anonymisation (e.g. "S同学",
  "双非", unnamed school) is kept; nothing is de-anonymised.
- No real full name, phone number, email, WeChat ID or any contact info is
  recorded. Posts that are clearly agency advertisements (contact info,
  "加微信", consultant cards, paid-promotion wording) were skipped.
- Facts are summarised in the collector's own words (undergrad, major, GPA,
  language scores, offer, intake, key experience). Long passages were not
  copied verbatim.
- Missing details are recorded as `null` — never invented or filled in.
- **One applicant = one card.** A card is an applicant, not an offer: every
  offer that applicant shared is listed in the card's `offers` array (see
  "One applicant, one card (Round 8)" below). Counts shown in the UI come
  from the data length, never a hardcoded number.

## One applicant, one card (Round 8, 2026-11-26)

The original 55 records counted offers, not applicants: four applicants had
been split across several cards each. They are now merged — the total fell
from 55 records to **41 cards covering 53 offers**:

- **sc-001 — yushijinhun** (一亩三分地， 2025-03-20): one post, 4 offers
  (CMU MS Robotics, UPenn MSE Robotics, UCSD MS ECE, BU MS Robotics and
  Autonomous Systems). The shared background/experience stays at applicant
  level; the three "同上" filler notes on the split cards are gone — each
  offer now carries its own content (here: none beyond the shared
  experience, so the per-offer notes are null).
- **sc-005 — Chasm** (一亩三分地， 2025-04-15): one post, 5 offers
  (Northeastern MS CS, Northeastern MS ECE, Rice MCS, Utah MS CS,
  Vanderbilt MS CS). Each offer keeps its own note (e.g. "25% 奖学金" on
  the NEU ECE offer, "出结果早；不卡双非" on Utah).
- **sc-039 — GradCafe IR applicant** (posted 2024-02-05, GPA 3.73,
  政治学本科）: 4 offers (Edinburgh IR, UCL International Public Policy,
  LSE IR, King's IR). Same person, confirmed by the shared GPA/date and
  by the Edinburgh row itself ("offers from UCL and Edinburgh within one
  day", "Grand Slam" UK application season) plus matching timelines
  across the four rows. The IELTS 7.5 (7.0) stated on the UCL row now
  applies to the whole card. The King's row had been left without a note;
  its note ("10 月 24 日递交，12 月 1 日获 offer") was added from the
  GradCafe row itself (Accepted on 1 Dec; TL: 10.24 submission, 12.1 offer).
- **sc-051 — liuxue.online founder** (小红书 @有正事没正经）: one story,
  3 offers (UWA, Adelaide, UTS — all IT / 数据方向）. The shared
  experience ("0 中介费 DIY;仅花 ¥85 成绩单翻译…") stays at applicant
  level; the two "同上" filler notes are gone. Re-checked against the live
  story page on 2026-11-26: 大连民族大学（双非）, 均分 70.5, 0 中介费，
  three QS100 Australian offers (UWA QS#77, Adelaide QS#82, UTS QS#96).
  The page shows no date, so `posted_date` stays null.

No other same-applicant groups exist: grouping the remaining records by
(platform, posted date, GPA) finds no further duplicates — the other
same-URL groups (e.g. five CMU CS rows sharing one GradCafe listing URL)
are different people with different GPAs/dates.

Two corrections found while regrouping:

- **"London School" (sc-045) → London School of Economics and Political
  Science.** GradCafe lists the school under truncated variants
  ("London School", "London School of Economics", "London School of
  Economics and Political Science (LSE)"); no other institution called
  "London School" offers an International Relations Masters, and the row
  (GPA 3.80, Added On 2024-02-06, 1 年相关工作经验） is a different
  applicant from the 3.73 IR group, so the card stays separate. The source
  URL is unchanged — GradCafe itself lists it as "London School".
- **Meta country counts were wrong** (US 25 / Canada 7). Recounted by
  offer from the institution: US 24, Canada 8 (Toronto Metropolitan and
  Saskatchewan plus six Toronto rows). UK 11, Australia 5, Hong Kong 3,
  Singapore 2 are unchanged apart from the two removed TSR cards.

## How cases were found

Searches (browser.search + social.search, 2026-11-25) across:

- **一亩三分地 (1Point3Acres)** — first-person 25Fall offer summaries with
  full backgrounds (GPA, TOEFL/GRE, research, internships). Two posters,
  2 cards / 9 offers.
- **The GradCafe survey results** — anonymous first-person result entries
  (GPA, GRE where given, decision date, intake). 38 cards / 41 offers.
  Sources are the filtered survey-listing URLs. **GradCafe has no
  per-record pages**: a result is a row in a paginated filtered list, so
  there is no per-record deep link to use. Each card therefore carries a
  `source_ref` listing locator next to the date — "survey p. 490" where
  the URL has a page number, "survey (cursor-pinned listing)" where the
  URL uses a cursor (the cursor URL itself pins the listing window). The
  row is findable by programme + institution + "Added On" date + GPA.
  Note that GradCafe pagination shifts over time, so a listed URL / page
  number may show a different page slice later — the programme /
  institution filter in the URL is the stable part, and the page
  reference is as collected on 2026-11-25.
- **去留学 liuxue.online** — the site founder's own DIY story (小红书
  @有正事没正经， 大连民族大学（双非）, 均分 70.5, 0 中介费）, 1 card /
  3 Australian offers. Note the discrepancy: the site's UCL school page
  teases the same author as "均分 82 拿下英国 G5 梦校 offer (UCL)", but
  the story page itself says 70.5 and three Australian offers with no
  UCL — only the story-page facts were recorded.

Search terms used (Chinese + English): 小红书 拿到 offer GPA 雅思 录取汇报；
留学 offer 汇报 GPA 语言成绩；知乎 拿到 offer 录取 GPA 雅思 美国研究生；
reddit accepted offer GPA admitted grad school; 一亩三分地 录取 汇报 GPA TOEFL
GRE offer 计算机；小红书 帝国理工 / 新国立 / UCL / 墨尔本大学 offer 均分 雅思；
一亩三分地 25fall MSCS 录取总结；reddit gradadmissions accepted MS CS Fall 2025;
thestudentroom offer Imperial UCL computer science; 澳洲八大 offer 均分 雅思 墨尔本大学；
知乎 帝国理工 MSc offer / 墨尔本大学 offer; 一亩三分地 港新 NUS NTU 录取汇报；
reddit ApplyingToCollege international Imperial UCL; thegradcafe NUS / Toronto /
Oxford Cambridge / UCL LSE Edinburgh / Hong Kong / Melbourne Sydney UNSW / Sydney /
NTU masters accepted GPA; 贴吧 留学吧 拿到 offer 汇报；reddit australianuniversities
accepted offer masters; 豆瓣 留学小组 拿到 offer 均分 雅思 录取汇报；
social.search (Instagram / Threads / Facebook): 拿到 offer 留学申请 GPA 雅思 /
got accepted grad school offer GPA / UCL offer 均分 雅思.

## Coverage (41 cards, 53 offers)

| Platform | Cards | Offers |
| --- | --- | --- |
| The GradCafe | 38 | 41 |
| 一亩三分地 | 2 | 9 |
| 去留学 liuxue.online | 1 | 3 |
| The Student Room | 0 | 0 (removed Round 8 — see below) |

| Offer country | Offers |
| --- | --- |
| US | 24 |
| UK | 11 |
| Canada | 8 |
| Australia | 5 |
| Hong Kong | 3 |
| Singapore | 2 |

| Level | Cards |
| --- | --- |
| Taught masters | 41 |
| Undergraduate | 0 (removed Round 8 — see below) |

Intakes: mostly Fall 2024 / Fall 2025 / Fall 2026, plus Spring 2026 and Spring
2027. Posted dates: GradCafe "Added On" date; 1Point3Acres post / last-edit
date (yushijinhun's post is dated by its last edit, 2025-03-20); the
liuxue.online story page shows no date, so `posted_date` is null there
(checked again 2026-11-26).

## What was excluded and why

- **The Student Room thread t=7231328 (sc-054 Imperial JMC, sc-055 UCL) —
  removed Round 8 (2026-11-26).** Re-reading the thread: it is a Year-12
  student (2022) asking whether it is worth applying to Imperial / UCL /
  KCL without CS A-level — not a success story. The "Imperial JMC offer"
  is a claim by a *commenter* (M_m_m03) about themselves ("I didn't do
  Computer Science at A-level but now do Joint Maths and Computer Science
  at Imperial… I also got an offer for UCL"), and the UCL offer has no
  evidence in the thread at all. Both cards were removed; undergraduate
  coverage is now zero (see Gaps).
- **Agency-hosted case libraries** — CompassEdu / 指南者， 启德， XDF 新东方，
  新航道， 51liuxue (无忧留学）, jingsailian and similar: consultant names,
  扫码 / 预约咨询 / phone funnels and paid-promotion wording. Agency content
  is advertising, not first-person student posts.
- **The reference video's success cases** — the Chinese study-abroad app in the
  user's screen recording shows agency-collected offer dossiers plus consultant
  WeChat cards. Those were never copied (DECISIONS.md #103/#104).
- **One 1Point3Acres CMU MSCS 2024 post** (普通 985, GPA 3.6, TOEFL 103,
  GRE 325) — forum moderators flagged it "真实性存疑，请谨慎看待", so it was
  excluded even though it had concrete details.
- **PhD result entries on The GradCafe** — out of scope; PathPilot covers
  undergraduate + taught masters only.
- **Instagram / Threads / Facebook results** (social.search) — mostly
  agency / creator content; no per-case post with verifiable programme, GPA
  and a stable URL surfaced (one Oxford 3.3 GPA creator video had no
  verifiable programme or URL).

## Gaps (honest, for the next collection pass)

- **Australia is thin** — only 2 Sydney GradCafe cases + 3 from the liuxue.online
  founder. No Melbourne first-person case found; searches returned agency guides.
- **NTU: no cases found.**
- **Undergraduate: no cases.** The only two UG records (the thin Imperial /
  UCL thread) were removed in Round 8 — they were not success stories.
  UG offer stories are mostly posted without grades, or behind agency pages.
- **No native Xiaohongshu / Tieba / X per-post URLs** in this pass — searches
  returned agency pages instead of retrievable first-person posts. The one
  Xiaohongshu author captured came via their own site (liuxue.online).
- **Douban** — searched; results were agency ranking articles and an XDF blog.
  No usable per-post case.
- **GradCafe cases are anonymous** — undergrad institution / major are null for
  most of them; the value is the offer + GPA + scores, not the background.
  GradCafe also has no per-record URLs (see above); the `source_ref`
  page/cursor locator is the best available pointer, and pagination shifts
  over time.
