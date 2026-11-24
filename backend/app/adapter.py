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
from pathlib import Path
from typing import Any

from app.data import DATA_DIR, DATA_VERSION
from app.schemas import (Budget, Language, MastersProfile, RuleResult,
                         StudentProfile, UndergradProfile)

RULES_VERSION = "rules-v1-2026-11-24"

# Verified expected text per rule id (same facts as data/versions/v1).
EXPECTED: dict[str, str] = {
    "ucl-ielts-overall": "IELTS overall 6.5",
    "ucl-ielts-components": "IELTS minimum 6.0 in each component",
    "ucl-academic": "A*A*A with A* in Maths/Further Maths, or IB 40 with HL Maths grade 7",
    "ucl-tara": "TARA required for the 2026 cycle (no score threshold stated)",
    "ucl-fee": "GBP 46,700 per year (overseas, 2026/27)",
    "nus-language": "IELTS min 6.0 overall (no component minimum stated) or TOEFL iBT min 90",
    "nus-language-components": "No IELTS component minimum stated",
    "nus-academic": "Good honours degree in computing, or related/business degree + 2 years IT experience",
    "nus-gre-gmat": "GRE 320 + 3.5 analytical or GMAT 650+ (no rejection rule stated for a missing or low score)",
    "nus-fee": "SGD 69,215 total incl. 9% GST",
    "fixture-writing": "IELTS writing 6.0 (fixture, synthetic)",
}

# Manifest fact id -> frontend source id (frontend/src/lib/programs.ts).
FACT_TO_SOURCE: dict[str, str] = {
    "f-ucl-alevel": "ucl-cs-entry",
    "f-ucl-ib": "ucl-cs-entry",
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
}


def source_manifest_hash() -> str:
    path = Path(DATA_DIR) / "source-manifest.json"
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def flat_to_student(d: dict) -> StudentProfile:
    """Convert the frontend wizard's flat profile to a StudentProfile."""
    track = d.get("track") or ""
    ielts_fields = ("ieltsOverall", "ieltsListening", "ieltsReading", "ieltsWriting", "ieltsSpeaking")
    has_ielts = any(_num(d.get(k)) is not None for k in ielts_fields)
    has_toefl = _num(d.get("toefl")) is not None
    if has_ielts:
        language = Language(exam="ielts", overall=_num(d.get("ieltsOverall")),
                            listening=_num(d.get("ieltsListening")),
                            reading=_num(d.get("ieltsReading")),
                            writing=_num(d.get("ieltsWriting")),
                            speaking=_num(d.get("ieltsSpeaking")))
    elif has_toefl:
        language = Language(exam="toefl", overall=_num(d.get("toefl")))
    else:
        language = Language(exam="none")

    budget_amount = _num(d.get("budget"))
    budget = Budget(amount=budget_amount,
                    currency=d.get("budgetCurrency") or ("GBP" if track == "undergraduate" else "SGD"),
                    period="per_year" if track == "undergraduate" else "total")

    undergrad = None
    masters = None
    if track == "undergraduate":
        grades = _parse_alevels(d.get("alevels"))
        maths = (d.get("mathsGrade") or "").strip().upper() or None
        undergrad = UndergradProfile(
            qualification_type="a_level" if grades else None,
            a_level_grades=grades or None,
            a_level_maths_grade=maths,
            tara_taken=None)
    elif track == "taught_masters":
        degree = d.get("degree") or ""
        honours = True if re.search(r"honou?rs", degree.lower()) else None
        masters = MastersProfile(
            degree_field=_classify_degree(degree),
            honours=honours,
            it_experience_years=None,
            gre_total=_num(d.get("greTotal")),
            gre_analytical=_num(d.get("greAw")),
            gmat_total=_num(d.get("gmat")))

    return StudentProfile(application_track=track, undergrad_profile=undergrad,
                          masters_profile=masters, language=language, budget=budget)


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
    if rule_id.startswith("ucl-ielts") or rule_id.startswith("nus-language"):
        return "SCORE_MEETS" if status == "MET" else "SCORE_BELOW"
    if rule_id in ("ucl-academic", "nus-academic"):
        return "REQUIREMENT_MET" if status == "MET" else "REQUIREMENT_NOT_MET"
    if rule_id.endswith("-fee"):
        return "BUDGET_COVERS" if status == "MET" else "BUDGET_BELOW"
    if rule_id == "ucl-tara":
        return "TEST_REQUIRED"
    return "MET" if status == "MET" else "NOT_MET"


def rule_to_frontend(r: RuleResult) -> dict:
    return {
        "ruleId": r.rule_id,
        "status": r.status,
        "observed": _fmt_observed(r),
        "expected": EXPECTED.get(r.rule_id, r.detail),
        "evidenceIds": [FACT_TO_SOURCE[f] for f in r.evidence_ids if f in FACT_TO_SOURCE],
        "reasonCode": _reason_code(r.rule_id, r.status),
        "unknownReason": r.detail if r.status == "UNKNOWN" else None,
    }


def summary_for(overall: str) -> str:
    """Backend overall -> frontend eligibilitySummary."""
    return {"KNOWN_MINIMUMS_MET": "MET", "UNKNOWN": "PARTIAL_UNKNOWN",
            "NOT_MET": "NOT_MET"}.get(overall, overall)


def match_response(evaluation_id: str, results: list[dict]) -> dict:
    return {"evaluation_id": evaluation_id, "results": results,
            "rules_version": RULES_VERSION,
            "source_manifest_hash": source_manifest_hash(), "data_version": DATA_VERSION}
