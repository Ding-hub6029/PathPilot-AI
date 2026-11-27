"""Round 24 (W3): /results headline contradiction — "0 meet" next to top matches.

The audit profile (China Gaokao, UG, CS, 680/750, IELTS 7.0, GBP 50k/yr,
2027 entry, prefers Switzerland) rendered the bare counts line
"0 programme(s) meet all known requirements, ..." directly above the
programme cards, which a real user reads as a contradiction: if 0 meet
the requirements, why are 3 recommended?

Fix is copy + presentation only: when the zero is Gaokao-caused (no
university publishes a Gaokao-to-A-level conversion, so the academic
rule is UNKNOWN everywhere), the "What to do next" headline is replaced
by two short lines — what the 0 means, and that the top matches below
are the closest verified matches, not fully-met ones. Engine verdicts,
matching logic and MET/NOT_MET/UNKNOWN statuses are untouched.

Run from the project root:
    .venv/bin/python -m pytest tests/test_r24_w3_zero_headline.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESSAGES = ROOT / "frontend" / "messages"
LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]
PAGE = ROOT / "frontend" / "src" / "app" / "results" / "page.tsx"

ZERO = "results.nextSummaryZero"
CLOSEST = "results.nextSummaryZeroClosest"

# Per locale: (line-1 must contain, line-2 must contain). Line 1 explains
# the zero (no Gaokao conversion published -> academic unknown); line 2
# says the top matches are the closest verified ones, not fully-met ones.
LINE1_MARKERS = {
    "en": ["Gaokao", "conversion", "unknown"],
    "zh-CN": ["高考", "换算", "未知"],
    "es": ["Gaokao", "conversión", "desconocido"],
    "fr": ["Gaokao", "conversion", "inconnue"],
    "pt-BR": ["Gaokao", "conversão", "desconhecido"],
    "ar": ["الغاوكاو", "معادلة", "غير معروف"],
}
LINE2_MARKERS = {
    "en": ["closest verified matches", "not fully-met"],
    "zh-CN": ["最接近", "已核实", "全部符合"],
    "es": ["cercanas", "verificadas", "totalmente cumplidos"],
    "fr": ["plus proches", "vérifiées", "entièrement remplis"],
    "pt-BR": ["mais próximas", "verificadas", "totalmente atendidos"],
    "ar": ["أقرب", "الموثقة", "مستوفاة بالكامل"],
}


def _load(locale: str) -> dict:
    return json.loads((MESSAGES / f"{locale}.json").read_text(encoding="utf-8"))


def test_zero_headline_keys_exist_in_all_locales():
    """New keys exist, are non-empty, take no placeholders, and the
    locale key sets still match exactly across all 6 locales."""
    base = _load("en")
    assert ZERO in base and CLOSEST in base
    base_keys = set(base)
    for locale in LOCALES:
        data = _load(locale)
        assert set(data) == base_keys, locale
        for key in (ZERO, CLOSEST):
            value = data[key]
            assert isinstance(value, str) and value.strip(), (locale, key)
            assert "{" not in value and "}" not in value, (locale, key)


def test_zero_headline_explains_zero_in_every_locale():
    """Line 1 says what the 0 means; line 2 says the top matches are
    the closest verified matches, not fully-met ones — in all 6 locales."""
    for locale in LOCALES:
        data = _load(locale)
        line1, line2 = data[ZERO], data[CLOSEST]
        for marker in LINE1_MARKERS[locale]:
            assert marker in line1, (locale, "line1", marker, line1)
        for marker in LINE2_MARKERS[locale]:
            assert marker in line2, (locale, "line2", marker, line2)


def test_zero_headline_is_two_short_lines():
    """The rewritten headline is two short lines, not a paragraph."""
    for locale in LOCALES:
        data = _load(locale)
        for key in (ZERO, CLOSEST):
            assert len(data[key]) <= 200, (locale, key, len(data[key]))


def test_results_page_renders_zero_headline_instead_of_bare_count():
    """Wiring: for the Gaokao-caused zero the page renders the two
    explanation lines INSTEAD of the bare counts summary — the "0 meet"
    line never sits next to the recommendations unexplained. The gate
    is the same one as the zero-met explainer below (met 0 + Gaokao
    profile + an academic rule UNKNOWN); every other profile keeps the
    counts summary."""
    src = PAGE.read_text(encoding="utf-8")
    assert "const zeroGaokao = metCount === 0 && hasGaokao && academicUnknown;" in src
    assert "profile.gaokaoScore !== ''" in src
    assert "x.ruleId.endsWith('-academic') && x.status === 'UNKNOWN'" in src
    assert "t('results.nextSummaryZero')" in src
    assert "t('results.nextSummaryZeroClosest')" in src
    # True branch (explanation) comes before the else branch (bare counts).
    assert src.index("t('results.nextSummaryZero')") < src.index("tf('results.nextSummary'")
    assert "zeroGaokao ? (" in src


def test_engine_still_reports_zero_met_for_audit_profile():
    """Grounding: the audit profile really does yield met=0 with the
    academic rule UNKNOWN on all 5 Swiss UG computing programmes, so
    the new headline describes a real engine state — and the fix
    changed no verdict (all 5 stay overall UNKNOWN, fee MET)."""
    from app.schemas import StudentProfile
    from domain.eligibility import overall_status
    from domain.expansion_eval import evaluate_expansion

    progs = {p["id"]: p for p in json.loads(
        (ROOT / "data" / "expansions" / "expansion.json").read_text()
    )["programs"]}
    ids = ["eth-cs-bsc-2027", "eth-cse-bsc-2027", "epfl-cs-bsc-2027",
           "epfl-ai-bsc-2027", "zurich-informatics-bsc-2027"]
    profile = StudentProfile(
        application_track="undergraduate",
        undergrad_profile={"curriculum": "cn_gaokao", "gaokao_score": 680,
                           "gaokao_total": 750},
        language={"exam": "ielts", "overall": 7.0},
        budget={"amount": 50000, "currency": "GBP", "period": "per_year"},
    )
    met = 0
    for pid in ids:
        results = evaluate_expansion(profile, progs[pid])
        by_id = {r.rule_id: r.status for r in results}
        assert by_id["exp-academic"] == "UNKNOWN", pid
        assert overall_status(results) == "UNKNOWN", pid
        if all(r.status == "MET" for r in results):
            met += 1
    assert met == 0
