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
import time
from dataclasses import dataclass, field

import httpx

SUPPORTED_PROVIDERS = ("openai", "deepseek", "gemini")

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}

DEFAULT_TIMEOUT_MS = 60_000
DEFAULT_MAX_TOKENS = 1200


class ProviderError(Exception):
    """A model call failed. ``message`` is sanitised: it never contains
    the API key, the request body, or a raw provider error payload."""

    def __init__(self, message: str, *, retryable: bool = False,
                 kind: str = "provider_error") -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.kind = kind


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

    # -- public API ---------------------------------------------------------
    def chat(self, messages: list[dict], *, system: str | None = None,
             timeout_s: float | None = None, max_tokens: int | None = None,
             temperature: float = 0.2) -> ChatResult:
        """One chat-completions call. ``messages`` is a list of
        {"role": "user"|"assistant", "content": str}. Raises ProviderError
        on any failure; never returns invented text."""
        if not self.available:
            raise ProviderError(
                "No AI provider configured (AI_PROVIDER/AI_MODEL/AI_API_KEY "
                "absent or incomplete).", retryable=False, kind="not_configured")
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
        except ProviderError:
            raise
        except httpx.TimeoutException:
            raise ProviderError("AI provider call timed out.",
                                retryable=True, kind="timeout")
        except httpx.HTTPError:
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
            raise ProviderError("AI provider returned an empty reply.",
                                retryable=True, kind="empty_reply")
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
                    temperature: float = 0.2) -> ChatResult:
        """Async twin of :meth:`chat`: the same request, validation and
        error mapping, but over ``httpx.AsyncClient`` — awaiting it
        never blocks the server's event loop, so a slow model call
        cannot wedge /health or any other endpoint. Same
        ``ProviderError`` contract as :meth:`chat`; never returns
        invented text."""
        if not self.available:
            raise ProviderError(
                "No AI provider configured (AI_PROVIDER/AI_MODEL/AI_API_KEY "
                "absent or incomplete).", retryable=False, kind="not_configured")
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
        except ProviderError:
            raise
        except httpx.TimeoutException:
            raise ProviderError("AI provider call timed out.",
                                retryable=True, kind="timeout")
        except httpx.HTTPError:
            raise ProviderError("Could not reach the AI provider.",
                                retryable=True, kind="transport_error")
        except ValueError:
            # Same malformed-URL mapping as chat(): a bad provider
            # URL is a provider error, not a 500.
            raise ProviderError("AI provider URL is not usable.",
                                retryable=False, kind="bad_url")
        latency_ms = int((time.monotonic() - started) * 1000)
        if not text or not text.strip():
            raise ProviderError("AI provider returned an empty reply.",
                                retryable=True, kind="empty_reply")
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
                retryable=True, kind="provider_http")
        if resp.status_code >= 400:
            raise ProviderError(
                f"AI provider rejected the request (HTTP {resp.status_code}).",
                retryable=False, kind="provider_http")
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
                retryable=True, kind="provider_http")
        if resp.status_code >= 400:
            raise ProviderError(
                f"AI provider rejected the request (HTTP {resp.status_code}).",
                retryable=False, kind="provider_http")
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
                retryable=True, kind="provider_http")
        if resp.status_code >= 400:
            raise ProviderError(
                f"AI provider rejected the request (HTTP {resp.status_code}).",
                retryable=False, kind="provider_http")
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
                retryable=True, kind="provider_http")
        if resp.status_code >= 400:
            raise ProviderError(
                f"AI provider rejected the request (HTTP {resp.status_code}).",
                retryable=False, kind="provider_http")
        try:
            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            usage = data.get("usageMetadata") or {}
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("AI provider returned an unreadable reply.",
                                retryable=True, kind="bad_reply")
        return text, usage
