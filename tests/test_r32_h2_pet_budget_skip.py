"""Round 32 H2 — pet re-asks the budget despite a saved budget.

Re-test 28: the pet's profile card clearly showed a saved budget
(50000 GBP on the sample profile; 60000 GBP on the user's own
Gaokao profile), yet the pet still asked "Roughly what is your
budget?" with Low / Medium / High buttons — persisting across
pages, refresh, and language switch.

Root cause (two linked gaps, not stale state):

* ``petKnownSteps`` (lib/chat.ts) derives the budget band ONLY
  when degree AND a single country are both already saved
  (``if (degree && country && typeof profile.budget === 'number')``).
  The sample profile — and the re-test Gaokao profile — has a saved
  budget but no single saved country (``sampleUndergrad`` ships
  ``prefCountries: []``, types.ts), so the band came back null and
  ``greet()`` legitimately asked Q2 (country).
* ``onChip`` in CompassPet.tsx then never re-consulted the saved
  budget: after the user answered the country, the step-1 branch
  pushed ``pet.q3`` UNCONDITIONALLY whenever the country had
  verified programmes; the step-0 branch did the same for Q2 after
  a degree answer. The flow consulted ``petKnownSteps`` exactly
  once, at greet time — so supplying the one missing piece
  (country) never unlocked the already-saved budget.

Fix (frontend-only, no copy / data / route / locale change):

* lib/chat.ts: new pure ``petBudgetBand(degree, country, budget,
  ceilings)`` — the band derivation, usable whenever degree +
  country become known. ``petKnownSteps`` now calls it (same
  result at greet time: a profile with no single saved country
  still yields ``band: null`` and still asks Q2).
* CompassPet.tsx ``onChip``: step 1 (country answered) derives
  the band from the saved budget and, when one exists, records it
  as the step-2 choice turn and goes straight to the suggestion
  instead of pushing ``pet.q3``; step 0 (degree answered) applies
  the same skip to a saved single country and its band, mirroring
  greet()'s petKnownSteps path. A missing/empty budget, several
  saved countries, or a country with no band table still asks the
  question, exactly as before.

Run from the project root:
    .venv/bin/pytest tests/test_r32_h2_pet_budget_skip.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
CHAT = FE / "src" / "lib" / "chat.ts"
PET = FE / "src" / "components" / "CompassPet.tsx"
TYPES = FE / "src" / "lib" / "types.ts"
EN_MESSAGES = FE / "messages" / "en.json"

_NODE_HARNESS = r"""
const chat = require(OUT + '/chat.js');
const types = require(OUT + '/types.js');
let fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('FAIL ' + name + ': got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want)); }
  else console.log('ok ' + name);
}
// BAND_CEILING, mirrored from CompassPet.tsx (GB/SG only).
const CEILINGS = {
  'undergraduate-GB': { low: 30000, mid: 50000, high: null },
  'taught_masters-GB': { low: 30000, mid: 50000, high: null },
  'undergraduate-SG': { low: 25000, mid: 45000, high: null },
  'taught_masters-SG': { low: 50000, mid: 80000, high: null },
};

// --- petBudgetBand: the re-test 28 cases -------------------------------
// Saved 50000 GBP, country GB just answered -> 'mid' (at the ceiling).
check('UG GB 50000 -> mid', chat.petBudgetBand('undergraduate', 'GB', 50000, CEILINGS), 'mid');
// Saved 60000 GBP, country GB just answered -> 'high'.
check('UG GB 60000 -> high', chat.petBudgetBand('undergraduate', 'GB', 60000, CEILINGS), 'high');
check('UG GB 30000 -> low', chat.petBudgetBand('undergraduate', 'GB', 30000, CEILINGS), 'low');
check('UG GB 25000 -> low', chat.petBudgetBand('undergraduate', 'GB', 25000, CEILINGS), 'low');
check('UG GB 50001 -> high', chat.petBudgetBand('undergraduate', 'GB', 50001, CEILINGS), 'high');
check('TM SG 70000 -> mid', chat.petBudgetBand('taught_masters', 'SG', 70000, CEILINGS), 'mid');
check('TM SG 90000 -> high', chat.petBudgetBand('taught_masters', 'SG', 90000, CEILINGS), 'high');
check('UG SG 20000 -> low', chat.petBudgetBand('undergraduate', 'SG', 20000, CEILINGS), 'low');
// No band table for this country: the band cannot be derived, so the
// question is still genuinely open (not a re-ask of a known answer).
check('UG CH 50000 -> null (no table)', chat.petBudgetBand('undergraduate', 'CH', 50000, CEILINGS), null);
check('null degree -> null', chat.petBudgetBand(null, 'GB', 50000, CEILINGS), null);
check('null country -> null', chat.petBudgetBand('undergraduate', null, 50000, CEILINGS), null);
check('empty budget -> null', chat.petBudgetBand('undergraduate', 'GB', '', CEILINGS), null);
check('undefined budget -> null', chat.petBudgetBand('undergraduate', 'GB', undefined, CEILINGS), null);

// --- petKnownSteps: unchanged at greet time ----------------------------
// The sample profile: degree known, budget saved, NO single saved
// country -> band stays null, so greet() still asks Q2 (country is
// genuinely unknown). The fix is mid-flow, in onChip, not here.
const sample = chat.petKnownSteps(types.sampleUndergrad, CEILINGS);
check('sample UG: degree known', sample.degree, 'undergraduate');
check('sample UG: country null (prefCountries empty)', sample.country, null);
check('sample UG: band null at greet time', sample.band, null);
const samplePg = chat.petKnownSteps(types.sampleMasters, CEILINGS);
check('sample TM: degree known', samplePg.degree, 'taught_masters');
check('sample TM: band null at greet time', samplePg.band, null);
// A profile with all three saved still skips everything at greet.
const full = { ...types.sampleUndergrad, prefCountries: ['GB'] };
check('full UG GB 50000: band mid at greet', chat.petKnownSteps(full, CEILINGS).band, 'mid');
// Several saved countries still need a choice, so no band either.
const multi = { ...types.sampleUndergrad, prefCountries: ['GB', 'SG'] };
check('multi-country: country null', chat.petKnownSteps(multi, CEILINGS).country, null);
check('multi-country: band null', chat.petKnownSteps(multi, CEILINGS).band, null);
// Empty budget still asks Q3.
const noBudget = { ...types.sampleUndergrad, prefCountries: ['GB'], budget: '' };
check('empty budget: band null', chat.petKnownSteps(noBudget, CEILINGS).band, null);

console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
process.exit(fail ? 1 : 0);
"""


def test_r32_h2_pet_budget_band_harness(tmp_path):
    """The band derivation against the real compiled lib code: the
    re-test 28 budgets map to a band once degree + country are
    known, and petKnownSteps is unchanged at greet time (the sample
    profile still yields band null because no single country is
    saved — Q2 is genuinely open; the skip happens mid-flow)."""
    outdir = tmp_path / "r32_h2"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/chat.ts", "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r32_h2_harness.js"
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
# Wiring pins — onChip must re-check the saved budget mid-flow
# ---------------------------------------------------------------------------

def test_pet_imports_pet_budget_band():
    """The component uses the shared derivation, not a second copy
    of the band table logic."""
    src = PET.read_text(encoding="utf-8")
    assert "petBudgetBand" in src
    assert "petBudgetBand, petKnownSteps" in src


def test_onchip_step1_derives_saved_band_before_asking_q3():
    """The re-test 28 fix: after the country answer, the step-1
    branch derives the band from the saved budget — it must not
    push pet.q3 unconditionally any more."""
    src = PET.read_text(encoding="utf-8")
    assert "const savedBand = petBudgetBand(answers.degree as Degree, country, profile.budget, BAND_CEILING);" in src


def test_onchip_step1_saved_band_skips_q3_and_suggests():
    """With a saved band, step 1 records it as the step-2 choice
    turn (same shape greet() uses) and goes straight to the
    suggestion instead of asking the budget question."""
    src = PET.read_text(encoding="utf-8")
    assert "push({ kind: 'choice', step: 2, value: savedBand, degree: answers.degree as Degree, country });" in src
    assert "void askSuggest(answers.degree as Degree, country, savedBand);" in src


def test_onchip_step1_q3_only_when_no_saved_band():
    """pet.q3 is pushed in step 1 only in the no-saved-band branch:
    an empty budget, or a country with no band table, still asks."""
    src = PET.read_text(encoding="utf-8")
    assert "} else {\n          push({ kind: 'prompt', key: 'pet.q3' });\n          setStep(2);\n        }" in src


def test_onchip_step0_applies_the_same_skip():
    """The same flaw in step 0 (degree answered): a saved single
    country and its band must be skipped too, mirroring greet()."""
    src = PET.read_text(encoding="utf-8")
    assert "const savedBand = petBudgetBand(degree, savedCountry, profile.budget, BAND_CEILING);" in src
    assert "push({ kind: 'choice', step: 2, value: savedBand, degree, country: savedCountry });" in src
    assert "void askSuggest(degree, savedCountry, savedBand);" in src


def test_pet_q3_has_exactly_three_push_sites():
    """pet.q3 is asked from exactly three places — greet() (band
    unknown at greet time), onChip step 0 (no saved band once the
    degree is known), onChip step 1 (no saved band once the country
    is known) — and nowhere else."""
    src = PET.read_text(encoding="utf-8")
    assert src.count("key: 'pet.q3'") == 3, src.count("key: 'pet.q3'")


def test_no_new_locale_keys():
    """No copy change: this fix adds no locale keys, so the 994-key
    pin stands in every locale file."""
    base = json.loads(EN_MESSAGES.read_text(encoding="utf-8"))
    assert len(base) == 994, len(base)
    for locale_file in ("zh-CN.json", "es.json", "fr.json", "pt-BR.json", "ar.json"):
        messages = json.loads((FE / "messages" / locale_file).read_text(encoding="utf-8"))
        assert len(messages) == 994, (locale_file, len(messages))
