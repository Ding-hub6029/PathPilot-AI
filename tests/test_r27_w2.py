"""Round 27 W2 — guided questionnaire replays all 8 questions after
the last answer (step-7 double-asking).

Re-test 21 (2026-11-28 00:28-00:39 CST): after the last preference
question (pressure "适中"), the guided questionnaire replayed all 8
questions from the start — the first 5 auto-filled from chat answers,
salary + pressure had to be answered again. The wizard must NOT
replay: once all 8 are known it should go to the summary/results.

Root cause, measured in the code (see DECISIONS #R27-W2): the guided
queue advanced POSITIONALLY — every answer, skip and Next button did
``setQIndex(i => Math.min(i + 1, QUESTIONS.length))`` — and resumed
positionally at ``firstUnanswered``. Answers can arrive OUT OF ORDER:
the model chat answers pressure, the pref-chat turn fails, and
``preserveFailedAnswer`` maps "适中" -> medium and drops to guided
mode with the merged profile (pressure known, salary still missing).
The queue then lands at salary (index 5) and walks 5 -> 6 -> 7,
re-asking pressure (already in the profile) and teaching (ditto when
known) before ``qIndex`` can reach 8 and ``done`` becomes true. The
first-5-auto-filled entry itself is correct — only the re-asking of
already-known later questions is the bug.

Fix pinned here:
1. ``nextMissingPrefIndex(known, from)`` (``frontend/src/lib/chat.ts``):
   the first still-unanswered question at or after ``from``, or
   ``PREF_QUESTIONS.length`` when nothing is left (the done state).
2. Every guided advance in ``PrefChat.tsx`` goes through
   ``advanceGuided(from, profile-with-just-applied-patch)`` instead of
   a bare +1: ``answerSingle``, the countries-note branch of
   ``applyLocalAnswer``, the why-answer branch of ``submitFreeText``,
   the ``confirmParse`` fallthrough, both ``skip`` branches, and the
   countries / salary Next buttons. ``firstUnanswered`` (guided entry
   + mount resume + ``enterGuidedMode``) delegates to the same helper,
   so entry and advance can never disagree about what counts as
   answered. The Back button (``i - 1``) and ``restart`` (``0``) are
   deliberately unchanged — going back to edit, and restarting, are
   the user's choice.

Covers, with no API key and no network:

- ``nextMissingPrefIndex`` via a node harness over the compiled
  ``frontend/src/lib/chat.ts`` (same pattern as
  tests/test_r26_w4_level_bubble.py): entry lands on the first
  missing question (never 0 when earlier answers exist), the re-test
  21 walk asks ONLY salary and then lands on done (8) with pressure
  never re-asked, teaching is asked exactly once when it is the only
  gap, all-8-known enters at done at once, and an empty profile still
  walks all 8 in order;
- source pins on ``PrefChat.tsx``: no positional ``+1`` advance
  remains, every advance site calls ``advanceGuided``, ``done`` is
  still ``qIndex >= QUESTIONS.length`` in guided mode, and
  ``enterGuidedMode`` still resumes at ``firstUnanswered``.

Run from the project root:
    .venv/bin/pytest tests/test_r27_w2.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"

# The re-test 21 profile when the drop to guided mode happened: the
# model chat had answered the first 5 (CH, cool, campus, Zurich,
# stay); salary was still missing; pressure ("适中") had just been
# preserved across the failed turn; teaching was already known.
FIRST5 = {
    "prefCountries": ["CH"], "prefClimate": "cool",
    "prefEnvironment": "campus", "prefCity": "Zurich",
    "prefAfterGrad": "stay",
}
RETEST21_KNOWN = {**FIRST5, "prefPressure": "medium", "prefTeaching": "hands_on"}
RETEST21_NO_TEACHING = {**FIRST5, "prefPressure": "medium"}

_NODE_HARNESS = r"""
const chat = require(OUT + '/chat.js');
const { emptyProfile } = require(OUT + '/types.js');
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + ' -> ' + g + ' want ' + w); fail++; }
  else console.log('PASS ' + name);
};
const knownOf = (patch) => chat.knownFromProfile({ ...emptyProfile, ...patch });
const idx = (patch, from) => chat.nextMissingPrefIndex(knownOf(patch), from);
const QS = chat.PREF_QUESTIONS;

// Entry: the first-5-auto-filled behaviour is preserved — the queue
// lands on the first MISSING question, never back at 0.
check('entry: empty profile starts at 0', idx({}, 0), 0);
check('entry: first 5 known lands at salary (5)', idx(FIRST5, 0), 5);
check('entry: re-test 21 profile lands at salary (5)', idx(RETEST21_KNOWN, 0), 5);
// A note-only countries answer counts as answered.
check('entry: countries note alone lands at climate (1)',
  idx({ prefCountriesNote: '环境优美' }, 0), 1);
// All 8 known: entering guided mode is done at once — the summary,
// never a replay.
check('entry: all 8 known lands on done (8)',
  idx({ ...FIRST5, prefSalary: 60000, prefPressure: 'medium', prefTeaching: 'hands_on' }, 0), 8);
check('from past the end returns 8', idx(FIRST5, 99), 8);

// The advance: after the missing question is answered, the queue
// jumps PAST every already-known later question.
check('advance: salary answered, pressure+teaching known -> done (8)',
  idx({ ...RETEST21_KNOWN, prefSalary: 60000 }, 6), 8);
check('advance: salary answered, teaching unknown -> teaching (7) once',
  idx({ ...RETEST21_NO_TEACHING, prefSalary: 60000 }, 6), 7);
check('advance: completing the 8th answer (teaching) lands on done (8)',
  idx({ ...FIRST5, prefSalary: 60000, prefPressure: 'medium' }, 8), 8);
check('advance: pressure genuinely missing is still asked (6)',
  idx({ ...FIRST5, prefSalary: 60000, prefTeaching: 'hands_on' }, 6), 6);
check('advance: pressure answered, teaching known -> done (8)',
  idx({ ...FIRST5, prefSalary: 60000, prefPressure: 'medium', prefTeaching: 'hands_on' }, 7), 8);

// Full guided walks, exactly as advanceGuided steps them:
// i = nextMissing(known, 0); answer QUESTIONS[i];
// i = nextMissing(known, i + 1); ... until i == 8 (done).
const ANSWERS = {
  countries: { prefCountries: ['CH'] }, climate: { prefClimate: 'cool' },
  environment: { prefEnvironment: 'campus' }, city: { prefCity: 'Zurich' },
  afterGrad: { prefAfterGrad: 'stay' }, salary: { prefSalary: 60000 },
  pressure: { prefPressure: 'medium' }, teaching: { prefTeaching: 'hands_on' },
};
const walk = (startPatch) => {
  const prof = { ...emptyProfile, ...startPatch };
  const asked = [];
  let i = chat.nextMissingPrefIndex(chat.knownFromProfile(prof), 0);
  while (i < QS.length) {
    asked.push(QS[i]);
    Object.assign(prof, ANSWERS[QS[i]]);
    i = chat.nextMissingPrefIndex(chat.knownFromProfile(prof), i + 1);
  }
  return { asked, end: i };
};
const w21 = walk(RETEST21_KNOWN);
check('walk re-test 21: only salary is asked', w21.asked, ['salary']);
check('walk re-test 21: ends at done (8)', w21.end, 8);
check('walk re-test 21: no question asked twice',
  new Set(w21.asked).size === w21.asked.length, true);
const wNoTeaching = walk(RETEST21_NO_TEACHING);
check('walk no-teaching: salary then teaching, nothing else',
  wNoTeaching.asked, ['salary', 'teaching']);
check('walk no-teaching: ends at done (8)', wNoTeaching.end, 8);
const wEmpty = walk({});
check('walk empty: all 8 asked in order', wEmpty.asked, QS);
check('walk empty: ends at done (8)', wEmpty.end, 8);
const wAll = walk({ ...FIRST5, prefSalary: 60000, prefPressure: 'medium', prefTeaching: 'hands_on' });
check('walk all-known: nothing is asked', wAll.asked, []);
check('walk all-known: ends at done (8)', wAll.end, 8);

if (fail) { console.log(fail + ' FAILURES'); process.exit(1); }
console.log('ALL HARNESS CASES PASS');
"""


def _compile_lib(tmp_path):
    outdir = tmp_path / "r27w2_chat"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/chat.ts", "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    return outdir


def test_r27_w2_next_missing_pref_index(tmp_path):
    """The queue arithmetic: entry lands on the first missing question,
    and every advance jumps past already-known later questions, so the
    re-test 21 walk asks ONLY salary and then reaches done (8) — the
    preserved pressure answer is never re-asked."""
    outdir = _compile_lib(tmp_path)
    harness = tmp_path / "r27w2_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FIRST5", json.dumps(FIRST5))
        .replace("RETEST21_KNOWN", json.dumps(RETEST21_KNOWN))
        .replace("RETEST21_NO_TEACHING", json.dumps(RETEST21_NO_TEACHING)),
        encoding="utf-8")
    env = {"PATH": os.environ["PATH"],
           "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout


def test_r27_w2_guided_advance_wiring():
    """Source pins: every guided advance goes through advanceGuided
    (the next-missing helper), no positional +1 advance remains, and
    the done condition + guided entry are unchanged."""
    src = (ROOT / "frontend/src/components/PrefChat.tsx").read_text(encoding="utf-8")
    chat_src = (ROOT / "frontend/src/lib/chat.ts").read_text(encoding="utf-8")
    # The helper lives in lib/chat.ts.
    assert "export function nextMissingPrefIndex(known: PrefKnown, from: number): number {" in chat_src
    # PrefChat imports it and firstUnanswered delegates to it, so
    # guided entry and advance can never disagree.
    assert "nextMissingPrefIndex," in src
    assert "return nextMissingPrefIndex(knownFromProfile(p), 0);" in src
    # The advance helper itself.
    assert "const advanceGuided = (from: number, p: Profile) => {" in src
    assert "setQIndex(nextMissingPrefIndex(knownFromProfile(p), from));" in src
    # No positional +1 advance remains anywhere in the component.
    assert "Math.min(i + 1, QUESTIONS.length)" not in src
    # All eight advance sites call advanceGuided: answerSingle, the
    # countries-note branch, the why-answer branch, confirmParse,
    # both skip branches, and the countries / salary Next buttons.
    assert src.count("advanceGuided(") == 8, src.count("advanceGuided(")
    # Done is still qIndex reaching the end in guided mode.
    assert "const done = mode === 'guided' ? qIndex >= QUESTIONS.length : modelDone;" in src
    # Guided entry still resumes at the first unanswered question.
    assert "setQIndex(firstUnanswered(base ?? profile));" in src
    # Deliberate exceptions, untouched: Back steps to the previous
    # question (edit), restart goes to 0.
    assert "setQIndex((i) => Math.max(0, i - 1))" in src
    assert "setQIndex(0);" in src
