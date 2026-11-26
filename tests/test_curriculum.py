"""Tests for the 2026-11-25 fix: country / curriculum branching.

Covers DECISIONS #66-#68: the wizard's first step (curriculum) drives the
engine, the GCSE rule is NOT_APPLICABLE outside the UK A-level branch,
Gaokao is never converted to A level (UCL + Imperial), the Imperial USA
AP standard supports a real verdict (below -> NOT_MET, standard met ->
UNKNOWN because the course-specific A* Maths cannot be checked from AP
grades), and Singapore A levels are evaluated as A levels. Also pins the
new flat-response fields (observedRaw / thresholdRaw / reasonKey) that
the frontend's localized renderer depends on.

Run from the project root:
    .venv/bin/python -m pytest tests/ -q
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapter import flat_to_student
from app.data import PROGRAMS
from app.main import app, reset_rate_limits
from app.schemas import Language, StudentProfile, UndergradProfile
from domain.eligibility import evaluate

client = TestClient(app)


def _ug(undergrad=None, language=None, budget=None):
    return StudentProfile(application_track="undergraduate",
                          undergrad_profile=undergrad or UndergradProfile(),
                          language=language, budget=budget)


def _rules(profile, pid):
    return {r.rule_id: r for r in evaluate(profile, PROGRAMS[pid])}


def _flat_rules(profile, pid):
    resp = client.post("/api/v1/match",
                       json={"profile": profile, "program_ids": [pid]})
    assert resp.status_code == 200, resp.text
    return {x["ruleId"]: x for x in resp.json()["results"][0]["ruleResults"]}


# --- Gaokao: no published equivalence -> UNKNOWN, never converted ----------

def test_ucl_gaokao_unknown_and_gcse_not_applicable():
    prof = _ug(UndergradProfile(curriculum="cn_gaokao", gaokao_score=680,
                                gaokao_total=750, gaokao_maths=140))
    rules = _rules(prof, "ucl-cs-bsc-2026")
    assert rules["ucl-academic"].status == "UNKNOWN"
    assert "Gaokao" in rules["ucl-academic"].detail
    assert rules["ucl-academic"].observed["gaokao_score"] == 680
    # GCSE is a UK-school qualification: no GCSEs on this branch.
    assert rules["ucl-gcse"].status == "NOT_APPLICABLE"


def test_imperial_gaokao_unknown():
    prof = _ug(UndergradProfile(curriculum="cn_gaokao", gaokao_score=700,
                                gaokao_total=750))
    rules = _rules(prof, "imperial-comp-beng-2027")
    assert rules["imp-beng-academic"].status == "UNKNOWN"
    assert "Gaokao" in rules["imp-beng-academic"].detail


def test_ucl_usa_unknown_no_conversion():
    # Even a perfect US record cannot be assessed for UCL: no US
    # equivalence is published for this programme.
    prof = _ug(UndergradProfile(curriculum="usa", sat_total=1550,
                                act_composite=35, ap_grades=[5, 5, 5, 5, 5]))
    rules = _rules(prof, "ucl-cs-bsc-2026")
    assert rules["ucl-academic"].status == "UNKNOWN"
    assert "SAT/ACT/AP" in rules["ucl-academic"].detail
    assert rules["ucl-gcse"].status == "NOT_APPLICABLE"


# --- Imperial USA: the published AP standard supports a verdict -----------

def test_imperial_usa_ap_below_standard_not_met():
    # Three APs 5,5,4 but SAT 1400 (< 1460) and no ACT: neither route met.
    prof = _ug(UndergradProfile(curriculum="usa", sat_total=1400,
                                ap_grades=[5, 5, 4]))
    assert _rules(prof, "imperial-comp-beng-2027")["imp-beng-academic"].status == "NOT_MET"
    # Five APs without the required 5,5,5,4,4 shape: also below.
    prof = _ug(UndergradProfile(curriculum="usa", ap_grades=[5, 5, 5, 4, 3]))
    assert _rules(prof, "imperial-comp-beng-2027")["imp-beng-academic"].status == "NOT_MET"


def test_imperial_usa_ap_standard_met_is_unknown_not_met():
    # Route A: five AP tests 5,5,5,4,4.
    prof = _ug(UndergradProfile(curriculum="usa", ap_grades=[5, 5, 5, 4, 4]))
    rules = _rules(prof, "imperial-comp-beng-2027")
    assert rules["imp-beng-academic"].status == "UNKNOWN"
    assert "general minimum standard" in rules["imp-beng-academic"].detail
    # Route B: three AP tests 5,5,4 with SAT 1500 (>= 1460).
    prof = _ug(UndergradProfile(curriculum="usa", sat_total=1500,
                                ap_grades=[5, 5, 4]))
    assert _rules(prof, "imperial-comp-beng-2027")["imp-beng-academic"].status == "UNKNOWN"
    # Route B with ACT 33 instead of SAT.
    prof = _ug(UndergradProfile(curriculum="usa", act_composite=33,
                                ap_grades=[5, 5, 4]))
    assert _rules(prof, "imperial-comp-beng-2027")["imp-beng-academic"].status == "UNKNOWN"
    # No AP grades at all: missing, never a failure.
    prof = _ug(UndergradProfile(curriculum="usa", sat_total=1500))
    assert _rules(prof, "imperial-comp-beng-2027")["imp-beng-academic"].status == "UNKNOWN"


# --- Singapore A level: evaluated as A level -------------------------------

def test_sg_alevel_verdict_and_no_gcse():
    prof = _ug(UndergradProfile(curriculum="sg_alevel",
                                a_level_grades=["A*", "A*", "A"],
                                a_level_maths_grade="A*"))
    assert _rules(prof, "ucl-cs-bsc-2026")["ucl-academic"].status == "MET"
    assert _rules(prof, "imperial-comp-beng-2027")["imp-beng-academic"].status == "MET"
    # Singapore students take O levels, not GCSEs.
    assert _rules(prof, "ucl-cs-bsc-2026")["ucl-gcse"].status == "NOT_APPLICABLE"
    # Below the offer: a real NOT_MET, same as the UK branch.
    prof = _ug(UndergradProfile(curriculum="sg_alevel",
                                a_level_grades=["A", "A", "B"],
                                a_level_maths_grade="A"))
    assert _rules(prof, "ucl-cs-bsc-2026")["ucl-academic"].status == "NOT_MET"


# --- IB branch unchanged; no-grades is UNKNOWN, never NOT_MET -------------

def test_ib_branch_unchanged():
    prof = _ug(UndergradProfile(curriculum="ib", ib_total=42,
                                ib_hl_maths_grade=7, ib_hl_total=21))
    assert _rules(prof, "ucl-cs-bsc-2026")["ucl-academic"].status == "MET"
    assert _rules(prof, "ucl-cs-bsc-2026")["ucl-gcse"].status == "NOT_APPLICABLE"


def test_uk_alevel_no_grades_is_unknown():
    prof = _ug(UndergradProfile(curriculum="uk_alevel"))
    assert _rules(prof, "ucl-cs-bsc-2026")["ucl-academic"].status == "UNKNOWN"


# --- Adapter: flat wizard profile -> curriculum fields ---------------------

def test_adapter_maps_curriculum_branches():
    gaokao = flat_to_student({"track": "undergraduate", "curriculum": "cn_gaokao",
                              "gaokaoScore": 680, "gaokaoTotal": 750,
                              "gaokaoMaths": 140, "ieltsOverall": 7.0,
                              "budget": 50000, "budgetCurrency": "GBP"})
    ug = gaokao.undergrad_profile
    assert ug.curriculum == "cn_gaokao"
    assert ug.gaokao_score == 680 and ug.gaokao_total == 750
    assert ug.qualification_type == "other"

    usa = flat_to_student({"track": "undergraduate", "curriculum": "usa",
                           "satTotal": 1500, "actComposite": 33,
                           "apGrades": "5,5,5,4,4",
                           "budget": 50000, "budgetCurrency": "GBP"})
    assert usa.undergrad_profile.curriculum == "usa"
    assert usa.undergrad_profile.ap_grades == [5, 5, 5, 4, 4]
    assert usa.undergrad_profile.sat_total == 1500
    assert usa.undergrad_profile.qualification_type == "other"

    sg = flat_to_student({"track": "undergraduate", "curriculum": "sg_alevel",
                          "alevels": "A*A*A", "mathsGrade": "A*",
                          "budget": 50000, "budgetCurrency": "GBP"})
    assert sg.undergrad_profile.curriculum == "sg_alevel"
    assert sg.undergrad_profile.qualification_type == "a_level"

    # Legacy flat profiles without a curriculum keep the old inference.
    legacy = flat_to_student({"track": "undergraduate", "alevels": "A*A*A",
                              "mathsGrade": "A*", "budget": 50000,
                              "budgetCurrency": "GBP"})
    assert legacy.undergrad_profile.curriculum == "uk_alevel"


# --- Flat /match response carries structured values + reason keys ----------

def test_flat_match_gaokao_reason_key_and_observed_raw():
    reset_rate_limits()
    rules = _flat_rules({"track": "undergraduate", "curriculum": "cn_gaokao",
                         "gaokaoScore": 680, "gaokaoTotal": 750,
                         "ieltsOverall": 7.0, "ieltsListening": 6.5,
                         "ieltsReading": 6.5, "ieltsWriting": 6.5,
                         "ieltsSpeaking": 6.5, "budget": 22,
                         "budgetCurrency": "GBP"},
                        "ucl-cs-bsc-2026")
    acad = rules["ucl-academic"]
    assert acad["status"] == "UNKNOWN"
    assert acad["reasonKey"] == "gaokao-no-equivalence"
    assert acad["observedRaw"] == {"curriculum": "cn_gaokao",
                                   "gaokao_score": 680, "gaokao_total": 750,
                                   "gaokao_maths": None}
    assert rules["ucl-gcse"]["status"] == "NOT_APPLICABLE"
    # The fee rule still carries plain numbers for the frontend's
    # localized budget sentence (budget 22 vs fee 48,600).
    fee = rules["ucl-fee"]
    assert fee["status"] == "NOT_MET"
    assert fee["observedRaw"] == 22
    assert fee["thresholdRaw"] == {"gbp_per_year": 48600}
    assert fee["reasonKey"] is None  # NOT_MET needs no reason key


def test_flat_match_usa_ap_reason_keys():
    reset_rate_limits()
    rules = _flat_rules({"track": "undergraduate", "curriculum": "usa",
                         "apGrades": "5,5,5,4,4", "budget": 50000,
                         "budgetCurrency": "GBP"},
                        "imperial-comp-beng-2027")
    assert rules["imp-beng-academic"]["status"] == "UNKNOWN"
    assert rules["imp-beng-academic"]["reasonKey"] == "usa-ap-general-only"
    rules = _flat_rules({"track": "undergraduate", "curriculum": "usa",
                         "apGrades": "5,5,4", "satTotal": 1400,
                         "budget": 50000, "budgetCurrency": "GBP"},
                        "imperial-comp-beng-2027")
    assert rules["imp-beng-academic"]["status"] == "NOT_MET"


def test_flat_match_contextual_reason_key():
    reset_rate_limits()
    rules = _flat_rules({"track": "undergraduate", "curriculum": "uk_alevel",
                         "alevels": "A*AB", "mathsGrade": "A*",
                         "gcseEnglish": "A", "gcseMaths": "A",
                         "ieltsOverall": 7.0, "ieltsListening": 6.5,
                         "ieltsReading": 6.5, "ieltsWriting": 6.5,
                         "ieltsSpeaking": 6.5, "budget": 50000,
                         "budgetCurrency": "GBP"},
                        "ucl-cs-bsc-2026")
    assert rules["ucl-academic"]["status"] == "UNKNOWN"
    assert rules["ucl-academic"]["reasonKey"] == "contextual-offer"


# --- /profile/validate: new field ranges -----------------------------------

def test_validate_new_field_errors():
    reset_rate_limits()
    base = {"application_track": "undergraduate",
            "undergrad_profile": {"curriculum": "cn_gaokao",
                                  "gaokao_score": 800},
            "language": {"exam": "none"}, "budget": None}
    body = client.post("/api/v1/profile/validate", json=base).json()
    assert any(e["field"] == "undergrad_profile.gaokao_score"
               for e in body["field_errors"])
    base["undergrad_profile"] = {"curriculum": "xx"}
    body = client.post("/api/v1/profile/validate", json=base).json()
    assert any(e["field"] == "undergrad_profile.curriculum"
               for e in body["field_errors"])
    base["undergrad_profile"] = {"curriculum": "usa", "sat_total": 1700,
                                 "ap_grades": [6]}
    body = client.post("/api/v1/profile/validate", json=base).json()
    fields = {e["field"] for e in body["field_errors"]}
    assert "undergrad_profile.sat_total" in fields
    assert "undergrad_profile.ap_grades" in fields
