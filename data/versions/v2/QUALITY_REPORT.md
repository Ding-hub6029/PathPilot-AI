# QUALITY_REPORT.md — data version v2 (Day 2, 2026-11-25)

## Coverage

8 real programmes, 0 fixtures, 0 synthetic flags. All four cells covered:

| Cell | Programmes |
|---|---|
| UK undergraduate | UCL Computer Science BSc (2026); Imperial Computing BEng (Oct 2027) |
| UK taught masters | Imperial Computing MSc (Oct 2027); UCL Computer Science MSc (Sep 2027) |
| Singapore undergraduate | NUS Bachelor of Computing (CS) (Aug 2027); NTU Bachelor of Computing (Hons) in CS (AY2027/28) |
| Singapore taught masters | NUS Master of Computing (CS) (Aug 2027); NTU MSc in Artificial Intelligence (AY2027/28) |

72 facts, 29 sources, 25 unknowns. Every fact traces to a source id + excerpt + `retrieved_at` in `source-manifest.json`.

## Provenance

- v1 programmes, facts, sources and unknowns are copied unchanged from `data/versions/v1/`, except the UCL TOEFL unknown entry, which is updated: TOEFL is now modelled in the Day 2 rules engine (Jan 2026 scale split; no test date → UNKNOWN).
- The 6 new programmes were researched 2026-11-24 16:28–16:32 UTC (2026-11-25 00:28–00:32 CST) from official university pages only, via browser crawls. **No content hashes are claimed** for Day 2 facts: they come from browser crawls, not direct byte fetches.
- Two targets from the brief do not exist and were switched (recorded as failed sources `imperial-bsc-target`, `ntu-cs-beng-target`): Imperial has no "Computing BSc" (the degree is Computing BEng, G400); NTU no longer offers a "Computer Science BEng" (current equivalent is Bachelor of Computing (Hons) in Computer Science).
- `f-ucl-gcse` was added in v2: the GCSE English Language and Mathematics grade C/4 requirement stated on the UCL BSc page (source `ucl-bsc`). The Day 2 engine cites it; v1 had no dedicated GCSE fact.

## Honest limitations (all recorded as UNKNOWN, never guessed)

- **No fixed academic minimums for NUS/NTU undergraduate programmes.** NUS and NTU publish only Indicative Grade Profiles of admitted students (IGP), not thresholds. Meeting an IGP figure does not guarantee admission, and the engine never treats IGP as a threshold — the academic rule for both Singapore undergraduate programmes is UNKNOWN with the IGP shown as context.
- **UCL Computer Science MSc English level is UNKNOWN.** The course page states no UCL English level. Third-party sites report Level 2 (IELTS 7.0/6.5), but that is not official evidence and was NOT used; the Level 2 definition is recorded only as a definition fact.
- **Singapore undergraduate fees are AY2026/27 rates** (latest published; AY2027/28 not yet published). NTU's non-subsidised band for Computer Science is not labelled lab/non-lab on the fee table, so the fee rule does not decide it — it returns UNKNOWN for non-subsidised applicants.
- **NTU MSAI deadline is UNKNOWN** (two conflicting NTU-wide statements found, neither programme-specific; neither adopted). NTU MSAI start month is also UNKNOWN.
- **Imperial MSc application fee and Round 1 deadline are UNKNOWN** (not stated on the course page; aggregator figures not copied).
- **Imperial BEng TMUA score threshold and STEP grade are UNKNOWN** (required, but no threshold stated).
- **UCL BSc page direct curl failed (exit 18) on 2026-11-23**; its facts rest on a browser crawl at 18:39–18:40 UTC, no SHA-256 hash claimed — carried over from v1.

## Checks run

- Cross-reference check (script, 2026-11-25): every programme source id, requirement source id, and manifest fact source/program id resolves; 0 bad references; fact ids unique.
- Backend startup validation (`data.py`): refuses fixtures in real data, validates `data_version`, duplicate ids, and source references at load time.
- Live verification after the v2 switch is recorded in `TASKS.md` (Day 2 section).
