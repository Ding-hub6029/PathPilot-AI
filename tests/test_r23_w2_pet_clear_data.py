"""Round 23 W2 — clear-data does not clear the pet's memory.

Re-test task 17 (2026-11-27): set preferences (undergraduate,
Switzerland) -> click "清除我的数据" -> the wizard resets to step 1
("你在哪里读书？") ✓, BUT the pet still remembers "本科" and "瑞士"
and greets "我还记得你的偏好：，不用再问一遍啦～" with an EMPTY
preference slot.

Root cause (see /tmp/r23-w2-decisions.md): NOT a missed localStorage
key. clearData (store.tsx) already wipes pp-profile / pp-check-done /
pp-wizard-step / pp-prefchat and bumps dataClearNonce, and CompassPet
touches no preference storage at all — its only sessionStorage keys
are the open-state flags pp-pet-open / pp-pet-dismissed. The missed
store is CompassPet's own in-memory conversation: the component is
mounted once in the root layout and never remounts, its conversation
(messages / answers / step) lives in local useState, greet() only runs
when the panel opens with an empty transcript, and — unlike the wizard
(round 18) — CompassPet never subscribed to dataClearNonce. So after
a clear the stale prefNote + choice turns ("本科", "瑞士") survived,
and the prefNote turn renders at render time from the CURRENT profile,
so against the now-empty profile it produced pet.greetingKnown with
prefSummary() == '' — the dangling "偏好：，" in every locale.

Fix (CompassPet.tsx only): (A) subscribe to dataClearNonce with the
same ref-seeded pattern as the wizard — on a bump since mount, reset
messages/answers/step, switch devil mode off (it can only be on while
saved preferences exist), and re-greet at once if the panel is open;
(B) defence in depth in renderTurn's prefNote case: when nothing is
remembered (no preferences, or an empty summary) fall back to the
plain first greeting (pet.greeting) instead of rendering
pet.greetingKnown with an empty {prefs} — so the remembered-
preferences greeting can never render with a dangling slot, in any
locale, even if a stale turn ever renders again.

Behavioural evidence: /tmp/r23-w2-harness.mjs (node, real lib code +
real locale strings, exact tester sequence) — 28 checks FAILED before
the fix (post-clear reopen rendered exactly the reported
["我还记得你的偏好：，不用再问一遍啦～","本科","瑞士",…] in zh-CN
and the empty-slot greeting in all 6 locales) and ALL 37 checks pass
after it (post-clear reopen renders the plain greeting + Q1).

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_r23_w2_pet_clear_data.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PET = ROOT / "frontend" / "src" / "components" / "CompassPet.tsx"
STORE = ROOT / "frontend" / "src" / "lib" / "store.tsx"
WIZARD = ROOT / "frontend" / "src" / "app" / "wizard" / "page.tsx"
LOCALES = ["en", "zh-CN", "es", "fr", "pt-BR", "ar"]


def _messages(locale: str) -> dict:
    return json.loads((ROOT / "frontend" / "messages" / f"{locale}.json").read_text(encoding="utf-8"))


def _pet_src() -> str:
    return PET.read_text(encoding="utf-8")


def _pref_note_case(src: str) -> str:
    start = src.index("case 'prefNote':")
    end = src.index("case 'choice':", start)
    return src[start:end]


# ---------------------------------------------------------------------------
# Fix A — the pet subscribes to dataClearNonce and resets its conversation
# ---------------------------------------------------------------------------

def test_pet_subscribes_to_data_clear_nonce():
    src = _pet_src()
    assert "dataClearNonce" in src, "CompassPet must read the clear nonce from the store"
    assert "const { t, tf, locale, profile, dataClearNonce } = useApp();" in src


def test_clear_nonce_effect_resets_conversation_state():
    src = _pet_src()
    assert "const clearNonceRef = useRef(dataClearNonce);" in src
    assert "if (dataClearNonce === clearNonceRef.current) return;" in src
    assert "clearNonceRef.current = dataClearNonce;" in src
    assert "setMessages([]);" in src
    assert "setAnswers({});" in src
    assert "setStep(0);" in src
    # Devil mode can only be switched on while saved preferences exist;
    # a clear leaves nothing to challenge, so it goes off too.
    assert "setDevilMode(false);" in src


def test_clear_nonce_effect_regreets_when_panel_is_open():
    # The [open] effect only fires on open, so a reset while the panel
    # is open must re-greet immediately — otherwise the open panel
    # would sit empty until the next open.
    assert "if (openRef.current) greet();" in _pet_src()


def test_clear_nonce_effect_depends_on_the_nonce_only():
    # Same shape as the wizard's effect: it runs when the nonce bumps,
    # never on mount (the ref seeds at mount) and never on profile
    # edits (a profile change is not a clear).
    src = _pet_src()
    assert re.search(r"\}, \[dataClearNonce\]\);", src), src


def test_store_still_bumps_the_nonce_in_clear_data():
    src = STORE.read_text(encoding="utf-8")
    assert "setDataClearNonce((n) => n + 1);" in src
    # And the wizard keeps its own subscription — this worker did not
    # move the mechanism, it extended it to the pet.
    assert "dataClearNonce" in WIZARD.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fix B — a prefNote turn can never render greetingKnown with empty prefs
# ---------------------------------------------------------------------------

def test_pref_note_falls_back_to_plain_greeting_when_nothing_remembered():
    case = _pref_note_case(_pet_src())
    assert "const summary = prefSummary(profile, t, locale);" in case
    assert "if (!hasPreferences(profile) || !summary) return { lines: [t('pet.greeting')] };" in case


def test_pref_note_still_uses_full_greeting_when_prefs_exist():
    case = _pref_note_case(_pet_src())
    assert "tf('pet.greetingKnown', { prefs: summary })" in case
    # The /results short acknowledgement (no {prefs}) is unchanged.
    assert "t('pet.greetingKnownShort')" in case


def test_greeting_known_template_dangles_with_empty_prefs_in_all_locales():
    # Why the guard is load-bearing, not cosmetic: every locale's
    # greetingKnown renders a dangling colon + separator when {prefs}
    # is empty ("偏好：，" / "preferences: —" / "preferencias: ;").
    dangling = re.compile(r"[:：]\s*[，,;；—–-]")
    for locale in LOCALES:
        rendered = _messages(locale)["pet.greetingKnown"].replace("{prefs}", "")
        assert dangling.search(rendered), (locale, rendered)


def test_plain_greeting_exists_and_has_no_prefs_slot_in_all_locales():
    for locale in LOCALES:
        value = _messages(locale)["pet.greeting"]
        assert value.strip(), locale
        assert "{prefs}" not in value, locale
        # The fallback must not itself claim remembered preferences.
        assert "还记得" not in value and "still remember" not in value.lower(), (locale, value)


# ---------------------------------------------------------------------------
# No other pet memory: the pet stores no preferences of its own
# ---------------------------------------------------------------------------

def test_pet_reads_preferences_only_through_the_store_profile():
    src = _pet_src()
    assert "localStorage" not in src, (
        "the pet must not keep its own persisted copy of preferences")
    # Its only sessionStorage keys are panel open-state flags, never
    # preference data.
    for key in re.findall(r"sessionStorage\.\w+\('([^']+)'", src):
        assert key in ("pp-pet-open", "pp-pet-dismissed"), key
    assert "pp-profile" not in re.sub(r"//.*|/\*.*?\*/", "", src, flags=re.S), (
        "outside comments, the pet must never touch the profile key directly")
