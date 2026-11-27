"""Round 19, W1: devil reply sentence order + one disclosure line.

Nit 1 — the offline devil template (and the model-backed devil reply)
ended with the "next step: start the eligibility check" line AFTER the
engine-computed difference sentence, so the comparison answer
("苏黎世与洛桑相差3项。") sat mid-reply instead of closing it. The
difference sentence is now the LAST sentence: the trailing "next" line
is dropped when the last rendered line already closes with a
difference sentence. Dropping, not moving: leading with the
call-to-action ahead of the conclusion reads worse in zh-CN, and the
wizard CTA still reaches the user through the frontend's nextSteps
button. Only the last line is checked — with several conflicts the
difference sits mid-reply by construction (climate is listed first)
and reordering conflicts is out of scope, so the offer is kept there.

Nit 2 is frontend-only (CompassPet.tsx: the body pet.offline line is
suppressed on devil offline turns, which already carry
devil.offlineBoundary); no backend test covers it — see
/tmp/r19-w1-decisions.md.

Audit profile (same as Rounds 16/17): China Gaokao, undergraduate
Computer Science, Gaokao 680/750, IELTS 7.0, budget GBP 50,000,
2027 entry, overseas residency, preference Switzerland (reason
环境优美), cool climate, university-town environment, city Zurich.
"""
from __future__ import annotations

import json

import httpx
import pytest

from ai.assistant import _t
from ai.chat import (_DEVIL_T, _devil_difference_sentence,
                     _devil_template_result, _ensure_devil_sources,
                     _retrieve, answer, devil_conflict_line,
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
# Two countries, one climate conflict + one budget conflict: the
# difference is in the FIRST line, not the last.
MULTI_PROFILE = {
    "countries": ["CH", "GB"],
    "climate": "cool",
    "level": "undergraduate",
    "budget_amount": 100,
    "budget_currency": "GBP",
    "budget_period": "per_year",
}
LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]


def _no_key_provider(monkeypatch) -> ProviderAdapter:
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return ProviderAdapter()


def _mock_provider(monkeypatch, payload_text: str) -> ProviderAdapter:
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": payload_text}}], "usage": {}})

    return ProviderAdapter(_transport=httpx.MockTransport(handler))


def _devil_payload(claim_text: str, summary_text: str | None = None) -> dict:
    return {
        "summary": summary_text or "换个角度看，似乎值得再想想。",
        "claims": [{"text": claim_text, "kind": "fact", "rule_ids": [],
                    "evidence_ids": ["climate:zurich", "climate:lausanne"]}],
        "unknowns": [], "actions": [], "limitations": []}


def _template_for(profile: dict, message: str, locale: str):
    """(lines, conflicts) exactly as answer() builds them for a devil
    turn, via the deterministic template."""
    conflicts = devil_conflicts(profile, message)
    _t_, sources, pids = _retrieve(
        message, locale, countries=[c for c in profile.get("countries", [])]
        or None,
        climate_class=profile.get("climate"), country_programmes=True)
    sources = _ensure_devil_sources(conflicts, sources)
    result = _devil_template_result(conflicts, sources, locale)
    return result["lines"], conflicts


# ---------------------------------------------------------------------------
# Template: audit case ends with the difference sentence, all locales
# ---------------------------------------------------------------------------

def test_template_audit_zh_ends_with_difference(monkeypatch):
    r = answer(AUDIT_MESSAGE_ZH, "zh-CN",
               provider=_no_key_provider(monkeypatch),
               mode="devil", profile=AUDIT_PROFILE)
    assert r["ai_status"] == "unavailable"
    assert r["lines"][-1].endswith("苏黎世与洛桑相差3项。")
    assert _t("zh-CN", "next") not in r["lines"]
    assert stated_differences("\n".join(r["lines"])) == [3]


def test_template_audit_en_ends_with_difference(monkeypatch):
    r = answer(AUDIT_MESSAGE, "en",
               provider=_no_key_provider(monkeypatch),
               mode="devil", profile=AUDIT_PROFILE)
    assert r["lines"][-1].endswith(
        "Zurich has 3 more verified programmes than Lausanne.")
    assert _t("en", "next") not in r["lines"]


def test_template_audit_ends_with_difference_all_locales(monkeypatch):
    conflicts = devil_conflicts(AUDIT_PROFILE, AUDIT_MESSAGE)
    assert conflicts[0]["count_difference"] == 3
    for locale in LOCALES:
        r = answer(AUDIT_MESSAGE, locale,
                   provider=_no_key_provider(monkeypatch),
                   mode="devil", profile=AUDIT_PROFILE)
        diff = _devil_difference_sentence(conflicts[0], locale)
        assert diff, locale
        assert r["lines"][-1].endswith(diff), (locale, r["lines"])
        assert _t(locale, "next") not in r["lines"], locale


def test_template_germany_ends_with_difference_11(monkeypatch):
    r = answer(GERMANY_MESSAGE, "zh-CN",
               provider=_no_key_provider(monkeypatch),
               mode="devil", profile=GERMANY_PROFILE)
    assert r["lines"][-1].endswith("慕尼黑与柏林相差11项。")
    assert _t("zh-CN", "next") not in r["lines"]


# ---------------------------------------------------------------------------
# Template: the offer is kept where no difference closes the reply
# ---------------------------------------------------------------------------

def test_template_no_conflict_keeps_next(monkeypatch):
    profile = {"countries": ["CH"], "level": "undergraduate",
               "budget_amount": 50000, "budget_currency": "GBP",
               "budget_period": "per_year"}
    r = answer("Is Switzerland right for me?", "zh-CN",
               provider=_no_key_provider(monkeypatch),
               mode="devil", profile=profile)
    assert r["lines"][-1] == _t("zh-CN", "next")
    assert r["lines"][0] == _DEVIL_T["zh-CN"]["no_conflict"]


def test_template_tie_without_difference_keeps_next():
    tie = {"kind": "climate", "country": "CH", "wanted": "cool",
           "cities": [("Zurich", "four_seasons", 5),
                      ("Lausanne", "four_seasons", 5)],
           "count_difference": 0, "evidence_ids": [], "sources": []}
    result = _devil_template_result([tie], [], "zh-CN")
    assert "相差" not in "\n".join(result["lines"])
    assert result["lines"][-1] == _t("zh-CN", "next")


def test_template_multi_conflict_keeps_next():
    """Climate + budget: the difference is in the FIRST line, so no
    placement of "next" could make it last without reordering
    conflicts (out of scope) — the offer stays as the closing line."""
    conflicts = devil_conflicts(MULTI_PROFILE, AUDIT_MESSAGE)
    assert [c["kind"] for c in conflicts] == ["climate", "budget"]
    lines, _c = _template_for(MULTI_PROFILE, AUDIT_MESSAGE, "zh-CN")
    assert "相差3项" in lines[0]
    assert lines[-1] == _t("zh-CN", "next")


# ---------------------------------------------------------------------------
# Model path: a live devil reply also ends with the difference
# ---------------------------------------------------------------------------

def test_model_devil_reply_ends_with_difference_zh(monkeypatch):
    payload = _devil_payload(
        "苏黎世有14个已核实项目、洛桑有11个，项目数量相差3项。",
        summary_text="换个角度看：苏黎世有14个已核实项目、洛桑有11个，"
                     "项目数量相差3项。")
    provider = _mock_provider(
        monkeypatch, json.dumps(payload, ensure_ascii=False))
    result = answer(AUDIT_MESSAGE_ZH, locale="zh-CN", provider=provider,
                    mode="devil", profile=AUDIT_PROFILE)
    assert result["ai_status"] == "available", result
    assert result["lines"][-1].endswith("相差3项。")
    assert _t("zh-CN", "next") not in result["lines"]


def test_model_devil_reply_ends_with_difference_en(monkeypatch):
    payload = {
        "summary": "Another angle: Zurich has 14 verified programmes, "
                   "Lausanne has 11 — 3 more in Zurich.",
        "claims": [{"text": "Zurich has 14 verified programmes, "
                            "Lausanne has 11 — 3 more in Zurich.",
                    "kind": "fact", "rule_ids": [],
                    "evidence_ids": ["climate:zurich",
                                     "climate:lausanne"]}],
        "unknowns": [], "actions": [], "limitations": []}
    provider = _mock_provider(
        monkeypatch, json.dumps(payload, ensure_ascii=False))
    result = answer(AUDIT_MESSAGE, locale="en", provider=provider,
                    mode="devil", profile=AUDIT_PROFILE)
    assert result["ai_status"] == "available", result
    assert result["lines"][-1].endswith("3 more in Zurich.")
    assert _t("en", "next") not in result["lines"]


def test_model_devil_reply_without_difference_keeps_next(monkeypatch):
    """Control: a model devil reply that states the counts separately,
    with no difference sentence, still gets the eligibility-check
    offer as its closing line."""
    payload = _devil_payload(
        "苏黎世（四季分明，14 个项目）、洛桑（四季分明，11 个项目）。")
    provider = _mock_provider(
        monkeypatch, json.dumps(payload, ensure_ascii=False))
    result = answer(AUDIT_MESSAGE_ZH, locale="zh-CN", provider=provider,
                    mode="devil", profile=AUDIT_PROFILE)
    assert result["ai_status"] == "available", result
    assert result["lines"][-1] == _t("zh-CN", "next")
