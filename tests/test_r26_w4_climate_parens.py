"""Round 26 W4 (i): English wizard climate reply typography.

Re-test 20 (2026-11-27): the English wizard's climate no-match answer
rendered "Zurich （Four seasons） , Lausanne （Four seasons） ." —
full-width parentheses in an English sentence. Root cause was
frontend-only: ``PrefChat.tsx`` built the city list with a hard-coded
``${city}（${climateLabel}）`` template in every locale, while the
backend evidence line (``ai.chat._CITY_ITEM``) already used
half-width parens outside zh-CN.

Fix: ``frontend/src/lib/format.ts`` gains ``parenNote(name, note,
locale)`` — full-width （） with no space in zh-CN, half-width ()
with a space everywhere else (the same rule
``localiseDurationParen`` already uses) — and the PrefChat
climate no-match site uses it.

Covers, with no API key and no network:

- ``parenNote`` in all 6 locales, via a node harness over the
  compiled ``frontend/src/lib/format.ts`` (same pattern as
  tests/test_r24_w2_list_separator.py): exact strings, no
  full-width paren outside zh-CN, no half-width paren in zh-CN;
- the PrefChat call site uses ``parenNote`` and the hard-coded
  full-width template is gone;
- the backend cities evidence line was already correct in en
  (no full-width paren) — the pin that the bug was frontend-only.

Run from the project root:
    .venv/bin/pytest tests/test_r26_w4_climate_parens.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ai.chat import _climate_evidence, evidence_cities_line

ROOT = Path(__file__).resolve().parents[1]

# (locale, city, climate label) -> exact expected rendering.
CASES = {
    "en": ("Zurich", "Four seasons", "Zurich (Four seasons)"),
    "zh-CN": ("苏黎世", "四季分明", "苏黎世（四季分明）"),
    "es": ("Zurich", "Cuatro estaciones", "Zurich (Cuatro estaciones)"),
    "fr": ("Zurich", "Quatre saisons", "Zurich (Quatre saisons)"),
    "pt-BR": ("Zurich", "Quatro estações", "Zurich (Quatro estações)"),
    "ar": ("Zurich", "فصول أربعة", "Zurich (فصول أربعة)"),
}


_NODE_HARNESS = r"""
const fmt = require(OUT + '/format.js');
const cases = JSON.parse(process.argv[2]);
let fail = 0;
for (const [loc, city, label, want] of cases) {
  const got = fmt.parenNote(city, label, loc);
  if (got !== want) {
    console.log('FAIL parenNote ' + loc + ' -> ' + JSON.stringify(got) + ' want ' + JSON.stringify(want));
    fail++;
  } else {
    console.log('PASS parenNote ' + loc);
  }
  if (loc === 'zh-CN') {
    if (got.includes('(') || got.includes(')')) { console.log('FAIL parenNote zh-CN leaks half-width parens: ' + JSON.stringify(got)); fail++; }
  } else {
    if (got.includes('（') || got.includes('）')) { console.log('FAIL parenNote ' + loc + ' leaks full-width parens: ' + JSON.stringify(got)); fail++; }
  }
}
// Unknown locale falls back to the half-width form, never full-width.
const fb = fmt.parenNote('Zurich', 'Four seasons', 'xx');
if (fb !== 'Zurich (Four seasons)') { console.log('FAIL parenNote fallback -> ' + JSON.stringify(fb)); fail++; }
if (fail) process.exit(1);
console.log('FRONTEND OK');
"""


def test_frontend_paren_note_all_locales(tmp_path):
    outdir = tmp_path / "r26_w4_format"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/format.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r26_w4_harness.js"
    harness.write_text(
        _NODE_HARNESS.replace("OUT", repr(str(outdir))), encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"],
           "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness),
         json.dumps([[loc, city, label, want]
                     for loc, (city, label, want) in CASES.items()],
                    ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout


def test_prefchat_climate_no_match_uses_paren_note():
    pref = (ROOT / "frontend/src/components/PrefChat.tsx").read_text(encoding="utf-8")
    assert "parenNote(cityDisplayName(city, t), climateLabel(climate, t), locale)" in pref
    # The hard-coded full-width template is gone from this file.
    assert "（${climateLabel" not in pref
    assert "import { joinList, parenNote } from '../lib/format';" in pref


def test_backend_cities_line_was_already_correct_in_en():
    """The backend was not the source: its en cities line already
    uses half-width parens (``_CITY_ITEM``), so the re-test-20
    rendering could only have come from the frontend template."""
    sources, _ = _climate_evidence("cool", countries=["CH"])
    line = evidence_cities_line(sources, "en")
    assert line is not None
    assert "Zurich (four-season, 14 programmes, all levels/fields)" in line
    assert "Lausanne (four-season, 11 programmes, all levels/fields)" in line
    assert "（" not in line and "）" not in line, line
    zh = evidence_cities_line(sources, "zh-CN")
    assert zh is not None
    # zh-CN keeps full-width parens — the fix must not flatten it.
    assert "苏黎世（四季分明，14 个项目，全部学位/方向）" in zh, zh
