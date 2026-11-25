"""AI evaluation endpoint (Day 3, spec Ch17).

GET /api/v1/ai/evaluation?mode=template|model -> the 12-case evaluation
report from ai.evaluation.run_evaluation_set.

- mode=template (default): template path, no key needed.
- mode=model: the configured provider if one is available; otherwise the
  template path with a note in the report (never a 500 when no key is
  configured).
- Any other mode: 422 VALIDATION_ERROR via app.errors.error_response.

``get_provider()`` is module-level so tests can monkeypatch
``router_eval.get_provider``. This router is standalone: it is not
imported by app.main (main.py is untouched by the evaluation work).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from ai.evaluation import run_evaluation_set
from ai.provider import ProviderAdapter
from app.errors import error_response

router = APIRouter(prefix="/api/v1", tags=["ai"])


def get_provider() -> ProviderAdapter:
    """The configured provider. Monkeypatchable in tests."""
    return ProviderAdapter()


@router.get("/ai/evaluation")
def get_ai_evaluation(request: Request, mode: str = "template"):
    """Run the frozen 12-case AI evaluation set and return the report."""
    rid = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    if mode not in ("template", "model"):
        return error_response(
            rid, "VALIDATION_ERROR",
            "mode must be 'template' or 'model'.", 422,
            field_errors=[{"field": "mode",
                           "message": "mode must be 'template' or 'model'."}])
    try:
        if mode == "model":
            provider = get_provider()
            report = run_evaluation_set(provider=provider, use_model=True)
            if report["mode"] != "model":
                report["note"] = ("No AI provider configured; ran on the "
                                  "template path.")
        else:
            report = run_evaluation_set(use_model=False)
        return report
    except Exception:
        return error_response(
            rid, "EVALUATION_ERROR",
            "The AI evaluation run failed.", 500, retryable=False)
