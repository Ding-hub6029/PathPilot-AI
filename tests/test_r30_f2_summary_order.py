"""Round 30 F2 regression tests (re-test 24 item a, 2026-11-28).

The wizard summary read
"凉爽 · 瑞士 · 环境优美 · 大学城·校园氛围 · 苏黎世 · 留在留学国家 ·
80000 CHF · 适中 · 小班研讨" — climate first, instead of the question
order. Root cause: ``prefSummary`` in
``frontend/src/lib/preferences.ts`` pushed its parts in field order
(climate, countries, note, environment, city, afterGrad, salary,
pressure, teaching), not in the order the wizard asks the 8 questions.
The fix extracts the part-building into the exported pure helper
``prefSummaryParts`` (same file), which pushes in the canonical
question order — countries, reason (the countries note), climate,
environment, city, afterGrad, salary, pressure, teaching — and
``prefSummary`` composes from it. Render/composition time only: the
stored Profile shape, the dedupe, and the localisation are untouched.

Covers, with no API key and no network, via a node harness over the
compiled frontend (same pattern as tests/test_r13_pref_summary.py):

- the re-test 24 profile renders in exact canonical order in zh-CN
  and en (the defect's own string, reordered);
- ``prefSummaryParts`` returns its part texts in exactly the
  canonical order for the full profile;
- a partial profile (countries + climate only) still reads
  countries before climate — the order is a property of the
  composer, not of a complete profile;
- calling the summary does not mutate the stored profile;
- source pins: ``prefSummary`` delegates to ``prefSummaryParts``,
  and the helper's pushes are in canonical order.

Run from the project root:
    .venv/bin/pytest tests/test_r30_f2_summary_order.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The re-test 24 profile: Switzerland / reason 环境优美 / cool /
# university-town / Zurich / stay / 80000 CHF / medium / seminar.
_AUDIT_PREFS = {
    "prefCountries": ["CH"],
    "prefCountriesNote": "环境优美",
    "prefClimate": "cool",
    "prefEnvironment": "campus",
    "prefCity": "Zurich",
    "prefAfterGrad": "stay",
    "prefSalary": 80000,
    "prefSalaryCurrency": "CHF",
    "prefPressure": "medium",
    "prefTeaching": "seminar",
}

_AUDIT_WANT = {
    "zh-CN": "瑞士 · 环境优美 · 凉爽 · 大学城·校园氛围 · 苏黎世 · 留在留学国家 · 80000 CHF · 适中 · 小班研讨",
    "en": "Switzerland · Beautiful environment · Cool · University town · campus vibe · Zurich · Stay in the country where I study · 80000 CHF · Moderate · Small seminars",
}

# (name, locale, pref patch, expected summary)
_CASES = [
    ("partial: countries + climate only, countries first",
     "zh-CN", {"prefCountries": ["CH"], "prefClimate": "cool"},
     "瑞士 · 凉爽"),
    ("partial: climate + teaching only, climate first",
     "zh-CN", {"prefClimate": "cool", "prefTeaching": "seminar"},
     "凉爽 · 小班研讨"),
    ("multi-country: list, then reason, then climate",
     "zh-CN", {"prefCountries": ["CH", "GB"], "prefCountriesNote": "环境优美", "prefClimate": "cool"},
     "瑞士 · 英国 · 环境优美 · 凉爽"),
    ("note without climate: countries, reason, environment",
     "zh-CN", {"prefCountries": ["CH"], "prefCountriesNote": "环境优美", "prefEnvironment": "campus"},
     "瑞士 · 环境优美 · 大学城·校园氛围"),
    ("salary + pressure + teaching keep question order",
     "en", {"prefSalary": 80000, "prefSalaryCurrency": "CHF",
            "prefPressure": "medium", "prefTeaching": "seminar"},
     "80000 CHF · Moderate · Small seminars"),
    ("no preferences, empty summary",
     "zh-CN", {},
     ""),
]

_NODE_HARNESS = r"""
const prefs = require(OUT + '/preferences.js');
const { emptyProfile } = require(OUT + '/types.js');
const en = require(FE + '/messages/en.json');
const auditPrefs = JSON.parse(process.argv[2]);
const auditWant = JSON.parse(process.argv[3]);
const cases = JSON.parse(process.argv[4]);
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + ' -> ' + g + ' want ' + w); fail++; }
  else console.log('PASS ' + name);
};
const tFor = (loc) => {
  const msgs = require(FE + '/messages/' + loc + '.json');
  return (k) => msgs[k] ?? en[k] ?? k;
};
// The audit profile: exact string per locale, in question order.
for (const loc of ['zh-CN', 'en']) {
  check('audit ' + loc,
    prefs.prefSummary({ ...emptyProfile, ...auditPrefs }, tFor(loc), loc), auditWant[loc]);
}
// The helper itself returns parts in exactly the canonical order.
const partsZh = prefs.prefSummaryParts({ ...emptyProfile, ...auditPrefs }, tFor('zh-CN'), 'zh-CN');
check('prefSummaryParts order zh',
  partsZh.map((p) => p.text),
  ['瑞士', '环境优美', '凉爽', '大学城·校园氛围', '苏黎世', '留在留学国家', '80000 CHF', '适中', '小班研讨']);
const partsEn = prefs.prefSummaryParts({ ...emptyProfile, ...auditPrefs }, tFor('en'), 'en');
check('prefSummaryParts order en',
  partsEn.map((p) => p.text),
  ['Switzerland', 'Beautiful environment', 'Cool', 'University town · campus vibe', 'Zurich', 'Stay in the country where I study', '80000 CHF', 'Moderate', 'Small seminars']);
// Only the note part is tagged fromNote (the dedupe's only input).
check('prefSummaryParts fromNote tags',
  partsZh.map((p) => p.fromNote),
  [false, true, false, false, false, false, false, false, false]);
// Partial profiles keep the same relative order.
for (const [name, loc, patch, want] of cases) {
  check(name, prefs.prefSummary({ ...emptyProfile, ...patch }, tFor(loc), loc), want);
}
// The summary never mutates the stored profile.
const profile = { ...emptyProfile, ...auditPrefs };
const before = JSON.stringify(profile);
prefs.prefSummary(profile, tFor('zh-CN'), 'zh-CN');
prefs.prefSummaryParts(profile, tFor('zh-CN'), 'zh-CN');
check('profile unchanged by summary', JSON.stringify(profile), before);
if (fail) { console.log(fail + ' FAILURES'); process.exit(1); }
console.log('ALL R30 F2 HARNESS CASES PASS');
"""


def test_r30_f2_summary_order(tmp_path):
    """Round 30 F2: the wizard summary reads in canonical question
    order — countries, reason, climate, environment, city, afterGrad,
    salary, pressure, teaching."""
    outdir = tmp_path / "r30_f2_pref"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/preferences.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r30_f2_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(fe))), encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"],
           "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness),
         json.dumps(_AUDIT_PREFS, ensure_ascii=False),
         json.dumps(_AUDIT_WANT, ensure_ascii=False),
         json.dumps(_CASES, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout


def test_r30_f2_summary_order_source_pin():
    """Source pin: prefSummary delegates to prefSummaryParts, and the
    helper pushes its parts in canonical question order (countries,
    reason, climate, environment, city, afterGrad, salary, pressure,
    teaching) — so a future push can never silently re-scramble it."""
    src = (ROOT / "frontend/src/lib/preferences.ts").read_text(encoding="utf-8")
    assert "export function prefSummaryParts(" in src
    assert "const parts = prefSummaryParts(profile, t, locale);" in src
    helper = src.split("export function prefSummaryParts(")[1].split(
        "\nexport function prefSummary(")[0]
    pushes = [
        "if (profile.prefCountries?.length) parts.push",
        "if (note) parts.push",
        "if (profile.prefClimate) parts.push",
        "if (profile.prefEnvironment) parts.push",
        "if (profile.prefCity) parts.push",
        "if (profile.prefAfterGrad) parts.push",
        "if (profile.prefSalary !== '' && profile.prefSalary !== undefined) parts.push",
        "if (profile.prefPressure) parts.push",
        "if (profile.prefTeaching) parts.push",
    ]
    idx = [helper.index(p) for p in pushes]
    assert all(i >= 0 for i in idx), "a canonical-order push is missing from prefSummaryParts"
    assert idx == sorted(idx), "prefSummaryParts pushes are not in canonical question order"
    # prefSummary itself builds no parts any more — the order lives in
    # exactly one place.
    body = src.split("export function prefSummary(")[1].split("\n// --- Countries-note")[0]
    assert "parts.push" not in body
