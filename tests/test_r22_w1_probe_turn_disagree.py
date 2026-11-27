"""Round 22 W1 — the probe can say "available" while a real turn goes
template-only: the evidence behind the footer leak DURING a question.

Re-test task 16 (2026-11-27 14:21-14:27): first open PASSed (checking
~1-2 s, then offline), but while asking a question inside the pet the
footer briefly showed "AI 回答", then returned to offline after the
answer — model down the whole run.

The frontend root cause is in CompassPet.tsx (the slow open probe's
verdict was applied whenever it landed, overwriting the turn's
verdict — see /tmp/r22-w1-harness.mjs). This file pins the backend
half of that story, the fact the frontend fix must respect: the
/ai/status probe is a 1-token chat (ai.provider probe_live, max_tokens=1),
weaker than a real turn (max_tokens=1200, 15 s budget). On a flapping
gateway the tiny probe call can succeed while the full turn call hangs
— so at the SAME moment the probe reports "available" and a real turn
answers template-only with ai_status "unavailable". A probe verdict
must therefore never overwrite a turn verdict, in either direction.

Same real-socket gateway pattern as tests/test_r21_w1_footer_probe.py:
httpx MockTransport does NOT enforce timeouts, so a hanging gateway
can only be simulated over real sockets. The gateway's
"probe-ok-chat-hangs" mode answers the 1-token probe call at once
and hangs every full-size chat call for 30 s (the turn's 15 s budget
fires first).

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r22_w1_probe_turn_disagree.py
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
    """Real HTTP gateway in a thread.

    GET /models: 200 at once.
    POST /chat/completions: the request body decides —
    max_tokens == 1 is the /ai/status liveness probe: 200 at once
    with a valid reply. Any larger max_tokens is a real turn: hang
    30 s (the turn's 15 s client budget fires first, so the turn
    falls back to its template). ``chat_max_tokens`` records every
    chat call's max_tokens in arrival order.
    """

    def __init__(self):
        self.chat_max_tokens: list[int | None] = []
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
                if self.path.endswith("/models"):
                    self._json(200, {"data": [{"id": "mock-model"}]})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                if not self.path.endswith("/chat/completions"):
                    self._json(404, {"error": "not found"})
                    return
                try:
                    max_tokens = json.loads(raw).get("max_tokens")
                except (ValueError, AttributeError):
                    max_tokens = None
                with gateway._lock:
                    gateway.chat_max_tokens.append(max_tokens)
                if max_tokens == 1:
                    # The 1-token probe call: answers at once.
                    self._json(200, {"choices": [{"message": {"content": "ok"}}],
                                     "usage": {}})
                    return
                # A real turn: hang past the turn's 15 s budget.
                time.sleep(30)
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


@pytest.fixture
def gateway(monkeypatch):
    with _MockGateway() as gw:
        for key, value in {
            "AI_PROVIDER": "openai",
            "AI_MODEL": "mock-r22-model",
            "AI_API_KEY": "mock-test-key",
            "AI_BASE_URL": gw.base_url,
        }.items():
            monkeypatch.setenv(key, value)
        yield gw


def test_probe_available_while_real_turn_goes_template(gateway):
    """The task-16 evidence, at one moment: a fresh probe reports
    "available" (its 1-token call succeeded) while the real turn
    answers template-only with ai_status "unavailable" (its full-size
    call hung past the 15 s budget). The probe and the turn disagree
    — so the frontend must never let a probe verdict overwrite a
    turn verdict (Round 22 W1, CompassPet probeVerdictApplies)."""
    r = client.get("/api/v1/ai/status?fresh=1")
    assert r.status_code == 200, r.text
    assert r.json()["ai_status"] == "available", (
        "the 1-token probe must succeed on this gateway")
    assert r.json()["probed"] is True
    assert gateway.chat_max_tokens == [1], (
        f"the probe must be exactly one 1-token chat call, saw {gateway.chat_max_tokens}")

    t0 = time.monotonic()
    r2 = client.post("/api/v1/assistant/chat",
                     json={"message": "What is the UCL Computer Science BSc tuition fee?",
                           "locale": "en"})
    elapsed = time.monotonic() - t0
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["ai_status"] == "unavailable", (
        "the hanging full-size turn must fall back to its template")
    assert body["model"] is None
    assert body["lines"], "the template answer must still answer, not be empty"
    # The turn spent its ~15 s model budget, not the probe's ~0 s.
    assert 14 < elapsed < 25, (
        f"turn must wait out its ~15 s model budget, took {elapsed:.1f}s")
    assert gateway.chat_max_tokens == [1, 1200], (
        f"the turn must be one full-size (1200-token) chat call, saw {gateway.chat_max_tokens}")
    # The failed turn trips the breaker — the gateway is known down
    # after it, even though the probe just said available.
    assert gateway_breaker_open()
