"""Round 23 W3 regression tests (re-test task 17, 2026-11-27).

The English /results preference summary read
"Cool · Switzerland · 环境很美·大学城·校园氛围 · University town ·
campus vibe · Zurich" — the stored countries note, kept verbatim in
the language the user typed it in, joined raw into a summary whose
every other part renders through t(). The Round 10/13 containment
dedupe could not catch it: it compares the note against the label in
the active locale's words, so in a non-Chinese locale the Chinese
note and the English label share nothing. The fix (localiseCountryNote
in frontend/src/lib/preferences.ts, used by prefSummary — the single
place that builds the summary for the results page, the report page,
PrefChat step 8 and the pet alike) renders the note's known reason
phrases through the active locale's strings (wizard.note* keys), keeps
a phrase already in the active locale verbatim, and drops an unknown
phrase that is in a foreign script — a foreign-script fragment can
never be rendered in-locale, so it is dropped from the derived summary
(it stays stored, and the chat still shows the user's own words).

Covers, with no API key and no network, via a node harness over the
compiled frontend (same pattern as tests/test_r13_pref_summary.py):

- The audit profile renders with zero CJK in en/es/fr/pt-BR/ar and
  the known-correct Chinese string is unchanged in zh-CN.
- The reverse direction: an English-stored note renders Chinese in
  zh-CN, with no Latin fragment left (other than the city name, which
  renders in English by the established untranslated-city rule).
- Unknown free text in a foreign script is dropped from the summary
  instead of leaking (zh "想去看看雪山" in en).
- Legacy '；'-joined notes localise segment by segment, like '·'.
- The Round 13/14 zh pins still hold verbatim (a phrase already in
  zh is never rewritten; '、'/'，' punctuation stays one atom).
- The NOTE_PHRASE_FORMS table mirrors frontend/messages/*.json: every
  canonical form equals the messages value for that locale and key.

Run from the project root:
    .venv/bin/pytest tests/test_r23_w3_pref_summary_locale.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]

# Audit profile (re-test task 17): cool / Switzerland / reason 环境很美 /
# university-town + campus vibe / Zurich.
_AUDIT_PREFS = {
    "prefClimate": "cool",
    "prefCountries": ["CH"],
    "prefCountriesNote": "环境很美·大学城·校园氛围",
    "prefEnvironment": "campus",
    "prefCity": "Zurich",
}

_AUDIT_WANT = {
    "en": "Cool · Switzerland · Beautiful environment · University town · campus vibe · Zurich",
    "zh-CN": "凉爽 · 瑞士 · 环境很美·大学城·校园氛围 · 苏黎世",
    "es": "Fresco · Suiza · Entorno hermoso · Ciudad universitaria · ambiente de campus · Zurich",
    "fr": "Frais · Suisse · Bel environnement · Ville universitaire · ambiance campus · Zurich",
    "pt-BR": "Fresco · Suíça · Ambiente bonito · Cidade universitária · clima de campus · Zurich",
    "ar": "بارد · سويسرا · بيئة جميلة · مدينة جامعية · أجواء الحرم الجامعي · Zurich",
}

# (name, locale, pref patch, expected summary) — single-locale cases.
_CASES = [
    ("zh pin (R13): note identical to the campus label is dropped",
     "zh-CN",
     {"prefCountries": ["CH"], "prefCountriesNote": "大学城·校园氛围", "prefEnvironment": "campus"},
     "瑞士 · 大学城·校园氛围"),
    ("zh pin (R13): note joined with '·' loses only the duplicated segment",
     "zh-CN",
     {"prefCountries": ["CH"], "prefCountriesNote": "环境优美·校园氛围", "prefEnvironment": "campus"},
     "瑞士 · 环境优美 · 大学城·校园氛围"),
    ("zh pin (R14): a note with '、' punctuation stays one atom",
     "zh-CN",
     {"prefCountries": ["CH"], "prefCountriesNote": "空气清新、湖光山色、安静宜居"},
     "瑞士 · 空气清新、湖光山色、安静宜居"),
    ("zh pin (R13): a note that adds words is kept whole",
     "zh-CN",
     {"prefCountries": ["CH"], "prefCountriesNote": "想去看看雪山", "prefEnvironment": "campus"},
     "瑞士 · 想去看看雪山 · 大学城·校园氛围"),
    ("zh pin (R13): '环境优美' is the user's own wording, never rewritten",
     "zh-CN",
     {"prefCountries": ["CH"], "prefCountriesNote": "环境优美", "prefEnvironment": "campus"},
     "瑞士 · 环境优美 · 大学城·校园氛围"),
    ("en: variant '环境优美' localises like '环境很美'",
     "en",
     {"prefCountries": ["CH"], "prefCountriesNote": "环境优美·校园氛围", "prefEnvironment": "campus"},
     "Switzerland · Beautiful environment · University town · campus vibe"),
    ("en: legacy '；'-joined note localises segment by segment",
     "en",
     {"prefCountries": ["CH"], "prefCountriesNote": "环境优美；校园氛围", "prefEnvironment": "campus"},
     "Switzerland · Beautiful environment · University town · campus vibe"),
    ("en: unknown Chinese free text is dropped, not leaked",
     "en",
     {"prefCountries": ["CH"], "prefCountriesNote": "想去看看雪山"},
     "Switzerland"),
    ("zh: English-stored note renders Chinese, no Latin fragment",
     "zh-CN",
     {"prefCountries": ["CH"],
      "prefCountriesNote": "Beautiful environment·University town·Campus vibe",
      "prefEnvironment": "campus", "prefCity": "Zurich"},
     "瑞士 · 环境很美 · 大学城·校园氛围 · 苏黎世"),
    ("en: note without an environment still keeps its translated reason",
     "en",
     {"prefCountries": ["CH"], "prefCountriesNote": "环境很美·大学城·校园氛围"},
     "Switzerland · Beautiful environment·University town·Campus vibe"),
]

_NODE_HARNESS = r"""
const prefs = require(OUT + '/preferences.js');
const { emptyProfile } = require(OUT + '/types.js');
const en = require(FE + '/messages/en.json');
const locales = JSON.parse(process.argv[2]);
const auditPrefs = JSON.parse(process.argv[3]);
const auditWant = JSON.parse(process.argv[4]);
const cases = JSON.parse(process.argv[5]);
const CJK = /[\u2E80-\u9FFF\uF900-\uFAFF]/;
let fail = 0;
// Audit profile: exact string per locale, and no CJK outside zh-CN.
for (const loc of locales) {
  const msgs = require(FE + '/messages/' + loc + '.json');
  const t = (k) => msgs[k] ?? en[k] ?? k;
  const got = prefs.prefSummary({ ...emptyProfile, ...auditPrefs }, t);
  if (got !== auditWant[loc]) {
    console.log('FAIL audit ' + loc + ' -> ' + JSON.stringify(got) + ' want ' + JSON.stringify(auditWant[loc]));
    fail++;
  } else {
    console.log('PASS audit ' + loc);
  }
  if (loc !== 'zh-CN' && CJK.test(got)) {
    console.log('FAIL audit ' + loc + ' contains CJK: ' + JSON.stringify(got));
    fail++;
  }
}
// Single-locale cases.
for (const [name, loc, patch, want] of cases) {
  const msgs = require(FE + '/messages/' + loc + '.json');
  const t = (k) => msgs[k] ?? en[k] ?? k;
  const got = prefs.prefSummary({ ...emptyProfile, ...patch }, t);
  if (got !== want) {
    console.log('FAIL ' + name + ' -> ' + JSON.stringify(got) + ' want ' + JSON.stringify(want));
    fail++;
  } else {
    console.log('PASS ' + name);
  }
}
// The phrase table mirrors the messages files: every canonical form
// equals the messages value for that locale and key.
for (const { key, forms } of prefs.NOTE_PHRASE_FORMS) {
  for (const loc of locales) {
    const msgs = require(FE + '/messages/' + loc + '.json');
    const canonical = forms[loc] && forms[loc][0];
    if (msgs[key] === undefined) {
      console.log('FAIL messages/' + loc + '.json missing key ' + key);
      fail++;
    } else if (canonical !== msgs[key]) {
      console.log('FAIL table/mirror drift ' + key + ' ' + loc + ': table ' + JSON.stringify(canonical) + ' vs messages ' + JSON.stringify(msgs[key]));
      fail++;
    }
  }
}
console.log('PASS phrase table mirrors messages files');
process.exit(fail ? 1 : 0);
"""


def test_r23_w3_pref_summary_locale(tmp_path):
    """Round 23 W3: the audit summary is fully localised in all 6
    locales, and the Chinese summary is unchanged."""
    outdir = tmp_path / "r23_w3_pref"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/preferences.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r23_w3_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(fe))), encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"],
           "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness),
         json.dumps(_LOCALES, ensure_ascii=False),
         json.dumps(_AUDIT_PREFS, ensure_ascii=False),
         json.dumps(_AUDIT_WANT, ensure_ascii=False),
         json.dumps(_CASES, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
