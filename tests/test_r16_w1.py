"""Round 16 W1 — PrefChat WHY order, WHY-in-history, input live during confirm.

Audit profile: China Gaokao, UG, CS, 680/750, IELTS 7.0, budget
GBP 50,000, 2027, overseas, Switzerland / cool / university-town /
Zurich. Audit flow: turn 1 "我想去瑞士，因为那边环境优美", WHY
answered "喜欢湖光山色、空气清新、安静宜居".

Re-test task 10 (2026-11-27 03:14-03:19 CST) found three P0s, all
in the same turn-rendering path:

FINDING 1 — WHY ORDER STILL WRONG. First-reply bubbles were (1)
record + climate question, (2) WHY question, (3) confirm bubble.
Root cause: the first reply's lines are model-written AND the server
appends the next-question (climate) line as the last line, while the
WHY renders as a separate bubble after the whole reply. Fix at the
source: when a turn carries a WHY follow-up, the backend withholds
the next-question line from `lines` (the WHY IS the turn's question)
and `next_question` still names the deferred preference; the
frontend renders the deferred question only after the WHY is
answered or skipped. The order is asserted on the RENDERED bubble
sequence (prefTurnBubbles in frontend/src/lib/chat.ts), in BOTH the
model-up and the gateway-down (template) paths — not on the API
field alone.

FINDING 2 — WHY ANSWER DETACHED FROM ITS QUESTION IN HISTORY. The
WHY answer rendered as a bottom-appended assistant bubble while the
WHY question bubble itself disappeared from history (awaitingReason
was cleared and nothing in the turn remembered the question). Fix:
the WHY is first-class turn state (PrefTurnWhy, persisted with the
turn in the pp-prefchat blob): the question stays in the turn's
history and the acknowledgement renders attached to it, in order.
The same shared rendering (renderPrefTurns) serves the model and
the guided branch, and resume restores it.

FINDING 3 — INPUT DISABLED WHILE CONFIRM IS PENDING. The model-mode
input/send/skip were disabled whenever a confirm was pending and no
WHY was open (`disabled={thinking || (!!pendingExtract &&
!awaitingReason)}`) — so the moment the WHY was answered (or on
resume with a pending extraction) the input died and the user could
not answer the next question before tapping confirm. Fix: the
input/send/skip stay live while a confirm is pending (only a call in
flight disables them); a send during a pending confirm goes through
as a new turn — the request's `known` folds the pending extraction
in, and a new extraction folds into the pending confirm (mergeExtracted)
instead of overwriting it, so nothing understood is dropped.

Run from the project root:
    .venv/bin/pytest tests/test_r16_w1.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from ai.pref_chat import _question_line, pref_answer
from ai.provider import ProviderAdapter

ROOT = Path(__file__).resolve().parents[1]

CLIMATE_Q = _question_line("climate", "zh-CN")
AUDIT_MSG = "我想去瑞士，因为那边环境优美"


# ---------------------------------------------------------------------------
# Mock-provider helpers (httpx.MockTransport; no real key, no network)
# ---------------------------------------------------------------------------

def _openai_reply(payload_text: str) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"content": payload_text}}], "usage": {}})


def _mock_provider(monkeypatch, handler) -> ProviderAdapter:
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")
    return ProviderAdapter(_transport=httpx.MockTransport(handler))


def _no_key_provider(monkeypatch) -> ProviderAdapter:
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return ProviderAdapter()


def _http500_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"error": "gateway down"})


def _fixed_model_handler(payload: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_reply(json.dumps(payload, ensure_ascii=False))
    return handler


AUDIT_MODEL_PAYLOAD = {
    "summary": "明白，你说那边环境优美，我记下了。",
    "claims": [{"text": "苏黎世：四季分明。", "kind": "fact",
                "rule_ids": [], "evidence_ids": ["climate:zurich"]}],
    "unknowns": [], "actions": [], "limitations": [],
    "extracted": {"countries": ["CH"], "note": "那边环境优美"},
    "next_question": "climate",
}


# ---------------------------------------------------------------------------
# Finding 1 — backend: the WHY is the turn's question, the climate
# question line is withheld from `lines` on all three paths
# ---------------------------------------------------------------------------

def test_r16_why_withholds_next_question_line_model_up(monkeypatch):
    # Round 29 W2 (E4) supersede: the audit sentence is a guided
    # answer, so this turn takes the deterministic route (model never
    # called) — the WHY-withholding pin holds there, exactly as the
    # no-key and gateway-error variants already pin. The reason rides
    # in `extracted.note` / `why_followup`, not in the reply lines
    # (the old "环境优美" in `lines` pin is superseded with the
    # routing change).
    provider = _mock_provider(monkeypatch, _fixed_model_handler(AUDIT_MODEL_PAYLOAD))
    r = pref_answer(AUDIT_MSG, "zh-CN", known={}, provider=provider)
    assert r["ai_status"] == "unavailable"
    assert r["why_followup"] == {"countries": ["CH"], "note": "那边环境优美"}
    assert r["extracted"] == {"countries": ["CH"], "note": "那边环境优美"}
    # The deferred preference still rides in next_question — but the
    # climate question line must NOT be in `lines`: it rendered ahead
    # of the WHY question in every re-test.
    assert r["next_question"] == "climate"
    assert CLIMATE_Q not in r["lines"]
    assert len(r["lines"]) <= 3


def test_r16_why_withholds_next_question_line_no_key(monkeypatch):
    r = pref_answer(AUDIT_MSG, "zh-CN", known={},
                    provider=_no_key_provider(monkeypatch))
    assert r["ai_status"] == "unavailable"
    assert r["why_followup"] == {"countries": ["CH"], "note": "那边环境优美"}
    assert r["next_question"] == "climate"
    assert CLIMATE_Q not in r["lines"]
    assert len(r["lines"]) <= 3


def test_r16_why_withholds_next_question_line_gateway_error(monkeypatch):
    provider = _mock_provider(monkeypatch, _http500_handler)
    r = pref_answer(AUDIT_MSG, "zh-CN", known={}, provider=provider)
    assert r["ai_status"] == "unavailable"
    assert r["why_followup"] == {"countries": ["CH"], "note": "那边环境优美"}
    assert r["next_question"] == "climate"
    assert CLIMATE_Q not in r["lines"]
    assert len(r["lines"]) <= 3


def test_r16_no_why_still_asks_next_question_last(monkeypatch):
    # Control: a turn with no new country carries no WHY, so the
    # next-question line is still the last line of `lines` — the
    # withholding fires ONLY when why_followup is present.
    r = pref_answer("凉爽", "zh-CN", known={"countries": ["CH"], "climate": "cool"},
                    provider=_no_key_provider(monkeypatch))
    assert r["why_followup"] is None
    assert r["next_question"] == "environment"
    assert r["lines"][-1] == _question_line("environment", "zh-CN")


def test_r16_why_suppressed_by_earlier_reason_still_asks(monkeypatch):
    # Control: a reason already on file from an earlier turn means no
    # WHY — the question line is asked as before.
    r = pref_answer("还想去新加坡", "zh-CN",
                    known={"countries": ["CH"], "note": "环境优美"},
                    provider=_no_key_provider(monkeypatch))
    assert r["why_followup"] is None
    assert r["next_question"] == "climate"
    assert r["lines"][-1] == CLIMATE_Q


# ---------------------------------------------------------------------------
# Findings 1+2 — rendered bubble order (node harness over lib/chat.ts)
# ---------------------------------------------------------------------------

_NODE_HARNESS = r"""
const chat = require(OUT + '/chat.js');
const { emptyProfile } = require(OUT + '/types.js');
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + ' -> ' + g + ' want ' + w); fail++; }
  else console.log('PASS ' + name);
};
const kinds = (bs) => bs.map((b) => b.kind);
const CLIMATE_Q = '你喜欢什么样的气候——暖和、凉爽、四季分明还是温和？';

// The audit first turn, as the backend now returns it on BOTH paths:
// lines carry NO climate question (withheld while the WHY is the
// turn's question); why_followup rides in the first reply;
// next_question still names the deferred preference.
const modelReply = {
  lines: ['明白，你说那边环境优美，我记下了。', '苏黎世：四季分明。'],
  ai_status: 'available', model: 'deepseek/test-model',
  extracted: { countries: ['CH'], note: '那边环境优美' },
  next_question: 'climate',
  why_followup: { countries: ['CH'], note: '那边环境优美' },
};
const templateReply = {
  lines: ['已核实的数据里有这些城市：苏黎世（四季分明，14 个项目）、洛桑（四季分明，11 个项目）。',
    '可以开始资格检查，逐项核对你的背景。'],
  ai_status: 'unavailable', model: null,
  extracted: { countries: ['CH'], note: '那边环境优美' },
  next_question: 'climate',
  why_followup: { countries: ['CH'], note: '那边环境优美' },
};
const whyOpen = { countries: ['CH'], note: '那边环境优美', turnId: 1 };
const whyRecord = { countries: ['CH'], note: '那边环境优美', answer: null, skipped: false };

// --- Finding 1: WHY before the climate question, both paths --------
for (const [label, reply, offline] of [['model-up', modelReply, false], ['gateway-down template', templateReply, true]]) {
  const turn = { id: 1, question: '我想去瑞士，因为那边环境优美',
    reply, replyLocale: 'zh-CN', offline, why: whyRecord };
  const bs = chat.prefTurnBubbles(turn, whyOpen);
  check('F1 ' + label + ': bubble order is user, reply, WHY',
    kinds(bs), ['user', 'reply', 'why']);
  check('F1 ' + label + ': no deferred question while the WHY is live',
    bs.some((b) => b.kind === 'deferredQuestion'), false);
  check('F1 ' + label + ': reply lines carry no climate question',
    bs.find((b) => b.kind === 'reply').lines.some((l) => l.includes('气候')), false);
  check('F1 ' + label + ': WHY question names the reason',
    bs.find((b) => b.kind === 'why'), { kind: 'why', countries: ['CH'], note: '那边环境优美' });
}

// --- Finding 2: WHY question + answer stay adjacent in history -----
const whyAnswer = '喜欢湖光山色、空气清新、安静宜居';
const turnsAnswered = chat.answerTurnWhy(
  [{ id: 1, question: '我想去瑞士，因为那边环境优美', reply: modelReply,
     replyLocale: 'zh-CN', offline: false, why: whyRecord }],
  1, whyAnswer, whyOpen);
check('F2 WHY answer attaches to its turn (not confirmedNotes)',
  turnsAnswered[0].why, { countries: ['CH'], note: '那边环境优美', answer: whyAnswer, skipped: false });
check('F2 other turns untouched by the answer',
  turnsAnswered.length, 1);
const bsAnswered = chat.prefTurnBubbles(turnsAnswered[0], null);
check('F2 bubble order after answering: user, reply, WHY, answer, deferred climate',
  kinds(bsAnswered), ['user', 'reply', 'why', 'whyAnswer', 'deferredQuestion']);
check('F2 WHY question and answer are adjacent in history',
  bsAnswered[2].kind === 'why' && bsAnswered[3].kind === 'whyAnswer', true);
check('F2 acknowledgement carries the verbatim answer',
  bsAnswered[3], { kind: 'whyAnswer', answer: whyAnswer });
check('F2 deferred question is climate, after the WHY answer',
  bsAnswered[4], { kind: 'deferredQuestion', question: 'climate' });
check('F2 reply lines still carry no climate question after answering',
  bsAnswered[1].lines.some((l) => l.includes('气候')), false);

// --- Finding 2: skipping keeps the question, asks the deferred one --
const turnsSkipped = chat.skipTurnWhy(
  [{ id: 1, question: '我想去瑞士，因为那边环境优美', reply: modelReply,
     replyLocale: 'zh-CN', offline: false, why: whyRecord }],
  1, whyOpen);
const bsSkipped = chat.prefTurnBubbles(turnsSkipped[0], null);
check('F2 skip: bubble order is user, reply, WHY, deferred climate (no answer)',
  kinds(bsSkipped), ['user', 'reply', 'why', 'deferredQuestion']);
check('F2 skip: WHY record keeps the question, marks skipped',
  turnsSkipped[0].why.skipped, true);

// --- Finding 1: locale re-fetch must not duplicate the question -----
// After the WHY was answered AND confirmed, a locale re-fetch
// recomputes why_followup as null, so the fresh reply DOES end with
// the climate question line. The turn still renders it once, as the
// deferred bubble — never twice, never inside the reply ahead of
// the WHY.
const refetchedReply = { ...modelReply, why_followup: null,
  lines: ['明白，你说那边环境优美，我记下了。', '苏黎世：四季分明。', CLIMATE_Q] };
const turnRefetched = { id: 1, question: '我想去瑞士，因为那边环境优美',
  reply: refetchedReply, replyLocale: 'zh-CN', offline: false,
  why: { countries: ['CH'], note: '那边环境优美', answer: whyAnswer, skipped: false } };
const bsRefetched = chat.prefTurnBubbles(turnRefetched, null);
check('F1 re-fetch: reply bubble drops the trailing question line',
  bsRefetched[1], { kind: 'reply', lines: ['明白，你说那边环境优美，我记下了。', '苏黎世：四季分明。'] });
check('F1 re-fetch: deferred climate question still renders once',
  bsRefetched.filter((b) => b.kind === 'deferredQuestion'), [{ kind: 'deferredQuestion', question: 'climate' }]);

// --- Finding 1 control (Round 28 D1 supersedes the old pin): a turn
// with no WHY no longer keeps its question line in the reply — the
// line is frozen in the reply's locale, so after a language switch
// the robot's question stayed Chinese in the English UI (re-test 22
// item d). The trailing line moves to a `question` bubble, rendered
// through the current locale's question key (see
// tests/test_r28_d1.py).
const climateTurn = { id: 2, question: '凉爽',
  reply: { lines: ['凉爽记下了。', CLIMATE_Q], ai_status: 'available',
    extracted: { climate: 'cool' }, next_question: 'environment' },
  replyLocale: 'zh-CN', offline: false };
check('F1 control (R28 D1): no-WHY turn moves the question line to a question bubble',
  chat.prefTurnBubbles(climateTurn, null),
  [{ kind: 'user', text: '凉爽' },
   { kind: 'reply', lines: ['凉爽记下了。'] },
   { kind: 'question', question: 'environment' }]);

// --- Finding 3: a new extraction folds into a pending confirm -------
check('F3 merge: pending countries + new climate both survive',
  chat.mergeExtracted({ countries: ['CH'], note: '那边环境优美' }, { climate: 'cool' }),
  { countries: ['CH'], note: '那边环境优美', climate: 'cool' });
check('F3 merge: newer enum wins',
  chat.mergeExtracted({ climate: 'warm' }, { climate: 'cool' }), { climate: 'cool' });
check('F3 merge: countries union',
  chat.mergeExtracted({ countries: ['CH'] }, { countries: ['SG'] }), { countries: ['CH', 'SG'] });
check('F3 merge: identical note is not duplicated',
  chat.mergeExtracted({ note: '环境优美' }, { note: '环境优美' }), { note: '环境优美' });
check('F3 merge: a new reason appends as one atom',
  chat.mergeExtracted({ countries: ['CH'], note: '那边环境优美' }, { countries: ['SG'], note: '想体验多元文化' }),
  { countries: ['CH', 'SG'], note: '那边环境优美·想体验多元文化' });

// --- Finding 2: the WHY record persists with its turn --------------
const savedProfile = { ...emptyProfile,
  prefCountries: ['CH'], prefCountriesNote: '环境优美·' + whyAnswer };
const fp = chat.prefChatFingerprint(savedProfile);
const state = {
  mode: 'model',
  turns: [{ id: 1, question: '我想去瑞士，因为那边环境优美',
    reply: modelReply, replyLocale: 'zh-CN', offline: false,
    why: { countries: ['CH'], note: '那边环境优美', answer: whyAnswer, skipped: false } }],
  modelTurns: [],
  qIndex: 0, skipped: [], serverNext: 'climate',
  awaitingReason: null, verbatim: {}, failedText: null,
  pendingExtract: { extracted: { countries: ['CH'], note: '那边环境优美' },
    rawText: '我想去瑞士，因为那边环境优美' },
  confirmedNotes: ['瑞士 · “环境优美”'],
};
const restored = chat.parsePrefChatState(chat.serializePrefChatState(state, fp), fp);
check('F2 leave-and-return restores the WHY record on its turn',
  restored && restored.turns[0].why,
  { countries: ['CH'], note: '那边环境优美', answer: whyAnswer, skipped: false });
check('F2 leave-and-return keeps the WHY answer out of confirmedNotes',
  restored && restored.confirmedNotes, ['瑞士 · “环境优美”']);
check('F2 leave-and-return still renders the WHY Q+A adjacent',
  restored && kinds(chat.prefTurnBubbles(restored.turns[0], null)),
  ['user', 'reply', 'why', 'whyAnswer', 'deferredQuestion']);
// A pre-round-16 blob has no why on its turns: it still parses,
// with the WHY simply absent (the live fallback still applies).
const oldBlobObj = JSON.parse(chat.serializePrefChatState(state, fp));
delete oldBlobObj.turns[0].why;
const restoredOld = chat.parsePrefChatState(JSON.stringify(oldBlobObj), fp);
check('F2 round 15 blob still parses',
  restoredOld !== null, true);
check('F2 round 15 blob has no WHY record on the turn',
  restoredOld && restoredOld.turns[0].why, undefined);
// A malformed why is dropped, never applied — the turn survives.
const badBlobObj = JSON.parse(chat.serializePrefChatState(state, fp));
badBlobObj.turns[0].why = { countries: 'CH', answer: 42, skipped: 'yes' };
const restoredBad = chat.parsePrefChatState(JSON.stringify(badBlobObj), fp);
check('F2 malformed WHY is dropped, turn kept',
  restoredBad && restoredBad.turns[0].why, undefined);
check('F2 malformed WHY still parses the turn',
  restoredBad && restoredBad.turns[0].question, '我想去瑞士，因为那边环境优美');
// answerTurnWhy with no matching turn changes nothing.
const untouched = chat.answerTurnWhy(
  [{ id: 1, question: 'x', reply: null, why: whyRecord }], 9, 'y', whyOpen);
check('F2 answerTurnWhy with an unknown turnId changes nothing',
  untouched, [{ id: 1, question: 'x', reply: null, why: whyRecord }]);
process.exit(fail ? 1 : 0);
"""


def test_r16_w1_turn_bubbles_and_persistence(tmp_path):
    """Round 16: the rendered bubble order (WHY before the deferred
    climate question, WHY question + answer adjacent in history) in
    both paths, the re-fetch strip, the extraction merge, and the
    WHY record surviving leave-and-return."""
    outdir = tmp_path / "r16_pref"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/preferences.ts", "src/lib/chat.ts",
         "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r16_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(fe))), encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"],
           "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout


def test_r16_w1_input_live_during_confirm_and_why_on_turn():
    """Round 16, source pins: the model-led input/send/skip stay live
    while a confirm is pending (only a call in flight disables
    them), a send during a pending confirm folds into the pending
    extraction instead of overwriting it, and the WHY answer attaches
    to its turn."""
    prefchat = (ROOT / "frontend/src/components/PrefChat.tsx").read_text(encoding="utf-8")

    # Finding 3: no confirm-pending clause may disable the input,
    # the send button or the skip button, in either branch.
    assert "disabled={thinking || (!!pendingExtract && !awaitingReason)}" not in prefchat
    assert "disabled={thinking || (!!pendingParse && !awaitingReason)}" not in prefchat
    # The model-mode input and skip, and the guided input, are gated
    # only by a call in flight.
    assert prefchat.count("disabled={thinking}") >= 3, (
        "model input, model skip and guided input must be disabled only while thinking")
    # A send during a pending confirm must go through, not return early.
    assert "if (pendingExtract) return;" not in prefchat
    # Both reply paths fold a new extraction into a pending confirm.
    assert prefchat.count("setPendingExtractMerged(r.extracted, trimmed)") == 2, (
        "template + model reply paths must merge into a pending extraction")
    # The request's known folds a pending extraction in, so the
    # server does not re-ask what it already understood.
    assert "mergeKnownWithExtracted(knownFromProfile(profile), pendingExtract.extracted)" in prefchat

    # Finding 2: the WHY answer attaches to its turn; the skip marks
    # it skipped on the turn; arming records the WHY on the turn.
    assert "answerTurnWhy(prev, anchorId, trimmed, awaitingReason)" in prefchat
    assert "skipTurnWhy(prev, anchorId, awaitingReason)" in prefchat
    assert "why: { ...armedWhy, answer: null, skipped: false }" in prefchat
    # The deferred question renders inside the turn, after the WHY.
    assert "t(ASK_KEY[bubble.question])" in prefchat
    # The gateway-down preserve path anchors the WHY to its turn too.
    assert "setAwaitingReason({ countries: newCountries, ...(note ? { note } : {}), turnId })" in prefchat
