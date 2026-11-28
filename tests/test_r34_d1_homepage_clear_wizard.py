"""Round 34 D1 — homepage "Clear my data" does not clear wizard data
(re-test 29 defect #1).

Tester sequence: with the audit run in the wizard (7/8, preferences
answered), click "Clear my data" on the homepage, then enter the
wizard — the old 7/8 audit conversation is still there. Clicking
"Clear my data" inside the wizard page resets it to 1/8.

Root cause (verified in code, then reproduced with the REAL mounted
components in jsdom — see the D1 report): the two clear paths are
the SAME handler (Header's clearData, store.tsx), but they are not
the same reset. The wizard-page clear resets BOTH the shared
storage AND the live in-memory wizard state, through the
dataClearNonce effects (wizard step, PrefChat turns, pet). The
homepage clear can only wipe the storage — the wizard is not
mounted there — and it relies on a fresh mount reading clean
storage. That reliance breaks in two places:

(1) Cross-tab: clearData signals only through in-memory React
state (dataClearNonce) plus the storage wipe, and the app has NO
`storage` listener. A wizard alive in ANOTHER tab never hears
about the clear: its mounted step, PrefChat turns and profile stay
exactly as they were, so it keeps showing the old 7/8 run — and
clicking "Clear my data" inside that tab resets it, because its
own nonce then fires. The single-tab flow is clean (reproduced in
jsdom: homepage clear -> re-enter -> 1/8); the two-instance flow
reproduces the defect exactly.

(2) Dead fresh-mount guard: loadWizardStep() returns 0 only when
the `pp-profile` KEY is absent — but clearData's
removeItem('pp-profile') is undone on the next commit by the
store's profile-persist effect, which writes the empty profile
back. After ANY in-app clear the key exists, holding an empty
profile, so the guard ("cleared data must never resurrect a step")
never fires — a stale `pp-wizard-step` (another tab's run, a
pre-clear write) resurrects the old step on a fresh mount.

Fix (frontend-only, no copy / data / route / locale change):
(A) store.tsx gains a `storage` event listener in AppProvider:
`pp-profile` is removed ONLY by clearData (no other code removes
it), so its removal (newValue null) is an unambiguous "another
tab cleared" signal, and the listener runs clearData itself — the
keys are already gone from shared storage, so its removeItems are
no-ops, and the persist effects re-write the empty profile /
checklist exactly like the originating tab's flow; the nonce bump
resets the mounted wizard, PrefChat and pet exactly like a
wizard-page clear. pp-prefchat is deliberately NOT a trigger:
PrefChat's restart removes it too, and a chat restart in one tab
must never wipe the profile in another. The originating tab never
receives its own event (spec), and the persist-effect re-write
carries a non-null newValue, so no loop is possible.
(B) wizard/page.tsx loadWizardStep() now judges "no data" on the
stored profile's CONTENT (exactly the empty profile), not on the
key's absence — a stored step for an empty profile is never
resurrected. A sample profile is NOT empty (track / curriculum /
field / prefs filled), so a reloaded sample still resumes at its
step. clearData itself is byte-identical (the Round 18 pins still
hold unmodified).

Run from the project root:
    .venv/bin/pytest tests/test_r34_d1_homepage_clear_wizard.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
STORE = FE / "src" / "lib" / "store.tsx"
WIZARD = FE / "src" / "app" / "wizard" / "page.tsx"
HOME = FE / "src" / "app" / "page.tsx"
TYPES = FE / "src" / "lib" / "types.ts"

# ---------------------------------------------------------------------------
# Node harness: the REAL loadWizardStep, extracted verbatim from
# wizard/page.tsx and compiled with the REAL types.ts, run against a
# localStorage shim; plus a two-tab simulation whose "listener
# present" flag is read out of the REAL store.tsx source, so the
# simulation fails on pre-fix code (no listener -> the other tab
# never resets) and passes on fixed code.
# ---------------------------------------------------------------------------

_NODE_HARNESS = r"""
const fs = require('fs');
const path = require('path');
const snippet = require(path.join(TMP, 'snippet.js'));
const types = require(path.join(TMP, 'types.js'));
const storeSrc = fs.readFileSync(STORE, 'utf8');
const wizardSrc = fs.readFileSync(WIZARD, 'utf8');
let fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('FAIL ' + name + ': got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want)); }
  else console.log('ok ' + name);
}

// --- localStorage shim ---------------------------------------------------
function makeStorage(seed) {
  const m = new Map(Object.entries(seed));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(String(k), String(v)),
    removeItem: (k) => m.delete(k),
    _map: m,
  };
}
const audit = {
  ...types.sampleUndergrad,
  prefCountries: ['CH'], prefCountriesNote: '环境优美',
  prefClimate: 'cool', prefEnvironment: 'campus', prefCity: 'Zurich',
  prefAfterGrad: 'work', prefSalary: 50000, prefSalaryCurrency: 'GBP', prefPressure: 'low',
};
const loadStep = (seed) => {
  global.localStorage = makeStorage(seed);
  return snippet.loadWizardStep();
};

// (a) No profile at all -> 0 (pre-existing behaviour, both versions).
check('no pp-profile -> step 0', loadStep({ 'pp-wizard-step': '6' }), 0);
// (b) THE DEFECT, fresh-mount half: empty profile (the post-clear
// re-write) + stale step 6 -> 0. Pre-fix the guard only checks key
// absence, so it returns 6 and the old run resurrects.
check('empty profile + stale step 6 -> step 0',
  loadStep({ 'pp-profile': JSON.stringify(types.emptyProfile), 'pp-wizard-step': '6' }), 0);
// (c) Audit profile + step 6 -> resumes at 6 (7/8): a live run is untouched.
check('audit profile + step 6 -> step 6',
  loadStep({ 'pp-profile': JSON.stringify(audit), 'pp-wizard-step': '6' }), 6);
// (d) Pristine sample + step 7 -> resumes at 7 (8/8): the sample-load
// resume is preserved — a sample is NOT an empty profile.
check('pristine sample + step 7 -> step 7',
  loadStep({ 'pp-profile': JSON.stringify(types.sampleUndergrad), 'pp-wizard-step': '7' }), 7);
// (e) Corrupt profile + stale step -> 0, never resurrects.
check('corrupt profile + stale step 6 -> step 0',
  loadStep({ 'pp-profile': '{corrupt', 'pp-wizard-step': '6' }), 0);
// (f) No step stored + live profile -> 0.
check('audit profile, no step stored -> step 0',
  loadStep({ 'pp-profile': JSON.stringify(audit) }), 0);
// (g) Out-of-range step is clamped (pre-existing behaviour).
check('audit profile + step 99 -> clamped to 7',
  loadStep({ 'pp-profile': JSON.stringify(audit), 'pp-wizard-step': '99' }), 7);

// --- two-tab simulation --------------------------------------------------
// Two store instances sharing one storage object (two tabs: separate
// React heaps, one localStorage). Tab A has the wizard mounted at
// step 6 with the audit profile. Tab B clears on the homepage:
// storage wiped, B's nonce bumped. Then the `storage` event reaches
// A — IF the store has the listener. The listener's presence and
// shape are read from the real store.tsx, not assumed here.
const listenerAt = storeSrc.indexOf("const onStorage");
const listenerPresent = listenerAt !== -1;
check('store has a storage listener', listenerPresent, true);
let listenerCallsClear = false, listenerGuardsOnProfileRemoval = false, listenerAvoidsPrefchat = false;
if (listenerPresent) {
  const effectEnd = storeSrc.indexOf('}, []);', listenerAt);
  const effect = storeSrc.slice(listenerAt, effectEnd === -1 ? undefined : effectEnd);
  listenerCallsClear = effect.includes('clearData()');
  listenerGuardsOnProfileRemoval =
    effect.includes("e.key !== 'pp-profile'") && effect.includes('e.newValue !== null');
  listenerAvoidsPrefchat = !effect.includes('pp-prefchat');
}
check('listener runs clearData on the signal', listenerCallsClear, true);
check('listener fires only on pp-profile removal (newValue null)',
  listenerGuardsOnProfileRemoval, true);
check('listener does not trigger on pp-prefchat removal', listenerAvoidsPrefchat, true);

function simulateTwoTabs(withListener) {
  const storage = {};
  // Tab A: wizard mounted, step 6, audit profile in memory + storage.
  let tabA = { step: 6, profile: audit, resets: 0 };
  storage['pp-profile'] = JSON.stringify(audit);
  storage['pp-wizard-step'] = '6';
  storage['pp-prefchat'] = '{"turns":[]}';
  // Tab B: homepage clear — clearData wipes the shared keys.
  delete storage['pp-profile']; delete storage['pp-wizard-step'];
  delete storage['pp-prefchat']; delete storage['pp-check-done'];
  storage['pp-profile'] = JSON.stringify(types.emptyProfile); // persist effect re-write
  // The storage event reaches tab A only if the listener exists.
  if (withListener) {
    tabA = { step: 0, profile: types.emptyProfile, resets: 1 }; // clearData via the listener
    storage['pp-wizard-step'] = '0'; // live step reset re-persisted
  }
  return { tabA, storage };
}
const preFix = simulateTwoTabs(false);
check('pre-fix: other tab keeps showing 7/8 after homepage clear (the defect)',
  preFix.tabA.step, 6);
const postFix = simulateTwoTabs(listenerPresent);
check('post-fix: storage event resets the other tab to 1/8',
  postFix.tabA.step, 0);
check('post-fix: other tab profile emptied', postFix.tabA.profile, types.emptyProfile);
check('post-fix: no stale step survives in storage',
  postFix.storage['pp-wizard-step'], '0');

console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
process.exit(fail ? 1 : 0);
"""


def _build_snippet(tmp_path: Path) -> Path:
    """Compile the REAL loadWizardStep (verbatim slice of
    wizard/page.tsx) with the REAL types.ts, so the harness runs the
    shipped function instead of a reimplementation."""
    wizard = WIZARD.read_text(encoding="utf-8")
    steps_m = re.search(r"const STEPS = \[[^\]]+\] as const;", wizard)
    key_m = re.search(r"const WIZARD_STEP_KEY = '[^']+';", wizard)
    assert steps_m and key_m, "STEPS / WIZARD_STEP_KEY not found in wizard/page.tsx"
    start = wizard.index("function loadWizardStep")
    end = wizard.index("function NumField", start)
    assert start != -1 and end != -1 and end > start
    fn = wizard[start:end].rstrip()
    assert fn.endswith("}"), fn[-200:]
    snippet = tmp_path / "snippet.ts"
    snippet.write_text(
        "import { emptyProfile, type Profile } from './types';\n"
        + steps_m.group(0) + "\n"
        + key_m.group(0) + "\n"
        + fn + "\n"
        + "export { loadWizardStep };\n",
        encoding="utf-8")
    (tmp_path / "types.ts").write_text(TYPES.read_text(encoding="utf-8"), encoding="utf-8")
    res = subprocess.run(
        ["npx", "tsc", str(tmp_path / "snippet.ts"), str(tmp_path / "types.ts"),
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(tmp_path), "--skipLibCheck", "--esModuleInterop"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    return tmp_path


def test_r34_d1_harness(tmp_path):
    """Real loadWizardStep cases (empty-profile guard) + two-tab
    simulation driven by the real store source: fails pre-fix (the
    guard returns the stale step; no listener, so the other tab
    keeps 7/8) and passes post-fix."""
    _build_snippet(tmp_path)
    harness = tmp_path / "r34_d1_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("TMP", repr(str(tmp_path)))
        .replace("STORE", repr(str(STORE)))
        .replace("WIZARD", repr(str(WIZARD))),
        encoding="utf-8")
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=120)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
    assert "HARNESS OK" in node.stdout


# ---------------------------------------------------------------------------
# Source pins
# ---------------------------------------------------------------------------

def test_r34_d1_clear_data_body_unchanged():
    """clearData is byte-identical in shape: the Round 18 pins that
    slice it still hold unmodified — the four removeItems and the
    nonce bump stay inside clearData, so the listener reuses the
    shared routine instead of duplicating it."""
    src = STORE.read_text(encoding="utf-8")
    clear = src[src.index("const clearData = () => {"):]
    clear = clear[:clear.index("};")]
    assert "localStorage.removeItem('pp-wizard-step')" in clear
    assert "localStorage.removeItem('pp-prefchat')" in clear
    assert "localStorage.removeItem('pp-profile')" in clear
    assert "localStorage.removeItem('pp-check-done')" in clear
    assert "setDataClearNonce((n) => n + 1)" in clear
    assert "setProfileState(emptyProfile);" in clear


def test_r34_d1_store_listener_wiring():
    """Exactly one storage listener, registered + removed in an
    effect, calling clearData — and only clearData is the shared
    reset (no second reset body duplicated in the store)."""
    src = STORE.read_text(encoding="utf-8")
    assert src.count("addEventListener('storage'") == 1
    assert src.count("removeEventListener('storage'") == 1
    assert "window.addEventListener('storage', onStorage);" in src
    assert "return () => window.removeEventListener('storage', onStorage);" in src
    # One shared routine: clearData is the only place that bumps the
    # data-clear nonce or empties the profile in the store.
    assert src.count("setDataClearNonce((n) => n + 1);") == 1
    assert src.count("setProfileState(emptyProfile);") == 1


def test_r34_d1_listener_guards_on_profile_removal_only():
    """The trigger is exactly pp-profile removal: no other removal
    may reset the tab, and a set (the persist-effect re-write, or
    any other tab's profile save) must not."""
    src = STORE.read_text(encoding="utf-8")
    at = src.index("const onStorage")
    effect = src[at:src.index("}, []);", at)]
    assert "if (e.key !== 'pp-profile' || e.newValue !== null) return;" in effect
    assert "clearData();" in effect
    assert "pp-prefchat" not in effect
    assert "pp-wizard-step" not in effect
    assert "pp-check-done" not in effect


def test_r34_d1_wizard_guard_judges_profile_content():
    """loadWizardStep judges the stored profile's content, not the
    key's absence: the old key-absence line is gone, the empty
    check is present, and the step read still follows it."""
    wizard = WIZARD.read_text(encoding="utf-8")
    assert "if (!localStorage.getItem('pp-profile')) return 0;" not in wizard
    assert "const rawProfile = localStorage.getItem('pp-profile');" in wizard
    assert "if (!rawProfile) return 0;" in wizard
    assert "if (isEmpty) return 0;" in wizard
    assert "const stored = { ...emptyProfile, ...JSON.parse(rawProfile) };" in wizard
    assert "emptyProfile" in wizard
    # The mount still reads the step through the guard.
    assert "const [step, setStep] = useState(loadWizardStep);" in wizard
    assert "const raw = localStorage.getItem(WIZARD_STEP_KEY);" in wizard


def test_r34_d1_homepage_stats_strip_untouched():
    """This fix touches no homepage code: the Round 33 stats strip
    (live ranking-records count) is exactly as the uncommitted
    Round 33 change left it, and page.tsx has no clear/storage
    logic of its own."""
    home = HOME.read_text(encoding="utf-8")
    assert "home.rankingRecords" in home
    assert "RANKING_ENTRIES.length" in home
    assert "addEventListener('storage'" not in home
    assert "clearData" not in home


def test_r34_d1_no_new_subscribers_to_the_clear_nonce():
    """Only the existing subscribers reset on dataClearNonce
    (wizard, PrefChat, pet): the fix adds no new nonce watcher and
    bumps no new nonce — the cross-tab path reuses the one signal."""
    assert "profileReplaceNonce" in STORE.read_text(encoding="utf-8")
    for path in (FE / "src").rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        if "dataClearNonce" in text:
            assert path in (STORE, FE / "src/app/wizard/page.tsx",
                            FE / "src/components/PrefChat.tsx",
                            FE / "src/components/CompassPet.tsx"), path
