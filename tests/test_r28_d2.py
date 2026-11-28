"""Round 28 D2 — guide-area climate wording + verified-cities line
(re-test 22 items (e) FAIL and (d)).

Re-test evidence (live browser, gateway offline the whole run): the
guide-area climate answer read, in Chinese, "AI 暂时无法连接，下面的
引导问题还能继续用，我只会给你标明了"离线"的回答。已核实的数据里有这些
城市：苏黎世（四季分明，14 个项目，全部学位/方向）、洛桑（四季分明，
11 个项目，全部学位/方向）。可以开始资格检查，逐项核对你的背景。" —
in the English UI only the first sentence localised; the cities line
and last sentence stayed Chinese. It had NO "no cool city" sentence
and NO "climate is only a preference" sentence, and the same generic
offline template repeated verbatim 6 times after preference answers.
The chat (devil's advocate) version of the same fact IS complete in
both locales.

Root cause (verified in code before changing anything): Round 27 W5
reworded the FRONTEND string ``wizard.chatOpClimateNoMatch``
(rendered by PrefChat ``opinion('climate')`` in the GUIDED queue),
but the model-led chat path — which the re-tester used — never
renders ``opinion()``: its reply comes from the BACKEND's
``_fallback_result`` (``backend/ai/pref_chat.py``), whose lines are
template lines with the first line replaced by the deterministic
cities line (``evidence_cities_line``) when climate evidence exists.
There was no climate-specific sentence anywhere in that composition.
And the cities line is a stored backend string in the request locale,
so it cannot follow a language switch (same class as the D1 defect,
but it needs structured data, not a reverse map — the frontend cannot
reconstruct city classes/counts from the stored ``reply.sources``,
which carry only ``{id, url, title}``).

Fix:
- backend: ``evidence_cities_items(sources)`` factors the parsing
  inside ``evidence_cities_line`` into structured items
  (``[{city, climate, count}]``); ``_fallback_result`` attaches
  ``evidence_cities`` + ``climate_wanted`` ONLY when the cities line
  was actually placed into ``lines[0]`` — fallback (offline) results
  only, never model replies. The cities-line insertion is now scoped
  to climate-relevant turns (message states a climate class, the turn
  just answered climate, or climate is the next question), so the
  identical block no longer repeats after every later answer.
- frontend: NEW pure helper ``localisedFallbackLines`` in
  ``frontend/src/lib/prefFallbackLines.ts`` re-renders the stored
  prefix lines ``lines[0..1]`` in the CURRENT locale from the
  structured block — cities line via 2 NEW locale keys
  (``wizard.prefFallbackCitiesLine`` / ``wizard.prefFallbackCityItem``,
  wording copied verbatim from the backend's ``_EVIDENCE_CITIES_LINES``
  / ``_CITY_ITEM`` tables), plus the existing
  ``wizard.chatOpClimateNoMatch`` sentence in the no-match case.
  It returns null when the reply has no block, so old snapshots and
  model replies keep their stored lines verbatim. The trailing
  question line is NOT this helper's — D1 re-localises it from the
  stored ``next_question``.

Run from the project root:
    .venv/bin/pytest tests/test_r28_d2.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
BACKEND = ROOT / "backend"
LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]

# The re-test 22 turn, verbatim: cold (no-key) pref_answer for "凉爽"
# with Switzerland known. The stored zh lines below are the
# pre-change output, byte for byte — the backend change must not alter
# `lines` on a climate-relevant turn.
_ZH_LINES = [
    "已核实的数据里有这些城市：苏黎世（四季分明，14 个项目，全部学位/方向）、洛桑（四季分明，11 个项目，全部学位/方向）。",
    "可以开始资格检查，逐项核对你的背景。",
    "你想住在什么样的地方——大城市、小城市、校园，还是安静的小镇？",
]
_EXPECTED_ITEMS = [
    {"city": "Zurich", "climate": "four_seasons", "count": 14},
    {"city": "Lausanne", "climate": "four_seasons", "count": 11},
]


def _no_key_provider(monkeypatch):
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    from ai.provider import ProviderAdapter
    provider = ProviderAdapter()
    assert not provider.available
    return provider


def test_cold_climate_turn_carries_structured_block(monkeypatch):
    """The re-test turn, cold: the fallback result carries
    ``evidence_cities`` + ``climate_wanted`` alongside the unchanged
    lines — the structured evidence the frontend re-renders from."""
    import sys
    sys.path.insert(0, str(BACKEND))
    from ai.pref_chat import pref_answer
    r = pref_answer("凉爽", "zh-CN", known={"countries": ["CH"]},
                    provider=_no_key_provider(monkeypatch))
    assert r["ai_status"] == "unavailable"
    assert r["evidence_cities"] == _EXPECTED_ITEMS
    assert r["climate_wanted"] == "cool"
    assert r["extracted"] == {"climate": "cool"}
    assert r["next_question"] == "environment"


def test_cold_climate_turn_lines_byte_identical(monkeypatch):
    """The backend change must not alter the rendered fallback lines
    on a climate-relevant turn: byte-identical to the pre-change
    (re-test 22) output."""
    import sys
    sys.path.insert(0, str(BACKEND))
    from ai.pref_chat import pref_answer
    r = pref_answer("凉爽", "zh-CN", known={"countries": ["CH"]},
                    provider=_no_key_provider(monkeypatch))
    assert r["lines"] == _ZH_LINES


def test_turn_with_no_climate_sources_carries_no_block(monkeypatch):
    """A turn with no climate sources (bare greeting, no countries
    known) carries neither new field — the helper then returns null
    and the stored lines render verbatim."""
    import sys
    sys.path.insert(0, str(BACKEND))
    from ai.pref_chat import pref_answer
    r = pref_answer("你好", "zh-CN", known={},
                    provider=_no_key_provider(monkeypatch))
    assert "evidence_cities" not in r
    assert "climate_wanted" not in r


def test_non_climate_turn_does_not_repeat_cities_block(monkeypatch):
    """Scoping (re-test 22's 6-times repetition): once climate is
    already known, a later non-climate answer ("大学城" -> campus)
    no longer re-places the cities line — the generic unknown line
    stays and no block is attached."""
    import sys
    sys.path.insert(0, str(BACKEND))
    from ai.pref_chat import pref_answer
    r = pref_answer("大学城", "zh-CN",
                    known={"countries": ["CH"], "climate": "cool"},
                    provider=_no_key_provider(monkeypatch))
    assert r["ai_status"] == "unavailable"
    assert "evidence_cities" not in r
    assert "climate_wanted" not in r
    assert r["lines"][0] == "这个我从已核实的数据里查不到，不知道。"
    assert r["next_question"] == "city"


def test_countries_turn_before_climate_still_places_cities_line(monkeypatch):
    """Scoping boundary: climate IS the next question on the turn
    that first names Switzerland, so the cities line is still placed
    there (evidence in hand must not be erased) — with the block."""
    import sys
    sys.path.insert(0, str(BACKEND))
    from ai.pref_chat import pref_answer
    r = pref_answer("我想去瑞士，因为那边环境优美", "zh-CN", known={},
                    provider=_no_key_provider(monkeypatch))
    assert r["ai_status"] == "unavailable"
    assert r["evidence_cities"] == _EXPECTED_ITEMS
    assert r["climate_wanted"] is None
    assert r["next_question"] == "climate"
    assert r["lines"][0] == _ZH_LINES[0]


def test_evidence_cities_items_matches_rendered_line():
    """Source pin: the structured items are the same parsing as the
    rendered line — same items, same order, same counts — and the
    rendered line itself is unchanged by the refactor."""
    import sys
    sys.path.insert(0, str(BACKEND))
    from ai.chat import (_climate_evidence, evidence_cities_items,
                        evidence_cities_line)
    sources, _ = _climate_evidence("cool", countries=["CH"])
    assert evidence_cities_items(sources) == _EXPECTED_ITEMS
    assert evidence_cities_items([]) == []
    assert evidence_cities_line(sources, "zh-CN") == _ZH_LINES[0]
    assert evidence_cities_line(sources, "en") == (
        "The verified data lists these cities: "
        "Zurich (four-season, 14 programmes, all levels/fields), "
        "Lausanne (four-season, 11 programmes, all levels/fields).")
    assert evidence_cities_line([], "zh-CN") is None


def test_new_locale_keys_copy_backend_wording_verbatim():
    """The 2 new keys exist in all 6 locales, and their wording is
    the backend's ``_EVIDENCE_CITIES_LINES`` / ``_CITY_ITEM`` tables
    verbatim — only the placeholder names are the frontend's
    (``{cls}`` -> ``{climate}``, ``{n}`` -> ``{count}``). No invented
    translations: the frontend keys are a copy of the backend's
    existing per-locale wording."""
    import sys
    sys.path.insert(0, str(BACKEND))
    from ai.chat import _CITY_ITEM, _EVIDENCE_CITIES_LINES
    for loc in LOCALES:
        msgs = json.loads(
            (FE / "messages" / f"{loc}.json").read_text(encoding="utf-8"))
        assert msgs["wizard.prefFallbackCitiesLine"] == _EVIDENCE_CITIES_LINES[loc], loc
        assert msgs["wizard.prefFallbackCityItem"] == (
            _CITY_ITEM[loc].replace("{cls}", "{climate}").replace("{n}", "{count}")), loc
        assert "{cities}" in msgs["wizard.prefFallbackCitiesLine"]
        for var in ("{city}", "{climate}", "{count}"):
            assert var in msgs["wizard.prefFallbackCityItem"], (loc, var)


# --- Frontend node harness -------------------------------------------
#
# The stored re-test reply (zh, as the backend returned it) rendered
# in en: the cities line in English with counts + the
# chatOpClimateNoMatch sentence in English (no-match case). The match
# case reuses the same real items with wanted='four_seasons' — no
# invented data. `want` is the climate label, exactly as the guided
# opinion('climate') passes it (en "Cool", zh "凉爽").

_STORED_ZH_REPLY = {
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
    "evidence_cities": _EXPECTED_ITEMS,
    "climate_wanted": "cool",
}

# (name, reply, locale, expected helper return)
_HELPER_CASES = [
    ("en no-match: cities line in English with counts + no-match sentence",
     _STORED_ZH_REPLY, "en",
     ["The verified data lists these cities: "
      "Zurich (Four seasons, 14 programmes, all levels/fields), "
      "Lausanne (Four seasons, 11 programmes, all levels/fields).",
      "The verified data lists these cities in your chosen countries: "
      "Zurich (Four seasons), Lausanne (Four seasons) — none has a "
      "Cool climate. Climate is only a preference — it never decides "
      "eligibility, it only orders results. Want to try a different "
      "climate, or another country?"]),
    ("zh no-match: re-rendered zh equals the stored zh prefix lines",
     _STORED_ZH_REPLY, "zh-CN",
     ["已核实的数据里有这些城市：苏黎世（四季分明，14 个项目，全部学位/方向）、洛桑（四季分明，11 个项目，全部学位/方向）。",
      "你选的国家里有这些城市：苏黎世（四季分明）、洛桑（四季分明），"
      "其中没有凉爽气候的城市。气候只是偏好，不影响资格，只影响排序。"
      "要换个气候偏好，或者换个国家看看吗？"]),
    ("en match (wanted four_seasons): only the cities line",
     {**_STORED_ZH_REPLY, "climate_wanted": "four_seasons"}, "en",
     ["The verified data lists these cities: "
      "Zurich (Four seasons, 14 programmes, all levels/fields), "
      "Lausanne (Four seasons, 11 programmes, all levels/fields)."]),
    ("no wanted class: only the cities line",
     {**_STORED_ZH_REPLY, "climate_wanted": None}, "en",
     ["The verified data lists these cities: "
      "Zurich (Four seasons, 14 programmes, all levels/fields), "
      "Lausanne (Four seasons, 11 programmes, all levels/fields)."]),
    ("reply without the block: null (old snapshot keeps stored lines)",
     {k: v for k, v in _STORED_ZH_REPLY.items()
      if k not in ("evidence_cities", "climate_wanted")}, "en", None),
    ("model reply (available, no block): null",
     {**_STORED_ZH_REPLY, "ai_status": "available",
      "evidence_cities": None, "climate_wanted": None}, "en", None),
    ("model reply must never be re-rendered even if a block were present",
     {**_STORED_ZH_REPLY, "ai_status": "available"}, "en", None),
    ("empty evidence_cities: null",
     {**_STORED_ZH_REPLY, "evidence_cities": []}, "en", None),
    ("unknown climate_wanted value: treated as unset, only cities line",
     {**_STORED_ZH_REPLY, "climate_wanted": "arctic"}, "en",
     ["The verified data lists these cities: "
      "Zurich (Four seasons, 14 programmes, all levels/fields), "
      "Lausanne (Four seasons, 11 programmes, all levels/fields)."]),
]

_NODE_HARNESS = r"""
const { localisedFallbackLines } = require(OUT + '/prefFallbackLines.js');
const en = require(FE + '/messages/en.json');
const cases = JSON.parse(process.argv[2]);
let fail = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL ' + name + '\n  got  ' + g + '\n  want ' + w); fail++; }
  else console.log('PASS ' + name);
};
// next-intl-style translate with vars: {x} interpolation, plain
// lookup falls back to the key (same contract the app's tf has).
const tFor = (loc) => {
  const msgs = require(FE + '/messages/' + loc + '.json');
  return (key, vars) => {
    let s = msgs[key] ?? en[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.split('{' + k + '}').join(String(v));
    return s;
  };
};
for (const [name, reply, loc, want] of cases) {
  check(name, localisedFallbackLines(reply, tFor(loc), loc), want);
  // Boundary: the helper returns ONLY the prefix replacement — it
  // never contains the trailing question line (D1 owns that line).
  const got = localisedFallbackLines(reply, tFor(loc), loc);
  if (got && reply.lines && reply.lines.length > 2) {
    check(name + ' [question line untouched]',
      got.includes(reply.lines[2]), false);
  }
}
// Caller contract: prefix replacement + stored tail, verbatim.
const stored = cases[0][1];
const prefix = localisedFallbackLines(stored, tFor('en'), 'en');
check('caller contract: prefix + stored tail keeps the question line',
  [...(prefix ?? []), ...stored.lines.slice(2)],
  [prefix[0], prefix[1], stored.lines[2]]);
if (fail) { console.log(fail + ' FAILURES'); process.exit(1); }
console.log('ALL D2 HARNESS CASES PASS');
"""


def test_r28_d2_frontend_helper(tmp_path):
    """Node harness over compiled prefFallbackLines.ts: the stored zh
    fallback reply re-renders in en (cities line + no-match sentence),
    the match case returns only the cities line, and replies without
    the block / model replies return null."""
    outdir = tmp_path / "r28d2"
    res = subprocess.run(
        ["npx", "tsc", "src/lib/prefFallbackLines.ts",
         "--module", "commonjs", "--target", "es2020", "--jsx", "react-jsx",
         "--outDir", str(outdir), "--skipLibCheck", "--esModuleInterop",
         "--resolveJsonModule"],
        cwd=str(FE), capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, res.stdout + res.stderr
    harness = tmp_path / "r28d2_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("OUT", repr(str(outdir)))
        .replace("FE", repr(str(FE))), encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "NODE_PATH": str(FE / "node_modules")}
    node = subprocess.run(
        ["node", str(harness), json.dumps(_HELPER_CASES, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120, env=env)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout


def test_r28_d2_router_passes_block_through():
    """Source pin: the pref-chat endpoint returns ``pref_answer``'s
    dict as-is (no field whitelist), so the new block reaches the
    frontend — and the frontend's persist path stores the reply
    whole, so no whitelist drops it there either."""
    router = (ROOT / "backend" / "app" / "router_chat.py").read_text(encoding="utf-8")
    assert "return await asyncio.to_thread(\n        pref_answer, req.message, req.locale," in router
    chat_ts = (FE / "src" / "lib" / "chat.ts").read_text(encoding="utf-8")
    assert "evidence_cities?:" in chat_ts
    assert "climate_wanted?:" in chat_ts
    # serializePrefChatState stores the reply object whole.
    assert "reply: x.reply," in chat_ts
    # parsePrefChatState passes the stored reply through whole.
    assert "reply: (t.reply && typeof t.reply === 'object' ? t.reply : null) as PrefChatReply | null," in chat_ts
    # PrefChat.tsx is untouched by this worker.
    assert "localisedFallbackLines" not in (
        ROOT / "frontend" / "src" / "components" / "PrefChat.tsx").read_text(encoding="utf-8")
