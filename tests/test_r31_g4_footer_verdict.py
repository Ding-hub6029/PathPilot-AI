"""Round 31 G4 — pet footer vs panel offline wording mismatch.

Re-test 26 (2026-11-28 16:00-16:08, gateway down the whole run,
0 model-led turns): the pet footer settled in <=7s (Round 30 F3
worked) to "AI answers · grounded in verified sources" while the
pet message area at the same moment said "Offline — showing the
built-in catalogue…". The two lines disagreed about the AI state.

Root cause, verified in code: the two lines read DIFFERENT
sources. The footer reads the CURRENT shared verdict —
``t(aiVerdictLineKey(aiVerdict))`` in CompassPet.tsx, live ->
``pet.aiLive`` ("AI answers · grounded in verified sources").
The panel's offline lead line (``renderTurn``'s ``offlineLine``)
took its WORDING from the current verdict (``timedOut``) but its
PRESENCE from the stored per-turn flag ``turn.offline`` — history,
not state. So a turn answered offline kept its offline lead after
a later probe flipped the verdict live, and the panel kept
claiming offline while the footer claimed AI answers.

How the verdict flips live with the gateway down (both paths
reproduced in the harness below): the 1-token /ai/status probe
returns fresh "available" while real model calls fail — the
flapping gateway documented since Round 21 — and (a) a probe
started AFTER the turn verdict is not blocked by the Round 22
guard (it only drops probes that were in flight when the turn
verdict landed), so the weaker probe verdict overwrites the
stronger real-turn verdict; (b) a panel re-open / footer retry /
devil enable resets the shared verdict to unknown and re-probes,
and the flaky probe says available again. Either way the footer
goes live while the stored offline turn stays in the panel.

Fix (frontend-only, CompassPet.tsx ``renderTurn``; the Round 29
E5 single-verdict design is untouched — lib/aiVerdict.ts is not
changed, and no locale key is added or changed):
- the offline lead line now shows only while the CURRENT shared
  verdict is offline (``offline`` from ``useAiVerdict()``), in
  every branch that emits it — ask template reply, ask rank
  lookup, ask country directory, ask bare line, suggest catalogue
  programme, suggest with no programme;
- the stored ``turn.offline`` flag still selects the CONTENT
  (template reply lines, rank lines, directory lines, catalogue
  programme) — history is preserved, only the state claim moved;
- a live model reply never gains the lead (``turn.offline`` is
  false for it); the devil boundary is untouched — it labels the
  reply's provenance, pinned by Round 18 W3
  (``devilOffline: turn.devil && turn.offline``).
Corner, accepted: an offline turn with NO other content renders
an empty bubble once the verdict goes live, rather than a stale
offline claim — that needs a failed turn with no rank or country
match, then a live probe.

Covers, with no API key and no network:
- node harness over the REAL lib/aiVerdict.ts (compiled with
  tsc, stubbed fetch, same pattern as
  tests/test_r30_f3_footer_settle.py): the exact re-test 26
  sequence — probe live, failed turn -> offline, later probe
  (no reset) -> live again, reset + re-probe -> live again —
  with the footer key at each step, plus a timed-out turn
  (offline+timedOut -> pet.offlineTimeout, the same key the
  panel lead uses);
- source pins: every offline-lead emission in renderTurn is
  gated on the current verdict, the stored flag still selects
  content, the footer still renders the shared line key, the
  devil boundary is unchanged, the old ungated expressions are
  gone, and the locale key count is still 984 (981 at Round 30
  + 3 Round 31 G2 sample.confirm keys — this fix adds none).

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r31_g4_footer_verdict.py
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "frontend"

_NODE_HARNESS = r"""
// ---- stubbed fetch: scripted /ai/status responses, in call order ----
// The flaky 1-token probe: fresh "available" while real model calls
// fail (the gateway flap documented since Round 21).
const scripted = [];
let fetchCalls = 0;
function okJson(body) {
  return { ok: true, status: 200, json: async () => body };
}
global.fetch = (path, init) => {
  fetchCalls++;
  const next = scripted.shift();
  if (next === undefined) return Promise.reject(new Error('unexpected fetch: ' + path));
  if (next instanceof Error) return Promise.reject(next);
  return Promise.resolve(next);
};

const aiVerdict = require(__OUT__ + '/aiVerdict.js');
const { aiVerdictLineKey, beginAiTurn, endAiTurn, getAiVerdict,
  noteAiTurnVerdict, probeAiVerdict, resetAiVerdict } = aiVerdict;

const fs = require('fs');
const pet = fs.readFileSync(__PET__, 'utf8');
const en = JSON.parse(fs.readFileSync(__MSG__ + '/en.json', 'utf8'));

let fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('FAIL ' + name + ': got ' + JSON.stringify(got) + ', want ' + JSON.stringify(want)); }
  else console.log('ok ' + name);
}
function checkTrue(name, cond) { check(name, !!cond, true); }
// The footer line key for the current shared verdict — what the
// footer renders (t(aiVerdictLineKey(aiVerdict))).
const footerKey = () => aiVerdictLineKey(getAiVerdict());

(async () => {
  // --- 0. The exact re-test 26 strings ---
  check('en footer live string is the reported one',
    en['pet.aiLive'], 'AI answers · grounded in verified sources');
  checkTrue('en panel offline string is the reported one',
    en['pet.offline'].startsWith('Offline — showing the built-in catalogue'));

  // --- 1. Footer key mapping (the shared verdict, both directions) ---
  check('live -> pet.aiLive', aiVerdictLineKey({ verdict: 'live', timedOut: false }), 'pet.aiLive');
  check('offline -> pet.offline', aiVerdictLineKey({ verdict: 'offline', timedOut: false }), 'pet.offline');
  check('offline+timeout -> pet.offlineTimeout', aiVerdictLineKey({ verdict: 'offline', timedOut: true }), 'pet.offlineTimeout');
  check('checking -> pet.aiChecking', aiVerdictLineKey({ verdict: 'checking', timedOut: false }), 'pet.aiChecking');

  // --- 2. The re-test 26 sequence, against the real store ---
  // (a) Panel opens: the flaky 1-token probe returns fresh
  // "available" while real turns fail — footer settles to AI
  // answers in ~one probe (Round 30 F3).
  scripted.push(okJson({ ai_status: 'available', probed: true }));
  check('open probe -> live', await probeAiVerdict({ budgetMs: 1500 }), { verdict: 'live', timedOut: false });
  check('footer claims AI answers after the open probe', footerKey(), 'pet.aiLive');
  // (b) The user asks: the turn fails fast to the verified
  // template (breaker open) — the turn verdict is offline, and
  // the turn is stored offline:true, so the panel shows the
  // offline lead. Footer and panel agree here: both offline.
  beginAiTurn();
  noteAiTurnVerdict(false, { timedOut: false });
  endAiTurn();
  check('failed turn -> offline', getAiVerdict(), { verdict: 'offline', timedOut: false });
  check('footer claims offline after the failed turn', footerKey(), 'pet.offline');
  // (c) A later probe, started AFTER the turn verdict: the Round
  // 22 guard does not block it (it only drops probes that were in
  // flight when the turn verdict landed), so the weaker probe
  // verdict overwrites the stronger real-turn verdict and the
  // footer flips back to AI answers — while the stored offline
  // turn is still in the panel. This is the disagreement state:
  // pre-fix the panel kept its offline lead here.
  scripted.push(okJson({ ai_status: 'available', probed: true }));
  check('later probe overwrites the turn verdict -> live', await probeAiVerdict({ budgetMs: 1500 }), { verdict: 'live', timedOut: false });
  check('footer claims AI answers again after the later probe', footerKey(), 'pet.aiLive');
  // (d) The re-open path: reset + re-probe, flaky probe says
  // available again — footer live once more, panel turn unchanged.
  resetAiVerdict();
  check('reset -> checking', getAiVerdict(), { verdict: 'checking', timedOut: false });
  scripted.push(okJson({ ai_status: 'available', probed: true }));
  check('re-open re-probe -> live', await probeAiVerdict({ budgetMs: 1500 }), { verdict: 'live', timedOut: false });
  check('footer claims AI answers after the re-open probe', footerKey(), 'pet.aiLive');
  check('the disagreement sequence used exactly three probe fetches', fetchCalls, 3);
  resetAiVerdict();

  // --- 3. Timed-out turn: footer and panel lead use the same key ---
  beginAiTurn();
  noteAiTurnVerdict(false, { timedOut: true });
  endAiTurn();
  check('timed-out turn -> offline+timedOut', getAiVerdict(), { verdict: 'offline', timedOut: true });
  check('footer says timed out, not bare offline', footerKey(), 'pet.offlineTimeout');
  resetAiVerdict();

  // --- 4. Source pins: the panel lead follows the shared verdict ---
  const renderAt = pet.indexOf('const renderTurn');
  const renderEnd = pet.indexOf('const askSuggest', renderAt);
  const renderFn = pet.slice(renderAt, renderEnd);
  checkTrue('renderTurn block found', renderAt !== -1 && renderEnd !== -1);
  // The lead's WORDING still comes from the current verdict's
  // timedOut (same key the footer uses for the same state).
  checkTrue('panel lead wording is the shared timedOut key',
    renderFn.includes("const offlineLine = timedOut ? t('pet.offlineTimeout') : t('pet.offline');"));
  // Every emission of the lead is gated on the CURRENT verdict
  // (`offline`), never on the stored flag alone:
  checkTrue('ask template reply: lead needs turn offline AND verdict offline',
    renderFn.includes('turn.offline && offline && !turn.devil ? [offlineLine, ...turn.reply.lines]'));
  checkTrue('ask rank lookup: lead only while the verdict is offline',
    renderFn.includes('lines: offline ? [offlineLine, ...rank.lines] : [...rank.lines],'));
  checkTrue('ask country directory: lead only while the verdict is offline',
    renderFn.includes('lines: offline ? [offlineLine, ...dir.lines] : [...dir.lines],'));
  checkTrue('ask bare line: no lead once the verdict is live',
    renderFn.includes('return { lines: offline ? [offlineLine] : [] };'));
  checkTrue('suggest catalogue programme: lead only while the verdict is offline',
    renderFn.includes('...(offline ? [offlineLine] : []),'));
  checkTrue('suggest with no programme: no lead once the verdict is live',
    renderFn.includes('if (!turn.offlineProgramId) return { lines: offline ? [offlineLine] : [] };'));
  // The old ungated expressions are gone:
  checkTrue('no ungated ask-reply lead left',
    !renderFn.includes('turn.offline && !turn.devil ? [offlineLine, ...turn.reply.lines]'));
  checkTrue('no ungated rank lead left',
    !renderFn.includes('lines: [offlineLine, ...rank.lines],'));
  checkTrue('no ungated directory lead left',
    !renderFn.includes('lines: [offlineLine, ...dir.lines],'));
  checkTrue('no ungated bare lead left',
    !renderFn.includes('return { lines: [offlineLine] };'));
  checkTrue('no ungated suggest lead left',
    !renderFn.includes('if (!turn.offlineProgramId) return { lines: [offlineLine] };'));
  // History is preserved: the stored flag still selects WHAT the
  // turn shows (template / rank / directory / catalogue) — only
  // the state claim moved to the shared verdict.
  checkTrue('stored flag still selects the offline content (suggest)',
    renderFn.includes('if (turn.offline) {'));
  checkTrue('stored flag still selects the offline content (ask)',
    renderFn.includes('if (turn.offline) {') && (renderFn.match(/if \(turn\.offline\) \{/g) || []).length >= 2);
  checkTrue('ask still renders the stored template reply lines',
    renderFn.includes('turn.reply.lines'));
  // The footer is untouched: it still renders the shared line key.
  checkTrue('footer still renders the shared line key',
    pet.includes('t(aiVerdictLineKey(aiVerdict))'));
  // The devil boundary is untouched: it labels the reply's
  // provenance (Round 18 W3), not the current state.
  checkTrue('devil boundary still keyed on the turn (provenance)',
    pet.includes('devilOffline: turn.devil && turn.offline'));
  // No new locale keys: the fix reuses pet.offline /
  // pet.offlineTimeout, so the count stays 984 (981 at Round 30
  // + 3 Round 31 G2 sample.confirm keys — this fix adds none).
  check('locale key count is still 984 (no new keys)', Object.keys(en).length, 984);

  console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error('HARNESS ERROR', e); process.exit(1); });
"""


def test_r31_g4_footer_verdict(tmp_path):
    """Round 31 G4: the pet footer and the pet panel can never
    disagree about the AI state — the panel's offline lead follows
    the same shared verdict as the footer."""
    outdir = tmp_path / "r31_g4"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/aiVerdict.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r31_g4_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("__OUT__", repr(str(outdir)))
        .replace("__PET__", repr(str(FE / "src/components/CompassPet.tsx")))
        .replace("__MSG__", repr(str(FE / "messages"))),
        encoding="utf-8")
    env = {"PATH": os.environ["PATH"],
           "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=180, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
    assert "HARNESS OK" in node.stdout
