"""Generic rule evaluator for expansion (v3) programmes.

The 8 v2 programmes keep their own hand-written evaluators in
domain/eligibility.py (byte-identical behaviour, untouched). Expansion
programmes have no hand-written rules: this module evaluates ONLY the
verified structured data in data/expansions/expansion.json —

- fee: fees.amount + currency + period, compared against the profile
  budget exactly the way v2 does (currency + period must match, else
  UNKNOWN; currencies are never converted; per-credit fees are
  UNKNOWN because the profile has no credit count);
- language: structured IELTS / TOEFL thresholds. Language
  requirements on one programme are ALTERNATIVE routes (an IELTS
  requirement, a TOEFL requirement and a Duolingo requirement are
  separate entries for the same programme), so the overall rule is MET
  when any route the applicant evidenced is met. Thresholds that are
  only Duolingo / PTE / HSK / CEFR are UNKNOWN — the profile has no
  such scores. TOEFL follows the v2 Jan 2026 scale split (an old-scale
  iBT threshold cannot be compared with a new-scale-looking score, and
  a new-scale threshold needs a test date on/after the cutoff);
- academic: A-level thresholds only, and only for the uk_alevel /
  sg_alevel curricula. Gaokao / SAT / IB scores are never converted
  to A-levels. Two structured shapes exist in the data: the string
  form {"a_level": "A*AA"} (ranges such as "A*A*A*-AAB" and
  alternatives such as "A*A*A or A*AAA" are read at their published
  minimum) and the grades form {"grades": ["A*", "A", "A"],
  "maths_grade": "A*"}. Any other academic threshold (GPA, IB total,
  degree class, ATAR, ...) is UNKNOWN.

Everything else is UNKNOWN, never MET on missing data. Rule ids are
exp-fee / exp-language / exp-language-components / exp-academic.
Overall status reuses the existing semantics (any NOT_MET -> NOT_MET;
any UNKNOWN -> PARTIAL_UNKNOWN; else MET) via overall_status().

Promotion (see app/data.py): a programme is matchable only when it
has at least one evaluable rule (fee amount known, or a structured
IELTS/TOEFL language threshold, or an A-level threshold) AND its
degree_level is undergraduate / taught_masters (the wizard has no
track for foundation / joint_honours).
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.schemas import Language, RuleResult, StudentProfile, UndergradProfile
from domain.eligibility import (
    TOEFL_SCALE_CUTOFF,
    _alevel_top3,
    _dec,
    _parse_test_date,
    _plain_number,
    _r,
    _toefl_score,
    effective_curriculum,
)

_GRADE_RANK = {"A*": 5, "A": 4, "B": 3, "C": 2, "D": 1, "E": 0}

_IELTS_COMPONENT_KEYS = ("ielts_listening", "ielts_reading",
                         "ielts_writing", "ielts_speaking")
_BARE_COMPONENT_KEYS = ("listening", "reading", "writing", "speaking")


def _num(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _classify_language_requirement(req: dict) -> str | None:
    """'ielts' | 'toefl' | 'duolingo' | 'pte' | 'hsk' | 'cefr' | 'other'.

    None when the requirement carries no structured threshold at all.
    Classification uses explicit threshold keys first, then the
    requirement id / description prefix (e.g. "...-ielts",
    "TOEFL iBT 90 ..."). The bare "overall" key is meaningless on its
    own — a TOEFL requirement's overall is an iBT score, a Duolingo
    requirement's overall is a Duolingo score — so an unclassified
    requirement is never treated as an IELTS threshold.
    """
    th = req.get("threshold")
    if not isinstance(th, dict):
        return None
    if "ielts_overall" in th or "ielts" in th:
        return "ielts"
    if "toefl_ibt" in th or "toefl_ibt_overall" in th:
        return "toefl"
    rid = str(req.get("id", "")).lower()
    desc = str(req.get("description", ""))[:40].lower()
    for key in ("ielts", "toefl", "duolingo", "pte", "hsk", "cefr"):
        if key in rid or key in desc:
            return key
    return "other"


def _ielts_overall_of(th: dict, kind: str) -> float | int | None:
    if kind != "ielts":
        return None
    for key in ("ielts_overall", "ielts", "overall"):
        v = _num(th.get(key))
        if v is not None:
            return v
    return None


def _toefl_overall_of(th: dict, kind: str) -> float | int | None:
    if kind != "toefl":
        return None
    for key in ("toefl_ibt_overall", "toefl_ibt", "overall"):
        v = _num(th.get(key))
        if v is not None:
            return v
    return None


def _ielts_component_sets(th: dict, kind: str) -> list[dict[str, float]]:
    """Component-minimum sets for one IELTS-classified threshold.

    Each set is one alternative way to satisfy the components: a plain
    each-component minimum gives one set; a three-components + remaining
    minimum (Edinburgh DS MSc) gives one set with a special marker.
    Bare listening/reading/writing/speaking keys with values <= 9 are
    IELTS components; values > 9 are TOEFL section scores (not
    evaluable — the profile has no TOEFL component scores).
    Returns [] when the threshold states no IELTS component minimum.
    """
    if kind != "ielts":
        return []
    sets: list[dict[str, float]] = []
    each = (_num(th.get("each_component")) or _num(th.get("ielts_min_each"))
            or _num(th.get("min_section")))
    if each is not None:
        sets.append({k: each for k in
                     ("listening", "reading", "writing", "speaking")})
    three = _num(th.get("ielts_min_three_components"))
    remaining = _num(th.get("ielts_min_remaining"))
    if three is not None and remaining is not None:
        sets.append({"__three__": three, "__remaining__": remaining})
    per: dict[str, float] = {}
    for key in _IELTS_COMPONENT_KEYS:
        v = _num(th.get(key))
        if v is not None and v <= 9:
            per[key[len("ielts_"):]] = v
    for key in _BARE_COMPONENT_KEYS:
        v = _num(th.get(key))
        if v is not None and v <= 9:
            per.setdefault(key, v)
    if per:
        sets.append(per)
    return sets


def _has_toefl_section_minima(th: dict, kind: str) -> bool:
    if kind != "toefl":
        return False
    if any(k in th for k in ("toefl_ibt_min_each", "toefl_ibt_min_other",
                             "toefl_ibt_writing")):
        return True
    return any(_num(th.get(k)) is not None and _num(th.get(k)) > 9  # type: ignore[operator]
               for k in _BARE_COMPONENT_KEYS)


def _language_thresholds(program: dict) -> dict[str, Any]:
    """Collect the evaluable language thresholds of one programme."""
    ielts_overalls: list[float] = []
    toefl_overalls: list[float] = []
    component_sets: list[dict[str, float]] = []
    has_toefl_sections = False
    has_any_language_req = False
    has_unassessable_only = False
    for req in program.get("requirements", []):
        if req.get("category") != "language":
            continue
        has_any_language_req = True
        th = req.get("threshold")
        if not isinstance(th, dict):
            continue
        kind = _classify_language_requirement(req)
        if kind in ("duolingo", "pte", "hsk", "cefr", "other"):
            has_unassessable_only = True
            continue
        io = _ielts_overall_of(th, kind or "")
        if io is not None:
            ielts_overalls.append(float(io))
        to = _toefl_overall_of(th, kind or "")
        if to is not None:
            toefl_overalls.append(float(to))
        component_sets.extend(_ielts_component_sets(th, kind or ""))
        if _has_toefl_section_minima(th, kind or ""):
            has_toefl_sections = True
    return {"ielts_overalls": ielts_overalls,
            "toefl_overalls": toefl_overalls,
            "component_sets": component_sets,
            "has_toefl_sections": has_toefl_sections,
            "has_any_language_req": has_any_language_req,
            "has_unassessable_only": has_unassessable_only}


def _toefl_route(score: float, threshold: float,
                 test_date: Any) -> str:
    """'met' | 'below' | 'unknown' for one TOEFL threshold.

    Thresholds <= 6 are new-scale (1-6) thresholds: they can only be
    compared when the test date is on/after the Jan 2026 cutoff.
    Thresholds > 6 are old-scale iBT thresholds: a new-scale-looking
    score (<= 6) cannot be compared with them.
    """
    if threshold <= 6:
        if test_date is None or test_date < TOEFL_SCALE_CUTOFF:
            return "unknown"
        return "met" if score >= threshold else "below"
    if score <= 6:
        return "unknown"
    return "met" if score >= threshold else "below"


def _parse_alevel_triples(text: str) -> list[list[int]]:
    """All grade triples stated in an A-level requirement string.

    "A*AA" -> [[5,4,4]]; "A*A*A or A*AAA" -> [[5,5,5],[5,4,4]];
    "A*A*A*-AAB" -> [[5,5,5],[4,4,3]] (a range: both ends listed).
    The published minimum is min() of the triples.
    """
    found = re.findall(r"A\*|[A-E]", text.upper())
    triples: list[list[int]] = []
    for i in range(0, len(found) - 2, 3):
        ranks = sorted((_GRADE_RANK[g] for g in found[i:i + 3]), reverse=True)
        triples.append(ranks)
    return triples


def _alevel_requirements(program: dict) -> list[dict[str, Any]]:
    """Structured A-level requirements: string form and grades form."""
    out: list[dict[str, Any]] = []
    for req in program.get("requirements", []):
        if req.get("category") != "academic":
            continue
        th = req.get("threshold")
        if not isinstance(th, dict):
            continue
        if isinstance(th.get("a_level"), str) and th["a_level"].strip():
            triples = _parse_alevel_triples(th["a_level"])
            if triples:
                out.append({"kind": "string", "minimum": min(triples),
                            "source_ids": list(req.get("source_ids") or []),
                            "req_id": req.get("id")})
        grades = th.get("grades")
        if isinstance(grades, list) and len(grades) >= 3 and all(
                isinstance(g, str) and g.upper() in _GRADE_RANK for g in grades):
            ranks = sorted((_GRADE_RANK[g.upper()] for g in grades),
                           reverse=True)[:3]
            maths = th.get("maths_grade")
            maths_rank = _GRADE_RANK.get(str(maths).upper()) \
                if isinstance(maths, str) else None
            out.append({"kind": "grades", "minimum": ranks,
                        "maths_rank": maths_rank,
                        "source_ids": list(req.get("source_ids") or []),
                        "req_id": req.get("id")})
    return out


def evaluable_rules(program: dict) -> dict[str, bool]:
    """Which generic rules can be evaluated for this programme."""
    fees = program.get("fees") or {}
    amount = fees.get("amount")
    fee = (isinstance(amount, (int, float)) and not isinstance(amount, bool)
           and fees.get("period") in ("per_year", "total"))
    lang = _language_thresholds(program)
    language = bool(lang["ielts_overalls"] or lang["toefl_overalls"]
                    or lang["component_sets"])
    academic = bool(_alevel_requirements(program))
    return {"fee": fee, "language": language, "academic": academic}


def _fee_rule(profile: StudentProfile, program: dict) -> RuleResult:
    fees = program.get("fees") or {}
    amount = fees.get("amount")
    currency = fees.get("currency") or ""
    period = fees.get("period") or ""
    fee_reqs = [r for r in program.get("requirements", [])
                if r.get("category") == "fee"]
    evidence = [s for r in fee_reqs for s in (r.get("source_ids") or [])]
    threshold = ({"amount": _plain_number(amount), "currency": currency,
                  "period": period}
                 if isinstance(amount, (int, float)) else None)
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        return _r("exp-fee", "UNKNOWN",
                  "No tuition fee amount is stated on the official programme page, so the fee cannot be compared with the budget.",
                  evidence, threshold=threshold)
    if period == "per_credit":
        return _r("exp-fee", "UNKNOWN",
                  f"Tuition is {currency} {amount:g} per credit; the profile has no credit count, so a per-credit fee cannot be compared with the budget.",
                  evidence, threshold=threshold)
    budget = profile.budget
    if budget is None or budget.amount is None:
        return _r("exp-fee", "UNKNOWN", "No budget supplied.", evidence,
                  threshold=threshold)
    if budget.currency != currency or budget.period != period:
        return _r("exp-fee", "UNKNOWN",
                  f"Budget currency/period ({budget.currency} {budget.period}) does not match {currency} {period}, so it cannot be compared with the fee.",
                  evidence,
                  observed={"amount": _plain_number(budget.amount),
                            "currency": budget.currency,
                            "period": budget.period},
                  threshold=threshold)
    fee = _dec(amount)
    got = _dec(budget.amount)
    if got >= fee:
        return _r("exp-fee", "MET",
                  f"Budget {currency} {got:g} {period} meets the {currency} {fee:g} {period} tuition fee.",
                  evidence, observed=_plain_number(got), threshold=threshold)
    return _r("exp-fee", "NOT_MET",
              f"Budget {currency} {got:g} {period} is below the {currency} {fee:g} {period} tuition fee.",
              evidence, observed=_plain_number(got), threshold=threshold)


def _language_rules(profile: StudentProfile, program: dict,
                    thresholds: dict[str, Any]) -> list[RuleResult]:
    results: list[RuleResult] = []
    lang = profile.language
    evidence: list[str] = []
    for req in program.get("requirements", []):
        if req.get("category") == "language":
            evidence.extend(s for s in (req.get("source_ids") or [])
                            if s not in evidence)
    ielts_overalls: list[float] = thresholds["ielts_overalls"]
    toefl_overalls: list[float] = thresholds["toefl_overalls"]
    # --- Overall: MET when any evidenced route is met. ---
    ielts_score = (lang.overall if lang is not None
                   and lang.exam == "ielts" else None)
    toefl_score = _toefl_score(lang)
    test_date = _parse_test_date(lang.test_date if lang else None)
    met = False
    assessable_failed = False
    relevant_supplied = False
    if ielts_score is not None:
        if ielts_overalls:
            relevant_supplied = True
            if any(ielts_score >= t for t in ielts_overalls):
                met = True
            else:
                assessable_failed = True
    if toefl_score is not None and not met:
        if toefl_overalls:
            relevant_supplied = True
            verdicts = [_toefl_route(toefl_score, t, test_date)
                        for t in toefl_overalls]
            if "met" in verdicts:
                met = True
            elif "below" in verdicts:
                assessable_failed = True
            # "unknown" verdicts (scale/date) leave the route undecided.
    if met:
        detail = ("Language requirement met by a supplied test score "
                  "(IELTS or TOEFL route).")
        results.append(_r("exp-language", "MET", detail, evidence,
                          observed={"ielts_overall": ielts_score,
                                    "toefl_overall": toefl_score},
                          threshold={"ielts_overall": ielts_overalls or None,
                                     "toefl_overall": toefl_overalls or None}))
    elif assessable_failed:
        results.append(_r("exp-language", "NOT_MET",
                          "A supplied test score is below the stated IELTS/TOEFL minimum for this programme.",
                          evidence,
                          observed={"ielts_overall": ielts_score,
                                    "toefl_overall": toefl_score},
                          threshold={"ielts_overall": ielts_overalls or None,
                                     "toefl_overall": toefl_overalls or None}))
    elif not relevant_supplied:
        if not ielts_overalls and not toefl_overalls \
                and not thresholds["component_sets"]:
            reason = ("This programme states a language requirement, but no "
                      "IELTS/TOEFL score is stated on the official page, so "
                      "it cannot be assessed from a test score.")
        elif toefl_score is not None and toefl_overalls:
            reason = ("TOEFL supplied but no valid test date. The Jan 2026 "
                      "scale split cannot be applied, so TOEFL is UNKNOWN, "
                      "never converted.")
        elif lang is None or lang.exam in (None, "none"):
            reason = "No language test supplied."
        elif ielts_score is not None:
            reason = ("IELTS supplied, but this programme states no IELTS "
                      "minimum (only TOEFL / Duolingo / other routes), so "
                      "the supplied score is not evidence for any stated route.")
        elif toefl_score is not None:
            reason = ("TOEFL supplied, but this programme states no TOEFL "
                      "minimum, so the supplied score is not evidence for "
                      "any stated route.")
        else:
            reason = ("No IELTS/TOEFL score supplied that matches a stated "
                      "route (Duolingo / PTE / HSK / CEFR routes cannot be "
                      "assessed from this profile).")
        results.append(_r("exp-language", "UNKNOWN", reason, evidence,
                          observed={"ielts_overall": ielts_score,
                                    "toefl_overall": toefl_score},
                          threshold={"ielts_overall": ielts_overalls or None,
                                     "toefl_overall": toefl_overalls or None}))
    else:
        # A relevant test was supplied but its route could not be
        # assessed (TOEFL scale/date): UNKNOWN, never a failure.
        if toefl_score is not None and toefl_score <= 6:
            reason = ("The supplied TOEFL score is 6 or below, so it "
                      "cannot be placed on the pre/post-Jan-2026 scale "
                      "against the stated iBT minimum; TOEFL is UNKNOWN, "
                      "never converted.")
        else:
            reason = ("TOEFL supplied but no valid test date. The Jan 2026 "
                      "scale split cannot be applied, so TOEFL is UNKNOWN, "
                      "never converted.")
        results.append(_r("exp-language", "UNKNOWN", reason, evidence,
                          observed={"ielts_overall": ielts_score,
                                    "toefl_overall": toefl_score},
                          threshold={"ielts_overall": ielts_overalls or None,
                                     "toefl_overall": toefl_overalls or None}))
    # --- Components: IELTS components only (the profile has no TOEFL
    # component scores). NOT_APPLICABLE when no component minimum is
    # stated at all and a test was supplied. ---
    sets: list[dict[str, float]] = thresholds["component_sets"]
    if not sets:
        if lang is None or lang.exam in (None, "none"):
            results.append(_r("exp-language-components", "UNKNOWN",
                              "No language test supplied.", evidence))
        elif thresholds["has_toefl_sections"]:
            results.append(_r("exp-language-components", "UNKNOWN",
                              "This programme states TOEFL section minimums only; the profile has no TOEFL component scores, so they cannot be assessed.",
                              evidence))
        else:
            results.append(_r("exp-language-components", "NOT_APPLICABLE",
                              "This programme states no IELTS/TOEFL component minimum (overall minimum only); there is no component requirement to check.",
                              evidence))
        return results
    if lang is None or lang.exam != "ielts":
        results.append(_r("exp-language-components", "UNKNOWN",
                          "TOEFL supplied; IELTS components do not apply. TOEFL is assessed under its own rule.",
                          evidence))
        return results
    comps = {"listening": lang.listening, "reading": lang.reading,
             "writing": lang.writing, "speaking": lang.speaking}
    missing = [k for k, v in comps.items() if v is None]
    if missing:
        results.append(_r("exp-language-components", "UNKNOWN",
                          f"Missing component score(s): {', '.join(missing)}.",
                          evidence, observed=comps))
        return results

    def _set_met(s: dict[str, float]) -> bool:
        if "__three__" in s:
            above = sum(1 for k in ("listening", "reading", "writing",
                                    "speaking")
                        if comps[k] >= s["__three__"])  # type: ignore[operator]
            return above >= 3 and all(comps[k] >= s["__remaining__"]
                                      for k in comps)  # type: ignore[operator]
        return all(comps[k] >= v for k, v in s.items())

    if any(_set_met(s) for s in sets):
        results.append(_r("exp-language-components", "MET",
                          "Every required IELTS component meets its minimum.",
                          evidence, observed=comps,
                          threshold=sets[0] if len(sets) == 1 else None))
    else:
        low = {k: v for k, v in comps.items()
               if any(k in s and v < s[k] for s in sets if "__three__" not in s)}
        results.append(_r("exp-language-components", "NOT_MET",
                          f"Component(s) below the minimum: {low}.",
                          evidence, observed=comps,
                          threshold=sets[0] if len(sets) == 1 else None))
    return results


def _academic_rule(profile: StudentProfile, program: dict,
                   alevels: list[dict[str, Any]]) -> RuleResult:
    evidence: list[str] = []
    for req in program.get("requirements", []):
        if req.get("category") == "academic":
            evidence.extend(s for s in (req.get("source_ids") or [])
                            if s not in evidence)
    if profile.application_track == "taught_masters":
        return _r("exp-academic", "UNKNOWN",
                  "A-level thresholds apply to undergraduate entry; this is a taught-masters programme, so no A-level rule can be assessed here.",
                  evidence)
    ug = profile.undergrad_profile or UndergradProfile()
    curriculum = effective_curriculum(ug)
    if not alevels:
        return _r("exp-academic", "UNKNOWN",
                  "No A-level threshold is stated for this programme (the academic requirement uses GPA / IB / degree-class or free-text criteria), so academic eligibility cannot be decided from grades alone.",
                  evidence)
    if curriculum not in ("uk_alevel", "sg_alevel"):
        return _r("exp-academic", "UNKNOWN",
                  "An A-level threshold is stated, but this applicant's curriculum is not A-level; A-level thresholds are only assessed for UK / Singapore A-level applicants, and other scores are never converted to A-levels.",
                  evidence)
    top = _alevel_top3(ug.a_level_grades)
    if top is None:
        return _r("exp-academic", "UNKNOWN",
                  "A-level grades not supplied (three grades are needed).",
                  evidence)
    maths_rank = _GRADE_RANK.get((ug.a_level_maths_grade or "").upper())
    for req in alevels:
        if top < req["minimum"]:
            continue
        if req["kind"] == "grades":
            if req.get("maths_rank") is not None:
                if maths_rank is None:
                    return _r("exp-academic", "UNKNOWN",
                              "A-level grades meet the stated grades, but the required Mathematics grade cannot be checked (no A-level Maths grade supplied).",
                              evidence)
                if maths_rank < req["maths_rank"]:
                    continue
        return _r("exp-academic", "MET",
                  "A-level grades meet the stated A-level threshold.",
                  evidence, observed={"grades": ug.a_level_grades,
                                      "maths": ug.a_level_maths_grade},
                  threshold={"a_level": req["minimum"]})
    return _r("exp-academic", "NOT_MET",
              "A-level grades do not meet the stated A-level threshold.",
              evidence, observed={"grades": ug.a_level_grades,
                                  "maths": ug.a_level_maths_grade})


def evaluate_expansion(profile: StudentProfile, program: dict) -> list[RuleResult]:
    """Evaluate one expansion programme against a profile.

    Only called for promoted (matchable) programmes. Every rule with
    verified structured data is evaluated; everything else is UNKNOWN.
    Test / other / fee-application requirements and deadlines are not
    rules and are never evaluated.
    """
    results: list[RuleResult] = []
    results.append(_fee_rule(profile, program))
    thresholds = _language_thresholds(program)
    if thresholds["has_any_language_req"]:
        results.extend(_language_rules(profile, program, thresholds))
    alevels = _alevel_requirements(program)
    has_academic_req = any(r.get("category") == "academic"
                           for r in program.get("requirements", []))
    if has_academic_req:
        results.append(_academic_rule(profile, program, alevels))
    return results
