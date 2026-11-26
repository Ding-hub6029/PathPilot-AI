"""Day 2 v2 tests: rule evaluators for the six new programmes.

Uses the nested spec contract (StudentProfile) so the engine is tested
directly, plus API-level checks for the 8-programme catalogue (v2).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.data import PROGRAMS
from app.main import app
from app.schemas import Budget, Language, MastersProfile, StudentProfile, UndergradProfile
from domain.eligibility import evaluate, overall_status

client = TestClient(app)


def _ug(undergrad=None, language=None, budget=None):
    return StudentProfile(application_track="undergraduate",
                          undergrad_profile=undergrad or UndergradProfile(),
                          language=language, budget=budget)


def _pg(masters=None, language=None, budget=None):
    return StudentProfile(application_track="taught_masters",
                          masters_profile=masters or MastersProfile(),
                          language=language, budget=budget)


def _rules(profile, pid):
    return {r.rule_id: r for r in evaluate(profile, PROGRAMS[pid])}


# --- catalogue -------------------------------------------------------------

def test_v2_has_eight_programs():
    assert len(PROGRAMS) == 8
    assert {p for p in PROGRAMS} == {
        "ucl-cs-bsc-2026", "nus-mcomp-cs",
        "imperial-comp-beng-2027", "imperial-msc-computing-2027",
        "ucl-cs-msc-2027", "nus-bcomp-cs-2027",
        "ntu-bcomp-cs-2027", "ntu-msai-2027"}


def test_programs_filter_and_pagination_v2():
    r = client.get("/api/v1/programs?country=SG")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 4
    assert r.json()["data_version"] == "v2"
    r = client.get("/api/v1/programs?limit=3")
    body = r.json()
    assert len(body["items"]) == 3 and body["next_cursor"]
    r2 = client.get(f"/api/v1/programs?limit=3&cursor={body['next_cursor']}")
    assert len(r2.json()["items"]) == 3
    r3 = client.get("/api/v1/programs?degree_level=taught_masters")
    assert len(r3.json()["items"]) == 4


# --- Imperial BEng ---------------------------------------------------------

def test_imp_beng_alevel_met_and_below():
    prof = _ug(UndergradProfile(qualification_type="a_level",
                                 a_level_grades=["A*", "A*", "A"],
                                 a_level_maths_grade="A*"),
               Language(exam="ielts", overall=7.0, listening=6.5, reading=6.5,
                        writing=6.5, speaking=6.5),
               Budget(amount=Decimal("50000"), currency="GBP", period="per_year"))
    rules = _rules(prof, "imperial-comp-beng-2027")
    assert rules["imp-beng-academic"].status == "MET"
    assert rules["imp-beng-language"].status == "MET"
    assert rules["imp-beng-language-components"].status == "MET"
    assert rules["imp-beng-tmua"].status == "UNKNOWN"
    assert rules["imp-beng-fee"].status == "MET"
    prof2 = _ug(UndergradProfile(qualification_type="a_level",
                                  a_level_grades=["A", "A", "B"],
                                  a_level_maths_grade="A"),
                Language(exam="ielts", overall=7.0, listening=6.5, reading=6.5,
                         writing=6.5, speaking=6.5),
                Budget(amount=Decimal("50000"), currency="GBP", period="per_year"))
    assert _rules(prof2, "imperial-comp-beng-2027")["imp-beng-academic"].status == "NOT_MET"


def test_imp_beng_ib_second_hl_unknown_and_fee_uk():
    prof = _ug(UndergradProfile(qualification_type="ib", ib_total=41,
                                 ib_hl_maths_grade=7, ib_hl_total=20),
               Language(exam="ielts", overall=7.0, listening=6.5, reading=6.5,
                        writing=6.5, speaking=6.5),
               Budget(amount=Decimal("11000"), currency="GBP", period="per_year"))
    rules = _rules(prof, "imperial-comp-beng-2027")
    # Second HL grade is not collected: IB can be UNKNOWN at best.
    assert rules["imp-beng-academic"].status == "UNKNOWN"
    assert rules["imp-beng-fee"].status == "NOT_MET"  # overseas assumed, 11,000 < 47,800
    prof_uk = _ug(UndergradProfile(qualification_type="ib", ib_total=41,
                                   ib_hl_maths_grade=7, ib_hl_total=20,
                                   residency="uk"),
                  Language(exam="ielts", overall=7.0, listening=6.5, reading=6.5,
                           writing=6.5, speaking=6.5),
                  Budget(amount=Decimal("11000"), currency="GBP", period="per_year"))
    assert _rules(prof_uk, "imperial-comp-beng-2027")["imp-beng-fee"].status == "MET"


def test_imp_beng_toefl_date_split():
    base = dict(qualification_type="a_level", a_level_grades=["A*", "A*", "A"],
                a_level_maths_grade="A*")
    prof_old = _ug(UndergradProfile(**base),
                   Language(exam="toefl", overall=95, test_date="2026-01-15"),
                   Budget(amount=Decimal("50000"), currency="GBP", period="per_year"))
    assert _rules(prof_old, "imperial-comp-beng-2027")["imp-beng-toefl"].status == "MET"
    prof_new = _ug(UndergradProfile(**base),
                   Language(exam="toefl", overall=4.5, test_date="2026-01-21"),
                   Budget(amount=Decimal("50000"), currency="GBP", period="per_year"))
    assert _rules(prof_new, "imperial-comp-beng-2027")["imp-beng-toefl"].status == "MET"
    prof_nodate = _ug(UndergradProfile(**base),
                      Language(exam="toefl", overall=95),
                      Budget(amount=Decimal("50000"), currency="GBP", period="per_year"))
    assert _rules(prof_nodate, "imperial-comp-beng-2027")["imp-beng-toefl"].status == "UNKNOWN"


# --- Imperial MSc ----------------------------------------------------------

def test_imp_msc_academic_first_class_and_computing_excluded():
    lang = Language(exam="ielts", overall=7.5, listening=7.0, reading=7.0,
                    writing=7.0, speaking=7.0)
    budget = Budget(amount=Decimal("50000"), currency="GBP", period="per_year")
    prof = _pg(MastersProfile(degree_field="related", honours=True,
                              degree_class="first"), lang, budget)
    rules = _rules(prof, "imperial-msc-computing-2027")
    assert rules["imp-msc-academic"].status == "MET"
    assert rules["imp-msc-language"].status == "MET"
    assert rules["imp-msc-test"].status == "NOT_APPLICABLE"
    prof_cs = _pg(MastersProfile(degree_field="computing", honours=True,
                                 degree_class="first"), lang, budget)
    assert _rules(prof_cs, "imperial-msc-computing-2027")["imp-msc-academic"].status == "NOT_MET"
    prof_21 = _pg(MastersProfile(degree_field="related", honours=True,
                                 degree_class="upper_second"), lang, budget)
    assert _rules(prof_21, "imperial-msc-computing-2027")["imp-msc-academic"].status == "NOT_MET"
    prof_bus = _pg(MastersProfile(degree_field="business", honours=True,
                                  degree_class="first", maths_alevel_grade="B"), lang, budget)
    assert _rules(prof_bus, "imperial-msc-computing-2027")["imp-msc-academic"].status == "NOT_MET"
    prof_bus_a = _pg(MastersProfile(degree_field="business", honours=True,
                                    degree_class="first", maths_alevel_grade="A"), lang, budget)
    assert _rules(prof_bus_a, "imperial-msc-computing-2027")["imp-msc-academic"].status == "MET"


# --- UCL MSc ---------------------------------------------------------------

def test_ucl_msc_academic_and_language_unknown():
    lang = Language(exam="ielts", overall=7.5, listening=7.0, reading=7.0,
                    writing=7.0, speaking=7.0)
    budget = Budget(amount=Decimal("50000"), currency="GBP", period="per_year")
    prof = _pg(MastersProfile(degree_field="related", honours=True,
                              degree_class="upper_second", maths_alevel_grade="B"), lang, budget)
    rules = _rules(prof, "ucl-cs-msc-2027")
    assert rules["ucl-msc-academic"].status == "MET"
    # No English level is stated on the course page: language is UNKNOWN.
    assert rules["ucl-msc-language"].status == "UNKNOWN"
    assert rules["ucl-msc-fee"].status == "MET"
    prof_cs = _pg(MastersProfile(degree_field="computing", honours=True,
                                 degree_class="first", maths_alevel_grade="A"), lang, budget)
    assert _rules(prof_cs, "ucl-cs-msc-2027")["ucl-msc-academic"].status == "NOT_MET"
    prof_nomaths = _pg(MastersProfile(degree_field="related", honours=True,
                                      degree_class="upper_second"), lang, budget)
    assert _rules(prof_nomaths, "ucl-cs-msc-2027")["ucl-msc-academic"].status == "UNKNOWN"


# --- NUS BComp -------------------------------------------------------------

def test_nus_bcomp_igp_unknown_and_language():
    prof = _ug(UndergradProfile(qualification_type="a_level",
                                 a_level_grades=["A", "A", "A"],
                                 a_level_maths_grade="A"),
               Language(exam="ielts", overall=7.0, listening=7.0, reading=7.0,
                        writing=7.0, speaking=7.0),
               Budget(amount=Decimal("25000"), currency="SGD", period="per_year"))
    rules = _rules(prof, "nus-bcomp-cs-2027")
    # IGP is not a threshold: academic is UNKNOWN even with AAA.
    assert rules["nus-bcomp-academic"].status == "UNKNOWN"
    assert rules["nus-bcomp-language"].status == "MET"
    assert rules["nus-bcomp-language-components"].status == "MET"
    # No residency supplied: grant status unknown -> fee UNKNOWN.
    assert rules["nus-bcomp-fee"].status == "UNKNOWN"
    prof_sg = _ug(UndergradProfile(qualification_type="a_level",
                                   a_level_grades=["A", "A", "A"],
                                   a_level_maths_grade="A", residency="sg_citizen"),
                  Language(exam="ielts", overall=7.0, listening=7.0, reading=7.0,
                           writing=7.0, speaking=7.0),
                  Budget(amount=Decimal("9000"), currency="SGD", period="per_year"))
    assert _rules(prof_sg, "nus-bcomp-cs-2027")["nus-bcomp-fee"].status == "MET"
    prof_toefl = _ug(UndergradProfile(qualification_type="a_level",
                                      a_level_grades=["A", "A", "A"],
                                      a_level_maths_grade="A"),
                     Language(exam="toefl", overall=95),
                     Budget(amount=Decimal("25000"), currency="SGD", period="per_year"))
    assert _rules(prof_toefl, "nus-bcomp-cs-2027")["nus-bcomp-toefl"].status == "MET"


# --- NTU BComp -------------------------------------------------------------

def test_ntu_bcomp_igp_unknown_language_and_fee_bands():
    prof = _ug(UndergradProfile(qualification_type="a_level",
                                 a_level_grades=["A", "A", "B"],
                                 a_level_maths_grade="A", residency="sg_intl_other"),
               Language(exam="ielts", overall=7.0, listening=7.0, reading=7.0,
                        writing=7.0, speaking=7.0),
               Budget(amount=Decimal("22000"), currency="SGD", period="per_year"))
    rules = _rules(prof, "ntu-bcomp-cs-2027")
    assert rules["ntu-bcomp-academic"].status == "UNKNOWN"
    assert rules["ntu-bcomp-language"].status == "MET"
    assert rules["ntu-bcomp-language-components"].status == "MET"
    assert rules["ntu-bcomp-fee"].status == "MET"
    prof_nogrant = _ug(UndergradProfile(qualification_type="a_level",
                                        a_level_grades=["A", "A", "B"],
                                        a_level_maths_grade="A",
                                        residency="sg_intl_nogrant"),
                       Language(exam="ielts", overall=7.0, listening=7.0, reading=7.0,
                                writing=7.0, speaking=7.0),
                       Budget(amount=Decimal("45000"), currency="SGD", period="per_year"))
    # Non-subsidised band is not labelled for CS: fee stays UNKNOWN.
    assert _rules(prof_nogrant, "ntu-bcomp-cs-2027")["ntu-bcomp-fee"].status == "UNKNOWN"


# --- SG multi-band fees, round 10 (R1) --------------------------------------
def test_sg_bcomp_fees_overseas_gbp_budget_fx():
    """Audit profile (Gaokao, residency 'overseas', budget GBP 50,000):
    the generic 'overseas' residency maps to the unsubsidised
    international band, compared across currencies with the dated FX
    table — never UNKNOWN + 'budget does not match'."""
    lang = Language(exam="ielts", overall=7.0, listening=7.0, reading=7.0,
                    writing=6.5, speaking=7.0)
    prof = _ug(UndergradProfile(qualification_type="cn_gaokao",
                                 gaokao_score=680, gaokao_total=750,
                                 residency="overseas"),
               lang, Budget(amount=Decimal("50000"), currency="GBP", period="per_year"))
    # NUS without-grant band S$39,700 ≈ GBP 23,491 (1 GBP = 1.69 SGD,
    # 2026-11-26) — well under a GBP 50,000 budget.
    nus = _rules(prof, "nus-bcomp-cs-2027")["nus-bcomp-fee"]
    assert nus.status == "MET"
    assert "does not match" not in nus.detail
    assert nus.threshold["approx_converted"]["amount"] == 23491
    assert nus.threshold["approx_converted"]["currency"] == "GBP"
    # NTU: the non-subsidised band is not labelled for CS (lab-based
    # S$40,600 vs non-lab-based S$36,350), so the fee stays UNKNOWN —
    # with the lab-band reason, never a mismatch claim.
    ntu = _rules(prof, "ntu-bcomp-cs-2027")["ntu-bcomp-fee"]
    assert ntu.status == "UNKNOWN"
    assert "does not match" not in ntu.detail
    assert "lab-based" in ntu.detail
    # A budget below the converted fee is a real NOT_MET, not UNKNOWN.
    prof_low = _ug(UndergradProfile(qualification_type="cn_gaokao",
                                     gaokao_score=680, gaokao_total=750,
                                     residency="overseas"),
                   lang, Budget(amount=Decimal("10000"), currency="GBP", period="per_year"))
    assert _rules(prof_low, "nus-bcomp-cs-2027")["nus-bcomp-fee"].status == "NOT_MET"
    # A budget currency with no reference rate is UNKNOWN ("cannot be
    # converted"), never a mismatch.
    prof_thb = _ug(UndergradProfile(qualification_type="cn_gaokao",
                                     gaokao_score=680, gaokao_total=750,
                                     residency="overseas"),
                   lang, Budget(amount=Decimal("800000"), currency="THB", period="per_year"))
    thb = _rules(prof_thb, "nus-bcomp-cs-2027")["nus-bcomp-fee"]
    assert thb.status == "UNKNOWN"
    assert "cannot be converted" in thb.detail
    assert "does not match" not in thb.detail


def test_sg_bcomp_fee_no_rate_reason_key_fx_cannot_convert():
    """Round 10 (O1): the v2 adapter maps a 'cannot be converted' fee
    detail to reasonKey 'fx-cannot-convert' (same as the exp- branch),
    so the frontend renders the localised FX wording, not 'missing-info'."""
    from app.adapter import rule_to_frontend
    lang = Language(exam="ielts", overall=7.0, listening=7.0, reading=7.0,
                    writing=6.5, speaking=7.0)
    prof_thb = _ug(UndergradProfile(qualification_type="cn_gaokao",
                                     gaokao_score=680, gaokao_total=750,
                                     residency="overseas"),
                   lang, Budget(amount=Decimal("800000"), currency="THB", period="per_year"))
    thb = _rules(prof_thb, "nus-bcomp-cs-2027")["nus-bcomp-fee"]
    assert thb.status == "UNKNOWN"
    assert rule_to_frontend(thb)["reasonKey"] == "fx-cannot-convert"


def test_ntu_bcomp_fee_reason_key_band_unlabelled():
    """Round 11, F4: for the audit profile (residency 'overseas') the
    NTU fee is UNKNOWN because the official table does not label the
    CS lab/non-lab band — the reason key must say so, never
    'fee-residency-unknown' (which claims the residency was not
    provided). A profile with no residency at all still maps to
    'fee-residency-unknown'."""
    from app.adapter import rule_to_frontend
    lang = Language(exam="ielts", overall=7.0, listening=7.0, reading=7.0,
                    writing=6.5, speaking=7.0)
    prof = _ug(UndergradProfile(qualification_type="cn_gaokao",
                                 gaokao_score=680, gaokao_total=750,
                                 residency="overseas"),
               lang, Budget(amount=Decimal("50000"), currency="GBP", period="per_year"))
    ntu = _rules(prof, "ntu-bcomp-cs-2027")["ntu-bcomp-fee"]
    assert ntu.status == "UNKNOWN"
    assert "lab-based" in ntu.detail
    assert rule_to_frontend(ntu)["reasonKey"] == "fee-band-unlabelled"
    # No residency supplied: the old key is still correct there.
    prof_nores = _ug(UndergradProfile(qualification_type="cn_gaokao",
                                       gaokao_score=680, gaokao_total=750),
                     lang, Budget(amount=Decimal("50000"), currency="GBP", period="per_year"))
    nores = _rules(prof_nores, "ntu-bcomp-cs-2027")["ntu-bcomp-fee"]
    assert nores.status == "UNKNOWN"
    assert rule_to_frontend(nores)["reasonKey"] == "fee-residency-unknown"


# --- NTU MSAI --------------------------------------------------------------
def test_ntu_msai_academic_language_gre_fee():
    lang = Language(exam="ielts", overall=7.0)
    budget = Budget(amount=Decimal("70000"), currency="SGD", period="total")
    prof = _pg(MastersProfile(degree_field="computing", honours=True), lang, budget)
    rules = _rules(prof, "ntu-msai-2027")
    assert rules["ntu-msai-academic"].status == "MET"
    assert rules["ntu-msai-language"].status == "MET"
    assert rules["ntu-msai-language-components"].status == "NOT_APPLICABLE"
    assert rules["ntu-msai-gre"].status == "UNKNOWN"
    assert rules["ntu-msai-fee"].status == "MET"
    prof_bach = _pg(MastersProfile(degree_field="related", honours=False,
                                   it_experience_years=3), lang, budget)
    assert _rules(prof_bach, "ntu-msai-2027")["ntu-msai-academic"].status == "MET"
    prof_toefl = _pg(MastersProfile(degree_field="computing", honours=True),
                     Language(exam="toefl", overall=105, test_date="2026-02-01"),
                     budget)
    rules2 = _rules(prof_toefl, "ntu-msai-2027")
    assert rules2["ntu-msai-language"].status == "MET"
    prof_low = _pg(MastersProfile(degree_field="computing", honours=True),
                   Language(exam="ielts", overall=6.0), budget)
    assert _rules(prof_low, "ntu-msai-2027")["ntu-msai-language"].status == "NOT_MET"


# --- API end-to-end for a new programme ------------------------------------

def test_match_api_new_programme_flat():
    r = client.post("/api/v1/match", json={
        "profile": {"track": "undergraduate", "targetProgramIds": ["imperial-comp-beng-2027"],
                    "alevels": "A*A*A", "mathsGrade": "A*",
                    "ieltsOverall": 7.0, "ieltsListening": 6.5, "ieltsReading": 6.5,
                    "ieltsWriting": 6.5, "ieltsSpeaking": 6.5,
                    "budget": 50000, "budgetCurrency": "GBP"},
        "program_ids": ["imperial-comp-beng-2027"]})
    assert r.status_code == 200, r.text
    rules = {x["ruleId"]: x for x in r.json()["results"][0]["ruleResults"]}
    assert rules["imp-beng-academic"]["status"] == "MET"
    assert rules["imp-beng-tmua"]["status"] == "UNKNOWN"
    # Every rule result must carry evidence ids the drawer can resolve.
    assert all(x["evidenceIds"] for x in rules.values())


def test_match_api_all_eight_programmes_have_evidence():
    r = client.get("/api/v1/programs?limit=20")
    ids = [p["id"] for p in r.json()["items"]]
    assert len(ids) == 8
    for pid in ids:
        r = client.get(f"/api/v1/programs/{pid}")
        assert r.status_code == 200, pid
        assert r.json()["sources"], pid
