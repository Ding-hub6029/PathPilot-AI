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
    assert len(promoted) == 593
    assert len(display) == 293
    # By degree level.
    assert sum(1 for p in promoted
               if p["degree_level"] == "undergraduate") == 365
    assert sum(1 for p in promoted
               if p["degree_level"] == "taught_masters") == 228
    # By evaluable rule.
    assert sum(1 for p in EXPANSION_PROGRAMS.values()
               if evaluable_rules(p)["fee"]) == 558
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
    assert len(exp) == 886
    assert sum(1 for p in exp if p["matchable"] is True) == 593
    assert sum(1 for p in exp if p["matchable"] is False) == 293


def test_programs_detail_serves_expansion():
    resp = client.get("/api/v1/programs/oxford-msc-adv-cs-2027")
    assert resp.status_code == 200
    assert resp.json()["matchable"] is True
    resp = client.get("/api/v1/programs/ucl-upc-foundation-2027")
    assert resp.status_code == 200
    assert resp.json()["matchable"] is False
    assert client.get("/api/v1/programs/no-such-program").status_code == 404


# --- Round 8: placeholder requirements are UNKNOWN, never NOT_MET -----------

def _placeholder_program(**overrides):
    """Oxford/Cambridge-shaped programme whose requirements carry no
    parseable numeric threshold: threshold missing, a string, or a
    dict of non-numeric values — the '... as stated on the official
    programme page' shape the audit caught being judged NOT_MET."""
    prog = {
        "id": "oxbridge-placeholder-2027",
        "fees": {"amount": None, "currency": "GBP", "period": "per_year"},
        "requirements": [
            {"id": "placeholder-language", "category": "language",
             "description": "IELTS / TOEFL minimum as stated on the "
                            "official programme page",
             "threshold": None, "source_ids": ["ox-english"]},
            {"id": "placeholder-academic", "category": "academic",
             "description": "A-level threshold as stated on the official "
                            "programme page",
             "threshold": {"note": "A*AA or equivalent, as stated on the "
                                   "official programme page"},
             "source_ids": ["ox-entry"]},
        ],
    }
    prog.update(overrides)
    return prog


def test_placeholder_language_is_unknown_not_not_met():
    # IELTS 7.0 supplied — below Oxford's real 7.5, but this programme
    # states NO numeric threshold, so the language rule must be UNKNOWN.
    prof = _ug(ielts=(7.0, 6.5), budget=100000)
    rules = {r.rule_id: r for r in
             evaluate_expansion(prof, _placeholder_program())}
    assert rules["exp-language"].status == "UNKNOWN"
    assert rules["exp-academic"].status == "UNKNOWN"
    assert rules["exp-fee"].status == "UNKNOWN"
    assert not any(r.status == "NOT_MET" for r in rules.values())


def test_placeholder_string_threshold_is_unknown():
    # Threshold dict whose values are strings ("7.5") parses to nothing.
    prog = _placeholder_program(requirements=[
        {"id": "placeholder-language", "category": "language",
         "description": "IELTS / TOEFL minimum as stated on the official "
                        "programme page",
         "threshold": {"ielts_overall": "7.5", "ielts_min_each": "7.0"},
         "source_ids": ["ox-english"]},
    ])
    prof = _ug(ielts=(7.0, 6.5), budget=100000)
    rules = {r.rule_id: r for r in evaluate_expansion(prof, prog)}
    assert rules["exp-language"].status == "UNKNOWN"
    # No component minimum is stated either: NOT_APPLICABLE, never a fail.
    assert rules["exp-language-components"].status == "NOT_APPLICABLE"
    assert not any(r.status == "NOT_MET" for r in rules.values())


def test_placeholder_string_fee_is_unknown():
    prog = _placeholder_program(
        fees={"amount": "as stated on the official programme page",
              "currency": "GBP", "period": "per_year"},
        requirements=[])
    prof = _ug(ielts=(8.0, 8.0), budget=1)
    rules = {r.rule_id: r for r in evaluate_expansion(prof, prog)}
    assert rules["exp-fee"].status == "UNKNOWN"


def test_real_oxford_threshold_still_fails():
    # Control: the guard must not swallow a genuine failure. Oxford CS
    # BA states IELTS 7.5 overall / 7.0 each and GBP 66,580/yr; IELTS
    # 7.0 with a GBP 50,000 budget is a real NOT_MET on both rules.
    prof = _ug(ielts=(7.0, 6.5), budget=50000)
    rules = {r.rule_id: r for r in
             evaluate_expansion(prof, EXPANSION_PROGRAMS["oxford-cs-ba-2027"])}
    assert rules["exp-language"].status == "NOT_MET"
    assert rules["exp-fee"].status == "NOT_MET"
    assert rules["exp-language-components"].status == "NOT_MET"


def test_no_not_met_without_numeric_threshold_anywhere():
    # Property: across every matchable programme and a battery of
    # profiles, no NOT_MET may rest on a placeholder requirement.
    from domain.expansion_eval import (_alevel_requirements,
                                       _language_thresholds)

    def has_threshold(p, rule_id):
        if rule_id == "exp-fee":
            amount = (p.get("fees") or {}).get("amount")
            return isinstance(amount, (int, float)) and not isinstance(amount, bool)
        th = _language_thresholds(p)
        if rule_id == "exp-language":
            return bool(th["ielts_overalls"] or th["toefl_overalls"])
        if rule_id == "exp-language-components":
            return bool(th["component_sets"])
        if rule_id == "exp-academic":
            return bool(_alevel_requirements(p))
        return True

    profiles = [
        _ug(ielts=(7.0, 6.5), budget=50000),
        _ug(ielts=(5.0, 5.0), budget=100000),
        _ug(toefl=92, test_date="2025-06-01", budget=20000,
            budget_currency="USD"),
        _ug(toefl=4.5, test_date="2026-03-01", budget=20000,
            budget_currency="USD"),
        _ug(grades=["A*", "A", "A"], maths="A*", ielts=(8.0, 8.0),
            budget=100000),
        _tm(ielts=(6.0, 6.0), budget=60000, budget_currency="SGD",
            budget_period="total"),
        _ug(budget=50000),  # no language test supplied
    ]
    violations = []
    for prof in profiles:
        for pid, prog in EXPANSION_MATCHABLE.items():
            for r in evaluate_expansion(prof, prog):
                if r.status == "NOT_MET" and not has_threshold(prog, r.rule_id):
                    violations.append((pid, r.rule_id))
    assert violations == []


def test_exp_expected_shows_the_real_threshold():
    # A NOT_MET card must show the number it was judged against, not
    # the generic placeholder-like label.
    from app.adapter import rule_to_frontend
    # A-level grades below the threshold, so every rule carries the
    # threshold it was judged against.
    prof = _ug(grades=["A", "A", "B"], maths="A", ielts=(7.0, 6.5),
            budget=50000)
    rules = evaluate_expansion(prof, EXPANSION_PROGRAMS["oxford-cs-ba-2027"])
    shown = {r.rule_id: rule_to_frontend(r)["expected"] for r in rules}
    assert shown["exp-language"] == "IELTS overall 7.5"
    assert shown["exp-language-components"] == "IELTS minimum 7 in each component"
    assert shown["exp-fee"] == "Tuition fee GBP 66580 per_year"
    assert shown["exp-academic"] == "A-level A*AA"
    # ... while a programme with genuinely no numeric threshold keeps
    # the generic label — and its rule is UNKNOWN, never NOT_MET.
    rules = evaluate_expansion(prof, _placeholder_program())
    shown = {r.rule_id: rule_to_frontend(r)["expected"] for r in rules}
    assert shown["exp-language"] == ("IELTS / TOEFL minimum as stated on "
                                     "the official programme page")
    assert shown["exp-fee"] == ("Tuition fee as stated on the official "
                                "programme page")


# --- Round 8: multi-programme /match makes no model calls -------------------

class _CountingProvider:
    """Stand-in provider that counts chat calls and always returns a
    payload that fails validation (so the explain path would spend a
    first call + a repair call if it ran at all)."""
    calls = 0

    def __init__(self, **kwargs):
        pass

    @property
    def available(self):
        return True

    @property
    def ai_status(self):
        return "available"

    def chat(self, messages, *, system=None, timeout_s=None,
             max_tokens=None, temperature=0.2):
        type(self).calls += 1

        class _R:
            text = '{"lines": ["not a valid explanation"]}'
        return _R()


def test_match_multi_programme_makes_no_model_calls(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "ProviderAdapter", _CountingProvider)
    _CountingProvider.calls = 0
    resp = client.post("/api/v1/match", json={
        "profile": _flat_ug(),
        "program_ids": ["glasgow-cs-bsc-2027", "oxford-cs-ba-2027",
                        "edinburgh-cs-bsc-2027", "ucl-cs-bsc-2026"]})
    assert resp.status_code == 200, resp.text
    assert _CountingProvider.calls == 0
    results = {r["programId"]: r for r in resp.json()["results"]}
    assert results["oxford-cs-ba-2027"]["eligibilitySummary"] == "NOT_MET"
    assert results["glasgow-cs-bsc-2027"]["eligibilitySummary"] == "MET"
    # No per-programme explanation/ai_status keys in the multi shape:
    # the frontend never reads them (MatchResult carries neither).
    assert all("explanation" not in r and "ai_status" not in r
               for r in resp.json()["results"])


def test_match_single_programme_still_uses_model_explain(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "ProviderAdapter", _CountingProvider)
    _CountingProvider.calls = 0
    # Single-programme /match takes the nested spec shape (MatchRequest),
    # not the flat wizard profile.
    nested = _ug(ielts=(7.0, 6.5), budget=40000).model_dump(mode="json")
    resp = client.post("/api/v1/match", json={
        "profile": nested, "program_id": "oxford-cs-ba-2027"})
    assert resp.status_code == 200, resp.text
    # First attempt + one repair attempt, then the template fallback.
    assert _CountingProvider.calls == 2
    assert resp.json()["ai_status"] == "unavailable"
    assert "oxford-cs-ba-2027" in resp.json()["explanation"]
