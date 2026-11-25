"""Free-text profile parsing (backend/ai/parse.py).

Pinned rules (see backend/ai/parse.py):
- the parse NEVER applies a profile: ``confirmation_required`` is
  always True and the response says so — applying happens via /match
  or /profile/validate with the user-confirmed profile;
- ``parsed_profile`` is StudentProfile-shaped and contains ONLY
  extracted fields (no invented gaokao_total, no guessed values);
- out-of-range values go into ``unparsed`` — NEVER clamped, rescaled
  or converted between grading scales (IELTS 12.0 stays unparsed,
  it does not become 9.0);
- the same validation rules apply to the model path and the regex path.
"""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai.parse import parse_profile
from ai.provider import ProviderAdapter
from app import router_chat

_test_app = FastAPI()
_test_app.include_router(router_chat.router)
client = TestClient(_test_app)


# ---------------------------------------------------------------------------
# Mock-provider helpers (httpx.MockTransport; no real key, no network)
# ---------------------------------------------------------------------------

def _openai_reply(payload_text: str) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"content": payload_text}}], "usage": {}})


def _mock_provider(monkeypatch, handler) -> ProviderAdapter:
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")
    return ProviderAdapter(_transport=httpx.MockTransport(handler))


def _no_key_provider(monkeypatch) -> ProviderAdapter:
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return ProviderAdapter()


_HAPPY_PAYLOAD = {
    "application_track": "undergraduate",
    "undergrad": {"curriculum": "cn_gaokao", "gaokao_score": 680,
                  "gaokao_total": None, "sat_total": None,
                  "act_composite": None, "ib_total": None,
                  "a_level_grades": None},
    "masters": {"degree_field": None, "degree_class": None,
                "it_experience_years": None, "gre_total": None,
                "gmat_total": None},
    "language": {"exam": "ielts", "overall": 7.0, "listening": None,
                 "reading": None, "writing": None, "speaking": None},
    "budget": {"amount": 50000, "currency": "GBP", "period": None},
    "target_intake": None,
    "unparsed": [],
    "confidence": {"undergrad_profile.gaokao_score": "high",
                   "language.overall": "high",
                   "budget.amount": "medium",
                   "budget.currency": "high"},
}


def _parse_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    envelope = json.loads(body["messages"][-1]["content"])
    assert envelope["task"] == "parse"
    assert envelope["prompt_version"] == "ai-prompts-v1"
    payload = json.loads(json.dumps(_HAPPY_PAYLOAD))
    if "12.0" in envelope["text"]:
        payload["language"]["overall"] = 12.0
    return _openai_reply(json.dumps(payload, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Model path: happy path
# ---------------------------------------------------------------------------

def test_parse_model_happy_path(monkeypatch):
    provider = _mock_provider(monkeypatch, _parse_handler)
    r = parse_profile("Gaokao 680, IELTS 7.0, budget 50k GBP", "en",
                      provider=provider)
    assert r["parser"] == "model"
    assert r["ai_status"] == "available"
    assert r["confirmation_required"] is True
    profile = r["parsed_profile"]
    assert profile["application_track"] == "undergraduate"
    assert profile["undergrad_profile"]["gaokao_score"] == 680
    # Nothing invented: no gaokao_total was stated, so none is present.
    assert "gaokao_total" not in profile["undergrad_profile"]
    assert profile["language"]["exam"] == "ielts"
    assert profile["language"]["overall"] == 7.0
    assert profile["budget"]["amount"] == 50000
    assert profile["budget"]["currency"] == "GBP"
    assert profile["budget"]["period"] is None
    assert r["confidence"]["budget.amount"] == "medium"
    assert r["unparsed"] == []
    assert "not applied" in r["note"]


def test_parse_model_out_of_range_is_unparsed_never_clamped(monkeypatch):
    provider = _mock_provider(monkeypatch, _parse_handler)
    r = parse_profile("Gaokao 680, IELTS 12.0, budget 50k GBP", "en",
                      provider=provider)
    assert r["parser"] == "model"
    profile = r["parsed_profile"]
    assert "overall" not in profile.get("language", {}), \
        "IELTS 12.0 must not be clamped to 9.0 or kept"
    assert profile["language"].get("overall") != 9.0
    assert any("12" in entry for entry in r["unparsed"])
    # The in-range fields still parse.
    assert profile["undergrad_profile"]["gaokao_score"] == 680
    assert profile["budget"]["amount"] == 50000


# ---------------------------------------------------------------------------
# Regex path (no key): same fields, same validation
# ---------------------------------------------------------------------------

def test_parse_regex_fallback_happy_path(monkeypatch):
    r = parse_profile("Gaokao 680, IELTS 7.0, budget 50k GBP", "en",
                      provider=_no_key_provider(monkeypatch))
    assert r["parser"] == "regex"
    assert r["ai_status"] == "unavailable"
    assert r["confirmation_required"] is True
    profile = r["parsed_profile"]
    assert profile["application_track"] == "undergraduate"
    assert profile["undergrad_profile"]["gaokao_score"] == 680
    assert profile["undergrad_profile"]["curriculum"] == "cn_gaokao"
    assert "gaokao_total" not in profile["undergrad_profile"]
    assert profile["language"]["overall"] == 7.0
    assert profile["budget"]["amount"] == 50000
    assert profile["budget"]["currency"] == "GBP"
    assert profile["budget"]["period"] is None
    assert r["confidence"]["budget.amount"] == "medium"
    assert r["unparsed"] == []


def test_parse_regex_masters_fields(monkeypatch):
    r = parse_profile("TOEFL 100, GRE 320, GMAT 700, intake 2027", "en",
                      provider=_no_key_provider(monkeypatch))
    profile = r["parsed_profile"]
    assert profile["application_track"] == "taught_masters"
    assert profile["language"]["exam"] == "toefl"
    assert profile["language"]["toefl_overall"] == 100
    assert "overall" not in profile["language"]
    assert profile["masters_profile"]["gre_total"] == 320
    assert profile["masters_profile"]["gmat_total"] == 700
    assert profile["target_intake"] == 2027
    assert r["unparsed"] == []


def test_parse_regex_out_of_range_is_unparsed_never_clamped(monkeypatch):
    r = parse_profile("IELTS 12.0, Gaokao 900, SAT 2000, GMAT 900", "en",
                      provider=_no_key_provider(monkeypatch))
    profile = r["parsed_profile"]
    assert profile.get("language", {}).get("overall") != 9.0
    assert "overall" not in profile.get("language", {})
    assert "gaokao_score" not in profile.get("undergrad_profile", {})
    assert "sat_total" not in profile.get("undergrad_profile", {})
    assert "gmat_total" not in profile.get("masters_profile", {})
    joined = " ".join(r["unparsed"])
    assert "12" in joined and "900" in joined and "2000" in joined


def test_parse_regex_unparsed_segments_and_bare_values(monkeypatch):
    r = parse_profile("Gaokao 680, I love basketball, budget 50000", "en",
                      provider=_no_key_provider(monkeypatch))
    assert r["parsed_profile"]["undergrad_profile"]["gaokao_score"] == 680
    assert any("basketball" in entry for entry in r["unparsed"])
    # A budget number with no currency stays unparsed (no units).
    assert "budget" not in r["parsed_profile"]
    assert any("50000" in entry for entry in r["unparsed"])


def test_parse_regex_personal_data_never_echoed(monkeypatch):
    r = parse_profile("Gaokao 680, my email is zhangsan@example.com", "en",
                      provider=_no_key_provider(monkeypatch))
    joined = " ".join(r["unparsed"]) + json.dumps(r["parsed_profile"])
    assert "zhangsan@example.com" not in joined
    assert r["parsed_profile"]["undergrad_profile"]["gaokao_score"] == 680


def test_parse_never_applies(monkeypatch):
    r = parse_profile("Gaokao 680, IELTS 7.0, budget 50k GBP", "en",
                      provider=_no_key_provider(monkeypatch))
    assert r["confirmation_required"] is True
    assert "not applied" in r["note"]
    assert "confirm" in r["note"].lower()


# ---------------------------------------------------------------------------
# Router: /profile/parse
# ---------------------------------------------------------------------------

def test_parse_endpoint_no_key(monkeypatch):
    monkeypatch.setattr(router_chat, "get_provider",
                        lambda: _no_key_provider(monkeypatch))
    r = client.post("/api/v1/profile/parse",
                    json={"text": "Gaokao 680, IELTS 7.0, budget 50k GBP",
                          "locale": "en"})
    assert r.status_code == 200
    body = r.json()
    assert body["parser"] == "regex"
    assert body["confirmation_required"] is True
    assert body["parsed_profile"]["budget"]["amount"] == 50000


def test_parse_endpoint_mock_model(monkeypatch):
    provider = _mock_provider(monkeypatch, _parse_handler)
    monkeypatch.setattr(router_chat, "get_provider", lambda: provider)
    r = client.post("/api/v1/profile/parse",
                    json={"text": "Gaokao 680, IELTS 7.0, budget 50k GBP",
                          "locale": "en"})
    assert r.status_code == 200
    body = r.json()
    assert body["parser"] == "model"
    assert body["ai_status"] == "available"
    assert body["parsed_profile"]["undergrad_profile"]["gaokao_score"] == 680


def test_parse_endpoint_invalid_input_422(monkeypatch):
    monkeypatch.setattr(router_chat, "get_provider",
                        lambda: _no_key_provider(monkeypatch))
    for body in (
            {"text": ""},
            {"text": "   "},
            {"text": "x" * 2001},
            {"locale": "en"},
            {"text": 123},
    ):
        r = client.post("/api/v1/profile/parse", json=body)
        assert r.status_code == 422, body
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"
