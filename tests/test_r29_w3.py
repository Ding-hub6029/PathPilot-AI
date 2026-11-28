"""Round 29 W3 — E5 (one shared AI verdict) + E6 (wizard clear-data
resurrects the pref chat), re-test task 23, 2026-11-28.

E5 — contradictory AI status signals. During one run the wizard
said "AI 暂时无法连接" (PrefChat's own per-turn `aiOffline` flag,
from a failed pref-chat turn) while the /results banner said "Live
backend connected" (backend health only — `useBackendStatus`,
which says nothing about the model) and the pet footer said "AI
answers" (CompassPet's own `aiLive` state, from its own fresh
probe + its own turn verdicts). Three surfaces, three independent
verdicts, three different answers about the same model at the
same moment.

Fix: one shared verdict store (frontend/src/lib/aiVerdict.ts) —
one cached verdict, one probe (FRESH ?fresh=1 through
freshAiVerdict), turn verdicts as the strongest evidence, the
Round 22 probe guard kept. The pet footer, the wizard's
guided-mode banner and the results banner all read
`useAiVerdict()` and render the same line key
(`aiVerdictLineKey`); the results "Live backend connected" line
renders only when the shared AI verdict is live (backend
reachable is not AI available); while the verdict is unknown
every surface says checking.

E6 — clear-data mid-wizard restores the old conversation.
Clearing from the wizard page mid-flow, then returning to the
preferences step, restored the previous incomplete conversation
(round 2's Switzerland / beautiful-environment / cool records).
Clearing from the results page reset properly. Root cause, in
PrefChat.tsx: the component never subscribed to dataClearNonce,
so its in-memory conversation survived the clear — and worse,
its persist effect re-saved the stale turns under the EMPTY
profile's fingerprint. The fingerprint guard only protects a
RESTORED snapshot (restoredFingerprintRef non-null); on a fresh
run the conversation was built in-memory with no snapshot, so
the guard passed and the stale blob was written. The wizard's
step reset unmounts PrefChat in the same flush, so the re-render
that would overwrite the blob with the reset state never
happens — the stale write is the last write, and the remount
resurrects it (fingerprint matches the empty profile). From the
results page nothing re-saves, which is why that clear worked.

Fix (PrefChat.tsx only): subscribe to dataClearNonce and reset
the full live set on a bump (the restart() set plus in-flight /
salary state), drop pp-prefchat — and give the persist effect
its own clear ref, so on a nonce bump it deletes the key and
writes nothing, whichever effect runs first in the commit.

Covers, with no API key and no network:
- node harness over the REAL lib/aiVerdict.ts (compiled with
  tsc, stubbed fetch): line-key mapping, initial checking,
  fresh probe live/offline, unconfirmed-bounded-to-offline,
  failed-probe offline, probe dedupe, min-checking hold,
  turn-verdict-beats-probe (both arms), reset invalidating an
  in-flight probe, timedOut passthrough;
- the E6 persist race replayed as a state simulation (fixed
  rule resurrects nothing; the old rule without the guard
  resurrects the stale turns — the simulation discriminates);
- source pins: CompassPet holds no local verdict state and
  publishes every turn verdict to the store; PrefChat's guided
  banner reads the shared verdict and its clear effect resets
  the full set + guards the persist write; the results banner
  gates "Live backend connected" on the shared AI verdict;
- locale keys: results.aiOffline + wizard.chatPrefAiBack exist
  in all 6 locales (984 keys total = 981 at Round 30 + Round 31
  G2's three sample.confirm* keys), non-empty, same set in all 6.

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r29_w3.py
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "frontend"

_NODE_HARNESS = r"""
// ---- stubbed fetch: scripted /ai/status responses, in call order ----
const scripted = [];
let fetchCalls = 0;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function okJson(body) {
  return { ok: true, status: 200, json: async () => body };
}
global.fetch = async (path, init) => {
  fetchCalls++;
  const next = scripted.shift();
  if (next === undefined) throw new Error('unexpected fetch: ' + path);
  if (next instanceof Error) throw next;
  if (typeof next === 'function') return next();
  return next;
};

const aiVerdict = require(__OUT__ + '/aiVerdict.js');
const { aiVerdictLineKey, beginAiTurn, endAiTurn, getAiVerdict,
  noteAiTurnVerdict, probeAiVerdict, resetAiVerdict } = aiVerdict;

const fs = require('fs');
const path = require('path');
const pet = fs.readFileSync(__PET__, 'utf8');
const pref = fs.readFileSync(__PREF__, 'utf8');
const results = fs.readFileSync(__RESULTS__, 'utf8');
const en = JSON.parse(fs.readFileSync(path.join(__MSG__, 'en.json'), 'utf8'));

let fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('FAIL ' + name + ': got ' + JSON.stringify(got) + ', want ' + JSON.stringify(want)); }
  else console.log('ok ' + name);
}
function checkTrue(name, cond) { check(name, !!cond, true); }

(async () => {
  // --- 1. Line-key mapping over the shared state ---
  check('live -> pet.aiLive', aiVerdictLineKey({ verdict: 'live', timedOut: false }), 'pet.aiLive');
  check('checking -> pet.aiChecking', aiVerdictLineKey({ verdict: 'checking', timedOut: false }), 'pet.aiChecking');
  check('offline -> pet.offline', aiVerdictLineKey({ verdict: 'offline', timedOut: false }), 'pet.offline');
  check('offline+timeout -> pet.offlineTimeout', aiVerdictLineKey({ verdict: 'offline', timedOut: true }), 'pet.offlineTimeout');

  // --- 2. Initial verdict is unknown, never affirmative ---
  check('initial verdict is checking', getAiVerdict(), { verdict: 'checking', timedOut: false });

  // --- 3. Fresh probe: available + probed -> live ---
  scripted.push(okJson({ ai_status: 'available', probed: true }));
  check('fresh available+probed -> live', await probeAiVerdict({ budgetMs: 1500 }), { verdict: 'live', timedOut: false });
  resetAiVerdict();

  // --- 4. Fresh probe: unavailable -> offline (safe direction) ---
  scripted.push(okJson({ ai_status: 'unavailable', probed: true }));
  check('unavailable -> offline', await probeAiVerdict({ budgetMs: 1500 }), { verdict: 'offline', timedOut: false });
  resetAiVerdict();

  // --- 5. Available-but-unprobed: bounded re-probes, then offline ---
  scripted.push(okJson({ ai_status: 'available', probed: false }));
  scripted.push(okJson({ ai_status: 'available', probed: false }));
  scripted.push(okJson({ ai_status: 'available', probed: false }));
  const t5 = Date.now();
  check('available-unprobed x3 -> offline', await probeAiVerdict({ budgetMs: 1500 }), { verdict: 'offline', timedOut: false });
  check('unconfirmed retries took ~4s (2 x 2s sleeps)', Date.now() - t5 >= 3800, true);
  check('unconfirmed path used 3 fetches', fetchCalls, 1 + 1 + 3);
  resetAiVerdict();

  // --- 6. Failed probe: HTTP 500 throws at once -> offline, not a timeout ---
  scripted.push({ ok: false, status: 500, json: async () => ({}) });
  check('HTTP 500 probe -> offline', await probeAiVerdict({ budgetMs: 1500 }), { verdict: 'offline', timedOut: false });
  resetAiVerdict();

  // --- 7. Failed probe: network error, small budget -> offline, no retry fired ---
  scripted.push(new Error('connection refused'));
  check('network-error probe -> offline', await probeAiVerdict({ budgetMs: 1500 }), { verdict: 'offline', timedOut: false });
  resetAiVerdict();

  // --- 8. Dedupe: concurrent callers share one in-flight probe ---
  const before = fetchCalls;
  scripted.push(async () => { await sleep(300); return okJson({ ai_status: 'available', probed: true }); });
  const [a, b] = await Promise.all([probeAiVerdict({ budgetMs: 1500 }), probeAiVerdict({ budgetMs: 1500 })]);
  check('concurrent probes resolve the same live verdict', a, b);
  check('concurrent probes made one fetch', fetchCalls - before, 1);
  resetAiVerdict();

  // --- 9. minChecking: the checking state is held visible ---
  scripted.push(okJson({ ai_status: 'available', probed: true }));
  const t9 = Date.now();
  check('minChecking probe -> live', await probeAiVerdict({ minChecking: true, budgetMs: 1500 }), { verdict: 'live', timedOut: false });
  check('minChecking held >= 1s', Date.now() - t9 >= 1000, true);
  resetAiVerdict();

  // --- 10. Turn verdict beats a probe (turn verdict landed mid-probe) ---
  scripted.push(async () => { await sleep(300); return okJson({ ai_status: 'available', probed: true }); });
  const p10 = probeAiVerdict({ budgetMs: 1500 });
  beginAiTurn();
  noteAiTurnVerdict(false, { timedOut: false });
  check('probe dropped after a turn verdict', await p10, { verdict: 'offline', timedOut: false });
  check('verdict stays offline (turn verdict wins)', getAiVerdict(), { verdict: 'offline', timedOut: false });
  resetAiVerdict();

  // --- 11. Turn verdict beats a probe (turn still in flight) ---
  scripted.push(async () => { await sleep(200); return okJson({ ai_status: 'available', probed: true }); });
  const p11 = probeAiVerdict({ budgetMs: 1500 });
  beginAiTurn();
  check('probe dropped while a turn is in flight', await p11, { verdict: 'checking', timedOut: false });
  // Round 30, F3: endAiTurn() re-arms a probe when the verdict is
  // still unknown (the dropped probe left the footer on checking
  // with nothing scheduled to re-probe) — script its response so
  // the re-arm consumes this one, not a later section's. The
  // resetAiVerdict() below invalidates it before it can land.
  scripted.push(okJson({ ai_status: 'unavailable', probed: true }));
  endAiTurn();
  check('verdict stays checking after the dropped probe', getAiVerdict(), { verdict: 'checking', timedOut: false });
  resetAiVerdict();

  // --- 12. A probe started AFTER a turn verdict applies (fresh evidence) ---
  noteAiTurnVerdict(true);
  check('model turn -> live', getAiVerdict(), { verdict: 'live', timedOut: false });
  scripted.push(okJson({ ai_status: 'unavailable', probed: true }));
  check('later probe saying unavailable applies', await probeAiVerdict({ budgetMs: 1500 }), { verdict: 'offline', timedOut: false });
  resetAiVerdict();

  // --- 13. Reset invalidates an in-flight probe (pre-clear evidence) ---
  scripted.push(async () => { await sleep(300); return okJson({ ai_status: 'available', probed: true }); });
  const p13 = probeAiVerdict({ budgetMs: 1500 });
  resetAiVerdict();
  check('reset verdict is checking', getAiVerdict(), { verdict: 'checking', timedOut: false });
  check('in-flight probe resolves to checking after reset', await p13, { verdict: 'checking', timedOut: false });
  check('verdict still checking after the stale probe lands', getAiVerdict(), { verdict: 'checking', timedOut: false });

  // --- 14. Turn verdict timedOut passthrough ---
  noteAiTurnVerdict(false, { timedOut: true });
  check('timed-out turn -> offline+timedOut', getAiVerdict(), { verdict: 'offline', timedOut: true });
  check('timed-out turn line key', aiVerdictLineKey(getAiVerdict()), 'pet.offlineTimeout');
  resetAiVerdict();

  // --- 15. E6: the clear-data persist race, replayed ---
  // Model of the FIXED effects (PrefChat.tsx): the persist effect
  // owns persistClearRef; on a nonce bump it deletes the key and
  // writes nothing. The reset effect owns clearNonceRef and resets
  // the live state. localStorage is a plain object here.
  function simulatePersistRace(useGuard, resetFirst) {
    const store = {}; // localStorage
    let nonce = 0, persistRef = 0, clearRef = 0;
    let turns = []; // in-memory conversation
    let profile = {}; // {} = empty profile
    const persistEffect = () => {
      if (useGuard && nonce !== persistRef) { persistRef = nonce; delete store['pp-prefchat']; return; }
      // fingerprint guard: only a RESTORED snapshot blocks the write
      const restoredFp = null; // fresh run: no snapshot was restored
      const fpEmpty = Object.keys(profile).length === 0;
      if (fpEmpty && restoredFp && restoredFp !== 'empty') return;
      store['pp-prefchat'] = JSON.stringify({ turns });
    };
    // The reset effect exists ONLY in the fixed code: pre-fix
    // PrefChat never subscribed to dataClearNonce, so the old-rule
    // branch must not run it at all (its delete is what wrongly
    // cleared the stale blob in the first version of this sim).
    const resetEffect = () => {
      if (nonce === clearRef) return;
      clearRef = nonce; turns = []; delete store['pp-prefchat'];
    };
    // Fresh wizard run: the user answers countries + climate.
    turns = [{ q: 'countries', a: 'Switzerland, beautiful environment' }, { q: 'climate', a: 'cool' }];
    profile = { prefCountries: ['CH'] };
    persistEffect(); // blob saved under the live profile
    check('E6 setup: blob saved during the run', !!store['pp-prefchat'], true);
    // Clear-data from the wizard page: store wipes the keys, profile empties.
    nonce = 1; profile = {}; delete store['pp-profile'];
    // The store's clearData also removes pp-prefchat:
    delete store['pp-prefchat'];
    // In the clear commit both effects may run, in either order;
    // the guard makes the fixed rule order-free.
    if (useGuard && resetFirst) resetEffect();
    persistEffect(); // runs in the clear commit, stale closure state
    if (useGuard && !resetFirst) resetEffect();
    // Wizard step reset unmounts PrefChat in the same flush.
    const remountSnapshot = store['pp-prefchat'] ? JSON.parse(store['pp-prefchat']) : null;
    return remountSnapshot;
  }
  const fixedA = simulatePersistRace(true, false);
  check('E6 fixed (persist first): remount finds no snapshot (fresh chat)', fixedA, null);
  const fixedB = simulatePersistRace(true, true);
  check('E6 fixed (reset first): remount finds no snapshot (fresh chat)', fixedB, null);
  const old = simulatePersistRace(false, false);
  check('E6 old rule: remount resurrects the stale turns', old && old.turns.length, 2);

  // --- 16. Source pins: CompassPet reads the shared verdict ---
  checkTrue('pet reads useAiVerdict()', pet.includes('useAiVerdict()'));
  checkTrue('pet renders the shared line key', pet.includes('aiVerdictLineKey(aiVerdict)'));
  checkTrue('pet publishes turn verdicts', pet.includes('noteAiTurnVerdict('));
  checkTrue('pet has two live-turn verdict sites', (pet.match(/noteAiTurnVerdict\(true\)/g) || []).length === 2);
  checkTrue('pet resets via the shared store', pet.includes('resetAiVerdict()'));
  checkTrue('pet holds no local verdict state',
    !pet.includes('setAiLive(') && !pet.includes('setOffline(') && !pet.includes('setTimedOut(') && !pet.includes('turnInFlightRef'));
  checkTrue('pet has no local probe left', !pet.includes('probeAiStatus(') && !pet.includes('fetchJsonPatient'));

  // --- 17. Source pins: PrefChat publishes + resets + guards ---
  checkTrue('pref reads useAiVerdict()', pref.includes('useAiVerdict()'));
  checkTrue('pref publishes turn verdicts', pref.includes('noteAiTurnVerdict('));
  checkTrue('pref begins/ends turns in the store', pref.includes('beginAiTurn()') && pref.includes('endAiTurn()'));
  const bannerAt = pref.indexOf('wizard.chatPrefOffline');
  const bannerBlock = pref.slice(Math.max(0, bannerAt - 900), bannerAt + 100);
  checkTrue('guided banner reads the shared verdict (live branch)',
    bannerBlock.includes("aiVerdict.verdict === 'live'") && bannerBlock.includes('wizard.chatPrefAiBack'));
  checkTrue('guided banner says checking while unknown',
    bannerBlock.includes("aiVerdict.verdict === 'checking'") && bannerBlock.includes('pet.aiChecking'));
  checkTrue('pref subscribes to the clear nonce', pref.includes('dataClearNonce'));
  const ceStart = pref.indexOf('Round 29, E6 — clear-data must clear the wizard chat too');
  const ceEnd = pref.indexOf('}, [dataClearNonce]);', ceStart);
  const clearEffect = pref.slice(ceStart, ceEnd);
  checkTrue('pref clear-effect block found', ceStart !== -1 && ceEnd !== -1);
  for (const stmt of ['setTurns([])', 'setModelTurns([])', 'setQIndex(0)', 'setSkipped([])',
      'setServerNext(undefined)', 'setPendingExtract(null)', 'setConfirmedNotes([])',
      'setFailedText(null)', 'setAwaitingReason(null)', 'setVerbatim({})',
      'setPendingParse(null)', "localStorage.removeItem(PREF_CHAT_KEY)"]) {
    checkTrue('pref clear effect resets: ' + stmt, clearEffect.includes(stmt));
  }
  checkTrue('persist effect owns its own clear ref', pref.includes('persistClearRef'));
  checkTrue('persist effect skips the write on a nonce bump',
    pref.includes('if (dataClearNonce !== persistClearRef.current)'));

  // --- 18. Source pins: results banner gates on the shared AI verdict ---
  checkTrue('results reads useAiVerdict()', results.includes('useAiVerdict()'));
  checkTrue('results Live line gated on the shared AI verdict',
    results.includes("backendStatus === 'live' && aiVerdict.verdict === 'live'") && results.includes("t('r9pages.backendLive')"));
  checkTrue('results checking line while the AI verdict is unknown',
    results.includes("backendStatus === 'live' && aiVerdict.verdict === 'checking'") && results.includes("t('pet.aiChecking')"));
  checkTrue('results AI-down line while the AI verdict is offline',
    results.includes("backendStatus === 'live' && aiVerdict.verdict === 'offline'") && results.includes("t('results.aiOffline')"));
  checkTrue('results no longer claims Live from backend health alone',
    !results.includes("{backendStatus === 'live' && <p"));

  // --- 19. Locale keys: the two new keys in all 6 locales ---
  const locales = ['en', 'zh-CN', 'es', 'fr', 'pt-BR', 'ar'];
  const msgs = {};
  for (const loc of locales) msgs[loc] = JSON.parse(fs.readFileSync(path.join(__MSG__, loc + '.json'), 'utf8'));
  const base = new Set(Object.keys(msgs.en));
  check('locale key count is 984 (981 + R31 G2 sample.confirm x3)', base.size, 984);
  for (const loc of locales) {
    check(loc + ' key set matches en', JSON.stringify(Object.keys(msgs[loc]).sort()), JSON.stringify([...base].sort()));
    check(loc + ' results.aiOffline present', typeof msgs[loc]['results.aiOffline'], 'string');
    check(loc + ' wizard.chatPrefAiBack present', typeof msgs[loc]['wizard.chatPrefAiBack'], 'string');
    check(loc + ' results.aiOffline non-empty', msgs[loc]['results.aiOffline'].trim().length > 0, true);
    check(loc + ' wizard.chatPrefAiBack non-empty', msgs[loc]['wizard.chatPrefAiBack'].trim().length > 0, true);
  }
  check('en aiOffline line names the AI as down', /AI unavailable/.test(en['results.aiOffline']), true);
  check('en aiBack line offers the retry', /retry the AI chat/i.test(en['wizard.chatPrefAiBack']), true);
  check('new keys differ from the old offline banner', en['results.aiOffline'] !== en['wizard.chatPrefOffline'], true);

  console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error('HARNESS ERROR', e); process.exit(1); });
"""


def test_r29_w3_shared_ai_verdict_and_wizard_clear(tmp_path):
    """Round 29 W3: one shared AI verdict (E5) + wizard clear-data
    resets the pref chat instead of resurrecting it (E6)."""
    outdir = tmp_path / "r29_w3"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/aiVerdict.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r29_w3_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("__OUT__", repr(str(outdir)))
        .replace("__PET__", repr(str(FE / "src/components/CompassPet.tsx")))
        .replace("__PREF__", repr(str(FE / "src/components/PrefChat.tsx")))
        .replace("__RESULTS__", repr(str(FE / "src/app/results/page.tsx")))
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
