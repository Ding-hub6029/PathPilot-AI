"""小罗盘 locale fix (2026-11-25) — pins the mixed-language bug fix.

The bug: CompassPet.tsx stored already-rendered strings in its message
bubbles (t('pet.greeting') evaluated at push time), so after a locale
switch the old bubbles stayed in the old language while the header,
chips and placeholder switched.

The fix pins here, by parsing frontend/src/components/CompassPet.tsx:
- message state holds structured data only (prompt keys, chosen values,
  the user's verbatim text, whole backend payloads + replyLocale) —
  no t()/tf() result and no `lines:` literal ever flows into a
  push()/setMessages() call;
- every assistant call (/assistant/chat) sends the current locale, and
  a reply counts as an AI answer only when ai_status is "available" —
  anything else falls back to the labelled offline catalogue, never a
  template line shown as chat;
- Round 27 W1 SUPERSEDES the old locale rule (re-test task 21): a
  stored backend reply is an immutable record — it renders exactly as
  answered, whatever locale that was, and NO [locale, messages] effect
  re-fetches it. A language switch re-renders chrome/labels only and
  never re-derives, re-fetches or rewrites reply content (the old
  re-fetch rewrote fee answers into rank lines and flipped the footer
  to "AI answers" while the model was down);
- the offline suggestion's programme name is rendered through
  displayProgramTitle() at render time, never stored as a string.

Global scope (2026-11-25): the product covers universities worldwide,
so the country question (Q2) is data-driven — its options come from the
countries in the verified data the frontend already ships (programmes'
countries first, then the rankings institutions' countries), rendered
with the existing `country.*` locale keys. A country with no verified
programme yet gets an honest structured `noProgrammes` turn (new keys
pet.suggestNone / pet.noProgrammesRank / pet.suggestUnknown2, rendered
at render time — exact 6-locale values are in the final report, the
parent adds them to messages/*.json); the backend /suggest path
degrades the same way instead of 422ing (see test_assistant.py).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PET = ROOT / "frontend" / "src" / "components" / "CompassPet.tsx"


@pytest.fixture(scope="module")
def pet_src() -> str:
    return PET.read_text(encoding="utf-8")


def _call_texts(src: str, name: str) -> list[str]:
    """Text of every `name(...)` call site, bracket-matched."""
    out = []
    # Only the standalone state helper `push(` — not `lines.push(` or any
    # other method call ending in push.
    for m in re.finditer(r"(?<![\w.])" + re.escape(name) + r"\(", src):
        i = m.end() - 1  # at the opening paren
        depth = 0
        j = i
        while j < len(src):
            ch = src[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append(src[m.start():j + 1])
    return out


# ---------------------------------------------------------------------------
# 1. No rendered string is ever stored in message state
# ---------------------------------------------------------------------------
def test_no_rendered_string_stored_in_message_state(pet_src):
    writes = _call_texts(pet_src, "push") + _call_texts(pet_src, "setMessages")
    assert writes, "no push()/setMessages() call sites found — test is stale"
    for call in writes:
        assert "t(" not in call, call
        assert "tf(" not in call, call
        # No bubble text is stored: turns carry kind/ids/values and whole
        # backend payloads (reply:), never a `lines:` literal.
        assert not re.search(r"\blines\s*:", call), call
    # Every push() stores a structured turn (kind-tagged), not a bubble.
    for call in _call_texts(pet_src, "push"):
        assert re.search(r"\{\s*kind\s*:", call), call


def test_render_happens_at_render_time_in_current_locale(pet_src):
    # A renderTurn() maps stored turns to visible strings with the
    # current t()/tf(), and the JSX renders through it — never raw state.
    assert "const renderTurn" in pet_src
    assert "renderTurn(m)" in pet_src
    render_fn = pet_src.split("const renderTurn")[1].split("const askSuggest")[0]
    assert "t(" in render_fn and "tf(" in render_fn
    # Prompt turns render through t() from their stored key.
    assert "t(turn.key)" in render_fn
    # Quick-reply choices render through t() from stored ids/values.
    assert "choiceLabel(turn)" in render_fn


# ---------------------------------------------------------------------------
# 2. Every assistant call sends the current locale
# ---------------------------------------------------------------------------
def test_assistant_calls_include_locale(pet_src):
    # Round 7, Fix A: user-initiated calls go through fetchJsonPatient
    # (cold-start retries in the shared path); the locale re-fetches
    # still use fetchJson. Round 15, F2: user-initiated calls go
    # through fetchJsonChat instead (one turn bounded to ~20 s, no
    # retry on a slow abort — same /assistant/chat endpoint, same
    # locale payload). Round 27 W1 SUPERSEDES the old count: the
    # locale re-fetches that used fetchJson are deleted — a stored
    # reply is never re-fetched — so the only /assistant/chat calls
    # are the two user-initiated ones (askSuggest + onSend). Both
    # helpers must send the current locale, and only /assistant/chat
    # may be called.
    calls = [c for c in _call_texts(pet_src, "fetchJson<ChatReply>")]
    calls += [c for c in _call_texts(pet_src, "fetchJsonPatient<ChatReply>")]
    calls += [c for c in _call_texts(pet_src, "fetchJsonChat<ChatReply>")]
    assert len(calls) == 2, calls  # askSuggest + onSend, no re-fetches
    for call in calls:
        assert "/api/assistant/" in call, call
        assert "locale" in call, call
    endpoints = sorted({re.search(r"/api/assistant/\w+", c).group(0) for c in calls})
    assert endpoints == ["/api/assistant/chat"]


def test_template_endpoints_are_not_called(pet_src):
    # Round 6, Job A: the pet talks to the real model only. The old
    # template endpoints (/assistant/ask, /assistant/suggest) must not
    # appear anywhere in the component — a template reply must never
    # be shown as a chat answer.
    assert "/api/assistant/ask" not in pet_src
    assert "/api/assistant/suggest" not in pet_src


# ---------------------------------------------------------------------------
# 3. Stored backend turns are shown as answered, never re-fetched
# ---------------------------------------------------------------------------
def test_stored_backend_turns_shown_as_answered_after_locale_change(pet_src):
    # Round 27 W1 SUPERSEDES test_stale_backend_turns_refetched_on_locale_change
    # (re-test task 21: the re-fetch rewrote fee answers into rank
    # lines and flipped the footer to "AI answers" while the model
    # was down). Turns still remember the locale their reply was
    # answered in — as a record, not a render gate.
    assert "replyLocale" in pet_src
    # A backend turn's lines render whatever locale they were answered
    # in: no replyLocale === locale gate anywhere in the component.
    assert "replyLocale === locale" not in pet_src
    render_fn = pet_src.split("const renderTurn")[1].split("const askSuggest")[0]
    assert "if (turn.reply) {" in render_fn
    # "Thinking…" remains only as the pending-turn fallback (one per
    # case); a stored reply never renders it.
    assert render_fn.count("t('pet.thinking')") == 2
    # No [locale, messages] effect re-fetches stale turns any more —
    # no useEffect dep array mentions locale at all.
    assert not re.search(r"\}, \[[^\]]*locale[^\]]*\]\);", pet_src)
    # No re-fetch fetch remains: the only /assistant/chat calls are
    # the user-initiated ones (see test 2 above).
    assert "fetchJson<" not in pet_src


# ---------------------------------------------------------------------------
# 4. Offline suggestion name follows the locale at render time
# ---------------------------------------------------------------------------
def test_offline_suggestion_name_uses_display_program_title(pet_src):
    assert "displayProgramTitle" in pet_src
    assert "from '../lib/programs'" in pet_src
    assert "displayProgramTitle(program, locale)" in pet_src
    # The old pattern — building "Institution — Official Name" as a
    # stored string — is gone.
    assert "institution} — ${" not in pet_src
    assert "picked.p.institution" not in pet_src


# ---------------------------------------------------------------------------
# 5. Country question (Q2) is data-driven, not hardcoded UK/Singapore
# ---------------------------------------------------------------------------
def test_country_options_are_data_driven(pet_src):
    # Options come from the verified data the frontend already ships:
    # the programmes' countries and the rankings institutions' countries.
    assert "PROGRAMS.map((p) => p.country)" in pet_src
    assert "RANKING_INSTITUTIONS.map((i) => i.country)" in pet_src
    # The old hardcoded UK/Singapore pair is gone from chips and labels.
    assert "pet.q2gb" not in pet_src
    assert "pet.q2sg" not in pet_src
    # Labels use the existing country.* locale keys, at render time.
    assert "t(`country.${code}`)" in pet_src
    assert "t(`country.${turn.value}`)" in pet_src


def test_no_programme_country_degrades_gracefully(pet_src):
    # A country with no verified programmes gets an honest structured
    # turn — never a /suggest call with a guessed route, never a stored
    # rendered string (the push() scan in test 1 covers the latter).
    assert "kind: 'noProgrammes'" in pet_src
    assert "hasVerifiedProgrammes(country)" in pet_src
    # The Q2 branch answers without asking a budget question whose
    # answer would be discarded; askSuggest guards the same way.
    ask_suggest = pet_src.split("const askSuggest")[1].split("const onChip")[0]
    assert "hasVerifiedProgrammes(country)" in ask_suggest
    # The turn renders at render time through t()/tf() with new keys
    # (exact 6-locale values are in the final report; the parent adds
    # them to messages/*.json).
    for key in ("pet.suggestNone", "pet.noProgrammesRank", "pet.suggestUnknown2"):
        assert key in pet_src, key
    # No new country or programme data is invented in the component.
    assert "'US'" not in pet_src and '"US"' not in pet_src
