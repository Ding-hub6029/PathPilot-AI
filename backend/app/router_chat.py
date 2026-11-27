"""Conversational chat + free-text profile parsing (Day 3).

Three endpoints, mounted under ``/api/v1`` by the app (this module does
NOT import ``app.main`` — that would be a circular import):

- ``POST /assistant/chat`` — one free-text question to the pet 小罗盘.
  Model-backed when a provider is configured, template-backed
  otherwise; see ``ai.chat`` for the grounding and fallback rules.
- ``POST /assistant/pref-chat`` — one turn of the model-led
  preference conversation (round 7): the model extracts the
  preferences this message states and picks the next question; see
  ``ai.pref_chat``. Extraction is validated server-side, never
  trusted; the offline path is honest (``ai_status="unavailable"``,
  empty extraction, deterministic next question).
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

import asyncio
import uuid
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, ValidationError, field_validator

from ai.chat import answer as chat_answer
from ai.parse import parse_profile
from ai.pref_chat import pref_answer
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
    # Devil's advocate (round 11): "devil" challenges the stated
    # preferences in ``profile`` with engine-computed conflicts; any
    # other value is a 422. ``profile`` is a plain dict validated
    # leniently in ai.chat (invalid values are dropped, never a 422):
    # {countries: [ISO codes], climate: warm|cool|four_seasons|mild,
    #  level: undergraduate|taught_masters,
    #  budget_amount: number, budget_currency: GBP|...,
    #  budget_period: per_year|total, city: str}.
    mode: Literal["normal", "devil"] = "normal"
    profile: dict | None = None
    # Caller-supplied programme scope (Round 21, W3): the programme
    # cards the user is looking at (RecChat's visible batch). Verified
    # ids only — ai.chat drops anything outside the verified
    # catalogue — so a deictic "this programme" question is answered
    # from those programmes' verified facts instead of the blanket
    # unknown. Never a programme the user named; the template's own
    # match still wins there.
    program_ids: list[str] = Field(default_factory=list, max_length=10)

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


class KnownPrefs(BaseModel):
    """Preferences already known, as the frontend sends them. Values
    are validated again in ``ai.pref_chat`` (invalid ones are dropped,
    never 422) — this model only enforces the JSON shape."""
    countries: list[str] = Field(default_factory=list)
    climate: str | None = None
    environment: str | None = None
    city: str | None = None
    afterGrad: str | None = None
    salary: float | None = None
    salaryCurrency: str | None = None
    pressure: str | None = None
    teaching: str | None = None
    note: str | None = None


class PrefChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    locale: str = "en"
    known: KnownPrefs = Field(default_factory=KnownPrefs)
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
    history: [{role, content}] (max 10 turns, each content max 500),
    mode: "normal"|"devil", profile: {...},
    program_ids: [verified programme ids in view]}`` — mode "devil" (round 11)
    challenges the stated preferences in ``profile`` with
    engine-computed conflicts; see ``ai.chat`` for the grounding and
    fallback rules. ``program_ids`` (round 21, W3) scopes a deictic
    "this programme" question to the cards the user is looking at.
    Response: ``{lines (at most 3, conclusion first), evidence_url,
    ai_status, model, sources: [{id, url, title}]}`` — devil replies
    additionally carry ``mode: "devil"`` and ``conflicts: [kinds]``.
    """
    req, err = await _parse_body(request, ChatRequest)
    if err is not None:
        return err
    # Round 9 (R6-backend): chat_answer's model call is synchronous
    # (httpx.Client, ~9-12 s live, up to 20 s + 15 s repair) and this
    # endpoint is async — calling it inline blocked the single
    # uvicorn event loop for the whole turn, so /health and every
    # other endpoint stopped answering. Run it in a worker thread:
    # the turn still takes as long as the model takes, but the loop
    # stays free for concurrent requests.
    return await asyncio.to_thread(
        chat_answer, req.message, req.locale,
        [turn.model_dump() for turn in req.history],
        provider=get_provider(), mode=req.mode, profile=req.profile,
        program_ids=req.program_ids)


@router.post("/assistant/pref-chat")
async def assistant_pref_chat_endpoint(request: Request):
    """One turn of the model-led preference conversation.

    Request: ``{message (1..500 chars), locale="en", known: {countries,
    climate, environment, city, afterGrad, salary, salaryCurrency,
    pressure, teaching, note}, history: [{role, content}] (max 10)}``.
    Response: ``{lines (at most 3, conclusion first, next question
    last — unless a WHY follow-up is present, in which case the WHY
    is the turn's question, the next-question line is withheld from
    lines and next_question names the deferred preference),
    evidence_url, ai_status, model, sources: [{id, url, title}],
    extracted, next_question, done}`` — ``extracted`` holds only the
    preferences understood from THIS message (validated server-side);
    ``next_question`` is the single most useful still-missing
    preference, or null when all 8 are known (``done`` True).
    """
    req, err = await _parse_body(request, PrefChatRequest)
    if err is not None:
        return err
    # Round 9 (R6-backend): same event-loop blockage as /assistant/chat
    # — the synchronous model call runs in a worker thread.
    return await asyncio.to_thread(
        pref_answer, req.message, req.locale,
        req.known.model_dump(),
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
    # Round 9 (R6-backend): same event-loop blockage as the chat
    # endpoints — the synchronous model call runs in a worker thread.
    return await asyncio.to_thread(
        parse_profile, req.text, req.locale, provider=get_provider())
