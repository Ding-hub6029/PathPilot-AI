"""PathPilot AI Day-1 backend — FastAPI. Run from backend/ so that
`app`, `domain` and `ai` are importable top-level packages.

    uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import copy
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ai.explain import explain as build_explanation
from ai.provider import ProviderAdapter
from app.adapter import (flat_to_student, match_response, rule_to_frontend,
                         summary_for)
from app.data import DATA_VERSION, PROGRAMS
from app.schemas import (ErrorBody, ErrorResponse, Evaluation, ExplainRequest,
                         MatchRequest, SimulateRequest, StudentProfile)
from domain.eligibility import evaluate, overall_status, track_mismatch

app = FastAPI(title="PathPilot AI — Day 1 backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _err(request_id: str, code: str, message: str, status: int,
         field_errors: list[dict] | None = None, retryable: bool = False) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message,
                        field_errors=field_errors or [], retryable=retryable),
        request_id=request_id).model_dump()
    return JSONResponse(status_code=status, content=body)


@app.middleware("http")
async def _request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
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


def _evaluate(profile: StudentProfile, program: dict) -> Evaluation:
    results = evaluate(profile, program)
    provider = ProviderAdapter()
    ev = Evaluation(program_id=program["id"], data_version=DATA_VERSION,
                    overall_status=overall_status(results), results=results,
                    ai_status=provider.ai_status)
    ev.explanation = build_explanation(ev, provider)
    return ev


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "data_version": DATA_VERSION, "programs": len(PROGRAMS)}


@app.get("/api/v1/ready")
def ready():
    return {"status": "ready", "data_version": DATA_VERSION,
            "programs": sorted(PROGRAMS.keys()), "ai_status": ProviderAdapter().ai_status}


@app.get("/api/v1/programs")
def list_programs():
    items = list(PROGRAMS.values())
    # "items" is what the frontend contract expects; "programs" kept for
    # the Day-1 spec contract.
    return {"data_version": DATA_VERSION, "programs": items, "items": items}


@app.get("/api/v1/programs/{program_id}")
def get_program(program_id: str, request: Request):
    program = PROGRAMS.get(program_id)
    if program is None:
        return _err(request.state.request_id, "PROGRAM_NOT_FOUND",
                    f"No program with id '{program_id}'.", 404)
    return program


@app.post("/api/v1/profile/validate")
def validate_profile(profile: StudentProfile, request: Request):
    problem = _validate_profile(profile)
    if problem:
        return _err(request.state.request_id, "TRACK_MISMATCH", problem, 422,
                    field_errors=[{"field": "application_track", "message": problem}])
    return {"valid": True, "application_track": profile.application_track}


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
        profile = flat_to_student(raw_profile) if "application_track" not in raw_profile else StudentProfile(**raw_profile)
        problem = _validate_profile(profile)
        if problem:
            return _err(rid, "TRACK_MISMATCH", problem, 422,
                        field_errors=[{"field": "application_track", "message": problem}])
        ids = body.get("program_ids") or []
        results = []
        for pid in ids:
            program = PROGRAMS.get(pid)
            if program is None:
                return _err(rid, "PROGRAM_NOT_FOUND", f"No program with id '{pid}'.", 404)
            mismatch = track_mismatch(profile, program)
            if mismatch:
                results.append({"programId": pid, "eligibilitySummary": "TRACK_MISMATCH",
                                "ruleResults": [], "trackMismatch": True})
                continue
            ev = _evaluate(profile, program)
            results.append({"programId": pid,
                            "eligibilitySummary": summary_for(ev.overall_status),
                            "ruleResults": [rule_to_frontend(r) for r in ev.results],
                            "trackMismatch": False,
                            "ai_status": ev.ai_status,
                            "explanation": ev.explanation})
        return match_response(f"eval-{rid[:8]}", results)
    try:
        req = MatchRequest(**body)
    except Exception as exc:  # pydantic validation error -> 422, spec shape
        return _err(rid, "VALIDATION_ERROR", str(exc), 422)
    problem = _validate_profile(req.profile)
    if problem:
        return _err(rid, "TRACK_MISMATCH", problem, 422,
                    field_errors=[{"field": "application_track", "message": problem}])
    program = PROGRAMS.get(req.program_id)
    if program is None:
        return _err(rid, "PROGRAM_NOT_FOUND",
                    f"No program with id '{req.program_id}'.", 404)
    mismatch = track_mismatch(req.profile, program)
    if mismatch:
        return _err(rid, "TRACK_MISMATCH", mismatch, 422,
                    field_errors=[{"field": "application_track", "message": mismatch}])
    return _evaluate(req.profile, program)


@app.post("/api/v1/explain")
def explain(req: ExplainRequest):
    ev = req.evaluation
    ev.explanation = build_explanation(ev, ProviderAdapter())
    ev.ai_status = ProviderAdapter().ai_status
    return ev


@app.post("/api/v1/simulate")
async def simulate(request: Request):
    """Baseline vs patch, same rules and data version.

    Frontend contract: {"baseline_profile": <flat>, "patch": <flat partial>,
    "program_ids": [...]} -> {"baseline": <MatchResponse>,
    "scenario": <MatchResponse>, "delta": [{program_id, rule_id,
    baseline_status, scenario_status}]}.
    Spec/test contract: {"profile": <nested>, "program_id": str,
    "patch": <nested dict>} -> {"program_id", "baseline", "patched"}.
    Patch is a deep-merge onto the profile dict. Changing language overall
    must NOT change the component scores (they are separate fields).
    """
    body = await request.json()
    rid = request.state.request_id
    if isinstance(body, dict) and "baseline_profile" in body:
        raw_base = body.get("baseline_profile") or {}
        raw_patch = body.get("patch") or {}
        base = flat_to_student(raw_base) if "application_track" not in raw_base else StudentProfile(**raw_base)
        problem = _validate_profile(base)
        if problem:
            return _err(rid, "TRACK_MISMATCH", problem, 422,
                        field_errors=[{"field": "application_track", "message": problem}])
        ids = body.get("program_ids") or []
        patched_dict = copy.deepcopy(base.model_dump())
        if "application_track" in raw_patch:
            _deep_merge(patched_dict, raw_patch)
            patched = StudentProfile(**patched_dict)
        else:
            merged_flat = copy.deepcopy(raw_base)
            _deep_merge(merged_flat, raw_patch)
            patched = flat_to_student(merged_flat)
        base_results, scen_results, delta = [], [], []
        for pid in ids:
            program = PROGRAMS.get(pid)
            if program is None:
                return _err(rid, "PROGRAM_NOT_FOUND", f"No program with id '{pid}'.", 404)
            mismatch = track_mismatch(base, program)
            if mismatch:
                base_results.append({"programId": pid, "eligibilitySummary": "TRACK_MISMATCH",
                                     "ruleResults": [], "trackMismatch": True})
                scen_results.append({"programId": pid, "eligibilitySummary": "TRACK_MISMATCH",
                                     "ruleResults": [], "trackMismatch": True})
                continue
            b_ev, s_ev = _evaluate(base, program), _evaluate(patched, program)
            base_results.append({"programId": pid, "eligibilitySummary": summary_for(b_ev.overall_status),
                                 "ruleResults": [rule_to_frontend(r) for r in b_ev.results]})
            scen_results.append({"programId": pid, "eligibilitySummary": summary_for(s_ev.overall_status),
                                 "ruleResults": [rule_to_frontend(r) for r in s_ev.results]})
            for br, sr in zip(b_ev.results, s_ev.results):
                if br.status != sr.status:
                    delta.append({"program_id": pid, "rule_id": br.rule_id,
                                  "baseline_status": br.status, "scenario_status": sr.status})
        return {"baseline": match_response(f"eval-base-{rid[:8]}", base_results),
                "scenario": match_response(f"eval-scen-{rid[:8]}", scen_results),
                "delta": delta}
    try:
        req = SimulateRequest(**body)
    except Exception as exc:
        return _err(rid, "VALIDATION_ERROR", str(exc), 422)
    problem = _validate_profile(req.profile)
    if problem:
        return _err(rid, "TRACK_MISMATCH", problem, 422,
                    field_errors=[{"field": "application_track", "message": problem}])
    program = PROGRAMS.get(req.program_id)
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
