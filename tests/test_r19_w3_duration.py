"""Round 19, worker W3 — nit 4: mixed-language duration on the step-8
UZH card (and nit 5 judgement lock-in).

Nit 4 root cause: `zurich-informatics-bsc-2027` carried no
`program.duration.<id>` key in any locale (the ETH siblings did),
and its data duration "3 years (180 ECTS)" has a parenthetical the
old generic fallback regex could not match, so the raw English fell
through on the step-8 card while the ETH cards showed
"3 年（180 学分）". Fix, display-side only (the expansion data is
untouched — the English string is the verified source value):
- the missing per-programme key in all 6 locales (established
  pattern, cf. eth-cs-bsc-2027);
- the generic fallback in `formatDuration` now parses the
  "(N credits)" / "(N ECTS)" / "(N semesters, N ECTS)" parenthetical
  through new `format.credit(s)` / `format.ects` /
  `format.semester(s)` keys, so any other programme with the same
  shape (e.g. the ETH MSc "2 years (4 semesters, 120 ECTS)") is
  localised too. A parenthetical the parser does not know
  ("1.5 years (three terms)", "2-3 years") still falls back to the
  raw value rather than an invented rendering.
- ECTS stays "ECTS" in every locale: it is a standard acronym, kept
  like IELTS elsewhere; only the surrounding words are localised
  ("3 years (180 ECTS)" -> "3 年（180 ECTS）" in zh-CN).

Round 20, worker W2 — the nit above is now resolved the other way
round: the two ETH BSc keys said "credits"/"学分" while the UZH key
said "ECTS", so the step-8 cards were inconsistent. The standard is
ECTS for both: ETH's own MSc records in the same repo quote ETH's
official admission requirement of "at least 180 ECTS" for a
bachelor's degree and give ETH MSc durations as "(4 semesters,
120 ECTS)", and the other Swiss BSc (EPFL AI) is "3 years
(180 ECTS)". Only the unit wording changed (180 unchanged); the
two ETH keys now read ECTS in all 6 locales. The generic fallback
is untouched — "credits" stays a real unit there (NUS "160
credits", NTU "30 academic credits") and the synthetic-credits
fallback expectations below still pin credits -> 学分.

Nit 5 (judgement, NOT fixed — see /tmp/r19-w3-decisions.md): the
Switzerland + cool flow shows the country and climate questions a
second time. Root cause is twofold and neither half is a one-line
ordering/gating fix: (1) the backend offline extractor
(`_deterministic_extract`, pref_chat.py) understands countries +
note only, never enums, so an offline climate answer ("凉爽")
extracts to {} and the template reply re-asks climate; (2) the
frontend then preserves that answer locally (`mapFailedPrefAnswer`
DOES understand "凉爽") and switches to the guided queue, whose
history re-renders the answered countries + climate blocks with the
no-match opinion. Nothing is lost and no re-answer is forced — the
queue advances to environment — so the behaviour is accepted as is.
The test below pins the backend half of that diagnosis, so a future
decision to extend the offline extractor changes it deliberately.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]
FORMAT = ROOT / "frontend" / "src" / "lib" / "format.ts"

# Audit profile (task 13): step-8 top 3, all Swiss, UG computing.
SWISS_STEP8 = ["eth-cs-bsc-2027", "eth-cse-bsc-2027", "zurich-informatics-bsc-2027"]

EXPECTED_ZH = {
    "eth-cs-bsc-2027": "3 年（180 ECTS）",
    "eth-cse-bsc-2027": "3 年（180 ECTS）",
    "zurich-informatics-bsc-2027": "3 年（180 ECTS）",
}
EXPECTED_EN = {
    "eth-cs-bsc-2027": "3 years (180 ECTS)",
    "eth-cse-bsc-2027": "3 years (180 ECTS)",
    "zurich-informatics-bsc-2027": "3 years (180 ECTS)",
}

# Raw English duration words that must never appear in a zh-CN card.
RAW_ENGLISH_WORDS = ("years", "year", "months", "month", "credits", "credit",
                     "semesters", "semester", "full-time")


def _messages(locale: str) -> dict:
    return json.loads((ROOT / "frontend" / "messages" / f"{locale}.json").read_text(encoding="utf-8"))


def _expansion_by_id() -> dict:
    data = json.loads((ROOT / "data" / "expansions" / "expansion.json").read_text(encoding="utf-8"))
    out: dict = {}

    def walk(o):
        if isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, dict):
            if o.get("id") and o.get("duration"):
                out[o["id"]] = o
            for v in o.values():
                walk(v)

    walk(data)
    return out


# ---------------------------------------------------------------------------
# Locale keys
# ---------------------------------------------------------------------------

def test_zurich_duration_key_exists_in_all_locales():
    for locale in LOCALES:
        msgs = _messages(locale)
        value = msgs.get("program.duration.zurich-informatics-bsc-2027")
        assert value, locale
        assert "180" in value and "3" in value, (locale, value)
        if locale != "en":
            assert value != "3 years (180 ECTS)", (locale, value)


def test_locale_key_parity_after_duration_keys():
    sets = {locale: set(_messages(locale)) for locale in LOCALES}
    base = sets["en"]
    # Round 23 W3: +3 wizard.note* keys (noteBeautifulEnv,
    # noteCampusVibe, noteUniversityTown) for the localised countries
    # note in prefSummary — parity across locales still holds.
    # Round 24 W3: +2 results.nextSummaryZero* keys (zero + closest
    # lines for the Gaokao-caused "0 meet" headline) — parity holds.
    assert len(base) == 975, len(base)
    for locale in LOCALES:
        assert sets[locale] == base, (locale, sets[locale] ^ base)


def test_duration_format_keys_exist_in_all_locales():
    for locale in LOCALES:
        msgs = _messages(locale)
        for key in ("format.credit", "format.credits", "format.ects",
                    "format.semester", "format.semesters"):
            assert msgs.get(key), (locale, key)


# ---------------------------------------------------------------------------
# Real formatDuration execution (node harness over tsc-compiled lib)
# ---------------------------------------------------------------------------

_NODE_HARNESS = r"""
const fmt = require(OUT + '/format.js');
const cases = JSON.parse(process.argv[2]);
const out = [];
for (const [id, duration, locale] of cases) {
  const msgs = require(FE + '/messages/' + locale + '.json');
  const t = (k) => (k in msgs ? msgs[k] : k);
  out.push({ id, rendered: fmt.formatDuration({ id, duration }, t, locale) });
}
console.log(JSON.stringify(out));
"""


def _run_format_duration(tmp_path, cases):
    """cases: [(id, duration, locale)] -> { (id, locale): rendered }.
    Compiles the real frontend format.ts (same pattern as
    tests/test_p0_retest6.py) and executes formatDuration against
    the real locale files."""
    outdir = tmp_path / "r19_format"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/format.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r19_format_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(fe))), encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness), json.dumps(cases, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    rendered = json.loads(node.stdout)
    assert len(rendered) == len(cases)
    return {(row["id"], case[2]): row["rendered"]
            for row, case in zip(rendered, cases)}


def test_step8_swiss_cards_localised_in_zh(tmp_path):
    """The audit-profile step-8 card set: no card shows a raw English
    duration when the UI locale is zh-CN."""
    by_id = _expansion_by_id()
    cases = [(pid, by_id[pid]["duration"], "zh-CN") for pid in SWISS_STEP8]
    got = _run_format_duration(tmp_path, cases)
    for pid in SWISS_STEP8:
        rendered = got[(pid, "zh-CN")]
        assert rendered == EXPECTED_ZH[pid], (pid, rendered)
        lowered = rendered.lower()
        for word in RAW_ENGLISH_WORDS:
            assert word not in lowered, (pid, rendered)


def test_step8_swiss_cards_english_stays_sensible(tmp_path):
    by_id = _expansion_by_id()
    cases = [(pid, by_id[pid]["duration"], "en") for pid in SWISS_STEP8]
    got = _run_format_duration(tmp_path, cases)
    for pid in SWISS_STEP8:
        assert got[(pid, "en")] == EXPECTED_EN[pid], (pid, got[(pid, "en")])


def test_step8_swiss_cards_localised_in_french(tmp_path):
    by_id = _expansion_by_id()
    cases = [(pid, by_id[pid]["duration"], "fr") for pid in SWISS_STEP8]
    got = _run_format_duration(tmp_path, cases)
    assert got[("eth-cs-bsc-2027", "fr")] == "3 ans (180 ECTS)"
    assert got[("zurich-informatics-bsc-2027", "fr")] == "3 ans (180 ECTS)"


def test_generic_parenthetical_fallback_zh(tmp_path):
    """The fallback alone (no per-programme key) localises the
    parenthetical — this is what fixes the next programme with the
    same shape, not just the UZH card."""
    cases = [
        ("synthetic-credits", "3 years (180 credits)", "zh-CN"),
        ("synthetic-ects", "3 years (180 ECTS)", "zh-CN"),
        ("synthetic-semesters", "2 years (4 semesters, 120 ECTS)", "zh-CN"),
        ("synthetic-plain", "3 years", "zh-CN"),
        ("synthetic-fulltime", "1 year full-time", "zh-CN"),
    ]
    got = _run_format_duration(tmp_path, cases)
    assert got[("synthetic-credits", "zh-CN")] == "3 年（180 学分）"
    assert got[("synthetic-ects", "zh-CN")] == "3 年（180 ECTS）"
    assert got[("synthetic-semesters", "zh-CN")] == "2 年（4 学期，120 ECTS）"
    assert got[("synthetic-plain", "zh-CN")] == "3 年"
    assert got[("synthetic-fulltime", "zh-CN")] == "1 年（全日制）"


def test_generic_parenthetical_fallback_english(tmp_path):
    cases = [
        ("synthetic-credits", "3 years (180 credits)", "en"),
        ("synthetic-ects", "3 years (180 ECTS)", "en"),
        ("synthetic-semesters", "2 years (4 semesters, 120 ECTS)", "en"),
    ]
    got = _run_format_duration(tmp_path, cases)
    assert got[("synthetic-credits", "en")] == "3 years (180 credits)"
    assert got[("synthetic-ects", "en")] == "3 years (180 ECTS)"
    assert got[("synthetic-semesters", "en")] == "2 years (4 semesters, 120 ECTS)"


def test_unparseable_duration_falls_back_raw(tmp_path):
    """Word parentheticals and ranges are not guessed at — the raw
    verified value is shown instead of an invented rendering."""
    cases = [
        ("synthetic-wordparen", "1.5 years (three terms)", "zh-CN"),
        ("synthetic-range", "2-3 years", "zh-CN"),
    ]
    got = _run_format_duration(tmp_path, cases)
    assert got[("synthetic-wordparen", "zh-CN")] == "1.5 years (three terms)"
    assert got[("synthetic-range", "zh-CN")] == "2-3 years"


def test_format_duration_call_sites_pass_locale():
    """The step-8 card (RecChat), the browse list and the detail page
    all pass the UI locale, so the parenthetical style follows it."""
    rec = (ROOT / "frontend" / "src" / "components" / "RecChat.tsx").read_text(encoding="utf-8")
    assert "formatDuration(p, t, locale)" in rec
    browse = (ROOT / "frontend" / "src" / "app" / "programs" / "page.tsx").read_text(encoding="utf-8")
    assert "formatDuration(p, t, locale)" in browse
    detail = (ROOT / "frontend" / "src" / "app" / "programs" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert detail.count("formatDuration(program, t, locale)") == 2
    src = FORMAT.read_text(encoding="utf-8")
    assert "formatDuration(program, t, locale)" in src  # formatProgramLine


# ---------------------------------------------------------------------------
# Round 21, worker W2 — /results cards showed no duration at all
# ---------------------------------------------------------------------------

def test_r21_results_card_renders_duration_via_format_duration():
    """P1 root cause, pinned: the /results card JSX never called
    formatDuration (nor formatProgramLine) — the only duration on the
    page lived on the wizard step-8 cards (RecChat comment) and the
    detail page, while the fee / IELTS figures here come from the
    per-rule RuleRows, so duration (not a rule) never appeared. The
    card now renders formatDuration(p, t, locale) under the title,
    on the same `p` the card already resolves from mergePrograms()."""
    results = (ROOT / "frontend" / "src" / "app" / "results" / "page.tsx").read_text(encoding="utf-8")
    assert "import { formatDuration, joinList } from '../../lib/format';" in results
    assert "{formatDuration(p, t, locale)}" in results


def test_r21_institution_cards_render_duration():
    """Same gap on the institution page, two shapes: the v2 list
    showed no duration at all, and the expansion card rendered the
    raw English value (` · ${p.duration}` — "3 years (180 credits)"
    in zh-CN). Both now go through the shared formatDuration path."""
    inst = (ROOT / "frontend" / "src" / "app" / "institutions" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert "import { formatDuration } from '../../../lib/format';" in inst
    assert inst.count("formatDuration(p, t, locale)") == 2  # v2 list + expansion card
    assert "{formatDuration(p, t, locale)}" in inst
    assert "` · ${formatDuration(p, t, locale)}`" in inst
    assert "` · ${p.duration}`" not in inst
    # The comparison columns on /results (WhyNot CompareView) had the
    # same gap — no duration in the column headers.
    whynot = (ROOT / "frontend" / "src" / "components" / "WhyNot.tsx").read_text(encoding="utf-8")
    assert "import { formatDuration, joinList } from '../lib/format';" in whynot
    assert "{formatDuration(program, t, locale)}" in whynot


def test_r21_no_programme_card_renders_raw_duration():
    """No .tsx anywhere renders a raw duration interpolation any more
    (the institution expansion card was the only one; api.ts data
    mappings and format.ts itself are not renders)."""
    for path in (ROOT / "frontend" / "src").rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        assert "${p.duration}" not in text, path
        assert "{p.duration}" not in text, path
        assert "${program.duration}" not in text, path
        assert "{program.duration}" not in text, path


def test_r21_format_duration_accepts_expansion_programme_shape():
    """The shared path is reused, not duplicated: formatDuration's
    parameter is Pick<Program, 'id' | 'duration'>, so an
    ExpansionProgram ({id, duration, ...} — no feeItems etc.)
    type-checks as an argument (proven by `npx tsc --noEmit` over
    the institution page, which passes one directly)."""
    src = FORMAT.read_text(encoding="utf-8")
    assert "formatDuration(program: Pick<Program, 'id' | 'duration'>" in src


_NODE_DATAFLOW_HARNESS = r"""
const api = require(OUT + '/api.js');
const fmt = require(OUT + '/format.js');
const fs = require('fs');
const ids = ['eth-cs-bsc-2027', 'eth-cse-bsc-2027', 'zurich-informatics-bsc-2027'];
const merged = api.mergePrograms([]);
const out = [];
for (const id of ids) {
  const p = merged.find((x) => x.id === id);
  if (!p) { out.push({ id, missing: true }); continue; }
  for (const locale of ['zh-CN', 'en']) {
    const msgs = JSON.parse(fs.readFileSync(FE + '/messages/' + locale + '.json', 'utf-8'));
    const t = (k) => (k in msgs ? msgs[k] : k);
    out.push({ id, locale, duration: p.duration, rendered: fmt.formatDuration(p, t, locale) });
  }
}
console.log(JSON.stringify(out));
"""


def test_r21_duration_reaches_results_card_for_swiss_three(tmp_path):
    """Data-flow end of the P1: the real compiled api.ts —
    expansionToProgram carries `duration` verbatim and mergePrograms
    includes all three Swiss ids — feeds the real formatDuration, and
    the value the /results card now renders is exactly
    "3 年（180 ECTS）" / "3 years (180 ECTS)". This is the value the
    card component receives: the card resolves `p` from the same
    mergePrograms(livePrograms) list (see the call-site test above)."""
    outdir = tmp_path / "r21_dataflow"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/api.ts", "src/lib/format.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r21_dataflow_harness.js"
    harness.write_text(
        _NODE_DATAFLOW_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(fe))), encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    rows = json.loads(node.stdout)
    assert len(rows) == 6, rows
    by_key = {(r["id"], r["locale"]): r for r in rows}
    for pid in SWISS_STEP8:
        assert not by_key[(pid, "zh-CN")].get("missing"), pid
        assert by_key[(pid, "zh-CN")]["duration"], pid  # raw value reaches the card
        assert by_key[(pid, "zh-CN")]["rendered"] == EXPECTED_ZH[pid], (pid, by_key[(pid, "zh-CN")])
        assert by_key[(pid, "en")]["rendered"] == EXPECTED_EN[pid], (pid, by_key[(pid, "en")])


# ---------------------------------------------------------------------------
# Round 22, worker W3 — EPFL 4th card: "3 years" without ECTS
# ---------------------------------------------------------------------------
# Root cause is DATA, not a rendering path (see /tmp/r22-w3-decisions.md):
# every programme-card surface already renders through the shared
# formatDuration path (results card, step-8 RecChat, browse, detail,
# institution pages, CompareView, homepage + report via
# formatProgramLine), and the R21 test above pins that no .tsx renders
# a raw duration. The 4th Swiss card is epfl-cs-bsc-2027, whose data
# duration was the bare "3 years" with no per-programme locale key,
# so the generic fallback honestly rendered just that — while its
# sibling epfl-ai-bsc-2027 already carried "3 years (180 ECTS)".
# The ECTS figure is verified, not invented: EPFL's official
# "Study programs structure" page states "Bachelor: 180 ECTS" and
# Ordinance RS 414.132.3 Art. 5 requires 180 ECTS credits for the
# Bachelor — so all five EPFL BSc programmes that had the bare value
# now carry "3 years (180 ECTS)" with the new source
# epfl-bachelor-ects (top-level + per-programme; the backend
# validator rejects a programme source id missing from data["sources"]).
# EPFL MSc programmes are deliberately untouched: the same official
# page says masters are "90 – 120 ECTS ... depending on the field",
# so no blanket figure can be assigned without per-programme checks.

EPFL_BSC = [
    "epfl-cs-bsc-2027",
    "epfl-ai-bsc-2027",
    "epfl-mechanical-engineering-bsc-2027",
    "epfl-electrical-engineering-bsc-2027",
    "epfl-civil-engineering-bsc-2027",
    "epfl-chemical-engineering-bsc-2027",
]
EPFL_BSC_FIXED = [pid for pid in EPFL_BSC if pid != "epfl-ai-bsc-2027"]
EPFL_BSC_ECTS_SOURCE = "epfl-bachelor-ects"


def _expansion_data() -> dict:
    return json.loads((ROOT / "data" / "expansions" / "expansion.json").read_text(encoding="utf-8"))


def test_r22_epfl_bsc_duration_data_carries_ects():
    """Data fix, pinned: no EPFL Bachelor is left with the bare
    "3 years" — all six carry "3 years (180 ECTS)"."""
    by_id = _expansion_by_id()
    for pid in EPFL_BSC:
        prog = by_id[pid]
        assert prog["degree_level"] == "undergraduate", pid
        assert prog["duration"] == "3 years (180 ECTS)", (pid, prog["duration"])


def test_r22_epfl_bsc_duration_source_is_traced():
    """The ECTS figure is sourced, not asserted: each fixed programme
    lists epfl-bachelor-ects, and that id resolves to the EPFL
    "Study programs structure" page in the top-level sources (the
    backend validator requires the resolution)."""
    data = _expansion_data()
    top = {s["id"]: s for s in data["sources"]}
    src = top.get(EPFL_BSC_ECTS_SOURCE)
    assert src, EPFL_BSC_ECTS_SOURCE
    assert src["url"] == "https://www.epfl.ch/education/bachelor/study-programs-structure/", src
    assert "180" in (src.get("title") or ""), src
    by_id = _expansion_by_id()
    for pid in EPFL_BSC_FIXED:
        ids = {s["id"] for s in by_id[pid]["sources"]}
        assert EPFL_BSC_ECTS_SOURCE in ids, (pid, ids)


def test_r22_epfl_cards_render_ects_in_zh_and_en(tmp_path):
    """Rendering end: the real formatDuration over the corrected data
    durations renders exactly "3 年（180 ECTS）" / "3 years
    (180 ECTS)" for every EPFL BSc card — the same strings the top-3
    Swiss cards already show (no per-programme locale key needed:
    the generic "(180 ECTS)" parenthetical fallback handles it)."""
    by_id = _expansion_by_id()
    cases = ([(pid, by_id[pid]["duration"], "zh-CN") for pid in EPFL_BSC]
             + [(pid, by_id[pid]["duration"], "en") for pid in EPFL_BSC])
    got = _run_format_duration(tmp_path, cases)
    for pid in EPFL_BSC:
        assert got[(pid, "zh-CN")] == "3 年（180 ECTS）", (pid, got[(pid, "zh-CN")])
        assert got[(pid, "en")] == "3 years (180 ECTS)", (pid, got[(pid, "en")])


def test_r22_epfl_msc_duration_not_invented():
    """Deliberate non-fix, pinned: EPFL masters stay at the bare
    "2 years" — the official page says masters are 90–120 ECTS
    depending on the field, so assigning one figure to all of them
    would be invented data. A per-programme MSc ECTS pass is a
    separate task."""
    by_id = _expansion_by_id()
    msc = [pid for pid, p in by_id.items()
           if pid.startswith("epfl-") and p.get("degree_level") == "taught_masters"]
    assert msc, "no EPFL MSc programmes found"
    for pid in msc:
        assert by_id[pid]["duration"] == "2 years", (pid, by_id[pid]["duration"])
        assert "ECTS" not in by_id[pid]["duration"], pid


def test_r22_no_swiss_bsc_card_lacks_ects(tmp_path):
    """Blanket guard over the audit profile: every Swiss
    undergraduate programme in the catalogue now renders with an
    ECTS figure in both locales — the EPFL gap cannot recur on the
    next card without this test failing."""
    by_id = _expansion_by_id()
    data = _expansion_data()
    swiss_bsc = [p["id"] for p in data["programs"]
                 if p.get("country") == "CH" and p.get("degree_level") == "undergraduate"]
    assert len(swiss_bsc) == 9, swiss_bsc  # 6 EPFL + 2 ETH + 1 UZH
    cases = ([(pid, by_id[pid]["duration"], "zh-CN") for pid in swiss_bsc]
             + [(pid, by_id[pid]["duration"], "en") for pid in swiss_bsc])
    got = _run_format_duration(tmp_path, cases)
    for pid in swiss_bsc:
        assert "180 ECTS" in got[(pid, "zh-CN")], (pid, got[(pid, "zh-CN")])
        assert "180 ECTS" in got[(pid, "en")], (pid, got[(pid, "en")])


# ---------------------------------------------------------------------------
# Nit 5 — judgement lock-in (backend half of the diagnosis)
# ---------------------------------------------------------------------------

def test_nit5_offline_climate_answer_not_extracted_by_backend(monkeypatch):
    """Pinned diagnosis, not a bug fix: with no model, the offline
    extractor understands countries + note only, so "凉爽" extracts
    to {} and the template reply re-asks climate (next_question
    stays 'climate'). The frontend preserves the answer locally
    (mapFailedPrefAnswer understands "凉爽") and the guided queue
    advances to environment, so no re-answer is forced — that is why
    the repeat is accepted (see /tmp/r19-w3-decisions.md). If the
    offline extractor is ever extended to enums, update this test
    deliberately."""
    from ai.pref_chat import pref_answer
    from ai.provider import ProviderAdapter

    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    provider = ProviderAdapter()
    assert not provider.available
    result = pref_answer("凉爽", "zh-CN",
                         known={"countries": ["CH"], "note": "环境优美"},
                         provider=provider)
    assert result["extracted"] == {}, result["extracted"]
    assert result["next_question"] == "climate", result["next_question"]
    assert result["ai_status"] == "unavailable"
