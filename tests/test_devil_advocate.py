"""Devil's advocate for 小罗盘 (round 11): a second AI voice that
challenges the user's stated preferences with verified facts.

Pinned rules (see backend/ai/chat.py):

- mode="devil" on POST /api/v1/assistant/chat challenges the profile
  (countries, climate, level, budget) with ENGINE-COMPUTED conflicts
  only — climate-vs-country class mismatch, country-with-no-programmes
  in the track, budget-vs-fee mismatch (same currency + period only);
  every devil claim cites verified sources (same source ids);
- no admission probabilities, no guarantees, no invented facts — a
  cross-currency budget is never a mismatch (unknown, not a guess);
- when the model is down, the deterministic template fallback carries
  the same conflict notes (ai_status "unavailable", model None) — a
  model answer is never faked.

Audit profile (the verification profile for this round): China Gaokao,
undergraduate Computer Science, Gaokao 680/750, IELTS 7.0, budget GBP
50,000 per year, 2027 entry, overseas residency, preference Switzerland
(reason 环境优美), cool climate, university town, Zurich. Its real
conflict is the climate one: Zurich and Lausanne are four-season in
the verified climate table, not cool. Switzerland DOES have verified
undergraduate CS programmes (ETH/EPFL/UZH), and its fees are CHF
while the budget is GBP, so neither the no-programmes nor the budget
conflict may fire for this profile.
"""
from __future__ import annotations

import json
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai.chat import answer, devil_conflicts
from ai.provider import ProviderAdapter
from app import router_chat

_test_app = FastAPI()
_test_app.include_router(router_chat.router)
client = TestClient(_test_app)

# The audit profile: Switzerland, cool climate, UG, GBP 50,000 / year.
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


def _devil_handler(captured: dict):
    """A well-behaved mock devil: challenges the first engine-computed
    conflict in the envelope, citing that conflict's own evidence ids
    and repeating the first sentence of the cited evidence excerpt —
    so every number in its text is in the cited evidence."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        envelope = json.loads(body["messages"][-1]["content"])
        captured["envelope"] = envelope
        catalog = {c["id"]: c for c in envelope.get("evidence_catalog", [])}
        conflicts = envelope.get("devil_conflicts") or []
        assert envelope.get("task") == "devil-chat"
        assert conflicts, "devil envelope must list engine-computed conflicts"
        first = conflicts[0]
        eid = first["evidence_ids"][0]
        excerpt = catalog[eid]["excerpt"]
        text = excerpt.split(".")[0].strip() + "."
        summary = ("In my opinion, this suggests a second thought: " + text)
        payload = {
            "summary": summary,
            "claims": [{"text": text, "kind": "fact", "rule_ids": [],
                        "evidence_ids": [eid]}],
            "unknowns": [], "actions": [], "limitations": []}
        return _openai_reply(json.dumps(payload, ensure_ascii=False))
    return handler


def _http500_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"error": "boom"})


# ---------------------------------------------------------------------------
# Conflict computation is deterministic and engine-only
# ---------------------------------------------------------------------------

def test_devil_conflicts_audit_profile_is_climate_only():
    conflicts = devil_conflicts(AUDIT_PROFILE, AUDIT_MESSAGE)
    assert [c["kind"] for c in conflicts] == ["climate"]
    (climate,) = conflicts
    assert climate["country"] == "CH"
    assert climate["wanted"] == "cool"
    cities = {c: cls for c, cls, _n in climate["cities"]}
    assert cities == {"Zurich": "four_seasons", "Lausanne": "four_seasons"}
    assert "climate:zurich" in climate["evidence_ids"]
    assert "climate:lausanne" in climate["evidence_ids"]


def test_devil_conflicts_no_programmes_france_undergraduate():
    # France has verified programmes, but none matchable at
    # undergraduate level — the no-programmes conflict fires, and its
    # evidence is the catalogue search itself.
    conflicts = devil_conflicts(
        {"countries": ["FR"], "level": "undergraduate"}, "Study in France.")
    assert [c["kind"] for c in conflicts] == ["no_programmes"]
    assert conflicts[0]["evidence_ids"] == ["catalogue:fr"]


def test_devil_conflicts_budget_mismatch_same_currency_only():
    # Cheapest verified UG programme in the UK is GBP 29,000 / year
    # (Leeds Marketing BA), above a GBP 25,000 / year budget.
    conflicts = devil_conflicts(
        {"countries": ["GB"], "level": "undergraduate",
         "budget_amount": 25000, "budget_currency": "GBP",
         "budget_period": "per_year"},
        "Recommend an undergraduate programme in the UK.")
    assert [c["kind"] for c in conflicts] == ["budget"]
    (budget,) = conflicts
    assert budget["programme_id"] == "leeds-marketing-ba-2027"
    assert budget["fee_range"][0] == 29000
    assert any(eid.startswith("src:leeds-marketing-ba-2027:")
               for eid in budget["evidence_ids"])


def test_devil_conflicts_cross_currency_budget_is_never_a_mismatch():
    # CHF fees vs a GBP budget: unknown, never a mismatch — even
    # though CHF 4,380 converts to far less than GBP 50,000.
    conflicts = devil_conflicts(AUDIT_PROFILE, AUDIT_MESSAGE)
    assert "budget" not in [c["kind"] for c in conflicts]


def test_devil_conflicts_no_clash_says_so():
    # Undergraduate, UK, mild climate (London is mild), GBP 50,000:
    # cheapest UG fee GBP 29,000 is inside the budget — no conflict.
    conflicts = devil_conflicts(
        {"countries": ["GB"], "climate": "mild", "level": "undergraduate",
         "budget_amount": 50000, "budget_currency": "GBP",
         "budget_period": "per_year"},
        "Is the UK right for me? I like a mild climate.")
    assert conflicts == []


# ---------------------------------------------------------------------------
# Template fallback (no key): the audit profile's climate conflict
# ---------------------------------------------------------------------------

def test_devil_template_audit_profile_names_four_season_conflict(monkeypatch):
    r = answer(AUDIT_MESSAGE, "en", provider=_no_key_provider(monkeypatch),
               mode="devil", profile=AUDIT_PROFILE)
    assert r["ai_status"] == "unavailable"
    assert r["model"] is None
    assert r["mode"] == "devil"
    assert r["conflicts"] == ["climate"]
    joined = "\n".join(r["lines"])
    assert "Zurich" in joined and "Lausanne" in joined
    assert "four-season" in joined
    assert "cool" in joined.lower()
    assert len(r["lines"]) <= 3
    assert "%" not in joined, "no admission probabilities anywhere"
    assert "guarantee" not in joined.lower()
    assert "http" not in joined, "no raw URL in answer text"
    # No invented budget mismatch: Swiss fees are CHF, budget is GBP.
    assert "above your" not in joined
    # The Swiss climate sources are cited.
    ids = [s["id"] for s in r["sources"]]
    assert "climate:zurich" in ids and "climate:lausanne" in ids
    assert r["evidence_url"] is not None
    assert r["evidence_url"].startswith("https://en.wikipedia.org/wiki/Zurich")


def test_devil_template_audit_profile_zh(monkeypatch):
    r = answer("瑞士适合我吗？我想要凉爽的气候。", "zh-CN",
               provider=_no_key_provider(monkeypatch),
               mode="devil", profile=AUDIT_PROFILE)
    assert r["ai_status"] == "unavailable"
    assert r["mode"] == "devil"
    joined = "\n".join(r["lines"])
    # Round 15: city names are localised in the Chinese reply — no bare
    # English city names in the template text.
    assert "苏黎世" in joined and "洛桑" in joined
    assert "Zurich" not in joined and "Lausanne" not in joined
    assert "四季分明" in joined
    assert "%" not in joined


def test_devil_template_no_programmes_and_budget(monkeypatch):
    provider = _no_key_provider(monkeypatch)
    r = answer("Study in France.", "en", provider=provider, mode="devil",
               profile={"countries": ["FR"], "level": "undergraduate"})
    assert r["mode"] == "devil"
    assert r["conflicts"] == ["no_programmes"]
    joined = "\n".join(r["lines"])
    assert "France" in joined and "no verified route" in joined
    assert any(s["id"] == "catalogue:fr" for s in r["sources"])

    r = answer("Recommend an undergraduate programme in the UK.", "en",
               provider=provider, mode="devil",
               profile={"countries": ["GB"], "level": "undergraduate",
                        "budget_amount": 25000, "budget_currency": "GBP",
                        "budget_period": "per_year"})
    assert r["conflicts"] == ["budget"]
    joined = "\n".join(r["lines"])
    assert "29,000" in joined and "above your" in joined
    assert any(s["id"].startswith("src:leeds-marketing-ba-2027:")
               for s in r["sources"])


def test_devil_template_no_conflict_is_honest(monkeypatch):
    r = answer("Is the UK right for me? I like a mild climate.", "en",
               provider=_no_key_provider(monkeypatch), mode="devil",
               profile={"countries": ["GB"], "climate": "mild",
                        "level": "undergraduate", "budget_amount": 50000,
                        "budget_currency": "GBP", "budget_period": "per_year"})
    assert r["mode"] == "devil"
    assert r["conflicts"] == []
    joined = "\n".join(r["lines"])
    assert "no clash" in joined
    assert "Another angle" not in joined, "no invented challenge"


def test_devil_template_invalid_profile_values_are_dropped(monkeypatch):
    # A garbage profile never 422s and never invents a conflict: the
    # message itself ("cool climate", Switzerland) still drives the
    # climate challenge.
    r = answer(AUDIT_MESSAGE, "en", provider=_no_key_provider(monkeypatch),
               mode="devil",
               profile={"countries": ["xx", 7], "climate": "freezing",
                        "level": "phd", "budget_amount": -5,
                        "budget_currency": "GBP", "budget_period": "weekly"})
    assert r["mode"] == "devil"
    assert r["conflicts"] == ["climate"]
    assert "four-season" in "\n".join(r["lines"])


# ---------------------------------------------------------------------------
# Model path (mock provider): grounded devil, cites the conflict
# ---------------------------------------------------------------------------

def test_devil_mock_model_cites_swiss_climate(monkeypatch):
    captured: dict = {}
    provider = _mock_provider(monkeypatch, _devil_handler(captured))
    r = answer(AUDIT_MESSAGE, "en", provider=provider,
               mode="devil", profile=AUDIT_PROFILE)
    assert r["ai_status"] == "available"
    assert r["model"] == "openai/test-model"
    assert r["mode"] == "devil"
    assert r["conflicts"] == ["climate"]
    joined = "\n".join(r["lines"])
    assert "four-season" in joined and "Zurich" in joined
    assert "suggests" in joined.lower(), "opinion language, never a verdict"
    assert "%" not in joined
    assert "http" not in joined
    assert len(r["lines"]) <= 3
    assert any(s["id"] == "climate:zurich" for s in r["sources"])
    assert captured["envelope"]["task"] == "devil-chat"
    assert captured["envelope"]["devil_conflicts"][0]["kind"] == "climate"
    assert "climate:zurich" in captured["envelope"]["devil_conflicts"][0]["evidence_ids"]
    assert r["evidence_url"].startswith("https://en.wikipedia.org/wiki/Zurich")


def test_devil_mock_model_that_ignores_the_conflict_falls_back(monkeypatch):
    """A model reply that answers without citing any conflict evidence
    is not a devil's-advocate answer: the template challenges instead."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        envelope = json.loads(body["messages"][-1]["content"])
        catalog = envelope["evidence_catalog"]
        first = catalog[0]
        text = first["excerpt"].split(".")[0].strip() + "."
        payload = {"summary": text,
                   "claims": [{"text": text, "kind": "fact", "rule_ids": [],
                               "evidence_ids": [first["id"]]}],
                   "unknowns": [], "actions": [], "limitations": []}
        return _openai_reply(json.dumps(payload, ensure_ascii=False))
    provider = _mock_provider(monkeypatch, handler)
    r = answer(AUDIT_MESSAGE, "en", provider=provider,
               mode="devil", profile=AUDIT_PROFILE)
    assert r["ai_status"] == "unavailable"
    assert r["mode"] == "devil"
    assert r["conflicts"] == ["climate"]
    assert "four-season" in "\n".join(r["lines"])


def test_devil_gateway_down_falls_back_to_template(monkeypatch):
    provider = _mock_provider(monkeypatch, _http500_handler)
    started = time.monotonic()
    r = answer(AUDIT_MESSAGE, "en", provider=provider,
               mode="devil", profile=AUDIT_PROFILE)
    elapsed = time.monotonic() - started
    assert r["ai_status"] == "unavailable"
    assert r["model"] is None
    assert r["mode"] == "devil"
    assert r["conflicts"] == ["climate"]
    assert "four-season" in "\n".join(r["lines"])
    assert elapsed < 5.0, f"fast gateway error took {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# Router: mode passthrough + validation
# ---------------------------------------------------------------------------

def test_devil_endpoint_no_key(monkeypatch):
    monkeypatch.setattr(router_chat, "get_provider",
                        lambda: _no_key_provider(monkeypatch))
    r = client.post("/api/v1/assistant/chat",
                    json={"message": AUDIT_MESSAGE, "locale": "en",
                          "mode": "devil", "profile": AUDIT_PROFILE})
    assert r.status_code == 200
    body = r.json()
    assert body["ai_status"] == "unavailable"
    assert body["mode"] == "devil"
    assert body["conflicts"] == ["climate"]
    assert "four-season" in "\n".join(body["lines"])
    assert any(s["id"] == "climate:zurich" for s in body["sources"])


def test_devil_endpoint_mock_model(monkeypatch):
    captured: dict = {}
    provider = _mock_provider(monkeypatch, _devil_handler(captured))
    monkeypatch.setattr(router_chat, "get_provider", lambda: provider)
    r = client.post("/api/v1/assistant/chat",
                    json={"message": AUDIT_MESSAGE, "locale": "en",
                          "mode": "devil", "profile": AUDIT_PROFILE})
    assert r.status_code == 200
    body = r.json()
    assert body["ai_status"] == "available"
    assert body["mode"] == "devil"
    assert "four-season" in "\n".join(body["lines"])


def test_devil_endpoint_invalid_mode_is_422(monkeypatch):
    monkeypatch.setattr(router_chat, "get_provider",
                        lambda: _no_key_provider(monkeypatch))
    r = client.post("/api/v1/assistant/chat",
                    json={"message": AUDIT_MESSAGE, "locale": "en",
                          "mode": "bogus", "profile": AUDIT_PROFILE})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_normal_chat_response_unchanged(monkeypatch):
    """No mode key, no conflicts key, no devil behaviour on the normal
    path — the passthrough must not change existing responses."""
    monkeypatch.setattr(router_chat, "get_provider",
                        lambda: _no_key_provider(monkeypatch))
    r = client.post("/api/v1/assistant/chat",
                    json={"message": "What is the UCL Computer Science BSc tuition fee?",
                          "locale": "en"})
    assert r.status_code == 200
    body = r.json()
    assert "mode" not in body and "conflicts" not in body
    assert "48,600" in body["lines"][0]


def test_devil_no_conflict_never_calls_the_model(monkeypatch):
    # Coordinator integration guard: when the engine finds no conflict,
    # the model must not be consulted at all — the prompt alone cannot
    # stop it inventing a challenge. The honest template answers.
    called: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        raise AssertionError("model must not be called with no conflicts")

    r = answer("Is the UK right for me? I like a mild climate.", "en",
               provider=_mock_provider(monkeypatch, handler), mode="devil",
               profile={"countries": ["GB"], "climate": "mild",
                        "level": "undergraduate", "budget_amount": 50000,
                        "budget_currency": "GBP", "budget_period": "per_year"})
    assert called == []
    assert r["mode"] == "devil"
    assert r["conflicts"] == []
    assert r["ai_status"] == "unavailable"
    assert "no clash" in "\n".join(r["lines"])
