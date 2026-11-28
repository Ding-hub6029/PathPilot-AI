"""Model-led preference conversation for PrefChat (Day 3, round 7).

The user tested the round-6 PrefChat and caught three real bugs: city
chips were a hardcoded London/Singapore/Boston/Toronto list even after
he chose Switzerland; typing "我想去瑞士，因为那边环境优美" recorded
just "瑞士", dropping the reason; and the climate opinion cited
Edinburgh for a Switzerland user. This module replaces the fixed
8-question queue with a model-led conversation:

- the model extracts, from THIS message only, the preferences it
  states (``extracted``) — including the user's reason in their own
  words (``note``) — and picks the single most useful still-missing
  preference (``next_question``);
- extraction is validated server-side and never trusted: countries
  must be ISO codes present in the verified catalogue, enums must be
  one of the allowed values, salary needs both a positive amount and
  a GBP/SGD/USD/CHF currency, anything else is dropped, never clamped or
  converted;
- climate evidence is scoped to the known countries (see
  ``ai.chat._climate_evidence``): when the chosen country has no city
  of the wanted class, the catalogue still carries that country's own
  cities with their ACTUAL classes, so the model says honestly that
  e.g. Switzerland has no cool-class city (Zurich and Lausanne are
  both four-season) instead of silently substituting Edinburgh;
- grounding is exactly the ``ai.chat`` chain: the same retrieval, the
  same ``check_model_output`` validation (citation id whitelist,
  numeric cross-check, no admission probabilities/guarantees, no raw
  URLs), one model call per turn and NO repair retry (round 10),
  then the template fallback with the deterministic extraction;
- the personal-data guard runs FIRST (reused from ``ai.assistant``);
  a message that looks like it contains a name/phone/email is refused
  with the fixed line — the value is never echoed and never stored;
- when the provider is unavailable or the model output fails
  validation: ``ai_status="unavailable"``, the template fallback
  lines, a DETERMINISTIC extraction (round 10: the country named in
  the message + the user's reason in their own words, matched
  without a model — so "我想去瑞士，因为那边环境优美" is recorded
  even while the gateway is down, instead of losing the sentence),
  and ``next_question`` computed deterministically as the first
  still-missing preference in the default order, AFTER applying
  that extraction.

The next question is asked as the last line of ``lines`` — EXCEPT when
the turn carries a WHY follow-up (see ``why_followup``): then the
turn's question IS the WHY, the next-question line is withheld from
``lines`` (Round 16: the climate question used to render ahead of the
WHY, so the user was asked climate before the reason was explored),
and ``next_question`` still names the deferred preference — the
frontend asks it after the WHY is answered or skipped. ``done`` is
True exactly when all 8 preferences are known (merged known +
extracted).

Round 29 W2 (E4): a message that answers the first still-missing
preference — a guided answer, not a question — no longer attempts
the model at all: it takes the deterministic route (the
deterministic extraction + the template fallback) in engine time,
in every gateway state, and returns ``ai_status="unavailable"``.
The model is attempted only for non-guided turns (a free question
mid-flow, a greeting, an answer the deterministic extraction cannot
read). Round 29 W2 (E3): on a climate no-match turn the model
reply's lines are post-validated to carry the cities line with
programme counts and the no-match + preference-only sentences
(``_pin_climate_no_match``), and the result carries ``climate_turn``
(True exactly on a climate turn) plus the R28 D2 structured block
(``evidence_cities`` + ``climate_wanted``) on a climate turn on
both paths — the frontend's dedupe signal for the cities line,
which is still placed on the countries turn as well.

Nothing is logged or stored: no message, history or key ever leaves
this call except inside the provider request itself.
"""
from __future__ import annotations

import json
import logging
import re
import time

from ai.assistant import (LOCALES, _t, ask as assistant_ask,
                          check_no_forbidden, contains_personal_data)
from ai.chat import (_CLASS_WORDS, _CLIMATE_PREFERENCE_ONLY,
                     _clean_history, _detect_climate_class,
                     _detect_country, _country_names, _evidence_texts,
                     _parse_model_json, _render_lines,
                     _resolve_evidence_url, _retrieve,
                     _validate_chat_payload, climate_no_match_line,
                     country_evidence_line, evidence_cities_items,
                     evidence_cities_line, localised_city_name)
from ai.grounding import Source
from ai.prompts import PROMPT_VERSION, pref_chat_system
from ai.provider import ProviderAdapter, ProviderError
from app.ai_status_cache import model_skip_cached
from app.data import EXPANSION_PROGRAMS, PROGRAMS, RANKINGS

# Failure-class diagnostics only (no message, history, extracted data
# or key material ever reaches a log line): the 2026-11-26 live
# failures were diagnosed from timings + local validation, but a
# recurrence needs the failure class visible in the Render log.
logger = logging.getLogger(__name__)

# The 8 preferences, in default ask order.
PREF_ORDER: tuple[str, ...] = (
    "countries", "climate", "environment", "city",
    "afterGrad", "salary", "pressure", "teaching",
)

_CLIMATE_VALUES = ("warm", "cool", "four_seasons", "mild")
_ENVIRONMENT_VALUES = ("big_city", "small_city", "campus", "quiet_town")
_AFTER_GRAD_VALUES = ("stay", "return_home", "hometown", "undecided")
_PRESSURE_VALUES = ("low", "medium", "high")
_TEACHING_VALUES = ("lecture", "seminar", "hands_on")
_SALARY_CURRENCIES = ("GBP", "SGD", "USD", "CHF")

_ENUM_FIELDS: dict[str, tuple[str, ...]] = {
    "climate": _CLIMATE_VALUES,
    "environment": _ENVIRONMENT_VALUES,
    "afterGrad": _AFTER_GRAD_VALUES,
    "pressure": _PRESSURE_VALUES,
    "teaching": _TEACHING_VALUES,
}

# ISO country codes present in the verified catalogue: any code a
# programme (v2 or expansion) or a rankings institution carries.
KNOWN_COUNTRIES: frozenset[str] = frozenset(
    {p.get("country") for p in list(PROGRAMS.values())
     + list(EXPANSION_PROGRAMS.values()) if p.get("country")}
    | {i.get("country") for i in RANKINGS.get("institutions", [])
       if i.get("country")})

NOTE_MAX_CHARS = 200

# Fixed localised next-question lines (one per preference, six
# locales). The server appends one as the last line of ``lines`` so
# the reply always ends by asking the next question, in the user's
# language, without trusting the model to do it.
_NEXT_QUESTION_LINES: dict[str, dict[str, str]] = {
    "countries": {
        "en": "Which country or countries would you like to study in?",
        "zh-CN": "你想去哪个国家留学？",
        "es": "¿En qué país o países te gustaría estudiar?",
        "fr": "Dans quel(s) pays aimerais-tu étudier ?",
        "pt-BR": "Em qual país ou países você gostaria de estudar?",
        "ar": "في أي دولة أو دول تريد الدراسة؟",
    },
    "climate": {
        "en": "What kind of climate do you prefer — warm, cool, four seasons, or mild?",
        "zh-CN": "你喜欢什么样的气候——暖和、凉爽、四季分明还是温和？",
        "es": "¿Qué clima prefieres: cálido, frío, de cuatro estaciones o suave?",
        "fr": "Quel climat préfères-tu : chaud, froid, quatre saisons ou doux ?",
        "pt-BR": "Que tipo de clima você prefere: quente, frio, de quatro estações ou ameno?",
        "ar": "ما نوع المناخ الذي تفضّله: حار أم بارد أم أربعة فصول أم معتدل؟",
    },
    "environment": {
        "en": "What kind of place do you want to live in — a big city, a small city, a campus, or a quiet town?",
        "zh-CN": "你想住在什么样的地方——大城市、小城市、校园，还是安静的小镇？",
        "es": "¿En qué tipo de lugar quieres vivir: una gran ciudad, una ciudad pequeña, un campus o un pueblo tranquilo?",
        "fr": "Dans quel type d'endroit veux-tu vivre : une grande ville, une petite ville, un campus ou une ville tranquille ?",
        "pt-BR": "Em que tipo de lugar você quer morar: uma cidade grande, uma cidade pequena, um campus ou uma cidade tranquila?",
        "ar": "في أي نوع من الأماكن تريد أن تعيش: مدينة كبيرة أم مدينة صغيرة أم حرم جامعي أم بلدة هادئة؟",
    },
    "city": {
        "en": "Is there a city you have in mind?",
        "zh-CN": "有没有你心仪的城市？",
        "es": "¿Hay alguna ciudad que tengas en mente?",
        "fr": "As-tu une ville en tête ?",
        "pt-BR": "Há alguma cidade que você tem em mente?",
        "ar": "هل هناك مدينة معيّنة في ذهنك؟",
    },
    "afterGrad": {
        "en": "After graduating, would you like to stay, return home, go to your hometown, or are you undecided?",
        "zh-CN": "毕业后你想留下来、回国、回老家，还是还没想好？",
        "es": "Después de graduarte, ¿te gustaría quedarte, volver a casa, ir a tu ciudad natal o aún no lo sabes?",
        "fr": "Après tes études, veux-tu rester, rentrer chez toi, aller dans ta ville natale, ou tu ne sais pas encore ?",
        "pt-BR": "Depois de se formar, você gostaria de ficar, voltar para casa, ir para sua cidade natal ou ainda não decidiu?",
        "ar": "بعد التخرج، هل تريد البقاء أم العودة إلى الوطن أم الذهاب إلى مسقط رأسك أم لم تقرر بعد؟",
    },
    "salary": {
        "en": "What salary do you hope to earn after graduating, and in which currency?",
        "zh-CN": "毕业后你希望拿到多少薪水，用什么货币？",
        "es": "¿Qué salario esperas ganar después de graduarte y en qué moneda?",
        "fr": "Quel salaire espères-tu après tes études, et dans quelle monnaie ?",
        "pt-BR": "Qual salário você espera ganhar depois de se formar e em qual moeda?",
        "ar": "ما الراتب الذي تأمل في الحصول عليه بعد التخرج وبأي عملة؟",
    },
    "pressure": {
        "en": "How much pressure are you happy with — low, medium, or high?",
        "zh-CN": "你能接受多大的压力——轻松、适中还是高强度？",
        "es": "¿Cuánta presión te parece bien: baja, media o alta?",
        "fr": "Quel niveau de pression te convient : faible, moyen ou élevé ?",
        "pt-BR": "Quanta pressão está bem para você: baixa, média ou alta?",
        "ar": "ما مقدار الضغط المناسب لك: منخفض أم متوسط أم مرتفع؟",
    },
    "teaching": {
        "en": "How do you like to learn — lectures, seminars, or hands-on practice?",
        "zh-CN": "你喜欢怎么上课——讲座、研讨，还是动手实践？",
        "es": "¿Cómo te gusta aprender: con clases magistrales, seminarios o práctica?",
        "fr": "Comment aimes-tu apprendre : cours magistraux, séminaires ou pratique ?",
        "pt-BR": "Como você gosta de aprender: aulas expositivas, seminários ou prática?",
        "ar": "كيف تحب أن تتعلم: محاضرات أم ندوات أم تدريب عملي؟",
    },
}


def _question_line(pref_id: str, locale: str) -> str:
    lines = _NEXT_QUESTION_LINES.get(pref_id, {})
    return lines.get(locale) or lines.get("en", "")


def why_followup(extracted: dict, known_before: dict) -> dict | None:
    """The WHY follow-up for a turn that just recorded new countries
    (Round 14, P0): ``{"countries": [...], "note": <reason>}`` when
    the extraction names countries not known before this turn and no
    reason was on file before it — the same rule as the frontend's
    ``shouldAskCountryWhy``. ``note`` is present only when this turn
    also carried a reason (then the follow-up asks what that reason
    means); without one it asks why from scratch. None when no new
    country was recorded, or a reason from an EARLIER turn is already
    on file (asking again would nag). The caller renders it in the
    FIRST reply of the turn — it must never wait for the user to
    confirm the extraction first, or a user who never taps confirm
    never sees it."""
    if not isinstance(extracted, dict):
        return None
    prior = known_before if isinstance(known_before, dict) else {}
    new = [c for c in (extracted.get("countries") or [])
           if c not in (prior.get("countries") or [])]
    if not new:
        return None
    if (prior.get("note") or "").strip():
        return None
    out: dict = {"countries": new}
    note = extracted.get("note")
    if isinstance(note, str) and note.strip():
        out["note"] = note.strip()
    return out


# ---------------------------------------------------------------------------
# Validation of `known` (client-supplied, never trusted as-is) and of the
# model's `extracted` (never trusted at all)
# ---------------------------------------------------------------------------

def _is_num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _clean_countries(value) -> list[str]:
    """Known ISO codes only, upper-cased, de-duplicated, order kept."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for code in value:
        if isinstance(code, str):
            code = code.strip().upper()
            if code in KNOWN_COUNTRIES and code not in out:
                out.append(code)
    return out


def _clean_enum(value, allowed: tuple[str, ...]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _clean_city(value) -> str | None:
    """Free text, kept as the user's own words — no data validation."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _clean_salary(amount, currency) -> dict | None:
    """{amount, currency} only when both are present and valid."""
    if not _is_num(amount) or amount <= 0:
        return None
    if not isinstance(currency, str) or currency.strip().upper() not in _SALARY_CURRENCIES:
        return None
    amount = int(amount) if float(amount).is_integer() else amount
    return {"amount": amount, "currency": currency.strip().upper()}


def _clean_note(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()[:NOTE_MAX_CHARS]
    return None


def validate_known(raw: dict | None) -> dict:
    """Clean a client-supplied ``known`` dict into the canonical shape
    (only valid values survive; ``note`` is kept but is not one of the
    8 preferences). Missing keys become None / []."""
    raw = raw if isinstance(raw, dict) else {}
    salary = _clean_salary(raw.get("salary"), raw.get("salaryCurrency"))
    return {
        "countries": _clean_countries(raw.get("countries")),
        "climate": _clean_enum(raw.get("climate"), _CLIMATE_VALUES),
        "environment": _clean_enum(raw.get("environment"), _ENVIRONMENT_VALUES),
        "city": _clean_city(raw.get("city")),
        "afterGrad": _clean_enum(raw.get("afterGrad"), _AFTER_GRAD_VALUES),
        "salary": salary["amount"] if salary else None,
        "salaryCurrency": salary["currency"] if salary else None,
        "pressure": _clean_enum(raw.get("pressure"), _PRESSURE_VALUES),
        "teaching": _clean_enum(raw.get("teaching"), _TEACHING_VALUES),
        "note": _clean_note(raw.get("note")),
    }


def validate_extracted(raw) -> dict:
    """Validate the model's ``extracted`` object. Only fields understood
    from THIS message survive, in the response shape: ``countries`` as
    a list of verified ISO codes, enums as themselves, ``city`` as the
    user's own words, ``salary`` as ``{amount, currency}`` only when
    both are present and valid, ``note`` as the user's reason
    (verbatim-ish, capped at 200 chars). Out-of-range/invalid values
    are dropped, never clamped or converted. Unknown keys are dropped.

    Round 10: ``city`` is dropped when it names a KIND of place
    instead of a city — the live model answered "大学城" to the
    environment question with ``environment=campus`` AND
    ``city="大学城"``, which counted the city as known so the city
    question was never asked and prefCity became "大学城". A real
    city name (e.g. "苏黎世", "Zurich") still passes.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    countries = _clean_countries(raw.get("countries"))
    if countries:
        out["countries"] = countries
    for field, allowed in _ENUM_FIELDS.items():
        value = _clean_enum(raw.get(field), allowed)
        if value is not None:
            out[field] = value
    city = _clean_city(raw.get("city"))
    if city is not None and _norm_place_word(city) not in _PLACE_CITY_WORDS:
        out["city"] = city
    salary_raw = raw.get("salary")
    salary = None
    if isinstance(salary_raw, dict):
        salary = _clean_salary(salary_raw.get("amount"),
                               salary_raw.get("currency"))
    if salary is not None:
        out["salary"] = salary
    note = _clean_note(raw.get("note"))
    if note is not None:
        out["note"] = note
    return out


def _norm_place_word(value: str) -> str:
    """Normalised form for kind-of-place comparison: lower-cased,
    spaces and CJK/ASCII punctuation stripped."""
    return re.sub(r"[\s·、，,；;。.!！？?\-_]", "", value.lower())


# Words that name a KIND of place, never a city — in the languages the
# chat serves. Any ``city`` extraction matching one (after
# normalisation) is dropped in validate_extracted, so the city
# question is still asked. Deliberately narrow: a real city name
# never collides with these.
_PLACE_CITY_WORDS: frozenset[str] = frozenset({
    "大学城", "大城市", "小城市", "校园", "小镇", "安静的小镇",
    "安静小镇", "市中心", "郊区",
    "bigcity", "smallcity", "campus", "quiettown", "downtown",
    "citycentre", "citycenter", "suburb", "universitytown",
    "grandville", "petiteville", "campusuniversitaire",
    "cidadegrande", "cidadepequena",
    "مدينةكبيرة", "مدينةصغيرة", "حرمجامعي",
})


# ---------------------------------------------------------------------------
# Deterministic extraction (round 10) — no model needed
#
# The gateway is intermittently down, and while it is down the old
# fallback returned extracted={}: the user's sentence was lost (the
# frontend dropped the turn and entered the guided queue without
# replaying it). What can be matched WITHOUT a model — a country
# named in the message (validated against the verified catalogue)
# and the reason the user gave for it — is extracted here, both for
# the offline fallback and as a fill-in when the model returns an
# empty extraction. Nothing is guessed: no country is inferred from
# a city, no enum is read from a synonym, and the note is the user's
# own words (the part after "因为" when present, else the whole
# sentence when it says more than the country name alone).
#
# Round 26 W1: the country-only rule left every other answer to be
# dropped by a timeout too — re-test task 20 (2026-11-27): the
# environment answer "大学城" came back extracted={} after a ~15 s
# model wait, so the frontend's only preservation was its local
# mapper keyed on the question the turn answered, and the answer was
# lost when that question context was wrong. The deterministic
# extraction now also maps the answer to the FIRST still-missing
# preference — the question the chat is actually asking — from the
# same exact-match synonym lists the frontend's local mapper uses
# (mapLocalAnswer in PrefChat.tsx): climate via _detect_climate_class
# (with the frontend's negation guard), the other enums via
# _DET_ENUM_SYNONYMS, salary as a number + GBP/SGD/USD/CHF currency, and
# a city as the user's own words. Only the first missing preference
# is ever mapped: the chat asks one question at a time, and a free
# question ("瑞士有哪些好学校？") must never be misread as an answer
# to a later question. A question is never mapped as an answer, and
# a kind of place ("大学城" when the city is what's missing) is never
# recorded as a city — the same place-word rule validate_extracted
# applies to the model.
# ---------------------------------------------------------------------------

# Negation guard for the climate wish (frontend mapLocalAnswer):
# "不喜欢冷" must not map to cool.
_CLIMATE_NEGATION_RE = re.compile(r"不喜欢|不要|不想|讨厌|don't like|don't want")

# Enum synonyms (value, synonyms) per preference, mirroring the
# frontend's local mapper chip labels + synonym lists. ASCII words
# match on word boundaries ("low" must not fire inside "follow");
# CJK words match as substrings (see _det_includes).
_DET_ENUM_SYNONYMS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "environment": (
        ("big_city", ("big city", "大城市", "繁华", "热闹", "buzzing")),
        ("small_city", ("small city", "小城市")),
        ("campus", ("campus", "校园", "大学城")),
        ("quiet_town", ("quiet", "安静", "小镇", "乡村", "peaceful")),
    ),
    "afterGrad": (
        ("stay", ("stay", "留下", "留下来", "定居", "留在")),
        ("return_home", ("return home", "go back", "回国", "回国发展")),
        ("hometown", ("hometown", "家乡")),
        ("undecided", ("undecided", "not sure", "不知道", "还没想好", "没决定")),
    ),
    "pressure": (
        ("low", ("take it easy", "relaxed", "轻松", "低压", "佛系")),
        ("medium", ("moderate", "适中", "中等")),
        ("high", ("intensity", "intense", "高压", "高强度")),
    ),
    "teaching": (
        ("lecture", ("lecture", "讲座", "大课")),
        ("seminar", ("seminar", "研讨", "讨论")),
        ("hands_on", ("hands-on", "practice", "实践", "动手")),
    ),
}

# Question markers: a message carrying one is a question (or a
# recommendation request), never an answer — the city branch refuses
# it. Mirrors the frontend's looksLikeQuestion markers + English
# question words.
_DET_QUESTION_MARKERS: tuple[str, ...] = (
    "?", "？", "吗", "么", "哪", "什么", "怎么", "为什么", "为何",
    "是否", "能不能", "可以吗", "有吗", "推荐", "建议", "怎样", "如何",
    "多久", "多少",
)
_DET_QUESTION_WORDS_EN = re.compile(
    r"\b(what|which|how|why|when|where|is there|are there|any|"
    r"recommend|suggest|do you|can you|could you|should i|would you)\b",
    re.IGNORECASE)


def _det_includes(haystack: str, word: str) -> bool:
    """Frontend includesWord, mirrored: ASCII words match on word
    boundaries; CJK (and hyphenated) words match as substrings."""
    if re.fullmatch(r"[a-z][a-z ]*", word):
        return re.search(r"\b" + word.replace(" ", r"\s+") + r"\b",
                         haystack) is not None
    return word in haystack


def _det_looks_like_question(message: str) -> bool:
    """True when a message is a question, not an answer."""
    text = (message or "").strip()
    if not text:
        return False
    if any(m in text for m in _DET_QUESTION_MARKERS):
        return True
    return _DET_QUESTION_WORDS_EN.search(text) is not None


def _deterministic_extract(message: str, known: dict | None = None) -> dict:
    """(countries, note) understood from one message without a model.
    Only fills what is missing: a country already known is not
    re-reported, and the note is only the user's reason — a bare
    country name yields no note."""
    msg = (message or "").strip()
    if not msg:
        return {}
    known = known if isinstance(known, dict) else {}
    out: dict = {}
    country = _detect_country(msg)
    if country and country in KNOWN_COUNTRIES:
        if country not in (known.get("countries") or []):
            out["countries"] = [country]
    # The reason, in the user's own words: the clause after 因为 /
    # because, else the whole sentence when it says more than the
    # country name plus bare travel scaffolding ("我想去瑞士" says
    # nothing beyond the country, so it yields no note; "瑞士，风景好"
    # does).
    reason: str | None = None
    m = re.search(r"因为|because", msg, re.IGNORECASE)
    if m:
        tail = re.split(r"[，。！？；,.;!?]", msg[m.end():])[0].strip()
        if tail:
            reason = tail
    if reason is None and country and not _det_looks_like_question(msg):
        # Lowercased copy: the alias table is lowercase, so a
        # capitalised "Switzerland" still strips for this check.
        # Round 26 W1: a question naming a country ("瑞士有哪些好学校？")
        # is not a reason for that country — without this guard its
        # whole text landed in the note.
        remainder = msg.lower()
        for alias, code in _country_names().items():
            if code == country:
                remainder = remainder.replace(alias, "")
        for word in ("我想去", "想去", "留学", "读书", "上学", "申请",
                     "study in", "study", "go to", "i want to",
                     "want to", "would like to"):
            remainder = remainder.replace(word, "")
        remainder = remainder.replace("去", "")
        if re.sub(r"[\s·、，,；;。.!！？?]", "", remainder):
            reason = msg
    if reason:
        note = _clean_note(reason)
        if note is not None:
            out["note"] = note
    # Round 26 W1 — the answer to the FIRST still-missing preference
    # (the question the chat is actually asking), matched without a
    # model so a timeout can never drop it. Only that one preference
    # is ever mapped, and only from an exact chip label / listed
    # synonym — a free question is never mapped as an answer (the
    # city branch refuses question markers), and a kind of place is
    # never recorded as a city.
    nxt = first_missing(known)
    if nxt == "climate":
        if not _CLIMATE_NEGATION_RE.search(msg):
            cls = _detect_climate_class(msg)
            if cls is not None:
                out["climate"] = cls
    elif nxt in _DET_ENUM_SYNONYMS:
        lowered = msg.lower()
        for value, synonyms in _DET_ENUM_SYNONYMS[nxt]:
            if any(_det_includes(lowered, s) for s in synonyms):
                out[nxt] = value
                break
    elif nxt == "salary":
        m = re.search(r"(\d+(?:\.\d+)?)\s*(GBP|SGD|USD|CHF)?", msg,
                      re.IGNORECASE)
        if m:
            amount = float(m.group(1))
            if amount > 0:
                currency = (m.group(2).upper() if m.group(2)
                            else (known.get("salaryCurrency") or "GBP"))
                out["salary"] = {
                    "amount": int(amount) if amount.is_integer() else amount,
                    "currency": currency}
    elif nxt == "city":
        if not _det_looks_like_question(msg):
            city = msg.strip()
            if city and _norm_place_word(city) not in _PLACE_CITY_WORDS:
                out["city"] = city
    return out


# ---------------------------------------------------------------------------
# Missing preferences / merging
# ---------------------------------------------------------------------------

def _is_known(known: dict, pref_id: str) -> bool:
    if pref_id == "countries":
        return bool(known.get("countries"))
    if pref_id == "salary":
        return known.get("salary") is not None and known.get("salaryCurrency") is not None
    return known.get(pref_id) is not None


def missing_prefs(known: dict) -> list[str]:
    """Still-missing preference ids, in default order."""
    return [pid for pid in PREF_ORDER if not _is_known(known, pid)]


def first_missing(known: dict) -> str | None:
    missing = missing_prefs(known)
    return missing[0] if missing else None


def merge_known(known: dict, extracted: dict) -> dict:
    """Known preferences after applying this message's extraction.
    Extracted values win where present; ``countries`` unions (the user
    may name a second country later); ``note`` is carried over but is
    not a preference."""
    merged = dict(known)
    merged["countries"] = list(known.get("countries") or [])
    for code in extracted.get("countries") or []:
        if code not in merged["countries"]:
            merged["countries"].append(code)
    for field in ("climate", "environment", "city", "afterGrad",
                  "pressure", "teaching"):
        if extracted.get(field) is not None:
            merged[field] = extracted[field]
    salary = extracted.get("salary")
    if isinstance(salary, dict):
        merged["salary"] = salary.get("amount")
        merged["salaryCurrency"] = salary.get("currency")
    if extracted.get("note") is not None:
        merged["note"] = extracted["note"]
    return merged


def _validate_next_question(value, merged_known: dict) -> str | None:
    """The next question to ask: the FIRST still-missing preference
    in default order, always (round 10). The model's suggestion is
    not trusted for ordering — live on 2026-11-26 it answered the
    environment turn with next_question="afterGrad", skipping the
    city entirely, so Zurich was never asked for. The model still
    leads the wording and the opinions; the rotation order is the
    server's, so every missing preference is eventually asked and
    none can be skipped by a model choice. None when done."""
    missing = missing_prefs(merged_known)
    return missing[0] if missing else None


# ---------------------------------------------------------------------------
# Rendering: model lines + the server-side next-question line
# ---------------------------------------------------------------------------

def _render_pref_lines(payload: dict, locale: str, sources: list[Source],
                       next_question: str | None,
                       why: dict | None = None) -> list[str]:
    """Model lines (at most 3, conclusion first) with the next question
    as the last line. When a question follows, the model substance is
    capped at 2 lines so the total stays within 3. Round 16: when the
    turn carries a WHY follow-up (``why`` non-null), the WHY is the
    turn's question and the next-question line is WITHHELD — the
    frontend renders it after the WHY is answered or skipped, so the
    climate question can never appear ahead of the WHY. ``lines`` is
    then substance only (at most 3)."""
    lines = _render_lines(payload, locale, sources)
    if next_question is None or why is not None:
        return lines[:3]
    question = _question_line(next_question, locale)
    body = [line for line in lines[:2] if line != question]
    if question and question not in body:
        body.append(question)
    return body[:3]


def _pin_climate_no_match(lines: list[str], *, wanted: str | None,
                          country: str | None, sources: list[Source],
                          locale: str, next_question: str | None,
                          why: dict | None) -> list[str]:
    """Round 29 W2 (E3) — deterministic post-validation for a climate
    no-match turn on the MODEL path (the R26 W3 precedent:
    deterministic post-validation pins the answer to the intent).

    Re-test 23 (gateway up, model-led): the climate answer HAS the
    no-match sentence but DROPS the "climate is only a preference,
    it never decides eligibility, it only orders results" sentence
    and drops the cities line with programme counts. The frontend
    helper ``localisedFallbackLines`` only re-renders OFFLINE
    replies, so a model reply must carry the sentences itself, in
    this turn's locale — and only from deterministic templates
    (``climate_no_match_line`` in ai.chat, built from ``_DEVIL_T``),
    never model text.

    When there is no no-match to state (``climate_no_match_line``
    returns None — a match, no wanted class, no country, no
    evidence), or the lines already carry BOTH the preference-only
    sentence and the cities line, the lines are returned unchanged.
    Otherwise the deterministic line replaces the last body line
    that states a listed city (canonical or localised name) or the
    wanted class word — the model's climate claim, searched from
    the end so the summary (which may carry the user's reason)
    is never the line replaced — or, when no body line states the
    climate at all, it is inserted first and the body is capped so
    the total stays within 3 lines with the next-question line
    still last (2 body lines + question, or 3 body lines on a WHY
    turn, where the question is withheld)."""
    det_line = climate_no_match_line(wanted, country, sources, locale)
    if det_line is None:
        return lines
    joined = "\n".join(lines)
    pref_only = (_CLIMATE_PREFERENCE_ONLY.get(locale)
                 or _CLIMATE_PREFERENCE_ONLY["en"])
    cities_line = evidence_cities_line(sources, locale)
    if pref_only in joined and cities_line is not None \
            and cities_line in joined:
        return lines
    question = (_question_line(next_question, locale)
                if next_question is not None and why is None else "")
    body = ([line for line in lines if line != question]
            if question else list(lines))
    items = evidence_cities_items(sources)
    names: set[str] = set()
    for it in items:
        names.add(it["city"])
        names.add(localised_city_name(it["city"], locale))
    words = _CLASS_WORDS.get(locale) or _CLASS_WORDS["en"]
    wanted_word = words.get(wanted, "") if wanted else ""
    target: int | None = None
    for i in range(len(body) - 1, -1, -1):
        if any(n in body[i] for n in names):
            target = i
            break
    if target is None and wanted_word:
        for i in range(len(body) - 1, -1, -1):
            if wanted_word in body[i]:
                target = i
                break
    max_body = 2 if question else 3
    if target is not None:
        body[target] = det_line
    else:
        body.insert(0, det_line)
        body = body[:max_body]
    out = body + ([question] if question else [])
    return out[:3]


def _fallback_result(template: dict, sources: list[Source], known: dict,
                     locale: str, *, force_no_url: bool = False,
                     extracted: dict | None = None,
                     why: dict | None = None,
                     climate_wanted: str | None = None,
                     climate_stated: bool = False) -> dict:
    """The honest offline result: template lines (at most 2) + the
    deterministic next question as the last line, the deterministic
    extraction (round 10 — ``{}`` only when nothing could be matched
    without a model, e.g. a bare greeting), deterministic
    next_question. ``force_no_url`` lets the personal-data guard force
    ``evidence_url`` None (the template's evidence link is meaningless
    there — chat.py does the same).

    Round 7 fix: when retrieval returned relevant climate evidence,
    the generic "I don't know" first line is replaced by what the
    evidence actually shows (cities + actual classes + counts) —
    the model being unavailable must not erase evidence already in
    hand. Any other template line is left exactly as written.

    Round 28 D2: when the cities line IS placed, the result also
    carries the structured block ``evidence_cities`` (from
    ``evidence_cities_items``) and ``climate_wanted`` (the wanted
    class, or None) — so the frontend can re-render the cities line
    and the no-match sentence in the CURRENT locale after a language
    switch, instead of the stored request-locale string. The block
    is attached only when the cities line was actually placed into
    ``lines[0]``, so the helper's "block present ⟺ lines[0] is the
    cities line" contract always holds. Round 29 W2 (E3) attaches
    the same block on a MODEL-path climate turn too (see
    ``pref_answer``) — the frontend helper still returns null for
    model replies today, but the block is the same shape, so the
    helper can be extended to model replies without a backend
    change.

    Round 28 D2 scoping: the cities line is placed only on a
    climate-relevant turn — this message states a climate class
    (``climate_stated``), the turn just answered climate
    (``extracted`` carries it), or climate is the next question.
    Before this, it fired on every turn once countries were known,
    so the identical block repeated verbatim after every later
    preference answer (re-test 22: 6 times). On a non-climate turn
    the generic unknown line stays, exactly as the template wrote
    it; the country line still fires only when there is no cities
    line at all, as before.

    Round 29 W2 (E3): the result also carries ``climate_turn``
    (bool, always present) — True exactly when THIS turn stated a
    climate class (``climate_stated``) or just answered climate
    (``extracted`` carries it). The cities line is still placed on
    the countries turn (climate is the next question there — the
    R28 D2 evidence-in-hand pin), so the identical cities line can
    still appear on two consecutive turns in ``lines``; the marker
    is the frontend's dedupe signal: render the cities line only
    on the turn where ``climate_turn`` is True (the climate turn),
    and suppress its re-render on the earlier turn. ``climate_turn``
    is also carried on model-path results (see ``pref_answer``),
    where the structured block is attached on a climate turn too.

    Round 30 F1: when this turn's deterministic extraction recorded
    a preference (``extracted`` non-empty), the generic unknown pair
    is dropped — the turn was understood, so "I can't find that"
    would be false. When the extraction genuinely failed
    (``extracted`` == {}) the pair stays: that is the honest "I
    don't know" case. The drop is scoped to the pair itself (see
    the code below): any other template line — a cities line, a
    country line, a specific unknown such as ``fee_unknown`` — is
    never removed by it.

    Round 16: when ``why`` is present, the WHY follow-up is the
    turn's question and the next-question line is WITHHELD from
    ``lines`` (same rule as the model path — see
    ``_render_pref_lines``): the deferred preference still rides in
    ``next_question``, and the frontend asks it after the WHY is
    answered or skipped."""
    nxt = first_missing(known)
    done = nxt is None
    lines = list(template["lines"][:2])
    # Round 30 F1: whether the template carried the generic unknown
    # pair, captured BEFORE the cities/country replacement below
    # rewrites lines[0] — the replacement can leave unknown_2
    # behind on its own (a climate turn's [cities, unknown_2]).
    unknown_pair = (_t(locale, "unknown"), _t(locale, "unknown_2"))
    had_unknown_pair = lines == list(unknown_pair)
    placed_cities = False
    if not force_no_url:
        cities = evidence_cities_line(sources, locale)
        country = country_evidence_line(sources, locale)
        climate_relevant = (climate_stated
                            or "climate" in (extracted or {})
                            or nxt == "climate")
        if lines and lines[0] == _t(locale, "unknown"):
            if cities is not None:
                if climate_relevant:
                    lines[0] = cities
                    placed_cities = True
                # Else the generic unknown line stays: the cities
                # block must not repeat on a non-climate turn.
            elif country is not None:
                lines[0] = country
        elif not lines:
            if cities is not None:
                if climate_relevant:
                    lines = [cities]
                    placed_cities = True
            elif country is not None:
                lines = [country]
    # Round 30 F1: when this turn's deterministic extraction recorded
    # a preference, the turn was understood — the generic unknown pair
    # ("I can't find that in the verified data" + "start the
    # eligibility check") must not be emitted: it claims the answer
    # was not found, which is false when the value was just recorded
    # (re-test 24 item a / re-test 25: every guided answer —
    # environment, city, afterGrad, salary, pressure, teaching —
    # repeated the pair even though the value bubble showed). Only
    # the pair is dropped, and only when the template actually
    # carried it: a specific unknown (fee_unknown,
    # ask_ielts_unknown, ...) is never a member of the pair and
    # stays, and when the extraction genuinely failed
    # (extracted == {}) the pair stays exactly as before — that is
    # the honest "I don't know" case. The question line below is
    # still appended, so a guided turn now answers with the question
    # alone (on a WHY turn, with no lines at all — the WHY is the
    # turn's question); the frontend renders a turn with empty reply
    # lines as its offline line + question bubble (prefTurnBubbles
    # emits the question bubble "even with empty lines").
    if extracted and had_unknown_pair:
        lines = [line for line in lines if line not in unknown_pair]
    if nxt is not None and why is None:
        lines.append(_question_line(nxt, locale))
    result: dict = {"lines": lines[:3],
                    "evidence_url": None if force_no_url else template.get("evidence_url"),
                    "ai_status": "unavailable", "model": None,
                    "sources": [{"id": s.id, "url": s.url, "title": s.title}
                                for s in sources],
                    "extracted": extracted or {}, "next_question": nxt, "done": done,
                    "why_followup": why,
                    "climate_turn": bool(climate_stated
                                         or "climate" in (extracted or {}))}
    if placed_cities:
        result["evidence_cities"] = evidence_cities_items(sources)
        result["climate_wanted"] = climate_wanted
    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def pref_answer(message: str, locale: str = "en",
                known: dict | None = None,
                history: list[dict] | None = None,
                provider: ProviderAdapter | None = None) -> dict:
    """One turn of the model-led preference conversation.

    Returns ``{lines, evidence_url, ai_status, model, sources,
    extracted, next_question, done, why_followup, climate_turn}``:
    ``lines`` at most 3, conclusion first, the next question as the
    last line while anything is still missing — UNLESS the turn
    carries a WHY follow-up, in which case the WHY is the turn's
    question, the next-question line is withheld from ``lines`` and
    ``next_question`` names the deferred preference (Round 16);
    ``extracted`` holds only the preferences understood from THIS
    message, validated server-side; ``next_question`` is the single
    most useful still-missing preference, or null when all 8 are
    known (``done`` True); ``why_followup`` is
    ``{"countries": [...], "note": <reason>}`` in the FIRST reply of
    a turn that records new countries (None otherwise) — the frontend
    renders it at once, never behind the confirm chip. ``ai_status``
    is ``"available"`` only when a validated model output was actually used.
    Round 29 W2 (E4): a message that answers the first still-missing
    preference — a guided answer, not a question — takes the
    deterministic route (extraction + template, no model call) and
    returns ``ai_status="unavailable"`` in engine time; the model is
    attempted only for non-guided turns (a free question mid-flow, a
    greeting, an answer the deterministic extraction cannot read).
    ``climate_turn`` is True exactly when this turn stated a climate
    class or just answered climate; on a climate turn the result
    also carries ``evidence_cities`` + ``climate_wanted`` (the R28 D2
    shape, on the model path too), and on a climate no-match turn
    the model reply's lines are post-validated to carry the cities
    line with programme counts and the no-match + preference-only
    sentences (Round 29 W2, E3).
    """
    loc = locale if locale in LOCALES else "en"
    msg = message or ""
    clean_known = validate_known(known)

    # (a) Personal-data guard first — the value is never echoed.
    if contains_personal_data(msg):
        template = assistant_ask(msg, loc)
        return _fallback_result(template, [], clean_known, loc,
                                force_no_url=True)

    provider = provider or ProviderAdapter()

    # (b) Retrieval, climate-scoped to the known countries (or the
    # country this message names, when none is known yet). The wanted
    # climate class comes from this message when it states one, else
    # from the stored preference.
    scope = list(clean_known["countries"])
    if not scope:
        detected = _detect_country(msg)
        if detected and detected in KNOWN_COUNTRIES:
            scope = [detected]
    wanted = _detect_climate_class(msg) or clean_known["climate"]
    template, sources, pids = _retrieve(
        msg, loc, countries=scope or None, climate_class=wanted)
    sources_out = [{"id": s.id, "url": s.url, "title": s.title}
                   for s in sources]

    # The deterministic extraction for this message (round 10 /
    # round 26 W1): what can be matched WITHOUT a model — the answer
    # to the FIRST still-missing preference (the question the chat is
    # actually asking), plus a country named in the message and the
    # user's reason in their own words. Computed once here and reused
    # by the guided route, the no-key branch, the model-failure
    # fallback, and the model-success fill-in below.
    det = _deterministic_extract(msg, clean_known)
    climate_stated = _detect_climate_class(msg) is not None

    def fallback() -> dict:
        # The deterministic result: the template + deterministic
        # extraction, so the sentence is recorded and the next
        # question advances past what it stated, instead of losing
        # the turn — on a model failure, with no key, and (round 29
        # W2, E4) on a guided answer (see below).
        merged = merge_known(clean_known, det)
        return _fallback_result(template, sources, merged, loc,
                                extracted=det,
                                why=why_followup(det, clean_known),
                                climate_wanted=wanted,
                                climate_stated=climate_stated)

    # (c) Guided answer: the deterministic route, no model call
    # (Round 29 W2, E4 — re-test 23 item c: the first preference
    # answer took 13-30 s on the model path while the offline path
    # answered in ~1-2 s). A guided answer is a message that answers
    # the FIRST still-missing preference — the question the chat is
    # asking — as the deterministic extraction reads it, and is not
    # itself a question (a free question mid-flow, e.g. "瑞士有哪些
    # 好学校？", keeps the model path below). The guided 8-question
    # answers are deterministic (extract the answer + confirm + ask
    # the next question) — the model adds nothing to them, and the
    # fee flow was made deterministic the same way in R25/R26 (the
    # template is the one route when the answer is already resolved).
    # A short model budget is NOT the fix here: a healthy gateway
    # answers a tiny chat in ~3.4 s (provider.py probe comment,
    # measured 2026-11-27), so no budget under ~2 s could ever use
    # the model when healthy, and any budget over ~2 s breaks the
    # ~2 s bound when the gateway is slow — while httpx
    # MockTransport ignores timeouts, so a budget could not even be
    # verified honestly in tests. The deterministic route lands in
    # engine time in every gateway state; ``ai_status`` is honestly
    # "unavailable" (no validated model output was used), exactly as
    # the fee template route reports it. Trade-off, stated plainly:
    # a guided turn no longer gets the model's in-lines
    # acknowledgement of the user's reason — the reason still rides
    # in ``extracted.note`` and in ``why_followup`` (the frontend
    # renders the WHY with it), which is the same wording the
    # offline path already showed in re-test 23 round 1.
    nxt_missing = first_missing(clean_known)
    guided = (nxt_missing is not None and nxt_missing in det
              and not _det_looks_like_question(msg))
    if guided:
        return fallback()

    # (d) No key: the template assistant is the honest answer, plus
    # the deterministic extraction (round 10) so the user's words
    # are recorded even with no model at all.
    if not provider.available:
        return fallback()

    # (e) Key present: model over the retrieved sources only.
    evidence_texts = _evidence_texts(sources, pids)
    missing_before = missing_prefs(clean_known)
    # Round 26 W1 — fail-fast parity with ai.chat.answer: when the
    # gateway is already known down (the breaker is open, or a probe
    # said "unavailable" within its 60 s TTL — model_skip_cached),
    # skip the model attempt and return the template + deterministic
    # extraction at once, instead of spending the 15 s budget proving
    # the gateway is still down. pref_chat never consulted this gate
    # before: the pet chat (ai.chat) and /simulate did, so a known-down
    # gateway cost every pref-chat turn the full 15 s while the same
    # question in the pet chat answered in ~1 s. A cold cache with a
    # closed breaker still attempts as before: the first slow failure
    # after the gateway dies is inherent (the /simulate residual).
    if model_skip_cached():
        return fallback()
    envelope = {
        "task": "pref-chat",
        "prompt_version": PROMPT_VERSION,
        "locale": loc,
        "message": msg,
        "history": _clean_history(history),
        "known": clean_known,
        "missing": missing_before,
        "evidence_catalog": [
            {"id": s.id, "url": s.url, "title": s.title, "excerpt": s.excerpt}
            for s in sources],
    }
    messages = [{"role": "user", "content": json.dumps(envelope, ensure_ascii=False)}]
    system = pref_chat_system(loc)
    # Timeouts (round 10 fix): live gateway calls took ~7-10 s each
    # on 2026-11-26, and the round-9 budgets (20 s first call + 15 s
    # repair) let one turn stack to ~35 s server-side — past the
    # frontend's 25 s per-attempt abort, so the browser retried the
    # whole turn and the user saw 45-60 s of silence. A turn now gets
    # ONE model call with a 15 s budget and NO repair retry: an
    # unparsable or invalid output falls back to the template at once
    # (with the deterministic extraction, so the words are still
    # recorded). Worst case per turn is ~15 s + retrieval, inside one
    # frontend attempt. The event-loop blockage itself is fixed at the
    # router (see app/router_chat.py).
    started = time.monotonic()
    try:
        result = provider.chat(messages, system=system, timeout_s=15.0)
    except ProviderError as e:
        logger.info("pref_chat model call failed kind=%s latency_ms=%d",
                    e.kind, int((time.monotonic() - started) * 1000))
        return fallback()
    parsed = _parse_model_json(result.text)
    if parsed is None:
        logger.info("pref_chat model output unparsable latency_ms=%d",
                    int((time.monotonic() - started) * 1000))
        return fallback()
    errors = _validate_chat_payload(parsed, sources, evidence_texts, loc)
    if errors:
        # Round 10: no repair retry — one bad output costs a second
        # ~10 s model call and still usually fails; the template +
        # deterministic extraction answers the user faster.
        logger.info("pref_chat model output failed validation errors=%d",
                    len(errors))
        return fallback()
    # (f) Server-side validation of the model's extraction + next
    # question — never trusted, always recomputed against merged known.
    # Round 10: the deterministic extraction fills in a country / a
    # reason the model missed (never overrides what the model did
    # extract), so a silent model gap cannot drop the user's words.
    # Round 26 W1: the same fill-in covers the enums (climate,
    # environment, afterGrad, pressure, teaching) — a model that
    # answers "大学城" with an empty extraction, or with city="大学城"
    # (dropped by validate_extracted's place-word rule), no longer
    # drops the environment answer. Salary / city stay fallback-only:
    # the model is the authority for those when it is up.
    extracted = validate_extracted(parsed.get("extracted"))
    for key in ("countries", "note", "climate", "environment",
                "afterGrad", "pressure", "teaching"):
        if key not in extracted and key in det:
            extracted[key] = det[key]
    merged = merge_known(clean_known, extracted)
    nxt = _validate_next_question(parsed.get("next_question"), merged)
    done = nxt is None
    # Round 14, P0: the WHY follow-up rides in the FIRST reply of the
    # turn that records new countries — never gated on the user
    # confirming the extraction first. Round 16: when it is present,
    # it IS the turn's question, so the next-question line is
    # withheld from `lines` (see _render_pref_lines) and `nxt` stays
    # the deferred preference.
    why = why_followup(extracted, clean_known)
    lines = _render_pref_lines(parsed, loc, sources, nxt, why)
    # Round 29 W2 (E3): the climate pin — when this turn is a climate
    # turn (it states a climate class, or just answered climate),
    # the model reply must carry the cities line with programme
    # counts AND the no-match + preference-only sentences (see
    # _pin_climate_no_match). The structured block rides along in
    # the same shape as the R28 D2 fallback block, so the frontend
    # can re-render the cities line in the current locale if it
    # extends its helper to model replies; ``climate_turn`` marks
    # the turn for the frontend's cities-line dedupe (see
    # _fallback_result).
    climate_turn = bool(climate_stated or "climate" in extracted)
    wanted_turn = (_detect_climate_class(msg)
                   or extracted.get("climate"))
    if climate_turn:
        lines = _pin_climate_no_match(
            lines, wanted=wanted_turn,
            country=(scope[0] if scope else None), sources=sources,
            locale=loc, next_question=nxt, why=why)
    # Defence in depth: a rendered line must never carry a raw URL, a
    # probability/guarantee, or key material — if it does, fall back.
    joined_lines = "\n".join(lines)
    if ("http://" in joined_lines or "https://" in joined_lines
            or "www." in joined_lines or check_no_forbidden(lines)
            or "sk-" in joined_lines.lower()):
        return fallback()
    result: dict = {"lines": lines,
                    "evidence_url": _resolve_evidence_url(parsed, sources),
                    "ai_status": "available",
                    "model": f"{result.provider}/{result.model}",
                    "sources": sources_out,
                    "extracted": extracted,
                    "next_question": nxt,
                    "done": done,
                    "why_followup": why,
                    "climate_turn": climate_turn}
    if climate_turn:
        items = evidence_cities_items(sources)
        if items:
            result["evidence_cities"] = items
            result["climate_wanted"] = wanted_turn
    return result
