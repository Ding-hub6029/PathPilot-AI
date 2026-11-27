"""Round 24 W4 — pet free-text latency diagnosis (P2).

Finding: the pet's offline template answers took 25-30 s
("Checking verified sources...") while the gateway was down
(ai_status unavailable). Timed breakdown, measured locally
against stub gateways (dummy key, localhost):

- retrieval (_retrieve, incl. the template ask): ~0.06 s
- template answer with no key configured: ~0.01 s
- provider.chat vs a read-hang gateway, cold breaker: ~15.0 s
  (the httpx read timeout); the turn then trips the breaker
- chat.answer turn 1 vs read-hang, cold breaker: 16.08 s
- chat.answer turn 2 (breaker open): 0.09 s
- POST /api/v1/assistant/chat vs read-hang, cold breaker: 15.64 s
- POST /api/v1/assistant/chat (breaker open): 0.07 s
- probe_live vs a hanging /models: 3.60 s; vs /models-OK +
  hanging chat: 8.11 s (both trip the breaker)
- provider.chat vs a gateway that answers HTTP 502 after ~12 s:
  12.98 s, then 12.41 s again, then chat.answer 12.49 s — the
  breaker NEVER tripped, so every turn paid the wait again.

Root cause (two holes, both in the "skip the model attempt when
the gateway is already known down" logic /simulate already has):

1. The breaker only tripped on slow timeout / transport failures.
   A slow HTTP 5xx (the flapping Shenjyai relay answering 502
   after its upstream hung) raised ProviderError kind=
   "provider_http", which never tripped it — so the 12 s wait
   repeated on every turn forever. Fix: a slow 5xx trips the
   breaker too (ai/provider.py _trips_breaker); a fast 5xx still
   does not (the existing test_breaker_does_not_trip_on_fast_500
   pins that), and a 429 / 4xx never trips however slow.
2. The pet's free-text path (CompassPet sendAskTurn) never
   consulted the known-down verdict before calling the backend —
   unlike askSuggest (Round 18 W2) and unlike /simulate's
   server-side _model_skip_cached. Every free-text turn hit the
   backend and paid the model attempt. A
   modelAvailability() === 'unavailable' gate was added to
   sendAskTurn in this round, then REMOVED at integration
   (Round 24 W1 conflict): skipping the backend call returns the
   offline rank fallback (reply: null) instead of the backend's
   verified template answer, so a fee question would get rank
   lines and the pending-disambiguation flow (W1) could never
   start — while the gate saves nothing measurable, because when
   the verdict is 'unavailable' the backend breaker is already
   open (the pet re-probes on every open; the 180 s breaker
   cooldown outlives the 60 s verdict cache) and the backend
   fails fast to the template in ~0.07 s. The backend breaker
   fix (1) is what makes the down-path fast; askSuggest keeps
   its gate because its offline catalogue reproduces the
   suggestion answer exactly.

The 25-30 s upper end is httpx's per-phase timeout: a single
timeout=15.0 sets connect=read=write=pool=15 s EACH (see the
installed httpx Timeout docstring), so one model call can take
up to ~30 s when the gateway's connect (TCP + TLS to the flapping
relay) is slow AND the read then hangs. That worst case is
inherent to the timeout and is NOT shortened here — live model
calls take 9-12 s, so a shorter budget would clip real replies.
The fix is to not attempt at all when the gateway is known down,
which is what (1) + (2) do: after the first slow failure, later
turns fail fast in engine time.

Drive-by fix in the same gate: askSuggest's Round 18 W2 gate
returned early without clearing busy/waking — its early return
runs before the try's finally, so the pet stayed stuck thinking
(chips hidden, input blocked) after a known-down suggestion.
Both gates now clear busy/waking on the early-return path.

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r24_w4_pet_latency.py
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

import ai.provider as provider_mod
from ai.chat import answer as chat_answer
from ai.provider import (
    ProviderAdapter,
    ProviderError,
    gateway_breaker_open,
    reset_gateway_breaker,
)

ROOT = Path(__file__).resolve().parent.parent
PET = ROOT / "frontend" / "src" / "components" / "CompassPet.tsx"

_MOCK_ENV = {
    "AI_PROVIDER": "openai",
    "AI_MODEL": "mock-r24-model",
    "AI_API_KEY": "mock-test-key",
    "AI_BASE_URL": "https://api.example.test/v1",
}


@pytest.fixture(autouse=True)
def _isolate():
    reset_gateway_breaker()
    yield
    reset_gateway_breaker()


def _adapter(monkeypatch, handler) -> ProviderAdapter:
    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    return ProviderAdapter(_transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Fix 1 — a slow HTTP 5xx trips the breaker (was: every turn paid ~12 s)
# ---------------------------------------------------------------------------

def test_breaker_trips_on_slow_500(monkeypatch):
    """A 502 that took real time to arrive trips the breaker: the
    first call raises kind=provider_http, the second raises kind=
    gateway_breaker_open at once with no further transport call.
    The mock sleeps 0.3 s with the latency gate lowered to 0.1 s
    (the real gate is 5 s; the production slow-502 stub measured
    12.98 s / 12.41 s / 12.49 s per attempt before this fix)."""
    calls = {"n": 0}

    def _slow_500(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        time.sleep(0.3)
        return httpx.Response(502, json={"error": "bad gateway"})

    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    adapter = _adapter(monkeypatch, _slow_500)
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "provider_http"
    assert excinfo.value.status_code == 502
    assert gateway_breaker_open()
    t0 = time.monotonic()
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert time.monotonic() - t0 < 1
    assert excinfo.value.kind == "gateway_breaker_open"
    assert calls["n"] == 1, "breaker-open call must not touch the network"


def test_breaker_does_not_trip_on_slow_429(monkeypatch):
    """A slow 429 is NOT a down gateway — it is up but throttling —
    so it must not trip the breaker however long it took: the next
    call still reaches the gateway."""
    calls = {"n": 0}

    def _slow_429(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        time.sleep(0.3)
        return httpx.Response(429, json={"error": "rate limited"})

    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    adapter = _adapter(monkeypatch, _slow_429)
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "provider_http"
    assert excinfo.value.status_code == 429
    assert not gateway_breaker_open()
    with pytest.raises(ProviderError):
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert calls["n"] == 2


def test_chat_answer_fast_after_slow_500(monkeypatch):
    """End to end at the answer() level: after one slow 502 the
    next free-text turn renders the verified template in engine
    time (~0 s, one transport call total) instead of paying the
    slow 502 again — and the template lines are unchanged."""
    calls = {"n": 0}

    def _slow_500(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        time.sleep(0.3)
        return httpx.Response(502, json={"error": "bad gateway"})

    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    adapter = _adapter(monkeypatch, _slow_500)
    first = chat_answer("瑞士有哪些好学校？", "zh-CN", provider=adapter)
    assert first["ai_status"] == "unavailable"
    assert calls["n"] == 1
    t0 = time.monotonic()
    second = chat_answer("瑞士有哪些好学校？", "zh-CN", provider=adapter)
    assert time.monotonic() - t0 < 1
    assert calls["n"] == 1, "second turn must not touch the network"
    assert second["ai_status"] == "unavailable"
    assert second["lines"] == first["lines"]
    assert "ETH Zurich" in second["lines"][0]


# ---------------------------------------------------------------------------
# Fix 2 — the free-text path must NOT skip the backend when known down
# (source pins: there is no JS test runner in this repo).
# Integration decision (Round 24 W1 conflict): a
# modelAvailability() === 'unavailable' gate in sendAskTurn was added
# in this round and removed at integration — it returned the offline
# rank fallback (reply: null) instead of the backend's verified
# template answer, so the fee-disambiguation flow (W1) could never
# start while known down, while saving nothing measurable (the
# breaker is already open then, so the backend fails fast to the
# template in ~0.07 s). askSuggest keeps its gate: its offline
# catalogue reproduces the suggestion answer exactly.
# ---------------------------------------------------------------------------

def test_free_text_path_has_no_known_down_gate():
    """sendAskTurn (the pet's free-text path) must NOT have the
    modelAvailability() === 'unavailable' early-offline gate: the
    template answers (fees, ambiguous lines, disambiguation
    candidates) live in the backend, and skipping the call would
    return the offline rank fallback instead. The backend breaker
    (Fix 1 above) is what makes the known-down path fast."""
    pet = PET.read_text(encoding="utf-8")
    start = pet.index("const sendAskTurn")
    end = pet.index("const onSend", start)
    block = pet[start:end]
    assert "modelAvailability()) === 'unavailable'" not in block
    assert "Round 24 W4/W1" in block  # the no-gate rationale comment
    assert "fetchJsonChat" in block  # the backend call still happens


def test_suggest_gate_clears_busy_on_early_return():
    """askSuggest's Round 18 W2 gate returned early without
    clearing busy/waking — its early return also runs before the
    try's finally — so the pet stayed stuck thinking (chips
    hidden, input blocked) after a known-down suggestion. The
    one remaining known-down gate in the file (askSuggest — the
    sendAskTurn gate was removed at integration, see the test
    above) must clear busy on the early-return path."""
    pet = PET.read_text(encoding="utf-8")
    gates = []
    idx = 0
    while True:
        idx = pet.find("modelAvailability()) === 'unavailable'", idx)
        if idx < 0:
            break
        gates.append(pet[idx:idx + 700])
        idx += 1
    assert len(gates) == 1, "only the askSuggest gate should remain"
    for gate_block in gates:
        assert "setBusy(false)" in gate_block
        assert "setWaking(false)" in gate_block
