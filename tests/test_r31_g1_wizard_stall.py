"""Round 31 G1 — wizard Q6 (afterGrad) stalls 25-27 s on the second run.

Re-test 26 (2026-11-28 16:00-16:08, gateway down the whole run,
0 model-led turns): on the second wizard run, after answering Q6
("stay in the country where I study" / afterGrad) the UI showed a
"Checking verified sources…" spinner with the input disabled; still
spinning at 12 s observed, confirmation only at ~25-27 s. The same
question on the first run answered instantly.

Root cause, verified in code and by reproduction before the fix
(/tmp/r31g1-repro.py): the English afterGrad Stay chip label is
"Stay in the country where I study", and the backend's question
detector (``_det_looks_like_question``, backend/ai/pref_chat.py)
matched its English question words ANYWHERE in the message — so
"where" inside the relative clause ("the country where I study")
read as a question. The deterministic extraction read the answer
correctly (``{'afterGrad': 'stay'}``), but the Round 29 E4 guided
gate (``guided = nxt_missing in det and not
_det_looks_like_question(msg)``) was False, so the turn took the
model path instead of the deterministic route: with the gateway
hanging, the model call burned the full 15 s backend budget
(``timeout_s=15.0``) inside the frontend's 18 s attempt window.
Reproduced pre-fix with a counting mock provider that raises
``httpx.ReadTimeout``: ``pref_answer("Stay in the country where I
study", "en", known={countries, climate, environment, city})``
made 1 model call. The first run was instant because the breaker
(180 s) / probe cache (60 s) was still warm from an earlier slow
failure, so ``model_skip_cached()`` skipped the attempt; the second
run's Q6 was the first model-path turn after the caches cooled —
and Q1-Q5 were instant because no other chip label contains a
question word mid-sentence. The frontend's ``looksLikeQuestion``
(frontend/src/lib/chat.ts) had the identical unanchored regex, so
the same sentence typed as guided free text went to ``askModel``
instead of ``/profile/parse`` + the local mapping.

Fix (no copy, data or i18n change; no new key; the E4 route and
the F1/F2/F3 behaviour are untouched): the English question words
only mark a question when they OPEN the message — ``match`` instead
of ``search`` in ``_det_looks_like_question``, and a ``^`` anchor
on ``QUESTION_WORDS_EN`` in ``looksLikeQuestion``. A genuine
question still opens with its question word ("What is the fee?",
"Where should I study?") or carries a "?" / CJK marker anywhere
(those still match anywhere), so those still take the model path.
Residual: a question word mid-clause without punctuation ("tell me
what take it easy means") can now read as an answer — the confirm
bubble is the safety net (nothing is applied until the user
confirms the extraction).

Covers, with no API key and no network:
- backend routing: every locale's afterGrad Stay chip label (read
  from frontend/messages/*.json) takes the deterministic route with
  ZERO model calls even against a hanging gateway (one test uses a
  handler that sleeps 3 s then raises — pre-fix the turn pays the
  hang; post-fix it never touches the handler and returns in
  engine time), extracted {afterGrad: stay}, next_question salary;
- every en chip label for the 8 preferences is not a question;
- genuine questions still take the model path (exactly one model
  attempt, including a question that ALSO matches an enum synonym);
- node harness over the REAL lib/chat.ts (compiled with tsc, same
  pattern as tests/test_r30_f3_footer_settle.py): the frontend
  detector agrees on the Stay sentence (false), a "?"-marked Stay
  sentence (true), and opening question words (true).

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r31_g1_wizard_stall.py
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from ai.pref_chat import (_det_looks_like_question, _deterministic_extract,
                          pref_answer)
from ai.provider import ProviderAdapter, reset_gateway_breaker
from app.ai_status_cache import reset_ai_status_cache

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "frontend"
MESSAGES = ROOT / "frontend" / "messages"

LOCALES = ("en", "zh-CN", "es", "fr", "pt-BR", "ar")

# The re-test's known set at Q6: countries, climate, environment,
# city answered; afterGrad being asked next.
KNOWN_UPTO_CITY = {"countries": ["CH"], "climate": "cool",
                   "environment": "campus", "city": "Zurich"}
KNOWN_UPTO_PRESSURE = dict(KNOWN_UPTO_CITY, afterGrad="stay",
                           salary=80000, salaryCurrency="CHF")


def _stay_label(locale: str) -> str:
    with open(MESSAGES / f"{locale}.json", encoding="utf-8") as f:
        return json.load(f)["wizard.prefAfterGradStay"]


def _en_chip_labels() -> list[str]:
    """Every en chip label the wizard can send as a guided answer
    (climate / environment / afterGrad / pressure / teaching)."""
    with open(MESSAGES / "en.json", encoding="utf-8") as f:
        msgs = json.load(f)
    prefixes = ("wizard.prefClimate", "wizard.prefEnvironment",
                "wizard.prefAfterGrad", "wizard.prefPressure",
                "wizard.prefTeaching")
    return [v for k, v in msgs.items()
            if k.startswith(prefixes) and isinstance(v, str)]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reset_ai_status_cache()
    reset_gateway_breaker()
    yield
    reset_ai_status_cache()
    reset_gateway_breaker()


def _counting_provider(monkeypatch, handler) -> tuple[ProviderAdapter, dict]:
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")
    calls: dict = {"n": 0}

    def counting(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return handler(request)

    return ProviderAdapter(_transport=httpx.MockTransport(counting)), calls


def _hanging_handler(request: httpx.Request) -> httpx.Response:
    """A hanging gateway: sleeps, then fails. httpx.MockTransport
    ignores timeouts, so a turn that takes the model path pays the
    whole sleep here — the stall, in miniature."""
    time.sleep(3.0)
    raise httpx.ReadTimeout("gateway hangs")


def _fast_fail_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("gateway hangs")


# ---------------------------------------------------------------------------
# (a) The defect: the en Stay label took the model path
# ---------------------------------------------------------------------------

def test_stay_label_en_is_not_a_question():
    assert _det_looks_like_question(
        "Stay in the country where I study") is False


@pytest.mark.parametrize("locale", LOCALES)
def test_stay_label_every_locale_is_not_a_question(locale):
    """Only the en label carried a mid-sentence question word, but
    the rule is pinned for all six Stay labels."""
    assert _det_looks_like_question(_stay_label(locale)) is False


def test_all_en_chip_labels_are_not_questions():
    """No other wizard chip label contains a question word
    mid-sentence — Q6 Stay was the only trap."""
    labels = _en_chip_labels()
    assert len(labels) >= 18  # 4 climate + 4 environment + 4 afterGrad + 3 pressure + 3 teaching
    for label in labels:
        assert _det_looks_like_question(label) is False, label


@pytest.mark.parametrize("locale", ("en", "zh-CN"))
def test_guided_stay_turn_makes_no_model_call(monkeypatch, locale):
    """The defect, turn by turn: a guided answer takes the
    deterministic route — zero model calls, engine time, the answer
    recorded and the next question asked. Only en/zh-CN are
    parametrised here: the deterministic synonyms are en/zh-only by
    design (see test_non_en_zh_stay_label_has_no_synonym_yet), so
    only those two labels are readable without a model today."""
    provider, calls = _counting_provider(monkeypatch, _fast_fail_handler)
    t0 = time.monotonic()
    r = pref_answer(_stay_label(locale), locale,
                    known=dict(KNOWN_UPTO_CITY), provider=provider)
    elapsed = time.monotonic() - t0
    assert calls["n"] == 0
    assert elapsed < 2.0, elapsed
    assert r["ai_status"] == "unavailable"
    assert r["extracted"] == {"afterGrad": "stay"}
    assert r["next_question"] == "salary"
    assert r["done"] is False


@pytest.mark.parametrize("locale", ("es", "fr", "pt-BR", "ar"))
def test_non_en_zh_stay_label_has_no_synonym_yet(locale):
    """Known gap, out of scope for G1: the deterministic synonym
    tables are en/zh-only, so the es/fr/pt-BR/ar Stay labels are
    (correctly) not questions but still unreadable without a model
    — they take the model path, not the guided route. G1 fixes the
    misclassification (a label that IS readable being sent to the
    model anyway); teaching the extractor the other four locales'
    labels is separate work, not a one-line classifier fix."""
    assert _det_looks_like_question(_stay_label(locale)) is False
    assert _deterministic_extract(_stay_label(locale),
                                  dict(KNOWN_UPTO_CITY)) == {}


def test_guided_stay_turn_not_blocked_by_hanging_gateway(monkeypatch):
    """The stall path itself: against a gateway that hangs 3 s, the
    guided Stay turn must not touch it at all — pre-fix this test
    took the 3 s hang (1 model call) before failing; post-fix it
    returns in engine time with no model call."""
    provider, calls = _counting_provider(monkeypatch, _hanging_handler)
    t0 = time.monotonic()
    r = pref_answer("Stay in the country where I study", "en",
                    known=dict(KNOWN_UPTO_CITY), provider=provider)
    assert time.monotonic() - t0 < 2.0
    assert calls["n"] == 0
    assert r["extracted"] == {"afterGrad": "stay"}
    assert r["next_question"] == "salary"


# ---------------------------------------------------------------------------
# (b) Genuine questions still take the model path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message,known", [
    ("Where should I study?", {}),
    ("What is the tuition fee for ETH Zurich Computer Science?", {}),
    # A question that ALSO matches an enum synonym: "take it easy"
    # would map pressure=low, but the opening "What" keeps it a
    # question — the model path, not a silent recording.
    ("What does take it easy mean?", KNOWN_UPTO_PRESSURE),
    # The "?" marker still marks a question anywhere, including on
    # the Stay sentence itself.
    ("Stay in the country where I study?", KNOWN_UPTO_CITY),
    # CJK markers still mark a question anywhere.
    ("瑞士有哪些好学校？", {}),
])
def test_genuine_question_still_attempts_model(monkeypatch, message, known):
    provider, calls = _counting_provider(monkeypatch, _fast_fail_handler)
    r = pref_answer(message, "en" if not message.startswith("瑞") else "zh-CN",
                    known=dict(known), provider=provider)
    assert calls["n"] == 1
    assert r["ai_status"] == "unavailable"


def test_mid_sentence_question_word_without_punctuation_is_answer():
    """Documented residual of the start-anchor rule: a question word
    mid-clause with no "?" reads as an answer. The confirm bubble
    is the safety net — nothing is applied until confirmed — so
    this pins the behaviour rather than the model path."""
    assert _det_looks_like_question(
        "tell me what take it easy means") is False
    assert _deterministic_extract(
        "tell me what take it easy means",
        dict(KNOWN_UPTO_PRESSURE)) == {"pressure": "low"}


# ---------------------------------------------------------------------------
# (c) Frontend detector agrees (node harness over real lib/chat.ts)
# ---------------------------------------------------------------------------

_NODE_HARNESS = r"""
const chat = require(__OUT__ + '/chat.js');
const { looksLikeQuestion } = chat;
const fs = require('fs');
const src = fs.readFileSync(__CHAT__, 'utf8');

let fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('FAIL ' + name + ': got ' + JSON.stringify(got) + ', want ' + JSON.stringify(want)); }
  else console.log('ok ' + name);
}
function checkTrue(name, cond) { check(name, !!cond, true); }

// The defect sentence, typed as guided free text: not a question —
// it goes to /profile/parse + the local mapping, never askModel.
check('en Stay sentence is not a question',
  looksLikeQuestion('Stay in the country where I study'), false);
check('zh Stay label is not a question',
  looksLikeQuestion('留在留学国家'), false);
check('other en chip labels are not questions',
  looksLikeQuestion('Take it easy'), false);
check('campus chip label is not a question',
  looksLikeQuestion('University town · campus vibe'), false);
// A "?" anywhere still marks a question, including on the Stay sentence.
check('Stay sentence with ? is a question',
  looksLikeQuestion('Stay in the country where I study?'), true);
check('CJK question marker still marks a question',
  looksLikeQuestion('瑞士有哪些好学校？'), true);
// Genuine questions still open with their question word.
check('opening Where is a question',
  looksLikeQuestion('Where should I study?'), true);
check('opening What is a question',
  looksLikeQuestion('What is the fee?'), true);
check('opening How is a question',
  looksLikeQuestion('How much pressure is too much?'), true);
// Source pin: the English words are anchored to the start.
checkTrue('QUESTION_WORDS_EN is start-anchored',
  src.includes('/^(what|which|how|why|when|where|is there|are there|any|recommend|suggest|do you|can you|could you|should i|would you)'));

console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
process.exit(fail ? 1 : 0);
"""


def test_frontend_detector_agrees(tmp_path):
    """The frontend's looksLikeQuestion (lib/chat.ts) carries the
    same start-anchor rule as the backend — a typed Stay sentence
    must not route to askModel in the guided queue."""
    outdir = tmp_path / "r31_g1"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/chat.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r31_g1_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("__OUT__", repr(str(outdir)))
        .replace("__CHAT__", repr(str(FE / "src/lib/chat.ts"))),
        encoding="utf-8")
    env = {"PATH": os.environ["PATH"],
           "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=180, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
    assert "HARNESS OK" in node.stdout
