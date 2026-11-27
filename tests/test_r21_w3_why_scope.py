"""Round 21, W3 — WHY helpfulness inconsistency: the step-8 chat
vs the programme detail page (re-test task 15).

Root cause (reproduced below): the SAME question — "What is the fee
and IELTS requirement for this programme, and is it a good fit for
me?" — got the verified fee line on the programme detail page but the
blanket "这个我从已核实的数据里查不到，不知道。" in the step-8
(RecChat) chat. The detail page scopes its question with the explicit
"Programme id <id>" marker, so retrieval brings that programme's
verified sources and the template states its fee. RecChat sent only
{message, locale, history}: no programme was ever in scope, so a
deictic "this programme" / "这个专业" question matched nothing — the
template's alias match needs a name in the text — and the verified fee
facts were never queried.

Fix: callers pass the visible cards' ids as ``program_ids`` (backend
``chat.answer`` / ``POST /assistant/chat``; RecChat sends its shown
batch). The scope only fills the gap the template leaves — it never
overrides a programme the template already answered, and never
answers a question that is not about a programme fact. Several
in-scope programmes get a which-one line naming them; a why-not
question about an in-scope programme gets a specific refusal naming
the programme and the missing piece (the rule-by-rule evaluation is
not in the chat). No-key path throughout (ai_status "unavailable").
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from ai.chat import _clean_program_ids, _retrieve, answer
from ai.provider import ProviderAdapter
from app.main import app

client = TestClient(app)

# The audit profile's question, as the detail page's AiEntry sends it
# (with the marker) and as the tester typed it in the step-8 chat
# (without one — RecChat never added programme context).
DETAIL_QUESTION = (
    "Programme id eth-cs-bsc-2027. I have Gaokao 680 out of 750 and "
    "IELTS 7.0 overall, and my budget is GBP 50,000 per year. What is "
    "the fee and IELTS requirement for this programme, and is it a "
    "good fit for me?")
STEP8_QUESTION = (
    "What is the fee and IELTS requirement for this programme, and is "
    "it a good fit for me?")
STEP8_QUESTION_ZH = "这个专业的学费和雅思要求是多少，适合我吗？"
WHY_NOT_MET_ZH = "为什么这个专业不达标？"
ETH_FEE_ZH = "苏黎世联邦理工计算机本科的学费是多少？"

ETH_CS = "eth-cs-bsc-2027"
ETH_CSE = "eth-cse-bsc-2027"
EPFL_CS = "epfl-cs-bsc-2027"
ZURICH_INF = "zurich-informatics-bsc-2027"
# The step-8 visible batch for the audit profile (preference-first
# Swiss UG computing, first three cards).
SWISS_BATCH = [ETH_CS, EPFL_CS, ZURICH_INF]


def _no_key_provider(monkeypatch) -> ProviderAdapter:
    for var in ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return ProviderAdapter()


def _answer_no_key(monkeypatch, message: str, locale: str,
                   program_ids=None) -> dict:
    return answer(message, locale, provider=_no_key_provider(monkeypatch),
                  program_ids=program_ids)


# ---------------------------------------------------------------------------
# Before/after: the same question, with and without scope
# ---------------------------------------------------------------------------

def test_deictic_fee_question_without_scope_stays_unknown(monkeypatch):
    # BEFORE (pinned): no programme in scope, no name in the text —
    # the verified fee facts are never queried, so the blanket
    # unknown is the honest answer. The fix does not change this:
    # without scope there is still nothing to answer from.
    body = _answer_no_key(monkeypatch, STEP8_QUESTION, "zh-CN")
    assert body["ai_status"] == "unavailable"
    assert body["lines"][0] == "这个我从已核实的数据里查不到，不知道。"
    body_zh = _answer_no_key(monkeypatch, STEP8_QUESTION_ZH, "zh-CN")
    assert body_zh["lines"][0] == "这个我从已核实的数据里查不到，不知道。"


def test_deictic_fee_question_single_scope_states_verified_fee(monkeypatch):
    # AFTER: the same question with the one programme in view answers
    # with the same verified fee line the detail page states.
    body = _answer_no_key(monkeypatch, STEP8_QUESTION, "zh-CN",
                          program_ids=[ETH_CS])
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "ETH Zurich" in joined
    assert "CHF 4,380" in joined
    assert "查不到" not in joined
    assert body["evidence_url"] is not None
    assert body["evidence_url"].startswith("https://")
    # The Chinese deictic form gets the same verified answer.
    body_zh = _answer_no_key(monkeypatch, STEP8_QUESTION_ZH, "zh-CN",
                             program_ids=[ETH_CS])
    joined_zh = "\n".join(body_zh["lines"])
    assert "CHF 4,380" in joined_zh
    assert "查不到" not in joined_zh


def test_detail_page_marker_answer_unchanged(monkeypatch):
    # The detail page's own path still works exactly as before.
    body = _answer_no_key(monkeypatch, DETAIL_QUESTION, "en")
    joined = "\n".join(body["lines"])
    assert "ETH Zurich" in joined
    assert "CHF 4,380" in joined


def test_scope_sources_join_catalogue():
    _, sources, _ = _retrieve(STEP8_QUESTION, "zh-CN",
                              program_ids=[ETH_CS])
    assert any(s.id.startswith(f"src:{ETH_CS}:") for s in sources)
    assert any(s.id == "rank:qs:eth-zurich" for s in sources)
    # ... while the scope stays out of the matched pids, so the
    # suggestion pick and the ranking overview keep gating on a real
    # match (a scope must never stop a suggestion question getting
    # its pick).
    _, _, pids = _retrieve(
        "Recommend an undergraduate programme in Switzerland "
        "(country code CH). Budget: under GBP 50,000 per year.", "en",
        program_ids=[ETH_CS])
    assert ETH_CS not in pids


# ---------------------------------------------------------------------------
# Several programmes in scope: specific refusal, not blanket unknown
# ---------------------------------------------------------------------------

def test_deictic_fee_question_batch_scope_names_programmes(monkeypatch):
    # The step-8 batch shows three cards: a bare "this programme"
    # fee question is genuinely ambiguous between them, so the
    # refusal names all three and asks which one — never the blanket
    # "查不到".
    body = _answer_no_key(monkeypatch, STEP8_QUESTION_ZH, "zh-CN",
                          program_ids=SWISS_BATCH)
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "查不到" not in joined
    assert "ETH Zurich" in joined
    assert "Lausanne" in joined or "洛桑" in joined
    assert "University of Zurich" in joined
    assert "哪一门" in joined


def test_named_eth_fee_narrowed_by_scope(monkeypatch):
    # Naming ETH matches TWO undergraduate siblings (CS BSc and CSE
    # BSc), so the template alone answers "ambiguous". When exactly
    # one of them is in view, the scope disambiguates to its fee.
    bare = _answer_no_key(monkeypatch, ETH_FEE_ZH, "zh-CN")
    assert "两个相关专业" in "\n".join(bare["lines"])
    scoped = _answer_no_key(monkeypatch, ETH_FEE_ZH, "zh-CN",
                            program_ids=[ETH_CS])
    joined = "\n".join(scoped["lines"])
    assert "CHF 4,380" in joined
    assert "两个相关专业" not in joined
    # Both siblings in scope: still ambiguous — and the ambiguous
    # line already names them, so it stands unchanged.
    both = _answer_no_key(monkeypatch, ETH_FEE_ZH, "zh-CN",
                          program_ids=[ETH_CS, ETH_CSE])
    assert "两个相关专业" in "\n".join(both["lines"])


def test_ielts_fact_via_scope(monkeypatch):
    # ETH CS BSc publishes no English requirement, so the honest
    # answer names the programme and says so — the same line the
    # template gives for a named programme — never a blanket unknown
    # and never an invented band.
    body = _answer_no_key(monkeypatch, "这个专业的雅思要求是多少？",
                          "zh-CN", program_ids=[ETH_CS])
    joined = "\n".join(body["lines"])
    assert "ETH Zurich" in joined
    assert "英语要求" in joined and "没有说明" in joined
    assert "查不到" not in joined


def test_deadline_fact_via_scope(monkeypatch):
    body = _answer_no_key(monkeypatch, "这个专业的申请截止日期是什么时候？",
                          "zh-CN", program_ids=[ETH_CS])
    joined = "\n".join(body["lines"])
    assert "31 March 2027" in joined
    assert "查不到" not in joined


# ---------------------------------------------------------------------------
# Why-not: genuinely no verified answer in chat — specific refusal
# ---------------------------------------------------------------------------

def test_why_not_met_with_scope_is_specific_not_blanket(monkeypatch):
    # The chat has no rule-by-rule evaluation, so "why isn't it met"
    # genuinely has no verified answer here — but the refusal must
    # name the programme and the missing piece, not say "查不到".
    body = _answer_no_key(monkeypatch, WHY_NOT_MET_ZH, "zh-CN",
                          program_ids=[ETH_CS])
    assert body["ai_status"] == "unavailable"
    joined = "\n".join(body["lines"])
    assert "查不到" not in joined
    assert "ETH Zurich" in joined
    assert "逐项" in joined
    # Without scope the blanket unknown is still the honest answer.
    bare = _answer_no_key(monkeypatch, WHY_NOT_MET_ZH, "zh-CN")
    assert bare["lines"][0] == "这个我从已核实的数据里查不到，不知道。"


# ---------------------------------------------------------------------------
# Guards: scope never hijacks other questions, unknown ids dropped
# ---------------------------------------------------------------------------

def test_scope_does_not_hijack_rank_question(monkeypatch):
    body = _answer_no_key(monkeypatch, "What is the rank of ETH Zurich?",
                          "en", program_ids=[ETH_CS])
    joined = "\n".join(body["lines"])
    assert "ETH Zurich" in joined
    assert "=8" in joined
    assert "CHF 4,380" not in joined


def test_scope_does_not_override_template_programme(monkeypatch):
    # The user names UCL; the scope shows ETH. The template's UCL
    # fee answer stands — the scope never overrides a named programme.
    body = _answer_no_key(
        monkeypatch, "What is the fee for UCL CS BSc?", "en",
        program_ids=[ETH_CS])
    joined = "\n".join(body["lines"])
    assert "GBP 48,600" in joined
    assert "CHF 4,380" not in joined


def test_unknown_scope_id_is_dropped():
    assert _clean_program_ids(["not-a-real-programme"]) == []
    assert _clean_program_ids([ETH_CS, "not-a-real-programme", ETH_CS]) == [ETH_CS]
    assert _clean_program_ids(None) == []


def test_endpoint_accepts_program_ids(monkeypatch):
    # POST /assistant/chat carries the scope through to the answer.
    _no_key_provider(monkeypatch)
    r = client.post("/api/v1/assistant/chat", json={
        "message": STEP8_QUESTION_ZH, "locale": "zh-CN",
        "program_ids": [ETH_CS]})
    assert r.status_code == 200
    body = r.json()
    assert body["ai_status"] == "unavailable"
    assert "CHF 4,380" in "\n".join(body["lines"])
    # ... and without it the same question stays unknown.
    r2 = client.post("/api/v1/assistant/chat", json={
        "message": STEP8_QUESTION_ZH, "locale": "zh-CN"})
    assert r2.status_code == 200
    assert r2.json()["lines"][0] == "这个我从已核实的数据里查不到，不知道。"
