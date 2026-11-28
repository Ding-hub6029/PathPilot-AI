"""Round 29 W2 — backend: E3 climate wording on the model path +
E4 deterministic guided pref answers (re-test 23 items b/c).

E3 — re-test 23 item b (PARTIAL FAIL): the guide-area climate answer
must carry BOTH sentences (no-match + preference-only) and the cities
line with programme counts in BOTH languages on EVERY path. The
offline/template path already does (frontend ``localisedFallbackLines``
re-renders the R28 D2 structured block), but the model path dropped
the preference-only sentence and the cities line (round 2 zh /
round 4: the no-match sentence is there, the preference-only sentence
and the cities line are not). Fix: ``pref_answer`` post-validates
model-path climate turns (``_pin_climate_no_match``, the R26 W3
precedent) with a deterministic line from ``_DEVIL_T``
(``climate_no_match_line`` in ai.chat), and attaches the R28 D2
structured block (``evidence_cities`` + ``climate_wanted``) on a
model-path climate turn too. Every reply also carries
``climate_turn`` (True exactly on a climate turn) — the frontend's
dedupe signal for the cities line, which is still placed on the
countries turn as well (R28 D2 evidence-in-hand pin).

E4 — re-test 23 item c (FAIL): the first preference answer took
13-30 s on the model path (gateway slow) vs ~1-2 s offline. Fix: a
guided answer — a message that answers the FIRST still-missing
preference and is not itself a question — takes the deterministic
route (extraction + template, no model call) in engine time, in
every gateway state. A short model budget is NOT the fix: a healthy
gateway answers a tiny chat in ~3.4 s (provider.py probe comment,
measured 2026-11-27), so no budget under ~2 s could ever use the
model when healthy, and any budget over ~2 s breaks the ~2 s bound
when the gateway is slow — while httpx MockTransport ignores
timeouts, so a budget could not even be verified honestly in tests.
The model is attempted only for non-guided turns (a free question
mid-flow, a greeting, an answer the deterministic extraction cannot
read). Trade-off: a guided turn no longer gets the model's in-lines
acknowledgement of the user's reason — the reason still rides in
``extracted.note`` and ``why_followup`` (the offline path already
showed the same wording in re-test 23 round 1).

Run from the project root:
    .venv/bin/pytest tests/test_r29_w2.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import time

import httpx
import pytest

from ai.chat import (_CLIMATE_PREFERENCE_ONLY, _DEVIL_T,
                     _climate_evidence, climate_no_match_line,
                     evidence_cities_items)
from ai.pref_chat import (_pin_climate_no_match, _question_line,
                          pref_answer)
from ai.provider import ProviderAdapter, reset_gateway_breaker
from app.ai_status_cache import reset_ai_status_cache

LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]
_ITEMS = [
    {"city": "Zurich", "climate": "four_seasons", "count": 14},
    {"city": "Lausanne", "climate": "four_seasons", "count": 11},
]
_PREF_ONLY_ZH = "气候只是偏好，不影响资格，只影响排序。"
_PREF_ONLY_EN = ("Climate is only a preference — it never decides "
                 "eligibility, it only orders results.")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reset_ai_status_cache()
    reset_gateway_breaker()
    yield
    reset_ai_status_cache()
    reset_gateway_breaker()


def _mock_provider(monkeypatch, handler) -> ProviderAdapter:
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")
    return ProviderAdapter(_transport=httpx.MockTransport(handler))


def _openai_reply(payload_text: str) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"content": payload_text}}], "usage": {}})


def _round2_like_handler(payload: dict):
    """A model reply shaped like the re-test 23 round-2 climate
    answer: it states the no-match, but drops the preference-only
    sentence and the cities line with programme counts."""
    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_reply(json.dumps(payload, ensure_ascii=False))
    return handler


def _slow_handler(calls: dict, delay_s: float = 5.0):
    """A gateway that answers only after ``delay_s`` — a guided turn
    must never wait on it (deterministic route), so the delay is
    only ever paid if the code wrongly attempts the model."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        time.sleep(delay_s)
        payload = {
            "summary": "明白，我记下了。",
            "claims": [{"text": "没有已核实的数据可以引用。",
                        "kind": "limitation", "rule_ids": [],
                        "evidence_ids": []}],
            "unknowns": [], "actions": [], "limitations": [],
            "extracted": {}, "next_question": None}
        return _openai_reply(json.dumps(payload, ensure_ascii=False))
    return handler


# ---------------------------------------------------------------------------
# E3 — deterministic climate line (unit)
# ---------------------------------------------------------------------------

def test_preference_only_sentences_match_devil_template_all_locales():
    """No invented translations: the preference-only sentence in
    every locale is verbatim the tail of the backend devil climate
    template (the same pin test_r27_w5 holds for the frontend key)."""
    for loc in LOCALES:
        assert _CLIMATE_PREFERENCE_ONLY[loc] in _DEVIL_T[loc]["climate"], loc


def test_climate_no_match_line_en_exact():
    sources, _ = _climate_evidence("cool", countries=["CH"])
    assert climate_no_match_line("cool", "CH", sources, "en") == (
        "You want a cool climate, but in Switzerland the verified "
        "data lists Zurich (four-season, 14 programmes, all levels/"
        "fields), Lausanne (four-season, 11 programmes, all levels/"
        "fields) — no cool-class city there. Climate is only a "
        "preference — it never decides eligibility, it only orders "
        "results.")


def test_climate_no_match_line_zh_exact():
    sources, _ = _climate_evidence("cool", countries=["CH"])
    assert climate_no_match_line("cool", "CH", sources, "zh-CN") == (
        "你想要凉爽气候，但已核实的数据里，瑞士列出的城市是苏黎世"
        "（四季分明，14 个项目，全部学位/方向）、洛桑（四季分明，"
        "11 个项目，全部学位/方向），其中没有凉爽气候的城市。气候"
        "只是偏好，不影响资格，只影响排序。")


def test_climate_no_match_line_none_when_no_no_match():
    sources, _ = _climate_evidence("cool", countries=["CH"])
    # A listed city HAS the wanted class: no correction to state.
    assert climate_no_match_line("four_seasons", "CH", sources, "en") is None
    # No wanted class / no country / no evidence: nothing to pin.
    assert climate_no_match_line(None, "CH", sources, "en") is None
    assert climate_no_match_line("cool", None, sources, "en") is None
    assert climate_no_match_line("cool", "CH", [], "en") is None
    assert climate_no_match_line("arctic", "CH", sources, "en") is None


def test_pin_leaves_complete_lines_unchanged():
    """When the lines already carry BOTH the preference-only sentence
    and the cities line, the post-validation is a no-op."""
    sources, _ = _climate_evidence("cool", countries=["CH"])
    from ai.chat import evidence_cities_line
    lines = [evidence_cities_line(sources, "en"),
             _PREF_ONLY_EN,
             _question_line("environment", "en")]
    assert _pin_climate_no_match(
        lines, wanted="cool", country="CH", sources=sources, locale="en",
        next_question="environment", why=None) == lines


# ---------------------------------------------------------------------------
# E3 — model-path climate turn (re-test 23 round 2/4 shape)
# ---------------------------------------------------------------------------

_ZH_MODEL_PAYLOAD = {
    "summary": "你说的“凉爽”，记下了；你也一直提到“环境优美”这个理由。",
    "claims": [{"text": "瑞士目前的证据里，苏黎世和洛桑都是四季型气候，"
                        "没有“凉爽”这一类城市。",
                "kind": "fact", "rule_ids": [],
                "evidence_ids": ["climate:zurich", "climate:lausanne"]}],
    "unknowns": [], "actions": [], "limitations": [],
    "extracted": {"climate": "cool"}, "next_question": "environment",
}
_EN_MODEL_PAYLOAD = {
    "summary": "Got it — noted you like it cool.",
    "claims": [{"text": "Zurich and Lausanne are both four-season, "
                        "with no cool-class city in Switzerland.",
                "kind": "fact", "rule_ids": [],
                "evidence_ids": ["climate:zurich", "climate:lausanne"]}],
    "unknowns": [], "actions": [], "limitations": [],
    "extracted": {"climate": "cool"}, "next_question": "environment",
}


def test_model_climate_turn_zh_carries_both_sentences_and_cities(monkeypatch):
    """The re-test 23 round-2 shape, model-led: the stub drops the
    preference-only sentence and the cities line, exactly as the
    live model did. The final lines must carry both sentences and
    the cities line with programme counts, in zh."""
    provider = _mock_provider(monkeypatch,
                              _round2_like_handler(_ZH_MODEL_PAYLOAD))
    r = pref_answer("我喜欢很冷的地方", "zh-CN",
                    known={"countries": ["CH"], "climate": "cool"},
                    provider=provider)
    assert r["ai_status"] == "available"
    joined = "\n".join(r["lines"])
    assert _PREF_ONLY_ZH in joined
    assert "苏黎世" in joined and "洛桑" in joined
    assert "14" in joined and "11" in joined
    assert "Edinburgh" not in joined and "爱丁堡" not in joined
    assert len(r["lines"]) <= 3
    assert r["lines"][-1] == _question_line("environment", "zh-CN")
    assert r["next_question"] == "environment"
    assert r["climate_turn"] is True
    assert r["evidence_cities"] == _ITEMS
    assert r["climate_wanted"] == "cool"


def test_model_climate_turn_en_carries_both_sentences_and_cities(monkeypatch):
    """Same turn in English: both sentences + cities line with
    counts, in en."""
    provider = _mock_provider(monkeypatch,
                              _round2_like_handler(_EN_MODEL_PAYLOAD))
    r = pref_answer("I like cold places", "en",
                    known={"countries": ["CH"], "climate": "cool"},
                    provider=provider)
    assert r["ai_status"] == "available"
    joined = "\n".join(r["lines"])
    assert _PREF_ONLY_EN in joined
    assert "Zurich" in joined and "Lausanne" in joined
    assert "14" in joined and "11" in joined
    assert "Edinburgh" not in joined
    assert len(r["lines"]) <= 3
    assert r["lines"][-1] == _question_line("environment", "en")
    assert r["climate_turn"] is True
    assert r["evidence_cities"] == _ITEMS
    assert r["climate_wanted"] == "cool"


def test_model_climate_match_turn_pins_nothing_but_attaches_block(monkeypatch):
    """Match case: a listed city HAS the wanted class, so no
    no-match line is forced — but the climate turn still carries
    the structured block for the frontend."""
    payload = {
        "summary": "明白，四季分明记下了。",
        "claims": [{"text": "苏黎世和洛桑都是四季分明。",
                    "kind": "fact", "rule_ids": [],
                    "evidence_ids": ["climate:zurich",
                                     "climate:lausanne"]}],
        "unknowns": [], "actions": [], "limitations": [],
        "extracted": {"climate": "four_seasons"},
        "next_question": "environment",
    }
    provider = _mock_provider(monkeypatch, _round2_like_handler(payload))
    r = pref_answer("我喜欢四季分明的地方", "zh-CN",
                    known={"countries": ["CH"],
                           "climate": "four_seasons"},
                    provider=provider)
    assert r["ai_status"] == "available"
    assert r["climate_turn"] is True
    assert r["evidence_cities"] == _ITEMS
    assert r["climate_wanted"] == "four_seasons"
    # No no-match sentence was invented for a match.
    assert "其中没有" not in "\n".join(r["lines"])


# ---------------------------------------------------------------------------
# E3 — climate_turn marker (frontend dedupe signal)
# ---------------------------------------------------------------------------

def test_climate_turn_marker_offline_turns(monkeypatch):
    """The marker on the fallback path: False on the countries turn
    (which still carries the cities line + block per the R28 D2
    evidence-in-hand pin — the frontend dedupes by this marker),
    True on the climate turn, False again on the next turn."""
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    provider = ProviderAdapter()
    countries = pref_answer("我想去瑞士，因为那边环境优美", "zh-CN",
                            known={}, provider=provider)
    assert countries["climate_turn"] is False
    assert countries["evidence_cities"] == _ITEMS
    assert countries["climate_wanted"] is None
    assert countries["next_question"] == "climate"

    climate = pref_answer("凉爽", "zh-CN", known={"countries": ["CH"]},
                          provider=provider)
    assert climate["climate_turn"] is True
    assert climate["evidence_cities"] == _ITEMS
    assert climate["climate_wanted"] == "cool"
    assert climate["next_question"] == "environment"

    later = pref_answer("大学城", "zh-CN",
                        known={"countries": ["CH"], "climate": "cool"},
                        provider=provider)
    assert later["climate_turn"] is False
    assert "evidence_cities" not in later
    assert "climate_wanted" not in later


# ---------------------------------------------------------------------------
# E4 — guided answers never touch a slow gateway
# ---------------------------------------------------------------------------

def test_guided_countries_turn_ignores_slow_model(monkeypatch):
    """Re-test 23 item c, first turn: Switzerland with a gateway
    that answers only after 5 s. The guided route must return in
    bounded time without calling the model at all."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _slow_handler(calls))
    started = time.monotonic()
    r = pref_answer("我想去瑞士，因为那边环境优美", "zh-CN", known={},
                    provider=provider)
    elapsed = time.monotonic() - started
    assert elapsed < 2.0, f"guided countries turn took {elapsed:.1f}s"
    assert calls["n"] == 0, "guided turn must not call the model"
    assert r["ai_status"] == "unavailable"
    assert r["extracted"]["countries"] == ["CH"]
    assert "环境优美" in r["extracted"]["note"]
    assert r["why_followup"] == {"countries": ["CH"],
                                 "note": "那边环境优美"}
    assert r["next_question"] == "climate"
    assert r["done"] is False
    assert len(r["lines"]) <= 3


def test_guided_climate_turn_ignores_slow_model(monkeypatch):
    """Second turn, same slow gateway: the climate answer is
    extracted deterministically and the question advances."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _slow_handler(calls))
    started = time.monotonic()
    r = pref_answer("凉爽", "zh-CN", known={"countries": ["CH"]},
                    provider=provider)
    elapsed = time.monotonic() - started
    assert elapsed < 2.0, f"guided climate turn took {elapsed:.1f}s"
    assert calls["n"] == 0
    assert r["ai_status"] == "unavailable"
    assert r["extracted"] == {"climate": "cool"}
    assert r["next_question"] == "environment"
    assert r["climate_turn"] is True


_GUIDED_SEQUENCE = [
    # (message, known-before, expected extracted, next_question)
    ("大学城",
     {"countries": ["CH"], "climate": "cool"},
     {"environment": "campus"}, "city"),
    ("苏黎世",
     {"countries": ["CH"], "climate": "cool", "environment": "campus"},
     {"city": "苏黎世"}, "afterGrad"),
    ("毕业后想留下来",
     {"countries": ["CH"], "climate": "cool", "environment": "campus",
      "city": "Zurich"},
     {"afterGrad": "stay"}, "salary"),
    ("80000 CHF",
     {"countries": ["CH"], "climate": "cool", "environment": "campus",
      "city": "Zurich", "afterGrad": "stay"},
     {"salary": {"amount": 80000, "currency": "CHF"}}, "pressure"),
    ("轻松一点就好",
     {"countries": ["CH"], "climate": "cool", "environment": "campus",
      "city": "Zurich", "afterGrad": "stay", "salary": 60000,
      "salaryCurrency": "GBP"},
     {"pressure": "low"}, "teaching"),
    ("喜欢动手实践",
     {"countries": ["CH"], "climate": "cool", "environment": "campus",
      "city": "Zurich", "afterGrad": "stay", "salary": 60000,
      "salaryCurrency": "GBP", "pressure": "low"},
     {"teaching": "hands_on"}, None),
]


def test_guided_sequence_all_eight_answers_ignore_slow_model(monkeypatch):
    """The remaining six guided answers, each against the 5 s-slow
    gateway: every turn lands in bounded time, extracts correctly,
    and advances — including the final turn, which completes the
    wizard (done, next_question None)."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _slow_handler(calls))
    for message, known, want_extracted, want_next in _GUIDED_SEQUENCE:
        started = time.monotonic()
        r = pref_answer(message, "zh-CN", known=dict(known),
                        provider=provider)
        elapsed = time.monotonic() - started
        assert elapsed < 2.0, f"{message!r} took {elapsed:.1f}s"
        assert r["extracted"] == want_extracted, message
        assert r["next_question"] == want_next, message
        assert r["ai_status"] == "unavailable"
        assert len(r["lines"]) <= 3
    assert calls["n"] == 0, "no guided turn may call the model"
    assert r["done"] is True


def test_free_question_mid_flow_still_uses_model(monkeypatch):
    """The guided route must not swallow a free question: "瑞士有
    哪些好学校？" names a country but IS a question, so the model
    path still runs (fast mock) and answers it."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        payload = {
            "summary": "瑞士有苏黎世和洛桑等城市。",
            "claims": [{"text": "苏黎世：四季分明。",
                        "kind": "fact", "rule_ids": [],
                        "evidence_ids": ["climate:zurich"]}],
            "unknowns": [], "actions": [], "limitations": [],
            "extracted": {}, "next_question": "climate"}
        return _openai_reply(json.dumps(payload, ensure_ascii=False))

    provider = _mock_provider(monkeypatch, handler)
    r = pref_answer("瑞士有哪些好学校？", "zh-CN", known={},
                    provider=provider)
    assert calls["n"] == 1
    assert r["ai_status"] == "available"
    assert r["next_question"] == "climate"
    # The country named in the question is still recorded (the
    # pre-existing R26 deterministic fill-in), but the turn was a
    # model turn, not a guided one.
    assert r["extracted"].get("countries") == ["CH"]
