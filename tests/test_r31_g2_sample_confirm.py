"""Round 31 G2 — "Try a sample profile" SILENTLY overwrites the
user's data. Re-test 26: one click loaded the synthetic A-level
sample profile and wiped the user's filled profile AND all 8
preference-chat answers (back to 0/8), with no confirmation. The
tester had to re-enter everything. The button appears on the
homepage hero AND on every black programme card (both route through
one trySample), plus the wizard's "Try a sample profile" button.

Root cause, verified before the fix: both call sites called
setProfile(sample) unconditionally — homepage page.tsx trySample
(``setProfile(which === 'ug' ? sampleUndergrad : sampleMasters);
router.push('/results')``) and wizard page.tsx loadSample
(``setProfile({ ...s }); setStep(7)``) — and setProfile replaces
the WHOLE profile (store.tsx ``setProfileState(p)``). The profile
is one object holding both the wizard fields and the 8 pref-chat
answers (prefClimate / prefCountries / prefEnvironment / prefCity /
prefAfterGrad / prefSalary / prefPressure / prefTeaching, written
by PrefChat via updateProfile), so the wholesale replace emptied
all of them at once. The sample profiles themselves carry no pref
answers (they spread emptyProfile), so the answers did not even
survive as sample data. Nothing in either call site checked whether
the current profile held user data first.

Fix, frontend only (no data or programme facts changed):
- New pure helper frontend/src/lib/sampleConfirm.ts ``hasProfileData``:
  true when any user-fillable field differs from emptyProfile, false
  for an empty profile AND for a profile still exactly equal to one
  of the two samples (a sample just loaded holds no user data, so
  loading another sample over it stays one-click; any edit after
  loading breaks the exact match and counts as user data). ``sample``
  (the synthetic marker) and ``targetProgramIds`` (a derived list
  the wizard finish step writes from the evaluated matches, never
  typed in) never count on their own.
- New frontend/src/components/SampleConfirmDialog.tsx: a small
  alertdialog (title + body + Replace / Close). Cancel reuses the
  existing common.close key; only three keys are new:
  sample.confirmTitle / sample.confirmBody / sample.confirmReplace
  (984 keys in all 6 locales at the time, up from 981;
  994 after Restyle 2 behaviour's ten keys).
- Both call sites gate on hasProfileData: with data filled in the
  click opens the dialog and only Confirm loads the sample (the
  homepage keeps the pending UG/PG choice until Confirm, so the
  dialog loads exactly the card tapped); with nothing filled the
  sample still loads with one click, no dialog.

Covers, with no API key and no network:
- node harness over the REAL lib/sampleConfirm.ts (compiled with
  tsc): empty -> no confirm; filled wizard + all 8 pref answers ->
  confirm; pref-answers-only -> confirm; exact sample UG / PG ->
  no confirm; sample + one edited field -> confirm; only
  targetProgramIds set -> no confirm; sample flag alone on an
  otherwise empty profile -> no confirm;
- source pins: both call sites import hasProfileData and gate on
  it, both render SampleConfirmDialog, Confirm loads the pending
  sample, Cancel clears it without loading; the homepage has
  exactly two trySample call sites (hero + programme cards); the
  dialog renders the three new keys, reuses common.close, and
  returns null when closed;
- locale keys: 994 in all 6 locales (984 at the time + Restyle 2
  behaviour's ten keys), same set, new keys non-empty,
  the en body names the preference answers and says it cannot be
  undone.

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r31_g2_sample_confirm.py
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "frontend"

_NODE_HARNESS = r"""
const { emptyProfile, sampleUndergrad, sampleMasters } = require(__OUT__ + '/types.js');
const { hasProfileData } = require(__OUT__ + '/sampleConfirm.js');

const fs = require('fs');
const path = require('path');
const home = fs.readFileSync(__HOME__, 'utf8');
const wizard = fs.readFileSync(__WIZARD__, 'utf8');
const dialog = fs.readFileSync(__DIALOG__, 'utf8');
const en = JSON.parse(fs.readFileSync(path.join(__MSG__, 'en.json'), 'utf8'));

let fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('FAIL ' + name + ': got ' + JSON.stringify(got) + ', want ' + JSON.stringify(want)); }
  else console.log('ok ' + name);
}
function checkTrue(name, cond) { check(name, !!cond, true); }

// --- 1. The defect's shape: a filled profile + all 8 pref answers ---
const filled = { ...emptyProfile,
  track: 'undergraduate', curriculum: 'uk_alevel', field: 'computing',
  alevels: 'A*A*A', mathsGrade: 'A*', ieltsOverall: 7.0, budget: 50000,
  prefClimate: 'cool', prefCountries: ['CH'], prefEnvironment: 'campus',
  prefCity: 'Zurich', prefAfterGrad: 'return_home', prefSalary: 80000,
  prefSalaryCurrency: 'CHF', prefPressure: 'low', prefTeaching: 'seminar' };
check('filled wizard + 8 pref answers -> confirm', hasProfileData(filled), true);

// --- 2. Empty state stays one-click ---
check('empty profile -> no confirm', hasProfileData(emptyProfile), false);
check('empty profile object literal -> no confirm', hasProfileData({ ...emptyProfile }), false);

// --- 3. Preference answers alone trigger the dialog ---
const prefsOnly = { ...emptyProfile, prefClimate: 'cool', prefCountries: ['CH'] };
check('pref answers only -> confirm', hasProfileData(prefsOnly), true);
const onePref = { ...emptyProfile, prefTeaching: 'seminar' };
check('a single pref answer -> confirm', hasProfileData(onePref), true);

// --- 4. A freshly loaded sample holds no user data ---
check('exact sample UG -> no confirm', hasProfileData({ ...sampleUndergrad }), false);
check('exact sample PG -> no confirm', hasProfileData({ ...sampleMasters }), false);

// --- 5. Any edit after loading a sample counts as user data ---
const editedSample = { ...sampleUndergrad, prefClimate: 'cool' };
check('sample + one edited pref answer -> confirm', hasProfileData(editedSample), true);
const editedSample2 = { ...sampleMasters, budget: 60000 };
check('sample + one edited wizard field -> confirm', hasProfileData(editedSample2), true);

// --- 6. Derived / marker fields never count on their own ---
const idsOnly = { ...emptyProfile, targetProgramIds: ['ucl-cs-bsc-2026'] };
check('only targetProgramIds set -> no confirm', hasProfileData(idsOnly), false);
const flagOnly = { ...emptyProfile, sample: true };
check('sample flag alone on an empty profile -> no confirm', hasProfileData(flagOnly), false);

// --- 7. Source pins: homepage gates both sample buttons on the check ---
checkTrue('home imports hasProfileData', home.includes("hasProfileData } from '../lib/sampleConfirm'"));
checkTrue('home imports the dialog', home.includes("SampleConfirmDialog } from '../components/SampleConfirmDialog'"));
checkTrue('home trySample gates on hasProfileData', home.includes('if (hasProfileData(profile)) { setPendingSample(which); return; }'));
checkTrue('home has exactly two trySample call sites (hero + cards)', (home.match(/onClick=\{\(\) => trySample\(/g) || []).length === 2);
checkTrue('home renders the dialog', home.includes('<SampleConfirmDialog'));
checkTrue('home Confirm loads the pending sample', home.includes('if (which) loadSample(which);'));
checkTrue('home Cancel clears the pending choice', home.includes('onCancel={() => setPendingSample(null)}'));
checkTrue('home loadSample still sets the profile and goes to results',
  home.includes("setProfile(which === 'ug' ? sampleUndergrad : sampleMasters);") && home.includes("router.push('/results');"));

// --- 8. Source pins: wizard gates its sample button the same way ---
checkTrue('wizard imports hasProfileData', wizard.includes("hasProfileData } from '../../lib/sampleConfirm'"));
checkTrue('wizard imports the dialog', wizard.includes("SampleConfirmDialog } from '../../components/SampleConfirmDialog'"));
checkTrue('wizard loadSample gates on hasProfileData', wizard.includes('if (hasProfileData(profile)) { setPendingSample(true); return; }'));
checkTrue('wizard Confirm applies the sample', wizard.includes('onConfirm={() => { setPendingSample(false); applySample(); }}'));
checkTrue('wizard Cancel clears without applying', wizard.includes('onCancel={() => setPendingSample(false)}'));
checkTrue('wizard applySample still replaces the profile and jumps to step 7',
  wizard.includes('setProfile({ ...s });') && wizard.includes('setStep(7);'));
checkTrue('wizard renders the dialog', wizard.includes('<SampleConfirmDialog'));

// --- 9. Source pins: the dialog itself ---
checkTrue('dialog is an alertdialog', dialog.includes('role="alertdialog"'));
checkTrue('dialog returns null when closed', dialog.includes('if (!open) return null;'));
checkTrue('dialog renders the title key', dialog.includes("t('sample.confirmTitle')"));
checkTrue('dialog renders the body key', dialog.includes("t('sample.confirmBody')"));
checkTrue('dialog renders the replace key', dialog.includes("t('sample.confirmReplace')"));
checkTrue('dialog Cancel reuses common.close (no new cancel key)', dialog.includes("t('common.close')"));
checkTrue('dialog overlay click cancels', dialog.includes('onClick={onCancel}'));
checkTrue('dialog card click does not cancel', dialog.includes('onClick={(e) => e.stopPropagation()}'));

// --- 10. Locale keys: three new keys, 994 in all 6 (984 at the time
// + Restyle 2 behaviour's ten keys), same set ---
const locales = ['en', 'zh-CN', 'es', 'fr', 'pt-BR', 'ar'];
const msgs = {};
for (const loc of locales) msgs[loc] = JSON.parse(fs.readFileSync(path.join(__MSG__, loc + '.json'), 'utf8'));
const base = new Set(Object.keys(msgs.en));
check('locale key count is 994 (981 + R31 G2 sample.confirm x3 + Restyle 2 behaviour x10)', base.size, 994);
for (const loc of locales) {
  check(loc + ' key set matches en', JSON.stringify(Object.keys(msgs[loc]).sort()), JSON.stringify([...base].sort()));
  for (const key of ['sample.confirmTitle', 'sample.confirmBody', 'sample.confirmReplace']) {
    check(loc + ' ' + key + ' present', typeof msgs[loc][key], 'string');
    check(loc + ' ' + key + ' non-empty', msgs[loc][key].trim().length > 0, true);
  }
}
check('en title names the sample profile', /sample profile/i.test(en['sample.confirmTitle']), true);
check('en body names the preference answers', /preference answers/i.test(en['sample.confirmBody']), true);
check('en body says it cannot be undone', /cannot be undone/i.test(en['sample.confirmBody']), true);
check('en replace button names the sample', /sample/i.test(en['sample.confirmReplace']), true);

console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
process.exit(fail ? 1 : 0);
"""


def test_r31_g2_sample_overwrite_confirms_when_data_filled(tmp_path):
    """Round 31 G2: loading a sample over a filled profile asks
    first; loading it over an empty (or freshly sampled) profile
    stays one click."""
    outdir = tmp_path / "r31_g2"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/sampleConfirm.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r31_g2_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("__OUT__", repr(str(outdir)))
        .replace("__HOME__", repr(str(FE / "src/app/page.tsx")))
        .replace("__WIZARD__", repr(str(FE / "src/app/wizard/page.tsx")))
        .replace("__DIALOG__", repr(str(FE / "src/components/SampleConfirmDialog.tsx")))
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
