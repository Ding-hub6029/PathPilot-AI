"""Round 15 regression tests (re-test task 9, 2026-11-27 02:23-02:34 CST).

Audit profile: China Gaokao, UG, CS, 680/750, IELTS 7.0, budget
GBP 50,000, 2027, overseas, Switzerland / cool / university-town /
Zurich. Audit flow: turn 1 "我想去瑞士，因为那边环境优美"
(confirmed), WHY answered "干净的空气、湖光山色、安静的生活",
turn 2 "凉爽" (climate understood, NOT yet confirmed) — then leave
to the homepage and return.

FINDING 1 — WHY in first reply STILL BROKEN (reproduced twice).
Re-diagnosis: the backend was already correct — `pref_answer`
returns `why_followup` in the FIRST reply on all three paths
(model-up, no-key fallback, gateway-error fallback; the third is
pinned in tests/test_pref_chat.py), and `armWhyFromReply` armed it
on reply. The drop was the RENDER order in
frontend/src/components/PrefChat.tsx: the WHY bubble sat inside the
`{!modelDone}` input block AFTER the confirm bubble, so the first
visible reply ended with the climate question and the WHY only
appeared underneath the confirm prompt. Round 15 anchors the bubble
to the turn that armed it (`whyAnchoredTurnId` in
frontend/src/lib/chat.ts): it renders inside that turn's block,
immediately after its reply — before the confirm bubble. The
unanchored fallback (old blob, no turnId) renders right after the
turns, still before the confirm bubble.

FINDING 2 — PrefChat resume STILL BROKEN (partial).
(a) The wizard step lived only in React state
(`useState(0)` in frontend/src/app/wizard/page.tsx, no storage at
all), so leaving reset the wizard to step 1/8 — six clicks back —
even though steps 1-6 form data was kept. Round 15 persists the
step in localStorage ('pp-wizard-step') and restores it on mount.
(b) Two pieces of chat state were React-only AND missing from the
persisted blob: `pendingExtract` (the unconfirmed extraction) and
the noted bubbles (the old single `confirmedNote` slot — which also
overwrote the WHY answer the moment the extraction was confirmed).
The persist effect did not even list them as dependencies, so the
blob never saw them: leaving with climate understood-but-unconfirmed
dropped the progress 2/8 -> 1/8 (the count merges the pending
extraction — see knownForProgress) and the confirm bubble, and
leaving after the WHY answer lost both noted bubbles. Round 15
persists `pendingExtract` and a `confirmedNotes` list, restores both
on mount, and renders one bubble per noted item, in order.

Run from the project root:
    .venv/bin/pytest tests/test_r15_pref_chat.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_NODE_HARNESS = r"""
const chat = require(OUT + '/chat.js');
const { emptyProfile } = require(OUT + '/types.js');
const zh = require(FE + '/messages/zh-CN.json');
const tZh = (k) => zh[k] ?? k;
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + ' -> ' + g + ' want ' + w); fail++; }
  else console.log('PASS ' + name);
};

// --- Finding 1: the WHY anchors to the turn that armed it ----------
check('F1 anchor: turnId present and in the list',
  chat.whyAnchoredTurnId({ countries: ['CH'], note: '那边环境优美', turnId: 1 }, [1, 2]), 1);
check('F1 anchor: second turn',
  chat.whyAnchoredTurnId({ countries: ['CH'], turnId: 2 }, [1, 2]), 2);
check('F1 anchor: no turnId -> unanchored fallback',
  chat.whyAnchoredTurnId({ countries: ['CH'], note: '那边环境优美' }, [1, 2]), null);
check('F1 anchor: null reason -> null',
  chat.whyAnchoredTurnId(null, [1, 2]), null);
check('F1 anchor: turnId for a turn no longer listed -> null',
  chat.whyAnchoredTurnId({ countries: ['CH'], turnId: 9 }, [1, 2]), null);
check('F1 anchor: empty turn list -> null',
  chat.whyAnchoredTurnId({ countries: ['CH'], turnId: 1 }, []), null);

// --- Finding 2b: leave-and-return over the audit flow --------------
// Profile after turn 1 confirmed + the WHY answered: Switzerland
// recorded, the reason appended to the note. Climate is NOT in the
// profile yet — it is only in the pending (unconfirmed) extraction.
const whyAnswer = '干净的空气、湖光山色、安静的生活';
const savedProfile = { ...emptyProfile,
  prefCountries: ['CH'], prefCountriesNote: '环境优美·' + whyAnswer };
const fp = chat.prefChatFingerprint(savedProfile);
const confirmSummary = chat.extractedSummary({ countries: ['CH'], note: '环境优美' }, tZh);
check('F2b confirm summary is the noted bubble text',
  confirmSummary, '瑞士 · “环境优美”');
const state = {
  mode: 'model',
  turns: [
    { id: 1, question: '我想去瑞士，因为那边环境优美',
      reply: { lines: ['明白，你说那边环境优美，我记下了。', 'Zurich: four-season climate.',
        '你喜欢什么样的气候——暖和、凉爽、四季分明还是温和？'],
        ai_status: 'available', model: 'openai/test-model',
        extracted: { countries: ['CH'], note: '那边环境优美' }, next_question: 'climate' },
      replyLocale: 'zh-CN', offline: false, pending: false },
    { id: 2, question: '凉爽',
      reply: { lines: ['凉爽记下了。', '你喜欢什么样的气候——暖和、凉爽、四季分明还是温和？'],
        ai_status: 'available', model: 'openai/test-model',
        extracted: { climate: 'cool' }, next_question: 'environment' },
      replyLocale: 'zh-CN', offline: false, pending: false },
  ],
  modelTurns: [],
  qIndex: 0, skipped: [], serverNext: 'environment',
  awaitingReason: null,
  verbatim: {}, failedText: null,
  // Left with the climate extraction UNCONFIRMED.
  pendingExtract: { extracted: { climate: 'cool' }, rawText: '凉爽' },
  // The WHY answer AND the confirm summary, in order.
  confirmedNotes: [whyAnswer, confirmSummary],
};
const blob = chat.serializePrefChatState(state, fp);
const restored = chat.parsePrefChatState(blob, fp);
check('F2b leave-and-return restores both turns',
  restored && restored.turns.length, 2);
check('F2b second turn reply survives the return',
  restored && restored.turns[1].reply && restored.turns[1].reply.extracted, { climate: 'cool' });
check('F2b unconfirmed extraction survives the return',
  restored && restored.pendingExtract, { extracted: { climate: 'cool' }, rawText: '凉爽' });
check('F2b WHY answer bubble survives the return',
  restored && restored.confirmedNotes[0], whyAnswer);
check('F2b confirm summary bubble survives the return',
  restored && restored.confirmedNotes[1], confirmSummary);
check('F2b noted bubbles stay in order',
  restored && restored.confirmedNotes, [whyAnswer, confirmSummary]);
// Progress: the profile alone counts 1 of 8 (countries+note); the
// pending climate extraction lifts it to 2 of 8. Before round 15 the
// pending extraction was never persisted, so the return showed 1/8
// and re-listed climate as missing.
const knownProfileOnly = chat.knownFromProfile(savedProfile);
check('F2b profile alone counts 1 of 8',
  chat.countKnownPrefs(knownProfileOnly), 1);
check('F2b profile + pending extraction counts 2 of 8',
  chat.countKnownPrefs(chat.mergeKnownWithExtracted(knownProfileOnly, restored.pendingExtract.extracted)), 2);
check('F2b next question after return is climate (pending, not yet applied)',
  chat.firstMissingPref(knownProfileOnly), 'climate');

// --- Finding 2b: WHY still open at leave time -----------------------
// Left while the WHY follow-up was open on turn 1: the anchor
// survives, so the bubble still renders with turn 1's reply.
const whyOpen = { ...state, awaitingReason: { countries: ['CH'], note: '那边环境优美', turnId: 1 },
  pendingExtract: { extracted: { countries: ['CH'], note: '那边环境优美' }, rawText: '我想去瑞士，因为那边环境优美' },
  confirmedNotes: [] };
const restoredWhy = chat.parsePrefChatState(chat.serializePrefChatState(whyOpen, fp), fp);
check('F2b open WHY survives the return, anchored to turn 1',
  restoredWhy && restoredWhy.awaitingReason, { countries: ['CH'], note: '那边环境优美', turnId: 1 });
check('F2b anchored WHY still resolves to turn 1 after return',
  chat.whyAnchoredTurnId(restoredWhy && restoredWhy.awaitingReason,
    (restoredWhy && restoredWhy.turns || []).map((x) => x.id)), 1);

// --- Backward compatibility: round 14 blobs --------------------------
// A blob written before round 15 has no pendingExtract /
// confirmedNotes keys (and no turnId on awaitingReason): it still
// parses, with the new fields defaulting — never a failure.
const oldBlobObj = JSON.parse(blob);
delete oldBlobObj.pendingExtract;
delete oldBlobObj.confirmedNotes;
delete oldBlobObj.awaitingReason;
const oldBlob = JSON.stringify({ ...oldBlobObj,
  awaitingReason: { countries: ['CH'], note: '那边环境优美' } });
const restoredOld = chat.parsePrefChatState(oldBlob, fp);
check('F2b round 14 blob still parses',
  restoredOld !== null, true);
check('F2b round 14 blob defaults pendingExtract to null',
  restoredOld && restoredOld.pendingExtract, null);
check('F2b round 14 blob defaults confirmedNotes to []',
  restoredOld && restoredOld.confirmedNotes, []);
check('F2b round 14 WHY without turnId is unanchored, not lost',
  restoredOld && restoredOld.awaitingReason, { countries: ['CH'], note: '那边环境优美' });
check('F2b round 14 WHY resolves to the unanchored fallback',
  chat.whyAnchoredTurnId(restoredOld && restoredOld.awaitingReason,
    (restoredOld && restoredOld.turns || []).map((x) => x.id)), null);
process.exit(fail ? 1 : 0);
"""


def test_r15_pref_chat_why_anchor_and_resume(tmp_path):
    """Round 15: the WHY anchors to its turn, the unconfirmed
    extraction and the noted bubbles survive leave-and-return, and
    round 14 blobs still parse."""
    outdir = tmp_path / "r15_pref"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/preferences.ts", "src/lib/chat.ts",
         "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r15_harness.js"
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


def test_r15_pref_chat_render_order_and_wizard_step():
    """Round 15, source-order pins (no jsdom harness exists for the
    TSX): the WHY bubble renders with its turn, before the confirm
    bubble — never after it — and the wizard step is persisted."""
    prefchat = (ROOT / "frontend/src/components/PrefChat.tsx").read_text(encoding="utf-8")
    wizard = (ROOT / "frontend/src/app/wizard/page.tsx").read_text(encoding="utf-8")

    # Finding 1: the anchored WHY renders inside renderPrefTurns,
    # and the unanchored fallback renders after the turns but before
    # the confirm bubble.
    anchor = prefchat.index("whyAnchor === turn.id && renderWhyBubble()")
    confirm = prefchat.index("{pendingExtract && (")
    assert anchor < confirm, "WHY anchor must render before the confirm bubble"
    fallback = prefchat.index(
        "whyAnchoredTurnId(awaitingReason, turns.map((x) => x.id)) === null && renderWhyBubble()")
    turns_render = prefchat.index("{renderPrefTurns()}")
    assert turns_render < fallback < confirm, (
        "unanchored WHY must render after the turns and before the confirm bubble")
    assert prefchat.count("armWhyFromReply(r, requestKnown, turnId)") == 2, (
        "both reply paths (template + model) must arm the WHY with the turn id")
    # The model-mode input block must no longer hold a WHY bubble
    # after the confirm bubble: between the model {!modelDone} block
    # and the model summary block there is no WHY copy.
    model_done = prefchat.index("{!modelDone && (")
    model_summary = prefchat.index(
        "{/* Summary bubble once all 8 are known", model_done)
    assert "p0.chatWhyReason" not in prefchat[model_done:model_summary], (
        "model-mode input block must not render the WHY after the confirm bubble")
    assert "renderModelChips()" in prefchat[model_done:model_summary]

    # Finding 2b: the persist call carries the previously-dropped
    # state, and no transient single-note slot remains.
    assert "pendingExtract, confirmedNotes" in prefchat
    assert "setConfirmedNote(" not in prefchat
    assert "confirmedNote," not in prefchat and "confirmedNote &&" not in prefchat

    # Finding 2a: the wizard step is persisted and restored.
    assert "pp-wizard-step" in wizard
    assert "useState(loadWizardStep)" in wizard
    assert "localStorage.setItem(WIZARD_STEP_KEY, String(step))" in wizard
    assert "Math.min(STEPS.length - 1, n)" in wizard
