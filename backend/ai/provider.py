"""AI provider adapter — env stub only. No cloud AI key is required.

If AI_PROVIDER / AI_MODEL / AI_API_KEY are all absent, the system runs in
rules/template mode: ai_status=unavailable and explanations are templates.
No key is ever read from code; only environment variables are consulted.
"""
from __future__ import annotations

import os


class ProviderAdapter:
    def __init__(self) -> None:
        self.provider = os.environ.get("AI_PROVIDER", "").strip() or None
        self.model = os.environ.get("AI_MODEL", "").strip() or None
        self.api_key = os.environ.get("AI_API_KEY", "").strip() or None

    @property
    def available(self) -> bool:
        return bool(self.provider and self.model and self.api_key)

    @property
    def ai_status(self) -> str:
        return "available" if self.available else "unavailable"

    def describe(self) -> dict:
        # Never expose the key value.
        return {"provider": self.provider, "model": self.model,
                "api_key_configured": bool(self.api_key), "ai_status": self.ai_status}

    def generate(self, prompt: str, timeout_s: float = 10.0) -> str:
        """Not implemented for Day 1: no provider is wired in. Callers must
        fall back to the template explanation on any failure/unavailability."""
        raise RuntimeError("No AI provider configured (AI_PROVIDER/AI_MODEL/AI_API_KEY absent or incomplete).")
