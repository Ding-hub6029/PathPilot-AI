# Programme expansion — data/expansions/

Goal (user direction, 2026-11-25, after the reference video of a Chinese
study-abroad app): QS 2027 top 100 institutions ALL fully covered, and
EVERY programme of every school included. The reference app's school detail
page shows: campus photo, rank chips, a stats row (total students,
student-faculty ratio, international %, graduate %, male:female), intro,
official website + address, membership tags, and tabs for 学校简介 /
费用概览 / 专业列表 / 留学资讯 / 成功案例. Programme rows show degree
name, duration, tuition, and application status.

This directory is the DATA + BACKEND foundation for that. Frontend work
(rankings page, pet, programme names, detail pages) is a separate agent's
job — do not touch `frontend/`.

## Files

| File | What it is |
|---|---|
| `schema/institution-profile.json` | JSON Schema for one institution's stats profile |
| `schema/expanded-program.json` | JSON Schema for one expanded programme (extends the v2 program shape) |
| `schema/expansion-file.json` | JSON Schema for the merged canonical file |
| `collectors/rank-*.json` | Raw per-band collector output (one file per QS rank band) |
| `expansion.json` | Merged canonical file (`data_version: "v3"`), the only file the backend loads |
| `traceability.csv` | One row per sourced fact (mirrors `data/versions/v2/traceability.csv`) |
| `source-manifest.json` | Registry of every source used in `expansion.json` |

`data/versions/v2/` is NEVER modified by expansion work.

## Collection rules (non-negotiable)

1. **Official sources only.** University official site, UCAS, government
   pages. Every fact carries `source_url` + `retrieved_at`.
2. **Never invent a fact.** No programme, fee, stat, deadline, threshold
   or requirement that is not on an official page. **Unknown stays
   unknown** (null + a note saying so).
3. **No U.S. News data anywhere** (user ordered it removed entirely).
   No ranking provider beyond QS / THE / ARWU.
4. **No agency "success cases".** The reference video's offer dossiers
   (student backgrounds + consultant cards) are agency-collected; we do
   not copy them. Cases on the site must be official student stories
   only (see `~/workspace/homepage_content_sources.md`).
5. **No combined/average rank** (BR15). Rankings live in
   `data/versions/v2/rankings.json` only; the expansion never stores a rank.
6. **Computer-related first.** The competition track is computer-related:
   collect computer UG + taught-masters programmes first, in QS rank
   order, then other fields only when the computer set is done.
7. **US undergraduate programmes share central admissions facts.**
   MIT / Stanford / Harvard / Princeton etc. admit centrally — record the
   central tuition, deadlines, SAT/ACT policy and English requirements on
   each programme with the central admissions page cited. Never invent a
   per-major threshold.
8. **`matchable` in the expansion file follows the round-6 promotion rule.**
   `tools/promote_expansion.py` sets `matchable=true` for every programme
   with at least one evaluable rule (see
   `domain/expansion_eval.evaluable_rules`) whose `degree_level` is
   `undergraduate` / `taught_masters`, and `matchable=false` for all
   others (foundation / joint_honours stay display-only — the wizard has
   no track for them). The backend serves matchable expansion programmes
   through `/match` with the generic evaluator; the rest are listed data
   only.
9. **Application status** (`open`/`closed`) only from an official
   admissions/deadline page that states it for the current cycle, with
   `application_status_source` + `application_status_as_of`. Otherwise
   `unknown`.
10. **Campus photos** only when freely licensed (Wikimedia Commons CC,
    CC0, public domain) with licence + attribution recorded. Never a press
    photo, never a hotlinked tokenised URL.
11. **Membership tags** only where the institution itself claims the
    membership on its official site, with the source per tag.

## Collection order (QS 2027 rank order)

| Band | QS ranks | Institutions |
|---|---|---|
| A | 1–10 | MIT, Imperial, Stanford, Oxford, Harvard, Cambridge, Caltech, ETH Zurich, UCL, NUS |
| B | 11–25 | HKU, NTU, Peking, Tsinghua, UPenn, Cornell, Yale, CUHK, UNSW, Johns Hopkins, UC Berkeley, EPFL, Melbourne, Chicago, TUM |
| C | 26–50 | Fudan, Princeton, Sydney, ANU, McGill, Monash, Toronto, HKUST, PSL, Edinburgh, SJTU, KCL, SNU, Tokyo, Manchester, Queensland, Yonsei, Columbia, Institut Polytechnique de Paris, Northwestern, UBC, Zhejiang, Delft, UCLA, HK PolyU |
| D | 51–75 | Michigan, CityU HK, Korea University, National Taiwan University, CMU, Universiti Malaya, Bristol, NYU, KU Leuven, Amsterdam, LMU, LSE, KFUPM, Kyoto, KAIST, Brown, Auckland, Birmingham, Warwick, Duke, Lund, UT Austin, Sorbonne, UIUC, Trinity College Dublin |
| E | 76–100 | Paris-Saclay, Leeds, UWA, Adelaide, Glasgow, UCSD, KTH, Sheffield, Buenos Aires, Durham, Heidelberg, Politecnico di Milano, UTS, Uppsala, Nanjing, Copenhagen, Penn State, Washington, Boston University, Osaka, Alberta, Institute of Science Tokyo, Nottingham, FU Berlin, Zurich |

Rank order is taken from `data/versions/v2/rankings.json` (provider `qs`,
edition `2027`); do not trust any other list. UCL / Imperial / NUS /
NTU already have 1–2 programmes each in v2 — collectors record the
*additional* computer programmes for those schools (new ids; never
re-record a v2 programme id) plus their institution stats profiles.

## Validation

```bash
cd ~/workspace/pathpilot-ai
.venv/bin/python tools/validate_expansion.py data/expansions/collectors/rank-01-10.json
.venv/bin/python tools/validate_expansion.py data/expansions/expansion.json
```

The validator checks: file shape, institution ids
exist in v2 rankings, programme ids are unique and do not collide with
v2, every referenced source exists, no U.S. News strings, no
`synthetic: true`, `matchable` flags follow the promotion rule, required fields,
`name_localized.zh-CN` present, application-status sourcing, sane stat
ranges, and traceability rows for every sourced fact. A band file that
fails validation is not merged.

## Backend contract

- `GET /api/v1/institutions` — list (country / query filters, cursor
  pagination). `GET /api/v1/institutions/{id}` — stats profile + ranks +
  programme list (v2 matchable programmes first, then expansion
  programmes, each flagged with its `catalogue`).
- `GET /api/v1/programs` gains `institution` and `field` filters and
  serves v2 + expansion programmes together; each item carries
  `catalogue: "v2" | "expansion"` and `matchable`. `/match`, `/explain`
  and `/simulate` are unchanged (v2 only).
- The backend loads `data/expansions/expansion.json` at import and
  refuses to start on any validation failure, same as v2.
