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
import logging
import re
import time

from ai.assistant import (LOCALES, _DEADLINE_WORDS, _FEE_WORDS,
                          _IELTS_WORDS, _RANK_WORDS, _TM_WORDS, _UG_WORDS,
                          _match_programmes, _norm, _qs_rank, _t,
                          ask as assistant_ask, check_no_forbidden,
                          contains_personal_data, country_display_name,
                          country_programmes, program_display_name,
                          program_evidence_url, program_fee_range)
from ai.grounding import (FORBIDDEN_PATTERNS, Source,
                          check_model_output, gaokao_sources,
                          programme_fact_texts, programme_sources,
                          ranking_sources, resolve_url)
from ai.prompts import PROMPT_VERSION, chat_system
from ai.provider import ProviderAdapter, ProviderError
from app.data import (CLIMATE, DATA_DIR, EXPANSION_MATCHABLE,
                      EXPANSION_PROGRAMS, PROGRAMS, RANKINGS,
                      V2_PROGRAM_INSTITUTION)

MAX_HISTORY_TURNS = 6

# Failure-class diagnostics only (no message, history or key material
# ever reaches a log line): the 2026-11-26 live pref-chat failures
# were diagnosed from timings + local validation, but a recurrence
# needs the failure class visible in the Render log.
logger = logging.getLogger(__name__)


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
    "Overseas fees 2027/28: GBP 48,600 per year".

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
              climate_class: str | None = None,
              country_programmes: bool = False):
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

    ``country_programmes`` (pet path only, round 9 R3): when no
    programme matched yet and the message names a country, that
    country's own verified programmes join the catalogue — one per
    top institution — plus a country summary source, so the model can
    never claim a covered country has no data. The pref-chat flow
    leaves this off: its country evidence is the climate-city list,
    pinned by its own tests.
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
    if countries:
        # Round 7 fix (live bug 2026-11-26): a country-selection turn
        # with no climate wish retrieved NO evidence at all, so the
        # model claimed "no verifiable data" for a country that has
        # programmes (Switzerland: Zurich 11, Lausanne 9). The chosen
        # countries' own cities join the catalogue with their actual
        # classes, whether or not a class was asked for. Only fires
        # when the caller scopes countries (the pref-chat flow);
        # answer() passes none, so the pet is unaffected.
        for city, n in _country_cities(countries):
            _add([_climate_source(city, n)])
    if country_programmes and not _match_programmes(_norm(message or "")):
        # Round 9 (R3): a country question with no matched programme
        # ("瑞士有哪些好学校？") retrieved nothing, so even the live
        # model could only say the country has no verified data —
        # while the results page showed 5 Swiss programmes. The
        # country's own programmes + a country summary source join
        # the catalogue here, so that claim can never be made again
        # for a covered country. Only fires on the pet path, only
        # when no specific programme was named (the template may
        # already have answered from the country list — its programme
        # is the top institution's, the picks below add the rest),
        # and never for a suggestion request (the suggest pick below
        # owns those).
        detected = _detect_country(message or "")
        if detected and _suggest_pick(message or "") is None:
            country_src = _country_source(detected)
            if country_src is not None:
                _add([country_src])
                for picked in _country_programme_picks(detected):
                    _add(_enriched_programme_sources(picked["id"]))
                    if picked["id"] not in pids:
                        pids.append(picked["id"])
                    iid = (picked.get("institution_id")
                           or V2_PROGRAM_INSTITUTION.get(picked["id"]))
                    if iid:
                        _add(ranking_sources(iid))
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
                 f"climate. Verified programmes in {city} "
                 f"(all levels and fields): {count}."))


# ---------------------------------------------------------------------------
# Country evidence (round 9, R3) — the pet's full-catalogue retrieval
#
# A country question used to retrieve nothing at all, so the model
# answered "no verified data" for Switzerland while the results page
# showed 5 Swiss programmes. These helpers give the model the
# country's own verified programmes (one per top institution) plus a
# country summary source whose count is scoped in the text itself:
# the TOTAL across all levels/fields, never a filtered sub-count.
# ---------------------------------------------------------------------------

def _country_programme_picks(country: str, limit: int = 3) -> list[dict]:
    """Up to ``limit`` programmes in a country, one per institution:
    institutions best QS rank first (no QS entry sorts last), each
    institution's first undergraduate programme, else first by id.
    Deterministic; a country with no verified programme yields []."""
    programmes = country_programmes(country)
    by_inst: dict[str, list[dict]] = {}
    for p in programmes:
        iid = p.get("institution_id") or V2_PROGRAM_INSTITUTION.get(p["id"])
        if iid:
            by_inst.setdefault(iid, []).append(p)
    ordered = sorted(
        by_inst.items(),
        key=lambda kv: (_qs_rank(kv[0]) if _qs_rank(kv[0]) is not None
                        else 10 ** 9,
                        kv[1][0].get("institution", "") or kv[0]))
    picks: list[dict] = []
    for _iid, own in ordered[:limit]:
        own.sort(key=lambda p: (0 if p.get("degree_level") == "undergraduate"
                                else 1, p["id"]))
        picks.append(own[0])
    return picks


def _country_source(country: str) -> Source | None:
    """One citable summary source for a country: total verified
    programme count (all levels and fields) + the picked programmes
    by name. None when the country has no verified programme."""
    programmes = country_programmes(country)
    picks = _country_programme_picks(country)
    if not programmes or not picks:
        return None
    name = country_display_name(country, "en")
    names = "; ".join(program_display_name(p) for p in picks)
    return Source(
        id=f"country:{country.lower()}",
        url=program_evidence_url(picks[0]),
        title=f"{name} verified programmes",
        excerpt=(f"{name}: {len(programmes)} verified programmes in total "
                 f"(all levels and fields). Including: {names}."))


# ---------------------------------------------------------------------------
# Source-aware fallback line (round 7 fix, 2026-11-26)
#
# When the model is genuinely unavailable but retrieval returned
# relevant climate evidence, the template fallback must say what the
# evidence shows instead of the generic "I don't know". The line is
# built deterministically from the retrieved climate sources only —
# never model text — city + actual class + verified programme count,
# at most 3 cities, in the user's locale.
# ---------------------------------------------------------------------------

_CLIMATE_LABEL_TO_CLASS = {"cool": "cool", "warm": "warm",
                          "four-season": "four_seasons", "mild": "mild"}
_CLIMATE_SOURCE_RE = re.compile(
    r"^(.+?): (cool|warm|four-season|mild) climate\. "
    r"Verified programmes in .+?: (\d+)\.$")
_CLASS_WORDS = {
    "en": {"cool": "cool", "warm": "warm", "four_seasons": "four-season",
           "mild": "mild"},
    "zh-CN": {"cool": "凉爽", "warm": "暖和", "four_seasons": "四季分明",
              "mild": "温和"},
    "es": {"cool": "frío", "warm": "cálido",
           "four_seasons": "de cuatro estaciones", "mild": "suave"},
    "fr": {"cool": "froid", "warm": "chaud",
           "four_seasons": "quatre saisons", "mild": "doux"},
    "pt-BR": {"cool": "frio", "warm": "quente",
              "four_seasons": "de quatro estações", "mild": "ameno"},
    "ar": {"cool": "بارد", "warm": "حار", "four_seasons": "أربعة فصول",
           "mild": "معتدل"},
}
_EVIDENCE_CITIES_LINES = {
    "en": "The verified data lists these cities: {cities}.",
    "zh-CN": "已核实的数据里有这些城市：{cities}。",
    "es": "Los datos verificados incluyen estas ciudades: {cities}.",
    "fr": "Les données vérifiées listent ces villes : {cities}.",
    "pt-BR": "Os dados verificados listam estas cidades: {cities}.",
    "ar": "تتضمن البيانات الموثّقة هذه المدن: {cities}.",
}
# Round 9 (R4): every count in a chat evidence line is labelled
# with its scope — the city counts are ALL programmes in that city
# (all levels/fields), never a filtered sub-count, so "Zurich 14"
# in chat can never contradict "5 undergraduate-computing" on a
# results page: they count different scopes, and the label says so.
_CITY_ITEM = {
    "en": "{city} ({cls}, {n} programmes, all levels/fields)",
    "zh-CN": "{city}（{cls}，{n} 个项目，全部学位/方向）",
    "es": "{city} ({cls}, {n} programas, todos los niveles y campos)",
    "fr": "{city} ({cls}, {n} programmes, tous niveaux et domaines)",
    "pt-BR": "{city} ({cls}, {n} programas, todos os níveis e áreas)",
    "ar": "{city} ({cls}، {n} برنامجًا، جميع المستويات والمجالات)",
}


def evidence_cities_line(sources: list[Source], locale: str) -> str | None:
    """One deterministic line stating the retrieved climate cities and
    their actual classes, or None when no climate source was
    retrieved. Built only from the verified catalogue excerpts."""
    items: list[str] = []
    for s in sources:
        if not s.id.startswith("climate:"):
            continue
        m = _CLIMATE_SOURCE_RE.match(s.excerpt or "")
        if not m:
            continue
        city, label, count = m.group(1), m.group(2), m.group(3)
        cls = _CLIMATE_LABEL_TO_CLASS[label]
        words = _CLASS_WORDS.get(locale) or _CLASS_WORDS["en"]
        item_t = _CITY_ITEM.get(locale) or _CITY_ITEM["en"]
        items.append(item_t.format(city=city, cls=words[cls], n=count))
        if len(items) >= 3:
            break
    if not items:
        return None
    line_t = (_EVIDENCE_CITIES_LINES.get(locale)
              or _EVIDENCE_CITIES_LINES["en"])
    sep = "、" if locale == "zh-CN" else ", "
    return line_t.format(cities=sep.join(items))


_COUNTRY_SOURCE_RE = re.compile(
    r"^(.+?): (\d+) verified programmes in total "
    r"\(all levels and fields\)\. Including: (.+)\.$")
_COUNTRY_LINES = {
    "en": "Verified data for {country} lists {names} — {n} verified programmes in total (all levels and fields).",
    "zh-CN": "已核实的数据里，{country}有 {names}，共 {n} 个已验证项目（全部学位/方向）。",
    "es": "Los datos verificados de {country} incluyen {names}: {n} programas verificados en total (todos los niveles y campos).",
    "fr": "Les données vérifiées pour {country} listent {names} : {n} programmes vérifiés au total (tous niveaux et domaines).",
    "pt-BR": "Os dados verificados de {country} listam {names}: {n} programas verificados no total (todos os níveis e áreas).",
    "ar": "تتضمن البيانات الموثّقة لـ{country} {names}: {n} برنامجًا موثّقًا في المجموع (جميع المستويات والمجالات).",
}


def country_evidence_line(sources: list[Source], locale: str) -> str | None:
    """One deterministic line stating what the retrieved country
    summary shows — country name (localised), named programmes, and
    the total verified count scoped as all levels/fields — or None
    when no country source was retrieved. Built only from the
    verified catalogue, never model text."""
    for s in sources:
        if not s.id.startswith("country:"):
            continue
        m = _COUNTRY_SOURCE_RE.match(s.excerpt or "")
        if not m:
            continue
        code = s.id[len("country:"):].upper()
        country = country_display_name(code, locale)
        n, names = m.group(2), m.group(3)
        if locale == "zh-CN":
            names = names.replace("; ", "、")
        line_t = _COUNTRY_LINES.get(locale) or _COUNTRY_LINES["en"]
        return line_t.format(country=country, names=names, n=n)
    return None


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


def _template_result(template: dict, sources: list[Source],
                     locale: str = "en") -> dict:
    """Template answer, with the generic "I don't know" first line
    replaced by what the retrieved evidence actually shows when
    climate sources were retrieved (round 7 fix: the model being
    unavailable must not erase evidence already in hand). Any other
    template line is left exactly as the template wrote it."""
    lines = list(template["lines"])
    cities = evidence_cities_line(sources, locale)
    country = country_evidence_line(sources, locale)
    if cities is not None and lines and lines[0] == _t(locale, "unknown"):
        lines[0] = cities
    elif country is not None and lines and lines[0] == _t(locale, "unknown"):
        lines[0] = country
    return {"lines": lines,
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
    template, sources, pids = _retrieve(msg, loc, country_programmes=True)
    sources_out = [{"id": s.id, "url": s.url, "title": s.title} for s in sources]

    # (c) No key: the template assistant is the honest answer.
    if not provider.available:
        return _template_result(template, sources, loc)

    # (d) Key present: model over the retrieved sources only.
    # Timeouts (round 9 fix): live gateway calls took ~9-12 s each on
    # 2026-11-26, and the round-7 budgets (30 s first call + 20 s
    # repair) let one turn stack to ~50 s of silence — the worst
    # cause of the 10-45 s replies in the live re-test. A single
    # turn now gets 20 s first attempt + 15 s repair (35 s worst
    # case, still ~2x the observed call time); anything slower falls
    # back to the template instead of holding the user. The
    # event-loop blockage itself is fixed at the router (see
    # app/router_chat.py): the sync model call runs in a worker
    # thread, so a slow chat can no longer wedge /health or any
    # other endpoint.
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
    started = time.monotonic()
    try:
        result = provider.chat(messages, system=chat_system(loc), timeout_s=20.0)
    except ProviderError as e:
        logger.info("assistant/chat model call failed kind=%s latency_ms=%d",
                    e.kind, int((time.monotonic() - started) * 1000))
        return _template_result(template, sources, loc)
    parsed = _parse_model_json(result.text)
    if parsed is None:
        logger.info("assistant/chat model output unparsable latency_ms=%d",
                    int((time.monotonic() - started) * 1000))
        return _template_result(template, sources, loc)
    errors = _validate_chat_payload(parsed, sources, evidence_texts, loc)
    if errors:
        logger.info("assistant/chat model output failed validation errors=%d",
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
                system=chat_system(loc), timeout_s=15.0)
        except ProviderError as e:
            logger.info("assistant/chat repair call failed kind=%s latency_ms=%d",
                        e.kind, int((time.monotonic() - retry_started) * 1000))
            return _template_result(template, sources, loc)
        parsed2 = _parse_model_json(retry.text)
        if parsed2 is None:
            logger.info("assistant/chat repair output unparsable")
            return _template_result(template, sources, loc)
        errors2 = _validate_chat_payload(parsed2, sources, evidence_texts, loc)
        if errors2:
            logger.info("assistant/chat repair output failed validation errors=%d",
                        len(errors2))
            return _template_result(template, sources, loc)
        parsed = parsed2
    lines = _render_lines(parsed, loc, sources)
    # Defence in depth: a rendered line must never carry a raw URL, a
    # probability/guarantee, or key material — if it does, fall back.
    joined_lines = "\n".join(lines)
    if ("http://" in joined_lines or "https://" in joined_lines
            or "www." in joined_lines or check_no_forbidden(lines)
            or "sk-" in joined_lines.lower()):
        return _template_result(template, sources, loc)
    return {"lines": lines,
            "evidence_url": _resolve_evidence_url(parsed, sources),
            "ai_status": "available",
            "model": f"{result.provider}/{result.model}",
            "sources": sources_out}
