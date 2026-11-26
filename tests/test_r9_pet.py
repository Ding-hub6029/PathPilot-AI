"""PathPilot Round 9 (W3) — pet/assistant retrieval, counts, chat latency.

Regression tests for the 2026-11-26 live re-test findings:

- R3 (P0): the pet answered "瑞士有哪些好学校？" with "没有任何瑞士
  院校或项目" while the results page showed 5 Swiss programmes. The
  pet/assistant retrieval must cover the FULL verified catalogue (all
  countries), so it can never claim a covered country has no data.
- R4 (P1): contradictory Swiss counts across the site. Every count in
  a chat evidence line is labelled with its scope (all levels/fields).
- R6-backend (P1): chat replies took 10-45 s. The synchronous model
  call ran inside an async endpoint and blocked the single uvicorn
  event loop; a slow chat must not wedge /health. Round 10: one turn
  is now ONE model call with a 15 s budget and no repair retry — a
  bad output falls back to the template at once, so a turn can no
  longer stack past the frontend's per-attempt abort into 45-60 s.
"""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai.assistant import ask, country_answer, suggest
from ai.chat import (_country_programme_picks, _country_source,
                     _retrieve, answer, country_evidence_line,
                     evidence_cities_line)
from ai.provider import ChatResult, ProviderAdapter, ProviderError
from app import router_chat

_test_app = FastAPI()
_test_app.include_router(router_chat.router)


@_test_app.get("/api/v1/health")
def _health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# R3: country questions name real institutions/programmes, never "no data"
# ---------------------------------------------------------------------------

def test_ask_switzerland_names_eth_epfl_uzh_and_25_programmes():
    r = ask("瑞士有哪些好学校？", "zh-CN")
    joined = "\n".join(r["lines"])
    assert "ETH Zurich" in joined
    assert "Lausanne" in joined or "洛桑" in joined
    assert "University of Zurich" in joined
    assert "25" in joined
    assert "全部学位/方向" in joined
    assert "没有" not in joined and "查不到" not in joined
    assert r["program_id"] == "eth-cs-bsc-2027"
    assert r["evidence_url"].startswith("https://ethz.ch/")


def test_ask_other_covered_countries_never_claim_zero_data():
    # The same false-zero risk, checked for France, Germany and the USA.
    for question, needle, total in (
            ("法国有哪些好学校？", "法国", 21),
            ("德国有哪些好大学", "德国", 24),
            ("美国有哪些好学校", "美国", 218)):
        r = ask(question, "zh-CN")
        joined = "\n".join(r["lines"])
        assert needle in joined, joined
        assert str(total) in joined, joined
        assert "没有" not in joined and "查不到" not in joined, joined
        assert r["program_id"] is not None
        assert r["evidence_url"] is not None
        assert r["evidence_url"].startswith("https://")


def test_ask_uncovered_country_still_honest_unknown():
    r = ask("南极洲有哪些好学校？", "zh-CN")
    assert "不知道" in "\n".join(r["lines"])
    assert r["program_id"] is None


def test_ask_country_mention_is_not_a_country_question():
    # A preference statement ("我想去瑞士…") is not a question: the
    # template stays unknown so the pref-chat flow's own retrieval
    # (climate cities) is untouched.
    r = ask("我想去瑞士，因为那边环境优美", "zh-CN")
    assert "不知道" in "\n".join(r["lines"])
    assert r["program_id"] is None


def test_country_answer_ch_counts_all_levels_fields():
    r = country_answer("CH", "zh-CN")
    assert r is not None
    assert "25" in r["lines"][0]
    assert "全部学位/方向" in r["lines"][0]
    assert country_answer("AQ", "en") is None


def test_retrieve_switzerland_carries_country_source_and_swiss_picks():
    template, sources, pids = _retrieve("瑞士有哪些好学校？", "zh-CN",
                                        country_programmes=True)
    ids = [s.id for s in sources]
    assert "country:ch" in ids
    country_src = next(s for s in sources if s.id == "country:ch")
    assert "25 verified programmes in total (all levels and fields)" \
        in country_src.excerpt
    assert "ETH Zurich" in country_src.excerpt
    picks = [p["id"] for p in _country_programme_picks("CH")]
    assert picks[0] == "eth-cs-bsc-2027"
    assert "zurich-informatics-bsc-2027" in picks
    assert all(pid in pids for pid in picks)
    # The model must be able to cite a Swiss programme, not just ETH.
    assert any(pid.startswith("epfl-") for pid in pids)


def test_retrieve_switzerland_pref_path_unchanged():
    # The pref-chat flow leaves country_programmes off: its retrieval
    # is still exactly the climate cities, pinned by test_pref_chat.
    _, sources, _ = _retrieve("我想去瑞士，因为那边环境优美", "zh-CN",
                              countries=["CH"], climate_class=None)
    assert [s.id for s in sources] == ["climate:zurich",
                                        "climate:lausanne"]


def test_chat_switzerland_mock_model_names_swiss_programme(monkeypatch):
    # A well-behaved mock model that cites the country source must
    # produce an available answer naming a Swiss programme — never a
    # "no Swiss data" claim.
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        content = body["messages"][-1]["content"]
        envelope = (captured["envelope"] if content.startswith(
            "Your previous output failed validation")
            else json.loads(content))
        captured["envelope"] = envelope
        catalog = envelope.get("evidence_catalog", [])
        hit = next((c for c in catalog if c["id"] == "country:ch"), None)
        assert hit is not None, "no country:ch source in the catalogue"
        text = hit["excerpt"].split(". Including:")[0].strip() + "."
        payload = {
            "summary": "瑞士有已核实的学校，例如 ETH Zurich。",
            "claims": [{"text": text, "kind": "fact", "rule_ids": [],
                        "evidence_ids": ["country:ch"]}],
            "unknowns": [], "actions": [], "limitations": []}
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(
                payload, ensure_ascii=False)}}], "usage": {}})

    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")
    provider = ProviderAdapter(_transport=httpx.MockTransport(handler))
    r = answer("瑞士有哪些好学校？", "zh-CN", provider=provider)
    assert r["ai_status"] == "available"
    joined = "\n".join(r["lines"])
    assert "ETH Zurich" in joined
    assert "没有任何瑞士" not in joined
    assert "没有瑞士" not in joined
    assert r["evidence_url"] is not None
    assert r["evidence_url"].startswith("https://ethz.ch/")


def test_chat_switzerland_no_key_fallback_names_swiss_schools(monkeypatch):
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    r = answer("瑞士有哪些好学校？", "zh-CN", provider=ProviderAdapter())
    assert r["ai_status"] == "unavailable"
    joined = "\n".join(r["lines"])
    assert "ETH Zurich" in joined and "25" in joined
    assert "没有任何瑞士" not in joined


def test_suggest_ch_returns_ch_programme_without_band_claim(monkeypatch):
    r = suggest("undergraduate", "CH", "mid", "zh-CN")
    assert r["program_id"] == "zurich-informatics-bsc-2027"
    assert "CHF 2,440" in "\n".join(r["lines"])
    assert "预算带" not in "\n".join(r["lines"])
    assert r["fee_fit"] == "unknown"
    r_us = suggest("undergraduate", "US", "mid", "en")
    assert r_us["program_id"] is not None
    assert r_us["evidence_url"].startswith("https://")


# ---------------------------------------------------------------------------
# R4: every chat count is labelled with its scope
# ---------------------------------------------------------------------------

def test_evidence_cities_line_labels_all_levels_fields_scope():
    from ai.chat import _climate_evidence
    sources, _ = _climate_evidence("cool", countries=["CH"])
    line = evidence_cities_line(sources, "zh-CN")
    assert line is not None
    assert "Zurich" in line and "Lausanne" in line
    assert "14" in line and "11" in line
    assert "全部学位/方向" in line
    line_en = evidence_cities_line(sources, "en")
    assert "all levels/fields" in line_en


def test_climate_source_excerpt_states_scope():
    from ai.chat import _climate_source
    src = _climate_source("Zurich", 14)
    assert "Verified programmes in Zurich (all levels and fields): 14." \
        in src.excerpt


def test_country_evidence_line_states_scoped_total():
    _, sources, _ = _retrieve("瑞士有哪些好学校？", "zh-CN",
                              country_programmes=True)
    line = country_evidence_line(sources, "zh-CN")
    assert line is not None
    assert "瑞士" in line and "25" in line
    assert "全部学位/方向" in line
    assert "ETH Zurich" in line
    line_en = country_evidence_line(sources, "en")
    assert "Switzerland" in line_en
    assert "all levels and fields" in line_en
    assert country_evidence_line([], "zh-CN") is None


# ---------------------------------------------------------------------------
# R6-backend: timeouts tightened, slow chat must not block /health
# ---------------------------------------------------------------------------

def _openai_reply(payload_text: str) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"content": payload_text}}], "usage": {}})


def test_provider_achat_parity_with_sync_chat(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_reply("hello from the model")

    provider = ProviderAdapter(_transport=httpx.MockTransport(handler))
    sync = provider.chat([{"role": "user", "content": "hi"}])
    assert sync.text == "hello from the model"
    assert (sync.provider, sync.model) == ("openai", "test-model")
    async_result = asyncio.run(provider.achat(
        [{"role": "user", "content": "hi"}]))
    assert async_result.text == "hello from the model"
    assert (async_result.provider, async_result.model) == ("openai", "test-model")


def test_provider_achat_http500_raises_provider_error(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")
    provider = ProviderAdapter(_transport=httpx.MockTransport(
        lambda request: httpx.Response(500, json={"error": "boom"})))
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.achat([{"role": "user", "content": "hi"}]))
    assert exc.value.kind == "provider_http"


def test_chat_invalid_output_falls_back_after_one_call(monkeypatch):
    # Round 10: one model call per turn, NO repair retry. The first
    # attempt fails validation (cites an unknown evidence id), so the
    # template fallback runs at once: exactly one call, 15 s budget
    # (was 20 s first attempt + 15 s repair, which stacked past the
    # frontend's 25 s per-attempt abort into 45-60 s turns).
    timeouts: list[float | None] = []
    calls = {"n": 0}

    class _RecordingProvider:
        available = True

        def chat(self, messages, system=None, timeout_s=None,
                 max_tokens=None, temperature=0.2):
            timeouts.append(timeout_s)
            calls["n"] += 1
            bad = {"summary": "UCL 学费 GBP 48,600。",
                   "claims": [{"text": "UCL 学费 GBP 48,600。",
                               "kind": "fact", "rule_ids": [],
                               "evidence_ids": ["src:made-up"]}],
                   "unknowns": [], "actions": [], "limitations": []}
            return ChatResult(text=json.dumps(bad, ensure_ascii=False),
                              model="test-model", provider="openai",
                              latency_ms=1)

    r = answer("UCL本科的学费是多少", "zh-CN",
               provider=_RecordingProvider())
    assert r["ai_status"] == "unavailable"
    assert calls["n"] == 1, calls
    assert timeouts == [15.0], timeouts
    # The template fallback still answers the fee question.
    assert "48,600" in "\n".join(r["lines"])


def test_slow_chat_does_not_block_health(monkeypatch):
    # A 3 s model call in flight must not delay /health: the router
    # runs the synchronous answer in a worker thread, so the event
    # loop stays free. (Before the fix the async endpoint blocked
    # the loop for the whole turn and /health queued behind it.)
    class _SlowProvider:
        available = True

        def chat(self, messages, system=None, timeout_s=None,
                 max_tokens=None, temperature=0.2):
            time.sleep(3.0)
            raise ProviderError("slow gateway", kind="timeout")

    monkeypatch.setattr(router_chat, "get_provider",
                        lambda: _SlowProvider())

    async def run():
        transport = httpx.ASGITransport(app=_test_app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://test") as client:
            chat_task = asyncio.create_task(client.post(
                "/api/v1/assistant/chat",
                json={"message": "瑞士有哪些好学校？", "locale": "zh-CN"}))
            await asyncio.sleep(0.2)  # let the chat turn start
            started = time.monotonic()
            health = await client.get("/api/v1/health")
            health_latency = time.monotonic() - started
            chat_resp = await chat_task
            return health, health_latency, chat_resp

    health, health_latency, chat_resp = asyncio.run(run())
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health_latency < 2.0, f"/health took {health_latency:.2f}s during a slow chat"
    assert chat_resp.status_code == 200
    # The slow turn still falls back honestly to the template.
    body = chat_resp.json()
    assert body["ai_status"] == "unavailable"
    assert "ETH Zurich" in "\n".join(body["lines"])


def test_chat_endpoint_switzerland_no_key(monkeypatch):
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(router_chat, "get_provider",
                        lambda: ProviderAdapter())
    client = TestClient(_test_app)
    r = client.post("/api/v1/assistant/chat",
                    json={"message": "瑞士有哪些好学校？", "locale": "zh-CN"})
    assert r.status_code == 200
    body = r.json()
    assert body["ai_status"] == "unavailable"
    assert "ETH Zurich" in "\n".join(body["lines"])
    assert "25" in "\n".join(body["lines"])
    assert any(s["id"] == "country:ch" for s in body["sources"])
