"""Round 27 W4: untranslated stored choice values after a language switch.

Re-test 21 (2026-11-28 00:28-00:39 CST): after switching to English,
the wizard replay left the 苏黎世 and 适中 choice bubbles in Chinese
while Cool / University town translated, and the English /results
preference line still showed 苏黎世 untranslated.

Root cause (two frozen-string paths, same defect as Round 26 W4's
level bubble, which stored a tap-time label as a verbatim turn):

1. A choice chip sends its LOCALISED label as the message, and the
   model-led turn stores that string verbatim as ``PrefTurn.question``
   (``PrefChat.tsx``); the guided history stores the same label in
   ``verbatim[q]`` via ``preserveFailedAnswer`` and renders
   ``verbatim[q] ?? answerText(q)``. After a locale switch both
   bubbles stay in the tap-time locale. Enum answers stored as
   canonical values (climate ``cool``, environment ``campus``) already
   re-localised through ``answerText`` — only the frozen strings did
   not.
2. ``cityDisplayName`` could only localise a CANONICAL English city
   name: a stored localised name ("苏黎世", stored by a failed turn's
   ``mapFailedPrefAnswer``) has no ``city.<slug>`` key, so
   ``prefSummary`` rendered it verbatim in every locale.

Fix (render time only — storage and the backend contract are
unchanged, and the persisted-turn whitelist in ``lib/chat.ts`` is
untouched, so old snapshots benefit too):

- ``frontend/src/lib/preferences.ts`` gains the reverse map
  ``CHOICE_LABEL_REVERSE`` (every choice label in every locale ->
  its canonical ``group:value``; generated from
  ``frontend/messages/*.json``), ``choiceRefsForLabel`` (exact-match
  reverse lookup), ``choiceLabelFor`` (forward label for one
  canonical choice), and ``canonicalCityName``. ``cityDisplayName``
  reverse-maps a stored localised city name to canonical first,
  then localises it in the current locale — so ``prefSummary`` shows
  "Zurich" in English for a stored "苏黎世".
- ``frontend/src/components/PrefChat.tsx`` gains exported pure
  helpers ``prefTurnUserText`` (a model-led user bubble renders its
  choice's current-locale label when the message is exactly one
  known choice label, else verbatim) and ``isBareChoiceLabel``
  (a guided-history string is a bare label for the stored answer).
  The model-led user bubble and the guided history bubble render
  through them; ``turn.question`` is still the verbatim message
  re-sent to the backend on a locale-switch re-fetch.

Deliberately unchanged: user-typed free text stays verbatim (a
sentence that merely contains a label never matches — matching is
exact); a bare synonym the user typed ("大学城", "动手") is the
user's own word, not a chip label, and stays verbatim; an ambiguous
label ("新加坡" is both the SG country name and the Singapore city
name; "香港" both HK and Hong Kong) stays verbatim when the question
is unknown. ``CompassPet.tsx`` needed no change: its chips already
push structured choice turns rendered through ``choiceLabel``.

Covers, with no API key and no network:

- node harness over compiled ``lib/preferences.ts`` (same pattern as
  tests/test_r23_w3_pref_summary_locale.py): ``cityDisplayName``
  both directions for stored localised and canonical cities,
  ``choiceRefsForLabel`` / ``choiceLabelFor`` / ``canonicalCityName``
  (incl. the ambiguous and free-text cases), and the ``prefSummary``
  audit for the re-test profile in en + zh;
- node harness over compiled ``PrefChat.tsx`` (same pattern as
  tests/test_r26_w1.py): ``prefTurnUserText`` and
  ``isBareChoiceLabel`` on the re-test values;
- the reverse table is re-derived from the locale files in Python
  and must equal the shipped table exactly, every relied-on key
  exists in all 6 locale files, the city reverse map is injective,
  and no non-English city label collides with a canonical English
  city name;
- source pins on the two render spots and on the unchanged
  ``question: trimmed`` backend contract.

Run from the project root:
    .venv/bin/pytest tests/test_r27_w4.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
LOCALES = ("en", "zh-CN", "es", "fr", "pt-BR", "ar")

_ENUM_KEYS: dict[str, dict[str, str]] = {
    "climate": {
        "warm": "wizard.prefClimateWarm", "cool": "wizard.prefClimateCool",
        "four_seasons": "wizard.prefClimateFourSeasons", "mild": "wizard.prefClimateMild",
    },
    "environment": {
        "big_city": "wizard.prefEnvironmentBigCity", "small_city": "wizard.prefEnvironmentSmallCity",
        "campus": "wizard.prefEnvironmentCampus", "quiet_town": "wizard.prefEnvironmentQuietTown",
    },
    "afterGrad": {
        "stay": "wizard.prefAfterGradStay", "return_home": "wizard.prefAfterGradReturnHome",
        "hometown": "wizard.prefAfterGradHometown", "undecided": "wizard.prefAfterGradUndecided",
    },
    "pressure": {
        "low": "wizard.prefPressureLow", "medium": "wizard.prefPressureMedium",
        "high": "wizard.prefPressureHigh",
    },
    "teaching": {
        "lecture": "wizard.prefTeachingLecture", "seminar": "wizard.prefTeachingSeminar",
        "hands_on": "wizard.prefTeachingHandsOn",
    },
}
_COUNTRY_CODES = ["GB", "US", "SG", "AU", "CA", "JP", "KR", "DE", "FR", "NL", "CH", "HK"]


def _messages() -> dict[str, dict[str, str]]:
    return {
        loc: json.load(open(FE / "messages" / f"{loc}.json", encoding="utf-8"))
        for loc in LOCALES
    }


def _derive_reverse(msgs: dict[str, dict[str, str]]) -> dict[str, str]:
    """The reverse map, re-derived from the locale files (same
    construction the shipped table was generated from)."""
    from collections import defaultdict
    full: dict[str, set[str]] = defaultdict(set)
    for group, vals in _ENUM_KEYS.items():
        for value, key in vals.items():
            for loc in LOCALES:
                s = msgs[loc].get(key)
                if s:
                    full[s.strip().lower()].add(f"{group}:{value}")
    for code in _COUNTRY_CODES:
        for loc in LOCALES:
            s = msgs[loc].get(f"country.{code}")
            if s:
                full[s.strip().lower()].add(f"countries:{code}")
    for key in [k for k in msgs["en"] if k.startswith("city.")]:
        for loc in LOCALES:
            s = msgs[loc].get(key)
            if s:
                full[s.strip().lower()].add(f"city:{msgs['en'][key]}")
    return {label: "|".join(sorted(v)) for label, v in sorted(full.items())}


# The re-test profile: Switzerland + cool + campus + Zurich (stored
# localised, as a failed turn leaves it) + medium pressure, with the
# reason note in the user's own Chinese words.
_AUDIT_PREFS = {
    "prefCountries": ["CH"], "prefCountriesNote": "环境优美",
    "prefClimate": "cool", "prefEnvironment": "campus",
    "prefCity": "苏黎世", "prefPressure": "medium",
}
_AUDIT_WANT = {
    "en": "Cool · Switzerland · Beautiful environment · University town · campus vibe · Zurich · Moderate",
    "zh-CN": "凉爽 · 瑞士 · 环境优美 · 大学城·校园氛围 · 苏黎世 · 适中",
}

_PREF_CASES = [
    # (name, locale, profile patch, expected summary)
    ("en: stored-localised city localises like a canonical one",
     "en", {**_AUDIT_PREFS, "prefCountriesNote": ""},
     "Cool · Switzerland · University town · campus vibe · Zurich · Moderate"),
    ("zh: stored-localised city stays Chinese",
     "zh-CN", {**_AUDIT_PREFS, "prefCountriesNote": ""},
     "凉爽 · 瑞士 · 大学城·校园氛围 · 苏黎世 · 适中"),
    ("en: canonical stored city renders the same",
     "en", {"prefCountries": ["CH"], "prefClimate": "cool", "prefEnvironment": "campus",
            "prefCity": "Zurich", "prefPressure": "medium"},
     "Cool · Switzerland · University town · campus vibe · Zurich · Moderate"),
    ("en: unknown typed city stays the user's own spelling",
     "en", {"prefCountries": ["CH"], "prefCity": "苏州"},
     "Switzerland · 苏州"),
    ("zh: unknown typed city stays verbatim",
     "zh-CN", {"prefCountries": ["CH"], "prefCity": "苏州"},
     "瑞士 · 苏州"),
]

_CITY_CASES = [
    # (stored city, locale, expected display name)
    ("Zurich", "en", "Zurich"),
    ("Zurich", "zh-CN", "苏黎世"),
    ("苏黎世", "en", "Zurich"),
    ("苏黎世", "zh-CN", "苏黎世"),
    ("洛桑", "en", "Lausanne"),
    ("Lausanne", "zh-CN", "洛桑"),
    ("Pékin", "en", "Beijing"),
    ("北京", "en", "Beijing"),
    ("新加坡", "en", "Singapore"),
    ("新加坡", "zh-CN", "新加坡"),
    ("香港", "en", "Hong Kong"),
    ("苏州", "en", "苏州"),
    ("", "en", ""),
]

# (text, expected refs as sorted [group, value] pairs)
_LABEL_CASES = [
    ("适中", [["pressure", "medium"]]),
    ("Moderate", [["pressure", "medium"]]),
    ("Moderada", [["pressure", "medium"]]),
    ("大学城·校园氛围", [["environment", "campus"]]),
    ("University town · campus vibe", [["environment", "campus"]]),
    ("Cool", [["climate", "cool"]]),
    ("凉爽", [["climate", "cool"]]),
    ("瑞士", [["countries", "CH"]]),
    ("Switzerland", [["countries", "CH"]]),
    ("苏黎世", [["city", "Zurich"]]),
    ("Zurich", [["city", "Zurich"]]),
    ("新加坡", [["city", "Singapore"], ["countries", "SG"]]),
    ("香港", [["city", "Hong Kong"], ["countries", "HK"]]),
    ("  适中  ", [["pressure", "medium"]]),
    ("我想去瑞士，因为那边环境优美", []),
    ("瑞士有哪些好学校？", []),
    ("60000 GBP", []),
    ("随便", []),
    ("", []),
]

# (ref, locale, expected label)
_FORWARD_CASES = [
    (["pressure", "medium"], "en", "Moderate"),
    (["pressure", "medium"], "zh-CN", "适中"),
    (["city", "Zurich"], "en", "Zurich"),
    (["city", "Zurich"], "zh-CN", "苏黎世"),
    (["countries", "CH"], "en", "Switzerland"),
    (["countries", "CH"], "zh-CN", "瑞士"),
    (["environment", "campus"], "en", "University town · campus vibe"),
    (["environment", "campus"], "zh-CN", "大学城·校园氛围"),
    (["climate", "cool"], "en", "Cool"),
    (["climate", "cool"], "zh-CN", "凉爽"),
]

# (stored city, expected canonical name or None)
_CANONICAL_CASES = [
    ("苏黎世", "Zurich"),
    ("Zurich", "Zurich"),
    ("新加坡", "Singapore"),
    ("香港", "Hong Kong"),
    ("苏州", None),
    ("瑞士", None),
    ("", None),
]

_NODE_HARNESS_PREFS = r"""
const prefs = require(OUT + '/preferences.js');
const { emptyProfile } = require(OUT + '/types.js');
const en = require(FE + '/messages/en.json');
const expectedReverse = JSON.parse(process.argv[2]);
const prefCases = JSON.parse(process.argv[3]);
const cityCases = JSON.parse(process.argv[4]);
const labelCases = JSON.parse(process.argv[5]);
const forwardCases = JSON.parse(process.argv[6]);
const canonicalCases = JSON.parse(process.argv[7]);
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
// The shipped reverse table equals the table re-derived from the
// locale files (no drift, no invented labels).
check('reverse table matches locale files', prefs.CHOICE_LABEL_REVERSE, expectedReverse);
// City display names, incl. the re-test's stored-localised city.
for (const [stored, loc, want] of cityCases) {
  check('cityDisplayName ' + JSON.stringify(stored) + ' in ' + loc,
    prefs.cityDisplayName(stored, tFor(loc)), want);
}
// Reverse lookups.
for (const [text, want] of labelCases) {
  const got = prefs.choiceRefsForLabel(text)
    .map((r) => [r.group, r.value]).sort();
  check('choiceRefsForLabel ' + JSON.stringify(text), got, want);
}
// Forward labels.
for (const [[group, value], loc, want] of forwardCases) {
  check('choiceLabelFor ' + group + ':' + value + ' in ' + loc,
    prefs.choiceLabelFor({ group, value }, tFor(loc)), want);
}
// Canonical city names.
for (const [stored, want] of canonicalCases) {
  check('canonicalCityName ' + JSON.stringify(stored),
    prefs.canonicalCityName(stored), want);
}
// The /results preference line for the re-test profile.
for (const [name, loc, patch, want] of prefCases) {
  check(name, prefs.prefSummary({ ...emptyProfile, ...patch }, tFor(loc)), want);
}
if (fail) { console.log(fail + ' FAILURES'); process.exit(1); }
console.log('ALL PREFS HARNESS CASES PASS');
"""

# The re-test profile, as the wizard holds it after the failed turn.
_BARE_PROFILE = {
    "prefCountries": ["CH"], "prefClimate": "cool", "prefEnvironment": "campus",
    "prefCity": "苏黎世", "prefPressure": "medium",
    "prefAfterGrad": "undecided", "prefTeaching": "hands_on",
}
# (question, text, profile patch or null, expected)
_BARE_CASES = [
    ("pressure", "适中", None, True),
    ("pressure", "Moderate", None, True),
    ("pressure", "轻松一点", None, False),
    ("pressure", "60000", None, False),
    ("city", "苏黎世", None, True),
    ("city", "Zurich", None, True),
    ("city", "洛桑", None, False),
    ("countries", "瑞士", None, True),
    ("countries", "瑞士，因为那边环境优美", None, False),
    ("countries", "英国", None, False),
    ("environment", "大学城·校园氛围", None, True),
    ("environment", "大学城", None, False),
    ("climate", "凉爽", None, True),
    ("climate", "Cool", None, True),
    ("salary", "60000 GBP", None, False),
    ("afterGrad", "还没想好", None, True),
    ("teaching", "动手", None, False),
    ("teaching", "动手实践", None, True),
    ("city", "苏黎世", {"prefCity": "Zurich"}, True),
    ("city", "苏黎世", {"prefCity": "苏州"}, False),
    ("pressure", "适中", {"prefPressure": "low"}, False),
]

# (message text, locale, expected bubble text)
_TURN_CASES = [
    ("苏黎世", "en", "Zurich"),
    ("苏黎世", "zh-CN", "苏黎世"),
    ("适中", "en", "Moderate"),
    ("适中", "zh-CN", "适中"),
    ("Cool", "zh-CN", "凉爽"),
    ("Cool", "en", "Cool"),
    ("瑞士", "en", "Switzerland"),
    ("大学城·校园氛围", "en", "University town · campus vibe"),
    ("Zurich", "zh-CN", "苏黎世"),
    ("Moderate", "zh-CN", "适中"),
    ("新加坡", "en", "新加坡"),
    ("香港", "en", "香港"),
    ("60000 GBP", "en", "60000 GBP"),
    ("瑞士有哪些好学校？", "en", "瑞士有哪些好学校？"),
    ("我想去瑞士，因为那边环境优美", "en", "我想去瑞士，因为那边环境优美"),
    ("大学城", "en", "大学城"),
]

_NODE_HARNESS_PREFCHAT = r"""
const pc = require(OUT + '/src/components/PrefChat.js');
const { emptyProfile } = require(OUT + '/src/lib/types.js');
const en = require(FE + '/messages/en.json');
const bareCases = JSON.parse(process.argv[2]);
const turnCases = JSON.parse(process.argv[3]);
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
const baseProfile = { ...emptyProfile, ...JSON.parse(process.argv[4]) };
for (const [q, text, patch, want] of bareCases) {
  const profile = patch ? { ...baseProfile, ...patch } : baseProfile;
  check('isBareChoiceLabel ' + q + ' ' + JSON.stringify(text),
    pc.isBareChoiceLabel(q, text, profile), want);
}
for (const [text, loc, want] of turnCases) {
  check('prefTurnUserText ' + JSON.stringify(text) + ' in ' + loc,
    pc.prefTurnUserText(text, tFor(loc)), want);
}
if (fail) { console.log(fail + ' FAILURES'); process.exit(1); }
console.log('ALL PREFCHAT HARNESS CASES PASS');
"""


def _run_node_harness(tmp_path, name, sources, harness_src, argv):
    outdir = tmp_path / name
    res = subprocess.run(
        ["npx", "tsc", *sources,
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / f"{name}_harness.js"
    harness.write_text(
        harness_src
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(FE))), encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness), *argv],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout


def test_r27_w4_preferences_reverse_map(tmp_path):
    """The reverse table is exactly the locale files' choice labels,
    and the /results line localises a stored-localised city."""
    msgs = _messages()
    _run_node_harness(
        tmp_path, "r27w4_prefs", ["src/lib/preferences.ts"],
        _NODE_HARNESS_PREFS,
        [json.dumps(_derive_reverse(msgs), ensure_ascii=False),
         json.dumps(_PREF_CASES, ensure_ascii=False),
         json.dumps(_CITY_CASES, ensure_ascii=False),
         json.dumps(_LABEL_CASES, ensure_ascii=False),
         json.dumps(_FORWARD_CASES, ensure_ascii=False),
         json.dumps(_CANONICAL_CASES, ensure_ascii=False)])


def test_r27_w4_prefchat_bubbles(tmp_path):
    """Model-led user bubbles and guided-history bubbles re-localise
    a bare choice label; free text, questions and bare synonyms stay
    verbatim."""
    _run_node_harness(
        tmp_path, "r27w4_prefchat", ["src/components/PrefChat.tsx"],
        _NODE_HARNESS_PREFCHAT,
        [json.dumps(_BARE_CASES, ensure_ascii=False),
         json.dumps(_TURN_CASES, ensure_ascii=False),
         json.dumps(_BARE_PROFILE, ensure_ascii=False)])


def test_r27_w4_locale_keys_and_table_shape():
    """Every key the reverse map relies on exists, non-empty, in all
    6 locale files; the city reverse map is injective; no
    non-English city label collides with a canonical English city
    name; the only ambiguous labels are the known HK / SG pairs."""
    msgs = _messages()
    for group, vals in _ENUM_KEYS.items():
        for value, key in vals.items():
            for loc in LOCALES:
                assert msgs[loc].get(key), f"{key} missing in {loc} ({group}:{value})"
    for code in _COUNTRY_CODES:
        for loc in LOCALES:
            assert msgs[loc].get(f"country.{code}"), f"country.{code} missing in {loc}"
    city_keys = [k for k in msgs["en"] if k.startswith("city.")]
    assert len(city_keys) == 80
    for key in city_keys:
        for loc in LOCALES:
            assert msgs[loc].get(key), f"{key} missing in {loc}"
    derived = _derive_reverse(msgs)
    assert len(derived) == 361
    city_rev: dict[str, str] = {}
    for label, vals in derived.items():
        for part in vals.split("|"):
            group, value = part.split(":", 1)
            if group == "city":
                assert label not in city_rev, f"city label collision: {label!r}"
                city_rev[label] = value
    canonical = {msgs["en"][k] for k in city_keys}
    for label, value in city_rev.items():
        if label != value.lower():
            assert label not in {c.lower() for c in canonical}, (
                f"non-English city label {label!r} collides with canonical city name")
    ambiguous = {k: v for k, v in derived.items() if "|" in v}
    assert set(ambiguous) == {"新加坡", "香港", "singapore", "hong kong",
                              "singapour", "singapur", "singapura"}, ambiguous


def test_r27_w4_prefchat_render_wiring():
    """Source pins: the two wizard bubble spots render through the
    round-27 helpers, and the stored turn message (the backend
    contract) is untouched."""
    prefchat = (ROOT / "frontend/src/components/PrefChat.tsx").read_text(encoding="utf-8")
    # Model-led user bubble re-localises a bare choice label.
    assert "<p>{prefTurnUserText(bubble.text, t)}</p>" in prefchat
    # Guided history bubble re-localises a bare stored label.
    assert "<p>{guidedAnswerText(q)}</p>" in prefchat
    assert "verbatim[q] ?? answerText(q)" not in prefchat
    # The helpers exist and are exported for the harness.
    assert "export function isBareChoiceLabel(" in prefchat
    assert "export function prefTurnUserText(" in prefchat
    # The turn's stored message is still the verbatim text the
    # backend re-fetch expects (rendering only — no storage change).
    assert "setTurns((prev) => [...prev, { id: turnId, question: trimmed," in prefchat
    # CompassPet's choiceLabel is untouched by this round: its three
    # structured steps still render through it.
    pet = (ROOT / "frontend/src/components/CompassPet.tsx").read_text(encoding="utf-8")
    assert "if (turn.step === 0) return t(turn.value === 'undergraduate' ? 'pet.q1ug' : 'pet.q1tm');" in pet
    assert "if (turn.step === 1) return t(`country.${turn.value}`);" in pet
