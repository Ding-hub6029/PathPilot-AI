"""Model-backed free-text chat for the pet 小罗盘 (Day 3).

The template assistant in ``ai.assistant`` stays the fast path: when no
AI provider is configured, or when the model fails / its output fails
citation validation, the answer is the template ``ask()`` result with
``ai_status="unavailable"`` — a model answer is never faked.

Model path (only when a provider is configured):

- the personal-data guard runs FIRST (reused from ``ai.assistant``);
  a message that looks like it contains a name/phone/email is refused
  with the fixed refusal line — the value is never echoed and never
  stored;
- retrieval finds verified facts only: programme fee/IELTS/deadline and
  rank lookup via the template assistant's helpers, plus the verified
  Gaokao-route facts when the message mentions Gaokao/高考, plus — since
  round 6 (Job A) — climate evidence (top cities of the wanted class
  from the curated climate table, with verified programme counts) when
  the message states a climate wish, and the cheapest verified
  programme in the stated track/country when the message asks for a
  recommendation (the guided 3-question flow's constructed message);
- the model sees ONLY those retrieved sources, as an evidence catalogue
  in a JSON envelope (``{task: "chat", prompt_version, locale, message,
  history, evidence_catalog}``); its structured JSON output is validated
  by ``ai.grounding.check_model_output`` (id whitelist, numeric
  cross-check, no probabilities/guarantees, no raw URLs), with one
  repair retry; on any failure the template answer is returned;
- evidence URLs are resolved server-side from cited source ids, never
  taken from model text. The final answer is at most 3 lines,
  conclusion first; unknown stays unknown, with the eligibility-check
  offer as the next step.

Nothing is logged or stored: no message, history or key ever leaves
this call except inside the provider request itself.
"""
from __future__ import annotations

import json
import re

from ai.assistant import (LOCALES, _DEADLINE_WORDS, _FEE_WORDS,
                          _IELTS_WORDS, _RANK_WORDS, _TM_WORDS, _UG_WORDS,
                          _match_programmes, _norm, _t,
                          ask as assistant_ask, check_no_forbidden,
                          contains_personal_data, program_fee_range)
from ai.grounding import (FORBIDDEN_PATTERNS, Source,
                          check_model_output, gaokao_sources,
                          programme_fact_texts, programme_sources,
                          ranking_sources, resolve_url)
from ai.prompts import PROMPT_VERSION, chat_system
from ai.provider import ProviderAdapter, ProviderError
from app.data import (CLIMATE, DATA_DIR, EXPANSION_MATCHABLE,
                      EXPANSION_PROGRAMS, PROGRAMS, RANKINGS)

MAX_HISTORY_TURNS = 6


# ---------------------------------------------------------------------------
# Model-JSON parsing (same fence tolerance as ai.explain)
# ---------------------------------------------------------------------------

def _parse_model_json(text: str) -> dict | None:
    """Parse a model reply as JSON, tolerating ```json fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


# ---------------------------------------------------------------------------
# Retrieval: verified facts only, enriched with manifest fact texts
# ---------------------------------------------------------------------------

_MANIFEST_FACTS: dict | None = None


def _manifest_facts() -> dict[tuple[str, str], list[str]]:
    """(program_id, source_id) -> manifest fact texts, e.g. the fee line
    "Overseas fees 2026/27: GBP 46,700 per year".

    Programme sources on their own carry only a page-title excerpt, so
    without these the model could never state a fee or deadline — and
    the numeric cross-check could never pass one either.
    """
    global _MANIFEST_FACTS
    if _MANIFEST_FACTS is None:
        grouped: dict[tuple[str, str], list[str]] = {}
        try:
            with open(DATA_DIR / "source-manifest.json", encoding="utf-8") as f:
                manifest = json.load(f)
            for fact in manifest.get("facts", []):
                key = (fact.get("program_id", ""), fact.get("source_id", ""))
                grouped.setdefault(key, []).append(
                    f"{fact.get('field', '')}: {fact.get('value', '')}. "
                    f"{fact.get('excerpt', '')}")
        except (OSError, ValueError):
            grouped = {}
        _MANIFEST_FACTS = grouped
    return _MANIFEST_FACTS


def _enriched_programme_sources(program_id: str) -> list[Source]:
    """Programme sources whose excerpts carry the manifest fact texts
    (and rule details) for their own source id — verified facts only,
    never anything from outside the programme's own sources."""
    sources = programme_sources(program_id)
    facts = _manifest_facts()
    details = programme_fact_texts(program_id)
    out: list[Source] = []
    for s in sources:
        sid = s.id[len(f"src:{program_id}:"):] if s.id.startswith(f"src:{program_id}:") else s.id
        extra = list(facts.get((program_id, sid), []))
        detail = details.get(f"src:{program_id}:{sid}", "")
        if detail:
            extra.append(detail)
        excerpt = s.excerpt + (" " + " ".join(extra) if extra else "")
        out.append(Source(id=s.id, url=s.url, title=s.title, excerpt=excerpt))
    return out


def _retrieve(message: str, locale: str, *, countries: list[str] | None = None,
              climate_class: str | None = None):
    """(template ask() result, retrieved sources, programme ids).

    Retrieval reuses the template assistant: its ``ask()`` already does
    the programme fee/IELTS/deadline match and the rank lookup, and its
    ``_match_programmes`` covers the ambiguous two-programme case where
    ``ask()`` returns no single programme. Gaokao keywords add the
    verified Gaokao-route facts for the matched programme (or the
    general routes when no programme matched).

    ``countries`` scopes the climate evidence to those countries (the
    pref-chat flow, round 7): when set, no other country's city is
    ever substituted for a missing wanted class — the chosen
    countries' own cities join the catalogue with their actual
    classes instead. ``climate_class`` overrides the class detected
    from the message (the pref-chat flow passes the stored climate
    preference); None means detect from the message as before.
    """
    template = assistant_ask(message, locale)
    sources: list[Source] = []
    seen: set[str] = set()

    def _add(new: list[Source]) -> None:
        for s in new:
            if s.id not in seen:
                seen.add(s.id)
                sources.append(s)

    pids: list[str] = []
    if template.get("program_id"):
        pids.append(template["program_id"])
    else:
        for pid in _match_programmes(_norm(message or "")):
            if (pid in PROGRAMS or pid in EXPANSION_MATCHABLE) \
                    and pid not in pids:
                pids.append(pid)
    for pid in pids:
        _add(_enriched_programme_sources(pid))
    if template.get("institution_id"):
        _add(ranking_sources(template["institution_id"]))
    lowered = (message or "").lower()
    if "gaokao" in lowered or "高考" in (message or ""):
        _add(gaokao_sources(pids[0] if pids else None))
    # (Round 6, Job A) Climate-aware evidence: a climate preference had
    # no evidence at all, so even the live model could only answer "I
    # don't know". The top cities of the wanted class (by verified
    # programme count) plus the cheapest programme in the top city are
    # verified data, so they join the catalogue — after the programme
    # sources, so existing catalogue order is unchanged.
    climate_class = climate_class or _detect_climate_class(message or "")
    if climate_class:
        climate_sources, top_programme = _climate_evidence(
            climate_class, countries=countries)
        _add(climate_sources)
        if top_programme and top_programme not in pids:
            _add(_enriched_programme_sources(top_programme))
            pids.append(top_programme)
    # (Round 6, Job A) Suggestion intent: the guided 3-question flow
    # sends one constructed message (degree + country + budget band).
    # With no programme matched, the cheapest verified programme in
    # that track/country is the evidence the model suggests from.
    # Never fires on a fee/IELTS/deadline or rank question.
    if not pids:
        picked = _suggest_pick(message or "")
        if picked is not None:
            _add(_enriched_programme_sources(picked))
            pids.append(picked)
    return template, sources, pids


# ---------------------------------------------------------------------------
# Climate-aware + suggestion retrieval (round 6, Job A)
#
# The template assistant can only answer questions that name a programme
# or an institution. Two free-text shapes the pet must answer had no
# evidence at all, so even the live model could only say "I don't know":
# - a climate preference ("我喜欢很冷的那种，你有什么推荐吗") — the
#   curated climate table (data/expansions/climate.json) plus the
#   verified programme counts per city are the evidence;
# - the guided 3-question suggestion (degree + country + budget band),
#   which the frontend sends as one constructed message — the cheapest
#   verified programme in that track/country is the evidence.
# Both branches add ONLY verified data to the evidence catalogue; the
# model still has to cite it, and the numeric cross-check still applies.
# They never change the template answer itself (the no-key path still
# returns the template lines, ai_status "unavailable").
# ---------------------------------------------------------------------------

_CLIMATE_CLASS_WORDS: dict[str, tuple[str, ...]] = {
    "cool": ("cool", "cold", "chilly", "寒冷", "很冷", "冷", "凉爽", "凉快",
             "froid", "frío", "frio", "بارد"),
    "warm": ("warm", "hot", "暖", "热", "炎热", "chaud", "caliente",
             "quente", "حار"),
    "four_seasons": ("four seasons", "four-season", "四季", "四季分明",
                     "quatre saisons", "cuatro estaciones"),
    "mild": ("mild", "温和", "宜人", "doux", "templado", "ameno", "معتدل"),
}

_CLIMATE_CLASS_LABEL = {"cool": "cool", "warm": "warm",
                        "four_seasons": "four-season", "mild": "mild"}

# "冷门/热门" (unpopular/popular major) is not a climate word — strip
# those compounds before scanning, or "有什么冷门专业" would read as a
# wish for cold weather.
_CLIMATE_STRIP_RES = (re.compile("冷门"), re.compile("热门"))

_COUNTRY_CODE_RE = re.compile(r"country code\s+([a-z]{2})", re.IGNORECASE)
_CEILING_RE = re.compile(
    r"(GBP|SGD|USD|HKD|EUR|AUD|CAD|JPY|KRW|CHF|CNY)\s*([\d,]+(?:\.\d+)?)"
    r"\s*(per year|total|per credit)?", re.IGNORECASE)

# Lowercased country name -> ISO code. The rankings data supplies the
# official English country_name per institution (see _country_names);
# this table adds the short / Chinese forms the frontend's users type.
_COUNTRY_ALIASES: dict[str, str] = {
    "uk": "GB", "great britain": "GB", "england": "GB",
    "usa": "US", "u.s.": "US", "america": "US",
    "south korea": "KR", "korea": "KR",
    "new zealand": "NZ", "hong kong": "HK", "saudi arabia": "SA",
    "英国": "GB", "美国": "US", "新加坡": "SG", "澳大利亚": "AU",
    "加拿大": "CA", "日本": "JP", "韩国": "KR", "德国": "DE",
    "法国": "FR", "荷兰": "NL", "瑞士": "CH", "香港": "HK",
    "中国": "CN", "爱尔兰": "IE", "意大利": "IT", "西班牙": "ES",
    "瑞典": "SE", "丹麦": "DK", "新西兰": "NZ", "马来西亚": "MY",
    "台湾": "TW", "挪威": "NO", "比利时": "BE", "奥地利": "AT",
    "以色列": "IL", "沙特": "SA", "阿根廷": "AR",
}

_SUGGEST_WORDS = ("recommend", "suggest", "推荐", "建议", "recomienda",
                  "recommande", "recomende")


def _detect_climate_class(message: str) -> str | None:
    """Wanted climate class from a free-text message, or None. The
    earliest class word in the message wins, so "冬天不要太冷，夏天
    不要太热" reads as the first wish stated, not both."""
    msg = _norm(message or "")
    for pat in _CLIMATE_STRIP_RES:
        msg = pat.sub("", msg)
    best: tuple[int, str] | None = None
    for cls, words in _CLIMATE_CLASS_WORDS.items():
        for word in words:
            i = msg.find(word)
            if i >= 0 and (best is None or i < best[0]):
                best = (i, cls)
    return best[1] if best else None


def _table_city(city: str | None) -> str | None:
    """Climate-table city for a programme city (campus suffixes map to
    the table city: "London Bloomsbury" -> "London")."""
    if not city:
        return None
    if city in CLIMATE:
        return city
    for known in CLIMATE:
        if city.startswith(known + " "):
            return known
    return None


def _country_cities(countries: list[str]) -> list[tuple[str, int]]:
    """(city, verified programme count) for cities with programmes in
    the given countries, that have a climate-table entry — count desc,
    name asc. Deterministic; a city with no table entry never appears."""
    wanted = {c.upper() for c in countries}
    counts: dict[str, int] = {}
    for program in list(PROGRAMS.values()) + list(EXPANSION_PROGRAMS.values()):
        if (program.get("country") or "").upper() not in wanted:
            continue
        city = _table_city(program.get("city"))
        if city and city in CLIMATE:
            counts[city] = counts.get(city, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _climate_source(city: str, count: int) -> Source:
    entry = CLIMATE[city]
    slug = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-")
    return Source(
        id=f"climate:{slug}",
        url=entry.get("source_url"),
        title=f"{city} climate",
        excerpt=(f"{city}: {_CLIMATE_CLASS_LABEL[entry['climate']]} "
                 f"climate. Verified programmes in {city}: {count}."))


def _climate_evidence(wanted: str, countries: list[str] | None = None
                      ) -> tuple[list[Source], str | None]:
    """Top 3 cities of the wanted climate class by verified programme
    count, each as one citable source (city + count + the table's own
    source URL), plus the cheapest verified programme in the top city
    (returned as a programme id; the caller adds its sources). A city
    with no entry in the table never appears; counts cover the v2
    programmes and every expansion programme, matchable or not.

    Round 7 (pref-chat): when ``countries`` is given, the wanted-class
    cities are taken WITHIN those countries first, and the chosen
    countries' own cities join the catalogue with their ACTUAL classes
    (so the model can say honestly that e.g. Switzerland has no
    cool-class city — both Zurich and Lausanne are four-season) instead
    of silently substituting another country's city. The cheapest
    programme is then also from within those countries, and is None
    when no wanted-class city exists there.
    """
    scope = [c.upper() for c in countries] if countries else None
    counts: dict[str, int] = {}
    for program in list(PROGRAMS.values()) + list(EXPANSION_PROGRAMS.values()):
        if scope is not None and (program.get("country") or "").upper() not in scope:
            continue
        city = _table_city(program.get("city"))
        if city and CLIMATE.get(city, {}).get("climate") == wanted:
            counts[city] = counts.get(city, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    sources: list[Source] = []
    seen: set[str] = set()
    for city, n in top:
        sources.append(_climate_source(city, n))
        seen.add(city)
    if scope is not None:
        # The chosen countries' own cities, with their actual classes,
        # so a missing wanted class is stated honestly, never papered
        # over with another country's city.
        for city, n in _country_cities(scope):
            if city not in seen:
                sources.append(_climate_source(city, n))
                seen.add(city)
    programme_id: str | None = None
    if top:
        city = top[0][0]
        pool = [p for p in list(PROGRAMS.values())
                + list(EXPANSION_MATCHABLE.values())
                if _table_city(p.get("city")) == city
                and (scope is None
                     or (p.get("country") or "").upper() in scope)]
        if pool:
            def sort_key(p):
                fr = program_fee_range(p)
                return (fr[0] if fr else float("inf"), p["id"])
            programme_id = sorted(pool, key=sort_key)[0]["id"]
    return sources, programme_id


def _country_names() -> dict[str, str]:
    """Lowercased country name -> code: official country_name values
    from the verified rankings data, plus the alias table."""
    names = dict(_COUNTRY_ALIASES)
    for inst in RANKINGS.get("institutions", []):
        name = (inst.get("country_name") or "").strip().lower()
        code = inst.get("country")
        if name and code and name not in names:
            names[name] = code
    return names


def _detect_country(message: str) -> str | None:
    """Country code from a message: the frontend's explicit "country
    code XX" marker first, then a country name. Short names match on
    word boundaries only, so "uk" never fires inside another word."""
    msg = _norm(message or "")
    m = _COUNTRY_CODE_RE.search(msg)
    if m:
        return m.group(1).upper()
    names = _country_names()
    for alias, code in sorted(names.items(), key=lambda kv: -len(kv[0])):
        if len(alias) <= 3:
            if re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", msg):
                return code
        elif alias in msg:
            return code
    return None


def _detect_level(message: str) -> str | None:
    """Degree level from the template assistant's own level words."""
    msg = _norm(message or "")
    if any(w in msg for w in _UG_WORDS):
        return "undergraduate"
    if any(w in msg for w in _TM_WORDS):
        return "taught_masters"
    return None


def _parse_ceiling(message: str) -> tuple[str, float, str] | None:
    """(currency, amount, period) budget ceiling from a message such as
    "under GBP 30,000 per year". "per credit" (or no period) has no
    comparable fee, so it yields no ceiling — never a guess."""
    m = _CEILING_RE.search(message or "")
    if not m:
        return None
    try:
        amount = float(m.group(2).replace(",", ""))
    except ValueError:
        return None
    period = {"per year": "per_year", "total": "total"}.get(
        (m.group(3) or "").lower())
    if period is None:
        return None
    return m.group(1).upper(), amount, period


def _pick_suggest_programme(level: str, country: str,
                            ceiling: tuple[str, float, str] | None) -> str | None:
    """Cheapest verified programme in the track/country: within the
    stated ceiling when one fits (same currency + period), else the
    cheapest in the ceiling's currency/period, else the cheapest in
    the largest same-currency/period group, else the first by id when
    no fee is verified anywhere. Deterministic throughout."""
    pool = [p for p in list(PROGRAMS.values())
            + list(EXPANSION_MATCHABLE.values())
            if p.get("degree_level") == level and p.get("country") == country]
    if not pool:
        return None
    with_fee = [(program_fee_range(p), p) for p in pool]
    with_fee = [(fr, p) for fr, p in with_fee if fr]
    if ceiling:
        currency, amount, period = ceiling
        same = [(fr, p) for fr, p in with_fee
                if fr[2] == currency and fr[3] == period]
        within = [(fr, p) for fr, p in same if fr[1] <= amount]
        if within:
            return min(within, key=lambda x: (x[0][0], x[1]["id"]))[1]["id"]
        if same:
            return min(same, key=lambda x: (x[0][0], x[1]["id"]))[1]["id"]
    if with_fee:
        groups: dict[tuple[str, str], list] = {}
        for fr, p in with_fee:
            groups.setdefault((fr[2], fr[3]), []).append((fr, p))
        key = sorted(groups.keys(),
                     key=lambda k: (-len(groups[k]), k[0], k[1]))[0]
        return min(groups[key], key=lambda x: (x[0][0], x[1]["id"]))[1]["id"]
    return sorted(pool, key=lambda p: p["id"])[0]["id"]


def _suggest_pick(message: str) -> str | None:
    """Programme id for a suggestion request (degree + country +
    optional budget ceiling), or None when the message is not one.
    Only fires on an explicit recommendation ask — a fee/IELTS/
    deadline or rank question never becomes a suggestion."""
    msg = _norm(message or "")
    if not any(w in msg for w in _SUGGEST_WORDS):
        return None
    if any(w in msg for w in _RANK_WORDS):
        return None
    if any(w in msg for w in _FEE_WORDS + _IELTS_WORDS + _DEADLINE_WORDS):
        return None
    level = _detect_level(message)
    country = _detect_country(message)
    if level is None or country is None:
        return None
    return _pick_suggest_programme(level, country, _parse_ceiling(message))


def _evidence_texts(sources: list[Source], programme_ids: list[str]) -> dict[str, str]:
    """Evidence id -> text for the numeric cross-check: the enriched
    source excerpts, plus the manifest fact texts under their own fact
    ids (so a model citing a fact id is checked against that fact)."""
    texts = {s.id: s.excerpt for s in sources}
    for pid in programme_ids:
        for fid, txt in programme_fact_texts(pid).items():
            if txt:
                texts.setdefault(fid, txt)
    return texts


def _clean_history(history: list[dict] | None) -> list[dict]:
    """Last 6 turns only; user/assistant roles, string content capped
    at 500 chars. Anything else is dropped, never repaired."""
    out: list[dict] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role, content = item.get("role"), item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        out.append({"role": role, "content": content[:500]})
    return out[-MAX_HISTORY_TURNS:]


# ---------------------------------------------------------------------------
# Validation of the structured model output
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(
    r"(?:GBP|SGD|USD|£|S\$|¥)?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{4,})")
_MEASURE_RE = re.compile(
    r"(GBP|SGD|USD|£|S\$|¥|%|percent|per year|total|overall|score)", re.IGNORECASE)


def _numbers_in(text: str) -> list[str]:
    """Measurement-like numbers only (same rule as ai.grounding)."""
    out = []
    for m in _NUMBER_RE.finditer(text):
        raw = m.group(0).strip()
        digits = re.sub(r"[^\d.]", "", raw)
        if not digits:
            continue
        if "." in digits or len(digits.replace(".", "")) >= 4 or _MEASURE_RE.search(raw):
            out.append(digits)
    return out


def _norm_number(n: str) -> str:
    return n.replace(",", "").rstrip("0").rstrip(".") if "." in n else n.replace(",", "")


def _safety_errors(text: str, evidence_joined: str) -> list[str]:
    """Extra checks check_model_output does not apply to the summary /
    action text: no raw URLs, no admission-probability/guarantee
    phrasing, no API-key-like material, and no number that is not in
    the cited evidence (a fact not in the retrieved sources)."""
    errors: list[str] = []
    lowered = text.lower()
    if "http://" in lowered or "https://" in lowered or "www." in lowered:
        errors.append("text contains a raw URL; cite an evidence_id instead")
    for pat in FORBIDDEN_PATTERNS:
        if re.search(pat, lowered):
            errors.append("text contains forbidden admission-probability/guarantee phrasing")
            break
    found = check_no_forbidden([text])
    if found:
        errors.append(f"text contains forbidden wording: {', '.join(found)}")
    if "api key" in lowered or "api_key" in lowered or "sk-" in lowered:
        errors.append("text mentions an API key")
    cited_norm = evidence_joined.replace(",", "")
    for num in _numbers_in(text):
        if _norm_number(num) not in cited_norm and num not in cited_norm:
            errors.append(f"text states number {num} which is not in the cited evidence")
    return errors


def _validate_chat_payload(payload: dict, sources: list[Source],
                           evidence_texts: dict[str, str],
                           locale: str) -> list[str]:
    """All validation errors for one structured model output (empty =
    valid). check_model_output covers claims/actions; the summary and
    action explanations get the extra safety scan as well."""
    check = check_model_output(
        payload, allowed_evidence_ids=set(evidence_texts),
        allowed_rule_ids=set(), rule_status={},
        evidence_texts=evidence_texts, locale=locale)
    errors = list(check.errors)
    joined = " ".join(evidence_texts.values())
    summary = payload.get("summary")
    if isinstance(summary, str) and summary.strip():
        errors.extend(_safety_errors(summary, joined))
    for action in payload.get("actions") or []:
        if isinstance(action, dict) and isinstance(action.get("explanation"), str):
            errors.extend(_safety_errors(action["explanation"], joined))
    return errors


# ---------------------------------------------------------------------------
# Rendering a validated payload into at most 3 lines, conclusion first
# ---------------------------------------------------------------------------

def _render_lines(payload: dict, locale: str, sources: list[Source]) -> list[str]:
    lines: list[str] = []
    summary = (payload.get("summary") or "").strip()
    for part in summary.splitlines():
        part = part.strip()
        if part and part not in lines:
            lines.append(part)
    for claim in payload.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        text = (claim.get("text") or "").strip()
        if text and text not in lines and len(lines) < MAX_HISTORY_TURNS - 3:
            lines.append(text)
    added_action = False
    for action in payload.get("actions") or []:
        if not isinstance(action, dict):
            continue
        text = (action.get("explanation") or "").strip()
        if text and text not in lines and len(lines) < 3:
            lines.append(text)
            added_action = True
    unknowns = payload.get("unknowns") or []
    is_unknown = bool(unknowns) or not sources
    if len(lines) < 3:
        if is_unknown:
            offer = _t(locale, "unknown_2")
            if offer not in lines:
                lines.append(offer)
        elif not added_action:
            nxt = _t(locale, "next")
            if nxt not in lines:
                lines.append(nxt)
    return lines[:3]


def _resolve_evidence_url(payload: dict, sources: list[Source]) -> str | None:
    """First cited evidence id that resolves to a URL; else the first
    retrieved source with a URL; else None. Never from model text."""
    for section in (payload.get("claims") or [], payload.get("actions") or []):
        for item in section:
            if not isinstance(item, dict):
                continue
            for eid in item.get("evidence_ids") or []:
                url = resolve_url(eid, sources)
                if url:
                    return url
    for s in sources:
        if s.url:
            return s.url
    return None


def _template_result(template: dict, sources: list[Source]) -> dict:
    return {"lines": template["lines"],
            "evidence_url": template.get("evidence_url"),
            "ai_status": "unavailable", "model": None,
            "sources": [{"id": s.id, "url": s.url, "title": s.title}
                        for s in sources]}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def answer(message: str, locale: str = "en",
           history: list[dict] | None = None,
           provider: ProviderAdapter | None = None) -> dict:
    """Answer one free-text question for 小罗盘.

    Returns ``{lines, evidence_url, ai_status, model, sources}``:
    ``lines`` at most 3, conclusion first; ``evidence_url`` resolved
    server-side from a cited source id (or the template's evidence
    link); ``ai_status`` is ``"available"`` only when a validated model
    output was actually used; ``model`` is ``"provider/model"`` or None;
    ``sources`` is the retrieved evidence catalogue.
    """
    loc = locale if locale in LOCALES else "en"
    msg = message or ""

    # (a) Personal-data guard first — the value is never echoed.
    if contains_personal_data(msg):
        template = assistant_ask(msg, loc)
        return {"lines": template["lines"], "evidence_url": None,
                "ai_status": "unavailable", "model": None, "sources": []}

    provider = provider or ProviderAdapter()
    template, sources, pids = _retrieve(msg, loc)
    sources_out = [{"id": s.id, "url": s.url, "title": s.title} for s in sources]

    # (c) No key: the template assistant is the honest answer.
    if not provider.available:
        return _template_result(template, sources)

    # (d) Key present: model over the retrieved sources only.
    evidence_texts = _evidence_texts(sources, pids)
    envelope = {
        "task": "chat",
        "prompt_version": PROMPT_VERSION,
        "locale": loc,
        "message": msg,
        "history": _clean_history(history),
        "evidence_catalog": [
            {"id": s.id, "url": s.url, "title": s.title, "excerpt": s.excerpt}
            for s in sources],
    }
    messages = [{"role": "user", "content": json.dumps(envelope, ensure_ascii=False)}]
    try:
        result = provider.chat(messages, system=chat_system(loc), timeout_s=12.0)
    except ProviderError:
        return _template_result(template, sources)
    parsed = _parse_model_json(result.text)
    if parsed is None:
        return _template_result(template, sources)
    errors = _validate_chat_payload(parsed, sources, evidence_texts, loc)
    if errors:
        # One repair retry: send the validation errors back, ask to fix
        # only those. Anything still invalid falls back to the template.
        repair = ("Your previous output failed validation. Fix ONLY these "
                  f"problems and output JSON only: {'; '.join(errors)}\n\n"
                  f"Previous output:\n{result.text[:4000]}")
        try:
            retry = provider.chat(
                messages + [{"role": "user", "content": repair}],
                system=chat_system(loc), timeout_s=8.0)
        except ProviderError:
            return _template_result(template, sources)
        parsed2 = _parse_model_json(retry.text)
        if parsed2 is None:
            return _template_result(template, sources)
        errors2 = _validate_chat_payload(parsed2, sources, evidence_texts, loc)
        if errors2:
            return _template_result(template, sources)
        parsed = parsed2
    lines = _render_lines(parsed, loc, sources)
    # Defence in depth: a rendered line must never carry a raw URL, a
    # probability/guarantee, or key material — if it does, fall back.
    joined_lines = "\n".join(lines)
    if ("http://" in joined_lines or "https://" in joined_lines
            or "www." in joined_lines or check_no_forbidden(lines)
            or "sk-" in joined_lines.lower()):
        return _template_result(template, sources)
    return {"lines": lines,
            "evidence_url": _resolve_evidence_url(parsed, sources),
            "ai_status": "available",
            "model": f"{result.provider}/{result.model}",
            "sources": sources_out}
