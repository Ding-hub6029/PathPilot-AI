"""Round 23 W4 — devil's-advocate toggle hijacks later free questions.

Re-test task 17 sequence (CompassPet): turn devil on, ask a devil
question, then ask an unrelated free-text question ("苏黎世的气候怎么
样？") — it got the devil climate reply (the engine-computed conflict
line ending "相差3项。") instead of an answer to the question.

Root causes pinned here:

1. Frontend (CompassPet.tsx): ``devilMode`` is a sticky boolean — once
   toggled on it stays on until the user manually toggles it off, and
   ``onSend`` sends ``mode='devil'`` for EVERY free-text turn while it
   is on. The fix is one-shot devil: the toggle applies to at most the
   next turn sent, then switches itself off.
2. Backend (ai/chat.py): the normal path could not answer the free
   question at all — "苏黎世的气候怎么样？" names a climate-table city
   but no climate class, so retrieval returned nothing and the template
   answered the blanket unknown. The fix retrieves the named city's
   verified climate source when the message asks about climate, so the
   normal template states its actual class (the existing
   ``evidence_cities_line`` replacement).
3. History leak (CompassPet.tsx ``buildHistory``): devil turns' lines
   were fed back as model context for later normal turns. Devil turns
   are now excluded from history.

The backend is stateless per request (``answer(mode=...)``) — mode
never persists there — so the sequence is tested as two calls: a devil
call, then a plain normal call with no ``mode`` key, exactly what the
one-shot frontend sends for the second question.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai.chat import answer
from ai.provider import ProviderAdapter
from app import router_chat

ROOT = Path(__file__).resolve().parent.parent
PET = ROOT / "frontend" / "src" / "components" / "CompassPet.tsx"

_test_app = FastAPI()
_test_app.include_router(router_chat.router)
client = TestClient(_test_app)

# Same audit profile as tests/test_devil_advocate.py: Switzerland, cool
# climate, UG, GBP 50,000 / year, Zurich. Its real conflict is climate:
# Zurich and Lausanne are four-season, not cool.
AUDIT_PROFILE = {
    "countries": ["CH"],
    "climate": "cool",
    "level": "undergraduate",
    "budget_amount": 50000,
    "budget_currency": "GBP",
    "budget_period": "per_year",
    "city": "Zurich",
}
DEVIL_QUESTION = "瑞士适合我吗？我喜欢凉爽的气候。"
FREE_QUESTION = "苏黎世的气候怎么样？"


def _no_key_provider(monkeypatch) -> ProviderAdapter:
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return ProviderAdapter()


def _post(body: dict) -> dict:
    r = client.post("/api/v1/assistant/chat", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Backend sequence: devil turn, then a plain free-text question
# ---------------------------------------------------------------------------

def test_devil_turn_still_challenges_with_difference_sentence(monkeypatch):
    """The actual devil turn is unchanged: mode devil, climate conflict,
    template ending with the engine-computed difference sentence."""
    r = answer(DEVIL_QUESTION, "zh-CN", provider=_no_key_provider(monkeypatch),
               mode="devil", profile=AUDIT_PROFILE)
    assert r["mode"] == "devil"
    assert r["conflicts"] == ["climate"]
    joined = "\n".join(r["lines"])
    assert "四季分明" in joined
    assert joined.rstrip().endswith("相差3项。")


def test_free_climate_question_after_devil_is_a_normal_answer(monkeypatch):
    """The follow-up free question, sent with NO mode (what the one-shot
    frontend sends), is a normal answer with Zurich climate facts —
    not a devil reply."""
    provider = _no_key_provider(monkeypatch)
    devil = answer(DEVIL_QUESTION, "zh-CN", provider=provider,
                   mode="devil", profile=AUDIT_PROFILE)
    assert devil["mode"] == "devil"
    r = answer(FREE_QUESTION, "zh-CN", provider=provider)
    assert "mode" not in r
    assert "conflicts" not in r
    joined = "\n".join(r["lines"])
    assert "换个角度" not in joined
    assert "相差" not in joined
    assert "苏黎世" in joined
    assert "四季分明" in joined
    assert r["evidence_url"] == "https://en.wikipedia.org/wiki/Zurich#Climate"


def test_free_climate_question_after_devil_via_endpoint(monkeypatch):
    """Same sequence through POST /api/v1/assistant/chat: the second
    call carries no mode key, and toggling devil off (i.e. sending a
    normal call) fully restores normal replies."""
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    first = _post({"message": DEVIL_QUESTION, "locale": "zh-CN",
                   "mode": "devil", "profile": AUDIT_PROFILE})
    assert first["mode"] == "devil"
    second = _post({"message": FREE_QUESTION, "locale": "zh-CN"})
    assert "mode" not in second
    assert "conflicts" not in second
    joined = "\n".join(second["lines"])
    assert "换个角度" not in joined and "相差" not in joined
    assert "苏黎世" in joined and "四季分明" in joined


def test_named_city_climate_question_in_english(monkeypatch):
    r = answer("What's the climate like in Zurich?", "en",
               provider=_no_key_provider(monkeypatch))
    assert "mode" not in r
    joined = "\n".join(r["lines"])
    assert "Zurich" in joined and "four-season" in joined


def test_non_climate_question_naming_a_city_gets_no_climate_line(monkeypatch):
    """The named-city retrieval fires only for a climate question: a
    general question naming Zurich must not be answered with the
    climate-cities line."""
    r = answer("苏黎世有什么好玩的？", "zh-CN",
               provider=_no_key_provider(monkeypatch))
    assert "mode" not in r
    joined = "\n".join(r["lines"])
    assert "四季分明" not in joined


def test_devil_off_restores_normal_for_a_second_free_question(monkeypatch):
    """Toggling devil off (a plain normal call) after a devil turn
    restores normal replies for every later question, not just the
    first one after."""
    provider = _no_key_provider(monkeypatch)
    answer(DEVIL_QUESTION, "zh-CN", provider=provider,
           mode="devil", profile=AUDIT_PROFILE)
    for _ in range(2):
        r = answer(FREE_QUESTION, "zh-CN", provider=provider)
        assert "mode" not in r and "相差" not in "\n".join(r["lines"])


# ---------------------------------------------------------------------------
# Frontend source pins (no JS test runner in this repo — same approach as
# tests/test_r13_frontend_failfast.py and test_r14_devil_and_failfast.py)
# ---------------------------------------------------------------------------

def _onsend_body() -> str:
    src = PET.read_text(encoding="utf-8")
    start = src.index("const onSend = async () => {")
    end = src.index("const chips:", start)
    return src[start:end]


def _sendask_body() -> str:
    """The shared send path (Round 24, W1: onSend's fetch body moved
    into sendAskTurn so the disambiguation follow-up sends through
    the same turn logic)."""
    src = PET.read_text(encoding="utf-8")
    start = src.index("const sendAskTurn = async (args: SendAskArgs) => {")
    end = src.index("const onSend = async () => {", start)
    return src[start:end]


def test_devil_is_one_shot_in_onsend():
    """onSend captures the devil flag for THIS turn only and switches
    the toggle off as the turn is sent, so the next free-text question
    is normal even if the user never taps the toggle again."""
    body = _onsend_body()
    assert "const isDevilTurn = devilMode" in body
    assert "setDevilMode(false)" in body
    # The reset happens when the turn is sent (before the normal-path
    # send call), not after the reply lands. The first sendAskTurn
    # call in onSend is the disambiguation resolve (devilTurn: false
    # — it never touches the toggle), so the ordering is checked
    # against the LAST call, the normal path.
    assert body.index("setDevilMode(false)") < body.rindex("sendAskTurn({")
    # The capture travels into the shared send path as its devilTurn
    # argument — never the sticky state.
    assert "devilTurn: isDevilTurn" in body
    send_body = _sendask_body()
    # Every devil marker inside the send path uses the per-turn
    # argument, never the sticky state — including the offline
    # fallback path.
    assert "devil: devilMode" not in send_body
    assert "devil: devilTurn" in send_body
    assert "devilProf = devilMode" not in send_body
    assert "devilProf = devilTurn" in send_body
    assert "mode: 'devil'" in send_body


def test_devil_turns_excluded_from_history():
    """buildHistory never feeds a devil turn's lines back as model
    context for a later (normal) question."""
    src = PET.read_text(encoding="utf-8")
    start = src.index("const buildHistory = ")
    end = src.index("};", src.index("return out.slice(-6);", start)) + 2
    body = src[start:end]
    assert "m.kind !== 'ask' || m.devil || !m.reply" in body
