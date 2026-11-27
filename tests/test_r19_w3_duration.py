"""Round 19, worker W3 — nit 4: mixed-language duration on the step-8
UZH card (and nit 5 judgement lock-in).

Nit 4 root cause: `zurich-informatics-bsc-2027` carried no
`program.duration.<id>` key in any locale (the ETH siblings did),
and its data duration "3 years (180 ECTS)" has a parenthetical the
old generic fallback regex could not match, so the raw English fell
through on the step-8 card while the ETH cards showed
"3 年（180 学分）". Fix, display-side only (the expansion data is
untouched — the English string is the verified source value):
- the missing per-programme key in all 6 locales (established
  pattern, cf. eth-cs-bsc-2027);
- the generic fallback in `formatDuration` now parses the
  "(N credits)" / "(N ECTS)" / "(N semesters, N ECTS)" parenthetical
  through new `format.credit(s)` / `format.ects` /
  `format.semester(s)` keys, so any other programme with the same
  shape (e.g. the ETH MSc "2 years (4 semesters, 120 ECTS)") is
  localised too. A parenthetical the parser does not know
  ("1.5 years (three terms)", "2-3 years") still falls back to the
  raw value rather than an invented rendering.
- ECTS stays "ECTS" in every locale: it is a standard acronym, kept
  like IELTS elsewhere; only the surrounding words are localised
  ("3 years (180 ECTS)" -> "3 年（180 ECTS）" in zh-CN).

Nit 5 (judgement, NOT fixed — see /tmp/r19-w3-decisions.md): the
Switzerland + cool flow shows the country and climate questions a
second time. Root cause is twofold and neither half is a one-line
ordering/gating fix: (1) the backend offline extractor
(`_deterministic_extract`, pref_chat.py) understands countries +
note only, never enums, so an offline climate answer ("凉爽")
extracts to {} and the template reply re-asks climate; (2) the
frontend then preserves that answer locally (`mapFailedPrefAnswer`
DOES understand "凉爽") and switches to the guided queue, whose
history re-renders the answered countries + climate blocks with the
no-match opinion. Nothing is lost and no re-answer is forced — the
queue advances to environment — so the behaviour is accepted as is.
The test below pins the backend half of that diagnosis, so a future
decision to extend the offline extractor changes it deliberately.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]
FORMAT = ROOT / "frontend" / "src" / "lib" / "format.ts"

# Audit profile (task 13): step-8 top 3, all Swiss, UG computing.
SWISS_STEP8 = ["eth-cs-bsc-2027", "eth-cse-bsc-2027", "zurich-informatics-bsc-2027"]

EXPECTED_ZH = {
    "eth-cs-bsc-2027": "3 年（180 学分）",
    "eth-cse-bsc-2027": "3 年（180 学分）",
    "zurich-informatics-bsc-2027": "3 年（180 ECTS）",
}
EXPECTED_EN = {
    "eth-cs-bsc-2027": "3 years (180 credits)",
    "eth-cse-bsc-2027": "3 years (180 credits)",
    "zurich-informatics-bsc-2027": "3 years (180 ECTS)",
}

# Raw English duration words that must never appear in a zh-CN card.
RAW_ENGLISH_WORDS = ("years", "year", "months", "month", "credits", "credit",
                     "semesters", "semester", "full-time")


def _messages(locale: str) -> dict:
    return json.loads((ROOT / "frontend" / "messages" / f"{locale}.json").read_text(encoding="utf-8"))


def _expansion_by_id() -> dict:
    data = json.loads((ROOT / "data" / "expansions" / "expansion.json").read_text(encoding="utf-8"))
    out: dict = {}

    def walk(o):
        if isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, dict):
            if o.get("id") and o.get("duration"):
                out[o["id"]] = o
            for v in o.values():
                walk(v)

    walk(data)
    return out


# ---------------------------------------------------------------------------
# Locale keys
# ---------------------------------------------------------------------------

def test_zurich_duration_key_exists_in_all_locales():
    for locale in LOCALES:
        msgs = _messages(locale)
        value = msgs.get("program.duration.zurich-informatics-bsc-2027")
        assert value, locale
        assert "180" in value and "3" in value, (locale, value)
        if locale != "en":
            assert value != "3 years (180 ECTS)", (locale, value)


def test_locale_key_parity_after_duration_keys():
    sets = {locale: set(_messages(locale)) for locale in LOCALES}
    base = sets["en"]
    assert len(base) == 970, len(base)
    for locale in LOCALES:
        assert sets[locale] == base, (locale, sets[locale] ^ base)


def test_duration_format_keys_exist_in_all_locales():
    for locale in LOCALES:
        msgs = _messages(locale)
        for key in ("format.credit", "format.credits", "format.ects",
                    "format.semester", "format.semesters"):
            assert msgs.get(key), (locale, key)


# ---------------------------------------------------------------------------
# Real formatDuration execution (node harness over tsc-compiled lib)
# ---------------------------------------------------------------------------

_NODE_HARNESS = r"""
const fmt = require(OUT + '/format.js');
const cases = JSON.parse(process.argv[2]);
const out = [];
for (const [id, duration, locale] of cases) {
  const msgs = require(FE + '/messages/' + locale + '.json');
  const t = (k) => (k in msgs ? msgs[k] : k);
  out.push({ id, rendered: fmt.formatDuration({ id, duration }, t, locale) });
}
console.log(JSON.stringify(out));
"""


def _run_format_duration(tmp_path, cases):
    """cases: [(id, duration, locale)] -> { (id, locale): rendered }.
    Compiles the real frontend format.ts (same pattern as
    tests/test_p0_retest6.py) and executes formatDuration against
    the real locale files."""
    outdir = tmp_path / "r19_format"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/format.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r19_format_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(fe))), encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness), json.dumps(cases, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    rendered = json.loads(node.stdout)
    assert len(rendered) == len(cases)
    return {(row["id"], case[2]): row["rendered"]
            for row, case in zip(rendered, cases)}


def test_step8_swiss_cards_localised_in_zh(tmp_path):
    """The audit-profile step-8 card set: no card shows a raw English
    duration when the UI locale is zh-CN."""
    by_id = _expansion_by_id()
    cases = [(pid, by_id[pid]["duration"], "zh-CN") for pid in SWISS_STEP8]
    got = _run_format_duration(tmp_path, cases)
    for pid in SWISS_STEP8:
        rendered = got[(pid, "zh-CN")]
        assert rendered == EXPECTED_ZH[pid], (pid, rendered)
        lowered = rendered.lower()
        for word in RAW_ENGLISH_WORDS:
            assert word not in lowered, (pid, rendered)


def test_step8_swiss_cards_english_stays_sensible(tmp_path):
    by_id = _expansion_by_id()
    cases = [(pid, by_id[pid]["duration"], "en") for pid in SWISS_STEP8]
    got = _run_format_duration(tmp_path, cases)
    for pid in SWISS_STEP8:
        assert got[(pid, "en")] == EXPECTED_EN[pid], (pid, got[(pid, "en")])


def test_step8_swiss_cards_localised_in_french(tmp_path):
    by_id = _expansion_by_id()
    cases = [(pid, by_id[pid]["duration"], "fr") for pid in SWISS_STEP8]
    got = _run_format_duration(tmp_path, cases)
    assert got[("eth-cs-bsc-2027", "fr")] == "3 ans (180 crédits)"
    assert got[("zurich-informatics-bsc-2027", "fr")] == "3 ans (180 ECTS)"


def test_generic_parenthetical_fallback_zh(tmp_path):
    """The fallback alone (no per-programme key) localises the
    parenthetical — this is what fixes the next programme with the
    same shape, not just the UZH card."""
    cases = [
        ("synthetic-credits", "3 years (180 credits)", "zh-CN"),
        ("synthetic-ects", "3 years (180 ECTS)", "zh-CN"),
        ("synthetic-semesters", "2 years (4 semesters, 120 ECTS)", "zh-CN"),
        ("synthetic-plain", "3 years", "zh-CN"),
        ("synthetic-fulltime", "1 year full-time", "zh-CN"),
    ]
    got = _run_format_duration(tmp_path, cases)
    assert got[("synthetic-credits", "zh-CN")] == "3 年（180 学分）"
    assert got[("synthetic-ects", "zh-CN")] == "3 年（180 ECTS）"
    assert got[("synthetic-semesters", "zh-CN")] == "2 年（4 学期，120 ECTS）"
    assert got[("synthetic-plain", "zh-CN")] == "3 年"
    assert got[("synthetic-fulltime", "zh-CN")] == "1 年（全日制）"


def test_generic_parenthetical_fallback_english(tmp_path):
    cases = [
        ("synthetic-credits", "3 years (180 credits)", "en"),
        ("synthetic-ects", "3 years (180 ECTS)", "en"),
        ("synthetic-semesters", "2 years (4 semesters, 120 ECTS)", "en"),
    ]
    got = _run_format_duration(tmp_path, cases)
    assert got[("synthetic-credits", "en")] == "3 years (180 credits)"
    assert got[("synthetic-ects", "en")] == "3 years (180 ECTS)"
    assert got[("synthetic-semesters", "en")] == "2 years (4 semesters, 120 ECTS)"


def test_unparseable_duration_falls_back_raw(tmp_path):
    """Word parentheticals and ranges are not guessed at — the raw
    verified value is shown instead of an invented rendering."""
    cases = [
        ("synthetic-wordparen", "1.5 years (three terms)", "zh-CN"),
        ("synthetic-range", "2-3 years", "zh-CN"),
    ]
    got = _run_format_duration(tmp_path, cases)
    assert got[("synthetic-wordparen", "zh-CN")] == "1.5 years (three terms)"
    assert got[("synthetic-range", "zh-CN")] == "2-3 years"


def test_format_duration_call_sites_pass_locale():
    """The step-8 card (RecChat), the browse list and the detail page
    all pass the UI locale, so the parenthetical style follows it."""
    rec = (ROOT / "frontend" / "src" / "components" / "RecChat.tsx").read_text(encoding="utf-8")
    assert "formatDuration(p, t, locale)" in rec
    browse = (ROOT / "frontend" / "src" / "app" / "programs" / "page.tsx").read_text(encoding="utf-8")
    assert "formatDuration(p, t, locale)" in browse
    detail = (ROOT / "frontend" / "src" / "app" / "programs" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert detail.count("formatDuration(program, t, locale)") == 2
    src = FORMAT.read_text(encoding="utf-8")
    assert "formatDuration(program, t, locale)" in src  # formatProgramLine


# ---------------------------------------------------------------------------
# Nit 5 — judgement lock-in (backend half of the diagnosis)
# ---------------------------------------------------------------------------

def test_nit5_offline_climate_answer_not_extracted_by_backend(monkeypatch):
    """Pinned diagnosis, not a bug fix: with no model, the offline
    extractor understands countries + note only, so "凉爽" extracts
    to {} and the template reply re-asks climate (next_question
    stays 'climate'). The frontend preserves the answer locally
    (mapFailedPrefAnswer understands "凉爽") and the guided queue
    advances to environment, so no re-answer is forced — that is why
    the repeat is accepted (see /tmp/r19-w3-decisions.md). If the
    offline extractor is ever extended to enums, update this test
    deliberately."""
    from ai.pref_chat import pref_answer
    from ai.provider import ProviderAdapter

    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    provider = ProviderAdapter()
    assert not provider.available
    result = pref_answer("凉爽", "zh-CN",
                         known={"countries": ["CH"], "note": "环境优美"},
                         provider=provider)
    assert result["extracted"] == {}, result["extracted"]
    assert result["next_question"] == "climate", result["next_question"]
    assert result["ai_status"] == "unavailable"
