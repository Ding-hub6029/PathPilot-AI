"""Model-led preference conversation (backend/ai/pref_chat.py, round 7).

Pinned rules (see backend/ai/pref_chat.py):
- the model extracts, from THIS message only, the preferences it
  states — including the user's reason in their own words (note) —
  and picks the next question; extraction is validated server-side
  and never trusted (bad enums / unknown country codes / salary
  without a currency are dropped, never clamped or converted);
- climate evidence is scoped to the known countries: CH + cool gives
  Zurich/Lausanne with their ACTUAL four-season classes and never
  Edinburgh (the 2026-11-26 live-test bug);
- no-key path falls back honestly (ai_status "unavailable", model
  None, extracted {}, deterministic next_question — never a known
  one); personal data is refused with the fixed line, never echoed;
- lines are at most 3, conclusion first, the next question as the
  last line while anything is still missing; done=True exactly when
  all 8 preferences are known.
"""
from __future__ import annotations

import json
import re

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai.chat import _climate_evidence
from ai.pref_chat import (PREF_ORDER, _question_line, first_missing,
                          missing_prefs, pref_answer, validate_extracted,
                          validate_known)
from ai.provider import ProviderAdapter
from app import router_chat

_test_app = FastAPI()
_test_app.include_router(router_chat.router)
client = TestClient(_test_app)

ALL_KNOWN = {
    "countries": ["CH"], "climate": "cool", "environment": "big_city",
    "city": "Zurich", "afterGrad": "stay", "salary": 50000,
    "salaryCurrency": "GBP", "pressure": "low", "teaching": "lecture",
}


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


def _extract_from_message(message: str) -> dict:
    """What a well-behaved model would extract from one message."""
    out: dict = {}
    msg = message or ""
    for word, code in (("瑞士", "CH"), ("Switzerland", "CH"),
                       ("英国", "GB"), ("United Kingdom", "GB"),
                       ("新加坡", "SG"), ("Singapore", "SG"),
                       ("美国", "US")):
        if word in msg:
            out.setdefault("countries", []).append(code)
    if "冷门" not in msg and "冷" in msg:
        out["climate"] = "cool"
    elif "暖" in msg or "热" in msg:
        out["climate"] = "warm"
    elif "四季" in msg:
        out["climate"] = "four_seasons"
    elif "温和" in msg or "宜人" in msg:
        out["climate"] = "mild"
    for word, value in (("大城市", "big_city"), ("小城市", "small_city"),
                        ("校园", "campus"), ("安静", "quiet_town"),
                        ("小镇", "quiet_town")):
        if word in msg:
            out["environment"] = value
    for word, city in (("苏黎世", "Zurich"), ("Zurich", "Zurich"),
                       ("洛桑", "Lausanne"), ("Lausanne", "Lausanne"),
                       ("伦敦", "London"), ("London", "London")):
        if word in msg:
            out["city"] = city
    for word, value in (("留下来", "stay"), ("留下", "stay"),
                        ("回国", "return_home"), ("老家", "hometown"),
                        ("还没想好", "undecided")):
        if word in msg:
            out["afterGrad"] = value
    m = re.search(r"(GBP|SGD|USD)\s*([\d,]+)", msg)
    if m:
        out["salary"] = {"amount": float(m.group(2).replace(",", "")),
                         "currency": m.group(1)}
    for word, value in (("轻松", "low"), ("适中", "medium"),
                        ("高压", "high"), ("高强度", "high")):
        if word in msg:
            out["pressure"] = value
    for word, value in (("讲座", "lecture"), ("研讨", "seminar"),
                        ("实践", "hands_on"), ("动手", "hands_on")):
        if word in msg:
            out["teaching"] = value
    if "因为" in msg:
        reason = msg.split("因为", 1)[1]
        reason = re.split(r"[，。！？；,.;!?]", reason)[0].strip()
        if reason:
            out["note"] = reason
    elif "环境优美" in msg:
        out["note"] = "环境优美"
    return out


def _pref_handler(captured: dict):
    """A well-behaved mock model: extracts from the message, answers
    only from the evidence catalogue, acknowledges the user's reason
    in their own words, and picks the next question from the missing
    list minus what this message just answered."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        content = body["messages"][-1]["content"]
        if content.startswith("Your previous output failed validation"):
            envelope = captured["envelope"]
        else:
            envelope = json.loads(content)
            captured["envelope"] = envelope
        locale = envelope.get("locale", "en")
        message = envelope.get("message", "")
        missing = list(envelope.get("missing") or [])
        extracted = _extract_from_message(message)
        answered = set()
        if extracted.get("countries"):
            answered.add("countries")
        for key in ("climate", "environment", "city", "afterGrad",
                    "salary", "pressure", "teaching"):
            if key in extracted:
                answered.add(key)
        remaining = [pid for pid in missing if pid not in answered]
        nxt = remaining[0] if remaining else None
        catalog = envelope.get("evidence_catalog", [])
        climate = [c for c in catalog if c["id"].startswith("climate:")]
        note = extracted.get("note")
        if locale == "zh-CN":
            summary = "明白" + (f"，你说{note}，我记下了" if note else "") + "。"
            claim_texts = [c["excerpt"].split(".")[0].strip() + "."
                           for c in climate]
        else:
            summary = "Got it" + (f" — you said {note}, noted" if note else "") + "."
            claim_texts = [c["excerpt"].split(".")[0].strip() + "."
                           for c in climate]
        claims = []
        if climate:
            claims.append({"text": " ".join(claim_texts), "kind": "fact",
                           "rule_ids": [],
                           "evidence_ids": [c["id"] for c in climate]})
        else:
            claims.append({"text": ("没有已核实的数据可以引用。"
                                    if locale == "zh-CN"
                                    else "No verified data to cite."),
                           "kind": "limitation", "rule_ids": [],
                           "evidence_ids": []})
        payload = {"summary": summary, "claims": claims,
                   "unknowns": [], "actions": [], "limitations": [],
                   "extracted": extracted, "next_question": nxt}
        return _openai_reply(json.dumps(payload, ensure_ascii=False))
    return handler


def _bad_extraction_handler(request: httpx.Request) -> httpx.Response:
    """A sloppy mock model: valid chat fields, but an invalid
    extraction (unknown country, bad enum, salary without currency,
    over-long note, unknown key) and a next_question that names a
    preference already known. The server must fix all of it."""
    payload = {
        "summary": "明白，我记下了。",
        "claims": [{"text": "没有已核实的数据可以引用。", "kind": "limitation",
                    "rule_ids": [], "evidence_ids": []}],
        "unknowns": [], "actions": [], "limitations": [],
        "extracted": {"countries": ["XX", "CH"], "climate": "freezing",
                      "salary": {"amount": 50000},
                      "note": "x" * 300, "bogus": 1},
        "next_question": "countries"}
    return _openai_reply(json.dumps(payload, ensure_ascii=False))


def _garbage_handler(request: httpx.Request) -> httpx.Response:
    return _openai_reply("this is not json at all")


# ---------------------------------------------------------------------------
# Unit: extraction / known validation (no provider needed)
# ---------------------------------------------------------------------------

def test_validate_extracted_keeps_only_valid_fields():
    raw = {"countries": ["ch", "XX", "CH", "GB"], "climate": "cool",
           "environment": "campus", "city": "  苏黎世  ",
           "afterGrad": "stay", "salary": {"amount": 50000, "currency": "gbp"},
           "pressure": "low", "teaching": "seminar",
           "note": "因为那边环境优美", "bogus": 1}
    out = validate_extracted(raw)
    assert out["countries"] == ["CH", "GB"]
    assert out["climate"] == "cool"
    assert out["city"] == "苏黎世"
    assert out["salary"] == {"amount": 50000, "currency": "GBP"}
    assert out["note"] == "因为那边环境优美"
    assert "bogus" not in out


def test_validate_extracted_drops_bad_values():
    # Bad enum, unknown country, salary without currency, non-positive
    # amount, non-string city, over-long note — all dropped, never
    # clamped or converted.
    raw = {"countries": ["XX"], "climate": "freezing",
           "environment": "downtown", "afterGrad": "maybe",
           "salary": {"amount": 50000},
           "pressure": "chill", "teaching": 3,
           "city": 42}
    out = validate_extracted(raw)
    assert out == {}, out
    raw2 = {"salary": {"amount": 0, "currency": "GBP"}}
    assert validate_extracted(raw2) == {}
    raw3 = {"salary": {"amount": -5, "currency": "USD"}}
    assert validate_extracted(raw3) == {}
    raw4 = {"salary": {"amount": "50000", "currency": "GBP"}}
    assert validate_extracted(raw4) == {}
    raw5 = {"note": "z" * 250}
    assert validate_extracted(raw5) == {"note": "z" * 200}
    assert validate_extracted("not a dict") == {}
    assert validate_extracted(None) == {}


def test_validate_known_drops_invalid_and_normalises():
    known = validate_known({"countries": ["ch", "ZZ"], "climate": "freezing",
                            "city": " ", "salary": 100, "salaryCurrency": "EUR",
                            "pressure": "low", "note": "n" * 250})
    assert known["countries"] == ["CH"]
    assert known["climate"] is None
    assert known["city"] is None
    assert known["salary"] is None and known["salaryCurrency"] is None
    assert known["pressure"] == "low"
    assert known["note"] == "n" * 200
    assert validate_known(None)["countries"] == []
    assert missing_prefs(validate_known(ALL_KNOWN)) == []
    assert first_missing(validate_known(ALL_KNOWN)) is None


# ---------------------------------------------------------------------------
# Unit: country-scoped climate evidence (chat._climate_evidence)
# ---------------------------------------------------------------------------

def test_climate_evidence_ch_cool_is_zurich_lausanne_not_edinburgh():
    # The 2026-11-26 live-test bug: a Switzerland + cool user got
    # Edinburgh. Scoped to CH there is NO cool-class city — both Swiss
    # cities are four-season, and no other country's city substitutes.
    sources, top_programme = _climate_evidence("cool", countries=["CH"])
    ids = [s.id for s in sources]
    assert ids == ["climate:zurich", "climate:lausanne"], ids
    assert all("four-season" in s.excerpt for s in sources)
    assert "11" in sources[0].excerpt and "9" in sources[1].excerpt
    assert not any("edinburgh" in i for i in ids)
    assert top_programme is None, "no cool-class city in CH, so no pick"


def test_climate_evidence_global_unchanged():
    # Without a country scope the old global top-3 behaviour stands:
    # Edinburgh first (19 verified programmes), cool only.
    sources, top_programme = _climate_evidence("cool")
    assert sources[0].id == "climate:edinburgh"
    assert "19" in sources[0].excerpt
    assert all("cool" in s.excerpt for s in sources)
    assert top_programme is not None


def test_climate_evidence_scoped_wanted_class_first():
    # GB + cool: Edinburgh is wanted-class AND in scope, so it leads,
    # and other GB cities with a table entry follow with actual classes.
    sources, _ = _climate_evidence("cool", countries=["GB"])
    assert sources[0].id == "climate:edinburgh"
    assert all("cool" in s.excerpt for s in sources[:1])


# ---------------------------------------------------------------------------
# Offline path: honest template fallback, deterministic next question
# ---------------------------------------------------------------------------

def test_pref_chat_no_key_first_question(monkeypatch):
    r = pref_answer("你好", "zh-CN", known={},
                    provider=_no_key_provider(monkeypatch))
    assert r["ai_status"] == "unavailable"
    assert r["model"] is None
    assert r["extracted"] == {}
    assert r["next_question"] == "countries"
    assert r["done"] is False
    assert len(r["lines"]) <= 3
    assert r["lines"][-1] == _question_line("countries", "zh-CN")


def test_pref_chat_no_key_next_question_skips_known(monkeypatch):
    provider = _no_key_provider(monkeypatch)
    r = pref_answer("你好", "zh-CN",
                    known={"countries": ["CH"], "climate": "cool"},
                    provider=provider)
    assert r["next_question"] == "environment"
    assert r["done"] is False
    r2 = pref_answer("你好", "en",
                     known={**ALL_KNOWN, "teaching": None},
                     provider=provider)
    assert r2["next_question"] == "teaching"


def test_pref_chat_no_key_done_when_all_known(monkeypatch):
    r = pref_answer("还有什么要问的吗", "zh-CN", known=dict(ALL_KNOWN),
                    provider=_no_key_provider(monkeypatch))
    assert r["ai_status"] == "unavailable"
    assert r["next_question"] is None
    assert r["done"] is True
    assert r["extracted"] == {}
    assert len(r["lines"]) <= 3


def test_pref_chat_garbage_model_falls_back(monkeypatch):
    provider = _mock_provider(monkeypatch, _garbage_handler)
    r = pref_answer("我想去瑞士", "zh-CN", known={},
                    provider=provider)
    assert r["ai_status"] == "unavailable"
    assert r["model"] is None
    assert r["extracted"] == {}
    assert r["next_question"] == "countries"
    assert r["done"] is False


# ---------------------------------------------------------------------------
# Personal data: refused, never echoed
# ---------------------------------------------------------------------------

def test_pref_chat_personal_data_refusal_no_echo(monkeypatch):
    provider = _mock_provider(monkeypatch, _pref_handler({}))
    r = pref_answer("my email is zhangsan@example.com, phone 13812345678",
                    "en", known={"countries": ["CH"]}, provider=provider)
    joined = "\n".join(r["lines"])
    assert "zhangsan@example.com" not in joined
    assert "13812345678" not in joined
    assert "don't collect" in r["lines"][0].lower()
    assert r["ai_status"] == "unavailable"
    assert r["model"] is None
    assert r["evidence_url"] is None
    assert r["sources"] == []
    assert r["extracted"] == {}
    # The conversation still knows what to ask next.
    assert r["next_question"] == "climate"
    assert r["done"] is False


# ---------------------------------------------------------------------------
# Mock-model path: reason kept, CH+cool scoped, next question honest
# ---------------------------------------------------------------------------

def test_pref_chat_switzerland_reason_kept(monkeypatch):
    # The 2026-11-26 live-test bug (2): "我想去瑞士，因为那边环境优美"
    # recorded just "瑞士". The reason must survive in `extracted`
    # and be acknowledged in the reply, in the user's own words.
    captured: dict = {}
    provider = _mock_provider(monkeypatch, _pref_handler(captured))
    r = pref_answer("我想去瑞士，因为那边环境优美", "zh-CN", known={},
                    provider=provider)
    assert r["ai_status"] == "available"
    assert r["model"] == "openai/test-model"
    assert r["extracted"]["countries"] == ["CH"]
    assert "环境优美" in r["extracted"]["note"]
    assert "环境优美" in "\n".join(r["lines"])
    assert r["next_question"] == "climate"
    assert r["done"] is False
    assert r["lines"][-1] == _question_line("climate", "zh-CN")
    assert len(r["lines"]) <= 3
    assert captured["envelope"]["task"] == "pref-chat"
    assert captured["envelope"]["prompt_version"] == "ai-prompts-v1"
    assert captured["envelope"]["known"]["countries"] == []
    assert captured["envelope"]["missing"] == list(PREF_ORDER)


def test_pref_chat_ch_cool_scoped_climate_no_edinburgh(monkeypatch):
    # The 2026-11-26 live-test bug (3): a Switzerland + cool user got
    # an Edinburgh opinion. The catalogue must carry only Zurich and
    # Lausanne (both four-season), and the reply must never mention
    # Edinburgh.
    captured: dict = {}
    provider = _mock_provider(monkeypatch, _pref_handler(captured))
    r = pref_answer("我喜欢很冷的地方", "zh-CN",
                    known={"countries": ["CH"], "climate": "cool"},
                    provider=provider)
    assert r["ai_status"] == "available"
    catalog = captured["envelope"]["evidence_catalog"]
    climate = [c for c in catalog if c["id"].startswith("climate:")]
    assert [c["id"] for c in climate] == ["climate:zurich",
                                          "climate:lausanne"]
    assert all("four-season" in c["excerpt"] for c in climate)
    assert not any(c["id"] == "climate:edinburgh" for c in climate)
    joined = "\n".join(r["lines"])
    assert "Zurich" in joined
    assert "Edinburgh" not in joined
    assert r["evidence_url"] is not None
    assert r["evidence_url"].startswith("https://en.wikipedia.org/wiki/")
    assert "Zurich" in r["evidence_url"] or "Lausanne" in r["evidence_url"]
    assert r["extracted"]["climate"] == "cool"
    assert r["next_question"] == "environment"
    assert r["lines"][-1] == _question_line("environment", "zh-CN")


def test_pref_chat_model_next_question_never_repeats_known(monkeypatch):
    # The mock answers next_question="countries" even though countries
    # is already known; the server must override it deterministically.
    captured: dict = {}
    provider = _mock_provider(monkeypatch, _pref_handler(captured))
    r = pref_answer("我喜欢很冷的地方", "zh-CN",
                    known={"countries": ["CH"], "climate": "cool"},
                    provider=provider)
    assert r["next_question"] == "environment"
    assert r["next_question"] not in ("countries", "climate")


def test_pref_chat_bad_extraction_fixed_server_side(monkeypatch):
    provider = _mock_provider(monkeypatch, _bad_extraction_handler)
    r = pref_answer("随便聊聊", "zh-CN", known={"countries": ["CH"]},
                    provider=provider)
    assert r["ai_status"] == "available"
    # Unknown country dropped, bad enum dropped, salary without a
    # currency omitted, note capped at 200, unknown key dropped.
    assert r["extracted"] == {"countries": ["CH"], "note": "x" * 200}
    # The model's next_question named an already-known preference;
    # the server recomputes it from the merged known prefs.
    assert r["next_question"] == "climate"
    assert r["done"] is False


def test_pref_chat_salary_extraction_needs_amount_and_currency(monkeypatch):
    captured: dict = {}
    provider = _mock_provider(monkeypatch, _pref_handler(captured))
    r = pref_answer("I hope to earn GBP 50000 a year after graduating",
                    "en", known={}, provider=provider)
    assert r["ai_status"] == "available"
    assert r["extracted"]["salary"] == {"amount": 50000, "currency": "GBP"}
    assert r["next_question"] == "countries"


def test_pref_chat_history_is_capped_at_six_turns(monkeypatch):
    captured: dict = {}
    provider = _mock_provider(monkeypatch, _pref_handler(captured))
    history = [{"role": "user", "content": f"question {i}"} for i in range(8)]
    r = pref_answer("我想去瑞士", "zh-CN", known={}, history=history,
                    provider=provider)
    assert r["ai_status"] == "available"
    assert len(captured["envelope"]["history"]) == 6
    assert captured["envelope"]["history"][0]["content"] == "question 2"


def test_pref_chat_done_true_when_all_known_model(monkeypatch):
    captured: dict = {}
    provider = _mock_provider(monkeypatch, _pref_handler(captured))
    r = pref_answer("还有什么要问的吗", "zh-CN", known=dict(ALL_KNOWN),
                    provider=provider)
    assert r["ai_status"] == "available"
    assert r["next_question"] is None
    assert r["done"] is True
    assert r["extracted"] == {}
    assert len(r["lines"]) <= 3
    # No next-question line is appended once done.
    assert all(line != _question_line(pid, "zh-CN")
               for line in r["lines"] for pid in PREF_ORDER)


# ---------------------------------------------------------------------------
# Router: /assistant/pref-chat
# ---------------------------------------------------------------------------

def test_pref_chat_endpoint_no_key(monkeypatch):
    monkeypatch.setattr(router_chat, "get_provider",
                        lambda: _no_key_provider(monkeypatch))
    r = client.post("/api/v1/assistant/pref-chat",
                    json={"message": "我想去瑞士", "locale": "zh-CN",
                          "known": {"countries": ["CH"]}})
    assert r.status_code == 200
    body = r.json()
    assert body["ai_status"] == "unavailable"
    assert body["model"] is None
    assert body["extracted"] == {}
    assert body["next_question"] == "climate"
    assert body["done"] is False
    assert body["lines"][-1] == _question_line("climate", "zh-CN")


def test_pref_chat_endpoint_mock_model(monkeypatch):
    captured: dict = {}
    provider = _mock_provider(monkeypatch, _pref_handler(captured))
    monkeypatch.setattr(router_chat, "get_provider", lambda: provider)
    r = client.post("/api/v1/assistant/pref-chat",
                    json={"message": "我想去瑞士，因为那边环境优美",
                          "locale": "zh-CN", "known": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["ai_status"] == "available"
    assert body["model"] == "openai/test-model"
    assert body["extracted"]["countries"] == ["CH"]
    assert "环境优美" in body["extracted"]["note"]
    assert "环境优美" in "\n".join(body["lines"])
    assert body["next_question"] == "climate"
    assert body["done"] is False


def test_pref_chat_endpoint_validation_errors(monkeypatch):
    monkeypatch.setattr(router_chat, "get_provider",
                        lambda: _no_key_provider(monkeypatch))
    for body in (
            {"message": ""},
            {"message": "   "},
            {"message": "x" * 501},
            {"message": "hi", "history": [{"role": "user", "content": "x"}] * 11},
            {"message": "hi", "history": [{"role": "system", "content": "x"}]},
            {"locale": "zh-CN"},
    ):
        r = client.post("/api/v1/assistant/pref-chat", json=body)
        assert r.status_code == 422, body
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"
