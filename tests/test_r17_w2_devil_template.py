"""Round 17, W2: the offline devil template states the engine-computed
difference.

Live re-test task 11 found the devil reply as a labelled template
listing 14 and 11 with NO difference stated at all — no wrong
"相差1项", but also no correct "相差3项". The model was offline the
whole run, so the checker path was never exercised live and the
comparison answer was simply missing in the common offline case.

Fix (this round): the climate conflict line
(``devil_conflict_line`` in backend/ai/chat.py, which the template
``_devil_template_result`` renders) appends a localised sentence
stating the engine-computed ``count_difference`` — the top-two
difference set in ``devil_conflicts`` — naming the two largest
cities. The template never subtracts: it renders
``conflict["count_difference"]`` verbatim. Stating it is consistent
with the template's role (it already lists the verified counts 14
and 11, fees, and other engine numbers); it is not numbers-light.

Audit profile (same as Round 16): China Gaokao, undergraduate
Computer Science, Gaokao 680/750, IELTS 7.0, budget GBP 50,000,
2027 entry, overseas residency, preference Switzerland (reason
环境优美), cool climate, university-town environment, city Zurich.
Second case: Germany, warm wanted — Munich 17, Berlin 6,
Heidelberg 1, top-two difference 11.
"""
from __future__ import annotations

import json

import httpx
import pytest

from ai.chat import (_devil_template_result, answer, devil_conflict_line,
                     devil_conflicts)
from ai.grounding import stated_differences
from ai.provider import ProviderAdapter

AUDIT_PROFILE = {
    "countries": ["CH"],
    "climate": "cool",
    "level": "undergraduate",
    "budget_amount": 50000,
    "budget_currency": "GBP",
    "budget_period": "per_year",
    "city": "Zurich",
}
AUDIT_MESSAGE = "Is Switzerland right for me? I want a cool climate."
AUDIT_MESSAGE_ZH = "瑞士适合我吗？我想要凉爽的气候。"
GERMANY_PROFILE = {
    "countries": ["DE"],
    "climate": "warm",
    "level": "undergraduate",
}
GERMANY_MESSAGE = "Study in Germany. I want a warm climate."
LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]


def _no_key_provider(monkeypatch) -> ProviderAdapter:
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return ProviderAdapter()


def _template_lines(monkeypatch, message, locale, profile):
    r = answer(message, locale, provider=_no_key_provider(monkeypatch),
               mode="devil", profile=profile)
    assert r["ai_status"] == "unavailable"
    assert r["model"] is None
    assert r["mode"] == "devil"
    return r


# ---------------------------------------------------------------------------
# Audit case: the offline template states 相差3项 / 3 more
# ---------------------------------------------------------------------------

def test_template_audit_zh_states_difference_3(monkeypatch):
    r = _template_lines(monkeypatch, AUDIT_MESSAGE_ZH, "zh-CN", AUDIT_PROFILE)
    joined = "\n".join(r["lines"])
    assert "相差3项" in joined
    assert "相差1项" not in joined
    assert "苏黎世" in joined and "洛桑" in joined
    assert stated_differences(joined) == [3]
    assert len(r["lines"]) <= 3


def test_template_audit_en_states_difference_3(monkeypatch):
    r = _template_lines(monkeypatch, AUDIT_MESSAGE, "en", AUDIT_PROFILE)
    joined = "\n".join(r["lines"])
    assert "Zurich has 3 more verified programmes than Lausanne" in joined
    assert stated_differences(joined) == [3]
    assert len(r["lines"]) <= 3


def test_template_germany_states_difference_11(monkeypatch):
    r = _template_lines(monkeypatch, GERMANY_MESSAGE, "zh-CN", GERMANY_PROFILE)
    joined = "\n".join(r["lines"])
    assert "相差11项" in joined
    assert "慕尼黑" in joined and "柏林" in joined
    assert stated_differences(joined) == [11]
    r = _template_lines(monkeypatch, GERMANY_MESSAGE, "en", GERMANY_PROFILE)
    joined = "\n".join(r["lines"])
    assert "Munich has 11 more verified programmes than Berlin" in joined
    assert stated_differences(joined) == [11]


# ---------------------------------------------------------------------------
# All six locales: the difference sentence is localised, not hardcoded
# Chinese, and names the localised top-two cities.
# ---------------------------------------------------------------------------

def test_conflict_line_difference_all_locales():
    conflicts = devil_conflicts(AUDIT_PROFILE, AUDIT_MESSAGE)
    assert conflicts[0]["count_difference"] == 3
    # (locale, top-two city names as rendered, difference fragment)
    expected = {
        "en": (("Zurich", "Lausanne"), "3 more verified programmes"),
        "zh-CN": (("苏黎世", "洛桑"), "相差3项"),
        "es": (("Zurich", "Lausanne"), "3 programas verificados más"),
        "fr": (("Zurich", "Lausanne"), "3 programmes vérifiés de plus"),
        "pt-BR": (("Zurich", "Lausanne"), "3 programas verificados a mais"),
        "ar": (("Zurich", "Lausanne"), "3 برامج موثّقة أكثر"),
    }
    for locale in LOCALES:
        line = devil_conflict_line(conflicts[0], locale)
        names, fragment = expected[locale]
        for name in names:
            assert name in line, (locale, line)
        assert fragment in line, (locale, line)
        if locale == "zh-CN":
            assert "Zurich" not in line and "Lausanne" not in line


def test_conflict_line_difference_germany_all_locales():
    conflicts = devil_conflicts(GERMANY_PROFILE, GERMANY_MESSAGE)
    assert conflicts[0]["count_difference"] == 11
    for locale in LOCALES:
        line = devil_conflict_line(conflicts[0], locale)
        assert "11" in line, (locale, line)
        # Only the top-two difference is stated (Munich vs Berlin);
        # the other pairwise differences (16, 5) stay model-only.
        assert "16" not in line and " 5 " not in line, (locale, line)


# ---------------------------------------------------------------------------
# Guards: no difference is stated when the engine supplied none
# ---------------------------------------------------------------------------

def test_no_sentence_without_count_difference():
    conflict = {"kind": "climate", "country": "CH", "wanted": "cool",
                "cities": [("Zurich", "four_seasons", 14),
                           ("Lausanne", "four_seasons", 11)]}
    for locale in LOCALES:
        line = devil_conflict_line(conflict, locale)
        assert "相差" not in line and " more " not in line, (locale, line)


def test_no_sentence_for_zero_tie_or_single_city():
    tie = {"kind": "climate", "country": "CH", "wanted": "cool",
           "cities": [("Zurich", "four_seasons", 5),
                      ("Lausanne", "four_seasons", 5)],
           "count_difference": 0}
    assert "相差" not in devil_conflict_line(tie, "zh-CN")
    assert " more " not in devil_conflict_line(tie, "en")
    single = {"kind": "climate", "country": "CH", "wanted": "cool",
              "cities": [("Zurich", "four_seasons", 14)],
              "count_difference": 14}
    assert "相差" not in devil_conflict_line(single, "zh-CN")


def test_template_uses_engine_field_verbatim_never_subtracts():
    """The template renders conflict["count_difference"] as-is: with
    a hand-built field of 7 over cities 14/11 it states 7, proving
    no subtraction happens in the template. In production the engine
    is the sole producer of the field (devil_conflicts sets it from
    the same listed cities), so a hand-built mismatch cannot occur
    through the real path — this pins the template's contract, not
    the engine's arithmetic (covered by the engine tests)."""
    conflict = {"kind": "climate", "country": "CH", "wanted": "cool",
                "cities": [("Zurich", "four_seasons", 14),
                           ("Lausanne", "four_seasons", 11)],
                "count_difference": 7}
    assert "相差7项" in devil_conflict_line(conflict, "zh-CN")
    assert "7 more verified programmes" in devil_conflict_line(conflict, "en")


def test_non_climate_conflict_lines_gain_no_difference():
    no_prog = {"kind": "no_programmes", "country": "FR",
               "level": "undergraduate"}
    assert "相差" not in devil_conflict_line(no_prog, "zh-CN")
    assert " more " not in devil_conflict_line(no_prog, "en")
    budget_conflicts = devil_conflicts(
        {"countries": ["GB"], "level": "undergraduate",
         "budget_amount": 25000, "budget_currency": "GBP",
         "budget_period": "per_year"},
        "Recommend an undergraduate programme in the UK.")
    assert [c["kind"] for c in budget_conflicts] == ["budget"]
    assert "相差" not in devil_conflict_line(budget_conflicts[0], "zh-CN")
    assert " more " not in devil_conflict_line(budget_conflicts[0], "en")


# ---------------------------------------------------------------------------
# End to end: gateway down -> template, with the correct difference
# ---------------------------------------------------------------------------

def test_gateway_down_template_states_correct_difference_en(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    provider = ProviderAdapter(_transport=httpx.MockTransport(handler))
    r = answer(AUDIT_MESSAGE, "en", provider=provider,
               mode="devil", profile=AUDIT_PROFILE)
    assert r["ai_status"] == "unavailable"
    joined = "\n".join(r["lines"])
    assert "Zurich has 3 more verified programmes than Lausanne" in joined
    assert stated_differences(joined) == [3]
