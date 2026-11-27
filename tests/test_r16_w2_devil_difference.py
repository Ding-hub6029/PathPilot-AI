"""Round 16, W2: devil's-advocate arithmetic — a wrong difference in a
verified-fact reply.

Browser re-test task 10 (2026-11-27) found the devil reply stating
"苏黎世有14个已核实项目、洛桑有11个……项目数量相差1项" — but
14 − 11 = 3, not 1. Root cause (model-written, not template):

- No template ever states a difference: ``grep 相差`` across
  backend/frontend/tests is empty, and the deterministic template line
  for this conflict only lists each city with its own count
  ("苏黎世（四季分明，14 个项目……）、洛桑（四季分明，11 个项目……）").
  The model received both counts (in the English conflict detail and
  in the climate evidence excerpts) and subtracted them itself — and
  got the subtraction wrong.
- The citation checker could not see it, for two independent reasons:
  (1) ``_numbers_in`` deliberately skips small bare integers, so the
  "1" in "相差1项" is never extracted for the numeric cross-check;
  (2) even an extracted "1" would pass as a substring of its own
  operands ("1" is in "14" and in "11"). The checker validates token
  presence, never arithmetic — a derived number is invisible to it.

Fix (generation site + checker enforcement):

- ``devil_conflicts`` now carries the engine-computed
  ``count_difference`` (top two city counts) on climate conflicts, and
  the model envelope carries it as a field plus a sentence in the
  detail; the devil prompt says to use ONLY that number, never to
  subtract in its head.
- ``check_model_output`` / ``_validate_chat_payload`` now take
  ``allowed_differences`` (the engine-computed pairwise differences
  for the turn). Any difference statement — in a claim, in the
  summary, or in an action explanation — whose number is not in that
  set is rejected and the caller falls back to the template.
  (Round 17 W2: the template now states the ENGINE-COMPUTED
  difference itself — ``相差3项`` for the audit case — so the two
  tests below that pinned "the template never states a difference"
  were updated to pin the correct difference instead. The template
  still never states a WRONG difference.) ``allowed_differences=None`` (explain.py
  and normal chat) keeps the old behaviour: no difference checking.

Audit profile (the verification profile for this round): China Gaokao,
undergraduate Computer Science, Gaokao 680/750, IELTS 7.0, budget GBP
50,000 per year, 2027 entry, overseas residency, preference
Switzerland (reason 环境优美), cool climate, university town, Zurich.
"""
from __future__ import annotations

import json

import httpx
import pytest

from ai.chat import (_devil_allowed_differences, _ensure_devil_sources,
                     _evidence_texts, _retrieve, _validate_chat_payload,
                     answer, devil_conflicts)
from ai.grounding import check_model_output, difference_errors
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
# Germany, warm wanted: Munich 17, Berlin 6, Heidelberg 1 — pairwise
# differences {11, 16, 5}, top-two difference 11.
GERMANY_PROFILE = {
    "countries": ["DE"],
    "climate": "warm",
    "level": "undergraduate",
}
GERMANY_MESSAGE = "Study in Germany. I want a warm climate."


def _openai_reply(payload_text: str) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"content": payload_text}}], "usage": {}})


def _mock_provider(monkeypatch, payload_text: str) -> ProviderAdapter:
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_reply(payload_text)

    return ProviderAdapter(_transport=httpx.MockTransport(handler))


def _evidence_for(profile: dict, message: str, locale: str = "zh-CN"):
    """(sources, evidence_texts, conflicts) exactly as answer() builds
    them for a devil turn."""
    from ai.chat import _devil_effective
    countries, wanted, _level, _budget = _devil_effective(profile, message)
    template, sources, pids = _retrieve(
        message, locale, countries=countries or None,
        climate_class=wanted, country_programmes=True)
    conflicts = devil_conflicts(profile, message)
    sources = _ensure_devil_sources(conflicts, sources)
    return sources, _evidence_texts(sources, pids), conflicts


def _devil_payload(claim_text: str, summary_text: str | None = None) -> dict:
    return {
        "summary": summary_text or "换个角度看，似乎值得再想想。",
        "claims": [{"text": claim_text, "kind": "fact", "rule_ids": [],
                    "evidence_ids": ["climate:zurich", "climate:lausanne"]}],
        "unknowns": [], "actions": [], "limitations": []}


# ---------------------------------------------------------------------------
# Engine-computed difference
# ---------------------------------------------------------------------------

def test_devil_climate_conflict_carries_engine_difference_14_11():
    conflicts = devil_conflicts(AUDIT_PROFILE, AUDIT_MESSAGE)
    assert [c["kind"] for c in conflicts] == ["climate"]
    (climate,) = conflicts
    assert [n for _c, _cls, n in climate["cities"]] == [14, 11]
    assert climate["count_difference"] == 3
    assert _devil_allowed_differences(conflicts) == frozenset({3})


def test_devil_template_states_engine_difference_14_11():
    """Round 17 W2 supersedes the Round 16 pin ("the template never
    states a difference"): the deterministic template now states the
    ENGINE-COMPUTED difference — 14 − 11 = 3 — so the comparison is
    not missing when the model is down. The sentence that was wrong
    still cannot come from here: only the engine's 3 may appear."""
    conflicts = devil_conflicts(AUDIT_PROFILE, AUDIT_MESSAGE)
    from ai.chat import _devil_template_result
    sources, _texts, _c = _evidence_for(AUDIT_PROFILE, AUDIT_MESSAGE)
    result = _devil_template_result(conflicts, sources, "zh-CN")
    joined = "\n".join(result["lines"])
    assert "14" in joined and "11" in joined
    assert "相差3项" in joined
    assert "相差1项" not in joined
    assert difference_errors(joined, frozenset({3})) == []


def test_second_case_germany_17_6_1_difference_is_11():
    conflicts = devil_conflicts(GERMANY_PROFILE, GERMANY_MESSAGE)
    assert [c["kind"] for c in conflicts] == ["climate"]
    (climate,) = conflicts
    assert [n for _c, _cls, n in climate["cities"]] == [17, 6, 1]
    assert climate["count_difference"] == 11
    assert _devil_allowed_differences(conflicts) == frozenset({11, 16, 5})


# ---------------------------------------------------------------------------
# Checker: the exact wrong sentence is rejected, the right one passes
# ---------------------------------------------------------------------------

def test_wrong_difference_1_in_claim_is_rejected():
    sources, texts, conflicts = _evidence_for(AUDIT_PROFILE, AUDIT_MESSAGE)
    allowed = _devil_allowed_differences(conflicts)
    payload = _devil_payload(
        "苏黎世有14个已核实项目、洛桑有11个，项目数量相差1项。")
    errors = _validate_chat_payload(payload, sources, texts, "zh-CN",
                                    allowed_differences=allowed)
    assert errors, "the 14/11 -> 'difference 1' payload must be rejected"
    assert any("difference of 1" in e for e in errors), errors


def test_wrong_difference_1_in_summary_is_rejected():
    """The wrong number hides in the summary just as easily as in a
    claim — the safety scan alone cannot see it."""
    sources, texts, conflicts = _evidence_for(AUDIT_PROFILE, AUDIT_MESSAGE)
    allowed = _devil_allowed_differences(conflicts)
    payload = _devil_payload(
        "苏黎世（四季分明，14 个项目）、洛桑（四季分明，11 个项目）。",
        summary_text="换个角度看：苏黎世有14个已核实项目、洛桑有11个，项目数量相差1项。")
    errors = _validate_chat_payload(payload, sources, texts, "zh-CN",
                                    allowed_differences=allowed)
    assert errors
    assert any("difference of 1" in e for e in errors), errors


def test_correct_difference_3_passes():
    sources, texts, conflicts = _evidence_for(AUDIT_PROFILE, AUDIT_MESSAGE)
    allowed = _devil_allowed_differences(conflicts)
    payload = _devil_payload(
        "苏黎世有14个已核实项目、洛桑有11个，项目数量相差3项。")
    errors = _validate_chat_payload(payload, sources, texts, "zh-CN",
                                    allowed_differences=allowed)
    assert errors == [], errors


def test_english_wrong_difference_rejected_correct_passes():
    sources, texts, conflicts = _evidence_for(AUDIT_PROFILE, AUDIT_MESSAGE)
    allowed = _devil_allowed_differences(conflicts)
    wrong = _devil_payload(
        "Zurich has 14 verified programmes, Lausanne has 11 — 1 more in Zurich.")
    wrong["claims"][0]["evidence_ids"] = ["climate:zurich", "climate:lausanne"]
    assert _validate_chat_payload(wrong, sources, texts, "en",
                                  allowed_differences=allowed)
    right = _devil_payload(
        "Zurich has 14 verified programmes, Lausanne has 11 — 3 more in Zurich.")
    right["claims"][0]["evidence_ids"] = ["climate:zurich", "climate:lausanne"]
    assert _validate_chat_payload(right, sources, texts, "en",
                                  allowed_differences=allowed) == []


def test_germany_wrong_1_rejected_correct_11_and_pairwise_5_pass():
    sources, texts, conflicts = _evidence_for(GERMANY_PROFILE, GERMANY_MESSAGE)
    allowed = _devil_allowed_differences(conflicts)
    assert allowed == frozenset({11, 16, 5})

    def payload(text: str) -> dict:
        return {
            "summary": "换个角度看，似乎值得再想想。",
            "claims": [{"text": text, "kind": "fact", "rule_ids": [],
                        "evidence_ids": ["climate:munich", "climate:berlin",
                                         "climate:heidelberg"]}],
            "unknowns": [], "actions": [], "limitations": []}

    assert _validate_chat_payload(
        payload("慕尼黑有17个已核实项目、柏林有6个，项目数量相差1项。"),
        sources, texts, "zh-CN", allowed_differences=allowed)
    assert _validate_chat_payload(
        payload("慕尼黑有17个已核实项目、柏林有6个，项目数量相差11项。"),
        sources, texts, "zh-CN", allowed_differences=allowed) == []
    # 6 − 1 = 5 is a real pairwise difference too (Berlin vs Heidelberg).
    assert _validate_chat_payload(
        payload("柏林有6个已核实项目、海德堡有1个，项目数量相差5项。"),
        sources, texts, "zh-CN", allowed_differences=allowed) == []


def test_difference_check_off_without_allowed_set():
    """Callers with no engine-computed diffs (explain.py, normal chat)
    keep the old behaviour: no difference checking. This documents the
    boundary — the devil path is the one that supplies the set."""
    check = check_model_output(
        _devil_payload("苏黎世有14个已核实项目、洛桑有11个，项目数量相差1项。"),
        allowed_evidence_ids={"climate:zurich", "climate:lausanne"},
        allowed_rule_ids=set(), rule_status={},
        evidence_texts={"climate:zurich": "Zurich: four-season climate. "
                        "Verified programmes in Zurich (all levels and "
                        "fields): 14.",
                        "climate:lausanne": "Lausanne: four-season climate. "
                        "Verified programmes in Lausanne (all levels and "
                        "fields): 11."},
        locale="zh-CN")
    assert check.valid, check.errors


# ---------------------------------------------------------------------------
# End to end: a mock model stating the wrong difference falls back to
# the template; stating the right one reaches the user as AI.
# ---------------------------------------------------------------------------

def test_mock_model_wrong_difference_falls_back_to_template(monkeypatch):
    payload = _devil_payload(
        "苏黎世有14个已核实项目、洛桑有11个，项目数量相差1项。",
        summary_text="换个角度看：苏黎世有14个已核实项目、洛桑有11个，项目数量相差1项。")
    provider = _mock_provider(monkeypatch, json.dumps(payload, ensure_ascii=False))
    result = answer(AUDIT_MESSAGE, locale="zh-CN", provider=provider,
                    mode="devil", profile=AUDIT_PROFILE)
    assert result["ai_status"] == "unavailable"
    assert result["model"] is None
    joined = "\n".join(result["lines"])
    # Round 17 W2: the fallback template itself now states the
    # engine-computed difference (3), never the model's wrong 1.
    assert "相差3项" in joined
    assert "相差1项" not in joined
    assert "14" in joined and "11" in joined


def test_mock_model_correct_difference_reaches_user(monkeypatch):
    payload = _devil_payload(
        "苏黎世有14个已核实项目、洛桑有11个，项目数量相差3项。",
        summary_text="换个角度看：苏黎世有14个已核实项目、洛桑有11个，项目数量相差3项。")
    provider = _mock_provider(monkeypatch, json.dumps(payload, ensure_ascii=False))
    result = answer(AUDIT_MESSAGE, locale="zh-CN", provider=provider,
                    mode="devil", profile=AUDIT_PROFILE)
    assert result["ai_status"] == "available", result
    joined = "\n".join(result["lines"])
    assert "相差3项" in joined
    assert "相差1项" not in joined


def test_model_envelope_carries_engine_difference(monkeypatch):
    """The model is handed the verified difference, not left to
    subtract: count_difference 3 is in the envelope for the audit
    profile."""
    captured: dict = {}
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["envelope"] = json.loads(body["messages"][-1]["content"])
        return _openai_reply(json.dumps(
            _devil_payload("苏黎世（四季分明，14 个项目）、洛桑（四季分明，11 个项目）。"),
            ensure_ascii=False))

    provider = ProviderAdapter(_transport=httpx.MockTransport(handler))
    answer(AUDIT_MESSAGE, locale="zh-CN", provider=provider,
           mode="devil", profile=AUDIT_PROFILE)
    conflicts = captured["envelope"]["devil_conflicts"]
    assert conflicts[0]["count_difference"] == 3
    # Round 17 W2: the English conflict line itself states the
    # difference ("3 more verified programmes"), so the envelope no
    # longer appends a second "Verified difference …" sentence.
    assert "3 more verified programmes" in conflicts[0]["detail"]
    assert "14 programmes" in conflicts[0]["detail"]
    assert "11 programmes" in conflicts[0]["detail"]
