"""Adapter between the frontend (wizard) contract and the backend rules engine.

Why this exists (Day-1 integration fix, 2026-11-24): the backend was built
against single-program requests with a nested StudentProfile
({application_track, undergrad_profile, language, budget}), while the
frontend wizard sends a flat profile ({track, alevels, ieltsOverall, ...})
with program_ids (plural) and expects a multi-program response
({evaluation_id, results: [{programId, eligibilitySummary, ruleResults}]}).

This module translates WITHOUT changing any rule logic: the pure engine in
domain/eligibility.py is the only place rules live. Assumptions are
documented here and in DECISIONS.md, never hidden:

- Wizard budget is per-year for undergraduate (GBP) and total for taught
  masters (SGD); the wizard sets budgetCurrency accordingly.
- A-level grades arrive as a string like "A*A*A"; parsed with a regex.
- Masters degree field is classified from free text: computing / business /
  related / other; honours detected from the words honours/honors.
- Evidence ids from the rules engine are manifest fact ids (f-ucl-ielts,
  ...); the frontend evidence drawer looks sources up by its own source ids,
  so they are mapped here (FACT_TO_SOURCE).
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.data import DATA_DIR, DATA_VERSION, EXPANSION_PROGRAMS
from app.schemas import (Budget, Language, MastersProfile, RuleResult,
                         StudentProfile, UndergradProfile)

RULES_VERSION = "rules-v2-2026-11-25"

# Verified expected text per rule id (same facts as data/versions/v1).
EXPECTED: dict[str, str] = {
    "ucl-ielts-overall": "IELTS overall 6.5",
    "ucl-ielts-components": "IELTS minimum 6.0 in each component",
    "ucl-toefl": "TOEFL iBT Level 1: 92 (tests before 21 Jan 2026) or 4.5 on the new scale (tests from 21 Jan 2026)",
    "ucl-gcse": "GCSE English and Maths at grade C/4 or above",
    "ucl-academic": "A*A*A with A* in Maths/Further Maths, or IB 40 with 20 HL points incl. HL Maths grade 7",
    "ucl-tara": "TARA required for the 2026 cycle (no score threshold stated)",
    "ucl-fee": "GBP 46,700 per year (overseas, 2026/27)",
    "nus-language": "IELTS min 6.0 overall (no component minimum stated) or TOEFL iBT min 90",
    "nus-toefl": "TOEFL iBT minimum 90 (supplementary; IELTS also supplied)",
    "nus-language-components": "No IELTS component minimum stated",
    "nus-academic": "Good honours degree in computing, or related/business degree + 2 years IT experience",
    "nus-gre-gmat": "GRE 320 + 3.5 analytical or GMAT 650+ (no rejection rule stated for a missing or low score)",
    "nus-fee": "SGD 69,215 total incl. 9% GST",
    "fixture-writing": "IELTS writing 6.0 (fixture, synthetic)",
    "imp-beng-academic": "A*A*A or A*AAA at A level incl. A* in Maths, or IB 41 with HL Maths 7 and another HL 7",
    "imp-beng-language": "IELTS 6.5 overall, min 6.0 in all elements (Standard)",
    "imp-beng-language-components": "IELTS minimum 6.0 in all elements",
    "imp-beng-toefl": "TOEFL iBT 92 overall, min 20 in all elements (before 21 Jan 2026) or 4.5 on the new scale",
    "imp-beng-tmua": "TMUA required (no score threshold stated)",
    "imp-beng-fee": "Home GBP 10,050/yr or overseas GBP 47,800/yr (Oct 2027)",
    "imp-msc-academic": "First-Class degree in a subject without substantial Computing content",
    "imp-msc-language": "IELTS 7.0 overall, min 6.5 in all elements (Higher, PG)",
    "imp-msc-language-components": "IELTS minimum 6.5 in all elements",
    "imp-msc-toefl": "TOEFL iBT 100 overall, min 22 in all elements (before 21 Jan 2026) or 5.0 on the new scale",
    "imp-msc-test": "Normally no admissions tests or interviews",
    "imp-msc-fee": "Home GBP 25,850 or overseas GBP 48,300 per year (Oct 2027)",
    "ucl-msc-academic": "Upper second-class degree in a subject other than CS/IT, maths to A-level standard",
    "ucl-msc-language": "No English language level stated on the course page",
    "ucl-msc-fee": "UK GBP 21,500/yr or international GBP 44,400/yr (2027/28)",
    "nus-bcomp-academic": "No fixed minimum published; Indicative Grade Profile AAA/A (admitted students)",
    "nus-bcomp-language": "IELTS 6.5 overall, 6.5 in Reading and Writing",
    "nus-bcomp-language-components": "IELTS 6.5 in Reading and Writing (Listening/Speaking minima not stated)",
    "nus-bcomp-toefl": "TOEFL iBT 92-93",
    "nus-bcomp-fee": "AY2026/27 rates: SC S$8,300; SPR S$11,600; IS with grant S$18,050 (ASEAN) / S$21,400; IS without grant S$39,700",
    "ntu-bcomp-academic": "No fixed minimum published; Indicative Grade Profile AAB/C (10th) to AAA/A (90th)",
    "ntu-bcomp-language": "IELTS 6.5 overall, 6.5 Writing, 6.5 Speaking",
    "ntu-bcomp-language-components": "IELTS 6.5 in Writing and Speaking",
    "ntu-bcomp-toefl": "TOEFL total 90 (before 21 Jan 2026) or 4.5 on the new scale",
    "ntu-bcomp-fee": "AY2026/27 rates: SC S$8,300; SPR S$11,600; ASEAN IS S$18,050; other IS S$21,400",
    "ntu-msai-academic": "Good honours in CS/CE/related with solid maths, or good bachelor's + 2 years industry experience",
    "ntu-msai-language": "IELTS >= 6.5 or TOEFL iBT >= 100 / >= 5.0 or MOI certification; no component minimums",
    "ntu-msai-language-components": "No IELTS/TOEFL component minimums stated",
    "ntu-msai-toefl": "TOEFL iBT >= 100 (before 21 Jan 2026) or >= 5.0 on the new scale",
    "ntu-msai-gre": "GRE optional; no rejection rule for a missing or low score",
    "ntu-msai-fee": "SGD 65,748.80 total incl. 9% GST",
    # Generic expansion rules (Day 3, round 6): thresholds come from the
    # programme's own verified requirements in expansion.json, so the
    # expected text is the rule detail itself (see rule_to_frontend
    # fallback); these entries keep the short display form consistent.
    "exp-fee": "Tuition fee as stated on the official programme page",
    "exp-language": "IELTS / TOEFL minimum as stated on the official programme page",
    "exp-language-components": "IELTS component minimums as stated on the official programme page",
    "exp-academic": "A-level threshold as stated on the official programme page",
}

# Manifest fact id -> frontend source id (frontend/src/lib/programs.ts).
FACT_TO_SOURCE: dict[str, str] = {
    "f-ucl-alevel": "ucl-cs-entry",
    "f-ucl-ib": "ucl-cs-entry",
    "f-ucl-gcse": "ucl-cs-entry",  # forward reference; v1 manifest has no
    # dedicated GCSE fact yet (DECISIONS #45) — the requirement is on the
    # ucl-bsc page; the v2 manifest must add f-ucl-gcse.
    "f-ucl-tara": "ucl-cs-entry",
    "f-ucl-ielts": "ucl-cs-english",
    "f-ucl-fee-overseas": "ucl-cs-fees",
    "f-ucl-name": "ucl-cs-entry",
    "f-ucl-ucas": "ucl-cs-entry",
    "f-ucl-deadline": "ucl-cs-entry",
    "f-ucl-duration": "ucl-cs-entry",
    "f-nus-academic": "nus-mcomp-admissions",
    "f-nus-ielts": "nus-mcomp-admissions",
    "f-nus-toefl": "nus-mcomp-admissions",
    "f-nus-gre": "nus-mcomp-gre",
    "f-nus-fee": "nus-mcomp-fees",
    "f-nus-appfee": "nus-mcomp-fees",
    "f-nus-deadline-unknown": "nus-mcomp-admissions",
    "f-nus-name": "nus-mcomp-admissions",
    "f-nus-intake": "nus-mcomp-admissions",
    "f-imperial-beng-name": "imperial-beng-entry",
    "f-imperial-beng-deadline": "imperial-beng-entry",
    "f-imperial-beng-fee-overseas": "imperial-beng-fees",
    "f-imperial-beng-fee-uk": "imperial-beng-fees",
    "f-imperial-beng-alevel": "imperial-beng-entry",
    "f-imperial-beng-ib": "imperial-beng-entry",
    "f-imperial-beng-english-level": "imperial-beng-english",
    "f-imperial-beng-ielts": "imperial-beng-english",
    "f-imperial-beng-tmua": "imperial-beng-entry",
    "f-imperial-msc-name": "imperial-msc-entry",
    "f-imperial-msc-deadline": "imperial-msc-entry",
    "f-imperial-msc-fee-overseas": "imperial-msc-fees",
    "f-imperial-msc-fee-uk": "imperial-msc-fees",
    "f-imperial-msc-academic": "imperial-msc-entry",
    "f-imperial-msc-academic-detail": "imperial-msc-entry",
    "f-imperial-msc-english-level": "imperial-msc-english",
    "f-imperial-msc-ielts": "imperial-msc-english",
    "f-imperial-msc-test": "imperial-msc-entry",
    "f-imperial-msc-appfee-unknown": "imperial-msc-entry",
    "f-ucl-msc-name": "ucl-msc-entry",
    "f-ucl-msc-deadline": "ucl-msc-entry",
    "f-ucl-msc-fee-overseas": "ucl-msc-fees",
    "f-ucl-msc-fee-uk": "ucl-msc-fees",
    "f-ucl-msc-appfee": "ucl-msc-fees",
    "f-ucl-msc-academic": "ucl-msc-entry",
    "f-ucl-msc-maths": "ucl-msc-entry",
    "f-ucl-msc-english-unknown": "ucl-msc-english",
    "f-ucl-msc-level2-definition": "ucl-msc-english",
    "f-nus-bcomp-name": "nus-bcomp-entry",
    "f-nus-bcomp-duration": "nus-bcomp-entry",
    "f-nus-bcomp-deadline": "nus-bcomp-entry",
    "f-nus-bcomp-fee-nogrant": "nus-bcomp-fees",
    "f-nus-bcomp-fee-grant": "nus-bcomp-fees",
    "f-nus-bcomp-appfee": "nus-bcomp-fees",
    "f-nus-bcomp-igp": "nus-bcomp-entry",
    "f-nus-bcomp-common-pool": "nus-bcomp-entry",
    "f-nus-bcomp-ielts": "nus-bcomp-english",
    "f-ntu-bcomp-name": "ntu-bcomp-entry",
    "f-ntu-bcomp-deadline": "ntu-bcomp-entry",
    "f-ntu-bcomp-fee-grant": "ntu-bcomp-fees",
    "f-ntu-bcomp-fee-nogrant": "ntu-bcomp-fees",
    "f-ntu-bcomp-appfee": "ntu-bcomp-fees",
    "f-ntu-bcomp-igp": "ntu-bcomp-entry",
    "f-ntu-bcomp-subject": "ntu-bcomp-entry",
    "f-ntu-bcomp-ielts": "ntu-bcomp-english",
    "f-ntu-msai-name": "ntu-msai-entry",
    "f-ntu-msai-duration": "ntu-msai-entry",
    "f-ntu-msai-deadline-unknown": "ntu-msai-entry",
    "f-ntu-msai-fee": "ntu-msai-fees",
    "f-ntu-msai-academic": "ntu-msai-entry",
    "f-ntu-msai-ielts": "ntu-msai-english",
    "f-ntu-msai-gre": "ntu-msai-entry",
    # Curriculum-branch facts (fix 2026-11-25, DECISIONS #67): UCL China
    # page (no Gaokao route) and Imperial's accepted-qualifications page
    # (USA AP standard; no China entry).
    "f-ucl-china-gaokao": "ucl-china-entry",
    "f-imperial-usa-ap": "imperial-accepted-qualifications",
    "f-imperial-china-none": "imperial-accepted-qualifications",
}


def source_manifest_hash() -> str:
    path = Path(DATA_DIR) / "source-manifest.json"
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Expansion source ids (round 6): requirement source ids on expansion
# programmes pass through rule_to_frontend unchanged (see above).
_EXPANSION_SOURCE_IDS: frozenset[str] = frozenset(
    s.get("id")
    for p in EXPANSION_PROGRAMS.values()
    for s in (p.get("sources") or [])
    if s.get("id"))


def _num(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_alevels(text: Any) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        return []
    return [g.upper() for g in re.findall(r"A\*|[A-E]", text.upper())]


def _classify_degree(text: Any) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    t = text.lower()
    if re.search(r"comput|software|information system|information technolog|data science", t):
        return "computing"
    if re.search(r"business|management|economics|finance|accounting|marketing", t):
        return "business"
    if re.search(r"engineer|math|statistic|physics|chemistry|biology|science", t):
        return "related"
    return "other"


def _residency(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip().lower()
    if v in ("uk", "home", "domestic"):
        return "uk"
    if v in ("overseas", "international"):
        return "overseas"
    if v in ("sg_citizen", "sg-citizen", "singapore citizen", "sc"):
        return "sg_citizen"
    if v in ("sg_pr", "sg-pr", "singapore pr", "spr"):
        return "sg_pr"
    if v in ("sg_intl_asean", "sg-intl-asean", "asean"):
        return "sg_intl_asean"
    if v in ("sg_intl_other", "sg-intl-other"):
        return "sg_intl_other"
    if v in ("sg_intl_nogrant", "sg-intl-nogrant", "no grant", "non-subsidised", "nonsubsidised"):
        return "sg_intl_nogrant"
    return None


def _degree_class(text: Any, explicit: Any = None) -> str | None:
    if isinstance(explicit, str) and explicit.strip():
        v = explicit.strip().lower()
        if v in ("first", "upper_second", "lower_second", "third", "other"):
            return v
    if not isinstance(text, str) or not text.strip():
        return None
    t = text.lower()
    if re.search(r"first[- ]class|\b1st\b|first honours", t):
        return "first"
    if re.search(r"upper second|2:1|\b2\.1\b|second class upper", t):
        return "upper_second"
    if re.search(r"lower second|2:2|\b2\.2\b", t):
        return "lower_second"
    if re.search(r"third|\b3rd\b", t):
        return "third"
    return None


def _grade_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().upper()
    return s or None


def _int_or_none(value: Any) -> int | None:
    n = _num(value)
    return int(n) if n is not None else None


def _curriculum(value: Any, grades: list[str], ib_total: int | None) -> str | None:
    """Wizard curriculum value, or inferred from the grades supplied.

    A valid explicit value wins. Legacy flat profiles without a
    curriculum keep the old inference (grades -> uk_alevel, IB total ->
    ib), so existing tests and API clients keep working.
    """
    if isinstance(value, str) and value.strip().lower() in (
            "cn_gaokao", "uk_alevel", "ib", "usa", "sg_alevel", "other"):
        return value.strip().lower()
    if grades:
        return "uk_alevel"
    if ib_total is not None:
        return "ib"
    return None


def _parse_ap_grades(value: Any) -> list[int] | None:
    """AP grades as a list of ints 1-5, from a list or a string like
    "5,5,5,4,4". Values outside 1-5 are dropped, never rescaled."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        nums = [_num(v) for v in value]
    elif isinstance(value, str):
        nums = [_num(t) for t in value.replace(";", ",").split(",")]
    else:
        return None
    grades = [int(n) for n in nums if n is not None and 1 <= n <= 5]
    return grades or None


def flat_to_student(d: dict) -> StudentProfile:
    """Convert the frontend wizard's flat profile to a StudentProfile.

    Day 2: maps the new wizard fields (ibTotal, ibHlMaths, ibHlTotal,
    gcseEnglish, gcseMaths, residency, intakeYear, testDate,
    graduationStatus, itExperienceYears, toefl). IELTS and TOEFL are BOTH
    passed through when both are present — TOEFL is never silently dropped
    (DECISIONS #36).

    Fix 2026-11-25 (DECISIONS #66): maps the wizard's first step,
    curriculum (cn_gaokao | uk_alevel | ib | usa | sg_alevel | other),
    plus Gaokao / SAT / ACT / AP fields. qualification_type is derived
    from the curriculum so the engine's branch logic and the legacy
    qualification_type inference stay consistent.
    """
    track = d.get("track") or ""
    ielts_fields = ("ieltsOverall", "ieltsListening", "ieltsReading", "ieltsWriting", "ieltsSpeaking")
    has_ielts = any(_num(d.get(k)) is not None for k in ielts_fields)
    has_toefl = _num(d.get("toefl")) is not None
    test_date = d.get("testDate") or d.get("ieltsTestDate") or d.get("toeflTestDate") or None
    if isinstance(test_date, str):
        test_date = test_date.strip() or None
    else:
        test_date = None
    if has_ielts:
        language = Language(exam="ielts", overall=_num(d.get("ieltsOverall")),
                            listening=_num(d.get("ieltsListening")),
                            reading=_num(d.get("ieltsReading")),
                            writing=_num(d.get("ieltsWriting")),
                            speaking=_num(d.get("ieltsSpeaking")),
                            test_date=test_date,
                            toefl_overall=_num(d.get("toefl")) if has_toefl else None)
    elif has_toefl:
        language = Language(exam="toefl", overall=_num(d.get("toefl")),
                            test_date=test_date)
    else:
        language = Language(exam="none", test_date=test_date)

    budget_amount = _num(d.get("budget"))
    budget = Budget(amount=budget_amount,
                    currency=d.get("budgetCurrency") or ("GBP" if track == "undergraduate" else "SGD"),
                    period="per_year" if track == "undergraduate" else "total")

    intake_year = _int_or_none(d.get("intakeYear") or d.get("targetIntake"))
    undergrad = None
    masters = None
    if track == "undergraduate":
        grades = _parse_alevels(d.get("alevels"))
        maths = (d.get("mathsGrade") or "").strip().upper() or None
        ib_total = _int_or_none(d.get("ibTotal"))
        curriculum = _curriculum(d.get("curriculum"), grades, ib_total)
        if curriculum is None:
            qualification = "a_level" if grades else ("ib" if ib_total is not None else None)
        elif curriculum in ("uk_alevel", "sg_alevel"):
            qualification = "a_level"
        elif curriculum == "ib":
            qualification = "ib"
        else:
            qualification = "other"
        undergrad = UndergradProfile(
            qualification_type=qualification,
            curriculum=curriculum,
            gaokao_score=_int_or_none(d.get("gaokaoScore")),
            gaokao_total=_int_or_none(d.get("gaokaoTotal")),
            gaokao_maths=_int_or_none(d.get("gaokaoMaths")),
            sat_total=_int_or_none(d.get("satTotal")),
            act_composite=_int_or_none(d.get("actComposite")),
            ap_grades=_parse_ap_grades(d.get("apGrades")),
            a_level_grades=grades or None,
            a_level_maths_grade=maths,
            ib_total=ib_total,
            ib_hl_maths_grade=_int_or_none(d.get("ibHlMaths")),
            ib_hl_total=_int_or_none(d.get("ibHlTotal")),
            gcse_english_grade=_grade_str(d.get("gcseEnglish")),
            gcse_maths_grade=_grade_str(d.get("gcseMaths")),
            residency=_residency(d.get("residency")),
            intake_year=intake_year,
            graduation_status=(str(d.get("graduationStatus")).strip()
                               if d.get("graduationStatus") else None),
            tara_taken=None)
    elif track == "taught_masters":
        degree = d.get("degree") or ""
        honours = True if re.search(r"honou?rs", degree.lower()) else None
        masters = MastersProfile(
            degree_field=_classify_degree(degree),
            honours=honours,
            degree_class=_degree_class(degree, d.get("degreeClass")),
            maths_alevel_grade=_grade_str(d.get("mastersMathsGrade")),
            it_experience_years=_num(d.get("itExperienceYears")),
            gre_total=_num(d.get("greTotal")),
            gre_analytical=_num(d.get("greAw")),
            gmat_total=_num(d.get("gmat")))

    return StudentProfile(application_track=track, undergrad_profile=undergrad,
                          masters_profile=masters, language=language, budget=budget,
                          target_intake=intake_year)


def _fmt_observed(r: RuleResult) -> str:
    obs = r.observed
    if obs is None:
        return "Not provided"
    if isinstance(obs, dict):
        if set(obs) <= {"listening", "reading", "writing", "speaking"}:
            labels = {"listening": "L", "reading": "R", "writing": "W", "speaking": "S"}
            return " / ".join(f"{labels[k]} {obs[k] if obs[k] is not None else '–'}"
                              for k in ("listening", "reading", "writing", "speaking"))
        return ", ".join(f"{k}: {v}" for k, v in obs.items())
    if isinstance(obs, list):
        return ", ".join(str(x) for x in obs)
    if isinstance(obs, float) and obs == int(obs):
        return str(int(obs))
    return str(obs)


def _reason_code(rule_id: str, status: str) -> str:
    if status == "UNKNOWN":
        return "MISSING_OR_UNVERIFIED"
    if rule_id.startswith("ucl-ielts") or rule_id.startswith("nus-language") \
            or rule_id in ("ucl-toefl", "nus-toefl"):
        return "SCORE_MEETS" if status == "MET" else "SCORE_BELOW"
    if rule_id in ("ucl-academic", "nus-academic", "ucl-gcse"):
        return "REQUIREMENT_MET" if status == "MET" else "REQUIREMENT_NOT_MET"
    if rule_id.endswith("-fee"):
        return "BUDGET_COVERS" if status == "MET" else "BUDGET_BELOW"
    if rule_id == "ucl-tara":
        return "TEST_REQUIRED"
    return "MET" if status == "MET" else "NOT_MET"


def _jsonable(value: Any) -> Any:
    """Recursively turn Decimals into plain JSON numbers.

    RuleResult.observed may hold a Decimal (fee rules); the frontend
    renders observed text from observedRaw, so it must be a plain
    number, not a string.
    """
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _derive_reason_key(rule_id: str, status: str, detail: str) -> str | None:
    """Machine-readable cause for an UNKNOWN rule, so the frontend can
    render the reason in the current locale instead of the English
    detail string. Derived from the engine's own detail strings in this
    one place; anything unrecognised falls back to 'missing-info'.
    MET / NOT_MET / NOT_APPLICABLE rules need no reason key (their
    observed + threshold values render the verdict)."""
    if status != "UNKNOWN":
        return None
    d = detail or ""
    # Generic expansion rules (round 6): same cause vocabulary as v2.
    if rule_id.startswith("exp-"):
        if "no valid test date" in d or "without a date" in d:
            return "missing-test-date"
        if "per credit" in d:
            return "missing-info"
        if "does not match" in d:
            return "budget-mismatch"
        if "not A-level" in d or "never converted" in d:
            return "no-equivalence"
        if "no IELTS/TOEFL score is stated" in d:
            return "no-threshold"
        if "No A-level threshold is stated" in d:
            return "no-threshold"
        return "missing-info"
    # Rule-specific causes first.
    if rule_id in ("ucl-tara", "imp-beng-tmua"):
        return "no-threshold"
    if rule_id == "ucl-msc-language":
        return "no-english-level"
    if rule_id in ("nus-bcomp-academic", "ntu-bcomp-academic"):
        return "igp-not-threshold"
    if rule_id in ("nus-gre-gmat", "ntu-msai-gre"):
        return "no-rejection-rule"
    # Cause phrases in the detail.
    if "Gaokao" in d:
        return "gaokao-no-equivalence"
    if "contextual" in d:
        return "contextual-offer"
    if "no valid test date" in d or "without a date" in d:
        return "missing-test-date"
    if "new 1-6 scale" in d:
        return "toefl-scale-unknown"
    if "Tuition-grant" in d or "tuition-grant status" in d or "fee band" in d:
        return "fee-residency-unknown"
    if "does not match" in d:
        return "budget-mismatch"
    if "no rejection rule" in d:
        return "no-rejection-rule"
    if "TOEFL supplied" in d and "IELTS" in d:
        return "toefl-instead"
    if "Indicative Grade Profile" in d:
        return "igp-not-threshold"
    if "AP/SAT/ACT" in d and "general minimum standard" in d:
        return "usa-ap-general-only"
    if "SAT/ACT/AP" in d:
        return "usa-no-equivalence"
    if "neither A level nor IB" in d:
        return "no-equivalence"
    if "Degree field not supplied" in d:
        return "missing-info"
    if "Degree field" in d or "not a listed route" in d:
        return "degree-unverified"
    return "missing-info"


def rule_to_frontend(r: RuleResult) -> dict:
    return {
        "ruleId": r.rule_id,
        "status": r.status,
        "observed": _fmt_observed(r),
        "expected": EXPECTED.get(r.rule_id, r.detail),
        # Manifest fact ids map to frontend source ids; expansion
        # requirement source ids (round 6) pass through unchanged —
        # the frontend resolves them against the programme's own
        # sources (mirrored from expansion.json). v2 fact ids that
        # are not mapped stay dropped, as before.
        "evidenceIds": [FACT_TO_SOURCE[f] for f in r.evidence_ids if f in FACT_TO_SOURCE]
                       + [f for f in r.evidence_ids
                          if f not in FACT_TO_SOURCE
                          and f in _EXPANSION_SOURCE_IDS],
        "reasonCode": _reason_code(r.rule_id, r.status),
        "unknownReason": r.detail if r.status == "UNKNOWN" else None,
        # Structured values for the frontend's localized renderer
        # (fix 2026-11-25): observedRaw/thresholdRaw carry the numbers
        # and dicts the English strings were formatted from, and
        # reasonKey names the UNKNOWN cause. The English `observed` /
        # `expected` / `unknownReason` strings stay as fallbacks.
        "observedRaw": _jsonable(r.observed),
        "thresholdRaw": _jsonable(r.threshold),
        "reasonKey": _derive_reason_key(r.rule_id, r.status, r.detail),
    }


def summary_for(overall: str) -> str:
    """Backend overall -> frontend eligibilitySummary."""
    return {"KNOWN_MINIMUMS_MET": "MET", "UNKNOWN": "PARTIAL_UNKNOWN",
            "NOT_MET": "NOT_MET"}.get(overall, overall)


def match_response(evaluation_id: str, results: list[dict]) -> dict:
    return {"evaluation_id": evaluation_id, "results": results,
            "rules_version": RULES_VERSION,
            "source_manifest_hash": source_manifest_hash(), "data_version": DATA_VERSION}
