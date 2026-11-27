"""Round 25 W3 — footer shows the affirmative "AI answers" line after
clear-data, before any fresh verdict (re-test task 19, 2026-11-27
17:36-17:45 CST).

Tester sequence (en UI): clear data while the pet panel is open,
before the first question the footer briefly showed
"AI answers · grounded in verified sources" (previously the neutral
"Checking the AI connection…"); after the first question it turned
offline and stayed.

Root cause, in CompassPet.tsx: CompassPet is mounted once in the
root layout and never remounts, and aiLive is plain useState(null).
The Round 23 W2 clear-data effect reset the conversation
(messages / answers / step / devilMode) and re-greeted, but never
touched the footer verdict (aiLive / offline) and never re-probed —
and the open effect, which resets aiLive to null and re-probes,
never re-runs on a clear because `open` does not change. So a
pre-clear `aiLive === true` (an earlier open's fresh probe, or a
model turn reply, from when the gateway had flapped up) survived
the clear and kept the footer claiming AI answers with no fresh
post-clear verdict behind it, until the first post-clear turn's
template verdict overwrote it with offline. The same first-paint
hole existed on the /results auto-restore path, which calls
setOpen(true) directly and bypassed the Round 21 W1 pre-paint
reset in toggle(true).

Fix (frontend-only, CompassPet.tsx): the clear-data effect now
resets the verdict to unknown (aiLive null, offline false, waking
false — the neutral checking line) and re-probes fresh with
minChecking when the panel is open, exactly like an open; when
closed the reset alone suffices, the next open re-probes anyway.
The /results auto-restore effect resets the verdict before
setOpen(true), mirroring toggle(true). No affirmative line can
appear without a fresh verdict: the probe verdict still goes
through freshAiVerdict + probeVerdictApplies (Rounds 21-22).

These tests replay the exact tester sequence — en and zh-CN,
fresh profile and after clear-data — over the REAL lib/aiStatus.ts
decision logic (compiled with tsc, same pattern as
tests/test_r15_w3.py) plus source pins on the two fixed paths.
The source pins FAIL on the pre-fix code (verified: the /tmp
reproduction harness exited 1 before the fix, 0 after).

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r25_w3_footer_clear_data.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "frontend"

_NODE_HARNESS = r"""
const fs = require('fs');
const path = require('path');
const aiStatus = require(OUT + '/aiStatus.js');
const { footerAiLineKey, freshAiVerdict, probeVerdictApplies } = aiStatus;

const src = fs.readFileSync(SRC, 'utf8');
const en = JSON.parse(fs.readFileSync(path.join(MSG, 'en.json'), 'utf8'));
const zh = JSON.parse(fs.readFileSync(path.join(MSG, 'zh-CN.json'), 'utf8'));

let fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('FAIL ' + name + ': got ' + JSON.stringify(got) + ', want ' + JSON.stringify(want)); }
  else console.log('ok ' + name);
}

// --- 1. The real footer decision: null verdict is checking, never AI.
check('null verdict -> checking key',
  footerAiLineKey({ offline: false, timedOut: false, aiLive: null }), 'pet.aiChecking');
check('true verdict -> aiLive key',
  footerAiLineKey({ offline: false, timedOut: false, aiLive: true }), 'pet.aiLive');
check('false verdict -> offline key',
  footerAiLineKey({ offline: false, timedOut: false, aiLive: false }), 'pet.offline');
check('offline flag beats a true verdict',
  footerAiLineKey({ offline: true, timedOut: false, aiLive: true }), 'pet.offline');

// --- 2. Fresh-verdict discipline (Rounds 21-22, unchanged by this fix).
check('fresh available+probed -> true', freshAiVerdict({ ai_status: 'available', probed: true }), true);
check('available-but-unprobed -> null (never live)', freshAiVerdict({ ai_status: 'available', probed: false }), null);
check('available, probed missing -> null', freshAiVerdict({ ai_status: 'available' }), null);
check('unavailable -> false', freshAiVerdict({ ai_status: 'unavailable', probed: true }), false);
check('probe applies with no turn in flight and no newer turn verdict',
  probeVerdictApplies({ turnInFlight: false, turnVerdictGenAtProbeStart: 3, turnVerdictGenNow: 3 }), true);
check('probe dropped while a turn is in flight',
  probeVerdictApplies({ turnInFlight: true, turnVerdictGenAtProbeStart: 3, turnVerdictGenNow: 3 }), false);
check('probe dropped after a turn verdict landed',
  probeVerdictApplies({ turnInFlight: false, turnVerdictGenAtProbeStart: 3, turnVerdictGenNow: 4 }), false);

// --- 3. Locale strings: the checking line is neutral in both locales,
// and distinct from the affirmative line.
for (const [name, m] of [['en', en], ['zh-CN', zh]]) {
  check(name + ' checking key exists', typeof m['pet.aiChecking'], 'string');
  check(name + ' aiLive key exists', typeof m['pet.aiLive'], 'string');
  check(name + ' checking != aiLive', m['pet.aiChecking'] !== m['pet.aiLive'], true);
  check(name + ' checking line is neutral (no AI-answers claim)',
    /Checking|确认/.test(m['pet.aiChecking']) && !/AI answers|AI 回答/.test(m['pet.aiChecking']), true);
}
check('en checking text', en['pet.aiChecking'], 'Checking the AI connection…');
check('en aiLive text', en['pet.aiLive'], 'AI answers · grounded in verified sources');
check('zh checking text', zh['pet.aiChecking'], '正在确认 AI 是否可用…');
check('zh aiLive text', zh['pet.aiLive'], 'AI 回答 · 只用已核实资料');

// --- 4. Source pins: the clear-data effect must reset the verdict
// and re-probe (fails on the pre-fix source, which reset only the
// conversation and left aiLive/offline untouched).
const cStart = src.indexOf('Round 23 W2');
const cEnd = src.indexOf('}, [dataClearNonce]);', cStart);
const clearEffect = src.slice(cStart, cEnd);
check('clear effect block found', cStart !== -1 && cEnd !== -1, true);
check('clear effect resets aiLive to null', /setAiLive\s*\(\s*null\s*\)/.test(clearEffect), true);
check('clear effect resets offline to false', /setOffline\s*\(\s*false\s*\)/.test(clearEffect), true);
check('clear effect clears waking', /setWaking\s*\(\s*false\s*\)/.test(clearEffect), true);
check('clear effect re-probes fresh while open',
  /if\s*\(\s*openRef\.current\s*\)\s*\{[^}]*probeAiStatus\s*\(\s*\{\s*minChecking:\s*true\s*\}\s*\)/.test(clearEffect), true);

// --- 5. Source pins: the /results auto-restore path must reset the
// verdict BEFORE setOpen(true) (it bypasses toggle's Round 21 reset).
const rStart = src.indexOf("pathname !== '/results'");
const rEnd = src.indexOf('}, [pathname, canDevil, open]);', rStart);
const restoreEffect = src.slice(rStart, rEnd);
check('auto-restore effect block found', rStart !== -1 && rEnd !== -1, true);
const openAt = restoreEffect.indexOf('setOpen(true)');
check('auto-restore resets aiLive before setOpen',
  restoreEffect.indexOf('setAiLive(null)') !== -1 && restoreEffect.indexOf('setAiLive(null)') < openAt, true);
check('auto-restore resets offline before setOpen',
  restoreEffect.indexOf('setOffline(false)') !== -1 && restoreEffect.indexOf('setOffline(false)') < openAt, true);

// --- 6. Initial state: the verdict starts unknown, never affirmative.
check('aiLive initial state is null',
  /const \[aiLive, setAiLive\] = useState<boolean \| null>\(null\)/.test(src), true);

// --- 7. The tester sequence, replayed through the real footer logic.
// State mirrors CompassPet's verdict state; transitions mirror the
// fixed effects (clear -> reset to null + fresh re-probe; a turn
// verdict sets aiLive directly; a fresh probe verdict applies only
// via freshAiVerdict).
function footer(state, locale) {
  const key = footerAiLineKey({ offline: state.offline, timedOut: false, aiLive: state.aiLive });
  return (locale === 'en' ? en : zh)[key];
}
let s = { aiLive: null, offline: false };           // fresh profile
check('fresh profile, en -> checking', footer(s, 'en'), 'Checking the AI connection…');
check('fresh profile, zh -> checking', footer(s, 'zh-CN'), '正在确认 AI 是否可用…');
s = { aiLive: true, offline: false };               // earlier open: fresh probe said available
check('earlier open, fresh available -> aiLive', footer(s, 'en'), 'AI answers · grounded in verified sources');
// Clear-data (fixed effect): verdict reset, re-probe in flight.
s = { aiLive: null, offline: false };
check('after clear-data, en -> checking (never aiLive)', footer(s, 'en'), 'Checking the AI connection…');
check('after clear-data, zh -> checking (never aiLive)', footer(s, 'zh-CN'), '正在确认 AI 是否可用…');
// First post-clear question lands template-only -> offline.
s = { aiLive: false, offline: true };
check('first question template-only, en -> offline', footer(s, 'en').startsWith('Offline'), true);
check('first question template-only, zh -> offline', footer(s, 'zh-CN').startsWith('离线'), true);
// A later fresh probe that says available may claim AI again.
const v = freshAiVerdict({ ai_status: 'available', probed: true });
s = { aiLive: v, offline: !v };
check('fresh available verdict after clear -> aiLive', footer(s, 'en'), 'AI answers · grounded in verified sources');

console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
process.exit(fail ? 1 : 0);
"""


def test_r25_w3_footer_after_clear_data(tmp_path):
    """Round 25 W3: after clear-data the footer shows the neutral
    checking line (en + zh-CN), never the affirmative AI line, until
    a fresh verdict lands."""
    outdir = tmp_path / "r25_w3"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/aiStatus.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r25_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("SRC", repr(str(FE / "src/components/CompassPet.tsx")))
        .replace("MSG", repr(str(FE / "messages"))),
        encoding="utf-8")
    env = {"PATH": os.environ["PATH"],
           "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
    assert "HARNESS OK" in node.stdout
