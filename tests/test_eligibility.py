"""Pytest unit tests for the PathPilot Day-1 rules engine and API.

Run from the project root:
    .venv/bin/python -m pytest tests/ -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.data import load_fixture
from app.main import app
from app.schemas import StudentProfile
from domain.eligibility import evaluate, overall_status

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = json.loads((ROOT / "data/versions/v1/programs.json").read_text())["programs"]
BY_ID = {p["id"]: p for p in PROGRAMS}

client = TestClient(app)


def ucl_profile(**overrides):
    base = {
        "application_track": "undergraduate",
        "undergrad_profile": {
            "qualification_type": "a_level",
            "a_level_grades": ["A*", "A*", "A"],
            "a_level_maths_grade": "A*",
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


# --- Engine: ordinary MET case (UCL) ---------------------------------------

def test_ucl_ordinary_met_case():
    profile = StudentProfile(**ucl_profile())
    results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
    assert status_of(results, "ucl-ielts-overall") == "MET"
    assert status_of(results, "ucl-ielts-components") == "MET"
    assert status_of(results, "ucl-academic") == "MET"
    assert status_of(results, "ucl-fee") == "MET"
    # TARA has no threshold, so the overall is UNKNOWN, not KNOWN_MINIMUMS_MET.
    assert status_of(results, "ucl-tara") == "UNKNOWN"
    assert overall_status(results) == "UNKNOWN"


def test_nus_ordinary_met_case():
    profile = StudentProfile(**nus_profile())
    results = evaluate(profile, BY_ID["nus-mcomp-cs"])
    assert status_of(results, "nus-language") == "MET"
    assert status_of(results, "nus-academic") == "MET"
    assert status_of(results, "nus-fee") == "MET"
    # GRE/GMAT missing is UNKNOWN, never NOT_MET; IELTS components are
    # NOT_APPLICABLE (no component minimum exists).
    assert status_of(results, "nus-gre-gmat") == "UNKNOWN"
    assert status_of(results, "nus-language-components") == "NOT_APPLICABLE"
    assert overall_status(results) == "UNKNOWN"


# --- Engine: NOT_MET language component ------------------------------------

def test_ucl_overall_7_writing_5_5_is_not_met():
    profile = StudentProfile(**ucl_profile(language={"writing": 5.5}))
    results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
    assert status_of(results, "ucl-ielts-overall") == "MET"  # overall 7.0
    assert status_of(results, "ucl-ielts-components") == "NOT_MET"
    assert overall_status(results) == "NOT_MET"


# --- Engine: UNKNOWN missing component --------------------------------------

def test_ucl_missing_component_is_unknown():
    profile = StudentProfile(**ucl_profile(language={"writing": None}))
    results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
    assert status_of(results, "ucl-ielts-components") == "UNKNOWN"


def test_ucl_toefl_is_unknown_never_converted():
    profile = StudentProfile(**ucl_profile(language={
        "exam": "toefl", "overall": 110.0, "listening": None,
        "reading": None, "writing": None, "speaking": None}))
    results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
    assert status_of(results, "ucl-ielts-overall") == "UNKNOWN"
    assert status_of(results, "ucl-ielts-components") == "UNKNOWN"


def test_nus_missing_gre_is_unknown_not_not_met():
    profile = StudentProfile(**nus_profile())
    results = evaluate(profile, BY_ID["nus-mcomp-cs"])
    assert status_of(results, "nus-gre-gmat") == "UNKNOWN"
    assert overall_status(results) != "NOT_MET"


# --- Day 1 audit fixes: contextual offer + NUS routes + components ---------

def test_ucl_contextual_alevel_is_unknown_not_not_met():
    # A*AB with A* in Maths meets the official contextual offer; without
    # evidence of contextual eligibility it is UNKNOWN, not a failure.
    profile = StudentProfile(**ucl_profile(undergrad_profile={
        "a_level_grades": ["A*", "A", "B"], "a_level_maths_grade": "A*"}))
    results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
    assert status_of(results, "ucl-academic") == "UNKNOWN"
    assert overall_status(results) == "UNKNOWN"


def test_ucl_ib_contextual_is_unknown_not_not_met():
    # IB 38 with HL Maths 7 is within the official contextual offer (IB 38);
    # HL total points are not recorded, so it cannot be decided.
    profile = StudentProfile(**ucl_profile(undergrad_profile={
        "qualification_type": "ib", "ib_total": 38, "ib_hl_maths_grade": 7}))
    results = evaluate(profile, BY_ID["ucl-cs-bsc-2026"])
    assert status_of(results, "ucl-academic") == "UNKNOWN"


def test_nus_related_bachelor_with_experience_is_unknown():
    # The related-discipline route requires honours; a related bachelor's + 2y
    # is not a listed route, so it must not be MET.
    profile = StudentProfile(**nus_profile(masters_profile={
        "degree_field": "related", "honours": False, "it_experience_years": 2}))
    results = evaluate(profile, BY_ID["nus-mcomp-cs"])
    assert status_of(results, "nus-academic") == "UNKNOWN"


def test_nus_related_honours_with_experience_is_met():
    profile = StudentProfile(**nus_profile(masters_profile={
        "degree_field": "related", "honours": True, "it_experience_years": 2}))
    results = evaluate(profile, BY_ID["nus-mcomp-cs"])
    assert status_of(results, "nus-academic") == "MET"


def test_nus_business_bachelor_with_experience_is_met():
    # Business route accepts bachelor's OR honours + 2y.
    profile = StudentProfile(**nus_profile(masters_profile={
        "degree_field": "business", "honours": False, "it_experience_years": 2}))
    results = evaluate(profile, BY_ID["nus-mcomp-cs"])
    assert status_of(results, "nus-academic") == "MET"


def test_nus_ielts_components_not_applicable():
    # NUS states no IELTS component minimum, so there is no component
    # requirement to check — NOT_APPLICABLE, not UNKNOWN.
    profile = StudentProfile(**nus_profile())
    results = evaluate(profile, BY_ID["nus-mcomp-cs"])
    assert status_of(results, "nus-language-components") == "NOT_APPLICABLE"


# --- Determinism ------------------------------------------------------------

def test_repeat_determinism_10x_identical():
    profile = StudentProfile(**ucl_profile())
    first = [r.model_dump() for r in evaluate(profile, BY_ID["ucl-cs-bsc-2026"])]
    for _ in range(10):
        assert [r.model_dump() for r in evaluate(profile, BY_ID["ucl-cs-bsc-2026"])] == first


# --- Simulation vs direct re-evaluation -------------------------------------

def test_simulation_matches_direct_reevaluation():
    base = ucl_profile()
    patch = {"language": {"overall": 6.0}}  # overall drops below 6.5
    resp = client.post("/api/v1/simulate",
                       json={"profile": base, "program_id": "ucl-cs-bsc-2026", "patch": patch})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Direct re-evaluation of the patched profile must equal the simulated one.
    patched_dict = {**base, "language": {**base["language"], "overall": 6.0}}
    direct = client.post("/api/v1/match",
                         json={"profile": patched_dict, "program_id": "ucl-cs-bsc-2026"})
    assert direct.status_code == 200, direct.text
    assert body["patched"] == direct.json()
    assert body["baseline"]["overall_status"] != body["patched"]["overall_status"]
    assert body["patched"]["overall_status"] == "NOT_MET"


def test_simulate_overall_change_does_not_change_components():
    base = ucl_profile()
    patch = {"language": {"overall": 8.0}}  # overall up, components untouched
    resp = client.post("/api/v1/simulate",
                       json={"profile": base, "program_id": "ucl-cs-bsc-2026", "patch": patch})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    comp_base = next(r for r in body["baseline"]["results"] if r["rule_id"] == "ucl-ielts-components")
    comp_patch = next(r for r in body["patched"]["results"] if r["rule_id"] == "ucl-ielts-components")
    assert comp_base == comp_patch


# --- Track mismatch 422 ------------------------------------------------------

def test_track_mismatch_422():
    # Masters profile sent against the undergraduate UCL programme.
    resp = client.post("/api/v1/match",
                       json={"profile": nus_profile(), "program_id": "ucl-cs-bsc-2026"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "TRACK_MISMATCH"

    # Cross-track fields in one profile.
    bad = ucl_profile()
    bad["masters_profile"] = {"degree_field": "computing", "honours": True}
    resp = client.post("/api/v1/profile/validate", json=bad)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "TRACK_MISMATCH"


# --- Fixture -----------------------------------------------------------------

def test_fixture_writing_5_5_is_not_met():
    fixture = load_fixture()
    assert fixture["synthetic"] is True
    profile = StudentProfile(**ucl_profile(language={"writing": 5.5}))
    results = evaluate(profile, fixture)
    assert status_of(results, "fixture-writing") == "NOT_MET"
    profile_ok = StudentProfile(**ucl_profile(language={"writing": 6.0}))
    assert status_of(evaluate(profile_ok, fixture), "fixture-writing") == "MET"


def test_programs_endpoint_has_two_real_programs_no_fixtures():
    resp = client.get("/api/v1/programs")
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["programs"]]
    assert ids == ["ucl-cs-bsc-2026", "nus-mcomp-cs"]
    assert not any(p.get("synthetic") for p in resp.json()["programs"])
    assert "fixture-p01" not in ids


def test_health_and_explain_rules_mode():
    assert client.get("/api/v1/health").json()["status"] == "ok"
    resp = client.post("/api/v1/match",
                       json={"profile": ucl_profile(), "program_id": "ucl-cs-bsc-2026"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ai_status"] == "unavailable"  # no key configured
    assert body["explanation"] is not None
    assert "ucl-ielts-overall" in body["explanation"]
