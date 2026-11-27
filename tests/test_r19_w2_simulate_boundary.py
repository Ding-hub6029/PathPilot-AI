"""Round 19 W2 — simulate panel boundary wording + first-click timing.

Nit 3 (re-test task 13): the simulate panel's static header still said
"AI 生成的解读" even when the summary above it said the model was
unconnected ("规则摘要——未连接 AI 模型"). The header must describe
the explanation actually shown: the AI wording only when the model
really wrote it (explanation.source == 'model'), the template
wording otherwise — before any run, and after a template run.

First-click timing (measured, not guessed): re-test task 13 reported
the first simulate run at "<=60 s" (minute-level clock) and the
second at "<=10 s", model down. Round 18 added mount warming
(SimulatePanel: warmModelAvailability() on mount, every 45 s, on
focus) and a 180 s breaker. This file measures the cold-click cost
honestly with a real uvicorn-style harness (real HTTP mock gateway,
cold probe cache + cold breaker, audit profile, matchable ids,
explain:true): the frontend click sequence (cold /ai/status probe
then explain:false) and the raw explain:true cold call (the path
taken when the frontend verdict is 'unknown' and the gate cannot
skip the model attempt).

Harness: real ThreadingHTTPServer mock gateway (httpx MockTransport
does NOT enforce timeouts, so a hanging gateway can only be
simulated over real sockets), same modes as test_r18_w2_latency.py:
healthy-json, flap (GET /models 200 at once, POST /chat/completions
hangs 30 s — the audit's gateway), hang-all (both hang 30 s).

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r19_w2_simulate_boundary.py
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import ai.provider as provider_mod
import app.main as app_main
from ai.provider import gateway_breaker_open, reset_gateway_breaker
from app.main import app, reset_ai_status_cache, reset_rate_limits

client = TestClient(app)

ROOT = Path(__file__).resolve().parents[1]
MESSAGES = ROOT / "frontend" / "messages"
PANEL = ROOT / "frontend" / "src" / "components" / "SimulatePanel.tsx"
LOCALES = ["ar", "en", "es", "fr", "pt-BR", "zh-CN"]

# Audit profile (browser re-test task 12/13): China Gaokao, UG, CS,
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
SCENARIOS = [
    {"name": "IELTS overall +0.5", "patch": {"ieltsOverall": 7.5}},
    {"name": "IELTS Writing +0.5", "patch": {"ieltsWriting": 7.0}},
    {"name": "Budget +£10,000", "patch": {"budget": 60000}},
]

# The template wording must never claim an AI generated it, in any
# locale. (zh "AI 生成", en "AI-generated", es "generada por IA",
# fr "générée par l'IA", pt "gerada por IA", ar "مولّدة بالذكاء".)
AI_GENERATION_MARKERS = [
    "AI 生成", "AI-generated", "generada por IA", "générée par l'IA",
    "gerada por IA", "مولّدة بالذكاء",
]


def _msgs(loc: str) -> dict:
    return json.loads((MESSAGES / f"{loc}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _isolate():
    reset_rate_limits()
    reset_ai_status_cache()
    reset_gateway_breaker()
    yield
    reset_rate_limits()
    reset_ai_status_cache()
    reset_gateway_breaker()


# ---------------------------------------------------------------------------
# Nit 3 — the new template boundary key, all 6 locales in sync
# ---------------------------------------------------------------------------

def test_boundary_template_key_exists_in_all_locales():
    """sim.boundaryTemplate exists, non-empty, in every locale, and
    the locale files stay in sync with each other. The count is
    asserted relatively (all six equal, at least the 964 this round
    adds to the 963 at Round 18) rather than as an absolute number,
    so a sibling worker adding keys in the same round cannot break
    this test — the absolute count is the coordinator's to pin."""
    counts = set()
    for loc in LOCALES:
        msgs = _msgs(loc)
        counts.add(len(msgs))
        assert msgs["sim.boundaryTemplate"].strip(), loc
        assert "sim.boundary" in msgs, loc
    assert len(counts) == 1, f"locale key counts diverged: {counts}"
    assert counts.pop() >= 964, counts


def test_boundary_template_never_claims_ai_generation():
    """The template wording must not say an AI generated anything,
    in any locale — that was the nit: the header claimed an
    AI-generated reading while the model was unconnected."""
    for loc in LOCALES:
        text = _msgs(loc)["sim.boundaryTemplate"]
        for marker in AI_GENERATION_MARKERS:
            assert marker not in text, f"{loc}: {marker!r} in {text!r}"
        assert "AI" not in text or "未使用 AI" in text or "no ai model" in text.lower() \
            or "sin modelo de IA" in text or "sans modèle d'IA" in text \
            or "sem modelo de IA" in text or "دون استخدام نموذج" in text, loc


def test_boundary_template_keeps_verified_facts_second_half():
    """The template wording keeps the existing boundary's second
    half verbatim: engine numbers are verified facts, suggestions
    are suggestions — only the first clause (who wrote it) changes."""
    zh = _msgs("zh-CN")
    assert zh["sim.boundaryTemplate"] == (
        "规则摘要，未使用 AI 模型，仅供参考，请以大学官网为准。"
        "引擎数字是已核实的事实；建议只是建议，不是事实。")
    assert zh["sim.boundaryTemplate"].endswith(
        "，仅供参考，请以大学官网为准。引擎数字是已核实的事实；建议只是建议，不是事实。")
    assert zh["sim.boundary"].endswith(
        "，仅供参考，请以大学官网为准。引擎数字是已核实的事实；建议只是建议，不是事实。")
    en = _msgs("en")
    assert en["sim.boundaryTemplate"].endswith(
        "Engine numbers are verified facts; suggestions are suggestions, not facts.")
    assert en["sim.boundary"].endswith(
        "Engine numbers are verified facts; suggestions are suggestions, not facts.")


def test_boundary_key_unchanged():
    """The AI wording itself is untouched (regression guard from
    test_r13_frontend_failfast.py, restated here so this round's
    edit cannot silently rewrite it)."""
    zh = _msgs("zh-CN")
    assert zh["sim.boundary"] == (
        "AI 生成的解读，仅供参考，请以大学官网为准。"
        "引擎数字是已核实的事实；建议只是建议，不是事实。")


# ---------------------------------------------------------------------------
# Nit 3 — the panel renders the boundary conditionally, at both sites
# ---------------------------------------------------------------------------

def test_panel_boundary_is_conditional_on_explanation_source():
    """Both boundary sites share one conditional keyed on the actual
    explanation source: 'sim.boundary' only when
    result.explanation.source === 'model', 'sim.boundaryTemplate'
    otherwise. No unconditional t('sim.boundary') may remain."""
    panel = PANEL.read_text(encoding="utf-8")
    assert "result?.explanation?.source === 'model'" in panel
    assert "const boundaryKey = explanationIsModel ? 'sim.boundary' : 'sim.boundaryTemplate'" in panel
    assert panel.count("t(boundaryKey)") == 2, (
        "both boundary sites (header + explanation footer) must use the conditional key")
    assert "t('sim.boundary')" not in panel, (
        "no unconditional AI-boundary render may remain")
    assert "t('sim.boundaryTemplate')" not in panel, (
        "the template key must only be reached through the conditional")


def test_panel_boundary_resolves_to_honest_text_in_both_states():
    """Data-level render check (zh-CN): resolving the panel's
    conditional per explanation source gives the honest text in
    both states — template wording with no "AI 生成" when the
    model is down, AI wording only when the model really wrote it."""
    zh = _msgs("zh-CN")

    def boundary_text(source):
        key = "sim.boundary" if source == "model" else "sim.boundaryTemplate"
        return zh[key]

    assert boundary_text(None) == (
        "规则摘要，未使用 AI 模型，仅供参考，请以大学官网为准。"
        "引擎数字是已核实的事实；建议只是建议，不是事实。")
    assert "AI 生成" not in boundary_text(None)
    assert boundary_text("template") == boundary_text(None)
    assert boundary_text("model") == zh["sim.boundary"]
    assert boundary_text("model").startswith("AI 生成的解读")


def test_panel_warming_is_wired_on_mount():
    """Round 18 warming really is wired (and still is after this
    round's edit): warm on mount, every 45 s, on window focus,
    cleaned up on unmount. The warming code is TS-only, so this
    grep pins it; the timing tests below measure what it buys."""
    panel = PANEL.read_text(encoding="utf-8")
    assert "warmModelAvailability();" in panel
    assert "setInterval(warmModelAvailability, MODEL_AVAILABILITY_WARM_MS)" in panel
    assert "window.addEventListener('focus', onFocus)" in panel
    assert "clearInterval(timer)" in panel


# ---------------------------------------------------------------------------
# Timing harness (real HTTP mock gateway, audit scale)
# ---------------------------------------------------------------------------

VALID_EXPLAIN = {
    "summary": "The budget change mattered most.",
    "claims": [],
    "unknowns": [],
    "actions": [],
    "limitations": [],
}


class _MockGateway:
    """Same modes as test_r18_w2_latency.py: healthy-json (chat 200
    after 0.3 s, valid structured explanation), flap (GET /models
    200 at once, POST /chat/completions hangs 30 s), hang-all (both
    hang 30 s)."""

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
                if gateway.mode in ("hang-all", "flap"):
                    time.sleep(30)
                    self._json(200, {"choices": [{"message": {"content": "ok"}}],
                                     "usage": {}})
                else:
                    time.sleep(0.3)
                    self._json(200, {"choices": [{"message": {
                        "content": json.dumps(VALID_EXPLAIN)}}], "usage": {}})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()

    def posts(self) -> int:
        with self._lock:
            return sum(1 for m, _ in self.requests if m == "POST")


@pytest.fixture
def gateway(monkeypatch):
    with _MockGateway() as gw:
        for key, value in {
            "AI_PROVIDER": "openai",
            "AI_MODEL": "mock-r19-model",
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
# Timing: first simulate click, model down (flap = audit gateway)
# ---------------------------------------------------------------------------

def test_first_click_cold_frontend_sequence_flap(gateway, capsys):
    """MEASURED — the actual frontend click sequence on a flapping
    gateway, cold probe cache + cold breaker: the click's
    modelAvailability() gate pays the cold /ai/status probe, then
    simulateMulti sends explain:false (engine time only). Before
    Round 18 this was probe 7.23 s + engine 2.42 s = 9.65 s; the
    mount warming added in Round 18 only helps if the results page
    has been open long enough for the mount probe to finish — a
    click inside the probe window still pays the probe (the gate
    dedupes onto the in-flight probe)."""
    gateway.mode = "flap"
    r, t_probe = _timed(_status)
    assert r.json()["ai_status"] == "unavailable"
    assert gateway_breaker_open()
    ids = _matchable_ids()
    print(f"\n[R19-W2] audit-scale ids sent to /simulate: {len(ids)}")
    posts = gateway.posts()
    r, t_engine = _timed(lambda: _simulate(ids, False))
    assert r.status_code == 200, r.text
    assert r.json()["explanation"]["source"] == "template"
    assert gateway.posts() == posts, "template simulate must not call the gateway"
    total = t_probe + t_engine
    print(f"[R19-W2] COLD first click (flap, frontend sequence): "
          f"probe {t_probe:.2f}s + engine {t_engine:.2f}s = {total:.2f}s")
    assert t_probe < 10, f"cold probe took {t_probe:.1f}s"
    assert t_engine < 5, f"cold engine took {t_engine:.2f}s"
    assert total < 15, f"cold first click took {total:.1f}s"


def test_second_click_warm_verdict_flap(gateway, capsys):
    """MEASURED — the second click with the verdict warm (probe
    already ran, breaker open): the gate reads the cached verdict
    and the click is engine time only."""
    gateway.mode = "flap"
    r, _ = _timed(_status)
    assert r.json()["ai_status"] == "unavailable"
    ids = _matchable_ids()
    r, t_warm = _timed(lambda: _simulate(ids, False))
    assert r.status_code == 200, r.text
    assert r.json()["explanation"]["source"] == "template"
    print(f"[R19-W2] WARM second click (flap): {t_warm:.2f}s")
    assert t_warm < 5, f"warm click took {t_warm:.1f}s"


def test_raw_explain_true_cold_burns_model_budget_flap(gateway, capsys):
    """MEASURED — the path the frontend gate exists to avoid: a raw
    explain:true call with a cold breaker and no cached verdict
    (what happens when the frontend verdict is 'unknown' — backend
    asleep, status read failed — so the gate cannot skip the model
    attempt). The backend spends the full 15 s model budget proving
    the gateway is down before the template renders. This is NOT
    fixed by mount warming: no cache can know the gateway died
    since the last probe. Pinned so it cannot silently grow."""
    gateway.mode = "flap"
    ids = _matchable_ids()
    posts_before = gateway.posts()
    r, elapsed = _timed(lambda: _simulate(ids, True))
    assert r.status_code == 200, r.text
    assert r.json()["explanation"]["source"] == "template"
    assert r.json()["explanation"]["ai_status"] == "unavailable"
    assert gateway.posts() == posts_before + 1, "one model attempt expected"
    assert gateway_breaker_open()
    print(f"[R19-W2] COLD raw explain:true (flap, no gate): {elapsed:.2f}s")
    assert 14 < elapsed < 25, (
        f"cold explain:true burn was {elapsed:.1f}s, expected ~15s + engine")


def test_cold_probe_hang_all(gateway, capsys):
    """MEASURED — cold probe when the gateway hangs on BOTH
    endpoints (worst case): the probe still returns 'unavailable'
    within its budget and trips the breaker, so the click after it
    is engine time only."""
    gateway.mode = "hang-all"
    r, t_probe = _timed(_status)
    assert r.json()["ai_status"] == "unavailable"
    assert gateway_breaker_open()
    print(f"[R19-W2] COLD probe (hang-all): {t_probe:.2f}s")
    assert t_probe < 15, f"hang-all probe took {t_probe:.1f}s"
    ids = _matchable_ids()
    r, t_engine = _timed(lambda: _simulate(ids, False))
    assert r.status_code == 200, r.text
    print(f"[R19-W2] post-probe simulate (hang-all): {t_engine:.2f}s")
    assert t_engine < 5, f"post-probe engine took {t_engine:.2f}s"


def test_healthy_gateway_simulate_returns_model_source(gateway):
    """Model-up branch: with a healthy gateway, explain:true really
    returns source='model' / ai_status='available' — the response
    the panel's conditional keys on, so the AI boundary wording is
    reachable and only reachable on a real model answer."""
    gateway.mode = "healthy-json"
    ids = _matchable_ids()
    r, elapsed = _timed(lambda: _simulate(ids, True))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["explanation"]["source"] == "model", body["explanation"]
    assert body["explanation"]["ai_status"] == "available"
    assert elapsed < 10, f"healthy explain:true took {elapsed:.1f}s"
