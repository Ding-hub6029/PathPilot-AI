"""Round 26 W4 (ii): level-chip bubble stays English after a language switch.

Re-test 20 (2026-11-27): after switching language, a history bubble
"Taught masters" stayed English. Root cause: in
``CompassPet.tsx`` the disambiguation chip tap (``onChip`` pending
branch) passed ``displayText: t('pet.q1tm')`` — the label localised
at TAP time — into ``sendAskTurn``, which stored it as a verbatim
``freeText`` turn. The bubble was then a frozen string, while the
onboarding step-0 choice bubble next to it re-localised through
``choiceLabel`` at render time.

Fix: the chip tap now passes ``levelChoice: level`` instead, and
``sendAskTurn`` stores it as a structured ``choice`` turn
(``{ kind: 'choice', step: 0, value: level }``), which renders
through the same ``choiceLabel`` path — ``pet.q1ug`` /
``pet.q1tm`` in the CURRENT locale. ``pendingDisambiguation``
(``frontend/src/lib/chat.ts``) treats a trailing ``choice`` turn
as terminating, so the answered disambiguation does not resurrect
the level chips until the follow-up ask lands. Typed level words
stay verbatim ``freeText`` — those are the user's own words, not
a UI-generated label — by design.

Covers, with no API key and no network:

- ``pendingDisambiguation`` via a node harness over the compiled
  ``frontend/src/lib/chat.ts`` (same pattern as
  tests/test_r24_w1_pet_fee_disambiguation.py): still live on the
  ambiguous reply, cleared by a trailing level-choice turn (both
  levels), cleared once the fee is answered, still live after a
  local re-ask;
- source pins on ``CompassPet.tsx``: the pending chip branch
  passes ``levelChoice`` (no baked ``displayText: t(...)``),
  ``sendAskTurn`` stores it as a ``choice`` step-0 turn, and
  ``choiceLabel`` still maps step 0 through ``pet.q1ug`` /
  ``pet.q1tm``;
- locale key check: ``pet.q1tm`` exists in all 6 locale files
  (so the re-localised bubble has a label to render in every
  locale).

Run from the project root:
    .venv/bin/pytest tests/test_r26_w4_level_bubble.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_NODE_HARNESS = r"""
const chat = require(OUT + '/chat.js');
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + ' -> ' + g + ' want ' + w); fail++; }
  else console.log('PASS ' + name);
};

const Q_EN = 'What is the tuition fee for ETH Zurich Computer Science?';
const BSC = 'eth-cs-bsc-2027';
const MSC = 'eth-cs-msc-2027';
const AMB = { lines: ['I found 2 matching programmes: ETH Zurich — MSc in Computer Science, ETH Zurich — Bachelor of Science in Computer Science. Tell me undergraduate or masters.'], ai_status: 'unavailable', candidates: [MSC, BSC] };
const FEE = { lines: ['ETH Zurich — Bachelor of Science in Computer Science tuition: CHF 4,380 per year.'], ai_status: 'unavailable' };

const base = [
  { kind: 'prompt', key: 'pet.greeting' },
  { kind: 'freeText', text: Q_EN },
  { kind: 'ask', message: Q_EN, reply: AMB, replyLocale: 'en', offline: true, devil: false },
];

// Still live on the ambiguous reply (pre-existing behaviour).
check('pending: live on the ambiguous reply',
  chat.pendingDisambiguation(base) !== null, true);

// Round 26 W4: a level-chip answer, stored as a structured choice
// turn, ends the pending state — it is the follow-up, not a turn
// to skip over on the way back to the ambiguous ask.
check('pending: cleared by a trailing taught_masters choice turn',
  chat.pendingDisambiguation([...base, { kind: 'choice', step: 0, value: 'taught_masters' }]), null);
check('pending: cleared by a trailing undergraduate choice turn',
  chat.pendingDisambiguation([...base, { kind: 'choice', step: 0, value: 'undergraduate' }]), null);

// The follow-up ask landing afterwards still clears it.
const answered = [...base,
  { kind: 'choice', step: 0, value: 'undergraduate' },
  { kind: 'ask', message: Q_EN, reply: FEE, replyLocale: 'en', offline: true, devil: false },
];
check('pending: cleared once the fee is answered', chat.pendingDisambiguation(answered), null);

// A local re-ask (same ambiguous reply, new ask turn) keeps it live.
const localReask = [...base,
  { kind: 'freeText', text: 'hmm' },
  { kind: 'ask', message: Q_EN, reply: AMB, replyLocale: 'en', offline: true, devil: false },
];
check('pending: live after a local re-ask', chat.pendingDisambiguation(localReask) !== null, true);

// Onboarding with no ask turn at all is untouched.
check('pending: null with no ask turn', chat.pendingDisambiguation([{ kind: 'prompt', key: 'pet.q1' }]), null);
check('pending: null on empty turns', chat.pendingDisambiguation([]), null);

if (fail) { console.log(fail + ' FAILURES'); process.exit(1); }
console.log('ALL HARNESS CASES PASS');
"""


def test_r26_w4_frontend_choice_ends_pending(tmp_path):
    outdir = tmp_path / "r26w4_chat"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/chat.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r26w4_harness.js"
    harness.write_text(
        _NODE_HARNESS.replace("OUT", repr(str(outdir))),
        encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"],
           "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout


def test_r26_w4_compass_pet_level_choice_wiring():
    pet = (ROOT / "frontend/src/components/CompassPet.tsx").read_text(encoding="utf-8")
    # The pending chip branch stores the LEVEL, not the baked label.
    pending_at = pet.index("const pendingNow = pendingDisambiguation(messages);")
    step0_at = pet.index("if (step === 0) {", pending_at)
    branch = pet[pending_at:step0_at]
    assert "levelChoice: level" in branch
    assert "displayText: t(level" not in branch
    # sendAskTurn stores a level choice as a structured choice turn.
    assert "levelChoice?: Degree;" in pet
    assert "if (levelChoice) push({ kind: 'choice', step: 0, value: levelChoice });" in pet
    # The choice bubble renders through choiceLabel in the current locale.
    assert "if (turn.step === 0) return t(turn.value === 'undergraduate' ? 'pet.q1ug' : 'pet.q1tm');" in pet
    # Typed level words are still the user's verbatim words (freeText).
    assert "displayText: text, baseMessage: text, askMessage: text," in pet


def test_r26_w4_level_labels_exist_in_all_locales():
    for locale in ("en", "zh-CN", "es", "fr", "pt-BR", "ar"):
        with open(ROOT / "frontend" / "messages" / f"{locale}.json",
                  encoding="utf-8") as f:
            messages = json.load(f)
        assert messages.get("pet.q1ug"), locale
        assert messages.get("pet.q1tm"), locale
