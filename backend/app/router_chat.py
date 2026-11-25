"""Conversational chat + free-text profile parsing (Day 3).

Two endpoints, mounted under ``/api/v1`` by the app (this module does
NOT import ``app.main`` — that would be a circular import):

- ``POST /assistant/chat`` — one free-text question to the pet 小罗盘.
  Model-backed when a provider is configured, template-backed
  otherwise; see ``ai.chat`` for the grounding and fallback rules.
- ``POST /profile/parse`` — parse free text into a
  StudentProfile-shaped dict. This NEVER applies a profile: it only
  returns the parse (``confirmation_required`` is always True);
  applying happens via the normal ``/match`` or ``/profile/validate``
  with the user-confirmed profile. See ``ai.parse``.

Validation: request bodies are parsed here and bad input returns the
standard error body (``422 VALIDATION_ERROR``) via
``app.errors.error_response``. Rate limiting (429) is handled by the
``app.main`` middleware, not here. Nothing is logged or stored: no
message, profile text or key is ever written anywhere by these
endpoints.

``get_provider()`` is module-level so tests can monkeypatch
``router_chat.get_provider`` to inject a provider backed by an
``httpx.MockTransport``.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, ValidationError, field_validator

from ai.chat import answer as chat_answer
from ai.parse import parse_profile
from ai.provider import ProviderAdapter
from app.errors import error_response

router = APIRouter(prefix="/api/v1", tags=["assistant"])


def get_provider() -> ProviderAdapter:
    """The configured provider (env AI_PROVIDER/AI_MODEL/AI_API_KEY).

    Monkeypatch ``router_chat.get_provider`` in tests to inject a
    mock-transport provider.
    """
    return ProviderAdapter()


# ---------------------------------------------------------------------------
# Request models (defined in this file)
# ---------------------------------------------------------------------------

class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=500)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    locale: str = "en"
    history: list[HistoryTurn] = Field(default_factory=list, max_length=10)

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value

    @field_validator("locale")
    @classmethod
    def _locale_default(cls, value: str) -> str:
        return value.strip() or "en"


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    locale: str = "en"

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value

    @field_validator("locale")
    @classmethod
    def _locale_default(cls, value: str) -> str:
        return value.strip() or "en"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def _validation_error_response(request: Request, exc: ValidationError):
    field_errors = [
        {"field": ".".join(str(part) for part in err.get("loc", ())),
         "message": err.get("msg", "Invalid value.")}
        for err in exc.errors()
    ]
    return error_response(_request_id(request), "VALIDATION_ERROR",
                          "Invalid request.", 422, field_errors=field_errors)


async def _parse_body(request: Request, model):
    """Parse + validate a JSON body; returns (instance, error_response)."""
    rid = _request_id(request)
    try:
        body = await request.json()
    except Exception:
        return None, error_response(
            rid, "VALIDATION_ERROR", "Request body must be valid JSON.", 422,
            field_errors=[{"field": "body", "message": "Request body must be valid JSON."}])
    if not isinstance(body, dict):
        return None, error_response(
            rid, "VALIDATION_ERROR", "Request body must be a JSON object.", 422,
            field_errors=[{"field": "body", "message": "Request body must be a JSON object."}])
    try:
        return model(**body), None
    except ValidationError as exc:
        return None, _validation_error_response(request, exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/assistant/chat")
async def assistant_chat_endpoint(request: Request):
    """Free-text question to 小罗盘.

    Request: ``{message (1..500 chars), locale="en",
    history: [{role, content}] (max 10 turns, each content max 500)}``.
    Response: ``{lines (at most 3, conclusion first), evidence_url,
    ai_status, model, sources: [{id, url, title}]}``.
    """
    req, err = await _parse_body(request, ChatRequest)
    if err is not None:
        return err
    return chat_answer(req.message, req.locale,
                       [turn.model_dump() for turn in req.history],
                       provider=get_provider())


@router.post("/profile/parse")
async def profile_parse_endpoint(request: Request):
    """Parse free text into a StudentProfile-shaped dict (parse only).

    Request: ``{text (1..2000 chars), locale="en"}``. Response:
    ``{parsed_profile, unparsed, confidence, confirmation_required,
    parser, ai_status, note}`` — the profile is NOT applied here; the
    caller applies the user-confirmed profile via ``/match`` or
    ``/profile/validate``.
    """
    req, err = await _parse_body(request, ParseRequest)
    if err is not None:
        return err
    return parse_profile(req.text, req.locale, provider=get_provider())
