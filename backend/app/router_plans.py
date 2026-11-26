"""Improvement-plan API (Day 3, spec Ch6 FR13/FR14).

POST   /api/v1/improvement-plan
GET    /api/v1/improvement-plan/{plan_id}
GET    /api/v1/improvement-plan/{plan_id}/export
POST   /api/v1/improvement-plan/{plan_id}/tasks/{task_id}
POST   /api/v1/improvement-plan/reassess

``get_provider`` is module-level so tests can monkeypatch it. The router
never imports app.main (circular import); it reuses the app's own
flat-to-nested profile conversion (app.adapter.flat_to_student), the
shared error shape (app.errors.error_response), and the plans module
(ai.plans) for all plan logic.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ai.plans import (
    IllegalTransition,
    InvalidPatch,
    PlanError,
    PlanNotFound,
    ProgramNotEvaluable,
    TaskNotFound,
    create_plan,
    evaluate_programs,
    get_plan,
    program_is_display_only,
    reassess,
    resolve_program,
    update_task_status,
)
from ai.prompts import PROMPT_VERSION
from ai.provider import ProviderAdapter
from app.adapter import flat_to_student
from app.data import DATA_VERSION
from app.errors import error_response
from app.schemas import StudentProfile
from domain.eligibility import track_mismatch

router = APIRouter(prefix="/api/v1", tags=["improvement-plan"])


def get_provider() -> ProviderAdapter:
    """Module-level provider factory (tests monkeypatch this)."""
    return ProviderAdapter()


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def _err(request: Request, exc: PlanError):
    return error_response(_request_id(request), exc.code, exc.message,
                          exc.status)


def _profile_from_raw(raw_profile: dict) -> StudentProfile:
    """Nested StudentProfile dict or flat wizard profile -> StudentProfile
    (same conversion the app uses)."""
    if "application_track" in raw_profile:
        return StudentProfile(**raw_profile)
    return flat_to_student(raw_profile)


def _validate_profile(profile: StudentProfile) -> str | None:
    """Cross-track checks (same rules as app.main._validate_profile)."""
    if profile.application_track not in ("undergraduate", "taught_masters"):
        return (f"application_track must be 'undergraduate' or "
                f"'taught_masters', got '{profile.application_track}'.")
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


# ---------------------------------------------------------------------------
# Request models (defined in this file)
# ---------------------------------------------------------------------------

class BudgetInput(BaseModel):
    amount: float | None = None
    currency: str | None = None


class PlanCreateRequest(BaseModel):
    profile: dict
    program_ids: list[str] = Field(default_factory=list)
    deadline: str | None = None
    weekly_hours: float | None = None
    budget: BudgetInput | None = None
    locale: str = "en"


class TaskStatusRequest(BaseModel):
    status: str
    user_confirmed_evidence: str | None = None


class ReassessRequest(BaseModel):
    plan_id: str
    profile_patch: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/improvement-plan")
async def create_improvement_plan(request: Request):
    """Create a plan: diagnose gaps from engine evaluations, build tasks
    (model path when a provider is configured, templates otherwise).

    Request: {profile (nested StudentProfile dict or flat wizard profile),
    program_ids, deadline (ISO date, optional), weekly_hours (optional),
    budget {amount, currency} (optional), locale (default "en")}.
    Response: {plan_id, track, gap_assessment, tasks, weekly_schedule,
    assumptions, limitations, ai_status, versions: [1]}.
    """
    rid = _request_id(request)
    try:
        body = await request.json()
    except Exception:
        return error_response(rid, "VALIDATION_ERROR",
                              "Request body must be valid JSON.", 422)
    try:
        req = PlanCreateRequest(**body) if isinstance(body, dict) else None
        if req is None:
            raise ValueError("Request body must be a JSON object.")
    except Exception as exc:
        return error_response(rid, "VALIDATION_ERROR", str(exc), 422)
    if not req.program_ids:
        return error_response(rid, "VALIDATION_ERROR",
                              "program_ids must be a non-empty list.", 422)
    if req.weekly_hours is not None and req.weekly_hours < 0:
        return error_response(rid, "VALIDATION_ERROR",
                              "weekly_hours must not be negative.", 422)
    try:
        profile = _profile_from_raw(req.profile)
    except Exception as exc:
        return error_response(rid, "VALIDATION_ERROR", str(exc), 422)
    problem = _validate_profile(profile)
    if problem:
        return error_response(rid, "TRACK_MISMATCH", problem, 422,
                              field_errors=[{"field": "application_track",
                                             "message": problem}])
    programs: list[dict] = []
    for pid in req.program_ids:
        # Resolution: v2 PROGRAMS first, then matchable expansion
        # programmes (ai.plans.resolve_program). Display-only expansion
        # programmes are an honest 422, never a plan invented from
        # nothing; genuinely unknown ids stay 404.
        if program_is_display_only(pid):
            return _err(request, ProgramNotEvaluable(pid))
        program = resolve_program(pid)
        if program is None:
            return error_response(rid, "PROGRAM_NOT_FOUND",
                                  f"No program with id '{pid}'.", 404)
        mismatch = track_mismatch(profile, program)
        if mismatch:
            return error_response(rid, "TRACK_MISMATCH", mismatch, 422,
                                  field_errors=[{"field": "application_track",
                                                 "message": mismatch}])
        programs.append(program)
    budget = (req.budget.model_dump() if req.budget is not None else None)
    try:
        evaluations = evaluate_programs(profile, req.program_ids)
        # Round 13 fail-fast: create_plan's model call is synchronous
        # (one 15 s attempt, no repair — ai.plans._model_tasks), so it
        # runs in a worker thread; the event loop stays free for
        # /health and every other request while the model thinks. The
        # hard 15 s cap (asyncio.wait_for) covers providers whose own
        # timeout is not honoured: on timeout the plan is rebuilt
        # with no provider, i.e. the deterministic template tasks
        # (the gap assessment is engine-only, already computed).
        # A provider failure inside create_plan already falls back to
        # template tasks and never raises.
        try:
            plan = await asyncio.wait_for(
                asyncio.to_thread(
                    create_plan, profile, evaluations, programs,
                    req.deadline, req.weekly_hours, budget, req.locale,
                    get_provider()),
                timeout=15.0)
        except asyncio.TimeoutError:
            plan = await asyncio.to_thread(
                create_plan, profile, evaluations, programs,
                req.deadline, req.weekly_hours, budget, req.locale, None)
    except PlanError as exc:
        return _err(request, exc)
    except ValueError as exc:  # e.g. bad deadline
        return error_response(rid, "VALIDATION_ERROR", str(exc), 422)
    return {
        "plan_id": plan["plan_id"],
        "track": plan["track"],
        "program_ids": plan["program_ids"],
        "deadline": plan["deadline"],
        "gap_assessment": plan["gap_assessment"],
        "tasks": plan["tasks"],
        "weekly_schedule": plan["weekly_schedule"],
        "assumptions": plan["assumptions"],
        "limitations": plan["limitations"],
        "ai_status": plan["ai_status"],
        "versions": [v["version"] for v in plan["versions"]],
    }


@router.get("/improvement-plan/{plan_id}")
async def get_improvement_plan(plan_id: str, request: Request):
    """Return the stored plan (404 if unknown)."""
    try:
        return get_plan(plan_id)
    except PlanNotFound as exc:
        return _err(request, exc)


@router.get("/improvement-plan/{plan_id}/export")
async def export_improvement_plan(plan_id: str, request: Request):
    """The plan as a JSON export document (same content plus export
    metadata)."""
    from ai.plans import _now_iso

    try:
        plan = get_plan(plan_id)
    except PlanNotFound as exc:
        return _err(request, exc)
    plan["export_metadata"] = {
        "exported_at": _now_iso(),
        "plan_id": plan_id,
        "format": "json",
        "data_version": DATA_VERSION,
        "prompt_version": PROMPT_VERSION,
    }
    return plan


@router.post("/improvement-plan/{plan_id}/tasks/{task_id}")
async def update_plan_task(plan_id: str, task_id: str, request: Request):
    """Update one task's status. 422 on an illegal transition. Completing
    a task changes no rule status; user_confirmed_evidence is recorded
    as a user statement only."""
    rid = _request_id(request)
    try:
        body = await request.json()
    except Exception:
        return error_response(rid, "VALIDATION_ERROR",
                              "Request body must be valid JSON.", 422)
    try:
        req = TaskStatusRequest(**body) if isinstance(body, dict) else None
        if req is None:
            raise ValueError("Request body must be a JSON object.")
    except Exception as exc:
        return error_response(rid, "VALIDATION_ERROR", str(exc), 422)
    try:
        return update_task_status(plan_id, task_id, req.status,
                                  req.user_confirmed_evidence)
    except (PlanNotFound, TaskNotFound) as exc:
        return _err(request, exc)
    except (IllegalTransition, PlanError) as exc:
        return _err(request, exc)


@router.post("/improvement-plan/reassess")
async def reassess_improvement_plan(request: Request):
    """Recompute a plan's evaluations from a profile patch (engine only;
    a client-supplied verdict is never trusted)."""
    rid = _request_id(request)
    try:
        body = await request.json()
    except Exception:
        return error_response(rid, "VALIDATION_ERROR",
                              "Request body must be valid JSON.", 422)
    try:
        req = ReassessRequest(**body) if isinstance(body, dict) else None
        if req is None:
            raise ValueError("Request body must be a JSON object.")
    except Exception as exc:
        return error_response(rid, "VALIDATION_ERROR", str(exc), 422)
    try:
        return reassess(req.plan_id, req.profile_patch)
    except PlanNotFound as exc:
        return _err(request, exc)
    except (InvalidPatch, PlanError) as exc:
        return _err(request, exc)
