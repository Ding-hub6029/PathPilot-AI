"""Round 15 integration — append-only chat drop + bounded chat turns.

Pins the coordinator integration of W3's PrefChat patch (W3 could not
edit PrefChat.tsx, which W1 owned) and the RecChat/AiEntry chat-budget
swap W3 flagged:

- a model drop never deletes the just-sent turn: preserveFailedAnswer
  marks it offline in place (markTurnOffline), never filters it out;
- the guided branch renders the earlier model turns above the guided
  continuation (renderPrefTurns), so a drop appends instead of
  rewriting the chat; the guided WHY block is skipped when the WHY is
  already anchored to a model turn (no double bubble);
- every chat turn (PrefChat, RecChat, AiEntry, pet) goes through
  fetchJsonChat (~20 s total, no retry on slow abort) — no 40 s
  attempt / 90 s budget remains on a chat call site. The /ai/status
  probes keep the patient fetch (they watch the Render wake).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src" / "components"


@pytest.fixture(scope="module")
def pref_src() -> str:
    return (SRC / "PrefChat.tsx").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rec_src() -> str:
    return (SRC / "RecChat.tsx").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def entry_src() -> str:
    return (SRC / "AiEntry.tsx").read_text(encoding="utf-8")


def test_drop_marks_turn_offline_instead_of_deleting(pref_src: str) -> None:
    assert "markTurnOffline(prev, turnId)" in pref_src
    assert "prev.filter((x) => x.id !== turnId)" not in pref_src


def test_guided_branch_renders_earlier_model_turns(pref_src: str) -> None:
    # renderPrefTurns is called once in the model branch and once in
    # the guided branch, above the offline banner — so a model drop
    # appends the guided continuation below the earlier turns instead
    # of hiding them.
    assert pref_src.count("{renderPrefTurns()}") >= 2
    first = pref_src.index("{renderPrefTurns()}")
    banner = pref_src.index("chatPrefOffline")
    assert "{renderPrefTurns()}" in pref_src[first + 1:banner]


def test_guided_why_block_skipped_when_anchored(pref_src: str) -> None:
    # The guided WHY bubble must not render when renderPrefTurns
    # already placed it after its anchored turn.
    assert "whyAnchoredTurnId(awaitingReason, turns.map((x) => x.id)) === null && (" in pref_src


def test_chat_turns_use_fetch_json_chat(pref_src: str, rec_src: str, entry_src: str) -> None:
    for src in (pref_src, rec_src, entry_src):
        assert "fetchJsonChat<" in src
    assert "fetchJsonChat<PrefChatReply>" in pref_src
    assert "fetchJsonChat<ChatReply>" in rec_src
    assert "fetchJsonChat<ChatReply>" in entry_src


def test_no_40s_attempt_left_on_chat_calls() -> None:
    for name in ("PrefChat.tsx", "RecChat.tsx", "AiEntry.tsx", "CompassPet.tsx"):
        src = (SRC / name).read_text(encoding="utf-8")
        assert "attemptTimeoutMs: 40000" not in src, name
