"""Round 23, W5 — pet free-text QA relevance + count bug
(re-test task 17, 2026-11-27).

Tester sequence (pet, no scope, model down): "What is the tuition
fee for ETH Zurich Computer Science?" got:
  "I found two matching programmes: Peking University — Computer
  Science, Tsinghua University — Computer Science, University of
  Toronto — Computer Science. Tell me undergraduate or masters."
— wrong schools entirely (nothing to do with ETH), AND "two" but
three listed.

Root cause (reproduced below), both in ``ai.assistant``:
  1. ``_match_by_display_title`` matches a programme only when its
     FULL degree name is a substring of the message. The message
     carries the short phrase "computer science", so only the three
     programmes whose official name is exactly "Computer Science"
     (Peking, Tsinghua, Toronto) hit — ETH's "Bachelor of Science
     in Computer Science" never does. The institution narrowing
     then finds no ETH programme among those hits and falls back
     to ``narrowed or hits`` — the unfiltered, wrong-institution
     hits — so the "ETH" token in the question constrains nothing.
     The expansion alias branch has the same shape: with no level
     word it returns ALL TEN ETH programmes (see "ETH Zurich
     Medicine" below, which must be unknown, not a 10-programme
     list).
  2. The ``ambiguous_programme`` template hard-codes "two" in all
     six locales while ``ask()`` joins ALL matched programmes, so
     any 3+-way match states the wrong count.

Fix: an institution token present in the question filters
candidates to that institution in every matcher branch (a named
degree that institution does not offer matches nothing — the
honest unknown, never a substitute from another institution);
degree phrases from the message match inside a programme's degree
name, so "computer science" reaches ETH's BSc and MSc; and the
ambiguous line carries ``{count}`` derived from the same list it
names. No-key path throughout (ai_status "unavailable").
"""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from ai.assistant import _match_programmes, _norm, ask
from ai.chat import _retrieve, answer
from ai.provider import ProviderAdapter
from app.main import app

client = TestClient(app)

Q_ETH_CS_FEE = "What is the tuition fee for ETH Zurich Computer Science?"
Q_ETH_CS_FEE_UG = ("What is the tuition fee for ETH Zurich Computer "
                   "Science undergraduate?")
Q_ETH_MEDICINE = "What is the tuition fee for ETH Zurich Medicine?"
Q_NO_INST_CS = "What is the tuition fee for Computer Science?"
Q_UCL_CS_FEE = "What is the tuition fee for UCL Computer Science?"
Q_ETH_FEE_ZH = "苏黎世联邦理工计算机本科的学费是多少？"


def _no_key_provider(monkeypatch) -> ProviderAdapter:
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return ProviderAdapter()


def _answer_no_key(monkeypatch, message: str, locale: str) -> dict:
    return answer(message, locale, provider=_no_key_provider(monkeypatch))


def _listed_count(line: str) -> int:
    """Programmes named in an ambiguous line: the names between the
    colon and the ". Tell me" tail, joined with the locale's
    enumeration separator (", " in en — Round 24 W2: ask() used to
    join with "、" in every locale)."""
    names_part = line.split(":", 1)[1].split(". Tell me")[0]
    return len([n for n in names_part.split(", ") if n.strip()])


def _count_word(line: str) -> int | None:
    m = re.search(r"I found (\d+) matching programmes", line)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# The exact tester question
# ---------------------------------------------------------------------------

def test_eth_fee_question_lists_eth_only(monkeypatch):
    body = _answer_no_key(monkeypatch, Q_ETH_CS_FEE, "en")
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "ETH Zurich" in joined
    # Never schools the user did not ask about.
    assert "Peking" not in joined
    assert "Tsinghua" not in joined
    assert "Toronto" not in joined
    # ETH's two Computer Science programmes (BSc + MSc, no level
    # word given) — a correct ETH-only disambiguation.
    assert "Bachelor of Science in Computer Science" in joined
    assert "MSc in Computer Science" in joined


def test_eth_fee_question_count_word_matches_list(monkeypatch):
    body = _answer_no_key(monkeypatch, Q_ETH_CS_FEE, "en")
    line = body["lines"][0]
    # The count word must come from the same list that is rendered:
    # 2 programmes, so "2" — never the hard-coded "two" with a
    # different number of names.
    assert "I found two matching programmes" not in line
    assert _count_word(line) == 2
    assert _count_word(line) == _listed_count(line)


def test_eth_fee_question_matcher_is_eth_only():
    pids = _match_programmes(_norm(Q_ETH_CS_FEE))
    assert pids, "the ETH question must match something"
    assert all(pid.startswith("eth-") for pid in pids)
    assert "peking-cs-bsc-2027" not in pids
    assert "tsinghua-cs-bsc-2027" not in pids
    assert "toronto-cs-bsc-2027" not in pids


def test_eth_fee_question_retrieval_is_eth_only():
    _, sources, pids = _retrieve(Q_ETH_CS_FEE, "en")
    assert pids and all(pid.startswith("eth-") for pid in pids)
    assert all(s.id.startswith("src:eth-") or s.id.startswith("rank:")
               for s in sources if s.id.startswith("src:"))


def test_eth_fee_question_with_level_reaches_fee_line(monkeypatch):
    # With the level word the match is single, so the verified fee
    # line is the answer — the same CHF 4,380/year the scoped
    # step-8 chat states.
    body = _answer_no_key(monkeypatch, Q_ETH_CS_FEE_UG, "en")
    joined = "\n".join(body["lines"])
    assert "ETH Zurich" in joined
    assert "CHF 4,380" in joined
    assert "Peking" not in joined
    assert "Tsinghua" not in joined
    assert "Toronto" not in joined


def test_eth_fee_question_via_endpoint(monkeypatch):
    _no_key_provider(monkeypatch)
    r = client.post("/api/v1/assistant/chat",
                    json={"message": Q_ETH_CS_FEE, "locale": "en"})
    assert r.status_code == 200
    body = r.json()
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "ETH Zurich" in joined
    assert "Peking" not in joined
    assert "Tsinghua" not in joined
    assert "Toronto" not in joined
    assert _count_word(body["lines"][0]) == _listed_count(body["lines"][0])


# ---------------------------------------------------------------------------
# Count bug on its own: a 3-way match said "two"
# ---------------------------------------------------------------------------

def test_three_way_match_states_three(monkeypatch):
    # No institution named: the three exact-"Computer Science"
    # programmes are genuinely ambiguous — but the line must say
    # three, matching the three names it lists.
    body = _answer_no_key(monkeypatch, Q_NO_INST_CS, "en")
    line = body["lines"][0]
    assert _count_word(line) == 3
    assert _count_word(line) == _listed_count(line)
    assert "I found two matching programmes" not in line


def test_zh_fee_question_resolves_to_single_fee_line(monkeypatch):
    # The Chinese ETH fee question used to list the two undergraduate
    # siblings ("两个相关专业"); the degree phrase "计算机" now
    # matches only the Computer Science BSc — "计算科学" (CSE) does
    # not contain "计算机" — and the "本科" level word drops the MSc,
    # so the verified fee line is the answer.
    body = _answer_no_key(monkeypatch, Q_ETH_FEE_ZH, "zh-CN")
    line = "\n".join(body["lines"])
    assert "CHF 4,380" in line
    assert "Bachelor of Science in Computer Science" in line
    assert "两个相关专业" not in line
    assert "2 个相关专业" not in line


# ---------------------------------------------------------------------------
# Same bug class, another institution
# ---------------------------------------------------------------------------

def test_ucl_cs_question_lists_ucl_only(monkeypatch):
    body = _answer_no_key(monkeypatch, Q_UCL_CS_FEE, "en")
    joined = "\n".join(body["lines"])
    assert "University College London" in joined
    assert "Peking" not in joined
    assert "Tsinghua" not in joined
    assert "Toronto" not in joined
    assert _count_word(body["lines"][0]) == _listed_count(body["lines"][0])


# ---------------------------------------------------------------------------
# Institution named, programme not offered: unknown, not a substitute
# ---------------------------------------------------------------------------

def test_named_institution_without_matching_programme_stays_unknown(
        monkeypatch):
    # ETH offers no Medicine programme. Before the fix the alias
    # branch returned ALL TEN ETH programmes and the line said "two"
    # for ten names. The honest answer is unknown — never ETH's
    # Computer Science fee, never another institution's programme.
    body = _answer_no_key(monkeypatch, Q_ETH_MEDICINE, "en")
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "I can't find that in the verified data" in joined
    assert "Peking" not in joined
    assert "Tsinghua" not in joined
    assert "Toronto" not in joined
    assert "Computer Science" not in joined
    assert "CHF 4,380" not in joined
    assert _match_programmes(_norm(Q_ETH_MEDICINE)) == []
