"""Shared /ai/status probe cache + known-down verdict (Round 25 W1).

This used to live in ``app.main`` (``_AI_STATUS_CACHE``,
``_model_skip_cached``), which only the /simulate handler could
consult: ``app.router_chat`` cannot import ``app.main`` (main mounts
the router — a circular import), so ``POST /assistant/chat`` never
knew the gateway was already known down and every turn paid the
full model budget proving it again (re-test task 19: ~15 s with a
profile, then the template list — while the same question without
a profile answered instantly once the breaker had tripped).

The cache + the skip verdict now live here, in a module that
imports only ``ai.provider`` (no ``app`` imports, so no cycle):
``app.main`` re-exports the names (its ``/ai/status`` endpoint
writes the same dict object, and ``app.main._AI_STATUS_CACHE`` /
``reset_ai_status_cache`` keep working for the existing tests),
and ``ai.chat`` consults ``model_skip_cached()`` before attempting
the model — the same fail-fast ``/simulate`` already has.

The verdict rules (unchanged from the old ``_model_skip_cached``):
- the circuit breaker is open (a slow model failure within the
  last 180 s) -> skip;
- a probe said "unavailable" within its 60 s TTL -> skip;
- a probe is in flight right now (lock held) -> do NOT wait on it,
  attempt as before;
- no cached verdict (cold cache) or a stale one -> attempt as before.

Nothing here is an endpoint and nothing is logged or stored beyond
the single cached payload dict.
"""
from __future__ import annotations

import threading
import time

from ai.provider import gateway_breaker_open

# --- /ai/status live-probe cache (Round 14) --------------------------------
# The probe exercises the gateway, so its result is cached for 60 s:
# at most one tiny probe per minute per backend process, shared by
# every user. reset_ai_status_cache() exists so tests can isolate
# probes; it is not an endpoint.
_AI_STATUS_TTL_S = 60.0
_AI_STATUS_CACHE: dict = {"at": 0.0, "payload": None}
_ai_status_lock = threading.Lock()


def reset_ai_status_cache() -> None:
    """Clear the cached /ai/status probe result (test isolation only)."""
    with _ai_status_lock:
        _AI_STATUS_CACHE["at"] = 0.0
        _AI_STATUS_CACHE["payload"] = None


def model_skip_cached() -> bool:
    """True when a model attempt would be wasted (Round 16 W3).

    The circuit breaker (ai.provider) only opens after a slow model
    failure, and the frontend's /ai/status read only gates the
    explain flag it sends — neither helps when the frontend's verdict
    is stale but the backend already knows: a probe that said
    "unavailable" within its 60 s TTL, or a breaker tripped by
    another endpoint's slow failure. In that case the caller skips
    the model attempt and the template renders in engine time
    instead of spending the 15 s model budget proving the gateway
    is still down (re-test task 10: 18 s to a template while the
    probe said "available" — the probe then only checked
    GET /models; it now confirms on the chat path, and this check
    makes the handler honour its verdict).

    Non-blocking: if a probe is in flight right now the lock is
    held and this returns False (attempt as before) instead of
    waiting on the probe. No cached verdict (cold cache) also means
    attempt as before — the probe refreshes on /ai/status reads.
    """
    if gateway_breaker_open():
        return True
    if not _ai_status_lock.acquire(blocking=False):
        return False
    try:
        payload = _AI_STATUS_CACHE["payload"]
        if payload is None:
            return False
        if time.monotonic() - _AI_STATUS_CACHE["at"] >= _AI_STATUS_TTL_S:
            return False
        return payload.get("ai_status") == "unavailable"
    finally:
        _ai_status_lock.release()


# Back-compat alias: the private name this function used to carry in
# app.main.
_model_skip_cached = model_skip_cached
