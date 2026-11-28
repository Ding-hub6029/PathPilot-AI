"""Round 34 D2 — wizard conversation duplicates after 8/8
(re-test 29 defect #2).

Reproduction (real PrefChat mounted in jsdom, gateway-down template
replies, 8 answers + WHY + confirms — see the D2 report): at 8/8 the
conversation read

  turn 1..8 (user bubble + reply + next question) …
  "Got it, noted!" Cool / "Got it, noted!" University town · …
  … seven detached noted bubbles, one per confirmed answer …
  summary bubble ("Here's what I noted down: …")

Root cause (verified in code, then reproduced): confirmExtract
appended every confirmation summary to the `confirmedNotes` list,
and the model branch rendered that list as a detached block AFTER
all turns (`{confirmedNotes.length > 0 && !pendingExtract &&
confirmedNotes.map(...)}`). Each confirmed answer's value therefore
rendered TWICE — once as its turn's user bubble, once as the noted
bubble's value line — and the noted bubbles arrived delayed (only
after the confirm tap) and out of order (piled after all turns,
not with the answer they confirm). The completed Q&A read twice
below the 8/8 header. Same family as the re-test 27 note.

Fix (same pattern as Round 16's WHY-in-turn fix): the confirmation
attaches to the turn it confirms — `PrefTurn.confirmedNote`, set by
confirmExtract on the latest turn (the same anchor the WHY backstop
uses) — and renders inside that turn as the last bubble before the
next question, via a new `confirmed` kind in `prefTurnBubbles`
(lib/chat.ts). The turn's note persists with the turn (serialize /
parse whitelist, same pattern as `why`), so leave-and-return keeps
it attached. confirmExtract no longer appends to `confirmedNotes`:
that list now holds ONLY notes with no turn to attach to (a
turn-less WHY answer, or a snapshot restored from before this
round), which still render in the old block — a note is never in
both places, so each "Got it, noted!" appears exactly once per
answer, in order, inside its turn. The 8/8 summary, the questions,
the answers and the guided flow are untouched.

Covers, with no API key and no network:
- node harness over the REAL lib/chat.ts (compiled with tsc):
  bubble order with / without a confirmed note (plain, WHY
  answered, WHY live, done turn, blank note), and the
  serialize/parse round-trip of the turn note (including old blobs
  without it and a malformed note) — the confirmedNotes list still
  round-trips (Round 15 pin preserved);
- renderToString mount of the REAL PrefChat (compiled with tsc,
  seeded pp-prefchat snapshots): a post-fix 8/8 run renders
  "Got it, noted!" exactly 8 times (1 WHY ack + 7 turn notes), each
  note before its turn's next question, the summary once, the
  Finish button present; a pre-fix snapshot (notes in the list,
  turns without notes) still renders its legacy notes once each,
  after the turns;
- source pins: confirmExtract attaches to the turn and no longer
  appends to the list, renderPrefTurns renders the `confirmed`
  bubble, the legacy block is kept for turn-less notes, no new
  locale keys.

The harness pins FAIL on pre-fix code (verified by running them
against the saved pre-fix lib/chat.ts + PrefChat.tsx: no
`confirmed` kind in prefTurnBubbles, serialize drops the turn
note, the mounted post-fix snapshot renders 1 noted bubble
instead of 8).

Run from the project root:
    .venv/bin/pytest tests/test_r34_d2_wizard_duplicate.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
PREFCHAT = FE / "src" / "components" / "PrefChat.tsx"
CHAT = FE / "src" / "lib" / "chat.ts"
LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]

# ---------------------------------------------------------------------------
# Node harness: the REAL prefTurnBubbles order + serialize/parse round-trip
# ---------------------------------------------------------------------------

_NODE_HARNESS = r"""
const path = require('path');
const chat = require(path.join(OUT, 'chat.js'));
const types = require(path.join(OUT, 'types.js'));
const preferences = require(path.join(OUT, 'preferences.js'));
const enMessages = require(ENMSG);
let fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('FAIL ' + name + ': got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want)); }
  else console.log('ok ' + name);
}
const kinds = (bs) => bs.map((b) => b.kind);

const templateReply = (extracted, next) => ({
  lines: ['Noted.'], ai_status: 'unavailable', extracted, next_question: next,
  done: next === null, climate_turn: false,
});
const modelReply = (extracted, next, why) => ({
  lines: ['Understood.'], ai_status: 'available', extracted, next_question: next,
  done: next === null, ...(why ? { why_followup: why } : {}),
});
const whyRecord = { countries: ['CH'], note: '那边环境优美', answer: null, skipped: false };
const whyAnswered = { countries: ['CH'], note: '那边环境优美', answer: '喜欢湖光山色', skipped: false };
const whyOpen = { countries: ['CH'], note: '那边环境优美', turnId: 1 };

// --- bubble order ----------------------------------------------------------
// (a) Plain turn + confirmed note: the note sits after the reply, before
// the next question — in order, inside its turn, never at the bottom.
const plain = { id: 2, question: 'Cool', reply: templateReply({ climate: 'cool' }, 'environment'), replyLocale: 'en', offline: true, confirmedNote: 'Cool' };
check('plain+note: order is user, reply, confirmed, question',
  kinds(chat.prefTurnBubbles(plain, null)), ['user', 'reply', 'confirmed', 'question']);
check('plain+note: confirmed bubble carries the note',
  chat.prefTurnBubbles(plain, null).find((b) => b.kind === 'confirmed'), { kind: 'confirmed', note: 'Cool' });
// (b) WHY answered + confirmed note: note after the WHY answer, before
// the deferred question.
const whyTurn = { id: 1, question: '我想去瑞士', reply: modelReply({ countries: ['CH'] }, 'climate', { countries: ['CH'], note: '那边环境优美' }), replyLocale: 'zh-CN', offline: false, why: whyAnswered, confirmedNote: '瑞士 · “那边环境优美”' };
check('WHY answered+note: order is user, reply, why, whyAnswer, confirmed, deferredQuestion',
  kinds(chat.prefTurnBubbles(whyTurn, null)), ['user', 'reply', 'why', 'whyAnswer', 'confirmed', 'deferredQuestion']);
// (c) WHY live + confirmed note (user confirmed before answering WHY):
// note after the WHY question, still no deferred question while live.
const whyLive = { id: 1, question: '我想去瑞士', reply: modelReply({ countries: ['CH'] }, 'climate', { countries: ['CH'], note: '那边环境优美' }), replyLocale: 'zh-CN', offline: false, why: whyRecord, confirmedNote: '瑞士' };
check('WHY live+note: order is user, reply, why, confirmed (no deferred while live)',
  kinds(chat.prefTurnBubbles(whyLive, whyOpen)), ['user', 'reply', 'why', 'confirmed']);
// (d) No note: the pre-fix orders are unchanged (R16/R28 pins hold).
const plainNoNote = { id: 2, question: 'Cool', reply: templateReply({ climate: 'cool' }, 'environment'), replyLocale: 'en', offline: true };
check('no note: plain turn unchanged', kinds(chat.prefTurnBubbles(plainNoNote, null)), ['user', 'reply', 'question']);
const whyNoNote = { id: 1, question: '我想去瑞士', reply: modelReply({ countries: ['CH'] }, 'climate', { countries: ['CH'], note: '那边环境优美' }), replyLocale: 'zh-CN', offline: false, why: whyAnswered };
check('no note: WHY answered unchanged', kinds(chat.prefTurnBubbles(whyNoNote, null)), ['user', 'reply', 'why', 'whyAnswer', 'deferredQuestion']);
// (e) Blank note renders no bubble.
const blankNote = { id: 2, question: 'Cool', reply: templateReply({ climate: 'cool' }, 'environment'), replyLocale: 'en', offline: true, confirmedNote: '   ' };
check('blank note: no confirmed bubble', kinds(chat.prefTurnBubbles(blankNote, null)), ['user', 'reply', 'question']);
// (f) Done turn (next_question null) + note: no question bubble, note last.
const doneTurn = { id: 8, question: 'Small seminars', reply: templateReply({ teaching: 'seminar' }, null), replyLocale: 'en', offline: true, confirmedNote: 'Small seminars' };
check('done+note: order is user, reply, confirmed (no question)',
  kinds(chat.prefTurnBubbles(doneTurn, null)), ['user', 'reply', 'confirmed']);

// --- persistence -----------------------------------------------------------
const profile = {
  ...types.emptyProfile,
  curriculum: 'cn_gaokao', track: 'undergraduate', field: 'computing',
  intakeYear: 2027, gaokaoScore: 600, gaokaoTotal: 750, gaokaoMaths: 130,
  ieltsOverall: 7, budget: 50000, budgetCurrency: 'GBP',
  prefCountries: ['CH'], prefCountriesNote: 'Because the environment is beautiful',
  prefClimate: 'cool', prefEnvironment: 'campus', prefCity: 'Zurich',
  prefAfterGrad: 'stay', prefSalary: 50000, prefSalaryCurrency: 'GBP',
  prefPressure: 'low', prefTeaching: 'seminar',
};
const fp = chat.prefChatFingerprint(profile);
const state = {
  mode: 'model',
  turns: [
    { id: 1, question: 'Switzerland', reply: templateReply({ countries: ['CH'] }, 'climate'), replyLocale: 'en', offline: true, why: whyAnswered },
    { id: 2, question: 'Cool', reply: templateReply({ climate: 'cool' }, 'environment'), replyLocale: 'en', offline: true, confirmedNote: 'Cool' },
  ],
  modelTurns: [], qIndex: 2, skipped: [], serverNext: 'environment',
  awaitingReason: null, verbatim: {}, failedText: null, pendingExtract: null,
  confirmedNotes: ['Legacy note here'],
};
const blob = chat.serializePrefChatState(state, fp);
check('serialize keeps confirmedNote on the turn', JSON.parse(blob).turns[1].confirmedNote, 'Cool');
check('serialize keeps WHY + note together', JSON.parse(blob).turns[0].why.answer, '喜欢湖光山色');
const restored = chat.parsePrefChatState(blob, fp);
check('round-trip keeps confirmedNote', restored.turns[1].confirmedNote, 'Cool');
check('round-trip keeps WHY answer', restored.turns[0].why.answer, '喜欢湖光山色');
check('round-trip keeps confirmedNotes list (R15)', restored.confirmedNotes, ['Legacy note here']);
// Old blob (no confirmedNote field): parses, note absent, turns intact.
const oldObj = JSON.parse(blob);
delete oldObj.turns[1].confirmedNote;
const restoredOld = chat.parsePrefChatState(JSON.stringify(oldObj), fp);
check('old blob parses', !!restoredOld, true);
check('old blob: confirmedNote absent', restoredOld.turns[1].confirmedNote, undefined);
check('old blob: turn intact', restoredOld.turns[1].question, 'Cool');
// Malformed note is dropped, the turn still parses.
const badObj = JSON.parse(blob);
badObj.turns[1].confirmedNote = 42;
const restoredBad = chat.parsePrefChatState(JSON.stringify(badObj), fp);
check('non-string note dropped, turn kept', restoredBad.turns[1].confirmedNote, undefined);
check('non-string note: turn intact', restoredBad.turns[1].question, 'Cool');

// --- summary content (the 8/8 summary is built from the same profile) -----
// The summary bubble itself needs the hydrated profile (the store
// hydrates in an effect, which renderToString never runs), so its
// CONTENT is pinned here at the lib level: the same profile the
// mounted run completes with lists all 8 prefs, once each.
const tEn = (k) => enMessages[k] ?? k;
const summaryText = preferences.prefSummary(profile, tEn, 'en');
for (const value of ['Switzerland', 'Cool', 'Zurich', '50000 GBP', 'Take it easy', 'Small seminars']) {
  check('summary lists ' + value, summaryText.includes(value), true);
}
check('summary lists the campus environment', summaryText.includes('University town'), true);
check('summary lists staying on', summaryText.includes('Stay in the country where I study'), true);

console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
process.exit(fail ? 1 : 0);
"""


def test_r34_d2_turn_bubbles_and_persistence(tmp_path):
    """prefTurnBubbles emits the `confirmed` bubble inside its turn
    (plain / WHY answered / WHY live / done / blank), the pre-fix
    orders are unchanged without a note, and the turn note survives
    serialize/parse (old blobs parse without it, malformed notes are
    dropped, the confirmedNotes list still round-trips)."""
    outdir = tmp_path / "r34d2_lib"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/preferences.ts", "src/lib/chat.ts",
         "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r34d2_lib_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("ENMSG", repr(str(FE / "messages" / "en.json"))),
        encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"], "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
    assert "HARNESS OK" in node.stdout


# ---------------------------------------------------------------------------
# renderToString mount: the REAL PrefChat, seeded snapshots, 8/8 run
# ---------------------------------------------------------------------------

_SSR_SCRIPT = r"""
const path = require('path');
const Module = require('module');
const origResolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...args) {
  if (request === 'next/link') return path.join(SRC, 'build/stubs/next/link.js');
  if (request === 'next/navigation') return path.join(SRC, 'build/stubs/next/navigation.js');
  return origResolve.call(this, request, ...args);
};
const store = new Map();
global.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(String(k), String(v)),
  removeItem: (k) => store.delete(k),
};
global.window = { addEventListener() {}, removeEventListener() {} };

const chat = require(path.join(SRC, 'build/lib/chat.js'));
const types = require(path.join(SRC, 'build/lib/types.js'));
const React = require('react');
const { renderToString } = require('react-dom/server');
const { AppProvider } = require(path.join(SRC, 'build/lib/store.js'));
const { PrefChat } = require(path.join(SRC, 'build/components/PrefChat.js'));

let fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('FAIL ' + name + ': got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want)); }
  else console.log('ok ' + name);
}
const count = (html, s) => (html.split(s).length - 1);

const profile = {
  ...types.emptyProfile,
  curriculum: 'cn_gaokao', track: 'undergraduate', field: 'computing',
  intakeYear: 2027, gaokaoScore: 600, gaokaoTotal: 750, gaokaoMaths: 130,
  ieltsOverall: 7, budget: 50000, budgetCurrency: 'GBP',
  prefCountries: ['CH'], prefCountriesNote: 'Because the environment is beautiful',
  prefClimate: 'cool', prefEnvironment: 'campus', prefCity: 'Zurich',
  prefAfterGrad: 'stay', prefSalary: 50000, prefSalaryCurrency: 'GBP',
  prefPressure: 'low', prefTeaching: 'seminar',
};
const fp = chat.prefChatFingerprint(profile);
const reply = (lines, extracted, next, extra = {}) => ({
  lines, ai_status: 'unavailable', extracted, next_question: next,
  done: next === null, climate_turn: false, ...extra,
});
const mkTurn = (id, question, extracted, next, extra = {}) => ({
  id, question, reply: reply(['Noted.'], extracted, next), replyLocale: 'en', offline: true, ...extra,
});
const turns = [
  mkTurn(1, 'Switzerland', { countries: ['CH'] }, 'climate',
    { why: { countries: ['CH'], answer: 'Because the environment is beautiful', skipped: false } }),
  { ...mkTurn(2, 'Cool', { climate: 'cool' }, 'environment'), confirmedNote: 'Cool' },
  { ...mkTurn(3, 'University town', { environment: 'campus' }, 'city'), confirmedNote: 'University town · campus vibe' },
  { ...mkTurn(4, 'Zurich', { city: 'Zurich' }, 'afterGrad'), confirmedNote: 'Zurich' },
  { ...mkTurn(5, 'Stay in the country where I study', { afterGrad: 'stay' }, 'salary'), confirmedNote: 'Stay in the country where I study' },
  { ...mkTurn(6, '50000 GBP', { salary: { amount: 50000, currency: 'GBP' } }, 'pressure'), confirmedNote: '50000 GBP' },
  { ...mkTurn(7, 'Take it easy', { pressure: 'low' }, 'teaching'), confirmedNote: 'Take it easy' },
  { ...mkTurn(8, 'Small seminars', { teaching: 'seminar' }, null), confirmedNote: 'Small seminars' },
];
const mount = (blob, seedProfile) => {
  store.clear();
  store.set('pp-profile', JSON.stringify(seedProfile));
  store.set('pp-locale', 'en');
  store.set('pp-prefchat', blob);
  return renderToString(React.createElement(AppProvider, null,
    React.createElement(PrefChat, { onDone: () => {} })));
};

// --- (A) post-fix 8/8 run: notes on their turns, nothing in the list -----
const postFix = chat.serializePrefChatState({
  mode: 'model', turns, modelTurns: [], qIndex: 0, skipped: [],
  serverNext: undefined, awaitingReason: null, verbatim: {}, failedText: null,
  pendingExtract: null, confirmedNotes: [],
}, fp);
const html = mount(postFix, profile);
// NOTE: the store hydrates the profile in an effect, which
// renderToString never runs, so the SSR tree sees the empty profile:
// the 8/8 header, the summary bubble and Finish (all gated on the
// hydrated profile) cannot render here. Their content is pinned in
// the lib harness (prefSummary) and the live 8/8 rendering was
// verified in the jsdom mount (see the D2 report). What SSR CAN pin
// is the defect itself: where the notes render, and how many.
// 1 WHY ack + 7 turn notes, each exactly once.
check('post-fix: Got it, noted! exactly 8 times', count(html, 'Got it, noted!'), 8);
// Each note renders inside its turn: turn 2's note sits BEFORE turn 3's
// question (pre-fix it piled after ALL turns, and on pre-fix code this
// post-fix snapshot renders no turn note at all).
const note2 = html.indexOf('<p>Got it, noted!</p><p class="mt-1 text-sm text-navy/70">Cool</p>');
const q3 = html.indexOf('What kind of environment do you like');
check('post-fix: turn 2 note before turn 3 question', note2 !== -1 && q3 !== -1 && note2 < q3, true);
// The notes are interleaved with the conversation, not a contiguous
// bottom pile: turn 3's question sits between note 2 and note 3.
const note3 = html.indexOf('<p>Got it, noted!</p><p class="mt-1 text-sm text-navy/70">University town · campus vibe</p>');
check('post-fix: notes interleaved (q3 between note 2 and note 3)',
  note2 !== -1 && q3 !== -1 && note3 !== -1 && note2 < q3 && q3 < note3, true);
// The last turn's note sits after its own user bubble (inside the turn),
// not in a detached block after the conversation.
const note8 = html.indexOf('<p>Got it, noted!</p><p class="mt-1 text-sm text-navy/70">Small seminars</p>');
const user8 = html.indexOf('Small seminars');
check('post-fix: last note after its turn', note8 !== -1 && user8 !== -1 && user8 < note8, true);

// --- (B) pre-fix snapshot: notes in the list, turns without notes ---------
// Backward compat: legacy notes still render once each, after the turns.
const legacyTurns = turns.map(({ confirmedNote, ...rest }) => rest);
const legacy = chat.serializePrefChatState({
  mode: 'model', turns: legacyTurns, modelTurns: [], qIndex: 0, skipped: [],
  serverNext: undefined, awaitingReason: null, verbatim: {}, failedText: null,
  pendingExtract: null, confirmedNotes: ['Cool', 'University town · campus vibe', 'Small seminars'],
}, fp);
const htmlLegacy = mount(legacy, profile);
check('legacy: Got it, noted! exactly 4 times (1 WHY ack + 3 legacy)',
  count(htmlLegacy, 'Got it, noted!'), 4);
check('legacy: each legacy note once',
  count(htmlLegacy, '<p>Got it, noted!</p><p class="mt-1 text-sm text-navy/70">Cool</p>'), 1);
const legacyNote = htmlLegacy.indexOf('<p>Got it, noted!</p><p class="mt-1 text-sm text-navy/70">Cool</p>');
const lastQ = htmlLegacy.indexOf('Last one — how do you like to learn?');
check('legacy: legacy notes render after the turns (old block position)',
  legacyNote !== -1 && lastQ !== -1 && legacyNote > lastQ, true);

console.log(fail ? 'SSR FAILURES: ' + fail : 'SSR OK');
process.exit(fail ? 1 : 0);
"""

_LINK_STUB = """import React from 'react';
export default function Link({ href, children, ...props }: { href: string; children?: React.ReactNode; [k: string]: unknown }) {
  return <a href={href} {...(props as Record<string, unknown>)}>{children}</a>;
}
"""

_NAV_STUB = """export function usePathname(): string { return '/wizard'; }
export function useRouter() { return { push() {}, back() {}, replace() {}, refresh() {} }; }
export function useSearchParams() { return new URLSearchParams(); }
"""


def _compile_component(tmp_path: Path) -> Path:
    """Copy the REAL PrefChat + its imports into tmp, compile with
    tsc (next/* stubbed), return the tmp root (build under it)."""
    src = tmp_path / "r34d2_ssr"
    shutil.copytree(FE / "src" / "lib", src / "src" / "lib")
    shutil.copytree(FE / "src" / "components", src / "src" / "components")
    shutil.copytree(FE / "messages", src / "messages")
    # tsc resolves 'react' (+ its types) from the importing file upward,
    # so the tmp tree needs the same node_modules links the repo has.
    nm = src / "src" / "node_modules"
    nm.mkdir(parents=True)
    os.symlink(FE / "node_modules" / "react", nm / "react")
    os.symlink(FE / "node_modules" / "@types", nm / "@types")
    stubs = src / "src" / "stubs" / "next"
    stubs.mkdir(parents=True)
    (stubs / "link.tsx").write_text(_LINK_STUB, encoding="utf-8")
    (stubs / "navigation.ts").write_text(_NAV_STUB, encoding="utf-8")
    (src / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {
            "target": "es2020", "module": "commonjs", "jsx": "react-jsx",
            "esModuleInterop": True, "resolveJsonModule": True,
            "skipLibCheck": True, "moduleResolution": "node",
            "baseUrl": "src",
            "paths": {"next/link": ["./stubs/next/link.tsx"],
                      "next/navigation": ["./stubs/next/navigation.ts"]},
            "outDir": "./build", "rootDir": "src", "strict": False,
        },
        "include": ["src/components/PrefChat.tsx",
                    "src/components/CompassPet.tsx", "src/lib/store.tsx"],
    }), encoding="utf-8")
    res = subprocess.run(
        ["npx", "tsc", "-p", str(src / "tsconfig.json")],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    return src


def test_r34_d2_mounted_conversation_renders_once(tmp_path):
    """renderToString mount of the real PrefChat: a post-fix 8/8 run
    renders each confirmation once, inside its turn (note before the
    next question, last note before the summary), the summary once,
    Finish present; a pre-fix snapshot's legacy notes still render
    once each, after the turns."""
    src = _compile_component(tmp_path)
    script = tmp_path / "r34d2_ssr.js"
    script.write_text(_SSR_SCRIPT.replace("SRC", repr(str(src))), encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"], "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(script)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
    assert "SSR OK" in node.stdout


# ---------------------------------------------------------------------------
# Source pins
# ---------------------------------------------------------------------------

def test_r34_d2_confirm_attaches_to_turn():
    """confirmExtract attaches the summary to the latest turn (the
    same anchor the WHY backstop uses) and no longer appends to the
    detached list; the turn type carries the note; the persist call
    still carries the list (Round 15)."""
    prefchat = PREFCHAT.read_text(encoding="utf-8")
    assert "confirmedNote: summary" in prefchat
    assert "setConfirmedNotes((prev) => [...prev, summary])" not in prefchat
    assert "confirmedNote?: string | null;" in prefchat
    assert "pendingExtract, confirmedNotes" in prefchat
    # The anchor is the latest turn; a turn already carrying a note
    # keeps its first one (same guard shape as the WHY record).
    assert "const anchorId = turns.length ? turns[turns.length - 1].id : undefined;" in prefchat
    assert "x.id === anchorId && !x.confirmedNote" in prefchat
    chat = CHAT.read_text(encoding="utf-8")
    assert "confirmedNote?: string | null;" in chat
    assert "| { kind: 'confirmed'; note: string }" in chat
    assert "out.push({ kind: 'confirmed', note: turn.confirmedNote });" in chat


def test_r34_d2_confirmed_bubble_render_and_legacy_block():
    """renderPrefTurns renders the `confirmed` bubble (same markup as
    the old block, localised value line); the detached block is kept
    only for notes with no turn (restored pre-R34 snapshots,
    turn-less WHY) — it must not re-render turn-anchored notes."""
    prefchat = PREFCHAT.read_text(encoding="utf-8")
    assert "if (bubble.kind === 'confirmed') {" in prefchat
    assert "pref-${turn.id}-confirmed" in prefchat
    assert "localisedConfirmedNote(bubble.note, t)" in prefchat
    # The legacy block still renders the list (R28 D1 pin: the stored
    # note prints through localisedConfirmedNote, never verbatim).
    assert "localisedConfirmedNote(note, t)" in prefchat
    assert "confirmedNotes.map((note, i)" in prefchat
    # The block is the only confirmedNotes render site left: no second
    # copy of the "Got it, noted!" bubble markup may render the list.
    assert prefchat.count("confirmedNotes.map((note, i)") == 1
    # Exactly three "Got it, noted!" render sites: the WHY-answer ack,
    # the turn's `confirmed` bubble, and the legacy block — one bubble
    # per note, never two sites for the same note.
    assert prefchat.count("{t('wizard.chatOpThanks')}") == 3


def test_r34_d2_no_new_locale_keys():
    """No locale keys are added by this fix: 994 keys in every locale
    file, the same key set in all 6 (Round 33's count)."""
    msgs = {
        loc: json.load(open(FE / "messages" / f"{loc}.json", encoding="utf-8"))
        for loc in LOCALES
    }
    base = set(msgs["en"])
    assert len(base) == 994, len(base)
    for loc in LOCALES:
        assert set(msgs[loc]) == base, loc


def test_r34_d2_store_and_wizard_page_untouched():
    """This fix touches no store / wizard-page / hero / stats code:
    the clear-data nonce, the loadWizardStep guard and the Round 33
    stats strip are exactly as the other Round 34 workers left them."""
    store = (FE / "src" / "lib" / "store.tsx").read_text(encoding="utf-8")
    assert "confirmedNote" not in store
    wizard = (FE / "src" / "app" / "wizard" / "page.tsx").read_text(encoding="utf-8")
    assert "confirmedNote" not in wizard
    assert "if (isEmpty) return 0;" in wizard  # D1's content guard intact
    home = (FE / "src" / "app" / "page.tsx").read_text(encoding="utf-8")
    assert "home.rankingRecords" in home
    assert "confirmedNote" not in home
