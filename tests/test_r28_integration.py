"""Round 28 integration: the D1 question bubble and the D2 fallback
re-render compose in ``renderPrefTurns``.

The two halves touch the SAME stored reply lines, so they must
compose without stepping on each other:

- D1 (``prefTurnBubbles``, lib/chat.ts) moves the trailing
  deterministic question line out of the reply bubble into a
  ``question`` bubble for non-WHY turns — the reply bubble keeps
  only the substance/prefix lines.
- D2 (``localisedFallbackLines``, lib/prefFallbackLines.ts)
  replaces the stored deterministic prefix lines ``lines[0..1]``
  (cities + generic suggest) in the current locale, from the
  structured evidence block.
- The wiring (``localisedReplyLines``, same file) composes them:
  it takes the BUBBLE lines (already question-stripped by D1) and
  returns ``[...replacement, ...bubbleLines.slice(2)]`` — slice(2)
  drops exactly the stored prefix lines, never the question line,
  which renders separately via ``t(ASK_KEY[...])``.

The re-test 22 turn, verbatim: cold (no-key) pref_answer for
"凉爽" with Switzerland known, stored in zh, rendered in en.
The stored zh lines are the pre-change backend output, byte for
byte (see test_r28_d2.py); the en expectations are the D2 helper's
pinned outputs.

Run from the project root:
    .venv/bin/pytest tests/test_r28_integration.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"

_ZH_LINES = [
    "已核实的数据里有这些城市：苏黎世（四季分明，14 个项目，全部学位/方向）、洛桑（四季分明，11 个项目，全部学位/方向）。",
    "可以开始资格检查，逐项核对你的背景。",
    "你想住在什么样的地方——大城市、小城市、校园，还是安静的小镇？",
]
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
# Round 29 E1: the backend template's unknown_2 line, English
# (backend/ai/assistant.py _T "unknown_2" — see test_r29_w1.py,
# which pins it against the backend in all 6 locales).
_EN_UNKNOWN2 = "Start the eligibility check to go through your background rule by rule."

_STORED_ZH_TURN = {
    "id": 7,
    "question": "凉爽",
    "reply": {
        "lines": _ZH_LINES,
        "evidence_url": None,
        "ai_status": "unavailable",
        "model": None,
        "sources": [
            {"id": "climate:zurich", "url": "https://en.wikipedia.org/wiki/Zurich#Climate", "title": "Zurich climate"},
            {"id": "climate:lausanne", "url": "https://en.wikipedia.org/wiki/Lausanne#Climate", "title": "Lausanne climate"},
        ],
        "extracted": {"climate": "cool"},
        "next_question": "environment",
        "done": False,
        "why_followup": None,
        "evidence_cities": _ITEMS,
        "climate_wanted": "cool",
    },
    "replyLocale": "zh-CN",
    "offline": True,
}

# (name, turn, offline, locale, expected rendered reply lines,
#  expected bubble kinds)
_COMPOSED_CASES = [
    ("re-test turn in en: cities + no-match in English, question separate",
     _STORED_ZH_TURN, True, "en",
     [_EN_CITIES, _EN_NO_MATCH],
     ["user", "reply", "question"]),
    ("re-test turn in zh: cities + no-match sentence in zh (suggest line replaced, as in en)",
     _STORED_ZH_TURN, True, "zh-CN",
     [_ZH_LINES[0],
      "你选的国家里有这些城市：苏黎世（四季分明）、洛桑（四季分明），"
      "其中没有凉爽气候的城市。气候只是偏好，不影响资格，只影响排序。"
      "要换个气候偏好，或者换个国家看看吗？"],
     ["user", "reply", "question"]),
    ("match case in en: only the cities line",
     {**_STORED_ZH_TURN,
      "reply": {**_STORED_ZH_TURN["reply"], "climate_wanted": "four_seasons"}},
     True, "en",
     [_EN_CITIES],
     ["user", "reply", "question"]),
    ("model reply: verbatim lines, question still separate",
     {**_STORED_ZH_TURN,
      "reply": {**_STORED_ZH_TURN["reply"], "ai_status": "available",
                "evidence_cities": None, "climate_wanted": None},
      "offline": False},
     False, "en",
     _ZH_LINES[:2],
     ["user", "reply", "question"]),
    ("no structured block (old snapshot): cities line verbatim, "
     "template unknown line localised (Round 29 E1)",
     {**_STORED_ZH_TURN,
      "reply": {k: v for k, v in _STORED_ZH_TURN["reply"].items()
                if k not in ("evidence_cities", "climate_wanted")}},
     True, "en",
     # Round 29 E1 (deliberate change): without the block the cities
     # line still cannot re-render, so it stays verbatim — but the
     # second line is the backend template's unknown_2, which E1
     # re-localises at render. The old expectation (_ZH_LINES[:2]
     # verbatim) is superseded by tests/test_r29_w1.py.
     [_ZH_LINES[0], _EN_UNKNOWN2],
     ["user", "reply", "question"]),
    ("offline flag false with a block present: verbatim (explicit gate)",
     _STORED_ZH_TURN, False, "en",
     _ZH_LINES[:2],
     ["user", "reply", "question"]),
]

_NODE_HARNESS = r"""
const chat = require(OUT + '/chat.js');
const fb = require(OUT + '/prefFallbackLines.js');
const en = require(FE + '/messages/en.json');
const cases = JSON.parse(process.argv[2]);
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
// What renderPrefTurns does for one turn: bubbles from prefTurnBubbles,
// then the reply bubble's lines through localisedReplyLines.
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
for (const [name, turn, offline, loc, wantLines, wantKinds] of cases) {
  const rendered = renderTurn(turn, offline, loc);
  check(name + ' [bubble kinds]', kinds(rendered), wantKinds);
  check(name + ' [rendered reply lines]',
    rendered.find((b) => b.kind === 'reply').lines, wantLines);
  // The question line is never inside the rendered reply lines.
  const q = rendered.find((b) => b.kind === 'question');
  if (q) {
    check(name + ' [question bubble carries the id, not text]',
      q, { kind: 'question', question: turn.reply.next_question });
    check(name + ' [no stored question line leaks into reply lines]',
      rendered.find((b) => b.kind === 'reply').lines.includes(turn.reply.lines[2]), false);
  }
}
// WHY turn: no question bubble; the prefix still re-renders.
const whyTurn = { id: 8, question: '瑞士',
  reply: { lines: JSON.parse(process.argv[5]).slice(0, 2), ai_status: 'unavailable',
    extracted: { countries: ['CH'] }, next_question: 'climate',
    why_followup: { countries: ['CH'] },
    evidence_cities: JSON.parse(process.argv[3]), climate_wanted: 'cool' },
  replyLocale: 'zh-CN', offline: true,
  why: { countries: ['CH'], answer: null, skipped: false } };
const whyRendered = renderTurn(whyTurn, true, 'en');
check('WHY turn: bubbles are user, reply, why (no question bubble)',
  kinds(whyRendered), ['user', 'reply', 'why']);
check('WHY turn: prefix re-renders in English',
  whyRendered.find((b) => b.kind === 'reply').lines,
  [JSON.parse(process.argv[4])[0], JSON.parse(process.argv[4])[1]]);
if (fail) { console.log(fail + ' FAILURES'); process.exit(1); }
console.log('ALL R28 INTEGRATION HARNESS CASES PASS');
"""


def test_r28_integration_composed_render(tmp_path):
    """The D1 question bubble and the D2 fallback re-render compose:
    a stored zh offline climate turn renders in en as the English
    cities line + English no-match sentence, with the environment
    question as a separate bubble — and verbatim everywhere the
    structured block is absent, except the known template lines,
    which Round 29 E1 re-localises (see the no-block case)."""
    outdir = tmp_path / "r28int_lib"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/preferences.ts", "src/lib/chat.ts",
         "src/lib/prefFallbackLines.ts", "src/lib/format.ts",
         "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r28int_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(FE))), encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness), json.dumps(_COMPOSED_CASES, ensure_ascii=False),
         json.dumps(_ITEMS, ensure_ascii=False),
         json.dumps([_EN_CITIES, _EN_NO_MATCH], ensure_ascii=False),
         json.dumps(_ZH_LINES, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout


def test_r28_integration_wiring_present():
    """Source pin: renderPrefTurns routes the reply bubble's lines
    through localisedReplyLines (D1 bubble lines in, current locale
    out) — the one place D1 and D2 compose. Round 29 E3 moved the
    call into the two-pass scoping head (pass 1 computes the lines,
    pass 2 scopes the cities line), so the pin follows the call
    there; the reply branch now renders scopedReplyLines."""
    src = (ROOT / "frontend/src/components/PrefChat.tsx").read_text(encoding="utf-8")
    assert ("localisedReplyLines(replyBubble.lines, turn.reply, turn.offline, tf, locale)"
            in src)
    assert "const lines = scopedReplyLines[turnIndex];" in src
    assert "import { localisedReplyLines, scopeCitiesLines, hasFallbackCitiesBlock } from '../lib/prefFallbackLines';" in src
    helper = (ROOT / "frontend/src/lib/prefFallbackLines.ts").read_text(encoding="utf-8")
    assert "export function localisedReplyLines(" in helper
