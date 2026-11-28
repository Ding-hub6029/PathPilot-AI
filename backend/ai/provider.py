"""AI provider client — real-model wiring (Day 3, DECISIONS #105).

Supports OpenAI-compatible chat-completions APIs (OpenAI, DeepSeek) and
Google Gemini, configured ONLY via environment variables:

- AI_PROVIDER: "openai" | "deepseek" | "gemini"
- AI_MODEL: model name, e.g. "gpt-4o-mini", "deepseek-chat",
  "gemini-2.0-flash"
- AI_API_KEY: the provider key. Never hardcoded, never stored in the repo,
  never logged, never echoed in an error message.
- AI_BASE_URL (optional): override the API base URL.
- AI_TIMEOUT_MS (optional): per-call budget cap in ms (default 60000).
  The spec Ch13/Ch17 20 s ceiling no longer matches observed gateway
  latency: live DeepSeek calls via the gateway took ~9-12 s each on
  2026-11-26, so a 20 s cap would clip the 30 s first-call budget the
  chat paths need (and the old 8 s repair budget was shorter than one
  call, so any first-attempt validation failure fell back).
- AI_MAX_TOKENS (optional): max output tokens per call (default 1200).

When any of provider/model/key is absent (or the provider is unknown),
``available`` is False and every AI endpoint must fall back honestly to
the rules/template behaviour with ai_status="unavailable" — a model
answer is never faked. Provider failures raise ProviderError (sanitised,
key-free); callers fall back to templates, never to invented text.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

import httpx

SUPPORTED_PROVIDERS = ("openai", "deepseek", "gemini")

# --- Gateway circuit breaker (Round 14) ------------------------------------
# The shenjyai gateway is intermittently down for minutes at a time
# (2026-11-27 00:42-00:50 CST: every model path template-only for the
# whole 8-minute browser run, while /ai/status still reported
# "available" — it only checked config). Every model call then burns
# its full 15 s budget before the template renders, and every endpoint
# pays it again on the next call because nothing remembers the failure.
#
# A slow failure (timeout / transport error — the gateway hanging or
# unreachable, the exact failure mode in the audit — or, since
# Round 24 W4, a slow HTTP 5xx: the relay answering 502 after its
# upstream hung, or, since Round 28 D3, a slow HTTP 200 with an
# empty or unreadable body: the relay answering garbage after its
# upstream hung) trips the breaker for GATEWAY_BREAKER_COOLDOWN_S:
# while it is open, chat()/achat() raise immediately without
# touching the network, so the callers fall back to their templates
# in engine time. A fast failure (HTTP 500, 401, bad JSON) does NOT
# trip it — it already fails fast, and a single 500 is not evidence
# the gateway is down. Any successful model call clears the breaker,
# and probe_live() bypasses it (the probe is what re-tests liveness)
# and clears it on success. The state is module-level, not
# per-adapter: adapters are constructed fresh per request, but the
# gateway is one shared service.
#
# Round 18 W2: the cooldown (180 s) deliberately OUTLIVES the 60 s
# /ai/status probe cache (app.main _AI_STATUS_TTL_S). With equal
# 60 s lifetimes both expired together, so the first user action
# after a minute of quiet paid the full 15 s model budget again —
# the 2026-11-27 10:19–10:24 re-test (parent's 10:18 check was fast
# on warm caches; the 10:23 clicks were not). Now a failed probe
# re-trips the breaker for another 180 s, and the frontend warms
# /ai/status every 45 s while the results page is open
# (SimulatePanel), so the breaker stays tripped for as long as the
# gateway stays down and the next turn is instant. Recovery is
# still detected: the probe bypasses the breaker, so the first probe
# after the cooldown expires clears it on success — the template-only
# lag after a real recovery is at most one cooldown.
GATEWAY_BREAKER_COOLDOWN_S = 180.0
_GATEWAY_BREAKER_LOCK = threading.Lock()
_gateway_down_until = 0.0


def gateway_breaker_open() -> bool:
    """True while the breaker is tripped (gateway recently hung)."""
    with _GATEWAY_BREAKER_LOCK:
        return time.monotonic() < _gateway_down_until


def reset_gateway_breaker() -> None:
    """Clear the breaker (test isolation; also called on recovery)."""
    global _gateway_down_until
    with _GATEWAY_BREAKER_LOCK:
        _gateway_down_until = 0.0


def _trip_gateway_breaker() -> None:
    global _gateway_down_until
    with _GATEWAY_BREAKER_LOCK:
        _gateway_down_until = time.monotonic() + GATEWAY_BREAKER_COOLDOWN_S


def _clear_gateway_breaker() -> None:
    global _gateway_down_until
    with _GATEWAY_BREAKER_LOCK:
        _gateway_down_until = 0.0


# A slow gateway failure trips the breaker; a fast one does not (see
# above). Only these kinds are "the gateway hung" — plus, since
# Round 24 W4, a slow HTTP 5xx (see _trips_breaker): the flapping
# relay answers 502 after its upstream hangs, so a 502 that took
# seconds to arrive is the same sickness as a timeout, and without
# tripping on it every chat turn paid the full ~12 s wait again.
# Round 28 D3 adds the two slow-200 kinds: "empty_reply" (the
# relay answers 200 with an empty body after seconds) and
# "bad_reply" (200 with an unreadable body after seconds) — both
# consumed the whole model budget and neither tripped, so the next
# turn paid the wait again (re-test 22: the second pref turn took
# ~15-25 s after a slow first failure). A slow 429 / 4xx still
# never trips (see _trips_breaker).
_BREAKER_TRIP_KINDS = ("timeout", "transport_error", "empty_reply", "bad_reply")

# Latency gate (Round 14 fix): the breaker exists to avoid REPEATING
# a slow wait, so only a failure that actually consumed real time
# trips it. An instant raise (e.g. the evaluation set's
# failure-timeout mock, which raises ReadTimeout immediately, or a
# connection-refused that fails in milliseconds) costs nothing to
# repeat and must NOT poison later calls: tripping on it turned one
# mock timeout in the 12-case evaluation run into 60 s of
# template-only for every later case and every later test in the
# process. Real hangs consume the full budget first (the audit's
# 15 s model attempts; the probe's 3 s GET), well above these bars.
_BREAKER_MIN_LATENCY_S = 5.0
_PROBE_BREAKER_MIN_LATENCY_S = 1.0

# Round 16 W3: budget for the probe's 1-token chat confirmation (see
# probe_live). A liveness call is time-to-first-token dominated — but
# the real gateway is slow even for that: a direct key test on
# 2026-11-27 ~03:36 CST measured a tiny chat answering in ~3.4 s
# while healthy — so 7 s is ~2x headroom over a healthy reply while
# still catching a hang in seconds instead of the 15 s model budget.
# (A 5 s budget was tried first and rejected: only 1.6 s of headroom
# over the measured 3.4 s would turn ordinary gateway slowness into
# false "unavailable" verdicts and template-only model paths.)
# The fallback chat probe (gateways without a /models endpoint) uses
# the same timeout_s - 3 s budget, i.e. 7 s at the default timeout.
_PROBE_CHAT_TIMEOUT_S = 7.0


def _slow_enough(started: float, minimum_s: float) -> bool:
    return (time.monotonic() - started) >= minimum_s


def _trips_breaker(exc: ProviderError, started: float,
                   minimum_s: float) -> bool:
    """True when a model failure should trip the gateway circuit
    breaker: the failure actually waited (latency-gated — an instant
    raise costs nothing to repeat), and its kind means the gateway
    hung: a timeout / transport error, a slow HTTP 200 with an empty
    or unreadable body (Round 28 D3: the relay answering garbage
    after its upstream hung is the same sickness as a timeout — the
    turn already paid the full model budget proving it), or — Round
    24 W4 — a slow HTTP 5xx. A 502/503 that took seconds to arrive
    is the relay reporting its upstream hung; every later turn would
    pay the same wait, so the breaker must remember it. A fast 5xx
    still does not trip (the existing test_breaker_does_not_trip_on_fast_500
    pins that: one transient 500 is not evidence the gateway is
    down), and a 429 / 4xx never trips however slow — a 429 means
    the gateway is UP but throttling, and a 4xx is our request,
    not the gateway. A fast empty / unreadable reply likewise does
    not trip: it failed fast, so repeating it costs nothing."""
    if not _slow_enough(started, minimum_s):
        return False
    if exc.kind in _BREAKER_TRIP_KINDS:
        return True
    return (exc.kind == "provider_http"
            and (exc.status_code or 0) >= 500)

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}

DEFAULT_TIMEOUT_MS = 60_000
DEFAULT_MAX_TOKENS = 1200


class ProviderError(Exception):
    """A model call failed. ``message`` is sanitised: it never contains
    the API key, the request body, or a raw provider error payload.
    ``status_code`` is the HTTP status when the failure was an HTTP
    error response (None otherwise): the breaker logic needs it to
    tell a slow 5xx (gateway sick) from a 429 / 4xx (gateway up)."""

    def __init__(self, message: str, *, retryable: bool = False,
                 kind: str = "provider_error",
                 status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.kind = kind
        self.status_code = status_code


@dataclass
class ChatResult:
    text: str
    model: str
    provider: str
    latency_ms: int
    usage: dict = field(default_factory=dict)


class ProviderAdapter:
    """One provider, configured from the environment at construction.

    ``_transport`` exists only so tests can inject an httpx.MockTransport;
    production code never passes it.
    """

    def __init__(self, *, _transport: httpx.BaseTransport | None = None) -> None:
        self.provider = os.environ.get("AI_PROVIDER", "").strip() or None
        self.model = os.environ.get("AI_MODEL", "").strip() or None
        self.api_key = os.environ.get("AI_API_KEY", "").strip() or None
        self.base_url = (
            os.environ.get("AI_BASE_URL", "").strip()
            or (DEFAULT_BASE_URLS.get(self.provider) if self.provider else None)
        )
        try:
            self.timeout_ms = int(os.environ.get("AI_TIMEOUT_MS", "") or DEFAULT_TIMEOUT_MS)
        except ValueError:
            self.timeout_ms = DEFAULT_TIMEOUT_MS
        try:
            self.max_tokens = int(os.environ.get("AI_MAX_TOKENS", "") or DEFAULT_MAX_TOKENS)
        except ValueError:
            self.max_tokens = DEFAULT_MAX_TOKENS
        self._transport = _transport

    @property
    def available(self) -> bool:
        return bool(self.provider and self.model and self.api_key
                    and self.provider in SUPPORTED_PROVIDERS)

    @property
    def ai_status(self) -> str:
        return "available" if self.available else "unavailable"

    def describe(self) -> dict:
        # Never expose the key value.
        return {"provider": self.provider, "model": self.model,
                "api_key_configured": bool(self.api_key),
                "ai_status": self.ai_status,
                "supported_providers": list(SUPPORTED_PROVIDERS)}

    # -- low-level HTTP -----------------------------------------------------
    # trust_env=False (round 11, F3): the provider connects directly to
    # the configured AI_BASE_URL and never through an environment proxy
    # — no proxy variable is part of the documented config surface, and
    # httpx's env-proxy parsing raises InvalidURL (not an HTTPError) on
    # unparseable proxy values (e.g. bracketed IPv6 literals in
    # NO_PROXY), which used to escape the ProviderError contract below
    # and 500 the whole chat endpoint instead of failing fast to the
    # template fallback. It also keeps the API key off any unexpected
    # egress proxy.
    def _client(self, timeout_s: float) -> httpx.Client:
        kwargs: dict = {"timeout": timeout_s, "trust_env": False}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.Client(**kwargs)

    def _async_client(self, timeout_s: float) -> httpx.AsyncClient:
        kwargs: dict = {"timeout": timeout_s, "trust_env": False}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    def _auth_headers(self) -> dict:
        """Auth header for this provider (never logged, never returned)."""
        if self.provider == "gemini":
            return {"x-goog-api-key": self.api_key or ""}
        return {"Authorization": f"Bearer {self.api_key or ''}",
                "Content-Type": "application/json"}

    def _probe_chat_call(self, timeout_s: float) -> bool:
        """One 1-token chat call as a liveness check. True only when
        the gateway actually answers on the model path. A slow
        failure (timeout / transport error that actually waited)
        trips the breaker, like a slow model call would; a fast
        failure (HTTP 500, bad reply, auth) already fails fast and
        does not. Bypasses the breaker — the probe is what re-tests
        liveness. Never raises: any ProviderError means not live."""
        started = time.monotonic()
        try:
            self.chat([{"role": "user", "content": "ok"}],
                      timeout_s=timeout_s,
                      max_tokens=1, temperature=0.0,
                      _bypass_breaker=True)
        except ProviderError as exc:
            # chat() itself trips the breaker on a slow timeout /
            # transport failure (and, since Round 24 W4, a slow 5xx;
            # since Round 28 D3, a slow empty / unreadable reply);
            # trip here too for the same kinds so the verdict is
            # consistent even if chat() did not (e.g. a ProviderError
            # raised before the trip logic runs).
            if exc.retryable and _trips_breaker(
                    exc, started, _PROBE_BREAKER_MIN_LATENCY_S):
                _trip_gateway_breaker()
            return False
        return True

    def probe_live(self, timeout_s: float = 10.0) -> bool:
        """Live gateway probe (Round 14, tightened Round 16 W3): True
        only when the gateway actually answers right now. /ai/status
        used to report the config-only ``ai_status`` ("available"
        whenever a key was configured), so it said "available"
        through a whole 8-minute outage. This exercises the real path
        instead:

        1. GET {base_url}/models (no generation, no tokens, fast when
           the gateway is up). 200 means the list endpoint answers —
           but NOT that the model works (Round 16 W3: the audit's
           gateway answered /models while POST /chat/completions
           hung, so the probe said "available" and a simulate click
           then spent the full 15 s model budget — re-test task 10,
           18 s to a template). So a 200 falls through to step 2
           as a confirmation. 401/403 means the key is rejected —
           the model cannot work, so False without tripping the
           breaker (a bad key fails fast anyway). Any other status
           (404/405/501: this gateway does not implement the list
           endpoint) falls through to step 2 as the only signal.
        2. One tiny chat call (max_tokens=1), bypassing the breaker —
           the probe is what re-tests liveness, so it must not be
           blocked by the breaker it is meant to clear. Success
           clears the breaker; any failure returns False.

        A transport error / timeout on step 1 trips the breaker and
        returns False at once — but only when the attempt actually
        waited (latency-gated, see _PROBE_BREAKER_MIN_LATENCY_S):
        an instant raise costs nothing to repeat. The whole
        probe costs at most ~timeout_s and is cached for 60 s by the
        /ai/status endpoint, so it is ~1 tiny call per minute per
        backend process, not one per user request."""
        if not self.available:
            return False
        probe_started = time.monotonic()
        try:
            with self._client(min(timeout_s, 3.0)) as client:
                resp = client.get(f"{self.base_url}/models",
                                  headers=self._auth_headers())
            if resp.status_code in (401, 403):
                return False
            if resp.status_code == 200:
                # List endpoint answers — confirm on the real model
                # path before reporting live (see step 1 above).
                return self._probe_chat_call(_PROBE_CHAT_TIMEOUT_S)
            # Any other status: this gateway may not implement the
            # list endpoint — fall through to the chat probe.
        except httpx.TimeoutException:
            # Latency-gated (see _BREAKER_MIN_LATENCY_S): only a GET
            # that actually waited trips the breaker; an instant
            # raise costs nothing to repeat.
            if _slow_enough(probe_started, _PROBE_BREAKER_MIN_LATENCY_S):
                _trip_gateway_breaker()
            return False
        except httpx.HTTPError:
            if _slow_enough(probe_started, _PROBE_BREAKER_MIN_LATENCY_S):
                _trip_gateway_breaker()
            return False
        except ValueError:
            # Malformed base URL: the chat probe would fail the same
            # way, fast — report it without spending the chat budget.
            return False
        # Fallback for gateways without a list endpoint: the chat call
        # is the only liveness signal, so it keeps the looser
        # timeout_s - 3 s budget (see _PROBE_CHAT_TIMEOUT_S).
        return self._probe_chat_call(max(1.0, timeout_s - 3.0))

    # -- public API ---------------------------------------------------------
    def chat(self, messages: list[dict], *, system: str | None = None,
             timeout_s: float | None = None, max_tokens: int | None = None,
             temperature: float = 0.2, _bypass_breaker: bool = False) -> ChatResult:
        """One chat-completions call. ``messages`` is a list of
        {"role": "user"|"assistant", "content": str}. Raises ProviderError
        on any failure; never returns invented text.

        Round 14: while the gateway circuit breaker is open (a recent
        timeout / transport failure — the gateway hung), this raises
        immediately without a network call, so callers fall back to
        their templates in engine time instead of spending another
        15 s proving the gateway is still down. ``_bypass_breaker``
        is for probe_live() only — the probe is what re-tests
        liveness."""
        if not self.available:
            raise ProviderError(
                "No AI provider configured (AI_PROVIDER/AI_MODEL/AI_API_KEY "
                "absent or incomplete).", retryable=False, kind="not_configured")
        if not _bypass_breaker and gateway_breaker_open():
            raise ProviderError(
                "AI gateway recently failed; skipping model call.",
                retryable=True, kind="gateway_breaker_open")
        budget_s = (self.timeout_ms / 1000.0)
        if timeout_s is None:
            timeout_s = budget_s
        else:
            timeout_s = min(timeout_s, budget_s)
        started = time.monotonic()
        try:
            if self.provider in ("openai", "deepseek"):
                text, usage = self._chat_openai_compatible(
                    messages, system=system, timeout_s=timeout_s,
                    max_tokens=max_tokens or self.max_tokens,
                    temperature=temperature)
            elif self.provider == "gemini":
                text, usage = self._chat_gemini(
                    messages, system=system, timeout_s=timeout_s,
                    max_tokens=max_tokens or self.max_tokens,
                    temperature=temperature)
            else:  # pragma: no cover - guarded by `available`
                raise ProviderError(f"Unsupported provider {self.provider!r}.",
                                    retryable=False, kind="unsupported_provider")
        except ProviderError as exc:
            # Round 14: a slow failure trips the breaker (see the
            # module header); a fast one (HTTP 500, bad reply, auth)
            # already fails fast and does not. The breaker-open raise
            # above has kind "gateway_breaker_open" and must not
            # re-trip (it would extend the cooldown on every call).
            # Latency-gated: only a failure that actually waited
            # trips it (an instant mock timeout must not poison
            # later calls — see _BREAKER_MIN_LATENCY_S). Round 24
            # W4: a slow HTTP 5xx trips too (see _trips_breaker).
            if (exc.retryable
                    and _trips_breaker(exc, started, _BREAKER_MIN_LATENCY_S)):
                _trip_gateway_breaker()
            raise
        except httpx.TimeoutException:
            if _slow_enough(started, _BREAKER_MIN_LATENCY_S):
                _trip_gateway_breaker()
            raise ProviderError("AI provider call timed out.",
                                retryable=True, kind="timeout")
        except httpx.HTTPError:
            if _slow_enough(started, _BREAKER_MIN_LATENCY_S):
                _trip_gateway_breaker()
            raise ProviderError("Could not reach the AI provider.",
                                retryable=True, kind="transport_error")
        except ValueError:
            # httpx.InvalidURL (a ValueError, not an HTTPError): a
            # malformed AI_BASE_URL, raised while building the client
            # or the request. A bad provider URL is a provider error,
            # not a 500 — callers fall back to the template.
            raise ProviderError("AI provider URL is not usable.",
                                retryable=False, kind="bad_url")
        latency_ms = int((time.monotonic() - started) * 1000)
        if not text or not text.strip():
            # Round 28 D3: this raise used to sit outside the try
            # block above, so a slow empty reply never tripped the
            # breaker and the next turn paid the model budget again
            # (re-test 22, second pref turn ~15-25 s). Route it
            # through the same trip decision as every other slow
            # failure — _trips_breaker, latency-gated, 429 / 4xx
            # pins untouched (an empty reply is neither).
            exc = ProviderError("AI provider returned an empty reply.",
                                retryable=True, kind="empty_reply")
            if _trips_breaker(exc, started, _BREAKER_MIN_LATENCY_S):
                _trip_gateway_breaker()
            raise exc
        _clear_gateway_breaker()
        return ChatResult(text=text.strip(), model=self.model or "",
                          provider=self.provider or "", latency_ms=latency_ms,
                          usage=usage)

    def generate(self, prompt: str, timeout_s: float = 10.0) -> str:
        """Backwards-compatible single-prompt call (used by the Day-1/2
        explain path). Callers that need structure should use chat()."""
        return self.chat([{"role": "user", "content": prompt}],
                         timeout_s=timeout_s).text

    async def achat(self, messages: list[dict], *, system: str | None = None,
                    timeout_s: float | None = None,
                    max_tokens: int | None = None,
                    temperature: float = 0.2,
                    _bypass_breaker: bool = False) -> ChatResult:
        """Async twin of :meth:`chat`: the same request, validation and
        error mapping, but over ``httpx.AsyncClient`` — awaiting it
        never blocks the server's event loop, so a slow model call
        cannot wedge /health or any other endpoint. Same
        ``ProviderError`` contract as :meth:`chat`; never returns
        invented text. Same circuit breaker as :meth:`chat` (Round 14)."""
        if not self.available:
            raise ProviderError(
                "No AI provider configured (AI_PROVIDER/AI_MODEL/AI_API_KEY "
                "absent or incomplete).", retryable=False, kind="not_configured")
        if not _bypass_breaker and gateway_breaker_open():
            raise ProviderError(
                "AI gateway recently failed; skipping model call.",
                retryable=True, kind="gateway_breaker_open")
        budget_s = (self.timeout_ms / 1000.0)
        if timeout_s is None:
            timeout_s = budget_s
        else:
            timeout_s = min(timeout_s, budget_s)
        started = time.monotonic()
        try:
            if self.provider in ("openai", "deepseek"):
                text, usage = await self._achat_openai_compatible(
                    messages, system=system, timeout_s=timeout_s,
                    max_tokens=max_tokens or self.max_tokens,
                    temperature=temperature)
            elif self.provider == "gemini":
                text, usage = await self._achat_gemini(
                    messages, system=system, timeout_s=timeout_s,
                    max_tokens=max_tokens or self.max_tokens,
                    temperature=temperature)
            else:  # pragma: no cover - guarded by `available`
                raise ProviderError(f"Unsupported provider {self.provider!r}.",
                                    retryable=False, kind="unsupported_provider")
        except ProviderError as exc:
            # Same trip rule as chat() (Round 24 W4: slow 5xx trips).
            if (exc.retryable
                    and _trips_breaker(exc, started, _BREAKER_MIN_LATENCY_S)):
                _trip_gateway_breaker()
            raise
        except httpx.TimeoutException:
            if _slow_enough(started, _BREAKER_MIN_LATENCY_S):
                _trip_gateway_breaker()
            raise ProviderError("AI provider call timed out.",
                                retryable=True, kind="timeout")
        except httpx.HTTPError:
            if _slow_enough(started, _BREAKER_MIN_LATENCY_S):
                _trip_gateway_breaker()
            raise ProviderError("Could not reach the AI provider.",
                                retryable=True, kind="transport_error")
        except ValueError:
            # Same malformed-URL mapping as chat(): a bad provider
            # URL is a provider error, not a 500.
            raise ProviderError("AI provider URL is not usable.",
                                retryable=False, kind="bad_url")
        latency_ms = int((time.monotonic() - started) * 1000)
        if not text or not text.strip():
            # Round 28 D3: same trip routing as chat() — a slow
            # empty reply trips the breaker (see the comment there).
            exc = ProviderError("AI provider returned an empty reply.",
                                retryable=True, kind="empty_reply")
            if _trips_breaker(exc, started, _BREAKER_MIN_LATENCY_S):
                _trip_gateway_breaker()
            raise exc
        _clear_gateway_breaker()
        return ChatResult(text=text.strip(), model=self.model or "",
                          provider=self.provider or "", latency_ms=latency_ms,
                          usage=usage)

    # -- OpenAI-compatible (OpenAI, DeepSeek) --------------------------------
    def _chat_openai_compatible(self, messages, *, system, timeout_s,
                                max_tokens, temperature):
        payload_messages = ([{"role": "system", "content": system}]
                            if system else []) + list(messages)
        body = {"model": self.model, "messages": payload_messages,
                "temperature": temperature, "max_tokens": max_tokens}
        with self._client(timeout_s) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions", json=body,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"})
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderError(
                f"AI provider returned HTTP {resp.status_code}.",
                retryable=True, kind="provider_http",
                status_code=resp.status_code)
        if resp.status_code >= 400:
            raise ProviderError(
                f"AI provider rejected the request (HTTP {resp.status_code}).",
                retryable=False, kind="provider_http",
                status_code=resp.status_code)
        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("AI provider returned an unreadable reply.",
                                retryable=True, kind="bad_reply")
        if not isinstance(text, str):
            raise ProviderError("AI provider returned an unreadable reply.",
                                retryable=True, kind="bad_reply")
        return text, usage

    # -- Google Gemini --------------------------------------------------------
    def _chat_gemini(self, messages, *, system, timeout_s,
                     max_tokens, temperature):
        # Gemini roles are "user" / "model"; system goes in systemInstruction.
        contents = []
        for m in messages:
            role = "model" if m.get("role") == "assistant" else "user"
            contents.append({"role": role,
                             "parts": [{"text": m.get("content", "")}]})
        body: dict = {
            "contents": contents,
            "generationConfig": {"temperature": temperature,
                                 "maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        with self._client(timeout_s) as client:
            resp = client.post(
                f"{self.base_url}/models/{self.model}:generateContent",
                json=body,
                headers={"x-goog-api-key": self.api_key,
                         "Content-Type": "application/json"})
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderError(
                f"AI provider returned HTTP {resp.status_code}.",
                retryable=True, kind="provider_http",
                status_code=resp.status_code)
        if resp.status_code >= 400:
            raise ProviderError(
                f"AI provider rejected the request (HTTP {resp.status_code}).",
                retryable=False, kind="provider_http",
                status_code=resp.status_code)
        try:
            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            usage = data.get("usageMetadata") or {}
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("AI provider returned an unreadable reply.",
                                retryable=True, kind="bad_reply")
        return text, usage

    # -- Async twins (same payloads / error mapping as above) --------------
    async def _achat_openai_compatible(self, messages, *, system, timeout_s,
                                       max_tokens, temperature):
        payload_messages = ([{"role": "system", "content": system}]
                            if system else []) + list(messages)
        body = {"model": self.model, "messages": payload_messages,
                "temperature": temperature, "max_tokens": max_tokens}
        async with self._async_client(timeout_s) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=body,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"})
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderError(
                f"AI provider returned HTTP {resp.status_code}.",
                retryable=True, kind="provider_http",
                status_code=resp.status_code)
        if resp.status_code >= 400:
            raise ProviderError(
                f"AI provider rejected the request (HTTP {resp.status_code}).",
                retryable=False, kind="provider_http",
                status_code=resp.status_code)
        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("AI provider returned an unreadable reply.",
                                retryable=True, kind="bad_reply")
        if not isinstance(text, str):
            raise ProviderError("AI provider returned an unreadable reply.",
                                retryable=True, kind="bad_reply")
        return text, usage

    async def _achat_gemini(self, messages, *, system, timeout_s,
                            max_tokens, temperature):
        contents = []
        for m in messages:
            role = "model" if m.get("role") == "assistant" else "user"
            contents.append({"role": role,
                             "parts": [{"text": m.get("content", "")}]})
        body: dict = {
            "contents": contents,
            "generationConfig": {"temperature": temperature,
                                 "maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        async with self._async_client(timeout_s) as client:
            resp = await client.post(
                f"{self.base_url}/models/{self.model}:generateContent",
                json=body,
                headers={"x-goog-api-key": self.api_key,
                         "Content-Type": "application/json"})
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderError(
                f"AI provider returned HTTP {resp.status_code}.",
                retryable=True, kind="provider_http",
                status_code=resp.status_code)
        if resp.status_code >= 400:
            raise ProviderError(
                f"AI provider rejected the request (HTTP {resp.status_code}).",
                retryable=False, kind="provider_http",
                status_code=resp.status_code)
        try:
            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            usage = data.get("usageMetadata") or {}
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("AI provider returned an unreadable reply.",
                                retryable=True, kind="bad_reply")
        return text, usage
