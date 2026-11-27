"""Round 21 W1 — footer first-open false "AI 回答": the /ai/status contract.

Re-test task 15 (2026-11-27 13:22-13:27): the pet footer claimed
"AI 回答" on the very first homepage open while the model was offline
the whole run, and the checking line was never seen. The parent's curl
at 13:21 saw /ai/status "available", then the real pref-chat call
flapped after 15.61 s.

Root cause, in the backend contract (see /tmp/r21-w1-decisions.md):
- /ai/status caches its verdict 60 s server-side, per-process, shared
  by every user/tab. A 13:21 live probe that succeeded primed the
  cache; the 13:22 pet probe was served that cached "available" in
  ~0 s without touching the gateway, while the gateway had already
  flapped. The probe is only a 1-token chat — weaker than a real turn.
- The cached payload was served with "probed": True (the flag from
  probe time), so no caller could tell a fresh probe from a stale
  cached verdict — and the pet probe did not even read "probed".

Fix pinned here (backend/app/main.py, ai_status() only):
1. A cached serve is labelled "probed": False and carries
   "cache_age_s": a cached verdict is never again mislabelled fresh.
2. GET /ai/status?fresh=1 bypasses the 60 s cache read and runs a live
   probe now. The breaker-open fast path is kept: breaker open still
   answers "unavailable", probed False, at once without probing.

These tests use a REAL in-process HTTP gateway (ThreadingHTTPServer),
same pattern as tests/test_r18_w2_latency.py: httpx MockTransport does
NOT enforce timeouts, so a hanging gateway can only be simulated over
real sockets.

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r21_w1_footer_probe.py
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
from ai.provider import gateway_breaker_open, reset_gateway_breaker
from app.main import app, reset_ai_status_cache, reset_rate_limits

client = TestClient(app)


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
    """Real HTTP gateway in a thread, switchable healthy <-> flap.

    healthy: GET /models 200 at once, POST /chat/completions 200
        after 0.3 s with a valid reply.
    flap (the audit's gateway): GET /models 200 at once, POST
        /chat/completions hangs 30 s — the probe's 7 s chat budget
        times out, so the probe reports unavailable and trips the
        breaker.
    ``requests`` records (method, path) in arrival order.
    """

    def __init__(self):
        self.mode = "healthy"
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
                if gateway.mode == "flap":
                    time.sleep(30)
                    self._json(200, {"choices": [{"message": {"content": "ok"}}],
                                     "usage": {}})
                else:
                    time.sleep(0.3)
                    self._json(200, {"choices": [{"message": {"content": "ok"}}],
                                     "usage": {}})

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

    def calls(self) -> int:
        with self._lock:
            return len(self.requests)


@pytest.fixture
def gateway(monkeypatch):
    with _MockGateway() as gw:
        for key, value in {
            "AI_PROVIDER": "openai",
            "AI_MODEL": "mock-r21-model",
            "AI_API_KEY": "mock-test-key",
            "AI_BASE_URL": gw.base_url,
        }.items():
            monkeypatch.setenv(key, value)
        yield gw


def _status(fresh: bool = False):
    qs = "/api/v1/ai/status?fresh=1" if fresh else "/api/v1/ai/status"
    return client.get(qs)


# ---------------------------------------------------------------------------
# Fix 1 — a cached verdict is never labelled a fresh probe
# ---------------------------------------------------------------------------

def test_cached_available_is_not_labelled_fresh(gateway):
    """Prime the cache with a live probe (available, probed True),
    then read again inside the 60 s TTL: the second read must still
    say "available" (same value) but probed MUST be False, with a
    cache_age_s, and it must not touch the gateway again. Before the
    fix the second read also said probed True — the footer could not
    tell a stale cached verdict from a live probe in this open."""
    r = _status()
    assert r.status_code == 200, r.text
    assert r.json()["ai_status"] == "available"
    assert r.json()["probed"] is True
    assert gateway.calls() == 2  # GET /models + POST chat confirmation
    r2 = _status()
    assert r2.status_code == 200, r2.text
    assert r2.json()["ai_status"] == "available"
    assert r2.json()["probed"] is False, (
        "cached serve must not claim a fresh probe")
    assert r2.json().get("cache_age_s") is not None
    assert r2.json()["cache_age_s"] >= 0
    assert gateway.calls() == 2, "cached read must not re-probe"


def test_cached_unavailable_is_not_labelled_fresh(gateway):
    """Same labelling rule for a cached "unavailable": the first
    (flapping-gateway) probe is probed True, the cached re-read is
    probed False. A cached down verdict is safe to show as offline,
    but it is still not a fresh probe."""
    gateway.mode = "flap"
    r = _status()
    assert r.json()["ai_status"] == "unavailable"
    assert r.json()["probed"] is True
    assert gateway_breaker_open()
    r2 = _status()
    assert r2.json()["ai_status"] == "unavailable"
    assert r2.json()["probed"] is False


# ---------------------------------------------------------------------------
# Fix 2 — ?fresh=1 bypasses the stale cache (the task-15 sequence)
# ---------------------------------------------------------------------------

def test_fresh_bypasses_stale_cached_available(gateway):
    """The task-15 sequence: a live probe at T0 caches "available"
    (the parent's 13:21 curl); the gateway then flaps; a plain read
    at T0+seconds still says "available" from cache — but a fresh
    read must re-probe and report "unavailable", probed True, after
    the ~7 s chat-confirmation budget, and trip the breaker. Before
    the fix ?fresh=1 was ignored and the read returned the cached
    "available" in ~0 s — exactly the footer's false claim."""
    r = _status()
    assert r.json()["ai_status"] == "available"
    assert r.json()["probed"] is True
    gateway.mode = "flap"
    # Plain read: still the stale cached verdict (documents the trap).
    r_plain = _status()
    assert r_plain.json()["ai_status"] == "available"
    assert r_plain.json()["probed"] is False
    # Fresh read: must actually probe the now-down gateway.
    calls_before = gateway.calls()
    t0 = time.monotonic()
    r_fresh = _status(fresh=True)
    elapsed = time.monotonic() - t0
    assert r_fresh.status_code == 200, r_fresh.text
    assert r_fresh.json()["ai_status"] == "unavailable", (
        "fresh probe of a flapping gateway must not report available")
    assert r_fresh.json()["probed"] is True
    assert 6.5 < elapsed < 12, (
        f"fresh probe must run the ~7 s chat confirmation, took {elapsed:.1f}s")
    assert gateway.calls() > calls_before, "fresh read must re-probe"
    assert gateway_breaker_open()
    # The fresh verdict refreshes the cache: the next plain read is
    # the fresh unavailable, labelled cached.
    r_after = _status()
    assert r_after.json()["ai_status"] == "unavailable"
    assert r_after.json()["probed"] is False


def test_fresh_healthy_reprobes_and_refreshes_cache(gateway):
    """With a healthy gateway, ?fresh=1 re-probes (gateway call count
    moves) and reports available, probed True. Before the fix the
    call count did not move — the parameter was ignored."""
    r = _status()
    assert r.json()["ai_status"] == "available"
    assert gateway.calls() == 2
    r2 = _status(fresh=True)
    assert r2.status_code == 200, r2.text
    assert r2.json()["ai_status"] == "available"
    assert r2.json()["probed"] is True
    assert r2.json().get("cache_age_s") == 0.0
    assert gateway.calls() == 4, "fresh read must run a new live probe"


def test_fresh_with_breaker_open_answers_unavailable_without_probe(gateway):
    """Breaker-open fast path is kept for fresh reads: after a failed
    probe trips the breaker, ?fresh=1 answers "unavailable",
    probed False, at once with no new gateway call — the breaker is
    fresher evidence of down than any probe would be."""
    gateway.mode = "flap"
    r = _status()
    assert r.json()["ai_status"] == "unavailable"
    assert gateway_breaker_open()
    calls_before = gateway.calls()
    t0 = time.monotonic()
    r2 = _status(fresh=True)
    elapsed = time.monotonic() - t0
    assert r2.status_code == 200, r2.text
    assert r2.json()["ai_status"] == "unavailable"
    assert r2.json()["probed"] is False
    assert elapsed < 2, f"breaker-open fresh read took {elapsed:.1f}s"
    assert gateway.calls() == calls_before, (
        "breaker-open read must not touch the gateway")
