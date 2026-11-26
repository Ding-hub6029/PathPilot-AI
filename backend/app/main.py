"""PathPilot AI Day-2 backend — FastAPI. Run from backend/ so that
`app`, `domain` and `ai` are importable top-level packages.

    uvicorn app.main:app --host 127.0.0.1 --port 8000

Day 2 changes (see DECISIONS.md #43-#50):
- POST /explain recomputes server-side from {profile, program_ids, locale};
  a client-supplied Evaluation is rejected with 422 EXPLAIN_REQUIRES_PROFILE.
- GET /programs supports country/subject/intake/degree_level filtering and
  cursor pagination (limit default 20, max 20).
- POST /profile/validate returns {valid, application_track,
  normalized_profile, warnings, field_errors}.
- In-memory per-IP rate limiting (60/min general, 10/min on /explain) with
  429 + the standard error body; /health and /ready are exempt.
- Security headers on every response (nosniff, DENY, no-referrer) plus the
  existing X-Request-Id.
- Money uses Decimal (see app/schemas.py); /openapi.json is generated into
  docs/openapi.json by tools/generate_openapi.py.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import threading
import time
import uuid
from decimal import Decimal

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ai.assistant import (BUDGET_BANDS, DEGREE_LEVELS, ask as assistant_ask,
                        suggest as assistant_suggest)
from ai.explain import explain_structured_with_status
from ai.prompts import PROMPT_VERSION
from ai.provider import ProviderAdapter
from app.adapter import (RULES_VERSION, flat_to_student, match_response,
                         rule_to_frontend, source_manifest_hash, summary_for)
from app.data import (CLIMATE, DATA_VERSION, EXPANSION_INSTITUTION_CITIES,
                      EXPANSION_INSTITUTIONS, EXPANSION_MATCHABLE,
                      EXPANSION_PROGRAMS, PROGRAMS, RANKINGS,
                      V2_PROGRAM_INSTITUTION)
from app.router_chat import router as router_chat
from app.router_eval import router as router_eval
from app.router_plans import router as router_plans
from app.router_whynot import router as router_whynot
from app.schemas import (AssistantAskRequest, AssistantSuggestRequest,
                         ErrorBody, ErrorResponse, Evaluation, ExplainRequest,
                         MatchRequest, SimulateRequest, StudentProfile)
from domain.climate import (climate_fit, normalise_preference,
                            resolve_city_climate)
from domain.eligibility import (_parse_test_date, effective_curriculum,
                                evaluate, overall_status, track_mismatch)
from domain.expansion_eval import evaluate_expansion

app = FastAPI(title="PathPilot AI — Day 2 backend", version="0.2.0")

# Day 3 AI routers (chat + profile parse, improvement plans, AI evaluation
# set). Each router defines its own Pydantic models; main.py only mounts
# them so a router can never collide with the Day 1/2 endpoints.
app.include_router(router_chat)
app.include_router(router_plans)
app.include_router(router_eval)
app.include_router(router_whynot)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Rate limiting (in-memory, per IP, sliding 60 s window) ----------------
# General: 60 req/min. /api/v1/explain: 10 req/min (its own bucket; the
# spec's anonymous-AI-call budget is 10/min/IP, Ch15). /health and /ready
# are exempt so liveness probes never 429. reset_rate_limits() exists so
# tests can isolate bursts; it is not an endpoint.
RATE_LIMIT_GENERAL_PER_MIN = 60
RATE_LIMIT_EXPLAIN_PER_MIN = 10
# Model calls cost money and latency: the AI endpoints share their own
# 10/min/IP bucket (spec Ch15 anonymous-AI-call budget). Template-only
# assistant endpoints (/assistant/suggest, /assistant/ask) stay on the
# general bucket; /ai/status is a cheap read and stays general too.
RATE_LIMIT_AI_PER_MIN = 10
AI_PATH_PREFIXES = ("/api/v1/assistant/chat", "/api/v1/profile/parse",
                    "/api/v1/improvement-plan", "/api/v1/ai/evaluation",
                    "/api/v1/whynot")
_RATE_WINDOW_S = 60.0
_rate_buckets: dict[str, list[float]] = {}


def reset_rate_limits() -> None:
    """Clear all rate-limit buckets (test isolation only)."""
    _rate_buckets.clear()


# --- /ai/status live-probe cache (Round 14) --------------------------------
# The probe exercises the gateway (see ai_status below), so its result
# is cached for 60 s: at most one tiny probe per minute per backend
# process, shared by every user. reset_ai_status_cache() exists so
# tests can isolate probes; it is not an endpoint.
_AI_STATUS_TTL_S = 60.0
_AI_STATUS_CACHE: dict = {"at": 0.0, "payload": None}
_ai_status_lock = threading.Lock()


def reset_ai_status_cache() -> None:
    """Clear the cached /ai/status probe result (test isolation only)."""
    with _ai_status_lock:
        _AI_STATUS_CACHE["at"] = 0.0
        _AI_STATUS_CACHE["payload"] = None


def _client_ip(request: Request) -> str:
    """Client IP for rate limiting, behind the Vercel proxy (Round 13).

    Vercel sends X-Forwarded-For with the browser client first, so
    the AI bucket is per-user instead of per-egress-IP: without this
    every browser user shared one 10/min AI bucket keyed on
    request.client.host (the Vercel egress IP). Falls back to the
    direct peer when no forwarded header is present (local dev,
    direct curl). Only the first entry is trusted — later entries
    are proxies the client can append arbitrarily.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first and first.lower() != "unknown":
            return first
    return request.client.host if request.client else "unknown"


def _rate_limited(client_ip: str, bucket: str, limit: int) -> bool:
    now = time.monotonic()
    key = f"{client_ip}:{bucket}"
    hits = [t for t in _rate_buckets.get(key, []) if now - t < _RATE_WINDOW_S]
    if len(hits) >= limit:
        _rate_buckets[key] = hits
        return True
    hits.append(now)
    _rate_buckets[key] = hits
    return False


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def _err(request_id: str, code: str, message: str, status: int,
         field_errors: list[dict] | None = None, retryable: bool = False) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message,
                        field_errors=field_errors or [], retryable=retryable),
        request_id=request_id).model_dump()
    resp = JSONResponse(status_code=status, content=body)
    resp.headers.update(SECURITY_HEADERS)
    resp.headers["X-Request-Id"] = request_id
    return resp


@app.middleware("http")
async def _request_id_and_limits(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    path = request.url.path
    client_ip = _client_ip(request)
    if path not in ("/api/v1/health", "/api/v1/ready"):
        if path == "/api/v1/explain":
            bucket, limit = "explain", RATE_LIMIT_EXPLAIN_PER_MIN
        elif path.startswith(AI_PATH_PREFIXES):
            bucket, limit = "ai", RATE_LIMIT_AI_PER_MIN
        else:
            bucket, limit = "general", RATE_LIMIT_GENERAL_PER_MIN
        if _rate_limited(client_ip, bucket, limit):
            return _err(request_id, "RATE_LIMITED",
                        f"Rate limit exceeded: {limit} requests per minute for {bucket}.",
                        429, retryable=True)
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    response.headers.update(SECURITY_HEADERS)
    return response


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    return _err(rid, "INTERNAL_ERROR", str(exc), 500)


def _validate_profile(profile: StudentProfile) -> str | None:
    """Cross-track checks. Returns an error message or None."""
    if profile.application_track not in ("undergraduate", "taught_masters"):
        return f"application_track must be 'undergraduate' or 'taught_masters', got '{profile.application_track}'."
    if profile.application_track == "undergraduate":
        if profile.masters_profile is not None:
            return "Undergraduate profile must not include masters_profile."
        if profile.undergrad_profile is None:
            return "Undergraduate profile requires undergrad_profile."
    if profile.application_track == "taught_masters":
        if profile.undergrad_profile is not None:
            return "Taught-masters profile must not include undergrad_profile."
        if profile.masters_profile is None:
            return "Taught-masters profile requires masters_profile."
    return None


def _evaluate(profile: StudentProfile, program: dict, locale: str = "en",
              explain: bool = True):
    # Day 3 round 6: v2 rules for the 8 v2 programmes, the generic
    # expansion evaluator for promoted expansion programmes.
    if program["id"] in PROGRAMS:
        results = evaluate(profile, program)
    else:
        results = evaluate_expansion(profile, program)
    if not explain:
        # Round 8: multi-programme /match needs rule results only. The
        # frontend never reads a per-programme explanation or ai_status
        # from /match (MatchResult carries neither), and a model call
        # per programme costs ~10 s each sequentially — 360 programmes
        # is ~an hour — while the synchronous provider calls block the
        # single uvicorn event loop for the whole request, so /health
        # and every other endpoint stop answering. Explanations are
        # generated on demand by /explain and single-programme /match.
        # ai_status stays "unavailable": no validated model output was
        # used for this evaluation.
        return Evaluation(program_id=program["id"], data_version=DATA_VERSION,
                          overall_status=overall_status(results), results=results)
    provider = ProviderAdapter()
    ev = Evaluation(program_id=program["id"], data_version=DATA_VERSION,
                    overall_status=overall_status(results), results=results,
                    ai_status=provider.ai_status)
    structured, text, status = explain_structured_with_status(ev, locale, provider)
    ev.explanation = text
    ev.ai_status = status
    ev.explanation_structured = structured
    return ev


def _get_programme_or_404(program_id: str):
    """Resolve a programme id to its data dict for evaluation: one of
    the 8 v2 programmes, or a promoted (matchable) expansion programme.
    Display-only expansion programmes and unknown ids are None (the
    caller returns PROGRAM_NOT_FOUND, as before)."""
    if program_id in PROGRAMS:
        return PROGRAMS[program_id]
    if program_id in EXPANSION_MATCHABLE:
        return EXPANSION_MATCHABLE[program_id]
    return None


def _get_programme_for_display(program_id: str):
    """Resolve a programme id for read endpoints (catalogue detail):
    v2 or ANY expansion programme (matchable or display-only)."""
    if program_id in PROGRAMS:
        return PROGRAMS[program_id]
    return EXPANSION_PROGRAMS.get(program_id)


def _preference_fit(raw_profile: dict, program: dict) -> str | None:
    """Climate signal for one result (round 6): the user's stated
    climate preference against the programme's city, from the curated
    CLIMATE table. Returns None (no signal) when the profile has no
    climate preference, the city is not in the table, or the preference
    is a free-text value. Never a rule status."""
    pref = normalise_preference(raw_profile.get("prefClimate"))
    if pref is None:
        return None
    return climate_fit(
        pref,
        resolve_city_climate(program, CLIMATE, EXPANSION_INSTITUTION_CITIES,
                             V2_PROGRAM_INSTITUTION))


def _attach_preference_fit(results: list[dict], raw_profile: dict) -> None:
    """Add the optional per-result ``preferenceFit`` key (only when a
    climate preference is set and the programme's city resolves).
    Results without a signal carry no key, so v2 output with no
    preference is byte-identical."""
    for r in results:
        program = _get_programme_for_display(r.get("programId", ""))
        if program is None:
            continue
        fit = _preference_fit(raw_profile, program)
        if fit is not None:
            r["preferenceFit"] = fit


def _profile_from_raw(raw_profile: dict) -> StudentProfile:
    """Nested StudentProfile dict or flat wizard profile -> StudentProfile."""
    if "application_track" in raw_profile:
        return StudentProfile(**raw_profile)
    return flat_to_student(raw_profile)


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        offset = int(raw)
    except Exception:
        raise ValueError(f"Invalid cursor: {cursor!r}")
    if offset < 0:
        raise ValueError(f"Invalid cursor: {cursor!r}")
    return offset


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "data_version": DATA_VERSION, "programs": len(PROGRAMS)}


@app.get("/api/v1/ai/status")
def ai_status():
    """AI integration status (Day 3). Never exposes the key value — only
    whether one is configured, which provider/model is selected, and the
    prompt version. With no key this reports ai_status="unavailable" and
    every AI endpoint falls back to the rules/template behaviour."""
    # Round 14 (live probe, not the old config-only answer): the old
    # endpoint returned "available" whenever a key was present, so it
    # said "available" through the whole 2026-11-27 00:42-00:50 gateway
    # outage while every model path was template-only — the signal the
    # frontend used to decide whether to attempt a model call was
    # false. ProviderAdapter.probe_live() exercises the gateway (GET
    # /models, else one 1-token chat call, ~3 s worst case when the
    # gateway is unreachable) and the result is cached for 60 s
    # server-side, so a probe costs ~1 tiny call per minute per backend
    # process, not one per user request; concurrent callers wait on
    # the lock and share the cached value. "probed" tells callers
    # whether the value came from that live probe (True) or from
    # config alone (False: no provider configured, so there is nothing
    # to probe). A failed probe also trips the provider circuit
    # breaker, so the model paths behind it fail fast to their
    # templates instead of each spending 15 s on a doomed attempt.
    # (This is a plain comment, not the docstring: the docstring is
    # the OpenAPI description, and docs/openapi.json must match it.)
    adapter = ProviderAdapter()
    info = adapter.describe()
    base = {"ai_status": info["ai_status"], "provider": info["provider"],
            "model": info["model"],
            "api_key_configured": info["api_key_configured"],
            "supported_providers": info["supported_providers"],
            "prompt_version": PROMPT_VERSION, "data_version": DATA_VERSION}
    if not adapter.available:
        return {**base, "probed": False}
    with _ai_status_lock:
        cached = _AI_STATUS_CACHE["payload"]
        if cached is not None and time.monotonic() - _AI_STATUS_CACHE["at"] < _AI_STATUS_TTL_S:
            return dict(cached)
        live = adapter.probe_live()
        payload = {**base,
                   "ai_status": "available" if live else "unavailable",
                   "probed": True}
        _AI_STATUS_CACHE["at"] = time.monotonic()
        _AI_STATUS_CACHE["payload"] = payload
        return dict(payload)


@app.get("/api/v1/ready")
def ready():
    return {"status": "ready", "data_version": DATA_VERSION,
            "programs": sorted(PROGRAMS.keys()), "ai_status": ProviderAdapter().ai_status}


@app.get("/api/v1/openapi.json")
def openapi_v1():
    """The generated OpenAPI spec under the /api/v1 prefix (the default
    FastAPI /openapi.json stays enabled too). docs/openapi.json is a copy
    of this, produced by tools/generate_openapi.py."""
    return app.openapi()


@app.get("/api/v1/programs")
def list_programs(request: Request,
                  country: str | None = Query(default=None),
                  subject: str | None = Query(default=None),
                  intake: str | None = Query(default=None),
                  degree_level: str | None = Query(default=None),
                  institution: str | None = Query(default=None),
                  field: str | None = Query(default=None),
                  catalogue: str = Query(default="v2"),
                  cursor: str | None = Query(default=None),
                  limit: int = Query(default=20, ge=1)):
    """Filter + cursor pagination (spec Ch12).

    Filters are exact for country/degree_level (case-insensitive) and
    substring for subject (case-insensitive). ``intake`` matches the
    program's intake_year, or the intake string when it holds a year
    (NUS stores "August 2027, AY2027/2028 Semester 1"). ``institution``
    matches the ranking institution id (v2 programmes via the explicit
    V2_PROGRAM_INSTITUTION mapping); ``field`` is an exact match on the
    programme's field slug. ``catalogue`` selects which catalogue to list:
    ``v2`` (default — the 8 matchable programmes, byte-identical to the
    Day-2 response), ``expansion`` (listed v3 programmes only) or ``all``
    (both; every item then carries ``catalogue`` + ``matchable`` flags).
    ``cursor`` is an opaque offset token; ``limit`` defaults to 20 and is
    capped at 20. Response keeps the Day-1 "programs" key for backward
    compatibility.
    """
    rid = request.state.request_id
    if catalogue not in ("v2", "expansion", "all"):
        return _err(rid, "VALIDATION_ERROR",
                    "catalogue must be 'v2', 'expansion' or 'all'.", 400)
    try:
        offset = _decode_cursor(cursor)
    except ValueError as exc:
        return _err(rid, "VALIDATION_ERROR", str(exc), 400)
    limit = min(limit, 20)
    if catalogue == "v2":
        items = list(PROGRAMS.values())
    elif catalogue == "expansion":
        items = [dict(p, catalogue="expansion",
                      matchable=p.get("matchable") is True)
                 for p in EXPANSION_PROGRAMS.values()]
    else:
        items = ([dict(p, catalogue="v2", matchable=True) for p in PROGRAMS.values()]
                 + [dict(p, catalogue="expansion",
                         matchable=p.get("matchable") is True)
                    for p in EXPANSION_PROGRAMS.values()])
    if country:
        items = [p for p in items if str(p.get("country", "")).upper() == country.strip().upper()]
    if subject:
        needle = subject.strip().lower()
        items = [p for p in items if needle in str(p.get("subject", "")).lower()]
    if intake:
        needle = intake.strip()
        def _intake_match(p: dict) -> bool:
            if p.get("intake_year") is not None and str(p["intake_year"]) == needle:
                return True
            return needle in str(p.get("intake") or "")
        items = [p for p in items if _intake_match(p)]
    if degree_level:
        items = [p for p in items if str(p.get("degree_level", "")) == degree_level.strip()]
    if institution:
        want = institution.strip()
        def _inst_match(p: dict) -> bool:
            if p.get("institution_id"):
                return str(p["institution_id"]) == want
            return V2_PROGRAM_INSTITUTION.get(p.get("id", "")) == want
        items = [p for p in items if _inst_match(p)]
    if field:
        needle = field.strip().lower()
        def _field_match(p: dict) -> bool:
            # v2 programmes carry subject "computer science" (spaces);
            # expansion programmes carry the field slug. Normalise both.
            value = str(p.get("field") or p.get("subject", "")).lower()
            return value.replace(" ", "-") == needle or value == needle
        items = [p for p in items if _field_match(p)]
    page = items[offset:offset + limit]
    next_offset = offset + len(page)
    next_cursor = _encode_cursor(next_offset) if next_offset < len(items) else None
    return {"data_version": DATA_VERSION, "items": page, "programs": page,
            "next_cursor": next_cursor}


@app.get("/api/v1/programs/{program_id}")
def get_program(program_id: str, request: Request):
    # Round 6: expansion programmes are readable here too (v2 + any
    # expansion programme, matchable or display-only); unknown ids 404.
    program = _get_programme_for_display(program_id)
    if program is None:
        return _err(request.state.request_id, "PROGRAM_NOT_FOUND",
                    f"No program with id '{program_id}'.", 404)
    return program


# --- Institution profiles (Day 3 expansion, v3) -----------------------------
# The institution is the reference app's school detail page: ranks (from
# v2 rankings.json — never stored here), a stats profile (v3 expansion,
# official sources only, null where unverified), and the programme list
# (v2 matchable programmes first, then expansion listed programmes).
# Stats exist only for institutions collectors have profiled; every other
# institution returns "stats": null — never invented stats.
@app.get("/api/v1/institutions")
def list_institutions(request: Request,
                      country: str | None = Query(default=None),
                      query: str | None = Query(default=None),
                      cursor: str | None = Query(default=None),
                      limit: int = Query(default=20, ge=1)):
    """All 148 ranking institutions, cursor-paginated.

    ``country`` matches the institution's country code (case-insensitive);
    ``query`` is a case-insensitive substring on the official name or the
    verified Chinese display name (name_zh). Each item carries
    ``has_stats_profile`` and ``programmes_count`` (v2 + expansion).
    """
    rid = request.state.request_id
    try:
        offset = _decode_cursor(cursor)
    except ValueError as exc:
        return _err(rid, "VALIDATION_ERROR", str(exc), 400)
    limit = min(limit, 20)
    items = list(RANKINGS.get("institutions", []))
    if country:
        items = [i for i in items if str(i.get("country", "")).upper() == country.strip().upper()]
    if query:
        needle = query.strip().lower()
        items = [i for i in items
                 if needle in str(i.get("official_name", "")).lower()
                 or needle in str(i.get("name_zh", "") or "").lower()]
    out = []
    for inst in items:
        iid = inst["id"]
        count = sum(1 for p in PROGRAMS.values()
                    if V2_PROGRAM_INSTITUTION.get(p["id"]) == iid)
        count += sum(1 for p in EXPANSION_PROGRAMS.values()
                     if p.get("institution_id") == iid)
        out.append(dict(inst, has_stats_profile=iid in EXPANSION_INSTITUTIONS,
                        programmes_count=count))
    page = out[offset:offset + limit]
    next_offset = offset + len(page)
    next_cursor = _encode_cursor(next_offset) if next_offset < len(items) else None
    return {"data_version": DATA_VERSION, "expansion_version": "v3",
            "items": page, "next_cursor": next_cursor}


@app.get("/api/v1/institutions/{institution_id}")
def get_institution(institution_id: str, request: Request):
    """One institution: ranking record, stats profile (or null), provider
    ranks, and programmes — v2 matchable first, then expansion listed."""
    inst = None
    for cand in RANKINGS.get("institutions", []):
        if cand["id"] == institution_id:
            inst = cand
            break
    if inst is None:
        return _err(request.state.request_id, "INSTITUTION_NOT_FOUND",
                    f"No institution with id '{institution_id}'.", 404)
    entries = [e for e in RANKINGS.get("entries", [])
               if e.get("institution_id") == institution_id]
    programs = ([dict(p, catalogue="v2", matchable=True)
                 for p in PROGRAMS.values()
                 if V2_PROGRAM_INSTITUTION.get(p["id"]) == institution_id]
                + [dict(p, catalogue="expansion",
                        matchable=p.get("matchable") is True)
                   for p in EXPANSION_PROGRAMS.values()
                   if p.get("institution_id") == institution_id])
    return {"data_version": DATA_VERSION, "expansion_version": "v3",
            "institution": inst,
            "stats": EXPANSION_INSTITUTIONS.get(institution_id),
            "rankings": entries, "programs": programs}


# --- Rankings (Day 3, spec Ch9 FR15/FR16, BR15/BR16) -----------------------
# Three providers (QS 2027, THE 2027, ARWU 2026), top 100 institutions
# each, 300 entries. No combined or
# averaged rank across providers exists anywhere (BR15); rankings never
# affect eligibility (BR16) — these endpoints only read the verified
# rankings.json file. World, national and subject ranks are kept
# separate: this build ships world ranks only; a subject filter returns
# an empty list because no subject entries were verified.
def _ranking_institution(entry: dict) -> dict | None:
    for inst in RANKINGS.get("institutions", []):
        if inst["id"] == entry.get("institution_id"):
            return inst
    return None


@app.get("/api/v1/rankings/providers")
def list_ranking_providers():
    """The three providers with edition, official links and rights status."""
    return {"data_version": DATA_VERSION,
            "providers": RANKINGS.get("providers", [])}


@app.get("/api/v1/rankings/editions")
def list_ranking_editions():
    """One record per provider edition actually shipped."""
    editions = []
    for p in RANKINGS.get("providers", []):
        editions.append({"provider": p["id"], "provider_name": p["name"],
                        "edition_label": p["edition_label"],
                        "published_at": p.get("published_at"),
                        "entry_url": p["entry_url"],
                        "rights_status": p["rights_status"]})
    return {"data_version": DATA_VERSION, "editions": editions}


@app.get("/api/v1/rankings")
def list_rankings(request: Request,
                  provider: str | None = Query(default=None),
                  edition: str | None = Query(default=None),
                  ranking_type: str | None = Query(default=None),
                  subject: str | None = Query(default=None),
                  country: str | None = Query(default=None),
                  query: str | None = Query(default=None),
                  cursor: str | None = Query(default=None),
                  limit: int = Query(default=20, ge=1)):
    """Filter + cursor pagination (spec Ch9).

    ``provider`` / ``edition`` / ``ranking_type`` are exact matches
    (case-insensitive). ``subject`` matches a subject name — this build
    ships world ranks only, so any subject filter returns an empty list
    rather than inventing a subject rank. ``country`` matches the
    institution's country code (any code in the data, e.g. GB, SG, US, CN).
    ``query`` is a case-insensitive
    substring on the institution's official name or its verified Chinese
    display name (name_zh). ``cursor`` is an opaque
    offset token; ``limit`` defaults to 20 and is capped at 20. No entry
    here is ever a combined or averaged rank (BR15).
    """
    rid = request.state.request_id
    try:
        offset = _decode_cursor(cursor)
    except ValueError as exc:
        return _err(rid, "VALIDATION_ERROR", str(exc), 400)
    limit = min(limit, 20)
    items = list(RANKINGS.get("entries", []))
    if provider:
        items = [e for e in items if str(e.get("provider", "")).lower() == provider.strip().lower()]
    if edition:
        items = [e for e in items if str(e.get("edition_label", "")) == edition.strip()]
    if ranking_type:
        items = [e for e in items if str(e.get("ranking_type", "")).lower() == ranking_type.strip().lower()]
    if subject:
        # No subject entries were verified for this build (see
        # RANKINGS_SOURCES.md §6); a subject rank must not be invented.
        items = []
    if country:
        items = [e for e in items
                 if (_ranking_institution(e) or {}).get("country", "").upper() == country.strip().upper()]
    if query:
        needle = query.strip().lower()
        items = [e for e in items
                 if needle in str((_ranking_institution(e) or {}).get("official_name", "")).lower()
                 or needle in str((_ranking_institution(e) or {}).get("name_zh", "") or "").lower()]
    page = items[offset:offset + limit]
    next_offset = offset + len(page)
    next_cursor = _encode_cursor(next_offset) if next_offset < len(items) else None
    return {"data_version": DATA_VERSION, "items": page,
            "next_cursor": next_cursor}


@app.get("/api/v1/institutions/{institution_id}/rankings")
def get_institution_rankings(institution_id: str, request: Request):
    """One institution's provider records — or each one's explicit
    missing reason. World ranks only; no cross-provider combination."""
    inst = None
    for cand in RANKINGS.get("institutions", []):
        if cand["id"] == institution_id:
            inst = cand
            break
    if inst is None:
        return _err(request.state.request_id, "INSTITUTION_NOT_FOUND",
                    f"No institution with id '{institution_id}'.", 404)
    entries = [e for e in RANKINGS.get("entries", [])
               if e.get("institution_id") == institution_id]
    return {"data_version": DATA_VERSION, "institution": inst,
            "rankings": entries}


# --- 小罗盘 desktop-pet assistant (Day 3) -----------------------------------
# Rules/template only: no model is connected (ai_status="unavailable"),
# so these endpoints answer strictly from the verified catalogue — the 8
# programmes and the 300 ranking entries. See ai/assistant.py for the
# policy (unknown stays unknown, no probabilities, no personal data).
@app.post("/api/v1/assistant/suggest")
def assistant_suggest_endpoint(req: AssistantSuggestRequest, request: Request):
    """Answer to the pet's 3 quick-reply questions: degree level,
    country, budget band -> a short route suggestion (max 3 lines,
    conclusion first, ONE evidence link). Global scope: a country with
    no verified programme yet gets the honest unknown answer
    (suggest_none), never a 422 and never a guessed route. Only
    degree_level and budget_band are validated enums."""
    if req.degree_level not in DEGREE_LEVELS:
        return _err(request.state.request_id, "VALIDATION_ERROR",
                    f"degree_level must be one of {list(DEGREE_LEVELS)}, got {req.degree_level!r}.", 422,
                    field_errors=[{"field": "degree_level", "message": "Must be 'undergraduate' or 'taught_masters'."}])
    if req.budget_band not in BUDGET_BANDS:
        return _err(request.state.request_id, "VALIDATION_ERROR",
                    f"budget_band must be one of {list(BUDGET_BANDS)}, got {req.budget_band!r}.", 422,
                    field_errors=[{"field": "budget_band", "message": "Must be 'low', 'mid' or 'high'."}])
    return assistant_suggest(req.degree_level, req.country, req.budget_band,
                             req.locale or "en")


@app.post("/api/v1/assistant/ask")
def assistant_ask_endpoint(req: AssistantAskRequest, request: Request):
    """Free-text question to the pet. Answered only from verified data;
    personal data is refused, never echoed, never stored."""
    return assistant_ask(req.message, req.locale or "en")


def _profile_field_errors(profile: StudentProfile) -> list[dict]:
    """Out-of-range / malformed values. Grades are never silently rescaled;
    bad values are reported here instead (spec FR01/Ch12)."""
    errors: list[dict] = []

    def add(field: str, message: str):
        errors.append({"field": field, "message": message})

    lang = profile.language
    if lang is not None:
        for name, value in (("language.overall", lang.overall),
                            ("language.listening", lang.listening),
                            ("language.reading", lang.reading),
                            ("language.writing", lang.writing),
                            ("language.speaking", lang.speaking)):
            if value is not None and (value < 0 or value > 9):
                add(name, f"IELTS score {value} is out of range 0-9.")
        if lang.toefl_overall is not None and (lang.toefl_overall < 0 or lang.toefl_overall > 120):
            add("language.toefl_overall", f"TOEFL score {lang.toefl_overall} is out of range 0-120.")
        if lang.exam == "toefl" and lang.overall is not None and (lang.overall < 0 or lang.overall > 120):
            add("language.overall", f"TOEFL score {lang.overall} is out of range 0-120.")
        if lang.test_date is not None and _parse_test_date(lang.test_date) is None:
            add("language.test_date", f"Test date {lang.test_date!r} is not a valid ISO date (YYYY-MM-DD).")
    ug = profile.undergrad_profile
    if ug is not None:
        if ug.curriculum is not None and str(ug.curriculum).strip().lower() not in (
                "cn_gaokao", "uk_alevel", "ib", "usa", "sg_alevel", "other"):
            add("undergrad_profile.curriculum",
                f"Curriculum {ug.curriculum!r} is not recognised "
                "(cn_gaokao | uk_alevel | ib | usa | sg_alevel | other).")
        if ug.gaokao_score is not None and (ug.gaokao_score < 0 or ug.gaokao_score > 750):
            add("undergrad_profile.gaokao_score", f"Gaokao score {ug.gaokao_score} is out of range 0-750.")
        if ug.gaokao_total is not None and (ug.gaokao_total <= 0 or ug.gaokao_total > 750):
            add("undergrad_profile.gaokao_total", f"Gaokao total {ug.gaokao_total} is out of range 1-750.")
        if ug.gaokao_maths is not None and (ug.gaokao_maths < 0 or ug.gaokao_maths > 150):
            add("undergrad_profile.gaokao_maths", f"Gaokao maths {ug.gaokao_maths} is out of range 0-150.")
        if ug.sat_total is not None and (ug.sat_total < 400 or ug.sat_total > 1600):
            add("undergrad_profile.sat_total", f"SAT total {ug.sat_total} is out of range 400-1600.")
        if ug.act_composite is not None and (ug.act_composite < 1 or ug.act_composite > 36):
            add("undergrad_profile.act_composite", f"ACT composite {ug.act_composite} is out of range 1-36.")
        for g in (ug.ap_grades or []):
            if not isinstance(g, int) or g < 1 or g > 5:
                add("undergrad_profile.ap_grades", f"AP grade {g!r} is not a valid AP grade (1-5).")
        if ug.ib_total is not None and (ug.ib_total < 0 or ug.ib_total > 45):
            add("undergrad_profile.ib_total", f"IB total {ug.ib_total} is out of range 0-45.")
        if ug.ib_hl_total is not None and (ug.ib_hl_total < 0 or ug.ib_hl_total > 21):
            add("undergrad_profile.ib_hl_total", f"IB HL total {ug.ib_hl_total} is out of range 0-21 (three HL subjects, max 7 each).")
        if ug.ib_hl_maths_grade is not None and (ug.ib_hl_maths_grade < 1 or ug.ib_hl_maths_grade > 7):
            add("undergrad_profile.ib_hl_maths_grade", f"IB HL Maths grade {ug.ib_hl_maths_grade} is out of range 1-7.")
        for field, grades in (("undergrad_profile.a_level_grades", ug.a_level_grades or []),
                              ("undergrad_profile.a_level_maths_grade",
                               [ug.a_level_maths_grade] if ug.a_level_maths_grade else [])):
            for g in grades:
                if str(g).upper() not in ("A*", "A", "B", "C", "D", "E", "U"):
                    add(field, f"A-level grade {g!r} is not a recognised grade (A*-E, U).")
        for field, grade in (("undergrad_profile.gcse_english_grade", ug.gcse_english_grade),
                             ("undergrad_profile.gcse_maths_grade", ug.gcse_maths_grade)):
            if grade is not None:
                g = str(grade).strip().upper()
                if not (g.isdigit() and 1 <= int(g) <= 9) and g not in ("A*", "A", "B", "C", "D", "E", "F", "G", "U"):
                    add(field, f"GCSE grade {grade!r} is not a recognised grade (numeric 1-9 or A*-G, U).")
        if ug.residency is not None and ug.residency not in ("uk", "overseas"):
            add("undergrad_profile.residency", f"Residency {ug.residency!r} must be 'uk' or 'overseas'.")
        if ug.intake_year is not None and (ug.intake_year < 2000 or ug.intake_year > 2100):
            add("undergrad_profile.intake_year", f"Intake year {ug.intake_year} is out of range 2000-2100.")
    mp = profile.masters_profile
    if mp is not None:
        if mp.it_experience_years is not None and mp.it_experience_years < 0:
            add("masters_profile.it_experience_years", "IT experience years cannot be negative.")
        if mp.gre_total is not None and (mp.gre_total < 0 or mp.gre_total > 340):
            add("masters_profile.gre_total", f"GRE total {mp.gre_total} is out of range 0-340.")
        if mp.gre_analytical is not None and (mp.gre_analytical < 0 or mp.gre_analytical > 6):
            add("masters_profile.gre_analytical", f"GRE analytical {mp.gre_analytical} is out of range 0-6.")
        if mp.gmat_total is not None and (mp.gmat_total < 200 or mp.gmat_total > 800):
            add("masters_profile.gmat_total", f"GMAT total {mp.gmat_total} is out of range 200-800.")
    if profile.budget is not None and profile.budget.amount is not None \
            and profile.budget.amount < 0:
        add("budget.amount", "Budget amount cannot be negative.")
    if profile.target_intake is not None and (profile.target_intake < 2000 or profile.target_intake > 2100):
        add("target_intake", f"Target intake {profile.target_intake} is out of range 2000-2100.")
    return errors


def _profile_warnings(profile: StudentProfile) -> list[str]:
    """Missing optional fields that will make rules UNKNOWN later."""
    warnings: list[str] = []
    lang = profile.language
    if lang is None or lang.exam in (None, "none"):
        warnings.append("No language test supplied; language rules will be UNKNOWN.")
    elif lang.exam == "toefl" and not lang.test_date:
        warnings.append("TOEFL supplied without a test date; the UCL TOEFL rule will be UNKNOWN (Jan 2026 scale split needs the date).")
    elif lang.exam == "ielts" and lang.toefl_overall is None:
        pass  # TOEFL is optional alongside IELTS.
    if profile.budget is None or profile.budget.amount is None:
        warnings.append("No budget supplied; fee rules will be UNKNOWN.")
    ug = profile.undergrad_profile
    if ug is not None:
        curriculum = effective_curriculum(ug)
        if not ug.curriculum and not ug.qualification_type:
            warnings.append("No curriculum / qualification type supplied; the academic rule will be UNKNOWN.")
        if ug.qualification_type == "ib" and ug.ib_hl_total is None:
            warnings.append("IB HL total not supplied; the IB academic rule will be UNKNOWN.")
        if curriculum == "uk_alevel" and (ug.gcse_english_grade is None or ug.gcse_maths_grade is None):
            warnings.append("GCSE English/Maths grade(s) not supplied; the GCSE rule will be UNKNOWN.")
        if curriculum == "cn_gaokao" and ug.gaokao_score is None:
            warnings.append("Gaokao score not supplied; the academic rule will be UNKNOWN.")
        if curriculum == "usa" and not ug.ap_grades:
            warnings.append("No AP grades supplied; the academic rule will be UNKNOWN.")
        if ug.residency is None:
            warnings.append("Residency not supplied; the UCL fee rule assumes the overseas fee (£48,600/yr).")
        if ug.intake_year is None and profile.target_intake is None:
            warnings.append("Intake year not supplied.")
        if not ug.graduation_status:
            warnings.append("Graduation status not supplied.")
    mp = profile.masters_profile
    if mp is not None:
        if mp.gre_total is None and mp.gmat_total is None:
            warnings.append("No GRE/GMAT score supplied; the GRE/GMAT rule will be UNKNOWN.")
        if mp.it_experience_years is None:
            warnings.append("IT experience years not supplied; experience-based academic routes cannot be assessed.")
    return warnings


def _plain_json(value):
    """Recursively turn Decimals into plain JSON numbers.

    jsonable_encoder/model_dump(mode="json") render Decimal as a *string*,
    so normalized_profile is built from model_dump() through here instead.
    """
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(v) for v in value]
    return value


@app.post("/api/v1/profile/validate")
def validate_profile(profile: StudentProfile, request: Request):
    problem = _validate_profile(profile)
    if problem:
        return _err(request.state.request_id, "TRACK_MISMATCH", problem, 422,
                    field_errors=[{"field": "application_track", "message": problem}])
    field_errors = _profile_field_errors(profile)
    warnings = _profile_warnings(profile)
    return {"valid": not field_errors,
            "application_track": profile.application_track,
            "normalized_profile": _plain_json(profile.model_dump()),
            "warnings": warnings,
            "field_errors": field_errors}


@app.post("/api/v1/match")
async def match(request: Request):
    """Two shapes, one engine.

    Frontend contract: {"profile": <flat wizard profile>, "program_ids": [...]}
    -> {"evaluation_id", "results": [{programId, eligibilitySummary,
    ruleResults}], "rules_version", "source_manifest_hash"}.
    Spec/test contract: {"profile": <nested StudentProfile>, "program_id": str}
    -> single Evaluation (unchanged).
    """
    body = await request.json()
    rid = request.state.request_id
    if isinstance(body, dict) and "program_ids" in body:
        raw_profile = body.get("profile") or {}
        try:
            profile = _profile_from_raw(raw_profile)
        except Exception as exc:
            return _err(rid, "VALIDATION_ERROR", str(exc), 422)
        problem = _validate_profile(profile)
        if problem:
            return _err(rid, "TRACK_MISMATCH", problem, 422,
                        field_errors=[{"field": "application_track", "message": problem}])
        ids = body.get("program_ids") or []
        results = []
        skipped: list[str] = []
        for pid in ids:
            program = _get_programme_or_404(pid)
            if program is None:
                # Round 9, R11: one unresolvable id must not fail the
                # whole batch. An id is unresolvable when it is unknown
                # entirely or a display-only expansion programme (e.g.
                # 'ntu-cyber-msc-2027', listed by /programs but not
                # evaluable by /match). It is recorded in
                # skippedProgramIds and the resolvable programmes are
                # still evaluated, so the frontend can show the skipped
                # ones as unknown instead of failing.
                skipped.append(pid)
                continue
            mismatch = track_mismatch(profile, program)
            if mismatch:
                results.append({"programId": pid, "eligibilitySummary": "TRACK_MISMATCH",
                                "ruleResults": [], "trackMismatch": True})
                continue
            ev = _evaluate(profile, program, explain=False)
            results.append({"programId": pid,
                            "eligibilitySummary": summary_for(ev.overall_status),
                            "ruleResults": [rule_to_frontend(r) for r in ev.results],
                            "trackMismatch": False})
        if not results and skipped:
            # Nothing in the batch could be evaluated: keep the
            # pre-existing 404 contract for an all-unresolvable batch
            # (a lone display-only id still 404s, as before).
            if len(skipped) == 1:
                return _err(rid, "PROGRAM_NOT_FOUND",
                            f"No program with id '{skipped[0]}'.", 404)
            return _err(rid, "PROGRAM_NOT_FOUND",
                        f"No program with ids {skipped}.", 404)
        _attach_preference_fit(results, raw_profile)
        resp = match_response(f"eval-{rid[:8]}", results)
        if skipped:
            resp["skippedProgramIds"] = skipped
        return resp
    try:
        req = MatchRequest(**body)
    except Exception as exc:  # pydantic validation error -> 422, spec shape
        return _err(rid, "VALIDATION_ERROR", str(exc), 422)
    problem = _validate_profile(req.profile)
    if problem:
        return _err(rid, "TRACK_MISMATCH", problem, 422,
                    field_errors=[{"field": "application_track", "message": problem}])
    program = _get_programme_or_404(req.program_id)
    if program is None:
        return _err(rid, "PROGRAM_NOT_FOUND",
                    f"No program with id '{req.program_id}'.", 404)
    mismatch = track_mismatch(req.profile, program)
    if mismatch:
        return _err(rid, "TRACK_MISMATCH", mismatch, 422,
                    field_errors=[{"field": "application_track", "message": mismatch}])
    return _evaluate(req.profile, program)


@app.post("/api/v1/explain")
async def explain(request: Request):
    """Server-side recompute (spec Ch12). New shape:
    {"profile": <nested StudentProfile | flat wizard profile>,
     "program_ids": [...], "locale": "en"}.
    A client-supplied Evaluation (the Day-1 shape {"evaluation": ...}) is
    rejected with 422 EXPLAIN_REQUIRES_PROFILE — the server recomputes, it
    never repeats a caller's verdict. Returns one recomputed explanation
    per program, in the same multi-program shape as /match.
    """
    body = await request.json()
    rid = request.state.request_id
    if isinstance(body, dict) and "evaluation" in body:
        return _err(rid, "EXPLAIN_REQUIRES_PROFILE",
                    "POST /explain recomputes server-side from a profile; "
                    "a client-supplied Evaluation is not accepted. Send "
                    "{profile, program_ids, locale} instead.", 422,
                    field_errors=[{"field": "evaluation",
                                   "message": "Client-supplied evaluations are not accepted; the server recomputes."}])
    try:
        req = ExplainRequest(**body)
    except Exception as exc:
        return _err(rid, "VALIDATION_ERROR", str(exc), 422)
    try:
        profile = _profile_from_raw(req.profile)
    except Exception as exc:
        return _err(rid, "VALIDATION_ERROR", str(exc), 422)
    problem = _validate_profile(profile)
    if problem:
        return _err(rid, "TRACK_MISMATCH", problem, 422,
                    field_errors=[{"field": "application_track", "message": problem}])
    ids = list(req.program_ids or [])
    if req.program_id:
        ids.append(req.program_id)
    if not ids:
        return _err(rid, "VALIDATION_ERROR", "program_ids must list at least one program.", 422)
    results = []
    for pid in ids:
        program = _get_programme_or_404(pid)
        if program is None:
            return _err(rid, "PROGRAM_NOT_FOUND", f"No program with id '{pid}'.", 404)
        mismatch = track_mismatch(profile, program)
        if mismatch:
            results.append({"programId": pid, "eligibilitySummary": "TRACK_MISMATCH",
                            "ruleResults": [], "trackMismatch": True,
                            "explanation": None, "ai_status": "unavailable"})
            continue
        ev = _evaluate(profile, program, locale=req.locale or "en")
        results.append({"programId": pid,
                        "eligibilitySummary": summary_for(ev.overall_status),
                        "ruleResults": [rule_to_frontend(r) for r in ev.results],
                        "trackMismatch": False,
                        "ai_status": ev.ai_status,
                        "explanation": ev.explanation,
                        "explanation_structured": ev.explanation_structured})
    _attach_preference_fit(results, req.profile)
    return {"evaluation_id": f"explain-{rid[:8]}", "results": results,
            "rules_version": RULES_VERSION,
            "source_manifest_hash": source_manifest_hash(),
            "data_version": DATA_VERSION,
            "locale": req.locale or "en"}


@app.post("/api/v1/simulate")
async def simulate(request: Request):
    """Baseline vs patch, same rules and data version.

    Frontend contract: {"baseline_profile": <flat>, "patch": <flat partial>,
    "program_ids": [...]} -> {"baseline": <MatchResponse>,
    "scenario": <MatchResponse>, "delta": [{program_id, rule_id,
    baseline_status, scenario_status}]}.
    Multi-scenario (Day 3): {"baseline_profile", "scenarios":
    [{name, patch}], "program_ids", "locale", "explain"} ->
    {"baseline", "scenarios": [{name, patch, scenario, delta,
    programme_flips, flipped_program_ids, rule_flip_count}],
    "scenario", "delta", "leverage", "explanation"} — "scenario"/"delta"
    are the first scenario, kept for backward compatibility.
    "leverage" ranks the candidate single-field changes the engine
    actually evaluates (see ai/simulate_explain.leverage_candidates):
    {"top": <candidate with most flips, or None>, "all": [...]} where a
    candidate is {id, patch, change, flips, flipped_program_ids,
    rule_flips, flipped_rules}. Ranking is by programme flips first,
    then rule flips (NOT_MET -> MET); ties keep candidate order.
    A "programme flip" means the programme leaves NOT_MET — to MET or
    to PARTIAL_UNKNOWN (all known minimums met, some rule still
    UNKNOWN). The strict NOT_MET -> MET count is kept alongside as
    "flips_to_met": it is structurally 0 for many programmes (e.g. UCL
    TARA and every Gaokao academic rule stay UNKNOWN, so a fully-MET
    summary is unreachable), and reporting only the strict count would
    hide every real improvement. "top" is None when no candidate flips
    any rule.
    "explanation" is {text, structured, ai_status, source} where source
    is "model" only when a citation-checked model output was used, else
    "template" (deterministic, from engine numbers). A model call is
    made only when "explain" is true; otherwise the template is
    returned and no model is called. The numbers in the text are the
    engine-computed ones; the model words carry no numbers of their own.
    Spec/test contract: {"profile": <nested>, "program_id": str,
    "patch": <nested dict>} -> {"program_id", "baseline", "patched"}.
    Patch is a deep-merge onto the profile dict. Changing language overall
    must NOT change the component scores (they are separate fields).

    Evaluations here use explain=False: a MatchResponse carries no
    per-programme explanation, and a model call per programme per
    scenario would block the event loop for minutes on a 369-programme
    batch. The single-programme /explain endpoint still explains on
    demand.
    """
    body = await request.json()
    rid = request.state.request_id
    if isinstance(body, dict) and "baseline_profile" in body:
        raw_base = body.get("baseline_profile") or {}
        raw_patch = body.get("patch") or {}
        try:
            base = _profile_from_raw(raw_base)
        except Exception as exc:
            return _err(rid, "VALIDATION_ERROR", str(exc), 422)
        problem = _validate_profile(base)
        if problem:
            return _err(rid, "TRACK_MISMATCH", problem, 422,
                        field_errors=[{"field": "application_track", "message": problem}])
        ids = body.get("program_ids") or []
        scenarios_spec = body.get("scenarios")
        if scenarios_spec is None:
            scenarios_spec = [{"name": None, "patch": raw_patch}]
        if not isinstance(scenarios_spec, list) or not scenarios_spec:
            return _err(rid, "VALIDATION_ERROR",
                        "scenarios must be a non-empty list of {name, patch}.", 422)
        for spec in scenarios_spec:
            if not isinstance(spec, dict) or not isinstance(spec.get("patch") or {}, dict):
                return _err(rid, "VALIDATION_ERROR",
                            "each scenario must be {name, patch} with a patch object.", 422)
        # Resolve every programme up front so an unknown id 404s before
        # any evaluation runs.
        programs = []
        for pid in ids:
            program = _get_programme_or_404(pid)
            if program is None:
                return _err(rid, "PROGRAM_NOT_FOUND", f"No program with id '{pid}'.", 404)
            programs.append((pid, program))

        def _patched_profile(patch: dict) -> StudentProfile:
            if "application_track" in patch:
                patched_dict = copy.deepcopy(base.model_dump())
                _deep_merge(patched_dict, patch)
                return StudentProfile(**patched_dict)
            merged_flat = copy.deepcopy(raw_base)
            _deep_merge(merged_flat, patch)
            return flat_to_student(merged_flat)

        def _run(profile: StudentProfile, raw_flat: dict):
            """(frontend results, evaluations) for every programme."""
            results, evs = [], []
            for pid, program in programs:
                mismatch = track_mismatch(profile, program)
                if mismatch:
                    results.append({"programId": pid, "eligibilitySummary": "TRACK_MISMATCH",
                                    "ruleResults": [], "trackMismatch": True})
                    evs.append(None)
                    continue
                ev = _evaluate(profile, program, explain=False)
                evs.append(ev)
                results.append({"programId": pid, "eligibilitySummary": summary_for(ev.overall_status),
                                "ruleResults": [rule_to_frontend(r) for r in ev.results]})
            _attach_preference_fit(results, raw_flat)
            return results, evs

        def _delta_and_flips(base_evs, scen_evs):
            """Rule-level delta + programme flips.

            A programme "flips" when it leaves NOT_MET: to MET, or to
            PARTIAL_UNKNOWN (every known minimum met, an UNKNOWN rule
            remains — the common case, since e.g. UCL TARA and Gaokao
            academic rules are UNKNOWN by construction). The strict
            NOT_MET -> MET count is returned alongside.
            """
            delta, programme_flips, rule_flips, strict_met = [], [], 0, 0
            for (pid, _), b_ev, s_ev in zip(programs, base_evs, scen_evs):
                if b_ev is None or s_ev is None:
                    continue
                b_sum = summary_for(b_ev.overall_status)
                s_sum = summary_for(s_ev.overall_status)
                if b_sum == "NOT_MET" and s_sum in ("MET", "PARTIAL_UNKNOWN"):
                    programme_flips.append({"program_id": pid,
                                           "baseline_summary": "NOT_MET",
                                           "scenario_summary": s_sum})
                    if s_sum == "MET":
                        strict_met += 1
                for br, sr in zip(b_ev.results, s_ev.results):
                    if br.status != sr.status:
                        delta.append({"program_id": pid, "rule_id": br.rule_id,
                                      "baseline_status": br.status,
                                      "scenario_status": sr.status})
                        if br.status == "NOT_MET" and sr.status == "MET":
                            rule_flips += 1
            return delta, programme_flips, rule_flips, strict_met

        base_results, base_evs = _run(base, raw_base)
        scenario_entries = []
        for spec in scenarios_spec:
            try:
                patched = _patched_profile(spec.get("patch") or {})
            except Exception as exc:
                return _err(rid, "VALIDATION_ERROR", str(exc), 422)
            merged_flat = copy.deepcopy(raw_base)
            _deep_merge(merged_flat, spec.get("patch") or {})
            scen_results, scen_evs = _run(patched, merged_flat)
            delta, programme_flips, rule_flips, strict_met = _delta_and_flips(base_evs, scen_evs)
            scenario_entries.append({
                "name": spec.get("name"),
                "patch": spec.get("patch") or {},
                "scenario": match_response(f"eval-scen-{rid[:8]}", scen_results),
                "delta": delta,
                "programme_flips": programme_flips,
                "flipped_program_ids": [f["program_id"] for f in programme_flips],
                "flipped_to_met_ids": [f["program_id"] for f in programme_flips
                                       if f["scenario_summary"] == "MET"],
                "rule_flip_count": rule_flips})
        # Leverage diagnosis: one evaluation per candidate change.
        from ai.simulate_explain import explain_simulation, leverage_candidates
        leverage_all = []
        for cand in leverage_candidates(raw_base):
            try:
                cand_profile = _patched_profile(cand["patch"])
            except Exception:
                continue
            _cand_results, cand_evs = _run(cand_profile, {**raw_base, **cand["patch"]})
            _d, programme_flips, rule_flips, strict_met = _delta_and_flips(base_evs, cand_evs)
            flipped_rules = [d for d in _d if d["baseline_status"] == "NOT_MET"
                             and d["scenario_status"] == "MET"][:200]
            leverage_all.append({**cand,
                                 "flips": len(programme_flips),
                                 "flipped_program_ids": [f["program_id"] for f in programme_flips],
                                 "flips_to_met": strict_met,
                                 "rule_flips": rule_flips,
                                 "flipped_rules": flipped_rules})
        cand_order = [c["id"] for c in leverage_all]
        ranked = sorted(leverage_all,
                        key=lambda c: (-c["flips"], -c["rule_flips"],
                                       cand_order.index(c["id"])))
        top = ranked[0] if ranked and (ranked[0]["flips"] or ranked[0]["rule_flips"]) else None
        leverage = {"top": top, "all": leverage_all}
        # Round 14: the explanation (template + model) must only name
        # changes the caller actually asked to simulate. The response's
        # leverage stays the global diagnosis (pinned by the Round 12
        # tests; the frontend filters its display to the checked
        # scenarios), but the explanation's top line is the best change
        # among the requested ones. The scenario ``name`` is a localised
        # label, so it cannot key this — the FIELD is the stable
        # contract: a scenario patching ``budget`` is about the budget
        # levers, whatever target value it sets (a requested patch need
        # not equal the candidate's baseline+step patch).
        requested_fields = set()
        for spec in scenarios_spec:
            requested_fields.update((spec.get("patch") or {}).keys())
        scoped_all = [c for c in leverage_all
                      if set(c["patch"]) & requested_fields]
        scoped_ranked = sorted(
            scoped_all,
            key=lambda c: (-c["flips"], -c["rule_flips"],
                           cand_order.index(c["id"])))
        scoped_top = (scoped_ranked[0] if scoped_ranked
                      and (scoped_ranked[0]["flips"]
                           or scoped_ranked[0]["rule_flips"]) else None)
        leverage_for_explain = {"top": scoped_top, "all": scoped_all}
        baseline_unknown_academic = any(
            ev is not None and any(r.rule_id.endswith("-academic") and r.status == "UNKNOWN"
                                   for r in ev.results)
            for ev in base_evs)
        locale = body.get("locale") or "en"
        # Model-backed simulate shares the 10/min/IP AI budget (spec Ch15):
        # the path middleware cannot see the request body, so the explain
        # branch checks the AI bucket itself. Template-only calls stay on
        # the general bucket.
        provider = None
        if body.get("explain") is True:
            # Same per-user key as the middleware (Round 13): the
            # manual check must use _client_ip, not request.client.host.
            if _rate_limited(_client_ip(request), "ai", RATE_LIMIT_AI_PER_MIN):
                return _err(rid, "RATE_LIMITED",
                            "AI call budget exceeded; try again shortly.", 429)
            provider = ProviderAdapter()
        # Round 13 fail-fast: explain_simulation's model call is
        # synchronous (up to 15 s single attempt, no repair), so it
        # runs in a worker thread — the event loop stays free for
        # /health and every other request while the model thinks.
        # The hard 15 s cap (asyncio.wait_for) covers providers whose
        # own timeout is not honoured: on timeout the template
        # explanation (engine numbers, already computed) is returned
        # instead of making the frontend's 25 s attempt wait it out.
        # A model failure inside explain_simulation already falls back
        # to the template and never raises.
        try:
            structured, text, ai_status = await asyncio.wait_for(
                asyncio.to_thread(
                    explain_simulation,
                    scenarios=scenario_entries, leverage=leverage_for_explain,
                    baseline_unknown_academic=baseline_unknown_academic,
                    locale=locale, provider=provider),
                timeout=15.0)
        except asyncio.TimeoutError:
            structured, text, ai_status = explain_simulation(
                scenarios=scenario_entries, leverage=leverage_for_explain,
                baseline_unknown_academic=baseline_unknown_academic,
                locale=locale, provider=None)
        first = scenario_entries[0]
        return {"baseline": match_response(f"eval-base-{rid[:8]}", base_results),
                "scenarios": scenario_entries,
                "scenario": first["scenario"],
                "delta": first["delta"],
                "leverage": leverage,
                "explanation": {"text": text, "structured": structured,
                                "ai_status": ai_status,
                                "source": "model" if ai_status == "available" else "template",
                                "top_change": (scoped_top or {}).get("id")}}
    try:
        req = SimulateRequest(**body)
    except Exception as exc:
        return _err(rid, "VALIDATION_ERROR", str(exc), 422)
    problem = _validate_profile(req.profile)
    if problem:
        return _err(rid, "TRACK_MISMATCH", problem, 422,
                    field_errors=[{"field": "application_track", "message": problem}])
    program = _get_programme_or_404(req.program_id)
    if program is None:
        return _err(rid, "PROGRAM_NOT_FOUND",
                    f"No program with id '{req.program_id}'.", 404)
    mismatch = track_mismatch(req.profile, program)
    if mismatch:
        return _err(rid, "TRACK_MISMATCH", mismatch, 422,
                    field_errors=[{"field": "application_track", "message": mismatch}])

    baseline = _evaluate(req.profile, program)

    patched_dict = copy.deepcopy(req.profile.model_dump())
    _deep_merge(patched_dict, req.patch)
    patched_profile = StudentProfile(**patched_dict)
    patched = _evaluate(patched_profile, program)
    return {"program_id": req.program_id, "data_version": DATA_VERSION,
            "baseline": baseline, "patched": patched}


def _deep_merge(base: dict, patch: dict) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
