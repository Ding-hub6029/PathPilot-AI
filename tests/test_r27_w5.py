"""Round 27 W5 — climate wording alignment (re-test 21).

(1) FIXED — the wizard guide line ``wizard.chatOpClimateNoMatch``
led with the negative ("no cool-climate city in your chosen
countries: Zurich (four-season), Lausanne (four-season)") while the
chat's own climate wording states the cities' actual classes first
("Zurich/Lausanne are four-season") — the same fact in two wordings
that read as contradictory. The guide line now mirrors the chat
(backend ``_DEVIL_T`` climate template, backend/ai/chat.py): list
the chosen countries' cities with their actual classes, then the
no-match, then the preference-only sentence (ordering, not
eligibility). Pure locale-string change in frontend/messages/*.json
— same ``{want}`` / ``{cities}`` vars, no code change in
PrefChat.tsx (its opinion('climate') no-match branch is unchanged).

(2) NOT FIXED — devil content mismatch, carried as a residual (see
~/workspace/r27-decisions-w5.md for the measured evidence). No test
pins the devil output here: pinning it would enshrine the mismatch
(same call as Round 26 W4).
"""
from __future__ import annotations

import json
from pathlib import Path

from ai.chat import _DEVIL_T

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]
KEY = "wizard.chatOpClimateNoMatch"

# The preference-only sentence, per locale — verbatim from the
# backend devil climate template (_DEVIL_T[loc]["climate"]): climate
# is a preference only, ordering not eligibility. The guide line must
# carry the SAME sentence so the two wordings cannot drift apart.
PREFERENCE_ONLY = {
    "en": "Climate is only a preference — it never decides eligibility, it only orders results.",
    "zh-CN": "气候只是偏好，不影响资格，只影响排序。",
    "es": "El clima es solo una preferencia: nunca decide la elegibilidad, solo ordena los resultados.",
    "fr": "Le climat n'est qu'une préférence : il ne décide jamais de l'éligibilité, il ne fait qu'ordonner les résultats.",
    "pt-BR": "O clima é só uma preferência: nunca decide a elegibilidade, só ordena os resultados.",
    "ar": "المناخ مجرد تفضيل — لا يقرر الأهلية أبدًا، بل يرتّب النتائج فقط.",
}

# The negative ("no {want}-class city") marker per locale: it must
# come AFTER the {cities} list, which states the actual classes.
NEGATIVE_MARKER = {
    "en": "none has",
    "zh-CN": "其中没有",
    "es": "ninguna tiene",
    "fr": "aucune n'a",
    "pt-BR": "nenhuma tem",
    "ar": "ولا مدينة",
}


def _messages(locale: str) -> dict:
    return json.loads(
        (ROOT / "frontend" / "messages" / f"{locale}.json").read_text(
            encoding="utf-8"))


def test_key_present_with_same_vars_in_all_locales():
    """The key exists in all 6 locale files with the same two vars
    the PrefChat no-match branch passes (want, cities)."""
    for loc in LOCALES:
        text = _messages(loc)[KEY]
        assert "{want}" in text, loc
        assert "{cities}" in text, loc


def test_preference_only_sentence_matches_backend_devil_template():
    """The guide line carries the backend devil template's own
    preference-only sentence, verbatim, in every locale — and the
    backend sentence is asserted to still be there, so either side
    drifting fails this test."""
    for loc in LOCALES:
        sentence = PREFERENCE_ONLY[loc]
        assert sentence in _DEVIL_T[loc]["climate"], loc
        assert sentence in _messages(loc)[KEY], loc


def test_cities_stated_before_the_negative():
    """Order, not just content: the cities (with their actual
    classes) are stated BEFORE the no-match negative, so the line
    reads as 'these cities are X; none is the wanted class' — the
    chat's order — instead of leading with the contradiction-looking
    negative."""
    for loc in LOCALES:
        text = _messages(loc)[KEY]
        assert text.index("{cities}") < text.index(NEGATIVE_MARKER[loc]), loc


def test_old_leading_negative_is_gone():
    """The old zh/en lead-ins that read as contradicting the chat's
    'four-season' statement are gone."""
    assert not _messages("zh-CN")[KEY].startswith("你选的国家里没有")
    assert not _messages("en")[KEY].startswith("None of the cities")


def test_rendered_zh_example():
    """The exact re-test 21 case, rendered: the climate is stated
    first, then the no-cool statement, then preference-only."""
    rendered = _messages("zh-CN")[KEY].format(
        want="凉爽", cities="苏黎世（四季分明）、洛桑（四季分明）")
    assert rendered == (
        "你选的国家里有这些城市：苏黎世（四季分明）、洛桑（四季分明），"
        "其中没有凉爽气候的城市。气候只是偏好，不影响资格，只影响排序。"
        "要换个气候偏好，或者换个国家看看吗？")


def test_rendered_en_example():
    rendered = _messages("en")[KEY].format(
        want="cool",
        cities="Zurich (Four seasons), Lausanne (Four seasons)")
    assert rendered == (
        "The verified data lists these cities in your chosen countries: "
        "Zurich (Four seasons), Lausanne (Four seasons) — none has a "
        "cool climate. Climate is only a preference — it never decides "
        "eligibility, it only orders results. Want to try a different "
        "climate, or another country?")


def test_prefchat_still_wires_the_key_with_want_and_cities():
    """Source pin: the string change must not detach from the code
    that renders it — PrefChat opinion('climate') still returns this
    key with the same vars."""
    src = (ROOT / "frontend" / "src" / "components"
           / "PrefChat.tsx").read_text(encoding="utf-8")
    assert "'wizard.chatOpClimateNoMatch'" in src
    assert "want: climateName" in src
    assert "cities: desc" in src
