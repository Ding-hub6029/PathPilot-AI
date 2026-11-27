"""Round 18 W1 — step-8 direct re-entry false empty state + leaked
{total} placeholder; clear-data does not reset the wizard step.

Audit profile throughout: China Gaokao, UG, CS, 680/750, IELTS 7.0,
budget GBP 50,000, 2027, overseas, Switzerland / cool / university-town
/ Zurich.

Re-test task 12 (2026-11-27 10:19-10:24 CST) found the main path
passing (summary contains 瑞士, step-8 top 3 all Swiss, results top 2
ETH) but a direct re-open of /wizard at 10:24 showing step 8 in an
error state: "这些结果里没有瑞士的课程" + "已为你评估的 {total} 个课
程中，没有一个在瑞士。你的偏好没有被忽略——只是筛选后的集合里确实
没有那边的课程。" + "这个方向还没有已核实的课程". Re-entering from
step 7 ("查看我的结果") restored the correct Swiss top 3.

FINDING 1 (P0) — FALSE EMPTY STATE ON DIRECT RE-ENTRY. Root cause,
verified with evidence before the fix (scratch harness
/tmp/r18-w1-before/repro.js, not committed): React runs child effects
before the parent (provider) hydration effect, so on a fresh load with
the stored step 7 the wizard's step-7 effect ran while `profile` was
still `emptyProfile` (track ''), the candidate filter matched nothing
(0 candidates), and the effect set recs to [] — and, with deps [step]
only, never re-ran after hydration. RecChat then saw recs=[] with the
hydrated profile's prefCountries=['CH'], so missingPrefCountries
returned ['CH'] and the no-country notice + the recommendEmpty state
rendered. The same race was fixed on the programme page in round 13
(its effect now depends on the profile); the wizard never got it.
Fix: the store exposes `hydrated` (true once the saved profile is
read) and the step-7 effect waits for it — deps [step, hydrated] — so
it re-runs once the saved profile is in. `hydrated` flips false ->
true exactly once, so the normal step 6 -> 7 path still matches
exactly once and an intake-year edit on step 7 does not re-trigger
the match. A cancelled flag stops a match still in flight when the
user leaves step 7 (or clears their data) from writing stale recs /
targetProgramIds afterwards.

FINDING 1b (P0) — LEAKED {total} PLACEHOLDER, AND A SECOND LEAK IN THE
SAME NOTICE. The noCountryNote string needs {total} in all 6 locales
but neither call site (RecChat.tsx, results/page.tsx) passed it, so
the raw "{total}" reached the user — visible in the 10:24 report.
Fix: both call sites pass total (the evaluated list: (recs ?? []).length
in RecChat, data.results.length on the results page). The audit of
every interpolation on the step-8 / recommendation path also found a
second leak in the same notice: results.noCountryNone needs {country}
in all 6 locales but was rendered with t() — which never
interpolates — in both files, so the raw "{country}" reached the user
whenever the verified catalogue held no programme in that country at
all. Fix: both sites use tf() with the country. No other tf()/t() call
on the path leaks: the audit test below parses all three files
against all 6 locales.

FINDING 2 (P0/P1) — CLEAR-DATA DOES NOT RESET THE WIZARD STEP.
clearData set the empty profile and removed pp-profile / pp-check-done
but did not remove pp-wizard-step or pp-prefchat, and did not reset
the wizard's in-memory step (useState only initialises at mount), so
after "清除我的数据" the mounted wizard sat on the step-8 empty state
and the tester had to click Back step by step to step 1. Fix, both
halves: clearData removes pp-wizard-step and pp-prefchat and bumps a
new dataClearNonce (same pattern as bannerClearNonce); the wizard
watches the nonce and resets the live step to 0 (plus recs /
recLoading / recWaking / error) at once. The watch seeds its ref at
mount, so a clear from BEFORE this mount — already reflected in the
mounted state via loadWizardStep — does not reset a fresh run.

Note on results/page.tsx scope: only the Round 8 no-country block
changed there (the noCountryNote call site and the noCountryNone
render in the same notice) — no other line of that file is touched.

Run from the project root:
    .venv/bin/pytest tests/test_r18_w1.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]
PATH_FILES = [
    "src/components/RecChat.tsx",
    "src/app/wizard/page.tsx",
    "src/app/results/page.tsx",
]


def _messages() -> dict[str, dict[str, str]]:
    return {
        loc: json.loads((FE / f"messages/{loc}.json").read_text(encoding="utf-8"))
        for loc in LOCALES
    }


def _placeholders(s: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", s))


def _balanced(src: str, i: int, open_c: str, close_c: str) -> tuple[str, int]:
    """Content inside the balanced pair starting at i, plus the index
    just past the closing char. Strings are honoured; a template
    literal's ${...} interpolation is skipped as one unit (simple
    identifiers only in this codebase — no nesting)."""
    depth = 0
    j = i
    instr: str | None = None
    esc = False
    while j < len(src):
        ch = src[j]
        if instr is not None:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif instr == "`" and ch == "$" and j + 1 < len(src) and src[j + 1] == "{":
                j = src.index("}", j + 2)  # skip the interpolation
            elif ch == instr:
                instr = None
        else:
            if ch in ("'", '"', "`"):
                instr = ch
            elif ch == open_c:
                depth += 1
            elif ch == close_c:
                depth -= 1
                if depth == 0:
                    return src[i + 1:j], j + 1
        j += 1
    return src[i + 1:], len(src)


def _split_top_level(s: str) -> list[str]:
    """Split on top-level commas, honouring nesting and strings."""
    parts: list[str] = []
    depth = 0
    instr: str | None = None
    esc = False
    start = 0
    for j, ch in enumerate(s):
        if instr is not None:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == instr:
                instr = None
        else:
            if ch in ("'", '"', "`"):
                instr = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append(s[start:j])
                start = j + 1
    parts.append(s[start:])
    return [p.strip() for p in parts if p.strip()]


def _vars_of_object(obj_src: str) -> set[str]:
    """Var names a { ... } object literal provides: `name:` keys and
    bare shorthand identifiers."""
    names: set[str] = set()
    for part in _split_top_level(obj_src):
        m = re.match(r"([A-Za-z_]\w*)\s*:", part)
        if m:
            names.add(m.group(1))
        elif re.fullmatch(r"[A-Za-z_]\w*", part):
            names.add(part)
    return names


def _tf_calls(src: str) -> list[tuple[int, list[str], set[str]]]:
    """(line, static key literals, provided var names) for every tf()
    call with a resolvable key. Dynamic keys are returned with an
    empty key list and handled by the caller."""
    out = []
    for m in re.finditer(r"\btf\(", src):
        content, _ = _balanced(src, m.end() - 1, "(", ")")
        parts = _split_top_level(content)
        keyexpr = parts[0] if parts else ""
        keys = re.findall(r"'([^']+)'", keyexpr)
        varnames: set[str] = set()
        if len(parts) > 1:
            obj = parts[1].strip()
            if obj.startswith("{"):
                inner, _ = _balanced(obj, 0, "{", "}")
                varnames = _vars_of_object(inner)
        out.append((src[:m.start()].count("\n") + 1, keys, varnames))
    return out


# ---------------------------------------------------------------------------
# Finding 1b — no placeholder may ever reach the user on this path
# ---------------------------------------------------------------------------

def test_r18_w1_no_placeholder_leak_on_step8_path():
    """Every tf() call in RecChat / wizard / results supplies every
    placeholder its string needs in ALL 6 locales, and no literal
    t() call renders a string that contains a placeholder. Fails on
    the pre-fix sources (noCountryNote missing total in both files;
    noCountryNone rendered with t() in both files)."""
    msgs = _messages()
    problems: list[str] = []
    for rel in PATH_FILES:
        src = (FE / rel).read_text(encoding="utf-8")
        for line, keys, varnames in _tf_calls(src):
            for key in keys:
                need: set[str] = set()
                for loc in LOCALES:
                    need |= _placeholders(msgs[loc].get(key, ""))
                missing = need - varnames
                if missing:
                    problems.append(
                        f"{rel}:{line} tf('{key}') missing {sorted(missing)} "
                        f"(passes {sorted(varnames)})")
                if key not in msgs["en"]:
                    problems.append(f"{rel}:{line} tf('{key}') key not in messages")
        for m in re.finditer(r"(?<![\w.])t\(\s*'([^']+)'\s*\)", src):
            key = m.group(1)
            need = set()
            for loc in LOCALES:
                need |= _placeholders(msgs[loc].get(key, ""))
            if need:
                problems.append(
                    f"{rel}:{src[:m.start()].count(chr(10)) + 1} "
                    f"t('{key}') renders a string needing {sorted(need)} "
                    f"but t() never interpolates")
    # The one dynamic call: tf(reply.key, reply.vars). Its two keys
    # are set in onSend with exactly the vars their strings need.
    recchat = (FE / "src/components/RecChat.tsx").read_text(encoding="utf-8")
    for key, var in [("wizard.recChatFilteredCountry", "country"),
                     ("wizard.recChatFilteredCity", "city")]:
        assert f"key: '{key}', vars: {{ {var}:" in recchat, (
            f"dynamic reply {key} must be set with {{{var}: ...}}")
        for loc in LOCALES:
            assert _placeholders(msgs[loc][key]) == {var}, (
                f"{key} in {loc} needs exactly {{{var}}}")
    assert not problems, "\n".join(problems)


def test_r18_w1_no_country_note_call_sites():
    """The two noCountryNote call sites pass total (the evaluated
    list), and both noCountryNone renders interpolate the country."""
    recchat = (FE / "src/components/RecChat.tsx").read_text(encoding="utf-8")
    results = (FE / "src/app/results/page.tsx").read_text(encoding="utf-8")
    assert "total: (recs ?? []).length" in recchat, (
        "RecChat must pass total=(recs ?? []).length to noCountryNote")
    assert "total: data.results.length" in results, (
        "results page must pass total=data.results.length to noCountryNote")
    assert "tf('results.noCountryNone', { country:" in recchat
    assert "tf('results.noCountryNone', { country:" in results
    assert "t('results.noCountryNone')" not in recchat
    assert "t('results.noCountryNone')" not in results


# ---------------------------------------------------------------------------
# Finding 1 — the step-7 effect waits for hydration
# ---------------------------------------------------------------------------

def test_r18_w1_step7_effect_waits_for_hydration():
    """The wizard's step-7 match must not run on the empty pre-
    hydration profile, and must re-run once the saved profile is in.
    Fails on the pre-fix sources (deps [step], no hydrated gate)."""
    store = (FE / "src/lib/store.tsx").read_text(encoding="utf-8")
    wizard = (FE / "src/app/wizard/page.tsx").read_text(encoding="utf-8")

    # The store exposes hydration state.
    assert "hydrated: boolean;" in store
    assert "hydrated" in store.split("const value = useMemo")[1].split("}")[0]
    assert "const { t, locale, profile, setProfile, updateProfile, hydrated, dataClearNonce } = useApp();" in wizard

    # The step-7 effect gates on it and re-runs when it flips.
    assert "if (step !== 7 || !hydrated) return;" in wizard
    assert "}, [step, hydrated]);" in wizard

    # A match still in flight when the user leaves step 7 (or clears
    # their data) must not write stale recs / targetProgramIds.
    assert "let cancelled = false;" in wizard
    assert "return () => { cancelled = true; };" in wizard
    assert wizard.count("if (cancelled) return;") >= 2, (
        "both the match and the local fallback must respect cancellation")


# ---------------------------------------------------------------------------
# Finding 2 — clear-data resets the wizard step
# ---------------------------------------------------------------------------

def test_r18_w1_clear_data_resets_wizard():
    """clearData removes the stored wizard step + pref-chat position
    and bumps a nonce; the mounted wizard watches the nonce (seeded
    at mount, so a pre-mount clear does not reset a fresh run) and
    resets the live step to 0 with the stale recommendations."""
    store = (FE / "src/lib/store.tsx").read_text(encoding="utf-8")
    wizard = (FE / "src/app/wizard/page.tsx").read_text(encoding="utf-8")

    clear = store[store.index("const clearData = () => {"):]
    clear = clear[:clear.index("};")]
    assert "localStorage.removeItem('pp-wizard-step')" in clear
    assert "localStorage.removeItem('pp-prefchat')" in clear
    assert "localStorage.removeItem('pp-profile')" in clear
    assert "localStorage.removeItem('pp-check-done')" in clear
    assert "setDataClearNonce((n) => n + 1)" in clear
    assert "dataClearNonce: number;" in store

    # The wizard watches the nonce, seeded at mount.
    assert "const clearNonceRef = useRef(dataClearNonce);" in wizard
    watch = wizard[wizard.index("const clearNonceRef"):]
    watch = watch[:watch.index("}, [dataClearNonce]);")]
    assert "if (dataClearNonce === clearNonceRef.current) return;" in watch
    assert "clearNonceRef.current = dataClearNonce;" in watch
    assert "setStep(0);" in watch
    assert "setRecs(null);" in watch


# ---------------------------------------------------------------------------
# Findings 1 + 1b — the exact tester path as data flow (node harness
# over lib/api.ts + lib/preferences.ts + lib/fields.ts), with the
# rendered strings taken from the real call sites
# ---------------------------------------------------------------------------

_NODE_HARNESS = r"""
const fs = require('fs');
const api = require(OUT + '/api.js');
const prefs = require(OUT + '/preferences.js');
const fields = require(OUT + '/fields.js');
const { emptyProfile } = require(OUT + '/types.js');
const zh = require(FE + '/messages/zh-CN.json');
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + ' -> ' + g + ' want ' + w); fail++; }
  else console.log('PASS ' + name);
};
// store.tsx tf(), verbatim logic: split/join per var, nothing else.
const tf = (key, vars) => {
  let s = zh[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v));
  return s;
};
const recchatSrc = fs.readFileSync(FE + '/src/components/RecChat.tsx', 'utf-8');
const resultsSrc = fs.readFileSync(FE + '/src/app/results/page.tsx', 'utf-8');
// The vars object of the FIRST tf('key', {...}) call in a source file,
// extracted with a balanced scan (a bare substring search would also
// match other call sites that pass a total, e.g. results.countLine).
const callVars = (src, key) => {
  const idx = src.indexOf(`tf('${key}'`);
  if (idx < 0) return null;
  const open = src.indexOf('{', src.indexOf(',', idx));
  if (open < 0) return null;
  let depth = 0, instr = null;
  for (let j = open; j < src.length; j++) {
    const ch = src[j];
    if (instr) { if (ch === instr) instr = null; continue; }
    if (ch === "'" || ch === '"' || ch === '`') { instr = ch; continue; }
    if (ch === '{') depth++;
    if (ch === '}') { depth--; if (depth === 0) return src.slice(open, j + 1); }
  }
  return null;
};

const programs = api.mergePrograms([]);
const AUDIT = { ...emptyProfile,
  track: 'undergraduate', curriculum: 'cn_gaokao', field: 'computing',
  gaokaoScore: 680, gaokaoTotal: 750,
  ieltsOverall: 7.0, budget: 50000, budgetCurrency: 'GBP',
  residency: 'overseas', intakeYear: 2027,
  prefCountries: ['CH'], prefClimate: 'cool',
  prefEnvironment: 'university-town', prefCity: 'Zurich' };
const candidatesFor = (profile) => programs.filter((p) =>
  p.degreeLevel === profile.track && p.matchable !== false &&
  profile.field && fields.programMatchesField(p, profile.field));

// --- BEFORE shape (the diagnosed mechanism, pinned as fact) -----------
check('before: the pre-hydration profile yields zero candidates',
  candidatesFor(emptyProfile).length, 0);
check('before: zero recs leaves Switzerland missing',
  prefs.missingPrefCountries(AUDIT, []), ['CH']);
// The note as the pre-fix call sites rendered it (no total passed).
const noteBefore = tf('results.noCountryNote', { country: '瑞士', level: '本科', field: '计算机' });
check('before: note with the pre-fix vars leaks {total}',
  noteBefore.includes('{total}'), true);
check('before: note with the pre-fix vars is the tester-quoted string',
  noteBefore,
  '已为你评估的 {total} 个课程中，没有一个在瑞士。你的偏好没有被忽略——只是筛选后的集合里确实没有那边的课程。');
check('before: t(noCountryNone) leaks {country}',
  zh['results.noCountryNone'].includes('{country}'), true);
check('before: empty recs render the tester-quoted empty state',
  zh['wizard.recommendEmpty'], '这个方向还没有已核实的课程');

// --- AFTER shape: the call sites pass what the strings need ----------
check('after: RecChat noCountryNote passes total',
  /\btotal\s*:/.test(callVars(recchatSrc, 'results.noCountryNote') || ''), true);
check('after: results noCountryNote passes total',
  /\btotal\s*:/.test(callVars(resultsSrc, 'results.noCountryNote') || ''), true);
check('after: RecChat noCountryNone interpolates the country',
  recchatSrc.includes("tf('results.noCountryNone', { country:"), true);
check('after: results noCountryNone interpolates the country',
  resultsSrc.includes("tf('results.noCountryNone', { country:"), true);

// --- AFTER shape: the re-entry renders the same as entry from step 7 --
const candidates = candidatesFor(AUDIT);
check('after: hydrated profile yields 89 candidates', candidates.length, 89);
const swiss = candidates.filter((p) => p.country === 'CH').map((p) => p.id).sort();
check('after: hydrated candidates include the 5 Swiss UG computing programmes',
  swiss,
  ['epfl-ai-bsc-2027', 'epfl-cs-bsc-2027', 'eth-cs-bsc-2027', 'eth-cse-bsc-2027', 'zurich-informatics-bsc-2027']);
const local = api.evaluateLocal(AUDIT, candidates.map((p) => p.id));
const sorted = prefs.sortRecsByPreference(local.results, programs, AUDIT);
const top3 = sorted.slice(0, 3).map((r) => programs.find((p) => p.id === r.programId).country);
check('after: top 3 on the re-entry path are all Swiss', top3, ['CH', 'CH', 'CH']);
const recPrograms = sorted.map((r) => programs.find((p) => p.id === r.programId)).filter(Boolean);
check('after: no missing countries on the hydrated path',
  prefs.missingPrefCountries(AUDIT, recPrograms), []);
// The notice as the fixed call sites render it (total = evaluated count).
const noteAfter = tf('results.noCountryNote',
  { country: '瑞士', level: '本科', field: '计算机', total: sorted.length });
check('after: note rendered with the fixed vars has no placeholder left',
  noteAfter.includes('{'), false);
check('after: note counts the evaluated list',
  noteAfter.includes(`已为你评估的 ${sorted.length} 个课程中`), true);
const noneAfter = tf('results.noCountryNone', { country: '瑞士' });
check('after: noCountryNone rendered with the country has no placeholder left',
  noneAfter.includes('{'), false);
check('after: noCountryNone names the country',
  noneAfter, '已核实目录里暂时还没有瑞士的课程。');
process.exit(fail ? 1 : 0);
"""


def test_r18_w1_exact_tester_path(tmp_path):
    """Round 18: the before-shape (empty pre-hydration profile -> 0
    candidates -> Switzerland missing -> the tester-quoted strings
    with the raw placeholders) and the after-shape (the fixed call
    sites pass total / interpolate the country; the hydrated profile
    yields 89 candidates with the 5 Swiss UG computing programmes and
    an all-Swiss top 3, so no notice renders at all on re-entry)."""
    outdir = tmp_path / "r18_wizard"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/api.ts", "src/lib/preferences.ts",
         "src/lib/fields.ts", "src/lib/types.ts", "src/lib/programs.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r18_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(FE))), encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"],
           "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
