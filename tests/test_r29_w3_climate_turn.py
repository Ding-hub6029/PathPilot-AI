"""Round 29 W3 — climate_turn marker: frontend cities-line dedupe.

Worker 2 (backend, E3) now marks every pref-chat reply with
``climate_turn`` (True exactly when the turn stated a climate
class or just answered climate), on both the fallback and the
model path — and the cities line is still placed on the countries
turn too (the R28 D2 evidence-in-hand pin), so it can appear in
``lines`` on two consecutive turns. The frontend dedupes via the
marker, not by expecting the server to remove it:

* ``PrefChatReply`` gains ``climate_turn?: boolean`` (persist
  path stores the reply whole — no whitelist change, same as the
  R28 D2 fields).
* PrefChat's ``scopeCitiesLines`` mapping prefers the marker when
  present — ``turn.reply?.climate_turn ?? !!extracted.climate`` —
  falling back to the extraction for old persisted snapshots,
  which carry no marker. The marker catches a climate stated in
  words that the extraction did not record; the old
  extraction-only rule then kept the cities line on the earlier
  countries turn instead of the climate turn.
* Model replies are NOT re-rendered (Worker 2's post-validation
  already pins their sentences verbatim; extending
  ``localisedFallbackLines`` to model replies was optional and
  is not done here) — a model turn never carries the block
  (``hasFallbackCitiesBlock`` vetoes ``ai_status === 'available'``)
  and passes through the scoping untouched.

The node harness compiles the real lib files (same file list as
test_r29_w1.py) and replays renderPrefTurns' two passes with the
marker-preferred mapping, which the Python pins below assert
verbatim in PrefChat.tsx so the mirror cannot drift silently.
"""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]

_ITEMS = [
    {"city": "Zurich", "climate": "four_seasons", "count": 3},
    {"city": "Lausanne", "climate": "cool", "count": 1},
]

_NODE_HARNESS = r"""
const chat = require(__OUT__ + '/chat.js');
const fb = require(__OUT__ + '/prefFallbackLines.js');
const en = require(__FE__ + '/messages/en.json');
const items = JSON.parse(process.argv[2]);
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + '\n  got  ' + g + '\n  want ' + w); fail++; }
  else console.log('PASS ' + name);
};
const tFor = (loc) => {
  const msgs = require(__FE__ + '/messages/' + loc + '.json');
  return (key, vars) => {
    let s = msgs[key] ?? en[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.split('{' + k + '}').join(String(v));
    return s;
  };
};
// Mirror of PrefChat.tsx renderPrefTurns' answeredClimate mapping
// (pinned verbatim by the Python source pins below): the backend
// marker wins when present; old snapshots fall back to extraction.
const answeredClimateFor = (reply) => (reply == null ? false : (reply.climate_turn ?? !!(reply.extracted && reply.extracted.climate)));
const oldAnsweredClimateFor = (reply) => !!(reply && reply.extracted && reply.extracted.climate);
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
    const rendered = renderTurn(turn, turn.offline, loc);
    const reply = rendered.find((b) => b.kind === 'reply');
    return reply ? reply.lines : [];
  });
  const scoped = fb.scopeCitiesLines(turns.map((turn, i) => ({
    lines: perTurn[i],
    carriesCitiesLine: fb.hasFallbackCitiesBlock(turn.reply),
    answeredClimate: answeredClimateFor(turn.reply),
  })));
  return turns.map((turn, i) => {
    const bs = chat.prefTurnBubbles(turn, null);
    return bs.map((b) => (b.kind === 'reply' ? { kind: 'reply', lines: scoped[i] } : b));
  });
};
const replyLinesOf = (conv, i) => conv[i].find((b) => b.kind === 'reply').lines;
// A fallback turn whose stored lines carry the cities line + the
// generic suggest line + the trailing question line (which
// prefTurnBubbles moves into a question bubble). Both turns carry
// the structured block — the backend places the cities line on the
// countries turn too (climate is the next question there).
const mkFallbackTurn = (id, question, extracted, nextQ, extraReply) => ({
  id, question,
  reply: { lines: ['STORED-CITIES', 'STORED-SUGGEST', 'STORED-QUESTION'],
    ai_status: 'unavailable', model: null,
    extracted, next_question: nextQ, done: nextQ === null,
    evidence_cities: items, climate_wanted: 'cool',
    ...(extraReply || {}) },
  replyLocale: 'zh-CN', offline: true,
});

// The re-localised cities line, in English — wording is pinned
// byte-identical by test_r28_d2.py; here it is only the value the
// scoping must keep on exactly one turn.
const probeReply = mkFallbackTurn(9, 'cool', { countries: ['Switzerland'], climate: 'cool' }, 'environment', { climate_turn: true }).reply;
const citiesEn = fb.localisedFallbackLines(probeReply, tFor('en'), 'en');
check('probe: fallback replacement is exactly the cities line', citiesEn && citiesEn.length, 1);

// --- 1. Marker on both turns: line kept only on the climate turn ---
const t0 = mkFallbackTurn(1, 'Switzerland', { countries: ['Switzerland'] }, 'climate', { climate_turn: false });
const t1 = mkFallbackTurn(2, 'cool', { countries: ['Switzerland'], climate: 'cool' }, 'environment', { climate_turn: true });
const conv = renderConversation([t0, t1], 'en');
check('marker: countries turn drops the cities line', replyLinesOf(conv, 0), []);
check('marker: climate turn keeps the cities line', replyLinesOf(conv, 1), citiesEn);
check('marker: countries question bubble intact', conv[0].find((b) => b.kind === 'question'), { kind: 'question', question: 'climate' });
check('marker: climate question bubble intact', conv[1].find((b) => b.kind === 'question'), { kind: 'question', question: 'environment' });

// --- 2. Marker catches a climate the extraction missed ---
// The user stated a cool preference in words; the extraction
// recorded no climate. The old extraction-only rule would keep
// the line on the countries turn instead of this one.
const s0 = mkFallbackTurn(1, 'Switzerland', { countries: ['Switzerland'] }, 'climate', { climate_turn: false });
const s1 = mkFallbackTurn(2, 'I like cool weather', { countries: ['Switzerland'] }, 'environment', { climate_turn: true });
check('stated-not-extracted: marker says climate turn', answeredClimateFor(s1.reply), true);
check('stated-not-extracted: extraction-only says not', oldAnsweredClimateFor(s1.reply), false);
const convS = renderConversation([s0, s1], 'en');
check('stated-not-extracted: cities line on the climate turn', replyLinesOf(convS, 1), citiesEn);
check('stated-not-extracted: countries turn drops it', replyLinesOf(convS, 0), []);

// --- 3. Old snapshot (no marker): extraction fallback, unchanged ---
const o0 = mkFallbackTurn(1, 'Switzerland', { countries: ['Switzerland'] }, 'climate', {});
const o1 = mkFallbackTurn(2, 'cool', { countries: ['Switzerland'], climate: 'cool' }, 'environment', {});
check('old snapshot: extraction fallback says climate turn', answeredClimateFor(o1.reply), true);
const convO = renderConversation([o0, o1], 'en');
check('old snapshot: cities line on the climate turn', replyLinesOf(convO, 1), citiesEn);
check('old snapshot: countries turn drops it', replyLinesOf(convO, 0), []);

// --- 4. No climate anywhere yet: first carrier keeps the line ---
const n0 = mkFallbackTurn(1, 'Switzerland', { countries: ['Switzerland'] }, 'climate', {});
const n1 = mkFallbackTurn(2, 'university town', { countries: ['Switzerland'], environment: 'campus' }, 'environment', {});
const convN = renderConversation([n0, n1], 'en');
check('no climate yet: first carrier keeps the line', replyLinesOf(convN, 0), citiesEn);
check('no climate yet: second carrier drops it', replyLinesOf(convN, 1), []);

// --- 5. Model turn between carriers: verbatim, never scoped ---
const mTurn = { id: 5, question: 'cool',
  reply: { lines: ['Zurich (four seasons): 3 programmes. Lausanne (cool): 1 programme.', 'STORED-QUESTION'],
    ai_status: 'available', model: 'deepseek/deepseek-v4.1-flash',
    extracted: { countries: ['Switzerland'], climate: 'cool' }, next_question: 'environment', done: false,
    evidence_cities: items, climate_wanted: 'cool', climate_turn: true },
  replyLocale: 'en', offline: false };
check('model turn is not a carrier', fb.hasFallbackCitiesBlock(mTurn.reply), false);
check('model reply lines render verbatim', fb.localisedReplyLines(mTurn.reply.lines, mTurn.reply, false, tFor('en'), 'en'), mTurn.reply.lines);
const convM = renderConversation([t0, mTurn, t1], 'en');
check('model between carriers: model lines untouched', replyLinesOf(convM, 1), ['Zurich (four seasons): 3 programmes. Lausanne (cool): 1 programme.']);
check('model between carriers: countries turn drops it', replyLinesOf(convM, 0), []);
check('model between carriers: climate turn keeps it', replyLinesOf(convM, 2), citiesEn);

// --- 6. Carrier gate ---
check('carrier: fallback with block', fb.hasFallbackCitiesBlock(t1.reply), true);
check('carrier: fallback without evidence is not', fb.hasFallbackCitiesBlock({ lines: ['x'], ai_status: 'unavailable', extracted: {} }), false);

if (fail) { console.log(fail + ' FAILURES'); process.exit(1); }
console.log('ALL R29 W3 CLIMATE_TURN HARNESS CASES PASS');
"""


def _run_node_harness(tmp_path):
    outdir = tmp_path / "r29w3_climate_lib"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/preferences.ts", "src/lib/chat.ts",
         "src/lib/prefFallbackLines.ts", "src/lib/format.ts",
         "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r29w3_climate_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("__OUT__", repr(str(outdir)))
        .replace("__FE__", repr(str(FE))), encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness), json.dumps(_ITEMS, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout, node.stdout


def test_r29_w3_climate_turn_harness(tmp_path):
    _run_node_harness(tmp_path)


def test_r29_w3_climate_turn_source_pins():
    """Type + wiring pins: the marker exists on the reply type, the
    PrefChat scoping mapping prefers it over the extraction, it is
    the single derivation site, and the backend sends it on both
    the fallback and the model path."""
    chat = (ROOT / "frontend/src/lib/chat.ts").read_text(encoding="utf-8")
    reply_seg = chat.split("export interface PrefChatReply {")[1].split(
        "export function isModelPrefReply")[0]
    assert "climate_turn?: boolean;" in reply_seg
    assert "Round 29 W2" in reply_seg
    helper = (ROOT / "frontend/src/lib/prefFallbackLines.ts").read_text(
        encoding="utf-8")
    like_seg = helper.split("export interface PrefFallbackReplyLike {")[1].split(
        "}")[0]
    assert "climate_turn?: boolean;" in like_seg
    prefchat = (ROOT / "frontend/src/components/PrefChat.tsx").read_text(
        encoding="utf-8")
    assert ("answeredClimate: turn.reply?.climate_turn ?? "
            "!!turn.reply?.extracted?.climate,") in prefchat
    assert prefchat.count("answeredClimate:") == 1
    backend = (ROOT / "backend/ai/pref_chat.py").read_text(encoding="utf-8")
    assert '"climate_turn": bool(climate_stated' in backend
    assert ('climate_turn = bool(climate_stated or "climate" in extracted)'
            in backend)


def test_r29_w3_climate_turn_locale_counts():
    """No new locale keys for this change (984 x 6 — 981 at Round 30
    + Round 31 G2's three sample.confirm* keys, unchanged by this change)."""
    msgs = {}
    for loc in LOCALES:
        msgs[loc] = json.loads(
            (FE / "messages" / f"{loc}.json").read_text(encoding="utf-8"))
    base = set(msgs["en"])
    assert len(base) == 984, len(base)
    for loc in LOCALES:
        assert set(msgs[loc]) == base, (loc, set(msgs[loc]) ^ base)
