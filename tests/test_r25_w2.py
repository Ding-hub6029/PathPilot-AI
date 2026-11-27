"""Round 25 W2 — wizard step-7 verification latency (P1).

Finding (browser re-test task 19, 2026-11-27 17:36-17:45 CST): every
step-7 verification showed "正在查已核实资料… 0 秒" and counted up
to ~12-14 s before the reply appeared.

Diagnosis — the wait is a LIVE MODEL CALL that succeeds, not a
burned timeout, a retry multiplier, or a cold start. No behaviour
change in this round: the remaining slow case is inherent (see
DECISIONS.md #280).

Trace (step 7 = the RecChat recommend step): each verification is
one RecChat free-text / chip-scoped turn -> exactly one
POST /api/v1/assistant/chat (RecChat askModel, one fetchJsonChat
call; the frontend caps one attempt at 18 s with retryOnTimeout
false, so there is no second attempt) -> ai.chat.answer() -> at
most one provider.chat() call with timeout_s=15.0 and NO repair
retry -> the model reply, or the verified template on failure.
Retrieval is ~0.06 s and the template ~0.01 s (Round 24 W4,
measured), so the whole turn time is the model call's time.

Measured against the LIVE deployed backend (Render, HEAD 263ec20d,
the code the re-test ran against) on 2026-11-27, minutes after the
re-test window, with the exact step-7 payload (zh-CN fee question,
program_ids ["ucl-cs-bsc-2026"], track "undergraduate"):

- 17:49-17:50 CST, gateway down, breaker open: 0.81 s / 0.80 s /
  0.59 s, ai_status unavailable (template) — the Round 24 W4
  breaker already makes the down-path fast.
- 17:54 CST, cold breaker: call 1 took 15.60 s with ai_status
  AVAILABLE, model deepseek/deepseek-v4.1-flash — a genuine live
  model answer. Call 2 took 16.18 s, ai_status unavailable (one
  slow failure, which tripped the breaker). Call 3 took 0.96 s,
  unavailable — breaker open, fail fast.
- 17:58-17:59 CST, cold breaker again: call 1 took 15.98 s,
  unavailable (slow failure, breaker tripped); calls 2-5 took
  0.57-0.79 s, unavailable.

The re-test's 12-14 s sits inside the live-model range (9-12 s
measured 2026-11-26; 15.6 s measured here) and matches a
successful model turn, not a failure: a down gateway cannot
produce "every check 12-14 s" while the breaker works, because
every check after the first slow failure lands in ~1 s. The
12-14 s is the price of the conversational model answer itself —
the gateway relay (Shenjyai DeepSeek) answers a full turn in
roughly 12-16 s — and shortening the 15 s budget would clip real
replies (Round 10), while answering from the template first would
throw away the working model answer (its conversational reply,
grounded in the same verified facts) the user asked for.

What Round 25 W1 (same round, other worker — uncommitted in this
working copy at the time of writing, no DECISIONS entry yet)
already cut for this path, measured locally here:
- a scoped fee question (one programme in scope) is answered by
  the template at once — the template carries candidates, so
  answer() returns it without ever attempting the model
  (0 transport calls, ~0.01 s, verified fee line). The re-test's
  fee verifications are exactly this shape.
- a turn attempted while the gateway is already known down
  (breaker open, or a probe said "unavailable" within its 60 s
  TTL — model_skip_cached, the /simulate fail-fast moved into
  app.ai_status_cache so /assistant/chat can consult it) skips
  the model attempt entirely.
The slow case that remains after W1 is a non-candidate question
with a cold cache and a closed breaker while the gateway is UP:
one live model call, 12-16 s, inherent — and the first slow
failure after the gateway dies is inherent too (the /simulate
residual, DECISIONS #267); the breaker bounds every call after it.

What is pinned here, so a future round does not re-litigate it:
1. A slow-but-valid model reply makes a non-candidate step-7
   turn take the gateway's time (one transport call, ai_status
   available).
2. When the gateway is up, EVERY such turn pays the gateway's
   time again — model answers are not cached, so repeated
   12-14 s checks are the expected steady state, not a
   regression.
3. A scoped fee question never attempts the model (W1
   candidates route): 0 transport calls, instant verified fee
   line.
4. A turn while the gateway is known down skips the model
   (W1 model_skip_cached parity): 0 transport calls.
5. When the gateway is down and NOT yet known down, the step-7
   endpoint fails fast after the first slow failure (Round 24 W4
   breaker, endpoint level, RecChat-shaped body): one slow turn,
   then engine-time turns.
6. The single-attempt shape on both sides: at most one
   provider.chat() per turn (timeout_s=15.0, no repair) and
   exactly one fetchJsonChat per RecChat turn inside an 18 s /
   20 s / retryOnTimeout=false budget — no retry or cold-start
   multiplier anywhere on the path.

Open (documented, NOT fixed): a slow failure mode that never
trips the breaker would still repeat per check — a slow HTTP 200
with an unreadable body (kind "bad_reply"), a slow empty reply
(kind "empty_reply", raised after the trip block), or a slow 200
whose text fails model-JSON parsing / validation in ai.chat
(answer() falls back to the template and chat() already cleared
the breaker on HTTP success). No live evidence of that mode: both
slow failures measured above DID trip the breaker (the next calls
were 0.57-0.96 s). See DECISIONS.md #280 for the exact sites.

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r25_w2.py
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
from ai.chat import answer as chat_answer
from ai.provider import (
    ProviderAdapter,
    gateway_breaker_open,
    reset_gateway_breaker,
)
from app import router_chat
from app.ai_status_cache import (
    _AI_STATUS_CACHE,
    reset_ai_status_cache,
)

ROOT = Path(__file__).resolve().parent.parent
CHAT_PY = ROOT / "backend" / "ai" / "chat.py"
API_TS = ROOT / "frontend" / "src" / "lib" / "api.ts"
REC_CHAT = ROOT / "frontend" / "src" / "components" / "RecChat.tsx"

_test_app = FastAPI()
_test_app.include_router(router_chat.router)
client = TestClient(_test_app)

_MOCK_ENV = {
    "AI_PROVIDER": "openai",
    "AI_MODEL": "mock-r25-model",
    "AI_API_KEY": "mock-test-key",
    "AI_BASE_URL": "https://api.example.test/v1",
}

# A step-7 free-text turn that reaches the model: a Switzerland
# reason, sent the way RecChat sends it (visible-batch program_ids
# + wizard track). No fee / IELTS / deadline word, so the scope
# line does not answer it and the template carries no candidates.
STEP7_MODEL_BODY = {
    "message": "我想去瑞士，因为那边环境优美",
    "locale": "zh-CN",
    "history": [],
    "program_ids": ["ucl-cs-bsc-2026", "eth-cs-bsc-2027"],
    "track": "undergraduate",
}

# The re-test's fee verification shape: a fee question scoped to
# exactly one programme in view.
STEP7_FEE_BODY = {
    "message": "这个专业的学费是多少？",
    "locale": "zh-CN",
    "history": [],
    "program_ids": ["ucl-cs-bsc-2026"],
    "track": "undergraduate",
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


def _openai_reply(payload_text: str) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"content": payload_text}}], "usage": {}})


def _slow_grounded_handler(calls: dict, delay_s: float = 0.3):
    """A slow-but-healthy gateway: answers after ``delay_s`` with a
    grounded model payload built from the envelope's own evidence
    catalogue (same shape as tests/test_ai_chat.py's grounded
    mock), so the turn is a real model answer, not a fallback."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        time.sleep(delay_s)
        envelope = json.loads(json.loads(request.content)["messages"][-1]["content"])
        catalog = envelope.get("evidence_catalog", [])
        locale = envelope.get("locale", "en")
        if not catalog:
            payload = {
                "summary": "我不知道。" if locale == "zh-CN" else "I do not know.",
                "claims": [{"text": "已核实的数据里没有相关内容。"
                            if locale == "zh-CN" else
                            "No verified data covers this.",
                            "kind": "limitation", "rule_ids": [],
                            "evidence_ids": []}],
                "unknowns": [], "actions": [], "limitations": []}
        else:
            fee = next((c for c in catalog if "48,600" in c.get("excerpt", "")), None)
            if fee:
                text = "UCL 计算机科学本科的海外学费为每年 GBP 48,600。"
                action = "开始资格检查，确认成绩和语言是否达标。"
                payload = {
                    "summary": text,
                    "claims": [{"text": text, "kind": "fact", "rule_ids": [],
                                "evidence_ids": [fee["id"]]}],
                    "unknowns": [],
                    "actions": [{"explanation": action,
                                 "evidence_ids": [fee["id"]]}],
                    "limitations": []}
            else:
                first = catalog[0]
                text = first["excerpt"].split(".")[0].strip() + "."
                payload = {
                    "summary": text,
                    "claims": [{"text": text, "kind": "fact", "rule_ids": [],
                                "evidence_ids": [first["id"]]}],
                    "unknowns": [], "actions": [], "limitations": []}
        return _openai_reply(json.dumps(payload, ensure_ascii=False))
    return handler


def _slow_502_handler(calls: dict, delay_s: float = 0.3):
    """The flapping-relay failure mode (Round 24 W4): HTTP 502
    after real time has passed."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        time.sleep(delay_s)
        return httpx.Response(502, json={"error": "bad gateway"})
    return handler


def _provider(monkeypatch, handler):
    monkeypatch.setattr(router_chat, "get_provider",
                        lambda: _adapter(monkeypatch, handler))


# ---------------------------------------------------------------------------
# 1 + 2 — a live model turn costs the gateway's time, every turn
# ---------------------------------------------------------------------------

def test_step7_live_model_turn_takes_gateway_time(monkeypatch):
    """One non-candidate step-7 turn against a slow-but-valid model
    takes the gateway's time (not a multiple of it): the 12-14 s
    the re-test saw is the model call itself. Live: 15.60 s,
    ai_status available, deepseek/deepseek-v4.1-flash."""
    calls = {"n": 0}
    adapter = _adapter(monkeypatch, _slow_grounded_handler(calls))
    t0 = time.monotonic()
    result = chat_answer("瑞士有哪些好学校？", "zh-CN", provider=adapter)
    elapsed = time.monotonic() - t0
    assert result["ai_status"] == "available"
    assert result["model"] == "openai/mock-r25-model"
    assert elapsed >= 0.3, "turn must take the gateway's time"
    assert elapsed < 5, "one model call, no retry stacking"
    assert calls["n"] == 1


def test_step7_live_model_every_turn_pays_gateway_time(monkeypatch):
    """When the gateway is up, EVERY non-candidate turn pays the
    gateway's time again — model answers are not cached. Two
    identical step-7 turns each take the gateway delay with one
    transport call apiece: repeated ~12-14 s checks are the
    expected steady state, not a regression to chase."""
    calls = {"n": 0}
    adapter = _adapter(monkeypatch, _slow_grounded_handler(calls))
    for _ in range(2):
        t0 = time.monotonic()
        result = chat_answer("瑞士有哪些好学校？", "zh-CN", provider=adapter)
        elapsed = time.monotonic() - t0
        assert result["ai_status"] == "available"
        assert elapsed >= 0.3
    assert calls["n"] == 2
    assert not gateway_breaker_open(), "a successful model call clears the breaker"


# ---------------------------------------------------------------------------
# 3 — the scoped fee question never attempts the model (W1 route)
# ---------------------------------------------------------------------------

def test_step7_scoped_fee_question_skips_model(monkeypatch):
    """The re-test's fee-verification shape — a fee question scoped
    to exactly one programme in view — is answered by the template
    at once: the template carries candidates, so answer() returns
    it without ever attempting the model (Round 25 W1 candidates
    route). 0 transport calls, instant verified fee line."""
    calls = {"n": 0}
    adapter = _adapter(monkeypatch, _slow_grounded_handler(calls))
    t0 = time.monotonic()
    result = chat_answer("这个专业的学费是多少？", "zh-CN",
                         provider=adapter,
                         program_ids=["ucl-cs-bsc-2026"],
                         track="undergraduate")
    assert time.monotonic() - t0 < 1
    assert calls["n"] == 0, "no model attempt for a candidate turn"
    assert result["ai_status"] == "unavailable"
    assert "48,600" in result["lines"][0]
    assert result.get("candidates") == ["ucl-cs-bsc-2026"]


def test_step7_endpoint_scoped_fee_question_skips_model(monkeypatch):
    """Same as above at the endpoint, with the exact RecChat body:
    one POST, instant verified fee line, no gateway contact."""
    calls = {"n": 0}
    _provider(monkeypatch, _slow_grounded_handler(calls))
    t0 = time.monotonic()
    r = client.post("/api/v1/assistant/chat", json=STEP7_FEE_BODY)
    assert time.monotonic() - t0 < 1
    assert r.status_code == 200
    assert r.json()["ai_status"] == "unavailable"
    assert "48,600" in r.json()["lines"][0]
    assert r.json().get("candidates") == ["ucl-cs-bsc-2026"]
    assert calls["n"] == 0


# ---------------------------------------------------------------------------
# 4 — a known-down turn skips the model (W1 model_skip_cached parity)
# ---------------------------------------------------------------------------

def test_step7_endpoint_known_down_skips_model(monkeypatch):
    """With a cached probe verdict of "unavailable" (60 s TTL),
    the step-7 endpoint skips the model attempt entirely — the
    /simulate fail-fast, now consulted by /assistant/chat (Round
    25 W1, app.ai_status_cache). 0 transport calls even against a
    slow-502 gateway that would otherwise burn the delay."""
    calls = {"n": 0}
    _provider(monkeypatch, _slow_502_handler(calls))
    _AI_STATUS_CACHE["at"] = time.monotonic()
    _AI_STATUS_CACHE["payload"] = {"ai_status": "unavailable"}
    t0 = time.monotonic()
    r = client.post("/api/v1/assistant/chat", json=STEP7_MODEL_BODY)
    assert time.monotonic() - t0 < 1
    assert r.status_code == 200
    assert r.json()["ai_status"] == "unavailable"
    assert calls["n"] == 0, "known-down turn must not touch the network"
    assert not gateway_breaker_open(), "skipping must not trip the breaker"


# ---------------------------------------------------------------------------
# 5 — the down-path at the step-7 endpoint fails fast after one burn
# ---------------------------------------------------------------------------

def test_step7_endpoint_slow_failure_then_fast(monkeypatch):
    """POST /api/v1/assistant/chat with the RecChat-shaped body
    against a slow-502 gateway, cold cache and closed breaker: the
    first turn burns the gateway delay once and renders the
    verified template, the second turn is engine time with no
    further transport call (Round 24 W4 breaker). Live: 15.98 s
    then 0.57-0.79 s."""
    calls = {"n": 0}
    monkeypatch.setattr(provider_mod, "_BREAKER_MIN_LATENCY_S", 0.1)
    _provider(monkeypatch, _slow_502_handler(calls))
    t0 = time.monotonic()
    first = client.post("/api/v1/assistant/chat", json=STEP7_MODEL_BODY)
    first_elapsed = time.monotonic() - t0
    assert first.status_code == 200
    assert first.json()["ai_status"] == "unavailable"
    assert first_elapsed >= 0.3
    assert calls["n"] == 1
    assert gateway_breaker_open()

    t0 = time.monotonic()
    second = client.post("/api/v1/assistant/chat", json=STEP7_MODEL_BODY)
    assert time.monotonic() - t0 < 1
    assert second.status_code == 200
    assert second.json()["ai_status"] == "unavailable"
    assert calls["n"] == 1, "second turn must not touch the network"
    assert second.json()["lines"] == first.json()["lines"]


# ---------------------------------------------------------------------------
# 6 — the single-attempt shape: no retry multiplier anywhere
# ---------------------------------------------------------------------------

def test_step7_backend_at_most_one_model_call_per_turn():
    """ai.chat.answer() makes at most one provider.chat() call per
    turn with a 15 s budget and no repair retry: a slow turn cannot
    be two stacked model calls. The W1 routing returns some turns
    before the call, so the bound is "at most one"."""
    src = CHAT_PY.read_text(encoding="utf-8")
    block = src[src.index("def answer("):]
    assert block.count("provider.chat(") == 1
    assert "timeout_s=15.0" in block
    assert "model_skip_cached()" in block


def test_step7_frontend_one_attempt_no_retry():
    """RecChat's askModel issues exactly one fetchJsonChat per turn,
    and fetchJsonChat bounds one attempt at 18 s inside a 20 s
    budget with retryOnTimeout=false: a slow backend reply is
    waited out once, never re-issued (the 18 s is headroom over
    the backend's 15 s, not a second attempt)."""
    api = API_TS.read_text(encoding="utf-8")
    fn = api[api.index("export async function fetchJsonChat"):]
    fn = fn[:fn.index("\n}\n") + 3]
    assert "budgetMs: 20_000" in fn
    assert "attemptTimeoutMs: 18_000" in fn
    assert "retryOnTimeout: false" in fn

    rec = REC_CHAT.read_text(encoding="utf-8")
    ask = rec[rec.index("const askModel"):rec.index("/** Free text:", rec.index("const askModel"))]
    assert ask.count("fetchJsonChat") == 1
    assert "r9chat.thinkingElapsed" in rec  # the "正在查已核实资料… N 秒" line
