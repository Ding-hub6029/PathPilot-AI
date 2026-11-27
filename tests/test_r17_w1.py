"""Round 17 W1 — PrefChat: the country preference must never be silently
lost; the WHY answer renders as a user bubble.

Audit profile: China Gaokao, UG, CS, 680/750, IELTS 7.0, budget
GBP 50,000, 2027, overseas, Switzerland / cool / university-town /
Zurich. Audit flow: turn 1 "我想去瑞士，因为那边环境优美", WHY
answered "喜欢湖光山色、空气清新、安静宜居", then the model drops
mid-flow and the guided fallback continues.

Re-test task 11 (2026-11-27 08:29-08:33 CST) found two P0s:

FINDING 1 (P0 NEW, worst) — COUNTRY PREFERENCE SILENTLY LOST. The first
reply confirmed "你想去瑞士", but the preference summary contained NO
"瑞士" at all; step-8 recommendations and the results page top 2 were
University of Alberta (Edmonton) and ANU (Canberra) — ZERO Swiss
schools. The confirm bubble was never clicked "对" — it DISAPPEARED
after the AI dropped — and the guided fallback reused the WHY free text
as the country answer ("喜欢湖光山色·空气清新·安静宜居" shown as the
country). Mechanism, verified with evidence before the fix (scratch
harness /tmp/r17-before/repro.js, not committed): the turn-1 extraction
{countries: ["CH"], note: "那边环境优美"} lived ONLY in the frontend's
`pendingExtract` (nothing applied until confirm); answering the WHY
stored only the note via `saveReason` (which never touched
`pendingExtract`); the drop ran `preserveFailedAnswer` ->
`enterGuidedMode`, which did `setPendingExtract(null)` and discarded
the CH extraction; and the note alone counts as the countries
preference answered (`isPrefKnown` / `isPrefAnswered`), so the guided
queue skipped the countries question and the summary showed the WHY
text where the country should be. Recommendations follow the profile
(`sortRecsByPreference`: preferred countries first), so with the
country lost the top 2 were Alberta/ANU by id order, with the country
kept they are the two Swiss programmes.
Fix, two halves: (a) answering the WHY about a country IS implicit
confirmation of that country — `saveReason` lands the WHY's countries
from the pending extraction (pure helper `splitWhyConfirmedCountries`)
in the same update as the note, so a later drop cannot lose it; only
the WHY's countries land, the rest stays pending for the confirm
bubble. (b) The pending extraction / confirm survives a drop —
`enterGuidedMode` and `retryModelChat` no longer discard it, and the
guided branch re-offers the same confirm bubble. The note-counts-as-
known helpers are deliberately NOT changed: a note alone is the
designed preservation for an unlisted country named in words, and
after (a)+(b) it can no longer masquerade as the country in the WHY
flow. The exact tester path is asserted end to end on the rendered
flow (node harness): summary contains 瑞士 and the top 2
recommendations are Swiss — with the BEFORE counterpart (country lost)
pinned as the failing shape.

FINDING 2 (P0) — WHY ANSWER RENDERING STILL WRONG. Answering the WHY
did NOT render as a cyan right-aligned user bubble under the WHY
question (the way the climate answer renders). Instead the answer was
merged into the pet's white assistant bubble ("收到，记下啦～" first
line, the user's own words second line in small grey). The bubble
order (`prefTurnBubbles`) already returned a separate `whyAnswer`
bubble (round 16 F2) — the component rendered that bubble inside a
white assistant container. Fix in `renderPrefTurns` only: the WHY
answer renders as a normal cyan user bubble, and the acknowledgement
is a separate assistant line after it, never a container that swallows
the user's words. Bubble kinds/order are unchanged (round 16
assertions still pass).

P1 (WHY order nit — climate facts stated before the WHY question) was
judged ACCEPTABLE with reasoning and is NOT fixed: the order
requirement is met (the WHY is the turn's only question, the climate
question line is withheld), and the facts are verified evidence lines
— in the template path the first line IS the evidence line — so
stripping them would gut the reply's evidence. See
/tmp/r17-w1-decisions.md. P2 (summary string twice: summary bubble +
pet title bar) is a residual: the second copy lives in CompassPet
(outside this worker's files).

Run from the project root:
    .venv/bin/pytest tests/test_r17_w1.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from ai.pref_chat import _question_line, pref_answer
from ai.provider import ProviderAdapter

ROOT = Path(__file__).resolve().parents[1]

AUDIT_MSG = "我想去瑞士，因为那边环境优美"
WHY_ANSWER = "喜欢湖光山色、空气清新、安静宜居"
CLIMATE_Q = _question_line("climate", "zh-CN")
ENV_Q = _question_line("environment", "zh-CN")
# The profile after the WHY is answered (fix A): the country landed
# with the WHY answer, the note is the WHY answer normalised to one
# atom, climate preserved by the drop's local mapping.
KNOWN_AFTER_WHY = {"countries": ["CH"],
                   "note": "喜欢湖光山色·空气清新·安静宜居"}


# ---------------------------------------------------------------------------
# Mock-provider helpers (httpx.MockTransport; no real key, no network)
# ---------------------------------------------------------------------------

def _openai_reply(payload_text: str) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"content": payload_text}}], "usage": {}})


def _mock_provider(monkeypatch, handler) -> ProviderAdapter:
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")
    return ProviderAdapter(_transport=httpx.MockTransport(handler))


def _no_key_provider(monkeypatch) -> ProviderAdapter:
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return ProviderAdapter()


def _fixed_model_handler(payload: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_reply(json.dumps(payload, ensure_ascii=False))
    return handler


AUDIT_MODEL_PAYLOAD = {
    "summary": "明白，你说那边环境优美，我记下了。",
    "claims": [{"text": "苏黎世：四季分明。", "kind": "fact",
                "rule_ids": [], "evidence_ids": ["climate:zurich"]}],
    "unknowns": [], "actions": [], "limitations": [],
    "extracted": {"countries": ["CH"], "note": "那边环境优美"},
    "next_question": "climate",
}

CLIMATE_MODEL_PAYLOAD = {
    "summary": "凉爽记下了。",
    "claims": [{"text": "苏黎世：四季分明。", "kind": "fact",
                "rule_ids": [], "evidence_ids": ["climate:zurich"]}],
    "unknowns": [], "actions": [], "limitations": [],
    "extracted": {"climate": "cool"},
    "next_question": "environment",
}


# ---------------------------------------------------------------------------
# Finding 1 — backend half of the fixed flow: the first turn returns
# what the frontend needs, and once the country has landed (fix A)
# the next turn advances instead of re-firing the WHY
# ---------------------------------------------------------------------------

def test_r17_first_turn_returns_country_and_why(monkeypatch):
    """Step 1 of the tester path, both paths: the turn-1 extraction is
    {countries: [CH], note} with the WHY follow-up riding in the first
    reply (the input fix A splits). The climate question line is
    withheld while the WHY is the turn's question (round 16)."""
    provider = _mock_provider(monkeypatch, _fixed_model_handler(AUDIT_MODEL_PAYLOAD))
    r = pref_answer(AUDIT_MSG, "zh-CN", known={}, provider=provider)
    assert r["ai_status"] == "available"
    assert r["extracted"] == {"countries": ["CH"], "note": "那边环境优美"}
    assert r["why_followup"] == {"countries": ["CH"], "note": "那边环境优美"}
    assert r["next_question"] == "climate"
    assert CLIMATE_Q not in r["lines"]
    r = pref_answer(AUDIT_MSG, "zh-CN", known={},
                    provider=_no_key_provider(monkeypatch))
    assert r["ai_status"] == "unavailable"
    assert r["extracted"] == {"countries": ["CH"], "note": "那边环境优美"}
    assert r["why_followup"] == {"countries": ["CH"], "note": "那边环境优美"}
    assert r["next_question"] == "climate"
    assert CLIMATE_Q not in r["lines"]


def test_r17_second_turn_after_country_lands_model_up(monkeypatch):
    """Step 2 of the tester path, model-up: the frontend sends
    known={countries: [CH], note} (the country landed with the WHY
    answer) and the climate answer. The WHY must NOT re-fire for CH,
    the climate extraction lands, and the next question is
    environment — the conversation advances past the country."""
    provider = _mock_provider(monkeypatch, _fixed_model_handler(CLIMATE_MODEL_PAYLOAD))
    r = pref_answer("凉快一点", "zh-CN", known=KNOWN_AFTER_WHY, provider=provider)
    assert r["ai_status"] == "available"
    assert r["extracted"] == {"climate": "cool"}
    assert r["why_followup"] is None
    assert r["next_question"] == "environment"
    assert r["lines"][-1] == ENV_Q


def test_r17_second_turn_after_country_lands_no_key(monkeypatch):
    """Step 2 offline: the WHY still does not re-fire for CH, and the
    deterministic order keeps climate as the open question — the
    offline path cannot read "凉快一点" as a climate enum, so the
    question stays open and the frontend's guided fallback maps it
    locally (that is the known offline behaviour, not a re-ask of
    the country)."""
    r = pref_answer("凉快一点", "zh-CN", known=KNOWN_AFTER_WHY,
                    provider=_no_key_provider(monkeypatch))
    assert r["ai_status"] == "unavailable"
    assert r["extracted"] == {}
    assert r["why_followup"] is None
    assert r["next_question"] == "climate"


# ---------------------------------------------------------------------------
# Findings 1+2 — the exact tester path as rendered flow (node harness
# over lib/chat.ts + lib/preferences.ts), plus the split helper
# ---------------------------------------------------------------------------

_NODE_HARNESS = r"""
const chat = require(OUT + '/chat.js');
const prefs = require(OUT + '/preferences.js');
const { emptyProfile } = require(OUT + '/types.js');
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + ' -> ' + g + ' want ' + w); fail++; }
  else console.log('PASS ' + name);
};
const kinds = (bs) => bs.map((b) => b.kind);
const tZh = (k) => ({
  'country.CH': '瑞士', 'country.CA': '加拿大', 'country.AU': '澳大利亚',
  'wizard.prefClimateCool': '凉爽',
}[k] ?? k);
const WHY_ANSWER = '喜欢湖光山色、空气清新、安静宜居';

// --- The split helper (fix A, pure) ------------------------------------
check('split: exact tester split confirms CH, keeps the note pending',
  chat.splitWhyConfirmedCountries(
    { countries: ['CH'], note: '那边环境优美' }, ['CH']),
  { confirmedCountries: ['CH'], remaining: { note: '那边环境优美' } });
check('split: no overlap confirms nothing, keeps everything pending',
  chat.splitWhyConfirmedCountries(
    { countries: ['SG'], climate: 'cool' }, ['CH']),
  { confirmedCountries: [], remaining: { countries: ['SG'], climate: 'cool' } });
check('split: multi-country extraction confirms only the WHY country',
  chat.splitWhyConfirmedCountries(
    { countries: ['CH', 'SG'], note: '想体验多元文化' }, ['CH']),
  { confirmedCountries: ['CH'], remaining: { countries: ['SG'], note: '想体验多元文化' } });
check('split: a countries-only extraction leaves nothing pending',
  chat.splitWhyConfirmedCountries({ countries: ['CH'] }, ['CH']),
  { confirmedCountries: ['CH'], remaining: null });
check('split: no pending extraction confirms nothing',
  chat.splitWhyConfirmedCountries(undefined, ['CH']),
  { confirmedCountries: [], remaining: null });
check('split: WHY for a country already in the profile still strips it from pending',
  chat.splitWhyConfirmedCountries({ countries: ['CH'], climate: 'cool' }, ['CH']),
  { confirmedCountries: ['CH'], remaining: { climate: 'cool' } });

// --- The exact tester path, end to end ----------------------------------
// Step 1 — turn 1 as the backend returns it (both paths): the
// extraction is {countries: [CH], note}, the WHY rides in the first
// reply, climate is the deferred next question.
const turn1Reply = {
  lines: ['明白，你说那边环境优美，我记下了。', '苏黎世：四季分明。'],
  ai_status: 'available', model: 'deepseek/test-model',
  extracted: { countries: ['CH'], note: '那边环境优美' },
  next_question: 'climate',
  why_followup: { countries: ['CH'], note: '那边环境优美' },
};
const whyRecord = { countries: ['CH'], note: '那边环境优美', answer: null, skipped: false };
const whyOpen = { countries: ['CH'], note: '那边环境优美', turnId: 1 };

// Step 2 — the WHY is answered WITHOUT clicking confirm. Fix A: the
// split lands CH in the profile (profilePatchFromExtracted, the same
// applier confirmExtract uses) and leaves only the note pending;
// the WHY answer becomes the countries note (one atom).
const split = chat.splitWhyConfirmedCountries(turn1Reply.extracted, ['CH']);
const profileAfterWhy = {
  ...chat.profilePatchFromExtracted({ countries: split.confirmedCountries }, emptyProfile),
  prefCountriesNote: chat.appendCountryNote('', WHY_ANSWER),
};
check('flow: WHY answer lands Switzerland in the profile',
  profileAfterWhy.prefCountries, ['CH']);
check('flow: WHY answer is the countries note (one atom)',
  profileAfterWhy.prefCountriesNote, '喜欢湖光山色·空气清新·安静宜居');
check('flow: the rest of the extraction stays pending for confirm',
  split.remaining, { note: '那边环境优美' });
check('flow: countries is known once the WHY answer lands it',
  chat.isPrefKnown('countries', chat.knownFromProfile(profileAfterWhy)), true);
check('flow: next question after the WHY is climate (not countries)',
  chat.firstMissingPref(chat.knownFromProfile(profileAfterWhy)), 'climate');

// Step 3 — the model drops mid-flow (the next send fails) and the
// guided fallback continues. The drop marks the turn offline IN PLACE
// (append-only, round 15) and the climate answer is preserved locally;
// the country is already in the profile, so the drop cannot lose it.
const turnsAnswered = chat.answerTurnWhy(
  [{ id: 1, question: '我想去瑞士，因为那边环境优美', reply: turn1Reply,
     replyLocale: 'zh-CN', offline: false, why: whyRecord }],
  1, WHY_ANSWER, whyOpen);
const turnsDropped = chat.markTurnOffline(turnsAnswered, 1, turn1Reply, 'zh-CN');
check('flow: drop keeps the turn (nothing removed or reordered)',
  turnsDropped.length, 1);
check('flow: dropped turn keeps its question verbatim',
  turnsDropped[0].question, '我想去瑞士，因为那边环境优美');
check('flow: dropped turn is marked offline, not pending',
  { offline: turnsDropped[0].offline, pending: turnsDropped[0].pending },
  { offline: true, pending: false });
check('flow: dropped turn keeps its WHY question + answer',
  turnsDropped[0].why,
  { countries: ['CH'], note: '那边环境优美', answer: WHY_ANSWER, skipped: false });
const profileAfterDrop = { ...profileAfterWhy, prefClimate: 'cool' };
check('flow: Switzerland is still in the profile after the drop',
  profileAfterDrop.prefCountries, ['CH']);

// Step 4 — the summary AND the recommendations after the drop.
const summary = prefs.prefSummary(profileAfterDrop, tZh);
check('flow: summary contains Switzerland',
  summary.includes('瑞士'), true);
check('flow: summary is the full preference string, WHY text as the reason',
  summary, '凉爽 · 瑞士 · 喜欢湖光山色·空气清新·安静宜居');
// Step-8 recommendations: preferred countries first
// (sortRecsByPreference); Gaokao academic UNKNOWN everywhere, so all
// four recs are PARTIAL_UNKNOWN and the preference decides the top.
const programs = [
  { id: 'eth-cs-bsc-2027', country: 'CH', city: 'Zurich' },
  { id: 'epfl-cs-bsc-2027', country: 'CH', city: 'Lausanne' },
  { id: 'alberta-cs-ai-bsc-2027', country: 'CA', city: 'Edmonton' },
  { id: 'anu-computing-bachelor-2027', country: 'AU', city: 'Canberra' },
];
const recs = programs.map((p) => ({ programId: p.id, eligibilitySummary: 'PARTIAL_UNKNOWN', ruleResults: [] }));
const topAfter = prefs.sortRecsByPreference(recs, programs, profileAfterDrop).slice(0, 2);
check('flow: top 2 recommendations after the drop are Swiss',
  topAfter.map((r) => r.programId), ['epfl-cs-bsc-2027', 'eth-cs-bsc-2027']);
check('flow: top 2 recommendations are in Switzerland',
  topAfter.map((r) => programs.find((p) => p.id === r.programId).country), ['CH', 'CH']);

// --- BEFORE counterpart: the same path with the country lost -----------
// (the R16 behaviour: the WHY answer stored only the note, the drop
// discarded the pending extraction). This is the failing shape the
// fix must never reproduce: summary with no 瑞士, Alberta/ANU on top.
const profileLost = { ...emptyProfile,
  prefCountries: [], prefCountriesNote: '喜欢湖光山色·空气清新·安静宜居',
  prefClimate: 'cool' };
const summaryLost = prefs.prefSummary(profileLost, tZh);
check('before: summary with the country lost has no Switzerland',
  summaryLost.includes('瑞士'), false);
check('before: summary with the country lost shows the WHY text as the country slot',
  summaryLost, '凉爽 · 喜欢湖光山色·空气清新·安静宜居');
check('before: top 2 with the country lost are Alberta and ANU (the reported symptom)',
  prefs.sortRecsByPreference(recs, programs, profileLost).slice(0, 2).map((r) => r.programId),
  ['alberta-cs-ai-bsc-2027', 'anu-computing-bachelor-2027']);

// --- Finding 2: the WHY answer stays attached to its question ---------
const bsAnswered = chat.prefTurnBubbles(turnsAnswered[0], null);
check('F2 bubble order after answering: user, reply, WHY, answer, deferred climate',
  kinds(bsAnswered), ['user', 'reply', 'why', 'whyAnswer', 'deferredQuestion']);
check('F2 WHY question and answer are adjacent in history',
  bsAnswered[2].kind === 'why' && bsAnswered[3].kind === 'whyAnswer', true);
check('F2 WHY answer bubble carries the verbatim answer',
  bsAnswered[3], { kind: 'whyAnswer', answer: WHY_ANSWER });
check('F2 deferred question is climate, after the WHY answer',
  bsAnswered[4], { kind: 'deferredQuestion', question: 'climate' });

// --- Leave-and-return keeps the fix ------------------------------------
// The pending remainder ({note}) and the WHY record survive the blob.
const fp = chat.prefChatFingerprint(profileAfterDrop);
const state = {
  mode: 'model',
  turns: [{ id: 1, question: '我想去瑞士，因为那边环境优美',
    reply: turn1Reply, replyLocale: 'zh-CN', offline: true,
    why: { countries: ['CH'], note: '那边环境优美', answer: WHY_ANSWER, skipped: false } }],
  modelTurns: [],
  qIndex: 0, skipped: [], serverNext: 'climate',
  awaitingReason: null, verbatim: {}, failedText: null,
  pendingExtract: { extracted: { note: '那边环境优美' },
    rawText: '我想去瑞士，因为那边环境优美' },
  confirmedNotes: [],
};
const restored = chat.parsePrefChatState(chat.serializePrefChatState(state, fp), fp);
check('leave-return: pending remainder survives',
  restored && restored.pendingExtract, { extracted: { note: '那边环境优美' }, rawText: '我想去瑞士，因为那边环境优美' });
check('leave-return: WHY question + answer survive on the turn',
  restored && restored.turns[0].why,
  { countries: ['CH'], note: '那边环境优美', answer: WHY_ANSWER, skipped: false });
check('leave-return: bubble order still user, reply, WHY, answer, deferred climate',
  restored && kinds(chat.prefTurnBubbles(restored.turns[0], null)),
  ['user', 'reply', 'why', 'whyAnswer', 'deferredQuestion']);
process.exit(fail ? 1 : 0);
"""


def test_r17_w1_exact_tester_path(tmp_path):
    """Round 17: the split helper, the exact tester path end to end
    (Switzerland sentence -> WHY answered without confirming -> model
    drop -> guided fallback: summary contains 瑞士, top 2
    recommendations are Swiss), the BEFORE counterpart as the failing
    shape, the WHY answer attached to its question, and leave-and-
    return keeping the fix."""
    outdir = tmp_path / "r17_pref"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/preferences.ts", "src/lib/chat.ts",
         "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r17_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(fe))), encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"],
           "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout


def test_r17_w1_source_pins():
    """Round 17, source pins: the WHY answer lands the country, the
    pending extraction survives a drop and its confirm is re-offered
    in the guided branch, and the WHY answer renders as a user bubble
    with a separate acknowledgement line."""
    prefchat = (ROOT / "frontend/src/components/PrefChat.tsx").read_text(encoding="utf-8")
    chat = (ROOT / "frontend/src/lib/chat.ts").read_text(encoding="utf-8")

    # Finding 1a: saveReason splits the pending extraction and applies
    # the WHY's countries with the note, in one update.
    assert "splitWhyConfirmedCountries" in chat
    assert "splitWhyConfirmedCountries(\n      pendingExtract?.extracted, whyCountries)" in prefchat
    assert "patch.prefCountries = [...new Set([...(profile.prefCountries ?? []), ...confirmedCountries])]" in prefchat
    assert "remaining ? { extracted: remaining, rawText: prev.rawText } : null" in prefchat

    # Finding 1b: the pending extraction is never silently discarded
    # on a drop or a retry — only confirm / dismiss / restart clear
    # it (three sites, all explicit user actions or a reset).
    assert prefchat.count("setPendingExtract(null)") == 3, (
        "only confirmExtract, dismissExtract and restart may clear a pending extraction")
    guided = prefchat[prefchat.index("const enterGuidedMode"):]
    guided = guided[:guided.index("const preserveFailedAnswer")]
    assert "setPendingExtract(null)" not in guided
    retry = prefchat[prefchat.index("const retryModelChat"):]
    retry = retry[:retry.index("const confirmExtract")]
    assert "setPendingExtract(null)" not in retry
    # The guided branch re-offers the same confirm bubble as the
    # model branch (two render sites, not one).
    assert prefchat.count(
        "{tf('wizard.chatParseConfirm', { summary: extractedSummary(pendingExtract.extracted, t, locale) })}") == 2, (
        "the confirm bubble must render in the model branch AND the guided branch")

    # Finding 2: the whyAnswer branch renders the answer as a cyan
    # right-aligned user bubble, with the acknowledgement as a
    # separate assistant line after it — never inside one white bubble.
    block = prefchat[prefchat.index("if (bubble.kind === 'whyAnswer')"):]
    block = block[:block.index("// deferredQuestion")]
    assert block.index("justify-end") < block.index("{bubble.answer}"), (
        "the WHY answer must sit in a right-aligned (user) container")
    assert "bg-teal" in block and "{bubble.answer}" in block
    assert block.index("{bubble.answer}") < block.index("t('wizard.chatOpThanks')"), (
        "the acknowledgement must come after the user's answer, as its own line")
    assert block.index("justify-end") < block.index("justify-start"), (
        "the user bubble comes first, the assistant acknowledgement second")
    assert 'text-navy/70">{bubble.answer}' not in block, (
        "the user's words must not render as small grey text inside the pet's bubble")
