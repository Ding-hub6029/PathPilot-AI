"""
Round 32, H2b — pet re-asks the budget for a saved amount in a country
with no band table (re-test 28 defect #1, audit profile).

The Round 32 H2 fix (DECISIONS #320) skips the budget question only
when the saved budget maps to a GB/SG band via petBudgetBand(). For
the audit profile (undergraduate, Switzerland, budget 50000 GBP) there
is no band table — petBudgetBand returns null — so greet() still
pushed pet.q3 ("Roughly what is your budget?") even though the amount
was saved and shown in the pet's own summary card. Same hole in
onChip steps 0 and 1.

Fix: when a budget AMOUNT is saved but no band table exists for the
degree + country, the pet must not ask the budget-band question at
all — the amount is already known. The flow proceeds to the
suggestion with a null band (no band ever claimed): the model
message states the saved amount with the wizard's period
(undergraduate per year, taught masters total — wizard.budgetHint),
and the offline catalogue ignores the band for no-table countries
(cheapest verified programme, fit null). No band ceilings are
invented for new countries; BAND_CEILING stays GB/SG only.

Run from the project root:
    .venv/bin/pytest tests/test_r32_h2b_pet_budget_no_band.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import subprocess
import os

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
CHAT = FE / "src" / "lib" / "chat.ts"
PET = FE / "src" / "components" / "CompassPet.tsx"
TYPES = FE / "src" / "lib" / "types.ts"
EN_MESSAGES = FE / "messages" / "en.json"
BACKEND_CHAT = ROOT / "backend" / "ai" / "chat.py"

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

// --- premise: no band exists for CH --------------------------------------
// The audit profile (UG, Switzerland, 50000 GBP): degree + country are
// known, the amount is saved, but petBudgetBand is null — the question
// is not "which band?" but "why ask at all?".
check('UG CH 50000 -> null (no table)', chat.petBudgetBand('undergraduate', 'CH', 50000, CEILINGS), null);
const audit = { ...types.sampleUndergrad, prefCountries: ['CH'] };
const known = chat.petKnownSteps(audit, CEILINGS);
check('audit: degree known', known.degree, 'undergraduate');
check('audit: country CH known', known.country, 'CH');
check('audit: band null at greet time', known.band, null);

// --- suggestMessage: null band states the amount, never a band ---------
// Undergraduate: the wizard's period is per year (wizard.budgetHint).
check('UG CH null band + 50000 GBP',
  chat.suggestMessage('undergraduate', 'CH', 'Switzerland', null, null, { amount: 50000, currency: 'GBP' }),
  'Recommend a undergraduate programme in Switzerland (country code CH). Budget: GBP 50,000 per year.');
// Taught masters: the wizard's period is total.
check('TM CH null band + 70000 SGD',
  chat.suggestMessage('taught_masters', 'CH', 'Switzerland', null, null, { amount: 70000, currency: 'SGD' }),
  'Recommend a taught masters programme in Switzerland (country code CH). Budget: SGD 70,000 total.');
// Null band with no saved amount: no budget sentence at all, and
// certainly no "Budget band: null." claim.
check('UG CH null band + no amount',
  chat.suggestMessage('undergraduate', 'CH', 'Switzerland', null, null, null),
  'Recommend a undergraduate programme in Switzerland (country code CH).');
// --- suggestMessage: band path byte-identical to before ------------------
check('UG GB mid + ceiling unchanged',
  chat.suggestMessage('undergraduate', 'GB', 'United Kingdom', 'mid', { currency: 'GBP', amount: 50000, period: 'per year' }),
  'Recommend a undergraduate programme in United Kingdom (country code GB). Budget band: mid. Budget: under GBP 50,000 per year.');
check('UG GB high + no ceiling unchanged',
  chat.suggestMessage('undergraduate', 'GB', 'United Kingdom', 'high', null),
  'Recommend a undergraduate programme in United Kingdom (country code GB). Budget band: high.');

console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
process.exit(fail ? 1 : 0);
"""


def test_r32_h2b_suggest_message_harness(tmp_path):
    """The null-band message states the saved amount with the wizard's
    period and never claims a band; the band path is byte-identical."""
    outdir = tmp_path / "r32_h2b"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/chat.ts", "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r32_h2b_harness.js"
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


def test_backend_parses_the_saved_amount_as_a_ceiling():
    """The null-band message is not just honest prose — the backend's
    own ceiling parser (backend/ai/chat.py _CEILING_RE) reads
    "GBP 50,000 per year" as ('GBP', 50000, per year), so the
    suggestion pick still respects the saved budget. The regex is
    taken from the real backend source, not re-typed here."""
    src = BACKEND_CHAT.read_text(encoding="utf-8")
    m = re.search(
        r"_CEILING_RE = re\.compile\(\s*r\"([^\"]+)\"\s*r\"([^\"]+)\"",
        src)
    assert m, "_CEILING_RE not found in backend/ai/chat.py"
    pattern = re.compile(m.group(1) + m.group(2), re.IGNORECASE)
    hit = pattern.search(
        "Recommend a undergraduate programme in Switzerland "
        "(country code CH). Budget: GBP 50,000 per year.")
    assert hit is not None
    assert hit.group(1).upper() == "GBP"
    assert float(hit.group(2).replace(",", "")) == 50000.0
    assert hit.group(3).lower() == "per year"


# ---------------------------------------------------------------------------
# Wiring pins — the null-band skip in greet() and onChip, and no invented band
# ---------------------------------------------------------------------------

def test_greet_skips_q3_for_saved_amount_without_a_band():
    """greet(): degree + country known, band null, amount saved → the
    flow goes straight to step 3 with a null band instead of pushing
    pet.q3. No step-2 choice turn: no band was ever chosen."""
    src = PET.read_text(encoding="utf-8")
    assert "} else if (typeof profile.budget === 'number') {" in src
    assert "if (stepNext === 3 && knownSteps.degree && knownSteps.country) {" in src
    assert "void askSuggest(knownSteps.degree, knownSteps.country, knownSteps.band);" in src


def test_onchip_step0_skips_q3_for_saved_amount_without_a_band():
    """Step 0 (degree answered): a saved single country with a saved
    amount but no band table skips the budget question and suggests
    with a null band."""
    src = PET.read_text(encoding="utf-8")
    assert "void askSuggest(degree, savedCountry, null);" in src


def test_onchip_step1_skips_q3_for_saved_amount_without_a_band():
    """Step 1 (country answered): the re-test 28 case — a saved amount
    in a no-table country skips the budget question and suggests with
    a null band, instead of pushing pet.q3."""
    src = PET.read_text(encoding="utf-8")
    assert "void askSuggest(answers.degree as Degree, country, null);" in src


def test_ask_suggest_accepts_a_null_band():
    """askSuggest, suggestMessageFor and the stored suggest turn all
    carry Band | null; suggestOffline guards the GB/SG ceiling lookup
    so a null band means no ceiling (the 'high' behaviour)."""
    src = PET.read_text(encoding="utf-8")
    assert "const askSuggest = async (degree: Degree, country: Country, band: Band | null) => {" in src
    assert "const suggestMessageFor = (degree: Degree, country: Country, band: Band | null): string => {" in src
    assert "band: Band | null;" in src
    assert "const ceiling = band === null ? null : BAND_CEILING[`${degree}-${country}`][band];" in src


def test_pet_q3_still_has_exactly_three_push_sites():
    """No new question site: pet.q3 is still asked from exactly three
    places (greet, onChip step 0, onChip step 1) — the fix adds
    branches around them, never a fourth push."""
    src = PET.read_text(encoding="utf-8")
    assert src.count("key: 'pet.q3'") == 3, src.count("key: 'pet.q3'")


def test_no_band_table_invented_for_new_countries():
    """No ceilings are invented: BAND_CEILING stays exactly the four
    GB/SG keys, and no CH key exists anywhere in the component."""
    src = PET.read_text(encoding="utf-8")
    for key in ("'undergraduate-GB'", "'taught_masters-GB'",
                "'undergraduate-SG'", "'taught_masters-SG'"):
        assert key in src, key
    assert "'undergraduate-CH'" not in src
    assert "'taught_masters-CH'" not in src
    assert src.count("typeof profile.budget === 'number'") == 4, (
        "greet + step 0 + step 1 + suggestMessageFor")


def test_no_new_locale_keys():
    """No copy change: this fix adds no locale keys, so the 994-key
    pin stands in every locale file."""
    base = json.loads(EN_MESSAGES.read_text(encoding="utf-8"))
    assert len(base) == 994, len(base)
    for locale_file in ("zh-CN.json", "es.json", "fr.json", "pt-BR.json", "ar.json"):
        messages = json.loads((FE / "messages" / locale_file).read_text(encoding="utf-8"))
        assert len(messages) == 994, (locale_file, len(messages))
