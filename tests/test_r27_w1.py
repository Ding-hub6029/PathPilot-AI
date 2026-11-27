"""Round 27 W1: a language switch rewrites chat history
(re-test task 21, 2026-11-28 00:28-00:39 CST, gateway offline the
whole run).

Tester finding: switching language re-generated assistant replies
and changed their content — fee answers ("ETH Zurich — MSc in
Computer Science tuition: CHF 4,380 per year.") mostly became the
rankings line ("ETH Zurich: QS 2027 #=8 · THE 2027 #12 · ARWU 2026
#19."), 9 occurrences across EN and zh histories; one Chinese chip
reply was left as a bare offline line with no fee; the same fee
appeared in three wordings; two replies stuck on "Thinking…" /
"想想……" for ~1 minute after the switch; the footer briefly
flipped to "AI answers · grounded in verified sources" while
offline after the switch, then back to the offline line.

Root cause (verified in code, not inferred): every chat surface
re-issued its turns to the backend on a locale change instead of
rendering the stored reply — CompassPet's [locale, messages]
effect, RecChat's [locale] effect, PrefChat's two [locale]
effects, and AiEntry's [locale, open, reply, replyLocale] effect.
Each re-fetch POSTed the turn again and overwrote the stored
reply with whatever came back, so the answer depended on what
the backend returned that minute instead of on what was answered:
- a re-fetch that failed (or came back with no lines) hit the
  toOffline path, which nulled the reply and fell back to the
  offline catalogue — the rank lookup — so the fee answer became
  the rankings line, or a bare offline line when no rank alias
  matched;
- while a re-fetch was in flight the render gated on
  replyLocale === locale and showed the thinking line — the ~1
  minute stall is the backend waking (Render free sleeps after
  15 min idle, first request ~50 s);
- the footer flip is the re-fetch's own verdict overwriting the
  turn verdict: its .then branch ran setOffline(false) +
  setAiLive(true) whenever a re-fetch caught the flapping gateway
  briefly up and returned ai_status "available", then a later
  re-fetch landing template/offline set it back. The re-fetch
  effect was the ONLY locale-change writer of aiLive/offline in
  CompassPet (the [open] probe does not run on a switch).

Fix (parent's decision): a stored assistant reply is an immutable
record. All four locale re-fetch effects are deleted; the render
gates on replyLocale === locale are removed, so a stored reply is
shown exactly as answered in the locale it was answered in, and
"Thinking…" now means only a genuinely in-flight turn. No locale
change issues any backend call or touches the footer verdict —
chrome/labels re-localise at render time, reply content never
does. Consequence, accepted by the parent: model replies in the
old locale stay in the old locale after a switch (trust over
translation). replyLocale / sentMessage are kept as records of
what was answered/sent, read by nothing now (removing the
sendAskTurn fields is out of this round's region).

Covers, with no API key and no network:

- node harness over compiled ``frontend/src/lib/aiStatus.ts``:
  the footer line key is offline whenever the offline verdict
  holds — even if a stale live claim is also present (the flip
  case) — and a probe verdict never applies once a turn verdict
  has landed after the probe started or while a turn is in
  flight;
- node harness over compiled ``frontend/src/lib/chat.ts``
  (``prefTurnBubbles``): the re-test 21 fee turn's reply bubble
  lines are byte-identical to the stored lines with no locale
  input at all, in EN and in zh, with no rankings line; same for
  an offline template turn and a WHY turn;
- source pins on the four components: no ``useEffect`` dep array
  mentions ``locale`` in any of them (so no switch can issue a
  backend call), no ``replyLocale === locale`` render gate
  remains, no ``fetchJson<`` re-fetch call remains in the three
  chat components, the pet's ``setAiLive(true)`` occurs only in
  the two real-turn paths (askSuggest, onSend), and AiEntry
  still re-asks when the question itself changes (the context
  effect is kept — only the locale effect is deleted).

Run from the project root:
    .venv/bin/pytest tests/test_r27_w1.py -q -p no:cacheprovider
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_CHAT_FILES = (
    "frontend/src/components/CompassPet.tsx",
    "frontend/src/components/RecChat.tsx",
    "frontend/src/components/PrefChat.tsx",
    "frontend/src/components/AiEntry.tsx",
)

_NODE_HARNESS = r"""
const aiStatus = require(OUT + '/aiStatus.js');
const chat = require(OUT + '/chat.js');
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + ' -> ' + g + ' want ' + w); fail++; }
  else console.log('PASS ' + name);
};

// --- Footer verdict (lib/aiStatus.ts) ---------------------------------
const key = aiStatus.footerAiLineKey;
// The re-test 21 flip: a stale live claim must never beat an offline
// verdict — the footer stays offline while turns are offline.
check('footer: offline beats a stale live claim',
  key({ offline: true, timedOut: false, aiLive: true }), 'pet.offline');
check('footer: offline + timeout beats a stale live claim',
  key({ offline: true, timedOut: true, aiLive: true }), 'pet.offlineTimeout');
check('footer: offline with no live claim',
  key({ offline: true, timedOut: false, aiLive: false }), 'pet.offline');
check('footer: live only when not offline',
  key({ offline: false, timedOut: false, aiLive: true }), 'pet.aiLive');
check('footer: unknown verdict is checking, never AI',
  key({ offline: false, timedOut: false, aiLive: null }), 'pet.aiChecking');
check('footer: false verdict is offline',
  key({ offline: false, timedOut: false, aiLive: false }), 'pet.offline');

// A probe verdict must never overwrite a turn verdict (Round 22 W1
// guard, re-pinned here because the flip is a probe-vs-turn race).
const applies = aiStatus.probeVerdictApplies;
check('probe: applies when nothing moved',
  applies({ turnInFlight: false, turnVerdictGenAtProbeStart: 3, turnVerdictGenNow: 3 }), true);
check('probe: dropped when a turn verdict landed after probe start',
  applies({ turnInFlight: false, turnVerdictGenAtProbeStart: 3, turnVerdictGenNow: 4 }), false);
check('probe: dropped while a turn is in flight',
  applies({ turnInFlight: true, turnVerdictGenAtProbeStart: 3, turnVerdictGenNow: 3 }), false);

// --- Stored reply lines are locale-independent (lib/chat.ts) ---------
// The re-test 21 fee turn, answered in EN.
const FEE_EN = ['ETH Zurich — MSc in Computer Science tuition: CHF 4,380 per year.'];
const feeTurn = { id: 1, question: 'What is the tuition fee for ETH Zurich Computer Science?', reply: { lines: FEE_EN, ai_status: 'unavailable' }, replyLocale: 'en' };
const bubblesEn = chat.prefTurnBubbles(feeTurn, null);
const replyEn = bubblesEn.find((b) => b.kind === 'reply');
check('prefTurnBubbles: fee turn reply lines are the stored lines',
  replyEn.lines, FEE_EN);
// Rendered again after the switch to zh-CN: the function takes no
// locale, so the lines cannot change — byte-identical, no rankings
// line smuggled in.
const bubblesZh = chat.prefTurnBubbles(feeTurn, null);
const replyZh = bubblesZh.find((b) => b.kind === 'reply');
check('prefTurnBubbles: same lines after a locale switch',
  replyZh.lines, FEE_EN);
check('prefTurnBubbles: no rankings line after a locale switch',
  replyZh.lines.join(' ').includes('QS 2027'), false);

// An offline template turn answered in zh-CN keeps its lines too.
const FEE_ZH = ['苏黎世联邦理工 — 计算机科学硕士学费：每年 CHF 4,380。'];
const zhTurn = { id: 2, question: '苏黎世联邦理工计算机科学硕士的学费是多少？', reply: { lines: FEE_ZH, ai_status: 'unavailable' }, replyLocale: 'zh-CN' };
check('prefTurnBubbles: zh offline template lines unchanged',
  chat.prefTurnBubbles(zhTurn, null).find((b) => b.kind === 'reply').lines, FEE_ZH);

// A WHY turn: the reply lines are unchanged and the WHY bubble is
// still attached (the strip only fires for a re-fetched reply, which
// no longer exists).
const whyTurn = { id: 3, question: '瑞士', reply: { lines: ['已记录：瑞士。'], ai_status: 'available', why_followup: { countries: ['CH'] }, next_question: 'climate' }, why: { countries: ['CH'], answer: null, skipped: false } };
const whyBubbles = chat.prefTurnBubbles(whyTurn, null);
check('prefTurnBubbles: WHY turn reply lines unchanged',
  whyBubbles.find((b) => b.kind === 'reply').lines, ['已记录：瑞士。']);
check('prefTurnBubbles: WHY bubble still attached',
  whyBubbles.some((b) => b.kind === 'why'), true);

// A turn with no reply yet yields an empty reply bubble (the
// component shows thinking for pending, never a stale line).
check('prefTurnBubbles: no-reply turn has empty reply lines',
  chat.prefTurnBubbles({ id: 4, question: 'hi', reply: null }, null).find((b) => b.kind === 'reply').lines, []);

if (fail) { console.log(fail + ' FAILURES'); process.exit(1); }
console.log('ALL HARNESS CASES PASS');
"""


def test_r27_w1_lib_harness(tmp_path):
    outdir = tmp_path / "r27w1_lib"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/chat.ts", "src/lib/aiStatus.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r27w1_harness.js"
    harness.write_text(
        _NODE_HARNESS.replace("OUT", repr(str(outdir))),
        encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"],
           "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_r27_w1_no_locale_effect_in_chat_components():
    """No useEffect dep array mentions locale in any chat surface,
    so a language switch cannot trigger any effect — in particular
    no backend call. (The only locale-dep effects left in the app
    are lib/store.tsx, which only sets document lang/dir and
    persists the locale, and results/page.tsx's why-not refresh —
    a separate surface, flagged as a residual, not a chat reply.)"""
    for rel in _CHAT_FILES:
        src = _read(rel)
        assert not re.search(r"\}, \[[^\]]*locale[^\]]*\]\);", src), rel


def test_r27_w1_no_reply_locale_render_gate():
    """No render gate on replyLocale === locale remains: a stored
    reply is shown whatever locale it was answered in."""
    for rel in _CHAT_FILES:
        assert "replyLocale === locale" not in _read(rel), rel


def test_r27_w1_no_refetch_fetch_call():
    """No fetchJson< call remains in the three chat components —
    the only fetchJson< calls were the locale re-fetch POSTs. Real
    turns still use fetchJsonChat, probes still use
    fetchJsonPatient (pinned by the tsc run, not by absence)."""
    for rel in _CHAT_FILES[:3]:
        assert "fetchJson<" not in _read(rel), rel


def test_r27_w1_pet_renders_stored_reply_and_footer_only_on_turns():
    pet = _read(_CHAT_FILES[0])
    # Both reply branches show the stored reply unconditionally.
    assert "case 'suggest': {\n        if (turn.reply) {" in pet
    assert "case 'ask': {\n        if (turn.reply) {" in pet
    # "Thinking…" remains only as the pending-turn fallback (one per
    # case); a stored reply never renders it.
    assert pet.count("t('pet.thinking')") == 2
    assert "if (turn.reply) return { lines: [t('pet.thinking')] };" not in pet
    # The footer verdict is written only by real turns now: the two
    # setAiLive(true) sites are askSuggest and onSend (the re-fetch
    # effect's setOffline(false) + setAiLive(true) is gone).
    assert pet.count("setAiLive(true)") == 2
    # Turns still record the locale they were answered in.
    assert "replyLocale: requestLocale" in pet


def test_r27_w1_recchat_and_prefchat_render_stored_reply():
    rec = _read(_CHAT_FILES[1])
    pref = _read(_CHAT_FILES[2])
    # The reply branch is unconditional on locale now; the stale
    # thinking branch is gone, so t('pet.thinking') is absent.
    assert ") : turn.reply ? (" in rec
    assert "t('pet.thinking')" not in rec
    assert pref.count(") : turn.reply ? (") == 2
    assert "t('pet.thinking')" not in pref


def test_r27_w1_aientry_keeps_question_change_reask_only():
    entry = _read(_CHAT_FILES[3])
    # A genuinely new question still re-asks (context effect kept);
    # a locale switch does not.
    assert "}, [question, open]);" in entry
    # The stored reply renders without a locale gate.
    assert "{!showThinking && !failed && reply && (" in entry
    assert "replyLocale === locale" not in entry
