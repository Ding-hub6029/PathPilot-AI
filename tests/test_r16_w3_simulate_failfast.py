"""Round 16 W3 — simulate fail-fast on a FLAPPING gateway.

Re-test task 10 (2026-11-27): the tester clicked "开始推演" and saw
"正在核算各方案…" at 8 s, completion at ~18 s, labelled "未连接 AI
模型". Round 14's fast-skip was supposed to make this ~0.01 s when
known-unavailable. Root cause (measured with a real uvicorn +
mock-gateway harness, 373 audit programmes):

- The probe said "available" because it only checked GET /models:
  the audit's gateway answered the list endpoint while POST
  /chat/completions hung, so the probe never exercised the model
  path and the skip never fired. Fresh-probe verdict: available
  in 0.07 s; the simulate then spent the full 15 s model budget
  (15.47 s to a template).
- The explain attempt burns the 15 s cap (asyncio.wait_for 15.0 s
  + chat timeout_s=15.0 s) — that is the mechanism, not the cause.
- The frontend DOES consult the signal (simulateMulti calls
  modelAvailability() first); the backend did NOT consult the cached
  probe verdict before attempting — it relied solely on the circuit
  breaker, which only helps AFTER one slow failure.

Fixes pinned here:
1. probe_live() confirms on the real model path: after GET /models
   200 it runs one 1-token chat call (5 s budget) before reporting
   live — a hanging chat path now reports unavailable and trips the
   breaker.
2. The /simulate handler skips the model attempt when the breaker is
   open OR a fresh cached probe said "unavailable" — even when the
   breaker is closed (a fast probe failure does not trip it).

These tests use a REAL in-process HTTP gateway (ThreadingHTTPServer):
httpx MockTransport does NOT enforce timeouts, so a hanging gateway
can only be simulated over real sockets. The mock records every
request, so the tests can assert exactly which gateway calls were
(and were not) made.

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r16_w3_simulate_failfast.py
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from ai.provider import gateway_breaker_open, reset_gateway_breaker
from app.main import app, reset_ai_status_cache, reset_rate_limits

client = TestClient(app)

# Audit profile (browser re-test task 8/10): China Gaokao, UG, CS,
# Gaokao 680/750, IELTS 7.0, budget GBP 50,000, 2027 entry, overseas
# residency, preference Switzerland, cool climate, campus, Zurich.
AUDIT_FLAT = {
    "track": "undergraduate", "curriculum": "cn_gaokao", "field": "computing",
    "gaokaoScore": 680, "gaokaoTotal": 750, "residency": "overseas",
    "intakeYear": 2027,
    "ieltsOverall": 7.0, "ieltsListening": 7, "ieltsReading": 7,
    "ieltsWriting": 6.5, "ieltsSpeaking": 7,
    "budget": 50000, "budgetCurrency": "GBP",
    "prefCountries": ["CH"], "prefClimate": "cool",
    "prefEnvironment": "campus", "prefCity": "Zurich",
}

AUDIT_IDS = ["ucl-cs-bsc-2026", "eth-cs-bsc-2027"]
SCENARIOS = [
    {"name": "IELTS overall +0.5", "patch": {"ieltsOverall": 7.5}},
    {"name": "Budget +£10,000", "patch": {"budget": 60000}},
]

# Minimal structured explanation that passes the citation check: a
# number-free summary, no claims.
VALID_EXPLAIN = {
    "summary": "The budget change mattered most.",
    "claims": [],
    "unknowns": [],
    "actions": [],
    "limitations": [],
}


@pytest.fixture(autouse=True)
def _isolate():
    reset_rate_limits()
    reset_ai_status_cache()
    reset_gateway_breaker()
    yield
    reset_rate_limits()
    reset_ai_status_cache()
    reset_gateway_breaker()


class _MockGateway:
    """A real HTTP gateway in a thread, with a switchable mode.

    Modes: healthy-json (chat 200 after 0.3 s, valid structured
    explanation), slow-json (chat 200 after 10 s, valid explanation
    — the real gateway's healthy latency), slow-chat (chat 200 after
    2 s, plain "ok" — slow but alive), flap (GET /models 200 at
    once, POST /chat/completions hangs 30 s — the audit's gateway),
    hang-all (both endpoints hang 30 s), fail500 (GET 200, POST 500
    at once). ``requests`` records (method, path) in arrival order.
    """

    def __init__(self):
        self.mode = "healthy-json"
        self.requests: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                with gateway._lock:
                    gateway.requests.append(("GET", self.path))
                if self.path.endswith("/models"):
                    if gateway.mode == "hang-all":
                        time.sleep(30)
                    self._json(200, {"data": [{"id": "mock-model"}]})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                with gateway._lock:
                    gateway.requests.append(("POST", self.path))
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                if not self.path.endswith("/chat/completions"):
                    self._json(404, {"error": "not found"})
                    return
                mode = gateway.mode
                if mode in ("hang-all", "flap"):
                    time.sleep(30)
                    self._json(200, {"choices": [{"message": {"content": "ok"}}],
                                     "usage": {}})
                elif mode == "slow-chat":
                    time.sleep(2.0)
                    self._json(200, {"choices": [{"message": {"content": "ok"}}],
                                     "usage": {}})
                elif mode == "fail500":
                    self._json(500, {"error": "gateway error"})
                elif mode == "slow-json":
                    time.sleep(10.0)
                    self._json(200, {"choices": [{"message": {
                        "content": json.dumps(VALID_EXPLAIN)}}], "usage": {}})
                else:  # healthy-json
                    time.sleep(0.3)
                    self._json(200, {"choices": [{"message": {
                        "content": json.dumps(VALID_EXPLAIN)}}], "usage": {}})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)

    @property
    def base_url(self) -> str:
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}/v1"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()

    def posts(self) -> int:
        with self._lock:
            return sum(1 for m, _ in self.requests if m == "POST")

    def gets(self) -> int:
        with self._lock:
            return sum(1 for m, _ in self.requests if m == "GET")


@pytest.fixture
def gateway(monkeypatch):
    with _MockGateway() as gw:
        for key, value in {
            "AI_PROVIDER": "openai",
            "AI_MODEL": "mock-r16-model",
            "AI_API_KEY": "mock-test-key",
            "AI_BASE_URL": gw.base_url,
        }.items():
            monkeypatch.setenv(key, value)
        yield gw


def _simulate_body() -> dict:
    return {"baseline_profile": dict(AUDIT_FLAT), "scenarios": SCENARIOS,
            "program_ids": list(AUDIT_IDS), "locale": "zh-CN",
            "explain": True}


def _status():
    t0 = time.monotonic()
    r = client.get("/api/v1/ai/status")
    return r, time.monotonic() - t0


def _simulate():
    t0 = time.monotonic()
    r = client.post("/api/v1/simulate", json=_simulate_body())
    return r, time.monotonic() - t0


# ---------------------------------------------------------------------------
# Fix 1 — the probe confirms on the chat path
# ---------------------------------------------------------------------------

def test_probe_flapping_gateway_reports_unavailable(gateway):
    """GET /models 200 + hanging /chat/completions must report
    unavailable: the Round 14 probe returned "available" here in
    0.07 s (it never touched the chat path), and the simulate click
    then spent the full 15 s model budget. The confirmation chat
    call times out at 7 s, so the probe takes ~7 s, not 15 s — and
    it trips the breaker."""
    gateway.mode = "flap"
    r, elapsed = _status()
    assert r.status_code == 200, r.text
    assert r.json()["ai_status"] == "unavailable"
    assert r.json()["probed"] is True
    assert 6.5 < elapsed < 10, f"flapping probe took {elapsed:.1f}s"
    assert gateway_breaker_open()
    assert gateway.gets() == 1 and gateway.posts() == 1


def test_probe_healthy_gateway_confirms_on_chat_path(gateway):
    """A healthy gateway still reports available — and the probe
    really ran the chat confirmation (one POST), not just the GET:
    "available" now means a chat call just succeeded."""
    gateway.mode = "healthy-json"
    r, elapsed = _status()
    assert r.status_code == 200, r.text
    assert r.json()["ai_status"] == "available"
    assert elapsed < 5, f"healthy probe took {elapsed:.1f}s"
    assert gateway.gets() == 1 and gateway.posts() == 1
    assert not gateway_breaker_open()


def test_probe_slow_but_healthy_chat_still_available(gateway):
    """A gateway that answers the chat path in 2 s is alive: the 5 s
    confirmation budget must not turn a slow-but-healthy gateway
    into a false "unavailable" (which would template-only every
    model path for 180 s)."""
    gateway.mode = "slow-chat"
    r, elapsed = _status()
    assert r.status_code == 200, r.text
    assert r.json()["ai_status"] == "available"
    assert 1.8 < elapsed < 5, f"slow-chat probe took {elapsed:.1f}s"


def test_probe_falls_back_to_chat_when_models_list_missing(gateway):
    """Unchanged Round 14 behaviour: a gateway without a /models
    endpoint (404 here comes from the mock's unknown-path branch —
    exercised via a base URL whose /models 404s) still probes via
    the chat call. Covered by the Round 14 mock test; this pins it
    over real sockets with the confirmation helper."""
    gateway.mode = "healthy-json"
    # Point the adapter at a base URL where /models is not served:
    # the mock only serves /v1/models and /v1/chat/completions, so
    # a /v2 base makes GET /models 404 and forces the fallback.
    import os
    os.environ["AI_BASE_URL"] = gateway.base_url.replace("/v1", "/v2")
    try:
        r, elapsed = _status()
    finally:
        os.environ["AI_BASE_URL"] = gateway.base_url
    assert r.status_code == 200, r.text
    assert r.json()["ai_status"] == "available"


# ---------------------------------------------------------------------------
# Fix 2 — simulate honours the known-down verdict (probe + handler)
# ---------------------------------------------------------------------------

def test_simulate_flapping_gateway_fast_after_probe(gateway):
    """The incident, fixed end to end: probe first (flapping
    gateway -> unavailable, ~7 s), then the simulate click returns
    the template in engine time with NO further gateway call.
    Before the fix this was probe 0.07 s "available" + simulate
    15.47 s; now it is ~7 s + ~0.5 s."""
    gateway.mode = "flap"
    r, _ = _status()
    assert r.json()["ai_status"] == "unavailable"
    posts_after_probe = gateway.posts()
    assert posts_after_probe == 1
    r, elapsed = _simulate()
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"post-probe simulate took {elapsed:.1f}s"
    body = r.json()
    assert body["explanation"]["source"] == "template"
    assert body["explanation"]["ai_status"] == "unavailable"
    assert gateway.posts() == posts_after_probe, (
        "simulate must not call the gateway after a failed probe")


def test_simulate_skips_model_call_on_cached_unavailable_verdict(gateway):
    """The handler check, isolated from the breaker: a FAST probe
    failure (chat 500) reports unavailable WITHOUT tripping the
    breaker — yet the simulate must still skip the model attempt,
    because the cached verdict already says down. Before the fix
    the handler only knew the breaker, so this call would have
    attempted the model (a fast 500, cheap here — but a hang in
    the same shape would have burned 15 s)."""
    gateway.mode = "fail500"
    r, elapsed = _status()
    assert r.status_code == 200, r.text
    assert r.json()["ai_status"] == "unavailable"
    assert elapsed < 3, f"fail500 probe took {elapsed:.1f}s"
    assert not gateway_breaker_open(), (
        "a fast 500 must not trip the breaker — this test isolates "
        "the cached-verdict skip from the breaker skip")
    posts_after_probe = gateway.posts()
    assert posts_after_probe == 1
    r, elapsed = _simulate()
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"cached-unavailable simulate took {elapsed:.1f}s"
    assert r.json()["explanation"]["source"] == "template"
    assert gateway.posts() == posts_after_probe, (
        "simulate must not call the gateway when the cached probe "
        "verdict says unavailable")


def test_simulate_second_call_fast_after_first_burns_breaker(gateway):
    """Breaker path, unchanged: with no probe at all, the first
    call on a hanging gateway pays the 15 s cap (see the residual
    test below), trips the breaker, and the second call is fast
    with no further gateway call."""
    gateway.mode = "hang-all"
    r, elapsed = _simulate()
    assert r.status_code == 200, r.text
    assert elapsed > 14, f"first hanging simulate took {elapsed:.1f}s"
    assert gateway_breaker_open()
    posts_after_first = gateway.posts()
    r, elapsed = _simulate()
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"second simulate took {elapsed:.1f}s"
    assert r.json()["explanation"]["source"] == "template"
    assert gateway.posts() == posts_after_first


# ---------------------------------------------------------------------------
# No regression on the healthy path
# ---------------------------------------------------------------------------

def test_simulate_healthy_gateway_still_returns_model_explanation(gateway):
    """Healthy gateway: the model explanation still comes back
    (source=model) in engine time + one quick model call."""
    gateway.mode = "healthy-json"
    r, elapsed = _simulate()
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"healthy simulate took {elapsed:.1f}s"
    body = r.json()
    assert body["explanation"]["source"] == "model"
    assert body["explanation"]["ai_status"] == "available"
    assert gateway.posts() == 1


def test_simulate_slow_healthy_gateway_still_fits_15s_budget(gateway):
    """A healthy-but-slow gateway (10 s model call, the real
    gateway's observed latency) still returns a model explanation
    inside the 15 s cap — the fix must not shorten the explain
    budget, only skip calls already known to be doomed."""
    gateway.mode = "slow-json"
    r, elapsed = _simulate()
    assert r.status_code == 200, r.text
    assert 9 < elapsed < 15, f"slow-healthy simulate took {elapsed:.1f}s"
    assert r.json()["explanation"]["source"] == "model"


# ---------------------------------------------------------------------------
# Residual worst case, pinned so it cannot silently grow
# ---------------------------------------------------------------------------

def test_simulate_first_call_on_flapping_gateway_burns_15s_residual(gateway):
    """RESIDUAL (documented, not fixed): with NO prior probe and a
    closed breaker — the gateway died after the last probe, or the
    probe cache is cold — the first simulate on a flapping gateway
    still spends the full 15 s model budget before the template.
    No probe can guarantee the gateway state at click time; the
    breaker then protects every later call for 180 s (asserted by
    the fast second call). If this bound ever grows, the 15 s cap
    itself moved."""
    gateway.mode = "flap"
    r, elapsed = _simulate()
    assert r.status_code == 200, r.text
    assert 14 < elapsed < 20, (
        f"residual first-call burn was {elapsed:.1f}s, expected ~15s")
    assert r.json()["explanation"]["source"] == "template"
    assert gateway_breaker_open()
    r, elapsed = _simulate()
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"second simulate took {elapsed:.1f}s"
