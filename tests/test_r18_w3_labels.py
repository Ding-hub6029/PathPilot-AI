"""Round 18, worker W3 — labels, copy, pet repetition (rendering only).

Task 1 (P1/P2): a devil reply carried BOTH "AI 生成" (devil.boundary,
rendered unconditionally at the top of the bubble) and "离线模式"
(pet.offline, prepended to the body of an offline template turn) —
self-contradictory. Fix: an offline devil turn wears the offline
boundary (devil.offlineBoundary, no AI-generation claim); a live
model devil turn keeps devil.boundary.

Task 2 (P2): the preference summary appeared 3x on /results — the
results page itself, the pet title-bar strip (pet.prefSaved) and the
pet.greetingKnown opening bubble. Fix (CompassPet only): the strip
is suppressed on /results and the opening bubble uses the short
acknowledgement (pet.greetingKnownShort, no {prefs}) there, so the
page shows the summary exactly once (its own copy).

Task 3 (P2): climate-classification wording. The devil climate line
said "no cool-class city" while Swiss schools still lead the
recommendations. Judgement (see /tmp/r18-w3-decisions.md): the facts
are right and flagging the clash IS the devil's job, but the line
overstated it — the engine rates cool-vs-four_seasons as "neutral"
(a four-season city does have cold winters) and climate is a
preference that only orders results, never an eligibility rule
(backend/domain/climate.py). Fix: the template now says so in all
6 locales; no climate data changed, no cool Swiss city invented.

Task 4 (P2): English residuals in the programme-detail minimums
area, traced (see /tmp/r18-w3-decisions.md):
- "Main teaching language of the Bachelor's programme; single
  courses may be taught in English." is an official-source excerpt
  (language_of_instruction.note, eth-cs/cse-bsc-2027, ETH source
  URL) — correctly kept verbatim with lang="en" and localised
  surrounding labels (RuleRow LanguageOfInstructionLine). Not
  translated, by design.
- "3 years (180 credits)" is the data duration field for the same
  two ETH programmes; formatDuration only localises durations it
  can parse or that carry a program.duration.<id> key, so the raw
  English fell through. Fix: per-programme duration keys in all
  6 locales (the established pattern — cf. nus-bcomp-cs-2027).
- "No IELTS component minimum published" is a hardcoded English
  fallback in frontend/src/lib/api.ts:466 and
  backend/app/adapter.py:591,648 — outside this worker's files, so
  NOT fixed here; flagged to the coordinator in the decision file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ai.chat import _DEVIL_T, devil_conflict_line  # noqa: E402

LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]
PET = ROOT / "frontend" / "src" / "components" / "CompassPet.tsx"
FORMAT = ROOT / "frontend" / "src" / "lib" / "format.ts"


def _messages(locale: str) -> dict:
    return json.loads((ROOT / "frontend" / "messages" / f"{locale}.json").read_text(encoding="utf-8"))


def _pet_src() -> str:
    return PET.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Task 1 — one honest label per devil reply
# ---------------------------------------------------------------------------

def test_offline_boundary_key_exists_in_all_locales():
    for locale in LOCALES:
        assert "devil.offlineBoundary" in _messages(locale), locale


def test_offline_boundary_never_claims_ai_generation():
    # No "AI" claim in any locale (covers "AI 生成", "AI-generated",
    # "Generado por IA", "Généré par IA", "مولّد بالذكاء الاصطناعي").
    for locale in LOCALES:
        value = _messages(locale)["devil.offlineBoundary"]
        assert "AI" not in value and "IA" not in value, (locale, value)
        assert "生成" not in value and "generated" not in value.lower(), (locale, value)
        # Still a devil boundary: a view, not a verdict; still says
        # the answer is a template / for reference only.
        lowered = value.lower()
        assert ("定论" in value or "verdict" in lowered
                or "veredicto" in lowered or "حكم" in value), (locale, value)


def test_live_boundary_still_claims_ai_generation():
    # The live path is unchanged: a model devil reply still says so.
    # (Arabic has no Latin "AI"/"IA" — it says الذكاء الاصطناعي.)
    markers = {"en": "AI", "zh-CN": "AI", "es": "IA", "fr": "IA",
               "pt-BR": "IA", "ar": "الذكاء الاصطناعي"}
    for locale in LOCALES:
        value = _messages(locale)["devil.boundary"]
        assert markers[locale] in value, (locale, value)


def test_pet_renders_offline_boundary_for_offline_devil_turns():
    src = _pet_src()
    assert "devilOffline: turn.devil && turn.offline" in src
    assert "t(rendered.devilOffline ? 'devil.offlineBoundary' : 'devil.boundary')" in src
    # The offline flag is part of the render contract, not a stray prop.
    assert "devilOffline?: boolean" in src


# ---------------------------------------------------------------------------
# Task 2 — no triple preference restatement on /results
# ---------------------------------------------------------------------------

def test_greeting_short_key_exists_in_all_locales_and_has_no_prefs():
    for locale in LOCALES:
        value = _messages(locale)["pet.greetingKnownShort"]
        assert "{prefs}" not in value, (locale, value)
        assert value.strip(), locale


def test_pet_suppresses_pref_strip_on_results():
    src = _pet_src()
    assert "hasPreferences(profile) && pathname !== '/results' && (" in src


def test_pet_uses_short_greeting_on_results():
    src = _pet_src()
    assert "pathname === '/results' ? t('pet.greetingKnownShort') : tf('pet.greetingKnown'" in src


def test_full_greeting_kept_off_results():
    # Elsewhere the opening bubble still states the full summary once.
    src = _pet_src()
    assert "tf('pet.greetingKnown', { prefs: prefSummary(profile, t) })" in src


# ---------------------------------------------------------------------------
# Task 3 — climate wording: soft preference, facts unchanged
# ---------------------------------------------------------------------------

AUDIT_CONFLICT = {
    "kind": "climate", "country": "CH", "wanted": "cool",
    "cities": [("Zurich", "four_seasons", 14), ("Lausanne", "four_seasons", 11)],
    "count_difference": 3,
}

_SOFT_MARKERS = {
    "en": "only orders results",
    "zh-CN": "只影响排序",
    "es": "solo ordena los resultados",
    "fr": "ne fait qu'ordonner les résultats",
    "pt-BR": "só ordena os resultados",
    "ar": "يرتّب النتائج فقط",
}


def test_climate_template_states_soft_preference_in_all_locales():
    for locale in LOCALES:
        assert _SOFT_MARKERS[locale] in _DEVIL_T[locale]["climate"], locale


def test_climate_template_keeps_placeholders_and_facts():
    # City names are localised per locale (苏黎世/洛桑 in zh-CN).
    city_names = {"en": ("Zurich", "Lausanne"), "zh-CN": ("苏黎世", "洛桑"),
                  "es": ("Zurich", "Lausanne"), "fr": ("Zurich", "Lausanne"),
                  "pt-BR": ("Zurich", "Lausanne"), "ar": ("Zurich", "Lausanne")}
    for locale in LOCALES:
        line = devil_conflict_line(AUDIT_CONFLICT, locale)
        for name in city_names[locale]:
            assert name in line, (locale, line)
        assert "14" in line and "11" in line, (locale, line)
        # Engine-computed difference still stated (Round 17).
        assert "3" in line, (locale, line)
        # Verified classes still named (localised per locale).
        class_markers = {"en": "four-season", "zh-CN": "四季分明",
                         "es": "cuatro estaciones", "fr": "quatre saisons",
                         "pt-BR": "quatro estações", "ar": "أربعة فصول"}
        assert class_markers[locale] in line, (locale, line)


def test_climate_template_still_uses_template_placeholders():
    for locale in LOCALES:
        raw = _DEVIL_T[locale]["climate"]
        assert "{prefix}" in raw and "{wanted}" in raw and "{country}" in raw and "{cities}" in raw, locale


# ---------------------------------------------------------------------------
# Task 4 — ETH duration localised via per-programme keys
# ---------------------------------------------------------------------------

def test_eth_duration_keys_exist_in_all_locales():
    for locale in LOCALES:
        msgs = _messages(locale)
        for pid in ("eth-cs-bsc-2027", "eth-cse-bsc-2027"):
            assert f"program.duration.{pid}" in msgs, (locale, pid)


def test_eth_duration_is_localised_not_raw_english():
    for locale in LOCALES:
        msgs = _messages(locale)
        for pid in ("eth-cs-bsc-2027", "eth-cse-bsc-2027"):
            value = msgs[f"program.duration.{pid}"]
            assert "180" in value, (locale, pid, value)
            assert "3" in value, (locale, pid, value)
            if locale != "en":
                assert value != "3 years (180 credits)", (locale, pid, value)


def test_format_duration_prefers_per_programme_key():
    # The established extension point: a program.duration.<id> key
    # wins over the generic parser (which cannot parse "(180 credits)").
    src = FORMAT.read_text(encoding="utf-8")
    assert "program.duration.${program.id}" in src
