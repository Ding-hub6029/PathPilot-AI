"""Round 13 regression tests (re-test task 7, 2026-11-26 23:30-23:45 CST).

Covers, with no API key and no network, via a node harness over the
compiled frontend (same pattern as tests/test_p0_retest6.py):

- P1: preference-summary dedupe. The audit summary read
  "凉爽 · 瑞士 · 环境优美；校园氛围 · 大学城·校园氛围 · 苏黎世 ·
  留在留学国家 · 60000 GBP · 适中 · 小班研讨" — "校园氛围" twice
  (standalone AND inside "大学城·校园氛围"). Root cause: the Round 10
  containment dedupe compared WHOLE parts, but the countries note is
  built by joining reasons with '；', so one part ("环境优美；校园氛围")
  held two values and neither whole string contains the other. The fix
  splits parts into atoms on the joining separators before deduping,
  in the single place that builds the summary (prefSummary in
  frontend/src/lib/preferences.ts — used by the results page, the
  report page, PrefChat and the pet alike).
- P2 (minor): the why-follow-up rule (shouldAskCountryWhy in
  frontend/src/lib/chat.ts). A reason that arrived in the SAME turn
  as the countries ("瑞士，环境优美") no longer suppresses the
  follow-up — the chat confirmed the phrase but never asked what it
  means, and went straight to climate. Only a reason recorded in an
  EARLIER turn suppresses it.

Run from the project root:
    .venv/bin/pytest tests/test_r13_pref_summary.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Audit profile (re-test task 7): China Gaokao, UG, CS, 680/750,
# IELTS 7.0, budget GBP 50,000, 2027, overseas, Switzerland / cool /
# university-town / Zurich. Only the preference fields feed the
# summary; the academic fields are listed to pin the profile.
_AUDIT_PREFS = {
    "prefClimate": "cool",
    "prefCountries": ["CH"],
    "prefCountriesNote": "环境优美；校园氛围",
    "prefEnvironment": "campus",
    "prefCity": "Zurich",
    "prefAfterGrad": "stay",
    "prefSalary": 60000,
    "prefSalaryCurrency": "GBP",
    "prefPressure": "medium",
    "prefTeaching": "seminar",
}

_SUMMARY_CASES = [
    # (name, pref patch, expected summary)
    ("audit profile: 校园氛围 exactly once",
     _AUDIT_PREFS,
     "凉爽 · 瑞士 · 环境优美 · 大学城·校园氛围 · 苏黎世 · 留在留学国家 · 60000 GBP · 适中 · 小班研讨"),
    ("note identical to the campus label is dropped",
     {"prefCountries": ["CH"], "prefCountriesNote": "大学城·校园氛围", "prefEnvironment": "campus"},
     "瑞士 · 大学城·校园氛围"),
    ("verbatim environment '校园氛围' plus a distinct note",
     {"prefCountries": ["CH"], "prefCountriesNote": "环境优美", "prefEnvironment": "校园氛围"},
     "瑞士 · 环境优美 · 校园氛围"),
    ("note joined with '·' loses only the duplicated segment",
     {"prefCountries": ["CH"], "prefCountriesNote": "环境优美·校园氛围", "prefEnvironment": "campus"},
     "瑞士 · 环境优美 · 大学城·校园氛围"),
    ("Round 14: a note with '、' punctuation stays one atom",
     {"prefCountries": ["CH"], "prefCountriesNote": "空气清新、湖光山色、安静宜居"},
     "瑞士 · 空气清新、湖光山色、安静宜居"),
    ("Round 14: a note with '，' punctuation stays one atom",
     {"prefCountries": ["CH"], "prefCountriesNote": "空气清新，湖光山色"},
     "瑞士 · 空气清新，湖光山色"),
    ("a note that adds words is kept whole",
     {"prefCountries": ["CH"], "prefCountriesNote": "想去看看雪山", "prefEnvironment": "campus"},
     "瑞士 · 想去看看雪山 · 大学城·校园氛围"),
    ("multi-country list keeps its ', ' join",
     {"prefCountries": ["CH", "GB"], "prefClimate": "cool"},
     "凉爽 · 瑞士, 英国"),
    ("no preferences, empty summary",
     {},
     ""),
]

_WHY_CASES = [
    # (name, new countries, prior note, expected)
    ("new country, no prior note -> ask", ["CH"], None, True),
    ("new country, empty prior note -> ask", ["CH"], "", True),
    ("new country, blank prior note -> ask", ["CH"], "   ", True),
    ("new country, reason from an earlier turn -> no ask", ["CH"], "环境优美", False),
    ("no new country -> no ask", [], None, False),
    ("already-known country re-added -> no ask", [], "环境优美", False),
]

_NODE_HARNESS = r"""
const prefs = require(OUT + '/preferences.js');
const chat = require(OUT + '/chat.js');
const { emptyProfile } = require(OUT + '/types.js');
const zh = require(FE + '/messages/zh-CN.json');
const t = (k) => zh[k] ?? k;
const [summaryCases, whyCases] = JSON.parse(process.argv[2]);
let fail = 0;
for (const [name, patch, want] of summaryCases) {
  const profile = { ...emptyProfile, ...patch };
  const got = prefs.prefSummary(profile, t);
  if (got !== want) {
    console.log('FAIL ' + name + ' -> ' + JSON.stringify(got) + ' want ' + JSON.stringify(want));
    fail++;
  } else {
    console.log('PASS ' + name);
  }
}
// The audit summary must contain 校园氛围 exactly once.
const audit = prefs.prefSummary({ ...emptyProfile, ...JSON.parse(process.argv[3]) }, t);
const count = (audit.match(/校园氛围/g) || []).length;
if (count !== 1) {
  console.log('FAIL audit 校园氛围 count=' + count + ' in ' + JSON.stringify(audit));
  fail++;
} else {
  console.log('PASS audit 校园氛围 count=1');
}
for (const [name, countries, priorNote, want] of whyCases) {
  const got = chat.shouldAskCountryWhy(countries, priorNote === null ? undefined : priorNote);
  if (got !== want) {
    console.log('FAIL ' + name + ' -> ' + JSON.stringify(got) + ' want ' + JSON.stringify(want));
    fail++;
  } else {
    console.log('PASS ' + name);
  }
}
process.exit(fail ? 1 : 0);
"""


def test_r13_pref_summary_dedupe_and_why_rule(tmp_path):
    """Round 13: the audit summary shows 校园氛围 once, and the
    why-follow-up rule fires for a same-turn reason."""
    outdir = tmp_path / "r13_pref"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/preferences.ts", "src/lib/chat.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r13_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(fe))), encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"],
           "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness),
         json.dumps([_SUMMARY_CASES, _WHY_CASES], ensure_ascii=False),
         json.dumps(_AUDIT_PREFS, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
