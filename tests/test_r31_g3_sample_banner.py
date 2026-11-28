"""Round 31 G3 — stale "Synthetic sample — not a real student" banner.

Re-test 26 item 3: after the user replaces the sample profile with
their own Gaokao profile, the banner stays visible at the top of the
wizard even though the profile shown is no longer the synthetic
sample — the label then contradicts the facts.

Root cause (verified before the fix): the banner renders wherever
``profile.sample`` is true (wizard/page.tsx:609, results/page.tsx:183,
report/page.tsx:114) and the flag is set only by the two sample
literals (``sampleUndergrad`` / ``sampleMasters`` in lib/types.ts),
but NOTHING ever cleared it:

* ``updateProfile`` (lib/store.tsx) merged patches over the previous
  profile (``{ ...prev, ...patch }``), so every wizard field edit —
  switching curriculum to Gaokao, entering a Gaokao score, changing
  IELTS — and every PrefChat preference edit kept ``sample: true``.
* the wizard's profile import spread the OLD profile first
  (``setProfile({ ...profile, ...p })``), so importing the user's own
  file (which has no ``sample`` field) kept ``sample: true`` from the
  loaded sample.

Fix (frontend only, no data / copy / locale change):
``frontend/src/lib/profile.ts`` (new) holds the two pure rules, both
wired in at the only places that can change the flag:

* ``applyProfilePatch(prev, patch)`` — any user edit clears the
  marker (``sample: false``). ``updateProfile`` in store.tsx now
  delegates to it. Loading a sample goes through ``setProfile`` with
  the sample objects, never through a patch, so a freshly loaded
  sample keeps its banner.
* ``mergeImportedProfile(prev, imported)`` — the banner follows the
  imported file's own flag: an import with no ``sample`` field clears
  it, re-importing an exported sample file (``sample: true``) keeps
  it. The wizard import handler now uses it.

The node harness below compiles the real lib code (``profile.ts`` +
``types.ts``) and exercises both rules; the source pins check the
wiring (store, wizard import, sample loaders, banner gates).

Run from the project root:
    .venv/bin/pytest tests/test_r31_g3_sample_banner.py -q -p no:cacheprovider
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
PROFILE_TS = FE / "src" / "lib" / "profile.ts"
STORE = FE / "src" / "lib" / "store.tsx"
WIZARD = FE / "src" / "app" / "wizard" / "page.tsx"
HOME = FE / "src" / "app" / "page.tsx"
RESULTS = FE / "src" / "app" / "results" / "page.tsx"
REPORT = FE / "src" / "app" / "report" / "page.tsx"

_NODE_HARNESS = r"""
const profile = require(OUT + '/profile.js');
const types = require(OUT + '/types.js');
let fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('FAIL ' + name + ': got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want)); }
  else console.log('ok ' + name);
}

// --- (a) The banner shows while the synthetic sample IS active -------
// The banner condition is `profile.sample`; both sample literals carry it.
check('sampleUndergrad carries sample:true', types.sampleUndergrad.sample, true);
check('sampleMasters carries sample:true', types.sampleMasters.sample, true);

// --- (b) Any user edit clears the banner -----------------------------
// The defect's exact case: sample loaded, user replaces it with their
// own Gaokao profile by editing the wizard fields.
const gaokaoEdit = profile.applyProfilePatch(types.sampleUndergrad, {
  curriculum: 'cn_gaokao', gaokaoScore: 680, gaokaoTotal: 750, gaokaoMaths: 140,
  alevels: '', mathsGrade: '', gcseEnglish: '', gcseMaths: '',
});
check('Gaokao replace clears sample', gaokaoEdit.sample, false);
check('Gaokao replace keeps the new curriculum', gaokaoEdit.curriculum, 'cn_gaokao');
check('Gaokao replace keeps the new score', gaokaoEdit.gaokaoScore, 680);
check('Gaokao replace keeps the new total', gaokaoEdit.gaokaoTotal, 750);
// A single-field edit clears it too — the banner must not survive any edit.
check('IELTS edit clears sample',
  profile.applyProfilePatch(types.sampleUndergrad, { ieltsOverall: 7.5 }).sample, false);
check('masters degree edit clears sample',
  profile.applyProfilePatch(types.sampleMasters, { degree: "BSc Mathematics" }).sample, false);
check('pref edit clears sample',
  profile.applyProfilePatch(types.sampleUndergrad, { prefClimate: 'cool' }).sample, false);
// Other fields are untouched by the clear — only the marker changes.
const patched = profile.applyProfilePatch(types.sampleUndergrad, { budget: 40000 });
check('edit keeps the other sample values', patched.alevels, 'A*A*A');
check('edit applies the patch', patched.budget, 40000);
check('edit clears sample', patched.sample, false);
// A non-sample profile stays non-sample after an edit.
check('own profile stays non-sample after edit',
  profile.applyProfilePatch(types.emptyProfile, { curriculum: 'cn_gaokao' }).sample, false);
// The input profile is not mutated (React state updater must be pure).
const before = JSON.stringify(types.sampleUndergrad);
profile.applyProfilePatch(types.sampleUndergrad, { ieltsOverall: 9 });
check('applyProfilePatch does not mutate its input', JSON.stringify(types.sampleUndergrad), before);

// --- (c) Importing a profile follows the imported file's flag --------
const ownGaokao = { ...types.emptyProfile, curriculum: 'cn_gaokao',
  gaokaoScore: 680, gaokaoTotal: 750, field: 'computing' };
check('import of own Gaokao file clears sample',
  profile.mergeImportedProfile(types.sampleUndergrad, ownGaokao).sample, false);
check('import keeps the imported Gaokao score',
  profile.mergeImportedProfile(types.sampleUndergrad, ownGaokao).gaokaoScore, 680);
check('import keeps the imported curriculum',
  profile.mergeImportedProfile(types.sampleUndergrad, ownGaokao).curriculum, 'cn_gaokao');
// Re-importing an exported sample file keeps the banner — it IS the sample.
check('re-import of the sample file keeps sample',
  profile.mergeImportedProfile(types.emptyProfile, { ...types.sampleUndergrad }).sample, true);
check('re-import of the masters sample keeps sample',
  profile.mergeImportedProfile(types.emptyProfile, { ...types.sampleMasters }).sample, true);
// An explicitly non-sample file clears it even over a loaded sample.
check('import of sample:false file clears sample',
  profile.mergeImportedProfile(types.sampleUndergrad, { ...ownGaokao, sample: false }).sample, false);
// Fields absent from the imported file still fall back to the old
// profile (the merge behaviour itself is unchanged) — a sparse
// import carries no budget key at all, unlike the emptyProfile
// spread above, which explicitly sets budget to ''.
const sparseImport = { curriculum: 'cn_gaokao', gaokaoScore: 680 };
check('import keeps old values for absent fields',
  profile.mergeImportedProfile(types.sampleUndergrad, sparseImport).budget, 50000);

console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
process.exit(fail ? 1 : 0);
"""


def test_r31_g3_sample_banner_rules(tmp_path):
    """The two pure rules, run against the real compiled lib code."""
    outdir = tmp_path / "r31_g3"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/profile.ts", "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r31_g3_harness.js"
    harness.write_text(
        _NODE_HARNESS.replace("OUT", repr(str(outdir))),
        encoding="utf-8")
    env = {"PATH": os.environ["PATH"],
           "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
    assert "HARNESS OK" in node.stdout


# ---------------------------------------------------------------------------
# Wiring pins — the rules must actually be reached from the UI
# ---------------------------------------------------------------------------

def test_store_update_profile_delegates_to_apply_profile_patch():
    """Every wizard / PrefChat edit goes through updateProfile, so the
    clear must live there — not in one field handler."""
    src = STORE.read_text(encoding="utf-8")
    assert "applyProfilePatch" in src
    assert "setProfileState((prev) => applyProfilePatch(prev, patch))" in src
    # The old merge that never touched the flag is gone.
    assert "setProfileState((prev) => ({ ...prev, ...patch }))" not in src


def test_wizard_import_uses_merge_imported_profile():
    """Importing a profile must follow the imported file's flag, not
    the profile being replaced."""
    src = WIZARD.read_text(encoding="utf-8")
    assert "mergeImportedProfile" in src
    assert "setProfile(mergeImportedProfile(profile, p))" in src
    # The old spread that kept `sample: true` from the loaded sample.
    assert "setProfile({ ...profile, ...p })" not in src


def test_sample_loaders_still_set_the_sample_flag():
    """The banner must still show while the synthetic sample IS the
    active profile: both loaders set the whole sample object through
    setProfile (never through updateProfile, which clears the flag)."""
    wizard = WIZARD.read_text(encoding="utf-8")
    assert "setProfile({ ...s });" in wizard  # loadSample
    home = HOME.read_text(encoding="utf-8")
    assert "setProfile(which === 'ug' ? sampleUndergrad : sampleMasters);" in home


def test_banner_still_gated_on_profile_sample_everywhere():
    """No redesign: the banner itself is unchanged, still rendered
    exactly where `profile.sample` is true — wizard, results, report."""
    for page in (WIZARD, RESULTS, REPORT):
        assert "profile.sample" in page.read_text(encoding="utf-8"), page
    assert "{profile.sample && " in WIZARD.read_text(encoding="utf-8")
    assert "t('common.synthetic')" in WIZARD.read_text(encoding="utf-8")


def test_no_other_writer_of_the_sample_flag():
    """The flag is set only by the two sample literals and cleared only
    by the two new helpers — no other code path writes `sample:`."""
    types = (FE / "src" / "lib" / "types.ts").read_text(encoding="utf-8")
    assert types.count("sample: true,") == 2  # the two sample literals
    profile = PROFILE_TS.read_text(encoding="utf-8")
    assert "return { ...prev, ...patch, sample: false };" in profile
    assert "return { ...prev, ...imported, sample: imported.sample === true };" in profile
    # Neither the store nor the wizard writes the flag directly.
    assert "sample:" not in STORE.read_text(encoding="utf-8")
    assert "sample:" not in WIZARD.read_text(encoding="utf-8")
