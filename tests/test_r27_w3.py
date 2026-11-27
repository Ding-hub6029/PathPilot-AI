"""Round 27 W3 — salary currency misread: "80000 CHF" confirmed as GBP.

Re-test 21 (2026-11-28 00:28-00:39 CST): a salary answer "80000 CHF"
was confirmed as "80000 GBP", and the guided salary form offers only
GBP/SGD/USD — no CHF.

Root cause: the salary currency was hardcoded to GBP/SGD/USD in the
salary path, and the deterministic extraction regex had no CHF
alternative, so the currency fell back to known-or-"GBP":
- ``backend/ai/pref_chat.py``: ``_SALARY_CURRENCIES`` and the
  deterministic salary regex (``(GBP|SGD|USD)?``) plus its
  ``or "GBP"`` default.
- ``backend/ai/prompts.py``: the pref-chat salary schema
  (``"currency": "GBP" | "SGD" | "USD"``) and its rule text.
- ``frontend/src/lib/chat.ts``: ``PrefKnown`` / ``PrefExtracted``
  salary currency unions and ``SALARY_CURRENCIES``.
- ``frontend/src/components/PrefChat.tsx``: the ``mapFailedPrefAnswer``
  salary regex + casts, the ``modelSalaryCur`` state type, and both
  salary currency chip lists (model-led input and guided form).

Fixes pinned here:
1. CHF is a fourth salary currency everywhere the three-currency
   salary list lives: backend validation/extraction/schema and the
   frontend types, constants, regexes and form options.
2. The bare-number default is unchanged: a number with no currency
   still defaults to the known currency, else GBP.
3. Budget is untouched: ``backend/ai/parse.py`` (``_CURRENCIES``,
   ``_BUDGET_RE``), ``backend/ai/prompts.py`` line ~125 (budget
   schema), ``backend/ai/chat.py`` line ~443 (budget regex),
   ``backend/ai/grounding.py`` lines ~255-256 and the wizard
   budget-currency select are budget code, not salary code.
   (Note: ``wizard/page.tsx`` line ~563 is the BUDGET currency
   select — there is no salary currency list on that page.)
4. No arithmetic breaks: the salary is display-only. No code
   converts or compares salary amounts — ``convertCurrency`` callers
   are all fee-vs-budget (``frontend/src/lib/api.ts``,
   ``frontend/src/components/RecChat.tsx``); salary is only rendered
   (results page, preference summary, ``PrefChat`` summary line) and
   passed as text in the model context (``chat.ts``).

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r27_w3.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from ai.pref_chat import (
    _deterministic_extract,
    pref_answer,
    validate_extracted,
    validate_known,
)
from ai.prompts import PREF_CHAT_SCHEMA

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"

# The re-test's profile at the salary turn: everything before salary
# known (countries, climate, environment, city, afterGrad).
KNOWN_BEFORE_SALARY = {
    "countries": ["CH"], "climate": "cool", "environment": "campus",
    "city": "Zurich", "afterGrad": "stay",
}


# ---------------------------------------------------------------------------
# (a) Backend deterministic extraction: CHF recognised, not coerced
# ---------------------------------------------------------------------------

_DET_CASES = [
    # (message, known, expected deterministic extraction)
    # The re-test's exact answer.
    ("80000 CHF", dict(KNOWN_BEFORE_SALARY),
     {"salary": {"amount": 80000, "currency": "CHF"}}),
    # Case-insensitive.
    ("80000 chf", dict(KNOWN_BEFORE_SALARY),
     {"salary": {"amount": 80000, "currency": "CHF"}}),
    # The other three currencies are unchanged.
    ("80000 GBP", dict(KNOWN_BEFORE_SALARY),
     {"salary": {"amount": 80000, "currency": "GBP"}}),
    ("80000 SGD", dict(KNOWN_BEFORE_SALARY),
     {"salary": {"amount": 80000, "currency": "SGD"}}),
    ("80000 USD", dict(KNOWN_BEFORE_SALARY),
     {"salary": {"amount": 80000, "currency": "USD"}}),
    # Bare number: default pinned — known currency first, else GBP.
    ("80000", dict(KNOWN_BEFORE_SALARY),
     {"salary": {"amount": 80000, "currency": "GBP"}}),
    ("80000", {**KNOWN_BEFORE_SALARY, "salaryCurrency": "CHF"},
     {"salary": {"amount": 80000, "currency": "CHF"}}),
    ("80000", {**KNOWN_BEFORE_SALARY, "salaryCurrency": "SGD"},
     {"salary": {"amount": 80000, "currency": "SGD"}}),
    # Decimal amounts keep their value.
    ("80500.50 CHF", dict(KNOWN_BEFORE_SALARY),
     {"salary": {"amount": 80500.5, "currency": "CHF"}}),
]


@pytest.mark.parametrize("message,known,want", _DET_CASES)
def test_deterministic_extract_salary_currency(message, known, want):
    assert _deterministic_extract(message, known) == want


def test_pref_answer_chf_salary_end_to_end(monkeypatch):
    """The re-test's turn through the no-key fallback (the same
    fallback a model timeout returns): "80000 CHF" extracts as CHF,
    the salary question is answered, and the next question advances
    to pressure — the answer is never coerced to GBP."""
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    from ai.provider import ProviderAdapter

    r = pref_answer("80000 CHF", "en", known=dict(KNOWN_BEFORE_SALARY),
                    provider=ProviderAdapter())
    assert r["ai_status"] == "unavailable"
    assert r["extracted"] == {"salary": {"amount": 80000,
                                         "currency": "CHF"}}
    assert r["next_question"] == "pressure"
    assert r["done"] is False


def test_validate_known_chf_survives_eur_still_dropped():
    """A client-supplied known salary in CHF is accepted; an
    unsupported currency (EUR) is still dropped, never clamped."""
    known = validate_known({"salary": 80000, "salaryCurrency": "CHF"})
    assert known["salary"] == 80000
    assert known["salaryCurrency"] == "CHF"
    known = validate_known({"salary": 80000, "salaryCurrency": "EUR"})
    assert known["salary"] is None and known["salaryCurrency"] is None
    known = validate_known({"salary": 80000, "salaryCurrency": "chf"})
    assert known["salaryCurrency"] == "CHF"


def test_validate_extracted_model_chf_survives():
    """A model extraction in CHF survives server-side validation;
    a model extraction in EUR is still dropped."""
    out = validate_extracted(
        {"salary": {"amount": 80000, "currency": "CHF"}})
    assert out["salary"] == {"amount": 80000, "currency": "CHF"}
    out = validate_extracted(
        {"salary": {"amount": 80000, "currency": "EUR"}})
    assert "salary" not in out


def test_pref_chat_schema_names_chf():
    """The model contract itself names CHF, so a model-led turn can
    extract it too — not just the deterministic fallback."""
    assert '"currency": "GBP" | "SGD" | "USD" | "CHF"' in PREF_CHAT_SCHEMA
    assert "(GBP/SGD/USD/CHF)" in PREF_CHAT_SCHEMA
    # Budget schema untouched: still the three-currency list.
    from ai.prompts import PARSE_SCHEMA

    assert '"currency": "GBP" | "SGD" | "USD" | null' in PARSE_SCHEMA
    assert "CHF" not in PARSE_SCHEMA.split('"budget"')[1].split("}")[0]


# ---------------------------------------------------------------------------
# Frontend: mapFailedPrefAnswer salary branch + SALARY_CURRENCIES
# (Node harness over the compiled frontend — same pattern as
# test_r26_w1.py). No locale keys are involved: currency options are
# rendered as the bare codes "GBP"/"SGD"/"USD"/"CHF".
# ---------------------------------------------------------------------------

_NODE_CASES = [
    # (name, text, question, profile currency, expected patch or None)
    ("re-test answer: 80000 CHF", "80000 CHF", "salary", "GBP",
     {"prefSalary": 80000, "prefSalaryCurrency": "CHF"}),
    ("lowercase chf", "80000 chf", "salary", "GBP",
     {"prefSalary": 80000, "prefSalaryCurrency": "CHF"}),
    ("GBP unchanged", "80000 GBP", "salary", "GBP",
     {"prefSalary": 80000, "prefSalaryCurrency": "GBP"}),
    ("bare number keeps GBP default", "80000", "salary", "GBP",
     {"prefSalary": 80000, "prefSalaryCurrency": "GBP"}),
    ("bare number keeps known CHF", "80000", "salary", "CHF",
     {"prefSalary": 80000, "prefSalaryCurrency": "CHF"}),
    ("no number maps to nothing", "lots", "salary", "GBP", None),
]

_NODE_HARNESS = r"""
const pc = require(OUT + '/src/components/PrefChat.js');
const chat = require(OUT + '/src/lib/chat.js');
const { emptyProfile } = require(OUT + '/src/lib/types.js');
const zh = require(FE + '/messages/zh-CN.json');
const t = (k) => zh[k] ?? k;
const cases = JSON.parse(process.argv[2]);
let fail = 0;
for (const [name, text, q, cur, want] of cases) {
  const profile = { ...emptyProfile, prefSalaryCurrency: cur };
  const got = pc.mapFailedPrefAnswer(text, q, t, profile);
  const gotPatch = got ? got.patch : null;
  if (JSON.stringify(gotPatch) !== JSON.stringify(want)) {
    console.log('FAIL ' + name + ' -> ' + JSON.stringify(gotPatch) + ' want ' + JSON.stringify(want));
    fail++;
  } else {
    console.log('PASS ' + name);
  }
}
// SALARY_CURRENCIES is module-private: exercise it through
// knownFromProfile — CHF must pass through, EUR must not.
const chf = chat.knownFromProfile({ ...emptyProfile, prefSalary: 80000, prefSalaryCurrency: 'CHF' });
if (chf.salaryCurrency !== 'CHF') { console.log('FAIL knownFromProfile CHF -> ' + chf.salaryCurrency); fail++; }
else { console.log('PASS knownFromProfile CHF'); }
const eur = chat.knownFromProfile({ ...emptyProfile, prefSalary: 80000, prefSalaryCurrency: 'EUR' });
if (eur.salaryCurrency !== null) { console.log('FAIL knownFromProfile EUR -> ' + eur.salaryCurrency); fail++; }
else { console.log('PASS knownFromProfile EUR dropped'); }
const gbp = chat.knownFromProfile({ ...emptyProfile, prefSalary: 80000, prefSalaryCurrency: 'GBP' });
if (gbp.salaryCurrency !== 'GBP') { console.log('FAIL knownFromProfile GBP -> ' + gbp.salaryCurrency); fail++; }
else { console.log('PASS knownFromProfile GBP'); }
process.exit(fail ? 1 : 0);
"""


def _compile_frontend(tmp_path):
    outdir = tmp_path / "r27_w3_frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/components/PrefChat.tsx", "src/lib/chat.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    return outdir


def test_failed_salary_answer_mapping_and_currency_list(tmp_path):
    """The frontend backstop: a timed-out "80000 CHF" turn is
    preserved as CHF (not GBP), a bare number keeps the GBP default,
    and CHF passes the shared currency list."""
    outdir = _compile_frontend(tmp_path)
    harness = tmp_path / "r27_w3_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(FE))), encoding="utf-8")
    env = {"PATH": os.environ["PATH"],
           "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness), json.dumps(_NODE_CASES, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout


def test_chf_option_in_both_salary_forms():
    """Both salary currency chip lists (the model-led input and the
    guided form) offer CHF alongside GBP/SGD/USD. The lists are
    literal arrays in PrefChat.tsx — checked in source, since the
    chips render the bare codes with no locale key involved."""
    src = (FE / "src/components/PrefChat.tsx").read_text(encoding="utf-8")
    lists = re.findall(
        r"\(\['GBP', 'SGD', 'USD', 'CHF'\] as const\)", src)
    assert len(lists) == 2, (
        f"expected 2 salary currency lists with CHF, found {len(lists)}")
    # The bare-number default is still GBP in both places.
    assert "?? 'GBP'" in src
    # The budget currency select on the wizard page is untouched:
    # still the three-currency list, no CHF.
    wizard = (FE / "src/app/wizard/page.tsx").read_text(encoding="utf-8")
    assert '<option value="GBP">GBP</option><option value="SGD">SGD</option><option value="USD">USD</option>' in wizard
