"""Round 26 W3 — a fee question must never come back as a rankings line
(re-test task 20).

Tester finding: the English fee question "What is the tuition fee for
ETH Zurich Computer Science?" asked a 5th time in a long conversation
returned "ETH Zurich: QS 2027 #=8 · THE 2027 #12 · ARWU 2026 #19."
instead of the fee answer.

Root cause (see ~/workspace/r26-w3-report.md): the model path had no
intent pin. With a UG profile the question matches a single programme,
so Round 25's two-candidate template routing does not apply and the
turn is model-first whenever the gateway allows it; _retrieve()'s
scope loop put ETH's QS/THE/ARWU rank sources into the model evidence
catalogue alongside the fee facts; and neither the system prompt nor
validation pinned the answer type to the question's intent — a model
payload answering the fee question with the rankings line validated
with zero errors.

Fix (backend/ai/chat.py):
1. _retrieve() gates the scope loop's ranking_sources() on rank
   intent: only a question that actually asks about ranks offers
   rank sources to the model.
2. answer() runs a deterministic post-validation intent check
   (_model_lines_match_intent): a fee question whose template
   resolved a programme with a fee must have the fee figure in the
   rendered lines, else the template fallback answers. Devil turns
   are excluded (their replies challenge conflicts, not facts).

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r26_w3_fee_intent.py
"""
from __future__ import annotations

import json

import httpx
import pytest

import app.ai_status_cache as status_cache
from ai.chat import _model_lines_match_intent, _retrieve, answer
from ai.provider import ProviderAdapter, reset_gateway_breaker

Q_EN = "What is the tuition fee for ETH Zurich Computer Science?"
Q_RANK = "What is the QS ranking of ETH Zurich?"
SCOPE = ["eth-cs-bsc-2027", "eth-cse-bsc-2027",
         "zurich-informatics-bsc-2027"]
RANK_LINE = "ETH Zurich: QS 2027 #=8 · THE 2027 #12 · ARWU 2026 #19."
RANK_EVIDENCE = ["rank:qs:eth-zurich", "rank:the:eth-zurich",
                 "rank:arwu:eth-zurich"]

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


def _ranking_payload_handler(calls: dict):
    """A stub model that always answers with the rankings line, citing
    the rank sources — exactly the payload the live 5th ask produced.
    Before the fix this validated clean and was returned verbatim."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        payload = {
            "summary": RANK_LINE,
            "claims": [{"text": RANK_LINE, "kind": "fact", "rule_ids": [],
                        "evidence_ids": list(RANK_EVIDENCE)}],
            "unknowns": [], "actions": [], "limitations": []}
        return _openai_reply(json.dumps(payload, ensure_ascii=False))
    return handler


def _fee_payload_handler(calls: dict):
    """A well-behaved stub model: answers the fee from the catalogue,
    citing the fee source — so a correct model fee answer must still
    reach the user (Layer 2 must not over-block)."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = json.loads(request.content)
        envelope = json.loads(body["messages"][-1]["content"])
        catalog = envelope.get("evidence_catalog", [])
        fee = next((c for c in catalog
                    if "4,380" in c.get("excerpt", "")), None)
        assert fee is not None, "fee source must be in the catalogue"
        text = next(s.strip() for s in fee["excerpt"].split(".")
                    if "4,380" in s) + "."
        payload = {
            "summary": text,
            "claims": [{"text": text, "kind": "fact", "rule_ids": [],
                        "evidence_ids": [fee["id"]]}],
            "unknowns": [], "actions": [], "limitations": []}
        return _openai_reply(json.dumps(payload, ensure_ascii=False))
    return handler


# ---------------------------------------------------------------------------
# The fix: a fee question answers the fee on every ask
# ---------------------------------------------------------------------------

def test_fee_question_never_returns_rank_line_over_five_asks(monkeypatch):
    """Re-test 20: the ETH fee question asked 5x must answer the fee
    every time, whatever the history and whether the model is up."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _ranking_payload_handler(calls))
    history: list[dict] = []
    for _ in range(5):
        r = answer(Q_EN, "en", history=list(history), provider=provider,
                   program_ids=list(SCOPE), track="undergraduate")
        assert "CHF 4,380" in r["lines"][0], r["lines"]
        assert "QS 2027" not in r["lines"][0], r["lines"]
        history.append({"role": "user", "content": Q_EN})
        history.append({"role": "assistant",
                        "content": " ".join(r["lines"])})
        history = history[-6:]
    # The stub model was attempted (the turn is model-first for a
    # single match), but its rankings line never reached the user.
    assert calls["n"] == 5


def test_fee_catalogue_has_no_rank_sources():
    _template, sources, _pids = _retrieve(
        Q_EN, "en", country_programmes=True,
        program_ids=list(SCOPE), track="undergraduate")
    assert not [s for s in sources if s.id.startswith("rank:")], \
        [s.id for s in sources]


def test_rank_question_catalogue_keeps_rank_sources():
    _template, sources, _pids = _retrieve(
        Q_RANK, "en", country_programmes=True,
        program_ids=["eth-cs-bsc-2027"], track="undergraduate")
    assert any(s.id.startswith("rank:") for s in sources), \
        [s.id for s in sources]


def test_correct_model_fee_answer_still_reaches_user(monkeypatch):
    """Layer 2 must not over-block: a model fee answer that states
    the verified fee figure passes the intent check."""
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _fee_payload_handler(calls))
    r = answer(Q_EN, "en", provider=provider,
               program_ids=list(SCOPE), track="undergraduate")
    assert r["ai_status"] == "available", r
    assert "CHF 4,380" in r["lines"][0], r["lines"]
    assert calls["n"] == 1


def test_intent_check_unit_fee_requires_fee_figure():
    template = {"program_id": "eth-cs-bsc-2027"}
    assert _model_lines_match_intent(
        ["ETH Zurich — Bachelor of Science in Computer Science "
         "tuition: CHF 4,380 per year."],
        template, Q_EN, "en") is True
    assert _model_lines_match_intent([RANK_LINE], template, Q_EN, "en") \
        is False
    # Unknown intent always passes; no programme resolved passes.
    assert _model_lines_match_intent([RANK_LINE], {}, Q_EN, "en") is True
    assert _model_lines_match_intent(
        [RANK_LINE], template,
        "What is the QS ranking of ETH Zurich?", "en") is True
    # The figure comparison tolerates the qualifier suffix: the
    # template fee_text is "GBP 48,600 per year (overseas)" while a
    # grounded model line says "... overseas tuition is GBP 48,600
    # per year." — same figure, must pass.
    assert _model_lines_match_intent(
        ["UCL Computer Science BSc overseas tuition is GBP 48,600 "
         "per year."],
        {"program_id": "ucl-cs-bsc-2026"},
        "What is the UCL Computer Science BSc tuition fee?",
        "en") is True
