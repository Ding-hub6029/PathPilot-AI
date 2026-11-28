"""Round 26 W1 — Chinese step-7 (PrefChat) timeout + answer loss.

Re-test task 20 (2026-11-27 19:58-20:12 CST, gateway flapping):
in the CHINESE wizard the pref-chat turn showed
"正在查已核实资料… 0 秒" counting up, waited up to ~60 s, then
fell back to a template offline answer — and on one round the
user's answer (大学城) was LOST: the chat announced the AI was
unreachable, restarted the guided questions from the beginning,
and progress stayed at "已了解 3 / 8 项". The ENGLISH wizard went
instant offline (1-2 s) with an honest offline note and never lost
an answer.

Root causes, measured before the fix (see DECISIONS #R26-W1):
1. ``ai.pref_chat.pref_answer`` never consulted
   ``model_skip_cached()`` — the fail-fast gate ``ai.chat.answer``
   and ``/simulate`` already use. With the gateway known down (a
   probe said "unavailable" within its 60 s TTL, breaker still
   closed because the probe failed fast) every pref-chat turn paid
   the full 15 s model budget. Measured: a cold-gateway pref turn
   cost 15.0 s in BOTH locales with ``extracted={}`` — there is no
   locale branch in the code; the en run was fast only because the
   breaker happened to be open then. The 60 s the tester saw is the
   stacked cost of that 15 s turn, the frontend's 18 s per-attempt
   abort, and the guided re-answer's own 12 s parse attempt.
2. The deterministic fallback extraction was countries-only, so for
   an enum answer the fallback reply carried ``extracted={}`` and
   the ONLY preservation was the frontend's ``preserveFailedAnswer``
   keyed on ``questionAtSend`` (the render-time ``nextQ``). When
   that context was wrong or null — the model considered the chat
   done, or the question was skipped — ``mapFailedPrefAnswer``
   returned null, the answer was only prefilled into the guided
   input, and ``enterGuidedMode()`` resumed the queue at the first
   unanswered CONFIRMED preference, i.e. from the beginning when
   the earlier answers were still unconfirmed pending extractions.

Fixes pinned here:
1. ``pref_answer`` consults ``model_skip_cached()`` before the
   model call (same gate as ``ai.chat.answer``) and returns the
   template + deterministic extraction at once; ``parse_profile``
   (the guided re-answer path) does the same instead of its 12 s
   model attempt.
2. The deterministic extraction now also maps the answer to the
   FIRST still-missing preference — the question the chat is
   actually asking — from the same exact-match synonym lists the
   frontend's local mapper uses, so the fallback reply itself
   carries the answer: the frontend keeps the turn as an offline
   turn with its confirm bubble (Round 10 path) and never drops to
   the guided queue at all. The model-success path fills in the
   same enums when the model returns an empty extraction.
3. The frontend's ``mapFailedPrefAnswer`` maps an exact enum answer
   even with no question context (``q`` null), so a fetch-level
   timeout (no backend reply at all) still preserves it.

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r26_w1.py
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

import app.ai_status_cache as ai_status_cache
from ai.parse import parse_profile
from ai.pref_chat import _deterministic_extract, _question_line, pref_answer
from ai.provider import ProviderAdapter, _trip_gateway_breaker, reset_gateway_breaker
from app.ai_status_cache import model_skip_cached, reset_ai_status_cache

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"

# The re-test's profile at the lost turn: Switzerland + cool known,
# environment (大学城) being answered next.
KNOWN_CH_COOL = {"countries": ["CH"], "climate": "cool"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reset_ai_status_cache()
    reset_gateway_breaker()
    yield
    reset_ai_status_cache()
    reset_gateway_breaker()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_provider(monkeypatch, handler) -> ProviderAdapter:
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")
    return ProviderAdapter(_transport=httpx.MockTransport(handler))


def _no_key_provider(monkeypatch) -> ProviderAdapter:
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return ProviderAdapter()


def _seed_probe_unavailable() -> None:
    """Pretend a probe just said the gateway is unavailable (fresh,
    inside its 60 s TTL) while the breaker is still closed — the
    regime the old pref-chat code paid the full model budget for."""
    with ai_status_cache._ai_status_lock:
        ai_status_cache._AI_STATUS_CACHE["at"] = time.monotonic()
        ai_status_cache._AI_STATUS_CACHE["payload"] = {"ai_status": "unavailable"}
    assert model_skip_cached()


def _counting_handler(calls: dict):
    """A gateway that must never be reached: records the attempt and
    answers 500 (a real hang would cost the 15 s budget)."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"error": "must not be called"})
    return handler


def _empty_extraction_handler(request: httpx.Request) -> httpx.Response:
    """A mock model that answers validly but extracts nothing — the
    silent-gap case the fill-in must cover."""
    payload = {
        "summary": "明白，我记下了。",
        "claims": [{"text": "没有已核实的数据可以引用。",
                    "kind": "limitation", "rule_ids": [],
                    "evidence_ids": []}],
        "unknowns": [], "actions": [], "limitations": [],
        "extracted": {}, "next_question": "city"}
    return httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps(payload,
                                                       ensure_ascii=False)}}],
        "usage": {}})


# ---------------------------------------------------------------------------
# (a) Fail-fast parity: zh step-7 with a down gateway returns in ~1 s
# ---------------------------------------------------------------------------

def test_zh_step7_probe_unavailable_returns_fast_and_keeps_answer(monkeypatch):
    """The re-test's exact turn: gateway known down via a fresh probe
    verdict, breaker closed. Old code: 15.0 s + extracted={}. New
    code: no gateway call at all, the answer in the extraction, and
    the next question advanced past environment."""
    _seed_probe_unavailable()
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _counting_handler(calls))
    started = time.monotonic()
    r = pref_answer("大学城", "zh-CN", known=dict(KNOWN_CH_COOL),
                    provider=provider)
    elapsed = time.monotonic() - started
    assert elapsed < 2.0, f"known-down turn took {elapsed:.1f}s"
    assert calls["n"] == 0, "fail-fast gate must skip the model call"
    assert r["ai_status"] == "unavailable"
    assert r["model"] is None
    assert r["extracted"] == {"environment": "campus"}
    assert r["next_question"] == "city"
    assert r["done"] is False
    assert r["lines"][-1] == _question_line("city", "zh-CN")
    assert len(r["lines"]) <= 3


def test_en_step7_breaker_open_returns_fast_and_keeps_answer(monkeypatch):
    """Same turn in English with the breaker open (the en re-test's
    regime): no gateway call, the chip label maps to campus."""
    _trip_gateway_breaker()
    assert model_skip_cached()
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _counting_handler(calls))
    started = time.monotonic()
    r = pref_answer("University town · campus vibe", "en",
                    known=dict(KNOWN_CH_COOL), provider=provider)
    elapsed = time.monotonic() - started
    assert elapsed < 2.0, f"breaker-open turn took {elapsed:.1f}s"
    assert calls["n"] == 0
    assert r["ai_status"] == "unavailable"
    assert r["extracted"] == {"environment": "campus"}
    assert r["next_question"] == "city"


def test_parse_profile_probe_unavailable_returns_fast(monkeypatch):
    """The guided re-answer path: a known-down gateway must not cost
    the 12 s parse model attempt either — the regex parse answers
    at once and the local mapping can apply."""
    _seed_probe_unavailable()
    calls = {"n": 0}
    provider = _mock_provider(monkeypatch, _counting_handler(calls))
    started = time.monotonic()
    r = parse_profile("我喜欢很冷的地方，雅思7分", "zh-CN", provider=provider)
    elapsed = time.monotonic() - started
    assert elapsed < 2.0, f"known-down parse took {elapsed:.1f}s"
    assert calls["n"] == 0
    assert r["parser"] == "regex"
    assert r["ai_status"] == "unavailable"


# ---------------------------------------------------------------------------
# (b) The saved answer survives a simulated timeout: deterministic
# extraction maps the first still-missing preference, never a
# question, never a kind of place as a city.
# ---------------------------------------------------------------------------

_DET_CASES = [
    # (message, known, expected deterministic extraction)
    ("大学城", {"countries": ["CH"], "climate": "cool"},
     {"environment": "campus"}),
    ("大学城·校园氛围", {"countries": ["CH"], "climate": "cool"},
     {"environment": "campus"}),
    ("大城市", {"countries": ["CH"], "climate": "cool"},
     {"environment": "big_city"}),
    ("很冷", {"countries": ["CH"]},
     {"climate": "cool"}),
    ("我喜欢四季分明", {"countries": ["CH"]},
     {"climate": "four_seasons"}),
    # Negation guard: "不喜欢冷" must not map to cool.
    ("不喜欢冷", {"countries": ["CH"]}, {}),
    # A bare reason is still not guessed (Round 14 pin).
    ("环境优美", {"countries": ["CH"]}, {}),
    # A free question is never mapped as an answer.
    ("瑞士有哪些好学校？", {"countries": ["CH"], "climate": "cool"}, {}),
    ("苏黎世有什么好玩的？",
     {"countries": ["CH"], "climate": "cool", "environment": "campus"}, {}),
    # A kind of place is never recorded as a city.
    ("大学城",
     {"countries": ["CH"], "climate": "cool", "environment": "campus"}, {}),
    # City free text, when the city is what's missing.
    ("苏黎世",
     {"countries": ["CH"], "climate": "cool", "environment": "campus"},
     {"city": "苏黎世"}),
    # Salary as a number + currency, when the salary is what's missing.
    ("60000 GBP",
     {"countries": ["CH"], "climate": "cool", "environment": "campus",
      "city": "Zurich", "afterGrad": "stay"},
     {"salary": {"amount": 60000, "currency": "GBP"}}),
    # After-grad, when that is what's missing.
    ("毕业后想留下来",
     {"countries": ["CH"], "climate": "cool", "environment": "campus",
      "city": "Zurich"},
     {"afterGrad": "stay"}),
    # Pressure / teaching, when each is what's missing.
    ("轻松一点就好",
     {"countries": ["CH"], "climate": "cool", "environment": "campus",
      "city": "Zurich", "afterGrad": "stay", "salary": 60000,
      "salaryCurrency": "GBP"},
     {"pressure": "low"}),
    ("喜欢动手实践",
     {"countries": ["CH"], "climate": "cool", "environment": "campus",
      "city": "Zurich", "afterGrad": "stay", "salary": 60000,
      "salaryCurrency": "GBP", "pressure": "low"},
     {"teaching": "hands_on"}),
    # An already-known preference is never re-reported: climate is
    # known here, so a cold wish cannot re-extract it (Round 15 pin:
    # "我喜欢很冷的地方" with CH+cool falls back with extracted={}).
    ("我喜欢很冷的地方", {"countries": ["CH"], "climate": "cool"}, {}),
]


@pytest.mark.parametrize("message,known,want", _DET_CASES)
def test_deterministic_extract_first_missing_preference(message, known, want):
    assert _deterministic_extract(message, known) == want


def test_pref_answer_timeout_keeps_answer_and_advances(monkeypatch):
    """End to end through the no-key fallback (the same fallback a
    model timeout returns): the environment answer is extracted,
    the next question advances to the city, and progress does not
    regress — the wizard continues from where it was."""
    provider = _no_key_provider(monkeypatch)
    r = pref_answer("大学城", "zh-CN", known=dict(KNOWN_CH_COOL),
                    provider=provider)
    assert r["ai_status"] == "unavailable"
    assert r["extracted"] == {"environment": "campus"}
    assert r["next_question"] == "city"
    assert r["done"] is False
    # The frontend's Round-10 path keys on this: a non-empty
    # extraction keeps the turn as an offline turn with its confirm
    # bubble instead of dropping to the guided queue.
    assert r["extracted"]


def test_model_success_empty_extraction_filled_in(monkeypatch):
    """A model that answers validly but extracts nothing no longer
    drops the answer either: the deterministic fill-in supplies the
    country / reason the model missed, and the model output itself
    is still used.

    Round 29 W2 (E4) supersede: the old message ("大学城") is now a
    guided answer and never reaches the model, so the fill-in is
    pinned with a non-guided message instead — a country named
    mid-flow ("我想去英国，因为那边环境优美") while environment is
    what's missing: the model extracts nothing, the fill-in adds
    the new country + reason, and the next question stays
    environment."""
    provider = _mock_provider(monkeypatch, _empty_extraction_handler)
    r = pref_answer("我想去英国，因为那边环境优美", "zh-CN",
                    known=dict(KNOWN_CH_COOL), provider=provider)
    assert r["ai_status"] == "available"
    assert r["extracted"] == {"countries": ["GB"], "note": "那边环境优美"}
    assert r["next_question"] == "environment"


# ---------------------------------------------------------------------------
# Frontend: mapFailedPrefAnswer with no question context (Node harness
# over the compiled frontend — same pattern as test_p0_retest6.py).
# ---------------------------------------------------------------------------

_NODE_CASES = [
    # (name, text, question, expected patch or None)
    ("environment chip word survives timeout", "大学城", "environment",
     {"prefEnvironment": "campus"}),
    ("environment chip label survives timeout", "大学城·校园氛围",
     "environment", {"prefEnvironment": "campus"}),
    ("no question context: 大学城 still maps to campus", "大学城", None,
     {"prefEnvironment": "campus"}),
    ("no question context: 很冷 still maps to cool", "很冷", None,
     {"prefClimate": "cool"}),
    ("no question context: country still wins", "瑞士", None,
     {"prefCountries": ["CH"]}),
    ("no question context: question never mapped",
     "瑞士有哪些好学校？", None, None),
    ("no question context: unmappable stays null", "随便", None, None),
]

_NODE_HARNESS = r"""
const pc = require(OUT + '/src/components/PrefChat.js');
const { emptyProfile } = require(OUT + '/src/lib/types.js');
const zh = require(FE + '/messages/zh-CN.json');
const t = (k) => zh[k] ?? k;
// The re-test's profile at the lost turn: CH + cool known.
const profile = { ...emptyProfile, prefCountries: ['CH'], prefClimate: 'cool' };
const cases = JSON.parse(process.argv[2]);
let fail = 0;
for (const [name, text, q, want] of cases) {
  const got = pc.mapFailedPrefAnswer(text, q, t, profile);
  const gotPatch = got ? got.patch : null;
  if (JSON.stringify(gotPatch) !== JSON.stringify(want)) {
    console.log('FAIL ' + name + ' -> ' + JSON.stringify(gotPatch) + ' want ' + JSON.stringify(want));
    fail++;
  } else {
    console.log('PASS ' + name);
  }
}
process.exit(fail ? 1 : 0);
"""


def test_failed_answer_mapping_without_question_context(tmp_path):
    """The frontend backstop: even when the question a timed-out turn
    answered is unknown (q null), an exact enum answer is preserved
    instead of only being prefilled — the answer survives the
    timeout and the guided queue resumes past it."""
    outdir = tmp_path / "r26_w1_prefchat"
    res = subprocess.run(
        ["npx", "tsc", "src/components/PrefChat.tsx",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r26_w1_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(FE))), encoding="utf-8")
    env = {"PATH": os.environ["PATH"],
           "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness), json.dumps(_NODE_CASES, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
