"""Round 26 W2 — masters fee after the level choice must be as fast
and deterministic as undergraduate (re-test task 20).

Tester finding (live browser, 2026-11-27 19:58-20:12 CST, gateway
flapping): after the 2-candidate list ("I found 2 matching
programmes: ETH Zurich — MSc in Computer Science, ETH Zurich —
Bachelor of Science in Computer Science. Tell me undergraduate or
masters."), tapping Undergraduate gave the fee line instantly, but
typed "masters" and tapping "Taught masters" went down a SLOW AI
path (~30 s, "Checking verified sources… 0s" counting) and the
wording varied between runs (fee number stable at CHF 4,380).

Root cause (reproduced first, /tmp/r26w2-repro2.py — BEFORE numbers,
healthy mock model): the follow-up ("…Computer Science? masters",
scoped to the two candidates) resolves in the template's own
``ask()`` to exactly ONE programme, so ``_template_result`` carries
NO ``candidates`` — candidates are only set on the ambiguous branch
itself, or on the scope's own which-one line, and ``_scope_line``
returns early once the template has a ``program_id``. Round 25 W1's
``_candidates_route_to_template`` therefore saw ``None`` and the
turn went to the model whenever the gateway was not already known
down: calls=1, ai_status=available, model wording ("Tuition fee:
CHF 4,380 per year." — no programme name) for BOTH levels, with or
without history, in en and zh. The live undergrad/masters asymmetry
was breaker/probe-state luck, not a code-path difference — and
Round 25's ``test_followup_still_uses_model_when_up`` had pinned
that model attempt as intended behaviour. The task's other
hypothesis was checked and is NOT the cause: both frontends already
send the follow-up scoped to the candidates — CompassPet
``onChip``/``onSend`` send ``programIds: pendingNow.candidates``
with ``disambiguationFollowupMessage`` (original question + level
word), and RecChat ``onSend`` sends
``disambiguationFollowupMessage(...)`` with
``pendingAsk.reply?.candidates`` (see the source pins below) — so
no frontend change was needed, and history does not affect the
template path either (it only feeds the model envelope).

Fix (backend/ai/chat.py only): ``_level_followup_template_route``
— a level answer to a two-candidate, one-per-level disambiguation
that the template already resolved to one programme is answered by
the template, never by the model. The shape is narrow on purpose:
the template resolved to one programme, the message names that
programme's level, the resolved programme is in the caller scope,
and the scope holds programmes of BOTH levels. A fresh single-match
question (no scope, or a single-level scope) and every other
ambiguity keep the model-first routing.

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r26_w2.py
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
from ai.chat import answer
from ai.provider import ProviderAdapter, reset_gateway_breaker
from app import router_chat

ROOT = Path(__file__).resolve().parent.parent
RECCHAT = ROOT / "frontend" / "src" / "components" / "RecChat.tsx"
PET = ROOT / "frontend" / "src" / "components" / "CompassPet.tsx"

_test_app = FastAPI()
_test_app.include_router(router_chat.router)
client = TestClient(_test_app)

Q_EN = "What is the tuition fee for ETH Zurich Computer Science?"
Q_ZH = "苏黎世联邦理工计算机科学的学费是多少？"
ETH_CANDIDATES = ["eth-cs-msc-2027", "eth-cs-bsc-2027"]
UCL_BSC = "ucl-cs-bsc-2026"
UCL_MSC = "ucl-cs-msc-2027"

HIST_EN = [
    {"role": "user", "content": Q_EN},
    {"role": "assistant", "content": (
        "I found 2 matching programmes: ETH Zurich — MSc in Computer "
        "Science, ETH Zurich — Bachelor of Science in Computer "
        "Science. Tell me undergraduate or masters.")},
]
HIST_ZH = [
    {"role": "user", "content": Q_ZH},
    {"role": "assistant", "content": (
        "我找到 2 个相关专业：ETH Zurich — MSc in Computer Science、"
        "ETH Zurich — Bachelor of Science in Computer Science。"
        "请告诉我是本科还是硕士。")},
]

_MOCK_ENV = {
    "AI_PROVIDER": "openai",
    "AI_MODEL": "mock-r26-model",
    "AI_API_KEY": "mock-test-key",
    "AI_BASE_URL": "https://api.example.test/v1",
}


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


def _eth_fee_handler(calls: dict):
    """A well-behaved mock model (copied from tests/test_r25_w1.py):
    answers from the evidence catalogue, citing the fee sentence
    itself when the catalogue carries one — so a model attempt is
    observable as a model-worded line, never as a failure."""
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


def _slow_502_handler(calls: dict):
    """A flapping relay: HTTP 502 after a real delay (copied from
    tests/test_r25_w1.py; the latency gate is lowered to 0.1 s so
    one such failure trips the breaker exactly as a slow production
    failure does)."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        time.sleep(0.3)
        return httpx.Response(502, json={"error": "bad gateway"})
    return handler


def _followup(question: str, level_word: str) -> str:
    """What both frontends send for a level answer: the ORIGINAL
    question + the level word (frontend/src/lib/chat.ts
    disambiguationFollowupMessage)."""
    return f"{question} {level_word}"


# ---------------------------------------------------------------------------
# The fix: a masters level answer is the instant template line
# ---------------------------------------------------------------------------

def test_masters_followup_never_attempts_model_when_up(monkeypatch):
    """The live bug, typed: "masters" after the 2-candidate list,
    with a HEALTHY mock model that would answer — zero model calls,
    the exact template MSc fee line, instantly. Before the fix this
    was calls=1, ai_status=available, model wording ("Tuition fee:
    CHF 4,380 per year."). History is the browser turn's history
    (the ambiguous reply is the previous assistant turn)."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _eth_fee_handler(calls))
    t0 = time.monotonic()
    r = answer(_followup(Q_EN, "masters"), "en", provider=provider,
               program_ids=ETH_CANDIDATES, history=HIST_EN)
    assert time.monotonic() - t0 < 1
    assert calls["n"] == 0, "a masters follow-up must not call the model"
    assert r["ai_status"] == "unavailable"
    assert r["lines"][0] == (
        "ETH Zurich — MSc in Computer Science "
        "tuition: CHF 4,380 per year.")
    assert "Bachelor" not in r["lines"][0]


def test_undergraduate_followup_identical_parity(monkeypatch):
    """The parity pin: the undergraduate follow-up is the same
    instant template line (BSc, not MSc), also with zero model
    calls — the two levels now behave identically in every gateway
    state, not just when the breaker happens to be open."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _eth_fee_handler(calls))
    t0 = time.monotonic()
    r = answer(_followup(Q_EN, "undergraduate"), "en", provider=provider,
               program_ids=ETH_CANDIDATES, history=HIST_EN)
    assert time.monotonic() - t0 < 1
    assert calls["n"] == 0
    assert r["ai_status"] == "unavailable"
    assert r["lines"][0] == (
        "ETH Zurich — Bachelor of Science in Computer Science "
        "tuition: CHF 4,380 per year.")
    assert "MSc" not in r["lines"][0]


def test_zh_followups_masters_and_undergraduate(monkeypatch):
    """Both levels in zh-CN, typed words 硕士 / 研究生 / 本科:
    zero model calls, the exact template line in Chinese wording,
    naming the right programme each time."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _eth_fee_handler(calls))
    cases = [
        ("硕士", "MSc in Computer Science", "Bachelor"),
        ("研究生", "MSc in Computer Science", "Bachelor"),
        ("本科", "Bachelor of Science in Computer Science", "MSc"),
    ]
    for word, named, absent in cases:
        t0 = time.monotonic()
        r = answer(_followup(Q_ZH, word), "zh-CN", provider=provider,
                   program_ids=ETH_CANDIDATES, history=HIST_ZH)
        assert time.monotonic() - t0 < 1, word
        assert calls["n"] == 0, word
        assert r["ai_status"] == "unavailable", word
        assert "4,380" in r["lines"][0], word
        assert named in r["lines"][0], word
        assert absent not in r["lines"][0], word


def test_masters_followup_with_flapping_gateway_is_instant(monkeypatch):
    """The live scenario verbatim: a flapping gateway that would
    burn the full model budget on this turn. The follow-up never
    touches it — zero transport calls, instant, the template MSc
    line — instead of ~15 s (plus the frontend retry, ~30 s in
    the browser) ending in a model-worded line."""
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _slow_502_handler(calls))
    t0 = time.monotonic()
    r = answer(_followup(Q_EN, "masters"), "en", provider=provider,
               program_ids=ETH_CANDIDATES, history=HIST_EN)
    assert time.monotonic() - t0 < 1
    assert calls["n"] == 0, "a flapping gateway must never be attempted here"
    assert r["ai_status"] == "unavailable"
    assert r["lines"][0] == (
        "ETH Zurich — MSc in Computer Science "
        "tuition: CHF 4,380 per year.")


def test_history_does_not_change_routing(monkeypatch):
    """History is not the cause and not the fix: the follow-up
    returns byte-identical lines with and without the ambiguous
    turn in history, with zero model calls either way (the
    history only feeds the model envelope, never the template)."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _eth_fee_handler(calls))
    with_hist = answer(_followup(Q_EN, "masters"), "en",
                       provider=provider, program_ids=ETH_CANDIDATES,
                       history=HIST_EN)
    without_hist = answer(_followup(Q_EN, "masters"), "en",
                          provider=provider, program_ids=ETH_CANDIDATES)
    assert calls["n"] == 0
    assert with_hist["lines"] == without_hist["lines"]
    assert with_hist["lines"][0].startswith(
        "ETH Zurich — MSc in Computer Science tuition: CHF 4,380")


def test_endpoint_masters_followup(monkeypatch):
    """Endpoint level, the exact browser turn: POST
    /assistant/chat with message, locale, history and program_ids
    against a HEALTHY mock model — 200, fast, zero transport
    calls, the template MSc line (and the same for undergraduate)."""
    calls = {"n": 0}
    monkeypatch.setattr(router_chat, "get_provider",
                        lambda: _mock_provider(monkeypatch,
                                               _eth_fee_handler(calls)))
    for word, named, absent in (
            ("masters", "MSc in Computer Science", "Bachelor"),
            ("undergraduate", "Bachelor of Science in Computer Science",
             "MSc")):
        t0 = time.monotonic()
        r = client.post("/api/v1/assistant/chat", json={
            "message": _followup(Q_EN, word), "locale": "en",
            "history": HIST_EN, "program_ids": ETH_CANDIDATES})
        assert time.monotonic() - t0 < 2, word
        assert r.status_code == 200
        assert calls["n"] == 0, word
        body = r.json()
        assert body["ai_status"] == "unavailable", word
        assert body["lines"][0] == (
            f"ETH Zurich — {named} tuition: CHF 4,380 per year."), word
        assert absent not in body["lines"][0], word


def test_endpoint_zh_masters_followup(monkeypatch):
    """Endpoint level, zh-CN: typed 硕士 after the list — the
    template MSc line, no model call."""
    calls = {"n": 0}
    monkeypatch.setattr(router_chat, "get_provider",
                        lambda: _mock_provider(monkeypatch,
                                               _eth_fee_handler(calls)))
    r = client.post("/api/v1/assistant/chat", json={
        "message": _followup(Q_ZH, "硕士"), "locale": "zh-CN",
        "history": HIST_ZH, "program_ids": ETH_CANDIDATES})
    assert r.status_code == 200
    assert calls["n"] == 0
    assert "4,380" in r.json()["lines"][0]
    assert "MSc in Computer Science" in r.json()["lines"][0]
    assert "Bachelor" not in r.json()["lines"][0]


# ---------------------------------------------------------------------------
# The narrowing, pinned both ways: only a level answer to a
# both-levels scope routes to the template
# ---------------------------------------------------------------------------

def test_fresh_single_match_without_scope_still_attempts_model(monkeypatch):
    """A fresh single-match question with NO caller scope keeps the
    model-first routing (Round 25 pin): the fix must not turn every
    single-programme answer into a template answer."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _eth_fee_handler(calls))
    r = answer("What is the tuition fee for UCL Computer Science BSc?",
               "en", provider=provider)
    assert calls["n"] == 1, "a scopeless single match still attempts the model"
    assert r["lines"]


def test_single_level_scope_still_attempts_model(monkeypatch):
    """Same boundary, scoped: the scope holds only the undergraduate
    programme, so there is no both-levels disambiguation for the
    level word to resolve — the model is still attempted when the
    gateway is up."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _eth_fee_handler(calls))
    r = answer("What is the tuition fee for UCL Computer Science BSc?",
               "en", provider=provider, program_ids=[UCL_BSC])
    assert calls["n"] == 1, "a single-level scope still attempts the model"
    assert r["lines"]


def test_scope_without_resolved_programme_still_attempts_model(monkeypatch):
    """The resolved programme must be IN the scope: a masters
    follow-up scoped to a different institution's pair does not
    route to the template."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _eth_fee_handler(calls))
    r = answer(_followup(Q_EN, "masters"), "en", provider=provider,
               program_ids=[UCL_BSC, UCL_MSC], history=HIST_EN)
    assert calls["n"] == 1, "an out-of-scope resolution still attempts the model"
    assert r["lines"]


def test_unrecognised_level_word_still_reasks(monkeypatch):
    """No regression on the re-ask: "grad" names no level, so the
    turn stays the ambiguous list (template route via the
    candidates, zero model calls) with the candidates intact, so
    the caller's pending disambiguation and level chips stay live."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _eth_fee_handler(calls))
    r = answer(_followup(Q_EN, "grad"), "en", provider=provider,
               program_ids=ETH_CANDIDATES)
    assert calls["n"] == 0
    assert ("2 matching programmes" in r["lines"][0]
            or "Which one do you mean" in r["lines"][0])
    assert sorted(r.get("candidates") or []) == sorted(ETH_CANDIDATES)


# ---------------------------------------------------------------------------
# Frontend: both callers already send the scoped follow-up — pin it,
# so a future frontend change cannot silently re-open this bug
# ---------------------------------------------------------------------------

def test_frontends_send_scoped_level_followup():
    """The task's alternative hypothesis was checked and is false:
    CompassPet (chip tap AND typed send) and RecChat (typed send)
    already scope the level follow-up to the disambiguation's
    candidates with the original question + level word. These pins
    guard that contract — if either caller stops sending the
    scope, the backend route above can no longer fire."""
    pet = PET.read_text(encoding="utf-8")
    rec = RECCHAT.read_text(encoding="utf-8")
    # CompassPet onChip: the pending branch answers with the level
    # chips, scoped to the pending candidates.
    assert "programIds: pendingNow.candidates" in pet
    assert ("disambiguationFollowupMessage(pendingNow.question, level, locale)"
            in pet)
    # CompassPet onSend: a typed level word takes the same path.
    assert "const level = detectLevelWord(text);" in pet
    # RecChat onSend: a typed level word re-asks the original
    # question + level word, scoped to the pending candidates.
    assert ("disambiguationFollowupMessage(pendingAsk.sent ?? pendingAsk.question, levelWord, locale)"
            in rec)
    assert "pendingAsk.reply?.candidates ?? []" in rec
    assert "programIdsOverride ?? shown.map((r) => r.programId)" in rec
