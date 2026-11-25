# Programme expansion — QS top 100, every programme

User direction (2026-11-25, after a 76-second screen recording of a Chinese
study-abroad app): QS top 100 institutions must ALL be fully covered, and
EVERY programme of every school must be included. This document describes
the data + backend foundation for that. The frontend (rankings vertical
list with crests, institution detail pages, programme names, pet) is a
separate agent's work.

## What the reference app shows (verified from video frames)

- **Ranking list**: vertical, one row per school — rank (with movement
  arrows), crest, Chinese + English names, country flag, QS trend tags
  （连续2年世界前三）, 历年排名 link. (The app's list is the **QS 2026**
  edition — Stanford 3, ↑3. PathPilot uses QS 2027 official data,
  Stanford =2. Never "correct" our ranks to the video.)
- **School detail tabs**: 学校简介 / 费用概览 / 专业列表 / 留学资讯 /
  成功案例.
- **Programme rows**: Chinese name, English name, duration （时长 12或18个
  月 / 90学分）, tuition （学费 80,718美元/年）, field tags （金融 / 金工金数）,
  application-status badge （已截止 / 申请中）.
- **Success-case tab**: agency offer dossiers (student background:
  毕业院校 / 本科专业 / 均分 / 雅思 / 实习） plus consultant cards
  （约专家 / 加微信）. **NOT copied** — agency-collected; cases on this
  site must be official student stories only (see
  `~/workspace/homepage_content_sources.md`).
- **School header** (per the user's description): campus photo, rank
  chips, stats row (total students, student-faculty ratio, international
  %, graduate %, male:female), intro, official website + address,
  membership tags.

## Schema

`data/expansions/schema/`:

| File | Contents |
|---|---|
| `institution-profile.json` | One institution's stats profile. Every stat is a sourced number (`value` + `source_url` + `retrieved_at`) or null (unknown). Membership tags carry one official source each. Campus photo only when freely licensed (Wikimedia Commons CC / CC0 / public domain) with licence + attribution. Intro quoted/paraphrased from the official About page with source. |
| `expanded-program.json` | One programme. Extends the v2 program shape with `institution_id` (rankings id), `field` (controlled slug list), `field_zh`, `application_status` (open/closed only from an official page stating it for the current cycle, else unknown, with source + as-of date), `name_localized.zh-CN` (required, standard degree-name convention), `matchable: false` (always), `catalogue: "expansion"`. Fees: currency + period (`per_year` / `total` / `per_credit`) + amount (null = unknown, explained in notes). Requirements use the v2 requirement shape (academic / language / test, threshold null when not stated). |
| `expansion-file.json` | The merged file: `data_version: "v3"`, `institutions`, `programs`, `sources`, `traceability` (one row per sourced fact). |

`data/versions/v2/` is NEVER modified by expansion work.

Collection rules (full list in `data/expansions/README.md`): official
sources only; never invent a fact — unknown stays unknown; no U.S. News
data anywhere; no provider beyond QS/THE/ARWU; no combined/average rank
(BR15); no agency success cases; US undergraduate programmes share
central admissions facts (cite the central page per programme, never
invent a per-major threshold); `matchable` is always false until engine
rules + per-programme tests exist.

## Collection order

Computer-related UG + taught-masters first (competition track), in QS
2027 rank order, five bands: A 1–10, B 11–25, C 26–50, D 51–75, E
76–100 (band membership in `data/expansions/README.md`). UCL / Imperial
/ NUS / NTU already have 1–2 programmes each in v2 — collectors record
the *additional* computer programmes for those schools only (never
re-record a v2 programme id).

Scope widened 2026-11-25 (user: "我之前怎么说的你就怎么做"): the target
is EVERY programme of EVERY QS top-100 school, all fields. Priority
after computer: business, engineering, natural sciences,
medicine/health, humanities, social sciences, law, arts/design, and any
remaining fields — UG + taught masters first. The controlled field list
is 51 slugs (see `tools/validate_expansion.py` FIELDS); "other" is a last
resort only, every use reported. One schema limit: `degree_level` allows
only undergraduate / taught_masters, so other levels (PhD, foundation,
French diplôme d'ingénieur) cannot merge yet and are recorded as gaps,
never forced in.

## Coverage so far

Merged 2026-11-25 (all five bands A–E — QS 2027 top 100 complete):

| Measure | Now |
|---|---|
| Institutions with stats profiles | 100 / 100 QS top-100 (all five bands merged) |
| Computer programmes collected (expansion) | 366 (A 27 + B 13 kept of 43 + C 68 + D 181 + E 77), plus the 8 v2 programmes = 374 listed in total |
| Institutions with any programme | 91 of the 100 profiled (all 4 v2 institutions — UCL, Imperial, NUS, NTU — also have expansion programmes); the 9 with none are exactly the band-B held schools (Cornell, EPFL, TUM, Berkeley, Chicago, Melbourne, UNSW, UPenn, Yale) |
| Programmes held for re-verification | 30 (all band B: aggregator/Wikipedia-cited fees — see `data/expansions/hold-list.md`) |
| Application statuses confirmed | 7 open (6 LSE taught-masters + 1 band C); all others unknown (no official page stated open/closed) |
| Deadlines | 57 of 366 programmes have a deadline from an official page; the rest are null (aggregator-only dates were not used) |
| Fees | 130 of 366 programmes have a stated fee amount; 236 (64%) are unknown — no official page stated a fee in this pass, and conflicting/stale aggregator figures were not used |
| Stats coverage | Total-students sourced for 40 institutions; international % for 18, graduate % for 11, male/female for 2, student-faculty ratio for 4, founded year for 49; intro for 12, address for 7, official website for 64; membership tags for 5 institutions (first ones: Paris-Saclay LERU/EUGLOH, Glasgow Russell Group/Universitas 21, Sheffield Russell Group, Nanjing C9 League, Zurich LERU/Universitas 21); campus photos 0 (no freely licensed photo verified) |

Non-computer collection (2026-11-25, same session): business **187**
(business-administration 71, finance 55, management 23, accounting 18,
economics 18, marketing 2) + engineering **279** (electrical 50,
mechanical 48, general 46, civil 42, chemical 41, biomedical 32,
aerospace 20; ranks 1–50 only). Merged total: **832 expansion
programmes** (366 computer + 187 business + 279 engineering), 508
sources, 1,158 traceability rows; 840 listed with the 8 v2 programmes.
All 100 institutions now have programmes. Fees across the whole file:
546 known, 286 unknown (35%); deadlines on 96; 7 open, 825 unknown;
455 UG / 377 taught masters. Gaps in this round: PSL engineering
(French diplôme d'ingénieur through member schools, no UG/TM mapping);
Fudan 3 programmes fee-null (official range only); IP Paris 3
programmes fee-null (track unconfirmed). No programme used the "other"
field slug.

Band E (QS 76–100, merged 2026-11-25): 25 institutions, 77 programmes, 0 held. The merge filter stripped 20 Wikipedia-sourced stats to null (totals/founded years at Leeds, UWA, UCSD, KTH, Sheffield, Buenos Aires, Durham, Penn State, Washington, Boston U, Nottingham) — the collector had disclosed them as Wikipedia/aggregator-sourced where no official facts page was retrievable. Band E is flagship programmes only (1–7 per school); joint honours, foundation years, conversion MScs and MSci variants are not collected, and non-English-taught bachelor's (Paris-Saclay licence, Heidelberg, Nanjing, Osaka, FU Berlin BSc) are not collected.

"Every programme of every school" is the stated end goal. What is
realistic in this pass: **all computer-related UG + taught-masters
programmes for the QS top 100** (a few hundred programmes — a typical
top-100 university lists 2–8 such programmes). Full coverage of *every*
field at *every* school is thousands of programmes and is a multi-day
programme, not a single session: after the computer set lands, the next
fields in priority order are data science / AI-adjacent (already inside
the computer set), then engineering, business, and medicine — each
needing the same official-source verification per programme.

## Backend

- `backend/app/data.py`: `load_expansion()` + `validate_expansion_data()`
  (same core checks as `tools/validate_expansion.py`). Refuses to start
  on invalid content; a missing file means an empty catalogue.
- `GET /api/v1/institutions` — all 148 ranking institutions, country /
  query filters, cursor pagination; each item carries
  `has_stats_profile` and `programmes_count` (v2 + expansion).
- `GET /api/v1/institutions/{id}` — ranking record, `stats` (profile or
  null — never invented), provider ranks, `programs` (v2 matchable first,
  then expansion listed). 404 `INSTITUTION_NOT_FOUND` for unknown ids.
- `GET /api/v1/programs` — new `institution`, `field` and `catalogue`
  params. `catalogue=v2` (default) is byte-identical to the Day-2
  response; `catalogue=expansion` lists v3 only; `catalogue=all` lists
  both with `catalogue` + `matchable` flags on every item.
- `/match`, `/explain`, `/simulate` are unchanged (v2 only). An
  expansion programme becomes matchable only by a separate, per-programme
  promotion: engine rules + tests for that programme.
- OpenAPI regenerated: 17 paths (`docs/openapi.json`).

## Validation

```bash
cd ~/workspace/pathpilot-ai
.venv/bin/python tools/validate_expansion.py data/expansions/collectors/rank-01-10.json
.venv/bin/python tools/validate_expansion.py data/expansions/expansion.json
.venv/bin/python -m pytest tests/test_expansion.py -q
```

## Still missing (by priority)

1. **Re-verification pass for the 30 held band-B programmes** (`data/expansions/hold-list.md`): check their fees against official pages; merge whatever verifies. (The 9 profiled institutions that had no programmes at all — Cornell, EPFL, TUM, Berkeley, Chicago, Melbourne, UNSW, UPenn, Yale — were filled by the business/engineering collection on 2026-11-25; all 100 profiled institutions now have ≥1 programme.)
2. **Engineering ranks 51–100** — not started.
3. **Non-computer fields, in priority order** — natural sciences, medicine/health, humanities, social sciences, law, arts/design, and any remaining fields; same schema, same rules, new collection rounds. Business (187) and engineering ranks 1–50 (279) are done. The controlled field list (51 slugs) already covers all of these.
4. **Other degree levels** (PhD, foundation years, French diplôme d'ingénieur, MSci/MEng variants, joint honours, conversion MScs) — cannot merge under the current schema (`degree_level` allows only undergraduate / taught_masters); needs a schema decision before collection. Known gap: PSL engineering (French diplôme d'ingénieur through member schools, no UG/TM mapping).
5. **Programme promotion to matchable**: per-programme engine rules +
   tests (the eligibility engine's fee/academic rules are currently
   written per programme — UCL, NUS, Imperial — so this is real work per
   programme, not a flag flip).
4. **Homepage news/cases** （留学资讯 / 成功案例）: BUILT 2026-11-25 — homepage
   top is success cases (6 featured, all 55 on `/cases`) + latest news &
   policy (curated link-outs; sources scoped in
   `~/workspace/homepage_content_sources.md` — NUS Newsroom RSS, Imperial
   news feeds, British Council Study UK blog, UCAS key dates, UCL News).
   The expansion programmes are wired into the frontend as a generated
   offline mirror (`tools/generate_frontend_mirrors.py` →
   `frontend/src/lib/expansion.ts`); re-run it after the source data
   changes — `tests/test_frontend_mirrors.py` fails if the mirror is stale.
   Business (187) and engineering ranks 1–50 (279) have since merged,
   bringing the total to 832; fields beyond business/engineering are
   still open (see items 2–3 above).
5. **Institution stats gaps**: any stat no official page states stays
   null; a second pass can try national statistics offices (e.g. HESA
   for the UK, MOE for Singapore/China) where the university itself
   publishes nothing.
