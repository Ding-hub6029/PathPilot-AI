"""Round 18 W2 — devil-chat and simulate latency on a down/flapping gateway.

Re-test task 12 (2026-11-27 10:19–10:24): the devil reply took
~25–30 s of "正在查已核实资料…" before the labelled offline
template (the parent's curl of the same call took 0.5 s), and the
"开始推演" click at 10:23 still showed "正在核算各方案…" at 10 s
(the parent's curl minutes earlier measured 3.85 s via the cached
skip).

Root causes, measured with a real uvicorn + mock-gateway harness
(894 programmes, 601 matchable, audit profile) BEFORE the fix:

- Devil: one turn is exactly one 15 s model budget when the breaker
  is closed (15.09 s flap / 15.39 s hang-all, cold) and 0.02 s when
  it is open. The browser's 25–30 s is the auto-suggest turn on
  panel open (~10 s, gateway briefly up) PLUS the devil turn's
  15 s burn as the first call after the gateway died — the breaker
  only trips AFTER a slow failure and only lasted 60 s, the same
  60 s as the probe cache, so both expired together and the next
  action paid the full budget again.
- Simulate click path: probe 7.23 s (flapping gateway, cold cache)
  + engine 2.42 s = 9.65 s cold, vs 2.88 s warm. The 60 s frontend
  cache, the 60 s backend probe cache and the 60 s breaker had all
  expired between the 10:18 check and the 10:23 click.
- /ai/status re-probed even with the breaker open: a stale-cache
  read cost 7.14 s on a flapping gateway although the breaker
  already knew the gateway was down.

Fixes pinned here:
1. The breaker cooldown is 180 s (provider.GATEWAY_BREAKER_COOLDOWN_S):
   it OUTLIVES the 60 s probe cache, so a known-down gateway stays
   skipped between probes; the probe bypasses the breaker and clears
   it on success, so recovery is detected by the next probe after
   expiry at the latest.
2. /ai/status answers "unavailable" at once while the breaker is
   open instead of re-probing (a stale cached "unavailable" is
   returned as-is; with no cached verdict a synthetic unavailable
   payload is returned). A stale cached "available" never
   short-circuits — the breaker is fresher evidence.
3. The frontend warms the verdict while the results page is open
   (SimulatePanel: on mount, every 45 s, on focus — TS-only, so
   pinned by tsc/build and the browser re-test, not here): both
   caches stay fresh and failed probes re-trip the breaker while
   the gateway stays down, so the click path is engine time only.

Residual (documented, not fixed): the FIRST model call after the
gateway dies — cold breaker, cold probe cache — still burns the
15 s model budget; no cache can know the gateway died since the
last probe. The fixes bound every call after that first burn.

These tests use a REAL in-process HTTP gateway (ThreadingHTTPServer):
httpx MockTransport does NOT enforce timeouts, so a hanging gateway
can only be simulated over real sockets. The mock records every
request, so the tests can assert exactly which gateway calls were
(and were not) made.

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r18_w2_latency.py
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

import ai.provider as provider_mod
import app.main as app_main
from ai.provider import (
    GATEWAY_BREAKER_COOLDOWN_S,
    gateway_breaker_open,
    reset_gateway_breaker,
)
from app.main import app, reset_ai_status_cache, reset_rate_limits

client = TestClient(app)

# Audit profile (browser re-test task 12): China Gaokao, UG, CS,
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
DEVIL_PROFILE = {
    "countries": ["CH"], "climate": "cool", "level": "undergraduate",
    "budget_amount": 50000, "budget_currency": "GBP",
    "budget_period": "per_year", "city": "Zurich",
}
DEVIL_MESSAGE = "瑞士适合我吗？我想要凉爽的气候。"
SCENARIOS = [
    {"name": "IELTS overall +0.5", "patch": {"ieltsOverall": 7.5}},
    {"name": "IELTS Writing +0.5", "patch": {"ieltsWriting": 7.0}},
    {"name": "Budget +£10,000", "patch": {"budget": 60000}},
]
AUDIT_IDS_2 = ["ucl-cs-bsc-2026", "eth-cs-bsc-2027"]

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
    explanation), flap (GET /models 200 at once, POST
    /chat/completions hangs 30 s — the audit's gateway), hang-all
    (both endpoints hang 30 s). ``requests`` records (method, path)
    in arrival order.
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
            "AI_MODEL": "mock-r18-model",
            "AI_API_KEY": "mock-test-key",
            "AI_BASE_URL": gw.base_url,
        }.items():
            monkeypatch.setenv(key, value)
        yield gw


def _timed(fn):
    t0 = time.monotonic()
    r = fn()
    return r, time.monotonic() - t0


def _status():
    return client.get("/api/v1/ai/status")


def _devil():
    return client.post("/api/v1/assistant/chat", json={
        "message": DEVIL_MESSAGE, "locale": "zh-CN", "history": [],
        "mode": "devil", "profile": DEVIL_PROFILE})


def _simulate(ids, explain):
    return client.post("/api/v1/simulate", json={
        "baseline_profile": dict(AUDIT_FLAT), "scenarios": SCENARIOS,
        "program_ids": list(ids), "locale": "zh-CN", "explain": explain})


def _matchable_ids():
    """Every matchable programme id, as the results page sends them."""
    ids, cursor = [], None
    while True:
        qs = "/api/v1/programs?catalogue=all&limit=20"
        if cursor:
            qs += f"&cursor={cursor}"
        r = client.get(qs)
        assert r.status_code == 200, r.text
        body = r.json()
        ids.extend(i["id"] for i in (body.get("items") or []))
        cursor = body.get("next_cursor")
        if not cursor:
            break
    r = client.post("/api/v1/match", json={
        "profile": dict(AUDIT_FLAT), "program_ids": ids})
    assert r.status_code == 200, r.text
    return [x["programId"] for x in r.json().get("results", [])]


# ---------------------------------------------------------------------------
# Fix 1 — the breaker outlives the probe cache (180 s > 60 s)
# ---------------------------------------------------------------------------

def test_breaker_cooldown_is_180s():
    """Pin the constant: the breaker must outlive the 60 s probe
    cache, so a known-down gateway stays skipped between probes.
    A future change to this number is a deliberate product decision
    (longer = slower recovery detection, shorter = repeat 15 s
    burns), not a drive-by edit."""
    assert GATEWAY_BREAKER_COOLDOWN_S == 180.0


def test_breaker_still_open_after_probe_cache_expires(gateway):
    """The incident's core: trip the breaker with a failed probe,
    then let the 60 s probe cache expire — the breaker must still
    be open (it has 180 s), and the devil turn must still be
    instant with no new gateway call. Before the fix both were
    60 s, so they expired together and the next turn paid 15 s."""
    gateway.mode = "flap"
    r, _ = _timed(_status)
    assert r.json()["ai_status"] == "unavailable"
    assert gateway_breaker_open()
    # Age the probe cache past its 60 s TTL, and age the breaker by
    # 61 s too (61 s of the 180 s cooldown elapsed).
    app_main._AI_STATUS_CACHE["at"] = time.monotonic() - 61
    provider_mod._gateway_down_until -= 61
    assert gateway_breaker_open(), (
        "breaker must outlive the 60 s probe cache")
    posts_before = gateway.posts()
    r, elapsed = _timed(_devil)
    assert r.status_code == 200, r.text
    assert elapsed < 2, f"devil with open breaker took {elapsed:.1f}s"
    assert r.json()["ai_status"] == "unavailable"
    assert gateway.posts() == posts_before, (
        "devil must not call the gateway while the breaker is open")


def test_devil_fast_after_failed_probe(gateway):
    """Probe first (flapping gateway -> unavailable, ~7 s, trips
    the breaker), then the devil turn renders the template in
    engine time with NO further gateway call — and the template
    still states the engine-computed difference (Round 17)."""
    gateway.mode = "flap"
    r, elapsed = _timed(_status)
    assert r.json()["ai_status"] == "unavailable"
    assert 6.5 < elapsed < 10, f"flapping probe took {elapsed:.1f}s"
    assert gateway_breaker_open()
    posts_after_probe = gateway.posts()
    assert posts_after_probe == 1
    r, elapsed = _timed(_devil)
    assert r.status_code == 200, r.text
    assert elapsed < 2, f"post-probe devil took {elapsed:.1f}s"
    body = r.json()
    assert body["ai_status"] == "unavailable"
    assert body["mode"] == "devil"
    assert "相差3项" in " ".join(body.get("lines") or []), body.get("lines")
    assert gateway.posts() == posts_after_probe


# ---------------------------------------------------------------------------
# Fix 2 — /ai/status answers from the breaker instead of re-probing
# ---------------------------------------------------------------------------

def test_status_shortcircuits_on_open_breaker_with_stale_cache(gateway):
    """A stale-cache status read with the breaker open must answer
    "unavailable" at once with NO new gateway call: before the fix
    it re-probed at ~7 s on a flapping gateway (measured 7.14 s),
    and that cost landed on the simulate click's modelAvailability
    gate whenever the 60 s cache had expired."""
    gateway.mode = "flap"
    r, _ = _timed(_status)
    assert r.json()["ai_status"] == "unavailable"
    assert gateway_breaker_open()
    app_main._AI_STATUS_CACHE["at"] = time.monotonic() - 61
    posts_before = gateway.posts()
    gets_before = gateway.gets()
    r, elapsed = _timed(_status)
    assert r.status_code == 200, r.text
    assert elapsed < 1, f"short-circuited status took {elapsed:.1f}s"
    assert r.json()["ai_status"] == "unavailable"
    assert gateway.posts() == posts_before and gateway.gets() == gets_before, (
        "no probe may run while the breaker is open")


def test_status_shortcircuits_on_open_breaker_without_cached_verdict(gateway):
    """Same short-circuit with NO cached verdict at all (the breaker
    was tripped by a chat failure before any probe ran): the read
    still answers "unavailable" at once, marked probed=False —
    the verdict comes from the breaker, not from a probe."""
    gateway.mode = "flap"
    r, _ = _timed(_status)
    assert r.json()["ai_status"] == "unavailable"
    assert gateway_breaker_open()
    reset_ai_status_cache()
    posts_before = gateway.posts()
    r, elapsed = _timed(_status)
    assert r.status_code == 200, r.text
    assert elapsed < 1, f"short-circuited status took {elapsed:.1f}s"
    assert r.json()["ai_status"] == "unavailable"
    assert r.json()["probed"] is False
    assert gateway.posts() == posts_before


def test_status_reprobes_after_breaker_expires(gateway):
    """Recovery detection is preserved: once the breaker expires,
    the next status read probes again (bypassing the breaker) —
    it must NOT keep answering from the breaker forever."""
    gateway.mode = "flap"
    r, _ = _timed(_status)
    assert r.json()["ai_status"] == "unavailable"
    assert gateway_breaker_open()
    app_main._AI_STATUS_CACHE["at"] = time.monotonic() - 61
    provider_mod._gateway_down_until = time.monotonic() - 1
    assert not gateway_breaker_open()
    posts_before = gateway.posts()
    r, elapsed = _timed(_status)
    assert r.status_code == 200, r.text
    assert r.json()["ai_status"] == "unavailable"
    assert 6.5 < elapsed < 10, f"re-probe took {elapsed:.1f}s"
    assert gateway.posts() == posts_before + 1, (
        "an expired breaker must re-probe instead of short-circuiting")
    assert gateway_breaker_open(), "the failed re-probe re-trips the breaker"


def test_devil_attempts_model_again_after_breaker_expires_healthy(gateway):
    """And on the healthy path: after the breaker expires, a devil
    turn attempts the model again (one gateway POST) instead of
    staying template-only."""
    gateway.mode = "flap"
    r, _ = _timed(_status)
    assert gateway_breaker_open()
    gateway.mode = "healthy-json"
    provider_mod._gateway_down_until = time.monotonic() - 1
    assert not gateway_breaker_open()
    posts_before = gateway.posts()
    r, elapsed = _timed(_devil)
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"recovered devil took {elapsed:.1f}s"
    assert gateway.posts() == posts_before + 1, (
        "the model must be attempted again once the breaker expires")
    assert not gateway_breaker_open(), (
        "a successful model call clears the breaker")


# ---------------------------------------------------------------------------
# No regression on the healthy path
# ---------------------------------------------------------------------------

def test_healthy_gateway_probe_and_devil_attempt_model(gateway):
    """Healthy gateway: the probe still reports available (and really
    ran the chat confirmation), the breaker stays closed, and a
    devil turn attempts the model — the breaker/short-circuit
    changes must not block healthy calls."""
    gateway.mode = "healthy-json"
    r, elapsed = _timed(_status)
    assert r.status_code == 200, r.text
    assert r.json()["ai_status"] == "available"
    assert elapsed < 5, f"healthy probe took {elapsed:.1f}s"
    assert gateway.gets() == 1 and gateway.posts() == 1
    assert not gateway_breaker_open()
    posts_before = gateway.posts()
    r, elapsed = _timed(_devil)
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"healthy devil took {elapsed:.1f}s"
    assert gateway.posts() == posts_before + 1


# ---------------------------------------------------------------------------
# Simulate click path at audit scale (backend half; the frontend
# warming that keeps the verdict fresh is TS-only — SimulatePanel)
# ---------------------------------------------------------------------------

def test_simulate_click_path_fast_after_probe_at_audit_scale(gateway):
    """The fixed click path, backend half: probe once on a flapping
    gateway (unavailable, ~7 s, trips the breaker), then the
    simulate click — explain:false, the full 601 matchable ids, 3
    scenarios — returns the template in engine time with NO further
    gateway call. BEFORE the fix the cold click paid the probe
    (7.23 s) + engine (2.42 s) = 9.65 s; with the verdict warm it
    is engine time only."""
    gateway.mode = "flap"
    r, _ = _timed(_status)
    assert r.json()["ai_status"] == "unavailable"
    ids = _matchable_ids()
    assert len(ids) > 500, f"audit scale expected, got {len(ids)} ids"
    posts_after_probe = gateway.posts()
    r, elapsed = _timed(lambda: _simulate(ids, False))
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"warm-verdict simulate took {elapsed:.1f}s"
    assert r.json()["explanation"]["source"] == "template"
    assert gateway.posts() == posts_after_probe, (
        "simulate must not call the gateway after a failed probe")


# ---------------------------------------------------------------------------
# Residual worst case, pinned so it cannot silently grow
# ---------------------------------------------------------------------------

def test_devil_first_call_after_gateway_death_burns_15s_residual(gateway):
    """RESIDUAL (documented, not fixed): with NO prior probe and a
    closed breaker — the gateway died after the last probe, or the
    probe cache is cold — the first devil turn still spends the
    full 15 s model budget before the template. No cache can know
    the gateway died since the last probe; the breaker then
    protects every later call for 180 s (asserted by the fast
    second call). If this bound ever grows, the 15 s cap itself
    moved."""
    gateway.mode = "flap"
    r, elapsed = _timed(_devil)
    assert r.status_code == 200, r.text
    assert 14 < elapsed < 20, (
        f"residual first-call burn was {elapsed:.1f}s, expected ~15s")
    assert r.json()["ai_status"] == "unavailable"
    assert gateway_breaker_open()
    posts_after_first = gateway.posts()
    r, elapsed = _timed(_devil)
    assert r.status_code == 200, r.text
    assert elapsed < 2, f"second devil took {elapsed:.1f}s"
    assert gateway.posts() == posts_after_first
