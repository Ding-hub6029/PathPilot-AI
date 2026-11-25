"""Tests for the Day-3 round-6 generic expansion evaluator + climate fit.

Covers: the generic evaluator (fee / language / academic, including the
UNKNOWN cases), the promotion counts as literals, the climate table and
fit rule, /match with expansion programme ids, and the v2 byte-identical
guarantee (no preferenceFit key and no changed rule results when no
climate preference is set).

Run from the project root:
    .venv/bin/python -m pytest tests/test_expansion_generic.py -q
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.data import (CLIMATE, EXPANSION_INSTITUTIONS, EXPANSION_MATCHABLE,
                      EXPANSION_PROGRAMS, PROGRAMS)
from app.main import app, reset_rate_limits
from domain.climate import climate_fit, resolve_city_climate
from domain.expansion_eval import evaluable_rules, evaluate_expansion
from app.schemas import (Budget, Language, StudentProfile, UndergradProfile,
                         MastersProfile)

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    reset_rate_limits()


# --- Profile builders ---------------------------------------------------------

def _ug(grades=None, maths=None, curriculum="uk_alevel", ielts=None,
        toefl=None, test_date=None, budget=None, budget_currency="GBP",
        budget_period="per_year"):
    lang = None
    if ielts is not None:
        lang = Language(exam="ielts", overall=ielts[0],
                        listening=ielts[1], reading=ielts[1],
                        writing=ielts[1], speaking=ielts[1],
                        test_date=test_date)
    elif toefl is not None:
        lang = Language(exam="toefl", overall=toefl, test_date=test_date)
    return StudentProfile(
        application_track="undergraduate",
        undergrad_profile=UndergradProfile(
            qualification_type="a_level" if curriculum in
            ("uk_alevel", "sg_alevel") else "other",
            curriculum=curriculum,
            a_level_grades=grades, a_level_maths_grade=maths,
            residency="overseas", intake_year=2027,
            graduation_status="final"),
        language=lang,
        budget=(Budget(amount=budget, currency=budget_currency,
                       period=budget_period) if budget is not None else None))


def _tm(ielts=None, toefl=None, test_date=None, budget=None,
        budget_currency="GBP", budget_period="per_year"):
    lang = None
    if ielts is not None:
        lang = Language(exam="ielts", overall=ielts[0],
                        listening=ielts[1], reading=ielts[1],
                        writing=ielts[1], speaking=ielts[1],
                        test_date=test_date)
    elif toefl is not None:
        lang = Language(exam="toefl", overall=toefl, test_date=test_date)
    return StudentProfile(
        application_track="taught_masters",
        masters_profile=MastersProfile(
            degree_subject="computer science",
            degree_class="first_class", residency="overseas",
            intake_year=2027),
        language=lang,
        budget=(Budget(amount=budget, currency=budget_currency,
                       period=budget_period) if budget is not None else None))


def _rules(pid, profile):
    ev = evaluate_expansion(profile, EXPANSION_PROGRAMS[pid])
    return {r.rule_id: r for r in ev}


# --- Fee ----------------------------------------------------------------------

def test_fee_met_and_not_met():
    # Glasgow CS BSc: GBP 33,708 per year (verified).
    p = EXPANSION_PROGRAMS["glasgow-cs-bsc-2027"]
    assert _rules("glasgow-cs-bsc-2027",
                  _ug(budget=40000)).get("exp-fee").status == "MET"
    assert _rules("glasgow-cs-bsc-2027",
                  _ug(budget=30000)).get("exp-fee").status == "NOT_MET"


def test_fee_unknown_no_amount():
    # UCSD CS BS states no fee amount.
    r = _rules("ucsd-cs-bs-2027", _ug(budget=90000,
                                      budget_currency="USD"))
    assert r["exp-fee"].status == "UNKNOWN"
    assert "No tuition fee amount" in r["exp-fee"].detail


def test_fee_unknown_currency_period_mismatch():
    # Never FX-convert: a USD budget against a GBP fee is UNKNOWN.
    r = _rules("glasgow-cs-bsc-2027",
               _ug(budget=40000, budget_currency="USD"))
    assert r["exp-fee"].status == "UNKNOWN"
    assert "does not match" in r["exp-fee"].detail


def test_fee_unknown_per_credit():
    # HK PolyU IT MSc is HKD 9,500 per credit: no credit count exists.
    r = _rules("hkpolyu-it-msc-2027",
               _tm(budget=200000, budget_currency="HKD"))
    assert r["exp-fee"].status == "UNKNOWN"
    assert "per credit" in r["exp-fee"].detail


def test_fee_unknown_no_budget():
    r = _rules("glasgow-cs-bsc-2027", _ug())
    assert r["exp-fee"].status == "UNKNOWN"


# --- Language -----------------------------------------------------------------

def test_language_ielts_met_and_not_met():
    # Glasgow CS BSc: IELTS 6.5 overall, 6.0 each component.
    r = _rules("glasgow-cs-bsc-2027", _ug(ielts=(7.0, 6.5)))
    assert r["exp-language"].status == "MET"
    assert r["exp-language-components"].status == "MET"
    r = _rules("glasgow-cs-bsc-2027", _ug(ielts=(6.0, 6.0)))
    assert r["exp-language"].status == "NOT_MET"


def test_language_alternative_routes():
    # UCSD CS BS: IELTS 7.0 / TOEFL 83 / Duolingo 115 are alternatives.
    # A TOEFL 90 (dated before the Jan 2026 scale split) meets it.
    r = _rules("ucsd-cs-bs-2027",
               _ug(toefl=90, test_date="2025-06-01"))
    assert r["exp-language"].status == "MET"
    r = _rules("ucsd-cs-bs-2027",
               _ug(toefl=80, test_date="2025-06-01"))
    assert r["exp-language"].status == "NOT_MET"


def test_language_toefl_missing_date_unknown():
    # A TOEFL score of 6 or below cannot be placed on the pre/post-Jan
    # 2026 scale against an old-scale iBT minimum: UNKNOWN, never a
    # failure and never converted. (A score above 6 is unambiguously
    # old-scale iBT, so TOEFL 90 with no date is MET — same as v2.)
    r = _rules("ucsd-cs-bs-2027", _ug(toefl=5))
    assert r["exp-language"].status == "UNKNOWN"
    r = _rules("ucsd-cs-bs-2027", _ug(toefl=90))
    assert r["exp-language"].status == "MET"


def test_language_no_matching_route_unknown():
    # IELTS-only profile against a TOEFL-only threshold is UNKNOWN,
    # never NOT_MET: the applicant may hold the other test.
    # UCLA CS BS states TOEFL 100 only.
    r = _rules("ucla-cs-bs-2027", _ug(ielts=(8.0, 7.5)))
    assert r["exp-language"].status == "UNKNOWN"


def test_language_duolingo_only_unknown():
    # Peking CS BSc states HSK 6 only: no IELTS/TOEFL threshold exists,
    # so a language score cannot be assessed.
    r = _rules("peking-cs-bsc-2027", _ug(ielts=(8.0, 7.5)))
    assert r["exp-language"].status == "UNKNOWN"


def test_language_components_three_of_four_and_not_applicable():
    # Edinburgh Data Science MSc: IELTS 7.0 overall, 6.5 in at least
    # three components and 6.0 in the remaining one.
    r = _rules("edinburgh-ds-msc-2027", _tm(ielts=(7.0, 6.5)))
    assert r["exp-language"].status == "MET"
    assert r["exp-language-components"].status == "MET"
    r = _rules("edinburgh-ds-msc-2027", _tm(ielts=(7.0, 6.0)))
    assert r["exp-language-components"].status == "NOT_MET"
    # Harvard CSE S.M. states an IELTS overall only, no component
    # minimum: the components rule is NOT_APPLICABLE when a test is
    # supplied.
    r = _rules("harvard-cse-sm-2027", _tm(ielts=(7.0, 6.5)))
    assert r["exp-language"].status == "MET"
    assert r["exp-language-components"].status == "NOT_APPLICABLE"


# --- Academic -----------------------------------------------------------------

def test_academic_alevel_string_form():
    # Oxford CS BA: A*AA.
    r = _rules("oxford-cs-ba-2027",
               _ug(grades=["A*", "A", "A"], maths="A*"))
    assert r["exp-academic"].status == "MET"
    r = _rules("oxford-cs-ba-2027",
               _ug(grades=["A", "A", "A"], maths="A"))
    assert r["exp-academic"].status == "NOT_MET"


def test_academic_alevel_grades_form_with_maths():
    # Glasgow CS BSc grades form: AAA + maths A.
    r = _rules("glasgow-cs-bsc-2027",
               _ug(grades=["A", "A", "A"], maths="A"))
    assert r["exp-academic"].status == "MET"
    r = _rules("glasgow-cs-bsc-2027",
               _ug(grades=["A", "A", "B"], maths="A"))
    assert r["exp-academic"].status == "NOT_MET"
    r = _rules("glasgow-cs-bsc-2027",
               _ug(grades=["A", "A", "A"], maths="B"))
    assert r["exp-academic"].status == "NOT_MET"


def test_academic_non_alevel_curriculum_unknown():
    # Gaokao / IB / SAT scores are never converted to A-levels.
    r = _rules("oxford-cs-ba-2027", _ug(curriculum="cn_gaokao"))
    assert r["exp-academic"].status == "UNKNOWN"
    assert "never converted" in r["exp-academic"].detail


def test_academic_taught_masters_unknown():
    # A-level thresholds say nothing about taught-masters applicants:
    # the Oxford MSc has an academic requirement (First-class degree),
    # but no A-level threshold, so its academic rule is UNKNOWN.
    r = _rules("oxford-msc-adv-cs-2027", _tm(ielts=(7.5, 7.0)))
    assert r["exp-academic"].status == "UNKNOWN"


def test_academic_no_threshold_unknown():
    # MIT CS SB states no A-level threshold: academic is UNKNOWN.
    r = _rules("mit-cs-sb-2027", _ug(grades=["A*", "A*", "A*"], maths="A*"))
    assert r["exp-academic"].status == "UNKNOWN"


# --- Promotion counts (literals) ----------------------------------------------

def test_promotion_counts():
    promoted = [p for p in EXPANSION_PROGRAMS.values()
                if p["matchable"] is True]
    display = [p for p in EXPANSION_PROGRAMS.values()
               if p["matchable"] is not True]
    assert len(promoted) == 588
    assert len(display) == 293
    # By degree level.
    assert sum(1 for p in promoted
               if p["degree_level"] == "undergraduate") == 360
    assert sum(1 for p in promoted
               if p["degree_level"] == "taught_masters") == 228
    # By evaluable rule.
    assert sum(1 for p in EXPANSION_PROGRAMS.values()
               if evaluable_rules(p)["fee"]) == 553
    assert sum(1 for p in EXPANSION_PROGRAMS.values()
               if evaluable_rules(p)["language"]) == 119
    assert sum(1 for p in EXPANSION_PROGRAMS.values()
               if evaluable_rules(p)["academic"]) == 20
    # Display-only reasons: 244 UG/TM with no evaluable rule, 39
    # joint_honours/foundation without one, 10 with a rule but no
    # wizard track.
    no_rule = [p for p in display if not any(evaluable_rules(p).values())]
    assert len(no_rule) == 283
    with_rule_no_track = [p for p in display
                          if any(evaluable_rules(p).values())]
    assert len(with_rule_no_track) == 10
    assert {p["id"] for p in with_rule_no_track} == {
        "ucl-upc-foundation-2027", "oxford-astrophoria-foundation-2027",
        "cambridge-foundation-year-2027", "edinburgh-ifp-foundation-2027",
        "bristol-ifp-arts-foundation-2027",
        "bristol-ifp-stem-foundation-2027",
        "warwick-ifp-foundation-2027", "leeds-ify-arts-foundation-2027",
        "leeds-ify-science-foundation-2027",
        "nottingham-history-politics-ba-2027"}
    assert all(p["degree_level"] in ("foundation", "joint_honours")
               for p in with_rule_no_track)


def test_promoted_programmes_have_evaluable_rule_and_track():
    for p in EXPANSION_PROGRAMS.values():
        if p["matchable"] is True:
            assert p["degree_level"] in ("undergraduate", "taught_masters")
            assert any(evaluable_rules(p).values())


# --- Climate ------------------------------------------------------------------

def test_climate_table_covers_all_cities():
    cities = {p["city"] for p in EXPANSION_PROGRAMS.values()}
    assert cities <= set(CLIMATE.keys())
    assert len(CLIMATE) == 80
    classes = {e["climate"] for e in CLIMATE.values()}
    assert classes == {"warm", "cool", "four_seasons", "mild"}
    assert all(e["source_url"].startswith("https://")
               for e in CLIMATE.values())


def test_climate_fit_singapore_cool_conflict():
    assert climate_fit("cool", resolve_city_climate(
        {"city": "Singapore"}, CLIMATE, {})) == "conflict"
    assert climate_fit("warm", resolve_city_climate(
        {"city": "Singapore"}, CLIMATE, {})) == "fit"
    assert climate_fit("four_seasons", resolve_city_climate(
        {"city": "Singapore"}, CLIMATE, {})) == "conflict"


def test_climate_fit_london_mild_fit():
    assert climate_fit("mild", resolve_city_climate(
        {"city": "London"}, CLIMATE, {})) == "fit"
    assert climate_fit("cool", resolve_city_climate(
        {"city": "London"}, CLIMATE, {})) == "neutral"


def test_climate_fit_unknown_city_no_signal():
    assert resolve_city_climate({"city": "Reykjavik"}, CLIMATE, {}) is None
    assert climate_fit("cool", None) is None


def test_climate_fit_v2_cities():
    # v2 cities resolve through the same table (London Bloomsbury is a
    # prefix of London; SG programmes resolve via their institution).
    assert resolve_city_climate({"city": "London Bloomsbury"}, CLIMATE, {}) \
        == "mild"
    assert resolve_city_climate({"city": "London South Kensington"},
                                CLIMATE, {}) == "mild"
    from app.data import V2_PROGRAM_INSTITUTION
    assert resolve_city_climate({"id": "nus-bcomp-cs-2027"}, CLIMATE, {},
                                V2_PROGRAM_INSTITUTION) == "warm"


# --- /match with expansion ids -------------------------------------------------

def _flat_ug(**overrides):
    base = {"track": "undergraduate", "curriculum": "uk_alevel",
            "alevels": "A*AA", "mathsGrade": "A*",
            "ieltsOverall": 7.0, "ieltsListening": 6.5, "ieltsReading": 6.5,
            "ieltsWriting": 6.5, "ieltsSpeaking": 6.5,
            "budget": 40000, "budgetCurrency": "GBP"}
    base.update(overrides)
    return base


def test_match_expansion_programme_evaluated():
    resp = client.post("/api/v1/match", json={
        "profile": _flat_ug(),
        "program_ids": ["glasgow-cs-bsc-2027", "oxford-cs-ba-2027"]})
    assert resp.status_code == 200, resp.text
    results = {r["programId"]: r for r in resp.json()["results"]}
    glasgow = results["glasgow-cs-bsc-2027"]
    assert glasgow["eligibilitySummary"] == "MET"
    assert {r["ruleId"] for r in glasgow["ruleResults"]} == {
        "exp-fee", "exp-language", "exp-language-components", "exp-academic"}
    assert all(r["status"] == "MET" for r in glasgow["ruleResults"])
    # Oxford CS BA (GBP 66,580/yr; IELTS 7.5/7.0) is NOT_MET for this
    # profile (GBP 40,000 budget, IELTS 7.0/6.5) — but its A-level rule
    # (A*AA) is MET.
    oxford = results["oxford-cs-ba-2027"]
    assert oxford["eligibilitySummary"] == "NOT_MET"
    by_rule = {r["ruleId"]: r["status"] for r in oxford["ruleResults"]}
    assert by_rule == {"exp-fee": "NOT_MET", "exp-language": "NOT_MET",
                       "exp-language-components": "NOT_MET",
                       "exp-academic": "MET"}


def test_match_display_only_expansion_404():
    resp = client.post("/api/v1/match", json={
        "profile": _flat_ug(),
        "program_ids": ["ucl-upc-foundation-2027"]})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PROGRAM_NOT_FOUND"


def test_match_expansion_no_climate_no_preference_fit_key():
    # Byte-identical guarantee: with no climate preference, no result
    # carries a preferenceFit key.
    resp = client.post("/api/v1/match", json={
        "profile": _flat_ug(),
        "program_ids": ["glasgow-cs-bsc-2027", "ucl-cs-bsc-2026"]})
    assert resp.status_code == 200, resp.text
    assert all("preferenceFit" not in r for r in resp.json()["results"])


def test_match_expansion_climate_preference_fit():
    # A cool-climate profile: Singapore programmes conflict (v2 NUS via
    # its institution city, expansion NTU directly), Glasgow (mild) is
    # neutral, Edinburgh (cool) fits.
    resp = client.post("/api/v1/match", json={
        "profile": _flat_ug(prefClimate="cool"),
        "program_ids": ["nus-bcomp-cs-2027", "ntu-dsai-bsc-2027",
                        "glasgow-cs-bsc-2027", "edinburgh-cs-bsc-2027"]})
    assert resp.status_code == 200, resp.text
    fits = {r["programId"]: r.get("preferenceFit")
            for r in resp.json()["results"]}
    assert fits["nus-bcomp-cs-2027"] == "conflict"
    assert fits["ntu-dsai-bsc-2027"] == "conflict"
    assert fits["glasgow-cs-bsc-2027"] == "neutral"
    assert fits["edinburgh-cs-bsc-2027"] == "fit"


def test_match_expansion_track_mismatch():
    resp = client.post("/api/v1/match", json={
        "profile": _flat_ug(),
        "program_ids": ["oxford-msc-adv-cs-2027"]})
    assert resp.status_code == 200, resp.text
    r = resp.json()["results"][0]
    assert r["eligibilitySummary"] == "TRACK_MISMATCH"


def test_programs_catalogue_all_reports_real_flags():
    items, cursor = [], None
    for _ in range(100):
        params = {"catalogue": "all"}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/api/v1/programs", params=params).json()
        items.extend(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    exp = [p for p in items if p["catalogue"] == "expansion"]
    assert len(exp) == 881
    assert sum(1 for p in exp if p["matchable"] is True) == 588
    assert sum(1 for p in exp if p["matchable"] is False) == 293


def test_programs_detail_serves_expansion():
    resp = client.get("/api/v1/programs/oxford-msc-adv-cs-2027")
    assert resp.status_code == 200
    assert resp.json()["matchable"] is True
    resp = client.get("/api/v1/programs/ucl-upc-foundation-2027")
    assert resp.status_code == 200
    assert resp.json()["matchable"] is False
    assert client.get("/api/v1/programs/no-such-program").status_code == 404
