"""Why-not explanations + comparison view (Day 3, W2 build round).

Covers, without an AI key (template mode unless a mock provider is
injected):
- the audit profile (China Gaokao, UG CS, Gaokao 680/750, IELTS 7.0
  with Writing 6.5, budget GBP 50,000, 2027 entry, overseas
  residency, Switzerland preference): no programme fails a rule —
  the why-not must say so honestly (academic UNKNOWN, Gaokao route,
  no invented score fix) instead of inventing a writing failure;
- a real IELTS-writing failure (frozen ordinary-gaokao-ucl case:
  Writing 5.5 vs 6.0 required): the why-not names the rule and the
  exact gap, the fee shortfall is the exact engine figure, and the
  cheapest fix (Writing +0.5) is verified by re-running the engine;
- cheapest-fix computation (budget-only failure, two failing
  components -> combined retake, academic-only failure -> no fix);
- the comparison data shape (rule families align across programmes);
- citation-check failure -> template fallback, and a valid mock
  model output -> model note with ai_status "available";
- the POST /api/v1/whynot endpoint contract (standalone test app:
  main.py is untouched, the coordinator registers the router).

Run: .venv/bin/pytest -q -p no:cacheprovider tests/test_whynot.py
"""
from __future__ import annotations

import copy
import json
import os
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai.explain import build_comparison, compute_whynot, whynot_with_model
from ai.grounding import programme_sources
from ai.provider import ProviderAdapter
from app.data import EXPANSION_PROGRAMS, PROGRAMS
from app.router_whynot import router as whynot_router
from app.schemas import Evaluation, StudentProfile
from domain.eligibility import evaluate, overall_status
from domain.expansion_eval import evaluate_expansion

# --- Audit profile (task brief) -------------------------------------------
AUDIT_FLAT = {
    "track": "undergraduate", "curriculum": "cn_gaokao", "field": "computing",
    "gaokaoScore": 680, "gaokaoTotal": 750, "residency": "overseas",
    "intakeYear": 2027,
    "ieltsOverall": 7.0, "ieltsListening": 7, "ieltsReading": 7,
    "ieltsWriting": 6.5, "ieltsSpeaking": 7,
    "budget": 50000, "budgetCurrency": "GBP",
    "prefCountries": ["CH"], "prefClimate": "cool",
    "prefEnvironment": "campus", "prefCity": "Zurich",
}

AUDIT_NESTED = {
    "application_track": "undergraduate",
    "undergrad_profile": {
        "curriculum": "cn_gaokao", "gaokao_score": 680, "gaokao_total": 750,
        "residency": "overseas", "intake_year": 2027},
    "language": {"exam": "ielts", "overall": 7.0, "listening": 7.0,
                 "reading": 7.0, "writing": 6.5, "speaking": 7.0},
    "budget": {"amount": 50000, "currency": "GBP", "period": "per_year"},
}

# Frozen ordinary-gaokao-ucl case (ai/evaluation.py): same Gaokao
# profile but IELTS Writing 5.5 (below UCL's 6.0 component minimum)
# and budget GBP 10,000 (below UCL's GBP 48,600 overseas fee).
FROZEN_NESTED = {
    "application_track": "undergraduate",
    "undergrad_profile": {
        "curriculum": "cn_gaokao", "gaokao_score": 680, "gaokao_total": 750,
        "gaokao_maths": 140, "residency": "overseas"},
    "language": {"exam": "ielts", "overall": 7.0, "listening": 7.0,
                 "reading": 7.0, "writing": 5.5, "speaking": 7.0},
    "budget": {"amount": 10000, "currency": "GBP", "period": "per_year"},
}

# A-level applicant, everything met except the budget (GBP 40,000 vs
# UCL's GBP 48,600 overseas fee).
BUDGET_SHORT_FLAT = {
    "track": "undergraduate", "targetProgramIds": ["ucl-cs-bsc-2026"],
    "alevels": "A*A*A", "mathsGrade": "A*",
    "ieltsOverall": 7.0, "ieltsListening": 7.0, "ieltsReading": 7.0,
    "ieltsWriting": 7.0, "ieltsSpeaking": 7.0,
    "budget": 40000, "budgetCurrency": "GBP",
}

# A-level grades below the stated minimum (BBB vs A*A*A): the academic
# rule fails and no single change is offered for it.
ACADEMIC_FAIL_FLAT = {
    "track": "undergraduate", "targetProgramIds": ["ucl-cs-bsc-2026"],
    "alevels": "BBB", "mathsGrade": "B",
    "ieltsOverall": 7.0, "ieltsListening": 7.0, "ieltsReading": 7.0,
    "ieltsWriting": 7.0, "ieltsSpeaking": 7.0,
    "budget": 50000, "budgetCurrency": "GBP",
}


def _evaluation(profile: dict, program_id: str) -> Evaluation:
    student = StudentProfile(**copy.deepcopy(profile))
    program = PROGRAMS.get(program_id)
    if program is not None:
        results = evaluate(student, program)
    else:
        results = evaluate_expansion(student, EXPANSION_PROGRAMS[program_id])
    return Evaluation(program_id=program_id, data_version="v2",
                      overall_status=overall_status(results), results=results)


def _whynot_app() -> TestClient:
    """Standalone app mounting only the why-not router (main.py is
    untouched — the coordinator registers the router at integration)."""
    test_app = FastAPI()
    test_app.include_router(whynot_router)
    return TestClient(test_app)


# --- Audit profile: no invented writing failure ----------------------------

def test_audit_profile_has_no_failing_rule_on_ucl_or_swiss_ug():
    """The audit profile (Writing 6.5) meets every known minimum on
    UCL and on the Swiss UG CS programmes; the only blockers are
    UNKNOWN academics / language-of-instruction. The why-not must
    report that honestly — no failing rule, no cheapest fix, and the
    Gaokao-route flag — never a Writing 6.5 vs 7.0 claim (no
    programme in the catalogue requires Writing 7.0)."""
    audit = StudentProfile(**copy.deepcopy(AUDIT_NESTED))
    for pid in ("ucl-cs-bsc-2026", "imperial-comp-beng-2027",
                "eth-cs-bsc-2027", "eth-cse-bsc-2027",
                "epfl-cs-bsc-2027", "zurich-informatics-bsc-2027"):
        ev = _evaluation(AUDIT_NESTED, pid)
        w = compute_whynot(ev, profile=audit, budget_currency="GBP")
        assert w["failing_rules"] == [], pid
        assert w["cheapest_fix"] is None, pid
        assert w["no_single_fix"] is False, pid
        assert w["academic_unknown"] is True, pid
        assert w["gaokao_route"] is True, pid
        assert "No university publishes a Gaokao equivalence" in w["template_text"]


# --- Real IELTS-writing failure (frozen case) -------------------------------

def test_whynot_names_real_failing_rule_and_exact_gap():
    ev = _evaluation(FROZEN_NESTED, "ucl-cs-bsc-2026")
    audit = StudentProfile(**copy.deepcopy(FROZEN_NESTED))
    w = compute_whynot(ev, profile=audit, budget_currency="GBP")
    failing = {f["rule_id"]: f for f in w["failing_rules"]}
    assert set(failing) == {"ucl-ielts-components", "ucl-fee"}
    comp = failing["ucl-ielts-components"]
    assert comp["family"] == "language-components"
    assert comp["gaps"] == [{"kind": "component", "label": "writing",
                             "required": 6.0, "observed": 5.5, "gap": 0.5}]
    fee = failing["ucl-fee"]
    assert fee["gaps"][0]["kind"] == "fee"
    assert fee["gaps"][0]["fee_currency"] == "GBP"
    assert fee["gaps"][0]["fee_amount"] == 48600
    assert fee["gaps"][0]["observed"] == 10000
    assert fee["gaps"][0]["gap"] == 38600  # exact engine shortfall
    assert "5.5" in w["template_text"] and "38,600" in w["template_text"]


def test_cheapest_fix_is_writing_plus_half_verified_by_engine():
    """Both failing rules could be cleared by one change each
    (Writing +0.5, budget +38,600); the tie-break prefers the
    language step, and the fix is verified by re-running the engine
    on the patched profile — not just asserted structurally."""
    ev = _evaluation(FROZEN_NESTED, "ucl-cs-bsc-2026")
    audit = StudentProfile(**copy.deepcopy(FROZEN_NESTED))
    w = compute_whynot(ev, profile=audit, budget_currency="GBP")
    fix = w["cheapest_fix"]
    assert fix is not None
    assert fix["kind"] == "ielts_component"
    assert fix["component"] == "writing"
    assert fix["from"] == 5.5 and fix["to"] == 6.0
    assert fix["resolves_rule_ids"] == ["ucl-ielts-components"]
    assert fix["rules_resolved"] == 1
    assert fix["verified"] is True


def test_cheapest_fix_budget_only_failure():
    from app.adapter import flat_to_student
    profile = flat_to_student(copy.deepcopy(BUDGET_SHORT_FLAT))
    ev = _evaluation(
        {"application_track": "undergraduate",
         "undergrad_profile": {"curriculum": "uk_alevel",
                               "a_level_grades": ["A*", "A*", "A"],
                               "a_level_maths_grade": "A*",
                               "gcse_english_grade": "A",
                               "gcse_maths_grade": "A",
                               "residency": "overseas"},
         "language": {"exam": "ielts", "overall": 7.0, "listening": 7.0,
                      "reading": 7.0, "writing": 7.0, "speaking": 7.0},
         "budget": {"amount": 40000, "currency": "GBP", "period": "per_year"}},
        "ucl-cs-bsc-2026")
    w = compute_whynot(ev, profile=profile, budget_currency="GBP",
                       fee_currency="GBP")
    assert [f["rule_id"] for f in w["failing_rules"]] == ["ucl-fee"]
    assert w["failing_rules"][0]["gaps"][0]["gap"] == 8600
    fix = w["cheapest_fix"]
    assert fix is not None and fix["kind"] == "budget"
    assert fix["from"] == 40000 and fix["to"] == 48600
    assert fix["currency"] == "GBP"
    assert fix["resolves_rule_ids"] == ["ucl-fee"]
    assert fix["verified"] is True


def test_two_failing_components_need_combined_retake():
    """Writing 5.5 AND Reading 5.5: raising one component alone
    clears no rule, so the cheapest fix is the combined retake."""
    prof = copy.deepcopy(FROZEN_NESTED)
    prof["language"]["reading"] = 5.5
    prof["budget"] = {"amount": 50000, "currency": "GBP", "period": "per_year"}
    ev = _evaluation(prof, "ucl-cs-bsc-2026")
    audit = StudentProfile(**copy.deepcopy(prof))
    w = compute_whynot(ev, profile=audit, budget_currency="GBP")
    assert [f["rule_id"] for f in w["failing_rules"]] == ["ucl-ielts-components"]
    fix = w["cheapest_fix"]
    assert fix is not None
    assert fix["kind"] == "ielts_components"
    assert fix["resolves_rule_ids"] == ["ucl-ielts-components"]
    assert fix["verified"] is True


def test_academic_only_failure_has_no_single_fix():
    """An academic NOT_MET (A-level grades below the minimum) has no
    candidate change: the why-not says so instead of inventing one."""
    from app.adapter import flat_to_student
    profile = flat_to_student(copy.deepcopy(ACADEMIC_FAIL_FLAT))
    nested = profile.model_dump(mode="json")
    ev = _evaluation(nested, "ucl-cs-bsc-2026")
    w = compute_whynot(ev, profile=profile, budget_currency="GBP")
    assert [f["rule_id"] for f in w["failing_rules"]] == ["ucl-academic"]
    assert w["cheapest_fix"] is None
    assert w["no_single_fix"] is True
    assert "No single change on its own clears a failed rule" in w["template_text"]


def test_fee_shortfall_uses_converted_figure_cross_currency():
    """ETH charges CHF 4,380/year; a GBP 3,000 budget falls short by
    the converted figure (fee approx. GBP — never a CHF-minus-GBP
    subtraction), and the budget fix is engine-verified."""
    prof = copy.deepcopy(AUDIT_NESTED)
    prof["budget"] = {"amount": 3000, "currency": "GBP", "period": "per_year"}
    ev = _evaluation(prof, "eth-cs-bsc-2027")
    audit = StudentProfile(**copy.deepcopy(prof))
    w = compute_whynot(ev, profile=audit, budget_currency="GBP",
                       fee_currency="CHF")
    fee = next(f for f in w["failing_rules"] if f["rule_id"] == "exp-fee")
    gap = fee["gaps"][0]
    assert gap["fee_currency"] == "CHF" and gap["fee_amount"] == 4380
    assert gap["converted_currency"] == "GBP"
    assert gap["gap"] == gap["converted_fee"] - 3000
    assert gap["gap"] > 0
    fix = w["cheapest_fix"]
    assert fix is not None and fix["kind"] == "budget"
    import math
    assert fix["to"] == math.floor(gap["converted_fee"]) + 1  # one whole unit above the rounded converted figure, so it actually clears the fee
    assert fix["verified"] is True


# --- Comparison data shape --------------------------------------------------

def test_comparison_aligns_by_rule_family():
    frozen = _evaluation(FROZEN_NESTED, "ucl-cs-bsc-2026")
    imperial = _evaluation(AUDIT_NESTED, "imperial-comp-beng-2027")
    comp = build_comparison([frozen, imperial])
    assert "language-components" in comp["rule_families"]
    assert "fee" in comp["rule_families"]
    assert "academic" in comp["rule_families"]
    by_pid = {c["program_id"]: c for c in comp["columns"]}
    assert by_pid["ucl-cs-bsc-2026"]["families"]["language-components"]["status"] == "NOT_MET"
    assert by_pid["ucl-cs-bsc-2026"]["families"]["fee"]["status"] == "NOT_MET"
    assert by_pid["imperial-comp-beng-2027"]["families"]["language-components"]["status"] == "MET"
    assert by_pid["imperial-comp-beng-2027"]["families"]["fee"]["status"] == "MET"
    assert by_pid["ucl-cs-bsc-2026"]["cheapest_fix"]["kind"] == "ielts_component"
    assert by_pid["imperial-comp-beng-2027"]["cheapest_fix"] is None


# --- Model polish: citation-check failure -> template fallback -------------

_MOCK_ENV = {
    "AI_PROVIDER": "openai",
    "AI_MODEL": "mock-whynot-model",
    "AI_API_KEY": "mock-test-key",
    "AI_BASE_URL": "https://api.openai.com/v1",
}


def _chat_response(payload: dict | str) -> httpx.Response:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                     "usage": {}})


def _mock_provider(handler) -> ProviderAdapter:
    with patch.dict(os.environ, _MOCK_ENV):
        return ProviderAdapter(_transport=httpx.MockTransport(handler))


def _handler_bad(request: httpx.Request) -> httpx.Response:
    """Claims a NOT_MET rule is MET, cites a fake evidence id, and
    includes a raw URL — the grounding whitelist must reject it."""
    return _chat_response({
        "summary": "Everything is met, see https://evil.example.com/proof.",
        "claims": [{
            "text": "ucl-ielts-components meets the stated minimum. "
                    "See https://evil.example.com/proof.",
            "kind": "fact",
            "rule_ids": ["ucl-ielts-components"],
            "evidence_ids": ["fake-evidence-999"],
        }],
        "unknowns": [], "actions": [], "limitations": []})


def _handler_good(request: httpx.Request) -> httpx.Response:
    """Number-free, properly cited reading: must pass validation."""
    sources = programme_sources("ucl-cs-bsc-2026")
    first = sources[0].id if sources else "src:ucl-cs-bsc-2026:ucl-bsc"
    return _chat_response({
        "summary": "The writing score suggests the components rule may be the closest gap.",
        "claims": [{
            "text": "The writing score suggests the components rule may be the closest gap to close.",
            "kind": "inference",
            "rule_ids": ["ucl-ielts-components"],
            "evidence_ids": [first],
        }],
        "unknowns": [{
            "field": "academic",
            "reason": "No Gaokao equivalence is published.",
            "question": "Which foundation route does the university publish?"}],
        "actions": [], "limitations": []})


def test_citation_check_failure_falls_back_to_template():
    ev = _evaluation(FROZEN_NESTED, "ucl-cs-bsc-2026")
    provider = _mock_provider(_handler_bad)
    whynot, model_note, ai_status = whynot_with_model(ev, "en", provider)
    assert ai_status == "unavailable"
    assert model_note is None
    # Template intact: the real failing rules and gaps survive.
    assert [f["rule_id"] for f in whynot["failing_rules"]] == [
        "ucl-ielts-components", "ucl-fee"]
    assert "evil.example.com" not in whynot["template_text"]
    assert "fake-evidence-999" not in whynot["template_text"]


def test_valid_mock_model_output_yields_model_note():
    ev = _evaluation(FROZEN_NESTED, "ucl-cs-bsc-2026")
    provider = _mock_provider(_handler_good)
    whynot, model_note, ai_status = whynot_with_model(ev, "en", provider)
    assert ai_status == "available"
    assert model_note is not None
    assert "suggests" in model_note
    assert whynot["failing_rules"][0]["rule_id"] == "ucl-ielts-components"


def test_no_provider_means_template_only():
    ev = _evaluation(FROZEN_NESTED, "ucl-cs-bsc-2026")
    with patch.dict(os.environ, {"AI_PROVIDER": "", "AI_MODEL": "",
                                 "AI_API_KEY": ""}):
        provider = ProviderAdapter()
    whynot, model_note, ai_status = whynot_with_model(ev, "en", provider)
    assert ai_status == "unavailable"
    assert model_note is None
    # Structural (unverified) ranking still names the writing fix.
    assert whynot["cheapest_fix"]["kind"] == "ielts_component"
    assert whynot["cheapest_fix"]["verified"] is False


# --- Endpoint contract ------------------------------------------------------

def test_whynot_endpoint_audit_profile():
    client = _whynot_app()
    r = client.post("/api/v1/whynot", json={
        "profile": AUDIT_FLAT,
        "program_ids": ["ucl-cs-bsc-2026", "eth-cs-bsc-2027"],
        "locale": "en"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["results"]) == 2
    for res in body["results"]:
        assert res["ai_status"] == "unavailable"  # no key in this env
        assert res["model_note"] is None
        w = res["whynot"]
        assert w["failing_rules"] == []
        assert w["academic_unknown"] is True
        assert w["gaokao_route"] is True
        assert w["cheapest_fix"] is None
        assert res["ruleResults"], "ruleResults travel with the whynot"


def test_whynot_endpoint_frozen_case_names_writing_fix():
    client = _whynot_app()
    r = client.post("/api/v1/whynot", json={
        "profile": FROZEN_NESTED,
        "program_ids": ["ucl-cs-bsc-2026"],
        "locale": "en"})
    assert r.status_code == 200, r.text
    w = r.json()["results"][0]["whynot"]
    assert w["cheapest_fix"]["kind"] == "ielts_component"
    assert w["cheapest_fix"]["component"] == "writing"
    assert w["cheapest_fix"]["from"] == 5.5
    assert w["cheapest_fix"]["to"] == 6.0
    assert w["cheapest_fix"]["verified"] is True
    fee_gap = next(f for f in w["failing_rules"]
                   if f["rule_id"] == "ucl-fee")["gaps"][0]
    assert fee_gap["gap"] == 38600


def test_whynot_endpoint_rejects_client_evaluation_and_unknown_id():
    client = _whynot_app()
    r = client.post("/api/v1/whynot", json={
        "evaluation": {"program_id": "ucl-cs-bsc-2026", "results": []},
        "program_ids": ["ucl-cs-bsc-2026"]})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "EXPLAIN_REQUIRES_PROFILE"
    r = client.post("/api/v1/whynot", json={
        "profile": AUDIT_FLAT, "program_ids": ["no-such-programme"]})
    assert r.status_code == 404
    r = client.post("/api/v1/whynot", json={
        "profile": AUDIT_FLAT, "program_ids": []})
    assert r.status_code == 422
