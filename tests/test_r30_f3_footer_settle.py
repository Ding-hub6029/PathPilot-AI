"""Round 30 F3 — pet footer sits on "Checking the AI connection…"
for ~30–60 s after opening/switching, before settling to offline,
even when the backend was already warm (health returned ok
immediately). Re-test 24 item d + re-test 25 item d, 2026-11-28.

Root cause — three cooperating defects, all in the shared verdict
path (frontend/src/lib/aiVerdict.ts + the pet's open effects in
frontend/src/components/CompassPet.tsx):

1. Two live probes per open. `useAiVerdict`'s auto-probe effect is
   registered before CompassPet's open effect, so by the time the
   open effect ran it had already started the open's probe — and
   the open effect then called `resetAiVerdict()` (which nulls
   inFlight WITHOUT aborting the first probe's fetch) and started
   a second one. Both ran server-side, serialised on the backend's
   /ai/status lock at ~7 s each on a hanging gateway (measured
   locally against a stub gateway in the Round 16 W3 flapping
   state — list endpoint answers, chat hangs: one live probe
   7.13 s, a concurrent second probe 7.12 s waiting on the lock,
   breaker-open probe 0.003 s, warm read 0.002 s; live Render:
   health 0.69 s, breaker-open fresh probe 0.55–0.98 s), so the
   footer paid two probe durations instead of one.
2. A slow probe attempt was retried. `probeAiVerdict` called
   `fetchJsonPatient` with the defaults — 25 s per-attempt timeout,
   retry on a slow abort, 90 s budget — so a probe delayed past
   25 s by the lock queue was aborted and silently re-issued,
   re-queueing behind the still-running probes and stacking
   25 s aborts. The `useAiVerdict` auto-probe passes no `onRetry`,
   so no waking line showed: the footer kept showing "Checking…"
   through the retries. A status read is not a turn: a slow abort
   is now final (`retryOnTimeout: false`, the fetchJsonChat rule
   from Round 15 F2) and settles offline with timedOut. A fast
   failure (backend waking) still retries inside the budget.
3. A dropped probe verdict stranded the footer on checking. The
   Round 22 turn guard drops a probe verdict while a turn is in
   flight — which is every open with a saved profile, because
   greet() auto-starts a turn before the open effect's probe
   resolves — and `probeAiVerdict` then resolved to the unchanged
   'checking' state with no probe in flight and nothing scheduled
   to re-probe (`useAiVerdict` only fires on a verdict change).
   The footer depended entirely on the turn's verdict, and a turn
   that ended WITHOUT noting one (superseded by a restart) left
   it stranded until the next explicit probe. `endAiTurn()` now
   re-arms a fresh probe when the verdict is still unknown.

Fix (frontend-only, E5 single-verdict design preserved):
- lib/aiVerdict.ts: probe fetch `retryOnTimeout: false` (+ an
  `attemptTimeoutMs` passthrough, same pattern as `budgetMs`);
  a slow abort settles offline with `timedOut` (AbortError);
  `endAiTurn()` re-arms a probe when the verdict is still
  'checking' and none is in flight.
- CompassPet.tsx: the open, /results-restore and devil-enable
  effects reset the shared verdict only when it is SETTLED —
  every open already resets before those effects when there is
  a stale verdict to clear (toggle pre-paint, restore before
  setOpen), and on a fresh mount the verdict cannot be settled
  yet — so the effect's `runProbe` joins the probe
  `useAiVerdict` already started instead of orphaning it and
  starting a second live probe. The clear-data reset stays
  unconditional (pre-clear evidence must be invalidated) and
  toggle(true) still resets pre-paint.

Covers, with no API key and no network:
- node harness over the REAL lib/aiVerdict.ts (compiled with
  tsc, stubbed fetch, same pattern as tests/test_r29_w3.py):
  a hanging probe aborts once and settles offline+timedOut
  (exactly one fetch, ~1 s — pre-fix it retried to ~4 s and
  two fetches); fast failures still retry (the backend-wake
  path survives the fix); a dropped probe verdict + a turn
  ending without a verdict re-arms exactly one probe that
  settles the footer; no re-arm when the turn already noted a
  verdict;
- source pins: the three CompassPet effects reset only a
  settled verdict and join the in-flight probe, toggle still
  resets pre-paint, clear-data still resets unconditionally,
  the probe passes retryOnTimeout:false, endAiTurn re-arms,
  useAiVerdict still auto-probes while checking.

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r30_f3_footer_settle.py
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "frontend"

_NODE_HARNESS = r"""
// ---- stubbed fetch: scripted /ai/status responses, in call order ----
// 'hang' never resolves; it rejects only when fetchJsonPatient's
// per-attempt timer aborts its signal — the hanging-gateway probe.
const scripted = [];
let fetchCalls = 0;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function okJson(body) {
  return { ok: true, status: 200, json: async () => body };
}
function abortErr() {
  try { return new DOMException('Aborted', 'AbortError'); }
  catch (e) { const err = new Error('Aborted'); err.name = 'AbortError'; return err; }
}
global.fetch = (path, init) => {
  fetchCalls++;
  const next = scripted.shift();
  if (next === undefined) return Promise.reject(new Error('unexpected fetch: ' + path));
  if (next === 'hang') {
    return new Promise((resolve, reject) => {
      const sig = init && init.signal;
      if (!sig) return; // never settles
      if (sig.aborted) { reject(abortErr()); return; }
      sig.addEventListener('abort', () => reject(abortErr()), { once: true });
    });
  }
  if (next instanceof Error) return Promise.reject(next);
  if (typeof next === 'function') return next();
  return Promise.resolve(next);
};

const aiVerdict = require(__OUT__ + '/aiVerdict.js');
const { beginAiTurn, endAiTurn, getAiVerdict,
  noteAiTurnVerdict, probeAiVerdict, resetAiVerdict } = aiVerdict;

const fs = require('fs');
const pet = fs.readFileSync(__PET__, 'utf8');
const verdictSrc = fs.readFileSync(__VERDICT__, 'utf8');

let fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('FAIL ' + name + ': got ' + JSON.stringify(got) + ', want ' + JSON.stringify(want)); }
  else console.log('ok ' + name);
}
function checkTrue(name, cond) { check(name, !!cond, true); }

(async () => {
  // --- 1. A slow probe attempt is final: one fetch, offline+timedOut ---
  // The fetch hangs past the per-attempt timeout, so fetchJsonPatient
  // aborts it (attemptTimeoutMs floors at 1000 ms in lib/api.ts).
  // Pre-fix the abort was retried (retryOnTimeout defaults true):
  // ~4 s and two fetches inside a 5 s budget. Post-fix it settles
  // after the one attempt, and the footer says "timed out".
  scripted.push('hang');
  const before1 = fetchCalls;
  const t1 = Date.now();
  check('hanging probe -> offline+timedOut', await probeAiVerdict({ budgetMs: 5000, attemptTimeoutMs: 100 }), { verdict: 'offline', timedOut: true });
  const elapsed1 = Date.now() - t1;
  check('hanging probe made exactly one fetch (no slow-abort retry)', fetchCalls - before1, 1);
  check('hanging probe settled in ~1 s, not a retry chain', elapsed1 < 2500, true);
  resetAiVerdict();

  // --- 2. Fast failures still retry (the backend-wake path survives) ---
  // Two fast network errors, then an unavailable verdict: the probe
  // must still retry inside the budget (2 s pause per retry) and
  // settle on the third attempt's answer, not give up after one.
  scripted.push(new Error('connection refused'));
  scripted.push(new Error('connection refused'));
  scripted.push(okJson({ ai_status: 'unavailable', probed: true }));
  const before2 = fetchCalls;
  const t2 = Date.now();
  check('fast failures retry to the third attempt', await probeAiVerdict({ budgetMs: 6000 }), { verdict: 'offline', timedOut: false });
  check('fast-failure probe made three fetches', fetchCalls - before2, 3);
  check('fast-failure retries took ~4 s (2 x 2 s pauses)', Date.now() - t2 >= 3800, true);
  resetAiVerdict();

  // --- 3. Dropped probe + turn ends without a verdict -> re-arm ---
  // The Round 22 guard drops the probe verdict while a turn is in
  // flight; the turn is then superseded (restart) so it notes no
  // verdict. Pre-fix the footer sat on checking with no probe in
  // flight and nothing scheduled. Post-fix endAiTurn() re-arms one
  // fresh probe, which settles the footer.
  scripted.push(async () => { await sleep(200); return okJson({ ai_status: 'available', probed: true }); });
  const p3 = probeAiVerdict({ budgetMs: 1500 });
  beginAiTurn();
  check('probe dropped while a turn is in flight', await p3, { verdict: 'checking', timedOut: false });
  scripted.push(okJson({ ai_status: 'unavailable', probed: true }));
  const before3 = fetchCalls;
  endAiTurn();
  check('verdict still checking right after the turn ends', getAiVerdict(), { verdict: 'checking', timedOut: false });
  await sleep(100);
  check('turn end without a verdict re-armed exactly one probe', fetchCalls - before3, 1);
  check('re-armed probe settles the footer offline', getAiVerdict(), { verdict: 'offline', timedOut: false });
  resetAiVerdict();

  // --- 4. No re-arm when the turn already noted a verdict ---
  // The normal path: the turn's verdict lands, then its finally
  // calls endAiTurn(). The store is settled, so no probe is started.
  scripted.push(async () => { await sleep(100); return okJson({ ai_status: 'available', probed: true }); });
  const p4 = probeAiVerdict({ budgetMs: 1500 });
  beginAiTurn();
  noteAiTurnVerdict(false, { timedOut: false });
  check('probe dropped after a turn verdict', await p4, { verdict: 'offline', timedOut: false });
  const before4 = fetchCalls;
  endAiTurn();
  await sleep(100);
  check('no re-arm when the turn already settled the verdict', fetchCalls - before4, 0);
  check('verdict stays offline', getAiVerdict(), { verdict: 'offline', timedOut: false });
  resetAiVerdict();

  // --- 5. Source pins: one probe per open (no orphaning reset) ---
  // The open effect: find its block (first `if (!open) return;`)
  // up to its `}, [open]);` close.
  const openAt = pet.indexOf('if (!open) return;');
  const openEnd = pet.indexOf('}, [open]);', openAt);
  const openEffect = pet.slice(openAt, openEnd);
  checkTrue('open-effect block found', openAt !== -1 && openEnd !== -1);
  checkTrue('open effect resets only a settled verdict',
    openEffect.includes("if (getAiVerdict().verdict !== 'checking') resetAiVerdict();"));
  checkTrue('open effect has no bare reset (no orphaned probe)',
    !/^\s*resetAiVerdict\(\);$/m.test(openEffect));
  checkTrue('open effect still re-probes (joins the in-flight probe)',
    openEffect.includes('runProbe({ minChecking: true })'));
  // The devil-enable effect: same guard, same join.
  const devilAt = pet.indexOf('devilWasOnRef');
  const devilEnd = pet.indexOf('}, [open, devilMode]);', devilAt);
  const devilEffect = pet.slice(devilAt, devilEnd);
  checkTrue('devil-effect block found', devilAt !== -1 && devilEnd !== -1);
  checkTrue('devil effect resets only a settled verdict',
    devilEffect.includes("if (getAiVerdict().verdict !== 'checking') resetAiVerdict();"));
  checkTrue('devil effect has no bare reset (no orphaned probe)',
    !/^\s*resetAiVerdict\(\);$/m.test(devilEffect));
  // The /results auto-restore effect: same guard before setOpen.
  const restoreAt = pet.indexOf('Round 25 W3: reset the shared verdict BEFORE the panel paints');
  const restoreEnd = pet.indexOf('}, [pathname, canDevil, open]);', restoreAt);
  const restoreEffect = pet.slice(restoreAt, restoreEnd);
  checkTrue('restore-effect block found', restoreAt !== -1 && restoreEnd !== -1);
  checkTrue('restore effect resets only a settled verdict',
    restoreEffect.includes("if (getAiVerdict().verdict !== 'checking') resetAiVerdict();"));
  checkTrue('restore effect has no bare reset (no orphaned probe)',
    !/^\s*resetAiVerdict\(\);$/m.test(restoreEffect));
  // The guarantees the guard must NOT weaken:
  const toggleAt = pet.indexOf('const toggle = (next: boolean)');
  const toggleEffect = pet.slice(toggleAt, pet.indexOf('setOpen(next);', toggleAt));
  checkTrue('toggle still resets pre-paint on open', toggleEffect.includes('resetAiVerdict();'));
  const clearAt = pet.indexOf('Round 23 W2 — clear-data must clear the pet');
  const clearEnd = pet.indexOf('}, [dataClearNonce]);', clearAt);
  const clearEffect = pet.slice(clearAt, clearEnd);
  checkTrue('clear-data block found', clearAt !== -1 && clearEnd !== -1);
  checkTrue('clear-data still resets unconditionally (pre-clear evidence is invalid)',
    /^\s*resetAiVerdict\(\);$/m.test(clearEffect));
  // The shared store: slow-abort final, re-arm on turn end, auto-probe kept.
  checkTrue('probe passes retryOnTimeout:false to the patient fetch',
    verdictSrc.includes('retryOnTimeout: false'));
  checkTrue('slow abort settles timedOut',
    verdictSrc.includes("?.name === 'AbortError'"));
  checkTrue('endAiTurn re-arms a probe while the verdict is unknown',
    verdictSrc.includes("if (cached.verdict === 'checking' && !inFlight) void probeAiVerdict();"));
  checkTrue('useAiVerdict still auto-probes while checking',
    verdictSrc.includes("if (state.verdict === 'checking') void probeAiVerdict();"));
  checkTrue('single-verdict design kept: one shared probe, turn verdicts strongest',
    verdictSrc.includes('probeAiVerdict') && verdictSrc.includes('noteAiTurnVerdict'));

  console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error('HARNESS ERROR', e); process.exit(1); });
"""


def test_r30_f3_footer_settle(tmp_path):
    """Round 30 F3: the pet footer settles promptly instead of
    showing "Checking the AI connection…" for 30–60 s."""
    outdir = tmp_path / "r30_f3"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/aiVerdict.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r30_f3_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("__OUT__", repr(str(outdir)))
        .replace("__PET__", repr(str(FE / "src/components/CompassPet.tsx")))
        .replace("__VERDICT__", repr(str(FE / "src/lib/aiVerdict.ts"))),
        encoding="utf-8")
    env = {"PATH": os.environ["PATH"],
           "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=180, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
    assert "HARNESS OK" in node.stdout
