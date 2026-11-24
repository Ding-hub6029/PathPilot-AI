"""Pydantic models for PathPilot AI Day 1 API. No network/model calls here."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Language(BaseModel):
    exam: str = "none"  # ielts | toefl | none
    overall: Optional[float] = None
    listening: Optional[float] = None
    reading: Optional[float] = None
    writing: Optional[float] = None
    speaking: Optional[float] = None


class Budget(BaseModel):
    amount: Optional[float] = None
    currency: Optional[str] = None  # GBP | SGD | USD
    period: Optional[str] = None  # per_year | total


class UndergradProfile(BaseModel):
    qualification_type: Optional[str] = None  # a_level | ib | other
    a_level_grades: Optional[list[str]] = None
    a_level_maths_grade: Optional[str] = None
    ib_total: Optional[int] = None
    ib_hl_maths_grade: Optional[int] = None
    tara_taken: Optional[bool] = None


class MastersProfile(BaseModel):
    degree_field: Optional[str] = None  # computing | related | business | other
    honours: Optional[bool] = None
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
    evaluation: Evaluation


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
