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
  plus — since the AI-visibility layer (W5) — a ranking-overview
  intent (one provider's top 100: top-3 institutions + a citable
  provider summary) when the message asks about a provider's ranking
  without naming an institution, and a programme-id intent (the
  explicit "Programme id <id>" marker) for the exact programme a
  page entry asks about. The template fallback states the
  ranking-overview top 3 / the exact programme's verified fee / the
  suggestion pick's fee deterministically when the template itself
  has no better answer, instead of the generic unknown; plus — since
  round 21 (W3) — a caller-supplied programme scope (the cards the
  user is looking at), so a deictic "this programme" question is
  answered from those programmes' verified facts instead of the
  blanket unknown;
- the model sees ONLY those retrieved sources, as an evidence catalogue
  in a JSON envelope (``{task: "chat", prompt_version, locale, message,
  history, evidence_catalog}``); its structured JSON output is validated
  by ``ai.grounding.check_model_output`` (id whitelist, numeric
  cross-check, no probabilities/guarantees, no raw URLs), with NO
  repair retry (round 10: one model call per turn, 15 s budget — a
  bad output falls back to the template at once instead of paying
  for a second call while the user waits); on any failure the
  template answer is returned;
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
                          _fmt, _ielts_fact, _match_programmes, _money,
                          _norm, _qs_rank, _t,
                          ask as assistant_ask, check_no_forbidden,
                          contains_personal_data, country_display_name,
                          country_programmes, fee_text,
                          program_display_name, program_evidence_url,
                          program_fee_range)
from ai.grounding import (FORBIDDEN_PATTERNS, Source,
                          check_model_output, difference_errors,
                          gaokao_sources, programme_fact_texts,
                          programme_sources, ranking_sources, resolve_url,
                          stated_differences)
from ai.locale_sep import join_list
from ai.prompts import PROMPT_VERSION, chat_system, devil_advocate_system
from ai.provider import ProviderAdapter, ProviderError
from app.ai_status_cache import model_skip_cached
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


def _clean_track(track) -> str | None:
    """Wizard track a chat question is asked under (undergraduate /
    taught_masters), or None when absent or invalid — an invalid value
    is dropped, never a 422 and never a match filter."""
    return track if track in ("undergraduate", "taught_masters") else None


# The frontend's saved-preferences context marker (frontend/src/lib/
# chat.ts savedPrefsContext, appended by CompassPet to the FIRST
# free-text turn only): "\nThe user's saved preferences from the
# eligibility check: ...". The model envelope keeps the full message
# (the model can use the context); retrieval and the template must
# see ONLY the user's verbatim question (see
# _strip_saved_prefs_context).
_SAVED_PREFS_MARKER = ("\nThe user's saved preferences from the "
                       "eligibility check: ")


def _strip_saved_prefs_context(message: str) -> str:
    """The user's verbatim question, without the frontend's appended
    saved-preferences context.

    Round 24 (W1): the context is English free text ("countries: CH;
    climate: cool") appended to the user's question, and the template
    matcher reads the WHOLE string as the question — the context
    words corrupt the degree-phrase extraction ("computer science
    saved preferences eligibility check countries ch climate cool"
    matches no degree name), so a fee question with a saved profile
    answered the blanket unknown and the climate-cities line hijacked
    the reply (Edinburgh / Durham / Lund for an ETH question),
    while the same question without a profile reached the ambiguous
    line. The same corruption broke greetings ("你好" + context is
    longer than the 12-character greeting cap). Retrieval and the
    template therefore match on the stripped question; the model
    envelope (built in answer() from the raw message) still carries
    the context. A message without the marker is returned unchanged
    — pref-chat and every other caller are unaffected."""
    idx = (message or "").find(_SAVED_PREFS_MARKER)
    return message[:idx] if idx >= 0 else message


def _retrieve(message: str, locale: str, *, countries: list[str] | None = None,
              climate_class: str | None = None,
              country_programmes: bool = False,
              program_ids: list[str] | None = None,
              track: str | None = None):
    """(template ask() result, retrieved sources, programme ids).

    Retrieval reuses the template assistant: its ``ask()`` already does
    the programme fee/IELTS/deadline match and the rank lookup, and its
    ``_match_programmes`` covers the ambiguous two-programme case where
    ``ask()`` returns no single programme. Gaokao keywords add the
    verified Gaokao-route facts for the matched programme (or the
    general routes when no programme matched).

    ``program_ids`` (Round 21, W3) is caller-supplied scope — the
    programme cards the user is looking at (RecChat's visible batch).
    Those programmes' verified sources join the catalogue so a deictic
    "this programme" question can be answered from the same verified
    facts the detail page's "Programme id" marker retrieves. The scope
    ids are deliberately NOT added to the returned ``pids``: the
    suggestion pick and the ranking overview below gate on "no
    programme matched", and scope is context, not a match — adding it
    there would stop a suggestion question in the same chat from ever
    getting its pick.

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

    ``track`` (Round 22, W2) is the wizard track the question is asked
    under (undergraduate / taught_masters): programme matching — the
    template's own match and the scope narrowing — filters by it, so
    an undergraduate profile can never match an MSc programme.

    Round 24 (W1): the message is stripped of the frontend's appended
    saved-preferences context before ANY matching or retrieval (see
    _strip_saved_prefs_context) — the context is for the model
    envelope only, which answer() builds from the raw message.
    """
    message = _strip_saved_prefs_context(message)
    # (Round 26, W3) Rank intent, decided once from the stripped
    # message: the scope loop below only offers ranking sources to
    # the model when the question actually asks about ranks. A fee
    # question used to receive ETH's QS/THE/ARWU facts alongside the
    # fee facts, and the model could answer the fee question with
    # the rankings line — nothing pinned the answer type to the
    # question's intent (re-test task 20: the same fee question
    # asked a 5th time came back as the rankings line).
    _wants_rank = any(w in _norm(message or "") for w in _RANK_WORDS)
    track = _clean_track(track)
    scope_ids = _clean_program_ids(program_ids)
    template = assistant_ask(message, locale, track=track)
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
        for pid in _match_programmes(_norm(message or ""),
                                     scope_ids=scope_ids, track=track):
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
    # Round 23 W4: a climate question naming a city (no class word)
    # retrieves that city's own verified climate source, so the
    # normal template can state its actual class instead of the
    # blanket unknown. _add dedupes by source id, so a city the
    # class evidence (or the devil path) already added is not
    # repeated; the city source alone joins — no programme is added
    # to pids, so suggestion / scope behaviour is untouched.
    if _asks_about_climate(message or ""):
        named_city = _detect_climate_city(message or "")
        if named_city:
            _add([_climate_source(named_city,
                                  _city_programme_count(named_city))])
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
    if country_programmes and not _match_programmes(
            _norm(message or ""), scope_ids=scope_ids, track=track):
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
    # (AI visibility layer, W5) Programme-id intent: a page entry
    # sends the explicit marker "Programme id <id>" so the exact
    # programme's verified sources join the catalogue even when the
    # template's alias match is ambiguous — an expansion programme
    # shares its institution alias with every sibling programme.
    # That institution's ranks join too, for the model to cite —
    # whether or not the programme was already matched above.
    id_pid = _detect_programme_id(message or "")
    if id_pid:
        if id_pid not in pids:
            _add(_enriched_programme_sources(id_pid))
            pids.append(id_pid)
        own = _verified_programme(id_pid) or {}
        iid = own.get("institution_id") or V2_PROGRAM_INSTITUTION.get(id_pid)
        if iid:
            _add(ranking_sources(iid))
    # (Round 21, W3) Caller-supplied programme scope: the visible
    # cards' verified sources join the catalogue — the same enriched
    # sources the "Programme id" intent above brings — so the model
    # path and the template fallback can answer a deictic "this
    # programme" question from verified facts. The scope ids stay out
    # of ``pids`` (see the docstring): they are context, not a match.
    for pid in scope_ids:
        _add(_enriched_programme_sources(pid))
        if _wants_rank:
            own = _verified_programme(pid) or {}
            iid = own.get("institution_id") or V2_PROGRAM_INSTITUTION.get(pid)
            if iid:
                _add(ranking_sources(iid))
    # (AI visibility layer, W5) Ranking-overview intent: a question
    # about one provider's top 100 with no single institution named
    # ("Explain the QS 2027 ranking") has no rank lookup to answer
    # it, so the provider's top-3 institutions + a citable provider
    # summary join the catalogue. A specific-institution question
    # keeps its rank lookup (template institution_id / pids set).
    if not pids and not template.get("institution_id"):
        provider = _detect_ranking_provider(message or "")
        if provider:
            _add(_ranking_overview_sources(provider))
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


# Round 23 W4: a climate question naming a city but no climate class
# ("苏黎世的气候怎么样？") retrieved nothing — _detect_climate_class
# needs a class word, and _detect_country knows countries, not cities —
# so the normal template answered the blanket unknown while the devil
# path (scoped to the profile's countries/climate) answered with the
# conflict line. A question that asks about climate and names a
# climate-table city now retrieves that city's own verified climate
# source, so the normal path states its actual class through the
# existing evidence_cities_line replacement. Only the named city, and
# only for a climate question — a general question naming the city
# ("苏黎世有什么好玩的？") retrieves nothing extra.
_CLIMATE_QUESTION_WORDS = ("气候", "天气", "climate", "clima", "climat",
                          "météo", "meteo", "weather", "مناخ", "طقس")


def _asks_about_climate(message: str) -> bool:
    """True when a message asks about climate/weather (any locale)."""
    msg = _norm(message or "")
    return any(w in msg for w in _CLIMATE_QUESTION_WORDS)


def _detect_climate_city(message: str) -> str | None:
    """Canonical climate-table city a message names, or None. Matches
    the canonical English name and the localised names in
    _CITY_NAMES (e.g. 苏黎世 -> Zurich), longest first so a longer
    city name wins over a shorter word inside it; short Latin names
    match on word boundaries only, as _detect_country does."""
    msg = _norm(message or "")
    names: dict[str, str] = {}
    for city in CLIMATE:
        names.setdefault(city.lower(), city)
        for loc_name in _CITY_NAMES.get(city, {}).values():
            names.setdefault(loc_name.lower(), city)
    for alias, city in sorted(names.items(), key=lambda kv: -len(kv[0])):
        if alias.isascii() and len(alias) <= 4:
            if re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", msg):
                return city
        elif alias in msg:
            return city
    return None


def _city_programme_count(city: str) -> int:
    """Verified programmes in a climate-table city (all levels/fields),
    counted the same way as the climate evidence — the count the
    climate source carries."""
    n = 0
    for program in list(PROGRAMS.values()) + list(EXPANSION_PROGRAMS.values()):
        if _table_city(program.get("city")) == city:
            n += 1
    return n


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
# Localised city names (Round 15, Finding 2): the deterministic chat
# lines below used to interpolate the canonical English city name
# ("Zurich", "Lausanne") into every locale, so a Chinese devil reply
# read "Zurich（四季分明，14 个项目…）". The table mirrors the
# frontend's own locale files (frontend/messages/*/city.* — the same
# keys localisedCityName/cityDisplayName read there), keeping only the
# locales where the name differs from the canonical English form; any
# other locale, and any city absent here, renders as the canonical
# name — never a guessed translation. "ETH Zurich" / "University of
# Zurich" are institution proper nouns, not city names, and stay as
# they are.
_CITY_NAMES: dict[str, dict[str, str]] = {
    "Adelaide": {"zh-CN": "阿德莱德"},
    "Amsterdam": {"zh-CN": "阿姆斯特丹"},
    "Ann Arbor": {"zh-CN": "安娜堡"},
    "Auckland": {"zh-CN": "奥克兰"},
    "Austin": {"zh-CN": "奥斯汀"},
    "Baltimore": {"zh-CN": "巴尔的摩"},
    "Beijing": {"es": "Pekín", "fr": "Pékin", "pt-BR": "Pequim", "zh-CN": "北京"},
    "Berkeley": {"zh-CN": "伯克利"},
    "Berlin": {"es": "Berlín", "pt-BR": "Berlim", "zh-CN": "柏林"},
    "Birmingham": {"zh-CN": "伯明翰"},
    "Boston": {"zh-CN": "波士顿"},
    "Brisbane": {"zh-CN": "布里斯班"},
    "Bristol": {"zh-CN": "布里斯托尔"},
    "Buenos Aires": {"zh-CN": "布宜诺斯艾利斯"},
    "Cambridge": {"zh-CN": "剑桥"},
    "Canberra": {"zh-CN": "堪培拉"},
    "Champaign": {"zh-CN": "香槟"},
    "Chicago": {"zh-CN": "芝加哥"},
    "Copenhagen": {"es": "Copenhague", "fr": "Copenhague", "pt-BR": "Copenhague", "zh-CN": "哥本哈根"},
    "Coventry": {"zh-CN": "考文垂"},
    "Daejeon": {"zh-CN": "大田"},
    "Delft": {"zh-CN": "代尔夫特"},
    "Dublin": {"es": "Dublín", "pt-BR": "Dublim", "zh-CN": "都柏林"},
    "Durham": {"zh-CN": "杜伦"},
    "Edinburgh": {"es": "Edimburgo", "fr": "Édimbourg", "pt-BR": "Edimburgo", "zh-CN": "爱丁堡"},
    "Edmonton": {"zh-CN": "埃德蒙顿"},
    "Evanston": {"zh-CN": "埃文斯顿"},
    "Glasgow": {"zh-CN": "格拉斯哥"},
    "Hangzhou": {"zh-CN": "杭州"},
    "Heidelberg": {"zh-CN": "海德堡"},
    "Hong Kong": {"zh-CN": "香港"},
    "Ithaca": {"zh-CN": "伊萨卡"},
    "Kowloon Tong": {"zh-CN": "九龙塘"},
    "Kuala Lumpur": {"zh-CN": "吉隆坡"},
    "Kyoto": {"es": "Kioto", "pt-BR": "Quioto", "zh-CN": "京都"},
    "Lausanne": {"zh-CN": "洛桑"},
    "Leeds": {"zh-CN": "利兹"},
    "Leuven": {"zh-CN": "鲁汶"},
    "London": {"es": "Londres", "fr": "Londres", "pt-BR": "Londres", "zh-CN": "伦敦"},
    "Los Angeles": {"es": "Los Ángeles", "zh-CN": "洛杉矶"},
    "Lund": {"zh-CN": "隆德"},
    "Manchester": {"zh-CN": "曼彻斯特"},
    "Melbourne": {"zh-CN": "墨尔本"},
    "Milan": {"es": "Milán", "pt-BR": "Milão", "zh-CN": "米兰"},
    "Montreal": {"fr": "Montréal", "zh-CN": "蒙特利尔"},
    "Munich": {"es": "Múnich", "pt-BR": "Munique", "zh-CN": "慕尼黑"},
    "Nanjing": {"es": "Nankín", "fr": "Nankin", "pt-BR": "Nanquim", "zh-CN": "南京"},
    "New Haven": {"zh-CN": "纽黑文"},
    "New York": {"es": "Nueva York", "pt-BR": "Nova York", "zh-CN": "纽约"},
    "Nottingham": {"zh-CN": "诺丁汉"},
    "Orsay": {"zh-CN": "奥赛"},
    "Oxford": {"zh-CN": "牛津"},
    "Palaiseau": {"zh-CN": "帕莱索"},
    "Paris": {"es": "París", "zh-CN": "巴黎"},
    "Pasadena": {"zh-CN": "帕萨迪纳"},
    "Perth": {"zh-CN": "珀斯"},
    "Philadelphia": {"es": "Filadelfia", "pt-BR": "Filadélfia", "zh-CN": "费城"},
    "Pittsburgh": {"zh-CN": "匹兹堡"},
    "Princeton": {"zh-CN": "普林斯顿"},
    "Providence": {"zh-CN": "普罗维登斯"},
    "San Diego": {"zh-CN": "圣迭戈"},
    "Seattle": {"zh-CN": "西雅图"},
    "Seoul": {"es": "Seúl", "fr": "Séoul", "pt-BR": "Seul", "zh-CN": "首尔"},
    "Sha Tin": {"zh-CN": "沙田"},
    "Shanghai": {"es": "Shanghái", "pt-BR": "Xangai", "zh-CN": "上海"},
    "Sheffield": {"zh-CN": "谢菲尔德"},
    "Singapore": {"es": "Singapur", "fr": "Singapour", "pt-BR": "Singapura", "zh-CN": "新加坡"},
    "Stanford": {"zh-CN": "斯坦福"},
    "Stockholm": {"es": "Estocolmo", "pt-BR": "Estocolmo", "zh-CN": "斯德哥尔摩"},
    "Suita": {"zh-CN": "吹田"},
    "Sydney": {"es": "Sídney", "zh-CN": "悉尼"},
    "Taipei": {"es": "Taipéi", "pt-BR": "Taipé", "zh-CN": "台北"},
    "Tokyo": {"es": "Tokio", "pt-BR": "Tóquio", "zh-CN": "东京"},
    "Toronto": {"zh-CN": "多伦多"},
    "Uppsala": {"zh-CN": "乌普萨拉"},
    "Urbana-Champaign": {"zh-CN": "厄巴纳-香槟"},
    "Vancouver": {"zh-CN": "温哥华"},
    "Zurich": {"zh-CN": "苏黎世"},
}

def localised_city_name(city: str, locale: str) -> str:
    """Localised name for a canonical (English) climate-table city in
    ``locale``: the table above when it has an entry, the canonical
    name otherwise."""
    return _CITY_NAMES.get(city, {}).get(locale, city)


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
        items.append(item_t.format(city=localised_city_name(city, locale),
                                   cls=words[cls], n=count))
        if len(items) >= 3:
            break
    if not items:
        return None
    line_t = (_EVIDENCE_CITIES_LINES.get(locale)
              or _EVIDENCE_CITIES_LINES["en"])
    return line_t.format(cities=join_list(items, locale))


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
        # The excerpt is canonical English ("; "-joined); the rendered
        # line re-joins the names with the active locale's separator.
        names = join_list(names.split("; "), locale)
        line_t = _COUNTRY_LINES.get(locale) or _COUNTRY_LINES["en"]
        return line_t.format(country=country, names=names, n=n)
    return None


# ---------------------------------------------------------------------------
# AI-visibility intents (W5): the page entries in AiEntry send questions
# the old retrieval could not answer, so they get deterministic
# evidence + a deterministic template line each (the same precedent as
# the climate / country lines above: the model being unavailable must
# not erase evidence already in hand, and the line is built only from
# the verified catalogue, never model text).
#
# - ranking overview: "Explain the QS 2027 ranking" names no
#   institution, so the rank lookup has nothing to look up. The
#   provider's top-3 institutions (by verified rank number) plus one
#   citable provider summary source join the catalogue.
# - programme id: a programme-detail entry sends the explicit marker
#   "Programme id <id>" (the same precedent as the "country code XX"
#   marker) so the exact programme's sources join even when the
#   template's alias match is ambiguous — an expansion programme
#   shares its institution alias with every sibling programme.
# - suggestion: a recommendation question already retrieves the
#   cheapest verified pick (see _suggest_pick), but the template
#   answered it with the generic unknown. Its line states the pick
#   and its verified fee, with a within/above-budget verdict ONLY
#   when the fee and the budget share currency + period — a
#   cross-currency comparison never judges affordability.
# ---------------------------------------------------------------------------

_RANKING_PROVIDER_RES: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("qs", re.compile(r"\bqs\b")),
    ("arwu", re.compile(r"\barwu\b|软科")),
    # "the" alone is an ordinary English word: only the full name, the
    # Chinese name, or "THE <year>" counts as the provider.
    ("the", re.compile(r"times higher education|the world university|泰晤士|\bthe\s+\d{4}\b")),
)


def _detect_ranking_provider(message: str) -> str | None:
    """Ranking provider a message asks about (qs/the/arwu), or None.
    A rank word must be present, so "the 2027 entry" without any rank
    word never becomes a ranking question."""
    msg = _norm(message or "")
    if not any(w in msg for w in _RANK_WORDS):
        return None
    for provider, pat in _RANKING_PROVIDER_RES:
        if pat.search(msg):
            return provider
    return None


def _ranking_overview_sources(provider: str) -> list[Source]:
    """One citable summary source for a provider's top 100 (world
    ranks) — provider name + edition + the top 3 by verified rank
    number — plus the ranking sources of those top-3 institutions, so
    the model can cite individual ranks and the UI can link onward.
    [] when the provider is unknown or has no verified entry."""
    meta = next((p for p in RANKINGS.get("providers", [])
                 if p.get("id") == provider), None)
    if meta is None:
        return []
    ranked: list[tuple[int, dict]] = []
    for e in RANKINGS.get("entries", []):
        if e.get("provider") != provider:
            continue
        if e.get("verification_status") != "verified":
            continue
        try:
            num = int(str(e.get("rank_display", "")).lstrip("=").strip())
        except ValueError:
            continue
        ranked.append((num, e))
    ranked.sort(key=lambda ne: (ne[0], ne[1].get("institution_id", "")))
    top = ranked[:3]
    if not top:
        return []
    insts = {i.get("id"): i for i in RANKINGS.get("institutions", [])}
    items = "; ".join(
        f"#{e.get('rank_display')} "
        f"{(insts.get(e.get('institution_id')) or {}).get('official_name', e.get('institution_id'))}"
        for _num, e in top)
    name = meta.get("name", provider.upper())
    edition = meta.get("edition_label", "")
    sources = [Source(
        id=f"ranking-overview:{provider}",
        url=meta.get("entry_url"),
        title=f"{name} {edition} top 100",
        excerpt=(f"{name} {edition} top 100 (world ranks). "
                 f"Top 3: {items}."))]
    for _num, e in top:
        sources.extend(ranking_sources(e.get("institution_id")))
    return sources


_RANKING_OVERVIEW_RE = re.compile(
    r"^(.+) top 100 \(world ranks\)\. Top 3: (.+)\.$")
_RANKING_OVERVIEW_LINES = {
    "en": "{provider} {edition} top 3 (world ranks, top 100): {items}.",
    "zh-CN": "{provider} {edition}前 3 名（世界排名，前 100 名）：{items}。",
    "es": "Top 3 de {provider} {edition} (rankings mundiales, top 100): {items}.",
    "fr": "Top 3 {provider} {edition} (classements mondiaux, top 100) : {items}.",
    "pt-BR": "Top 3 de {provider} {edition} (rankings mundiais, top 100): {items}.",
    "ar": "أفضل 3 في {provider} {edition} (التصنيفات العالمية، أفضل 100): {items}.",
}


def ranking_overview_line(sources: list[Source], locale: str) -> str | None:
    """One deterministic line stating a provider's top 3 from the
    retrieved overview source — provider + edition + "Name (#rank)"
    items — or None when no overview source was retrieved. Built only
    from the verified catalogue excerpt, never model text."""
    for s in sources:
        if not s.id.startswith("ranking-overview:"):
            continue
        m = _RANKING_OVERVIEW_RE.match(s.excerpt or "")
        if not m:
            continue
        head, items_raw = m.group(1), m.group(2)
        parts = head.rsplit(" ", 1)
        if len(parts) == 2 and re.fullmatch(r"\d{4}", parts[1]):
            provider_name, edition = parts
        else:
            provider_name, edition = head, ""
        items: list[str] = []
        for raw in items_raw.split("; "):
            mm = re.match(r"^#(\S+)\s+(.+)$", raw)
            if mm:
                items.append(f"{mm.group(2)} (#{mm.group(1)})")
        if not items:
            continue
        line_t = (_RANKING_OVERVIEW_LINES.get(locale)
                  or _RANKING_OVERVIEW_LINES["en"])
        return line_t.format(provider=provider_name, edition=edition,
                             items=join_list(items, locale))
    return None


_PROGRAMME_ID_RE = re.compile(r"programme id ([a-z0-9][a-z0-9\-]*)")


def _detect_programme_id(message: str) -> str | None:
    """Verified programme id from the explicit "Programme id <id>"
    marker, or None when the marker is absent or the id is not in the
    verified catalogue (v2 + matchable expansion)."""
    m = _PROGRAMME_ID_RE.search(_norm(message or ""))
    if not m:
        return None
    pid = m.group(1)
    if pid in PROGRAMS or pid in EXPANSION_MATCHABLE:
        return pid
    return None


def _verified_programme(program_id: str) -> dict | None:
    """Verified programme dict (v2 or matchable expansion), or None."""
    return PROGRAMS.get(program_id) or EXPANSION_MATCHABLE.get(program_id)


_PROGRAMME_FEE_LINES = {
    "en": "{name}: fee {fee}.",
    "zh-CN": "{name}：学费{fee}。",
    "es": "{name}: matrícula {fee}.",
    "fr": "{name} : frais {fee}.",
    "pt-BR": "{name}: mensalidade {fee}.",
    "ar": "{name}: الرسوم {fee}.",
}
_PROGRAMME_FEE_UNKNOWN_LINES = {
    "en": "{name}: no fee is published in the verified data.",
    "zh-CN": "{name}：已核实的数据里没有公布学费。",
    "es": "{name}: no hay matrícula publicada en los datos verificados.",
    "fr": "{name} : aucun frais publié dans les données vérifiées.",
    "pt-BR": "{name}: nenhuma mensalidade publicada nos dados verificados.",
    "ar": "{name}: لا توجد رسوم منشورة في البيانات الموثّقة.",
}


def _programme_fact_line(program_id: str, locale: str) -> str | None:
    """One deterministic line for one verified programme: its official
    display name + verified fee, or the honest fee-unknown line when
    the catalogue publishes no fee. Never a guess."""
    prog = _verified_programme(program_id)
    if prog is None:
        return None
    name = program_display_name(prog)
    fr = program_fee_range(prog)
    if fr is None:
        line_t = (_PROGRAMME_FEE_UNKNOWN_LINES.get(locale)
                  or _PROGRAMME_FEE_UNKNOWN_LINES["en"])
        return line_t.format(name=name)
    line_t = (_PROGRAMME_FEE_LINES.get(locale)
              or _PROGRAMME_FEE_LINES["en"])
    return line_t.format(name=name, fee=fee_text(fr, locale))


# ---------------------------------------------------------------------------
# Caller-supplied programme scope (Round 21, W3)
#
# Root cause of the step-8 / detail-page inconsistency (re-test task
# 15): the SAME question — "What is the fee and IELTS requirement
# for this programme, and is it a good fit for me?" — got the
# verified fee line on the programme detail page but the blanket
# "这个我从已核实的数据里查不到，不知道。" in the step-8 (RecChat)
# chat. The detail page scopes its question with the explicit
# "Programme id <id>" marker, so _retrieve brings that programme's
# verified sources and _template_result states its fee. RecChat sent
# only {message, locale, history}: no programme was ever in scope,
# so a deictic "this programme" / "这个专业" question matched nothing
# — _match_programmes needs a name or alias in the text — and the
# template honestly answered unknown. The verified fee facts existed
# all along; the chat retrieval simply never queried them.
#
# The fix: callers that show programme cards (RecChat) pass the
# visible cards' ids as ``program_ids``. The ids are caller context,
# not user text — they only fill the gap the template itself leaves:
# they never override a programme the template already answered, and
# they never answer a question that is not about a programme fact
# (or a why-not question naming one). When the scope holds several
# programmes and the question names none of them, the refusal names
# them and asks which one, instead of the blanket unknown.
# ---------------------------------------------------------------------------

def _clean_program_ids(program_ids) -> list[str]:
    """Verified programme ids from caller-supplied scope: v2 +
    matchable expansion only, deduped, order preserved, at most 10.
    An unknown id is dropped, never a guess."""
    out: list[str] = []
    for pid in program_ids or []:
        if not isinstance(pid, str):
            continue
        pid = pid.strip()
        if (pid and pid not in out
                and (pid in PROGRAMS or pid in EXPANSION_MATCHABLE)):
            out.append(pid)
        if len(out) >= 10:
            break
    return out


def _scope_fact_line(program_id: str, message: str, locale: str) -> str | None:
    """One deterministic fact line for one in-scope programme, in the
    same wording the template assistant uses for a named programme
    (fee first, then IELTS, then deadline — the same order as
    ``assistant.ask``). Only verified data, never a guess."""
    prog = _verified_programme(program_id)
    if prog is None:
        return None
    name = program_display_name(prog)
    msg = _norm(message or "")
    if any(w in msg for w in _FEE_WORDS):
        return _programme_fact_line(program_id, locale)
    if any(w in msg for w in _IELTS_WORDS):
        fact = _ielts_fact(prog, locale)
        if fact is None:
            return _fmt("ask_ielts_unknown", locale, program=name)
        return _fmt("ask_ielts", locale, program=name, fact=fact)
    if any(w in msg for w in _DEADLINE_WORDS):
        deadline = prog.get("application_deadline")
        if not deadline:
            return _fmt("ask_deadline_unknown", locale, program=name)
        return _fmt("ask_deadline", locale, program=name, deadline=deadline)
    return None


_WHICH_ONE_LINES = {
    "en": "Which one do you mean — {names}? Name one and I'll answer from its verified data.",
    "zh-CN": "你问的是其中哪一门——{names}？说一门，我按它已核实的数据回答。",
    "es": "¿A cuál te refieres: {names}? Nombra uno y responderé con sus datos verificados.",
    "fr": "Duquel parlez-vous — {names} ? Nommez-en un et je répondrai à partir de ses données vérifiées.",
    "pt-BR": "A qual você se refere — {names}? Nomeie um e responderei com os dados verificados dele.",
    "ar": "أي برنامج تقصد — {names}؟ سمِّ واحدًا وسأجيب من بياناته الموثّقة.",
}

_WHY_REFUSAL_LINES = {
    "en": "You mean {names} — but why it isn't met needs a rule-by-rule check of your background, and this chat doesn't have that evaluation.",
    "zh-CN": "你问的是{names}——但它为什么不达标，要按你的背景逐项核对规则，聊天里没有这份逐项评估。",
    "es": "Te refieres a {names}, pero saber por qué no se cumple exige revisar tus antecedentes regla por regla, y este chat no tiene esa evaluación.",
    "fr": "Vous parlez de {names}, mais dire pourquoi ce n'est pas satisfait exige de vérifier votre profil règle par règle, et ce chat n'a pas cette évaluation.",
    "pt-BR": "Você se refere a {names}, mas saber por que não foi atendido exige conferir seu perfil regra por regra, e este chat não tem essa avaliação.",
    "ar": "تقصد {names} — لكن معرفة سبب عدم الاستيفاء تتطلب فحص خلفيتك قاعدةً قاعدة، وهذه المحادثة لا تملك ذلك التقييم.",
}

# Why-not words (a "why isn't it met" question). The refusal below
# only fires for these — a bare "why" ("为什么瑞士？") names no
# programme failure and keeps the honest generic unknown.
_WHY_WORDS = ("为什么", "为何", "为啥", "why")
_WHY_NOT_MET_WORDS = ("不达标", "达不到", "没通过", "不通过", "不符合",
                      "not met", "why not", "why isn't", "why doesn't",
                      "why is it not", "fail")


def _scope_names_line(candidates: list[str], locale: str,
                      lines: dict[str, str]) -> str:
    """Programme display names for a scope line: at most 3, joined
    with the locale's list separator."""
    names = [program_display_name(_verified_programme(pid))
             for pid in candidates[:3]]
    line_t = lines.get(locale) or lines["en"]
    return line_t.format(names=join_list(names, locale))


def _scope_line(scope_ids: list[str], message: str, lines: list[str],
                template: dict, locale: str,
                track: str | None = None) -> tuple[str | None, list[str]]:
    """Deterministic first line for a question about a programme the
    caller has in scope, plus the candidate programme ids the line is
    about — (line, candidates); (None, []) when the scope must not
    answer it.

    - Fact question (fee / IELTS / deadline) + exactly one candidate
      programme in scope -> that programme's verified fact line (the
      same line the detail page's marker path states).
    - Fact question + several candidates and the template said unknown
      -> a which-one line naming them, not the blanket unknown.
    - Why-not question about an in-scope programme -> a specific
      refusal naming the programme(s) and the missing piece (the
      rule-by-rule evaluation is not in this chat). The question
      genuinely has no verified answer here; only the refusal gets
      specific.
    - Anything else (rank / climate / suggestion / country question,
      or the template already answered a programme) -> None: the
      scope never hijacks those, and never overrides a template
      answer. ``candidates`` narrows the template's own alias match
      to the scope: naming ETH matches two undergraduate siblings,
      so the scope disambiguates only when exactly one of them is
      in view.

    Round 24 (W1): the candidates travel with a fact / which-one
    line so the caller keeps the disambiguation live (a which-one
    reply without them would drop the caller's pending state and its
    level chips). The why refusal carries none: it is not a level
    disambiguation, and its candidates must not keep level chips up.

    ``track`` (Round 22, W2): the wizard track — candidates are
    filtered by it, and the match itself (localised display titles
    included) runs with it, so an undergraduate profile can never
    be answered from an MSc programme in scope."""
    msg = _norm(message or "")
    if not scope_ids or template.get("program_id") is not None:
        return None, []
    track = _clean_track(track)
    matched = _match_programmes(msg, scope_ids=scope_ids, track=track)
    if matched:
        candidates = [pid for pid in matched if pid in scope_ids]
        if not candidates:
            return None, []
    else:
        candidates = list(scope_ids)
    if track is not None:
        candidates = [pid for pid in candidates
                      if (_verified_programme(pid) or {}).get("degree_level")
                      == track]
        if not candidates:
            return None, []
    unknown_first = bool(lines) and lines[0] == _t(locale, "unknown")
    # The template's ambiguous-programme line is only reachable when
    # the message carries no rank word (the rank branch answers
    # first in assistant.ask); without that guard a rank+fee
    # question's rank answer would be replaced by a fee line.
    # "Ambiguous" also covers the template failing to answer at all
    # without saying unknown — i.e. its ambiguous-programme line:
    # the display-title match may have narrowed to one programme in
    # scope while the template's own global match stayed ambiguous
    # (Round 22, W2: a shared Chinese degree name with no institution
    # token is ambiguous globally but unique in the visible batch).
    # program_id is None here (the early return above), so a
    # non-unknown first line can only be that ambiguous line.
    ambiguous = (len(matched) > 1 or not unknown_first) and not any(
        w in msg for w in _RANK_WORDS)
    if any(w in msg for w in _FEE_WORDS + _IELTS_WORDS + _DEADLINE_WORDS):
        if len(candidates) == 1 and (unknown_first or ambiguous):
            return _scope_fact_line(candidates[0], message, locale), list(candidates)
        if len(candidates) > 1 and unknown_first:
            return _scope_names_line(candidates, locale, _WHICH_ONE_LINES), list(candidates)
        return None, []
    if (any(w in msg for w in _WHY_WORDS)
            and any(w in msg for w in _WHY_NOT_MET_WORDS)
            and unknown_first):
        return _scope_names_line(candidates, locale, _WHY_REFUSAL_LINES), []
    return None, []



_SUGGEST_PERIOD_WORDS = {
    "en": {"per_year": "per year", "total": "in total"},
    "zh-CN": {"per_year": "每年", "total": "总计"},
    "es": {"per_year": "al año", "total": "en total"},
    "fr": {"per_year": "par an", "total": "au total"},
    "pt-BR": {"per_year": "por ano", "total": "no total"},
    "ar": {"per_year": "سنويًا", "total": "إجمالًا"},
}
_SUGGEST_LINES = {
    "en": "Verified suggestion — {level} in {country}: {name}, fee {fee}.",
    "zh-CN": "已核实推荐——{country}{level}：{name}，学费{fee}。",
    "es": "Sugerencia verificada: {level} en {country}: {name}, matrícula {fee}.",
    "fr": "Suggestion vérifiée : {level} en {country} : {name}, frais {fee}.",
    "pt-BR": "Sugestão verificada: {level} em {country}: {name}, mensalidade {fee}.",
    "ar": "اقتراح موثّق — {level} في {country}: {name}، الرسوم {fee}.",
}
_SUGGEST_WITHIN_LINES = {
    "en": "Verified suggestion — {level} in {country}: {name}, fee {fee}, within your {currency} {amount} {period} budget.",
    "zh-CN": "已核实推荐——{country}{level}：{name}，学费{fee}，在你{currency} {amount}{period}的预算内。",
    "es": "Sugerencia verificada: {level} en {country}: {name}, matrícula {fee}, dentro de tu presupuesto de {currency} {amount} {period}.",
    "fr": "Suggestion vérifiée : {level} en {country} : {name}, frais {fee}, dans votre budget de {currency} {amount} {period}.",
    "pt-BR": "Sugestão verificada: {level} em {country}: {name}, mensalidade {fee}, dentro do seu orçamento de {currency} {amount} {period}.",
    "ar": "اقتراح موثّق — {level} في {country}: {name}، الرسوم {fee}، ضمن ميزانيتك البالغة {currency} {amount} {period}.",
}
_SUGGEST_ABOVE_LINES = {
    "en": "Verified suggestion — {level} in {country}: {name}, fee {fee}, above your {currency} {amount} {period} budget.",
    "zh-CN": "已核实推荐——{country}{level}：{name}，学费{fee}，高于你{currency} {amount}{period}的预算。",
    "es": "Sugerencia verificada: {level} en {country}: {name}, matrícula {fee}, por encima de tu presupuesto de {currency} {amount} {period}.",
    "fr": "Suggestion vérifiée : {level} en {country} : {name}, frais {fee}, au-dessus de votre budget de {currency} {amount} {period}.",
    "pt-BR": "Sugestão verificada: {level} em {country}: {name}, mensalidade {fee}, acima do seu orçamento de {currency} {amount} {period}.",
    "ar": "اقتراح موثّق — {level} في {country}: {name}، الرسوم {fee}، أعلى من ميزانيتك البالغة {currency} {amount} {period}.",
}


def _suggestion_line(program_id: str, message: str, locale: str) -> str | None:
    """One deterministic line for a suggestion pick: the verified
    programme + its fee, with a within/above-budget verdict ONLY when
    fee and budget share currency + period (same rule as
    fee_fit: a range straddling the ceiling, or a cross-currency
    budget, gets no verdict — the fee alone). None when the level or
    country cannot be read from the message."""
    prog = _verified_programme(program_id)
    if prog is None:
        return None
    level = _detect_level(message)
    country = _detect_country(message)
    if level is None or country is None:
        return None
    name = program_display_name(prog)
    fr = program_fee_range(prog)
    if fr is None:
        return _programme_fact_line(program_id, locale)
    level_name = _t(locale, f"level_{level}")
    country_name = country_display_name(country, locale)
    fee = fee_text(fr, locale)
    ceiling = _parse_ceiling(message)
    verdict: str | None = None
    if ceiling is not None:
        currency, amount, period = ceiling
        if fr[2] == currency and fr[3] == period:
            if fr[1] <= amount:
                verdict = "within"
            elif fr[0] > amount:
                verdict = "above"
    words = (_SUGGEST_PERIOD_WORDS.get(locale)
             or _SUGGEST_PERIOD_WORDS["en"])
    if verdict == "within" and ceiling is not None:
        line_t = (_SUGGEST_WITHIN_LINES.get(locale)
                  or _SUGGEST_WITHIN_LINES["en"])
        return line_t.format(level=level_name, country=country_name,
                             name=name, fee=fee, currency=ceiling[0],
                             amount=_money(ceiling[1]),
                             period=words[ceiling[2]])
    if verdict == "above" and ceiling is not None:
        line_t = (_SUGGEST_ABOVE_LINES.get(locale)
                  or _SUGGEST_ABOVE_LINES["en"])
        return line_t.format(level=level_name, country=country_name,
                             name=name, fee=fee, currency=ceiling[0],
                             amount=_money(ceiling[1]),
                             period=words[ceiling[2]])
    line_t = _SUGGEST_LINES.get(locale) or _SUGGEST_LINES["en"]
    return line_t.format(level=level_name, country=country_name,
                         name=name, fee=fee)


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
                           locale: str,
                           allowed_differences: frozenset[int] | None = None
                           ) -> list[str]:
    """All validation errors for one structured model output (empty =
    valid). check_model_output covers claims/actions; the summary and
    action explanations get the extra safety scan as well.
    ``allowed_differences`` is the set of engine-computed differences
    the model may state (devil chat); None disables difference
    checking. A wrong difference hides in the summary just as easily
    as in a claim, so the summary and action explanations are checked
    for it too — the safety scan alone cannot see it (small integers
    are not cross-checked, and a wrong difference is a substring of
    its own operands)."""
    check = check_model_output(
        payload, allowed_evidence_ids=set(evidence_texts),
        allowed_rule_ids=set(), rule_status={},
        evidence_texts=evidence_texts, locale=locale,
        allowed_differences=allowed_differences)
    errors = list(check.errors)
    joined = " ".join(evidence_texts.values())
    summary = payload.get("summary")
    if isinstance(summary, str) and summary.strip():
        errors.extend(_safety_errors(summary, joined))
        errors.extend(difference_errors(summary, allowed_differences))
    for action in payload.get("actions") or []:
        if isinstance(action, dict) and isinstance(action.get("explanation"), str):
            errors.extend(_safety_errors(action["explanation"], joined))
            errors.extend(
                difference_errors(action["explanation"], allowed_differences))
    return errors


def _devil_allowed_differences(conflicts: list[dict]) -> frozenset[int]:
    """Engine-computed differences the devil's model reply may state:
    every pairwise absolute difference between the listed city counts
    of each climate conflict. A difference between any other pair of
    numbers is not in the set and is rejected — the model must state
    counts separately instead. Empty when no climate conflict lists
    two cities: then no difference may be stated at all."""
    diffs: set[int] = set()
    for conflict in conflicts:
        if conflict.get("kind") != "climate":
            continue
        counts = [n for _city, _cls, n in conflict.get("cities") or []]
        for i in range(len(counts)):
            for j in range(i + 1, len(counts)):
                diffs.add(abs(counts[i] - counts[j]))
    return frozenset(diffs)


def _model_lines_match_intent(lines: list[str], template: dict,
                              message: str, locale: str) -> bool:
    """True when a validated model reply answers the fact type the
    question asks about (Round 26, W3 — defence in depth behind the
    intent-gated catalogue in _retrieve).

    Fee/IELTS/deadline/rank intents are read exactly as ask() reads
    them. A reply that states a different fact type (e.g. the ranks
    for a fee question) fails, so the deterministic template answers
    instead. Unknown-intent questions always pass, and the check only
    fires when the template itself resolved a programme with a fee —
    so an ambiguous or fee-unknown question is unaffected and the
    Oxford-style multi-programme model answers (Round 6 pin) are
    untouched. First pass covers the fee intent only.

    The comparison is on the fee FIGURE (digits, commas stripped),
    not on the full fee_text string: fee_text carries a qualifier
    suffix ("GBP 48,600 per year (overseas)") that a correctly
    grounded model line ("... overseas tuition is GBP 48,600 per
    year.") does not repeat, and the exact-substring form wrongly
    rejected it (test_ai_chat mock-grounded tests).
    """
    msg = _norm(_strip_saved_prefs_context(message or ""))
    if any(w in msg for w in _FEE_WORDS) and template.get("program_id"):
        prog = _verified_programme(template["program_id"])
        fr = program_fee_range(prog) if prog else None
        if fr is not None:
            figures = [n.replace(",", "")
                       for n in re.findall(r"\d[\d,]*", fee_text(fr, locale))]
            if figures:
                joined = "\n".join(lines).replace(",", "")
                return any(fig in joined for fig in figures)
    return True


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
            # Round 19 (W1): when the last rendered line already
            # closes with an engine-checked difference statement
            # (devil replies: "相差3项。" / "3 more …"), the
            # "next" line must not follow it — the difference is
            # the reply's closing sentence. Detection uses the
            # same patterns as the difference checker, so this
            # covers en/zh; the other locales have no checker
            # patterns yet (pre-existing gap, Round 17).
            if not (lines and stated_differences(lines[-1])):
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
                     locale: str = "en", *, programme_id: str | None = None,
                     message: str = "",
                     scope_program_ids: list[str] | None = None,
                     track: str | None = None) -> dict:
    """Template answer, with the generic "I don't know" first line
    replaced by what the retrieved evidence actually shows when
    climate sources were retrieved (round 7 fix: the model being
    unavailable must not erase evidence already in hand). Any other
    template line is left exactly as the template wrote it.

    AI-visibility layer (W5): the same replacement covers the new
    intents, most specific first — the exact programme's fee line
    (when the template did not already answer that same programme),
    the ranking-overview top-3 line (replacing the unknown, the
    "tell me which institution" line, or the ambiguous-institutions
    line — the overview question deliberately names none of them),
    the suggestion pick's line — then the climate / country
    lines as before. Only the first line is ever replaced.

    Round 21 (W3): ``scope_program_ids`` — the caller-supplied
    programme scope (RecChat's visible cards) — sits between the
    marker line and the ranking line: a fact question about an
    in-scope programme gets that programme's verified fact line (the
    same line the detail page states), several in-scope programmes
    get the which-one line, and a why-not question about an in-scope
    programme gets the specific refusal naming it. Rank / climate /
    suggestion / country questions are never touched by the scope.
    """
    lines = list(template["lines"])
    prog_line = (_programme_fact_line(programme_id, locale)
                 if programme_id else None)
    rank_line = ranking_overview_line(sources, locale)
    scope_line, scope_candidates = (
        _scope_line(_clean_program_ids(scope_program_ids),
                    message, lines, template, locale, track=track)
        if scope_program_ids else (None, []))
    sugg_line: str | None = None
    if message:
        sugg_pid = _suggest_pick(message)
        if sugg_pid:
            sugg_line = _suggestion_line(sugg_pid, message, locale)
    unknown_first = bool(lines) and lines[0] == _t(locale, "unknown")
    evidence_url = template.get("evidence_url")
    replaced = False
    if (prog_line is not None and lines
            and template.get("program_id") != programme_id):
        lines[0] = prog_line
        replaced = True
    elif scope_line is not None and lines:
        lines[0] = scope_line
        replaced = True
    elif rank_line is not None and lines:
        # The overview sources only join when the template named no
        # single institution (see _retrieve), so the template's first
        # line here is the unknown, the "tell me which institution"
        # line, or the ambiguous-institutions line — the top-3 line
        # answers all three better.
        lines[0] = rank_line
        replaced = True
    elif sugg_line is not None and unknown_first:
        lines[0] = sugg_line
        replaced = True
    else:
        cities = evidence_cities_line(sources, locale)
        country = country_evidence_line(sources, locale)
        if cities is not None and unknown_first:
            lines[0] = cities
            # Round 23 W4: the cities line states verified facts, so
            # it needs its own evidence link — the climate source's
            # URL (previously the replaced line carried no link at
            # all, since only the prog/scope/rank/sugg branches set
            # `replaced`). The template's own evidence_url still wins
            # when it has one.
            if evidence_url is None:
                evidence_url = next((s.url for s in sources
                                     if s.id.startswith("climate:")
                                     and s.url), None)
        elif country is not None and unknown_first:
            lines[0] = country
            if evidence_url is None:
                evidence_url = next((s.url for s in sources
                                     if s.id.startswith("country:")
                                     and s.url), None)
    if replaced and evidence_url is None:
        # The replaced line states verified facts, so it needs a real
        # official link: the first retrieved source that has one (the
        # provider table for a ranking overview, the programme's own
        # official page otherwise).
        evidence_url = next((s.url for s in sources if s.url), None)
    result = {"lines": lines,
              "evidence_url": evidence_url,
              "ai_status": "unavailable", "model": None,
              "sources": [{"id": s.id, "url": s.url, "title": s.title}
                          for s in sources]}
    if template.get("candidates"):
        # Round 24 (W1): the template's ambiguous-programme line
        # resolves nothing on its own — the caller needs the matched
        # ids to carry the pending disambiguation forward (original
        # question + level answer, scoped to these ids). Only present
        # when the template itself was ambiguous.
        result["candidates"] = list(template["candidates"])
    elif scope_candidates:
        # Round 24 (W1): the scope's own re-ask (the which-one line
        # for an unrecognised level word) is a pending
        # disambiguation too — without the ids the caller would drop
        # its pending state and its level chips.
        result["candidates"] = list(scope_candidates)
    return result


# ---------------------------------------------------------------------------
# Devil's advocate (round 11): a second AI voice that challenges the
# user's stated preferences with verified facts.
#
# The conflicts are ENGINE-COMPUTED from the verified catalogue only —
# never invented, never model text. Three kinds:
# - climate: the wanted climate class has no city in a chosen country
#   (that country's listed cities carry their actual classes — the
#   PrefChat prototype: Switzerland's Zurich and Lausanne are
#   four-season, not cool);
# - no_programmes: no matchable programme in the chosen track/country;
# - budget: the cheapest verified programme in the track/country whose
#   fee is in the SAME currency + period as the budget costs more than
#   the budget. A cross-currency budget is never a mismatch: the FX
#   table (data/expansions/fx_rates.json) says a converted comparison
#   is approximate and can never judge a mismatch, so it stays unknown.
# A country with no climate-table city is likewise never a climate
# conflict. When no conflict is found the devil says so honestly.
# ---------------------------------------------------------------------------

_DEVIL_CLIMATES = ("warm", "cool", "four_seasons", "mild")
_DEVIL_LEVELS = ("undergraduate", "taught_masters")

_DEVIL_T: dict[str, dict[str, str]] = {
    "en": {
        "prefix": "Another angle: ",
        "climate": "{prefix}you want a {wanted} climate, but in {country} the verified data lists {cities} — no {wanted}-class city there. Climate is only a preference — it never decides eligibility, it only orders results.",
        "no_programmes": "{prefix}the verified catalogue lists no {level} programme in {country} yet, so that combination has no verified route.",
        "budget": "{prefix}the cheapest verified {level} programme in {country} costs {fee} — above your {currency} {amount} {period} budget.",
        "no_conflict": "I checked your preferences against the verified data and found no clash — nothing here contradicts itself.",
        "period_per_year": "per year",
        "period_total": "in total",
    },
    "zh-CN": {
        "prefix": "换个角度看：",
        "climate": "{prefix}你想要{wanted}气候，但已核实的数据里，{country}列出的城市是{cities}，其中没有{wanted}气候的城市。气候只是偏好，不影响资格，只影响排序。",
        "no_programmes": "{prefix}已核实的目录里，{country}还没有{level}专业，这个组合没有已核实的路线。",
        "budget": "{prefix}{country}最便宜的已核实{level}专业学费是{fee}，高于你{currency} {amount}{period}的预算。",
        "no_conflict": "我按已核实的数据核对了你的偏好，没有发现冲突。",
        "period_per_year": "每年",
        "period_total": "总计",
    },
    "es": {
        "prefix": "Otra mirada: ",
        "climate": "{prefix}quieres un clima {wanted}, pero en {country} los datos verificados listan {cities} — ninguna ciudad de clase {wanted}. El clima es solo una preferencia: nunca decide la elegibilidad, solo ordena los resultados.",
        "no_programmes": "{prefix}el catálogo verificado aún no lista ningún programa de {level} en {country}; esa combinación no tiene ruta verificada.",
        "budget": "{prefix}el programa verificado de {level} más barato en {country} cuesta {fee}, por encima de tu presupuesto de {currency} {amount} {period}.",
        "no_conflict": "Revisé tus preferencias con los datos verificados y no encontré contradicciones.",
        "period_per_year": "al año",
        "period_total": "en total",
    },
    "fr": {
        "prefix": "Autre angle : ",
        "climate": "{prefix}vous voulez un climat {wanted}, mais en {country} les données vérifiées listent {cities} — aucune ville de classe {wanted}. Le climat n'est qu'une préférence : il ne décide jamais de l'éligibilité, il ne fait qu'ordonner les résultats.",
        "no_programmes": "{prefix}le catalogue vérifié ne liste encore aucun programme de {level} en {country} ; cette combinaison n'a pas de route vérifiée.",
        "budget": "{prefix}le programme vérifié de {level} le moins cher en {country} coûte {fee}, au-dessus de votre budget de {currency} {amount} {period}.",
        "no_conflict": "J'ai vérifié vos préférences avec les données vérifiées : aucune contradiction.",
        "period_per_year": "par an",
        "period_total": "au total",
    },
    "pt-BR": {
        "prefix": "Outro ângulo: ",
        "climate": "{prefix}você quer um clima {wanted}, mas em {country} os dados verificados listam {cities} — nenhuma cidade de classe {wanted}. O clima é só uma preferência: nunca decide a elegibilidade, só ordena os resultados.",
        "no_programmes": "{prefix}o catálogo verificado ainda não lista nenhum programa de {level} em {country}; essa combinação não tem rota verificada.",
        "budget": "{prefix}o programa verificado de {level} mais barato em {country} custa {fee}, acima do seu orçamento de {currency} {amount} {period}.",
        "no_conflict": "Conferi suas preferências com os dados verificados e não encontrei contradições.",
        "period_per_year": "por ano",
        "period_total": "no total",
    },
    "ar": {
        "prefix": "من زاوية أخرى: ",
        "climate": "{prefix}تريد مناخًا {wanted}، لكن البيانات الموثّقة في {country} تدرج {cities} — ولا مدينة من فئة {wanted}. المناخ مجرد تفضيل — لا يقرر الأهلية أبدًا، بل يرتّب النتائج فقط.",
        "no_programmes": "{prefix}لا يدرج الكتالوج الموثّق أي برنامج {level} في {country} بعد؛ هذا المزيج بلا مسار موثّق.",
        "budget": "{prefix}أرخص برنامج {level} موثّق في {country} تكلفته {fee} — أعلى من ميزانيتك البالغة {currency} {amount} {period}.",
        "no_conflict": "راجعت تفضيلاتك مع البيانات الموثّقة ولم أجد أي تعارض.",
        "period_per_year": "سنويًا",
        "period_total": "إجمالًا",
    },
}


# Round 17 (W2): the offline template states the engine-computed
# difference too. Re-test task 11 found the template listing 14 and
# 11 with NO difference at all — the comparison answer was missing
# in the common model-down case. The sentence below uses ONLY the
# engine-computed ``count_difference`` carried on the conflict (the
# top-two difference, set in ``devil_conflicts``); the template never
# subtracts. It names the top two listed cities (``_country_cities``
# sorts count desc, so cities[0]/cities[1] are the two largest) and
# is omitted when there is no usable difference (missing key, a
# single city, or a 0 tie — the listed counts already show the tie).
# Localised in all six locales; the en/zh wordings match the
# ``stated_differences`` patterns in grounding.py (``3 more`` /
# ``相差3项``), so the stated number is checkable against the allowed
# set. The other locales have no difference pattern in the checker
# yet (pre-existing gap, noted in /tmp/r17-w2-decisions.md) — the
# sentence is still engine-sourced there, never invented.
_DEVIL_DIFFERENCE = {
    "en": "{city1} has {n} more verified programmes than {city2}.",
    "zh-CN": "{city1}与{city2}相差{n}项。",
    "es": "{city1} tiene {n} programas verificados más que {city2}.",
    "fr": "{city1} compte {n} programmes vérifiés de plus que {city2}.",
    "pt-BR": "{city1} tem {n} programas verificados a mais que {city2}.",
    "ar": "{city1} لديها {n} برامج موثّقة أكثر من {city2}.",
}


def _devil_difference_sentence(conflict: dict, loc: str) -> str:
    """Localised difference sentence for a climate conflict, or ""
    when the engine supplied no positive difference to state."""
    diff = conflict.get("count_difference")
    cities = conflict.get("cities") or []
    if (not isinstance(diff, int) or isinstance(diff, bool)
            or diff <= 0 or len(cities) < 2):
        return ""
    template = _DEVIL_DIFFERENCE.get(loc) or _DEVIL_DIFFERENCE["en"]
    return template.format(
        city1=localised_city_name(cities[0][0], loc),
        city2=localised_city_name(cities[1][0], loc), n=diff)


_DEVIL_COUNTRY_CODES: frozenset | None = None


def _devil_country_codes() -> frozenset:
    """ISO codes the verified data actually covers (rankings
    institutions + programmes): a two-letter code that appears
    nowhere in the data is dropped, never judged."""
    global _DEVIL_COUNTRY_CODES
    if _DEVIL_COUNTRY_CODES is None:
        codes = {i.get("country") for i in RANKINGS.get("institutions", [])}
        codes |= {p.get("country")
                  for p in list(PROGRAMS.values())
                  + list(EXPANSION_PROGRAMS.values())}
        _DEVIL_COUNTRY_CODES = frozenset(
            c for c in codes if isinstance(c, str) and len(c) == 2)
    return _DEVIL_COUNTRY_CODES


def _clean_devil_profile(profile) -> dict:
    """Lenient normalisation of the optional devil profile (the router
    passes it through as a plain dict): invalid values are dropped,
    never a 422 — the devil then falls back to what the message itself
    states. ``budget`` is (currency, amount, period) when all three
    are usable, else absent."""
    if not isinstance(profile, dict):
        return {}
    out: dict = {}
    countries = profile.get("countries")
    if isinstance(countries, list):
        cleaned: list[str] = []
        for c in countries:
            if isinstance(c, str) and len(c.strip()) == 2 and c.strip().isalpha():
                code = c.strip().upper()
                if code not in cleaned and code in _devil_country_codes():
                    cleaned.append(code)
        if cleaned:
            out["countries"] = cleaned[:5]
    climate = profile.get("climate")
    if isinstance(climate, str) and climate in _DEVIL_CLIMATES:
        out["climate"] = climate
    level = profile.get("level")
    if isinstance(level, str) and level in _DEVIL_LEVELS:
        out["level"] = level
    amount = profile.get("budget_amount")
    currency = profile.get("budget_currency")
    period = profile.get("budget_period")
    if (isinstance(amount, (int, float)) and not isinstance(amount, bool)
            and amount > 0 and isinstance(currency, str)
            and len(currency.strip()) == 3 and currency.strip().isalpha()
            and period in ("per_year", "total")):
        out["budget"] = (currency.strip().upper(), float(amount), period)
    city = profile.get("city")
    if isinstance(city, str) and city.strip():
        out["city"] = city.strip()[:100]
    return out


def _devil_effective(profile, message: str):
    """(countries, wanted climate, level, budget) the devil judges:
    the profile first, the message itself as fallback. ``profile`` is
    the raw dict (cleaned here, so callers never clean twice);
    ``budget`` is (currency, amount, period) or None."""
    clean_profile = _clean_devil_profile(profile)
    countries = clean_profile.get("countries")
    if not countries:
        detected = _detect_country(message or "")
        countries = [detected] if detected else []
    wanted = clean_profile.get("climate") or _detect_climate_class(message or "")
    level = clean_profile.get("level") or _detect_level(message or "")
    budget = clean_profile.get("budget") or _parse_ceiling(message or "")
    return countries, wanted, level, budget


def _devil_cheapest(level: str, country: str, currency: str, period: str):
    """(programme, fee_range) for the cheapest verified programme in
    the track/country whose fee is in the given currency + period, or
    None when no comparable fee exists. Same currency + period only —
    a cross-currency comparison can never judge a mismatch."""
    pool = [p for p in list(PROGRAMS.values())
            + list(EXPANSION_MATCHABLE.values())
            if p.get("degree_level") == level and p.get("country") == country]
    same = [(program_fee_range(p), p) for p in pool]
    same = [(fr, p) for fr, p in same
            if fr and fr[2] == currency and fr[3] == period]
    if not same:
        return None
    fr, p = min(same, key=lambda x: (x[0][0], x[1]["id"]))
    return p, fr


def _devil_catalogue_source(country: str, level: str) -> Source:
    """One citable source for a no-programmes conflict: the claim is
    about an absence in the verified catalogue, so the catalogue
    search itself — total size + zero hits in the track/country — is
    the evidence. It carries no URL (there is no official page for
    an absence); the UI resolves the evidence link from the other
    retrieved sources."""
    total = len(PROGRAMS) + len(EXPANSION_PROGRAMS)
    name = country_display_name(country, "en")
    level_name = _t("en", f"level_{level}")
    return Source(
        id=f"catalogue:{country.lower()}",
        url=None,
        title="Verified programme catalogue",
        excerpt=(f"Verified catalogue search ({total} programmes, v2 + "
                 f"expansion): 0 {level_name} programmes in {name}."))


def devil_conflicts(profile, message: str) -> list[dict]:
    """Engine-computed preference conflicts, each with the evidence ids
    that support it and the Source objects behind them (``sources``).
    ``profile`` is the raw dict (cleaned here). Deterministic; at most
    one conflict per kind per country, in the order climate,
    no-programmes, budget."""
    countries, wanted, level, budget = _devil_effective(profile, message or "")
    conflicts: list[dict] = []
    for country in countries:
        if wanted:
            cities = _country_cities([country])
            if cities and not any(
                    CLIMATE.get(city, {}).get("climate") == wanted
                    for city, _n in cities):
                listed = [(city, CLIMATE[city]["climate"], n)
                          for city, n in cities[:3]]
                conflict = {
                    "kind": "climate", "country": country, "wanted": wanted,
                    "cities": listed,
                    "evidence_ids": [_climate_source(city, n).id
                                     for city, n in cities[:3]],
                    "sources": [_climate_source(city, n)
                                for city, n in cities[:3]],
                }
                if len(listed) >= 2:
                    # Engine-computed difference between the two
                    # largest city counts (Round 16 W2): the model may
                    # only ever state THIS difference — never one it
                    # subtracted itself (14 vs 11 was answered "1").
                    conflict["count_difference"] = abs(
                        listed[0][2] - listed[1][2])
                conflicts.append(conflict)
        if level:
            pool = [p for p in list(PROGRAMS.values())
                    + list(EXPANSION_MATCHABLE.values())
                    if p.get("degree_level") == level
                    and p.get("country") == country]
            if not pool:
                src = _devil_catalogue_source(country, level)
                conflicts.append({
                    "kind": "no_programmes", "country": country,
                    "level": level, "evidence_ids": [src.id],
                    "sources": [src],
                })
        if level and budget:
            currency, amount, period = budget
            cheapest = _devil_cheapest(level, country, currency, period)
            if cheapest is not None:
                picked, fr = cheapest
                if fr[0] > amount:
                    enriched = _enriched_programme_sources(picked["id"])
                    conflicts.append({
                        "kind": "budget", "country": country, "level": level,
                        "programme_id": picked["id"], "fee_range": fr,
                        "budget": (currency, amount, period),
                        "evidence_ids": [s.id for s in enriched],
                        "sources": enriched,
                    })
    return conflicts


def devil_conflict_line(conflict: dict, locale: str = "en") -> str:
    """One localised devil line for one engine-computed conflict:
    the challenge, in the user's locale, with the verified numbers
    (city classes + counts, fee) taken from the conflict itself."""
    loc = locale if locale in _DEVIL_T else "en"
    t = _DEVIL_T[loc]
    kind = conflict["kind"]
    if kind == "climate":
        words = _CLASS_WORDS.get(loc) or _CLASS_WORDS["en"]
        wanted = words[conflict["wanted"]]
        item_t = _CITY_ITEM.get(loc) or _CITY_ITEM["en"]
        cities = join_list((item_t.format(
            city=localised_city_name(c, loc), cls=words[cls], n=n)
            for c, cls, n in conflict["cities"][:3]), loc)
        line = t["climate"].format(
            prefix=t["prefix"], wanted=wanted,
            country=country_display_name(conflict["country"], loc),
            cities=cities)
        # Round 17 (W2): the template states the engine-computed
        # difference (top two city counts) in the same line, so the
        # comparison is not missing when the model is down. The
        # sentence comes from _devil_difference_sentence, which reads
        # only conflict["count_difference"] — never a subtraction here.
        diff_sentence = _devil_difference_sentence(conflict, loc)
        if diff_sentence:
            sep = "" if loc == "zh-CN" else " "
            line = f"{line}{sep}{diff_sentence}"
        return line
    if kind == "no_programmes":
        return t["no_programmes"].format(
            prefix=t["prefix"],
            level=_t(loc, f"level_{conflict['level']}"),
            country=country_display_name(conflict["country"], loc))
    if kind == "budget":
        currency, amount, period = conflict["budget"]
        period_word = (t["period_per_year"] if period == "per_year"
                       else t["period_total"])
        return t["budget"].format(
            prefix=t["prefix"],
            level=_t(loc, f"level_{conflict['level']}"),
            country=country_display_name(conflict["country"], loc),
            fee=fee_text(conflict["fee_range"], loc),
            currency=currency, amount=_money(amount), period=period_word)
    return ""


def _ensure_devil_sources(conflicts: list[dict],
                          sources: list[Source]) -> list[Source]:
    """Every evidence id a conflict cites must be present in the
    returned catalogue (the model path validates citations against
    it); append any that retrieval did not already bring."""
    seen = {s.id for s in sources}
    out = list(sources)
    for conflict in conflicts:
        for s in conflict.get("sources") or []:
            if s.id not in seen:
                seen.add(s.id)
                out.append(s)
    return out


def _devil_template_result(conflicts: list[dict], sources: list[Source],
                           locale: str = "en") -> dict:
    """Deterministic template fallback for devil mode: the conflict
    lines (at most 3, conclusion first) or the honest no-clash line
    when nothing conflicts, plus the eligibility-check offer when
    there is room. A climate line states the engine-computed
    difference between the two largest city counts (Round 17 W2).
    Round 19 (W1): when the last conflict line already closes with
    that difference sentence, the offer is dropped — the difference
    is the reply's closing sentence. Never a model answer, never an
    invented clash."""
    if conflicts:
        lines = [devil_conflict_line(c, locale) for c in conflicts[:3]]
    else:
        loc = locale if locale in _DEVIL_T else "en"
        lines = [_DEVIL_T[loc]["no_conflict"]]
    if len(lines) < 3:
        # Round 19 (W1): the trailing "next" line must not follow a
        # difference sentence. Dropping, not moving, the offer:
        # putting it before the conflict would lead with the
        # call-to-action ahead of the conclusion, and the wizard
        # CTA still reaches the user through the frontend's
        # nextSteps button. Only the last line is checked: with
        # several conflicts the difference sits mid-reply by
        # construction (climate is listed first), and reordering
        # conflicts is out of scope — the offer is kept there.
        last = conflicts[len(lines) - 1] if conflicts else None
        if not (last is not None
                and _devil_difference_sentence(last, locale)):
            lines.append(_t(locale, "next"))
    evidence_url: str | None = None
    for conflict in conflicts:
        for eid in conflict["evidence_ids"]:
            evidence_url = resolve_url(eid, sources)
            if evidence_url:
                break
        if evidence_url:
            break
    if evidence_url is None:
        for s in sources:
            if s.url:
                evidence_url = s.url
                break
    return {"lines": lines[:3],
            "evidence_url": evidence_url,
            "ai_status": "unavailable", "model": None,
            "mode": "devil",
            "conflicts": [c["kind"] for c in conflicts],
            "sources": [{"id": s.id, "url": s.url, "title": s.title}
                        for s in sources]}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _candidates_route_to_template(candidates: list[str] | None) -> bool:
    """True when the template's candidate-carrying reply is the
    turn's one route, never the model (Round 25 W1 — decided once
    per turn from the retrieval result, before any gateway
    contact). Two shapes, and only these two:

    - Exactly one candidate: the caller-supplied scope already
      resolved the question to one programme and the template
      states its verified fact (the scope's fact line — see
      _scope_line; ask()'s own ambiguous branch only ever sets
      candidates with 2+ ids, so a single candidate can only be
      the resolved scope). There is nothing left to disambiguate
      and the model could only restate the same fee — the
      step-7 fee verifications are exactly this shape (Round 25
      W2 pins it: 0 transport calls, instant verified fee line).
    - Exactly two candidates, one undergraduate and one
      taught_masters: a level answer uniquely resolves the
      disambiguation ("undergraduate" / "masters", 本科 / 硕士),
      so the template list is the deterministic route — the ETH
      fee flow (re-test task 19: the same question flipped
      between a direct model answer and the list run to run).

    Any other shape keeps the model-first routing: one level only
    (the three undergraduate Computer Science programmes), or
    several programmes per level ("What are Oxford's tuition
    fees?" matches six across fields and levels) — the level
    question cannot resolve those, so the template list would
    strand the user in a re-ask loop instead of answering (a
    Round 6 pin: the model answers Oxford's fees from the
    verified programme evidence). An id outside the verified
    catalogue never routes to the template either — the model is
    attempted as before."""
    if not candidates:
        return False
    if len(candidates) == 1:
        return True
    if len(candidates) != 2:
        return False
    levels = []
    for pid in candidates:
        prog = _verified_programme(pid)
        if prog is None:
            return False
        levels.append(prog.get("degree_level"))
    return sorted(levels) == ["taught_masters", "undergraduate"]


def _level_followup_template_route(template: dict, message: str,
                                  program_ids: list[str] | None) -> bool:
    """True when this turn is a level answer to a two-candidate,
    one-per-level disambiguation that the template already resolved
    to a single programme — so the template's verified fact line is
    the turn's one route, never the model (Round 26 W2).

    Root cause of re-test task 20 (2026-11-27): after the ambiguous
    list ("I found 2 matching programmes … Tell me undergraduate
    or masters."), the follow-up ("…Computer Science? masters",
    scoped to the two candidates) resolves in the template's own
    ``ask()`` to exactly ONE programme — so ``_template_result``
    carries NO ``candidates`` (candidates are only set on the
    ambiguous branch itself, or on the scope's own which-one line,
    and ``_scope_line`` returns early once the template has a
    ``program_id``). ``_candidates_route_to_template`` therefore
    saw ``None`` and the turn went to the model whenever the
    gateway was not already known down: ~15 s of model budget
    (plus the frontend retry, ~30 s in the browser) and a
    model-worded fee line that varied run to run — while the
    undergraduate tap on the same flow answered instantly whenever
    the breaker / probe cache happened to be in the known-down
    state. The asymmetry was breaker-state luck, not a code-path
    difference: with a healthy mock both levels attempt the model
    (repro /tmp/r26w2-repro2.py: calls=1, ai_status=available,
    "Tuition fee: CHF 4,380 per year." for both).

    The shape recognised here is deliberately narrow, so no other
    routing changes: the template resolved to one programme, the
    message names that programme's level (``_detect_level`` — the
    same UG/TM words the matcher uses, en + zh), the resolved
    programme is in the caller-supplied scope, and the scope holds
    programmes of BOTH levels (the disambiguation pair — a shown
    batch of 3 that still holds both levels counts, so the locale
    re-fetch of the same turn routes the same way). A fresh
    single-match question (no scope, or a single-level scope)
    keeps the model-first routing, exactly as before."""
    pid = template.get("program_id")
    if not pid:
        return False
    prog = _verified_programme(pid)
    if prog is None:
        return False
    level = _detect_level(_strip_saved_prefs_context(message or ""))
    if level is None or prog.get("degree_level") != level:
        return False
    scope = _clean_program_ids(program_ids)
    if pid not in scope:
        return False
    levels = {(_verified_programme(s) or {}).get("degree_level")
              for s in scope}
    return "undergraduate" in levels and "taught_masters" in levels


def answer(message: str, locale: str = "en",
           history: list[dict] | None = None,
           provider: ProviderAdapter | None = None,
           mode: str = "normal", profile: dict | None = None,
           program_ids: list[str] | None = None,
           track: str | None = None) -> dict:
    """Answer one free-text question for 小罗盘.

    Returns ``{lines, evidence_url, ai_status, model, sources}``:
    ``lines`` at most 3, conclusion first; ``evidence_url`` resolved
    server-side from a cited source id (or the template's evidence
    link); ``ai_status`` is ``"available"`` only when a validated model
    output was actually used; ``model`` is ``"provider/model"`` or None;
    ``sources`` is the retrieved evidence catalogue.

    ``program_ids`` (Round 21, W3) is caller-supplied scope — the
    programme cards the user is looking at (RecChat's visible batch).
    A deictic "this programme" question is answered from those
    programmes' verified facts instead of the blanket unknown; see
    ``_scope_line``. Devil's advocate ignores it (its profile is the
    scope there).

    ``track`` (Round 22, W2) is the wizard track the question is asked
    under (undergraduate / taught_masters, else None): programme
    matching filters by it, so an undergraduate profile can never
    match an MSc programme. An invalid value is dropped, never a 422.

    Devil's advocate (``mode="devil"``): the same retrieval + grounding,
    but the answer challenges the user's stated preferences (from
    ``profile`` — countries, climate, level, budget — else from the
    message) with the engine-computed conflicts in ``devil_conflicts``.
    The model path additionally requires at least one claim/action to
    cite a conflict's evidence; the no-key / model-failure path is the
    deterministic template (``_devil_template_result``). Devil replies
    carry ``"mode": "devil"`` and ``"conflicts": [kinds]``; normal
    replies are unchanged.
    """
    loc = locale if locale in LOCALES else "en"
    msg = message or ""
    is_devil = (mode == "devil")

    # (a) Personal-data guard first — the value is never echoed.
    if contains_personal_data(msg):
        template = assistant_ask(msg, loc)
        result = {"lines": template["lines"], "evidence_url": None,
                  "ai_status": "unavailable", "model": None, "sources": []}
        if is_devil:
            result["mode"] = "devil"
            result["conflicts"] = []
        return result

    provider = provider or ProviderAdapter()
    track = _clean_track(track)
    if is_devil:
        # Retrieval scoped to the challenged preferences: the wanted
        # climate class within the chosen countries, so the catalogue
        # carries those countries' own cities with their actual classes
        # (Zurich/Lausanne four-season for a cool wish in Switzerland).
        countries, wanted, _level, _budget = _devil_effective(profile, msg)
        template, sources, pids = _retrieve(
            msg, loc, countries=countries or None, climate_class=wanted,
            country_programmes=True, track=track)
        conflicts = devil_conflicts(profile, msg)
        sources = _ensure_devil_sources(conflicts, sources)
        if not conflicts:
            # No engine-computed conflict: nothing for the model to
            # challenge. Skip the model call entirely — the prompt
            # alone cannot stop it inventing a challenge — and answer
            # from the template, which says honestly that nothing
            # clashes.
            return _devil_template_result(conflicts, sources, loc)
    else:
        template, sources, pids = _retrieve(
            msg, loc, country_programmes=True,
            program_ids=_clean_program_ids(program_ids), track=track)
        conflicts = []
    sources_out = [{"id": s.id, "url": s.url, "title": s.title} for s in sources]

    def fallback() -> dict:
        if is_devil:
            return _devil_template_result(conflicts, sources, loc)
        return _template_result(template, sources, loc,
                                programme_id=_detect_programme_id(msg),
                                message=msg,
                                scope_program_ids=_clean_program_ids(program_ids),
                                track=track)

    # Round 25 W1 — deterministic routing, decided once per turn
    # from the retrieval result, before any gateway contact:
    #
    # (1) A turn whose template reply carries candidates in one of
    # the two shapes _candidates_route_to_template recognises —
    # exactly one candidate (the scope already resolved it and the
    # template states its verified fact), or exactly two
    # candidates, one per level (a level answer uniquely resolves
    # the disambiguation) — is answered by the template, never by
    # the model. The disambiguation is a clarification only the
    # user can answer — which of the two levels they mean — not a
    # knowledge gap the model can fill: while the gateway was up
    # the model answered such a question directly (skipping the
    # list), and while it was down or slow the turn fell back to
    # the list after the full model budget, so the same ETH fee
    # question flipped between the two behaviours run to run
    # (re-test task 19). The template list is now the one route in
    # every gateway state, with or without a saved profile, in
    # every locale — and it is instant, because no model call is
    # ever attempted for it. The narrowing is deliberate: for any
    # other ambiguity the level question cannot resolve it — one
    # level only (three undergraduate Computer Science
    # programmes), or several programmes per level ("What are
    # Oxford's tuition fees?" matches six programmes across fields
    # and levels) — so those turns keep the model-first routing
    # (a Round 6 pin: the model answers Oxford's fees from the
    # verified programme evidence). Devil's advocate is excluded
    # too: its challenge is the point of the turn, and its
    # no-conflict path already returns the template.
    # (2) When the gateway is already known down — the breaker is
    # open, or a probe said "unavailable" within its 60 s TTL
    # (model_skip_cached: the /simulate fail-fast, moved out of
    # app.main into app.ai_status_cache in this round so this
    # endpoint can consult it) — the model attempt is skipped and
    # the template answers at once, instead of spending the 15 s
    # budget proving the gateway is still down. A cold cache with
    # a closed breaker still attempts as before: the first slow
    # failure after the gateway dies is inherent (the /simulate
    # residual, DECISIONS #267) — after it, the breaker keeps
    # later turns fast for 180 s.
    if not is_devil:
        template_result = fallback()
        if _candidates_route_to_template(template_result.get("candidates")):
            return template_result
        # Round 26 (W2): the level follow-up to a two-candidate,
        # one-per-level disambiguation — the template already
        # resolved it to one programme (see
        # _level_followup_template_route), so it carries no
        # candidates for the check above and would otherwise go to
        # the model whenever the gateway is not known down.
        if _level_followup_template_route(template, msg, program_ids):
            return template_result
    if model_skip_cached():
        return fallback()

    # (c) No key: the template assistant is the honest answer.
    if not provider.available:
        return fallback()

    # (d) Key present: model over the retrieved sources only.
    # Timeouts (round 10 fix): live gateway calls took ~7-10 s each
    # on 2026-11-26, and the round-9 budgets (20 s first call + 15 s
    # repair) let one turn stack to ~35 s server-side — past the
    # frontend's 25 s per-attempt abort, so the browser retried the
    # whole turn and the user saw 45-60 s of silence, then offline.
    # A turn now gets ONE model call with a 15 s budget and NO repair
    # retry: an unparsable or invalid output falls back to the
    # template at once (the template now reaches the user — see
    # CompassPet — instead of being discarded). Worst case per turn
    # is ~15 s + retrieval, inside one frontend attempt. The
    # event-loop blockage itself is fixed at the router (see
    # app/router_chat.py): the sync model call runs in a worker
    # thread, so a slow chat can no longer wedge /health or any
    # other endpoint.
    evidence_texts = _evidence_texts(sources, pids)
    envelope = {
        "task": "devil-chat" if is_devil else "chat",
        "prompt_version": PROMPT_VERSION,
        "locale": loc,
        "message": msg,
        "history": _clean_history(history),
        "evidence_catalog": [
            {"id": s.id, "url": s.url, "title": s.title, "excerpt": s.excerpt}
            for s in sources],
    }
    if is_devil:
        # The engine-computed conflicts are the ONLY challenges the
        # model may raise, each with its supporting evidence ids. The
        # climate conflict additionally carries the engine-computed
        # difference between the two largest city counts
        # (``count_difference``): the model may state ONLY that
        # difference, never one it subtracted itself — and the checker
        # enforces it against _devil_allowed_differences below. The
        # English conflict line already states the difference
        # (Round 17 W2: devil_conflict_line appends the
        # engine-computed count_difference), so no second difference
        # sentence is appended here.
        envelope["devil_conflicts"] = [
            {"kind": c["kind"], "evidence_ids": c["evidence_ids"],
             "detail": devil_conflict_line(c, "en"),
             "count_difference": c.get("count_difference")}
            for c in conflicts]
    messages = [{"role": "user", "content": json.dumps(envelope, ensure_ascii=False)}]
    started = time.monotonic()
    try:
        result = provider.chat(
            messages,
            system=(devil_advocate_system(loc) if is_devil
                    else chat_system(loc)),
            timeout_s=15.0)
    except ProviderError as e:
        logger.info("assistant/chat model call failed kind=%s latency_ms=%d",
                    e.kind, int((time.monotonic() - started) * 1000))
        return fallback()
    parsed = _parse_model_json(result.text)
    if parsed is None:
        logger.info("assistant/chat model output unparsable latency_ms=%d",
                    int((time.monotonic() - started) * 1000))
        return fallback()
    errors = _validate_chat_payload(
        parsed, sources, evidence_texts, loc,
        allowed_differences=(_devil_allowed_differences(conflicts)
                             if is_devil else None))
    if errors:
        # Round 10: no repair retry — one bad output costs a second
        # ~10 s model call and still usually fails; the verified
        # template answers the user faster and honestly.
        logger.info("assistant/chat model output failed validation errors=%d",
                    len(errors))
        return fallback()
    if is_devil and conflicts:
        # A devil's answer must actually challenge a computed conflict
        # with its evidence — a grounded but unchallenging reply is
        # not a devil's-advocate answer, so the template challenges
        # instead.
        conflict_ids = {eid for c in conflicts for eid in c["evidence_ids"]}
        cited: set[str] = set()
        for section in (parsed.get("claims") or [], parsed.get("actions") or []):
            for item in section:
                if isinstance(item, dict):
                    cited.update(item.get("evidence_ids") or [])
        if not (cited & conflict_ids):
            logger.info("assistant/chat devil output cited no conflict evidence")
            return fallback()
    lines = _render_lines(parsed, loc, sources)
    if not is_devil and not _model_lines_match_intent(lines, template, msg, loc):
        # Round 26, W3: a fee question answered with the ranks (or
        # any other fact type) is not a grounded answer to the
        # question asked — the verified template answers instead.
        logger.info("assistant/chat model output mismatched question intent")
        return fallback()
    # Defence in depth: a rendered line must never carry a raw URL, a
    # probability/guarantee, or key material — if it does, fall back.
    joined_lines = "\n".join(lines)
    if ("http://" in joined_lines or "https://" in joined_lines
            or "www." in joined_lines or check_no_forbidden(lines)
            or "sk-" in joined_lines.lower()):
        return fallback()
    result = {"lines": lines,
              "evidence_url": _resolve_evidence_url(parsed, sources),
              "ai_status": "available",
              "model": f"{result.provider}/{result.model}",
              "sources": sources_out}
    if is_devil:
        result["mode"] = "devil"
        result["conflicts"] = [c["kind"] for c in conflicts]
    return result
