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
  a GBP/SGD/USD currency, anything else is dropped, never clamped or
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
  URLs), one repair retry, then the template fallback;
- the personal-data guard runs FIRST (reused from ``ai.assistant``);
  a message that looks like it contains a name/phone/email is refused
  with the fixed line — the value is never echoed and never stored;
- when the provider is unavailable or the model output fails
  validation: ``ai_status="unavailable"``, the template fallback
  lines, ``extracted={}`` (no regex extraction in this path — keep it
  simple and honest), and ``next_question`` computed deterministically
  as the first still-missing preference in the default order.

The next question is asked as the last line of ``lines``. The line is
built server-side from a fixed localised template (never model text),
so the contract holds even when the model does not end with a
question; the model is told not to ask it itself. ``done`` is True
exactly when all 8 preferences are known (merged known + extracted).

Nothing is logged or stored: no message, history or key ever leaves
this call except inside the provider request itself.
"""
from __future__ import annotations

import json
import logging
import time

from ai.assistant import (LOCALES, _t, ask as assistant_ask,
                          check_no_forbidden, contains_personal_data)
from ai.chat import (_clean_history, _detect_climate_class,
                     _detect_country, _evidence_texts, _parse_model_json,
                     _render_lines, _resolve_evidence_url, _retrieve,
                     _validate_chat_payload, country_evidence_line,
                     evidence_cities_line)
from ai.grounding import Source
from ai.prompts import PROMPT_VERSION, pref_chat_system
from ai.provider import ProviderAdapter, ProviderError
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
_SALARY_CURRENCIES = ("GBP", "SGD", "USD")

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
    if city is not None:
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
    """The model's next_question, accepted only when it names a
    preference still missing after this message; otherwise the
    deterministic first missing preference (or None when done)."""
    missing = missing_prefs(merged_known)
    if isinstance(value, str) and value in missing:
        return value
    return missing[0] if missing else None


# ---------------------------------------------------------------------------
# Rendering: model lines + the server-side next-question line
# ---------------------------------------------------------------------------

def _render_pref_lines(payload: dict, locale: str, sources: list[Source],
                       next_question: str | None) -> list[str]:
    """Model lines (at most 3, conclusion first) with the next question
    as the last line. When a question follows, the model substance is
    capped at 2 lines so the total stays within 3."""
    lines = _render_lines(payload, locale, sources)
    if next_question is None:
        return lines[:3]
    question = _question_line(next_question, locale)
    body = [line for line in lines[:2] if line != question]
    if question and question not in body:
        body.append(question)
    return body[:3]


def _fallback_result(template: dict, sources: list[Source], known: dict,
                     locale: str, *, force_no_url: bool = False) -> dict:
    """The honest offline result: template lines (at most 2) + the
    deterministic next question as the last line, empty extraction,
    deterministic next_question. ``force_no_url`` lets the
    personal-data guard force ``evidence_url`` None (the template's
    evidence link is meaningless there — chat.py does the same).

    Round 7 fix: when retrieval returned relevant climate evidence,
    the generic "I don't know" first line is replaced by what the
    evidence actually shows (cities + actual classes + counts) —
    the model being unavailable must not erase evidence already in
    hand. Any other template line is left exactly as written."""
    nxt = first_missing(known)
    done = nxt is None
    lines = list(template["lines"][:2])
    if not force_no_url:
        cities = evidence_cities_line(sources, locale)
        country = country_evidence_line(sources, locale)
        if cities is not None and lines and lines[0] == _t(locale, "unknown"):
            lines[0] = cities
        elif country is not None and lines and lines[0] == _t(locale, "unknown"):
            lines[0] = country
        elif cities is not None and not lines:
            lines = [cities]
        elif country is not None and not lines:
            lines = [country]
    if nxt is not None:
        lines.append(_question_line(nxt, locale))
    return {"lines": lines[:3],
            "evidence_url": None if force_no_url else template.get("evidence_url"),
            "ai_status": "unavailable", "model": None,
            "sources": [{"id": s.id, "url": s.url, "title": s.title}
                        for s in sources],
            "extracted": {}, "next_question": nxt, "done": done}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def pref_answer(message: str, locale: str = "en",
                known: dict | None = None,
                history: list[dict] | None = None,
                provider: ProviderAdapter | None = None) -> dict:
    """One turn of the model-led preference conversation.

    Returns ``{lines, evidence_url, ai_status, model, sources,
    extracted, next_question, done}``: ``lines`` at most 3, conclusion
    first, the next question as the last line while anything is still
    missing; ``extracted`` holds only the preferences understood from
    THIS message, validated server-side; ``next_question`` is the
    single most useful still-missing preference, or null when all 8
    are known (``done`` True). ``ai_status`` is ``"available"`` only
    when a validated model output was actually used.
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

    # (c) No key: the template assistant is the honest answer.
    if not provider.available:
        return _fallback_result(template, sources, clean_known, loc)

    # (d) Key present: model over the retrieved sources only.
    def fallback() -> dict:
        return _fallback_result(template, sources, clean_known, loc)

    evidence_texts = _evidence_texts(sources, pids)
    missing_before = missing_prefs(clean_known)
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
    # Timeouts (round 9 fix): live gateway calls took ~9-12 s each on
    # 2026-11-26, and the round-7 budgets (30 s first call + 20 s
    # repair) let one turn stack to ~50 s of silence. A single turn
    # now gets 20 s first attempt + 15 s repair (35 s worst case);
    # anything slower falls back to the template. The event-loop
    # blockage itself is fixed at the router (see app/router_chat.py).
    started = time.monotonic()
    try:
        result = provider.chat(messages, system=system, timeout_s=20.0)
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
        logger.info("pref_chat model output failed validation errors=%d",
                    len(errors))
        # One repair retry: send the validation errors back, ask to fix
        # only those. Anything still invalid falls back to the template.
        repair = ("Your previous output failed validation. Fix ONLY these "
                  f"problems and output JSON only: {'; '.join(errors)}\n\n"
                  f"Previous output:\n{result.text[:4000]}")
        try:
            retry_started = time.monotonic()
            retry = provider.chat(
                messages + [{"role": "user", "content": repair}],
                system=system, timeout_s=15.0)
        except ProviderError as e:
            logger.info("pref_chat repair call failed kind=%s latency_ms=%d",
                        e.kind, int((time.monotonic() - retry_started) * 1000))
            return fallback()
        parsed2 = _parse_model_json(retry.text)
        if parsed2 is None:
            logger.info("pref_chat repair output unparsable")
            return fallback()
        errors2 = _validate_chat_payload(parsed2, sources, evidence_texts, loc)
        if errors2:
            logger.info("pref_chat repair output failed validation errors=%d",
                        len(errors2))
            return fallback()
        parsed = parsed2
    # (e) Server-side validation of the model's extraction + next
    # question — never trusted, always recomputed against merged known.
    extracted = validate_extracted(parsed.get("extracted"))
    merged = merge_known(clean_known, extracted)
    nxt = _validate_next_question(parsed.get("next_question"), merged)
    done = nxt is None
    lines = _render_pref_lines(parsed, loc, sources, nxt)
    # Defence in depth: a rendered line must never carry a raw URL, a
    # probability/guarantee, or key material — if it does, fall back.
    joined_lines = "\n".join(lines)
    if ("http://" in joined_lines or "https://" in joined_lines
            or "www." in joined_lines or check_no_forbidden(lines)
            or "sk-" in joined_lines.lower()):
        return fallback()
    return {"lines": lines,
            "evidence_url": _resolve_evidence_url(parsed, sources),
            "ai_status": "available",
            "model": f"{result.provider}/{result.model}",
            "sources": sources_out,
            "extracted": extracted,
            "next_question": nxt,
            "done": done}
