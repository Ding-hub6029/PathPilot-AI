"""Round 23, W1 — chip tap leaks the internal programme id into the
user bubble (re-test task 17, 2026-11-27).

Tester sequence (wizard step 8): ask "这个专业学费多少？" -> the
which-one line + 3 one-tap programme chips -> tap the
"ETH Zurich — 计算机科学理学学士" chip -> the user bubble rendered
"Programme id eth-cs-bsc-2027. 这个专业学费多少？".

Root cause: the chip's onClick called
``askModel(`Programme id ${p.id}. ${turn.question}`)`` and askModel
stored that string verbatim as ``turn.question``, which the user
bubble rendered raw (``<p>{turn.question}</p>``).

Fix: the turn splits display from sent. ``turn.question`` is the
user-visible bubble text (programme display name + the question);
``turn.sent`` is the exact message POSTed to the backend and keeps
the "Programme id <id>." marker the backend keys its programme-id
intent on (backend/app/router_chat.py program_ids). The bubble
renders through ``stripProgrammeMarker`` as a render-side guard, and
a retry re-sends the stored ``sent``, so the scoping survives it.
Round 27 W1: the locale re-fetch that also re-sent ``sent`` is
deleted — a stored reply is never re-fetched. The sent marker
string itself is unchanged, so the backend behaviour is identical
— the existing no-key scope tests
(test_r21_w3_why_scope, test_r22_w2_why_disambiguation) still cover
it. A node harness (/tmp/r23-w1-harness.mjs) exercises the real
helpers from frontend/src/lib/chat.ts plus this wiring.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REC_CHAT = ROOT / "frontend" / "src" / "components" / "RecChat.tsx"
CHAT_LIB = ROOT / "frontend" / "src" / "lib" / "chat.ts"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_chip_tap_never_passes_marker_as_display_text():
    # The old one-liner is gone: no call site passes the raw marker
    # string as askModel's display text any more.
    src = _src(REC_CHAT)
    assert "askModel(`Programme id ${p.id}. ${turn.question}`)" not in src


def test_chip_tap_sends_display_and_scoped_message_separately():
    src = _src(REC_CHAT)
    assert "scopedProgrammeDisplay(displayProgramTitle(p, locale), turn.question, locale)" in src
    assert "scopedProgrammeMessage(p.id, turn.question)" in src


def test_turn_stores_sent_separately_from_question():
    src = _src(REC_CHAT)
    assert re.search(r"id: number; question: string; sent: string;", src)


def test_backend_receives_sent_message_not_display_label():
    src = _src(REC_CHAT)
    # askModel sends the stored sent message, never the display label.
    assert "body: JSON.stringify({ message: sent, locale: requestLocale" in src
    # History and the retry re-send the stored sent message. (Round 27
    # W1: the locale re-fetch that also re-sent it is deleted.)
    assert "content: turn.sent ?? turn.question" in src


def test_user_bubble_renders_through_strip_guard():
    src = _src(REC_CHAT)
    assert "<p>{stripProgrammeMarker(turn.question)}</p>" in src
    assert "<p>{turn.question}</p>" not in src


def test_retry_button_shows_for_offline_chip_turn():
    # A chip-scoped turn never sets lastQuestion (free text only), so
    # the retry button must also appear when an offline turn exists —
    # retryAi re-sends that turn's stored `sent`, marker included.
    src = _src(REC_CHAT)
    assert "aiTurns.some((x) => x.offline)" in src


def test_scoped_helpers_exist_in_chat_lib():
    lib = _src(CHAT_LIB)
    assert "export function scopedProgrammeMessage" in lib
    assert "export function scopedProgrammeDisplay" in lib
    assert "export function stripProgrammeMarker" in lib
    # The sent marker format is byte-identical to the old one, so the
    # backend's programme-id intent keeps matching.
    assert "return `Programme id ${programId}. ${question}`;" in lib


def test_no_other_chat_surface_renders_a_programme_id_marker():
    # Audit (round 23): the only "Programme id" constructions in the
    # frontend are the shared helper (lib/chat.ts, sent only) and the
    # programme-detail page's AiEntry question — AiEntry never renders
    # its question, only POSTs it. PrefChat chips send display labels
    # only; the pet renders verbatim free text / choice labels and
    # never its constructed messages. So no .tsx file may build the
    # marker inline any more.
    tsx_files = list((ROOT / "frontend" / "src").rglob("*.tsx"))
    assert tsx_files, "no .tsx files found — wrong root?"
    detail_rel = Path("app") / "programs" / "[id]" / "page.tsx"
    for path in tsx_files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT / "frontend" / "src")
        # The programme-detail page is the one allowed inline build:
        # its marker goes only to AiEntry (checked below), which never
        # renders its question.
        if rel == detail_rel:
            continue
        assert "Programme id ${" not in text, f"{path} still builds a marker inline"
    # The detail page's marker reaches only AiEntry, which never
    # renders its `question` prop (it only POSTs it).
    detail = (ROOT / "frontend" / "src" / "app" / "programs" / "[id]" / "page.tsx").read_text(encoding="utf-8")
    assert "Programme id ${program.id}." in detail
    assert "<AiEntry label={t('aivis.programme')} question={programQuestion}" in detail
    ai_entry = (ROOT / "frontend" / "src" / "components" / "AiEntry.tsx").read_text(encoding="utf-8")
    # AiEntry renders reply lines and labels only — never the question.
    assert re.search(r"\{question\}", ai_entry) is None
