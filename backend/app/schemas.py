"""Pydantic models for PathPilot AI Day 2 API. No network/model calls here.

Day 2 changes (see DECISIONS.md #43-#48):
- Language gains test_date (ISO date string) and toefl_overall (a TOEFL
  score held separately from the IELTS overall, so a second exam is never
  silently dropped when IELTS is also present).
- UndergradProfile gains ib_hl_total, GCSE grades, residency, intake_year
  and graduation_status.
- StudentProfile gains target_intake.
- Budget.amount is Decimal (spec Ch11: money must use Decimal, never float).
  JSON output stays a plain number: FastAPI's encoder renders Decimal as a
  JSON number, and /profile/validate returns jsonable_encoder output.

Fix 2026-11-25 (DECISIONS #66-#68): UndergradProfile gains curriculum
(cn_gaokao | uk_alevel | ib | usa | sg_alevel | other) plus Gaokao,
SAT/ACT/AP fields, so the engine can evaluate against the applicant's
own branch instead of assuming A-level/IB/GCSE for everyone.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field


class Language(BaseModel):
    exam: str = "none"  # ielts | toefl | none
    overall: Optional[float] = None
    listening: Optional[float] = None
    reading: Optional[float] = None
    writing: Optional[float] = None
    speaking: Optional[float] = None
    # ISO date the test was taken, e.g. "2026-01-15". Needed for the UCL
    # TOEFL Jan 2026 scale split; without it TOEFL stays UNKNOWN.
    test_date: Optional[str] = None
    # TOEFL iBT score held separately from the IELTS overall, so that when
    # both exams are supplied the TOEFL result is evaluated as its own rule
    # (ucl-toefl / nus-toefl) instead of being dropped.
    toefl_overall: Optional[float] = None


class Budget(BaseModel):
    # Decimal, not float (spec Ch11). Accepts int/float/str input; pydantic
    # converts floats via their short string form, so 46699.99 stays exact.
    amount: Optional[Decimal] = None
    currency: Optional[str] = None  # GBP | SGD | USD
    period: Optional[str] = None  # per_year | total


class UndergradProfile(BaseModel):
    qualification_type: Optional[str] = None  # a_level | ib | other
    # Country / curriculum branch (fix 2026-11-25, DECISIONS #66):
    # cn_gaokao | uk_alevel | ib | usa | sg_alevel | other. When None the
    # engine infers it from qualification_type (a_level -> uk_alevel,
    # ib -> ib, other -> other) so pre-branch API clients keep working.
    curriculum: Optional[str] = None
    # Gaokao (China): score out of gaokao_total (usually 750).
    gaokao_score: Optional[int] = None
    gaokao_total: Optional[int] = None
    gaokao_maths: Optional[int] = None
    # USA: SAT total (400-1600), ACT composite (1-36), AP grades 1-5.
    sat_total: Optional[int] = None
    act_composite: Optional[int] = None
    ap_grades: Optional[list[int]] = None
    a_level_grades: Optional[list[str]] = None
    a_level_maths_grade: Optional[str] = None
    ib_total: Optional[int] = None
    ib_hl_maths_grade: Optional[int] = None
    tara_taken: Optional[bool] = None
    # Points in three Higher Level subjects (max 21). Required to call an IB
    # applicant MET: total 40 + HL Maths 7 with HL sum < 20 was wrongly MET
    # on Day 1 (DECISIONS #39).
    ib_hl_total: Optional[int] = None
    # GCSE English / Maths grades, e.g. "C" or "4". UCL requires C/4 in both.
    gcse_english_grade: Optional[str] = None
    gcse_maths_grade: Optional[str] = None
    # Fee residency: "uk" -> UK fee, "overseas" or missing -> overseas fee
    # (documented assumption; the wizard must say so).
    residency: Optional[str] = None  # uk | overseas | sg_citizen | sg_pr | sg_intl_asean | sg_intl_other | sg_intl_nogrant
    intake_year: Optional[int] = None
    graduation_status: Optional[str] = None  # e.g. current | predicted | final


class MastersProfile(BaseModel):
    degree_field: Optional[str] = None  # computing | related | business | other
    honours: Optional[bool] = None
    # Day 2 (v2 programmes): degree class is a stated threshold for
    # Imperial MSc (First-Class) and UCL MSc (upper second-class).
    degree_class: Optional[str] = None  # first | upper_second | lower_second | third | other
    # A-level Mathematics grade, for programmes that require maths to
    # A-level standard (UCL MSc) or at least A in Maths (Imperial MSc, non-STEM).
    maths_alevel_grade: Optional[str] = None
    it_experience_years: Optional[float] = None
    gre_total: Optional[int] = None
    gre_analytical: Optional[float] = None
    gmat_total: Optional[int] = None


class StudentProfile(BaseModel):
    application_track: str  # undergraduate | taught_masters
    undergrad_profile: Optional[UndergradProfile] = None
    masters_profile: Optional[MastersProfile] = None
    language: Optional[Language] = None
    budget: Optional[Budget] = None
    target_intake: Optional[int] = None


class RuleResult(BaseModel):
    rule_id: str
    status: str  # MET | NOT_MET | UNKNOWN | NOT_APPLICABLE
    detail: str = ""
    evidence_ids: list[str] = []
    observed: Any = None
    threshold: Optional[dict] = None


class Evaluation(BaseModel):
    program_id: str
    data_version: str = "v1"
    overall_status: str
    results: list[RuleResult] = []
    ai_status: str = "unavailable"
    explanation: Optional[str] = None


class MatchRequest(BaseModel):
    profile: StudentProfile
    program_id: str


class ExplainRequest(BaseModel):
    """Day 2 /explain request: the server recomputes from a profile.

    ``profile`` is a nested StudentProfile dict or a flat wizard profile;
    ``program_ids`` lists the programs to explain. ``locale`` is the
    explanation language (template explanations are English on Day 2).
    A client-supplied Evaluation is NEVER accepted here — see main.py.
    """
    profile: dict
    program_ids: list[str] = Field(default_factory=list)
    program_id: Optional[str] = None
    locale: Optional[str] = None


class SimulateRequest(BaseModel):
    profile: StudentProfile
    program_id: str
    patch: dict = Field(default_factory=dict)


class ErrorBody(BaseModel):
    code: str
    message: str
    field_errors: list[dict] = []
    retryable: bool = False


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str
