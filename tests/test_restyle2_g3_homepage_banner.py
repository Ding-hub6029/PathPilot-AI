"""Restyle 2 G3 — homepage "Sample profile" line never clears.

Re-test 27 PARTIAL FAIL: Round 31 G3 fixed the "Synthetic sample —
not a real student" banner on the results page, wizard, and report
page, but the HOMEPAGE line under the programme cards
("Sample profile — synthetic data, not a real student") did NOT
clear — even after a full wizard re-run in en and ar; only
"Clear my data" cleared it.

Root cause (different source, not stale state): the other three
pages gate their banner on the shared flag —
``{profile.sample && ...}`` (wizard/page.tsx:627,
results/page.tsx:183, report/page.tsx:114) — so the Round 31
state-layer fix (``applyProfilePatch`` / ``mergeImportedProfile``
clearing ``profile.sample``) cleared them. The homepage line never
read the flag at all: page.tsx rendered ``{t('home.sampleNote')}``
UNCONDITIONALLY, a static locale string under the programme cards.
No state-layer fix could ever clear it, because nothing in the
homepage consulted the state.

Fix (one line of banner wiring in page.tsx, no state / data / copy /
locale change): gate the line on the same flag the other pages use —
``{profile.sample && <p ...>{t('home.sampleNote')}</p>}``.
``profile`` was already destructured from ``useApp()`` in HomePage,
so no new import or prop is needed. The flag itself is already
maintained by the Round 31 rules:

* any user edit clears it (``applyProfilePatch`` via
  ``updateProfile`` in lib/store.tsx),
* a wizard re-run replaces the profile through edits, so it clears,
* an own-file import clears it (``mergeImportedProfile`` follows the
  imported file's flag),
* loading a sample goes through ``setProfile`` with the sample
  literals, so a freshly loaded sample keeps the line.

The en and ar cases from the re-test are covered by the locale
checks below: the gate is locale-independent (the same
``profile.sample`` flag drives every locale), and both
``messages/en.json`` and ``messages/ar.json`` carry
``home.sampleNote`` — the line's text in each locale — so the fix
applies identically in en and ar.

Run from the project root:
    .venv/bin/pytest tests/test_restyle2_g3_homepage_banner.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
PROFILE_TS = FE / "src" / "lib" / "profile.ts"
STORE = FE / "src" / "lib" / "store.tsx"
HOME = FE / "src" / "app" / "page.tsx"
RESULTS = FE / "src" / "app" / "results" / "page.tsx"
REPORT = FE / "src" / "app" / "report" / "page.tsx"
WIZARD = FE / "src" / "app" / "wizard" / "page.tsx"

_NODE_HARNESS = r"""
const profile = require(OUT + '/profile.js');
const types = require(OUT + '/types.js');
let fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('FAIL ' + name + ': got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want)); }
  else console.log('ok ' + name);
}
// The homepage banner condition is `profile.sample` (same gate as the
// other three pages). Simulate the full user journeys against the real
// compiled lib code and check what the gate would render.

// --- (a) Freshly loaded sample: banner shows -------------------------
// Loading goes through setProfile with the sample literals.
check('fresh UG sample: banner shows', types.sampleUndergrad.sample, true);
check('fresh PG sample: banner shows', types.sampleMasters.sample, true);

// --- (b) Any user edit: banner clears --------------------------------
// The re-test's exact case: full wizard re-run replacing the sample
// with the user's own Gaokao profile (field edits via updateProfile).
const gaokaoRun = profile.applyProfilePatch(types.sampleUndergrad, {
  curriculum: 'cn_gaokao', gaokaoScore: 680, gaokaoTotal: 750, gaokaoMaths: 140,
  alevels: '', mathsGrade: '', gcseEnglish: '', gcseMaths: '',
});
check('wizard re-run (Gaokao replace): banner clears', gaokaoRun.sample, false);
// A single-field edit clears it too.
check('single edit clears banner',
  profile.applyProfilePatch(types.sampleMasters, { ieltsOverall: 7.5 }).sample, false);

// --- (c) Profile replace via own-file import: banner clears ----------
const ownGaokao = { ...types.emptyProfile, curriculum: 'cn_gaokao',
  gaokaoScore: 680, gaokaoTotal: 750, field: 'computing' };
check('own-file import: banner clears',
  profile.mergeImportedProfile(types.sampleUndergrad, ownGaokao).sample, false);

// --- (d) Re-loading a sample after clearing: banner shows again ------
const cleared = profile.applyProfilePatch(types.sampleUndergrad, { budget: 40000 });
check('edit cleared the flag first', cleared.sample, false);
check('re-loading the sample shows the banner again',
  types.sampleUndergrad.sample, true);
// Re-importing an exported sample file also keeps it.
check('re-import of the sample file shows the banner',
  profile.mergeImportedProfile(types.emptyProfile, { ...types.sampleMasters }).sample, true);

console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
process.exit(fail ? 1 : 0);
"""


def test_restyle2_g3_homepage_banner_state_chain(tmp_path):
    """The flag chain behind the homepage gate, run against the real
    compiled lib code: shows for a fresh sample, clears on edit /
    replace / own-file import, shows again on a fresh sample load."""
    outdir = tmp_path / "restyle2_g3"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/profile.ts", "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "restyle2_g3_harness.js"
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
# Wiring pins — the homepage must actually read the flag
# ---------------------------------------------------------------------------

def test_homepage_sample_note_is_gated_on_profile_sample():
    """The fix: the homepage line renders only while `profile.sample`
    is true, exactly like the results / report / wizard banners."""
    src = HOME.read_text(encoding="utf-8")
    assert "{profile.sample && <p className=\"mt-3 text-sm text-navy/60\">{t('home.sampleNote')}</p>}" in src


def test_homepage_sample_note_is_not_rendered_unconditionally():
    """The defect: a bare `{t('home.sampleNote')}` line with no gate.
    No unconditional render of the note may remain anywhere in the
    homepage source."""
    src = HOME.read_text(encoding="utf-8")
    assert src.count("home.sampleNote") == 1  # only the gated line
    # The old defect was this bare line, indented as a statement of its
    # own; the gated line starts with `{profile.sample && `, so the
    # standalone form must be gone.
    assert "\n        <p className=\"mt-3 text-sm text-navy/60\">{t('home.sampleNote')}</p>\n" not in src


def test_no_other_unconditional_sample_note_in_src():
    """`home.sampleNote` is used in exactly one place — the gated
    homepage line — so no other page can show the note unconditionally."""
    hits = []
    for path in (FE / "src").rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        if "home.sampleNote" in text:
            hits.append(path)
    assert hits == [HOME], hits


def test_all_four_banners_share_the_same_gate():
    """Homepage, results, report, and wizard all gate their synthetic
    banner on `profile.sample` — one flag, one behaviour, no divergent
    source left."""
    for page in (HOME, RESULTS, REPORT, WIZARD):
        assert "profile.sample && " in page.read_text(encoding="utf-8"), page


def test_homepage_gate_uses_profile_already_in_scope():
    """The fix adds no import or prop: `profile` is destructured from
    `useApp()` at the top of HomePage, the same binding the sample
    buttons already use."""
    src = HOME.read_text(encoding="utf-8")
    assert "const { t, tf, locale, profile, setProfile } = useApp();" in src


def test_homepage_sample_note_exists_in_en_and_ar():
    """The en and ar cases from re-test 27: both locales carry the
    note's text, and the gate is locale-independent, so the fix
    applies identically in en and ar."""
    for locale_file in ("en.json", "ar.json"):
        messages = json.loads((FE / "messages" / locale_file).read_text(encoding="utf-8"))
        assert "home.sampleNote" in messages, locale_file
        assert messages["home.sampleNote"], locale_file
    en = json.loads((FE / "messages" / "en.json").read_text(encoding="utf-8"))
    ar = json.loads((FE / "messages" / "ar.json").read_text(encoding="utf-8"))
    assert en["home.sampleNote"] == "Sample profile — synthetic data, not a real student"
    assert ar["home.sampleNote"] == "ملف تعريفي نموذجي — بيانات اصطناعية، وليس طالبًا حقيقيًا"
