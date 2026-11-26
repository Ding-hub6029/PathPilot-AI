"""Round 14 regression tests (re-test task 8, 2026-11-27 00:42-00:50 CST).

Covers, with no API key and no network, via a node harness over the
compiled frontend (same pattern as tests/test_r13_pref_summary.py):

- P0 (WHY hidden behind the confirm chip): `whyFollowupFromExtracted`
  in frontend/src/lib/chat.ts derives the follow-up from a reply's
  extraction against the known set BEFORE the turn — so the frontend
  can arm it in the FIRST reply, in both the model-up path (the
  backend now also sends `why_followup`, tested in
  tests/test_pref_chat.py) and the template/gateway-down path. A
  reason from an earlier turn still suppresses it.
- P1 (progress lost on leaving mid-way): `serializePrefChatState` /
  `parsePrefChatState` in frontend/src/lib/chat.ts round-trip the
  chat's turn/progress state, validated against a fingerprint of the
  saved Profile's preference fields. A blob for another profile, a
  corrupt blob, or a wrong version is discarded; a turn that was
  still pending when the user left restores as offline, never as
  pending forever.
- P2a (WHY answer split into summary atoms): `normaliseCountryNote`
  / `appendCountryNote` store the note joined with an unspaced '·',
  so `prefSummary` keeps it as ONE atom (its '·' separators are not
  atom separators) — while the Round 13 dedupe still holds: a note
  built as "环境优美·校园氛围" next to the campus label still shows
  "校园氛围" exactly once.
- P2b (unlocalised confirm copy): `extractedSummary` in
  frontend/src/lib/chat.ts renders an extracted city through the
  localised lookup, so the confirm bubble reads "苏黎世", never the
  raw stored "Zurich".

Run from the project root:
    .venv/bin/pytest tests/test_r14_pref_chat.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Audit profile (re-test task 8): China Gaokao, UG, CS, 680/750,
# IELTS 7.0, budget GBP 50,000, 2027, overseas, Switzerland / cool /
# university-town / Zurich. Only the preference fields feed the
# summary; the academic fields are listed to pin the profile.
_AUDIT_PREFS = {
    "prefClimate": "cool",
    "prefCountries": ["CH"],
    "prefCountriesNote": "环境优美·校园氛围",
    "prefEnvironment": "campus",
    "prefCity": "Zurich",
    "prefAfterGrad": "stay",
    "prefSalary": 60000,
    "prefSalaryCurrency": "GBP",
    "prefPressure": "medium",
    "prefTeaching": "seminar",
}

_NODE_HARNESS = r"""
const prefs = require(OUT + '/preferences.js');
const chat = require(OUT + '/chat.js');
const { emptyProfile } = require(OUT + '/types.js');
const zh = require(FE + '/messages/zh-CN.json');
const en = require(FE + '/messages/en.json');
const tZh = (k) => zh[k] ?? k;
const tEn = (k) => en[k] ?? k;
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + ' -> ' + g + ' want ' + w); fail++; }
  else console.log('PASS ' + name);
};
const knownEmpty = chat.knownFromProfile(emptyProfile);

// --- P0: WHY follow-up derived from the reply's extraction ---------
check('P0 model turn: country+reason -> why with note',
  chat.whyFollowupFromExtracted({ countries: ['CH'], note: '环境优美' }, knownEmpty),
  { countries: ['CH'], note: '环境优美' });
check('P0 chip turn: country, no reason -> why without note',
  chat.whyFollowupFromExtracted({ countries: ['CH'] }, knownEmpty),
  { countries: ['CH'] });
check('P0 reason from an earlier turn -> no why',
  chat.whyFollowupFromExtracted({ countries: ['CH'], note: '环境优美' },
    chat.knownFromProfile({ ...emptyProfile, prefCountriesNote: '环境优美' })),
  null);
check('P0 no new country -> no why',
  chat.whyFollowupFromExtracted({ countries: ['CH'] },
    chat.knownFromProfile({ ...emptyProfile, prefCountries: ['CH'] })),
  null);
check('P0 empty extraction -> no why',
  chat.whyFollowupFromExtracted({}, knownEmpty), null);
check('P0 second country added later -> why for the new one only',
  chat.whyFollowupFromExtracted({ countries: ['CH', 'GB'] },
    chat.knownFromProfile({ ...emptyProfile, prefCountries: ['CH'] })),
  { countries: ['GB'] });

// --- P2b: confirm bubble localises the city -------------------------
check('P2b confirm summary localises Zurich',
  chat.extractedSummary({ city: 'Zurich' }, tZh), '苏黎世');
check('P2b confirm summary: country + city + note',
  chat.extractedSummary({ countries: ['CH'], city: 'Zurich', note: '环境优美' }, tZh),
  '瑞士 · 苏黎世 · “环境优美”');
check('P2b confirm summary localises Lausanne',
  chat.extractedSummary({ city: 'Lausanne' }, tZh), '洛桑');
check('P2b a Chinese city name passes through unchanged',
  chat.extractedSummary({ city: '苏黎世' }, tZh), '苏黎世');
check('P2b English UI still shows Zurich',
  chat.extractedSummary({ city: 'Zurich' }, tEn), 'Zurich');

// --- P2a: the note is stored/joined as ONE summary atom ------------
check('P2a note typed with 、 separators normalises to ·',
  chat.normaliseCountryNote('空气清新、湖光山色、安静宜居'),
  '空气清新·湖光山色·安静宜居');
check('P2a note typed with ； separators normalises to ·',
  chat.normaliseCountryNote('环境优美；校园氛围'), '环境优美·校园氛围');
check('P2a single reason unchanged',
  chat.normaliseCountryNote('环境优美'), '环境优美');
check('P2a appending a second reason joins with ·',
  chat.appendCountryNote('环境优美', '校园氛围'), '环境优美·校园氛围');
check('P2a appending a duplicate does not repeat it',
  chat.appendCountryNote('环境优美', '环境优美'), '环境优美');
check('P2a appending to an empty note',
  chat.appendCountryNote(undefined, '空气清新 · 湖光山色'), '空气清新·湖光山色');
check('P2a profile patch joins the note with ·',
  chat.profilePatchFromExtracted({ countries: ['CH'], note: '校园氛围' },
    { ...emptyProfile, prefCountries: ['CH'], prefCountriesNote: '环境优美' }).prefCountriesNote,
  '环境优美·校园氛围');
// The WHY answer renders as ONE element of the summary, not three.
const whyProfile = { ...emptyProfile,
  prefCountries: ['CH'], prefClimate: 'cool', prefCity: 'Zurich',
  prefCountriesNote: chat.normaliseCountryNote('空气清新、湖光山色、安静宜居') };
const whySummary = prefs.prefSummary(whyProfile, tZh);
const whyAtoms = whySummary.split(' · ');
check('P2a WHY answer is one summary atom',
  whyAtoms.includes('空气清新·湖光山色·安静宜居'), true);
check('P2a WHY summary has exactly 4 atoms',
  whyAtoms.length, 4);
// Round 13 dedupe still holds with the ·-joined note.
const audit = prefs.prefSummary({ ...emptyProfile, ...JSON.parse(process.argv[2]) }, tZh);
check('P2a audit summary unchanged',
  audit, '凉爽 · 瑞士 · 环境优美 · 大学城·校园氛围 · 苏黎世 · 留在留学国家 · 60000 GBP · 适中 · 小班研讨');
check('P2a audit 校园氛围 exactly once',
  (audit.match(/校园氛围/g) || []).length, 1);

// --- P1: leave-and-return persists the chat --------------------------
// Profile after the first (confirmed) turn: Switzerland + reason
// recorded, climate not yet asked. 1 of 8 known, next is climate.
const savedProfile = { ...emptyProfile,
  prefCountries: ['CH'], prefCountriesNote: '环境优美' };
const fp = chat.prefChatFingerprint(savedProfile);
check('P1 progress is 1 of 8 after the first turn',
  chat.countKnownPrefs(chat.knownFromProfile(savedProfile)), 1);
check('P1 next question after return is climate',
  chat.firstMissingPref(chat.knownFromProfile(savedProfile)), 'climate');
const state = {
  mode: 'model',
  turns: [
    { id: 1, question: '我想去瑞士，因为那边环境优美',
      reply: { lines: ['明白，你说那边环境优美，我记下了。', 'Zurich: four-season climate.',
        '你喜欢什么样的气候——暖和、凉爽、四季分明还是温和？'],
        ai_status: 'available', model: 'openai/test-model',
        extracted: { countries: ['CH'], note: '那边环境优美' }, next_question: 'climate' },
      replyLocale: 'zh-CN', offline: false, pending: false },
    // Left while the second turn was still thinking: no reply yet.
    { id: 2, question: '凉爽', reply: null, replyLocale: null, offline: false, pending: true },
  ],
  modelTurns: [],
  qIndex: 0, skipped: [], serverNext: 'climate',
  awaitingReason: { countries: ['CH'], note: '那边环境优美' },
  verbatim: {}, failedText: null,
};
const blob = chat.serializePrefChatState(state, fp);
check('P1 serialised blob never stores pending',
  blob.includes('"pending"'), false);
const restored = chat.parsePrefChatState(blob, fp);
check('P1 leave-and-return restores the mode', restored && restored.mode, 'model');
check('P1 leave-and-return restores both turns',
  restored && restored.turns.length, 2);
check('P1 first turn reply survives the return',
  restored && restored.turns[0].reply && restored.turns[0].reply.extracted.countries, ['CH']);
check('P1 first turn still counts as model reply',
  restored && chat.isModelPrefReply(restored.turns[0].reply), true);
check('P1 pending turn restores as offline, not pending',
  restored && restored.turns[1].offline, true);
check('P1 pending turn has no reply after return',
  restored && restored.turns[1].reply, null);
check('P1 next question survives the return',
  restored && restored.serverNext, 'climate');
check('P1 WHY follow-up survives the return',
  restored && restored.awaitingReason, { countries: ['CH'], note: '那边环境优美' });
// A blob for another profile is never resurrected: cleared data,
// a restart elsewhere, a stale completed chat after a reset.
check('P1 cleared profile discards the blob',
  chat.parsePrefChatState(blob, chat.prefChatFingerprint(emptyProfile)), null);
check('P1 corrupt blob is discarded',
  chat.parsePrefChatState('{not json', fp), null);
check('P1 wrong version is discarded',
  chat.parsePrefChatState(JSON.stringify({ ...JSON.parse(blob), version: 0 }), fp), null);
check('P1 empty storage is discarded',
  chat.parsePrefChatState(null, fp), null);
check('P1 tampered fingerprint is discarded',
  chat.parsePrefChatState(JSON.stringify({ ...JSON.parse(blob), fingerprint: 'other' }), fp), null);
process.exit(fail ? 1 : 0);
"""


def test_r14_pref_chat_why_persist_note_city(tmp_path):
    """Round 14: WHY fires from the first reply, progress survives
    leave-and-return, the note stays one summary atom, and the
    confirm bubble localises the city."""
    outdir = tmp_path / "r14_pref"
    fe = ROOT / "frontend"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/preferences.ts", "src/lib/chat.ts",
         "src/lib/types.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(fe), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r14_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(fe))), encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"],
           "NODE_PATH": str(fe / "node_modules")}
    node = subprocess.run(
        ["node", str(harness), json.dumps(_AUDIT_PREFS, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
