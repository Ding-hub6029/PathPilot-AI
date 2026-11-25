# Success Cases — collection notes (2026-11-25)

Source data: `data/expansions/success_cases.json` (55 cases).

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

## How cases were found

Searches (browser.search + social.search, 2026-11-25) across:

- **一亩三分地 (1Point3Acres)** — first-person 25Fall offer summaries with
  full backgrounds (GPA, TOEFL/GRE, research, internships). Two posters,
  9 offer records (one record per offer).
- **The GradCafe survey results** — anonymous first-person result entries
  (GPA, GRE where given, decision date, intake). 41 offer records. Sources are
  the filtered survey-listing URLs; note that GradCafe pagination shifts over
  time, so a listed URL may show a different page slice later — the programme /
  institution filter in the URL is the stable part.
- **去留学 liuxue.online** — the site founder's own DIY story (小红书
  @有正事没正经， 大连民族大学（双非）, 均分 70.5, 0 中介费）, 3 Australian
  offers. Note the discrepancy: the site's UCL school page teases the same
  author as "均分 82 拿下英国 G5 梦校 offer (UCL)", but the story page itself
  says 70.5 and three Australian offers with no UCL — only the story-page
  facts were recorded.
- **The Student Room** — one thread, an Imperial Joint Maths & CS student who
  got offers from Imperial JMC and UCL without CS A-level; grades not stated,
  so most fields are null. Included because it is the only undergraduate case
  found; kept thin rather than padded.

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

## Coverage (55 cases)

| Platform | Cases |
| --- | --- |
| The GradCafe | 41 |
| 一亩三分地 | 9 |
| 去留学 liuxue.online | 3 |
| The Student Room | 2 |

| Offer country | Cases |
| --- | --- |
| US | 25 |
| UK | 13 |
| Canada | 7 |
| Australia | 5 |
| Hong Kong | 3 |
| Singapore | 2 |

| Level | Cases |
| --- | --- |
| Taught masters | 53 |
| Undergraduate | 2 |

Intakes: mostly Fall 2024 / Fall 2025 / Fall 2026, plus Spring 2026 and Spring
2027. Posted dates: GradCafe "Added On" date; 1Point3Acres post / last-edit
date (yushijinhun's post is dated by its last edit, 2025-03-20); liuxue.online
and The Student Room posts carry no visible date, so `posted_date` is null.

## What was excluded and why

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
- **Undergraduate: only 2 records** (the thin Imperial / UCL thread). UG offer
  stories are mostly posted without grades, or behind agency pages.
- **No native Xiaohongshu / Tieba / X per-post URLs** in this pass — searches
  returned agency pages instead of retrievable first-person posts. The one
  Xiaohongshu author captured came via their own site (liuxue.online).
- **Douban** — searched; results were agency ranking articles and an XDF blog.
  No usable per-post case.
- **GradCafe cases are anonymous** — undergrad institution / major are null for
  most of them; the value is the offer + GPA + scores, not the background.
- **"London School"** (sc-045) is recorded exactly as GradCafe lists it; no
  expansion to LSE was assumed.
