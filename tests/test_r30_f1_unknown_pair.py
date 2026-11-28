"""Round 30 F1 — the unknown pair on a guided turn whose answer was recorded.

Re-test 24 item a + re-test 25: in the Chinese preference wizard,
after the user answered environment / city / afterGrad / salary /
pressure / teaching, the guide repeated "这个我从已核实的数据里查不
到，不知道。可以开始资格检查，逐项核对你的背景。" even though the
value WAS recorded (the value bubble shows). Curl-verified: pref-chat
with 大学城 returned extracted {environment: campus} AND lines
[unknown, unknown_2, question].

Root cause, verified before the fix: the offline template comes from
``assistant_ask`` (backend/ai/assistant.py ``ask``, line 1392), which
knows nothing about the pref-chat extraction — a message that matches
no fee/IELTS/deadline/rank/country question gets the generic
``_T`` "unknown" + "unknown_2" pair — and ``_fallback_result``
(backend/ai/pref_chat.py) copied ``template["lines"][:2]`` verbatim,
replacing lines[0] only with a cities/country line when one applied.
So a guided turn whose deterministic extraction succeeded still
confessed "I can't find that".

Fix, backend only (backend/ai/pref_chat.py ``_fallback_result``):
when this turn's deterministic extraction recorded a preference
(``extracted`` non-empty) AND the template actually carried the
unknown pair, both pair lines are dropped — including a leftover
``unknown_2`` behind a cities line on a climate turn. A specific
unknown (``fee_unknown``, ``ask_ielts_unknown``, ...) is never a
member of the pair and stays; a cities/country line stays; and when
the extraction genuinely failed (``extracted`` == {}) the pair stays
exactly as before — that is the honest "I don't know" case. No
frontend change: a guided turn now answers with the question line
alone (a WHY turn with no lines at all — the WHY is the turn's
question), and the frontend already renders a turn with empty reply
lines as its offline line + question bubble (``prefTurnBubbles``
emits the question bubble "even with empty lines"). The Round 29 E1
re-localisation of stored unknown-pair lines is untouched — this
file never touches the frontend; test_r29_w1.py still pins it.

Run from the project root:
    .venv/bin/pytest tests/test_r30_f1_unknown_pair.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json

import httpx
import pytest

import app.ai_status_cache as ai_status_cache
from ai.assistant import _t
from ai.pref_chat import _question_line, pref_answer
from ai.provider import ProviderAdapter, reset_gateway_breaker
from app.ai_status_cache import reset_ai_status_cache

# The re-test's profile at the environment turn: Switzerland + cool
# known, environment (大学城) being answered next.
KNOWN_CH_COOL = {"countries": ["CH"], "climate": "cool"}
KNOWN_CH_COOL_CAMPUS = {"countries": ["CH"], "climate": "cool",
                        "environment": "campus"}
KNOWN_CH_COOL_CAMPUS_CITY = dict(KNOWN_CH_COOL_CAMPUS, city="苏黎世")
KNOWN_UPTO_AFTERGRAD = dict(KNOWN_CH_COOL_CAMPUS_CITY,
                            afterGrad="return_home")
KNOWN_UPTO_SALARY = dict(KNOWN_UPTO_AFTERGRAD, salary=80000,
                         salaryCurrency="CHF")
KNOWN_UPTO_PRESSURE = dict(KNOWN_UPTO_SALARY, pressure="low")

_ZH_UNKNOWN = "这个我从已核实的数据里查不到，不知道。"
_ZH_UNKNOWN2 = "可以开始资格检查，逐项核对你的背景。"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reset_ai_status_cache()
    reset_gateway_breaker()
    yield
    reset_ai_status_cache()
    reset_gateway_breaker()


def _no_key_provider(monkeypatch) -> ProviderAdapter:
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return ProviderAdapter()


def _mock_provider(monkeypatch, handler) -> ProviderAdapter:
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")
    return ProviderAdapter(_transport=httpx.MockTransport(handler))


def _assert_no_unknown_pair(lines: list[str]) -> None:
    for loc in ("en", "zh-CN", "es", "fr", "pt-BR", "ar"):
        assert _t(loc, "unknown") not in lines, loc
        assert _t(loc, "unknown_2") not in lines, loc


# ---------------------------------------------------------------------------
# (a) Guided turn, extraction succeeded: NO unknown-pair lines
# ---------------------------------------------------------------------------

# The six re-test guidance turns, in wizard order: (message,
# known-before, expected extracted, expected next question).
_GUIDED_TURNS = [
    ("大学城", KNOWN_CH_COOL, {"environment": "campus"}, "city"),
    ("苏黎世", KNOWN_CH_COOL_CAMPUS, {"city": "苏黎世"}, "afterGrad"),
    ("回国发展", KNOWN_CH_COOL_CAMPUS_CITY,
     {"afterGrad": "return_home"}, "salary"),
    ("80000 CHF", KNOWN_UPTO_AFTERGRAD,
     {"salary": {"amount": 80000, "currency": "CHF"}}, "pressure"),
    ("轻松一点", KNOWN_UPTO_SALARY, {"pressure": "low"}, "teaching"),
    ("小班研讨", KNOWN_UPTO_PRESSURE, {"teaching": "seminar"}, None),
]


@pytest.mark.parametrize(
    "message,known,extracted,next_q", _GUIDED_TURNS)
def test_guided_turn_with_extraction_emits_no_unknown_pair(
        monkeypatch, message, known, extracted, next_q):
    """The defect, turn by turn: the value is recorded, so the guide
    must not claim it could not be found. The reply is the next
    question alone (nothing at all on the done turn)."""
    r = pref_answer(message, "zh-CN", known=dict(known),
                    provider=_no_key_provider(monkeypatch))
    assert r["ai_status"] == "unavailable"
    assert r["extracted"] == extracted
    assert r["next_question"] == next_q
    assert r["done"] is (next_q is None)
    _assert_no_unknown_pair(r["lines"])
    assert len(r["lines"]) <= 3
    if next_q is not None:
        assert r["lines"] == [_question_line(next_q, "zh-CN")]
    else:
        assert r["lines"] == []


def test_curl_verified_case_environment_answer(monkeypatch):
    """The exact curl-verified case from the defect report: pref-chat
    with 大学城 used to return extracted {environment: campus} AND
    lines [unknown, unknown_2, question]. Now only the question."""
    r = pref_answer("大学城", "zh-CN", known=dict(KNOWN_CH_COOL),
                    provider=_no_key_provider(monkeypatch))
    assert r["extracted"] == {"environment": "campus"}
    assert r["lines"] == [_question_line("city", "zh-CN")]
    assert r["next_question"] == "city"


# ---------------------------------------------------------------------------
# (b) Guided turn, extraction genuinely failed: the pair STAYS
# ---------------------------------------------------------------------------

def test_failed_extraction_still_emits_unknown_pair_zh(monkeypatch):
    """A bare chat message matches nothing without a model: the
    generic unknown pair is the honest answer, plus the next
    question."""
    r = pref_answer("随便聊聊", "zh-CN", known={},
                    provider=_no_key_provider(monkeypatch))
    assert r["ai_status"] == "unavailable"
    assert r["extracted"] == {}
    assert r["lines"] == [_ZH_UNKNOWN, _ZH_UNKNOWN2,
                          _question_line("countries", "zh-CN")]
    assert r["next_question"] == "countries"


def test_failed_extraction_still_emits_unknown_pair_en(monkeypatch):
    r = pref_answer("随便聊聊", "en", known={},
                    provider=_no_key_provider(monkeypatch))
    assert r["extracted"] == {}
    assert r["lines"] == [_t("en", "unknown"), _t("en", "unknown_2"),
                          _question_line("countries", "en")]


def test_failed_extraction_mid_flow_still_emits_unknown_pair(monkeypatch):
    """Mid-flow, city being asked: a free question names no city, so
    the extraction fails and the pair stays (no cities line either —
    the turn is not climate-relevant, so the Round 7 / Round 28 D2
    evidence pin does not fire)."""
    r = pref_answer("苏黎世有什么好玩的？", "zh-CN",
                    known=dict(KNOWN_CH_COOL_CAMPUS),
                    provider=_no_key_provider(monkeypatch))
    assert r["extracted"] == {}
    assert r["lines"] == [_ZH_UNKNOWN, _ZH_UNKNOWN2,
                          _question_line("city", "zh-CN")]
    assert r["next_question"] == "city"


# ---------------------------------------------------------------------------
# (c) Neighbouring cases
# ---------------------------------------------------------------------------

def test_climate_turn_with_extraction_drops_leftover_unknown_2(monkeypatch):
    """The split-pair case: on a climate turn the cities line already
    replaced lines[0], but unknown_2 used to survive as lines[1].
    With the climate answer recorded, the cities evidence stays and
    the leftover unknown_2 goes."""
    r = pref_answer("凉爽", "zh-CN", known={"countries": ["CH"]},
                    provider=_no_key_provider(monkeypatch))
    assert r["extracted"] == {"climate": "cool"}
    assert r["next_question"] == "environment"
    assert "苏黎世" in r["lines"][0] and "洛桑" in r["lines"][0]
    _assert_no_unknown_pair(r["lines"])
    assert r["lines"][-1] == _question_line("environment", "zh-CN")


def test_why_turn_with_extraction_keeps_cities_line_only(monkeypatch):
    """New countries + a reason: the WHY is the turn's question, so
    no question line is appended — and with the extraction recorded
    the unknown pair goes, while the cities evidence line (Round 7:
    evidence already in hand) stays."""
    r = pref_answer("我想去瑞士，因为那边环境优美", "zh-CN", known={},
                    provider=_no_key_provider(monkeypatch))
    assert r["extracted"] == {"countries": ["CH"], "note": "那边环境优美"}
    assert r["why_followup"] == {"countries": ["CH"],
                                 "note": "那边环境优美"}
    assert len(r["lines"]) == 1
    assert "苏黎世" in r["lines"][0] and "洛桑" in r["lines"][0]
    _assert_no_unknown_pair(r["lines"])


def test_country_question_with_extraction_keeps_country_line(monkeypatch):
    """A non-pair template line is never removed by the fix: a
    country question that also records the country keeps its country
    line (and its next-step line) verbatim, with no unknown lines."""
    r = pref_answer("瑞士有哪些好学校？", "zh-CN", known={},
                    provider=_no_key_provider(monkeypatch))
    assert r["extracted"] == {"countries": ["CH"]}
    assert "瑞士已核实的学校" in r["lines"][0]
    assert "25 个已验证项目" in r["lines"][0]
    _assert_no_unknown_pair(r["lines"])


def _model_echoes_unknown_handler(request: httpx.Request) -> httpx.Response:
    """A well-formed mock model whose own narration IS the unknown
    line (same shape as test_r26_w1.py's _empty_extraction_handler,
    summary swapped). The model path must return it verbatim — the
    F1 filter lives in the offline fallback only."""
    payload = {
        "summary": _ZH_UNKNOWN,
        "claims": [{"text": "没有已核实的数据可以引用。",
                    "kind": "limitation", "rule_ids": [],
                    "evidence_ids": []}],
        "unknowns": [], "actions": [], "limitations": [],
        "extracted": {}, "next_question": "teaching"}
    return httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps(
            payload, ensure_ascii=False)}}],
        "usage": {}})


def test_model_path_turn_untouched(monkeypatch):
    """A free question mid-flow takes the model path (not a guided
    answer, so no deterministic route). A validated model reply is
    returned verbatim — even when its own narration is the unknown
    line, it is the model's words, not the offline template, and the
    F1 filter must not rewrite it (Round 29 E1 model veto)."""
    provider = _mock_provider(monkeypatch, _model_echoes_unknown_handler)
    r = pref_answer("瑞士有哪些好学校？", "zh-CN",
                    known=dict(KNOWN_UPTO_PRESSURE), provider=provider)
    assert r["ai_status"] == "available"
    assert r["extracted"] == {}
    assert r["lines"][0] == _ZH_UNKNOWN
    assert r["lines"][-1] == _question_line("teaching", "zh-CN")
    assert r["next_question"] == "teaching"
