"""Round 24 W2: list separators follow the active locale.

The pet's English reply to "What is the tuition fee for ETH Zurich
Computer Science?" read "I found 2 matching programmes: ETH Zurich
— MSc in Computer Science、ETH Zurich — Bachelor of Science in
Computer Science. Tell me undergraduate or masters." — programme
names joined with "、", the Chinese enumeration comma, inside an
English sentence. Root cause: two sites in ``ai.assistant`` joined
with a bare ``"、"`` in every locale (``ask()`` ambiguous_programme
and ambiguous_rank), and every other site hard-coded ``"、” if
locale == "zh-CN" else ", "``, so ar (Arabic comma "،") never got
its own separator anywhere.

The fix routes every name-list join through one helper per side —
``ai.locale_sep.join_list`` (backend) and ``joinList`` in
``frontend/src/lib/format.ts`` (frontend) — with the standard
enumeration separator per locale: ", " in en/es/fr/pt-BR, "、" in
zh-CN, "، " in ar.

Covers, with no API key and no network:

- the "found N matching programmes" line (``assistant.ask``),
  in all 6 locales, via the exact reporter question;
- the step-8 which-one line (``chat._scope_names_line``);
- the country institutions line (``assistant.country_answer``);
- the deterministic evidence lines (cities / country / ranking
  top 3) and the devil conflict line (``ai.chat``);
- the explain gap-state joins (other-requirement labels, GCSE
  subjects, IELTS components) and the IELTS fact join;
- the frontend ``joinList`` helper, via a node harness over the
  compiled ``frontend/src/lib/format.ts`` (same pattern as
  tests/test_r13_pref_summary.py);
- locale key parity across ``frontend/messages/*.json`` (no new
  keys were needed for this fix, and the counts must still match).

Every rendered line is asserted to join with its own locale's
separator AND to contain no other locale's separator.

Run from the project root:
    .venv/bin/pytest tests/test_r24_w2_list_separator.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ai.assistant import LOCALES, ask, country_answer
from ai.chat import (_WHICH_ONE_LINES, _climate_evidence, _scope_names_line,
                     country_evidence_line, devil_conflict_line,
                     evidence_cities_line, ranking_overview_line)
from ai.explain import localised_gap_state
from ai.grounding import Source
from ai.locale_sep import LIST_SEPARATORS, join_list, list_separator
from app.schemas import RuleResult

ROOT = Path(__file__).resolve().parents[1]

Q_ETH_CS_FEE = "What is the tuition fee for ETH Zurich Computer Science?"
ETH_MSC = "ETH Zurich — MSc in Computer Science"
ETH_BSC = "ETH Zurich — Bachelor of Science in Computer Science"

SEP = {"en": ", ", "zh-CN": "、", "es": ", ", "fr": ", ", "pt-BR": ", ",
       "ar": "، "}
# Separators no line in this locale may contain (the other locales'
# distinct marks; ", " is shared by en/es/fr/pt-BR so it is only
# forbidden where the locale's own separator is not ", ").
FORBIDDEN = {
    "en": ("、", "،"),
    "zh-CN": (", ", "،"),
    "es": ("、", "،"),
    "fr": ("、", "،"),
    "pt-BR": ("、", "،"),
    "ar": ("、", ", "),
}


def _assert_joined(line: str, names: tuple[str, ...], locale: str) -> None:
    """``names`` appear in ``line`` joined with ``locale``'s separator
    (in either order — call sites order the list differently) and no
    other locale's separator appears anywhere in the line."""
    for name in names:
        assert name in line, (locale, line)
    sep = SEP[locale]
    joined = (sep.join(names) in line) or (sep.join(reversed(names)) in line)
    assert joined, (locale, line)
    for bad in FORBIDDEN[locale]:
        assert bad not in line, (locale, bad, line)


# ---------------------------------------------------------------------------
# The helper itself
# ---------------------------------------------------------------------------

def test_list_separator_table():
    assert LIST_SEPARATORS == SEP
    for locale in LOCALES:
        assert list_separator(locale) == SEP[locale]
        assert join_list(["A", "B", "C"], locale) == SEP[locale].join(["A", "B", "C"])
    # Unknown locale falls back to the Latin comma, never "、".
    assert list_separator("xx") == ", "
    assert join_list(["A", "B"], "xx") == "A, B"


# ---------------------------------------------------------------------------
# The reported line, and the other backend name-list joins
# ---------------------------------------------------------------------------

def test_ask_ambiguous_programme_all_locales():
    for locale in LOCALES:
        line = ask(Q_ETH_CS_FEE, locale)["lines"][0]
        _assert_joined(line, (ETH_MSC, ETH_BSC), locale)


def test_country_answer_all_locales():
    names = ("ETH Zurich", "École Polytechnique Fédérale de Lausanne",
             "University of Zurich")
    for locale in LOCALES:
        line = country_answer("CH", locale)["lines"][0]
        _assert_joined(line, names, locale)


def test_step8_which_one_line_all_locales():
    for locale in LOCALES:
        line = _scope_names_line(
            ["eth-cs-bsc-2027", "eth-cs-msc-2027"], locale, _WHICH_ONE_LINES)
        _assert_joined(line, (ETH_MSC, ETH_BSC), locale)


def test_evidence_lines_all_locales():
    sources, _ = _climate_evidence("cool", countries=["CH"])
    city_names = ("Zurich (four-season, 14 programmes, all levels/fields)",
                  "Lausanne (four-season, 11 programmes, all levels/fields)")
    country_src = [Source(
        id="country:ch", url=None, title="Switzerland verified programmes",
        excerpt=("Switzerland: 25 verified programmes in total "
                 "(all levels and fields). Including: "
                 f"{ETH_MSC}; {ETH_BSC}."))]
    rank_src = [Source(
        id="ranking-overview:qs", url=None, title="QS 2027 top 100",
        excerpt=("QS 2027 top 100 (world ranks). Top 3: "
                 "#1 Massachusetts Institute of Technology; "
                 "#=2 Imperial College London; "
                 "#=2 Stanford University."))]
    for locale in LOCALES:
        line = evidence_cities_line(sources, locale)
        assert line is not None
        # City items are phrases ("Zurich (…, 14 programmes, …)"), so
        # the join shows at the item boundary: closing paren (full-
        # width in zh-CN) + separator.
        close = "）" if locale == "zh-CN" else ")"
        assert "Zurich" in line and "Lausanne" in line or (
            "苏黎世" in line and "洛桑" in line), (locale, line)
        assert f"{close}{SEP[locale]}" in line, (locale, line)
        for bad in FORBIDDEN[locale]:
            assert bad not in line, (locale, bad, line)
        line = country_evidence_line(country_src, locale)
        assert line is not None
        _assert_joined(line, (ETH_MSC, ETH_BSC), locale)
        line = ranking_overview_line(rank_src, locale)
        assert line is not None
        _assert_joined(line, ("Massachusetts Institute of Technology (#1)",
                              "Imperial College London (#=2)",
                              "Stanford University (#=2)"), locale)


def test_devil_conflict_line_all_locales():
    conflict = {"kind": "climate", "country": "CH", "wanted": "cool",
                "cities": [("Zurich", "four_seasons", 14),
                           ("Lausanne", "four_seasons", 11)],
                "count_difference": 3}
    for locale in LOCALES:
        line = devil_conflict_line(conflict, locale)
        if locale == "zh-CN":
            assert "苏黎世" in line and "洛桑" in line, (locale, line)
        else:
            assert "Zurich" in line and "Lausanne" in line, (locale, line)
        # City items are phrases; the join shows at the item boundary
        # (full-width closing paren in zh-CN).
        close = "）" if locale == "zh-CN" else ")"
        assert f"{close}{SEP[locale]}" in line, (locale, line)
        for bad in FORBIDDEN[locale]:
            assert bad not in line, (locale, bad, line)


def test_gap_state_joins_all_locales():
    lang_other = RuleResult(
        rule_id="ucl-language", status="UNKNOWN", detail="",
        evidence_ids=[], observed={},
        threshold={"other_requirements": ["German C1 (CEFR)",
                                         "French B2 (CEFR)"]})
    gcse = RuleResult(
        rule_id="ucl-gcse", status="UNKNOWN", detail="",
        evidence_ids=[], observed={"english": None, "maths": None},
        threshold=None)
    comps = RuleResult(
        rule_id="ucl-ielts-components", status="UNKNOWN", detail="",
        evidence_ids=[],
        observed={"listening": 7.0, "reading": 7.0, "writing": None,
                  "speaking": None},
        threshold={"listening": 6.5, "reading": 6.5, "writing": 6.0,
                   "speaking": 6.0})
    for locale in LOCALES:
        line = localised_gap_state(lang_other, locale, "Language")
        assert f"German C1 (CEFR){SEP[locale]}French B2 (CEFR)" in line, (locale, line)
        for bad in FORBIDDEN[locale]:
            assert bad not in line, (locale, bad, line)
        line = localised_gap_state(gcse, locale, "GCSE")
        # The two subjects, joined with the locale separator.
        assert SEP[locale] in line, (locale, line)
        for bad in FORBIDDEN[locale]:
            assert bad not in line, (locale, bad, line)
        line = localised_gap_state(comps, locale, "Language")
        assert SEP[locale] in line, (locale, line)
        for bad in FORBIDDEN[locale]:
            assert bad not in line, (locale, bad, line)


def test_ielts_fact_join_all_locales():
    from ai.assistant import _ielts_fact
    from app.data import PROGRAMS
    program = PROGRAMS["ucl-cs-bsc-2026"]
    for locale in LOCALES:
        fact = _ielts_fact(program, locale)
        assert fact is not None
        assert SEP[locale] in fact, (locale, fact)
        for bad in FORBIDDEN[locale]:
            assert bad not in fact, (locale, bad, fact)


# ---------------------------------------------------------------------------
# Frontend helper (node harness over compiled format.ts)
# ---------------------------------------------------------------------------

_NODE_HARNESS = r"""
const fmt = require(OUT + '/format.js');
const locales = JSON.parse(process.argv[2]);
const want = JSON.parse(process.argv[3]);
const names = ["ETH Zurich — MSc in Computer Science", "ETH Zurich — Bachelor of Science in Computer Science"];
const forbidden = {"en": ["、", "،"], "zh-CN": [", ", "،"], "es": ["、", "،"], "fr": ["、", "،"], "pt-BR": ["、", "،"], "ar": ["、", ", "]};
let fail = 0;
for (const loc of locales) {
  const got = fmt.joinList(names, loc);
  if (got !== names.join(want[loc])) {
    console.log('FAIL joinList ' + loc + ' -> ' + JSON.stringify(got));
    fail++;
  } else {
    console.log('PASS joinList ' + loc);
  }
  for (const bad of forbidden[loc]) {
    if (got.includes(bad)) {
      console.log('FAIL joinList ' + loc + ' leaks ' + JSON.stringify(bad) + ': ' + JSON.stringify(got));
      fail++;
    }
  }
  if (fmt.listSeparator(loc) !== want[loc]) {
    console.log('FAIL listSeparator ' + loc);
    fail++;
  }
}
if (fmt.listSeparator('xx') !== ', ') { console.log('FAIL listSeparator fallback'); fail++; }
if (fail) process.exit(1);
console.log('FRONTEND OK');
"""


def test_frontend_join_list_all_locales(tmp_path):
    outdir = tmp_path / "r24_w2_format"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/format.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r24_w2_harness.js"
    harness.write_text(
        _NODE_HARNESS.replace("OUT", repr(str(outdir))), encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"],
           "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness), json.dumps(list(LOCALES)),
         json.dumps(SEP, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout


# ---------------------------------------------------------------------------
# Locale key parity (no new keys were needed; counts must still match)
# ---------------------------------------------------------------------------

def test_locale_key_parity():
    key_sets = {}
    for locale in LOCALES:
        with open(ROOT / "frontend" / "messages" / f"{locale}.json",
                  encoding="utf-8") as f:
            key_sets[locale] = set(json.load(f))
    counts = {locale: len(keys) for locale, keys in key_sets.items()}
    assert len(set(counts.values())) == 1, counts
    for locale in LOCALES:
        assert key_sets[locale] == key_sets["en"], locale
