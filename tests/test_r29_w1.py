"""Round 29 W1 (frontend PrefChat render/localisation): re-test 23 item a.

E1 — six guidance ANSWERS stay Chinese in English UI. Root cause,
verified in code (not inferred): the offline pref-chat fallback's
generic unknown pair comes from backend/ai/assistant.py ``_T``
("unknown" + "unknown_2", returned as the template's two lines by
``assistant_ask`` / ``_fallback_result`` in ai/pref_chat.py when the
gateway is down and nothing matched). The cities line already had a
structured re-render (R28 D2); the unknown pair had none — the
render printed the stored request-locale lines verbatim, so all six
guidance turns (environment, city, afterGrad, salary, pressure,
teaching) showed "这个我从已核实的数据里查不到，不知道。可以开始
资格检查，逐项核对你的背景。" in the English UI. Fix, render-time
only: lib/prefFallbackLines.ts gains a reverse map from the exact
stored template line (any of the 6 locales) to its frontend locale
key — "unknown" -> new ``wizard.prefFallbackUnknown`` (backend
wording verbatim in all 6 locales), "unknown_2" -> the existing
``pet.suggestUnknown2`` (already byte-identical to the backend in
all 6 locales) — applied in localisedReplyLines to offline turns
only. Model replies (ai_status 'available') are never re-localised.
The joined single-line form of the pair splits into the two keys.
One pre-existing one-character drift was fixed along the way: the
frontend's ar ``pet.suggestUnknown2`` ended with "。" (U+3002) while
the backend's ar "unknown_2" ends with "." (U+002E) — the stored
line comes from the backend, so the frontend value now matches the
backend exactly (see test_r29_w1_backend_wording_pin).
Only these two fixed lines map; every other template line (a
country line, fee_unknown, free text) stays verbatim — fee_unknown
is a documented residual below, not a regression.

E2 — reason bubble has no value. Root cause, verified in code: the
WHY answer renders as a user bubble plus a BARE "Got it, noted!"
acknowledgement — the only "Got it, noted!" bubble with no value
line underneath it, so the reason answer never became a value bubble
like the other seven preference answers (re-test 23 item a: the
bubble was empty in both languages, while "Beautiful environment"
only appeared in the summary line). Fix: (a) PrefChat's whyAnswer
branch renders the value line under the thanks line, through
localisedConfirmedNote, exactly like the confirmedNotes bubbles;
(b) lib/chat.ts localisedConfirmedNote also re-localises an exact
KNOWN reason phrase via NOTE_PHRASE_FORMS (the same table
prefSummary's localiseCountryNote uses), so a WHY answer of
"环境优美" renders "Beautiful environment" in English — while a
free-text reason stays verbatim and the QUOTED form ("“环境优美”")
still stays verbatim, so the Round 28 D1 pins on it are unchanged.

E3-frontend — cities-line scoping. Root cause, verified in code:
the backend places the cities line whenever climate is the next
question as well as when the turn answers climate, so the
countries turn AND the climate turn both carried it (re-test 23
round 1). Fix, render-side over the whole turn list at once:
scopeCitiesLines keeps the cities line on the climate turn (the
first carrier whose extraction recorded a climate value, or whose
reply carries the backend's ``climate_turn`` marker — Round 29 W2:
True exactly when the turn stated a climate class or just answered
climate, so it catches a climate stated in words that the
extraction did not record; the marker is preferred when present,
the extraction is the fallback for old snapshots) and drops
it from every other carrier; with no climate-answering carrier the
first carrier keeps it. Within a turn, identical lines render once
(dedupeTemplateLines in localisedReplyLines — a backend-appended
duplicate never doubles). Backend lines are authoritative; Worker 2
owns the server-side append (deterministic sentences + cities line
+ structured evidence_cities/climate_wanted + the climate_turn
marker). The harness below pins the frontend half of the contract:
block present ⟺ lines[0] is the cities line; marker preferred,
extraction fallback.

Deliberate expectation change in test_r28_integration.py: its "no
structured block (old snapshot)" case expected the stored zh lines
verbatim in en. Under E1 the cities line still stays verbatim
there (no block to re-render it from), but the template unknown_2
line now localises — the case is updated to expect that, with a
comment. The locale key-count pins (977 at Round 28, 979 after
Round 29 W3's two keys) move to 980 with this worker's one key.

Run from the project root:
    .venv/bin/pytest tests/test_r29_w1.py -q -p no:cacheprovider
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
BACKEND = ROOT / "backend"
LOCALES = ("en", "zh-CN", "es", "fr", "pt-BR", "ar")

_ZH_UNKNOWN = "这个我从已核实的数据里查不到，不知道。"
_ZH_UNKNOWN2 = "可以开始资格检查，逐项核对你的背景。"
_ZH_FEE_UNKNOWN = "这个专业的学费在已核实的数据里查不到。"
# Backend ai/pref_chat.py _NEXT_QUESTION_LINES, zh-CN (the trailing
# line of each stored reply; prefTurnBubbles moves it out).
_Q_ZH = {
    "climate": "你喜欢什么样的气候——暖和、凉爽、四季分明还是温和？",
    "environment": "你想住在什么样的地方——大城市、小城市、校园，还是安静的小镇？",
    "city": "有没有你心仪的城市？",
    "afterGrad": "毕业后你想留下来、回国、回老家，还是还没想好？",
    "salary": "毕业后你希望拿到多少薪水，用什么货币？",
    "pressure": "你能接受多大的压力——轻松、适中还是高强度？",
    "teaching": "你喜欢怎么上课——讲座、研讨，还是动手实践？",
}
# Re-test 22 zh cities line + items (see test_r28_integration.py).
_ZH_CITIES = (
    "已核实的数据里有这些城市：苏黎世（四季分明，14 个项目，全部学位/方向）、"
    "洛桑（四季分明，11 个项目，全部学位/方向）。")
_ITEMS = [
    {"city": "Zurich", "climate": "four_seasons", "count": 14},
    {"city": "Lausanne", "climate": "four_seasons", "count": 11},
]
_EN_CITIES = (
    "The verified data lists these cities: "
    "Zurich (Four seasons, 14 programmes, all levels/fields), "
    "Lausanne (Four seasons, 11 programmes, all levels/fields).")
_EN_NO_MATCH = (
    "The verified data lists these cities in your chosen countries: "
    "Zurich (Four seasons), Lausanne (Four seasons) — none has a "
    "Cool climate. Climate is only a preference — it never decides "
    "eligibility, it only orders results. Want to try a different "
    "climate, or another country?")

# The six re-test 23 guidance turns, stored in zh (gateway down):
# (user message, extracted, next_question).
_E1_TURNS = [
    ("大学城", {"environment": "campus"}, "city"),
    ("苏黎世", {"city": "苏黎世"}, "afterGrad"),
    ("回国发展", {"afterGrad": "return_home"}, "salary"),
    ("80000 CHF", {"salary": {"amount": 80000, "currency": "CHF"}}, "pressure"),
    ("轻松一点", {"pressure": "low"}, "teaching"),
    ("小班研讨", {"teaching": "seminar"}, None),
]

# (stored confirmed note, locale, expected rendered note) — E2 new
# cases first, then the Round 28 D1 pins that must not move.
_NOTE_CASES = [
    ("环境优美", "en", "Beautiful environment"),
    ("环境优美", "zh-CN", "环境优美"),
    ("Beautiful environment", "zh-CN", "环境很美"),
    ("大学城", "en", "University town"),
    ("校园氛围", "en", "Campus vibe"),
    ("喜欢湖光山色、空气清新", "en", "喜欢湖光山色、空气清新"),
    ("瑞士 · 环境优美", "en", "Switzerland · Beautiful environment"),
    ("“环境优美”", "en", "“环境优美”"),
    ("瑞士 · “环境优美”", "en", "Switzerland · “环境优美”"),
    ("苏黎世", "en", "Zurich"),
    ("80000 CHF", "en", "80000 CHF"),
    ("瑞士 · 凉爽 · 大学城·校园氛围 · 还没想好 · 小班研讨", "en",
     "Switzerland · Cool · University town · campus vibe · Not sure yet · Small seminars"),
    ("Cool · Switzerland · University town · campus vibe", "zh-CN",
     "凉爽 · 瑞士 · 大学城·校园氛围"),
    ("环境优美·校园氛围", "en", "环境优美·校园氛围"),
    ("新加坡", "en", "新加坡"),
]

_NODE_HARNESS = r"""
const chat = require(OUT + '/chat.js');
const fb = require(OUT + '/prefFallbackLines.js');
const en = require(FE + '/messages/en.json');
const e1Turns = JSON.parse(process.argv[2]);
const qZh = JSON.parse(process.argv[3]);
const noteCases = JSON.parse(process.argv[4]);
const zhUnknown = process.argv[5], zhUnknown2 = process.argv[6];
const zhCities = process.argv[7], zhFeeUnknown = process.argv[8];
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + '\n  got  ' + g + '\n  want ' + w); fail++; }
  else console.log('PASS ' + name);
};
const kinds = (bs) => bs.map((b) => b.kind);
const tFor = (loc) => {
  const msgs = require(FE + '/messages/' + loc + '.json');
  return (key, vars) => {
    let s = msgs[key] ?? en[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.split('{' + k + '}').join(String(v));
    return s;
  };
};
const unknown = (loc) => tFor(loc)('wizard.prefFallbackUnknown');
const unknown2 = (loc) => tFor(loc)('pet.suggestUnknown2');
// What renderPrefTurns does for ONE turn: bubbles, then the reply
// bubble's lines through localisedReplyLines.
const renderTurn = (turn, offline, loc) => {
  const bs = chat.prefTurnBubbles(turn, null);
  const out = [];
  for (const b of bs) {
    if (b.kind === 'reply') {
      out.push({ kind: 'reply',
        lines: fb.localisedReplyLines(b.lines, turn.reply, offline, tFor(loc), loc) });
    } else out.push(b);
  }
  return out;
};
// What renderPrefTurns does for the WHOLE conversation (Round 29
// E3 two-pass): per-turn localised lines, then scopeCitiesLines.
const renderConversation = (turns, loc) => {
  const perTurn = turns.map((turn) => {
    const rendered = renderTurn(turn, true, loc);
    const reply = rendered.find((b) => b.kind === 'reply');
    return reply ? reply.lines : [];
  });
  const scoped = fb.scopeCitiesLines(turns.map((turn, i) => ({
    lines: perTurn[i],
    carriesCitiesLine: fb.hasFallbackCitiesBlock(turn.reply),
    // Same mapping as PrefChat's renderPrefTurns (Round 29 W2's
    // `climate_turn` marker preferred when present — it catches a
    // climate stated in words that the extraction did not record;
    // old snapshots without the marker fall back to the extraction).
    answeredClimate: turn.reply && turn.reply.climate_turn !== undefined && turn.reply.climate_turn !== null
      ? !!turn.reply.climate_turn
      : !!(turn.reply && turn.reply.extracted && turn.reply.extracted.climate),
  })));
  return turns.map((turn, i) => {
    const bs = chat.prefTurnBubbles(turn, null);
    return bs.map((b) => (b.kind === 'reply' ? { kind: 'reply', lines: scoped[i] } : b));
  });
};
const mkTurn = (id, question, extracted, nextQ, extraReply) => ({
  id, question,
  reply: { lines: [zhUnknown, zhUnknown2].concat(nextQ ? [qZh[nextQ]] : []),
    ai_status: 'unavailable', model: null,
    extracted, next_question: nextQ, done: nextQ === null,
    ...(extraReply || {}) },
  replyLocale: 'zh-CN', offline: true,
});

// --- E1: the six guidance turns re-localise in English ----------
// The next question after each turn is the stored zh question line;
// it leaves the reply bubble (question bubble) in every case.
for (const [question, extracted, nextQ] of e1Turns) {
  const turn = mkTurn(10, question, extracted, nextQ);
  const rendered = renderTurn(turn, true, 'en');
  check('E1 ' + question + ': reply lines are the English unknown pair',
    rendered.find((b) => b.kind === 'reply').lines,
    [unknown('en'), unknown2('en')]);
  check('E1 ' + question + ': no Chinese template line leaks',
    rendered.find((b) => b.kind === 'reply').lines.some((l) => l.includes('查不到') || l.includes('资格检查')), false);
  if (nextQ) {
    check('E1 ' + question + ': question bubble carries ' + nextQ,
      rendered.find((b) => b.kind === 'question'), { kind: 'question', question: nextQ });
  } else {
    check('E1 ' + question + ': done turn has no question bubble',
      rendered.some((b) => b.kind === 'question'), false);
  }
}
// One zh turn in Spanish: the same pair, Spanish wording.
{
  const turn = mkTurn(11, '大学城', { environment: 'campus' }, 'city');
  check('E1 es: reply lines are the Spanish unknown pair',
    renderTurn(turn, true, 'es').find((b) => b.kind === 'reply').lines,
    [unknown('es'), unknown2('es')]);
}
// An English-stored pair in zh UI renders zh.
{
  const turn = { id: 12, question: 'campus',
    reply: { lines: [unknown('en'), unknown2('en'), qZh.city],
      ai_status: 'unavailable', model: null,
      extracted: { environment: 'campus' }, next_question: 'city', done: false },
    replyLocale: 'en', offline: true };
  check('E1 en-stored in zh: reply lines are the Chinese unknown pair',
    renderTurn(turn, true, 'zh-CN').find((b) => b.kind === 'reply').lines,
    [unknown('zh-CN'), unknown2('zh-CN')]);
}
// The joined single-line form splits into the two keys.
{
  const turn = { id: 13, question: '大学城',
    reply: { lines: [zhUnknown + zhUnknown2, qZh.city],
      ai_status: 'unavailable', model: null,
      extracted: { environment: 'campus' }, next_question: 'city', done: false },
    replyLocale: 'zh-CN', offline: true };
  check('E1 joined pair: splits into the two English lines',
    renderTurn(turn, true, 'en').find((b) => b.kind === 'reply').lines,
    [unknown('en'), unknown2('en')]);
}
// Model replies are NEVER re-localised, even with identical lines.
{
  const modelTurn = { id: 14, question: '大学城',
    reply: { lines: [zhUnknown, zhUnknown2, qZh.city],
      ai_status: 'available', model: 'deepseek/test-model',
      extracted: { environment: 'campus' }, next_question: 'city', done: false },
    replyLocale: 'zh-CN', offline: false };
  check('E1 model reply: lines stay verbatim (trust over translation)',
    renderTurn(modelTurn, false, 'en').find((b) => b.kind === 'reply').lines,
    [zhUnknown, zhUnknown2]);
  check('E1 offline flag with a model reply: still verbatim (ai_status veto)',
    fb.localisedReplyLines([zhUnknown, zhUnknown2],
      { ai_status: 'available', lines: [zhUnknown, zhUnknown2] }, true, tFor('en'), 'en'),
    [zhUnknown, zhUnknown2]);
}
// A backend-appended duplicate of a line renders once per turn.
check('E1+E3 within-turn dedupe: a repeated unknown line renders once',
  fb.localisedReplyLines([zhUnknown, zhUnknown2, zhUnknown],
    { ai_status: 'unavailable', lines: [zhUnknown, zhUnknown2, zhUnknown] }, true, tFor('en'), 'en'),
  [unknown('en'), unknown2('en')]);
// Lines that are not the unknown pair stay verbatim — including the
// fee_unknown template line, which E1 deliberately does NOT map
// (documented residual: no frontend key exists for it yet).
check('E1 non-template lines stay verbatim (incl. fee_unknown residual)',
  fb.localisedReplyLines(['苏黎世：四季分明。', zhFeeUnknown],
    { ai_status: 'unavailable', lines: ['苏黎世：四季分明。', zhFeeUnknown] }, true, tFor('en'), 'en'),
  ['苏黎世：四季分明。', zhFeeUnknown]);

// --- E2: reason phrases re-localise in confirmed notes -----------
for (const [note, loc, want] of noteCases) {
  check('E2 localisedConfirmedNote ' + JSON.stringify(note) + ' in ' + loc,
    chat.localisedConfirmedNote(note, tFor(loc)), want);
}

// --- E3: cities line scoped to the climate turn ------------------
// Pure scopeCitiesLines cases.
{
  const C = 'CITIES', N = 'NO-MATCH';
  check('E3 climate carrier keeps, earlier carrier drops',
    fb.scopeCitiesLines([
      { lines: [C], carriesCitiesLine: true, answeredClimate: false },
      { lines: [C, N], carriesCitiesLine: true, answeredClimate: true },
    ]), [[], [C, N]]);
  check('E3 no climate answer: first carrier keeps',
    fb.scopeCitiesLines([
      { lines: [C], carriesCitiesLine: true, answeredClimate: false },
      { lines: [C], carriesCitiesLine: true, answeredClimate: false },
    ]), [[C], []]);
  check('E3 single carrier keeps',
    fb.scopeCitiesLines([{ lines: [C], carriesCitiesLine: true, answeredClimate: false }]),
    [[C]]);
  check('E3 non-carriers pass through untouched',
    fb.scopeCitiesLines([
      { lines: ['model line'], carriesCitiesLine: false, answeredClimate: false },
      { lines: [C], carriesCitiesLine: true, answeredClimate: true },
    ]), [['model line'], [C]]);
  check('E3 no carriers: unchanged',
    fb.scopeCitiesLines([{ lines: ['a', 'b'], carriesCitiesLine: false, answeredClimate: false }]),
    [['a', 'b']]);
}
// The re-test 23 two-turn conversation, stored zh, rendered en:
// countries turn (cities block, climate is next) + climate turn
// (cities block, climate answered). The cities line survives on the
// climate turn only; both question bubbles survive.
{
  const items = JSON.parse(process.argv[9]);
  const enCities = process.argv[10], enNoMatch = process.argv[11];
  const countriesTurn = { id: 1, question: '我想去瑞士，因为那边环境优美',
    reply: { lines: [zhCities, zhUnknown2, qZh.climate], ai_status: 'unavailable', model: null,
      extracted: { countries: ['CH'], note: '那边环境优美' }, next_question: 'climate', done: false,
      evidence_cities: items, climate_wanted: null },
    replyLocale: 'zh-CN', offline: true };
  const climateTurn = { id: 2, question: '凉爽',
    reply: { lines: [zhCities, zhUnknown2, qZh.environment], ai_status: 'unavailable', model: null,
      extracted: { climate: 'cool' }, next_question: 'environment', done: false,
      evidence_cities: items, climate_wanted: 'cool' },
    replyLocale: 'zh-CN', offline: true };
  const rendered = renderConversation([countriesTurn, climateTurn], 'en');
  check('E3 conversation: countries turn loses the cities line',
    rendered[0].find((b) => b.kind === 'reply').lines, []);
  check('E3 conversation: climate turn keeps cities + no-match',
    rendered[1].find((b) => b.kind === 'reply').lines, [enCities, enNoMatch]);
  check('E3 conversation: countries question bubble survives',
    rendered[0].find((b) => b.kind === 'question'), { kind: 'question', question: 'climate' });
  check('E3 conversation: climate question bubble survives',
    rendered[1].find((b) => b.kind === 'question'), { kind: 'question', question: 'environment' });
  check('E3 conversation: the cities line appears exactly once',
    rendered.flatMap((bs) => bs.filter((b) => b.kind === 'reply').flatMap((b) => b.lines))
      .filter((l) => l === enCities).length, 1);
}
// The `climate_turn` marker (Round 29 W2): a carrier turn whose
// reply marks climate_turn=true keeps the cities line even when its
// extraction recorded no climate value (climate stated in words),
// over an earlier carrier whose extraction did record one — the
// marker is the dedupe signal, the extraction only the fallback.
{
  const items = JSON.parse(process.argv[9]);
  const enCities = process.argv[10], enNoMatch = process.argv[11];
  const countriesTurn = { id: 1, question: '瑞士',
    reply: { lines: [zhCities, zhUnknown2, qZh.climate], ai_status: 'unavailable', model: null,
      extracted: { countries: ['CH'] }, next_question: 'climate', done: false,
      evidence_cities: items, climate_wanted: null },
    replyLocale: 'zh-CN', offline: true };
  const statedTurn = { id: 2, question: '喜欢凉爽的天气',
    reply: { lines: [zhCities, zhUnknown2, qZh.environment], ai_status: 'unavailable', model: null,
      extracted: {}, next_question: 'environment', done: false,
      evidence_cities: items, climate_wanted: 'cool', climate_turn: true },
    replyLocale: 'zh-CN', offline: true };
  const rendered = renderConversation([countriesTurn, statedTurn], 'en');
  check('E3 climate_turn marker: stated turn keeps the cities line',
    rendered[1].find((b) => b.kind === 'reply').lines, [enCities, enNoMatch]);
  check('E3 climate_turn marker: earlier carrier drops it',
    rendered[0].find((b) => b.kind === 'reply').lines, []);
}
// A model turn between two carriers is never touched by scoping.
{
  const items = JSON.parse(process.argv[9]);
  const modelTurn = { id: 3, question: '瑞士有哪些好学校？',
    reply: { lines: ['苏黎世：四季分明。', qZh.climate], ai_status: 'available', model: 'deepseek/test-model',
      extracted: {}, next_question: 'climate', done: false },
    replyLocale: 'zh-CN', offline: false };
  check('E3 model turn between carriers: verbatim lines',
    renderTurn(modelTurn, false, 'en').find((b) => b.kind === 'reply').lines,
    ['苏黎世：四季分明。']);
}

if (fail) { console.log(fail + ' FAILURES'); process.exit(1); }
console.log('ALL R29 W1 HARNESS CASES PASS');
"""


def _run_node_harness(tmp_path):
    outdir = tmp_path / "r29w1_lib"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/preferences.ts", "src/lib/chat.ts",
         "src/lib/prefFallbackLines.ts", "src/lib/format.ts",
         "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r29w1_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(FE))), encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness),
         json.dumps(_E1_TURNS, ensure_ascii=False),
         json.dumps(_Q_ZH, ensure_ascii=False),
         json.dumps(_NOTE_CASES, ensure_ascii=False),
         _ZH_UNKNOWN, _ZH_UNKNOWN2, _ZH_CITIES, _ZH_FEE_UNKNOWN,
         json.dumps(_ITEMS, ensure_ascii=False),
         _EN_CITIES, _EN_NO_MATCH],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout, node.stdout


def test_r29_w1_harness(tmp_path):
    """E1 unknown-pair re-localisation, E2 reason-phrase
    re-localisation, E3 cities-line scoping — all in the node
    harness over the compiled frontend libs."""
    _run_node_harness(tmp_path)


def _backend_templates() -> dict:
    """backend/ai/assistant.py ``_T`` (the localised template
    table), as a plain dict."""
    src = (BACKEND / "ai" / "assistant.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "_T"):
            return ast.literal_eval(node.value)
    raise AssertionError("backend _T table not found")


def test_r29_w1_backend_wording_pin():
    """The E1 reverse map copies the backend wording verbatim: the
    new ``wizard.prefFallbackUnknown`` equals backend "unknown" and
    the reused ``pet.suggestUnknown2`` equals backend "unknown_2"
    in all 6 locales. Any drift fails here first."""
    backend = _backend_templates()
    for loc in LOCALES:
        msgs = json.load(open(FE / "messages" / f"{loc}.json", encoding="utf-8"))
        assert msgs["wizard.prefFallbackUnknown"] == backend[loc]["unknown"], loc
        assert msgs["pet.suggestUnknown2"] == backend[loc]["unknown_2"], loc


def test_r29_w1_locale_keys():
    """994 keys in every locale file (981 at Round 30 + Round 31
    G2's three sample.confirm* keys + Restyle 2 behaviour's ten keys;
    Round 33 swaps common.languages for home.rankingRecords, net
    zero), the same key set in all 6, and every key E1/E2/E3 renders
    through exists in all 6."""
    msgs = {
        loc: json.load(open(FE / "messages" / f"{loc}.json", encoding="utf-8"))
        for loc in LOCALES
    }
    base = set(msgs["en"])
    assert len(base) == 994, len(base)
    for loc in LOCALES:
        assert set(msgs[loc]) == base, (loc, set(msgs[loc]) ^ base)
    for key in (
        "home.rankingRecords",
        "wizard.prefFallbackUnknown", "pet.suggestUnknown2",
        "wizard.prefFallbackCitiesLine", "wizard.prefFallbackCityItem",
        "wizard.chatOpClimateNoMatch", "wizard.chatOpThanks",
        "wizard.noteBeautifulEnv", "wizard.noteUniversityTown",
        "wizard.noteCampusVibe",
    ):
        for loc in LOCALES:
            assert msgs[loc].get(key), f"{key} missing in {loc}"


def test_r29_w1_source_pins():
    """Wiring pins: PrefChat's reply branch renders the
    conversation-scoped lines (not a per-turn localisedReplyLines
    call), the whyAnswer acknowledgement carries the value line,
    and the helpers exist with the E1/E2/E3 entry points."""
    prefchat = (ROOT / "frontend/src/components/PrefChat.tsx").read_text(encoding="utf-8")
    assert "const lines = scopedReplyLines[turnIndex];" in prefchat
    assert "scopeCitiesLines(turns.map" in prefchat
    assert "hasFallbackCitiesBlock(turn.reply)" in prefchat
    assert "answeredClimate: turn.reply?.climate_turn ?? !!turn.reply?.extracted?.climate," in prefchat
    assert "localisedReplyLines(replyBubble.lines, turn.reply, turn.offline, tf, locale)" in prefchat
    assert "const lines = localisedReplyLines(bubble.lines, turn.reply, turn.offline, tf, locale);" not in prefchat
    assert "<p>{t('wizard.chatOpThanks')}</p>" in prefchat
    assert "{localisedConfirmedNote(bubble.answer, t)}</p>" in prefchat
    assert "<p>{bubble.answer}</p>" in prefchat
    helper = (ROOT / "frontend/src/lib/prefFallbackLines.ts").read_text(encoding="utf-8")
    for name in ("export function localiseTemplateLines(",
                 "export function dedupeTemplateLines(",
                 "export function scopeCitiesLines(",
                 "export function hasFallbackCitiesBlock("):
        assert name in helper, name
    assert "wizard.prefFallbackUnknown" in helper
    chat = (ROOT / "frontend/src/lib/chat.ts").read_text(encoding="utf-8")
    assert "NOTE_PHRASE_FORMS" in chat
    assert "function localisedNotePhrase(" in chat
