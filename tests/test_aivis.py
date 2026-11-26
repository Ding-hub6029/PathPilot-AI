"""AI-visibility layer (W5): page entries in AiEntry ask /assistant/chat
questions the old retrieval could not answer.

Pinned rules (see backend/ai/chat.py):
- a ranking-overview question ("Explain the QS 2027 ranking") names no
  institution, so the rank lookup has nothing to look up — the
  provider's top-3 institutions + a citable provider summary join the
  catalogue, and the template fallback states the top 3 deterministically
  instead of asking "tell me which institution";
- a programme-detail question carries the explicit "Programme id <id>"
  marker, so the exact programme's verified fee is stated even when
  the template's alias match is ambiguous (expansion siblings);
- a recommendation question states the cheapest verified pick and its
  fee, with a within/above-budget verdict ONLY when fee and budget
  share currency + period — a cross-currency budget never judges
  affordability (the CHF fee vs a GBP budget gets no verdict);
- unknown stays unknown when no provider / no programme id / no
  verified programme matches; nothing is ever invented. No-key path
  throughout (ai_status "unavailable", model None) — a model answer is
  never faked.
"""
from __future__ import annotations

import pytest

from ai.chat import (_detect_programme_id, _detect_ranking_provider,
                     _retrieve, answer, ranking_overview_line)
from ai.provider import ProviderAdapter

QS_QUESTION = ("Explain the QS 2027 ranking (top 100, world ranks): "
               "which universities are at the top, and what does the "
               "ranking measure?")
THE_QUESTION = ("Explain the THE 2027 ranking (top 100, world ranks): "
                "which universities are at the top, and what does the "
                "ranking measure?")
ARWU_QUESTION = ("Explain the ARWU 2026 ranking (top 100, world ranks): "
                 "which universities are at the top, and what does the "
                 "ranking measure?")
ETH_QUESTION = "What is the rank of ETH Zurich in QS, THE and ARWU?"
ETH_PROGRAMME_QUESTION = (
    "Programme id eth-cs-bsc-2027. I have Gaokao 680 out of 750 and "
    "IELTS 7.0 overall, and my budget is GBP 50,000 per year. What is "
    "the fee and IELTS requirement for this programme, and is it a "
    "good fit for me?")
UCL_PROGRAMME_QUESTION = (
    "Programme id ucl-cs-bsc-2026. I have Gaokao 680 out of 750 and "
    "IELTS 7.0 overall. What is the fee and IELTS requirement for "
    "this programme, and is it a good fit for me?")
CH_SUGGEST_QUESTION = (
    "Recommend an undergraduate programme in Switzerland "
    "(country code CH). Budget: under GBP 50,000 per year.")
GB_SUGGEST_QUESTION = (
    "Recommend an undergraduate programme in the United Kingdom "
    "(country code GB). Budget band: low. "
    "Budget: under GBP 30,000 per year.")


def _no_key_provider(monkeypatch) -> ProviderAdapter:
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return ProviderAdapter()


def _answer_no_key(monkeypatch, message: str, locale: str) -> dict:
    return answer(message, locale, provider=_no_key_provider(monkeypatch))


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def test_detect_ranking_provider():
    assert _detect_ranking_provider(QS_QUESTION) == "qs"
    assert _detect_ranking_provider(THE_QUESTION) == "the"
    assert _detect_ranking_provider(ARWU_QUESTION) == "arwu"
    assert _detect_ranking_provider("解释一下泰晤士 2027 排名，哪些大学排在最前面？") == "the"
    assert _detect_ranking_provider("解释一下软科 2026 排名") == "arwu"
    # No rank word: "THE <year>" alone is not a ranking question.
    assert _detect_ranking_provider("Tell me about the 2027 entry") is None
    # No provider token: a bare ranking question stays provider-less.
    assert _detect_ranking_provider(
        "Explain the ranking: which institutions are at the top?") is None
    # A bare "the" in ordinary text is not the provider.
    assert _detect_ranking_provider(
        "What is the rank of ETH Zurich?") is None


def test_detect_programme_id():
    assert _detect_programme_id(ETH_PROGRAMME_QUESTION) == "eth-cs-bsc-2027"
    assert _detect_programme_id(UCL_PROGRAMME_QUESTION) == "ucl-cs-bsc-2026"
    assert _detect_programme_id("What is the fee?") is None
    # An id that is not in the verified catalogue is dropped, never a guess.
    assert _detect_programme_id("Programme id not-a-real-programme.") is None


# ---------------------------------------------------------------------------
# Ranking overview (no key: template fallback states the top 3)
# ---------------------------------------------------------------------------

def test_retrieve_ranking_overview_qs():
    _, sources, _ = _retrieve(QS_QUESTION, "en")
    ids = [s.id for s in sources]
    assert "ranking-overview:qs" in ids
    assert "rank:qs:massachusetts-institute-of-technology" in ids
    assert "rank:qs:imperial" in ids
    assert "rank:qs:stanford-university" in ids
    line = ranking_overview_line(sources, "en")
    assert line is not None
    assert "Massachusetts Institute of Technology (#1)" in line
    assert "Imperial College London (#=2)" in line
    assert "Stanford University (#=2)" in line
    assert ranking_overview_line([], "en") is None


def test_chat_rankings_qs_overview_no_key(monkeypatch):
    body = _answer_no_key(monkeypatch, QS_QUESTION, "en")
    assert body["ai_status"] == "unavailable"
    assert body["model"] is None
    joined = "\n".join(body["lines"])
    assert "Massachusetts Institute of Technology (#1)" in joined
    assert "Imperial College London (#=2)" in joined
    assert "Stanford University (#=2)" in joined
    assert "Tell me which institution" not in joined
    assert body["evidence_url"] is not None
    assert body["evidence_url"].startswith("https://")
    assert any(s["id"] == "ranking-overview:qs" for s in body["sources"])


def test_chat_rankings_the_and_arwu_no_key(monkeypatch):
    the = _answer_no_key(monkeypatch, THE_QUESTION, "en")
    joined_the = "\n".join(the["lines"])
    assert "University of Oxford (#1)" in joined_the
    assert "Massachusetts Institute of Technology (#2)" in joined_the
    arwu = _answer_no_key(monkeypatch, ARWU_QUESTION, "en")
    joined_arwu = "\n".join(arwu["lines"])
    assert "Harvard University (#1)" in joined_arwu
    assert "Stanford University (#2)" in joined_arwu
    # Chinese THE question answers in Chinese, same top 3.
    zh = _answer_no_key(
        monkeypatch, "解释一下泰晤士 2027 排名，哪些大学排在最前面？", "zh-CN")
    joined_zh = "\n".join(zh["lines"])
    assert "University of Oxford (#1)" in joined_zh
    assert "前 3 名" in joined_zh
    # Provider name and edition are separated (no "Rankings2027").
    assert "Rankings 2027" in joined_zh


def test_chat_rankings_no_provider_stays_unknown(monkeypatch):
    # No provider token: no overview source joins, and no ranking is
    # ever invented. (The template's honest reply here is its
    # ambiguous-institutions line — the word "ranking" substring-
    # matches "King" in "King Fahd University…", a pre-existing
    # token-matching quirk in ai/assistant.py, outside this layer.)
    body = _answer_no_key(
        monkeypatch,
        "Explain the ranking: which universities are at the top?", "en")
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "Massachusetts Institute of Technology (#1)" not in joined
    assert "University of Oxford (#1)" not in joined
    assert not any(s["id"].startswith("ranking-overview:")
                   for s in body["sources"])


def test_chat_rankings_specific_institution_unchanged(monkeypatch):
    # A named institution keeps its rank lookup — no overview source.
    body = _answer_no_key(monkeypatch, ETH_QUESTION, "en")
    joined = "\n".join(body["lines"])
    assert "ETH Zurich" in joined
    assert "=8" in joined and "12" in joined and "19" in joined
    assert not any(s["id"].startswith("ranking-overview:")
                   for s in body["sources"])


# ---------------------------------------------------------------------------
# Programme-id intent (no key)
# ---------------------------------------------------------------------------

def test_retrieve_programme_id_eth():
    _, sources, pids = _retrieve(ETH_PROGRAMME_QUESTION, "en")
    assert "eth-cs-bsc-2027" in pids
    assert any(s.id.startswith("src:eth-cs-bsc-2027:")
               for s in sources)
    # The institution's ranks join too, for the model to cite.
    assert any(s.id == "rank:qs:eth-zurich" for s in sources)


def test_chat_programme_id_expansion_states_fee_no_key(monkeypatch):
    # ETH CS BSc is an expansion programme: the template's alias match
    # is ambiguous (every ETH undergraduate sibling matches), so
    # without the id marker this would answer "ambiguous". The marker
    # makes the template state this programme's verified fee instead.
    body = _answer_no_key(monkeypatch, ETH_PROGRAMME_QUESTION, "en")
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "ETH Zurich" in joined
    assert "CHF 4,380" in joined
    assert "ambiguous" not in joined.lower()
    assert body["evidence_url"] is not None
    assert body["evidence_url"].startswith("https://")


def test_chat_programme_id_v2_keeps_template_fee_answer(monkeypatch):
    # UCL CS BSc is a v2 programme: the template already answers its
    # fee from the alias match, and that answer stands.
    body = _answer_no_key(monkeypatch, UCL_PROGRAMME_QUESTION, "en")
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "University College London" in joined
    assert "GBP 48,600" in joined
    assert "can't find that in the verified data" not in joined


def test_chat_programme_id_unknown_stays_unknown(monkeypatch):
    body = _answer_no_key(
        monkeypatch, "Programme id not-a-real-programme. What is the fee?",
        "en")
    assert body["ai_status"] == "unavailable"
    assert "can't find that in the verified data" in "\n".join(body["lines"])


# ---------------------------------------------------------------------------
# Suggestion line (no key): verified pick + fee, verdict only when the
# fee and the budget are comparable (same currency + period)
# ---------------------------------------------------------------------------

def test_chat_suggest_switzerland_no_budget_verdict(monkeypatch):
    # Cheapest verified UG programme in Switzerland is Zurich
    # Informatics at CHF 2,440/year. The budget is GBP, so no
    # within/above verdict is ever stated — the fee alone.
    body = _answer_no_key(monkeypatch, CH_SUGGEST_QUESTION, "en")
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "University of Zurich" in joined
    assert "CHF 2,440" in joined
    assert "within" not in joined and "above" not in joined
    assert "can't find that in the verified data" not in joined
    assert any(s["id"].startswith("src:zurich-informatics-bsc-2027:")
               for s in body["sources"])


def test_chat_suggest_gb_within_budget(monkeypatch):
    # Same currency + period (GBP per year): the pick is within the
    # GBP 30,000 ceiling, and the line says so.
    body = _answer_no_key(monkeypatch, GB_SUGGEST_QUESTION, "en")
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "GBP 29,000" in joined
    assert "within" in joined
    assert "above" not in joined


def test_chat_suggest_switzerland_chinese(monkeypatch):
    body = _answer_no_key(
        monkeypatch,
        "推荐一个瑞士的本科项目 (country code CH)。Budget: under "
        "GBP 50,000 per year.", "zh-CN")
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "CHF 2,440" in joined
    assert "预算内" not in joined and "高于" not in joined
