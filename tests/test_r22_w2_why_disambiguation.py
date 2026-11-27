"""Round 22, W2 — WHY disambiguation still fails for a normal user
(re-test task 16, 2026-11-27 14:21-14:27 CST, model down the whole run).

Tester sequence (wizard step 8, three Swiss UG computing programmes in
view — ETH CS BSc, ETH CSE BSc, UZH Informatics BSc):
  1. "这个专业学费多少？" -> asked which one (acceptable-ish).
  2. "ETH Zurich 计算机科学理学学士学费多少？" (the CHINESE display
     name shown on the card) -> MIS-matched to MSc programmes
     (MSc in Computer Science, MSc in Data Science, MSc in Cyber
     Security...) and asked undergrad-or-masters, ignoring the
     undergraduate background.
  3. Only the exact English full name "ETH Zurich — Bachelor of
     Science in Computer Science 学费多少？" got the verified fee line
     (CHF 4,380).

Root cause (reproduced below): the name-token matcher in
``ai.assistant._match_programmes`` knows only English tokens and
institution aliases. "计算机科学理学学士" carries no level word it
recognises ("学士" was not in _UG_WORDS, only "本科"/"bachelor"), so
the level was None and the "eth" alias branch returned ALL TEN ETH
programmes — MSc first. The scoped programmes' localised display
titles (``name_localized``) were never consulted, and the matcher
never received the current track at all.

Fix: match against the scoped programmes' localised display titles
(degree name in any locale + institution token in either language),
add "学士" to the undergraduate level words, and thread the wizard
track (frontend sends ``profile.track``) through the chat endpoint
into the matcher, so an undergraduate profile never matches an MSc
programme. Step 1 stays a which-one line (genuinely ambiguous) —
the frontend makes that clarification one-tap with chips naming the
visible programmes. No-key path throughout (ai_status "unavailable").
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from ai.chat import answer
from ai.provider import ProviderAdapter
from app.main import app

client = TestClient(app)

ETH_CS = "eth-cs-bsc-2027"
ETH_CSE = "eth-cse-bsc-2027"
ZURICH_INF = "zurich-informatics-bsc-2027"
# The step-8 visible batch for the tester sequence.
SWISS_BATCH = [ETH_CS, ETH_CSE, ZURICH_INF]

Q_DEICTIC = "这个专业学费多少？"
Q_CHINESE_NAME = "ETH Zurich 计算机科学理学学士学费多少？"
Q_ENGLISH_NAME = "ETH Zurich — Bachelor of Science in Computer Science 学费多少？"
Q_MSC_NAME = "ETH Zurich MSc in Computer Science 学费多少？"


def _no_key_provider(monkeypatch) -> ProviderAdapter:
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return ProviderAdapter()


def _answer_no_key(monkeypatch, message: str, locale: str,
                   program_ids=None, track=None) -> dict:
    return answer(message, locale, provider=_no_key_provider(monkeypatch),
                  program_ids=program_ids, track=track)


# ---------------------------------------------------------------------------
# The exact three-step tester sequence
# ---------------------------------------------------------------------------

def test_tester_sequence_step1_deictic_still_which_one(monkeypatch):
    # Step 1: genuinely ambiguous between the three cards in view —
    # the which-one line naming them stands (the frontend makes it
    # one-tap with chips); never the blanket unknown.
    body = _answer_no_key(monkeypatch, Q_DEICTIC, "zh-CN",
                          program_ids=SWISS_BATCH)
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "查不到" not in joined
    assert "哪一门" in joined
    assert "ETH Zurich" in joined
    assert "University of Zurich" in joined


def test_tester_sequence_step2_chinese_display_name_resolves(monkeypatch):
    # Step 2 (THE bug): the Chinese display name on the card must
    # resolve to the one undergraduate programme — never the MSc list.
    # BEFORE the fix this returned the 10-programme ambiguous line
    # starting "MSc in Computer Science, MSc in Data Science...".
    body = _answer_no_key(monkeypatch, Q_CHINESE_NAME, "zh-CN",
                          program_ids=SWISS_BATCH)
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "CHF 4,380" in joined
    assert "Bachelor of Science in Computer Science" in joined
    assert "查不到" not in joined
    assert "两个相关专业" not in joined
    assert "MSc" not in joined
    assert body["evidence_url"] is not None
    assert body["evidence_url"].startswith("https://")


def test_tester_sequence_step3_english_full_name_resolves(monkeypatch):
    # Step 3: the exact English full name must also resolve to the
    # single programme in scope — before the fix it fell back to the
    # two-sibling ambiguous line ("请告诉我是本科还是硕士").
    body = _answer_no_key(monkeypatch, Q_ENGLISH_NAME, "zh-CN",
                          program_ids=SWISS_BATCH)
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "CHF 4,380" in joined
    assert "Bachelor of Science in Computer Science" in joined
    assert "查不到" not in joined
    assert "两个相关专业" not in joined
    assert "MSc" not in joined
    assert body["evidence_url"] is not None
    assert body["evidence_url"].startswith("https://")


def test_chinese_display_name_resolves_without_scope(monkeypatch):
    # The same Chinese name resolves even with no cards in scope: the
    # institution token ("ETH Zurich") narrows the degree name, which
    # on its own is shared by 20 programmes worldwide.
    body = _answer_no_key(monkeypatch, Q_CHINESE_NAME, "zh-CN")
    joined = "\n".join(body["lines"])
    assert "CHF 4,380" in joined
    assert "Bachelor of Science in Computer Science" in joined
    assert "MSc" not in joined


# ---------------------------------------------------------------------------
# Track: an undergraduate profile must NEVER match an MSc programme
# ---------------------------------------------------------------------------

def test_ug_track_never_matches_msc(monkeypatch):
    # Step 2 with the wizard track threaded through: still the UG
    # programme, no MSc anywhere in the answer.
    body = _answer_no_key(monkeypatch, Q_CHINESE_NAME, "zh-CN",
                          program_ids=SWISS_BATCH,
                          track="undergraduate")
    joined = "\n".join(body["lines"])
    assert "CHF 4,380" in joined
    assert "MSc" not in joined
    # An explicitly named MSc programme under a UG profile must NOT
    # be answered: no MSc name, no MSc fee line — the honest unknown
    # instead. (ETH MSc CS happens to cost the same CHF 4,380, so the
    # assertion is on the programme name, not the amount.)
    msc = _answer_no_key(monkeypatch, Q_MSC_NAME, "zh-CN",
                         track="undergraduate")
    msc_joined = "\n".join(msc["lines"])
    assert "MSc in Computer Science" not in msc_joined
    assert "查不到" in msc_joined


def test_tm_track_still_matches_msc(monkeypatch):
    # The track filter must not break the other direction: a taught
    # masters profile naming the MSc programme gets its verified fee.
    body = _answer_no_key(monkeypatch, Q_MSC_NAME, "zh-CN",
                          track="taught_masters")
    joined = "\n".join(body["lines"])
    assert "MSc in Computer Science" in joined
    assert "CHF 4,380" in joined
    assert "查不到" not in joined


def test_invalid_track_is_dropped_not_422(monkeypatch):
    # An unknown track value is dropped leniently (never a 422, never
    # a wrong match): the Chinese name still resolves.
    body = _answer_no_key(monkeypatch, Q_CHINESE_NAME, "zh-CN",
                          program_ids=SWISS_BATCH, track="phd")
    joined = "\n".join(body["lines"])
    assert "CHF 4,380" in joined
    assert "MSc" not in joined


# ---------------------------------------------------------------------------
# Endpoint: track threads through POST /assistant/chat
# ---------------------------------------------------------------------------

def test_endpoint_accepts_track_and_scope(monkeypatch):
    _no_key_provider(monkeypatch)
    r = client.post("/api/v1/assistant/chat", json={
        "message": Q_CHINESE_NAME, "locale": "zh-CN",
        "program_ids": SWISS_BATCH, "track": "undergraduate"})
    assert r.status_code == 200
    body = r.json()
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "CHF 4,380" in joined
    assert "MSc" not in joined
    # An invalid track is dropped, not a 422.
    r2 = client.post("/api/v1/assistant/chat", json={
        "message": Q_CHINESE_NAME, "locale": "zh-CN",
        "program_ids": SWISS_BATCH, "track": "phd"})
    assert r2.status_code == 200
    assert "CHF 4,380" in "\n".join(r2.json()["lines"])
