"""Why-not endpoint (Day 3, W2 build round).

POST /api/v1/whynot {profile, program_ids, locale} -> one
why-not explanation per programme, recomputed server-side from the
profile (a client-supplied Evaluation is never accepted — same rule
as /explain).

Round 13 fail-fast: the batched endpoint is TEMPLATE-ONLY. Each result
carries the /match ruleResults plus ``whynot`` from
ai.explain.compute_whynot (failing rules with exact engine gaps,
academic-unknown / Gaokao flags, and the cheapest fix — verified by
re-running the engine on the patched profile, never invented) and
always ``model_note=None`` / ``ai_status="unavailable"``. The
per-programme model polish that used to run here
(whynot_with_model -> explain_structured_with_status -> one sync
provider.chat of up to 30 s + 20 s repair PER programme, inline in
the async handler) blocked the single uvicorn event loop for ~11 s
per programme — 80 programmes ≈ 15 min of total backend
unresponsiveness per results-page load, which wedged /simulate,
/improvement-plan and chat behind it too. The deterministic template
already carries the verified why-not (same fix /match got in
Round 8), so the batch never touches the model at all.

The single-programme model-polish helper ai.explain.whnnot_with_model
is KEPT (and still unit-tested) as the on-demand path for one
programme: if it is ever wired to an endpoint, that endpoint must
run it in a worker thread with a <=15 s budget, never in a
per-programme loop. ``get_provider`` is kept for that future path
(and so tests can prove the batch never constructs a provider).

This router is standalone: main.py only mounts it, so the router
never imports app.main (no circular import). The coordinator
registers it at integration; until then the endpoint is exercised
through a test app in tests/test_whynot.py.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from ai.explain import compute_whynot
from ai.provider import ProviderAdapter
from app.adapter import (RULES_VERSION, flat_to_student, match_response,
                         rule_to_frontend, summary_for)
from app.data import DATA_VERSION, EXPANSION_MATCHABLE, PROGRAMS
from app.errors import error_response
from app.schemas import Evaluation, ExplainRequest, StudentProfile
from domain.eligibility import evaluate, overall_status, track_mismatch
from domain.expansion_eval import evaluate_expansion

router = APIRouter(prefix="/api/v1", tags=["whynot"])


def get_provider() -> ProviderAdapter:
    """The configured provider. Monkeypatchable in tests.

    Round 13: the batched /whynot handler no longer calls this — the
    batch is template-only and must never touch the model (see module
    docstring). Kept for the future single-programme on-demand path
    (ai.explain.whnnot_with_model) and so tests can prove the batch
    never constructs a provider.
    """
    return ProviderAdapter()


def _profile_from_raw(raw_profile: dict) -> StudentProfile:
    """Nested StudentProfile dict or flat wizard profile -> StudentProfile
    (same rule as app.main._profile_from_raw)."""
    if "application_track" in raw_profile:
        return StudentProfile(**raw_profile)
    return flat_to_student(raw_profile)


def _programme_or_none(program_id: str):
    if program_id in PROGRAMS:
        return PROGRAMS[program_id]
    if program_id in EXPANSION_MATCHABLE:
        return EXPANSION_MATCHABLE[program_id]
    return None


def _fee_currency(program: dict) -> str | None:
    fees = program.get("fees") or {}
    currency = fees.get("currency")
    return currency if isinstance(currency, str) and currency else None


@router.post("/whynot")
async def whynot(request: Request):
    """Server-side recompute of why-not explanations (spec W2).

    Body: {"profile": <nested StudentProfile | flat wizard profile>,
    "program_ids": [...], "locale": "en"}. A client-supplied
    Evaluation ({"evaluation": ...}) is rejected with 422
    EXPLAIN_REQUIRES_PROFILE, like /explain.
    """
    body = await request.json()
    rid = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    if isinstance(body, dict) and "evaluation" in body:
        return error_response(
            rid, "EXPLAIN_REQUIRES_PROFILE",
            "POST /whynot recomputes server-side from a profile; "
            "a client-supplied Evaluation is not accepted. Send "
            "{profile, program_ids, locale} instead.", 422,
            field_errors=[{"field": "evaluation",
                           "message": "Client-supplied evaluations are not accepted; the server recomputes."}])
    try:
        req = ExplainRequest(**body)
    except Exception as exc:
        return error_response(rid, "VALIDATION_ERROR", str(exc), 422)
    try:
        profile = _profile_from_raw(req.profile)
    except Exception as exc:
        return error_response(rid, "VALIDATION_ERROR", str(exc), 422)
    if profile.application_track not in ("undergraduate", "taught_masters"):
        return error_response(
            rid, "TRACK_MISMATCH",
            f"application_track must be 'undergraduate' or 'taught_masters', "
            f"got '{profile.application_track}'.", 422,
            field_errors=[{"field": "application_track",
                           "message": "Invalid application_track."}])
    ids = list(req.program_ids or [])
    if req.program_id:
        ids.append(req.program_id)
    if not ids:
        return error_response(
            rid, "VALIDATION_ERROR",
            "program_ids must list at least one program.", 422)
    locale = req.locale or "en"
    budget_currency = None
    if profile.budget is not None and profile.budget.currency:
        budget_currency = profile.budget.currency
    # Round 13 fail-fast: template-only batch — no provider is
    # constructed and no model call is made, however many ids arrive.
    # The template carries the verified why-not; a model note, if ever
    # wanted, belongs on a single-programme on-demand path, not here.
    results = []
    for pid in ids:
        program = _programme_or_none(pid)
        if program is None:
            return error_response(
                rid, "PROGRAM_NOT_FOUND", f"No program with id '{pid}'.", 404)
        mismatch = track_mismatch(profile, program)
        if mismatch:
            results.append({"programId": pid,
                            "eligibilitySummary": "TRACK_MISMATCH",
                            "ruleResults": [], "trackMismatch": True,
                            "whynot": None, "model_note": None,
                            "ai_status": "unavailable"})
            continue
        rule_results = (evaluate(profile, program) if pid in PROGRAMS
                        else evaluate_expansion(profile, program))
        ev = Evaluation(program_id=pid, data_version=DATA_VERSION,
                        overall_status=overall_status(rule_results),
                        results=rule_results)
        whynot = compute_whynot(
            ev, profile=profile, budget_currency=budget_currency,
            fee_currency=_fee_currency(program))
        results.append({"programId": pid,
                        "eligibilitySummary": summary_for(ev.overall_status),
                        "ruleResults": [rule_to_frontend(r) for r in ev.results],
                        "trackMismatch": False,
                        "whynot": whynot,
                        "model_note": None,
                        "ai_status": "unavailable"})
    resp = match_response(f"whynot-{rid[:8]}", results)
    resp["locale"] = locale
    return resp
