"""Restyle 2 behaviour half (Worker B) — Gen UI pattern in the pet.

- Proactive pet greeting: a selection-progress summary from the real
  stored profile (filled / still missing, never invented) + 3 quick
  suggestions (check deadlines / compare schools / prepare documents).
- Plan-change sentence: one user sentence changing the country, the
  budget, or the intake timing proposes the change and asks to
  confirm — nothing is applied until Confirm, Skip discards it; the
  confirm refreshes the follow-up checklist.
- Follow-up tracking section on /results (no new route): school
  comparison, deadline countdowns, interview/visa steps as a
  checkable list + timeline, with a "continue the conversation"
  entry back to the pet.

Hard boundary, pinned here: no admission probabilities, no
guarantees, no interview step (no verified interview data exists),
and every checklist/tracking item derives from the stored profile +
verified programme data only.

Covers, with no API key and no network:
- node harness over the REAL lib/tracking.ts (compiled with tsc,
  same pattern as tests/test_r31_g4_footer_verdict.py): plan-change
  detection (country / budget / intake / no-change / question guard /
  first-time-set guard), budget parsing (k / 万 / currency tokens),
  profile progress (full / empty / partial), checklist derivation
  (deadline / documents / visa, no items without verified data) and
  merge (done flags survive by id), deadline parsing (simple date,
  multi-date picks the earliest future date, past date, unparseable);
- source pins: the pet greeting pushes the summary turn with the 3
  suggestion actions, the plan-change intercept never reaches the
  model, Confirm applies the patch + refreshes the checklist, the
  store persists the checklist, /results renders the tracking
  section with the comparison table, countdowns, checkable list and
  the continue-conversation entry;
- locale keys: 994 in all 6 locales (984 + 10 new Restyle 2 keys),
  same set, new keys non-empty in all 6;
- scope pins: no new top-level route, PrefChat untouched by this
  half (the plan-change flow lives in the pet only), DECISIONS.md
  untouched (the #317 draft lives in /tmp/decision-restyle2-B.md).

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_restyle2_b_behaviour.py
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "frontend"
LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]

NEW_KEYS = [
    "pet.suggestDeadlines", "pet.suggestCompare", "pet.suggestDocuments",
    "pet.planChangeAsk", "pet.planConfirm", "pet.planSkip",
    "pet.summaryMissing",
    "results.trackingTitle", "results.trackingDaysLeft",
    "results.trackingInterview",
]

_NODE_HARNESS = r"""
const tracking = require(__OUT__ + '/tracking.js');
const fs = require('fs');
const en = JSON.parse(fs.readFileSync(__MSG__ + '/en.json', 'utf8'));
const t = (k) => en[k] ?? k;

let fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('FAIL ' + name + ': got ' + JSON.stringify(got) + ', want ' + JSON.stringify(want)); }
  else console.log('ok ' + name);
}
function checkTrue(name, cond) { check(name, !!cond, true); }

const COUNTRIES = [
  { code: 'GB', names: ['UK', 'United Kingdom', '英国'] },
  { code: 'CH', names: ['Switzerland', '瑞士'] },
  { code: 'SG', names: ['Singapore', '新加坡'] },
];
const NOW = Date.UTC(2026, 10, 28); // 2026-11-28, fixed for countdowns

// --- 1. Plan-change detection ---
const base = { track: 'undergraduate', targetProgramIds: ['ucl-cs-bsc-2026'],
  prefCountries: ['GB'], budget: 50000, budgetCurrency: 'GBP', intakeYear: 2026 };

check('country change GB -> CH',
  tracking.detectPlanChange('I want to change to Switzerland instead', base, COUNTRIES),
  { kind: 'country', country: 'CH', fromCountries: ['GB'] });
check('country change in Chinese',
  tracking.detectPlanChange('我想改去瑞士', base, COUNTRIES),
  { kind: 'country', country: 'CH', fromCountries: ['GB'] });
check('same country is not a change',
  tracking.detectPlanChange('change to the UK instead', base, COUNTRIES), null);
check('question with no change cue never fires',
  tracking.detectPlanChange('What are the deadlines for Swiss schools?', base, COUNTRIES), null);
check('first-time country set is not a change',
  tracking.detectPlanChange('change to Switzerland instead', { ...base, prefCountries: [] }, COUNTRIES), null);
check('budget change',
  tracking.detectPlanChange('change my budget to 60000', base, COUNTRIES),
  { kind: 'budget', budget: 60000, budgetCurrency: 'GBP', fromBudget: 50000 });
check('budget change with "now" cue',
  tracking.detectPlanChange('my budget is now 60000', base, COUNTRIES),
  { kind: 'budget', budget: 60000, budgetCurrency: 'GBP', fromBudget: 50000 });
check('same budget is not a change',
  tracking.detectPlanChange('change my budget to 50000', base, COUNTRIES), null);
check('budget change with new currency',
  tracking.detectPlanChange('change my budget to 50000 SGD', base, COUNTRIES),
  { kind: 'budget', budget: 50000, budgetCurrency: 'SGD', fromBudget: 50000 });
check('intake change',
  tracking.detectPlanChange('move my intake to 2027', base, COUNTRIES),
  { kind: 'intake', intakeYear: 2027, fromIntakeYear: 2026 });
check('same intake is not a change',
  tracking.detectPlanChange('move my intake to 2026', base, COUNTRIES), null);
check('country wins over budget in one sentence',
  tracking.detectPlanChange('change to Switzerland with a budget of 60000', base, COUNTRIES).kind, 'country');
check('empty message never fires',
  tracking.detectPlanChange('   ', base, COUNTRIES), null);

// --- 2. Budget parsing ---
check('bare number', tracking.budgetFromText('change my budget to 60000', 'GBP'),
  { amount: 60000, currency: 'GBP' });
check('k multiplier', tracking.budgetFromText('budget 60k', 'GBP'),
  { amount: 60000, currency: 'GBP' });
check('wan multiplier + CNY', tracking.budgetFromText('预算改成5万', 'GBP'),
  { amount: 50000, currency: 'CNY' });
check('pound sign + commas', tracking.budgetFromText('budget is now £39,700', 'GBP'),
  { amount: 39700, currency: 'GBP' });
check('year is not a budget', tracking.budgetFromText('intake 2027', 'GBP'), null);

// --- 3. Country-name matching ---
check('word boundary: uk inside fluke does not fire',
  tracking.countryFromText('I like fluke', COUNTRIES), null);
check('standalone UK fires', tracking.countryFromText('study in the UK', COUNTRIES), 'GB');
check('Chinese name fires', tracking.countryFromText('去瑞士留学', COUNTRIES), 'CH');

// --- 4. Plan-change patch ---
check('country patch replaces preferred countries',
  tracking.planChangePatch({ kind: 'country', country: 'CH' }), { prefCountries: ['CH'] });
check('budget patch',
  tracking.planChangePatch({ kind: 'budget', budget: 60000, budgetCurrency: 'SGD' }),
  { budget: 60000, budgetCurrency: 'SGD' });
check('intake patch',
  tracking.planChangePatch({ kind: 'intake', intakeYear: 2027 }), { intakeYear: 2027 });

// --- 5. Profile progress ---
const full = { ...base, field: 'computing', ieltsOverall: 7.0, gaokaoScore: 650, gaokaoTotal: 750 };
const fullProgress = tracking.profileProgress(full, t, 'en');
check('full profile: 6 filled, none missing',
  [fullProgress.filled.length, fullProgress.missing.length], [6, 0]);
check('full profile: no invented values',
  fullProgress.filled.map((e) => e.text).join(' | '),
  'Undergraduate | Computing | United Kingdom | 50000 GBP | 2026 | Gaokao 650/750 · IELTS 7');
const emptyProgress = tracking.profileProgress(
  { track: '', targetProgramIds: [], prefCountries: [] }, t, 'en');
check('empty profile: nothing filled, 6 missing',
  [emptyProgress.filled.length, emptyProgress.missing.length], [0, 6]);
check('empty profile: missing labels are the real field labels',
  emptyProgress.missing,
  ['report.profileDegree', 'report.profileField', 'results.prefTitle',
   'report.profileBudget', 'report.profileIntake', 'report.profileScores']);
const partialProgress = tracking.profileProgress(
  { track: 'taught_masters', targetProgramIds: [], prefCountries: ['SG'] }, t, 'en');
check('partial profile: degree + countries filled',
  partialProgress.filled.map((e) => e.labelKey),
  ['report.profileDegree', 'results.prefTitle']);

// --- 6. Checklist derivation ---
const PROGS = [
  { id: 'ep1', country: 'GB', applicationDeadline: '15 January 2027',
    requirements: [{ category: 'academic', description: 'A-levels' },
                   { category: 'language', description: 'IELTS 6.5' }],
    sources: [{ url: 'https://example.ac.uk/ep1' }] },
  { id: 'ep2', country: 'CH', applicationDeadline: null,
    requirements: [], sources: [] },
  { id: 'ep3', country: 'SG', applicationDeadline: '1 Dec 2026',
    requirements: [{ category: 'language', description: 'IELTS 6.0' }],
    sources: [{ url: 'https://example.edu.sg/ep3' }] },
];
const derived = tracking.deriveChecklist(
  { ...base, targetProgramIds: ['ep1', 'ep2', 'ep3'] }, PROGS);
check('derived items: deadline + documents per dated programme, visa per GB/SG country',
  derived.map((i) => i.id),
  ['deadline:ep1', 'documents:ep1', 'deadline:ep3', 'documents:ep3', 'visa:GB', 'visa:SG']);
check('no item for the programme with no verified deadline or requirements',
  derived.some((i) => (i.programId ?? '') === 'ep2'), false);
check('no interview item is ever derived',
  derived.some((i) => i.kind === 'interview'), false);
check('no visa item for a country without official guidance (CH)',
  derived.some((i) => i.id === 'visa:CH'), false);
check('empty profile derives an empty checklist',
  tracking.deriveChecklist({ track: '', targetProgramIds: [] }, PROGS), []);
check('unknown programme id is skipped, never invented',
  tracking.deriveChecklist({ ...base, targetProgramIds: ['no-such-programme'] }, PROGS), []);

// --- 7. Checklist merge ---
const merged = tracking.mergeChecklist(
  [{ id: 'deadline:ep1', kind: 'deadline', programId: 'ep1', done: true },
   { id: 'deadline:gone', kind: 'deadline', programId: 'gone', done: true }],
  derived);
check('merge keeps the done flag by id',
  merged.find((i) => i.id === 'deadline:ep1').done, true);
check('merge drops steps that no longer derive',
  merged.some((i) => i.id === 'deadline:gone'), false);
check('merge leaves new steps undone',
  merged.find((i) => i.id === 'documents:ep1').done, false);

// --- 8. Deadline parsing ---
check('simple date: 1 Dec 2026 is 3 days out from 28 Nov 2026',
  tracking.parseDeadline('1 Dec 2026', NOW), { dateMs: Date.UTC(2026, 11, 1), daysLeft: 3 });
check('multi-date: earliest FUTURE date wins (Regular, not past Early Action)',
  tracking.parseDeadline('1 November 2026 (Early Action); 4 January 2027 (Regular Action)', NOW),
  { dateMs: Date.UTC(2027, 0, 4), daysLeft: 37 });
check('annotated date parses through the note',
  tracking.parseDeadline('15 October 2026 (UCAS, 6pm UK time)', NOW).daysLeft, -44);
check('unparseable deadline returns null, never a guessed date',
  tracking.parseDeadline('Rolling', NOW), null);
check('null deadline returns null', tracking.parseDeadline(null, NOW), null);
check('far-future date counts out',
  tracking.parseDeadline('30 April 2027', NOW).daysLeft, 153);

console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
process.exit(fail ? 1 : 0);
"""


def _compile_tracking(tmp_path):
    outdir = tmp_path / "restyle2_b"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/tracking.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    return outdir


def test_restyle2_b_tracking_harness(tmp_path):
    """Node harness over the REAL lib/tracking.ts: plan-change
    detection, budget/country parsing, profile progress, checklist
    derivation + merge, and deadline parsing."""
    outdir = _compile_tracking(tmp_path)
    harness = tmp_path / "restyle2_b_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("__OUT__", repr(str(outdir)))
        .replace("__MSG__", repr(str(FE / "messages"))),
        encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=180, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
    assert "HARNESS OK" in node.stdout


def test_restyle2_b_locale_keys():
    """994 keys in every locale file (984 at Round 31 + 10 new
    Restyle 2 behaviour keys), the same key set in all 6, and every
    new key non-empty in all 6."""
    msgs = {
        loc: json.load(open(FE / "messages" / f"{loc}.json", encoding="utf-8"))
        for loc in LOCALES
    }
    base = set(msgs["en"])
    assert len(base) == 994, len(base)
    for loc in LOCALES:
        assert set(msgs[loc]) == base, (loc, set(msgs[loc]) ^ base)
    for key in NEW_KEYS:
        for loc in LOCALES:
            assert msgs[loc][key].strip(), (key, loc)


def _read(rel: str) -> str:
    return (FE / rel).read_text(encoding="utf-8")


def test_restyle2_b_pet_greeting_wiring():
    """The pet greeting pushes the proactive summary turn with the 3
    quick suggestions, and the summary renders from the real stored
    profile only."""
    pet = _read("src/components/CompassPet.tsx")
    assert "msgs.push({ kind: 'summary' });" in pet
    assert "case 'summary':" in pet
    assert "profileProgress(profile, t, locale)" in pet
    assert "t('pet.suggestDeadlines')" in pet
    assert "t('pet.suggestCompare')" in pet
    assert "t('pet.suggestDocuments')" in pet
    assert "push({ kind: 'deadlines' })" in pet
    assert "push({ kind: 'documents' })" in pet
    assert 'href="/results#tracking"' in pet
    # The suggestion turns answer locally from verified data — they
    # never call the model.
    assert "case 'deadlines':" in pet and "case 'documents':" in pet
    assert "EXPANSION_PROGRAMS" in pet


def test_restyle2_b_plan_change_wiring():
    """One plan-change sentence proposes + asks to confirm; Confirm
    applies the patch and refreshes the checklist, Skip discards it —
    and the proposal never reaches the model."""
    pet = _read("src/components/CompassPet.tsx")
    assert "detectPlanChange(text, profile, countryNameList())" in pet
    assert "push({ kind: 'planChange', change: planChange, status: 'pending' })" in pet
    assert "case 'planChange':" in pet
    assert "resolvePlanChange(i, true)" in pet
    assert "resolvePlanChange(i, false)" in pet
    assert "t('pet.planConfirm')" in pet
    assert "t('pet.planSkip')" in pet
    assert "t('pet.planChangeAsk')" in pet
    assert "planChangePatch(turn.change)" in pet
    assert "refreshChecklist(nextProfile, EXPANSION_PROGRAMS)" in pet
    # The intercept returns before the normal send: the block that
    # pushes the planChange turn ends with a return, and the
    # sendAskTurn call below it is unreachable from that path.
    idx = pet.index("push({ kind: 'planChange'")
    assert pet.index("return;", idx) < pet.index("const isDevilTurn", idx)
    # The pet listens for the tracking section's continue entry.
    assert "window.addEventListener('pp-open-pet'" in pet


def test_restyle2_b_store_checklist():
    """The checklist lives in the store and persists like the rest of
    the profile; clearing data clears it too."""
    store = _read("src/lib/store.tsx")
    assert "checklist: ChecklistItem[]" in store
    assert "toggleChecklistItem" in store
    assert "refreshChecklist" in store
    assert "localStorage.getItem('pp-checklist')" in store
    assert "localStorage.setItem('pp-checklist'" in store
    assert "localStorage.removeItem('pp-checklist')" in store
    assert "mergeChecklist(prev, deriveChecklist(p, programmes))" in store


def test_restyle2_b_results_tracking_section():
    """The /results tracking section: comparison table, deadline
    countdowns, checkable list + timeline, interview stays unknown,
    and a continue-the-conversation entry back to the pet."""
    page = _read("src/app/results/page.tsx")
    assert 'id="tracking"' in page
    assert "t('results.trackingTitle')" in page
    assert "tf('results.trackingDaysLeft'" in page
    assert "parseDeadline(" in page
    assert "toggleChecklistItem(item.id)" in page
    assert "t('results.trackingInterview')" in page
    assert "window.dispatchEvent(new CustomEvent('pp-open-pet'))" in page
    assert "t('pet.openLabel')" in page
    # Comparison: the top evaluated programmes, fee + duration +
    # deadline from verified data.
    assert "shown.slice(0, 3)" in page
    assert "EXPANSION_PROGRAMS.find((x) => x.id === p.id)" in page


def test_restyle2_b_boundary_and_scope():
    """Hard boundary + scope pins: no admission probabilities or
    guarantees anywhere in the new module, no interview step is ever
    derived, no new top-level route, PrefChat untouched by this half,
    and the coordinator appended the #317 entry exactly once."""
    tracking = _read("src/lib/tracking.ts")
    assert "No admission probabilities" in tracking
    assert "ChecklistKind = 'deadline' | 'documents' | 'visa'" in tracking
    assert "'interview'" not in tracking
    assert "probability" not in tracking.lower()
    assert not (ROOT / "frontend/src/app/tracking").exists()
    prefchat = _read("src/components/PrefChat.tsx")
    assert "planChange" not in prefchat
    assert "Restyle 2" not in prefchat
    decisions = (ROOT / "DECISIONS.md").read_text(encoding="utf-8")
    # The worker kept its draft in /tmp; the coordinator appended the
    # #317 entry exactly once when the half landed.
    assert decisions.count("| 317 |") == 1
    assert "Gen UI behaviour" not in decisions
