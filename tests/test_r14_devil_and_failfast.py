"""Round 14 W2 (devil toggle + model-availability track) regression tests.

Finding 1 — the devil's-advocate toggle vanished (re-test task 8,
2026-11-27): it appeared exactly once, on the first results-page load
from a stale ``pp-pet-open`` session flag, and never came back after a
pref-chat reset + two full wizard runs with the identical 8/8
preference summary. The toggle JSX had NO profile gate — it rendered
whenever the panel was open — and the panel opens on load ONLY from
that session flag, which every close path removed, while the wizard
finishes with router.push('/results') (client-side navigation: the
layout never remounts, the mount restore never re-runs). These tests
pin the fix in CompassPet.tsx (source pins — there is no JS test
runner in this repo, same approach as test_r13_frontend_failfast.py):
the toggle renders exactly when saved preferences exist
(devilProfileFor(profile) != null); the panel re-opens on arrival at
/results with challengeable preferences unless explicitly dismissed;
navigation-link closes keep the open memory, explicit closes record
the dismiss.

Finding 2 — /ai/status was config-only: it reported "available"
whenever a key was configured, so it said "available" through the
whole 2026-11-27 00:42-00:50 gateway outage while every model path
was template-only. It is now a live probe (GET /models, else one
1-token chat call), cached 60 s, and a slow gateway failure trips a
circuit breaker in the provider so later model attempts fail fast
instead of each spending 15 s. The rate-limit keying needed no fix:
it is already per-user via X-Forwarded-For (Round 13 tests
test_rate_limit_* in test_r13_failfast.py pin it, including the
/simulate manual check).

Finding 3 — simulate/plan took 20-25 s when the model was down (the
15 s model budget spent before the template rendered). The fix is at
the request layer: simulateMulti asks the live /ai/status signal
first and sends explain:false at once when the model is known
unavailable; createPlan runs the same status read first (the failed
probe trips the backend breaker, so the plan POST returns template
tasks in engine time — the plan endpoint has no template-only flag,
the plan itself can only be created server-side). A failed status
read ('unknown': backend asleep, network error) still attempts the
model once. These tests pin both the frontend branching (source pins)
and the backend behaviour (live TestClient timings with a gateway
that hangs / fails fast).

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r14_devil_and_failfast.py
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as app_main
import app.router_plans as router_plans
import ai.provider as provider_mod
from ai.provider import (
    ProviderAdapter,
    ProviderError,
    gateway_breaker_open,
    reset_gateway_breaker,
)
from app.main import app, reset_ai_status_cache, reset_rate_limits

client = TestClient(app)

ROOT = Path(__file__).resolve().parent.parent
PET = ROOT / "frontend" / "src" / "components" / "CompassPet.tsx"
SIMULATE_TS = ROOT / "frontend" / "src" / "lib" / "simulate.ts"
PLANS_TS = ROOT / "frontend" / "src" / "lib" / "plans.ts"
API_TS = ROOT / "frontend" / "src" / "lib" / "api.ts"

_MOCK_ENV = {
    "AI_PROVIDER": "openai",
    "AI_MODEL": "mock-r14-model",
    "AI_API_KEY": "mock-test-key",
    "AI_BASE_URL": "https://api.example.test/v1",
}


def _plans_app() -> TestClient:
    test_app = FastAPI()
    test_app.include_router(router_plans.router)
    return TestClient(test_app)


@pytest.fixture(autouse=True)
def _isolate():
    reset_rate_limits()
    reset_ai_status_cache()
    reset_gateway_breaker()
    yield
    reset_rate_limits()
    reset_ai_status_cache()
    reset_gateway_breaker()


def _mock_adapter(monkeypatch, handler) -> ProviderAdapter:
    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    adapter = ProviderAdapter(_transport=httpx.MockTransport(handler))
    monkeypatch.setattr(app_main, "ProviderAdapter", lambda: adapter)
    return adapter


# ---------------------------------------------------------------------------
# Finding 2a — /ai/status is a live probe now, not a config echo
# ---------------------------------------------------------------------------

def test_ai_status_unconfigured_reports_unavailable_without_probe(monkeypatch):
    """No provider configured: unavailable at once, probed=False —
    there is no gateway to probe, so no network call is attempted."""
    for key in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    t0 = time.monotonic()
    r = client.get("/api/v1/ai/status")
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 2, f"unconfigured status took {elapsed:.1f}s"
    body = r.json()
    assert body["ai_status"] == "unavailable"
    assert body["probed"] is False
    assert body["api_key_configured"] is False


def test_ai_status_live_probe_available_and_cached(monkeypatch):
    """Gateway answers GET /models AND the 1-token chat confirmation:
    available, probed=True — and the second call within the 60 s TTL
    does NOT probe again (neither endpoint is called again).
    Pre-fix this returned "available" without ever touching the
    gateway, so it could not distinguish a live gateway from a dead
    one. Round 16 W3: GET /models 200 alone no longer means live —
    the audit's gateway answered the list endpoint while
    /chat/completions hung, so the probe confirms on the chat path
    before reporting available."""
    calls = {"models": 0, "chat": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/models"):
            calls["models"] += 1
            return httpx.Response(200, json={"data": [{"id": "mock-r14-model"}]})
        assert request.method == "POST" and request.url.path.endswith("/chat/completions")
        calls["chat"] += 1
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}], "usage": {}})

    _mock_adapter(monkeypatch, _handler)
    r = client.get("/api/v1/ai/status")
    assert r.status_code == 200, r.text
    assert r.json()["ai_status"] == "available"
    assert r.json()["probed"] is True
    assert calls == {"models": 1, "chat": 1}, (
        "available must mean the list endpoint AND the chat path "
        "both answered")
    r = client.get("/api/v1/ai/status")
    assert r.json()["ai_status"] == "available"
    assert calls == {"models": 1, "chat": 1}, (
        "second status read within TTL must not re-probe")


def test_ai_status_live_probe_down_reports_unavailable_and_trips_breaker(monkeypatch):
    """Gateway unreachable (connect error on the probe): unavailable,
    probed=True — and the breaker is tripped, so a later model attempt
    fails at once WITHOUT another network call (the handler count does
    not move). Pre-fix this returned "available" and every model path
    then spent 15 s each proving the gateway was down."""
    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("gateway down", request=request)

    # The mock raises instantly; the latency gate would (correctly)
    # not trip on a zero-time failure, so drop the gate for this test
    # — the behaviour under test is "a waited-out probe failure trips
    # the breaker", and the real probe waits its 3 s budget first.
    monkeypatch.setattr(provider_mod, "_PROBE_BREAKER_MIN_LATENCY_S", 0)
    _mock_adapter(monkeypatch, _handler)
    t0 = time.monotonic()
    r = client.get("/api/v1/ai/status")
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"down-gateway status took {elapsed:.1f}s"
    assert r.json()["ai_status"] == "unavailable"
    assert r.json()["probed"] is True
    assert gateway_breaker_open()
    before = calls["n"]
    with pytest.raises(ProviderError) as excinfo:
        ProviderAdapter(_transport=httpx.MockTransport(_handler)).chat(
            [{"role": "user", "content": "hi"}])
    assert excinfo.value.kind == "gateway_breaker_open"
    assert calls["n"] == before, "breaker-open call must not touch the network"


def test_ai_status_probe_falls_back_to_chat_when_models_list_missing(monkeypatch):
    """A gateway that does not implement GET /models (404) is NOT
    declared down on that alone: the probe falls back to one tiny
    chat call, and a healthy chat answer means available. (The
    shenjyai gateway's /models support is unverified, so this path
    must work.)"""
    calls = {"models": 0, "chat": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            calls["models"] += 1
            return httpx.Response(404, json={"error": "not found"})
        calls["chat"] += 1
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}], "usage": {}})

    _mock_adapter(monkeypatch, _handler)
    r = client.get("/api/v1/ai/status")
    assert r.status_code == 200, r.text
    assert r.json()["ai_status"] == "available"
    assert r.json()["probed"] is True
    assert calls == {"models": 1, "chat": 1}


# ---------------------------------------------------------------------------
# Finding 2b — circuit breaker: slow failures trip it, fast ones do not
# ---------------------------------------------------------------------------

def test_breaker_trips_on_timeout_and_second_call_is_instant(monkeypatch):
    """A hanging gateway (read timeout) trips the breaker: the first
    chat raises kind=timeout, the second raises kind=
    gateway_breaker_open at once with no further transport call.
    A later healthy probe clears the breaker and chat works again."""
    calls = {"n": 0}

    def _hanging(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("gateway hung", request=request)

    # Instant mock raise: drop the latency gate (see the probe test
    # above) so this test exercises the trip itself, not the wait.
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0)
    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    adapter = ProviderAdapter(_transport=httpx.MockTransport(_hanging))
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "timeout"
    assert gateway_breaker_open()
    t0 = time.monotonic()
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert time.monotonic() - t0 < 1
    assert excinfo.value.kind == "gateway_breaker_open"
    assert calls["n"] == 1, "breaker-open call must not touch the network"

    def _healthy(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}], "usage": {}})

    adapter._transport = httpx.MockTransport(_healthy)
    assert adapter.probe_live() is True
    assert not gateway_breaker_open()
    result = adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert result.text == "ok"


def test_breaker_does_not_trip_on_instant_timeout(monkeypatch):
    """Latency gate: a timeout raised INSTANTLY (no time consumed)
    must not trip the breaker. The 12-case evaluation set's
    failure-timeout mock raises ReadTimeout immediately, and tripping
    on it used to poison every later case in the run — and every
    later mock-model test in the process — into template-only for
    60 s. Only a failure that actually waited trips it."""
    calls = {"n": 0}

    def _instant_timeout(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("mock provider timeout", request=request)

    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    adapter = ProviderAdapter(_transport=httpx.MockTransport(_instant_timeout))
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "timeout"
    assert not gateway_breaker_open()
    # The next call still reaches the gateway (nothing was skipped).
    with pytest.raises(ProviderError):
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert calls["n"] == 2


def test_breaker_does_not_trip_on_fast_500(monkeypatch):
    """A fast HTTP 500 already fails fast — it is not evidence the
    gateway is down, so it must NOT trip the breaker: the next call
    still reaches the gateway (handler called again). Tripping here
    would turn one transient 500 into 60 s of template-only."""
    calls = {"n": 0}

    def _failing(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"error": "gateway error"})

    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    adapter = ProviderAdapter(_transport=httpx.MockTransport(_failing))
    with pytest.raises(ProviderError) as excinfo:
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert excinfo.value.kind == "provider_http"
    assert not gateway_breaker_open()
    with pytest.raises(ProviderError):
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Finding 3 (backend half) — with the breaker open, template is fast
# ---------------------------------------------------------------------------

def _simulate_body() -> dict:
    return {
        "baseline_profile": {
            "track": "undergraduate", "targetProgramIds": ["ucl-cs-bsc-2026"],
            "alevels": "A*A*A", "mathsGrade": "A*",
            "ieltsOverall": 7.0, "ieltsListening": 6.5, "ieltsReading": 6.5,
            "ieltsWriting": 5.5, "ieltsSpeaking": 6.5,
            "budget": 50000, "budgetCurrency": "GBP"},
        "scenarios": [{"name": "writing", "patch": {"ieltsWriting": 6.5}}],
        "program_ids": ["ucl-cs-bsc-2026"], "explain": True}


def test_simulate_with_breaker_open_returns_template_without_model_call(monkeypatch):
    """Gateway hung once (timeout) -> breaker open -> a /simulate
    explain:true returns the template with the correct engine numbers
    and NO further gateway call. Without the breaker every such call
    spent the 15 s model budget first (parent curl: 15.37 s)."""
    calls = {"n": 0}

    def _hanging(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("gateway hung", request=request)

    # Instant mock raise: drop the latency gate (see the probe test
    # above) so this test exercises the trip itself, not the wait.
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0)
    adapter = _mock_adapter(monkeypatch, _hanging)
    # The first model attempt hangs and trips the breaker.
    with pytest.raises(ProviderError):
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert calls["n"] == 1 and gateway_breaker_open()
    reset_rate_limits()
    t0 = time.monotonic()
    r = client.post("/api/v1/simulate", json=_simulate_body())
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"breaker-open simulate took {elapsed:.1f}s"
    body = r.json()
    assert body["explanation"]["source"] == "template"
    assert body["explanation"]["ai_status"] == "unavailable"
    assert body["leverage"]["top"]["id"] == "ielts-writing-plus-0.5"
    assert calls["n"] == 1, "breaker-open simulate must not call the gateway"


def test_plan_with_breaker_open_returns_template_tasks_without_model_call(monkeypatch):
    """Same for /improvement-plan: with the breaker open the plan
    returns template tasks in engine time and no gateway call is
    made. (The plan endpoint has no template-only flag, so the
    breaker is what makes the frontend's pre-check effective.)"""
    calls = {"n": 0}

    def _hanging(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("gateway hung", request=request)

    # Instant mock raise: drop the latency gate (see the probe test
    # above) so this test exercises the trip itself, not the wait.
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0)
    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    adapter = ProviderAdapter(_transport=httpx.MockTransport(_hanging))
    monkeypatch.setattr(router_plans, "get_provider", lambda: adapter)
    with pytest.raises(ProviderError):
        adapter.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert calls["n"] == 1 and gateway_breaker_open()
    body = {"profile": {
        "application_track": "undergraduate",
        "undergrad_profile": {
            "qualification_type": "a_level", "curriculum": "uk_alevel",
            "a_level_grades": ["A*", "A*", "A"], "a_level_maths_grade": "A*",
            "gcse_english_grade": "C", "gcse_maths_grade": "4",
            "residency": "overseas"},
        "language": {"exam": "ielts", "overall": 6.5, "listening": 6.5,
                     "reading": 6.5, "writing": 5.5, "speaking": 6.0},
        "budget": {"amount": 48600, "currency": "GBP", "period": "per_year"},
        "target_intake": 2026},
        "program_ids": ["ucl-cs-bsc-2026"],
        "weekly_hours": 6, "budget": None, "deadline": None, "locale": "en"}
    t0 = time.monotonic()
    r = _plans_app().post("/api/v1/improvement-plan", json=body)
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"breaker-open plan took {elapsed:.1f}s"
    assert r.json()["ai_status"] == "unavailable"
    assert r.json()["tasks"], "template tasks must cover the gaps"
    assert calls["n"] == 1, "breaker-open plan must not call the gateway"


# ---------------------------------------------------------------------------
# Finding 3 (frontend half) — skip logic, source pins (no JS runner)
# ---------------------------------------------------------------------------

def test_simulate_skips_model_when_status_says_unavailable():
    src = SIMULATE_TS.read_text(encoding="utf-8")
    assert "modelAvailability" in src
    body = src.split("export async function simulateMulti")[1]
    # Only 'unavailable' skips: 'unknown' (status read failed) still
    # attempts the model once — the pin must be !== 'unavailable',
    # never === 'available'.
    assert "(await modelAvailability()) !== 'unavailable'" in body
    assert "const explain = wantExplain &&" in body
    # The request body carries the computed flag, not the raw option.
    assert re.search(r"explain,\n", body), body
    assert "explain: opts?.explain ?? true" not in body


def test_create_plan_probes_status_before_post():
    src = PLANS_TS.read_text(encoding="utf-8")
    body = src.split("export async function createPlan")[1].split(
        "export async function getPlan")[0]
    # The status read runs before the POST (its failed probe is what
    # trips the backend breaker, so the POST returns template tasks
    # in engine time). The patient budgets are unchanged (Round 13).
    assert "await modelAvailability();" in body
    assert body.index("await modelAvailability();") < body.index("fetchJsonPatient<Plan>")
    assert len(re.findall(r"attemptTimeoutMs:\s*40_000", src)) >= 2
    assert len(re.findall(r"budgetMs:\s*90_000", src)) >= 2


def test_model_availability_helper_contract():
    src = API_TS.read_text(encoding="utf-8")
    assert "export async function modelAvailability" in src
    body = src.split("export async function modelAvailability")[1].split(
        "export function resetModelAvailabilityCache")[0]
    # Cached 60 s, shared in-flight read, 12 s read budget.
    assert "AI_STATUS_TTL_MS = 60_000" in src
    assert "AI_STATUS_TIMEOUT_MS = 12_000" in src
    assert "_aiStatusInFlight" in body
    # A failed status read is 'unknown' (attempt the model once),
    # never 'unavailable' and never an error.
    assert "'unknown'" in body
    assert ".catch(() => 'unknown'" in body


# ---------------------------------------------------------------------------
# Finding 1 — devil toggle: profile-gated, restores on /results
# ---------------------------------------------------------------------------

def test_devil_toggle_gated_on_saved_preferences():
    src = PET.read_text(encoding="utf-8")
    # Presence is a pure function of the durable profile, never of
    # session flags: non-null exactly when there are saved preferences
    # to challenge (countries, climate, level, budget or city).
    assert "const canDevil = devilProfileFor(profile) !== null;" in src
    # The toggle JSX lives inside the canDevil conditional — the old
    # unconditional footer button is gone.
    idx = src.index("{canDevil && (")
    assert "devil.toggle" in src[idx:], "toggle must render inside canDevil gate"
    assert "devil.toggleActive" in src[idx:]
    # The devil send path is untouched: mode=devil + devilProfileFor.
    assert "mode: 'devil'" in src
    assert "devilProfileFor(profile)" in src


def test_pet_restores_on_results_with_prefs_unless_dismissed():
    src = PET.read_text(encoding="utf-8")
    # The restore is driven by the route + the durable profile, not
    # only by the mount-time session flag (which client-side
    # navigation never re-runs): arriving at /results with
    # challengeable preferences re-opens the panel.
    assert "usePathname" in src
    assert "pathname !== '/results'" in src
    assert "pp-pet-dismissed" in src
    effect = src.split("pathname !== '/results'")[1].split("}, [pathname")[0]
    assert "canDevil" in effect
    assert "setOpen(true)" in effect
    # It never steals input focus on a page load (no toggle(true) CALL).
    # Round 25 W3: the effect's comment now mentions toggle(true) by
    # name, so strip line comments before checking for the call.
    code = re.sub(r"//.*", "", effect)
    assert "toggle(true)" not in code
    # An explicit close records the dismiss; opening clears it.
    toggle_fn = src.split("const toggle = ")[1].split("const closeForNavigation")[0]
    assert "sessionStorage.setItem('pp-pet-dismissed', '1')" in toggle_fn
    assert "sessionStorage.removeItem('pp-pet-dismissed')" in toggle_fn


def test_navigation_link_closes_keep_open_memory():
    src = PET.read_text(encoding="utf-8")
    # Pet next-step / edit-preferences links close the panel for the
    # navigation but must NOT erase the open memory or record a
    # dismiss — the old toggle(false) here is what lost the toggle
    # for the rest of the session after one wizard trip.
    assert "const closeForNavigation = " in src
    nav_fn = src.split("const closeForNavigation = ")[1].split("};")[0]
    assert "setOpen(false)" in nav_fn
    assert "pp-pet-open" not in nav_fn
    assert "pp-pet-dismissed" not in nav_fn
    assert src.count("onClick={closeForNavigation}") == 5, (
        "all five pet links (prefEdit + wizard/programme/institution "
        "next steps + the Restyle 2 compare suggestion) must use closeForNavigation")
    # The explicit closes (x button, Escape, floating button) still
    # go through toggle(false) and therefore record the dismiss.
    assert "toggle(false)" in src
