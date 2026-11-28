"""Round 28 D3 — first two preference answers slow (re-test 22).

Live browser, gateway offline the whole run (2026-11-28 01:31-01:41
CST): in the Chinese wizard the countries answer （瑞士） took
~10-12 s and the climate answer （凉爽） ~15-25 s (spinner
"正在查已核实资料… 9 秒" still spinning). Later answers
（大学城， 苏黎世， 去向， 薪资， 压力， 上课方式， 原因） all
~1 s and never lost. Round 26 W1's fail-fast fix made step-7 <2 s
via curl, but the first two turns still paid a model/probe budget
in the real browser flow.

Root causes, each verified in code before the fix (see
DECISIONS.md #R28-D3 for the full enumeration):

(a) THE QUIET PERIOD. The skip verdict that makes pref turns fast
(model_skip_cached in backend/app/ai_status_cache.py: breaker open
within 180 s, or a probe saying "unavailable" within its 60 s TTL)
EXPIRES while the user spends minutes on the academic form (Gaokao,
IELTS, budget) before the first preference answer. The frontend
keeps that verdict warm ONLY on the results page: SimulatePanel
warms it on mount, every 45 s and on window focus. Nothing warmed
it while the wizard was open — PrefChat / CompassPet only read
modelAvailability() on demand per turn, never on an interval — and
the backend is a single uvicorn worker (backend/Dockerfile CMD has
no --workers flag), so one cold cache poisons every first turn.
Fix: mirror the SimulatePanel warmer in the wizard page
(mount + 45 s interval + window focus, background only, never on
the submit path).

(b) THE SECOND SLOW TURN. After the first slow failure the breaker
SHOULD be open, so the second turn should skip — but it took
15-25 s. Enumeration of every slow failure kind that consumes the
model budget but did not trip (provider.py, before this fix):
- "empty_reply": ProviderError raised in chat()/achat() AFTER the
  try/except that trips the breaker, so a slow 200 with an empty
  body NEVER tripped. THE hole (test_r25_w2 already named it as
  open, with no live evidence then; re-test 22 is that evidence).
- "bad_reply": raised INSIDE the try (unreadable 200 body), but
  _trips_breaker did not recognise the kind, so a slow unreadable
  200 also never tripped.
- Everything else already tripped when slow: "timeout" and
  "transport_error" (httpx branches), "provider_http" with status
  >= 500 (Round 24 W4). Pinned non-trips kept green: a slow 429
  never trips (gateway UP but throttling), a slow 4xx never trips
  (our request, not the gateway), and a FAST failure of any kind
  never trips (latency gate, _BREAKER_MIN_LATENCY_S = 5.0).
Fix: "empty_reply" and "bad_reply" join _BREAKER_TRIP_KINDS (the
single trip decision in _trips_breaker — chat, achat and the probe
all consult it), and the empty-reply raise in chat()/achat() is
routed through that same decision instead of sitting outside it.

On the frontend-abort candidate for the second turn: fetchJsonChat
caps one attempt at 18 s inside a 20 s budget (retryOnTimeout
false), and the backend pref turn is one provider.chat with a 15 s
budget — but httpx's per-phase timeout lets one call take up to
~30 s (test_r24_w4 header), so a 15-25 s second turn is
consistent with a second full model attempt that never tripped
(the provider hole above), not only with an 18 s frontend abort.
Either way the warmer in (a) is the fix for the abort case too —
a warm verdict skips the model attempt before any budget is
spent — and the trip rule in (b) is independently correct per the
"any slow failure that consumed the budget trips" principle, so
both fixes land.

Residual (NOT fixed here): a slow 200 whose text is non-empty but
fails model-JSON parsing / validation in ai.chat.answer() /
ai.pref_chat.pref_answer() — chat() already cleared the breaker on
HTTP success, and the parse happens in the caller, outside
provider.py. A gateway returning unparsable text slowly on every
turn would still repeat the wait; fixing it needs ai/chat.py or
ai/pref_chat.py, which are outside this worker's files. The first
slow failure after the gateway dies mid-session is likewise
inherent (the /simulate residual): the warmer only prevents it
after a quiet period, it cannot prevent it when the gateway dies
mid-session.

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r28_d3.py
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

import httpx
import pytest

import ai.provider as provider_mod
from ai.pref_chat import pref_answer
from ai.provider import (
    ProviderAdapter,
    ProviderError,
    gateway_breaker_open,
    reset_gateway_breaker,
)
from app.ai_status_cache import reset_ai_status_cache

ROOT = Path(__file__).resolve().parent.parent
WIZARD = ROOT / "frontend" / "src" / "app" / "wizard" / "page.tsx"
SIMULATE_PANEL = ROOT / "frontend" / "src" / "components" / "SimulatePanel.tsx"
PREF_CHAT = ROOT / "frontend" / "src" / "components" / "PrefChat.tsx"
COMPASS_PET = ROOT / "frontend" / "src" / "components" / "CompassPet.tsx"
API_TS = ROOT / "frontend" / "src" / "lib" / "api.ts"
FRONTEND_SRC = ROOT / "frontend" / "src"

_MOCK_ENV = {
    "AI_PROVIDER": "openai",
    "AI_MODEL": "mock-r28-model",
    "AI_API_KEY": "mock-test-key",
    "AI_BASE_URL": "https://api.example.test/v1",
}


@pytest.fixture(autouse=True)
def _isolate():
    reset_gateway_breaker()
    reset_ai_status_cache()
    yield
    reset_gateway_breaker()
    reset_ai_status_cache()


def _adapter(monkeypatch, handler) -> ProviderAdapter:
    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    return ProviderAdapter(_transport=httpx.MockTransport(handler))


def _slow_empty_reply(calls: dict, delay_s: float = 0.3):
    """A gateway that answers HTTP 200 with an empty body after
    real time has passed — the re-test 22 second-turn failure mode:
    the relay answering garbage after its upstream hung."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        time.sleep(delay_s)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": ""}}], "usage": {}})
    return handler


def _slow_bad_reply(calls: dict, delay_s: float = 0.3):
    """A gateway that answers HTTP 200 with an unreadable body
    after real time has passed."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        time.sleep(delay_s)
        return httpx.Response(200, content=b"not json")
    return handler


def _slow_status(calls: dict, status: int, delay_s: float = 0.3):
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        time.sleep(delay_s)
        return httpx.Response(status, json={"error": "gateway"})
    return handler


# ---------------------------------------------------------------------------
# (a) — the wizard warmer (source pins: no JS test runner in this repo)
# ---------------------------------------------------------------------------

def test_wizard_page_warms_model_availability():
    """The wizard page mirrors the SimulatePanel warmer (Round 18
    W2): warm on mount, every 45 s, on window focus, cleaned up on
    unmount — so the skip verdict stays fresh through the minutes
    the user spends on the academic form before the first
    preference answer."""
    page = WIZARD.read_text(encoding="utf-8")
    assert "warmModelAvailability" in page
    assert "setInterval(warmModelAvailability, MODEL_AVAILABILITY_WARM_MS)" in page
    assert "window.addEventListener('focus', onFocus)" in page
    assert "clearInterval(timer)" in page
    assert "window.removeEventListener('focus', onFocus)" in page
    assert "warmModelAvailability();" in page
    # The warmer lives in a mount effect (useEffect with [] deps),
    # not in a click handler: it is background only, never on the
    # submit path.
    assert re.search(
        r"useEffect\(\(\) => \{\n    warmModelAvailability\(\);\n"
        r"    const timer = setInterval\(warmModelAvailability, "
        r"MODEL_AVAILABILITY_WARM_MS\);",
        page) is not None


def test_wizard_warmer_is_background_only():
    """warmModelAvailability is called from the import + the one
    mount effect only — never from next / back / finish or any
    submit path, where the verdict must already be warm."""
    page = WIZARD.read_text(encoding="utf-8")
    assert page.count("warmModelAvailability") == 4  # import + call + interval + focus
    assert page.count("MODEL_AVAILABILITY_WARM_MS") == 2  # import + interval
    assert "MODEL_AVAILABILITY_WARM_MS, warmModelAvailability" in page
    assert "from '../../lib/api'" in page


def test_no_other_wizard_warmer_double_warms():
    """No warmer already covered the wizard (which would make this
    one a duplicate): PrefChat and CompassPet only read
    modelAvailability() on demand per turn, never warm it, and the
    only warm call sites in the frontend are the wizard page and
    SimulatePanel (plus the definition in lib/api)."""
    assert "warmModelAvailability" not in PREF_CHAT.read_text(encoding="utf-8")
    assert "warmModelAvailability" not in COMPASS_PET.read_text(encoding="utf-8")
    callers = {
        str(p.relative_to(FRONTEND_SRC))
        for p in FRONTEND_SRC.rglob("*.tsx")
        if "warmModelAvailability" in p.read_text(encoding="utf-8")
    } | {
        str(p.relative_to(FRONTEND_SRC))
        for p in FRONTEND_SRC.rglob("*.ts")
        if "warmModelAvailability" in p.read_text(encoding="utf-8")
    }
    assert callers == {
        "app/wizard/page.tsx",
        "components/SimulatePanel.tsx",
        "lib/api.ts",
    }


def test_warmer_dedupes_and_honours_the_60s_cache():
    """The warmer is cheap because modelAvailability() dedupes
    concurrent callers (one shared in-flight read) and honours the
    60 s cache, and the 45 s warm interval sits inside that TTL —
    so a warm is a no-op when the verdict is fresh and one shared
    /ai/status read otherwise."""
    api = API_TS.read_text(encoding="utf-8")
    assert "export const MODEL_AVAILABILITY_WARM_MS = 45_000;" in api
    assert "const AI_STATUS_TTL_MS = 60_000;" in api
    assert 45_000 < 60_000
    assert "if (_aiStatusInFlight) return _aiStatusInFlight;" in api
    assert "void modelAvailability().catch(() => undefined);" in api


# ---------------------------------------------------------------------------
# (b) — the breaker trip hole: slow empty / unreadable replies
# ---------------------------------------------------------------------------

def test_breaker_trips_on_slow_empty_reply(monkeypatch):
    """A 200 with an empty body after real time trips the breaker:
    the first call raises kind=empty_reply, the second raises
    kind=gateway_breaker_open at once with no further transport
    call. Before this fix the empty raise sat outside the trip
    block, so every turn paid the wait again (re-test 22: the
    second pref turn took ~15-25 s). The mock sleeps 0.3 s with
    the latency gate lowered to 0.1 s (the real gate is 5 s)."""
    calls = {"n": 0}
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    adapter = _adapter(monkeypatch, _slow_empty_reply(calls))
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "empty_reply"
    assert gateway_breaker_open()
    t0 = time.monotonic()
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert time.monotonic() - t0 < 1
    assert excinfo.value.kind == "gateway_breaker_open"
    assert calls["n"] == 1, "breaker-open call must not touch the network"


def test_breaker_trips_on_slow_empty_reply_async(monkeypatch):
    """Same hole through achat(): the async twin raised its empty
    reply outside its trip block too, so it gets the same routing
    through _trips_breaker."""
    calls = {"n": 0}
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    adapter = _adapter(monkeypatch, _slow_empty_reply(calls))
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(adapter.achat([{"role": "user", "content": "hi"}],
                                  timeout_s=5.0))
    assert excinfo.value.kind == "empty_reply"
    assert gateway_breaker_open()
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(adapter.achat([{"role": "user", "content": "hi"}],
                                  timeout_s=5.0))
    assert excinfo.value.kind == "gateway_breaker_open"
    assert calls["n"] == 1, "breaker-open call must not touch the network"


def test_breaker_trips_on_slow_bad_reply(monkeypatch):
    """A 200 with an unreadable body after real time trips the
    breaker too: bad_reply was raised inside the try but
    _trips_breaker did not recognise the kind, so it never
    tripped either."""
    calls = {"n": 0}
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    adapter = _adapter(monkeypatch, _slow_bad_reply(calls))
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "bad_reply"
    assert gateway_breaker_open()
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "gateway_breaker_open"
    assert calls["n"] == 1, "breaker-open call must not touch the network"


def test_probe_trips_on_slow_empty_reply(monkeypatch):
    """The probe path had the same hole: _probe_chat_call consults
    _trips_breaker, which did not recognise empty_reply, so a probe
    that got a slow empty 200 reported unavailable without
    re-tripping the breaker. A /models-OK + slow-empty-chat probe
    now trips it (probe latency gate lowered to 0.1 s)."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        time.sleep(0.3)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": ""}}], "usage": {}})

    monkeypatch.setattr(provider_mod, "_PROBE_BREAKER_MIN_LATENCY_S", 0.1)
    adapter = _adapter(monkeypatch, handler)
    assert adapter.probe_live(timeout_s=10.0) is False
    assert gateway_breaker_open()
    assert calls["n"] == 2  # GET /models + the 1-token chat probe


def test_breaker_does_not_trip_on_slow_429(monkeypatch):
    """Pin kept green: a slow 429 never trips — the gateway is UP
    but throttling — so the next call still reaches the gateway."""
    calls = {"n": 0}
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    adapter = _adapter(monkeypatch, _slow_status(calls, 429))
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "provider_http"
    assert excinfo.value.status_code == 429
    assert not gateway_breaker_open()
    with pytest.raises(ProviderError):
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert calls["n"] == 2


def test_breaker_trips_on_slow_500(monkeypatch):
    """Pin kept green (Round 24 W4): a slow 5xx trips the breaker."""
    calls = {"n": 0}
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    adapter = _adapter(monkeypatch, _slow_status(calls, 502))
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "provider_http"
    assert excinfo.value.status_code == 502
    assert gateway_breaker_open()
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "gateway_breaker_open"
    assert calls["n"] == 1, "breaker-open call must not touch the network"


def test_breaker_does_not_trip_on_fast_500(monkeypatch):
    """Pin kept green: a fast 5xx does not trip — one transient
    500 is not evidence the gateway is down."""
    calls = {"n": 0}
    adapter = _adapter(monkeypatch, _slow_status(calls, 502, delay_s=0.0))
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "provider_http"
    assert not gateway_breaker_open()
    with pytest.raises(ProviderError):
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert calls["n"] == 2


def test_breaker_does_not_trip_on_fast_empty_reply(monkeypatch):
    """Latency gate pin for the new kinds: a FAST empty reply does
    not trip — it failed fast, so repeating it costs nothing, and
    tripping on it would poison later calls for no saving."""
    calls = {"n": 0}
    adapter = _adapter(monkeypatch, _slow_empty_reply(calls, delay_s=0.0))
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "empty_reply"
    assert not gateway_breaker_open()
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "empty_reply"
    assert calls["n"] == 2


def test_breaker_does_not_trip_on_fast_bad_reply(monkeypatch):
    """Same latency gate for bad_reply: an instantly unreadable
    200 does not trip."""
    calls = {"n": 0}
    adapter = _adapter(monkeypatch, _slow_bad_reply(calls, delay_s=0.0))
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "bad_reply"
    assert not gateway_breaker_open()
    with pytest.raises(ProviderError):
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Pref level — the re-test 22 shape, end to end
# ---------------------------------------------------------------------------

def test_pref_first_slow_empty_fallback_second_turn_no_model_attempt(monkeypatch):
    """Mocked gateway down (slow empty 200s), cold cache, closed
    breaker — the re-test 22 shape. The FIRST pref turn pays the
    model budget once (inherent — no latency asserted, only that
    it returns the fallback with the answer recorded), the SECOND
    pref turn returns the fallback without a model attempt: the
    slow empty reply tripped the breaker, so model_skip_cached()
    skips the call and the turn is engine time. Before this fix
    the second turn paid the budget again (~15-25 s in the
    browser)."""
    calls = {"n": 0}
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    adapter = _adapter(monkeypatch, _slow_empty_reply(calls))
    first = pref_answer("我想去瑞士，因为那边环境优美", "zh-CN",
                        known={}, provider=adapter)
    assert first["ai_status"] == "unavailable"
    assert first["extracted"].get("countries") == ["CH"]
    assert calls["n"] == 1
    assert gateway_breaker_open()

    t0 = time.monotonic()
    second = pref_answer("我喜欢凉爽的地方", "zh-CN",
                         known={"countries": ["CH"]}, provider=adapter)
    assert time.monotonic() - t0 < 1
    assert second["ai_status"] == "unavailable"
    assert second["extracted"].get("climate") == "cool"
    assert calls["n"] == 1, "second turn must not touch the network"
