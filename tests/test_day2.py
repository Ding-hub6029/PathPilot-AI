"""Pytest suite for PathPilot AI Day 2 backend changes.

Covers spec tests T01-T05, T08, T09 plus every new Day 2 branch (GCSE,
IB HL total, residency fees, both-exams-present, /explain recompute,
/programs filter+pagination, /profile/validate full shape, rate limiting,
Decimal money) and regression tests for the five Day 1 audit fixes.

Day 1 files (test_eligibility.py, test_api_contract.py) are untouched;
all Day 2 tests live here.

Run from the project root:
    .venv/bin/python -m pytest tests/ -q
"""
from __future__ import annotations

import csv
import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.data as app_data
from ai.provider import ProviderAdapter
from app.adapter import RULES_VERSION, flat_to_student
from app.data import load_programs
from app.main import app, reset_rate_limits
from app.schemas import Budget, StudentProfile
from domain.eligibility import evaluate, overall_status

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = json.loads((ROOT / "data/versions/v1/programs.json").read_text())["programs"]
BY_ID = {p["id"]: p for p in PROGRAMS}

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Rate limits are per-IP and the TestClient shares one IP, so every
    test starts (and ends) with empty buckets — otherwise bursts in one
    test would 429 unrelated tests, including the Day 1 files."""
    reset_rate_limits()
    yield
    reset_rate_limits()


def ucl_profile(**overrides):
    base = {
        "application_track": "undergraduate",
        "undergrad_profile": {
            "qualification_type": "a_level",
            "a_level_grades": ["A*", "A*", "A"],
            "a_level_maths_grade": "A*",
            "gcse_english_grade": "C",
            "gcse_maths_grade": "4",
            "residency": "overseas",
            "intake_year": 2026,
            "graduation_status": "final",
            "tara_taken": True,
        },
        "language": {"exam": "ielts", "overall": 7.0, "listening": 6.5,
                     "reading": 6.5, "writing": 6.5, "speaking": 6.5},
        "budget": {"amount": 50000, "currency": "GBP", "period": "per_year"},
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


def nus_profile(**overrides):
    base = {
        "application_track": "taught_masters",
        "masters_profile": {
            "degree_field": "computing", "honours": True,
            "it_experience_years": 0, "gre_total": None,
            "gre_analytical": None, "gmat_total": None,
        },
        "language": {"exam": "ielts", "overall": 6.5},
        "budget": {"amount": 70000, "currency": "SGD", "period": "total"},
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


def status_of(results, rule_id):
    return next(r.status for r in results if r.rule_id == rule_id)


def rule_ids(results):
    return [r.rule_id for r in results]


def flat_rules(body, program_id):
    rules = {x["ruleId"]: x for x in body["results"][0]["ruleResults"]}
    assert body["results"][0]["programId"] == program_id
    return rules


# --- T01: ordinary cases ----------------------------------------------------

def test_t01_ordinary_cases():
    # UCL: everything supplied and meeting thresholds (TARA stays UNKNOWN:
    # required, no threshold stated — so overall is UNKNOWN, not MET).
    profile = StudentProfile(**ucl_profile())
    results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
    assert status_of(results, "ucl-ielts-overall") == "MET"
    assert status_of(results, "ucl-ielts-components") == "MET"
    assert status_of(results, "ucl-gcse") == "MET"
    assert status_of(results, "ucl-academic") == "MET"
    assert status_of(results, "ucl-fee") == "MET"
    assert status_of(results, "ucl-tara") == "UNKNOWN"
    assert overall_status(results) == "UNKNOWN"
    # NUS: same shape, different track.
    profile = StudentProfile(**nus_profile())
    results = evaluate(profile, BY_ID["nus-mcomp-cs"])
    assert status_of(results, "nus-language") == "MET"
    assert status_of(results, "nus-academic") == "MET"
    assert status_of(results, "nus-fee") == "MET"
    assert status_of(results, "nus-gre-gmat") == "UNKNOWN"
    assert status_of(results, "nus-language-components") == "NOT_APPLICABLE"
    assert overall_status(results) == "UNKNOWN"


# --- T02: ordinary B — non-A-level/IB background => UNKNOWN -----------------

def test_t02_non_alevel_ib_background_unknown():
    # A UCL applicant whose qualification is neither A level nor IB: no
    # equivalence evidence exists, so the academic rule is UNKNOWN.
    profile = StudentProfile(**ucl_profile(undergrad_profile={
        "qualification_type": "other", "a_level_grades": None,
        "a_level_maths_grade": None, "gcse_english_grade": "C",
        "gcse_maths_grade": "C"}))
    results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
    assert status_of(results, "ucl-academic") == "UNKNOWN"
    assert overall_status(results) == "UNKNOWN"
    # Same for a masters applicant outside the stated degree routes.
    profile = StudentProfile(**nus_profile(masters_profile={
        "degree_field": "other", "honours": False, "it_experience_years": 5}))
    results = evaluate(profile, BY_ID["nus-mcomp-cs"])
    assert status_of(results, "nus-academic") == "UNKNOWN"
    # And a UCL applicant with no qualification type at all.
    profile = StudentProfile(**ucl_profile(undergrad_profile={
        "qualification_type": None, "a_level_grades": None,
        "a_level_maths_grade": None}))
    assert status_of(evaluate(profile, BY_ID["ucl-cs-bsc-2026"]), "ucl-academic") == "UNKNOWN"


# --- T03: repeat determinism -------------------------------------------------

def test_t03_repeat_determinism_10x():
    profile = StudentProfile(**ucl_profile(language={
        "exam": "ielts", "overall": 7.0, "listening": 6.5, "reading": 6.5,
        "writing": 6.5, "speaking": 6.5, "toefl_overall": 95.0,
        "test_date": "2026-01-15"}))
    first = [r.model_dump() for r in evaluate(profile, BY_ID["ucl-cs-bsc-2026"])]
    for _ in range(10):
        assert [r.model_dump() for r in evaluate(profile, BY_ID["ucl-cs-bsc-2026"])] == first
    # Same through the API: identical rule results on repeated calls.
    body = {"profile": ucl_profile(), "program_ids": ["ucl-cs-bsc-2026"]}
    first_api = client.post("/api/v1/match", json=body).json()["results"]
    for _ in range(3):
        assert client.post("/api/v1/match", json=body).json()["results"] == first_api


# --- T04: complex — OR path, cross-currency budget, unknown date -----------

def test_t04_complex_or_cross_currency_unknown_date():
    # OR path: NUS business bachelor's + 2y IT experience is a listed route.
    profile = StudentProfile(**nus_profile(masters_profile={
        "degree_field": "business", "honours": False, "it_experience_years": 2}))
    assert status_of(evaluate(profile, BY_ID["nus-mcomp-cs"]), "nus-academic") == "MET"
    # Cross-currency budget: UCL fee cannot be compared with an SGD budget.
    profile = StudentProfile(**ucl_profile(budget={
        "amount": 90000, "currency": "SGD", "period": "per_year"}))
    results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
    assert status_of(results, "ucl-fee") == "UNKNOWN"
    assert overall_status(results) == "UNKNOWN"
    # Unknown date: TOEFL without a test date stays UNKNOWN, never converted.
    profile = StudentProfile(**ucl_profile(language={
        "exam": "toefl", "overall": 110.0, "test_date": None}))
    results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
    assert status_of(results, "ucl-toefl") == "UNKNOWN"
    assert status_of(results, "ucl-ielts-overall") == "UNKNOWN"
    # All three unknowns together still never produce a false MET.
    assert overall_status(results) == "UNKNOWN"


# --- T05: boundaries ---------------------------------------------------------

def test_t05_ielts_threshold_boundaries():
    # Overall exactly 6.5 MET, 6.4 NOT_MET; component exactly 6.0 MET.
    for overall, expected in ((6.5, "MET"), (6.4, "NOT_MET")):
        profile = StudentProfile(**ucl_profile(language={"overall": overall}))
        assert status_of(evaluate(profile, BY_ID["ucl-cs-bsc-2026"]),
                         "ucl-ielts-overall") == expected
    # Overall MET but a component below 6.0 => components NOT_MET, overall NOT_MET.
    profile = StudentProfile(**ucl_profile(language={"overall": 7.0, "writing": 5.5}))
    results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
    assert status_of(results, "ucl-ielts-overall") == "MET"
    assert status_of(results, "ucl-ielts-components") == "NOT_MET"
    assert overall_status(results) == "NOT_MET"
    profile = StudentProfile(**ucl_profile(language={"writing": 6.0}))
    assert status_of(evaluate(profile, BY_ID["ucl-cs-bsc-2026"]),
                     "ucl-ielts-components") == "MET"


def test_t05_toefl_date_boundary():
    # 2026-01-20 is the last old-scale day (92); 2026-01-21 is the first
    # new-scale day (4.5). Same score, different date, different verdict.
    cases = [
        ("2026-01-20", 92, "MET"), ("2026-01-20", 91, "NOT_MET"),
        ("2026-01-21", 4.5, "MET"), ("2026-01-21", 4.0, "NOT_MET"),
        ("2026-01-20", 4.5, "NOT_MET"),  # new-scale number on an old-scale date
        (None, 110, "UNKNOWN"),  # no date: never converted
    ]
    for test_date, score, expected in cases:
        profile = StudentProfile(**ucl_profile(language={
            "exam": "toefl", "overall": float(score), "test_date": test_date,
            "listening": None, "reading": None, "writing": None, "speaking": None}))
        results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
        assert status_of(results, "ucl-toefl") == expected, (test_date, score)


def test_t05_ib_hl_total_boundaries():
    base = {"qualification_type": "ib", "ib_total": 40, "ib_hl_maths_grade": 7}
    # HL total 20 MET, 19 NOT_MET (total 40 + HL Maths 7 alone is not enough).
    for hl_total, expected in ((20, "MET"), (19, "NOT_MET")):
        profile = StudentProfile(**ucl_profile(undergrad_profile={
            **base, "ib_hl_total": hl_total}))
        assert status_of(evaluate(profile, BY_ID["ucl-cs-bsc-2026"]),
                         "ucl-academic") == expected, hl_total
    # Contextual: IB 38 + HL Maths 7 + 18 HL points => UNKNOWN (not a failure).
    profile = StudentProfile(**ucl_profile(undergrad_profile={
        **base, "ib_total": 38, "ib_hl_total": 18}))
    assert status_of(evaluate(profile, BY_ID["ucl-cs-bsc-2026"]),
                     "ucl-academic") == "UNKNOWN"
    # IB 38 + HL Maths 7 + 17 HL points is below even the contextual 18.
    profile = StudentProfile(**ucl_profile(undergrad_profile={
        **base, "ib_total": 38, "ib_hl_total": 17}))
    assert status_of(evaluate(profile, BY_ID["ucl-cs-bsc-2026"]),
                     "ucl-academic") == "NOT_MET"


def test_t05_gcse_boundaries():
    cases = [(("C", "C"), "MET"), (("4", "4"), "MET"), (("C", "4"), "MET"),
             (("D", "C"), "NOT_MET"), (("C", "3"), "NOT_MET"),
             ((None, "C"), "UNKNOWN"), (("C", None), "UNKNOWN"),
             (("B", "A"), "MET")]
    for (eng, maths), expected in cases:
        profile = StudentProfile(**ucl_profile(undergrad_profile={
            "gcse_english_grade": eng, "gcse_maths_grade": maths}))
        assert status_of(evaluate(profile, BY_ID["ucl-cs-bsc-2026"]),
                         "ucl-gcse") == expected, (eng, maths)


def test_t05_fee_boundaries():
    # UK fee: exactly 9,790 MET, 9,789 NOT_MET.
    for amount, expected in ((9790, "MET"), (9789, "NOT_MET")):
        profile = StudentProfile(**ucl_profile(
            undergrad_profile={"residency": "uk"},
            budget={"amount": amount, "currency": "GBP", "period": "per_year"}))
        assert status_of(evaluate(profile, BY_ID["ucl-cs-bsc-2026"]),
                         "ucl-fee") == expected, amount
    # Overseas fee: exactly 46,700 MET, 46,699 NOT_MET.
    for amount, expected in ((46700, "MET"), (46699, "NOT_MET")):
        profile = StudentProfile(**ucl_profile(
            budget={"amount": amount, "currency": "GBP", "period": "per_year"}))
        assert status_of(evaluate(profile, BY_ID["ucl-cs-bsc-2026"]),
                         "ucl-fee") == expected, amount
    # NUS total: exactly 69,215 MET, 69,214 NOT_MET.
    for amount, expected in ((69215, "MET"), (69214, "NOT_MET")):
        profile = StudentProfile(**nus_profile(
            budget={"amount": amount, "currency": "SGD", "period": "total"}))
        assert status_of(evaluate(profile, BY_ID["nus-mcomp-cs"]),
                         "nus-fee") == expected, amount


# --- New branches: IB HL total ----------------------------------------------

def test_ib_hl_total_met_unknown_not_met():
    # No HL total supplied: total 40 + HL Maths 7 can no longer be MET
    # (Day 1 wrongly returned MET for HL sum < 20 — DECISIONS #39).
    profile = StudentProfile(**ucl_profile(undergrad_profile={
        "qualification_type": "ib", "ib_total": 40, "ib_hl_maths_grade": 7,
        "ib_hl_total": None}))
    result = next(r for r in evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
                  if r.rule_id == "ucl-academic")
    assert result.status == "UNKNOWN"
    assert "HL total not supplied" in result.detail


# --- New branches: GCSE ------------------------------------------------------

def test_gcse_met_not_met_unknown():
    for grades, expected in (({"gcse_english_grade": "C", "gcse_maths_grade": "C"}, "MET"),
                             ({"gcse_english_grade": "D", "gcse_maths_grade": "C"}, "NOT_MET"),
                             ({"gcse_english_grade": None, "gcse_maths_grade": None}, "UNKNOWN")):
        profile = StudentProfile(**ucl_profile(undergrad_profile=grades))
        assert status_of(evaluate(profile, BY_ID["ucl-cs-bsc-2026"]),
                         "ucl-gcse") == expected, grades


# --- New branches: residency -------------------------------------------------

def test_residency_uk_fee():
    profile = StudentProfile(**ucl_profile(
        undergrad_profile={"residency": "uk"},
        budget={"amount": 10000, "currency": "GBP", "period": "per_year"}))
    result = next(r for r in evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
                  if r.rule_id == "ucl-fee")
    assert result.status == "MET"
    assert "9,790" in result.detail


def test_residency_missing_assumes_overseas():
    # No residency supplied: the overseas fee applies and the detail says so.
    profile = StudentProfile(**ucl_profile(
        undergrad_profile={"residency": None},
        budget={"amount": 10000, "currency": "GBP", "period": "per_year"}))
    result = next(r for r in evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
                  if r.rule_id == "ucl-fee")
    assert result.status == "NOT_MET"
    assert "overseas assumed" in result.detail


# --- New branches: both exams present ----------------------------------------

def test_both_exams_ucl_toefl_present():
    # IELTS 7.0 + TOEFL 95 on 2026-01-15 (old scale): both rules evaluated.
    profile = StudentProfile(**ucl_profile(language={
        "exam": "ielts", "overall": 7.0, "listening": 6.5, "reading": 6.5,
        "writing": 6.5, "speaking": 6.5, "toefl_overall": 95.0,
        "test_date": "2026-01-15"}))
    results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
    assert status_of(results, "ucl-ielts-overall") == "MET"
    assert status_of(results, "ucl-toefl") == "MET"
    # Same profile, TOEFL 85: the TOEFL rule is NOT_MET, IELTS still MET.
    profile.language.toefl_overall = 85.0
    results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
    assert status_of(results, "ucl-toefl") == "NOT_MET"
    assert status_of(results, "ucl-ielts-overall") == "MET"


def test_both_exams_nus_toefl_present():
    profile = StudentProfile(**nus_profile(language={
        "exam": "ielts", "overall": 6.5, "toefl_overall": 95.0}))
    results = evaluate(profile, BY_ID["nus-mcomp-cs"])
    assert status_of(results, "nus-language") == "MET"
    assert status_of(results, "nus-toefl") == "MET"
    profile.language.toefl_overall = 80.0
    results = evaluate(profile, BY_ID["nus-mcomp-cs"])
    assert status_of(results, "nus-toefl") == "NOT_MET"
    assert status_of(results, "nus-language") == "MET"
    # TOEFL alone: nus-language covers it, no duplicate nus-toefl rule.
    profile = StudentProfile(**nus_profile(language={"exam": "toefl", "overall": 95.0}))
    results = evaluate(profile, BY_ID["nus-mcomp-cs"])
    assert status_of(results, "nus-language") == "MET"
    assert "nus-toefl" not in rule_ids(results)


def test_adapter_maps_new_wizard_fields_and_keeps_both_exams():
    flat = {
        "track": "undergraduate", "alevels": "A*A*A", "mathsGrade": "A*",
        "ieltsOverall": 7.0, "ieltsListening": 6.5, "ieltsReading": 6.5,
        "ieltsWriting": 6.5, "ieltsSpeaking": 6.5,
        "toefl": 95, "testDate": "2026-01-15",
        "ibTotal": None, "ibHlMaths": None, "ibHlTotal": None,
        "gcseEnglish": "B", "gcseMaths": "5", "residency": "uk",
        "intakeYear": 2026, "graduationStatus": "final",
        "budget": 10000, "budgetCurrency": "GBP",
    }
    profile = flat_to_student(flat)
    assert profile.language.exam == "ielts"
    assert profile.language.overall == 7.0
    assert profile.language.toefl_overall == 95
    assert profile.language.test_date == "2026-01-15"
    assert profile.undergrad_profile.gcse_english_grade == "B"
    assert profile.undergrad_profile.gcse_maths_grade == "5"
    assert profile.undergrad_profile.residency == "uk"
    assert profile.undergrad_profile.intake_year == 2026
    assert profile.undergrad_profile.graduation_status == "final"
    assert profile.target_intake == 2026
    # Through /match: the TOEFL rule is present, not dropped.
    resp = client.post("/api/v1/match", json={"profile": flat,
                                              "program_ids": ["ucl-cs-bsc-2026"]})
    assert resp.status_code == 200, resp.text
    rules = flat_rules(resp.json(), "ucl-cs-bsc-2026")
    assert rules["ucl-toefl"]["status"] == "MET"
    assert rules["ucl-gcse"]["status"] == "MET"
    assert rules["ucl-fee"]["status"] == "MET"  # UK fee 9,790, budget 10,000
    assert rules["ucl-toefl"]["expected"].startswith("TOEFL iBT Level 1")
    assert rules["ucl-gcse"]["expected"] == "GCSE English and Maths at grade C/4 or above"
    assert RULES_VERSION == "rules-v2-2026-11-25"
    assert resp.json()["rules_version"] == "rules-v2-2026-11-25"


def test_adapter_maps_ib_and_masters_experience_fields():
    flat_ib = {"track": "undergraduate", "ibTotal": 42, "ibHlMaths": 7,
               "ibHlTotal": 21, "gcseEnglish": "C", "gcseMaths": "C",
               "ieltsOverall": 7.0, "ieltsListening": 6.5, "ieltsReading": 6.5,
               "ieltsWriting": 6.5, "ieltsSpeaking": 6.5,
               "budget": 50000, "budgetCurrency": "GBP"}
    profile = flat_to_student(flat_ib)
    assert profile.undergrad_profile.qualification_type == "ib"
    assert profile.undergrad_profile.ib_total == 42
    assert profile.undergrad_profile.ib_hl_maths_grade == 7
    assert profile.undergrad_profile.ib_hl_total == 21
    resp = client.post("/api/v1/match", json={"profile": flat_ib,
                                              "program_ids": ["ucl-cs-bsc-2026"]})
    assert flat_rules(resp.json(), "ucl-cs-bsc-2026")["ucl-academic"]["status"] == "MET"
    flat_pg = {"track": "taught_masters", "degree": "Bachelor of Business",
               "ieltsOverall": 6.5, "itExperienceYears": 3,
               "budget": 70000, "budgetCurrency": "SGD"}
    profile = flat_to_student(flat_pg)
    assert profile.masters_profile.it_experience_years == 3
    resp = client.post("/api/v1/match", json={"profile": flat_pg,
                                              "program_ids": ["nus-mcomp-cs"]})
    assert flat_rules(resp.json(), "nus-mcomp-cs")["nus-academic"]["status"] == "MET"


# --- /explain recompute -------------------------------------------------------

def test_explain_forged_evaluation_422():
    forged = {"program_id": "ucl-cs-bsc-2026", "data_version": "v1",
              "overall_status": "KNOWN_MINIMUMS_MET", "results": [],
              "ai_status": "available", "explanation": "forged"}
    resp = client.post("/api/v1/explain", json={"evaluation": forged})
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["error"]["code"] == "EXPLAIN_REQUIRES_PROFILE"
    assert "recompute" in body["error"]["message"].lower()


def test_explain_recomputes_from_profile():
    # Writing 5.5 must come back NOT_MET — recomputed, never trusted.
    resp = client.post("/api/v1/explain", json={
        "profile": ucl_profile(language={"writing": 5.5}),
        "program_ids": ["ucl-cs-bsc-2026"], "locale": "en"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data_version"] == "v2"
    assert body["locale"] == "en"
    rules = flat_rules(body, "ucl-cs-bsc-2026")
    assert rules["ucl-ielts-components"]["status"] == "NOT_MET"
    assert rules["ucl-ielts-overall"]["status"] == "MET"
    assert body["results"][0]["ai_status"] == "unavailable"
    assert "ucl-ielts-components" in body["results"][0]["explanation"]
    # A forged KNOWN_MINIMUMS_MET sent alongside a profile cannot leak in:
    # the endpoint ignores any client verdict and recomputes.
    resp2 = client.post("/api/v1/explain", json={
        "profile": ucl_profile(language={"writing": 5.5}),
        "program_ids": ["ucl-cs-bsc-2026"]})
    assert resp2.json()["results"][0]["eligibilitySummary"] == "NOT_MET"


def test_explain_flat_profile_and_track_mismatch():
    flat = {"track": "undergraduate", "alevels": "A*A*A", "mathsGrade": "A*",
            "ieltsOverall": 7.0, "ieltsListening": 6.5, "ieltsReading": 6.5,
            "ieltsWriting": 6.5, "ieltsSpeaking": 6.5,
            "budget": 50000, "budgetCurrency": "GBP"}
    resp = client.post("/api/v1/explain", json={"profile": flat,
                                                "program_ids": ["ucl-cs-bsc-2026"]})
    assert resp.status_code == 200, resp.text
    assert flat_rules(resp.json(), "ucl-cs-bsc-2026")["ucl-ielts-overall"]["status"] == "MET"
    # Masters profile against UCL: per-program TRACK_MISMATCH, not a crash.
    resp = client.post("/api/v1/explain", json={
        "profile": nus_profile(), "program_ids": ["ucl-cs-bsc-2026"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"][0]["eligibilitySummary"] == "TRACK_MISMATCH"
    # Unknown program: 404.
    resp = client.post("/api/v1/explain", json={
        "profile": ucl_profile(), "program_ids": ["no-such-program"]})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PROGRAM_NOT_FOUND"


# --- T08: service failure ------------------------------------------------------

def test_t08_provider_timeout_keeps_rules(monkeypatch):
    # Inject a provider timeout AND a configured provider, so ai_status
    # must flip to unavailable while the rule results survive intact.
    monkeypatch.setenv("AI_PROVIDER", "test-provider")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "test-key")

    def _boom(self, prompt, timeout_s=10.0):
        raise TimeoutError("simulated provider timeout")

    monkeypatch.setattr(ProviderAdapter, "generate", _boom)
    resp = client.post("/api/v1/explain", json={
        "profile": ucl_profile(language={"writing": 5.5}),
        "program_ids": ["ucl-cs-bsc-2026"]})
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["ai_status"] == "unavailable"
    # The profile input is not lost: writing 5.5 still evaluates NOT_MET.
    rules = {x["ruleId"]: x for x in result["ruleResults"]}
    assert rules["ucl-ielts-components"]["status"] == "NOT_MET"
    assert rules["ucl-ielts-overall"]["status"] == "MET"
    assert result["explanation"] is not None
    assert "ucl-ielts-overall" in result["explanation"]


# --- T09: data failure ---------------------------------------------------------

def _copy_v1_to(tmp_path):
    # Copies the CURRENT data version (v2 since the Day 2 switch); the name
    # is kept so the T09 tests read unchanged.
    for name in ("programs.json", "source-manifest.json"):
        shutil.copy(ROOT / "data" / "versions" / "v2" / name, tmp_path / name)
    return tmp_path


def test_t09_corrupt_manifest_refuses_load(monkeypatch, tmp_path):
    d = _copy_v1_to(tmp_path)
    (d / "source-manifest.json").write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(app_data, "DATA_DIR", d)
    with pytest.raises(ValueError):
        load_programs()


def test_t09_missing_manifest_refuses_load(monkeypatch, tmp_path):
    d = _copy_v1_to(tmp_path)
    (d / "source-manifest.json").unlink()
    monkeypatch.setattr(app_data, "DATA_DIR", d)
    with pytest.raises(FileNotFoundError):
        load_programs()


def test_t09_fixture_in_real_data_refused(monkeypatch, tmp_path):
    d = _copy_v1_to(tmp_path)
    data = json.loads((d / "programs.json").read_text())
    data["programs"].append({"id": "fixture-p01", "synthetic": True,
                             "sources": [], "requirements": []})
    (d / "programs.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(app_data, "DATA_DIR", d)
    with pytest.raises(ValueError, match="fixture"):
        load_programs()


def test_t09_manifest_fact_unknown_program_refused(monkeypatch, tmp_path):
    d = _copy_v1_to(tmp_path)
    manifest = json.loads((d / "source-manifest.json").read_text())
    manifest["facts"].append({"id": "f-bogus", "program_id": "no-such-program",
                              "source_id": "ucl-bsc", "excerpt": "bogus",
                              "field": "x", "value": "y"})
    (d / "source-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(app_data, "DATA_DIR", d)
    with pytest.raises(ValueError, match="unknown program"):
        load_programs()


# --- /programs filter + pagination --------------------------------------------

def test_programs_filter_country():
    resp = client.get("/api/v1/programs", params={"country": "GB"})
    assert resp.status_code == 200
    body = resp.json()
    assert [p["id"] for p in body["items"]] == [
        "ucl-cs-bsc-2026", "imperial-comp-beng-2027",
        "imperial-msc-computing-2027", "ucl-cs-msc-2027"]
    assert body["programs"] == body["items"]  # backward-compat key
    assert body["data_version"] == "v2"
    assert body["next_cursor"] is None
    resp = client.get("/api/v1/programs", params={"country": "sg"})
    assert [p["id"] for p in resp.json()["items"]] == [
        "nus-mcomp-cs", "nus-bcomp-cs-2027", "ntu-bcomp-cs-2027", "ntu-msai-2027"]


def test_programs_filter_subject_intake_degree():
    assert [p["id"] for p in client.get("/api/v1/programs", params={"subject": "computer science"}).json()["items"]] == [
        "ucl-cs-bsc-2026", "nus-mcomp-cs", "imperial-comp-beng-2027",
        "imperial-msc-computing-2027", "ucl-cs-msc-2027", "nus-bcomp-cs-2027",
        "ntu-bcomp-cs-2027", "ntu-msai-2027"]
    assert client.get("/api/v1/programs", params={"subject": "physics"}).json()["items"] == []
    assert [p["id"] for p in client.get("/api/v1/programs", params={"intake": "2026"}).json()["items"]] == [
        "ucl-cs-bsc-2026"]
    assert [p["id"] for p in client.get("/api/v1/programs", params={"intake": "2027"}).json()["items"]] == [
        "nus-mcomp-cs", "imperial-comp-beng-2027", "imperial-msc-computing-2027",
        "ucl-cs-msc-2027", "nus-bcomp-cs-2027", "ntu-bcomp-cs-2027", "ntu-msai-2027"]
    assert [p["id"] for p in client.get("/api/v1/programs", params={"degree_level": "taught_masters"}).json()["items"]] == [
        "nus-mcomp-cs", "imperial-msc-computing-2027", "ucl-cs-msc-2027", "ntu-msai-2027"]
    assert [p["id"] for p in client.get("/api/v1/programs", params={"country": "GB", "degree_level": "taught_masters"}).json()["items"]] == [
        "imperial-msc-computing-2027", "ucl-cs-msc-2027"]


def test_programs_pagination_cursor():
    seen, cursor = [], None
    for _ in range(10):
        page = client.get("/api/v1/programs",
                          params={"limit": 1, **({"cursor": cursor} if cursor else {})}).json()
        assert len(page["items"]) == 1
        seen.append(page["items"][0]["id"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == ["ucl-cs-bsc-2026", "nus-mcomp-cs", "imperial-comp-beng-2027",
                    "imperial-msc-computing-2027", "ucl-cs-msc-2027", "nus-bcomp-cs-2027",
                    "ntu-bcomp-cs-2027", "ntu-msai-2027"]
    # Full walk with limit=1 visits all eight programs exactly once.
    assert len(set(seen)) == 8
    # limit above the max is capped at 20, not an error.
    capped = client.get("/api/v1/programs", params={"limit": 50}).json()
    assert len(capped["items"]) == 8
    assert capped["next_cursor"] is None
    # An invalid cursor is a 400, not a silent restart.
    bad = client.get("/api/v1/programs", params={"cursor": "!!!not-a-cursor"})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "VALIDATION_ERROR"


# --- /profile/validate full shape ----------------------------------------------

def test_validate_full_shape_valid():
    resp = client.post("/api/v1/profile/validate", json=ucl_profile())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True
    assert body["application_track"] == "undergraduate"
    assert body["warnings"] == []
    assert body["field_errors"] == []
    norm = body["normalized_profile"]
    assert norm["undergrad_profile"]["gcse_english_grade"] == "C"
    assert norm["undergrad_profile"]["residency"] == "overseas"
    assert norm["target_intake"] is None  # not set on this profile
    # Budget stays a plain JSON number, not a string.
    assert norm["budget"]["amount"] == 50000
    assert isinstance(norm["budget"]["amount"], (int, float))


def test_validate_warnings_for_missing_fields():
    profile = {"application_track": "undergraduate",
               "undergrad_profile": {"qualification_type": "a_level",
                                     "a_level_grades": ["A*", "A*", "A"],
                                     "a_level_maths_grade": "A*"},
               "language": {"exam": "none"}, "budget": None}
    resp = client.post("/api/v1/profile/validate", json=profile)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True  # warnings do not invalidate
    joined = " ".join(body["warnings"])
    assert "No language test" in joined
    assert "No budget" in joined
    assert "GCSE" in joined
    assert "Residency" in joined
    assert "Intake year" in joined
    assert body["normalized_profile"]["application_track"] == "undergraduate"


def test_validate_field_errors():
    profile = ucl_profile(
        language={"exam": "ielts", "overall": 9.5, "listening": 6.5,
                  "reading": 6.5, "writing": 6.5, "speaking": 6.5,
                  "test_date": "2026-02-30"},
        undergrad_profile={"ib_total": 46, "ib_hl_total": 22},
        budget={"amount": -100, "currency": "GBP", "period": "per_year"})
    resp = client.post("/api/v1/profile/validate", json=profile)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is False
    fields = {e["field"] for e in body["field_errors"]}
    assert "language.overall" in fields  # IELTS > 9
    assert "language.test_date" in fields  # 30 Feb is not a real date
    assert "undergrad_profile.ib_total" in fields  # > 45
    assert "undergrad_profile.ib_hl_total" in fields  # > 21
    assert "budget.amount" in fields  # negative
    # Grades are reported, never silently rescaled.
    profile2 = ucl_profile(undergrad_profile={"a_level_grades": ["A*", "Z", "A"]})
    body2 = client.post("/api/v1/profile/validate", json=profile2).json()
    assert body2["valid"] is False
    assert any(e["field"] == "undergrad_profile.a_level_grades"
               for e in body2["field_errors"])


# --- Rate limiting + security headers + OpenAPI --------------------------------

def test_rate_limit_explain_429():
    body = {"profile": ucl_profile(), "program_ids": ["ucl-cs-bsc-2026"]}
    for _ in range(10):
        assert client.post("/api/v1/explain", json=body).status_code == 200
    resp = client.post("/api/v1/explain", json=body)
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "RATE_LIMITED"
    assert resp.json()["request_id"]
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_rate_limit_general_429():
    for _ in range(60):
        assert client.get("/api/v1/programs").status_code == 200
    resp = client.get("/api/v1/programs")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "RATE_LIMITED"
    # Health stays up even when the general bucket is exhausted.
    assert client.get("/api/v1/health").status_code == 200


def test_security_headers_present():
    resp = client.get("/api/v1/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["X-Request-Id"]
    resp = client.get("/api/v1/programs")
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_openapi_matches_generated_copy():
    live = client.get("/api/v1/openapi.json")
    assert live.status_code == 200
    stored = json.loads((ROOT / "docs" / "openapi.json").read_text())
    assert live.json() == stored
    assert "/api/v1/explain" in live.json()["paths"]
    assert "/api/v1/programs" in live.json()["paths"]
    assert "/api/v1/profile/validate" in live.json()["paths"]
    docs = client.get("/docs")
    assert docs.status_code == 200


# --- Decimal money --------------------------------------------------------------

def test_decimal_budget_comparison():
    # Budget.amount is Decimal in-process; JSON output stays a plain number.
    assert isinstance(Budget(amount=50000).amount, Decimal)
    assert Budget(amount=46699.99).amount == Decimal("46699.99")
    assert Budget(amount="46700.10").amount == Decimal("46700.10")
    # Exact-boundary behaviour: 46,699.99 is below 46,700 (no float error).
    for amount, expected in ((46700, "MET"), (46699.99, "NOT_MET"),
                             (46700.10, "MET")):
        profile = StudentProfile(**ucl_profile(
            budget={"amount": amount, "currency": "GBP", "period": "per_year"}))
        assert status_of(evaluate(profile, BY_ID["ucl-cs-bsc-2026"]),
                         "ucl-fee") == expected, amount
    # Through the API the observed fee amount is a JSON number, not a string.
    resp = client.post("/api/v1/match", json={
        "profile": ucl_profile(budget={"amount": 46700, "currency": "GBP",
                                       "period": "per_year"}),
        "program_id": "ucl-cs-bsc-2026"})
    assert resp.status_code == 200, resp.text
    fee = next(r for r in resp.json()["results"] if r["rule_id"] == "ucl-fee")
    assert fee["observed"] == 46700
    assert isinstance(fee["observed"], (int, float))


# --- Day 1 audit-fix regressions (must NOT regress) ------------------------------

def test_regression_ucl_contextual_unknown():
    profile = StudentProfile(**ucl_profile(undergrad_profile={
        "a_level_grades": ["A*", "A", "B"], "a_level_maths_grade": "A*"}))
    assert status_of(evaluate(profile, BY_ID["ucl-cs-bsc-2026"]),
                     "ucl-academic") == "UNKNOWN"


def test_regression_nus_related_degree_honours_rule():
    # Related bachelor's + 2y is NOT a listed route (honours required).
    profile = StudentProfile(**nus_profile(masters_profile={
        "degree_field": "related", "honours": False, "it_experience_years": 2}))
    assert status_of(evaluate(profile, BY_ID["nus-mcomp-cs"]),
                     "nus-academic") == "UNKNOWN"
    # Related honours + 2y IS a listed route.
    profile = StudentProfile(**nus_profile(masters_profile={
        "degree_field": "related", "honours": True, "it_experience_years": 2}))
    assert status_of(evaluate(profile, BY_ID["nus-mcomp-cs"]),
                     "nus-academic") == "MET"


def test_regression_nus_ielts_components_not_applicable():
    profile = StudentProfile(**nus_profile())
    assert status_of(evaluate(profile, BY_ID["nus-mcomp-cs"]),
                     "nus-language-components") == "NOT_APPLICABLE"


def test_regression_ucl_toefl_unknown_without_date():
    profile = StudentProfile(**ucl_profile(language={
        "exam": "toefl", "overall": 110.0}))
    results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
    assert status_of(results, "ucl-ielts-overall") == "UNKNOWN"
    assert status_of(results, "ucl-toefl") == "UNKNOWN"


def test_regression_nus_gre_gmat_unknown_reason():
    profile = StudentProfile(**nus_profile())
    result = next(r for r in evaluate(profile, BY_ID["nus-mcomp-cs"])
                  if r.rule_id == "nus-gre-gmat")
    assert result.status == "UNKNOWN"
    assert "no rejection rule" in result.detail
    assert "FAQ" not in result.detail  # the unverifiable FAQ claim was removed


# --- Traceability artifact -------------------------------------------------------

def test_traceability_csv_exists_and_covers_day2():
    path = ROOT / "data" / "versions" / "v2" / "traceability.csv"
    assert path.exists(), "run tools/generate_traceability.py"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert set(rows[0].keys()) == {"requirement_id", "implementation",
                                   "test_id", "evidence", "release_sha"}
    by_id = {r["requirement_id"]: r for r in rows}
    for req in ("FR01", "FR02", "FR05", "FR06", "T01", "T02", "T03", "T04",
                "T05", "T08", "T09", "NFR04"):
        assert req in by_id, req
        assert by_id[req]["test_id"], req
        assert by_id[req]["implementation"], req
