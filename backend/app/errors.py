"""Shared error-response helper for API routers (Day 3).

Same error body as app.main._err: {"error": {code, message, field_errors,
retryable}, "request_id": ...} plus the security headers. Routers import
this instead of duplicating the shape.
"""
from __future__ import annotations

from fastapi.responses import JSONResponse

from app.schemas import ErrorBody, ErrorResponse

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def error_response(request_id: str, code: str, message: str, status: int,
                   field_errors: list[dict] | None = None,
                   retryable: bool = False) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message,
                        field_errors=field_errors or [], retryable=retryable),
        request_id=request_id).model_dump()
    resp = JSONResponse(status_code=status, content=body)
    resp.headers.update(SECURITY_HEADERS)
    resp.headers["X-Request-Id"] = request_id
    return resp
