"""Round 28 D1: stored-value re-localisation incomplete (re-test 22
item d, PARTIAL FAIL).

Passing already: /results English preference line fully localised;
user answer bubbles and the summary bubble localise. Failing, in the
English UI after a zh->en switch:

(1) The 8 "Got it, noted!" confirmation bubbles still showed Chinese
    values, e.g. "Got it, noted! 苏黎世", "Got it, noted! 适中",
    "Got it, noted! 瑞士 · 凉爽 · 大学城·校园氛围 · 还没想好 ·
    小班研讨".
(2) The 6 robot questions (environment, city, afterGrad, salary,
    pressure, teaching) stayed Chinese in English UI.
(3) The verified-cities line stays Chinese — NOT covered here: the
    D2 worker owns it via structured backend evidence
    (prefFallbackLines.ts). This file must not touch it.

Root cause (verified in code, not inferred):

(1) confirmedNotes are stored strings: confirmExtract (PrefChat.tsx)
    stores `extractedSummary(pendingExtract.extracted, t, locale)` —
    a ' · '-joined string built in the confirm-time locale — and
    saveReason stores the user's verbatim WHY text. The render
    printed the stored string verbatim under a re-localised "Got it,
    noted!" prefix. Round 27 W4 wired choiceLabel into the other
    bubbles but missed this one; its residual explicitly said
    confirmed-notes bubbles need lib/chat.ts work — this is that work.
(2) The robot's question is the LAST line of each stored reply (the
    backend appends the deterministic _question_line when
    next_question is non-null — backend/ai/pref_chat.py
    _render_pref_lines and _fallback_result, both paths), and
    renderPrefTurns printed reply.lines verbatim. The WHY case was
    already handled: the backend withholds the question on WHY turns
    and the deferredQuestion bubble renders it via t(ASK_KEY[...]).

Fix (render time only — storage, backend contract and the persist
whitelist untouched, so old snapshots benefit):

- lib/chat.ts gains `localisedConfirmedNote(note, t)`: split the
  stored note on ' · ' (space-dot-space — the environment label
  itself contains '·' WITHOUT spaces, "大学城·校园氛围", so it stays
  one segment), map each segment through the existing reverse map
  (choiceRefsForLabel, then choiceLabelFor in the current locale)
  and re-join with ' · '. A segment re-localises ONLY when it
  resolves unambiguously to a single choice ref (ambiguous labels
  like "新加坡"/"香港" country-vs-city stay verbatim); segments with
  no reverse-map match stay verbatim — that covers the salary
  ("80000 CHF") and the WHY reason in the user's own words
  ("“环境优美”"), which must NEVER be re-localised; a multi-label
  segment ("瑞士和英国", "瑞士、英国") stays verbatim (documented
  residual). A choice label can itself span the separator — the
  environment campus label is "University town · campus vibe" in
  en/es/fr/pt-BR/ar (spaced '·') — so the two-segment join is tried
  first, then the single segment. The confirmedNotes render in
  PrefChat.tsx prints through it; the "Got it, noted!" prefix already
  re-localised via t('wizard.chatOpThanks').
- lib/chat.ts `prefTurnBubbles` gains a `question` bubble kind: for
  a turn with NO why record and reply.next_question non-null, the
  trailing line leaves the reply bubble and a `question` bubble
  {question: next_question} is emitted AFTER it, so the component
  renders it via t(ASK_KEY[question]) in the current locale (the
  same rendering as the deferredQuestion kind). For a WHY turn the
  behaviour is exactly unchanged (strip defence + deferredQuestion
  after resolution). Only the deterministic trailing question line
  moves — model narration lines are never touched. The invariant
  relied on (last line is the question when next_question is
  non-null) is pinned here and by the backend's own tests
  (test_r16_w1.py: no-WHY turns still ask the next question last).

Deliberately unchanged: the stored turn message (the backend
re-fetch contract) is untouched; no re-fetch is introduced (Round
27 W1); no locale keys are added (977 keys in all 6 files, D2's
two wizard.prefFallback* keys included); the cities line is D2's.
(Round 29 W3 later added two keys — results.aiOffline and
wizard.chatPrefAiBack — and Round 29 W1 one more
(wizard.prefFallbackUnknown), so the count pin below is 980.)

Covers, with no API key and no network:

- node harness over compiled lib/chat.ts: localisedConfirmedNote
  on the re-test values (single labels, the full re-test note,
  salary, WHY reason, multi-label, ambiguous, slash-joined,
  cross-locale labels, the en-built campus label in zh) and
  prefTurnBubbles (non-WHY climate turn, all six re-test
  questions, WHY answered / live / with-why_followup unchanged,
  done turn, empty lines + next_question, the pre-round-16
  why_followup-without-why guard, offline template turn);
- source pins on the two render spots, the stored-message contract,
  and the no-re-fetch rule; locale key counts unchanged.

NOTE on the re-test report's slashes: the report wrote the note as
"瑞士/凉爽/大学城·校园氛围/还没想好/小班研讨", but no stored note
uses '/': the only producers are extractedSummary (joins ' · ')
and saveReason (verbatim WHY text). The '/' form is reporter
shorthand; it is pinned here as staying verbatim (one unresolvable
segment), not split.

Run from the project root:
    .venv/bin/pytest tests/test_r28_d1.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
LOCALES = ("en", "zh-CN", "es", "fr", "pt-BR", "ar")

# (stored note, locale, expected rendered note)
_NOTE_CASES = [
    ("苏黎世", "en", "Zurich"),
    ("适中", "en", "Moderate"),
    ("凉爽 · 瑞士", "en", "Cool · Switzerland"),
    ("大学城·校园氛围", "en", "University town · campus vibe"),
    ("瑞士 · 凉爽 · 大学城·校园氛围 · 还没想好 · 小班研讨", "en",
     "Switzerland · Cool · University town · campus vibe · Not sure yet · Small seminars"),
    ("80000 CHF", "en", "80000 CHF"),
    ("“环境优美”", "en", "“环境优美”"),
    ("瑞士和英国", "en", "瑞士和英国"),
    ("瑞士、英国", "en", "瑞士、英国"),
    ("新加坡", "en", "新加坡"),
    ("香港", "en", "香港"),
    ("瑞士 · “环境优美”", "en", "Switzerland · “环境优美”"),
    ("Cool · Switzerland · University town · campus vibe", "zh-CN",
     "凉爽 · 瑞士 · 大学城·校园氛围"),
    ("苏黎世", "zh-CN", "苏黎世"),
    ("", "en", ""),
    ("瑞士/凉爽/大学城·校园氛围/还没想好/小班研讨", "en",
     "瑞士/凉爽/大学城·校园氛围/还没想好/小班研讨"),
    ("瑞士 · 凉爽 · 苏黎世 · 适中", "en", "Switzerland · Cool · Zurich · Moderate"),
    ("Fresco", "en", "Cool"),
    ("Modérée", "en", "Moderate"),
    ("Ciudad universitaria · ambiente de campus", "en", "University town · campus vibe"),
]

# Real zh next-question lines (backend/ai/pref_chat.py
# _NEXT_QUESTION_LINES) — the trailing line of each stored reply.
_Q_ZH = {
    "climate": "你喜欢什么样的气候——暖和、凉爽、四季分明还是温和？",
    "environment": "你想住在什么样的地方——大城市、小城市、校园，还是安静的小镇？",
    "city": "有没有你心仪的城市？",
    "afterGrad": "毕业后你想留下来、回国、回老家，还是还没想好？",
    "salary": "毕业后你希望拿到多少薪水，用什么货币？",
    "pressure": "你能接受多大的压力——轻松、适中还是高强度？",
    "teaching": "你喜欢怎么上课——讲座、研讨，还是动手实践？",
}

_NODE_HARNESS = r"""
const chat = require(OUT + '/chat.js');
const en = require(FE + '/messages/en.json');
const noteCases = JSON.parse(process.argv[2]);
const qZh = JSON.parse(process.argv[3]);
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + ' -> ' + g + ' want ' + w); fail++; }
  else console.log('PASS ' + name);
};
const kinds = (bs) => bs.map((b) => b.kind);
const tFor = (loc) => {
  const msgs = require(FE + '/messages/' + loc + '.json');
  return (k) => msgs[k] ?? en[k] ?? k;
};

// --- (1) confirmed notes re-localise at render time --------------
for (const [note, loc, want] of noteCases) {
  check('localisedConfirmedNote ' + JSON.stringify(note) + ' in ' + loc,
    chat.localisedConfirmedNote(note, tFor(loc)), want);
}

// --- (2) robot question lines become `question` bubbles -----------
const CLIMATE_Q = qZh.climate;
const climateTurn = { id: 2, question: '凉爽',
  reply: { lines: ['凉爽记下了。', CLIMATE_Q], ai_status: 'available',
    extracted: { climate: 'cool' }, next_question: 'environment' },
  replyLocale: 'zh-CN', offline: false };
check('non-WHY climate turn: bubbles are user, reply, question',
  kinds(chat.prefTurnBubbles(climateTurn, null)), ['user', 'reply', 'question']);
check('non-WHY climate turn: reply drops the trailing question line',
  chat.prefTurnBubbles(climateTurn, null)[1], { kind: 'reply', lines: ['凉爽记下了。'] });
check('non-WHY climate turn: question bubble names environment',
  chat.prefTurnBubbles(climateTurn, null)[2], { kind: 'question', question: 'environment' });

// All six re-test 22 questions move the same way.
for (const q of ['environment', 'city', 'afterGrad', 'salary', 'pressure', 'teaching']) {
  const turn = { id: 10, question: 'x',
    reply: { lines: ['记下了。', qZh[q]], ai_status: 'available', next_question: q },
    replyLocale: 'zh-CN', offline: false };
  const bs = chat.prefTurnBubbles(turn, null);
  check('question ' + q + ': bubbles are user, reply, question', kinds(bs), ['user', 'reply', 'question']);
  check('question ' + q + ': reply keeps substance only', bs[1], { kind: 'reply', lines: ['记下了。'] });
  check('question ' + q + ': question bubble carries the id', bs[2], { kind: 'question', question: q });
}

// --- WHY turns are unchanged --------------------------------------
const modelReply = {
  lines: ['明白，你说那边环境优美，我记下了。', '苏黎世：四季分明。'],
  ai_status: 'available', model: 'deepseek/test-model',
  extracted: { countries: ['CH'], note: '那边环境优美' },
  next_question: 'climate',
  why_followup: { countries: ['CH'], note: '那边环境优美' },
};
const whyRecord = { countries: ['CH'], note: '那边环境优美', answer: null, skipped: false };
const whyOpen = { countries: ['CH'], note: '那边环境优美', turnId: 1 };
const whyLiveTurn = { id: 1, question: '我想去瑞士，因为那边环境优美',
  reply: modelReply, replyLocale: 'zh-CN', offline: false, why: whyRecord };
check('WHY live: bubbles are user, reply, why (no question bubble)',
  kinds(chat.prefTurnBubbles(whyLiveTurn, whyOpen)), ['user', 'reply', 'why']);
const whyAnswered = chat.answerTurnWhy(
  [{ id: 1, question: '我想去瑞士，因为那边环境优美', reply: modelReply,
     replyLocale: 'zh-CN', offline: false, why: whyRecord }],
  1, '喜欢湖光山色、空气清新、安静宜居', whyOpen);
check('WHY answered: bubbles are user, reply, why, whyAnswer, deferredQuestion',
  kinds(chat.prefTurnBubbles(whyAnswered[0], null)),
  ['user', 'reply', 'why', 'whyAnswer', 'deferredQuestion']);
check('WHY answered: no `question` bubble alongside the deferred one',
  chat.prefTurnBubbles(whyAnswered[0], null).some((b) => b.kind === 'question'), false);
check('WHY answered: deferred question is climate',
  chat.prefTurnBubbles(whyAnswered[0], null)[4], { kind: 'deferredQuestion', question: 'climate' });
const whyWithheldTurn = { id: 1, question: '瑞士',
  reply: { lines: ['已记录：瑞士。'], ai_status: 'available',
    why_followup: { countries: ['CH'] }, next_question: 'climate' },
  replyLocale: 'zh-CN', offline: false,
  why: { countries: ['CH'], answer: null, skipped: false } };
check('WHY turn with withheld line: reply lines intact',
  chat.prefTurnBubbles(whyWithheldTurn, null).find((b) => b.kind === 'reply').lines, ['已记录：瑞士。']);
check('WHY turn with withheld line: no question bubble',
  chat.prefTurnBubbles(whyWithheldTurn, null).some((b) => b.kind === 'question'), false);

// --- Done / empty / old-blob / offline edge cases ------------------
const doneTurn = { id: 3, question: '动手实践',
  reply: { lines: ['全部记下了。'], ai_status: 'available', next_question: null, done: true },
  replyLocale: 'zh-CN', offline: false };
check('done turn: no question bubble',
  kinds(chat.prefTurnBubbles(doneTurn, null)), ['user', 'reply']);
const emptyTurn = { id: 4, question: 'x',
  reply: { lines: [], ai_status: 'available', next_question: 'salary' },
  replyLocale: 'zh-CN', offline: false };
check('empty lines + next_question: no crash, question bubble still emitted',
  kinds(chat.prefTurnBubbles(emptyTurn, null)), ['user', 'reply', 'question']);
check('empty lines + next_question: reply bubble is empty',
  chat.prefTurnBubbles(emptyTurn, null)[1], { kind: 'reply', lines: [] });
// Pre-round-16 blob: reply carries why_followup but the turn has no
// why record — the line was withheld, so nothing moves.
const oldBlobTurn = { id: 5, question: '瑞士',
  reply: { lines: ['已记录：瑞士。', '苏黎世：四季分明。'], ai_status: 'available',
    why_followup: { countries: ['CH'] }, next_question: 'climate' },
  replyLocale: 'zh-CN', offline: false };
check('old blob (why_followup, no why): lines intact',
  chat.prefTurnBubbles(oldBlobTurn, null).find((b) => b.kind === 'reply').lines,
  ['已记录：瑞士。', '苏黎世：四季分明。']);
check('old blob (why_followup, no why): no question bubble',
  chat.prefTurnBubbles(oldBlobTurn, null).some((b) => b.kind === 'question'), false);
// Offline template turn: its question line moves too (the template
// path appends it the same way — backend _fallback_result).
const offlineTurn = { id: 6, question: '凉爽',
  reply: { lines: ['已核实的数据里有这些城市：苏黎世（四季分明，14 个项目）、洛桑（四季分明，11 个项目）。', qZh.environment],
    ai_status: 'unavailable', model: null,
    extracted: { climate: 'cool' }, next_question: 'environment' },
  replyLocale: 'zh-CN', offline: true };
const offlineBs = chat.prefTurnBubbles(offlineTurn, null);
check('offline template turn: bubbles are user, reply, question',
  kinds(offlineBs), ['user', 'reply', 'question']);
check('offline template turn: reply keeps the cities line only',
  offlineBs[1].lines,
  ['已核实的数据里有这些城市：苏黎世（四季分明，14 个项目）、洛桑（四季分明，11 个项目）。']);
check('offline template turn: question bubble names environment',
  offlineBs[2], { kind: 'question', question: 'environment' });

if (fail) { console.log(fail + ' FAILURES'); process.exit(1); }
console.log('ALL R28 D1 HARNESS CASES PASS');
"""


def _run_node_harness(tmp_path):
    outdir = tmp_path / "r28d1_lib"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/preferences.ts", "src/lib/chat.ts",
         "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r28d1_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(FE))), encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"],
           "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness),
         json.dumps(_NOTE_CASES, ensure_ascii=False),
         json.dumps(_Q_ZH, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout


def test_r28_d1_harness(tmp_path):
    """Confirmed notes re-localise at render time; non-WHY question
    lines move to a `question` bubble; WHY turns are unchanged."""
    _run_node_harness(tmp_path)


def test_r28_d1_confirmed_notes_render():
    """Source pins: the confirmedNotes render prints through
    localisedConfirmedNote (not the stored string verbatim), under
    the already-localised "Got it, noted!" prefix."""
    prefchat = (ROOT / "frontend/src/components/PrefChat.tsx").read_text(encoding="utf-8")
    assert "localisedConfirmedNote(note, t)" in prefchat
    assert "<p>{t('wizard.chatOpThanks')}</p>" in prefchat
    assert '<p className="mt-1 text-sm text-navy/70">{note}</p>' not in prefchat
    chat = (ROOT / "frontend/src/lib/chat.ts").read_text(encoding="utf-8")
    assert "export function localisedConfirmedNote(" in chat
    assert "choiceRefsForLabel" in chat and "choiceLabelFor" in chat


def test_r28_d1_question_bubble_render():
    """Source pins: renderPrefTurns renders the `question` bubble
    through ASK_KEY (same rendering as deferredQuestion, its own
    key), and the `question` kind exists in lib/chat.ts."""
    prefchat = (ROOT / "frontend/src/components/PrefChat.tsx").read_text(encoding="utf-8")
    assert "if (bubble.kind === 'question') {" in prefchat
    assert "pref-${turn.id}-question" in prefchat
    assert "pref-${turn.id}-deferred" in prefchat
    chat = (ROOT / "frontend/src/lib/chat.ts").read_text(encoding="utf-8")
    assert "| { kind: 'question'; question: Exclude<PrefNextQuestion, null> };" in chat
    assert "out.push({ kind: 'question', question: turn.reply.next_question });" in chat


def test_r28_d1_no_refetch_and_stored_contract():
    """No re-fetch is introduced (Round 27 W1): no fetch call in the
    chat components' locale path, no locale-dep effect in PrefChat,
    no fetch at all in lib/chat.ts — and the stored turn message
    (the backend contract) is untouched."""
    prefchat = (ROOT / "frontend/src/components/PrefChat.tsx").read_text(encoding="utf-8")
    assert "fetchJson<" not in prefchat
    assert not re.search(r"\}, \[[^\]]*locale[^\]]*\]\);", prefchat)
    assert "setTurns((prev) => [...prev, { id: turnId, question: trimmed," in prefchat
    chat = (ROOT / "frontend/src/lib/chat.ts").read_text(encoding="utf-8")
    assert "fetch(" not in chat


def test_r28_d1_locale_keys_unchanged():
    """No locale keys are added by THIS fix: 984 keys in every locale
    file (981 at Round 30 + Round 31 G2's three sample.confirm* keys),
    the same key set in all 6, and every key this fix renders through exists in
    all 6."""
    msgs = {
        loc: json.load(open(FE / "messages" / f"{loc}.json", encoding="utf-8"))
        for loc in LOCALES
    }
    base = set(msgs["en"])
    assert len(base) == 984, len(base)
    for loc in LOCALES:
        assert set(msgs[loc]) == base, (loc, set(msgs[loc]) ^ base)
    for key in (
        "wizard.chatOpThanks",
        "wizard.chatQCountries", "wizard.chatQClimate", "wizard.chatQEnvironment",
        "wizard.chatQCity", "wizard.chatQAfterGrad", "wizard.chatQSalary",
        "wizard.chatQPressure", "wizard.chatQTeaching",
    ):
        for loc in LOCALES:
            assert msgs[loc].get(key), f"{key} missing in {loc}"
