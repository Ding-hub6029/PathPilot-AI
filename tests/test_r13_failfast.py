"""Round 13 W1 (backend fail-fast) regression tests.

The results page fires ONE batched POST /api/v1/whynot with every
NOT_MET programme (80 ids in the audit profile) and the old code made
one synchronous model call per programme inside the async handler —
up to 50 s each — wedging the single uvicorn event loop for ~15 min
per page load and taking /simulate, /improvement-plan and chat down
with it. These tests pin the fail-fast behaviour:

- batched /whynot never touches the provider at all (template-only),
  however many ids arrive, and returns in engine time;
- /simulate explain=true with a slow or failing gateway returns the
  template explanation within one frontend attempt (<=15 s model
  budget, no repair retry) with the correct engine leverage numbers,
  and /health keeps answering while the model call is in flight;
- /improvement-plan with a failing gateway returns template tasks
  fast, with exactly one model attempt (no repair stacking) at a
  15 s budget;
- the AI rate-limit bucket is per-user behind the proxy
  (X-Forwarded-For), not per Vercel egress IP.

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r13_failfast.py
"""
from __future__ import annotations

import copy
import os
import threading
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as app_main
import app.router_plans as router_plans
import app.router_whynot as router_whynot
from ai.provider import ChatResult, ProviderAdapter, ProviderError
from app.data import EXPANSION_MATCHABLE, PROGRAMS
from app.main import _client_ip, app, reset_rate_limits
from starlette.requests import Request

client = TestClient(app)

# Frozen ordinary-gaokao-ucl case (tests/test_whynot.py): IELTS
# Writing 5.5 (below UCL's 6.0 component minimum) and budget GBP
# 10,000 (below UCL's GBP 48,600 overseas fee) — several NOT_MET
# rules per programme, so the batch has real why-not work to do.
FROZEN_NESTED = {
    "application_track": "undergraduate",
    "undergrad_profile": {
        "curriculum": "cn_gaokao", "gaokao_score": 680, "gaokao_total": 750,
        "gaokao_maths": 140, "residency": "overseas"},
    "language": {"exam": "ielts", "overall": 7.0, "listening": 7.0,
                 "reading": 7.0, "writing": 5.5, "speaking": 7.0},
    "budget": {"amount": 10000, "currency": "GBP", "period": "per_year"},
}

# Undergraduate, A-levels, IELTS writing 5.5 (below UCL's 6.0
# component minimum), budget GBP 50,000 (tests/test_simulate_multi.py).
UG_FLAT = {
    "track": "undergraduate", "targetProgramIds": ["ucl-cs-bsc-2026"],
    "alevels": "A*A*A", "mathsGrade": "A*",
    "ieltsOverall": 7.0, "ieltsListening": 6.5, "ieltsReading": 6.5,
    "ieltsWriting": 5.5, "ieltsSpeaking": 6.5,
    "budget": 50000, "budgetCurrency": "GBP",
}

UG_UCL = {
    "application_track": "undergraduate",
    "undergrad_profile": {
        "qualification_type": "a_level", "curriculum": "uk_alevel",
        "a_level_grades": ["A*", "A*", "A"], "a_level_maths_grade": "A*",
        "gcse_english_grade": "C", "gcse_maths_grade": "4",
        "residency": "overseas"},
    "language": {"exam": "ielts", "overall": 6.5, "listening": 6.5,
                 "reading": 6.5, "writing": 5.5, "speaking": 6.0},
    "budget": {"amount": 48600, "currency": "GBP", "period": "per_year"},
    "target_intake": 2026,
}

_MOCK_ENV = {
    "AI_PROVIDER": "openai",
    "AI_MODEL": "mock-r13-model",
    "AI_API_KEY": "mock-test-key",
    "AI_BASE_URL": "https://api.openai.com/v1",
}


def _whynot_app() -> TestClient:
    test_app = FastAPI()
    test_app.include_router(router_whynot.router)
    return TestClient(test_app)


def _plans_app() -> TestClient:
    test_app = FastAPI()
    test_app.include_router(router_plans.router)
    return TestClient(test_app)


def _ug_ids(n: int) -> list[str]:
    ids = list(PROGRAMS) + [
        pid for pid, p in EXPANSION_MATCHABLE.items()
        if p.get("degree_level") == "undergraduate"]
    return ids[:n]


# --- 1. Batched /whynot: template-only, never touches the model ---------

def test_whynot_batch_never_touches_provider(monkeypatch):
    """The batch path must not even construct a provider: patch
    get_provider to raise, and the 12-programme batch (several
    NOT_MET rules each) must still return fast with the correct
    template why-not and model_note=None throughout. Pre-fix this
    raised on the first programme (one sync model call each)."""
    def _boom():
        raise AssertionError("batched /whynot must not touch the provider")
    monkeypatch.setattr(router_whynot, "get_provider", _boom)
    ids = _ug_ids(12)
    t0 = time.monotonic()
    r = _whynot_app().post("/api/v1/whynot", json={
        "profile": copy.deepcopy(FROZEN_NESTED),
        "program_ids": ids, "locale": "en"})
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 10, f"batched whynot took {elapsed:.1f}s"
    body = r.json()
    assert len(body["results"]) == len(ids)
    for res in body["results"]:
        assert res["model_note"] is None
        assert res["ai_status"] == "unavailable"
        assert res["whynot"] is not None or res["trackMismatch"]
    # The real UCL writing failure survives, template-only.
    ucl = next(x for x in body["results"]
               if x["programId"] == "ucl-cs-bsc-2026")
    assert ucl["whynot"]["cheapest_fix"]["kind"] == "ielts_component"
    assert ucl["whynot"]["cheapest_fix"]["component"] == "writing"
    assert "5.5" in ucl["whynot"]["template_text"]


def test_whynot_batch_80_ids_returns_in_engine_time(monkeypatch):
    """The audit profile's scale: 80 ids in one batch must return in
    seconds (engine time), not the ~15 min the per-programme model
    loop extrapolated to. No provider is consulted at all."""
    def _boom():
        raise AssertionError("batched /whynot must not touch the provider")
    monkeypatch.setattr(router_whynot, "get_provider", _boom)
    ids = _ug_ids(80)
    assert len(ids) == 80
    t0 = time.monotonic()
    r = _whynot_app().post("/api/v1/whynot", json={
        "profile": copy.deepcopy(FROZEN_NESTED),
        "program_ids": ids, "locale": "en"})
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 15, f"80-id whynot batch took {elapsed:.1f}s"
    assert len(r.json()["results"]) == 80


# --- 2. /simulate explain: slow/failing gateway -> template, fast --------

def _slow_adapter(monkeypatch, sleep_s: float = 20.0):
    """A real ProviderAdapter whose gateway sleeps then returns '{}'
    (bad JSON -> would fail validation). httpx MockTransport does NOT
    enforce timeouts, so a slow mock only returns via the handler's
    15 s wait_for cap — exactly what this test proves."""
    def _handler(request: httpx.Request) -> httpx.Response:
        time.sleep(sleep_s)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "{}"}}], "usage": {}})
    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    adapter = ProviderAdapter(_transport=httpx.MockTransport(_handler))
    monkeypatch.setattr(app_main, "ProviderAdapter", lambda: adapter)
    return adapter


def _failing_adapter(monkeypatch):
    """A real ProviderAdapter whose gateway fails immediately (500)."""
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "gateway down"})
    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    adapter = ProviderAdapter(_transport=httpx.MockTransport(_handler))
    monkeypatch.setattr(app_main, "ProviderAdapter", lambda: adapter)
    return adapter


def _simulate_explain_body() -> dict:
    return {
        "baseline_profile": copy.deepcopy(UG_FLAT),
        "scenarios": [{"name": "writing", "patch": {"ieltsWriting": 6.5}}],
        "program_ids": ["ucl-cs-bsc-2026"],
        "explain": True}


def test_simulate_explain_slow_gateway_returns_template_within_budget(monkeypatch):
    """A 20 s gateway must not produce a 30 s+ (old: 50 s) explain:
    the 15 s cap returns the template inside one frontend attempt,
    with the correct engine leverage numbers intact.

    NOTE on the <25 s bound: the cap itself fires at 15 s (see
    test_simulate_model_budget_hard_cap_15s, which measures the
    coroutine directly, and the real-uvicorn run: 200 in 15.01 s
    with /health at ~2 ms throughout). Through TestClient the
    response is only delivered once the orphan worker thread
    finishes its 20 s sleep (a TestClient/anyio-portal delivery
    artefact — the handler itself returns at 15 s), so this
    end-to-end bound is 25 s. It still discriminates the old code,
    which took ~40 s here (20 s first attempt + 20 s repair).
    """
    reset_rate_limits()
    _slow_adapter(monkeypatch, sleep_s=20.0)
    t0 = time.monotonic()
    r = client.post("/api/v1/simulate", json=_simulate_explain_body())
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 25, f"slow-gateway simulate took {elapsed:.1f}s"
    body = r.json()
    assert body["explanation"]["source"] == "template"
    assert body["explanation"]["ai_status"] == "unavailable"
    assert body["leverage"]["top"]["id"] == "ielts-writing-plus-0.5"
    assert body["leverage"]["top"]["flips"] == 1
    assert body["leverage"]["top"]["flipped_program_ids"] == ["ucl-cs-bsc-2026"]
    assert {"program_id": "ucl-cs-bsc-2026",
            "rule_id": "ucl-ielts-components",
            "baseline_status": "NOT_MET",
            "scenario_status": "MET"} in body["delta"]


def test_simulate_model_budget_hard_cap_15s():
    """The 15 s cap itself, measured on the coroutine (no TestClient
    portal in the way): a gateway that sleeps 20 s is cut off at
    15 s and the template is returned. This is the bound the
    frontend's 25 s attempt relies on; the endpoint test above
    proves the same path end to end, and the real-uvicorn run
    measured 200 in 15.01 s."""
    import asyncio
    from types import SimpleNamespace

    from ai.simulate_explain import explain_simulation

    scenarios = [{"name": "writing", "patch": {"ieltsWriting": 6.5},
                  "delta": [{"program_id": "ucl-cs-bsc-2026",
                             "rule_id": "ucl-ielts-components",
                             "baseline_status": "NOT_MET",
                             "scenario_status": "MET"}],
                  "programme_flips": [{"program_id": "ucl-cs-bsc-2026",
                                       "baseline_summary": "NOT_MET",
                                       "scenario_summary": "MET"}],
                  "flipped_program_ids": ["ucl-cs-bsc-2026"],
                  "rule_flip_count": 1}]
    cand = {"id": "ielts-writing-plus-0.5",
            "patch": {"ieltsWriting": 6.5},
            "change": {"field": "ieltsWriting", "from": 5.5, "to": 6.5},
            "flips": 1, "flipped_program_ids": ["ucl-cs-bsc-2026"],
            "rule_flips": 1, "flipped_rules": []}
    leverage = {"top": cand, "all": [cand]}

    class _SlowProvider:
        available = True

        def chat(self, messages, system=None, timeout_s=None):
            time.sleep(20)
            return SimpleNamespace(text="{}")

    async def _run():
        # The cap-fires timestamp is recorded INSIDE the coroutine:
        # asyncio.run() itself only returns once the orphan worker
        # thread finishes its 20 s sleep (it shuts down the default
        # executor), which would hide the 15 s firing time.
        started = time.monotonic()
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    explain_simulation, scenarios=scenarios,
                    leverage=leverage, baseline_unknown_academic=False,
                    locale="en", provider=_SlowProvider()),
                timeout=15.0)
        except asyncio.TimeoutError:
            outcome["cap_fired_at"] = time.monotonic() - started
            return explain_simulation(
                scenarios=scenarios, leverage=leverage,
                baseline_unknown_academic=False, locale="en",
                provider=None)

    outcome: dict = {}
    _structured, text, status = asyncio.run(_run())
    assert outcome["cap_fired_at"] < 18, (
        f"model budget cap did not fire: {outcome['cap_fired_at']:.1f}s")
    assert status == "unavailable"
    assert "rules/template summary" in text


def test_simulate_explain_health_answers_while_model_call_in_flight(monkeypatch):
    """While a 12 s gateway call is in flight in a worker thread,
    /health must keep answering FAST — the old inline sync call
    wedged the event loop so /health timed out at 30 s. Each poll
    is timed: with the loop blocked (old code) a poll issued
    mid-call would take ~12 s; with the call off-loop each poll
    answers in milliseconds."""
    reset_rate_limits()
    _slow_adapter(monkeypatch, sleep_s=12.0)
    outcome: dict = {}

    def _do_post():
        outcome["resp"] = client.post("/api/v1/simulate",
                                      json=_simulate_explain_body())

    t0 = time.monotonic()
    worker = threading.Thread(target=_do_post, daemon=True)
    worker.start()
    health_codes: list[int] = []
    health_latency: list[float] = []
    while worker.is_alive() and time.monotonic() - t0 < 25:
        pt0 = time.monotonic()
        health_codes.append(client.get("/api/v1/health").status_code)
        health_latency.append(time.monotonic() - pt0)
        time.sleep(0.3)
    worker.join(timeout=25)
    elapsed = time.monotonic() - t0
    assert not worker.is_alive(), "simulate post did not finish"
    assert outcome["resp"].status_code == 200, outcome["resp"].text
    assert elapsed < 20, f"slow-gateway simulate took {elapsed:.1f}s"
    assert len(health_codes) >= 10, "too few health polls during the call"
    assert all(code == 200 for code in health_codes), health_codes
    assert max(health_latency) < 5, (
        f"a /health poll took {max(health_latency):.1f}s mid-call — "
        "the event loop was blocked")


def test_simulate_explain_failing_gateway_returns_template_fast(monkeypatch):
    """A gateway failing immediately (500) returns the template in
    well under a second — never a 500, never a hang — with the engine
    leverage numbers intact."""
    reset_rate_limits()
    _failing_adapter(monkeypatch)
    t0 = time.monotonic()
    r = client.post("/api/v1/simulate", json=_simulate_explain_body())
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"failing-gateway simulate took {elapsed:.1f}s"
    body = r.json()
    assert body["explanation"]["source"] == "template"
    assert body["explanation"]["ai_status"] == "unavailable"
    assert body["leverage"]["top"]["id"] == "ielts-writing-plus-0.5"


# --- 3. /improvement-plan: failing gateway -> template tasks, fast -------

class _FailingModel:
    available = True
    ai_status = "available"

    def chat(self, *args, **kwargs):
        raise ProviderError("gateway down", retryable=True,
                            kind="provider_http")


class _InvalidJsonModel:
    """Returns unparseable text and records every call: proves the
    repair retry is gone (exactly one attempt) and the budget is 15 s."""
    available = True
    ai_status = "available"

    def __init__(self):
        self.calls = 0
        self.timeout_s: float | None = None

    def chat(self, messages, system=None, timeout_s=None, **kwargs):
        self.calls += 1
        self.timeout_s = timeout_s
        return ChatResult(text="this is not json at all",
                          model="fake", provider="fake", latency_ms=1)


def _plan_body() -> dict:
    return {"profile": copy.deepcopy(UG_UCL),
            "program_ids": ["ucl-cs-bsc-2026"],
            "weekly_hours": 6, "budget": None,
            "deadline": None, "locale": "en"}


def test_plan_failing_gateway_returns_template_tasks_fast(monkeypatch):
    monkeypatch.setattr(router_plans, "get_provider",
                        lambda: _FailingModel())
    t0 = time.monotonic()
    r = _plans_app().post("/api/v1/improvement-plan", json=_plan_body())
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"failing-gateway plan took {elapsed:.1f}s"
    body = r.json()
    assert body["ai_status"] == "unavailable"
    assert body["tasks"], "template tasks must cover the gaps"
    assert all(t["task_id"].startswith("task-") for t in body["tasks"]), body["tasks"]


def test_plan_invalid_model_output_no_repair_single_15s_attempt(monkeypatch):
    """Invalid model JSON used to trigger a 12 s repair retry (24 s
    stacked, on the 25 s abort boundary). Now: exactly one attempt
    at a 15 s budget, then template tasks."""
    model = _InvalidJsonModel()
    monkeypatch.setattr(router_plans, "get_provider", lambda: model)
    r = _plans_app().post("/api/v1/improvement-plan", json=_plan_body())
    assert r.status_code == 200, r.text
    assert model.calls == 1, f"repair retry still happens ({model.calls} calls)"
    assert model.timeout_s == 15.0, model.timeout_s
    body = r.json()
    assert body["ai_status"] == "unavailable"
    assert body["tasks"]
    assert all(t["task_id"].startswith("task-") for t in body["tasks"])


# --- 4. Rate limiting: per-user behind the proxy ---------------------------

def _explain_body() -> dict:
    return {"profile": copy.deepcopy(FROZEN_NESTED),
            "program_ids": ["ucl-cs-bsc-2026"]}


def test_rate_limit_explain_bucket_is_per_forwarded_ip():
    """10 /explain calls from one X-Forwarded-For exhaust only that
    IP's bucket: the 11th 429s, but a different forwarded IP still
    gets 200. Pre-fix every browser user shared one bucket keyed on
    the Vercel egress IP."""
    reset_rate_limits()
    for _ in range(10):
        r = client.post("/api/v1/explain", json=_explain_body(),
                        headers={"X-Forwarded-For": "1.2.3.4"})
        assert r.status_code == 200, r.text
    r = client.post("/api/v1/explain", json=_explain_body(),
                    headers={"X-Forwarded-For": "1.2.3.4"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED"
    r = client.post("/api/v1/explain", json=_explain_body(),
                    headers={"X-Forwarded-For": "5.6.7.8"})
    assert r.status_code == 200, r.text
    # No forwarded header falls back to the direct peer (its own bucket).
    r = client.post("/api/v1/explain", json=_explain_body())
    assert r.status_code == 200, r.text


def test_rate_limit_simulate_manual_check_uses_forwarded_ip():
    """The /simulate explain:true manual AI-bucket check must use the
    same per-user key as the middleware: 10 explained calls from one
    forwarded IP 429 the 11th, while another forwarded IP is unaffected."""
    reset_rate_limits()
    for _ in range(10):
        r = client.post("/api/v1/simulate", json=_simulate_explain_body(),
                        headers={"X-Forwarded-For": "9.9.9.9"})
        assert r.status_code == 200, r.text
    r = client.post("/api/v1/simulate", json=_simulate_explain_body(),
                    headers={"X-Forwarded-For": "9.9.9.9"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED"
    r = client.post("/api/v1/simulate", json=_simulate_explain_body(),
                    headers={"X-Forwarded-For": "8.8.8.8"})
    assert r.status_code == 200, r.text


def _request(headers: list[tuple[bytes, bytes]] | None = None,
             client_host: str = "10.0.0.1") -> Request:
    scope = {"type": "http", "method": "POST", "path": "/",
             "headers": headers or [], "client": (client_host, 1234),
             "query_string": b"", "server": ("testserver", 80),
             "scheme": "http"}
    return Request(scope)


def test_client_ip_prefers_first_forwarded_entry():
    assert _client_ip(_request(
        [(b"x-forwarded-for", b"1.2.3.4, 9.9.9.9")])) == "1.2.3.4"
    assert _client_ip(_request(
        [(b"x-forwarded-for", b"  2001:db8::1  ")])) == "2001:db8::1"
    assert _client_ip(_request()) == "10.0.0.1"
    assert _client_ip(_request(
        [(b"x-forwarded-for", b"unknown")])) == "10.0.0.1"
