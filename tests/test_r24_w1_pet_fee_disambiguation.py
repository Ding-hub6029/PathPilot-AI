"""Round 24, W1 — pet free-text fee flow is broken end to end.

Tester sequence (pet assistant, English, with and without a profile,
three times, identical result):
  1. "What is the tuition fee for ETH Zurich Computer Science?"
     -> "I found 2 matching programmes: ETH Zurich — MSc in Computer
        Science, ETH Zurich — Bachelor of Science in Computer
        Science. Tell me undergraduate or masters." (correct)
  2. Then it breaks:
     (i)   no fee line is ever given;
     (ii)  tapping "Undergraduate" is treated as onboarding
           question 1 and jumps to country selection;
     (iii) typing "undergraduate" spins, then answers "I can't find
           that in the verified data, so I don't know" — while the
           SAME fee data answers CHF 4,380 directly in wizard step 8
           (RecChat) for the ETH BSc.

Root causes (see the fix comments in code):
- Backend (ai/assistant.py ask): the ambiguous reply named the two
  programmes but carried no ids — the frontend had no machine-
  readable pending context to carry forward. Fixed: the ambiguous
  reply carries `candidates` (the matched programme ids), threaded
  through ai/chat.py _template_result.
- Backend (ai/chat.py _retrieve): the frontend appends the saved-
  preferences context to the FIRST free-text turn, and the template
  matcher read the whole string as the question — the context words
  corrupted the degree-phrase extraction, so with a saved profile
  the same question answered the blanket unknown and the climate-
  cities line hijacked the reply (Edinburgh / Durham / Lund for an
  ETH question). Fixed: retrieval and the template match on the
  question with the context stripped; the model envelope still
  carries the full message.
- Frontend (CompassPet.tsx): the chips were driven by the onboarding
  `step` alone, so the "Undergraduate" chip WAS onboarding Q1; and
  onSend sent a bare level word to the backend. Fixed: the pending
  disambiguation is derived from the turns (last ask whose reply
  lists 2+ candidates); while it is pending the chips are its level
  chips, a tap or a typed level word sends the ORIGINAL question +
  the level word scoped to the candidates, and a reply that names
  no level and is not a new question is re-asked locally — never
  sent bare to the backend.

No-key path throughout (ai_status "unavailable").

Run from the project root:
    .venv/bin/pytest tests/test_r24_w1_pet_fee_disambiguation.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from ai.chat import answer
from ai.provider import ProviderAdapter
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)

ETH_BSC = "eth-cs-bsc-2027"
ETH_MSC = "eth-cs-msc-2027"
# The backend's order for the ambiguous reply (MSc first).
ETH_CANDIDATES = [ETH_MSC, ETH_BSC]

Q_EN = "What is the tuition fee for ETH Zurich Computer Science?"
Q_ZH = "苏黎世联邦理工计算机科学的学费是多少？"
# Exactly what CompassPet appends to the first free-text turn when a
# wizard profile is saved (frontend/src/lib/chat.ts savedPrefsContext):
# countries CH + climate cool, the realistic wizard state.
CTX_EN = ("The user's saved preferences from the eligibility check: "
          "countries: CH; climate: cool.")


def _no_key_provider(monkeypatch) -> ProviderAdapter:
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return ProviderAdapter()


def _answer_no_key(monkeypatch, message: str, locale: str,
                   program_ids=None, track=None) -> dict:
    return answer(message, locale, provider=_no_key_provider(monkeypatch),
                  program_ids=program_ids, track=track)


def _followup(question: str, level_word: str) -> str:
    """What the pet sends for a level answer: the ORIGINAL question +
    the level word (frontend/src/lib/chat.ts
    disambiguationFollowupMessage)."""
    return f"{question} {level_word}"


# ---------------------------------------------------------------------------
# Step 1: the ambiguous reply, with and without a saved profile
# ---------------------------------------------------------------------------

def test_step1_en_ambiguous_carries_candidates(monkeypatch):
    r = _answer_no_key(monkeypatch, Q_EN, "en")
    assert r["ai_status"] == "unavailable"
    assert "2 matching programmes" in r["lines"][0]
    assert "Tell me undergraduate or masters" in r["lines"][0]
    assert r.get("program_id") is None
    assert sorted(r.get("candidates") or []) == sorted(ETH_CANDIDATES)


def test_step1_zh_ambiguous_carries_candidates(monkeypatch):
    r = _answer_no_key(monkeypatch, Q_ZH, "zh-CN")
    assert "2 个相关专业" in r["lines"][0]
    assert "本科还是硕士" in r["lines"][0]
    assert sorted(r.get("candidates") or []) == sorted(ETH_CANDIDATES)


def test_step1_with_profile_context_still_ambiguous(monkeypatch):
    # The saved-preferences context used to corrupt the degree-phrase
    # match, so the same question answered unknown + the climate-
    # cities line (Edinburgh / Durham / Lund) instead of the
    # ambiguous line. The context is for the model envelope only;
    # retrieval matches on the bare question.
    r = _answer_no_key(monkeypatch, Q_EN + "\n" + CTX_EN, "en")
    assert "2 matching programmes" in r["lines"][0]
    assert sorted(r.get("candidates") or []) == sorted(ETH_CANDIDATES)
    assert "Edinburgh" not in "\n".join(r["lines"])
    assert "Durham" not in "\n".join(r["lines"])


def test_greeting_with_profile_context_still_greets(monkeypatch):
    # Same corruption, second victim: "你好" + context exceeded the
    # 12-character greeting cap, so the greeting branch never fired.
    r = _answer_no_key(monkeypatch, "你好\n" + CTX_EN, "zh-CN")
    assert "小罗盘" in r["lines"][0]
    assert len(r["lines"]) == 1


# ---------------------------------------------------------------------------
# Step 2: the level follow-up completes the fee answer
# ---------------------------------------------------------------------------

def test_followup_button_undergraduate_answers_bsc_fee(monkeypatch):
    r = _answer_no_key(monkeypatch, _followup(Q_EN, "undergraduate"), "en",
                       program_ids=ETH_CANDIDATES)
    assert "CHF 4,380 per year" in r["lines"][0]
    assert "Bachelor of Science in Computer Science" in r["lines"][0]
    assert "MSc" not in r["lines"][0]
    assert (r.get("evidence_url") or "").startswith("https://ethz.ch")


def test_followup_typed_masters_answers_msc_fee(monkeypatch):
    r = _answer_no_key(monkeypatch, _followup(Q_EN, "masters"), "en",
                       program_ids=ETH_CANDIDATES)
    assert "CHF 4,380 per year" in r["lines"][0]
    assert "MSc in Computer Science" in r["lines"][0]
    assert "Bachelor" not in r["lines"][0]
    assert (r.get("evidence_url") or "").startswith("https://ethz.ch")


def test_followup_zh_button_and_typed(monkeypatch):
    r = _answer_no_key(monkeypatch, _followup(Q_ZH, "本科"), "zh-CN",
                       program_ids=ETH_CANDIDATES)
    assert "4,380" in r["lines"][0]
    assert "Bachelor of Science in Computer Science" in r["lines"][0]
    assert "MSc" not in r["lines"][0]
    r = _answer_no_key(monkeypatch, _followup(Q_ZH, "硕士"), "zh-CN",
                       program_ids=ETH_CANDIDATES)
    assert "4,380" in r["lines"][0]
    assert "MSc in Computer Science" in r["lines"][0]
    assert "Bachelor" not in r["lines"][0]


def test_followup_zh_postgraduate_word_answers_msc(monkeypatch):
    # "研究生" is a masters word (added to _TM_WORDS with this fix):
    # a natural zh typed answer for the masters side.
    r = _answer_no_key(monkeypatch, _followup(Q_ZH, "研究生"), "zh-CN",
                       program_ids=ETH_CANDIDATES)
    assert "4,380" in r["lines"][0]
    assert "MSc in Computer Science" in r["lines"][0]


def test_followup_without_scope_still_resolves(monkeypatch):
    # The scope is belt-and-braces; the message alone (original
    # question + level word) already resolves — the matcher never
    # depended on the scope.
    r = _answer_no_key(monkeypatch, _followup(Q_EN, "undergraduate"), "en")
    assert "CHF 4,380 per year" in r["lines"][0]
    assert "Bachelor of Science in Computer Science" in r["lines"][0]


# ---------------------------------------------------------------------------
# Requirement 3: an unrecognised level word asks again, never unknown
# ---------------------------------------------------------------------------

def test_unrecognised_level_word_asks_again_not_unknown(monkeypatch):
    # "grad" / "hmm" name no level the matcher recognises. The reply
    # must ask again — the template's ambiguous line when the match
    # itself stays ambiguous, the scope's which-one line when the
    # scope is what narrows it — never the blanket unknown. Both
    # re-ask shapes carry the candidates, so the caller's pending
    # disambiguation (and its level chips) stay live.
    for word in ("grad", "hmm"):
        r = _answer_no_key(monkeypatch, _followup(Q_EN, word), "en",
                           program_ids=ETH_CANDIDATES)
        joined = "\n".join(r["lines"])
        assert ("2 matching programmes" in r["lines"][0]
                or "Which one do you mean" in r["lines"][0]), word
        assert "don't know" not in joined, word
        assert sorted(r.get("candidates") or []) == sorted(ETH_CANDIDATES)


def test_bare_level_word_without_context_stays_unknown(monkeypatch):
    # The contract boundary, pinned: the backend is stateless per
    # request and a bare level word carries no question and no scope,
    # so it honestly answers unknown. The FRONTEND must never send
    # one — it sends original question + level word, scoped to the
    # candidates (see the node-harness cases below), and re-asks
    # locally when the reply names no level at all.
    for word in ("undergraduate", "masters", "本科", "硕士"):
        r = _answer_no_key(monkeypatch, word, "en" if word.isascii() else "zh-CN")
        assert "don't know" in r["lines"][0] or "不知道" in r["lines"][0], word


# ---------------------------------------------------------------------------
# Endpoint: the exact tester sequence, en + zh, with profile context
# ---------------------------------------------------------------------------

def test_endpoint_full_sequence_en(monkeypatch):
    _no_key_provider(monkeypatch)
    r = client.post("/api/v1/assistant/chat", json={
        "message": Q_EN, "locale": "en"})
    assert r.status_code == 200
    body = r.json()
    assert body["ai_status"] == "unavailable"
    assert sorted(body.get("candidates") or []) == sorted(ETH_CANDIDATES)
    # Button tap: "Undergraduate".
    r = client.post("/api/v1/assistant/chat", json={
        "message": _followup(Q_EN, "undergraduate"), "locale": "en",
        "program_ids": body["candidates"]})
    assert r.status_code == 200
    joined = "\n".join(r.json()["lines"])
    assert "CHF 4,380" in joined
    assert "Bachelor of Science in Computer Science" in joined
    # Typed: "masters".
    r = client.post("/api/v1/assistant/chat", json={
        "message": _followup(Q_EN, "masters"), "locale": "en",
        "program_ids": body["candidates"]})
    joined = "\n".join(r.json()["lines"])
    assert "CHF 4,380" in joined
    assert "MSc in Computer Science" in joined


def test_endpoint_full_sequence_zh_with_profile(monkeypatch):
    _no_key_provider(monkeypatch)
    # With a saved profile: the first turn carries the context.
    r = client.post("/api/v1/assistant/chat", json={
        "message": Q_ZH + "\n" + CTX_EN, "locale": "zh-CN"})
    assert r.status_code == 200
    body = r.json()
    assert sorted(body.get("candidates") or []) == sorted(ETH_CANDIDATES)
    r = client.post("/api/v1/assistant/chat", json={
        "message": _followup(Q_ZH, "本科"), "locale": "zh-CN",
        "program_ids": body["candidates"]})
    joined = "\n".join(r.json()["lines"])
    assert "4,380" in joined
    assert "Bachelor of Science in Computer Science" in joined


# ---------------------------------------------------------------------------
# Regression: unrelated answers are unchanged
# ---------------------------------------------------------------------------

def test_regression_single_match_fee_still_direct(monkeypatch):
    r = _answer_no_key(monkeypatch,
                       "What is the tuition fee for UCL Computer Science BSc?",
                       "en")
    assert "48,600" in r["lines"][0]
    assert "candidates" not in r


def test_regression_suggestion_still_works(monkeypatch):
    # The guided 3-question flow's constructed message (onboarding
    # must still work when NO disambiguation is pending).
    r = _answer_no_key(
        monkeypatch,
        "Recommend an undergraduate programme in Switzerland "
        "(country code CH). Budget band: mid.",
        "en")
    # Cheapest verified UG programme in CH is UZH Informatics
    # (CHF 2,440/year) — the pick is the engine's, the point here is
    # the suggestion path still answers instead of erroring.
    assert "Verified suggestion" in r["lines"][0]
    assert "University of Zurich" in r["lines"][0]
    assert "CHF 2,440" in "\n".join(r["lines"])


def test_regression_unrelated_unknown_stays_unknown(monkeypatch):
    r = _answer_no_key(monkeypatch, "我应该申几所学校", "zh-CN")
    assert "不知道" in r["lines"][0]
    assert "candidates" not in r


# ---------------------------------------------------------------------------
# Frontend: lib/chat.ts disambiguation helpers (node harness)
# ---------------------------------------------------------------------------

_NODE_HARNESS = r"""
const chat = require(OUT + '/chat.js');
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + ' -> ' + g + ' want ' + w); fail++; }
  else console.log('PASS ' + name);
};

const Q_EN = 'What is the tuition fee for ETH Zurich Computer Science?';
const Q_ZH = '苏黎世联邦理工计算机科学的学费是多少？';
const BSC = 'eth-cs-bsc-2027';
const MSC = 'eth-cs-msc-2027';
const AMB = { lines: ['I found 2 matching programmes: ETH Zurich — MSc in Computer Science, ETH Zurich — Bachelor of Science in Computer Science. Tell me undergraduate or masters.'], ai_status: 'unavailable', candidates: [MSC, BSC] };
const FEE = { lines: ['ETH Zurich — Bachelor of Science in Computer Science tuition: CHF 4,380 per year.'], ai_status: 'unavailable' };
const PROGRAMS = [
  { id: BSC, degreeLevel: 'undergraduate' },
  { id: MSC, degreeLevel: 'taught_masters' },
];

// --- detectLevelWord: the frontend and the backend agree on levels ---
check('level: undergraduate', chat.detectLevelWord('undergraduate'), 'undergraduate');
check('level: Undergraduate (case)', chat.detectLevelWord('Undergraduate'), 'undergraduate');
check('level: masters', chat.detectLevelWord('masters'), 'taught_masters');
check('level: Master\'s', chat.detectLevelWord("Master's"), 'taught_masters');
check('level: BSc', chat.detectLevelWord('BSc'), 'undergraduate');
check('level: MSc', chat.detectLevelWord('MSc'), 'taught_masters');
check('level: 本科', chat.detectLevelWord('本科'), 'undergraduate');
check('level: 硕士', chat.detectLevelWord('硕士'), 'taught_masters');
check('level: 研究生', chat.detectLevelWord('研究生'), 'taught_masters');
check('level: 学士', chat.detectLevelWord('学士'), 'undergraduate');
check('level: grad is not a level word', chat.detectLevelWord('grad'), null);
check('level: hmm is not a level word', chat.detectLevelWord('hmm'), null);
check('level: a new question names no level', chat.detectLevelWord('What about Oxford?'), null);
check('level: both named, undergraduate wins (backend order)', chat.detectLevelWord('undergraduate or masters?'), 'undergraduate');

// --- disambiguationFollowupMessage: original question + level word ---
check('followup en UG', chat.disambiguationFollowupMessage(Q_EN, 'undergraduate', 'en'), Q_EN + ' undergraduate');
check('followup en TM', chat.disambiguationFollowupMessage(Q_EN, 'taught_masters', 'en'), Q_EN + ' masters');
check('followup zh UG', chat.disambiguationFollowupMessage(Q_ZH, 'undergraduate', 'zh-CN'), Q_ZH + ' 本科');
check('followup zh TM', chat.disambiguationFollowupMessage(Q_ZH, 'taught_masters', 'zh-CN'), Q_ZH + ' 硕士');

// --- disambiguationLevels: undergraduate first, unknown ids drop out ---
check('levels: both, UG first (not backend MSc-first order)',
  chat.disambiguationLevels([MSC, BSC], PROGRAMS), ['undergraduate', 'taught_masters']);
check('levels: UG only', chat.disambiguationLevels([BSC], PROGRAMS), ['undergraduate']);
check('levels: unknown ids resolve to none', chat.disambiguationLevels(['nope-1'], PROGRAMS), []);

// --- pendingDisambiguation: derived from the turns alone ---
const base = [
  { kind: 'prompt', key: 'pet.greeting' },
  { kind: 'freeText', text: Q_EN },
  { kind: 'ask', message: Q_EN, reply: AMB, replyLocale: 'en', offline: true, devil: false },
];
const pend = chat.pendingDisambiguation(base);
check('pending: candidates from the ambiguous reply', pend && pend.candidates, [MSC, BSC]);
check('pending: question is the original question', pend && pend.question, Q_EN);
check('pending: replyLocale kept', pend && pend.replyLocale, 'en');
check('pending: reply is the ambiguous reply', pend && pend.reply, AMB);

// A follow-up turn ends it (fee answer has no candidates).
const answered = [...base,
  { kind: 'freeText', text: 'Undergraduate' },
  { kind: 'ask', message: Q_EN, reply: FEE, replyLocale: 'en', offline: true, devil: false },
];
check('pending: cleared once the fee is answered', chat.pendingDisambiguation(answered), null);

// A follow-up that comes back ambiguous again keeps it live.
const reasked = [...base,
  { kind: 'freeText', text: 'grad' },
  { kind: 'ask', message: Q_EN, reply: AMB, replyLocale: 'en', offline: true, devil: false },
];
check('pending: live again when the follow-up asks once more',
  chat.pendingDisambiguation(reasked) && chat.pendingDisambiguation(reasked).candidates, [MSC, BSC]);

// A local re-ask turn (same reply, new turn) keeps it live.
const localReask = [...base,
  { kind: 'freeText', text: 'hmm' },
  { kind: 'ask', message: Q_EN, reply: AMB, replyLocale: 'en', offline: true, devil: false },
];
check('pending: live after a local re-ask', chat.pendingDisambiguation(localReask) !== null, true);

// A new question supersedes it.
const newQ = [...base,
  { kind: 'freeText', text: 'What about Oxford?' },
  { kind: 'ask', message: 'What about Oxford?', reply: { lines: ['Oxford rank.'], ai_status: 'unavailable' }, replyLocale: 'en', offline: true, devil: false },
];
check('pending: cleared by a new question', chat.pendingDisambiguation(newQ), null);

// No ambiguous ask at all: onboarding is untouched.
check('pending: null with no ask turn', chat.pendingDisambiguation([{ kind: 'prompt', key: 'pet.q1' }]), null);
check('pending: null when the reply has no candidates',
  chat.pendingDisambiguation([{ kind: 'ask', message: Q_EN, reply: FEE, replyLocale: 'en' }]), null);
check('pending: null on empty turns', chat.pendingDisambiguation([]), null);

if (fail) { console.log(fail + ' FAILURES'); process.exit(1); }
console.log('ALL HARNESS CASES PASS');
"""


def test_r24_w1_frontend_disambiguation_helpers(tmp_path):
    """Node harness over frontend/src/lib/chat.ts: the level-word
    detection, the follow-up message, the level chips and the pending
    derivation — the frontend half of the contract."""
    outdir = tmp_path / "r24w1_chat"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/chat.ts",
         "--module", "commonjs", "--target", "es2020",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r24w1_harness.js"
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


# ---------------------------------------------------------------------------
# Frontend: CompassPet wiring (source pins — the component itself is
# exercised in the browser; the pins guard the routing decisions)
# ---------------------------------------------------------------------------

def test_r24_w1_compass_pet_routing_pins():
    """The chip tap and the typed send route through the pending
    disambiguation BEFORE any onboarding branch, and the follow-up
    carries the original question + level word scoped to the
    candidates. The onboarding branches themselves are intact below
    the pending branch."""
    pet = (ROOT / "frontend/src/components/CompassPet.tsx").read_text(encoding="utf-8")
    chat = (ROOT / "frontend/src/lib/chat.ts").read_text(encoding="utf-8")

    # The helpers exist and are imported by the component.
    for name in ("detectLevelWord", "disambiguationFollowupMessage",
                 "disambiguationLevels", "pendingDisambiguation"):
        assert f"export function {name}" in chat, name
        assert name in pet, name
    assert "candidates?: string[]" in chat

    # onChip: the pending branch runs before the onboarding steps.
    pending_at = pet.index("const pendingNow = pendingDisambiguation(messages);")
    step0_at = pet.index("if (step === 0) {", pending_at)
    assert "void sendAskTurn({" in pet[pending_at:step0_at]
    assert "programIds: pendingNow.candidates" in pet[pending_at:step0_at]
    assert "skipContext: true" in pet[pending_at:step0_at]

    # onSend: a typed level word resolves; a non-level, non-question
    # reply is re-asked locally (never sent bare).
    assert "const level = detectLevelWord(text);" in pet
    assert "if (!looksLikeQuestion(text)) {" in pet
    assert "reply: pendingNow.reply" in pet

    # Chips: the pending level chips override the onboarding chips.
    assert "pendingChips ??" in pet
    assert "disambiguationLevels(pending.candidates, allPrograms())" in pet

    # Round 27 W1 SUPERSEDES the old locale rule below (re-test
    # task 21): the locale re-fetch that re-sent a follow-up's
    # constructed message is deleted — a stored reply is never
    # re-fetched. The constructed message is still what onSend
    # itself sends for the follow-up turn.
    assert "message: sentMessage, locale: requestLocale" in pet

    # Onboarding itself is intact: the step branches still exist,
    # after the pending branch, and the suggestion path is untouched.
    assert "push({ kind: 'prompt', key: 'pet.q2' });" in pet
    assert "void askSuggest(degree, country, band);" in pet
