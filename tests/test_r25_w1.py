"""Round 25 W1 — with-profile fee questions are slow and inconsistent
(re-test task 19, P1).

Tester finding: WITHOUT a profile the fee flow is instant (offline
list -> tap Undergraduate -> fee line at once). WITH a profile the
same question sometimes takes ~15 s (the AI attempt timing out, then
falling back to the offline list / fee line) and sometimes goes down
the AI path and answers directly, skipping the disambiguation list
entirely — the same question flips between the two behaviours run to
run.

Root cause (reproduced first, /tmp/r25w1-repro.py — BEFORE numbers):
every /assistant/chat turn with a key configured attempted the model
first, and the only fail-fast was the circuit breaker, which only
opens AFTER a slow failure and only for 180 s. So the outcome of a
turn depended on gateway/breaker timing, not on the question:
- fee Q + profile, hanging gateway, fresh breaker: 16.4 / 16.1 /
  16.0 s (3 runs) -> template ambiguous list;
- same Q, healthy gateway: 0.10 s, ai_status=available, NO
  candidates — the model answered directly, skipping the list;
- single-match fee Q, hanging gateway, probe cache seeded
  "unavailable": 16.07 s — the backend ignored the known-down
  verdict (the _model_skip_cached parity /simulate has, which lived
  in app.main and /assistant/chat could not import without a
  circular import);
- fee Q WITHOUT profile, hanging gateway: 16.08 s — the same burn.
  There is no profile-dependent branch in the send path (the only
  with-profile difference is the appended saved-preferences
  context, which retrieval already strips); the tester's "without
  profile instant" was breaker-state luck, not a code path.

Fix (backend/ai/chat.py answer() + backend/app/ai_status_cache.py,
new module):
1. Deterministic routing, decided once per turn from the retrieval
   result, before any gateway contact: a turn whose template reply
   carries candidates in one of two shapes is answered by the
   template, never by the model — exactly one candidate (the
   scope already resolved it and the template states its verified
   fact: the step-7 fee verifications, Round 25 W2), or exactly
   two candidates, one undergraduate and one taught_masters (a
   level answer uniquely resolves the disambiguation: the ETH fee
   flow). The disambiguation is a clarification only the user can
   answer — which of the two levels they mean — not a knowledge
   gap the model can fill. The template list is now the one route
   in every gateway state, with or without a saved profile, in
   every locale — and it is instant, because no model call is ever
   attempted for it. The narrowing is deliberate: for any other
   ambiguity the level question cannot resolve it — one level
   only (three undergraduate Computer Science programmes), or
   several programmes per level ("What are Oxford's tuition
   fees?" matches six across fields and levels) — so those turns
   keep the model-first routing (a Round 6 pin: the model answers
   Oxford's fees from the verified programme evidence). Devil's
   advocate is excluded too: its challenge is the point of the
   turn.
2. Fail-fast parity with /simulate: the probe cache +
   _model_skip_cached moved out of app.main into
   app.ai_status_cache (which imports only ai.provider, so no
   cycle); answer() consults model_skip_cached() before the model
   attempt — breaker open, or a probe said "unavailable" within
   its 60 s TTL, means the template answers at once. A cold cache
   with a closed breaker still attempts as before: the first slow
   failure after the gateway dies is inherent (the /simulate
   residual, DECISIONS #267).
Knock-on: RecChat can also receive a template ambiguous reply, and
a typed level word there dead-ended (bare level word -> unknown).
Its onSend now intercepts a typed level word while the latest ask
turn carries 2+ candidates and re-asks original question + level
word, scoped to the candidates — the same follow-up the pet sends.

AFTER numbers (same repro script): A 0.20 / 0.01 / 0.08 s, B
0.02 s with the identical list (no flip), C 0.08 s, D 0.01 s,
every E/E-zh step <= 0.07 s with the fee line reached, F still
model/available for a single-match question when the gateway is up.

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r25_w1.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ai.provider as provider_mod
import app.ai_status_cache as status_cache
import app.main as app_main
from ai.chat import answer
from ai.provider import (
    ProviderAdapter,
    gateway_breaker_open,
    reset_gateway_breaker,
)
from app import router_chat

ROOT = Path(__file__).resolve().parent.parent
RECCHAT = ROOT / "frontend" / "src" / "components" / "RecChat.tsx"

_test_app = FastAPI()
_test_app.include_router(router_chat.router)
client = TestClient(_test_app)

Q_EN = "What is the tuition fee for ETH Zurich Computer Science?"
Q_ZH = "苏黎世联邦理工计算机科学的学费是多少？"
CTX_EN = ("The user's saved preferences from the eligibility check: "
          "countries: CH; climate: cool.")
UCL_Q = "What is the tuition fee for UCL Computer Science BSc?"
ETH_CANDIDATES = ["eth-cs-msc-2027", "eth-cs-bsc-2027"]

_MOCK_ENV = {
    "AI_PROVIDER": "openai",
    "AI_MODEL": "mock-r25-model",
    "AI_API_KEY": "mock-test-key",
    "AI_BASE_URL": "https://api.example.test/v1",
}

# The audit profile/message from tests/test_devil_advocate.py
# (Switzerland, cool climate, UG, GBP 50,000 / year).
AUDIT_PROFILE = {
    "countries": ["CH"],
    "climate": "cool",
    "level": "undergraduate",
    "budget_amount": 50000,
    "budget_currency": "GBP",
    "budget_period": "per_year",
    "city": "Zurich",
}
AUDIT_MESSAGE = "Is Switzerland right for me? I want a cool climate."


@pytest.fixture(autouse=True)
def _isolate():
    reset_gateway_breaker()
    status_cache.reset_ai_status_cache()
    yield
    reset_gateway_breaker()
    status_cache.reset_ai_status_cache()


def _mock_provider(monkeypatch, handler) -> ProviderAdapter:
    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    return ProviderAdapter(_transport=httpx.MockTransport(handler))


def _openai_reply(payload_text: str) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"content": payload_text}}], "usage": {}})


def _slow_502_handler(calls: dict):
    """A flapping relay: answers HTTP 502 after a real delay. The
    latency gate is lowered to 0.1 s (the production gate is 5 s;
    the real relay measured ~12 s), so one such failure trips the
    breaker exactly as a slow production failure does."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        time.sleep(0.3)
        return httpx.Response(502, json={"error": "bad gateway"})
    return handler


def _seed_unavailable():
    """What the pet's open probe leaves: a fresh "unavailable"
    verdict in the probe cache."""
    status_cache._AI_STATUS_CACHE["payload"] = {
        "ai_status": "unavailable", "probed": True}
    status_cache._AI_STATUS_CACHE["at"] = time.monotonic()


def _eth_fee_handler(calls: dict):
    """A well-behaved mock model: answers from the evidence
    catalogue, citing the fee sentence itself when the catalogue
    carries one (the ETH fee line, "4,380"), else the first
    entry's first sentence — the proven grounded shape from
    tests/test_ai_chat.py, so every number in its text is in the
    cited evidence."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = json.loads(request.content)
        envelope = json.loads(body["messages"][-1]["content"])
        catalog = envelope.get("evidence_catalog", [])
        fee = next((c for c in catalog
                    if "4,380" in c.get("excerpt", "")), None)
        if fee is not None:
            text = next(s.strip() for s in fee["excerpt"].split(".")
                        if "4,380" in s) + "."
            eid = fee["id"]
        else:
            first = catalog[0]
            text = first["excerpt"].split(".")[0].strip() + "."
            eid = first["id"]
        payload = {
            "summary": text,
            "claims": [{"text": text, "kind": "fact", "rule_ids": [],
                        "evidence_ids": [eid]}],
            "unknowns": [], "actions": [], "limitations": []}
        return _openai_reply(json.dumps(payload, ensure_ascii=False))
    return handler


def _devil_handler(calls: dict):
    """A well-behaved mock devil: challenges the first
    engine-computed conflict, citing that conflict's own evidence
    ids — copied from tests/test_devil_advocate.py."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = json.loads(request.content)
        envelope = json.loads(body["messages"][-1]["content"])
        assert envelope.get("task") == "devil-chat"
        catalog = {c["id"]: c
                   for c in envelope.get("evidence_catalog", [])}
        conflicts = envelope.get("devil_conflicts") or []
        assert conflicts, "devil envelope must list conflicts"
        first = conflicts[0]
        eid = first["evidence_ids"][0]
        text = catalog[eid]["excerpt"].split(".")[0].strip() + "."
        payload = {
            "summary": "In my opinion, this suggests a second thought: " + text,
            "claims": [{"text": text, "kind": "fact", "rule_ids": [],
                        "evidence_ids": [eid]}],
            "unknowns": [], "actions": [], "limitations": []}
        return _openai_reply(json.dumps(payload, ensure_ascii=False))
    return handler


def _followup(question: str, level_word: str) -> str:
    return f"{question} {level_word}"


# ---------------------------------------------------------------------------
# The cache move: app.main re-exports the same cache object
# ---------------------------------------------------------------------------

def test_probe_cache_is_shared_between_main_and_new_module():
    """The /ai/status endpoint in app.main writes the same dict
    object ai.chat now reads: seeding it through app.main must
    make model_skip_cached() True, and main's reset must clear it
    — otherwise the move silently split the verdict in two."""
    assert app_main._AI_STATUS_CACHE is status_cache._AI_STATUS_CACHE
    assert app_main.reset_ai_status_cache is status_cache.reset_ai_status_cache
    assert app_main._model_skip_cached is status_cache.model_skip_cached
    assert status_cache.model_skip_cached() is False
    _seed_unavailable()
    assert status_cache.model_skip_cached() is True
    assert app_main._model_skip_cached() is True
    app_main.reset_ai_status_cache()
    assert status_cache.model_skip_cached() is False


def test_model_skip_cached_true_on_open_breaker(monkeypatch):
    """Breaker-open alone (cold probe cache) is a known-down verdict:
    after one slow 502 the skip fires with no probe ever run."""
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _slow_502_handler(calls))
    assert status_cache.model_skip_cached() is False
    with pytest.raises(Exception):
        provider.chat([{"role": "user", "content": "hi"}], timeout_s=5.0)
    assert gateway_breaker_open()
    assert status_cache.model_skip_cached() is True


# ---------------------------------------------------------------------------
# (i) Fail fast when the gateway is known down
# ---------------------------------------------------------------------------

def test_known_down_skips_model_attempt(monkeypatch):
    """Seeded "unavailable" verdict + hanging gateway: the
    single-match question answers from the template at once, with
    ZERO transport calls — the parity gap (before: 16.07 s, one
    full model budget, for this exact call)."""
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _slow_502_handler(calls))
    _seed_unavailable()
    t0 = time.monotonic()
    r = answer(UCL_Q, "en", provider=provider)
    assert time.monotonic() - t0 < 1
    assert calls["n"] == 0, "known-down turn must not touch the network"
    assert r["ai_status"] == "unavailable"
    assert "48,600" in r["lines"][0]


def test_cold_cache_attempts_as_before(monkeypatch):
    """Cold cache + closed breaker still attempts (the first slow
    failure after the gateway dies is inherent): exactly one
    transport call, the template fee line, and the breaker open
    afterwards so the NEXT turn is fast."""
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _slow_502_handler(calls))
    r = answer(UCL_Q, "en", provider=provider)
    assert calls["n"] == 1
    assert r["ai_status"] == "unavailable"
    assert "48,600" in r["lines"][0]
    assert gateway_breaker_open()


def test_stale_cache_attempts_as_before(monkeypatch):
    """A probe verdict past its 60 s TTL is not a known-down
    verdict: the turn attempts the model (one call) instead of
    trusting the stale "unavailable"."""
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _slow_502_handler(calls))
    _seed_unavailable()
    status_cache._AI_STATUS_CACHE["at"] = time.monotonic() - 61
    assert status_cache.model_skip_cached() is False
    r = answer(UCL_Q, "en", provider=provider)
    assert calls["n"] == 1
    assert "48,600" in r["lines"][0]


def test_breaker_open_second_turn_is_instant(monkeypatch):
    """After one slow failure trips the breaker, the next turn of
    the same question is instant with no further transport call —
    the Round 24 W4 behaviour, now also reachable through the
    shared skip verdict."""
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _slow_502_handler(calls))
    first = answer(UCL_Q, "en", provider=provider)
    assert calls["n"] == 1
    t0 = time.monotonic()
    second = answer(UCL_Q, "en", provider=provider)
    assert time.monotonic() - t0 < 1
    assert calls["n"] == 1, "breaker-open turn must not touch the network"
    assert second["lines"] == first["lines"]


def test_endpoint_known_down_skips_model_attempt(monkeypatch):
    """Endpoint level: POST /assistant/chat with a seeded
    "unavailable" verdict never reaches the gateway — the
    /simulate parity, at the endpoint the pet actually calls."""
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    calls = {"n": 0}
    monkeypatch.setattr(router_chat, "get_provider",
                        lambda: _mock_provider(monkeypatch,
                                               _slow_502_handler(calls)))
    _seed_unavailable()
    t0 = time.monotonic()
    r = client.post("/api/v1/assistant/chat",
                    json={"message": UCL_Q, "locale": "en"})
    assert time.monotonic() - t0 < 2
    assert r.status_code == 200
    assert calls["n"] == 0
    assert "48,600" in "\n".join(r.json()["lines"])


# ---------------------------------------------------------------------------
# (ii) Deterministic routing: a level-resolvable disambiguation is
# always the template; other ambiguities keep model-first routing
# ---------------------------------------------------------------------------

def test_ambiguous_turn_never_attempts_model_when_up(monkeypatch):
    """The core determinism pin: with a HEALTHY mock model that
    would answer, the ambiguous fee question still returns the
    template disambiguation — zero model calls. Before this fix
    the same call returned ai_status=available with no candidates
    (the B run of the repro: 0.10 s, model answered directly)."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _eth_fee_handler(calls))
    r = answer(Q_EN + "\n" + CTX_EN, "en", provider=provider)
    assert calls["n"] == 0, "a disambiguation turn must never call the model"
    assert r["ai_status"] == "unavailable"
    assert "2 matching programmes" in r["lines"][0]
    assert sorted(r.get("candidates") or []) == sorted(ETH_CANDIDATES)


def test_ambiguous_turn_identical_across_gateway_states(monkeypatch):
    """The same question, with and without a profile, against a
    healthy gateway and against a flapping one: byte-identical
    lines and candidates. No run may flip to a direct model
    answer, and no run may pay a model budget."""
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    healthy_calls = {"n": 0}
    healthy = _mock_provider(monkeypatch, _eth_fee_handler(healthy_calls))
    flap_calls = {"n": 0}
    flap = _mock_provider(monkeypatch, _slow_502_handler(flap_calls))
    results = []
    for message in (Q_EN, Q_EN + "\n" + CTX_EN):
        for provider in (healthy, flap):
            r = answer(message, "en", provider=provider)
            results.append(r)
    first = results[0]
    for r in results[1:]:
        assert r["lines"] == first["lines"]
        assert sorted(r.get("candidates") or []) == sorted(ETH_CANDIDATES)
        assert r["ai_status"] == "unavailable"
    assert healthy_calls["n"] == 0
    # The flapping gateway is never even attempted for this turn.
    assert flap_calls["n"] == 0


def test_single_candidate_scope_question_never_attempts_model(monkeypatch):
    """The other half of rule 1: a scoped fee question resolved to
    exactly one programme ("这个专业" with one programme in view)
    is answered by the template at once — the template already
    states the verified fee line, so the model could only restate
    it. Zero transport calls. (Round 25 W2 pins the same shape at
    the step-7 endpoint; this pins the rule's branch here.)"""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _eth_fee_handler(calls))
    t0 = time.monotonic()
    r = answer("这个专业的学费是多少？", "zh-CN", provider=provider,
               program_ids=["ucl-cs-bsc-2026"], track="undergraduate")
    assert time.monotonic() - t0 < 1
    assert calls["n"] == 0, "a scope-resolved turn must not call the model"
    assert r["ai_status"] == "unavailable"
    assert "48,600" in r["lines"][0]
    assert r.get("candidates") == ["ucl-cs-bsc-2026"]


def test_non_level_resolvable_ambiguity_keeps_model_first(monkeypatch):
    """The narrowing, pinned both ways: "What are Oxford's tuition
    fees?" matches six programmes across fields and levels, so a
    level answer cannot resolve it — the turn keeps the model-first
    routing (Round 6 pin: the model answers from the verified
    programme evidence, never "don't know", never another
    programme's fee). The broad rule (any candidates -> template)
    broke this test; the level-resolvable rule preserves it."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _eth_fee_handler(calls))
    r = answer("What are Oxford's tuition fees?", "en", provider=provider)
    assert calls["n"] == 1, "a non-resolvable ambiguity still attempts the model"
    assert r["ai_status"] == "available"
    assert r["evidence_url"] is not None
    assert r["evidence_url"].startswith("https://www.ox.ac.uk")
    joined = "\n".join(r["lines"])
    assert "don't know" not in joined.lower()
    assert "48,600" not in joined and "48,300" not in joined


def test_single_level_ambiguity_keeps_model_first(monkeypatch):
    """Same boundary, the other side: three matching programmes,
    all undergraduate — "undergraduate or masters" cannot pick one
    — so the model is still attempted when the gateway is up."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _eth_fee_handler(calls))
    r = answer("What is the fee for Computer Science?", "en",
               provider=provider)
    # The routing pin is the call count: the model is attempted.
    # (Whether its output validates is the mock's business, not
    # the router's — the template fallback answers otherwise.)
    assert calls["n"] == 1, "a single-level ambiguity still attempts the model"
    assert r["lines"]


def test_followup_still_uses_model_when_up(monkeypatch):
    """The rule stops at the disambiguation: the follow-up (one
    programme, no candidates) still goes to the model when the
    gateway is up, and the model answers the fee line from the
    verified catalogue."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _eth_fee_handler(calls))
    r = answer(_followup(Q_EN, "undergraduate"), "en", provider=provider,
               program_ids=ETH_CANDIDATES)
    assert calls["n"] == 1
    assert r["ai_status"] == "available"
    assert "CHF 4,380" in "\n".join(r["lines"])


def test_devil_excluded_from_disambiguation_rule(monkeypatch):
    """Devil's advocate is not a disambiguation turn: with a
    healthy gateway its challenge still goes to the model (the
    rule (1) carve-out), citing the engine-computed conflict."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _devil_handler(calls))
    r = answer(AUDIT_MESSAGE, "en", provider=provider,
               mode="devil", profile=AUDIT_PROFILE)
    assert calls["n"] == 1
    assert r["ai_status"] == "available"
    assert r["mode"] == "devil"
    assert r["conflicts"] == ["climate"]


def test_devil_known_down_still_skips(monkeypatch):
    """...but the fail-fast (rule 2) DOES apply to devil: a seeded
    "unavailable" verdict means the template challenges at once,
    with zero transport calls."""
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _slow_502_handler(calls))
    _seed_unavailable()
    t0 = time.monotonic()
    r = answer(AUDIT_MESSAGE, "en", provider=provider,
               mode="devil", profile=AUDIT_PROFILE)
    assert time.monotonic() - t0 < 1
    assert calls["n"] == 0
    assert r["ai_status"] == "unavailable"
    assert r["mode"] == "devil"
    assert r["conflicts"] == ["climate"]


# ---------------------------------------------------------------------------
# The exact tester sequence, 3x: en + zh, with/without profile,
# button + typed level answers — every run gives the fee line, and
# every with-profile offline run is fast
# ---------------------------------------------------------------------------

def test_endpoint_full_sequence_3x(monkeypatch):
    """The task-19 sequence, repeated 3x per combination, against
    a flapping gateway with the probe verdict seeded "unavailable"
    and the breaker reset before every POST (simulating cooldown
    expiry): each POST must be fast and the fee line must be
    reached — no ~15 s burn, no flip. The transport-call count
    pins WHY it is fast: step 1 never attempts the model (rule 1),
    the follow-ups skip it on the known-down verdict (rule 2)."""
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    calls = {"n": 0}
    monkeypatch.setattr(router_chat, "get_provider",
                        lambda: _mock_provider(monkeypatch,
                                               _slow_502_handler(calls)))
    cases = [
        ("en", Q_EN, "undergraduate", "masters",
         "Bachelor of Science in Computer Science",
         "MSc in Computer Science"),
        ("zh-CN", Q_ZH, "本科", "硕士",
         "Bachelor of Science in Computer Science",
         "MSc in Computer Science"),
    ]
    for rep in range(3):
        for locale, question, ug_word, tm_word, ug_name, tm_name in cases:
            for with_profile in (False, True):
                message = question + ("\n" + CTX_EN if with_profile else "")
                reset_gateway_breaker()
                _seed_unavailable()
                t0 = time.monotonic()
                r = client.post("/api/v1/assistant/chat", json={
                    "message": message, "locale": locale})
                assert time.monotonic() - t0 < 2, (rep, locale, with_profile)
                assert r.status_code == 200
                body = r.json()
                assert "candidates" in body, (rep, locale, with_profile)
                assert sorted(body["candidates"]) == sorted(ETH_CANDIDATES)
                # Button tap: the level word.
                reset_gateway_breaker()
                _seed_unavailable()
                t0 = time.monotonic()
                r = client.post("/api/v1/assistant/chat", json={
                    "message": _followup(question, ug_word),
                    "locale": locale, "program_ids": body["candidates"]})
                assert time.monotonic() - t0 < 2, (rep, locale, with_profile)
                joined = "\n".join(r.json()["lines"])
                assert "4,380" in joined, (rep, locale, with_profile)
                assert ug_name in joined
                # Typed: the other level.
                reset_gateway_breaker()
                _seed_unavailable()
                t0 = time.monotonic()
                r = client.post("/api/v1/assistant/chat", json={
                    "message": _followup(question, tm_word),
                    "locale": locale, "program_ids": body["candidates"]})
                assert time.monotonic() - t0 < 2, (rep, locale, with_profile)
                joined = "\n".join(r.json()["lines"])
                assert "4,380" in joined, (rep, locale, with_profile)
                assert tm_name in joined
    assert calls["n"] == 0, "no offline run in this sequence may call the model"


# ---------------------------------------------------------------------------
# RecChat knock-on: a typed level word answers the pending
# disambiguation instead of dead-ending on the bare word
# ---------------------------------------------------------------------------

def test_recchat_level_interception_pins():
    """RecChat can now receive a template ambiguous reply while
    the model is up too (rule 1), so its onSend must intercept a
    typed level word while the latest ask turn carries 2+
    candidates — original question + level word, scoped to the
    candidates — instead of sending the bare word the backend
    honestly answers unknown with. Only the LATEST ask turn
    counts, and only a bare level word qualifies (a new question
    that merely mentions a level is not intercepted)."""
    rec = RECCHAT.read_text(encoding="utf-8")
    for name in ("detectLevelWord", "disambiguationFollowupMessage",
                 "looksLikeQuestion"):
        assert name in rec, name

    # The pending branch runs before the country/city fast paths.
    pending_at = rec.index("const lastAsk = [...aiTurns].reverse().find((x) => x.reply);")
    country_at = rec.index("for (const code of countries)")
    assert pending_at < country_at
    branch = rec[pending_at:country_at]
    assert "const lastAsk = [...aiTurns].reverse().find((x) => x.reply);" in branch
    assert "(lastAsk.reply?.candidates?.length ?? 0) >= 2" in branch
    assert "const levelWord = pendingAsk ? detectLevelWord(text) : null;" in branch
    assert "if (pendingAsk && levelWord && !looksLikeQuestion(text)) {" in branch
    assert "disambiguationFollowupMessage(pendingAsk.sent ?? pendingAsk.question, levelWord, locale)" in branch
    assert "pendingAsk.reply?.candidates ?? []" in branch

    # askModel carries the override through to the POST body.
    assert "programIdsOverride?: string[]" in rec
    assert "program_ids: programIdsOverride ?? shown.map((r) => r.programId)" in rec
