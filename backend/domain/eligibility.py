"""Pure rules engine. No network calls, no model calls, no I/O.

Statuses: MET / NOT_MET / UNKNOWN / NOT_APPLICABLE.
Overall: any NOT_MET -> NOT_MET; else any UNKNOWN -> UNKNOWN;
else KNOWN_MINIMUMS_MET.
"""
from __future__ import annotations

from typing import Any

from app.schemas import Budget, Language, MastersProfile, RuleResult, StudentProfile, UndergradProfile


def _r(rule_id: str, status: str, detail: str, evidence_ids: list[str],
        observed: Any = None, threshold: dict | None = None) -> RuleResult:
    return RuleResult(rule_id=rule_id, status=status, detail=detail,
                      evidence_ids=evidence_ids, observed=observed, threshold=threshold)


def _components(language: Language | None) -> dict[str, float | None]:
    if language is None:
        return {}
    return {"listening": language.listening, "reading": language.reading,
            "writing": language.writing, "speaking": language.speaking}


def evaluate_ucl(profile: StudentProfile, program: dict) -> list[RuleResult]:
    results: list[RuleResult] = []
    lang = profile.language
    ug = profile.undergrad_profile or UndergradProfile()

    # --- Language: IELTS overall ---
    if lang is None or lang.exam in (None, "none"):
        results.append(_r("ucl-ielts-overall", "UNKNOWN",
                          "No language test supplied.", ["f-ucl-ielts"]))
    elif lang.exam == "toefl":
        # No UCL TOEFL mapping in our sources — never convert.
        results.append(_r("ucl-ielts-overall", "UNKNOWN",
                          "TOEFL supplied but no UCL TOEFL mapping exists in the verified sources; IELTS not supplied.",
                          ["f-ucl-ielts"], observed={"exam": "toefl", "overall": lang.overall}))
    elif lang.exam == "ielts":
        if lang.overall is None:
            results.append(_r("ucl-ielts-overall", "UNKNOWN",
                              "IELTS overall not supplied.", ["f-ucl-ielts"]))
        elif lang.overall >= 6.5:
            results.append(_r("ucl-ielts-overall", "MET",
                              f"IELTS overall {lang.overall} meets 6.5.", ["f-ucl-ielts"],
                              observed=lang.overall, threshold={"overall": 6.5}))
        else:
            results.append(_r("ucl-ielts-overall", "NOT_MET",
                              f"IELTS overall {lang.overall} is below 6.5.", ["f-ucl-ielts"],
                              observed=lang.overall, threshold={"overall": 6.5}))
    else:
        results.append(_r("ucl-ielts-overall", "UNKNOWN",
                          f"Unrecognised exam type: {lang.exam}.", ["f-ucl-ielts"]))

    # --- Language: IELTS components ---
    if lang is None or lang.exam in (None, "none"):
        results.append(_r("ucl-ielts-components", "UNKNOWN",
                          "No language test supplied.", ["f-ucl-ielts"]))
    elif lang.exam != "ielts":
        results.append(_r("ucl-ielts-components", "UNKNOWN",
                          "No UCL TOEFL mapping in the verified sources; components cannot be assessed.",
                          ["f-ucl-ielts"]))
    else:
        comps = _components(lang)
        missing = [k for k, v in comps.items() if v is None]
        if missing:
            results.append(_r("ucl-ielts-components", "UNKNOWN",
                              f"Missing component score(s): {', '.join(missing)}.",
                              ["f-ucl-ielts"], observed=comps))
        elif all(v >= 6.0 for v in comps.values()):
            results.append(_r("ucl-ielts-components", "MET",
                              "Every IELTS component is at least 6.0.", ["f-ucl-ielts"],
                              observed=comps, threshold={"each_component": 6.0}))
        else:
            low = {k: v for k, v in comps.items() if v < 6.0}
            results.append(_r("ucl-ielts-components", "NOT_MET",
                              f"Component(s) below 6.0: {low}.", ["f-ucl-ielts"],
                              observed=comps, threshold={"each_component": 6.0}))

    # --- Academic ---
    if ug.qualification_type == "a_level":
        grades = ug.a_level_grades or []
        maths_ok = ug.a_level_maths_grade == "A*"
        # A*A*A: at least three grades, sorted top three are A*, A*, A or better.
        rank = {"A*": 5, "A": 4, "B": 3, "C": 2, "D": 1, "E": 0}
        top = sorted((rank.get(g, -1) for g in grades), reverse=True)[:3]
        grades_ok = len(top) == 3 and top[0] >= 5 and top[1] >= 5 and top[2] >= 4
        if grades_ok and maths_ok:
            results.append(_r("ucl-academic", "MET",
                              "A-level grades A*A*A with A* in Mathematics.", ["f-ucl-alevel"],
                              observed={"grades": grades, "maths": ug.a_level_maths_grade}))
        else:
            results.append(_r("ucl-academic", "NOT_MET",
                              "A-level grades do not meet A*A*A with A* in Mathematics.",
                              ["f-ucl-alevel"],
                              observed={"grades": grades, "maths": ug.a_level_maths_grade}))
    elif ug.qualification_type == "ib":
        if ug.ib_total is None or ug.ib_hl_maths_grade is None:
            results.append(_r("ucl-academic", "UNKNOWN",
                              "IB total or HL Mathematics grade not supplied.", ["f-ucl-ib"]))
        elif ug.ib_total >= 40 and ug.ib_hl_maths_grade == 7:
            results.append(_r("ucl-academic", "MET",
                              "IB total 40+ with HL Mathematics grade 7.", ["f-ucl-ib"],
                              observed={"total": ug.ib_total, "hl_maths": ug.ib_hl_maths_grade}))
        else:
            results.append(_r("ucl-academic", "NOT_MET",
                              "IB total below 40 or HL Mathematics below grade 7.", ["f-ucl-ib"],
                              observed={"total": ug.ib_total, "hl_maths": ug.ib_hl_maths_grade}))
    elif ug.qualification_type == "other":
        results.append(_r("ucl-academic", "UNKNOWN",
                          "Qualification is neither A level nor IB; no equivalence evidence in the verified sources.",
                          ["f-ucl-alevel", "f-ucl-ib"]))
    else:
        results.append(_r("ucl-academic", "UNKNOWN",
                          "Qualification type not supplied.", ["f-ucl-alevel", "f-ucl-ib"]))

    # --- TARA: required, no threshold stated -> always UNKNOWN ---
    results.append(_r("ucl-tara", "UNKNOWN",
                      "TARA is required for the 2026 cycle, but no score threshold is stated on the page.",
                      ["f-ucl-tara"], observed=ug.tara_taken))

    # --- Fee: GBP per year vs 46700 ---
    results.append(_fee_ucl(profile.budget))
    return results


def _fee_ucl(budget: Budget | None) -> RuleResult:
    if budget is None or budget.amount is None:
        return _r("ucl-fee", "UNKNOWN", "No budget supplied.", ["f-ucl-fee-overseas"])
    if budget.currency != "GBP" or budget.period != "per_year":
        return _r("ucl-fee", "UNKNOWN",
                  "Budget currency/period does not match GBP per year, so it cannot be compared with the overseas fee.",
                  ["f-ucl-fee-overseas"], observed=budget.model_dump())
    if budget.amount >= 46700:
        return _r("ucl-fee", "MET", f"Budget GBP {budget.amount:g} per year meets GBP 46,700.",
                  ["f-ucl-fee-overseas"], observed=budget.amount, threshold={"gbp_per_year": 46700})
    return _r("ucl-fee", "NOT_MET", f"Budget GBP {budget.amount:g} per year is below GBP 46,700.",
              ["f-ucl-fee-overseas"], observed=budget.amount, threshold={"gbp_per_year": 46700})


def evaluate_nus(profile: StudentProfile, program: dict) -> list[RuleResult]:
    results: list[RuleResult] = []
    lang = profile.language
    mp = profile.masters_profile or MastersProfile()

    # --- Language ---
    if lang is None or lang.exam in (None, "none"):
        results.append(_r("nus-language", "UNKNOWN", "No language test supplied.",
                          ["f-nus-ielts", "f-nus-toefl"]))
        results.append(_r("nus-language-components", "UNKNOWN",
                          "No component minimum is stated for NUS.", ["f-nus-ielts"]))
    elif lang.exam == "ielts":
        if lang.overall is None:
            results.append(_r("nus-language", "UNKNOWN", "IELTS overall not supplied.", ["f-nus-ielts"]))
        elif lang.overall >= 6.0:
            results.append(_r("nus-language", "MET", f"IELTS overall {lang.overall} meets 6.0.",
                              ["f-nus-ielts"], observed=lang.overall, threshold={"overall": 6.0}))
        else:
            results.append(_r("nus-language", "NOT_MET", f"IELTS overall {lang.overall} is below 6.0.",
                              ["f-nus-ielts"], observed=lang.overall, threshold={"overall": 6.0}))
        results.append(_r("nus-language-components", "UNKNOWN",
                          "NUS states no IELTS component minimum.", ["f-nus-ielts"]))
    elif lang.exam == "toefl":
        if lang.overall is None:
            results.append(_r("nus-language", "UNKNOWN", "TOEFL score not supplied.", ["f-nus-toefl"]))
        elif lang.overall >= 90:
            results.append(_r("nus-language", "MET", f"TOEFL iBT {lang.overall:g} meets 90.",
                              ["f-nus-toefl"], observed=lang.overall, threshold={"overall": 90}))
        else:
            results.append(_r("nus-language", "NOT_MET", f"TOEFL iBT {lang.overall:g} is below 90.",
                              ["f-nus-toefl"], observed=lang.overall, threshold={"overall": 90}))
        results.append(_r("nus-language-components", "NOT_APPLICABLE",
                          "TOEFL supplied; IELTS components do not apply.", []))
    else:
        results.append(_r("nus-language", "UNKNOWN", f"Unrecognised exam type: {lang.exam}.",
                          ["f-nus-ielts", "f-nus-toefl"]))

    # --- Academic ---
    field = mp.degree_field
    exp = mp.it_experience_years
    honours = mp.honours
    if field == "computing" and honours:
        results.append(_r("nus-academic", "MET", "Good honours degree in computing.",
                          ["f-nus-academic"], observed={"field": field, "honours": honours}))
    elif field in ("related", "business", "computing") and exp is not None and exp >= 2:
        results.append(_r("nus-academic", "MET",
                          f"Degree in {field} with {exp:g} years of IT industry experience.",
                          ["f-nus-academic"], observed={"field": field, "experience_years": exp}))
    elif field in ("related", "business", "computing") and (exp is None or exp < 2):
        # Insufficient evidence to call this NOT_MET: the source lists
        # experience-based routes without stating a hard rejection.
        results.append(_r("nus-academic", "UNKNOWN",
                          "Degree field/experience do not clearly meet a stated route, and the source gives no hard rejection rule.",
                          ["f-nus-academic"], observed={"field": field, "experience_years": exp}))
    elif field == "other":
        results.append(_r("nus-academic", "UNKNOWN",
                          "Degree field is outside the stated routes; insufficient evidence to reject.",
                          ["f-nus-academic"], observed={"field": field}))
    else:
        results.append(_r("nus-academic", "UNKNOWN",
                          "Degree field not supplied.", ["f-nus-academic"]))

    # --- GRE/GMAT: missing is UNKNOWN, never NOT_MET ---
    gre_ok = (mp.gre_total is not None and mp.gre_analytical is not None
              and mp.gre_total >= 320 and mp.gre_analytical >= 3.5)
    gmat_ok = mp.gmat_total is not None and mp.gmat_total >= 650
    if gre_ok or gmat_ok:
        results.append(_r("nus-gre-gmat", "MET",
                          "GRE 320+ with analytical 3.5+, or GMAT 650+, met.", ["f-nus-gre"],
                          observed={"gre_total": mp.gre_total, "gre_analytical": mp.gre_analytical,
                                    "gmat_total": mp.gmat_total}))
    else:
        results.append(_r("nus-gre-gmat", "UNKNOWN",
                          "GRE/GMAT not supplied or below the stated minimums; the FAQ says GRE/GMAT is not mandatory, so this is UNKNOWN, not NOT_MET.",
                          ["f-nus-gre"],
                          observed={"gre_total": mp.gre_total, "gre_analytical": mp.gre_analytical,
                                    "gmat_total": mp.gmat_total}))

    # --- Fee: SGD total vs 69215 ---
    budget = profile.budget
    if budget is None or budget.amount is None:
        results.append(_r("nus-fee", "UNKNOWN", "No budget supplied.", ["f-nus-fee"]))
    elif budget.currency != "SGD" or budget.period != "total":
        results.append(_r("nus-fee", "UNKNOWN",
                          "Budget currency/period does not match SGD total, so it cannot be compared with the total tuition.",
                          ["f-nus-fee"], observed=budget.model_dump()))
    elif budget.amount >= 69215:
        results.append(_r("nus-fee", "MET", f"Budget SGD {budget.amount:g} total meets SGD 69,215.",
                          ["f-nus-fee"], observed=budget.amount, threshold={"sgd_total": 69215}))
    else:
        results.append(_r("nus-fee", "NOT_MET", f"Budget SGD {budget.amount:g} total is below SGD 69,215.",
                          ["f-nus-fee"], observed=budget.amount, threshold={"sgd_total": 69215}))
    return results


def evaluate_fixture(profile: StudentProfile, program: dict) -> list[RuleResult]:
    """Synthetic fixture rule only: IELTS writing >= 6.0. Test-only."""
    lang = profile.language
    writing = lang.writing if lang else None
    if writing is None:
        return [_r("fixture-writing", "UNKNOWN", "Writing score not supplied.", ["fixture"])]
    if writing >= 6.0:
        return [_r("fixture-writing", "MET", f"Writing {writing} meets 6.0.", ["fixture"],
                   observed=writing, threshold={"writing": 6.0})]
    return [_r("fixture-writing", "NOT_MET", f"Writing {writing} is below 6.0.", ["fixture"],
               observed=writing, threshold={"writing": 6.0})]


def evaluate(profile: StudentProfile, program: dict) -> list[RuleResult]:
    pid = program.get("id")
    if pid == "ucl-cs-bsc-2026":
        return evaluate_ucl(profile, program)
    if pid == "nus-mcomp-cs":
        return evaluate_nus(profile, program)
    if pid == "fixture-p01":
        return evaluate_fixture(profile, program)
    raise ValueError(f"Unknown program id: {pid}")


def overall_status(results: list[RuleResult]) -> str:
    statuses = {r.status for r in results}
    if "NOT_MET" in statuses:
        return "NOT_MET"
    if "UNKNOWN" in statuses:
        return "UNKNOWN"
    return "KNOWN_MINIMUMS_MET"


def track_mismatch(profile: StudentProfile, program: dict) -> str | None:
    """Return an error message if profile track/program track conflict, else None."""
    prog_track = program.get("degree_level")
    if profile.application_track != prog_track:
        return (f"Profile track '{profile.application_track}' does not match program track "
                f"'{prog_track}' for program {program.get('id')}.")
    if profile.application_track == "undergraduate" and profile.masters_profile is not None:
        return "Undergraduate profile must not include masters_profile."
    if profile.application_track == "taught_masters" and profile.undergrad_profile is not None:
        return "Taught-masters profile must not include undergrad_profile."
    return None
