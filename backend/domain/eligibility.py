"""Pure rules engine. No network calls, no model calls, no I/O.

Statuses: MET / NOT_MET / UNKNOWN / NOT_APPLICABLE.
Overall: any NOT_MET -> NOT_MET; else any UNKNOWN -> UNKNOWN;
else KNOWN_MINIMUMS_MET.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.schemas import Budget, Language, MastersProfile, RuleResult, StudentProfile, UndergradProfile

# UCL TOEFL iBT Level 1, verified 2026-11-25 from the UCL Study Abroad
# English page (https://www.ucl.ac.uk/prospective-students/study-abroad-at-ucl/how-apply/english-language-requirements/):
# tests taken from 21 Jan 2026 use the new 1-5 scale (overall 4.5);
# tests taken before that date use the old scale (overall 92).
# Without a test date the scale cannot be chosen, so TOEFL stays UNKNOWN.
TOEFL_SCALE_CUTOFF = date(2026, 1, 21)
TOEFL_NEW_SCALE_OVERALL = 4.5
TOEFL_OLD_SCALE_OVERALL = 92


# --- FX reference table (round 10, R1) -------------------------------------
# Twin of the loader in domain/expansion_eval.py (round 9, R2): the same
# dated, approximate mid-market rates from data/expansions/fx_rates.json
# (units per 1 GBP). It lives here too because expansion_eval imports
# this module, so importing the table from there would be circular.
# Keep the two loaders in sync. A missing/unreadable file means "no
# rates": every cross-currency comparison is UNKNOWN, never a mismatch,
# never a crash. Converted figures are always labelled approximate.
_FX_PATH = Path(__file__).resolve().parents[2] / "data" / "expansions" / "fx_rates.json"


def _load_fx_table() -> tuple[dict[str, Decimal], str | None]:
    try:
        with open(_FX_PATH, encoding="utf-8") as f:
            data = json.load(f)
        rates: dict[str, Decimal] = {}
        for code, value in (data.get("rates_per_gbp") or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                rates[str(code).upper()] = Decimal(str(value))
        return rates, str(data.get("as_of") or "") or None
    except Exception:
        return {}, None


_FX_RATES, _FX_AS_OF = _load_fx_table()


def _convert_fee(amount: Decimal, from_currency: str, to_currency: str) -> Decimal | None:
    """Convert a fee amount from one currency to another via GBP.

    Returns None when either currency has no reference rate (the
    caller must then return UNKNOWN, never a mismatch). Same currency
    returns the amount unchanged.
    """
    from_currency = (from_currency or "").upper()
    to_currency = (to_currency or "").upper()
    if from_currency == to_currency:
        return amount
    from_rate = _FX_RATES.get(from_currency)
    to_rate = _FX_RATES.get(to_currency)
    if from_rate is None or to_rate is None:
        return None
    return amount / from_rate * to_rate


def _fx_note(from_currency: str, to_currency: str) -> str:
    """Rate provenance suffix for a converted-fee detail, e.g.
    " (reference rate 1 GBP = 1.69 SGD, 2026-11-26 — approximate)"."""
    parts: list[str] = []
    for ccy in ((from_currency or "").upper(), (to_currency or "").upper()):
        if ccy and ccy != "GBP":
            rate = _FX_RATES.get(ccy)
            if rate is not None:
                part = f"1 GBP = {rate:g} {ccy}"
                if part not in parts:
                    parts.append(part)
    if not parts:
        return ""
    return (f" (reference rate {', '.join(parts)}, "
            f"{_FX_AS_OF or 'undated'} — approximate)")


def _parse_test_date(value: str | None) -> date | None:
    """Strict ISO YYYY-MM-DD parse; returns None for missing/invalid."""
    if not value or not isinstance(value, str):
        return None
    try:
        parts = value.strip().split("-")
        if len(parts) != 3 or len(parts[0]) != 4:
            return None
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        return None


def _toefl_score(language: Language | None) -> float | None:
    """The TOEFL score to evaluate, if any is supplied.

    exam == "toefl": the primary overall IS the TOEFL score.
    exam == "ielts" with toefl_overall set: the supplementary TOEFL score.
    Otherwise no TOEFL score was supplied.
    """
    if language is None:
        return None
    if language.exam == "toefl":
        return language.overall
    if language.exam == "ielts":
        return language.toefl_overall
    return None


# Country / curriculum branches (fix 2026-11-25, DECISIONS #66). The wizard
# asks this first; the engine evaluates against the applicant's own
# branch instead of assuming A-level/IB/GCSE for everyone.
CURRICULA = ("cn_gaokao", "uk_alevel", "ib", "usa", "sg_alevel", "other")


def effective_curriculum(ug: UndergradProfile) -> str:
    """The applicant's curriculum branch.

    An explicit curriculum wins. Otherwise it is inferred from the legacy
    qualification_type (a_level -> uk_alevel, ib -> ib, other -> other),
    and a profile with neither is treated as uk_alevel so pre-branch API
    clients keep the old behaviour (Day 1/2 tests included).
    """
    if ug.curriculum:
        c = str(ug.curriculum).strip().lower()
        if c in CURRICULA:
            return c
    return {"a_level": "uk_alevel", "ib": "ib", "other": "other"}.get(
        ug.qualification_type or "", "uk_alevel")


def _ug_observed(ug: UndergradProfile) -> dict:
    """Branch-relevant observed values for an undergraduate academic rule.

    Only the current branch's fields are included, so the frontend can
    render "your situation" from structured data instead of English text.
    """
    cur = effective_curriculum(ug)
    obs: dict[str, Any] = {"curriculum": cur}
    if cur in ("uk_alevel", "sg_alevel"):
        obs["grades"] = ug.a_level_grades
        obs["maths"] = ug.a_level_maths_grade
    elif cur == "ib":
        obs["total"] = ug.ib_total
        obs["hl_maths"] = ug.ib_hl_maths_grade
        obs["hl_total"] = ug.ib_hl_total
    elif cur == "cn_gaokao":
        obs["gaokao_score"] = ug.gaokao_score
        obs["gaokao_total"] = ug.gaokao_total
        obs["gaokao_maths"] = ug.gaokao_maths
    elif cur == "usa":
        obs["sat_total"] = ug.sat_total
        obs["act_composite"] = ug.act_composite
        obs["ap_grades"] = ug.ap_grades
    return obs


def _ap_route_met(ug: UndergradProfile) -> bool | None:
    """Imperial's published US standard (accepted-qualifications page):
    five AP tests with grades 5,5,5,4,4, or three AP tests 5,5,4 together
    with an acceptable school-leaving qualification and SAT 1460+ or
    ACT 31+. True if met, False if AP grades were supplied but the
    standard is not met, None if no AP grades were supplied at all.
    The school-leaving qualification itself is not collected; the met
    case is therefore only ever UNKNOWN at course level (see
    evaluate_imperial_beng), never a MET verdict."""
    grades = sorted((g for g in (ug.ap_grades or []) if isinstance(g, int)),
                    reverse=True)
    if not grades:
        return None

    def _covers(need: list[int]) -> bool:
        pool = list(grades)
        for n in need:
            if n in pool:
                pool.remove(n)
            else:
                return False
        return True

    if _covers([5, 5, 5, 4, 4]):
        return True
    if _covers([5, 5, 4]) and ((ug.sat_total or 0) >= 1460
                               or (ug.act_composite or 0) >= 31):
        return True
    return False


def _ucl_toefl_rule(language: Language | None) -> RuleResult | None:
    """Separate UCL TOEFL rule (ucl-toefl), or None if no TOEFL supplied.

    Never converts blindly: without a test date the Jan 2026 scale split
    cannot be applied, so the result is UNKNOWN.
    """
    score = _toefl_score(language)
    if score is None:
        return None
    test_date = _parse_test_date(language.test_date if language else None)
    if test_date is None:
        return _r("ucl-toefl", "UNKNOWN",
                  "TOEFL supplied but no valid test date. UCL Level 1 is 92 on the old iBT scale (tests before 21 Jan 2026) and 4.5 on the new scale (tests from 21 Jan 2026); without a date the scale cannot be chosen, so TOEFL is UNKNOWN, never converted.",
                  ["f-ucl-ielts"], observed={"exam": "toefl", "overall": score, "test_date": language.test_date if language else None})
    if test_date >= TOEFL_SCALE_CUTOFF:
        threshold = TOEFL_NEW_SCALE_OVERALL
        scale = "new scale (tests from 21 Jan 2026)"
    else:
        threshold = TOEFL_OLD_SCALE_OVERALL
        scale = "old scale (tests before 21 Jan 2026)"
    if score >= threshold:
        return _r("ucl-toefl", "MET",
                  f"TOEFL iBT {score:g} on {test_date.isoformat()} meets UCL Level 1 ({threshold:g}, {scale}).",
                  ["f-ucl-ielts"], observed={"exam": "toefl", "overall": score, "test_date": test_date.isoformat()},
                  threshold={"overall": threshold})
    return _r("ucl-toefl", "NOT_MET",
              f"TOEFL iBT {score:g} on {test_date.isoformat()} is below UCL Level 1 ({threshold:g}, {scale}).",
              ["f-ucl-ielts"], observed={"exam": "toefl", "overall": score, "test_date": test_date.isoformat()},
              threshold={"overall": threshold})


_GCSE_LETTER_RANK = {"A*": 7, "A": 6, "B": 5, "C": 4, "D": 3, "E": 2, "F": 1, "G": 0, "U": -1}


def _gcse_pass(grade: str | None) -> bool | None:
    """True if the GCSE grade is C/4 or above, False if below, None if
    missing or unrecognised (cannot be assessed, never guessed)."""
    if grade is None:
        return None
    g = str(grade).strip().upper()
    if not g:
        return None
    if g.isdigit():
        return int(g) >= 4
    if g in _GCSE_LETTER_RANK:
        return _GCSE_LETTER_RANK[g] >= 4
    return None


def _gcse_rule(ug: UndergradProfile, curriculum: str) -> RuleResult:
    """UCL GCSE rule (ucl-gcse): English + Maths at grade C/4 required.

    GCSEs are a UK-school qualification, so the rule is evaluated for UK
    A-level applicants, and for any applicant who supplied GCSE grades
    (legacy / API profiles, e.g. an IB student with GCSEs). For other
    curriculum branches without GCSE grades it is NOT_APPLICABLE, never
    UNKNOWN — a Gaokao / USA / IB / Singapore applicant must not be
    asked for GCSEs they do not have (fix 2026-11-25, DECISIONS #66).

    Evidence: the requirement is stated on the UCL BSc page (source
    ucl-bsc). The v1 manifest has no dedicated GCSE fact, so the rule cites
    the forward-reference id f-ucl-gcse, which the v2 manifest must add
    (DECISIONS #45); the frontend maps it to ucl-cs-entry meanwhile.
    """
    if curriculum != "uk_alevel" and ug.gcse_english_grade is None \
            and ug.gcse_maths_grade is None:
        return _r("ucl-gcse", "NOT_APPLICABLE",
                  "GCSE is a UK-school qualification; this applicant's curriculum branch does not include GCSEs, so there is no GCSE requirement to check.",
                  ["f-ucl-gcse"], observed={"curriculum": curriculum})
    eng = _gcse_pass(ug.gcse_english_grade)
    maths = _gcse_pass(ug.gcse_maths_grade)
    observed = {"english": ug.gcse_english_grade, "maths": ug.gcse_maths_grade}
    if eng is None or maths is None:
        missing = [n for n, v in (("English", eng), ("Maths", maths)) if v is None]
        return _r("ucl-gcse", "UNKNOWN",
                  f"GCSE grade(s) not supplied or unrecognised: {', '.join(missing)}. UCL requires GCSE English and Maths at grade C/4.",
                  ["f-ucl-gcse"], observed=observed)
    if eng and maths:
        return _r("ucl-gcse", "MET",
                  "GCSE English and Maths are both at grade C/4 or above.",
                  ["f-ucl-gcse"], observed=observed, threshold={"each": "C/4"})
    below = [n for n, v in (("English", eng), ("Maths", maths)) if not v]
    return _r("ucl-gcse", "NOT_MET",
              f"GCSE grade(s) below C/4: {', '.join(below)}.",
              ["f-ucl-gcse"], observed=observed, threshold={"each": "C/4"})


def _dec(value: Any) -> Decimal | None:
    """Normalise a budget amount to Decimal (int/float/str/Decimal in)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _plain_number(value: Any) -> Any:
    """Decimal -> plain JSON number (int when whole, else float).

    FastAPI/pydantic serialise Decimal as a JSON *string* in model_dump
    mode="json", so any Decimal that reaches a response must be converted
    first — the API contract is plain numbers (spec Ch11/Ch12).
    """
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


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
    curriculum = effective_curriculum(ug)

    # --- Language: IELTS overall ---
    if lang is None or lang.exam in (None, "none"):
        results.append(_r("ucl-ielts-overall", "UNKNOWN",
                          "No language test supplied.", ["f-ucl-ielts"]))
    elif lang.exam == "toefl":
        # TOEFL is assessed by its own rule (ucl-toefl, below) using the
        # test date and the Jan 2026 scale split. There is no IELTS score
        # to assess here, so the IELTS rules stay UNKNOWN.
        results.append(_r("ucl-ielts-overall", "UNKNOWN",
                          "TOEFL supplied, IELTS not supplied. TOEFL is assessed under rule ucl-toefl.",
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
                          "TOEFL supplied; IELTS components do not apply. TOEFL is assessed under rule ucl-toefl.",
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

    # --- Language: TOEFL (separate rule, never silently dropped) ---
    toefl_rule = _ucl_toefl_rule(lang)
    if toefl_rule is not None:
        results.append(toefl_rule)

    # --- GCSE: English + Maths at grade C/4 (UK A-level branch only;
    # other branches without GCSE grades are NOT_APPLICABLE) ---
    results.append(_gcse_rule(ug, curriculum))

    # --- Academic: evaluated against the applicant's own curriculum ---
    if curriculum in ("uk_alevel", "sg_alevel"):
        grades = ug.a_level_grades or []
        maths_ok = ug.a_level_maths_grade == "A*"
        # A*A*A: at least three grades, sorted top three are A*, A*, A or better.
        rank = {"A*": 5, "A": 4, "B": 3, "C": 2, "D": 1, "E": 0}
        top = sorted((rank.get(g, -1) for g in grades), reverse=True)[:3]
        grades_ok = len(top) == 3 and top[0] >= 5 and top[1] >= 5 and top[2] >= 4
        # Contextual offer A*AB with A* in Mathematics is a real alternative
        # route on the official page. Without evidence of contextual
        # eligibility it cannot be MET, but it is not a failure either.
        contextual_ok = len(top) == 3 and top[0] >= 5 and top[1] >= 4 and top[2] >= 3 and maths_ok
        if not grades and ug.a_level_maths_grade is None:
            # No A-level evidence at all (e.g. a profile with no
            # qualification info): missing, never a failure.
            results.append(_r("ucl-academic", "UNKNOWN",
                              "A-level grades not supplied.", ["f-ucl-alevel"],
                              observed=_ug_observed(ug)))
        elif grades_ok and maths_ok:
            results.append(_r("ucl-academic", "MET",
                              "A-level grades A*A*A with A* in Mathematics.", ["f-ucl-alevel"],
                              observed=_ug_observed(ug)))
        elif contextual_ok:
            results.append(_r("ucl-academic", "UNKNOWN",
                              "A-level grades meet the UCL contextual offer (A*AB with A* in Mathematics), but contextual eligibility is not confirmed for this applicant.",
                              ["f-ucl-alevel"],
                              observed=_ug_observed(ug)))
        else:
            results.append(_r("ucl-academic", "NOT_MET",
                              "A-level grades do not meet A*A*A with A* in Mathematics.",
                              ["f-ucl-alevel"],
                              observed=_ug_observed(ug)))
    elif curriculum == "ib":
        if ug.ib_total is None or ug.ib_hl_maths_grade is None:
            results.append(_r("ucl-academic", "UNKNOWN",
                              "IB total or HL Mathematics grade not supplied.", ["f-ucl-ib"]))
        elif ug.ib_hl_total is None:
            # DECISIONS #39: without the HL total, an IB applicant can no
            # longer be MET on total + HL Maths alone — total 40 with an HL
            # sum below 20 was wrongly MET on Day 1.
            results.append(_r("ucl-academic", "UNKNOWN",
                              "HL total not supplied. UCL requires 20 points in three Higher Level subjects (including grade 7 in Mathematics) for IB 40, so the academic rule cannot be decided without it.",
                              ["f-ucl-ib"],
                              observed=_ug_observed(ug)))
        elif ug.ib_total >= 40 and ug.ib_hl_maths_grade == 7 and ug.ib_hl_total >= 20:
            results.append(_r("ucl-academic", "MET",
                              "IB total 40+ with 20+ points in three HL subjects including HL Mathematics grade 7.",
                              ["f-ucl-ib"],
                              observed=_ug_observed(ug)))
        elif ug.ib_total >= 40 and ug.ib_hl_maths_grade == 7:
            # Total 40 + HL Maths 7 but HL sum below 20: fails the stated
            # "20 points in three HL subjects" requirement.
            results.append(_r("ucl-academic", "NOT_MET",
                              f"IB total {ug.ib_total} with HL Mathematics grade 7, but only {ug.ib_hl_total} points in three HL subjects (20 required).",
                              ["f-ucl-ib"],
                              observed=_ug_observed(ug)))
        elif ug.ib_total >= 38 and ug.ib_hl_maths_grade == 7 and ug.ib_hl_total >= 18:
            # Contextual offer is IB 38 (18 points in three HL subjects incl.
            # grade 7 in Maths). Without evidence of contextual eligibility
            # it cannot be MET, but it is not a failure.
            results.append(_r("ucl-academic", "UNKNOWN",
                              "IB total 38-39 with HL Mathematics grade 7 and 18+ HL points is within the UCL contextual offer (IB 38), but contextual eligibility is not confirmed for this applicant.",
                              ["f-ucl-ib"],
                              observed=_ug_observed(ug)))
        else:
            results.append(_r("ucl-academic", "NOT_MET",
                              "IB total below 40 or HL Mathematics below grade 7 (or HL total below the contextual 18).", ["f-ucl-ib"],
                              observed=_ug_observed(ug)))
    elif curriculum == "cn_gaokao":
        # No Gaokao direct-entry route is published for this programme:
        # UCL's China page states the minimum equivalent entry requirement
        # is ABB at A level or 36 IB points (or one year of a Chinese
        # bachelor's degree at 90%). A Gaokao score is never converted to
        # A-level grades. Verified 2026-11-25 (DECISIONS #67).
        results.append(_r("ucl-academic", "UNKNOWN",
                          "Gaokao scores cannot be assessed for this programme: UCL's China page states the minimum equivalent entry requirement is ABB at A level or 36 IB points (or one year of a Chinese bachelor's degree at 90%), and no direct Gaokao entry route is published for Computer Science BSc. Gaokao is never treated as A level.",
                          ["f-ucl-china-gaokao"], observed=_ug_observed(ug)))
    elif curriculum == "usa":
        # No US (SAT/ACT/AP) equivalence is stated on the UCL Computer
        # Science BSc page or in the verified sources, so a US-curriculum
        # applicant cannot be assessed against A*A*A. Scores are never
        # converted to A-level grades (DECISIONS #67).
        results.append(_r("ucl-academic", "UNKNOWN",
                          "No US (SAT/ACT/AP) equivalence is stated on the UCL Computer Science BSc page or in the verified sources, so a US-curriculum applicant cannot be assessed against the A*A*A requirement. SAT/ACT/AP scores are never converted to A-level grades.",
                          ["f-ucl-alevel"], observed=_ug_observed(ug)))
    elif ug.qualification_type == "other":
        results.append(_r("ucl-academic", "UNKNOWN",
                          "Qualification is neither A level nor IB; no equivalence evidence in the verified sources.",
                          ["f-ucl-alevel", "f-ucl-ib"], observed=_ug_observed(ug)))
    else:
        results.append(_r("ucl-academic", "UNKNOWN",
                          "Qualification type not supplied.", ["f-ucl-alevel", "f-ucl-ib"],
                          observed=_ug_observed(ug)))

    # --- TARA: required, no threshold stated -> always UNKNOWN ---
    results.append(_r("ucl-tara", "UNKNOWN",
                      "TARA is required for the 2027/28 admission, but no score threshold is stated on the page.",
                      ["f-ucl-tara"], observed=ug.tara_taken))

    # --- Fee: GBP per year vs the residency fee (Decimal comparison) ---
    results.append(_fee_ucl(profile.budget, ug.residency))
    return results


def _fee_ucl(budget: Budget | None, residency: str | None = None) -> RuleResult:
    # UK fee GBP 10,050/yr; overseas GBP 48,600/yr (programs.json fees).
    # Missing residency assumes overseas — a documented assumption, and the
    # detail says so; the wizard must say so too (DECISIONS #37/#46).
    is_uk = (residency or "").strip().lower() == "uk"
    fee = Decimal(10050) if is_uk else Decimal(48600)
    fee_label = "UK GBP 10,050" if is_uk else "overseas GBP 48,600 (residency not supplied, overseas assumed)" if not residency else "overseas GBP 48,600"
    if budget is None or budget.amount is None:
        return _r("ucl-fee", "UNKNOWN", f"No budget supplied. Fee is {fee_label} per year.",
                  ["f-ucl-fee-overseas"] if not is_uk else ["f-ucl-fee-uk"])
    if budget.currency != "GBP" or budget.period != "per_year":
        return _r("ucl-fee", "UNKNOWN",
                  "Budget currency/period does not match GBP per year, so it cannot be compared with the fee.",
                  ["f-ucl-fee-overseas"] if not is_uk else ["f-ucl-fee-uk"],
                  observed={"amount": _plain_number(budget.amount),
                            "currency": budget.currency, "period": budget.period})
    amount = _dec(budget.amount)
    if amount >= fee:
        return _r("ucl-fee", "MET", f"Budget GBP {amount:g} per year meets {fee_label}.",
                  ["f-ucl-fee-overseas"] if not is_uk else ["f-ucl-fee-uk"],
                  observed=_plain_number(amount), threshold={"gbp_per_year": int(fee)})
    return _r("ucl-fee", "NOT_MET", f"Budget GBP {amount:g} per year is below {fee_label}.",
              ["f-ucl-fee-overseas"] if not is_uk else ["f-ucl-fee-uk"],
              observed=_plain_number(amount), threshold={"gbp_per_year": int(fee)})


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
        results.append(_r("nus-language-components", "NOT_APPLICABLE",
                          "NUS states no IELTS component minimum (overall 6.0 only); there is no component requirement to check.",
                          ["f-nus-ielts"]))
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
        results.append(_r("nus-language-components", "UNKNOWN",
                          "Exam type unrecognised; components cannot be assessed.", ["f-nus-ielts"]))

    # --- Language: TOEFL supplementary rule (both exams present) ---
    # When IELTS is the primary exam but a TOEFL score was also supplied,
    # evaluate it as its own rule (nus-toefl, iBT 90) instead of dropping it.
    # When TOEFL is the only exam, nus-language above already covers it.
    if lang is not None and lang.exam == "ielts" and lang.toefl_overall is not None:
        toefl = lang.toefl_overall
        if toefl >= 90:
            results.append(_r("nus-toefl", "MET", f"TOEFL iBT {toefl:g} meets 90 (supplementary; IELTS also supplied).",
                              ["f-nus-toefl"], observed=toefl, threshold={"overall": 90}))
        else:
            results.append(_r("nus-toefl", "NOT_MET", f"TOEFL iBT {toefl:g} is below 90 (supplementary; IELTS also supplied).",
                              ["f-nus-toefl"], observed=toefl, threshold={"overall": 90}))

    # --- Academic ---
    field = mp.degree_field
    exp = mp.it_experience_years
    honours = mp.honours
    # Official routes (NUS admissions page): honours in computing; honours in a
    # related discipline + 2y IT experience; bachelor's in computing + 2y;
    # bachelor's OR honours in a business-related discipline + 2y. The related
    # route requires honours — a related bachelor's + 2y is not a listed route.
    if field == "computing" and honours:
        results.append(_r("nus-academic", "MET", "Good honours degree in computing.",
                          ["f-nus-academic"], observed={"field": field, "honours": honours}))
    elif field == "computing" and exp is not None and exp >= 2:
        results.append(_r("nus-academic", "MET",
                          "Bachelor's degree in computing with 2+ years of IT industry experience.",
                          ["f-nus-academic"], observed={"field": field, "experience_years": exp}))
    elif field == "business" and exp is not None and exp >= 2:
        results.append(_r("nus-academic", "MET",
                          "Bachelor's or honours degree in a business-related discipline with 2+ years of IT industry experience.",
                          ["f-nus-academic"], observed={"field": field, "experience_years": exp}))
    elif field == "related" and honours and exp is not None and exp >= 2:
        results.append(_r("nus-academic", "MET",
                          "Good honours degree in a related discipline with 2+ years of IT industry experience.",
                          ["f-nus-academic"], observed={"field": field, "experience_years": exp}))
    elif field in ("related", "business", "computing") and (exp is None or exp < 2):
        # Insufficient evidence to call this NOT_MET: the source lists
        # experience-based routes without stating a hard rejection.
        results.append(_r("nus-academic", "UNKNOWN",
                          "Degree field/experience do not clearly meet a stated route, and the source gives no hard rejection rule.",
                          ["f-nus-academic"], observed={"field": field, "experience_years": exp}))
    elif field == "related" and not honours and exp is not None and exp >= 2:
        results.append(_r("nus-academic", "UNKNOWN",
                          "A related-discipline bachelor's degree with 2+ years of experience is not a listed route (the related route requires honours); insufficient evidence to reject.",
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
                          "GRE/GMAT not supplied or below the stated minimums. The admissions page lists GRE/GMAT as evidence to submit but states no rejection rule for a missing or low score, so this is UNKNOWN, not NOT_MET.",
                          ["f-nus-gre"],
                          observed={"gre_total": mp.gre_total, "gre_analytical": mp.gre_analytical,
                                    "gmat_total": mp.gmat_total}))

    # --- Fee: SGD total vs 69215 (Decimal comparison) ---
    budget = profile.budget
    if budget is None or budget.amount is None:
        results.append(_r("nus-fee", "UNKNOWN", "No budget supplied.", ["f-nus-fee"]))
    elif budget.currency != "SGD" or budget.period != "total":
        results.append(_r("nus-fee", "UNKNOWN",
                          "Budget currency/period does not match SGD total, so it cannot be compared with the total tuition.",
                          ["f-nus-fee"], observed={"amount": _plain_number(budget.amount),
                                                   "currency": budget.currency,
                                                   "period": budget.period}))
    elif _dec(budget.amount) >= Decimal(69215):
        amount = _dec(budget.amount)
        results.append(_r("nus-fee", "MET", f"Budget SGD {amount:g} total meets SGD 69,215.",
                          ["f-nus-fee"], observed=_plain_number(amount), threshold={"sgd_total": 69215}))
    else:
        amount = _dec(budget.amount)
        results.append(_r("nus-fee", "NOT_MET", f"Budget SGD {amount:g} total is below SGD 69,215.",
                          ["f-nus-fee"], observed=_plain_number(amount), threshold={"sgd_total": 69215}))
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



# ---------------------------------------------------------------------------
# Day 2 (v2) shared helpers for the six new programmes.
# ---------------------------------------------------------------------------

def _alevel_top3(grades: list[str] | None) -> list[int] | None:
    """Sorted top-three A-level ranks (A*=5 ... E=0), or None if unusable."""
    if not grades:
        return None
    rank = {"A*": 5, "A": 4, "B": 3, "C": 2, "D": 1, "E": 0}
    vals = [rank.get(g, -1) for g in grades]
    if any(v < 0 for v in vals) or len(vals) < 3:
        return None
    return sorted(vals, reverse=True)[:3]


def _ielts_overall_rule(rule_id: str, lang: Language | None, minimum: float,
                       evidence: list[str], label: str) -> RuleResult:
    if lang is None or lang.exam in (None, "none"):
        return _r(rule_id, "UNKNOWN", "No language test supplied.", evidence)
    if lang.exam == "toefl":
        return _r(rule_id, "UNKNOWN",
                  f"TOEFL supplied, IELTS not supplied. TOEFL is assessed under its own rule; {label} IELTS cannot be assessed.",
                  evidence)
    if lang.exam != "ielts":
        return _r(rule_id, "UNKNOWN", f"Unrecognised exam type: {lang.exam}.", evidence)
    if lang.overall is None:
        return _r(rule_id, "UNKNOWN", "IELTS overall not supplied.", evidence)
    if lang.overall >= minimum:
        return _r(rule_id, "MET", f"IELTS overall {lang.overall} meets {minimum:g}.",
                  evidence, observed=lang.overall, threshold={"overall": minimum})
    return _r(rule_id, "NOT_MET", f"IELTS overall {lang.overall} is below {minimum:g}.",
              evidence, observed=lang.overall, threshold={"overall": minimum})


def _ielts_components_rule(rule_id: str, lang: Language | None, minima: dict[str, float],
                           evidence: list[str], label: str) -> RuleResult:
    if lang is None or lang.exam in (None, "none"):
        return _r(rule_id, "UNKNOWN", "No language test supplied.", evidence)
    if lang.exam != "ielts":
        return _r(rule_id, "UNKNOWN",
                  f"TOEFL supplied; IELTS components do not apply. TOEFL is assessed under its own rule.",
                  evidence)
    comps = _components(lang)
    missing = [k for k in minima if comps.get(k) is None]
    if missing:
        return _r(rule_id, "UNKNOWN", f"Missing component score(s): {', '.join(missing)}.",
                  evidence, observed=comps)
    low = {k: comps[k] for k, v in minima.items() if comps[k] < v}
    if not low:
        return _r(rule_id, "MET",
                  f"Every required IELTS component meets its minimum ({label}).",
                  evidence, observed=comps, threshold=dict(minima))
    return _r(rule_id, "NOT_MET", f"Component(s) below the minimum: {low}.",
              evidence, observed=comps, threshold=dict(minima))


def _toefl_generic_rule(rule_id: str, lang: Language | None, old_overall: float,
                        new_overall: float | None, evidence: list[str],
                        label: str) -> RuleResult | None:
    """Date-dependent TOEFL rule. Returns None if no TOEFL was supplied.

    If the page states only an old-scale iBT threshold (new_overall None), a
    score that looks like the new 1-6 scale (<= 6) is UNKNOWN, never compared
    against the iBT threshold.
    """
    score = _toefl_score(lang)
    if score is None:
        return None
    if new_overall is None:
        if score <= 6:
            return _r(rule_id, "UNKNOWN",
                      f"TOEFL score {score:g} looks like the new 1-6 scale, but {label} states only an iBT threshold ({old_overall:g}); the score cannot be compared.",
                      evidence, observed={"exam": "toefl", "overall": score})
        if score >= old_overall:
            return _r(rule_id, "MET", f"TOEFL iBT {score:g} meets {old_overall:g} ({label}).",
                      evidence, observed=score, threshold={"overall": old_overall})
        return _r(rule_id, "NOT_MET", f"TOEFL iBT {score:g} is below {old_overall:g} ({label}).",
                  evidence, observed=score, threshold={"overall": old_overall})
    test_date = _parse_test_date(lang.test_date if lang else None)
    if test_date is None:
        return _r(rule_id, "UNKNOWN",
                  f"TOEFL supplied but no valid test date. {label} is {old_overall:g} on the old iBT scale (tests before 21 Jan 2026) and {new_overall:g} on the new scale (tests from 21 Jan 2026); without a date the scale cannot be chosen, so TOEFL is UNKNOWN, never converted.",
                  evidence, observed={"exam": "toefl", "overall": score,
                                      "test_date": lang.test_date if lang else None})
    threshold = new_overall if test_date >= TOEFL_SCALE_CUTOFF else old_overall
    scale = "new scale (tests from 21 Jan 2026)" if test_date >= TOEFL_SCALE_CUTOFF else "old scale (tests before 21 Jan 2026)"
    if score >= threshold:
        return _r(rule_id, "MET",
                  f"TOEFL iBT {score:g} on {test_date.isoformat()} meets {label} ({threshold:g}, {scale}).",
                  evidence, observed={"exam": "toefl", "overall": score, "test_date": test_date.isoformat()},
                  threshold={"overall": threshold})
    return _r(rule_id, "NOT_MET",
              f"TOEFL iBT {score:g} on {test_date.isoformat()} is below {label} ({threshold:g}, {scale}).",
              evidence, observed={"exam": "toefl", "overall": score, "test_date": test_date.isoformat()},
              threshold={"overall": threshold})


def _fee_for_residency(rule_id: str, budget: Budget | None, residency: str | None,
                       currency: str, period: str,
                       bands: dict[str, Decimal | None],
                       unknown_reasons: dict[str, str],
                       evidence: list[str], label: str) -> RuleResult:
    # Round 10, R1: the old order bailed on a currency mismatch BEFORE
    # looking at the residency band, so a GBP budget against an SGD fee
    # came back UNKNOWN with "does not match" — which the adapter maps
    # to reasonKey budget-mismatch, rendering "学费：未知" next to
    # "你的预算与该课程的学费不匹配。" for the same rule. The band is
    # now resolved first, and a cross-currency fee is compared with the
    # dated, approximate FX reference table (same table as the generic
    # expansion evaluator): the converted figure is always labelled
    # approximate, and a currency with no reference rate is UNKNOWN
    # ("cannot be converted"), never a false mismatch. Only a period
    # mismatch still returns the "does not match" wording — periods
    # genuinely cannot be compared.
    if budget is None or budget.amount is None:
        return _r(rule_id, "UNKNOWN", "No budget supplied.", evidence)
    if budget.period != period:
        return _r(rule_id, "UNKNOWN",
                  f"Budget period ({budget.period}) does not match the fee period ({period}), so it cannot be compared with the fee.",
                  evidence, observed=budget.model_dump())
    key = residency if residency in bands else "missing"
    amount = bands.get(key)
    if amount is None:
        return _r(rule_id, "UNKNOWN",
                  unknown_reasons.get(key, f"Fee for residency '{residency}' cannot be decided from the verified sources."),
                  evidence, observed={"residency": residency})
    amount = Decimal(str(amount))
    got = Decimal(str(budget.amount))
    threshold: dict[str, Any] = {"amount": float(amount)}
    if budget.currency != currency:
        converted = _convert_fee(amount, currency, budget.currency or "")
        if converted is None:
            return _r(rule_id, "UNKNOWN",
                      f"The fee is {currency} {amount:g} {period} and the budget is in {budget.currency}; no reference exchange rate is available for this currency pair, so the fee cannot be converted for comparison.",
                      evidence,
                      observed={"amount": _plain_number(budget.amount),
                                "currency": budget.currency,
                                "period": budget.period},
                      threshold=threshold)
        converted_note = (f"(about {budget.currency} {converted:,.0f}"
                          f"{_fx_note(currency, budget.currency or '')})")
        # Carry the converted figure in the threshold payload so
        # renderers can show it without re-parsing the detail string
        # (same shape as the generic expansion evaluator).
        threshold = {**threshold,
                     "approx_converted": {"amount": round(float(converted)),
                                          "currency": budget.currency or "",
                                          "as_of": _FX_AS_OF}}
        if got >= converted:
            return _r(rule_id, "MET", f"Budget {budget.currency} {got:g} {period} covers the {currency} {amount:g} {period} tuition fee {converted_note}.",
                      evidence, observed=got, threshold=threshold)
        return _r(rule_id, "NOT_MET", f"Budget {budget.currency} {got:g} {period} is below the {currency} {amount:g} {period} tuition fee {converted_note}.",
                  evidence, observed=got, threshold=threshold)
    if got >= amount:
        return _r(rule_id, "MET", f"Budget {currency} {got:g} {period} meets {label} {amount:g}.",
                  evidence, observed=got, threshold=threshold)
    return _r(rule_id, "NOT_MET", f"Budget {currency} {got:g} {period} is below {label} {amount:g}.",
              evidence, observed=got, threshold=threshold)


def evaluate_imperial_beng(profile: StudentProfile, program: dict) -> list[RuleResult]:
    results: list[RuleResult] = []
    lang = profile.language
    ug = profile.undergrad_profile or UndergradProfile()
    curriculum = effective_curriculum(ug)
    # --- Academic: A-level A*A*A or A*AAA incl. A* Maths; IB 41 + HL Maths 7
    # + another HL 7 (second HL grade is not collected, so IB can be UNKNOWN
    # at best once total + HL Maths are met). US applicants are assessed
    # against Imperial's published AP standard; Gaokao has no published
    # equivalence (China is not in Imperial's accepted-qualifications
    # table). DECISIONS #67.
    if curriculum in ("uk_alevel", "sg_alevel"):
        top = _alevel_top3(ug.a_level_grades)
        maths_ok = ug.a_level_maths_grade == "A*"
        if top is None or not maths_ok and ug.a_level_maths_grade is None:
            results.append(_r("imp-beng-academic", "UNKNOWN",
                              "A-level grades or Maths grade not supplied.", ["f-imperial-beng-alevel"],
                              observed=_ug_observed(ug)))
        elif top is not None and maths_ok and (top >= [5, 5, 4] or top >= [5, 4, 4]):
            results.append(_r("imp-beng-academic", "MET",
                              "A-level grades A*A*A or A*AAA with A* in Mathematics.", ["f-imperial-beng-alevel"],
                              observed=_ug_observed(ug)))
        else:
            results.append(_r("imp-beng-academic", "NOT_MET",
                              "A-level grades do not meet A*A*A or A*AAA with A* in Mathematics.",
                              ["f-imperial-beng-alevel"],
                              observed=_ug_observed(ug)))
    elif curriculum == "ib":
        if ug.ib_total is None or ug.ib_hl_maths_grade is None:
            results.append(_r("imp-beng-academic", "UNKNOWN",
                              "IB total or HL Mathematics grade not supplied.", ["f-imperial-beng-ib"]))
        elif ug.ib_total < 41 or ug.ib_hl_maths_grade < 7:
            results.append(_r("imp-beng-academic", "NOT_MET",
                              "IB total below 41 or HL Mathematics below grade 7.", ["f-imperial-beng-ib"],
                              observed=_ug_observed(ug)))
        else:
            results.append(_r("imp-beng-academic", "UNKNOWN",
                              "IB total 41+ with HL Mathematics grade 7, but a second Higher Level subject at grade 7 is also required and was not supplied, so this cannot be decided.",
                              ["f-imperial-beng-ib"],
                              observed=_ug_observed(ug)))
    elif curriculum == "usa":
        # Imperial's accepted-qualifications page publishes a US standard
        # (five AP tests 5,5,5,4,4, or three AP tests 5,5,4 + SAT 1460 /
        # ACT 31). Meeting it only establishes equivalence to 3 A levels;
        # the Computing BEng course requirement (A* in Mathematics) cannot
        # be checked from AP grades alone, and the page states some courses
        # require higher than the general minimum — so a met standard is
        # UNKNOWN, never MET. Below the standard is a real NOT_MET.
        ap = _ap_route_met(ug)
        if ap is None:
            results.append(_r("imp-beng-academic", "UNKNOWN",
                              "No AP grades supplied. Imperial's published US standard is five AP tests with grades 5,5,5,4,4, or three AP tests 5,5,4 with SAT 1460+ or ACT 31+.",
                              ["f-imperial-usa-ap"], observed=_ug_observed(ug)))
        elif ap:
            results.append(_r("imp-beng-academic", "UNKNOWN",
                              "AP/SAT/ACT scores meet Imperial's published general minimum standard for US applicants (five AP tests 5,5,5,4,4, or three AP tests 5,5,4 with SAT 1460+ or ACT 31+), but the Computing BEng course requirement (A* in Mathematics) cannot be checked from AP grades alone — the course page states higher requirements than the general minimum.",
                              ["f-imperial-usa-ap"], observed=_ug_observed(ug)))
        else:
            results.append(_r("imp-beng-academic", "NOT_MET",
                              "AP/SAT/ACT scores are below Imperial's published minimum standard for US applicants (five AP tests 5,5,5,4,4, or three AP tests 5,5,4 with SAT 1460+ or ACT 31+).",
                              ["f-imperial-usa-ap"], observed=_ug_observed(ug)))
    elif curriculum == "cn_gaokao":
        # China does not appear in Imperial's accepted-qualifications
        # table at all, so no Gaokao equivalence is published for this
        # programme. Verified 2026-11-25 (DECISIONS #67).
        results.append(_r("imp-beng-academic", "UNKNOWN",
                          "Gaokao scores cannot be assessed for this programme: China does not appear in Imperial's accepted-qualifications table, so no Gaokao equivalence is published for Computing BEng. Gaokao is never treated as A level.",
                          ["f-imperial-china-none"], observed=_ug_observed(ug)))
    else:
        results.append(_r("imp-beng-academic", "UNKNOWN",
                          "Qualification type not supplied or neither A level nor IB; no equivalence evidence in the verified sources.",
                          ["f-imperial-beng-alevel", "f-imperial-beng-ib"],
                          observed=_ug_observed(ug)))
    # --- Language ---
    results.append(_ielts_overall_rule("imp-beng-language", lang, 6.5,
                                       ["f-imperial-beng-ielts"], "Imperial BEng (Standard)"))
    results.append(_ielts_components_rule("imp-beng-language-components", lang,
                                          {"listening": 6.0, "reading": 6.0, "writing": 6.0, "speaking": 6.0},
                                          ["f-imperial-beng-ielts"], "6.0 in all elements"))
    toefl = _toefl_generic_rule("imp-beng-toefl", lang, 92, 4.5,
                                ["f-imperial-beng-ielts"], "Imperial BEng TOEFL (Standard)")
    if toefl is not None:
        results.append(toefl)
    # --- TMUA: required, no threshold stated ---
    results.append(_r("imp-beng-tmua", "UNKNOWN",
                      "TMUA is required for this course, but no score threshold is stated on the programme specification or course page.",
                      ["f-imperial-beng-tmua"], observed=ug.tara_taken))
    # --- Fee: UK 10,050 / overseas 47,800 per year ---
    results.append(_fee_for_residency(
        "imp-beng-fee", profile.budget, ug.residency, "GBP", "per_year",
        {"uk": Decimal("10050"), "overseas": Decimal("47800"), "missing": Decimal("47800")},
        {"missing": "Residency not supplied; overseas fee assumed (see wizard note)."},
        ["f-imperial-beng-fee-overseas", "f-imperial-beng-fee-uk"], "GBP"))
    return results


def evaluate_imperial_msc(profile: StudentProfile, program: dict) -> list[RuleResult]:
    results: list[RuleResult] = []
    lang = profile.language
    mp = profile.masters_profile or MastersProfile()
    # --- Academic: First-Class in a non-computing subject ---
    field = mp.degree_field
    if field == "computing":
        results.append(_r("imp-msc-academic", "NOT_MET",
                          "This conversion MSc requires a First-Class degree in a subject without substantial Computing content; a computing degree does not meet it.",
                          ["f-imperial-msc-academic"], observed={"field": field}))
    elif mp.degree_class is None:
        results.append(_r("imp-msc-academic", "UNKNOWN",
                          "Degree class not supplied; a First-Class degree is required.", ["f-imperial-msc-academic"]))
    elif mp.degree_class != "first":
        results.append(_r("imp-msc-academic", "NOT_MET",
                          "A First-Class degree is required.", ["f-imperial-msc-academic"],
                          observed={"degree_class": mp.degree_class}))
    elif field == "related":
        results.append(_r("imp-msc-academic", "MET",
                          "First-Class degree in a STEM-related subject; the A-in-A-level-Maths condition applies to non-STEM applicants.",
                          ["f-imperial-msc-academic", "f-imperial-msc-academic-detail"],
                          observed={"field": field, "degree_class": mp.degree_class}))
    elif field in ("business", "other"):
        if mp.maths_alevel_grade in ("A*", "A"):
            results.append(_r("imp-msc-academic", "MET",
                              "First-Class degree in a non-STEM subject with at least A in A-level Mathematics.",
                              ["f-imperial-msc-academic", "f-imperial-msc-academic-detail"],
                              observed={"field": field, "maths_alevel": mp.maths_alevel_grade}))
        elif mp.maths_alevel_grade is None:
            results.append(_r("imp-msc-academic", "UNKNOWN",
                              "First-Class degree in a non-STEM subject; at least A in A-level Mathematics is required and no Maths grade was supplied.",
                              ["f-imperial-msc-academic-detail"]))
        else:
            results.append(_r("imp-msc-academic", "NOT_MET",
                              "A First-Class degree in a non-STEM subject requires at least A in A-level Mathematics.",
                              ["f-imperial-msc-academic-detail"],
                              observed={"maths_alevel": mp.maths_alevel_grade}))
    else:
        results.append(_r("imp-msc-academic", "UNKNOWN",
                          "Degree field not supplied.", ["f-imperial-msc-academic"]))
    # --- Language ---
    results.append(_ielts_overall_rule("imp-msc-language", lang, 7.0,
                                       ["f-imperial-msc-ielts"], "Imperial MSc (Higher, PG)"))
    results.append(_ielts_components_rule("imp-msc-language-components", lang,
                                          {"listening": 6.5, "reading": 6.5, "writing": 6.5, "speaking": 6.5},
                                          ["f-imperial-msc-ielts"], "6.5 in all elements"))
    toefl = _toefl_generic_rule("imp-msc-toefl", lang, 100, 5.0,
                                ["f-imperial-msc-ielts"], "Imperial MSc TOEFL (Higher, PG)")
    if toefl is not None:
        results.append(toefl)
    # --- No admissions test ---
    results.append(_r("imp-msc-test", "NOT_APPLICABLE",
                      "There are normally no admissions tests or interviews for this course.",
                      ["f-imperial-msc-test"]))
    # --- Fee: UK 25,850 / overseas 48,300 per year ---
    results.append(_fee_for_residency(
        "imp-msc-fee", profile.budget, None, "GBP", "per_year",
        {"uk": Decimal("25850"), "overseas": Decimal("48300"), "missing": Decimal("48300")},
        {}, ["f-imperial-msc-fee-overseas", "f-imperial-msc-fee-uk"], "GBP"))
    return results


def evaluate_ucl_msc(profile: StudentProfile, program: dict) -> list[RuleResult]:
    results: list[RuleResult] = []
    mp = profile.masters_profile or MastersProfile()
    # --- Academic: upper second-class in a subject OTHER than CS/IT ---
    field = mp.degree_field
    if field == "computing":
        results.append(_r("ucl-msc-academic", "NOT_MET",
                          "This MSc requires a degree in a subject other than computer science or information technology; a computing degree does not meet it.",
                          ["f-ucl-msc-academic"], observed={"field": field}))
    elif mp.degree_class is None:
        results.append(_r("ucl-msc-academic", "UNKNOWN",
                          "Degree class not supplied; an upper second-class degree is required.", ["f-ucl-msc-academic"]))
    elif mp.degree_class in ("lower_second", "third", "other"):
        results.append(_r("ucl-msc-academic", "NOT_MET",
                          "An upper second-class degree is required.", ["f-ucl-msc-academic"],
                          observed={"degree_class": mp.degree_class}))
    elif mp.maths_alevel_grade is None:
        results.append(_r("ucl-msc-academic", "UNKNOWN",
                          "Upper second-class degree in a non-CS/IT subject, but mathematical skills to at least Mathematics A-level standard have not been evidenced (no A-level Maths grade supplied).",
                          ["f-ucl-msc-academic", "f-ucl-msc-maths"]))
    else:
        results.append(_r("ucl-msc-academic", "MET",
                          "Upper second-class degree in a non-CS/IT subject with mathematics to A-level standard.",
                          ["f-ucl-msc-academic", "f-ucl-msc-maths"],
                          observed={"degree_class": mp.degree_class, "maths_alevel": mp.maths_alevel_grade}))
    # --- Language: no level stated on the course page ---
    results.append(_r("ucl-msc-language", "UNKNOWN",
                      "The course page does not state which UCL English language level applies to this programme, so no language threshold can be assessed. (Third-party reports of Level 2 are not official evidence and were not used.)",
                      ["f-ucl-msc-english-unknown"]))
    # --- Fee: UK 21,500 / international 44,400 per year ---
    results.append(_fee_for_residency(
        "ucl-msc-fee", profile.budget, None, "GBP", "per_year",
        {"uk": Decimal("21500"), "overseas": Decimal("44400"), "missing": Decimal("44400")},
        {}, ["f-ucl-msc-fee-overseas", "f-ucl-msc-fee-uk"], "GBP"))
    return results


_SG_UG_FEE_BANDS = {
    "sg_citizen": Decimal("8300"), "sg_pr": Decimal("11600"),
    "sg_intl_asean": Decimal("18050"), "sg_intl_other": Decimal("21400"),
}
_SG_UG_FEE_UNKNOWN = {
    "sg_intl_nogrant": "Non-subsidised fee band for this programme is not labelled on the official fee table (lab-based S$40,600 vs non-lab-based S$36,350), so the fee cannot be decided.",
    "uk": "UK residency does not map to a Singapore tuition band; tuition-grant status is unknown, so the fee cannot be decided.",
    "overseas": "Tuition-grant status is unknown, so the fee cannot be decided.",
    "missing": "Residency / tuition-grant status not supplied, so the fee cannot be decided.",
}


def evaluate_nus_bcomp(profile: StudentProfile, program: dict) -> list[RuleResult]:
    results: list[RuleResult] = []
    lang = profile.language
    ug = profile.undergrad_profile or UndergradProfile()
    # --- Academic: no fixed minimum published; IGP only ---
    results.append(_r("nus-bcomp-academic", "UNKNOWN",
                      "NUS publishes no fixed A-level/IB minimum for this programme — only the Indicative Grade Profile of admitted students (Common CS Programmes AAA/A at the 10th and 90th percentile). An IGP figure is not a threshold and meeting it does not guarantee admission, so academic eligibility cannot be decided from grades alone.",
                      ["f-nus-bcomp-igp"],
                      observed=_ug_observed(ug)))
    # --- Language ---
    results.append(_ielts_overall_rule("nus-bcomp-language", lang, 6.5,
                                       ["f-nus-bcomp-ielts"], "NUS BComp CS"))
    results.append(_ielts_components_rule("nus-bcomp-language-components", lang,
                                          {"reading": 6.5, "writing": 6.5},
                                          ["f-nus-bcomp-ielts"], "6.5 in Reading and Writing (Listening/Speaking minima not stated)"))
    toefl = _toefl_generic_rule("nus-bcomp-toefl", lang, 92, None,
                                ["f-nus-bcomp-ielts"], "NUS BComp CS TOEFL")
    if toefl is not None:
        results.append(toefl)
    # --- Fee: AY2026/27 bands; without-grant S$39,700 is stated ---
    bands = dict(_SG_UG_FEE_BANDS)
    bands["sg_intl_nogrant"] = Decimal("39700")
    # Round 10, R1: a generic 'overseas' residency is an international
    # applicant with no Singapore residency and no tuition grant claimed
    # — the conservative unsubsidised band. The wizard's sg_* options
    # are the only way to claim a grant band; 'overseas' claims none,
    # and overseas fees are assumed unless UK residency is chosen.
    residency = "sg_intl_nogrant" if ug.residency == "overseas" else ug.residency
    results.append(_fee_for_residency(
        "nus-bcomp-fee", profile.budget, residency, "SGD", "per_year", bands,
        dict(_SG_UG_FEE_UNKNOWN), ["f-nus-bcomp-fee-grant", "f-nus-bcomp-fee-nogrant"], "SGD"))
    return results


def evaluate_ntu_bcomp(profile: StudentProfile, program: dict) -> list[RuleResult]:
    results: list[RuleResult] = []
    lang = profile.language
    ug = profile.undergrad_profile or UndergradProfile()
    # --- Academic: no fixed minimum published; IGP only ---
    results.append(_r("ntu-bcomp-academic", "UNKNOWN",
                      "NTU publishes no fixed A-level/IB minimum for this programme — only the Indicative Grade Profile of admitted students (Computer Science AAB/C at the 10th percentile to AAA/A at the 90th percentile). An IGP figure is not a threshold and meeting it does not guarantee admission, so academic eligibility cannot be decided from grades alone. Minimum subject: Mathematics or Physics at Senior High School level (not collected in the wizard yet).",
                      ["f-ntu-bcomp-igp", "f-ntu-bcomp-subject"],
                      observed=_ug_observed(ug)))
    # --- Language ---
    results.append(_ielts_overall_rule("ntu-bcomp-language", lang, 6.5,
                                       ["f-ntu-bcomp-ielts"], "NTU BComp CS"))
    results.append(_ielts_components_rule("ntu-bcomp-language-components", lang,
                                          {"writing": 6.5, "speaking": 6.5},
                                          ["f-ntu-bcomp-ielts"], "6.5 in Writing and Speaking"))
    toefl = _toefl_generic_rule("ntu-bcomp-toefl", lang, 90, 4.5,
                                ["f-ntu-bcomp-ielts"], "NTU BComp CS TOEFL")
    if toefl is not None:
        results.append(toefl)
    # --- Fee: AY2026/27 bands; non-subsidised band not labelled for CS ---
    bands = dict(_SG_UG_FEE_BANDS)
    bands["sg_intl_nogrant"] = None
    # Round 10, R1: same 'overseas' mapping as NUS (international, no
    # grant claimed -> unsubsidised band). Here the band is None because
    # the table does not label CS lab/non-lab, so the fee stays UNKNOWN
    # with the lab-band reason — never a mismatch.
    residency = "sg_intl_nogrant" if ug.residency == "overseas" else ug.residency
    results.append(_fee_for_residency(
        "ntu-bcomp-fee", profile.budget, residency, "SGD", "per_year", bands,
        dict(_SG_UG_FEE_UNKNOWN), ["f-ntu-bcomp-fee-grant", "f-ntu-bcomp-fee-nogrant"], "SGD"))
    return results


def evaluate_ntu_msai(profile: StudentProfile, program: dict) -> list[RuleResult]:
    results: list[RuleResult] = []
    lang = profile.language
    mp = profile.masters_profile or MastersProfile()
    # --- Academic: honours in CS/CE/related, or bachelor's + 2y experience ---
    field = mp.degree_field
    exp = mp.it_experience_years
    honours = mp.honours
    if field in ("computing", "related") and honours:
        results.append(_r("ntu-msai-academic", "MET",
                          "Good honours degree in computer science, computer engineering or a related discipline with solid mathematical training.",
                          ["f-ntu-msai-academic"], observed={"field": field, "honours": honours}))
    elif field in ("computing", "related") and exp is not None and exp >= 2:
        results.append(_r("ntu-msai-academic", "MET",
                          "Good bachelor's degree in computer science, computer engineering or a related discipline with 2+ years of industry experience.",
                          ["f-ntu-msai-academic"], observed={"field": field, "experience_years": exp}))
    elif field in ("computing", "related"):
        results.append(_r("ntu-msai-academic", "UNKNOWN",
                          "Degree field is in scope but neither honours nor 2+ years of industry experience is evidenced.",
                          ["f-ntu-msai-academic"], observed={"field": field, "experience_years": exp}))
    elif field in ("business", "other"):
        results.append(_r("ntu-msai-academic", "UNKNOWN",
                          "Degree field is outside the stated routes (CS/CE/related); insufficient evidence to reject.",
                          ["f-ntu-msai-academic"], observed={"field": field}))
    else:
        results.append(_r("ntu-msai-academic", "UNKNOWN",
                          "Degree field not supplied.", ["f-ntu-msai-academic"]))
    # --- Language: IELTS >= 6.5 or TOEFL >= 100 / >= 5.0; no components ---
    if lang is None or lang.exam in (None, "none"):
        results.append(_r("ntu-msai-language", "UNKNOWN", "No language test supplied.",
                          ["f-ntu-msai-ielts"]))
    elif lang.exam == "ielts":
        if lang.overall is None:
            results.append(_r("ntu-msai-language", "UNKNOWN", "IELTS overall not supplied.", ["f-ntu-msai-ielts"]))
        elif lang.overall >= 6.5:
            results.append(_r("ntu-msai-language", "MET", f"IELTS overall {lang.overall} meets 6.5.",
                              ["f-ntu-msai-ielts"], observed=lang.overall, threshold={"overall": 6.5}))
        else:
            results.append(_r("ntu-msai-language", "NOT_MET", f"IELTS overall {lang.overall} is below 6.5.",
                              ["f-ntu-msai-ielts"], observed=lang.overall, threshold={"overall": 6.5}))
    elif lang.exam == "toefl":
        toefl = _toefl_generic_rule("ntu-msai-language", lang, 100, 5.0,
                                    ["f-ntu-msai-ielts"], "NTU MSAI TOEFL")
        results.append(toefl)  # type: ignore[arg-type]
    else:
        results.append(_r("ntu-msai-language", "UNKNOWN", f"Unrecognised exam type: {lang.exam}.",
                          ["f-ntu-msai-ielts"]))
    toefl_sup = _toefl_generic_rule("ntu-msai-toefl", lang, 100, 5.0,
                                    ["f-ntu-msai-ielts"], "NTU MSAI TOEFL")
    if lang is not None and lang.exam == "ielts" and toefl_sup is not None:
        results.append(toefl_sup)
    results.append(_r("ntu-msai-language-components", "NOT_APPLICABLE" if lang is not None and lang.exam in ("ielts", "toefl") else "UNKNOWN",
                      "NTU MSAI states no IELTS/TOEFL component minimums (overall minimums only); there is no component requirement to check." if lang is not None and lang.exam in ("ielts", "toefl") else "No language test supplied.",
                      ["f-ntu-msai-ielts"]))
    # --- GRE: optional, no rejection rule ---
    results.append(_r("ntu-msai-gre", "UNKNOWN",
                      "GRE scores are listed as 'Optional' among the required documents. The programme page states no rejection rule for a missing or low GRE score, so this is UNKNOWN, never NOT_MET.",
                      ["f-ntu-msai-gre"],
                      observed={"gre_total": mp.gre_total, "gre_analytical": mp.gre_analytical}))
    # --- Fee: SGD 65,748.80 total incl. GST ---
    results.append(_fee_for_residency(
        "ntu-msai-fee", profile.budget, None, "SGD", "total",
        {"missing": Decimal("65748.80")},
        {}, ["f-ntu-msai-fee"], "SGD"))
    return results


def evaluate(profile: StudentProfile, program: dict) -> list[RuleResult]:
    pid = program.get("id")
    if pid == "ucl-cs-bsc-2026":
        return evaluate_ucl(profile, program)
    if pid == "nus-mcomp-cs":
        return evaluate_nus(profile, program)
    if pid == "imperial-comp-beng-2027":
        return evaluate_imperial_beng(profile, program)
    if pid == "imperial-msc-computing-2027":
        return evaluate_imperial_msc(profile, program)
    if pid == "ucl-cs-msc-2027":
        return evaluate_ucl_msc(profile, program)
    if pid == "nus-bcomp-cs-2027":
        return evaluate_nus_bcomp(profile, program)
    if pid == "ntu-bcomp-cs-2027":
        return evaluate_ntu_bcomp(profile, program)
    if pid == "ntu-msai-2027":
        return evaluate_ntu_msai(profile, program)
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
