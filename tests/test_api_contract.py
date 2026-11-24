"""Contract tests for the frontend (wizard) API shapes.

The backend also serves the spec/test contract (single program_id, nested
StudentProfile) — see tests/test_eligibility.py. These tests pin the
frontend contract: flat wizard profile + program_ids, multi-program
response, frontend-shaped rule results, and simulate baseline/scenario.

Run: .venv/bin/python -m pytest tests/ -v
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

UG_FLAT = {
    "track": "undergraduate", "targetProgramIds": ["ucl-cs-bsc-2026"],
    "alevels": "A*A*A", "mathsGrade": "A*",
    "ieltsOverall": 7.0, "ieltsListening": 6.5, "ieltsReading": 6.5,
    "ieltsWriting": 5.5, "ieltsSpeaking": 6.5,
    "budget": 50000, "budgetCurrency": "GBP",
}

PG_FLAT = {
    "track": "taught_masters", "targetProgramIds": ["nus-mcomp-cs"],
    "degree": "Bachelor's in Computing (Honours)",
    "ieltsOverall": 6.5, "greTotal": 325, "greAw": 4.0,
    "budget": 70000, "budgetCurrency": "SGD",
}


def test_programs_has_items():
    r = client.get("/api/v1/programs")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2
    assert {p["id"] for p in r.json()["items"]} == {"ucl-cs-bsc-2026", "nus-mcomp-cs"}


def test_match_flat_ug_writing_below():
    r = client.post("/api/v1/match", json={"profile": UG_FLAT,
                                           "program_ids": ["ucl-cs-bsc-2026"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["results"][0]["programId"] == "ucl-cs-bsc-2026"
    rules = {x["ruleId"]: x for x in body["results"][0]["ruleResults"]}
    assert rules["ucl-ielts-components"]["status"] == "NOT_MET"
    assert rules["ucl-ielts-overall"]["status"] == "MET"
    assert rules["ucl-academic"]["status"] == "MET"
    assert rules["ucl-fee"]["status"] == "MET"
    # Evidence ids must be frontend source ids, so the drawer can find them.
    assert "ucl-cs-english" in rules["ucl-ielts-components"]["evidenceIds"]
    assert body["results"][0]["eligibilitySummary"] == "NOT_MET"


def test_match_flat_pg_sample():
    r = client.post("/api/v1/match", json={"profile": PG_FLAT,
                                           "program_ids": ["nus-mcomp-cs"]})
    assert r.status_code == 200, r.text
    rules = {x["ruleId"]: x for x in r.json()["results"][0]["ruleResults"]}
    assert rules["nus-language"]["status"] == "MET"
    assert rules["nus-academic"]["status"] == "MET"
    assert rules["nus-gre-gmat"]["status"] == "MET"
    assert rules["nus-fee"]["status"] == "MET"
    # NUS states no IELTS component minimum, so the rule is NOT_APPLICABLE.
    assert rules["nus-language-components"]["status"] == "NOT_APPLICABLE"


def test_match_flat_track_mismatch_is_per_program():
    r = client.post("/api/v1/match", json={"profile": PG_FLAT,
                                           "program_ids": ["ucl-cs-bsc-2026"]})
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["eligibilitySummary"] == "TRACK_MISMATCH"
    assert r.json()["results"][0]["trackMismatch"] is True


def test_simulate_flat_writing_patch_flips_status():
    r = client.post("/api/v1/simulate", json={
        "baseline_profile": UG_FLAT, "patch": {"ieltsWriting": 6.5},
        "program_ids": ["ucl-cs-bsc-2026"]})
    assert r.status_code == 200, r.text
    body = r.json()
    base = {x["ruleId"]: x for x in body["baseline"]["results"][0]["ruleResults"]}
    scen = {x["ruleId"]: x for x in body["scenario"]["results"][0]["ruleResults"]}
    assert base["ucl-ielts-components"]["status"] == "NOT_MET"
    assert scen["ucl-ielts-components"]["status"] == "MET"
    assert {"program_id": "ucl-cs-bsc-2026", "rule_id": "ucl-ielts-components",
            "baseline_status": "NOT_MET", "scenario_status": "MET"} in body["delta"]
    # Changing writing must not change the overall score rule.
    assert scen["ucl-ielts-overall"]["status"] == "MET"


def test_simulate_flat_overall_only_does_not_fix_components():
    r = client.post("/api/v1/simulate", json={
        "baseline_profile": UG_FLAT, "patch": {"ieltsOverall": 8.0},
        "program_ids": ["ucl-cs-bsc-2026"]})
    assert r.status_code == 200, r.text
    scen = {x["ruleId"]: x for x in r.json()["scenario"]["results"][0]["ruleResults"]}
    assert scen["ucl-ielts-components"]["status"] == "NOT_MET"
